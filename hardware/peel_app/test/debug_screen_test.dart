import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:peel_app/debug_screen.dart';
import 'package:peel_app/link.dart';
import 'package:peel_app/session.dart';

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

void main() {
  testWidgets('the screen shows what the board said, and sends what is tapped',
      (tester) async {
    final session = Session(watchUsb: false, logging: false);
    final link = FakeLink();

    await tester.pumpWidget(MaterialApp(home: DebugScreen(session: session)));
    expect(find.text('no readings yet'), findsOneWidget);
    expect(find.text('none'), findsOneWidget); // no faults

    // Commands are dead until there is a board to send them to.
    expect(
      tester.widget<ElevatedButton>(find.widgetWithText(ElevatedButton, 'b  blank')).onPressed,
      isNull,
    );

    await session.connectTo(link);
    link.say('{"t":12.5,"trans":2460,"scat":41,"tempC":22.4,"blank":2500,"absT":0.0068,'
        '"absS":null,"stir":0,"swept":0}');
    link.say('# blank stored');
    link.say('rst:0x1 (POWERON)');
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pump();

    expect(find.textContaining('connected: fake board'), findsOneWidget);
    expect(find.text('2460 mV'), findsOneWidget);
    expect(find.text('12.5 s'), findsOneWidget);
    expect(find.text('0.0068'), findsOneWidget);

    await tester.tap(find.widgetWithText(ElevatedButton, 'z  t=0'));
    await tester.pump();
    expect(link.sent, contains('z'));

    // The notes and the lines that are not protocol are at the bottom of the one screen.
    await tester.drag(find.byType(ListView), const Offset(0, -1200));
    await tester.pump();
    expect(find.text('# blank stored'), findsOneWidget);
    expect(find.text('rst:0x1 (POWERON)'), findsOneWidget);

    session.dispose();
    await tester.pump();
  });
}
