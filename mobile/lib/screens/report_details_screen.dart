import 'dart:io';

import 'package:flutter/material.dart';

import '../data/api_models.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/field_card.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import 'sending_report_screen.dart';

class ReportDetailsScreen extends StatefulWidget {
  const ReportDetailsScreen({super.key});

  @override
  State<ReportDetailsScreen> createState() => _ReportDetailsScreenState();
}

class _ReportDetailsScreenState extends State<ReportDetailsScreen> {
  late DateTime? _purchasedOn = _parseDate(scanSession.reportDraft.purchasedOn);
  late final _label = TextEditingController(
    text: scanSession.reportDraft.purchaseLocation?.label ?? '',
  );
  late final _city = TextEditingController(
    text: scanSession.reportDraft.purchaseLocation?.city ?? '',
  );
  late final _region = TextEditingController(
    text: scanSession.reportDraft.purchaseLocation?.region ?? '',
  );
  late final _country = TextEditingController(
    text: scanSession.reportDraft.purchaseLocation?.country ?? '',
  );
  late final _seller = TextEditingController(
    text: scanSession.reportDraft.seller ?? '',
  );

  @override
  void dispose() {
    _label.dispose();
    _city.dispose();
    _region.dispose();
    _country.dispose();
    _seller.dispose();
    super.dispose();
  }

  DateTime? _parseDate(String? raw) {
    if (raw == null || raw.isEmpty) return null;
    return DateTime.tryParse(raw);
  }

  String? _dateString() {
    final date = _purchasedOn;
    if (date == null) return null;
    final y = date.year.toString().padLeft(4, '0');
    final m = date.month.toString().padLeft(2, '0');
    final d = date.day.toString().padLeft(2, '0');
    return '$y-$m-$d';
  }

  ReportDraft _draft() {
    final location = PurchaseLocation(
      label: _label.text.trim().isEmpty ? null : _label.text.trim(),
      city: _city.text.trim().isEmpty ? null : _city.text.trim(),
      region: _region.text.trim().isEmpty ? null : _region.text.trim(),
      country: _country.text.trim().isEmpty ? null : _country.text.trim(),
    );
    return ReportDraft(
      purchasedOn: _dateString(),
      purchaseLocation: location.isEmpty ? null : location,
      seller: _seller.text.trim().isEmpty ? null : _seller.text.trim(),
    );
  }

  Future<void> _pickDate() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _purchasedOn ?? now,
      firstDate: DateTime(now.year - 10),
      lastDate: now,
    );
    if (picked == null || !mounted) return;
    setState(() => _purchasedOn = picked);
  }

  void _submit() {
    scanSession.applyDraft(_draft());
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => const SendingReportScreen(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final scan = scanSession.scan;
    final research = scan?.research;
    return PeelScaffold(
      topBar: PeelTopBar(
        title: 'Report',
        onBack: () => Navigator.of(context).pop(),
      ),
      content: [
        const _Section(title: 'Purchase'),
        GestureDetector(
          onTap: _pickDate,
          child: PeelFieldCard(
            label: 'Purchased on',
            value: _dateString() ?? 'Choose a date',
          ),
        ),
        const SizedBox(height: PeelSpace.x8),
        _Field(label: 'Place', controller: _label),
        const SizedBox(height: PeelSpace.x8),
        _Field(label: 'City', controller: _city),
        const SizedBox(height: PeelSpace.x8),
        _Field(label: 'Region', controller: _region),
        const SizedBox(height: PeelSpace.x8),
        _Field(label: 'Country', controller: _country),
        const SizedBox(height: PeelSpace.x8),
        _Field(label: 'Seller', controller: _seller),
        const _Section(title: 'Scan'),
        PeelFieldCard(
          label: 'Bottle',
          value: _mapLine(scan?.bottle, ['generic_name', 'brand_name']),
        ),
        const SizedBox(height: PeelSpace.x8),
        PeelFieldCard(
          label: 'Imprint',
          value: scan?.imprint?['imprint'] as String? ?? 'Not read',
        ),
        const SizedBox(height: PeelSpace.x8),
        PeelFieldCard(
          label: 'Pill',
          value: scan?.hardware?['status'] as String? ?? 'unknown',
        ),
        if (research != null) ...[
          const SizedBox(height: PeelSpace.x8),
          PeelFieldCard(label: 'Finding', value: research.headline),
        ],
        // Photo thumbnails stay in the file, commented out until we show them.
        // const _Section(title: 'Scan evidence'),
        // const Text('Attached scan photos', style: PeelText.caption),
        // const SizedBox(height: PeelSpace.x8),
        // const _EvidenceRow(),
      ],
      actions: [
        PeelButton(label: 'Submit', onPressed: _submit),
        PeelButton(
          label: 'Back',
          variant: PeelButtonVariant.secondary,
          onPressed: () => Navigator.of(context).pop(),
        ),
      ],
    );
  }

  String _mapLine(Map<String, dynamic>? map, List<String> keys) {
    if (map == null) return 'No observation';
    for (final key in keys) {
      final value = map[key];
      if (value is String && value.isNotEmpty) return value;
    }
    return 'Not read';
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

class _Field extends StatelessWidget {
  const _Field({required this.label, required this.controller});

  final String label;
  final TextEditingController controller;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      style: PeelText.body,
      decoration: InputDecoration(
        labelText: label,
        labelStyle: PeelText.caption,
        filled: true,
        fillColor: PeelColors.surface,
        border: OutlineInputBorder(
          borderRadius: PeelRadii.r12,
          borderSide: const BorderSide(color: PeelColors.line),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: PeelRadii.r12,
          borderSide: const BorderSide(color: PeelColors.line),
        ),
      ),
    );
  }
}

// ignore: unused_element
class _EvidenceRow extends StatelessWidget {
  const _EvidenceRow();

  @override
  Widget build(BuildContext context) {
    const steps = [
      (ScanStep.bottle, 'Bottle'),
      (ScanStep.imprint, 'Imprint'),
    ];
    return Row(
      children: [
        for (var i = 0; i < steps.length; i++) ...[
          if (i > 0) const SizedBox(width: PeelSpace.x8),
          Expanded(
            child: _Thumb(
              label: steps[i].$2,
              photo: scanSession.photoFor(steps[i].$1),
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
