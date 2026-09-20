import 'dart:async';

import '../data/mock_data.dart';

/// Voice states shown by the prototype.
enum VoiceState { listening, thinking, speaking }

/// Mocked voice loop for the demo.
///
/// The real implementation will call the backend's `POST /deepgram/session`
/// for a scan and drive a Deepgram Voice Agent websocket from the returned
/// `websocket_url` + `settings`, emitting the same listening / thinking /
/// speaking states. No Deepgram key ships in the app.
class VoiceService {
  VoiceService({required this.verdict});

  final ScanVerdict verdict;

  static const String _transcript = 'Is it safe to take this pill?';

  /// Emits the listening → thinking → speaking loop with the copy for each
  /// state.
  Stream<({VoiceState state, String text})> run() async* {
    yield (state: VoiceState.listening, text: 'Listening');
    await Future<void>.delayed(const Duration(milliseconds: 2600));
    yield (state: VoiceState.thinking, text: _transcript);
    await Future<void>.delayed(const Duration(milliseconds: 1800));
    yield (
      state: VoiceState.speaking,
      text: MockBackend.reply(verdict, _transcript)
    );
  }
}
