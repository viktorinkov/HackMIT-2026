import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:usb_serial/usb_serial.dart';

import 'link.dart';
import 'reading.dart';

enum LinkState { idle, connecting, live, demo }

/// Everything the dashboard shows: the connection, the latest reading, the current run's
/// curve, the board's messages, and a CSV of every line received.
class Session extends ChangeNotifier {
  Session({this.watchUsb = true});

  /// False in tests, where the USB plugin does not exist.
  final bool watchUsb;

  LinkState state = LinkState.idle;
  String? error;
  String? deviceLabel;

  Reading? latest;
  DateTime? lastLineAt;

  /// Readings since t = 0 of the current run. Kept after a stop so the last curve stays on
  /// screen, and cleared when the next run starts.
  final List<Reading> run = [];

  /// The last [recentWindow] readings regardless of run, for the pre-run live view.
  final List<Reading> recent = [];
  static const recentWindow = 90;

  /// The board's '#' messages, newest last.
  final List<String> notes = [];

  /// 17_stream boots with auto t=0 on; the board announces every change.
  bool autoZero = true;

  final List<String> _csv = [];
  static const csvHeader = 'wall,t_s,trans_mv,scat_mv,absT,absS,tC,stir_pct,'
      'sweep_red,sweep_yellow,sweep_green,sweep_blue,swept';

  Link? _link;
  bool _disposed = false;
  StreamSubscription<String>? _lineSub;
  StreamSubscription<UsbEvent>? _usbSub;
  Timer? _clock;

  bool get connected => state == LinkState.live || state == LinkState.demo;

  /// Connected, but nothing has arrived for a while: the board is probably not running
  /// 17_stream, or it browned out when the stirrer kicked in.
  bool get stale =>
      connected &&
      (lastLineAt == null || DateTime.now().difference(lastLineAt!) > const Duration(seconds: 3));

  int get rowCount => _csv.length;

  Future<void> init() async {
    if (!watchUsb) return;
    _usbSub = UsbSerial.usbEventStream?.listen((event) {
      if (event.event == UsbEvent.ACTION_USB_ATTACHED && state == LinkState.idle) {
        connectUsb();
      } else if (event.event == UsbEvent.ACTION_USB_DETACHED && state == LinkState.live) {
        _drop('Board unplugged.');
      }
    });
    // Launched by plugging the board in: connect straight away.
    try {
      if ((await UsbLink.devices()).isNotEmpty) await connectUsb();
    } catch (_) {/* no USB host on this device; the user can still pick demo */}
  }

  Future<void> connectUsb() async {
    if (state == LinkState.connecting) return;
    await disconnect();
    state = LinkState.connecting;
    error = null;
    notifyListeners();
    try {
      final devices = await UsbLink.devices();
      if (devices.isEmpty) {
        throw StateError('No board found. Plug the DevKitC\'s port marked USB into the phone '
            'through the OTG adapter.');
      }
      final link = await UsbLink.open(devices.first);
      _attach(link, LinkState.live);
    } catch (e) {
      state = LinkState.idle;
      error = e is StateError ? e.message : '$e';
      notifyListeners();
    }
  }

  Future<void> startDemo() async {
    await disconnect();
    error = null;
    _attach(DemoLink(), LinkState.demo);
  }

  void _attach(Link link, LinkState newState) {
    _link = link;
    deviceLabel = link.label;
    state = newState;
    lastLineAt = null;
    _lineSub = link.lines.listen(_onLine,
        onError: (Object e) => _drop('Connection error: $e'),
        onDone: () => _drop('Connection closed.'));
    // Tick once a second so the stale warning appears even when no lines arrive.
    _clock = Timer.periodic(const Duration(seconds: 1), (_) => notifyListeners());
    notifyListeners();
  }

  Future<void> disconnect() async {
    _clock?.cancel();
    await _lineSub?.cancel();
    _lineSub = null;
    final link = _link;
    _link = null;
    if (link != null) {
      try {
        await link.close();
      } catch (_) {}
    }
    if (state != LinkState.connecting) state = LinkState.idle;
    if (!_disposed) notifyListeners();
  }

  void _drop(String why) {
    if (!connected) return;
    error = why;
    disconnect();
  }

  Future<void> send(String command) async {
    final link = _link;
    if (link == null) return;
    try {
      await link.send(command);
    } catch (e) {
      _drop('Could not send "$command": $e');
    }
  }

  void _onLine(String raw) {
    final line = parseLine(raw);
    if (line == null) return;
    lastLineAt = DateTime.now();
    switch (line) {
      case NoteLine(:final text):
        notes.add(text);
        if (text.startsWith('auto t=0')) autoZero = text.endsWith('on');
        if (text.startsWith('17_stream ready')) autoZero = true;
        if (notes.length > 50) notes.removeAt(0);
      case DataLine(:final reading):
        _record(reading);
    }
    notifyListeners();
  }

  void _record(Reading r) {
    latest = r;
    recent.add(r);
    if (recent.length > recentWindow) recent.removeAt(0);

    final t = r.t;
    if (t != null) {
      // The clock went backwards: a new run started, so the old curve goes.
      if (run.isNotEmpty && t < run.last.t! - 0.5) run.clear();
      run.add(r);
    }

    String f(num? v) => v == null ? '' : '$v';
    _csv.add([
      DateTime.now().toIso8601String(),
      f(r.t), f(r.transMv), f(r.scatMv), f(r.absT), f(r.absS), f(r.tempC), r.stirPct,
      for (final c in Reading.colours) f(r.sweep[c]),
      r.swept,
    ].join(','));
  }

  /// Every reading this session, same columns as tools/peel_monitor.py writes.
  String csv() => ([csvHeader, ..._csv]).join('\n');

  @override
  void dispose() {
    _disposed = true;
    _usbSub?.cancel();
    disconnect();
    super.dispose();
  }
}
