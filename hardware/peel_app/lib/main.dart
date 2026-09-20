import 'package:flutter/material.dart';

import 'debug_screen.dart';
import 'session.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final session = Session()..init();
  runApp(PeelApp(session: session));
}

/// Material defaults on purpose: this build is the instrument's debug head, not a product.
class PeelApp extends StatelessWidget {
  const PeelApp({super.key, required this.session});
  final Session session;

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Peel debug',
        home: DebugScreen(session: session),
      );
}
