import 'package:flutter/material.dart';
import 'package:rive/rive.dart' as rive;

import '../theme/peel_theme.dart';
import 'peel_rive_stage.dart';

/// Wraps the navigator and paints the one shared artboard over whichever
/// [PeelRiveSlot] is on screen. The artboard is never rebuilt on navigation,
/// so the animation runs straight through the flow.
class PeelRiveHost extends StatefulWidget {
  const PeelRiveHost({required this.child, super.key});

  final Widget child;

  @override
  State<PeelRiveHost> createState() => _PeelRiveHostState();
}

class _PeelRiveHostState extends State<PeelRiveHost> {
  @override
  void initState() {
    super.initState();
    peelRiveStage.load();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: peelRiveStage,
      builder: (context, _) {
        final controller = peelRiveStage.controller;
        final rect = peelRiveStage.rect;
        return Stack(
          children: [
            widget.child,
            if (controller != null && rect != null)
              AnimatedPositioned(
                duration: const Duration(milliseconds: 240),
                curve: Curves.easeOutCubic,
                left: rect.left,
                top: rect.top,
                width: rect.width,
                height: rect.height,
                child: IgnorePointer(
                  child: rive.RiveWidget(
                    controller: controller,
                    fit: rive.Fit.contain,
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}

/// A hole in a screen where the shared artboard is drawn. It reports its
/// position to [peelRiveStage] and sets the stage the screen wants to show.
class PeelRiveSlot extends StatefulWidget {
  const PeelRiveSlot({
    required this.stage,
    this.aspectRatio = PeelRiveStage.aspectRatio,
    this.fallback,
    super.key,
  });

  final PeelStage stage;
  final double aspectRatio;

  /// Shown instead of the artboard when the Rive file cannot be loaded.
  final Widget? fallback;

  @override
  State<PeelRiveSlot> createState() => _PeelRiveSlotState();
}

class _PeelRiveSlotState extends State<PeelRiveSlot> {
  final _key = GlobalKey();
  late final PeelRiveSlotHandle _handle = peelRiveStage.register();

  @override
  void initState() {
    super.initState();
    peelRiveStage.show(widget.stage);
    _scheduleMeasure();
  }

  @override
  void didUpdateWidget(PeelRiveSlot oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.stage != widget.stage) peelRiveStage.show(widget.stage);
    _scheduleMeasure();
  }

  @override
  void dispose() {
    _handle.release();
    super.dispose();
  }

  void _scheduleMeasure() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final box = _key.currentContext?.findRenderObject();
      if (box is! RenderBox || !box.hasSize) return;
      _handle.moveTo(box.localToGlobal(Offset.zero) & box.size);
    });
  }

  @override
  Widget build(BuildContext context) {
    _scheduleMeasure();
    return AspectRatio(
      key: _key,
      aspectRatio: widget.aspectRatio,
      child: peelRiveStage.failed
          ? (widget.fallback ??
              const DecoratedBox(
                decoration: BoxDecoration(
                  color: PeelColors.soft,
                  borderRadius: PeelRadii.r16,
                ),
              ))
          : const SizedBox.expand(),
    );
  }
}
