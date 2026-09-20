import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_animate/flutter_animate.dart';

import '../services/peel_voice_client.dart';
import '../theme/peel_theme.dart';

class TranscriptTicker extends StatefulWidget {
  const TranscriptTicker({
    super.key,
    required this.lines,
    this.onAgentLineComplete,
  });

  final List<TranscriptLine> lines;
  final VoidCallback? onAgentLineComplete;

  @override
  State<TranscriptTicker> createState() => _TranscriptTickerState();
}

class _TickerEntry {
  _TickerEntry(this.line, this.id);

  TranscriptLine line;
  final int id;

  /// Keeps the word-reveal state alive when the exit animation rewraps it.
  final GlobalKey wordsKey = GlobalKey();
  bool exiting = false;
}

class _TranscriptTickerState extends State<TranscriptTicker> {
  static const _keep = 8;
  static const _boxHeight = 256.0;
  static const _exit = Duration(milliseconds: 280);
  static const _follow = Duration(milliseconds: 220);

  final ScrollController _scroll = ScrollController();
  final List<_TickerEntry> _entries = [];
  int _nextId = 0;
  int _seen = 0;
  bool _followQueued = false;
  double? _followingTo;

  @override
  void initState() {
    super.initState();
    _sync();
  }

  @override
  void didUpdateWidget(TranscriptTicker oldWidget) {
    super.didUpdateWidget(oldWidget);
    _sync();
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _sync() {
    final lines = widget.lines;
    if (lines.length < _seen) {
      _seen = lines.length;
    }
    for (var i = _seen; i < lines.length; i++) {
      _entries.add(_TickerEntry(lines[i], _nextId++));
    }
    _seen = lines.length;
    if (_entries.isNotEmpty && lines.isNotEmpty) {
      _entries.last.line = lines.last;
    }
    while (_entries.where((entry) => !entry.exiting).length > _keep) {
      final oldest = _entries.firstWhere((entry) => !entry.exiting);
      oldest.exiting = true;
      Future<void>.delayed(_exit, () {
        if (!mounted) return;
        setState(() => _entries.remove(oldest));
        _followEnd();
      });
    }
    _followEnd();
  }

  /// Pins the newest text to the bottom. Requests in the same frame collapse
  /// into one animation, and an animation already heading to the current
  /// bottom is left alone.
  void _followEnd() {
    if (_followQueued) return;
    _followQueued = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _followQueued = false;
      if (!mounted || !_scroll.hasClients) return;
      final target = _scroll.position.maxScrollExtent;
      if (_followingTo == target) return;
      if ((target - _scroll.offset).abs() < 1) {
        _followingTo = null;
        return;
      }
      _followingTo = target;
      _scroll
          .animateTo(target, duration: _follow, curve: Curves.easeOutCubic)
          .whenComplete(() {
        if (_followingTo == target) _followingTo = null;
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: _boxHeight,
      child: SingleChildScrollView(
        controller: _scroll,
        physics: const NeverScrollableScrollPhysics(),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: _boxHeight),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            mainAxisAlignment: MainAxisAlignment.end,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              for (final entry in _entries)
                _TickerLine(
                  key: ValueKey(entry.id),
                  entry: entry,
                  onAgentProgress: _followEnd,
                  onAgentComplete: entry.line.role == 'assistant'
                      ? widget.onAgentLineComplete
                      : null,
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TickerLine extends StatelessWidget {
  const _TickerLine({
    super.key,
    required this.entry,
    required this.onAgentProgress,
    this.onAgentComplete,
  });

  final _TickerEntry entry;
  final VoidCallback onAgentProgress;
  final VoidCallback? onAgentComplete;

  @override
  Widget build(BuildContext context) {
    final line = entry.line;
    final child = Padding(
      padding: const EdgeInsets.only(bottom: PeelSpace.x8),
      child: Align(
        alignment:
            line.role == 'user' ? Alignment.centerRight : Alignment.centerLeft,
        child: line.role == 'user'
            ? Text(
                line.text,
                textAlign: TextAlign.right,
                style: PeelText.body.copyWith(fontWeight: FontWeight.w700),
              )
            : _AgentWords(
                key: entry.wordsKey,
                line: line,
                onProgress: onAgentProgress,
                onComplete: onAgentComplete,
              ),
      ),
    );
    final animated = child.animate(key: ValueKey('${entry.id}-${entry.exiting}'));
    if (entry.exiting) {
      return animated
          .fadeOut(duration: 280.ms)
          .blurXY(begin: 0, end: 8)
          .slideY(begin: 0, end: -0.35);
    }
    return animated
        .fadeIn(duration: 280.ms)
        .slideY(begin: 0.2, duration: 280.ms)
        .blurXY(begin: 8, end: 0, duration: 280.ms);
  }
}

class _AgentWords extends StatefulWidget {
  const _AgentWords({
    super.key,
    required this.line,
    required this.onProgress,
    this.onComplete,
  });

  final TranscriptLine line;
  final VoidCallback onProgress;
  final VoidCallback? onComplete;

  @override
  State<_AgentWords> createState() => _AgentWordsState();
}

class _AgentWordsState extends State<_AgentWords> {
  static const _perWord = Duration(milliseconds: 380);
  late List<String> _words = _split(widget.line.text);
  int _shown = 0;
  Timer? _timer;
  bool _notified = false;

  @override
  void initState() {
    super.initState();
    _start();
  }

  @override
  void didUpdateWidget(_AgentWords oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.line.text != widget.line.text) {
      _words = _split(widget.line.text);
      _shown = 0;
      _notified = false;
      _start();
    } else if (widget.line.interrupted) {
      _timer?.cancel();
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _finishLine() {
    if (_notified || widget.line.interrupted) return;
    _notified = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || widget.line.interrupted) return;
      widget.onComplete?.call();
    });
  }

  void _start() {
    _timer?.cancel();
    if (widget.line.interrupted) {
      _shown = _words.length;
      return;
    }
    if (_words.isEmpty) {
      _finishLine();
      return;
    }
    _timer = Timer.periodic(_perWord, (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      if (_shown >= _words.length) {
        timer.cancel();
        _finishLine();
        return;
      }
      setState(() => _shown += 1);
      widget.onProgress();
      if (_shown >= _words.length) {
        timer.cancel();
        _finishLine();
      }
    });
  }

  List<String> _split(String text) =>
      text.split(RegExp(r'\s+')).where((word) => word.isNotEmpty).toList();

  @override
  Widget build(BuildContext context) {
    final interrupted = widget.line.interrupted;
    final visible = _words.take(_shown).join(' ');
    final text = interrupted
        ? (visible.isEmpty ? '…' : '$visible…')
        : visible;
    final style = interrupted
        ? PeelText.body.copyWith(color: PeelColors.muted)
        : PeelText.body;
    if (text.isEmpty) return const SizedBox.shrink();
    if (_shown >= _words.length || interrupted) {
      return Text(text, style: style);
    }
    return DefaultTextStyle(
      style: style,
      child: Wrap(
        children: [
          for (var i = 0; i < _shown; i++)
            Text('${_words[i]} ', style: style)
                .animate(key: ValueKey('aw-$i'))
                .fadeIn(duration: 180.ms),
        ],
      ),
    );
  }
}
