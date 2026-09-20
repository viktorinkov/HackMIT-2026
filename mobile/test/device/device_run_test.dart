import 'dart:convert';
import 'dart:io';

import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:peel_mobile/device/device_run.dart';
import 'package:peel_mobile/device/session.dart';
import 'package:peel_mobile/device/session_log.dart';
import 'package:peel_mobile/state/scan_session.dart';

import 'session_test.dart' show FakeLink;

String line({
  double t = -1,
  bool swept = false,
  double? temp,
  double red = 116,
}) => jsonEncode({
  't': t,
  'trans': 400,
  'scat': 60,
  'absT': 0.1,
  'tC': temp,
  'sweep': {'red': red, 'yellow': 137, 'green': 400, 'blue': null},
  'swept': swept,
});

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

  void say(FakeAsync time, String text) {
    link.say(text);
    time.flushMicrotasks();
  }

  void connect(FakeAsync time) {
    session.connectTo(link);
    time.flushMicrotasks();
    say(time, line());
  }

  void blank(FakeAsync time) {
    run.act();
    time.flushMicrotasks();
    say(time, '# blank stored: transmission 400 mV, scatter 60 mV');
    for (var i = 0; i < 5; i++) {
      say(time, line(swept: true));
    }
    expect(run.phase, DevicePhase.ready);
  }

  void startSample(FakeAsync time) {
    run.act();
    time.flushMicrotasks();
    expect(link.sent.last, 'z');
    say(time, line(t: 0));
    expect(run.phase, DevicePhase.dissolving);
    run.act(); // User confirms that the pill dissolved.
    time.flushMicrotasks();
    expect(run.phase, DevicePhase.checking);
  }

  test(
    'blank requires five new color sweeps, not cached or partial data',
    () => fakeAsync((time) {
      connect(time);
      say(time, line(swept: true)); // Before Water ready, not a baseline.
      expect(run.phase, DevicePhase.connected);
      run.act();
      time.flushMicrotasks();
      expect(link.sent.last, 'b');
      say(time, '# blank stored: transmission 400 mV, scatter 60 mV');
      for (var i = 0; i < 20; i++) {
        say(time, line());
      }
      say(
        time,
        '{"t":-1,"trans":100,"scat":5,"swept":true,"sweep":{"red":10,"yellow":20,"green":null}}',
      );
      expect(run.blankSweeps, 0);
      for (var i = 0; i < 4; i++) {
        say(time, line(swept: true));
      }
      expect(run.phase, DevicePhase.blanking);
      run.act();
      expect(link.sent.last, 'b');
      say(time, line(swept: true));
      expect(run.phase, DevicePhase.ready);
      say(
        time,
        line(swept: true, red: 999),
      ); // Freeze water before adding pill.
      expect(run.blankSweeps, 5);
    }),
  );

  test(
    'timer cannot finish before five post-dissolution sweeps and board stop',
    () => fakeAsync((time) {
      run.dispose();
      run = DeviceRun(session, scan, runDuration: const Duration(seconds: 20));
      connect(time);
      blank(time);
      run.act();
      time.flushMicrotasks();
      for (var i = 0; i < 5; i++) {
        say(time, line(t: i * 10.0, swept: true, red: 999));
      }
      time.elapse(const Duration(seconds: 90));
      expect(link.sent, isNot(contains('s')));
      expect(run.sampleSweeps, 0);
      run.act();
      time.flushMicrotasks();
      time.elapse(const Duration(seconds: 20));
      expect(link.sent, isNot(contains('s')));
      for (var i = 0; i < 5; i++) {
        say(time, line(t: 50 + i * 10.0, swept: true, red: 20));
      }
      expect(link.sent.where((c) => c == 's'), hasLength(1));
      expect(run.phase, DevicePhase.checking);
      expect(scan.runReadings, isEmpty);
      say(time, line());
      expect(run.phase, DevicePhase.complete);
      expect(scan.blankReadings.map((r) => r.sweep['red']), everyElement(116));
      expect(scan.sampleReadings.map((r) => r.sweep['red']), everyElement(20));
      expect(scan.runReadings, hasLength(10));
    }),
  );

  test(
    'manual stop is gated and the latest five sample sweeps are retained',
    () => fakeAsync((time) {
      connect(time);
      blank(time);
      startSample(time);
      run.act();
      time.flushMicrotasks();
      expect(link.sent, isNot(contains('s')));
      for (var i = 0; i < 7; i++) {
        say(time, line(t: i * 10.0, swept: true, red: i + 1.0));
      }
      run.act();
      time.flushMicrotasks();
      expect(link.sent.last, 's');
      expect(run.phase, DevicePhase.checking);
      say(time, line());
      expect(scan.sampleReadings.map((r) => r.sweep['red']), [3, 4, 5, 6, 7]);
    }),
  );

  test(
    'external starts cannot classify without this session water capture',
    () => fakeAsync((time) {
      connect(time);
      say(time, line(t: 0));
      expect(run.phase, DevicePhase.dissolving);
      run.act();
      time.flushMicrotasks();
      expect(link.sent.last, 's');
      say(time, line());
      expect(run.phase, DevicePhase.connected);
      expect(run.captureError, contains('incomplete'));
      expect(scan.runReadings, isEmpty);
    }),
  );

  test(
    'early stop, reset and disconnect discard incomplete captures',
    () => fakeAsync((time) {
      connect(time);
      blank(time);
      startSample(time);
      say(time, line(t: 10, swept: true));
      say(time, line()); // Physical stop before enough sweeps.
      expect(run.phase, DevicePhase.connected);
      expect(scan.runReadings, isEmpty);
      blank(time);
      say(time, '# 17_stream ready. Stirrer off');
      expect(run.blankSweeps, 0);
      say(time, line());
      blank(time);
      link.unplug();
      time.flushMicrotasks();
      expect(run.phase, DevicePhase.connecting);
      expect(run.blankSweeps, 0);
      expect(scan.blankReadings, isEmpty);
    }),
  );

  test(
    'disconnect cancels timed stop and reconnect needs a new water capture',
    () => fakeAsync((time) {
      run.dispose();
      run = DeviceRun(session, scan, runDuration: const Duration(seconds: 60));
      connect(time);
      blank(time);
      startSample(time);
      for (var i = 0; i < 5; i++) {
        say(time, line(t: i * 10.0, swept: true));
      }
      session.disconnect();
      time.flushMicrotasks();
      link = FakeLink();
      connect(time);
      time.elapse(const Duration(seconds: 65));
      expect(link.sent, isNot(contains('s')));
      expect(run.phase, DevicePhase.connected);
      expect(run.blankSweeps, 0);
    }),
  );

  test(
    'temperature advice and sentinel handling still follow telemetry',
    () => fakeAsync((time) {
      connect(time);
      blank(time);
      for (final temp in [20.0, 40.0]) {
        say(time, line(temp: temp));
        expect(run.phase, DevicePhase.temperature);
      }
      for (final temp in [35.5, 37.0, 38.5, -127.0, 85.0]) {
        say(time, line(temp: temp));
        expect(run.phase, DevicePhase.ready);
      }
      expect(run.temperature, isNull);
    }),
  );

  test(
    'complete run retains raw readings and log while reset clears captures',
    () async {
      final dir = await Directory.systemTemp.createTemp('peel-run');
      final log = await SessionLog.open(directory: dir);
      Future<void> sayAsync(String text) async {
        link.say(text);
        await Future<void>.delayed(Duration.zero);
      }

      try {
        await session.connectTo(link);
        session.log = log;
        await sayAsync(line());
        await run.act();
        await sayAsync('# blank stored: transmission 400 mV, scatter 60 mV');
        for (var i = 0; i < 5; i++) {
          await sayAsync(line(swept: true));
        }
        await run.act();
        await sayAsync(line(t: 0));
        await run.act();
        for (var t = 1; t < 305; t++) {
          await sayAsync(line(t: t.toDouble(), swept: t % 10 == 0));
        }
        await sayAsync(line());
        expect(run.phase, DevicePhase.complete);
        expect(scan.runReadings, hasLength(305));
        expect(scan.runLogPath, log.path);
        expect(await log.read(), contains('"kind":"reading"'));
        scan.reset();
        expect(run.phase, DevicePhase.connected);
        expect(scan.blankReadings, isEmpty);
        expect(scan.sampleReadings, isEmpty);
        expect(scan.runReadings, isEmpty);
      } finally {
        await session.disconnect();
        await log.close();
        await dir.delete(recursive: true);
      }
    },
  );
}
