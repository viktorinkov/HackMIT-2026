import 'package:flutter/material.dart';

import '../theme/peel_theme.dart';

enum PlaceholderTone { warm, mint }

/// Text-only stand-in for the future Rive artboard. 13:16 aspect ratio,
/// fit contain, same dimensions across bottle, imprint, device check and
/// completion, exactly as the prototype describes.
class AnimationPlaceholder extends StatelessWidget {
  const AnimationPlaceholder({
    super.key,
    required this.description,
    this.tone = PlaceholderTone.warm,
    this.aspectRatio = 13 / 16,
    this.child,
  });

  final String description;
  final PlaceholderTone tone;
  final double aspectRatio;
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    final isMint = tone == PlaceholderTone.mint;
    return AspectRatio(
      aspectRatio: aspectRatio,
      child: Container(
        decoration: BoxDecoration(
          color: isMint ? PeelColors.tealSoft : PeelColors.soft,
          borderRadius: PeelRadii.r16,
          border: Border.all(color: PeelColors.line),
        ),
        padding: const EdgeInsets.all(PeelSpace.x24),
        alignment: Alignment.center,
        child: child ??
            Text(
              description,
              textAlign: TextAlign.center,
              style: PeelText.body.copyWith(
                color: isMint ? PeelColors.teal : PeelColors.muted,
              ),
            ),
      ),
    );
  }
}
