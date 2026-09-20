import 'package:flutter/material.dart';

import '../theme/peel_theme.dart';

/// White field card: a small label over its value, as used by the Results and
/// Report screens.
class PeelFieldCard extends StatelessWidget {
  const PeelFieldCard({
    required this.label,
    this.value,
    this.detail,
    super.key,
  });

  final String label;
  final String? value;
  final String? detail;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(PeelSpace.x12),
      decoration: BoxDecoration(
        color: PeelColors.surface,
        borderRadius: PeelRadii.r12,
        border: Border.all(color: PeelColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: PeelText.caption.copyWith(color: PeelColors.muted),
          ),
          if (value != null && value!.isNotEmpty)
            Text(value!, style: PeelText.body),
          if (detail != null && detail!.isNotEmpty)
            Text(detail!, style: PeelText.body),
        ],
      ),
    );
  }
}
