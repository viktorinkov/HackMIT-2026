import 'dart:async';

import 'package:flutter/material.dart';

import 'hardware/debug_screen.dart';
import 'rive/peel_rive_stage.dart';
import 'rive/peel_rive_widgets.dart';
import 'screens/device_screen.dart';
import 'screens/onboarding_screen.dart';
import 'screens/voice_screen.dart';
import 'services/peel_api.dart';
import 'state/instrument.dart';
import 'state/scan_session.dart';
import 'theme/peel_theme.dart';
import 'widgets/peel_scaffold.dart';

const _peelStart = String.fromEnvironment('PEEL_START');
const _voiceScanId = String.fromEnvironment(
  'PEEL_VOICE_SCAN_ID',
  defaultValue: 'scan-8a507aa7063c4fa5',
);

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await scanSession.loadDeviceId();
  unawaited(instrument.init());
  runApp(const PeelApp());
}

class PeelApp extends StatelessWidget {
  const PeelApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Peel',
      debugShowCheckedModeBanner: false,
      theme: buildPeelTheme(),
      home: switch (_peelStart) {
        'voice' => const _VoiceTestHome(),
        'debug' => DebugScreen(session: instrument),
        'device' => const DeviceScreen(),
        _ => const OnboardingScreen(),
      },
      navigatorObservers: [PeelRiveNavigatorObserver()],
      builder: (context, child) => PeelRiveHost(child: child ?? const SizedBox()),
    );
  }
}

/// Dev-only: `--dart-define=PEEL_START=voice` skips onboarding and opens Talk to Peel;
/// `PEEL_START=debug` opens the instrument's bench screen instead of the product;
/// `PEEL_START=device` opens the device step directly, for bench runs without the photo steps.
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
