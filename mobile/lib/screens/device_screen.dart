import 'dart:async';

import 'package:flutter/material.dart';

import '../rive/peel_rive_stage.dart';
import '../rive/peel_rive_widgets.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import '../widgets/scan_steps.dart';
import 'results_screen.dart';

enum DevicePhase { connecting, connected, checking, complete }

/// Device connect + pill check. The device link and the readings are mocked.
class DeviceScreen extends StatefulWidget {
  const DeviceScreen({super.key});

  @override
  State<DeviceScreen> createState() => _DeviceScreenState();
}

class _DeviceScreenState extends State<DeviceScreen> {
  DevicePhase _phase = DevicePhase.connecting;
  Timer? _timer;

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
      if (next == DevicePhase.complete) {
        _timer = Timer(const Duration(milliseconds: 1600), () {
          if (!mounted) return;
          Navigator.of(context).pushReplacement(
            MaterialPageRoute<void>(
              builder: (_) => const ResultsScreen(),
              settings: const RouteSettings(name: 'results'),
            ),
          );
        });
      }
    });
  }

  void _startCheck() {
    setState(() => _phase = DevicePhase.checking);
    _schedule(const Duration(milliseconds: 2400), DevicePhase.complete);
  }

  PeelStage get _stage => switch (_phase) {
        DevicePhase.connecting => PeelStage.deviceConnect,
        DevicePhase.connected => PeelStage.pillSubmerged,
        DevicePhase.checking => PeelStage.checking,
        DevicePhase.complete => PeelStage.complete,
      };

  ({String title, String body, String placeholder}) get _copy =>
      switch (_phase) {
        DevicePhase.connecting => (
            title: 'Check pill',
            body: 'Looking for the Peel device nearby.',
            placeholder: 'Device blinks while the phone looks for it',
          ),
        DevicePhase.connected => (
            title: 'Check pill',
            body: 'Device connected. Put the pill in the tray and close it.',
            placeholder: 'Pill drops into the open device tray',
          ),
        DevicePhase.checking => (
            title: 'Checking pill',
            body: 'The device is reading the pill. This takes a few seconds.',
            placeholder: 'Light sweeps over the pill inside the device',
          ),
        DevicePhase.complete => (
            title: 'Scan complete',
            body: 'All three steps are done. Opening your results.',
            placeholder: 'Orange closes around the pill',
          ),
      };

  @override
  Widget build(BuildContext context) {
    final copy = _copy;
    final busy =
        _phase == DevicePhase.connecting || _phase == DevicePhase.checking;

    return PeelScaffold(
      content: [
        Text(copy.title, style: PeelText.brand),
        const SizedBox(height: PeelSpace.x8),
        Text(copy.body, style: PeelText.body),
        const SizedBox(height: PeelSpace.x24),
        PeelRiveSlot(stage: _stage),
        const SizedBox(height: PeelSpace.x16),
        const ScanSteps(current: ScanStep.pill),
      ],
      actions: [
        if (_phase != DevicePhase.complete)
          PeelButton(
            label: switch (_phase) {
              DevicePhase.connecting => 'Connecting…',
              DevicePhase.connected => 'Check pill',
              _ => 'Checking…',
            },
            onPressed: busy ? null : _startCheck,
          ),
        if (_phase != DevicePhase.complete)
          PeelButton(
            label: 'Back',
            variant: PeelButtonVariant.secondary,
            onPressed: () => Navigator.of(context).pop(),
          ),
      ],
    );
  }
}
