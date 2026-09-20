# Phone-controlled Peel display

A minimal BOX-3 build: the phone chooses the displayed greeting, and the ESP
renders the existing default Peel character. Boot shows **Hello!**. This sketch
has no ESP-NOW, sensor, motor, or touch-driven workflow.

Build/upload with the installed ESP32 Arduino core 3.3.11 and GFX Library for Arduino:

```sh
arduino-cli compile --fqbn esp32:esp32:esp32s3box hardware/firmware/23_phone_display
arduino-cli upload --fqbn esp32:esp32:esp32s3box --port <BOX-3-port> hardware/firmware/23_phone_display
```

Use only the BOX-3 port. Back up its flash before replacing existing firmware.
The display uses the proven active-high LCD reset, 320×240 framebuffer, and
unaltered ready-state RGB565 character/effect spans from the existing artwork.

USB protocol (115200 baud, newline-terminated):

- `HELLO` → default Peel with “Hello!”
- `PEEL` → default Peel with “Peel”
- Reply after drawing: `{"display":"peel","text":"Hello!","version":1}`
- Boot: `{"displayReady":1}`; current state is repeated every three seconds.
- Invalid/overlong commands are rejected without changing the screen.

Build the phone controller from `mobile/`:

```sh
flutter build apk --release -t lib/display_demo.dart
```

It uses the existing Android application ID, replacing the normal Peel app when
installed. Connect the phone directly to the BOX-3 with a USB data cable and
allow USB access. Install/debug over wireless adb while its USB port is occupied.
Rebuild `lib/main.dart` to return to the instrument app.

For an Android emulator, run a mock on the development computer:

```sh
python3 hardware/sim/display_bridge.py --mock
cd mobile
flutter build apk --release -t lib/display_demo.dart --dart-define=DISPLAY_HOST=10.0.2.2
```

To drive the physical display from the emulator, replace the mock process with
`python3 hardware/sim/display_bridge.py --serial <BOX-3-port>` and tap Reconnect.
This development bridge accepts only HELLO/PEEL and binds localhost. The physical
phone uses direct USB and does not need the computer or bridge.
