import 'dart:async';

import 'package:flutter/material.dart';

import '../rive/peel_rive_stage.dart';
import '../rive/peel_rive_widgets.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';

/// Sending → sent. Submission is mocked.
class SendingReportScreen extends StatefulWidget {
  const SendingReportScreen({super.key});

  @override
  State<SendingReportScreen> createState() => _SendingReportScreenState();
}

class _SendingReportScreenState extends State<SendingReportScreen> {
  bool _sent = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer(const Duration(milliseconds: 2200), () {
      if (mounted) setState(() => _sent = true);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return PeelScaffold(
      content: [
        Text(_sent ? 'Report sent' : 'Sending report', style: PeelText.title),
        const SizedBox(height: PeelSpace.x8),
        Text(
          _sent
              ? 'Thank you. Someone will look at this bottle.'
              : 'Your report and scan photos are on their way.',
          style: PeelText.body,
        ),
        const SizedBox(height: PeelSpace.x24),
        PeelRiveSlot(
          stage: _sent ? PeelStage.complete : PeelStage.research,
          aspectRatio: 13 / 12,
        ),
      ],
      actions: [
        if (_sent)
          PeelButton(
            label: 'Back to results',
            onPressed: () => Navigator.of(context).popUntil(
              (route) => route.settings.name == 'results' || route.isFirst,
            ),
          ),
      ],
    );
  }
}
