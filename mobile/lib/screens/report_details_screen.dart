import 'dart:io';

import 'package:flutter/material.dart';

import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/field_card.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import 'edit_report_screen.dart';
import 'sending_report_screen.dart';

class ReportDetailsScreen extends StatefulWidget {
  const ReportDetailsScreen({super.key});

  @override
  State<ReportDetailsScreen> createState() => _ReportDetailsScreenState();
}

class _ReportDetailsScreenState extends State<ReportDetailsScreen> {
  Future<void> _edit() async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => const EditReportScreen()),
    );
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    return PeelScaffold(
      topBar: PeelTopBar(
        title: 'Report',
        trailing: TextButton(
          onPressed: _edit,
          child: Text(
            'Edit',
            style: PeelText.label.copyWith(color: PeelColors.deep),
          ),
        ),
      ),
      content: [
        const _Section(title: 'Concern'),
        Text(scanSession.concern, style: PeelText.body),
        const SizedBox(height: PeelSpace.x8),
        PeelFieldCard(label: 'Date noticed', value: scanSession.dateNoticed),
        const _Section(title: 'Medicine'),
        PeelFieldCard(label: 'Medicine name', value: scanSession.medicineName),
        const SizedBox(height: PeelSpace.x8),
        PeelFieldCard(label: 'Strength', value: scanSession.strength),
        const SizedBox(height: PeelSpace.x8),
        PeelFieldCard(label: 'Manufacturer', value: scanSession.manufacturer),
        const _Section(title: 'Bottle details'),
        PeelFieldCard(label: 'Lot number', value: scanSession.lotNumber),
        const SizedBox(height: PeelSpace.x8),
        PeelFieldCard(label: 'Expiry date', value: scanSession.expiryDate),
        const _Section(title: 'Scan evidence'),
        const Text('Attached scan photos', style: PeelText.caption),
        const SizedBox(height: PeelSpace.x8),
        const _EvidenceRow(),
      ],
      actions: [
        PeelButton(
          label: 'Submit report',
          onPressed: () => Navigator.of(context).push(
            MaterialPageRoute<void>(
              builder: (_) => const SendingReportScreen(),
            ),
          ),
        ),
        PeelButton(
          label: 'Back',
          variant: PeelButtonVariant.secondary,
          onPressed: () => Navigator.of(context).pop(),
        ),
      ],
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(
        top: PeelSpace.x16,
        bottom: PeelSpace.x8,
      ),
      child: Text(title, style: PeelText.heading),
    );
  }
}

class _EvidenceRow extends StatelessWidget {
  const _EvidenceRow();

  @override
  Widget build(BuildContext context) {
    const labels = ['Bottle', 'Imprint', 'Pill'];
    return Row(
      children: [
        for (var i = 0; i < ScanStep.values.length; i++) ...[
          if (i > 0) const SizedBox(width: PeelSpace.x8),
          Expanded(
            child: _Thumb(
              label: labels[i],
              photo: scanSession.photoFor(ScanStep.values[i]),
            ),
          ),
        ],
      ],
    );
  }
}

class _Thumb extends StatelessWidget {
  const _Thumb({required this.label, required this.photo});

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
