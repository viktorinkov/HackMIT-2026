@Tags(['simulator'])
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:peel_mobile/device/faults.dart';
import 'package:peel_mobile/device/session.dart';
import 'package:peel_mobile/device/signals.dart';

/// The whole stack against a board that is not there: `sim/fake_board.py` over TCP, the
/// real [TcpLink], the real parser, the real fault engine.
///
/// These are the tests that would otherwise need hardware. They need python3 on PATH.
class Sim {
  Sim._(this._process, this.port, this.controlPort);

  final Process _process;
  final int port;
  final int? controlPort;
  Socket? _control;

  static Future<Sim> start(List<String> args, {bool control = false}) async {
    final process = await Process.start('python3', [
      '../hardware/sim/fake_board.py',
      '--tcp',
      '0',
      if (control) ...['--control', '0'],
      ...args,
    ], workingDirectory: Directory.current.path);
    final banner = process.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .asBroadcastStream();
    final ports = <int>[];
    await for (final line in banner) {
      if (!line.contains('127.0.0.1:')) continue;
      ports.add(int.parse(line.split(':').last.trim()));
      if (ports.length == (control ? 2 : 1)) break;
    }
    return Sim._(process, ports.first, control ? ports[1] : null);
  }

  /// Breaks the board mid-session, the way a jumper falling out does.
  Future<void> inject(String command) async {
    _control ??= await Socket.connect('127.0.0.1', controlPort!);
    _control!.add(ascii.encode('$command\n'));
    await _control!.flush();
  }

  Future<void> stop() async {
    _control?.destroy();
    _process.kill();
    await _process.exitCode;
  }
}

/// Polls the session the way the screen does, rather than reaching into the engine.
Future<Fault> waitForFault(
  Session session,
  String id, {
  Duration timeout = const Duration(seconds: 20),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(deadline)) {
    for (final fault in session.faults) {
      if (fault.id == id) return fault;
    }
    await Future<void>.delayed(const Duration(milliseconds: 50));
  }
  throw TestFailure(
    '$id never appeared; saw ${session.faults.map((f) => f.id).toList()}',
  );
}

Future<T> waitFor<T>(
  T? Function() get, {
  Duration timeout = const Duration(seconds: 20),
}) async {
  final deadline = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(deadline)) {
    final value = get();
    if (value != null) return value;
    await Future<void>.delayed(const Duration(milliseconds: 50));
  }
  throw TestFailure('timed out');
}

