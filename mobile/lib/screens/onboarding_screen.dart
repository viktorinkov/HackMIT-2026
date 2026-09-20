import 'package:flutter/material.dart';

import '../rive/peel_rive_stage.dart';
import '../rive/peel_rive_widgets.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import 'capture_screen.dart';

class OnboardingScreen extends StatelessWidget {
  const OnboardingScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return PeelScaffold(
      fill: true,
      padding: const EdgeInsets.symmetric(horizontal: PeelSpace.x24),
      content: const [
        PeelStageHeader(title: 'Peel'),
        PeelRiveSlot(stage: PeelStage.bottleScan),
        SizedBox(height: PeelSpace.x16),
        Flexible(
          child: Text(
            'Check a pill against its bottle in three short steps.',
            style: PeelText.body,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
          ),
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
