import 'package:flutter/material.dart';

import '../data/api_models.dart';
import '../rive/peel_rive_stage.dart';
import '../rive/peel_rive_widgets.dart';
import '../services/peel_api.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';

class SendingReportScreen extends StatefulWidget {
  const SendingReportScreen({super.key});

  @override
  State<SendingReportScreen> createState() => _SendingReportScreenState();
}

class _SendingReportScreenState extends State<SendingReportScreen> {
  bool _busy = true;
  String? _error;
  FiledReport? _filed;

  @override
  void initState() {
    super.initState();
    _submit();
  }

  Future<void> _submit() async {
    final scanId = scanSession.scanId ?? scanSession.scan?.scanId;
    setState(() {
      _busy = true;
      _error = null;
    });
    if (scanId == null || scanId.isEmpty) {
      setState(() {
        _busy = false;
        _error = 'No scan to report.';
      });
      return;
    }
    try {
      final filed = await peelApi.submitReport(scanId, scanSession.reportDraft);
      if (!mounted) return;
      setState(() {
        _busy = false;
        _filed = filed;
      });
    } on PeelApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = error.message;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = error.toString();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final filed = _filed;
    final title = filed != null
        ? 'Report saved'
        : _busy
            ? 'Sending report'
            : 'Could not send';
    return PeelScaffold(
      fill: true,
      padding: const EdgeInsets.symmetric(horizontal: PeelSpace.x24),
      content: [
        PeelStageHeader(title: title),
        PeelRiveSlot(
          stage: filed != null ? PeelStage.complete : PeelStage.research,
        ),
        const SizedBox(height: PeelSpace.x16),
        if (filed != null)
          Text(
            'Report ${filed.reportId}',
            style: PeelText.body,
          )
        else if (_error != null)
          Text(
            _error!,
            style: PeelText.body.copyWith(color: PeelColors.error),
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
          )
        else
          const Text(
            'Saving your report.',
            style: PeelText.body,
          ),
      ],
      actions: [
        if (filed != null)
          PeelButton(
            label: 'Back to results',
            onPressed: () => Navigator.of(context).popUntil(
              (route) => route.settings.name == 'results' || route.isFirst,
            ),
          ),
        if (_error != null)
          PeelButton(label: 'Retry', onPressed: _submit),
      ],
    );
  }
}
