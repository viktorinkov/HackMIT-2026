import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:peel_mobile/main.dart';

void main() {
  setUpAll(() async {
    final loader = FontLoader('Inter')
      ..addFont(rootBundle.load('assets/fonts/Inter-Regular.ttf'));
    await loader.load();
  });
  testWidgets('onboarding leads into the bottle scan', (tester) async {
    tester.view.physicalSize = const Size(1320, 2700);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const PeelApp(animations: false));

    expect(find.text('Peel'), findsOneWidget);

    await tester.tap(find.text('Get started'));
    await tester.pumpAndSettle();

    expect(find.text('Scan bottle'), findsWidgets);
    expect(find.text('Bottle'), findsOneWidget);
  });
}
