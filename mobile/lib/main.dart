import 'dart:io';

import 'package:flutter/material.dart';

import 'device/session.dart';
import 'device/debug_screen.dart';
import 'screens/device_screen.dart';
import 'device/device_run.dart';
import 'device/workflow_sync.dart';

import 'rive/peel_rive_stage.dart';
import 'rive/peel_rive_widgets.dart';
import 'screens/onboarding_screen.dart';
import 'screens/voice_screen.dart';
import 'services/peel_api.dart';
import 'state/scan_session.dart';
import 'theme/peel_theme.dart';
import 'widgets/peel_scaffold.dart';

const deviceHost = String.fromEnvironment('PEEL_DEVICE_HOST');
const peelRunSeconds = int.fromEnvironment(
  'PEEL_RUN_SECONDS',
  defaultValue: 60,
);
final deviceSession = Session(
  watchUsb: Platform.isAndroid && deviceHost.isEmpty,
);
final deviceRun = DeviceRun(
  deviceSession,
  scanSession,
  runDuration: Duration(seconds: peelRunSeconds),
);
final hardwareSync = WorkflowSync(deviceSession, peelRiveStage.workflowStage);

const _peelStart = String.fromEnvironment('PEEL_START');
const _voiceScanId = String.fromEnvironment(
  'PEEL_VOICE_SCAN_ID',
  defaultValue: 'scan-8a507aa7063c4fa5',
);

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await scanSession.loadDeviceId();
  hardwareSync.session.init();
  if (deviceHost.isNotEmpty) {
    deviceSession.connectTcp(deviceHost, 9001);
  }
  runApp(const PeelApp());
}

class PeelApp extends StatelessWidget {
  const PeelApp({super.key, this.animations = true});

  final bool animations;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Peel',
      debugShowCheckedModeBanner: false,
      theme: buildPeelTheme(),
      home: switch (_peelStart) {
        'voice' => const _VoiceTestHome(),
        'device' => const DeviceScreen(),
        'debug' => Theme(
          data: ThemeData(),
          child: DebugScreen(session: deviceSession),
        ),
        _ => const OnboardingScreen(),
      },
      navigatorObservers: [PeelRiveNavigatorObserver()],
      builder: (context, child) =>
          PeelRiveHost(enabled: animations, child: child ?? const SizedBox()),
    );
  }
}

/// Dev-only: `--dart-define=PEEL_START=voice` skips onboarding and opens Talk to Peel.
class _VoiceTestHome extends StatefulWidget {
  const _VoiceTestHome();

  @override
  State<_VoiceTestHome> createState() => _VoiceTestHomeState();
}

class _VoiceTestHomeState extends State<_VoiceTestHome> {
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final scan = await peelApi.getScan(_voiceScanId);
      scanSession.scanId = scan.scanId;
      scanSession.scan = scan;
      if (!mounted) return;
      setState(() => _error = null);
    } catch (caught) {
      if (!mounted) return;
      setState(() => _error = caught);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) {
      return PeelScaffold(
        topBar: const PeelTopBar(title: 'Peel'),
        content: [
          Text('Could not load $_voiceScanId.\n$_error', style: PeelText.body),
        ],
      );
    }
    if (scanSession.scanId == null) {
      return const Scaffold(
        backgroundColor: PeelColors.canvas,
        body: Center(child: CircularProgressIndicator()),
      );
    }
    return const VoiceScreen();
  }
}
