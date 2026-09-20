import 'package:flutter/material.dart';

import '../rive/peel_rive_stage.dart';
import '../services/photo_service.dart';
import '../state/scan_session.dart';
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
};

/// Bottle / imprint as a horizontal [PageView] of titles only. One shared
/// [PeelRiveSlot] sits outside the pager so its global rect stays fixed.
class CaptureScreen extends StatefulWidget {
  const CaptureScreen({super.key, this.initialStep = ScanStep.bottle})
      : assert(
          initialStep == ScanStep.bottle || initialStep == ScanStep.imprint,
          'CaptureScreen only handles bottle and imprint photos',
        );

  final ScanStep initialStep;

  static const _photoSteps = [ScanStep.bottle, ScanStep.imprint];

  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen> {
  static const _pageDuration = Duration(milliseconds: 320);

  late final PageController _pages = PageController(
    initialPage: CaptureScreen._photoSteps.indexOf(widget.initialStep),
  );
  late ScanStep _step = widget.initialStep;

  CaptureCopy get copy => _copy[_step]!;

  PeelStage _stageFor(ScanStep step) => switch (step) {
        ScanStep.bottle => PeelStage.bottleScan,
        ScanStep.imprint => PeelStage.pillScan,
        ScanStep.pill => PeelStage.pillScan,
      };

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  void _onPageChanged(int index) {
    setState(() => _step = CaptureScreen._photoSteps[index]);
  }

  Future<void> _pick() async {
    final file = await choosePhoto(context, title: copy.title);
    if (file == null || !mounted) return;
    scanSession.setPhoto(_step, file);
    setState(() {});
    await _review();
  }

  Future<void> _review() async {
    final photo = scanSession.photoFor(_step);
    if (photo == null) return;
    final choice = await PhotoScreen.open(
      context,
      title: copy.title,
      photo: photo,
      step: _step,
      onReplaced: (file) => scanSession.setPhoto(_step, file),
    );
    if (!mounted) return;
    if (choice != null) scanSession.setPhoto(_step, choice.file);
    setState(() {});
  }

  Future<void> _continue() async {
    final index = CaptureScreen._photoSteps.indexOf(_step);
    if (index < CaptureScreen._photoSteps.length - 1) {
      await _pages.nextPage(
        duration: _pageDuration,
        curve: Curves.easeInOutCubic,
      );
      return;
    }
    if (!mounted) return;
    Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => const DeviceScreen()),
    );
  }

  Future<void> _back() async {
    final index = CaptureScreen._photoSteps.indexOf(_step);
    if (index > 0) {
      await _pages.previousPage(
        duration: _pageDuration,
        curve: Curves.easeInOutCubic,
      );
      return;
    }
    if (!mounted) return;
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: scanSession,
      builder: (context, _) {
        final photo = scanSession.photoFor(_step);
        final ready = scanSession.hasVision(_step);
        return PeelStageScaffold(
          header: SizedBox(
            height: PeelStageHeader.height,
            child: PageView.builder(
              controller: _pages,
              itemCount: CaptureScreen._photoSteps.length,
              onPageChanged: _onPageChanged,
              itemBuilder: (context, index) {
                final step = CaptureScreen._photoSteps[index];
                return PeelStageHeader(title: _copy[step]!.title);
              },
            ),
          ),
          stage: _stageFor(_step),
          bottom: ScanSteps(current: _step),
          primaryAction: PeelButton(
            key: ValueKey('primary-$_step-${photo == null}-$ready'),
            label: !ready
                ? (photo == null ? copy.action : 'Use this photo')
                : 'Continue',
            onPressed: !ready
                ? (photo == null ? _pick : _review)
                : _continue,
          ),
          secondaryAction: PeelButton(
            label: 'Back',
            variant: PeelButtonVariant.secondary,
            onPressed: _back,
          ),
        );
      },
    );
  }
}
