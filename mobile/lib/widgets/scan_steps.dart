import 'package:flutter/material.dart';

import '../state/scan_session.dart';
import '../theme/peel_theme.dart';

/// Numbered steps: 1 Bottle, 2 Imprint, 3 Pill (device check).
///
/// Every chip is outlined. The tertiary outline + filled number circle slide
/// left → right onto the active chip when [current] changes.
class ScanSteps extends StatefulWidget {
  const ScanSteps({super.key, required this.current});

  final ScanStep current;

  static const extent = 32.0;
  static const circle = 28.0;
  static const _labels = ['Bottle', 'Imprint', 'Pill'];
  static const _slideDuration = Duration(milliseconds: 420);

  @override
  State<ScanSteps> createState() => _ScanStepsState();
}

class _ScanStepsState extends State<ScanSteps>
    with SingleTickerProviderStateMixin {
  final _stackKey = GlobalKey();
  final _stepKeys = List.generate(3, (_) => GlobalKey());

  late final AnimationController _slide;
  Animation<double> _t = const AlwaysStoppedAnimation(1);
  Rect? _start;
  Rect? _end;

  int get _currentIndex => ScanStep.values.indexOf(widget.current);

  Rect? get _pill {
    final a = _start;
    final b = _end;
    if (a == null && b == null) return null;
    if (a == null) return b;
    if (b == null) return a;
    return Rect.lerp(a, b, _t.value);
  }

  @override
  void initState() {
    super.initState();
    _slide = AnimationController(
      vsync: this,
      duration: ScanSteps._slideDuration,
    )..addListener(() => setState(() {}));
    WidgetsBinding.instance.addPostFrameCallback((_) => _jumpToCurrent());
  }

  @override
  void dispose() {
    _slide.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(ScanSteps oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.current != widget.current) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _animateBetween(
          ScanStep.values.indexOf(oldWidget.current),
          _currentIndex,
        );
      });
    }
  }

  Rect? _rectFor(int index) {
    final stackBox = _stackKey.currentContext?.findRenderObject();
    final stepBox = _stepKeys[index].currentContext?.findRenderObject();
    if (stackBox is! RenderBox || stepBox is! RenderBox) return null;
    if (!stackBox.hasSize || !stepBox.hasSize) return null;
    final offset = stepBox.localToGlobal(Offset.zero, ancestor: stackBox);
    return Rect.fromLTWH(
      offset.dx,
      0,
      stepBox.size.width,
      ScanSteps.circle,
    );
  }

  void _jumpToCurrent() {
    final rect = _rectFor(_currentIndex);
    if (rect == null || !mounted) return;
    setState(() {
      _start = rect;
      _end = rect;
      _t = const AlwaysStoppedAnimation(1);
    });
    _slide.value = 1;
  }

  void _animateBetween(int from, int to) {
    final start = _rectFor(from) ?? _pill;
    final end = _rectFor(to);
    if (start == null || end == null || !mounted) return;
    setState(() {
      _start = start;
      _end = end;
      _t = CurvedAnimation(parent: _slide, curve: Curves.easeInOutCubic);
    });
    _slide.forward(from: 0);
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final highlight = colors.tertiary;
    final pill = _pill;

    return SizedBox(
      height: ScanSteps.extent,
      child: Center(
        child: Stack(
          key: _stackKey,
          clipBehavior: Clip.none,
          children: [
            if (pill != null)
              Positioned(
                left: pill.left,
                top: pill.top,
                width: pill.width,
                height: pill.height,
                child: IgnorePointer(
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      borderRadius:
                          BorderRadius.circular(ScanSteps.circle / 2),
                      border: Border.all(color: highlight, width: 1.5),
                    ),
                    child: Align(
                      alignment: Alignment.centerLeft,
                      child: SizedBox(
                        width: ScanSteps.circle,
                        height: ScanSteps.circle,
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            color: highlight,
                            shape: BoxShape.circle,
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                for (var i = 0; i < ScanSteps._labels.length; i++) ...[
                  if (i > 0) const SizedBox(width: PeelSpace.x8),
                  _StepChip(
                    key: _stepKeys[i],
                    index: i + 1,
                    label: ScanSteps._labels[i],
                    selected: i == _currentIndex,
                  ),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _StepChip extends StatelessWidget {
  const _StepChip({
    super.key,
    required this.index,
    required this.label,
    required this.selected,
  });

  final int index;
  final String label;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final numberColor =
        selected ? colors.onTertiary : colors.onSurfaceVariant;
    final labelColor =
        selected ? colors.onTertiaryContainer : colors.onSurfaceVariant;

    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(ScanSteps.circle / 2),
        border: Border.all(
          color: selected ? Colors.transparent : colors.outline,
          width: 1.5,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(
            width: ScanSteps.circle,
            height: ScanSteps.circle,
            child: Center(
              child: Text(
                '$index',
                style: PeelText.label.copyWith(
                  color: numberColor,
                  fontSize: 12,
                  height: 1,
                ),
              ),
            ),
          ),
          const SizedBox(width: PeelSpace.x8),
          Padding(
            padding: const EdgeInsets.only(right: 10),
            child: Text(
              label,
              style: PeelText.caption.copyWith(
                color: labelColor,
                fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