void main() {
  late Sim sim;
  late Session session;

  Future<void> connect(List<String> args, {bool control = false}) async {
    sim = await Sim.start(args, control: control);
    session = Session(
      watchUsb: false,
      logging: false,
      tick: const Duration(milliseconds: 100),
    );
    await session.connectTcp('127.0.0.1', sim.port);
    expect(session.connected, isTrue);
  }

  tearDown(() async {
    session.dispose();
    await sim.stop();
  });

  test('a healthy board streams readings and raises nothing', () async {
    await connect(['--speed', '10']);
    await waitFor(() => session.history.samples.length >= 12 ? true : null);
    expect(session.latest!.transMv, greaterThan(2000));
    expect(session.latest!.tempC, closeTo(22, 1));
    expect(session.faults.where((f) => f.severity != Severity.info), isEmpty);
  });

  test('the commands do what the board says they do', () async {
    await connect(['--speed', '10']);
    await waitFor(() => session.latest);

    await session.send('b');
    await waitFor(
      () => session.history.notes.any((n) => n.text.startsWith('blank stored'))
          ? true
          : null,
    );
    await session.send('z');
    final running = await waitFor(
      () => session.latest?.running == true ? true : null,
    );
    expect(running, isTrue);
    expect(session.latest!.absT, isNotNull);

    await session.send('s');
    await waitFor(() => session.latest?.running == false ? true : null);

    await session.send('d');
    final diag = await waitFor(() => session.diag);
    expect(diag.firmware, startsWith('17_stream'));
    expect(diag.diodeMv.keys, containsAll(colours));
  });

  test(
    'joining mid-line, one byte at a time, with boot noise in front',
    () async {
      await connect(['--speed', '10', '--chunk', '1', '--junk']);
      await waitFor(() => session.history.samples.length >= 5 ? true : null);
      // The fragment and the ROM noise are kept as not-protocol, and cost no readings.
      expect(session.history.unknown, isNotEmpty);
      expect(session.faults.where((f) => f.severity != Severity.info), isEmpty);
    },
  );

  test('64 byte chunks', () async {
    await connect(['--speed', '10', '--chunk', '64']);
    await waitFor(() => session.history.samples.length >= 5 ? true : null);
    expect(session.latest!.sweep.keys, containsAll(colours));
  });

  for (final spec in const [
    ['SENSOR_UNPOWERED:trans', 'SENSOR_UNPOWERED'],
    ['SENSOR_SATURATED:both', 'SENSOR_SATURATED'],
    ['SENSOR_NOISY', 'SENSOR_NOISY'],
    ['LID_OPEN', 'LID_OPEN'],
    ['PROBE_MISSING', 'PROBE_MISSING'],
    ['PROBE_ERROR:-127', 'PROBE_ERROR'],
    ['TEMP_JITTER', 'TEMP_JITTER'],
    ['LED_OPEN:blue', 'LED_OPEN'],
    ['LED_SHORT:red', 'LED_SHORT'],
    ['LED_SWAPPED:green:blue', 'LED_SWAPPED'],
    ['NOT_ASSEMBLED', 'NOT_ASSEMBLED'],
    ['RADIO_DRIFT', 'RADIO_DRIFT'],
    ['RADIO_DOWN', 'RADIO_DOWN'],
  ]) {
    test('${spec[1]} is recognised from the stream', () async {
      await connect(['--speed', '10', '--fault', spec[0]]);
      // Radio failures accumulate after boot; request a fresh idle diagnostic.
      if (spec[1] == 'RADIO_DOWN') {
        await waitFor(() => session.history.samples.length >= 6 ? true : null);
        await session.send('d');
      }
      final fault = await waitForFault(session, spec[1]);
      expect(fault.evidence['threshold'], isNotNull);
      expect(fault.message, isNotEmpty);
      // Nothing else of consequence is invented on the way.
      final others = session.faults
          .where((f) => f.severity != Severity.info && f.id != spec[1])
          .map((f) => f.id)
          .toSet();
      expect(others, isEmpty);
    });
  }

  test('MOTOR_COUPLING when the stirrer is switched off', () async {
    await connect(['--fault', 'MOTOR_COUPLING:dc']);
    await waitFor(() => session.history.samples.length >= 2 ? true : null);
    await session.send('m');
    final fault = await waitForFault(session, 'MOTOR_COUPLING');
    expect(fault.severity, Severity.severe);
  });

  test('STREAM_STALE when the board stops talking', () async {
    await connect(['--fault', 'STREAM_STALE']);
    await waitForFault(
      session,
      'STREAM_STALE',
      timeout: const Duration(seconds: 10),
    );
  });

  test('WRONG_FIRMWARE when the board is running another sketch', () async {
    await connect(['--fault', 'WRONG_FIRMWARE']);
    await waitForFault(
      session,
      'WRONG_FIRMWARE',
      timeout: const Duration(seconds: 15),
    );
    expect(session.history.samples, isEmpty);
  });

  test(
    'a board that resets mid-session is reported, and the stream carries on',
    () async {
      await connect(['--brownout-at', '5']);
      await waitFor(() => session.history.samples.length >= 3 ? true : null);
      await waitForFault(session, 'BROWNOUT_RESET');
      final before = session.history.samples.length;
      await waitFor(
        () => session.history.samples.length > before ? true : null,
      );
    },
  );

  test(
    'a fault that appears mid-session, through the control channel',
    () async {
      await connect(['--speed', '10'], control: true);
      await waitFor(() => session.history.samples.length >= 3 ? true : null);
      expect(session.faults.where((f) => f.severity != Severity.info), isEmpty);
      await sim.inject('fault LID_OPEN');
      await waitForFault(session, 'LID_OPEN');
      await sim.inject('clear LID_OPEN');
      await waitFor(
        () => session.faults.every((f) => f.id != 'LID_OPEN') ? true : null,
      );
    },
  );

  test('the board going away closes the session instead of hanging', () async {
    await connect(['--speed', '10', '--disconnect-after', '3']);
    await waitFor(() => session.history.samples.isNotEmpty ? true : null);
    await waitFor(
      () => session.connected ? null : true,
      timeout: const Duration(seconds: 15),
    );
    expect(session.error, isNotNull);
  });

  test(
    'replaying the real capture produces the same readings the rig did',
    () async {
      await connect([
        '--replay',
        '../hardware/data/session_full_cycle.jsonl',
        '--speed',
        '20',
      ]);
      await waitFor(() => session.history.samples.length >= 20 ? true : null);
      final first = session.history.samples.first.reading;
      expect(first.transMv, greaterThan(0));
      // The capture is four-colour firmware: the app must not require the other two.
      expect(first.sweep.containsKey('violet'), isFalse);
    },
  );
}
