import 'dart:async';

import 'package:flutter/foundation.dart';

import '../state/scan_session.dart';
import 'session.dart';
import 'signals.dart';

enum DevicePhase {
  connecting,
  connected,
  blanking,
  temperature,
  ready,
  dissolving,
  checking,
  complete,
}

/// Capture a water baseline, then fresh color sweeps after dissolution.
class DeviceRun extends ChangeNotifier {
  DeviceRun(this.session, this.scan, {this.runDuration = Duration.zero}) {
    _generation = scan.generation;
    _resetCount = session.resetCount;
    _blankCount = session.blankCount;
    scan.addListener(_scanChanged);
    session.addListener(_update);
    _update();
  }

  static const requiredSweeps = 5;
  final Duration runDuration;
  final Session session;
  final ScanSession scan;
  DevicePhase phase = DevicePhase.connecting;
  String? captureError;
  final _run = <Reading>[];
  final _blank = <Reading>[];
  final _sample = <Reading>[];
  Reading? _previous;
  late int _resetCount;
  late int _generation;
  late int _blankCount;
  bool _blankAcknowledged = false;
  bool _blanking = false;
  bool _measuring = false;
  bool _running = false;
  bool _durationElapsed = false;
  bool _stopRequested = false;
  Timer? _stopTimer;

  int get blankSweeps => _blank.length;
  int get sampleSweeps => _sample.length;
  bool get canStop => _sample.length >= requiredSweeps;
  double? get temperature {
    final value = session.latest?.tempC;
    return value == -127 || value == 85 ? null : value;
  }

  void _clearCapture() {
    _stopTimer?.cancel();
    _run.clear();
    _blank.clear();
    _sample.clear();
    _blanking = false;
    session.capturingBlank = false;
    _blankAcknowledged = false;
    _measuring = false;
    _running = false;
    _durationElapsed = false;
    _stopRequested = false;
  }

  void _scanChanged() {
    if (_generation == scan.generation) return;
    _generation = scan.generation;
    _clearCapture();
    captureError = null;
    _previous = session.latest;
    phase = session.connected ? DevicePhase.connected : DevicePhase.connecting;
    notifyListeners();
  }

  void _update() {
    if (!session.connected || session.resetCount != _resetCount) {
      _resetCount = session.resetCount;
      _clearCapture();
      _previous = null;
      phase = session.connected
          ? DevicePhase.connected
          : DevicePhase.connecting;
      notifyListeners();
      return;
    }
    final reading = session.latest;
    if (session.blankCount != _blankCount) {
      _blankCount = session.blankCount;
      if (_blanking) {
        _blank.clear();
        _blankAcknowledged = true;
      } else {
        _clearCapture();
        phase = DevicePhase.connected;
        captureError = 'Water baseline changed. Empty the cup and take a new water reading.';
      }
    }
    if (reading != null && !identical(reading, _previous)) {
      _previous = reading;
      if (reading.running) {
        _running = true;
        _blanking = false;
        session.capturingBlank = false;
        _run.add(reading);
        if (_measuring) {
          if (reading.isClassificationSweep) {
            _sample.add(reading);
            if (_sample.length > requiredSweeps) _sample.removeAt(0);
          }
          phase = DevicePhase.checking;
          _maybeStop();
        } else {
          // An external start cannot bypass explicit dissolution confirmation.
          phase = DevicePhase.dissolving;
        }
      } else if (_running) {
        _running = false;
        _stopTimer?.cancel();
        if (_blank.length == requiredSweeps && canStop && _measuring) {
          scan.finishRun(
            _run,
            session.log?.path,
            blank: _blank,
            sample: _sample,
          );
          phase = DevicePhase.complete;
        } else {
          _clearCapture();
          captureError =
              'Capture incomplete. Empty the cup and take a new water reading.';
          phase = DevicePhase.connected;
        }
      } else if (_blanking) {
        if (_blankAcknowledged && reading.isClassificationSweep) {
          _blank.add(reading);
        }
        if (_blank.length >= requiredSweeps) {
          _blanking = false;
          session.capturingBlank = false;
        }
        phase = _blanking ? DevicePhase.blanking : _readyPhase;
      } else if (phase != DevicePhase.complete) {
        phase = _blank.length == requiredSweeps
            ? _readyPhase
            : DevicePhase.connected;
      }
    }
    if (phase == DevicePhase.complete &&
        scan.runLogPath == null &&
        session.log != null) {
      scan.finishRun(_run, session.log!.path, blank: _blank, sample: _sample);
    }
    notifyListeners();
  }

  DevicePhase get _readyPhase {
    final temp = temperature;
    return temp != null && (temp < 35.5 || temp > 38.5)
        ? DevicePhase.temperature
        : DevicePhase.ready;
  }

  void _maybeStop() {
    if (_durationElapsed &&
        canStop &&
        !_stopRequested &&
        session.connected &&
        _running) {
      _stopRequested = true;
      unawaited(session.send('s'));
    }
  }

  Future<void> act() async {
    switch (phase) {
      case DevicePhase.connecting:
        await session.connectUsb();
      case DevicePhase.connected:
        _clearCapture();
        captureError = null;
        _previous = session.latest;
        _blanking = true;
        session.capturingBlank = true;
        _blankCount = session.blankCount;
        phase = DevicePhase.blanking;
        await session.send('b');
      case DevicePhase.temperature:
      case DevicePhase.ready:
        await session.send('z');
      case DevicePhase.dissolving:
        if (_blank.length != requiredSweeps) {
          captureError = 'No water reading. Stop, empty the cup, and take a new water reading.';
          await session.send('s');
          break;
        }
        _measuring = true;
        _sample.clear();
        phase = DevicePhase.checking;
        if (runDuration > Duration.zero) {
          _stopTimer = Timer(runDuration, () {
            _durationElapsed = true;
            _maybeStop();
          });
        }
      case DevicePhase.checking:
        if (canStop && !_stopRequested) {
          _stopRequested = true;
          await session.send('s');
        }
      case DevicePhase.blanking:
      case DevicePhase.complete:
        break;
    }
    notifyListeners();
  }

  @override
  void dispose() {
    session.capturingBlank = false;
    _stopTimer?.cancel();
    scan.removeListener(_scanChanged);
    session.removeListener(_update);
    super.dispose();
  }
}
