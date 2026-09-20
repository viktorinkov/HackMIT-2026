import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:audio_stream_player/audio_stream_player.dart';
import 'package:flutter/foundation.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:record/record.dart';
import 'package:web_socket_channel/io.dart';

import '../data/api_models.dart';
import 'peel_api.dart';

enum VoiceAgentState {
  connecting,
  listening,
  thinking,
  speaking,
  ended,
  error,
}

class TranscriptLine {
  const TranscriptLine({
    required this.role,
    required this.text,
    this.interrupted = false,
  });

  final String role;
  final String text;
  final bool interrupted;
}

class PeelVoiceClient extends ChangeNotifier {
  PeelVoiceClient({required this.scanId, PeelApi? api}) : _api = api ?? peelApi;

  final String scanId;
  final PeelApi _api;

  VoiceAgentState state = VoiceAgentState.connecting;
  String? error;
  double micRms = 0;
  double playRms = 0;
  final List<TranscriptLine> lines = [];
  ReportDraft? lastDraft;
  int turn = 0;

  IOWebSocketChannel? _socket;
  AudioRecorder? _recorder;
  AudioStreamPlayer? _player;
  StreamSubscription<Uint8List>? _micSub;
  StreamSubscription<dynamic>? _wsSub;
  Timer? _listenDebounce;
  bool _dropPlayback = false;
  bool _closed = false;
  bool _fedPlayback = false;
  bool _stopping = false;
  bool _playStarted = false;
  bool _agentAnimating = false;
  int _playbackGen = 0;
  Future<void> _playerQueue = Future<void>.value();
  final List<String> _recentAgent = [];
  final List<String> _pendingAssistant = [];
  Completer<void>? _welcome;
  Completer<void>? _settingsApplied;

  Future<void> connect() async {
    state = VoiceAgentState.connecting;
    error = null;
    notifyListeners();
    final mic = await Permission.microphone.request();
    if (!mic.isGranted) {
      _fail('Microphone permission is required.');
      return;
    }
    final playerFuture = AudioStreamPlayer.create(sampleRate: 24000);
    late final DeepgramSession session;
    try {
      session = await _api.createSession(scanId);
    } on PeelApiException catch (caught) {
      try {
        await (await playerFuture).dispose();
      } catch (_) {}
      _fail(caught.message);
      return;
    } catch (caught) {
      try {
        await (await playerFuture).dispose();
      } catch (_) {}
      _fail(caught.toString());
      return;
    }
    try {
      _player = await playerFuture;
    } catch (caught) {
      _fail(caught.toString());
      return;
    }
    final headers = <String, dynamic>{};
    if (session.authorization == 'Bearer' &&
        session.accessToken != null &&
        session.accessToken!.isNotEmpty) {
      headers['Authorization'] = 'Bearer ${session.accessToken}';
    } else {
      const key = String.fromEnvironment('DEEPGRAM_API_KEY');
      if (key.isEmpty) {
        _fail(session.grantError ?? 'No Deepgram token.');
        return;
      }
      headers['Authorization'] = 'Token $key';
    }
    _welcome = Completer<void>();
    _settingsApplied = Completer<void>();
    _socket = IOWebSocketChannel.connect(
      Uri.parse(session.websocketUrl),
      headers: headers,
    );
    _wsSub = _socket!.stream.listen(
      _onMessage,
      onError: (Object caught) => _fail(caught.toString()),
      onDone: () {
        if (!_closed && state != VoiceAgentState.ended) {
          _fail('The voice session closed.');
        }
      },
    );
    try {
      await _welcome!.future.timeout(const Duration(seconds: 8));
    } on TimeoutException {
      _fail('Deepgram did not welcome the session.');
      return;
    }
    if (_closed) return;
    _socket!.sink.add(jsonEncode(session.settings));
    try {
      await _settingsApplied!.future.timeout(const Duration(seconds: 8));
    } on TimeoutException {
      _fail('Deepgram did not apply settings.');
      return;
    }
    if (_closed) return;
    try {
      _recorder = AudioRecorder();
      final stream = await _recorder!.startStream(
        const RecordConfig(
          encoder: AudioEncoder.pcm16bits,
          sampleRate: 16000,
          numChannels: 1,
          echoCancel: true,
          noiseSuppress: false,
          androidConfig: AndroidRecordConfig(
            audioSource: AndroidAudioSource.voiceCommunication,
            audioManagerMode: AudioManagerMode.modeNormal,
            speakerphone: false,
            manageBluetooth: false,
          ),
        ),
      );
      _micSub = stream.listen((chunk) {
        if (_closed) return;
        micRms = _rms(chunk);
        _socket?.sink.add(chunk);
        notifyListeners();
      });
    } catch (caught) {
      _fail(caught.toString());
      return;
    }
    state = VoiceAgentState.listening;
    notifyListeners();
  }

