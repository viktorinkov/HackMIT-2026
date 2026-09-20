import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:rive/rive.dart' as rive;

import '../theme/peel_theme.dart';
import 'peel_rive_stage.dart';

/// Wraps the navigator and paints the one shared artboard over whichever
/// [PeelRiveSlot] is on screen. The artboard is never rebuilt on navigation,
/// so the animation runs straight through the flow.
class PeelRiveHost extends StatefulWidget {
  const PeelRiveHost({required this.child, this.enabled = true, super.key});

  final bool enabled;

  final Widget child;

  @override
  State<PeelRiveHost> createState() => _PeelRiveHostState();
}

class _PeelRiveHostState extends State<PeelRiveHost> {
  @override
  void initState() {
    super.initState();
    if (widget.enabled) peelRiveStage.load();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: peelRiveStage,
      builder: (context, _) {
        final controller = peelRiveStage.controller;
        final rect = peelRiveStage.rect;
        return Stack(
          key: peelRiveStage.hostKey,
          children: [
            widget.child,
            // Painted above the navigator into empty slots. Left visible during
            // bottom sheets so the artboard does not vanish; IgnorePointer lets
            // sheet taps pass through if the rect overlaps.
            if (controller != null && rect != null)
              Positioned(
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
///
/// Sizes to the artboard aspect ratio at full content width. In a fill
/// column leftover height sits below (via [Spacer]), not as letterboxing
/// around the artboard.
class PeelRiveSlot extends StatefulWidget {
  const PeelRiveSlot({
    required this.stage,
    this.fallback,
    this.active = true,
    super.key,
  });

  /// Width-based artboard size. Height always follows aspect ratio so the slot
  /// does not grow/shrink with leftover Column space.
  static Size sizeFor(BoxConstraints constraints, {double maxWidth = 0}) {
    final widthCap = maxWidth > 0
        ? maxWidth
        : (constraints.maxWidth.isFinite ? constraints.maxWidth : 0.0);
    if (widthCap <= 0) return Size.zero;
    return Size(widthCap, widthCap / PeelRiveStage.aspectRatio);
  }

  final PeelStage stage;

  /// When false (e.g. an offstage [PageView] page), this slot does not claim
  /// the shared artboard.
  final bool active;

  /// Shown instead of the artboard when the Rive file cannot be loaded.
  final Widget? fallback;

  @override
  State<PeelRiveSlot> createState() => _PeelRiveSlotState();
}

class _PeelRiveSlotState extends State<PeelRiveSlot> {
  final _key = GlobalKey();
  bool _measured = false;
  late final PeelRiveSlotHandle _handle = peelRiveStage.register();

  @override
  void initState() {
    super.initState();
    if (widget.active) peelRiveStage.show(widget.stage);
    _scheduleMeasure();
  }

  @override
  void didUpdateWidget(PeelRiveSlot oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active &&
        (oldWidget.stage != widget.stage || !oldWidget.active)) {
      peelRiveStage.show(widget.stage);
    }
    if (!widget.active && oldWidget.active) _handle.clear();
  }

  @override
  void dispose() {
    _handle.release();
    super.dispose();
  }

  /// Re-measured every frame: the slot moves with scrolling and route
  /// transitions without rebuilding, and [PeelRiveSlotHandle.moveTo] only
  /// notifies when the rect actually changes.
  void _scheduleMeasure() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _measure();
      // The first frame can lay the slot out at zero size; keep frames coming
      // until it has a real rect to report.
      if (!_measured) WidgetsBinding.instance.scheduleFrame();
      _scheduleMeasure();
    });
  }

  void _measure() {
    if (!widget.active) {
      _handle.clear();
      return;
    }
    final route = ModalRoute.of(context);
    if (route == null || !route.isActive) {
      _handle.clear();
      return;
    }
    // Another full page is on top — yield the artboard. A popup (bottom
    // sheet / dialog) also makes isCurrent false; keep the last rect so the
    // artboard stays visible under the dimmed barrier.
    if (!route.isCurrent) {
      if (!peelRiveStage.covered) _handle.clear();
      return;
    }
    final box = _key.currentContext?.findRenderObject();
    final host = peelRiveStage.hostKey.currentContext?.findRenderObject();
    if (box is! RenderBox || host is! RenderBox) return;
    if (!box.hasSize || box.size.isEmpty) return;
    _measured = true;
    // Also covers popping back to a screen whose slot never rebuilds.
    peelRiveStage.show(widget.stage);
    _handle.moveTo(box.localToGlobal(Offset.zero, ancestor: host) & box.size);
  }

  @override
  Widget build(BuildContext context) {
    final gutterWidth = math.max(
      MediaQuery.sizeOf(context).width - 2 * PeelSpace.x24,
      0.0,
    );
    return LayoutBuilder(
      builder: (context, constraints) {
        final size = PeelRiveSlot.sizeFor(
          constraints,
          maxWidth: gutterWidth,
        );
        // Top-aligned; width-sized so stage screens share one global rect.
        return Align(
          alignment: Alignment.topCenter,
          child: SizedBox(
            key: _key,
            width: size.width,
            height: size.height,
            child: peelRiveStage.failed
                ? (widget.fallback ??
                    const DecoratedBox(
                      decoration: BoxDecoration(
                        color: PeelColors.soft,
                        borderRadius: PeelRadii.r16,
                      ),
                    ))
                : const SizedBox.expand(),
          ),
        );
      },
    );
  }
}
