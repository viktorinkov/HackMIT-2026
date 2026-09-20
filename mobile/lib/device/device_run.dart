import 'dart:async';

import 'package:flutter/foundation.dart';

import '../state/scan_session.dart';
import 'session.dart';
import 'signals.dart';

enum DevicePhase {
  connecting,
  connected,
  temperature,
  ready,
  checking,
  complete,
}

/// Telemetry drives consumer state, including runs started by the BOX-3.
class DeviceRun extends ChangeNotifier {
  DeviceRun(this.session, this.scan, {this.runDuration = Duration.zero}) {
    _generation = scan.generation;
    scan.addListener(_scanChanged);
    _resetCount = session.resetCount;
    session.addListener(_update);
    _update();
  }
  final Duration runDuration;
  Timer? _stopTimer;
  final Session session;
  final ScanSession scan;
  DevicePhase phase = DevicePhase.connecting;
  final _run = <Reading>[];
  Reading? _previous;
  late int _resetCount;
  late int _generation;
  bool _resetWaiting = false;
  bool _running = false;

  double? get temperature {
    final value = session.latest?.tempC;
    return value == -127 || value == 85 ? null : value;
  }

  void _scanChanged() {
    if (_generation == scan.generation) return;
    _generation = scan.generation;
    _stopTimer?.cancel();
    _run.clear();
    _running = false;
    _previous = null;
    phase = DevicePhase.connecting;
    _update();
  }

  void _update() {
    if (!session.connected || session.resetCount != _resetCount) {
      _resetWaiting = session.connected;
      _resetCount = session.resetCount;
      _stopTimer?.cancel();
      _run.clear();
      _running = false;
      _previous = null;
      phase = _resetWaiting ? DevicePhase.connected : DevicePhase.connecting;
    }
    final reading = session.latest;
    if (session.connected &&
        reading != null &&
        !identical(reading, _previous)) {
      _resetWaiting = false;
      _previous = reading;
      if (reading.running) {
        if (!_running) {
          _run.clear();
          _stopTimer?.cancel();
          if (runDuration > Duration.zero) {
            _stopTimer = Timer(runDuration, () {
              if (_running && session.connected) unawaited(session.send('s'));
            });
          }
        }
        _running = true;
        _run.add(reading);
        phase = DevicePhase.checking;
      } else if (reading.absT == null) {
        _stopTimer?.cancel();
        _run.clear();
        _running = false;
        phase = DevicePhase.connected;
      } else if (_running) {
        _stopTimer?.cancel();
        _running = false;
        scan.finishRun(_run, session.log?.path);
        phase = DevicePhase.complete;
      } else if (phase != DevicePhase.complete) {
        final temp = temperature;
        phase = temp != null && (temp < 35.5 || temp > 38.5)
            ? DevicePhase.temperature
            : DevicePhase.ready;
      }
    } else if (session.connected && reading == null && !_resetWaiting) {
      phase = DevicePhase.connecting;
    }
    if (phase == DevicePhase.complete &&
        scan.runLogPath == null &&
        session.log != null) {
      scan.finishRun(_run, session.log!.path);
    }
    notifyListeners();
  }

  Future<void> act() => switch (phase) {
    DevicePhase.connecting => session.connectUsb(),
    DevicePhase.connected => session.send('b'),
    DevicePhase.temperature || DevicePhase.ready => session.send('z'),
    DevicePhase.checking => session.send('s'),
    DevicePhase.complete => Future<void>.value(),
  };
  @override
  void dispose() {
    _stopTimer?.cancel();
    session.removeListener(_update);
    scan.removeListener(_scanChanged);
    super.dispose();
  }
}
