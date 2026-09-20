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
- Device connection, pill check and report submission are timed placeholders.
- Chat replies are canned.
- Voice chat cycles listening → thinking → speaking over a `waveform_flutter`
  bar waveform (`lib/widgets/voice_waveform.dart`), which gives each state its
  own colour and motion: orange jitter for you, a grey pulse while Peel thinks,
  a teal swell while Peel answers. Voice is mocked; the planned integration
  is the backend's `POST /deepgram/session` (Deepgram Voice Agent) — no key
  ships in the app.

## Backend

The app does not call the backend yet. `lib/data/mock_data.dart`
(`MockBackend`) and `lib/state/scan_session.dart` are the seams for
`POST /scans`, `POST /reports` and `POST /deepgram/session`.

## Animation

One shared Rive artboard (`assets/rive/peel_scan_flow.riv`, artboard
`PeelScan`, state machine `State Machine 1`, view-model number input `stage`)
is owned by `lib/rive/peel_rive_stage.dart` above the Navigator and painted
over whichever `PeelRiveSlot` is on screen (`lib/rive/peel_rive_widgets.dart`),
so it never restarts between screens. Stage mapping: bottle 0, pill 1,
connect 2, submerged 3, checking 4, complete 5, research 6, clear 7. It
hides while a dialog or sheet is up.
