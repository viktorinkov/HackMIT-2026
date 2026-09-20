import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:waveform_flutter/waveform_flutter.dart';

import '../services/voice_service.dart';
import '../theme/peel_theme.dart';

/// Bar waveform for the voice screen.
///
/// The band is always full width: it starts as a flat baseline and the bars
/// rise in place as amplitudes arrive, instead of sweeping in from one side.
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
  static const _barWidth = 4.0;
  static const _barGap = 4.0;
  static const _flatHold = Duration(milliseconds: 500);

  final _random = Random();
  final _levels = <double>[];
  Timer? _timer;
  int _frame = 0;
  DateTime _flatUntil = DateTime.now().add(_flatHold);

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
      _flatUntil = DateTime.now().add(_flatHold);
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
    final amplitude = DateTime.now().isBefore(_flatUntil)
        ? Amplitude(current: 0, max: 100)
        : Amplitude(current: _level * 100, max: 100);
    _levels
      ..removeAt(0)
      ..add(amplitude.current / amplitude.max);
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
      child: LayoutBuilder(
        builder: (context, constraints) {
          final bars = (constraints.maxWidth / (_barWidth + _barGap)).floor();
          if (bars != _levels.length) {
            _levels
              ..clear()
              ..addAll(List<double>.filled(bars, 0));
          }
          return Row(
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
