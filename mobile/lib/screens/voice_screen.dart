import 'dart:async';

import 'package:flutter/material.dart';

import '../services/voice_service.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import '../widgets/voice_waveform.dart';

class VoiceScreen extends StatefulWidget {
  const VoiceScreen({super.key});

  @override
  State<VoiceScreen> createState() => _VoiceScreenState();
}

class _VoiceScreenState extends State<VoiceScreen> {
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
        const SizedBox(height: PeelSpace.x24),
        PeelVoiceWaveform(state: _state),
        const SizedBox(height: PeelSpace.x16),
        Center(
          child: Text(
            _stateLabel,
            style: PeelText.heading.copyWith(color: PeelColors.teal),
          ),
        ),
        const SizedBox(height: PeelSpace.x8),
        Center(
          child: Text(
            _state == VoiceState.listening
                ? 'Ask your question out loud.'
                : _text,
            style: PeelText.body,
            textAlign: TextAlign.center,
          ),
        ),
        const SizedBox(height: PeelSpace.x8),
        if (_service.isMocked)
          const Center(
            child: Text(
              'Demo voice. Deepgram streaming turns on with an API key.',
              style: PeelText.caption,
              textAlign: TextAlign.center,
            ),
          ),
      ],
      actions: [
        PeelButton(
          label: 'End voice',
          onPressed: () => Navigator.of(context).pop(),
        ),
        PeelButton(
          label: 'Ask again',
          variant: PeelButtonVariant.secondary,
          onPressed: _start,
        ),
      ],
    );
  }
}
