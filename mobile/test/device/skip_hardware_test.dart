import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:peel_mobile/device/device_run.dart';
import 'package:peel_mobile/device/session.dart';
import 'package:peel_mobile/rive/peel_rive_widgets.dart';
import 'package:peel_mobile/screens/device_screen.dart';
import 'package:peel_mobile/state/scan_session.dart';
import 'package:peel_mobile/theme/peel_theme.dart';

void main() {
  testWidgets('hardware can be skipped without connecting or inventing a run', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1320, 2700);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final session = Session(watchUsb: false, logging: false);
    final scan = ScanSession();
    final run = DeviceRun(session, scan);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildPeelTheme(),
        home: DeviceScreen(controller: run),
        builder: (context, child) =>
            PeelRiveHost(enabled: false, child: child!),
      ),
    );
    expect(find.text('Check pill'), findsOneWidget);
    await tester.tap(find.text('Skip hardware'));
    await tester.pumpAndSettle();
    expect(find.text('Results'), findsOneWidget);
    expect(scan.hardwareSkipped, isTrue);
    expect(scan.runReadings, isEmpty);
    expect(scan.runLogPath, isNull);
    expect(session.state, LinkState.idle);
    await tester.pumpWidget(const SizedBox());
    run.dispose();
    scan.dispose();
    session.dispose();
    await tester.pump();
  });
}
