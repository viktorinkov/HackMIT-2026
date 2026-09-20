import 'dart:convert';
import 'dart:io';

import 'faults.dart';
import 'signals.dart';

/// One JSONL file per connection, holding the raw line, what it parsed into, and every
/// fault transition, each with a wall clock timestamp.
///
/// The point is that after a bad run at the bench there is a file to look at, rather than
/// a memory of what the screen said. Nothing is aggregated and nothing is dropped: it is
/// the session as it happened.
///
/// Records are one of:
///   {"at": "...", "kind": "raw",   "line": "{\"t\":12.0,...}"}
///   {"at": "...", "kind": "reading", ...every field...}
///   {"at": "...", "kind": "diag", ...}
///   {"at": "...", "kind": "note" | "unknown", "text": "..."}
///   {"at": "...", "kind": "fault", "event": "raised" | "cleared", "id": "...", ...}
class SessionLog {
  SessionLog._(this.file, this._sink, this.startedAt);

  final File file;
  final IOSink _sink;
  final DateTime startedAt;
  int _records = 0;
  bool _closed = false;

  int get records => _records;
  bool get isClosed => _closed;
  String get path => file.path;

  /// Opens `peel-<timestamp>.jsonl` in [directory], creating it if needed. On Android
  /// [Directory.systemTemp] is the app's own cache directory, which `adb pull` can reach
  /// without any storage permission; see `PLUG_IN_DAY.md`, in `hardware/docs/` on the
  /// `hardware-component` branch.
  static Future<SessionLog> open({Directory? directory, DateTime? now}) async {
    final at = now ?? DateTime.now();
    final dir = directory ?? Directory('${Directory.systemTemp.path}/peel');
    await dir.create(recursive: true);
    // Milliseconds, and a counter after them, because two connections a second apart
    // sharing a file would put two sessions in one log.
    final stamp = at.toIso8601String().replaceAll(':', '-');
    var file = File('${dir.path}/peel-$stamp.jsonl');
    for (var n = 2; file.existsSync(); n++) {
      file = File('${dir.path}/peel-$stamp-$n.jsonl');
    }
    final sink = file.openWrite();
    final log = SessionLog._(file, sink, at);
    log._write({'kind': 'session', 'app': 'peel_mobile', 'logVersion': 1}, at);
    return log;
  }

  void raw(String line, DateTime at) => _write({'kind': 'raw', 'line': line}, at);

  void line(Line parsed, DateTime at) {
    switch (parsed) {
      case DataLine(:final reading):
        _write({
          'kind': 'reading',
          't': reading.t,
          'trans': reading.transMv,
          'scat': reading.scatMv,
          'absT': reading.absT,
          'absS': reading.absS,
          'tC': reading.tempC,
          'sweep': reading.sweep,
          'sweepS': reading.sweepScatter,
          'darkTrans': reading.darkTransMv,
          'darkScat': reading.darkScatMv,
          'stir': reading.stirPct,
          'swept': reading.swept,
        }, at);
      case DiagLine(:final diag):
        _write({
          'kind': 'diag',
          'fw': diag.firmware,
          'ver': diag.version,
          'reset': diag.resetReason,
          'up': diag.uptimeMs,
          'heap': diag.heapBytes,
          'heapMin': diag.heapMinBytes,
          'loopMax': diag.loopMaxUs,
          'dark': {'trans': diag.darkTransMv, 'scat': diag.darkScatMv},
          'diode': diag.diodeMv,
          'noise': {'trans': diag.noiseTransMv, 'scat': diag.noiseScatMv},
          'probe': {
            'present': diag.probePresent,
            'count': diag.probeCount,
            'addr': diag.probeAddress,
          },
          'radio': {
            'ch': diag.radioChannel,
            'fail': diag.radioSendFailures,
            'drift': diag.radioDriftCorrections,
          },
          'motor': {
            'stir': diag.motorStirPct,
            'transShift': diag.motorTransShiftMv,
            'scatShift': diag.motorScatShiftMv,
          },
        }, at);
      case NoteLine(:final text):
        _write({'kind': 'note', 'text': text}, at);
      case UnknownLine(:final text):
        _write({'kind': 'unknown', 'text': text}, at);
    }
  }

  void fault(Fault fault, {required bool raised, required DateTime at}) => _write({
        'kind': 'fault',
        'event': raised ? 'raised' : 'cleared',
        'id': fault.id,
        'severity': fault.severity.name,
        'message': fault.message,
        'evidence': fault.evidence,
      }, at);

  void event(String what, Map<String, Object?> detail, DateTime at) =>
      _write({'kind': 'event', 'event': what, ...detail}, at);

  void _write(Map<String, Object?> record, DateTime at) {
    // A disconnect closes the log while lines and fault transitions may still be in
    // flight; late records are dropped rather than thrown.
    if (_closed) return;
    _records++;
    _sink.writeln(jsonEncode({'at': at.toIso8601String(), ...record}));
  }

  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    await _sink.flush();
    await _sink.close();
  }

  /// The whole log as text, for sharing off a phone with no file manager.
  Future<String> read() async {
    if (!_closed) await _sink.flush();
    return file.readAsString();
  }
}
