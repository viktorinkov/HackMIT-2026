import 'dart:async';

import 'package:flutter/material.dart';

import '../rive/peel_rive_stage.dart';
import '../rive/peel_rive_widgets.dart';
import '../main.dart' show deviceRun;
import '../device/device_run.dart';
import '../device/debug_screen.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import '../widgets/scan_steps.dart';
import '../state/scan_session.dart' show ScanStep;
import 'results_screen.dart';

/// Device connect + pill check, driven by the instrument.
class DeviceScreen extends StatefulWidget {
  const DeviceScreen({super.key});

  @override
  State<DeviceScreen> createState() => _DeviceScreenState();
}

class _DeviceScreenState extends State<DeviceScreen> {
  DevicePhase get _phase => deviceRun.phase;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    deviceRun.addListener(_changed);
    if (!deviceRun.session.connected) deviceRun.session.connectUsb();
    _changed();
  }

  void _changed() {
    if (!mounted) return;
    setState(() {});
    if (_phase != DevicePhase.complete) {
      _timer?.cancel();
      _timer = null;
    } else {
      _timer ??= Timer(const Duration(milliseconds: 1600), () {
        if (!mounted) return;
        Navigator.of(context).pushReplacement(
          MaterialPageRoute<void>(
            builder: (_) => const ResultsScreen(),
            settings: const RouteSettings(name: 'results'),
          ),
        );
      });
    }
  }

  @override
  void dispose() {
    deviceRun.removeListener(_changed);
    _timer?.cancel();
    super.dispose();
  }

  PeelStage get _stage => switch (_phase) {
    DevicePhase.connecting => PeelStage.deviceConnect,
    DevicePhase.connected ||
    DevicePhase.temperature ||
    DevicePhase.ready => PeelStage.pillSubmerged,
    DevicePhase.checking => PeelStage.checking,
    DevicePhase.complete => PeelStage.complete,
  };

  ({String title, String body, String placeholder})
  get _copy => switch (_phase) {
    DevicePhase.connecting => (
      title: 'Check pill',
      body:
          deviceRun.session.error ??
          'Connect Peel with a USB cable. Waiting for readings.',
      placeholder: 'Device blinks while the phone looks for it',
    ),
    DevicePhase.connected => (
      title: 'Check pill',
      body: 'Fill with clear water and close the lid.',
      placeholder: 'Pill drops into the open device tray',
    ),
    DevicePhase.temperature => (
      title: 'Water temperature',
      body:
          'Water is too ${deviceRun.temperature! < 35.5 ? 'cold' : 'hot'} (${deviceRun.temperature} °C). Aim for 37 °C.',
      placeholder: 'Water temperature',
    ),
    DevicePhase.ready => (
      title: 'Check pill',
      body: deviceRun.temperature == null
          ? 'Probe not connected. Drop the pill in; you can still run.'
          : 'Ready. Drop the pill in and close it.',
      placeholder: 'Pill drops into the open device tray',
    ),
    DevicePhase.checking => (
      title: 'Checking pill',
      body:
          'Reading the pill: ${deviceRun.session.latest?.t} s. Stirrer ${deviceRun.session.latest?.stirPct}%.',
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

    return PeelScaffold(
      fill: true,
      padding: const EdgeInsets.symmetric(horizontal: PeelSpace.x24),
      content: [
        GestureDetector(
          onLongPress: () => Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) => Theme(
                data: ThemeData(),
                child: DebugScreen(session: deviceRun.session),
              ),
            ),
          ),
          child: PeelStageHeader(title: copy.title),
        ),
        PeelRiveSlot(stage: _stage),
        const SizedBox(height: PeelSpace.x16),
        const ScanSteps(current: ScanStep.pill),
        const SizedBox(height: PeelSpace.x8),
        Flexible(
          child: Text(
            copy.body,
            style: PeelText.body,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
      actions: [
        if (_phase != DevicePhase.complete)
          PeelButton(
            label: switch (_phase) {
              DevicePhase.connecting => 'Retry connection',
              DevicePhase.connected => 'Water ready',
              DevicePhase.temperature => 'Start anyway',
              DevicePhase.ready => 'Check pill',
              _ => 'Stop',
            },
            onPressed: deviceRun.act,
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