  void _onMessage(dynamic raw) {
    if (raw is List<int>) {
      final bytes = raw is Uint8List ? raw : Uint8List.fromList(raw);
      _onAgentAudio(bytes);
      return;
    }
    if (raw is! String) return;
    Map<String, dynamic> message;
    try {
      message = jsonDecode(raw) as Map<String, dynamic>;
    } on FormatException {
      return;
    }
    final type = message['type'] as String? ?? '';
    final role = (message['role'] as String? ?? '').toLowerCase();
    final content =
        (message['content'] ?? message['transcript'] ?? message['description'] ?? '')
            .toString();
    if (type != 'LatencyReport' && type != 'History') {
      _logVoice(
        '$type role=$role drop=$_dropPlayback stopping=$_stopping gen=$_playbackGen ${_clip(content)}',
      );
    }
    switch (type) {
      case 'Welcome':
        _complete(_welcome);
      case 'SettingsApplied':
        _complete(_settingsApplied);
      case 'UserStartedSpeaking':
        _onUserStartedSpeaking();
      case 'AgentStartedSpeaking':
        _armPlayback();
        unawaited(_ensurePlaying(_playbackGen));
        _staySpeaking();
        notifyListeners();
      case 'AgentAudioDone':
        unawaited(_finishPlayback(_playbackGen));
      case 'AgentThinking':
        _armPlayback();
        if (state != VoiceAgentState.speaking &&
            state != VoiceAgentState.ended &&
            state != VoiceAgentState.error) {
          state = VoiceAgentState.thinking;
          notifyListeners();
        }
      case 'ConversationText':
        _onConversation(message);
      case 'FunctionCallRequest':
        unawaited(_onFunctionCall(message));
      case 'FunctionCallCancelled':
        break;
      case 'LatencyReport':
        break;
      case 'Error':
        _fail(message['description'] as String? ?? 'Voice error');
      case 'Warning':
        break;
    }
  }

  void _onUserStartedSpeaking() {
    turn += 1;
    _playbackGen += 1;
    final gen = _playbackGen;
    _dropPlayback = true;
    _fedPlayback = false;
    _playStarted = false;
    _stopping = true;
    _listenDebounce?.cancel();
    _listenDebounce = null;
    _interruptAgentLine();
    state = VoiceAgentState.listening;
    notifyListeners();
    unawaited(_serial(() async {
      try {
        await _player?.stop();
      } catch (caught) {
        _logVoice('stop $caught');
      }
      if (_playbackGen != gen) return;
      _stopping = false;
      playRms = 0;
    }));
  }

  void _onAgentAudio(Uint8List bytes) {
    _logVoice(
      'binary ${bytes.length} drop=$_dropPlayback stopping=$_stopping gen=$_playbackGen',
    );
    if (_stopping) return;
    if (_dropPlayback) {
      _armPlayback();
      _logVoice('arm binary gen=$_playbackGen');
    }
    final gen = _playbackGen;
    playRms = _rms(bytes);
    _fedPlayback = true;
    _staySpeaking();
    notifyListeners();
    unawaited(_serial(() async {
      if (_playbackGen != gen || _dropPlayback || _stopping) return;
      await _ensurePlayingLocked(gen);
      if (_playbackGen != gen || _dropPlayback) return;
      try {
        await _player?.feed(bytes);
      } catch (caught) {
        _logVoice('feed $caught');
      }
    }));
  }

  void _armPlayback() {
    _dropPlayback = false;
  }

  void _complete(Completer<void>? completer) {
    if (completer != null && !completer.isCompleted) {
      completer.complete();
    }
  }

  void _onConversation(Map<String, dynamic> message) {
    final role = (message['role'] as String? ?? '').toLowerCase();
    final text = (message['content'] ?? message['transcript'] ?? '').toString();
    if (text.isEmpty) return;
    if (role == 'user' && _isEcho(text)) return;
    if (role == 'assistant' || role == 'agent') {
      _recentAgent.add(text);
      if (_recentAgent.length > 6) _recentAgent.removeAt(0);
      _armPlayback();
      _staySpeaking();
      _offerAssistant(text);
    } else if (role == 'user') {
      lines.add(TranscriptLine(role: 'user', text: text));
      if (state != VoiceAgentState.ended && state != VoiceAgentState.error) {
        state = VoiceAgentState.listening;
      }
    }
    notifyListeners();
  }

  bool _isEcho(String text) {
    final needle = _normalize(text);
    if (needle.isEmpty) return false;
    for (final said in _recentAgent.reversed.take(4)) {
      final hay = _normalize(said);
      if (hay.isEmpty) continue;
      if (needle == hay) return true;
      if (hay.contains(needle) && needle.length > 12) return true;
      if (needle.contains(hay) && hay.length > 12) return true;
    }
    return false;
  }

  String _normalize(String text) {
    return text
        .toLowerCase()
        .replaceAll(RegExp(r'[^a-z0-9 ]'), ' ')
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
  }

  void _offerAssistant(String text) {
    if (lines.isNotEmpty) {
      final last = lines.last;
      if (last.role == 'assistant' &&
          !last.interrupted &&
          text != last.text &&
          (text.startsWith(last.text) || last.text.startsWith(text))) {
        lines[lines.length - 1] = TranscriptLine(role: 'assistant', text: text);
        _agentAnimating = true;
        return;
      }
    }
    if (!_agentAnimating) {
      lines.add(TranscriptLine(role: 'assistant', text: text));
      _agentAnimating = true;
      return;
    }
    _pendingAssistant.add(text);
  }

