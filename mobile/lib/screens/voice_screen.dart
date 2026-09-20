import 'dart:async';

import 'package:flutter/material.dart';
import 'package:siri_wave/siri_wave.dart';

import '../services/voice_service.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/animation_placeholder.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';

class VoiceScreen extends StatefulWidget {
  const VoiceScreen({super.key});

  @override
  State<VoiceScreen> createState() => _VoiceScreenState();
}

class _VoiceScreenState extends State<VoiceScreen> {
  final _waveController = IOS9SiriWaveformController(amplitude: 1, speed: 0.15);
  final _service = VoiceService(
    verdict: scanSession.result.verdict,
    apiKey: const String.fromEnvironment('DEEPGRAM_API_KEY'),
  );

  StreamSubscription<({VoiceState state, String text})>? _subscription;
  VoiceState _state = VoiceState.listening;
  String _text = 'Listening';

  @override
  void initState() {
    super.initState();
    _start();
  }

  @override
  void dispose() {
    _subscription?.cancel();
    super.dispose();
  }

  void _start() {
    _subscription?.cancel();
    setState(() {
      _state = VoiceState.listening;
      _text = 'Listening';
    });
    _subscription = _service.run().listen((event) {
      if (!mounted) return;
      setState(() {
        _state = event.state;
        _text = event.text;
      });
      _waveController.amplitude = switch (event.state) {
        VoiceState.listening => 1,
        VoiceState.thinking => 0.25,
        VoiceState.speaking => 0.8,
      };
    });
  }

  String get _stateLabel => switch (_state) {
        VoiceState.listening => 'Listening',
        VoiceState.thinking => 'Thinking',
        VoiceState.speaking => 'Speaking',
      };

  @override
  Widget build(BuildContext context) {
    return PeelScaffold(
      topBar: PeelTopBar(
        title: 'Voice chat',
        onBack: () => Navigator.of(context).pop(),
      ),
      content: [
        Text(_stateLabel, style: PeelText.title),
        const SizedBox(height: PeelSpace.x8),
        Text(
          _state == VoiceState.listening
              ? 'Ask your question out loud.'
              : _text,
          style: PeelText.body,
        ),
        const SizedBox(height: PeelSpace.x24),
        AnimationPlaceholder(
          description: '',
          tone: PlaceholderTone.mint,
          aspectRatio: 13 / 10,
          child: SiriWaveform.ios9(
            controller: _waveController,
            options: const IOS9SiriWaveformOptions(height: 180, width: 320),
          ),
        ),
        const SizedBox(height: PeelSpace.x8),
        if (_service.isMocked)
          const Text(
            'Demo voice. Deepgram streaming turns on with an API key.',
            style: PeelText.caption,
          ),
      ],
      actions: [
        PeelButton(
          label: 'Ask again',
          variant: PeelButtonVariant.secondary,
          onPressed: _start,
        ),
        PeelButton(
          label: 'End voice',
          onPressed: () => Navigator.of(context).pop(),
        ),
      ],
    );
  }
}
