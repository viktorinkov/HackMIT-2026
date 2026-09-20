import 'package:flutter/material.dart';

import 'rive/peel_rive_widgets.dart';
import 'screens/onboarding_screen.dart';
import 'theme/peel_theme.dart';

void main() => runApp(const PeelApp());

class PeelApp extends StatelessWidget {
  const PeelApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Peel',
      debugShowCheckedModeBanner: false,
      theme: buildPeelTheme(),
      home: const OnboardingScreen(),
      builder: (context, child) => PeelRiveHost(child: child ?? const SizedBox()),
    );
  }
}
