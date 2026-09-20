# Hardware in hand

This is what the build is actually using at HackMIT: parts checked out from the hardware
desk, plus a few brought from home. It is not a wish list.

## Controller

**Espressif ESP32-S3-DevKitC-1-N8R8** (Espressif sponsor unit). Same chip as the Seeed
XIAO ESP32-S3 the firmware was first developed on, so the firmware runs on both.

- Two **micro-USB** ports: **USB** (the native USB-Serial/JTAG, where the firmware's
  `Serial` appears) and **UART** (via a bridge chip; silent with this build, but it can
  power the board).
- Build: `arduino-cli compile --fqbn "esp32:esp32:esp32s3:CDCOnBoot=cdc,PSRAM=opi,FlashSize=8M" firmware/17_stream`
- Libraries: `OneWire`, `DallasTemperature`.
- **Do not use:** GPIO 35–37 (octal PSRAM on the N8R8), 19/20 (USB), 43/44 (UART0), 0/45/46 (strapping pins).

## Pin map

The DevKitC plugs into a 400-point breadboard. It is wide enough to bury one header, so
everything is on the **J1** header.

| function | DevKitC GPIO | XIAO pin |
|---|---|---|
| red / yellow / green / blue LED, each through 220 Ω | 3 / 4 / 5 / 6 | D2 / D3 / D4 / D5 |
| DS18B20 data (4.7 k pull-up to 3V3) | 7 | D8 |
| transmission sensor | 8 | D9 |
| scatter sensor | 9 | D10 |
| stirrer PWM → TB6612 `PWMA` | 14 | D7 |

## Light sensors: photoresistors, not TEMT6000

HackMIT had no TEMT6000 phototransistors. The build uses **5 mm CdS photoresistors
(GL5539)** from the Elegoo kit, each in a divider: LDR from 3V3 to the pin, 10 k from the
pin to GND. More light means a higher voltage, the same polarity as the TEMT6000, so the
firmware and the protocol are unchanged.

Consequence: a photoresistor takes about **600 ms** to settle after the light changes.

- The fast channel is fine: the green LED stays on, so the light never switches.
- The four-colour **sweep is not fine**: `SETTLE_MS = 12` was tuned for the TEMT6000. See the handoff.

## Stirrer

Yellow **TT gear motor** (brought from home), driven by a **TB6612FNG**
(WWZMDiB module). The direction pins are hardwired, so the firmware only needs PWM:

| TB6612 pin | connect to |
|---|---|
| VM | 5V |
| VCC | 3V3 |
| GND | GND |
| STBY, AIN1 | 3V3 |
| AIN2 | GND |
| PWMA | GPIO 14 |
| AO1 / AO2 | motor |

The firmware drives PWM at 20 kHz with a 250 ms full-power kick to break stiction.

## Other parts on the bench

- **DS18B20** waterproof probes (Gikfun EK1083, 6 × 50 mm, 1 m cable)
- **ADS1115** 16-bit ADC (Lonely Binary 3-pack). **Not used by the firmware yet**, a future upgrade over the ESP32's ADC.
- **940 nm IR emitter/receiver pairs** (HiLetgo): future break-beam t = 0 and tachometer.
- LEDs (BOJACK 5-colour kit), resistor kit, jumpers, neodymium magnets (hub and stir bar).

## The USB chain to the phone

```
Samsung Galaxy A16 (SM-A165M, Android 15, USB-C)
  └─ USB-C (male) → USB-A (female) OTG adapter
       └─ USB-A → micro-USB cable
            └─ DevKitC port marked "USB"
```

- **Power:** a phone's OTG port supplies limited current. If the board resets when the
  stirrer kicks in, plug a charger into the DevKitC's **UART** port as well; the board
  takes power from either or both.
- **Debugging while the phone hosts the board:** the phone's only USB port is busy, so use
  wireless debugging (Developer options → Wireless debugging → `adb pair`, then
  `adb connect`).

## Build flags

Both are `#define`s at the top of `17_stream.ino`, overridable with `--build-property "build.extra_flags=-D..."`:

| flag | default | meaning |
|---|---|---|
| `SENSOR_LDR` | `1` | Photoresistor build: the sweep settles 700 ms per colour and runs every 30 s. Set `0` for a TEMT6000 rig. |
| `FAST_LED` | `2` (green) | Which LED lights the fast channel. Use the colour the active absorbs: `3` (blue) for riboflavin. |

The JSON line format does not change with either flag; the boot note reports the fast colour.
