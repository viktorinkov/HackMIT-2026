import 'dart:async';

import 'package:flutter/material.dart';

import '../data/api_models.dart';
import '../hardware/debug_screen.dart';
import '../hardware/pill_run.dart';
import '../rive/peel_rive_stage.dart';
import '../services/peel_api.dart';
import '../state/instrument.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import '../widgets/scan_steps.dart';
import 'results_screen.dart';

enum DevicePhase { connecting, connected, checking, complete, research }

/// Device connect over USB (or the simulator), a pill run on the instrument, then wait
/// for the research result. "Continue without device" falls back to the backend's mock
/// `/pill` so the flow still runs with no board on the cable.
class DeviceScreen extends StatefulWidget {
  const DeviceScreen({super.key});

  @override
  State<DeviceScreen> createState() => _DeviceScreenState();
}

class _DeviceScreenState extends State<DeviceScreen> {
  DevicePhase _phase = DevicePhase.connecting;
  String? _error;
  bool _busy = false;

  /// Seconds into the run, for the caption while checking. Null when not on the board.
  int? _runSeconds;

  @override
  void initState() {
    super.initState();
    instrument.addListener(_onInstrument);
    if (instrument.connected) {
      _phase = DevicePhase.connected;
    } else if (peelSimulator.isNotEmpty) {
      unawaited(_connectSimulator());
    } else if (!instrument.connecting) {
      unawaited(instrument.connectUsb());
    }
  }

  @override
  void dispose() {
    instrument.removeListener(_onInstrument);
    super.dispose();
  }

  /// The connection is the instrument's to report; this screen only follows it while it
  /// is waiting for one. A drop mid-run is PillRun's to raise.
  void _onInstrument() {
    if (!mounted) return;
    if (_phase == DevicePhase.connecting && instrument.connected) {
      setState(() {
        _phase = DevicePhase.connected;
        _error = null;
      });
    } else if (_phase == DevicePhase.connected && !instrument.connected) {
      setState(() {
        _phase = DevicePhase.connecting;
        _error = instrument.error;
      });
    } else if (_phase == DevicePhase.connecting) {
      setState(() => _error = instrument.error);
    }
  }

  Future<void> _connectSimulator() async {
    final parts = peelSimulator.split(':');
    final port = parts.length > 1 ? int.tryParse(parts[1]) ?? 9000 : 9000;
    await instrument.connectSim(parts.first, port);
  }

  String? get _pillType =>
      scanSession.bottleResult?.genericName ?? scanSession.bottleResult?.brandName;

