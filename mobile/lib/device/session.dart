import 'dart:async';
import 'dart:convert';

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
    Future<SessionLog> Function()? openLog,
  }) : _openLog = openLog ?? SessionLog.open;

  /// False in tests and on the desktop, where the USB plugin has no implementation.
  final bool watchUsb;

  /// False in tests that must not touch the filesystem.
  final bool logging;

  /// How a connection gets its log. Tests pass their own to decide when the file is ready.
  final Future<SessionLog> Function() _openLog;

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

  /// Unknown unless explicitly announced by the firmware.
  bool? autoZero;

  bool _initialDiagSent = false;
  bool _startPending = false;
  int resetCount = 0;
  int blankCount = 0;
  bool capturingBlank = false;
  bool supportsWorkflowDisplay = false;

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
        throw StateError(
          'No board found. Plug the XIAO into the phone with a USB-C cable '
          'that carries data, and allow the permission dialog.',
        );
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
    supportsWorkflowDisplay = false;
    autoZero = null;
    _initialDiagSent = false;
    _startPending = false;
    history.clear();
    history.connectedAt = DateTime.now();
    faults = const [];
    if (logging) {
      log = null;
      _openLog()
          .then((opened) {
            // The file opens in its own time, and the connection it was for may be gone by
            // then: hung up, or replaced by one with a log of its own on the way. Nothing
            // would ever close this one, so it is closed here instead of adopted.
            if (_disposed || !identical(_link, link)) {
              unawaited(opened.close());
              return;
            }
            log = opened;
            opened.event('connected', {'device': link.label}, DateTime.now());
            notifyListeners();
          })
          .catchError((Object e) {
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

  /// Hanging up on purpose. The fault engine stops with the connection: a board nobody
  /// asked to keep talking is not a stale stream.
  Future<void> disconnect() => _close(deliberate: true);

  Future<void> _close({required bool deliberate}) async {
    _stopDiag();
    // Detach ownership before awaiting I/O: an old unplug must never close a
    // newly attached link while its own cancellation is still finishing.
    final lines = _lineSub;
    final link = _link;
    final open = log;
    final lineCount = _lineCount;
    _lineSub = null;
    _link = null;
    state = LinkState.idle;
    supportsWorkflowDisplay = false;
    if (deliberate) {
      _clock?.cancel();
      _clock = null;
      faults = const [];
    }
    notifyListeners();
    await lines?.cancel();
    if (link != null) {
      try {
        await link.close();
      } catch (_) {}
    }
    if (open != null && !open.isClosed) {
      open.event('disconnected', {'lines': lineCount}, DateTime.now());
      unawaited(open.close());
    }
  }

  /// The connection going away on its own. The clock keeps running, so the board that
  /// stopped mid-run still raises STREAM_STALE.
  void _drop(String why) {
    if (!connected) return;
    error = why;
    unawaited(_close(deliberate: false));
  }

  /// b blank, z mark t=0, a toggle auto t=0, s stop, m stirrer, d diagnostics.
  Future<void> send(String command) async {
    // Automatic tablet detection is unreliable on the demo instrument.
    if (command.contains('a')) return;
    if (command.contains('d') &&
        (latest == null ||
            latest!.running ||
            _startPending ||
            capturingBlank)) {
      return;
    }
    final link = _link;
    if (link == null) return;
    if (command == 'z') _startPending = true;
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

    // Capability gating keeps display commands away from older instrument builds.
    if (raw.contains('"displayRelay"')) {
      try {
        final value = jsonDecode(raw);
        if (value is Map) supportsWorkflowDisplay = value['displayRelay'] == 2;
      } on FormatException {
        /* The regular parser handles malformed input. */
      }
    }
    final parsed = parseLine(raw);
    if (parsed == null) return;
    log?.line(parsed, at);
    history.addLine(parsed, at);

    switch (parsed) {
      case DataLine(:final reading):
        if (reading.running) _startPending = false;
        if (!_initialDiagSent && !reading.running) {
          _initialDiagSent = true;
          unawaited(send('d'));
        }
        if (!_readings.isClosed) _readings.add(reading);
      case NoteLine(:final text):
        if (text.startsWith('blank stored')) blankCount++;
        if (text.startsWith('auto t=0')) autoZero = text.endsWith('on');
        if (text.startsWith('17_stream ready')) {
          resetCount++;
          supportsWorkflowDisplay = false;
          history.samples.clear();
          history.diag = null;
          autoZero = null;
          _startPending = false;
        }
      case DiagLine():
      case UnknownLine():
        break;
    }
    _refresh(at);
  }

  /// Probe once after an idle data line confirms that it is safe. Only firmware
  /// that actually returns structured diagnostics is polled again, and only idle.
  void _startDiag() {
    _stopDiag();
    _diagClock = Timer.periodic(diagEvery, (_) {
      if (diag != null) unawaited(send('d'));
    });
  }

  void _stopDiag() {
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
    final changed =
        before.length != after.length ||
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
    if (_disposed) return;
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
