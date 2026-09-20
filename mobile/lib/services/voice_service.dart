import 'dart:async';

/// Voice states shown by the prototype.
enum VoiceState { listening, thinking, speaking }

/// Mocked voice loop.
///
/// The real chat will run on Deepgram: the official Flutter example
/// (deepgram_speech_to_text) streams microphone bytes into
/// `deepgram.listen.live(stream)` for transcription and plays
/// `deepgram.speak.text(reply)` back. That needs a Deepgram API key, so the
/// demo cycles through the same three states with canned copy instead.
class VoiceService {
  VoiceService({this.apiKey});

  /// Pass with `--dart-define=DEEPGRAM_API_KEY=...` to wire the real service.
  final String? apiKey;

  static const String _transcript = 'Is it safe to take this pill?';
  static const String _reply =
      'No. The imprint does not match the bottle, so do not take it.';

  bool get isMocked => apiKey == null || apiKey!.isEmpty;

  /// Emits the listening → thinking → speaking loop with the copy for each
  /// state.
  Stream<({VoiceState state, String text})> run() async* {
    yield (state: VoiceState.listening, text: 'Listening');
    await Future<void>.delayed(const Duration(milliseconds: 2600));
    yield (state: VoiceState.thinking, text: _transcript);
    await Future<void>.delayed(const Duration(milliseconds: 1800));
    yield (state: VoiceState.speaking, text: _reply);
  }
}
