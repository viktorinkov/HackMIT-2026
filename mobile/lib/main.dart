import 'package:flutter/material.dart';

import 'device/session.dart';
import 'device/workflow_sync.dart';
import 'device/device_run.dart';
import 'state/scan_session.dart';

import 'rive/peel_rive_stage.dart';
import 'rive/peel_rive_widgets.dart';
import 'screens/onboarding_screen.dart';
import 'theme/peel_theme.dart';

final scanSession = ScanSession();
const deviceHost = String.fromEnvironment('PEEL_DEVICE_HOST');
final deviceSession = Session(watchUsb: deviceHost.isEmpty);
final deviceRun = DeviceRun(deviceSession, scanSession);
final hardwareSync = WorkflowSync(
  deviceRun.session,
  peelRiveStage.workflowStage,
);

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  // Collect runs from the first line, even while onboarding is on screen.
  hardwareSync.session.init();
  if (deviceHost.isNotEmpty) deviceSession.connectSim(deviceHost, 9001);
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
      home: const OnboardingScreen(),
      navigatorObservers: [PeelRiveNavigatorObserver()],
      builder: (context, child) =>
          PeelRiveHost(enabled: animations, child: child ?? const SizedBox()),
    );
  }
}