  /// The real thing: blank, t = 0, stream for [peelRunSeconds], stop.
  Future<void> _startCheck() => _check(() async {
        final run = await PillRun.measure(
          instrument,
          duration: Duration(seconds: peelRunSeconds),
          pillType: _pillType,
          onReading: (_, elapsed) {
            if (mounted) setState(() => _runSeconds = elapsed.inSeconds);
          },
        );
        if (run.severeFaults.isNotEmpty && mounted) {
          final ids = run.severeFaults.map((f) => f.id).join(', ');
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Instrument faults during the run: $ids')),
          );
        }
        return run.analysis;
      });

  /// No board: the backend's mock reading, as before the instrument existed.
  Future<void> _skipDevice() => _check(() => peelApi.analyzePill(pillType: _pillType));

  Future<void> _check(Future<PillHardwareAnalysis> Function() measure) async {
    setState(() {
      _phase = DevicePhase.checking;
      _error = null;
      _busy = true;
      _runSeconds = null;
    });
    final started = DateTime.now();
    try {
      scanSession.hardware = await measure();
      final elapsed = DateTime.now().difference(started);
      const floor = Duration(milliseconds: 2400);
      if (elapsed < floor) {
        await Future<void>.delayed(floor - elapsed);
      }
      if (!mounted) return;
      setState(() => _phase = DevicePhase.complete);
      await Future<void>.delayed(const Duration(milliseconds: 800));
      if (!mounted) return;
      await _startResearch();
    } on PeelApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = error.message;
      });
    } on StateError catch (error) {
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

  Future<void> _startResearch() async {
    setState(() {
      _phase = DevicePhase.research;
      _error = null;
      _busy = true;
    });
    try {
      final deviceId = scanSession.deviceId;
      if (deviceId == null || deviceId.isEmpty) {
        await scanSession.loadDeviceId();
      }
      final photos = <PhotoRef>[
        if (scanSession.bottleRef != null) scanSession.bottleRef!,
        if (scanSession.imprintRef != null) scanSession.imprintRef!,
      ];
      final created = await peelApi.createScan(
        deviceId: scanSession.deviceId!,
        bottle: scanSession.bottleResult,
        imprint: scanSession.imprintResult,
        hardware: scanSession.hardware?.result,
        hardwareModel: scanSession.hardware?.model,
        photos: photos,
      );
      scanSession.scanId = created.scanId;
      scanSession.scan = created;
      var scan = created;
      while (scan.status == 'pending' || scan.status == 'partial') {
        await Future<void>.delayed(const Duration(seconds: 1));
        if (!mounted) return;
        scan = await peelApi.getScan(created.scanId);
        scanSession.scan = scan;
      }
      if (scan.status == 'error') {
        setState(() {
          _busy = false;
          _error = 'Research did not finish. Retry to poll again.';
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
        DevicePhase.connected => PeelStage.pillSubmerged,
        DevicePhase.checking => PeelStage.checking,
        DevicePhase.complete => PeelStage.complete,
        DevicePhase.research => PeelStage.research,
      };

  String get _title => switch (_phase) {
        DevicePhase.connecting || DevicePhase.connected => 'Check pill',
        DevicePhase.checking => 'Checking pill',
        DevicePhase.complete => 'Scan complete',
        DevicePhase.research => 'Researching',
      };

  Widget get _primaryAction {
    if (_phase == DevicePhase.connecting) {
      return instrument.connecting
          ? const PeelButton(label: 'Connecting…')
          : PeelButton(
              label: 'Connect device',
              onPressed: peelSimulator.isNotEmpty
                  ? _connectSimulator
                  : instrument.connectUsb,
            );
    }
    if (_phase == DevicePhase.connected) {
      return PeelButton(label: 'Check pill', onPressed: _startCheck);
    }
    if (_phase == DevicePhase.checking && _error == null) {
      return PeelButton(
        label: _runSeconds == null
            ? 'Checking…'
            : 'Checking… ${_runSeconds}s / ${peelRunSeconds}s',
      );
    }
    if (_phase == DevicePhase.checking && _error != null) {
      return PeelButton(
        label: 'Retry',
        onPressed: instrument.connected ? _startCheck : _skipDevice,
      );
    }
    if (_phase == DevicePhase.research && _error == null) {
      return const PeelButton(label: 'Researching…');
    }
    if (_phase == DevicePhase.research && _error != null) {
      return PeelButton(label: 'Retry', onPressed: _startResearch);
    }
    // complete → brief handoff into research
    return const PeelButton(label: 'Checking…');
  }

  @override
  Widget build(BuildContext context) {
    final showBack = _phase == DevicePhase.connecting ||
        _phase == DevicePhase.connected ||
        (_phase == DevicePhase.checking && !_busy);

    return PeelStageScaffold(
      // Long-press the title for the instrument's bench screen: raw values, faults, log.
      header: GestureDetector(
        onLongPress: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => DebugScreen(session: instrument),
          ),
        ),
        child: PeelStageHeader(title: _title),
      ),
      stage: _stage,
      bottom: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_error != null) ...[
            Text(
              _error!,
              style: PeelText.body.copyWith(color: PeelColors.error),
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
            ),
            const SizedBox(height: PeelSpace.x16),
          ] else if (_phase == DevicePhase.connected) ...[
            Text(
              'Connected to ${instrument.deviceLabel ?? 'the instrument'}. '
              'Drop the pill in, then check.',
              style: PeelText.body.copyWith(color: PeelColors.muted),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
            const SizedBox(height: PeelSpace.x16),
          ],
          const ScanSteps(current: ScanStep.pill),
        ],
      ),
      primaryAction: _primaryAction,
      secondaryAction: _phase == DevicePhase.connecting
          ? PeelButton(
              label: 'Continue without device',
              variant: PeelButtonVariant.text,
              onPressed: _skipDevice,
            )
          : showBack
              ? PeelButton(
                  label: 'Back',
                  variant: PeelButtonVariant.secondary,
                  onPressed: () => Navigator.of(context).pop(),
                )
              : null,
    );
  }
}
