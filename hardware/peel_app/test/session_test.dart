import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:peel_app/link.dart';
import 'package:peel_app/session.dart';
import 'package:peel_app/session_log.dart';
import 'package:peel_app/signals.dart';

/// A board under the test's control: no USB, no sockets.
class FakeLink implements Link {
  FakeLink([this.label = 'fake board']);

  @override
  final String label;
  final sent = <String>[];
  final _lines = StreamController<String>.broadcast();
  bool closed = false;

  void say(String line) => _lines.add(line);

  /// The cable coming out.
  void unplug() => _lines.close();

  void fail(Object error) => _lines.addError(error);

  @override
  Stream<String> get lines => _lines.stream;

  @override
  Future<void> send(String command) async => sent.add(command);

  @override
  Future<void> close() async {
    closed = true;
    if (!_lines.isClosed) await _lines.close();
  }
}

const _data = '{"t":1.0,"trans":2460,"scat":40,"tempC":22.0,"blank":2500,'
    '"absT":0.0068,"absS":null,"stir":0,"swept":0}';

Future<void> settle([int ms = 30]) =>
    Future<void>.delayed(Duration(milliseconds: ms));

void main() {
  late Session session;
  late FakeLink link;

  setUp(() {
    session = Session(watchUsb: false, logging: false, tick: const Duration(milliseconds: 50));
    link = FakeLink();
  });

  tearDown(() => session.dispose());

  test('lines become readings, faults and notifications', () async {
    var notified = 0;
    session.addListener(() => notified++);
    await session.connectTo(link);
    expect(session.connected, isTrue);
    expect(session.deviceLabel, 'fake board');

    final readings = <Reading>[];
    session.readings.listen(readings.add);
    link.say(_data);
    await settle();

    expect(readings.single.transMv, 2460);
    expect(session.lineCount, 1);
    expect(notified, greaterThan(0));
  });

  test('it asks the board for diagnostics on connect and does not stop asking', () async {
    await session.connectTo(link);
    await settle(400);
    expect(link.sent, ['d']);
  });

  test('# notes track the auto t=0 state the board reports', () async {
    await session.connectTo(link);
    expect(session.autoZero, isTrue);
    link.say('# auto t=0 off');
    await settle();
    expect(session.autoZero, isFalse);
    link.say('# auto t=0 on');
    await settle();
    expect(session.autoZero, isTrue);
  });

  test('unplugging ends the session with a reason instead of hanging', () async {
    await session.connectTo(link);
    link.say(_data);
    await settle();
    link.unplug();
    await settle();
    expect(session.connected, isFalse);
    expect(session.error, contains('closed'));
  });

  test('a read error ends the session with the error', () async {
    await session.connectTo(link);
    link.fail(StateError('usb went away'));
    await settle();
    expect(session.connected, isFalse);
    expect(session.error, contains('usb went away'));
  });

  test('replugging starts clean: no readings from the last connection', () async {
    await session.connectTo(link);
    link.say(_data);
    await settle();
    expect(session.history.samples, hasLength(1));

    link.unplug();
    await settle();
    final second = FakeLink('fake board 2');
    await session.connectTo(second);
    expect(session.history.samples, isEmpty);
    expect(session.latest, isNull);
    expect(session.lineCount, 0);
    expect(link.closed, isTrue);
  });

  test('commands reach the board, and are dropped when it is not there', () async {
    await session.send('b');
    expect(link.sent, isEmpty);
    await session.connectTo(link);
    for (final c in ['b', 'z', 'a', 's', 'm', 'd']) {
      await session.send(c);
    }
    expect(link.sent, containsAllInOrder(['b', 'z', 'a', 's', 'm', 'd']));
  });

  test('STREAM_STALE arrives on the clock, with no line to trigger it', () async {
    await session.connectTo(link);
    link.say(_data);
    // The engine has to run on a timer, or a board that stops looks healthy forever.
    await Future<void>.delayed(const Duration(milliseconds: 3200));
    expect(session.faults.map((f) => f.id), contains('STREAM_STALE'));
  }, timeout: const Timeout(Duration(seconds: 15)));

  test('hanging up on purpose is not a stale stream', () async {
    await session.connectTo(link);
    link.say(_data);
    await session.disconnect();
    await Future<void>.delayed(const Duration(milliseconds: 3200));
    expect(session.faults, isEmpty);
  }, timeout: const Timeout(Duration(seconds: 15)));

  group('the session log', () {
    late Directory dir;

    setUp(() => dir = Directory.systemTemp.createTempSync('peel-log'));
    tearDown(() => dir.deleteSync(recursive: true));

    test('one file per session, holding everything the board said', () async {
      final log = SessionLog.open(directory: dir, now: DateTime(2026, 5, 1, 9, 30, 15));
      expect(log.file.path, endsWith('peel-2026-05-01T09-30-15.000.jsonl'));

      final at = DateTime(2026, 5, 1, 9, 30, 16);
      log.event('connected', {'device': 'XIAO'}, at);
      log.raw(_data, at);
      log.line(parseLine(_data)!, at);
      log.raw('# blank stored', at);
      log.line(parseLine('# blank stored')!, at);
      log.raw('rst:0x1 (POWERON)', at);
      log.line(parseLine('rst:0x1 (POWERON)')!, at);
      log.event('command', {'command': 'b'}, at);
      await log.close();

      final records = LineSplitter.split(await log.read())
          .map((l) => jsonDecode(l) as Map<String, Object?>)
          .toList();
      expect(records.first['kind'], 'session');
      final kinds = records.map((r) => r['kind']).toList();
      expect(kinds,
          containsAllInOrder(['session', 'event', 'raw', 'reading', 'raw', 'note']));
      expect(kinds, contains('unknown'));

      final reading = records.firstWhere((r) => r['kind'] == 'reading');
      expect(reading['trans'], 2460);
      expect(reading['absT'], closeTo(0.0068, 1e-9));
      // The raw line is kept verbatim next to the parse, so a capture can be replayed.
      expect(records.firstWhere((r) => r['kind'] == 'raw')['line'], _data);
    });

    test('two connections in the same second get a file each', () async {
      final at = DateTime(2026, 5, 1, 9, 30, 15);
      final first = SessionLog.open(directory: dir, now: at);
      final second = SessionLog.open(directory: dir, now: at);
      await first.close();
      await second.close();

      expect(second.file.path, isNot(first.file.path));
      for (final log in [first, second]) {
        expect(LineSplitter.split(await log.read()).length, 1);
      }
    });

    test('the first line of the run is in the log, not lost to opening it', () async {
      final logged = Session(watchUsb: false, logging: true, logDirectory: dir);
      addTearDown(logged.dispose);
      await logged.connectTo(link);
      link.say(_data);
      await settle();
      final log = logged.log!;
      await log.close();

      expect(await log.read(), contains('"kind":"reading"'));
    });

    test('the log survives the disconnect that closed it, so the run can be read back',
        () async {
      final log = SessionLog.open(directory: dir);
      final logged = Session(watchUsb: false, logging: false);
      addTearDown(logged.dispose);
      await logged.connectTo(link);
      logged.log = log;

      link.say(_data);
      await settle();
      await logged.disconnect();

      expect(logged.log, same(log));
      expect(log.isClosed, isTrue);
      expect(await log.read(), contains('"kind":"reading"'));
    });

    test('faults are written when they are raised and again when they clear', () async {
      final log = SessionLog.open(directory: dir);
      final logged = Session(
        watchUsb: false,
        logging: false,
        tick: const Duration(milliseconds: 50),
      );
      addTearDown(logged.dispose);
      await logged.connectTo(link);
      logged.log = log;

      // Spread out, because SENSOR_UNPOWERED wants five seconds of floor readings and not
      // merely five readings.
      for (var i = 1; i < 10; i++) {
        link.say('{"t":$i.0,"trans":10,"scat":10,"tempC":22.0,"swept":0}');
        await settle(600);
      }
      await settle(200);
      expect(logged.faults.map((f) => f.id), contains('SENSOR_UNPOWERED'));

      link.say('{"t":9.0,"trans":2460,"scat":40,"tempC":22.0,"swept":0}');
      await settle(200);
      await log.close();

      final records = LineSplitter.split(await log.read())
          .map((l) => jsonDecode(l) as Map<String, Object?>)
          .where((r) => r['kind'] == 'fault' && r['id'] == 'SENSOR_UNPOWERED')
          .toList();
      expect(records.map((r) => r['event']), containsAllInOrder(['raised', 'cleared']));
      expect(records.first['evidence'], isA<Map<String, Object?>>());
      expect(records.first['severity'], 'severe');
    }, timeout: const Timeout(Duration(seconds: 30)));
  });
}
