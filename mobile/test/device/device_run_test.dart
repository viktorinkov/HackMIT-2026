import 'dart:convert';
import 'dart:io';

import 'package:fake_async/fake_async.dart';

import 'package:flutter_test/flutter_test.dart';
import 'package:peel_mobile/device/device_run.dart';
import 'package:peel_mobile/device/session.dart';
import 'package:peel_mobile/device/session_log.dart';
import 'package:peel_mobile/state/scan_session.dart';

import 'session_test.dart' show FakeLink;

const idle =
    '{"t":-1.0,"trans":186,"scat":80,"absT":0.1988,"absS":-0.4881,"tC":null,"sweep":{"red":-314,"yellow":-321,"green":-327,"blue":null},"stir":0,"swept":false}';
const sweep =
    '{"t":-1.0,"trans":23,"scat":314,"absT":1.1066,"absS":-1.0820,"tC":null,"sweep":{"red":-84,"yellow":-82,"green":-82,"blue":null},"stir":0,"swept":true}';
String line({
  double t = -1,
  double? temp,
  bool blank = true,
  bool swept = false,
}) {
  final data = jsonDecode(swept ? sweep : idle) as Map<String, dynamic>;
  data['t'] = t;
  data['tC'] = temp;
  data['stir'] = t >= 0 ? (t < 2 ? 50 : 30) : 0;
  if (!blank) {
    data.remove('absT');
    data.remove('absS');
  }
  return jsonEncode(data);
}

void main() {
  late Session session;
  late FakeLink link;
  late ScanSession scan;
  late DeviceRun run;
  setUp(() {
    session = Session(watchUsb: false, logging: false);
    link = FakeLink();
    scan = ScanSession();
    run = DeviceRun(session, scan);
  });
  tearDown(() {
    run.dispose();
    session.dispose();
    scan.dispose();
  });

  test(
    'device dialect: blank, start, stop; diagnostics never disturb a run',
    () => fakeAsync((time) {
      session.connectTo(link);
      time.flushMicrotasks();
      expect(run.phase, DevicePhase.connecting);
      link.say(line(blank: false));
      time.flushMicrotasks();
      expect(run.phase, DevicePhase.connected);
      run.act();
      expect(link.sent.last, 'b');
      expect(run.phase, DevicePhase.connected);
      link.say(idle);
      time.flushMicrotasks();
      expect(run.phase, DevicePhase.ready);
      expect(session.latest!.sweep['blue'], isNull);
      expect(run.temperature, isNull);
      expect(session.latest!.sweep['red'], -314);
      link.say(sweep);
      time.flushMicrotasks();
      expect(session.latest!.transMv, 23);
      time.elapse(const Duration(seconds: 61));
      expect(link.sent.where((c) => c == 'd'), hasLength(1));
      run.act();
      expect(link.sent.last, 'z');
      expect(run.phase, DevicePhase.ready);
      session.send('d');
      expect(link.sent.last, 'z');
      link.say(line(t: 0));
      time.flushMicrotasks();
      expect(run.phase, DevicePhase.checking);
      link.say('{"diag":{}}');
      time.flushMicrotasks();
      final before = link.sent.length;
      time.elapse(const Duration(seconds: 61));
      session.send('d');
      session.send('a');
      expect(link.sent.length, before);
      expect(link.sent, isNot(contains('m')));
      link.say(line(t: 10, swept: true));
      time.flushMicrotasks();
      run.act();
      expect(link.sent.last, 's');
      expect(run.phase, DevicePhase.checking);
      link.say(idle);
      time.flushMicrotasks();
      expect(run.phase, DevicePhase.complete);
      expect(scan.runReadings.map((r) => r.t), [0, 10]);
      expect(scan.runReadings.last.swept, isTrue);
      expect(scan.runReadings.last.transMv, 23);
      time.elapse(const Duration(seconds: 30));
      expect(link.sent.last, 'd');
      session.dispose();
      time.flushMicrotasks();
    }),
  );

  test(
    'external start, temperature advice, reset and detach follow telemetry',
    () => fakeAsync((time) {
      session.connectTo(link);
      time.flushMicrotasks();
      for (final temp in [20.0, 40.0]) {
        link.say(line(temp: temp));
        time.flushMicrotasks();
        expect(run.phase, DevicePhase.temperature);
      }
      for (final temp in [35.5, 37.0, 38.5, -127.0, 85.0]) {
        link.say(line(temp: temp));
        time.flushMicrotasks();
        expect(run.phase, DevicePhase.ready);
      }
      link.say(line(t: 3));
      time.flushMicrotasks();
      expect(run.phase, DevicePhase.checking);
      expect(link.sent, isNot(contains('z')));
      link.say('# 17_stream ready. Stirrer off');
      time.flushMicrotasks();
      expect(run.phase, DevicePhase.connected);
      expect(scan.runReadings, isEmpty);
      link.say(line(blank: false));
      time.flushMicrotasks();
      expect(run.phase, DevicePhase.connected);
      link.say(line(t: 0));
      time.flushMicrotasks();
      link.unplug();
      time.flushMicrotasks();
      expect(run.phase, DevicePhase.connecting);
      expect(scan.runReadings, isEmpty);
      session.connectTo(FakeLink());
      time.flushMicrotasks();
      expect(run.phase, DevicePhase.connecting);
      session.dispose();
      time.flushMicrotasks();
    }),
  );

  test(
    'joining an active run never sends the initial diode check',
    () => fakeAsync((time) {
      session.connectTo(link);
      time.flushMicrotasks();
      link.say(line(t: 20));
      time.flushMicrotasks();
      time.elapse(const Duration(seconds: 61));
      expect(link.sent, isEmpty);
      expect(run.phase, DevicePhase.checking);
      link.say(idle);
      time.flushMicrotasks();
      expect(run.phase, DevicePhase.complete);
      expect(link.sent, ['d']);
      session.dispose();
      time.flushMicrotasks();
    }),
  );
  test(
    'a complete long run keeps every raw reading and its log path',
    () async {
      final dir = await Directory.systemTemp.createTemp('peel-run');
      final log = await SessionLog.open(directory: dir);
      try {
        await session.connectTo(link);
        session.log = log;
        for (var t = 0; t < 305; t++) {
          link.say(line(t: t.toDouble(), swept: t % 10 == 0));
        }
        link.say(idle);
        await Future<void>.delayed(const Duration(milliseconds: 30));
        expect(run.phase, DevicePhase.complete);
        expect(scan.runReadings, hasLength(305));
        expect(scan.runReadings.first.t, 0);
        expect(scan.runReadings.last.t, 304);
        expect(scan.runLogPath, log.path);
        expect(await log.read(), contains('"kind":"reading"'));
        scan.reset();
        expect(run.phase, DevicePhase.ready);
        expect(scan.runReadings, isEmpty);
      } finally {
        await session.disconnect();
        await log.close();
        await dir.delete(recursive: true);
      }
    },
  );
}
