import 'dart:io';

import 'package:flutter/material.dart';

import '../state/scan_session.dart';
import '../rive/peel_rive_stage.dart';
import '../theme/peel_theme.dart';
import '../widgets/field_card.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import 'report_details_screen.dart';
import 'voice_screen.dart';

class ResultsScreen extends StatefulWidget {
  const ResultsScreen({super.key});

  @override
  State<ResultsScreen> createState() => _ResultsScreenState();
}

class _ResultsScreenState extends State<ResultsScreen> {
  @override
  void initState() {
    super.initState();
    peelRiveStage.show(PeelStage.clear);
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: scanSession,
      builder: (context, _) {
        final scan = scanSession.scan;
        final research = scan?.research;
        if (scan == null || research == null) {
          return PeelScaffold(
            topBar: const PeelTopBar(title: 'Results'),
            content: [Text('No research result yet.', style: PeelText.body)],
            actions: [
              PeelButton(
                label: 'Start over',
                onPressed: () {
                  scanSession.reset();
                  Navigator.of(context).popUntil((route) => route.isFirst);
                },
              ),
            ],
          );
        }
        final tone = _toneFor(research.verdict, research.riskLevel);
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
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(PeelSpace.x16),
              decoration: BoxDecoration(
                color: tone.background,
                borderRadius: PeelRadii.r16,
              ),
              child: Text(
                research.headline,
                style: PeelText.label.copyWith(color: tone.foreground),
              ),
            ),
            const SizedBox(height: PeelSpace.x12),
            PeelFieldCard(label: 'Bottle', value: _bottleLine(scan.bottle)),
            const SizedBox(height: PeelSpace.x8),
            PeelFieldCard(label: 'Imprint', value: _imprintLine(scan.imprint)),
            const SizedBox(height: PeelSpace.x8),
            PeelFieldCard(label: 'Pill', value: _hardwareLine(scan.hardware)),
            // Photo thumbnails stay in the file, commented out until we show them.
            // if (scanSession.bottlePhoto != null) ...[
            //   const SizedBox(height: PeelSpace.x8),
            //   _EvidencePhoto(photo: scanSession.bottlePhoto!),
            // ],
            // if (scanSession.imprintPhoto != null) ...[
            //   const SizedBox(height: PeelSpace.x8),
            //   _EvidencePhoto(photo: scanSession.imprintPhoto!),
            // ],
            if (research.findings.isNotEmpty) ...[
              const SizedBox(height: PeelSpace.x12),
              _Card(
                title: 'Findings',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final finding in research.findings)
                      _Bullet(text: finding.statement),
                  ],
                ),
              ),
            ],
            if (research.mismatches.isNotEmpty) ...[
              const SizedBox(height: PeelSpace.x12),
              _Card(
                title: 'Mismatches',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final mismatch in research.mismatches)
                      _Bullet(text: mismatch.explanation),
                  ],
                ),
              ),
            ],
            if (research.recallHits.isNotEmpty) ...[
              const SizedBox(height: PeelSpace.x12),
              _Card(
                title: 'Recall hits',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final hit in research.recallHits)
                      _Bullet(text: hit.title),
                  ],
                ),
              ),
            ],
            if (research.drugFacts.isNotEmpty) ...[
              const SizedBox(height: PeelSpace.x12),
              _Card(
                title: 'Drug facts',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final fact in research.drugFacts)
                      _Bullet(text: fact.text),
                  ],
                ),
              ),
            ],
            if (research.nextSteps.isNotEmpty) ...[
              const SizedBox(height: PeelSpace.x12),
              _Card(
                title: 'Next steps',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final step in research.nextSteps) _Bullet(text: step),
                  ],
                ),
              ),
            ],
            if (research.gaps.isNotEmpty) ...[
              const SizedBox(height: PeelSpace.x12),
              _Card(
                title: 'Gaps',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final gap in research.gaps) _Bullet(text: gap),
                  ],
                ),
              ),
            ],
            if (research.sources.isNotEmpty) ...[
              const SizedBox(height: PeelSpace.x12),
              _Card(
                title: 'Sources',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final source in research.sources)
                      _Bullet(
                        text: source.sourceOrg == null
                            ? source.title
                            : '${source.title} · ${source.sourceOrg}',
                      ),
                  ],
                ),
              ),
            ],
          ],
          actions: [
            PeelButton(
              label: 'Talk to Peel',
              onPressed: scan.status == 'complete'
                  ? () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => const VoiceScreen(),
                      ),
                    )
                  : null,
            ),
            if (research.canReport)
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
      },
    );
  }
}

({Color background, Color foreground}) _toneFor(
  String verdict,
  String riskLevel,
) {
  if (verdict == 'mismatch_found' || verdict == 'recall_match') {
    return (background: PeelColors.errorSoft, foreground: PeelColors.error);
  }
  if (riskLevel == 'high') {
    return (background: PeelColors.errorSoft, foreground: PeelColors.error);
  }
  if (verdict == 'insufficient_evidence') {
    return (background: PeelColors.soft, foreground: PeelColors.deep);
  }
  return (background: PeelColors.tealSoft, foreground: PeelColors.teal);
}

String _bottleLine(Map<String, dynamic>? bottle) {
  if (bottle == null) return 'No bottle observation';
  final name =
      (bottle['generic_name'] as String?) ?? (bottle['brand_name'] as String?);
  final strength = bottle['strength'] as String?;
  if (name == null) return 'Bottle not read';
  if (strength == null || strength.isEmpty) return name;
  return '$name · $strength';
}

String _imprintLine(Map<String, dynamic>? imprint) {
  if (imprint == null) return 'No imprint observation';
  final mark = imprint['imprint'] as String?;
  if (mark == null || mark.isEmpty) return 'Imprint not read';
  final color = imprint['color'] as String?;
  final shape = imprint['shape'] as String?;
  final extras = [color, shape].whereType<String>().where((s) => s.isNotEmpty);
  if (extras.isEmpty) return mark;
  return '$mark · ${extras.join(' · ')}';
}

String _hardwareLine(Map<String, dynamic>? hardware) {
  if (hardware == null) return 'No hardware observation';
  final status = hardware['status'] as String? ?? 'unknown';
  final pillType = hardware['pill_type'] as String?;
  if (status != 'unknown' && pillType != null && pillType.isNotEmpty) {
    return 'Hardware: $status · $pillType';
  }
  final count = hardware['sensor_sample_count'] as int?;
  if (count != null && count > 0) return '$count sensor readings recorded';
  final trace = hardware['spectrum'] as List? ?? const [];
  if (trace.isNotEmpty &&
      hardware['model'] != 'mock-spectrometry' &&
      hardware['model'] != 'truepill-snapshot') {
    return '${trace.length} absorbance readings recorded';
  }
  return 'Hardware: $status';
}

/// Full-width scan photo, framed the way the prototype frames its captures.
// ignore: unused_element
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
