import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:peel_mobile/data/api_models.dart';
import 'package:peel_mobile/screens/results_screen.dart';
import 'package:peel_mobile/state/scan_session.dart';
import 'package:peel_mobile/theme/peel_theme.dart';

void main() {
  testWidgets('older real scans show recorded trace instead of unknown', (
    tester,
  ) async {
    scanSession.scan = ScanEnvelope.fromJson({
      'scan_id': 'legacy-real',
      'device_id': 'test',
      'status': 'complete',
      'hardware': {
        'status': 'unknown',
        'model': 'peel-xiao',
        'spectrum': [0.0344, 0.2558],
      },
      'research': {'headline': 'Recorded optical response'},
    });
    await tester.pumpWidget(
      MaterialApp(theme: buildPeelTheme(), home: const ResultsScreen()),
    );
    expect(find.text('2 absorbance readings recorded'), findsOneWidget);
    expect(find.textContaining('Hardware: unknown'), findsNothing);
    await tester.pumpWidget(const SizedBox());
    scanSession.reset();
  });
}
