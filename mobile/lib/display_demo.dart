import 'package:flutter/material.dart';

import 'device/display_session.dart';
import 'theme/peel_theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const DisplayDemo());
}

/// Separate entry point for bringing up the phone-controlled BOX-3 display.
class DisplayDemo extends StatefulWidget {
  const DisplayDemo({super.key});
  @override
  State<DisplayDemo> createState() => _DisplayDemoState();
}

class _DisplayDemoState extends State<DisplayDemo> {
  static const host = String.fromEnvironment('DISPLAY_HOST');
  final session = DisplaySession();

  @override
  void initState() {
    super.initState();
    if (host.isEmpty) session.watchUsb();
    session.connect(host: host);
  }

  @override
  void dispose() {
    session.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Peel display',
    debugShowCheckedModeBanner: false,
    theme: buildPeelTheme(),
    home: Scaffold(
      appBar: AppBar(title: const Text('Peel display')),
      body: SafeArea(
        child: AnimatedBuilder(
          animation: session,
          builder: (context, _) => Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              children: [
                Text(
                  host.isEmpty ? 'BOX-3 display' : 'Display simulator',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 24),
                Expanded(
                  child: Center(
                    child: AspectRatio(
                      aspectRatio: 4 / 3,
                      child: Container(
                        color: Colors.black,
                        child: Stack(
                          children: [
                            Positioned.fill(
                              child: Image.asset(
                                'assets/display/peel.png',
                                fit: BoxFit.contain,
                              ),
                            ),
                            Align(
                              alignment: Alignment.topCenter,
                              child: Padding(
                                padding: const EdgeInsets.only(top: 12),
                                child: Text(
                                  session.text,
                                  style: const TextStyle(
                                    color: Color(0xffff841c),
                                    fontSize: 28,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 24),
                Text(
                  session.error ??
                      (session.ready
                          ? 'Display connected'
                          : 'Connecting to display…'),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 20),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: session.ready ? session.showHello : null,
                    child: const Text('Say hello'),
                  ),
                ),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton(
                    onPressed: session.ready ? session.showPeel : null,
                    child: const Text('Default Peel'),
                  ),
                ),
                TextButton(
                  onPressed: session.connecting
                      ? null
                      : () => session.connect(host: host),
                  child: const Text('Reconnect'),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
