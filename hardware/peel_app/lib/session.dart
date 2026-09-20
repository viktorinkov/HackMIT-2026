import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:usb_serial/usb_serial.dart';

import 'faults.dart';
import 'link.dart';
import 'session_log.dart';
import 'signals.dart';

enum LinkState { idle, connecting, connected }

/// Everything above the cable. The UI asks this object for values, faults and the
/// connection, and never learns whether the bytes came from USB, from TCP or from a file.
///
/// It owns: the link, the parse, the history the fault engine reads, the session log, and
/// the clock that lets time-based faults fire when nothing is arriving.
class Session extends ChangeNotifier {
  Session({
    this.watchUsb = true,
    this.logging = true,
    this.tick = const Duration(milliseconds: 500),
  });

  /// False in tests and on the desktop, where the USB plugin has no implementation.
  final bool watchUsb;

  /// False in tests that must not touch the filesystem.
  final bool logging;

  final Duration tick;

  /// How often to ask the board for a diagnostics line.
  static const diagEvery = Duration(seconds: 30);

  // ------------------------------------------------------------------ what the UI reads
  LinkState state = LinkState.idle;

  /// The last thing that went wrong, kept until the next successful connect. A denied
  /// permission dialog lands here.
  String? error;
  String? deviceLabel;

  final History history = History();
  List<Fault> faults = const [];
  SessionLog? log;

  Reading? get latest => history.latest;
  Diag? get diag => history.diag;
  bool get connected => state == LinkState.connected;
  int get lineCount => _lineCount;

  /// 17_stream boots with auto t=0 on and announces every change.
  bool autoZero = true;

  // ------------------------------------------------------------------ streams
  final _readings = StreamController<Reading>.broadcast();
  final _faultChanges = StreamController<List<Fault>>.broadcast();
  final _rawLines = StreamController<String>.broadcast();

  /// Every data line, parsed. For anything that wants the values without the widget tree.
  Stream<Reading> get readings => _readings.stream;

  /// The active fault list, each time it changes.
  Stream<List<Fault>> get faultChanges => _faultChanges.stream;

  /// Every line exactly as the board sent it.
  Stream<String> get rawLines => _rawLines.stream;

  // ------------------------------------------------------------------ internals
  Link? _link;
  StreamSubscription<String>? _lineSub;
  StreamSubscription<UsbEvent>? _usbSub;
  Timer? _clock;
  Timer? _diagClock;
  Timer? _firstDiag;
  bool _disposed = false;
  int _lineCount = 0;

  Future<void> init() async {
    _startClock();
    if (!watchUsb) return;
    _usbSub = UsbSerial.usbEventStream?.listen((event) {
      if (event.event == UsbEvent.ACTION_USB_ATTACHED) {
        // Plugged in, or replugged after a detach: connect without the user tapping.
        if (state == LinkState.idle) connectUsb();
      } else if (event.event == UsbEvent.ACTION_USB_DETACHED) {
        _drop('Board unplugged. It will reconnect when you plug it back in.');
      }
    });
    // Launched by plugging the board in.
    try {
      if ((await UsbLink.devices()).isNotEmpty) await connectUsb();
    } catch (_) {
      // No USB host on this device; the simulator is still available.
    }
  }

  Future<void> connectUsb() async {
    if (state == LinkState.connecting) return;
    await disconnect();
    state = LinkState.connecting;
    error = null;
    notifyListeners();
    try {
      final device = UsbLink.pick(await UsbLink.devices());
      if (device == null) {
        throw StateError('No board found. Plug the XIAO into the phone with a USB-C cable '
            'that carries data, and allow the permission dialog.');
      }
      // Opening the port is what triggers Android's permission dialog; if the user says no,
      // open() returns false and UsbLink throws with that explanation.
      _attach(await UsbLink.open(device));
    } catch (e) {
      state = LinkState.idle;
      error = e is StateError ? e.message : '$e';
      notifyListeners();
    }
  }

  /// Developer-only: the simulator, `python3 hardware/sim/fake_board.py --tcp 9000`.
  Future<void> connectSim(String host, int port) async {
    await disconnect();
    state = LinkState.connecting;
    error = null;
    notifyListeners();
    try {
      _attach(await TcpLink.connect(host, port));
    } catch (e) {
      state = LinkState.idle;
      error = 'No simulator at $host:$port ($e).';
      notifyListeners();
    }
  }

  /// For tests and for any other source of lines.
  Future<void> connectTo(Link link) async {
    await disconnect();
    _attach(link);
  }

