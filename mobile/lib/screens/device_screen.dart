import 'dart:async';

import 'package:flutter/material.dart';

import '../rive/peel_rive_stage.dart';
import '../data/api_models.dart';
import '../services/peel_api.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import '../widgets/scan_steps.dart';
import 'results_screen.dart';

enum DevicePhase { connecting, connected, checking, complete, research }

/// Device connect, mocked hardware, then wait for the research result.
class DeviceScreen extends StatefulWidget {
  const DeviceScreen({super.key});

  @override
  State<DeviceScreen> createState() => _DeviceScreenState();
}

class _DeviceScreenState extends State<DeviceScreen> {
  DevicePhase _phase = DevicePhase.connecting;
  Timer? _timer;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _schedule(const Duration(seconds: 2), DevicePhase.connected);
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _schedule(Duration delay, DevicePhase next) {
    _timer?.cancel();
    _timer = Timer(delay, () {
      if (!mounted) return;
      setState(() => _phase = next);
    });
  }

  Future<void> _startCheck() async {
    setState(() {
      _phase = DevicePhase.checking;
      _error = null;
      _busy = true;
    });
    final started = DateTime.now();
    try {
      final pillType = scanSession.bottleResult?.genericName ??
          scanSession.bottleResult?.brandName;
      final analysis = await peelApi.analyzePill(pillType: pillType);
      scanSession.hardware = analysis;
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
      return const PeelButton(label: 'Connecting…');
    }
    if (_phase == DevicePhase.connected) {
      return PeelButton(label: 'Check pill', onPressed: _startCheck);
    }
    if (_phase == DevicePhase.checking && _error == null) {
      return const PeelButton(label: 'Checking…');
    }
    if (_phase == DevicePhase.checking && _error != null) {
      return PeelButton(label: 'Retry', onPressed: _startCheck);
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
      header: PeelStageHeader(title: _title),
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
          ],
          const ScanSteps(current: ScanStep.pill),
        ],
      ),
      primaryAction: _primaryAction,
      secondaryAction: showBack
          ? PeelButton(
              label: 'Back',
              variant: PeelButtonVariant.secondary,
              onPressed: () => Navigator.of(context).pop(),
            )
          : null,
    );
  }
}
