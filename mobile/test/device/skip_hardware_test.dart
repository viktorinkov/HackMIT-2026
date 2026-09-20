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
          : 'completed run classifies captures before submitting the scan',
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
        final paths = <String>[];
        final api = PeelApi(
          client: MockClient((request) async {
            paths.add(request.url.path);
            if (request.url.path == '/pill') {
              final body = jsonDecode(request.body) as Map;
              expect(body['blank'], hasLength(5));
              expect(body['sample'], hasLength(5));
              expect(body.containsKey('status'), isFalse);
              expect(body['sample'][0]['sweep'], {
                'red': 20.0,
                'yellow': 15.0,
                'green': 90.0,
              });
              return http.Response(
                jsonEncode({
                  'model': 'truepill-snapshot',
                  'result': {
                    'status': 'substandard',
                    'spectrum': [0.5, 0.6, 0.4],
                    'pill_type': 'advil',
                    'degraded': true,
                    'confidence': 0.8,
                  },
                }),
                200,
              );
            }
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
          scan.finishRun(
            const [
              Reading(t: 0, transMv: 10, scatMv: 5, absT: -0.2),
              Reading(t: 1, transMv: 10, scatMv: 5, absT: 0.7, swept: true),
              Reading(t: 2, transMv: 10, scatMv: 5, absT: 0.3),
            ],
            '/test/log',
            blank: List.generate(
              5,
              (_) => const Reading(
                t: null,
                transMv: 400,
                scatMv: 5,
                swept: true,
                sweep: {'red': 116, 'yellow': 137, 'green': 400, 'blue': null},
              ),
            ),
            sample: List.generate(
              5,
              (_) => const Reading(
                t: 50,
                transMv: 90,
                scatMv: 5,
                swept: true,
                sweep: {'red': 20, 'yellow': 15, 'green': 90, 'blue': null},
              ),
            ),
          );
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
          expect(paths, ['/scans']);
          expect(requests.single.containsKey('hardware'), isFalse);
          expect(requests.single.containsKey('hardware_model'), isFalse);
        } else {
          expect(paths, ['/pill', '/scans']);
          expect(requests.single['hardware_model'], 'truepill-snapshot');
          final hardware = requests.single['hardware'] as Map;
          expect(hardware['spectrum'], [0.5, 0.6, 0.4]);
          expect(hardware['status'], 'substandard');
          expect(hardware['confidence'], 0.8);
          expect(hardware['degraded'], isTrue);
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

  for (final legacy in [false, true]) {
    testWidgets(
      legacy
          ? 'legacy mock response is refused'
          : 'classification error stays on retry and never submits a scan',
      (tester) async {
        tester.view.physicalSize = const Size(1320, 2700);
        tester.view.devicePixelRatio = 3;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final session = Session(watchUsb: false, logging: false);
        final scan = scanSession;
        scan.reset();
        scan.deviceId = 'test-device';
        final run = DeviceRun(session, scan)..phase = DevicePhase.complete;
        final paths = <String>[];
        final api = PeelApi(
          client: MockClient((request) async {
            paths.add(request.url.path);
            if (legacy) {
              return http.Response(
                '{"model":"mock-spectrometry","result":{"status":"real","spectrum":[0.5],"confidence":0.9,"degraded":false}}',
                200,
              );
            }
            return http.Response('{"detail":"Capture rejected"}', 422);
          }),
        );
        await tester.pumpWidget(
          MaterialApp(
            theme: buildPeelTheme(),
            home: DeviceScreen(controller: run, api: api),
            builder: (context, child) =>
                PeelRiveHost(enabled: false, child: child!),
          ),
        );
        await tester.pump(const Duration(milliseconds: 1600));
        await tester.pumpAndSettle();
        expect(paths, ['/pill']);
        expect(
          find.text(
            legacy
                ? 'Update the backend to enable real pill classification.'
                : 'Capture rejected',
          ),
          findsOneWidget,
        );
        expect(find.text('Retry'), findsOneWidget);
        expect(scan.hardware, isNull);
        expect(scan.scanId, isNull);
        await tester.tap(find.text('Retry'));
        await tester.pumpAndSettle();
        expect(paths, ['/pill', '/pill']);
        await tester.pumpWidget(const SizedBox());
        run.dispose();
        session.dispose();
        scan.reset();
      },
    );
  }
}
