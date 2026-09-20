import 'package:flutter/material.dart';

import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/animation_placeholder.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import 'capture_screen.dart';

class OnboardingScreen extends StatelessWidget {
  const OnboardingScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return PeelScaffold(
      content: const [
        Text('Peel', style: PeelText.brand),
        SizedBox(height: PeelSpace.x8),
        Text(
          'Check a pill against its bottle in three short steps.',
          style: PeelText.body,
        ),
        SizedBox(height: PeelSpace.x24),
        AnimationPlaceholder(
          description: 'Half cut orange with pill',
          tone: PlaceholderTone.mint,
          aspectRatio: 13 / 12,
        ),
      ],
      actions: [
        PeelButton(
          label: 'Get started',
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) => const CaptureScreen(step: ScanStep.bottle),
            ),
          ),
        ),
      ],
    );
  }
}
