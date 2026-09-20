import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:peel_mobile/hardware/instrument_session.dart';
import 'package:peel_mobile/hardware/link.dart';
import 'package:peel_mobile/hardware/pill_run.dart';

class FakeLink implements Link {
  @override
  final String label = 'fake board';
  final sent = <String>[];
  final _lines = StreamController<String>.broadcast();

  void say(String line) => _lines.add(line);

  @override
  Stream<String> get lines => _lines.stream;

  @override
  Future<void> send(String command) async => sent.add(command);

  @override
  Future<void> close() async {
    if (!_lines.isClosed) await _lines.close();
  }
}

String data(double t, double absT, {bool swept = false}) =>
    '{"t":$t,"trans":1200,"scat":300,"absT":$absT,"absS":0.01,"tC":21.5,'
    '"stir":0,"swept":$swept}';

void main() {
  test('a run blanks, marks t=0, keeps the running trace and stops', () async {
    final session = InstrumentSession(watchUsb: false, logging: false);
    final link = FakeLink();
    await session.connectTo(link);
    link.say('{"diag":{"fw":"17_stream","ver":"1.4"}}');

    final feed = Timer.periodic(const Duration(milliseconds: 100), (timer) {
      link.say(timer.tick == 3 ? data(3, 0.3, swept: true) : data(timer.tick.toDouble(), timer.tick / 10));
    });
    final run = await PillRun.measure(
      session,
      duration: const Duration(milliseconds: 1600),
      pillType: 'ibuprofen',
    );
    feed.cancel();

    final commands = link.sent.where((c) => c != 'd').toList();
    expect(commands.take(2), ['b', 'z']);
    expect(commands.last, 's');
    expect(run.analysis.result.status, 'unknown');
    expect(run.analysis.result.pillType, 'ibuprofen');
    expect(run.analysis.result.spectrum, isNotEmpty);
    expect(run.analysis.result.spectrum, isNot(contains(0.3)));
    expect(run.analysis.model, '17_stream 1.4');
    expect(run.severeFaults, isEmpty);

    await session.disconnect();
    session.dispose();
  });

  test('the board going away mid-run fails the run instead of hanging', () async {
    final session = InstrumentSession(watchUsb: false, logging: false);
    final link = FakeLink();
    await session.connectTo(link);

    final pending = PillRun.measure(session, duration: const Duration(seconds: 30));
    await Future<void>.delayed(const Duration(milliseconds: 100));
    await link.close();

    await expectLater(pending, throwsA(isA<StateError>()));
    session.dispose();
  });
}
