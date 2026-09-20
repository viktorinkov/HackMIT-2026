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

Onboarding → scan bottle → scan imprint → device check (optional) → research
→ results → voice or report.

Each scan step takes a photo with the camera or picks an existing one, previews
it and can replace or remove it. Camera permission denial and cancellation are
handled in the picker sheet.

## Services

Bottle and imprint identification, research, reporting, and voice use the backend
through `lib/services/peel_api.dart`. Configure `PEEL_API_BASE` at build time.
The app retains the current main-branch UI, voice flow and persistent device ID.

## Instrument

Use Flutter 3.47.5 / Dart 3.13.4, JDK 21, and a USB-C data cable from the
Android phone to the XIAO. The app requests USB permission and reconnects on
attach. Keep the bench firmware: the app supports both its four-colour output
and the repository's 1.1.0 protocol.

Fill with clear water and close the lid.
Tap Water ready and wait for five fresh color sweeps, about 50 seconds.
Add the pill and tap Start stirrer.
After the pill dissolves, tap Pill dissolved.
The app collects five new color sweeps and requests a stop after 60 seconds.
It waits for idle telemetry before classification.
Set `PEEL_RUN_SECONDS=0` to stop manually after five sample sweeps. The
legacy BOX-3 control firmware can also start/stop it; the new display-only
firmware mirrors the phone workflow. Temperature advice targets 37 ± 1.5 °C; a missing
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

Completed runs retain all raw readings and their session log path.
The app calls `/pill` with five water sweeps and five dissolved pill sweeps.
It forwards the returned classifier result and model to `/scans`.
The app stops on a classification request error and provides a retry.
Skip hardware omits hardware and continues research.
See [the capture contract and limits](../backend/pill-hardware.md).

## Animation

One shared Rive artboard (`assets/rive/peel_scan_flow.riv`, artboard
`PeelScan`, state machine `State Machine 1`, view-model number input `stage`)
is owned by `lib/rive/peel_rive_stage.dart` above the Navigator and painted
over whichever `PeelRiveSlot` is on screen (`lib/rive/peel_rive_widgets.dart`),
so it never restarts between screens. Stage mapping: bottle 0, pill 1,
connect 2, submerged 3, checking 4, complete 5, research 6, clear 7. It
hides while a dialog or sheet is up.

### Optional hardware display

The normal Peel app mirrors workflow stages through the Seeed USB connection to
the BOX-3 over radio when compatible firmware is connected. Use **Skip hardware**
on the device screen to continue without a hardware run. Skipping creates no
synthetic readings. See [firmware setup](../hardware/firmware/23_phone_display/README.md).

### Development entry points

`PEEL_START=device` opens the device step, `PEEL_START=debug` opens diagnostics,
and `PEEL_START=voice` retains the upstream voice test entry point.
`PEEL_SIM=10.0.2.2:9000` uses the full instrument simulator;
`PEEL_DEVICE_HOST=10.0.2.2` uses the display bridge on port 9001.
