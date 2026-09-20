import 'package:flutter/material.dart';
import 'package:rive/rive.dart' as rive;

/// Stages of the single `peel_scan_flow.riv` state machine, as documented in
/// the animation handoff.
enum PeelStage {
  bottleScan(0),
  pillScan(1),
  deviceConnect(2),
  pillSubmerged(3),
  checking(4),
  complete(5),
  research(6),
  clear(7);

  const PeelStage(this.value);

  final double value;
}

/// One artboard for the whole flow: the controller lives above the navigator
/// and only the slot it is drawn into changes, so the state machine keeps
/// running across screens instead of restarting per route.
class PeelRiveStage extends ChangeNotifier {
  static const artboard = 'PeelScan';
  static const stateMachine = 'State Machine 1';
  static const viewModel = 'ViewModel2';
  static const instance = 'Instance';
  static const asset = 'assets/rive/peel_scan_flow.riv';
  static const aspectRatio = 364 / 416;

  /// Identifies the stack the artboard is positioned in, so slots can report
  /// their rect in that stack's coordinates rather than global ones.
  final hostKey = GlobalKey();

  final List<PeelRiveSlotHandle> _slots = [];

  rive.File? _file;
  rive.RiveWidgetController? _controller;
  rive.ViewModelInstanceNumber? _stage;
  Object? _error;

  rive.RiveWidgetController? get controller => _controller;
  bool get failed => _error != null;

  /// The rect of the slot that should currently hold the artboard, in global
  /// coordinates. Screens lower in the navigator stack keep their slots
  /// registered, so the most recent one wins.
  Rect? get rect {
    for (final slot in _slots.reversed) {
      if (slot.rect != null) return slot.rect;
    }
    return null;
  }

  Future<void> load() async {
    if (_file != null || _error != null) return;
    try {
      await rive.RiveNative.init();
      final file = await rive.File.asset(asset, riveFactory: rive.Factory.rive);
      if (file == null) throw StateError('Could not decode $asset');
      final controller = _controllerFor(file);
      final vmi = _bind(controller);
      _file = file;
      _controller = controller;
      _stage = vmi.number('stage');
      debugPrint('Rive stage ready: artboard=${controller.artboard.name} '
          'machine=${controller.stateMachine.name} instance=${vmi.name} '
          'properties=${vmi.properties.map((p) => p.name).toList()}');
    } catch (error) {
      _error = error;
      debugPrint('Rive stage unavailable: $error');
    }
    notifyListeners();
  }

  /// Falls back to the file's defaults when an export does not carry the
  /// documented artboard and state machine names.
  rive.RiveWidgetController _controllerFor(rive.File file) {
    try {
      return rive.RiveWidgetController(
        file,
        artboardSelector: const rive.ArtboardNamed(artboard),
        stateMachineSelector: const rive.StateMachineNamed(stateMachine),
      );
    } catch (error) {
      debugPrint('Rive stage falling back to defaults: $error');
      return rive.RiveWidgetController(file);
    }
  }

  rive.ViewModelInstance _bind(rive.RiveWidgetController controller) {
    try {
      return controller.dataBind(const rive.BindByName(instance));
    } catch (error) {
      debugPrint('Rive stage falling back to the default instance: $error');
      return controller.dataBind(const rive.AutoBind());
    }
  }

  void show(PeelStage stage) {
    _stage?.value = stage.value;
  }

  PeelRiveSlotHandle register() {
    final handle = PeelRiveSlotHandle._(this);
    _slots.add(handle);
    return handle;
  }

  void _unregister(PeelRiveSlotHandle handle) {
    _slots.remove(handle);
    notifyListeners();
  }

  void _moved() => notifyListeners();

  @override
  void dispose() {
    _controller?.dispose();
    _file?.dispose();
    super.dispose();
  }
}

/// A slot's claim on the shared artboard. Kept while the screen is mounted so
/// the stage can fall back to the screen underneath when a route pops.
class PeelRiveSlotHandle {
  PeelRiveSlotHandle._(this._stage);

  final PeelRiveStage _stage;
  Rect? rect;

  void moveTo(Rect value) {
    if (rect == value) return;
    rect = value;
    _stage._moved();
  }

  void release() => _stage._unregister(this);
}

/// The demo runs against one stage instance.
final peelRiveStage = PeelRiveStage();
