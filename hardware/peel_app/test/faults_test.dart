import 'package:flutter_test/flutter_test.dart';
import 'package:peel_app/faults.dart';
import 'package:peel_app/signals.dart';

/// Builds a history the way the session does: one line at a time, a second apart.
class Board {
  Board({this.start}) : _at = start ?? DateTime(2026, 9, 20, 10) {
    history.connectedAt = _at;
  }

  final DateTime? start;
  final History history = History();
  DateTime _at;

  DateTime get now => _at;

  void wait(Duration d) => _at = _at.add(d);

  void line(String raw, {Duration after = const Duration(seconds: 1)}) {
    _at = _at.add(after);
    final parsed = parseLine(raw);
    if (parsed != null) history.addLine(parsed, _at);
  }

  void data({
    double trans = 2460,
    double scat = 180,
    double? tC = 22.0,
    Map<String, double>? sweep,
    double dark = 126,
    int stir = 100,
    bool swept = false,
    int count = 1,
    Duration every = const Duration(seconds: 1),
  }) {
    for (var i = 0; i < count; i++) {
      line(
        '{"t":-1.0,"trans":$trans,"scat":$scat,"absT":null,"absS":null,'
        '"tC":${tC ?? 'null'},'
        '${sweep == null ? '' : '"sweep":${_map(sweep)},'}'
        '"dark":{"trans":$dark,"scat":$dark},"stir":$stir,"swept":$swept}',
        after: every,
      );
    }
  }

  static String _map(Map<String, double> m) =>
      '{${m.entries.map((e) => '"${e.key}":${e.value}').join(',')}}';

  void diag(String body) => line('{"diag":{$body}}');

  List<Fault> get faults => evaluate(history, _at);
  Set<String> get ids => faults.map((f) => f.id).toSet();

  /// Every fault but the informational ones, which are not failures.
  Set<String> get problems =>
      faults.where((f) => f.severity != Severity.info).map((f) => f.id).toSet();
}

const healthySweep = {
  'ir': 820.0,
  'red': 897.0,
  'yellow': 1301.0,
  'green': 2463.0,
  'blue': 1700.0,
  'violet': 1096.0,
};
const healthyDiode = '"diode":{"ir":246,"red":547,"yellow":624,"green":1208,'
    '"blue":1510,"violet":1763}';

