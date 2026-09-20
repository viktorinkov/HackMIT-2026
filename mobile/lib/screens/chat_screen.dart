import 'dart:async';

import 'package:flutter/material.dart';

import '../data/mock_data.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import 'report_details_screen.dart';
import 'voice_screen.dart';

class ChatMessage {
  const ChatMessage(this.text, {required this.fromPeel});

  final String text;
  final bool fromPeel;
}

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  late final _messages = <ChatMessage>[
    ChatMessage(
      MockBackend.chatPrompt(scanSession.result.verdict),
      fromPeel: true,
    ),
  ];
  bool _thinking = false;
  bool _reportReady = false;

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _send([String? preset]) async {
    final text = (preset ?? _controller.text).trim();
    if (text.isEmpty) return;
    setState(() {
      _messages.add(ChatMessage(text, fromPeel: false));
      _controller.clear();
      _thinking = true;
    });
    _scrollToEnd();
    await Future<void>.delayed(const Duration(milliseconds: 1200));
    if (!mounted) return;
    setState(() {
      _thinking = false;
      _messages.add(
        ChatMessage(
          MockBackend.reply(scanSession.result.verdict, text),
          fromPeel: true,
        ),
      );
      _reportReady = scanSession.result.canReport;
    });
    _scrollToEnd();
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) return;
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: PeelColors.canvas,
      body: SafeArea(
        child: Column(
          children: [
            PeelTopBar(
              title: 'Chat',
              onBack: () => Navigator.of(context).pop(),
              trailing: IconButton(
                tooltip: 'Start over',
                onPressed: () {
                  scanSession.reset();
                  Navigator.of(context).popUntil((route) => route.isFirst);
                },
                icon: const Icon(Icons.home_outlined, color: PeelColors.ink),
              ),
            ),
            Expanded(
              child: ListView(
                controller: _scrollController,
                padding: const EdgeInsets.all(PeelSpace.x24),
                children: [
                  for (final message in _messages) _Bubble(message: message),
                  if (_thinking)
                    const Padding(
                      padding: EdgeInsets.only(top: PeelSpace.x8),
                      child: Text('Thinking…', style: PeelText.caption),
                    ),
                  if (_reportReady) ...[
                    const SizedBox(height: PeelSpace.x16),
                    Container(
                      padding: const EdgeInsets.all(PeelSpace.x16),
                      decoration: BoxDecoration(
                        color: PeelColors.surface,
                        borderRadius: PeelRadii.r16,
                        border: Border.all(color: PeelColors.line),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('Report ready', style: PeelText.label),
                          const SizedBox(height: PeelSpace.x4),
                          const Text(
                            'Peel filled a report with your scan. Check it '
                            'before sending.',
                            style: PeelText.body,
                          ),
                          const SizedBox(height: PeelSpace.x12),
                          PeelButton(
                            label: 'Review report',
                            variant: PeelButtonVariant.secondary,
                            onPressed: () => Navigator.of(context).push(
                              MaterialPageRoute<void>(
                                builder: (_) => const ReportDetailsScreen(),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
            if (_messages.length == 1)
              Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: PeelSpace.x24,
                  vertical: PeelSpace.x8,
                ),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: ActionChip(
                    backgroundColor: PeelColors.soft,
                    side: const BorderSide(color: PeelColors.line),
                    label: const Text(
                      MockBackend.chatSuggestion,
                      style: PeelText.body,
                    ),
                    onPressed: () => _send(MockBackend.chatSuggestion),
                  ),
                ),
              ),
            _Composer(
              controller: _controller,
              onSend: _send,
              onVoice: () => Navigator.of(context).push(
                MaterialPageRoute<void>(builder: (_) => const VoiceScreen()),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble({required this.message});

  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final fromPeel = message.fromPeel;
    return Align(
      alignment: fromPeel ? Alignment.centerLeft : Alignment.centerRight,
      child: Container(
        margin: const EdgeInsets.only(bottom: PeelSpace.x12),
        padding: const EdgeInsets.all(PeelSpace.x12),
        constraints: const BoxConstraints(maxWidth: 300),
        decoration: BoxDecoration(
          color: fromPeel ? PeelColors.surface : PeelColors.soft,
          borderRadius: PeelRadii.r16,
          border: Border.all(color: PeelColors.line),
        ),
        child: Text(message.text, style: PeelText.body),
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.onSend,
    required this.onVoice,
  });

  final TextEditingController controller;
  final VoidCallback onSend;
  final VoidCallback onVoice;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(
        PeelSpace.x16,
        PeelSpace.x8,
        PeelSpace.x16,
        PeelSpace.x16,
      ),
      decoration: const BoxDecoration(
        color: PeelColors.canvas,
        border: Border(top: BorderSide(color: PeelColors.line)),
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: controller,
              style: PeelText.body,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => onSend(),
              decoration: InputDecoration(
                hintText: 'Ask about this pill',
                hintStyle: PeelText.body.copyWith(color: PeelColors.muted),
                filled: true,
                fillColor: PeelColors.surface,
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: PeelSpace.x16,
                  vertical: PeelSpace.x12,
                ),
                border: const OutlineInputBorder(
                  borderRadius: PeelRadii.r24,
                  borderSide: BorderSide(color: PeelColors.line),
                ),
                enabledBorder: const OutlineInputBorder(
                  borderRadius: PeelRadii.r24,
                  borderSide: BorderSide(color: PeelColors.line),
                ),
                focusedBorder: const OutlineInputBorder(
                  borderRadius: PeelRadii.r24,
                  borderSide: BorderSide(color: PeelColors.orange),
                ),
              ),
            ),
          ),
          const SizedBox(width: PeelSpace.x8),
          _RoundAction(
            icon: Icons.mic_none,
            background: PeelColors.surface,
            onPressed: onVoice,
            tooltip: 'Talk instead',
          ),
          const SizedBox(width: PeelSpace.x8),
          _RoundAction(
            icon: Icons.arrow_upward,
            background: PeelColors.orange,
            onPressed: onSend,
            tooltip: 'Send',
          ),
        ],
      ),
    );
  }
}

class _RoundAction extends StatelessWidget {
  const _RoundAction({
    required this.icon,
    required this.background,
    required this.onPressed,
    required this.tooltip,
  });

  final IconData icon;
  final Color background;
  final VoidCallback onPressed;
  final String tooltip;

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Material(
        color: background,
        shape: const CircleBorder(side: BorderSide(color: PeelColors.line)),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: onPressed,
          child: SizedBox(
            width: 48,
            height: 48,
            child: Icon(icon, color: PeelColors.ink),
          ),
        ),
      ),
    );
  }
}
