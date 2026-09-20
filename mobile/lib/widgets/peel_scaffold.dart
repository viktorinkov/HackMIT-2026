import 'package:flutter/material.dart';

import '../rive/peel_rive_stage.dart';
import '../rive/peel_rive_widgets.dart';
import '../theme/peel_theme.dart';
import 'scan_steps.dart';

/// Screen shell from Figma: scroll area with 24 dp gutters plus a pinned
/// bottom action stack.
class PeelScaffold extends StatelessWidget {
  const PeelScaffold({
    super.key,
    required this.content,
    this.actions = const [],
    this.topBar,
    this.fill = false,
    this.padding,
  });

  final List<Widget> content;
  final List<Widget> actions;
  final Widget? topBar;

  /// Lays the content out inside the viewport instead of scrolling it, so the
  /// shared Rive slot keeps its size instead of scrolling out of view.
  final bool fill;

  final EdgeInsets? padding;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: PeelColors.canvas,
      body: SafeArea(
        child: Column(
          children: [
            if (topBar != null) topBar!,
            Expanded(
              child: Padding(
                padding:
                    padding ??
                    const EdgeInsets.fromLTRB(
                      PeelSpace.x24,
                      PeelSpace.x16,
                      PeelSpace.x24,
                      PeelSpace.x24,
                    ),
                child: fill
                    ? Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: content,
                      )
                    : SingleChildScrollView(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: content,
                        ),
                      ),
              ),
            ),
            if (actions.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  PeelSpace.x24,
                  PeelSpace.x8,
                  PeelSpace.x24,
                  PeelSpace.x16,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    for (var i = 0; i < actions.length; i++) ...[
                      if (i > 0) const SizedBox(height: PeelSpace.x8),
                      actions[i],
                    ],
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// Shared geometry for Peel → capture → device so [PeelRiveSlot] reports the
/// same global rect on every stage screen (viewport + constants only).
///
/// Do not wrap [PeelRiveSlot] in [Expanded] + vertical [Center]/[Align] —
/// the slot stays top-aligned under a fixed header.
class PeelStageScaffold extends StatelessWidget {
  const PeelStageScaffold({
    super.key,
    required this.header,
    required this.stage,
    required this.primaryAction,
    this.bottom,
    this.secondaryAction,
  });

  /// Usually a [PeelStageHeader], or a [PageView] of headers at the same height.
  final Widget header;

  final PeelStage stage;

  /// Chips or other footer. When null, reserves [ScanSteps.extent] empty space.
  final Widget? bottom;

  final Widget primaryAction;

  /// Second action row. When null, reserves [actionHeight] empty space so the
  /// actions band matches screens with Back / secondary.
  final Widget? secondaryAction;

  static const actionHeight = 56.0;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: PeelColors.canvas,
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: PeelSpace.x24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    header,
                    Expanded(child: PeelRiveSlot(stage: stage)),
                    bottom ?? const SizedBox(height: ScanSteps.extent),
                  ],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                PeelSpace.x24,
                PeelSpace.x8,
                PeelSpace.x24,
                PeelSpace.x16,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  primaryAction,
                  const SizedBox(height: PeelSpace.x8),
                  secondaryAction ??
                      const SizedBox(height: PeelStageScaffold.actionHeight),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Fixed-height brand header above the shared Rive slot so the artboard
/// keeps the same Y across onboarding and scan screens.
class PeelStageHeader extends StatelessWidget {
  const PeelStageHeader({super.key, required this.title, this.trailing});

  /// Top pad (16) + two brand lines (68×2) + bottom pad (8).
  static const height = 160.0;

  final String title;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: height,
      width: double.infinity,
      child: Padding(
        padding: const EdgeInsets.only(
          top: PeelSpace.x16,
          bottom: PeelSpace.x8,
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Text(
                title,
                style: PeelText.brand,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            if (trailing != null) trailing!,
          ],
        ),
      ),
    );
  }
}

/// Back / home row used on results, chat and report screens.
class PeelTopBar extends StatelessWidget {
  const PeelTopBar({
    super.key,
    required this.title,
    this.onBack,
    this.trailing,
  });

  final String title;
  final VoidCallback? onBack;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 56,
      padding: const EdgeInsets.symmetric(horizontal: PeelSpace.x12),
      decoration: const BoxDecoration(
        color: PeelColors.canvas,
        border: Border(bottom: BorderSide(color: PeelColors.line)),
      ),
      child: Row(
        children: [
          if (onBack != null)
            IconButton(
              onPressed: onBack,
              icon: const Icon(Icons.arrow_back, color: PeelColors.ink),
              tooltip: 'Back',
            )
          else
            const SizedBox(width: PeelSpace.x12),
          Expanded(child: Text(title, style: PeelText.heading)),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}
