import 'package:flutter/material.dart';

import '../rive/peel_rive_stage.dart';
import '../rive/peel_rive_widgets.dart';
import '../services/photo_service.dart';
import '../state/scan_session.dart';
import '../theme/peel_theme.dart';
import '../widgets/peel_button.dart';
import '../widgets/peel_scaffold.dart';
import '../widgets/scan_steps.dart';
import 'device_screen.dart';
import 'photo_screen.dart';

class CaptureCopy {
  const CaptureCopy({required this.title, required this.action});

  final String title;
  final String action;
}

const _copy = {
  ScanStep.bottle: CaptureCopy(title: 'Scan bottle', action: 'Scan bottle'),
  ScanStep.imprint: CaptureCopy(title: 'Scan imprint', action: 'Scan imprint'),
  ScanStep.pill: CaptureCopy(title: 'Scan pill', action: 'Scan pill'),
};

class CaptureScreen extends StatefulWidget {
  const CaptureScreen({super.key, required this.step});

  final ScanStep step;

  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen> {
  CaptureCopy get copy => _copy[widget.step]!;

  PeelStage get stage => switch (widget.step) {
        ScanStep.bottle => PeelStage.bottleScan,
        ScanStep.imprint => PeelStage.pillScan,
        ScanStep.pill => PeelStage.pillScan,
      };

  /// Source sheet first, then the full-screen preview of what was taken.
  Future<void> _pick() async {
    final file = await choosePhoto(context, title: copy.title);
    if (file == null || !mounted) return;
    scanSession.setPhoto(widget.step, file);
    setState(() {});
    await _review();
  }

  Future<void> _review() async {
    final photo = scanSession.photoFor(widget.step);
    if (photo == null) return;
    final choice = await PhotoScreen.open(
      context,
      title: copy.title,
      photo: photo,
      onReplaced: (file) => scanSession.setPhoto(widget.step, file),
    );
    if (!mounted) return;
    // Closing with the X leaves the photo as it is.
    if (choice != null) scanSession.setPhoto(widget.step, choice.file);
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
      fill: true,
      padding: const EdgeInsets.symmetric(horizontal: PeelSpace.x24),
      content: [
        PeelStageHeader(
          title: copy.title,
          trailing: photo == null
              ? null
              : TextButton(
                  onPressed: _review,
                  child: Text(
                    'View photo',
                    style: PeelText.label.copyWith(color: PeelColors.deep),
                  ),
                ),
        ),
        PeelRiveSlot(stage: stage),
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