  void onAgentLineComplete() {
    if (_closed) return;
    if (_pendingAssistant.isEmpty) {
      _agentAnimating = false;
      return;
    }
    lines.add(
      TranscriptLine(role: 'assistant', text: _pendingAssistant.removeAt(0)),
    );
    _agentAnimating = true;
    notifyListeners();
  }

  void _interruptAgentLine() {
    _pendingAssistant.clear();
    _agentAnimating = false;
    if (lines.isEmpty) return;
    final last = lines.last;
    if (last.role != 'assistant' || last.interrupted) return;
    lines[lines.length - 1] = TranscriptLine(
      role: last.role,
      text: last.text,
      interrupted: true,
    );
  }

  Future<void> _onFunctionCall(Map<String, dynamic> message) async {
    final calls = message['functions'] as List? ?? const [];
    for (final call in calls) {
      if (call is! Map) continue;
      final name = call['name'] as String?;
      final id = call['id'] as String?;
      if (name != 'draft_report' || id == null) continue;
      Map<String, dynamic> args = {};
      try {
        final raw = call['arguments'];
        if (raw is String) {
          args = jsonDecode(raw) as Map<String, dynamic>;
        } else if (raw is Map<String, dynamic>) {
          args = raw;
        }
      } on FormatException {
        args = {};
      }
      lastDraft = ReportDraft.fromJson(args);
      _socket?.sink.add(
        jsonEncode({
          'type': 'FunctionCallResponse',
          'id': id,
          'name': name,
          'content': jsonEncode({'status': 'preview_open'}),
        }),
      );
      notifyListeners();
    }
  }

  Future<void> _serial(Future<void> Function() op) {
    final next = _playerQueue.then((_) async {
      if (_closed) return;
      await op();
    });
    _playerQueue = next.catchError((Object caught) {
      _logVoice('player $caught');
    });
    return next;
  }

  Future<void> _ensurePlaying(int gen) {
    return _serial(() => _ensurePlayingLocked(gen));
  }

  Future<void> _ensurePlayingLocked(int gen) async {
    if (_playbackGen != gen || _dropPlayback || _stopping) return;
    if (_playStarted) return;
    try {
      await _player?.play();
    } catch (caught) {
      _logVoice('play $caught');
      return;
    }
    if (_playbackGen != gen) return;
    _playStarted = true;
  }

  void _staySpeaking() {
    _listenDebounce?.cancel();
    _listenDebounce = null;
    if (state != VoiceAgentState.ended && state != VoiceAgentState.error) {
      state = VoiceAgentState.speaking;
    }
  }

  void _scheduleListening() {
    _listenDebounce?.cancel();
    _listenDebounce = Timer(const Duration(milliseconds: 800), () {
      if (_closed) return;
      if (state == VoiceAgentState.speaking ||
          state == VoiceAgentState.thinking) {
        state = VoiceAgentState.listening;
        playRms = 0;
        notifyListeners();
      }
    });
  }

  Future<void> _finishPlayback(int gen) async {
    await _serial(() async {
      if (_playbackGen != gen) return;
      if (_fedPlayback) {
        try {
          await _player?.endOfStream();
        } catch (caught) {
          _logVoice('eos $caught');
        }
      }
      if (_playbackGen != gen) return;
      _fedPlayback = false;
      _playStarted = false;
      if (_closed) return;
      _scheduleListening();
    });
  }

  void _logVoice(String message) {
    if (kDebugMode) debugPrint('peel.voice $message');
  }

  String _clip(String text) {
    final trimmed = text.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (trimmed.isEmpty) return '';
    if (trimmed.length <= 80) return trimmed;
    return '${trimmed.substring(0, 80)}…';
  }

  Future<void> end() async {
    _closed = true;
    _listenDebounce?.cancel();
    _listenDebounce = null;
    if (state != VoiceAgentState.error) {
      state = VoiceAgentState.ended;
    }
    await _micSub?.cancel();
    await _wsSub?.cancel();
    try {
      await _recorder?.stop();
    } catch (_) {}
    try {
      await _recorder?.dispose();
    } catch (_) {}
    try {
      await _player?.stop();
    } catch (_) {}
    try {
      await _player?.dispose();
    } catch (_) {}
    _player = null;
    try {
      await _socket?.sink.close();
    } catch (_) {}
    notifyListeners();
  }

  void _fail(String message) {
    if (_closed) return;
    error = message;
    state = VoiceAgentState.error;
    notifyListeners();
    unawaited(end());
  }

  double _rms(Uint8List pcm) {
    if (pcm.length < 2) return 0;
    var sum = 0.0;
    final samples = pcm.length ~/ 2;
    final data = ByteData.sublistView(pcm);
    for (var i = 0; i < samples; i++) {
      final sample = data.getInt16(i * 2, Endian.little) / 32768.0;
      sum += sample * sample;
    }
    return min(1, sqrt(sum / samples) * 4);
  }
}
