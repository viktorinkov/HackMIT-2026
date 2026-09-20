import 'package:flutter_test/flutter_test.dart';
import 'package:peel_mobile/main.dart';

void main() {
  testWidgets('onboarding leads into the bottle scan', (tester) async {
    await tester.pumpWidget(const PeelApp());

    expect(find.text('Peel'), findsOneWidget);

    await tester.tap(find.text('Get started'));
    await tester.pumpAndSettle();

    expect(find.text('Scan bottle'), findsWidgets);
    expect(find.text('Bottle'), findsOneWidget);
  });
}
