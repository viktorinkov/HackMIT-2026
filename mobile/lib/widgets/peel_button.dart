import 'package:flutter/material.dart';

import '../theme/peel_theme.dart';

enum PeelButtonVariant { primary, secondary, text }

/// Peel action button: 56 dp primary/secondary, 48 dp text actions.
class PeelButton extends StatelessWidget {
  const PeelButton({
    super.key,
    required this.label,
    this.onPressed,
    this.variant = PeelButtonVariant.primary,
  });

  final String label;
  final VoidCallback? onPressed;
  final PeelButtonVariant variant;

  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null;
    final isText = variant == PeelButtonVariant.text;

    final background = switch (variant) {
      PeelButtonVariant.primary =>
        enabled ? PeelColors.orange : PeelColors.soft,
      PeelButtonVariant.secondary => PeelColors.surface,
      PeelButtonVariant.text => Colors.transparent,
    };
    final border = variant == PeelButtonVariant.secondary
        ? Border.all(color: PeelColors.line)
        : null;
    final foreground = enabled ? PeelColors.ink : PeelColors.muted;

    return Semantics(
      button: true,
      label: label,
      child: Material(
        color: background,
        borderRadius: PeelRadii.r12,
        child: InkWell(
          onTap: onPressed,
          borderRadius: PeelRadii.r12,
          child: Container(
            height: isText ? 48 : 56,
            decoration: BoxDecoration(borderRadius: PeelRadii.r12, border: border),
            padding: const EdgeInsets.symmetric(horizontal: PeelSpace.x16),
            alignment: Alignment.center,
            child: Text(
              label,
              textAlign: TextAlign.center,
              style: PeelText.label.copyWith(color: foreground),
            ),
          ),
        ),
      ),
    );
  }
}
