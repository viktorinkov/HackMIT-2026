# Peel: hardware

The instrument side of Peel. A Seeed XIAO ESP32-S3 watches a tablet dissolve through light and
streams one reading a second over USB to an Android phone, which also powers it. An
ESP32-S3-BOX-3 in the wall of the orange is its face, linked over ESP-NOW.

```
firmware/17_stream/      XIAO firmware. The source of truth for the protocol.
firmware/18_selftest/    Bench diagnostic: lock-in LED test, diode check, noise.
firmware/21_box3_face/   The BOX-3's face: eyes, moods, one-button blank / start / stop.
firmware/19_box3_link/, 22_box3_probe/    Bring-up tools.
peel_app/                Flutter Android app: USB serial → parser → faults → session log.
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
cd peel_app
flutter build apk --debug
adb install -r build/app/outputs/flutter-apk/app-debug.apk
```

With no board plugged in, run the simulator and press **Simulator** in the app, with
`host:port` in the field beside it:

```bash
python3 sim/fake_board.py --tcp 9000
```
