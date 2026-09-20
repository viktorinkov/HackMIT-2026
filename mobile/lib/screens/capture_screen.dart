import 'package:flutter/material.dart';

import '../services/photo_service.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import '../widgets/photo_slot.dart';
import '../widgets/scan_steps.dart';
import 'device_screen.dart';

class CaptureCopy {
  const CaptureCopy({
    required this.title,
    required this.instruction,
    required this.placeholder,
    required this.action,
  });

  final String title;
  final String instruction;
  final String placeholder;
  final String action;
}

const _copy = {
  ScanStep.bottle: CaptureCopy(
    title: 'Scan bottle',
    instruction: 'Hold the bottle label flat and take a photo of it.',
    placeholder: 'Bottle comes to screen and the phone takes a picture of it',
    action: 'Scan bottle',
  ),
  ScanStep.imprint: CaptureCopy(
    title: 'Scan imprint',
    instruction: 'Place the pill so the letters and numbers face the camera.',
    placeholder: 'Pill turns until the imprint faces the camera',
    action: 'Scan imprint',
  ),
  ScanStep.pill: CaptureCopy(
    title: 'Scan pill',
    instruction: 'Take one more photo of the whole pill.',
    placeholder: 'Pill rests on the tray while the phone takes a picture',
    action: 'Scan pill',
  ),
};

class CaptureScreen extends StatefulWidget {
  const CaptureScreen({super.key, required this.step});

  final ScanStep step;

  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen> {
  CaptureCopy get copy => _copy[widget.step]!;

  Future<void> _pick() async {
    final file = await choosePhoto(context, title: copy.title);
    if (file == null) return;
    scanSession.setPhoto(widget.step, file);
    setState(() {});
  }

  void _continue() {
    final Widget next = switch (widget.step) {
      ScanStep.bottle => const CaptureScreen(step: ScanStep.imprint),
      ScanStep.imprint => const CaptureScreen(step: ScanStep.pill),
      ScanStep.pill => const DeviceScreen(),
    };
    Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => next),
    );
  }

  @override
  Widget build(BuildContext context) {
    final photo = scanSession.photoFor(widget.step);
    return PeelScaffold(
      content: [
        Text(copy.title, style: PeelText.brand),
        const SizedBox(height: PeelSpace.x8),
        Text(copy.instruction, style: PeelText.body),
        const SizedBox(height: PeelSpace.x24),
        PhotoSlot(
          photo: photo,
          description: copy.placeholder,
          onAdd: _pick,
          onReplace: _pick,
          onRemove: () {
            scanSession.setPhoto(widget.step, null);
            setState(() {});
          },
        ),
        const SizedBox(height: PeelSpace.x16),
        ScanSteps(current: widget.step),
      ],
      actions: [
        PeelButton(
          label: photo == null ? copy.action : 'Continue',
          onPressed: photo == null ? _pick : _continue,
        ),
        if (Navigator.of(context).canPop())
          PeelButton(
            label: 'Back',
            variant: PeelButtonVariant.secondary,
            onPressed: () => Navigator.of(context).pop(),
          ),
      ],
    );
  }
}
