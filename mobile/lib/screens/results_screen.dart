import 'dart:io';

import 'package:flutter/material.dart';

import '../data/mock_data.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/field_card.dart';
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
            child: Text(
              result.finding,
              style: PeelText.label.copyWith(color: tone.foreground),
            ),
          ),
        ),
        const SizedBox(height: PeelSpace.x12),
        for (var i = 0; i < result.rows.length; i++) ...[
          if (scanSession.photoFor(ScanStep.values[i]) != null) ...[
            _EvidencePhoto(photo: scanSession.photoFor(ScanStep.values[i])!),
            const SizedBox(height: PeelSpace.x8),
          ],
          PeelFieldCard(
            label: result.rows[i].label,
            value: result.rows[i].value,
            detail: result.rows[i].detail,
          ),
          const SizedBox(height: PeelSpace.x8),
        ],
        const SizedBox(height: PeelSpace.x4),
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
          label: 'Chat about results',
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute<void>(builder: (_) => const ChatScreen()),
          ),
        ),
        if (result.canReport)
          PeelButton(
            label: 'Report a concern',
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
        background: PeelColors.soft,
        foreground: PeelColors.deep
      ),
  };
}

/// Full-width scan photo, framed the way the prototype frames its captures.
class _EvidencePhoto extends StatelessWidget {
  const _EvidencePhoto({required this.photo});

  final File photo;

  @override
  Widget build(BuildContext context) {
    return AspectRatio(
      aspectRatio: 16 / 9,
      child: ClipRRect(
        borderRadius: PeelRadii.r12,
        child: Container(
          color: PeelColors.camera,
          child: Image.file(photo, fit: BoxFit.cover),
        ),
      ),
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
