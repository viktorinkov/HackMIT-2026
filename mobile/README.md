# Peel mobile

Android-only Flutter app built from the Peel Figma prototype
(`lPyn5YG33z3lPlWiaKjsK9`, page "Peel").

## Run

```bash
flutter pub get
flutter run                 # debug on a connected device or emulator
flutter build apk --debug   # build/app/outputs/flutter-apk/app-debug.apk
flutter analyze && flutter test
```

## Flow

Onboarding → scan bottle → scan imprint → scan pill → device connect and pill
check → results → chat (text or voice) → report → report sent.

Each scan step takes a photo with the camera or picks an existing one, previews
it and can replace or remove it. Camera permission denial and cancellation are
handled in the picker sheet.

## Mocked for the demo

- Recognition and the verdict (`lib/data/mock_data.dart`). The results screen
  starts on the mismatch story so the report flow is reachable; tap the finding
  card to cycle match / mismatch / could not confirm / degradation.
- Report submission is a timed placeholder. Device connection and run state use real telemetry.
- Chat replies are canned.
- Voice chat cycles listening → thinking → speaking over a `waveform_flutter`
  bar waveform (`lib/widgets/voice_waveform.dart`), which gives each state its
  own colour and motion: orange jitter for you, a grey pulse while Peel thinks,
  a teal swell while Peel answers. Voice is mocked; the planned integration
  is the backend's `POST /deepgram/session` (Deepgram Voice Agent) — no key
  ships in the app.

## Instrument

Use Flutter 3.47.5 / Dart 3.13.4, JDK 21, and a USB-C data cable from the
Android phone to the XIAO. The app requests USB permission and reconnects on
attach. Keep the bench firmware: the app supports both its four-colour output
and the repository's 1.1.0 protocol.

Fill with clear water, close the lid, and tap **Water ready** to take the blank.
Drop in the pill and tap **Check pill** to start; **Stop** ends the run. The
BOX-3 can also start/stop it. Temperature advice targets 37 ± 1.5 °C; a missing
probe or the -127/85 sentinels do not block a run. Sensor faults remain in debug,
and raw values are not smoothed or used to invent a pill verdict.

Long-press the device screen title for the Material debug screen, logs, and TCP
simulator connection. From the repository root run:

```bash
python3 hardware/sim/fake_board.py --tcp 9000
```

Use `10.0.2.2:9000` from an Android emulator or the computer's LAN address from a
phone. Device-dialect tests replay the actual nullable four-colour data as well
as start/stop, external starts, resets, and disconnects. Use wireless adb for a
physical phone: its USB port is occupied by the board.

## Backend

The app does not call the backend yet. `lib/data/mock_data.dart`
(`MockBackend`) and `lib/state/scan_session.dart` are the seams for
`POST /scans`, `POST /reports` and `POST /deepgram/session`. Finished runs are
available as `ScanSession.runReadings` and `ScanSession.runLogPath`. The reading
list includes swept lines unchanged; exclude those lines when plotting or
judging trans/scat. The log path is nullable if logging is unavailable; it points
to a per-connection JSONL file in the app cache.

## Animation

One shared Rive artboard (`assets/rive/peel_scan_flow.riv`, artboard
`PeelScan`, state machine `State Machine 1`, view-model number input `stage`)
is owned by `lib/rive/peel_rive_stage.dart` above the Navigator and painted
over whichever `PeelRiveSlot` is on screen (`lib/rive/peel_rive_widgets.dart`),
so it never restarts between screens. Stage mapping: bottle 0, pill 1,
connect 2, submerged 3, checking 4, complete 5, research 6, clear 7. It
hides while a dialog or sheet is up.
