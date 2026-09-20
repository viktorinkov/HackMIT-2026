import 'package:flutter/material.dart';

import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';

class EditReportScreen extends StatefulWidget {
  const EditReportScreen({super.key});

  @override
  State<EditReportScreen> createState() => _EditReportScreenState();
}

class _EditReportScreenState extends State<EditReportScreen> {
  late final _concern = TextEditingController(text: scanSession.concern);
  late final _date = TextEditingController(text: scanSession.dateNoticed);
  late final _medicine = TextEditingController(text: scanSession.medicineName);
  late final _strength = TextEditingController(text: scanSession.strength);
  late final _manufacturer =
      TextEditingController(text: scanSession.manufacturer);
  late final _lot = TextEditingController(text: scanSession.lotNumber);
  late final _expiry = TextEditingController(text: scanSession.expiryDate);

  @override
  void dispose() {
    for (final controller in [
      _concern,
      _date,
      _medicine,
      _strength,
      _manufacturer,
      _lot,
      _expiry,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  void _save() {
    scanSession.updateReport(
      concern: _concern.text,
      dateNoticed: _date.text,
      medicineName: _medicine.text,
      strength: _strength.text,
      manufacturer: _manufacturer.text,
      lotNumber: _lot.text,
      expiryDate: _expiry.text,
    );
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    return PeelScaffold(
      topBar: PeelTopBar(
        title: 'Edit report',
        onBack: () => Navigator.of(context).pop(),
      ),
      content: [
        _Field(label: 'Concern', controller: _concern, maxLines: 3),
        _Field(label: 'Date noticed', controller: _date),
        _Field(label: 'Medicine name', controller: _medicine),
        _Field(label: 'Strength', controller: _strength),
        _Field(label: 'Manufacturer', controller: _manufacturer),
        _Field(label: 'Lot number', controller: _lot),
        _Field(label: 'Expiry date', controller: _expiry),
      ],
      actions: [
        PeelButton(label: 'Done', onPressed: _save),
        PeelButton(
          label: 'Cancel',
          variant: PeelButtonVariant.text,
          onPressed: () => Navigator.of(context).pop(),
        ),
      ],
    );
  }
}

class _Field extends StatelessWidget {
  const _Field({
    required this.label,
    required this.controller,
    this.maxLines = 1,
  });

  final String label;
  final TextEditingController controller;
  final int maxLines;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: PeelSpace.x16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: PeelText.caption),
          const SizedBox(height: PeelSpace.x4),
          TextField(
            controller: controller,
            maxLines: maxLines,
            style: PeelText.body,
            decoration: const InputDecoration(
              filled: true,
              fillColor: PeelColors.surface,
              contentPadding: EdgeInsets.all(PeelSpace.x12),
              border: OutlineInputBorder(
                borderRadius: PeelRadii.r12,
                borderSide: BorderSide(color: PeelColors.line),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: PeelRadii.r12,
                borderSide: BorderSide(color: PeelColors.line),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: PeelRadii.r12,
                borderSide: BorderSide(color: PeelColors.orange),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
