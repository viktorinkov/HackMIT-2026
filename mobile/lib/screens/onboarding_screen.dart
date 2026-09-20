import 'package:flutter/material.dart';

import '../rive/peel_rive_stage.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import 'capture_screen.dart';

class OnboardingScreen extends StatelessWidget {
  const OnboardingScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return PeelStageScaffold(
      header: const PeelStageHeader(title: 'Peel'),
      stage: PeelStage.bottleScan,
      primaryAction: PeelButton(
        label: 'Get started',
        onPressed: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => const CaptureScreen(),
          ),
        ),
      ),
    );
  }
}
