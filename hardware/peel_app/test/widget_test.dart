import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:peel_app/link.dart';
import 'package:peel_app/main.dart';
import 'package:peel_app/reading.dart';
import 'package:peel_app/session.dart';

void main() {
  group('parseLine, against what 17_stream actually prints', () {
    test('a full reading mid-run', () {
      final line = parseLine('{"t":12.0,"trans":1830,"scat":140,"absT":0.1240,"absS":-0.0430,'
          '"tC":37.02,"sweep":{"red":1200,"yellow":900,"green":2400,"blue":1700},'
          '"stir":100,"swept":false}');
      final r = (line as DataLine).reading;
      expect(r.t, 12.0);
      expect(r.running, isTrue);
      expect(r.transMv, 1830);
      expect(r.absT, closeTo(0.124, 1e-9));
      expect(r.cloudiness, closeTo(0.043, 1e-9)); // scatter up = absS down = cloudier
      expect(r.tempC, 37.02);
      expect(r.sweep['blue'], 1700);
      expect(r.stirPct, 100);
    });

    test('before blank and before t = 0', () {
      final r = (parseLine('{"t":-1.0,"trans":2460,"scat":180,"absT":null,"absS":null,'
              '"tC":null,"sweep":{"red":null,"yellow":null,"green":null,"blue":null},'
              '"stir":0,"swept":false}') as DataLine)
          .reading;
      expect(r.t, isNull);
      expect(r.running, isFalse);
      expect(r.blanked, isFalse);
      expect(r.tempC, isNull);
      expect(r.sweep['red'], isNull);
    });

    test('old firmware printed nan for a dark sensor: keep the line, drop the field', () {
      final r = (parseLine('{"t":3.0,"trans":0,"scat":181,"absT":nan,"absS":-0.0021,"tC":null,'
              '"sweep":{"red":null,"yellow":null,"green":null,"blue":null},"stir":100,'
              '"swept":false}') as DataLine)
          .reading;
      expect(r.absT, isNull);
      expect(r.absS, closeTo(-0.0021, 1e-9));
    });

    test('board messages, with the CR that println leaves', () {
      final line = parseLine('# blank stored: transmission 2460 mV, scatter 180 mV\r');
      expect((line as NoteLine).text, startsWith('blank stored'));
    });

    test('a fragment from connecting mid-line, and blank lines, are ignored', () {
      expect(parseLine('ns":100,"swept":false}'), isNull);
      expect(parseLine('{"t":1.0,"trans":18'), isNull);
      expect(parseLine('   '), isNull);
    });
  });

  test('demo speaks the same protocol: every line parses, and a run develops', () async {
    final demo = DemoLink(tick: const Duration(milliseconds: 5));
    final readings = <Reading>[];
    var unparsed = 0;
    final sub = demo.lines.listen((raw) {
      final line = parseLine(raw);
      if (line == null) unparsed++;
      if (line is DataLine) readings.add(line.reading);
    });
    await Future<void>.delayed(const Duration(milliseconds: 30));
    await demo.send('b'); // blank; auto t=0 fires six ticks later
    await Future<void>.delayed(const Duration(milliseconds: 600));
    await sub.cancel();
    await demo.close();

    expect(unparsed, 0);
    final run = readings.where((r) => r.running).toList();
    expect(run.length, greaterThan(20));
    expect(run.last.absT!, greaterThan(run.first.absT! + 0.1)); // absorbance climbed
  });

  testWidgets('dashboard renders a whole demo run at phone width without overflow',
      (tester) async {
    tester.view.physicalSize = const Size(1080, 2220);
    tester.view.devicePixelRatio = 3; // 360 x 740 dp, a small phone
    addTearDown(tester.view.reset);

    final session = Session(watchUsb: false);
    await tester.pumpWidget(PeelApp(session: session));
    expect(find.text('Not connected'), findsOneWidget);

    await tester.tap(find.text('Try demo'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 2));
    expect(find.text('Demo · simulated tablet'), findsOneWidget);
    expect(find.textContaining('tap Blank'), findsOneWidget);

    unawaited(session.send('b'));
    for (var i = 0; i < 40; i++) {
      await tester.pump(const Duration(seconds: 1));
    }
    expect(find.text('Dissolution curve'), findsOneWidget);
    expect(session.run.length, greaterThan(25));

    // Scroll the rest of the dashboard into view so every card lays out.
    await tester.drag(find.byType(ListView), const Offset(0, -3000));
    await tester.pump();
    expect(find.text('Board messages'), findsOneWidget);
    expect(find.text('Auto start'), findsOneWidget);

    await session.disconnect();
    await tester.pump();
  });
}
