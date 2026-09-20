# Plug-in day

The half hour where the board, the phone and the app meet for the first time. Do it in this
order; each step tells you what "working" looks like, so you know which one broke.

## 0. Before you touch the phone

Check the holes. Every one of these has cost an hour at some point (`WIRING.md`):

- **A a1 → B a8** and **A a2 → B a9**: IR and violet. The sweep now drives six colours, so a
  missing one of these shows up as `LED_OPEN` in the app instead of being invisible.
- **A i3 – i6**: the 5.1 kΩ DS18B20 pull-up. Without it `tC` is null forever and the app says
  `PROBE_MISSING`.
- **A i4** scatter SIG, **A i5** transmission SIG. Swapped, the two channels behave backwards:
  `trans` rises when you shade the beam.
- **Board B row 1 left** is 3V3 and **row 1 right** is GND. A sensor in the wrong one reads a
  flat few mV, which the app calls `SENSOR_UNPOWERED`.
- **A j1** carries 5 V to the motor rail. Pull it once the power bank feeds the motor
  (`POWER.md`), or the stirrer starting will brown the XIAO out and you will see
  `BROWNOUT_RESET` the first time you press **m**.

## 1. Flash the XIAO

```
arduino-cli core install esp32:esp32 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli lib install OneWire DallasTemperature
arduino-cli compile --upload -p <port> --fqbn esp32:esp32:XIAO_ESP32S3 firmware/17_stream
```

If the port never appears: hold **BOOT**, tap **RESET**, release **BOOT**, and upload again.
`tools/flash_when_ready.py` waits for the port and does it for you.

Check it on a laptop first, with `tools/peel_monitor.py` or any serial monitor at 115200. You
want the banner and then one JSON line a second:

```
# 17_stream ready. Fast channel = green LED. Stirrer 100%. Temperature probe: found
# commands: b blank, z mark t=0, a toggle auto t=0, s stop, m stirrer, d diagnostics
{"t":-1.0,"trans":2461,"scat":179,"absT":null,"absS":null,"tC":22.94,
 "sweep":{"ir":812,"red":898,"yellow":1291,"green":2455,"blue":1702,"violet":1094},
 "sweepS":{"ir":65,"red":71,"yellow":103,"green":196,"blue":135,"violet":87},
 "dark":{"trans":128,"scat":119},"stir":100,"swept":false}
```

Press **d** and you get one `{"diag":{…}}` line. Its `diode` numbers should climb
IR < red < yellow < green < blue < violet, near the values in `BASELINES.md`. Anything at
3300 mV is not in its holes; anything near zero is in backwards.

## 2. The cable

The phone has to be the USB **host**, so the XIAO must plug into it directly, not through a
laptop or a charger.

- A plain **USB-C to USB-C data** cable is what works. Charge-only cables are the usual
  culprit: the phone shows nothing at all, no permission dialog, no device.
- A USB-A OTG adapter plus the XIAO's own cable also works.
- A powered OTG hub is worth having if the phone drops the board when the stirrer starts:
  the motor is the largest load on the bus.

## 3. The Android permission dialog

Install the app (`flutter run`, or the `app-debug.apk` from CI), then plug in the board.

Android shows **"Allow the app to access the USB device?"** — tick *Use by default for this
USB device* and accept. The app connects on its own from then on, because the manifest has a
`USB_DEVICE_ATTACHED` filter for the three vendor IDs this hardware can appear as:
Espressif `0x303A` (the XIAO's native USB), CP210x `0x10C4` and CH34x `0x1A86` (either of the
USB-serial bridges, if you are on a board that has one).

If you deny it once, the app's top line reads `permission denied`. Unplug, replug, accept.

## 4. What the app should show

The debug screen, top to bottom:

- **connected**, the device name, and a line count that climbs once a second.
- Current `trans`, `scat`, `absT`, `absS`, `tC`.
- Six sweep values, and the dark reading, refreshed every ten seconds.
- **no faults** — an empty fault list is the pass condition.
- A diagnostics block: the app asks for one `d` shortly after connecting and every 30 s.

Then exercise it: **b** with clear water in the vial (a note comes back with both values),
drop the tablet, watch `t` leave −1 and `absT` climb. **m** toggles the stirrer; the one long
gap right after it is the motor's start ramp and is expected.

## 5. Wireless adb, so the USB port stays free

The phone's only USB port is holding the board, so run the app over Wi-Fi:

```
adb tcpip 5555                     # once, with the phone on USB
adb connect <phone-ip>:5555        # then unplug, plug in the XIAO
flutter run -d <phone-ip>:5555
```

On Android 11 and later you can skip the cable entirely: *Developer options → Wireless
debugging → Pair device with pairing code*, then `adb pair <ip>:<port>`.

## 6. When it does not work

| what you see | what it usually is |
|---|---|
| no permission dialog, no device | charge-only cable, or the phone is not acting as host |
| `permission denied` | the dialog was dismissed; unplug and replug |
| connected, but no lines | wrong sketch on the board — the app raises `WRONG_FIRMWARE`. Reflash `17_stream` |
| lines stop when the stirrer starts | the motor is browning out the board: power it from the bank, pull **A j1** |
| `tC` null | DS18B20 or its 5.1 kΩ pull-up; `diag.probe.count` is 0 |
| every sweep colour negative | no optical path — `NOT_ASSEMBLED`. The LEDs and sensors are not facing each other through the vial |
| both channels jump together on **m** | `MOTOR_COUPLING`: shared ground or supply with the motor (`POWER.md`) |
| board resets mid-run | `BROWNOUT_RESET`; `diag.reset` says `BROWNOUT` |

No board to hand? The app talks to `sim/fake_board.py` over TCP — **Simulator** in the app bar,
`host:port` of the machine running it (port 9000 if you leave it off):

```
python3 sim/fake_board.py --tcp 9000
python3 sim/fake_board.py --tcp 9000 --fault LED_OPEN:blue --fault-at 10
```
