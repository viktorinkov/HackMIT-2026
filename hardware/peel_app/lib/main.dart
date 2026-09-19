import 'package:flutter/material.dart';

import 'dashboard.dart';
import 'session.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final session = Session()..init();
  runApp(PeelApp(session: session));
}

class PeelApp extends StatelessWidget {
  const PeelApp({super.key, required this.session});
  final Session session;

  static const _peel = Color(0xFFF28C28); // it's an orange

  @override
  Widget build(BuildContext context) {
    ThemeData theme(Brightness b) => ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: _peel, brightness: b),
          useMaterial3: true,
        );
    return MaterialApp(
      title: 'Peel',
      debugShowCheckedModeBanner: false,
      theme: theme(Brightness.light),
      darkTheme: theme(Brightness.dark),
      home: Dashboard(session: session),
    );
  }
}
