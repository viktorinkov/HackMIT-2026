import 'dart:async';

import 'package:flutter/material.dart';

import '../rive/peel_rive_stage.dart';
import '../data/api_models.dart';
import '../services/peel_api.dart';
import '../main.dart' show deviceRun, deviceHost;
import '../device/device_run.dart';
import '../device/signals.dart';
import '../device/debug_screen.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import '../widgets/scan_steps.dart';
import '../state/scan_session.dart' show ScanStep;
import 'results_screen.dart';

/// Device connect + pill check, driven by the instrument.
class DeviceScreen extends StatefulWidget {
  const DeviceScreen({super.key, this.controller, this.api});

  final DeviceRun? controller;
  final PeelApi? api;

  @override
  State<DeviceScreen> createState() => _DeviceScreenState();
}

class _DeviceScreenState extends State<DeviceScreen> {
  DeviceRun get run => widget.controller ?? deviceRun;
  DevicePhase get _phase => run.phase;
  Timer? _timer;
  bool _research = false;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    run.addListener(_changed);
    if (!run.session.connected && run.session.watchUsb) {
      run.session.connectUsb();
    }
    _changed();
  }

  void _changed() {
    if (!mounted) return;
    setState(() {});
    if (_research) return;
    if (_phase != DevicePhase.complete) {
      _timer?.cancel();
      _timer = null;
    } else {
      _timer ??= Timer(const Duration(milliseconds: 1600), () {
        if (!mounted) return;
        _startResearch();
      });
    }
  }

  @override
  void dispose() {
    run.removeListener(_changed);
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _startResearch() async {
    if (_busy) return;
    setState(() {
      _research = true;
      _error = null;
      _busy = true;
    });
    try {
      final deviceId = run.scan.deviceId;
      if (deviceId == null || deviceId.isEmpty) {
        await run.scan.loadDeviceId();
      }
      if (!run.scan.hardwareSkipped) {
        final analysis = await (widget.api ?? peelApi).analyzePill(
          blank: run.scan.blankReadings,
          sample: run.scan.sampleReadings,
          pillType:
              run.scan.bottleResult?.genericName ??
              run.scan.bottleResult?.brandName,
        );
        final result = analysis.result;
        run.scan.hardware = PillHardwareAnalysis(
          model: analysis.model,
          result: PillHardwareResult(
            status: result.status,
            spectrum: result.spectrum,
            pillType: result.pillType,
            degraded: result.degraded,
            confidence: result.confidence,
            sensorReadings: sensorPayload(run.scan.runReadings),
            sensorSampleCount: run.scan.runReadings.length,
          ),
        );
      }
      final photos = <PhotoRef>[
        if (run.scan.bottleRef != null) run.scan.bottleRef!,
        if (run.scan.imprintRef != null) run.scan.imprintRef!,
      ];
      final created = await (widget.api ?? peelApi).createScan(
        deviceId: run.scan.deviceId!,
        bottle: run.scan.bottleResult,
        imprint: run.scan.imprintResult,
        hardware: run.scan.hardware?.result,
        hardwareModel: run.scan.hardware?.model,
        photos: photos,
      );
      run.scan.scanId = created.scanId;
      run.scan.scan = created;
      var scan = created;
      while (scan.status == 'pending' || scan.status == 'partial') {
        await Future<void>.delayed(const Duration(seconds: 1));
        if (!mounted) return;
        scan = await (widget.api ?? peelApi).getScan(created.scanId);
        run.scan.scan = scan;
      }
      if (!mounted) return;
      if (scan.status == 'error') {
        setState(() {
          _busy = false;
          _error = 'Research did not finish. Retry to start research again.';
        });
        return;
      }
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute<void>(
          builder: (_) => const ResultsScreen(),
          settings: const RouteSettings(name: 'results'),
        ),
      );
    } on PeelApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = error.message;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = error.toString();
      });
    }
  }

  PeelStage get _stage => switch (_phase) {
    DevicePhase.connecting => PeelStage.deviceConnect,
    DevicePhase.connected ||
    DevicePhase.blanking ||
    DevicePhase.temperature ||
    DevicePhase.ready ||
    DevicePhase.dissolving => PeelStage.pillSubmerged,
    DevicePhase.checking => PeelStage.checking,
    DevicePhase.complete => PeelStage.complete,
  };

  ({String title, String body, String placeholder})
  get _copy => switch (_phase) {
    DevicePhase.connecting => (
      title: 'Check pill',
      body:
          run.session.error ??
          'Connect Peel with a USB cable. Waiting for readings.',
      placeholder: 'Device blinks while the phone looks for it',
    ),
    DevicePhase.connected => (
      title: 'Check pill',
      body: run.captureError ?? 'Fill with clear water and close the lid.',
      placeholder: 'Pill drops into the open device tray',
    ),
    DevicePhase.temperature => (
      title: 'Water temperature',
      body:
          'Water is too ${run.temperature! < 35.5 ? 'cold' : 'hot'} (${run.temperature} °C). Aim for 37 °C.',
      placeholder: 'Water temperature',
    ),
    DevicePhase.ready => (
      title: 'Check pill',
      body: 'Water reading complete. Add the pill and start the stirrer.',
      placeholder: 'Pill drops into the open device tray',
    ),
    DevicePhase.blanking => (
      title: 'Reading clear water',
      body:
          'Keep only water in the cup. Readings: ${run.blankSweeps}/5. Allow about 50 seconds.',
      placeholder: 'Reading the water baseline',
    ),
    DevicePhase.dissolving => (
      title: 'Dissolving pill',
      body:
          run.captureError ??
          'Wait until the pill dissolves, then tap Pill dissolved.',
      placeholder: 'Pill dissolves in the water',
    ),
    DevicePhase.checking => (
      title: 'Checking pill',
      body:
          'Fresh color readings: ${run.sampleSweeps}/5. Keep the lid closed. Allow about 60 seconds.',
      placeholder: 'Light sweeps over the pill inside the device',
    ),
    DevicePhase.complete => (
      title: 'Scan complete',
      body: 'All three steps done. Opening results.',
      placeholder: 'Orange closes around the pill',
    ),
  };

  @override
  Widget build(BuildContext context) {
    final copy = _copy;
    final canLeave =
        !_research &&
        _phase != DevicePhase.blanking &&
        _phase != DevicePhase.dissolving &&
        _phase != DevicePhase.checking &&
        _phase != DevicePhase.complete;
    return PeelStageScaffold(
      header: GestureDetector(
        onLongPress: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => Theme(
              data: ThemeData(),
              child: DebugScreen(session: run.session),
            ),
          ),
        ),
        child: PeelStageHeader(title: _research ? 'Researching' : copy.title),
      ),
      stage: _research ? PeelStage.research : _stage,
      bottom: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            _error ?? (_research ? 'Preparing your results.' : copy.body),
            style: PeelText.body,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
          ),
          const SizedBox(height: PeelSpace.x8),
          const ScanSteps(current: ScanStep.pill),
          if (canLeave)
            PeelButton(
              label: 'Skip hardware',
              variant: PeelButtonVariant.text,
              onPressed: () {
                run.scan.skipHardware();
                _startResearch();
              },
            ),
        ],
      ),
      primaryAction: _research
          ? PeelButton(
              label: _error == null ? 'Researching…' : 'Retry',
              onPressed: _busy ? null : _startResearch,
            )
          : PeelButton(
              label: switch (_phase) {
                DevicePhase.connecting => 'Retry connection',
                DevicePhase.connected => 'Water ready',
                DevicePhase.blanking => 'Reading water…',
                DevicePhase.temperature => 'Start anyway',
                DevicePhase.ready => 'Start stirrer',
                DevicePhase.dissolving =>
                  run.blankSweeps < 5 ? 'Stop and refill' : 'Pill dissolved',
                DevicePhase.complete => 'Opening results…',
                _ => 'Stop',
              },
              onPressed:
                  _phase == DevicePhase.complete ||
                      _phase == DevicePhase.blanking ||
                      (_phase == DevicePhase.checking && !run.canStop)
                  ? null
                  : () {
                      if (_phase == DevicePhase.connecting &&
                          !run.session.watchUsb &&
                          deviceHost.isNotEmpty) {
                        run.session.connectTcp(deviceHost, 9001);
                      } else {
                        run.act();
                      }
                    },
            ),
      secondaryAction: canLeave
          ? PeelButton(
              label: 'Back',
              variant: PeelButtonVariant.secondary,
              onPressed: () => Navigator.of(context).pop(),
            )
          : null,
    );
  }
}

/// Keep timestamps and all channels aligned; long runs retain their full span.
List<Map<String, dynamic>> sensorPayload(List<Reading> readings) {
  final count = readings.length > 256 ? 256 : readings.length;
  double? finite(double? value) =>
      value != null && value.isFinite ? value : null;
  return [
    for (var i = 0; i < count; i++)
      (() {
        final r =
            readings[count == readings.length
                ? i
                : (i * (readings.length - 1) / (count - 1)).round()];
        return <String, dynamic>{
          't': finite(r.t),
          'trans': finite(r.transMv),
          'scat': finite(r.scatMv),
          'absT': finite(r.absT),
          'absS': finite(r.absS),
          'tC': finite(r.tempC),
          'darkTrans': finite(r.darkTransMv),
          'darkScat': finite(r.darkScatMv),
          'stir': r.stirPct,
          'swept': r.swept,
          'sweep': {for (final e in r.sweep.entries) e.key: finite(e.value)},
          'sweepS': {
            for (final e in r.sweepScatter.entries) e.key: finite(e.value),
          },
        };
      })(),
  ];
}
