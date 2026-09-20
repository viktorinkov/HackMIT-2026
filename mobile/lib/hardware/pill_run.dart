import 'dart:async';

import '../data/api_models.dart';
import 'faults.dart';
import 'instrument_session.dart';
import 'signals.dart';

/// One pill check on the real instrument: blank, mark t = 0, collect the 1 Hz readings for
/// [duration], stop. The result is the transmission absorbance trace as the board reported
/// it, in the shape `POST /scans` takes as `hardware`.
///
/// The phone does not classify: status is `unknown`, confidence 0, and the spectrum is
/// the raw trace. Deciding what the trace means is the backend's job.
class PillRunResult {
  const PillRunResult({required this.analysis, required this.severeFaults});

  final PillHardwareAnalysis analysis;

  /// Faults at [Severity.severe] seen at any point during the run: the numbers came
  /// through, but the bench says not to trust them.
  final List<Fault> severeFaults;
}

class PillRun {
  const PillRun._();

  /// The board is still settling from the blank when `z` would otherwise go out.
  static const settle = Duration(milliseconds: 1200);

  /// The backend caps `hardware.spectrum` at this many values.
  static const maxSpectrum = 4096;

  static Future<PillRunResult> measure(
    InstrumentSession instrument, {
    required Duration duration,
    String? pillType,
    void Function(Reading reading, Duration elapsed)? onReading,
  }) async {
    if (!instrument.connected) {
      throw StateError(instrument.error ?? 'The instrument is not connected.');
    }
    final readings = <Reading>[];
    final severe = <String, Fault>{};
    final done = Completer<void>();
    done.future.ignore();
    final started = DateTime.now();

    void check() {
      if (done.isCompleted) return;
      if (!instrument.connected) {
        done.completeError(
            StateError(instrument.error ?? 'The instrument disconnected mid-run.'));
        return;
      }
      for (final f in instrument.faults.where((f) => f.severity == Severity.severe)) {
        severe[f.id] = f;
      }
      if (DateTime.now().difference(started) >= duration) done.complete();
    }

    final sub = instrument.readings.listen((r) {
      if (!r.running) return;
      readings.add(r);
      onReading?.call(r, DateTime.now().difference(started));
      check();
    });
    instrument.addListener(check);
    final clock = Timer.periodic(const Duration(milliseconds: 500), (_) => check());
    try {
      await instrument.send('b');
      await Future.any([Future<void>.delayed(settle), done.future]);
      if (!done.isCompleted) await instrument.send('z');
      await done.future;
    } finally {
      clock.cancel();
      instrument.removeListener(check);
      await sub.cancel();
      if (instrument.connected) await instrument.send('s');
    }

    final trace = [
      for (final r in readings)
        if (r.absT != null && !r.swept) r.absT!,
    ];
    if (trace.length > maxSpectrum) trace.removeRange(maxSpectrum, trace.length);

    final diag = instrument.diag;
    final model = diag?.firmware == null
        ? 'peel-xiao'
        : '${diag!.firmware}${diag.version == null ? '' : ' ${diag.version}'}';

    return PillRunResult(
      analysis: PillHardwareAnalysis(
        model: model,
        result: PillHardwareResult(
          status: 'unknown',
          spectrum: trace,
          pillType: pillType,
          degraded: false,
          confidence: 0,
        ),
      ),
      severeFaults: severe.values.toList(),
    );
  }
}
