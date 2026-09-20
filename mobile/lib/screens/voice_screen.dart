import 'package:flutter/material.dart';

import '../data/api_models.dart';
import '../services/peel_voice_client.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import '../widgets/transcript_ticker.dart';
import '../widgets/voice_waveform.dart';
import 'report_details_screen.dart';

class VoiceScreen extends StatefulWidget {
  const VoiceScreen({super.key});

  @override
  State<VoiceScreen> createState() => _VoiceScreenState();
}

class _VoiceScreenState extends State<VoiceScreen> {
  PeelVoiceClient? _client;
  ReportDraft? _openedDraft;
  bool _openingDraft = false;

  @override
  void initState() {
    super.initState();
    final scanId = scanSession.scanId ?? scanSession.scan?.scanId;
    if (scanId == null || scanId.isEmpty) {
      return;
    }
    final client = PeelVoiceClient(scanId: scanId);
    _client = client;
    client.addListener(_onClient);
    client.connect();
  }

  @override
  void dispose() {
    final client = _client;
    client?.removeListener(_onClient);
    client?.end();
    super.dispose();
  }

  void _onClient() {
    final client = _client;
    if (client == null || !mounted) return;
    setState(() {});
    final draft = client.lastDraft;
    if (draft == null || identical(draft, _openedDraft) || _openingDraft) {
      return;
    }
    _openedDraft = draft;
    _openingDraft = true;
    scanSession.applyDraft(draft);
    Navigator.of(context)
        .push(
          MaterialPageRoute<void>(
            builder: (_) => const ReportDetailsScreen(),
          ),
        )
        .whenComplete(() {
      _openingDraft = false;
    });
  }

  Future<void> _end() async {
    await _client?.end();
    if (!mounted) return;
    if (Navigator.of(context).canPop()) {
      Navigator.of(context).pop();
    }
  }

  String _label(VoiceAgentState state) => switch (state) {
        VoiceAgentState.connecting => 'Connecting',
        VoiceAgentState.listening => 'Listening',
        VoiceAgentState.thinking => 'Thinking',
        VoiceAgentState.speaking => 'Speaking',
        VoiceAgentState.ended => 'Ended',
        VoiceAgentState.error => 'Error',
      };

  @override
  Widget build(BuildContext context) {
    final client = _client;
    if (client == null) {
      return PeelScaffold(
        topBar: PeelTopBar(
          title: 'Peel',
          onBack: () => Navigator.of(context).pop(),
        ),
        content: [
          Text('No scan to talk about.', style: PeelText.body),
        ],
        actions: [
          PeelButton(
            label: 'End',
            onPressed: () => Navigator.of(context).pop(),
          ),
        ],
      );
    }
    final rms = client.state == VoiceAgentState.speaking
        ? client.playRms
        : client.micRms;
    return PeelScaffold(
      topBar: PeelTopBar(
        title: 'Peel',
        onBack: _end,
      ),
      content: [
        const SizedBox(height: PeelSpace.x24),
        PeelVoiceWaveform(state: client.state, rms: rms),
        const SizedBox(height: PeelSpace.x16),
        Text(
          _label(client.state),
          style: PeelText.heading.copyWith(color: PeelColors.teal),
          textAlign: TextAlign.center,
        ),
        if (client.error != null) ...[
          const SizedBox(height: PeelSpace.x8),
          Text(
            client.error!,
            style: PeelText.body.copyWith(color: PeelColors.error),
            textAlign: TextAlign.center,
          ),
        ],
        const SizedBox(height: PeelSpace.x16),
        TranscriptTicker(
          lines: client.lines,
          onAgentLineComplete: client.onAgentLineComplete,
        ),
      ],
      actions: [
        PeelButton(label: 'End', onPressed: _end),
      ],
    );
  }
}
