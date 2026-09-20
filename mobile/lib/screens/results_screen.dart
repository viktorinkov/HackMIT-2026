import 'dart:io';

import 'package:flutter/material.dart';

import '../data/mock_data.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import 'chat_screen.dart';
import 'report_details_screen.dart';

class ResultsScreen extends StatefulWidget {
  const ResultsScreen({super.key});

  @override
  State<ResultsScreen> createState() => _ResultsScreenState();
}

class _ResultsScreenState extends State<ResultsScreen> {
  @override
  Widget build(BuildContext context) {
    final result = scanSession.result;
    final tone = _toneFor(result.verdict);

    return PeelScaffold(
      topBar: PeelTopBar(
        title: 'Results',
        trailing: IconButton(
          tooltip: 'Start over',
          onPressed: () {
            scanSession.reset();
            Navigator.of(context).popUntil((route) => route.isFirst);
          },
          icon: const Icon(Icons.home_outlined, color: PeelColors.ink),
        ),
      ),
      content: [
        GestureDetector(
          onTap: () => setState(scanSession.cycleResult),
          child: Container(
            padding: const EdgeInsets.all(PeelSpace.x16),
            decoration: BoxDecoration(
              color: tone.background,
              borderRadius: PeelRadii.r16,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  result.finding,
                  style: PeelText.heading.copyWith(color: tone.foreground),
                ),
                const SizedBox(height: PeelSpace.x4),
                Text(result.findingDetail, style: PeelText.body),
              ],
            ),
          ),
        ),
        const SizedBox(height: PeelSpace.x16),
        Text(result.medicine, style: PeelText.title),
        const SizedBox(height: PeelSpace.x16),
        const _EvidenceStrip(),
        const SizedBox(height: PeelSpace.x16),
        _Card(
          title: 'What we saw',
          child: Column(
            children: [
              for (final row in result.rows) _RecognitionTile(row: row),
            ],
          ),
        ),
        const SizedBox(height: PeelSpace.x12),
        _Card(
          title: 'Drug facts',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final fact in result.facts) _Bullet(text: fact),
            ],
          ),
        ),
        const SizedBox(height: PeelSpace.x12),
        _Card(
          title: 'Side effects',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final effect in result.sideEffects) _Bullet(text: effect),
            ],
          ),
        ),
      ],
      actions: [
        PeelButton(
          label: 'Chat about this',
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute<void>(builder: (_) => const ChatScreen()),
          ),
        ),
        if (result.canReport)
          PeelButton(
            label: 'Report a problem',
            variant: PeelButtonVariant.secondary,
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => const ReportDetailsScreen(),
              ),
            ),
          ),
      ],
    );
  }
}

({Color background, Color foreground}) _toneFor(ScanVerdict verdict) {
  return switch (verdict) {
    ScanVerdict.match => (
        background: PeelColors.successSoft,
        foreground: PeelColors.success
      ),
    ScanVerdict.mismatch => (
        background: PeelColors.errorSoft,
        foreground: PeelColors.error
      ),
    ScanVerdict.unconfirmed => (
        background: PeelColors.soft,
        foreground: PeelColors.deep
      ),
    ScanVerdict.degradation => (
        background: PeelColors.tealSoft,
        foreground: PeelColors.teal
      ),
  };
}

class _EvidenceStrip extends StatelessWidget {
  const _EvidenceStrip();

  @override
  Widget build(BuildContext context) {
    const labels = ['Bottle', 'Imprint', 'Pill'];
    return Row(
      children: [
        for (var i = 0; i < ScanStep.values.length; i++) ...[
          if (i > 0) const SizedBox(width: PeelSpace.x8),
          Expanded(
            child: _EvidenceThumb(
              label: labels[i],
              photo: scanSession.photoFor(ScanStep.values[i]),
            ),
          ),
        ],
      ],
    );
  }
}

class _EvidenceThumb extends StatelessWidget {
  const _EvidenceThumb({required this.label, required this.photo});

  final String label;
  final File? photo;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        AspectRatio(
          aspectRatio: 1,
          child: ClipRRect(
            borderRadius: PeelRadii.r12,
            child: Container(
              color: photo == null ? PeelColors.soft : PeelColors.camera,
              alignment: Alignment.center,
              child: photo == null
                  ? const Icon(Icons.image_outlined, color: PeelColors.muted)
                  : Image.file(photo!, fit: BoxFit.cover),
            ),
          ),
        ),
        const SizedBox(height: PeelSpace.x4),
        Text(label, style: PeelText.caption),
      ],
    );
  }
}

class _Card extends StatelessWidget {
  const _Card({required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(PeelSpace.x16),
      decoration: BoxDecoration(
        color: PeelColors.surface,
        borderRadius: PeelRadii.r16,
        border: Border.all(color: PeelColors.line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: PeelText.label),
          const SizedBox(height: PeelSpace.x8),
          child,
        ],
      ),
    );
  }
}

class _RecognitionTile extends StatelessWidget {
  const _RecognitionTile({required this.row});

  final RecognitionRow row;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: PeelSpace.x8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 76,
            child: Text(row.label, style: PeelText.caption),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(row.value, style: PeelText.body),
                if (row.detail != null)
                  Text(row.detail!, style: PeelText.caption),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Bullet extends StatelessWidget {
  const _Bullet({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: PeelSpace.x4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('·  ', style: PeelText.body),
          Expanded(child: Text(text, style: PeelText.body)),
        ],
      ),
    );
  }
}
