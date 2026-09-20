# Peel mobile

Android-only Flutter app built from the Peel Figma prototype
(`lPyn5YG33z3lPlWiaKjsK9`, page "Peel").

## Run

```bash
flutter pub get
flutter run                 # debug on a connected device or emulator
flutter build apk --debug   # build/app/outputs/flutter-apk/app-debug.apk
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
  a teal swell while Peel answers. Deepgram streaming (the official `deepgram_speech_to_text` Flutter
  example shape) turns on when a key is supplied:
  `flutter run --dart-define=DEEPGRAM_API_KEY=...`.
- Animations are text-only placeholders in the Rive slots, as the prototype
  specifies.
