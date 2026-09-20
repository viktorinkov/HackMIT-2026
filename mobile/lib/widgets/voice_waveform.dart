import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:waveform_flutter/waveform_flutter.dart';

import '../services/voice_service.dart';
import '../theme/peel_theme.dart';

/// Scrolling bar waveform for the voice screen.
///
/// Each state gets its own colour and motion so you can tell who is talking
/// without reading the label: orange jitter while you speak, a slow grey pulse
/// while Peel thinks, a steady teal swell while Peel answers.
class PeelVoiceWaveform extends StatefulWidget {
  const PeelVoiceWaveform({required this.state, super.key});

  final VoiceState state;

  @override
  State<PeelVoiceWaveform> createState() => _PeelVoiceWaveformState();
}

class _PeelVoiceWaveformState extends State<PeelVoiceWaveform> {
  static const _tick = Duration(milliseconds: 70);
  static const _height = 132.0;
  static const _barSpace = 8.0;
  // Long enough for the baseline bars to finish animating in and be seen.
  static const _flatHold = Duration(milliseconds: 500);

  final _random = Random();
  final _amplitudes = StreamController<Amplitude>.broadcast();
  Timer? _timer;
  int _frame = 0;

  @override
  void initState() {
    super.initState();
    _flatten();
  }

  @override
  void didUpdateWidget(PeelVoiceWaveform oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.state != widget.state) _flatten();
  }

  /// Fills the band with baseline bars and holds them there, so the wave
  /// starts as a flat line across the full width and rises in place rather
  /// than scrolling in from the right.
  void _flatten() {
    _timer?.cancel();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final bars = (MediaQuery.of(context).size.width / _barSpace).ceil();
      for (var i = 0; i < bars; i++) {
        _amplitudes.add(Amplitude(current: 0, max: 100));
      }
      _timer = Timer(_flatHold, _run);
    });
  }

  void _run() {
    _timer = Timer.periodic(_tick, (_) {
      _frame++;
      _amplitudes.add(Amplitude(current: _level * 100, max: 100));
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _amplitudes.close();
    super.dispose();
  }

  double get _level {
    final phase = _frame * 0.35;
    return switch (widget.state) {
      VoiceState.listening => 0.35 + _random.nextDouble() * 0.65,
      VoiceState.thinking => 0.10 + 0.05 * (1 + sin(phase * 0.6)),
      VoiceState.speaking =>
        0.30 + 0.45 * (0.5 + 0.5 * sin(phase)) + _random.nextDouble() * 0.1,
    };
  }

  Color get _color => switch (widget.state) {
        VoiceState.listening => PeelColors.orange,
        VoiceState.thinking => PeelColors.line,
        VoiceState.speaking => PeelColors.teal,
      };

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: _height,
      child: AnimatedWaveList(
        // Restarting the list per state keeps old bars from being recoloured,
        // so each state reads as its own wave.
        key: ValueKey(widget.state),
        stream: _amplitudes.stream,
        barBuilder: (animation, amplitude) => _Bar(
          animation: animation,
          level: amplitude.current / amplitude.max,
          color: _color,
        ),
      ),
    );
  }
}

class _Bar extends StatelessWidget {
  const _Bar({
    required this.animation,
    required this.level,
    required this.color,
  });

  final Animation<double> animation;
  final double level;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return SizeTransition(
      sizeFactor: animation,
      axis: Axis.horizontal,
      child: Center(
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          curve: Curves.easeOut,
          width: 4,
          height: 8 + level * 104,
          margin: const EdgeInsets.symmetric(horizontal: 2),
          decoration: BoxDecoration(
            color: color,
            borderRadius: BorderRadius.circular(999),
          ),
        ),
      ),
    );
  }
}
