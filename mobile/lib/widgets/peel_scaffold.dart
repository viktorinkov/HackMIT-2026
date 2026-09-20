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
  });

  final List<Widget> content;
  final List<Widget> actions;
  final Widget? topBar;

  /// Lays the content out inside the viewport instead of scrolling it, so a
  /// flexible child shrinks rather than sliding under the pinned actions.
  final bool fill;

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
                padding: const EdgeInsets.fromLTRB(
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
