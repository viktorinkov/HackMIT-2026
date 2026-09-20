# Peel: hardware

The instrument side of Peel. A Seeed XIAO ESP32-S3 watches a tablet dissolve through light and
streams one reading a second over USB to an Android phone, which also powers it. An
ESP32-S3-BOX-3 in the wall of the orange is its face, linked over ESP-NOW.

```
firmware/17_stream/      XIAO firmware. The source of truth for the protocol.
firmware/18_selftest/    Bench diagnostic: lock-in LED test, diode check, noise.
firmware/21_box3_face/   The BOX-3's face: eyes, moods, one-button blank / start / stop.
firmware/19_box3_link/, 22_box3_probe/    Bring-up tools.
../mobile/               Product app with USB serial, parser, faults and session logs.
sim/                     fake_board.py: the XIAO in software, breakable on purpose.
tools/                   Desktop serial clients: peel_monitor.py, capture.py, flash_when_ready.py.
data/                    Real captures from this hardware.
```

The reference docs the code comments name (`PROTOCOL.md`, `SIGNALS.md`, `FAULTS.md`,
`BASELINES.md`, `PLUG_IN_DAY.md`) are kept off main: they are in `hardware/docs/` on the
`hardware-component` branch.

## Flash the board

```bash
arduino-cli compile --upload -p /dev/cu.usbmodemXXXX --fqbn esp32:esp32:XIAO_ESP32S3 firmware/17_stream
arduino-cli compile --upload -p /dev/cu.usbmodemYYYY --fqbn esp32:esp32:esp32s3box   firmware/21_box3_face
```

## Run the app

```bash
cd ../mobile
flutter build apk --debug
adb install -r build/app/outputs/flutter-apk/app-debug.apk
```

With no board plugged in, run the simulator and long-press the device screen title and press **Simulator** in the debug screen, with
`host:port` in the field beside it:

```bash
python3 sim/fake_board.py --tcp 9000
```

The demo board runs newer firmware than `firmware/17_stream`; do not flash it as
part of app setup. The app tolerates both dialects. Blank with clear water, then
start explicitly; `z` starts the stirrer and `s` stops it. A missing temperature
probe does not block a run. Sensor thresholds appear only in debug, never as a
pill verdict. Diagnostics are requested only when telemetry says idle, and polled
only if structured diagnostics have been received. Completed raw readings and
the log path are on `ScanSession.runReadings` and `ScanSession.runLogPath`.

Use Flutter 3.47.5 / Dart 3.13.4 and JDK 21. From `mobile/`, run `flutter analyze`,
`flutter test` (includes the TCP simulator and recorded device dialect), and
`flutter build apk`. The Android package remains `ai.peel.peel_app`. Use wireless
adb while the phone's USB port hosts the XIAO.
