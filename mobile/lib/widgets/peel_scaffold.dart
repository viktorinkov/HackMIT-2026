import 'package:flutter/material.dart';

import '../theme/peel_theme.dart';

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
                padding: padding ??
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

/// Figma's "Shared scan header" (364x176): a fixed block above the shared
/// Rive slot, so the slot starts at the same y on every screen of the flow
/// and the artboard neither moves nor resizes across navigation.
class PeelStageHeader extends StatelessWidget {
  const PeelStageHeader({super.key, required this.title, this.trailing});

  static const height = 176.0;
  static const _titleHeight = 136.0;

  final String title;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: height,
      width: double.infinity,
      child: Padding(
        padding: const EdgeInsets.only(top: PeelSpace.x24),
        child: SizedBox(
          height: _titleHeight,
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
