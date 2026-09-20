import 'package:flutter/services.dart';

import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:peel_mobile/services/peel_api.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:peel_mobile/device/device_run.dart';
import 'package:peel_mobile/device/session.dart';
import 'package:peel_mobile/device/signals.dart';
import 'package:peel_mobile/rive/peel_rive_widgets.dart';
import 'package:peel_mobile/screens/device_screen.dart';
import 'package:peel_mobile/state/scan_session.dart';
import 'package:peel_mobile/theme/peel_theme.dart';

void main() {
  setUpAll(() async {
    final loader = FontLoader('Inter')
      ..addFont(rootBundle.load('assets/fonts/Inter-Regular.ttf'));
    await loader.load();
  });
  test(
    'long sensor payload keeps timestamps and endpoint channels aligned',
    () {
      final readings = List.generate(
        300,
        (i) => Reading(
          t: i.toDouble(),
          transMv: i.toDouble(),
          scatMv: 3,
          darkTransMv: -2,
          sweep: const {'red': -10, 'blue': null},
        ),
      );
      final rows = sensorPayload(readings);
      expect(rows, hasLength(256));
      expect(rows.first['t'], 0);
      expect(rows.last['t'], 299);
      expect(rows.last['trans'], 299);
      expect(rows.first['darkTrans'], -2);
      expect(rows.first['sweep'], {'red': -10.0, 'blue': null});
    },
  );
  for (final skip in [true, false]) {
    testWidgets(
      skip
          ? 'skip omits hardware and continues research'
          : 'completed run submits raw evidence without a verdict',
      (tester) async {
        tester.view.physicalSize = const Size(1320, 2700);
        tester.view.devicePixelRatio = 3;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final session = Session(watchUsb: false, logging: false);
        final scan = scanSession;
        scan.reset();
        scan.deviceId = 'test-device';
        final requests = <Map<String, dynamic>>[];
        final api = PeelApi(
          client: MockClient((request) async {
            expect(request.url.path, '/scans');
            requests.add(jsonDecode(request.body) as Map<String, dynamic>);
            return http.Response(
              jsonEncode({
                'scan_id': 'test-scan',
                'device_id': 'test-device',
                'status': 'complete',
                'research': {},
              }),
              200,
            );
          }),
        );
        final run = DeviceRun(session, scan);
        if (!skip) {
          scan.finishRun(const [
            Reading(t: 0, transMv: 10, scatMv: 5, absT: -0.2),
            Reading(t: 1, transMv: 10, scatMv: 5, absT: 0.7, swept: true),
            Reading(t: 2, transMv: 10, scatMv: 5, absT: 0.3),
          ], '/test/log');
          run.phase = DevicePhase.complete;
        }
        await tester.pumpWidget(
          MaterialApp(
            theme: buildPeelTheme(),
            home: DeviceScreen(controller: run, api: api),
            builder: (context, child) =>
                PeelRiveHost(enabled: false, child: child!),
          ),
        );
        if (skip) {
          expect(find.text('Check pill'), findsOneWidget);
          await tester.tap(find.text('Skip hardware'));
        } else {
          await tester.pump(const Duration(milliseconds: 1600));
        }
        await tester.pumpAndSettle();
        expect(find.text('Results'), findsOneWidget);
        expect(scan.hardwareSkipped, skip);
        expect(scan.runReadings, hasLength(skip ? 0 : 3));
        expect(scan.runLogPath, skip ? isNull : "/test/log");
        expect(session.state, LinkState.idle);
        await tester.pumpWidget(const SizedBox());
        run.dispose();
        expect(requests, hasLength(1));
        if (skip) {
          expect(requests.single.containsKey('hardware'), isFalse);
          expect(requests.single.containsKey('hardware_model'), isFalse);
        } else {
          final hardware = requests.single['hardware'] as Map;
          expect(hardware['spectrum'], [-0.2, 0.3]);
          expect(hardware['status'], 'unknown');
          expect(hardware['confidence'], 0);
          expect(hardware['sensor_sample_count'], 3);
          final rows = hardware['sensor_readings'] as List;
          expect(rows, hasLength(3));
          expect(rows[0]['absT'], -0.2);
          expect(rows[1]['swept'], true);
          expect(rows[2]['t'], 2);
        }
        scan.reset();
        session.dispose();
        await tester.pump();
      },
    );
  }
}