void main() {
  test('a healthy board raises nothing', () {
    final b = Board()
      ..line('# 17_stream ready. Fast channel = green LED.')
      ..data(sweep: healthySweep, swept: true)
      ..data(sweep: healthySweep, count: 8)
      ..diag('"fw":"17_stream+diag","reset":"POWERON",$healthyDiode,'
          '"noise":{"trans":44,"scat":44},"probe":{"present":true,"count":1},'
          '"radio":{"ch":1,"fail":0,"drift":0}');
    expect(b.ids, isEmpty);
  });

  test('SENSOR_UNPOWERED: below the ADC floor for five seconds', () {
    final b = Board()..data(trans: 12, count: 6);
    expect(b.problems, {'SENSOR_UNPOWERED'});
    expect(b.faults.first.evidence['channel'], 'trans');
    // Two lines is not yet evidence of anything.
    expect((Board()..data(trans: 12, count: 2)).problems, isEmpty);
    // Neither is a burst of lines: five seconds of floor readings means five seconds, not
    // five readings a few hundred milliseconds apart.
    expect(
      (Board()..data(trans: 12, count: 6, every: const Duration(milliseconds: 200)))
          .problems,
      isEmpty,
    );
  });

  test('SENSOR_SATURATED: pinned at full scale', () {
    expect((Board()..data(trans: 3100, count: 4)).problems, {'SENSOR_SATURATED'});
  });

  test('a swept line is not evidence of an unpowered sensor', () {
    final b = Board()..data(trans: 20, swept: true, count: 6);
    expect(b.problems, isEmpty);
    expect(b.ids, {'SWEPT_LINE'});
  });

  test('SENSOR_NOISY: the spread the firmware measured', () {
    final b = Board()
      ..data(count: 2)
      ..diag('"noise":{"trans":212,"scat":44}');
    expect(b.problems, {'SENSOR_NOISY'});
  });

  test('LID_OPEN: the dark reading is room light', () {
    expect((Board()..data(dark: 620, count: 2)).problems, {'LID_OPEN'});
    expect((Board()..data(dark: 160, count: 2)).problems, isEmpty);
  });

  test('NOT_ASSEMBLED: every colour at or below dark, three sweeps running', () {
    const flat = {'ir': -200.0, 'red': -180.0, 'yellow': -220.0,
      'green': -160.0, 'blue': -240.0, 'violet': -190.0};
    final b = Board();
    for (var i = 0; i < 3; i++) {
      b.data(sweep: flat, swept: true);
      b.data(sweep: flat, count: 3);
    }
    expect(b.problems, {'NOT_ASSEMBLED'});
    expect((Board()..data(sweep: healthySweep, swept: true, count: 3)).problems, isEmpty);
  });

  test('LED_OPEN: about 3300 mV, and no swap is reported for the same LED', () {
    final b = Board()
      ..data(count: 2)
      ..diag('"diode":{"ir":246,"red":547,"yellow":624,"green":1208,'
          '"blue":3300,"violet":1763}');
    expect(b.problems, {'LED_OPEN'});
    expect(b.faults.first.evidence['colour'], 'blue');
  });

  test('LED_SHORT: near zero', () {
    final b = Board()
      ..data(count: 2)
      ..diag('"diode":{"ir":246,"red":21,"yellow":624,"green":1208,'
          '"blue":1510,"violet":1763}');
    expect(b.problems, {'LED_SHORT'});
  });

  test('LED_SWAPPED: two forward drops the wrong way round', () {
    final b = Board()
      ..data(count: 2)
      ..diag('"diode":{"ir":246,"red":547,"yellow":624,"green":1510,'
          '"blue":1208,"violet":1763}');
    expect(b.problems, {'LED_SWAPPED'});
  });

  test('PROBE_MISSING: null temperature for three lines', () {
    expect((Board()..data(tC: null, count: 3)).problems, {'PROBE_MISSING'});
    expect((Board()..data(tC: null, count: 2)).problems, isEmpty);
  });

  test('PROBE_ERROR: the library sentinels, and not called missing as well', () {
    expect((Board()..data(tC: -127.0, count: 3)).problems, {'PROBE_ERROR'});
    expect((Board()..data(tC: 85.0, count: 3)).problems, {'PROBE_ERROR'});
  });

  test('TEMP_JITTER: more than half a degree in one second', () {
    final b = Board()
      ..data(tC: 22.0)
      ..data(tC: 23.8)
      ..data(tC: 22.1);
    expect(b.problems, {'TEMP_JITTER'});
    final steady = Board()
      ..data(tC: 22.0)
      ..data(tC: 22.06)
      ..data(tC: 22.13);
    expect(steady.problems, isEmpty);
  });

  test('STREAM_STALE: nothing for three seconds', () {
    final b = Board()..data(count: 3);
    expect(b.problems, isEmpty);
    b.wait(const Duration(seconds: 4));
    expect(b.problems, {'STREAM_STALE'});
  });

  test('LINE_GAP: one late line, reported once and not held against the board', () {
    final b = Board()
      ..data(count: 3)
      ..data(every: const Duration(milliseconds: 2200));
    expect(b.ids, {'LINE_GAP'});
    b.data(count: 2);
    expect(b.ids, isEmpty);
  });

  test('WRONG_FIRMWARE: connected, talking, but not 17_stream', () {
    final b = Board()
      ..line('# 18_selftest ready. Commands: d diode check, l lock-in, n noise')
      ..line('trans 2460 mV   scat  180 mV   tC 22.10')
      ..line('trans 2461 mV   scat  181 mV   tC 22.10');
    expect(b.problems, isEmpty, reason: 'give it five seconds first');
    b.line('trans 2462 mV   scat  179 mV   tC 22.11');
    b.line('trans 2463 mV   scat  180 mV   tC 22.12');
    b.line('trans 2464 mV   scat  180 mV   tC 22.12');
    expect(b.problems, {'WRONG_FIRMWARE'});
  });

  test('a silent board is stale, not the wrong firmware', () {
    final b = Board()..line('# 17_stream ready.');
    b.wait(const Duration(seconds: 10));
    expect(b.problems, {'STREAM_STALE'});
  });

  test('BROWNOUT_RESET: a second boot banner with no run in progress', () {
    final b = Board()
      ..line('# 17_stream ready.')
      ..data(count: 3)
      ..line('# 17_stream ready.')
      ..diag('"reset":"BROWNOUT"');
    expect(b.problems, {'BROWNOUT_RESET'});
    expect(b.faults.first.evidence['resetReason'], 'BROWNOUT');
  });

  test('BOARD_RESET: a firmware reset is not a supply problem', () {
    final b = Board()
      ..line('# 17_stream ready.')
      ..data(count: 3)
      ..line('# 17_stream ready.')
      ..diag('"reset":"PANIC"');
    expect(b.problems, {'BOARD_RESET'});
    expect(b.faults.first.message, contains('PANIC'));
  });

  test('BOARD_RESET_MIDRUN: the same thing during a run', () {
    final b = Board()..line('# 17_stream ready.');
    b.line('{"t":12.0,"trans":2460,"scat":180,"tC":22.0,"stir":100,"swept":false}');
    b.line('# 17_stream ready.');
    expect(b.problems, {'BOARD_RESET_MIDRUN'});
  });

  test('RADIO_DRIFT is information, RADIO_DOWN is a warning', () {
    final drift = Board()
      ..data(count: 2)
      ..line('# radio had drifted to channel 6, pulled back to 1');
    expect(drift.problems, isEmpty);
    expect(drift.ids, {'RADIO_DRIFT'});

    final down = Board()
      ..data(count: 2)
      ..diag('"radio":{"ch":1,"fail":40,"drift":0}');
    expect(down.problems, {'RADIO_DOWN'});
  });

  test('MOTOR_COUPLING: both channels move together across a stirrer toggle', () {
    final b = Board()
      ..data(trans: 2610, scat: 330, count: 3)
      ..data(trans: 2460, scat: 180, count: 2, stir: 0);
    expect(b.problems, {'MOTOR_COUPLING'});
    expect(b.faults.first.severity, Severity.warning);

    final dc = Board()
      ..data(trans: 4460, scat: 2180, count: 3)
      ..data(trans: 2460, scat: 180, count: 2, stir: 0);
    expect(dc.faults.firstWhere((f) => f.id == 'MOTOR_COUPLING').severity, Severity.severe);
  });

  test('a stirrer toggle that changes nothing is not a fault', () {
    final b = Board()
      ..data(count: 3)
      ..data(count: 3, stir: 0);
    expect(b.problems, isEmpty);
  });

  test('the firmware own before and after means are used when they are there', () {
    final b = Board()
      ..data(count: 2)
      ..diag('"motor":{"stir":100,"transBefore":2460,"transAfter":2610,'
          '"scatBefore":180,"scatAfter":330}');
    expect(b.problems, {'MOTOR_COUPLING'});
    expect(b.faults.first.evidence['source'], contains('firmware'));
  });

  test('every fault carries a threshold and a one line message', () {
    final b = Board()..data(trans: 12, count: 6);
    for (final f in b.faults) {
      expect(f.evidence['threshold'], isNotNull, reason: f.id);
      expect(f.message, isNot(contains('\n')), reason: f.id);
      expect(f.message.length, lessThan(160), reason: f.id);
    }
  });

  test('history is capped, so a long session does not grow without bound', () {
    final b = Board()..data(count: 400, every: const Duration(milliseconds: 10));
    expect(b.history.samples.length, 300);
  });
}
