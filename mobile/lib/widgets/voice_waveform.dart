import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';

import '../services/peel_voice_client.dart';
import '../theme/peel_theme.dart';

/// Bar waveform for the voice screen, driven by live mic and playback RMS.
class PeelVoiceWaveform extends StatefulWidget {
  const PeelVoiceWaveform({
    required this.state,
    required this.rms,
    super.key,
  });

  final VoiceAgentState state;
  final double rms;

  @override
  State<PeelVoiceWaveform> createState() => _PeelVoiceWaveformState();
}

class _PeelVoiceWaveformState extends State<PeelVoiceWaveform> {
  static const _tick = Duration(milliseconds: 110);
  static const _height = 132.0;
  static const _barWidth = 4.0;
  static const _barGap = 4.0;

  final _levels = <double>[];
  Timer? _timer;
  int _frame = 0;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(_tick, (_) => setState(_advance));
  }

  @override
  void didUpdateWidget(PeelVoiceWaveform oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.state != widget.state) {
      _levels.fillRange(0, _levels.length, 0);
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _advance() {
    if (_levels.isEmpty) return;
    _frame++;
    final mid = _levels.length ~/ 2;
    final next = _level;
    for (var i = 0; i < mid; i++) {
      _levels[i] = _levels[i + 1];
    }
    for (var i = _levels.length - 1; i > mid; i--) {
      _levels[i] = _levels[i - 1];
    }
    _levels[mid] = next;
    if (_levels.length.isEven && mid > 0) {
      _levels[mid - 1] = next;
    }
  }

  double get _level {
    final live = widget.rms.clamp(0.0, 1.0);
    final phase = _frame * 0.35;
    return switch (widget.state) {
      VoiceAgentState.listening => max(0.06, min(1.0, pow(live, 0.55) * 1.8)),
      VoiceAgentState.speaking => max(0.08, live),
      VoiceAgentState.thinking => 0.10 + 0.05 * (1 + sin(phase * 0.6)),
      VoiceAgentState.connecting ||
      VoiceAgentState.ended ||
      VoiceAgentState.error =>
        0,
    };
  }

  Color get _color => switch (widget.state) {
        VoiceAgentState.listening => PeelColors.orange,
        VoiceAgentState.thinking => PeelColors.line,
        VoiceAgentState.speaking => PeelColors.teal,
        VoiceAgentState.connecting ||
        VoiceAgentState.ended ||
        VoiceAgentState.error =>
          PeelColors.line,
      };

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: _height,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final bars = (constraints.maxWidth / (_barWidth + _barGap)).floor();
          if (bars != _levels.length) {
            _levels
              ..clear()
              ..addAll(List<double>.filled(max(0, bars), 0));
          }
          return Row(
            key: ValueKey(widget.state),
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              for (final level in _levels)
                AnimatedContainer(
                  duration: _tick,
                  curve: Curves.easeOut,
                  width: _barWidth,
                  height: 4 + level * 108,
                  margin: const EdgeInsets.symmetric(horizontal: _barGap / 2),
                  decoration: BoxDecoration(
                    color: _color,
                    borderRadius: BorderRadius.circular(999),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}
