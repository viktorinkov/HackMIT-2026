import 'dart:io';

import 'package:flutter/foundation.dart';

import '../hardware/instrument_session.dart';

/// `--dart-define=PEEL_SIM=host:port` connects to `hardware/sim/fake_board.py` instead of
/// waiting for a board on USB. `10.0.2.2:9000` reaches a simulator on the emulator's host.
const peelSimulator = String.fromEnvironment('PEEL_SIM');

/// `--dart-define=PEEL_RUN_SECONDS=20`: how long a pill check streams before it stops.
const peelRunSeconds = int.fromEnvironment('PEEL_RUN_SECONDS', defaultValue: 20);

/// The one connection to the instrument, shared by every screen. Only Android has the USB
/// plugin; anywhere else the session still runs, for the simulator and for tests.
final instrument = InstrumentSession(watchUsb: !kIsWeb && Platform.isAndroid);
