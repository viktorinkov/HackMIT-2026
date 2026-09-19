# Peel: hardware

The instrument side of Peel. An ESP32-S3 watches a tablet dissolve through light and
streams one reading a second over USB. An Android app shows the readings live.

```
firmware/17_stream/     ESP32-S3 firmware (Arduino). The source of truth for the protocol.
peel_app/               Flutter Android app: USB OTG serial → parser → live dashboard.
tools/peel_monitor.py   Desktop reference client: the same stream as a terminal dashboard, plus CSV.
docs/PROTOCOL.md        The line protocol between the board and the phone.
docs/HARDWARE.md        Parts in hand, pin map, wiring, the USB chain to the phone.
DEVIN_HANDOFF.md        Current task: have the signal path ready before the board arrives.
```

## Flash the board

```bash
arduino-cli compile --upload -p /dev/cu.usbmodemXXXX \
  --fqbn "esp32:esp32:esp32s3:CDCOnBoot=cdc,PSRAM=opi,FlashSize=8M" firmware/17_stream
```

## Run the app

```bash
cd peel_app
flutter build apk --debug
adb install -r build/app/outputs/flutter-apk/app-debug.apk
```

With no board plugged in, open the ⋮ menu and choose **Demo mode**. It runs a simulated
tablet through the same parser.
