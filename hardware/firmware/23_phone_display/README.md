# Phone → Seeed → Peel display

The normal Peel app connects by USB to the Seeed XIAO, which forwards workflow
stages over ESP-NOW channel 1 to the BOX-3. The display mirrors the app; it does
not control navigation or pill verdicts. Hardware is optional: use **Skip hardware**
on the device screen to continue without a run or synthetic readings.

Flash `hardware/firmware/24_phone_relay` to the Seeed and this sketch to the BOX-3.
The relay preserves the working four-colour instrument firmware, 30% stirrer soft
start and disabled automatic detection. Back up existing firmware before flashing.

```sh
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 hardware/firmware/24_phone_relay
arduino-cli upload --fqbn esp32:esp32:XIAO_ESP32S3 --port <Seeed-port> hardware/firmware/24_phone_relay
arduino-cli compile --fqbn esp32:esp32:esp32s3box hardware/firmware/23_phone_display
arduino-cli upload --fqbn esp32:esp32:esp32s3box --port <BOX-3-port> hardware/firmware/23_phone_display
cd mobile
flutter build apk --release
```

Install the normal app, connect the phone to the Seeed, allow USB access, and
power the BOX-3 separately. No separate controller app is needed.

The Seeed advertises `displayRelay:2` in telemetry. Only then does the app send
newline-terminated `PHASE0` through `PHASE7` on its existing serial session.
Older firmware receives no display commands. Reconnecting resends the current
stage. Display failures never block app navigation.

| Phase | Display |
| --- | --- |
| 0 | Scan bottle |
| 1 | Scan pill |
| 2 | Connect Peel |
| 3 | Drop pill |
| 4 | Checking... |
| 5 | All done! |
| 6 | Working... |
| 7 | Results |

`HELLO` and `PEEL` remain available for bench testing at 115200 baud. The BOX-3
uses the original Peel artwork and dims during checking. Radio acknowledgement
occurs after rendering, with a numeric `scene` in the Seeed reply. Missing
acknowledgements produce `displayError` rather than success.

Shared four-byte packets are defined in `../display_protocol.h`. Requests retry
up to eight times with sequence and peer checks. Seeed MAC: `68:EE:8F:50:27:E8`;
BOX-3 MAC: `80:45:6B:64:89:18`. Update both sketches if boards change. Uppercase
display lines are isolated from single-character instrument commands.

For emulator testing, run the bridge from the repository root, then build the
same normal app with a development endpoint:

```sh
python3 hardware/sim/display_bridge.py --mock
# In another terminal:
cd mobile
flutter build apk --release --dart-define=PEEL_DEVICE_HOST=10.0.2.2
```

Replace `--mock` with `--serial <Seeed-port>` for real radio testing. The bridge
binds localhost, accepts only display commands, and refuses the BOX-3 serial port.
The phone in normal use needs neither the Mac nor bridge.

```sh
c++ -std=c++11 hardware/tests/display_protocol_test.cpp -o /tmp/display-protocol-test
/tmp/display-protocol-test
cd mobile && flutter analyze && flutter test
```
