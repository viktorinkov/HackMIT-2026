# Phone → Seeed → Peel display

The phone connects by USB to the **Seeed XIAO**, which forwards display commands
over ESP-NOW channel 1 to the BOX-3. The BOX-3 only renders the default Peel
character and “Hello!” or “Peel”; it does not control the instrument workflow.

Flash the Seeed with `hardware/firmware/24_phone_relay` and the BOX-3 with this
sketch. The relay is based on the locally working four-colour bench firmware,
including its 30% stirrer setting, soft start and disabled automatic detection.
The repository's older `17_stream` and the original local files are unchanged.
Back up both boards before flashing.

```sh
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 hardware/firmware/24_phone_relay
arduino-cli upload --fqbn esp32:esp32:XIAO_ESP32S3 --port <Seeed-port> hardware/firmware/24_phone_relay
arduino-cli compile --fqbn esp32:esp32:esp32s3box hardware/firmware/23_phone_display
arduino-cli upload --fqbn esp32:esp32:esp32s3box --port <BOX-3-port> hardware/firmware/23_phone_display
```

USB commands to the Seeed (115200 baud, newline-terminated):

- `HELLO` → default Peel with “Hello!”
- `PEEL` → default Peel with “Peel”
- Reply only after the BOX-3 renders and acknowledges over radio:
  `{"display":"peel","text":"Hello!","version":1,"via":"seeed-radio"}`
- Missing radio acknowledgements produce `displayError`, never a success.

Display packets are separate four-byte requests/acknowledgements defined in
`../display_protocol.h`; existing instrument telemetry is unchanged. Requests
retry up to eight times, with sequence matching and peer MAC checks. Seeed MAC:
`68:EE:8F:50:27:E8`; BOX-3 MAC: `80:45:6B:64:89:18`. Update both sketches if the
boards change. Uppercase display lines are parsed separately from the existing
single-character instrument commands, so malformed display text cannot trigger
a stirrer command. The BOX-3 retains direct USB commands for bench testing only.

Build the controller from `mobile/`:

```sh
flutter build apk --release -t lib/display_demo.dart
```

This entry point uses the existing Android package ID and replaces the normal
Peel app when installed. Connect the phone to the **Seeed**, allow USB access,
and power the BOX-3 separately. Install/debug over wireless adb when the phone's
USB port is occupied. Build `lib/main.dart` to restore the normal instrument UI.

For emulator testing, from the repository root:

```sh
python3 hardware/sim/display_bridge.py --mock
cd mobile
flutter build apk --release -t lib/display_demo.dart --dart-define=DISPLAY_HOST=10.0.2.2
```

For the real radio path, replace the mock with
`python3 hardware/sim/display_bridge.py --serial <Seeed-port>` and tap Reconnect.
The development bridge binds localhost and accepts only HELLO/PEEL. It refuses
the BOX-3 serial port. The phone in normal use needs neither the Mac nor bridge.

Validation:

```sh
c++ -std=c++11 hardware/tests/display_protocol_test.cpp -o /tmp/display-protocol-test
/tmp/display-protocol-test
cd mobile && flutter analyze && flutter test
```

The screen uses the proven active-high LCD reset, 320×240 framebuffer and
unaltered ready-state RGB565 character/effect spans from the existing artwork.
