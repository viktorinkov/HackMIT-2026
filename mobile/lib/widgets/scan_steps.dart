import 'package:flutter/material.dart';

import '../state/scan_session.dart';
import '../theme/peel_theme.dart';

/// Numbered steps 1 Bottle, 2 Imprint, 3 Pill. The current step uses semibold
/// text and a deep orange number, previous steps keep orange numbers and
/// upcoming steps use muted ink.
class ScanSteps extends StatelessWidget {
  const ScanSteps({super.key, required this.current});

  final ScanStep current;

  static const _labels = ['Bottle', 'Imprint', 'Pill'];

  @override
  Widget build(BuildContext context) {
    final currentIndex = ScanStep.values.indexOf(current);
    return Row(
      children: [
        for (var i = 0; i < _labels.length; i++) ...[
          if (i > 0) const SizedBox(width: PeelSpace.x16),
          _Step(
            index: i + 1,
            label: _labels[i],
            state: i == currentIndex
                ? _StepState.current
                : i < currentIndex
                    ? _StepState.done
                    : _StepState.upcoming,
          ),
        ],
      ],
    );
  }
}

enum _StepState { done, current, upcoming }

class _Step extends StatelessWidget {
  const _Step({required this.index, required this.label, required this.state});

  final int index;
  final String label;
  final _StepState state;

  @override
  Widget build(BuildContext context) {
    final numberColor = switch (state) {
      _StepState.current => PeelColors.deep,
      _StepState.done => PeelColors.orange,
      _StepState.upcoming => PeelColors.muted,
    };
    final labelStyle = state == _StepState.current
        ? PeelText.label
        : PeelText.body.copyWith(color: PeelColors.muted);

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text('$index',
            style: PeelText.label.copyWith(color: numberColor)),
        const SizedBox(width: PeelSpace.x4),
        Text(label, style: labelStyle),
      ],
    );
  }
}