  void _attach(Link link) {
    _link = link;
    deviceLabel = link.label;
    state = LinkState.connected;
    _lineCount = 0;
    autoZero = true;
    history.clear();
    history.connectedAt = DateTime.now();
    faults = const [];
    if (logging) {
      log = null;
      SessionLog.open().then((opened) {
        log = opened;
        opened.event('connected', {'device': link.label}, DateTime.now());
        if (!_disposed) notifyListeners();
      }).catchError((Object e) {
        // A log we cannot write is not a reason to lose the run.
        error = 'Session log unavailable: $e';
        return null;
      });
    }
    _lineSub = link.lines.listen(
      _onLine,
      onError: (Object e) => _drop('Connection error: $e'),
      onDone: () => _drop('Connection closed.'),
    );
    _startClock();
    _startDiag();
    notifyListeners();
  }

  Future<void> disconnect() async {
    _stopDiag();
    await _lineSub?.cancel();
    _lineSub = null;
    final link = _link;
    _link = null;
    if (link != null) {
      try {
        await link.close();
      } catch (_) {}
    }
    // The log outlives the connection: closed, but still readable, so the run can be
    // exported after the board has gone away. _attach replaces it on the next connect.
    final open = log;
    if (open != null && !open.isClosed) {
      open.event('disconnected', {'lines': _lineCount}, DateTime.now());
      unawaited(open.close());
    }
    if (state != LinkState.connecting) state = LinkState.idle;
    if (!_disposed) notifyListeners();
  }

  void _drop(String why) {
    if (!connected) return;
    error = why;
    unawaited(disconnect());
  }

  /// b blank, z mark t=0, a toggle auto t=0, s stop, m stirrer, d diagnostics.
  Future<void> send(String command) async {
    final link = _link;
    if (link == null) return;
    log?.event('command', {'command': command}, DateTime.now());
    try {
      await link.send(command);
    } catch (e) {
      _drop('Could not send "$command": $e');
    }
  }

  void _onLine(String raw) {
    final at = DateTime.now();
    _lineCount++;
    if (!_rawLines.isClosed) _rawLines.add(raw);
    log?.raw(raw, at);

    final parsed = parseLine(raw);
    if (parsed == null) return;
    log?.line(parsed, at);
    history.addLine(parsed, at);

    switch (parsed) {
      case DataLine(:final reading):
        if (!_readings.isClosed) _readings.add(reading);
      case NoteLine(:final text):
        if (text.startsWith('auto t=0')) autoZero = text.endsWith('on');
        if (text.startsWith('17_stream ready')) autoZero = true;
      case DiagLine():
      case UnknownLine():
        break;
    }
    _refresh(at);
  }

  /// The board streams into the void whether anyone is listening or not, so the phone
  /// almost always misses the boot diagnostics. Ask for a fresh set on connect, and again
  /// every [diagEvery]: that is what keeps the LED, probe and radio faults current.
  void _startDiag() {
    _stopDiag();
    _firstDiag = Timer(const Duration(milliseconds: 300), () => send('d'));
    _diagClock = Timer.periodic(diagEvery, (_) => send('d'));
  }

  void _stopDiag() {
    _firstDiag?.cancel();
    _firstDiag = null;
    _diagClock?.cancel();
    _diagClock = null;
  }

  void _startClock() {
    _clock?.cancel();
    _clock = Timer.periodic(tick, (_) => _refresh(DateTime.now()));
  }

  /// Re-runs the fault engine. Called on every line and on the clock, because
  /// STREAM_STALE is about lines that did not arrive.
  void _refresh(DateTime now) {
    if (_disposed) return;
    final next = evaluate(history, now);
    final before = {for (final f in faults) f.id: f};
    final after = {for (final f in next) f.id: f};
    final changed = before.length != after.length ||
        !before.keys.every(after.containsKey) ||
        !next.every((f) => before[f.id]?.message == f.message);
    faults = next;
    if (changed) {
      for (final f in next.where((f) => !before.containsKey(f.id))) {
        log?.fault(f, raised: true, at: now);
      }
      for (final f in before.values.where((f) => !after.containsKey(f.id))) {
        log?.fault(f, raised: false, at: now);
      }
      if (!_faultChanges.isClosed) _faultChanges.add(next);
    }
    notifyListeners();
  }

  @override
  void notifyListeners() {
    if (!_disposed) super.notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _clock?.cancel();
    _stopDiag();
    _usbSub?.cancel();
    unawaited(disconnect());
    _readings.close();
    _faultChanges.close();
    _rawLines.close();
    super.dispose();
  }
}
