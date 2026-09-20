# System settings

## Toolchain
| item | version |
|---|---|
| arduino-cli | Homebrew build, `/opt/homebrew/bin/arduino-cli` |
| esp32 Arduino core | 3.3.11 (`esp32:esp32`) |
| esptool | 5.3.1 (bundled with the core) |
| OneWire | 2.3.8 |
| DallasTemperature | 4.0.6 |
| GFX Library for Arduino | 1.6.7 (BOX-3 only) |
| Flutter | 3.47.5 stable |
| Gradle / AGP / JDK | 9.3.1 / 9 / 21 |
| usb_serial | 0.5.2, vendored in `peel_app/packages/usb_serial` with its `build.gradle` rewritten (no `jcenter()`) |

## Build targets
| board | FQBN | sketch | flash used |
|---|---|---|---|
| XIAO ESP32-S3 | `esp32:esp32:XIAO_ESP32S3` | `firmware/17_stream` | 871 kB of 3.3 MB (26 %), 45 kB RAM |
| XIAO ESP32-S3 | `esp32:esp32:XIAO_ESP32S3` | `firmware/18_selftest` | 290 kB (8 %) |
| ESP32-S3-BOX-3 | `esp32:esp32:esp32s3box` | `firmware/21_box3_face` | 928 kB of 3.1 MB (29 %) |

`esp32s3box` defaults: USB mode *Hardware CDC and JTAG*, partition scheme *16M Flash (3MB APP/9.9MB FATFS)*.
Upload and monitor: `arduino-cli compile --upload -p <port> --fqbn <FQBN> <sketch>`.
On the development Mac the XIAO enumerates as `/dev/cu.usbmodem101` and the BOX-3 as
`/dev/cu.usbmodem2101`; both report as "ESP32 Family Device".

## Serial
115200 8N1 (ignored by native USB, set anyway). Lines end `\n`; `println` lines end `\r\n`.
Open with DTR asserted, then RTS. **RTS asserted with DTR deasserted holds the chip in reset.**
Hard reset from a host: DTR low, RTS high for 150–250 ms, RTS low, DTR high. RTC memory does not
survive that reset.

## `17_stream` constants
| name | value | meaning |
|---|---|---|
| `SAMPLES` | 24 | ADC reads averaged per reported value, 150 µs apart: a window of about 6 ms |
| `SETTLE_MS` | 12 | wait after switching an LED |
| `REPORT_MS` | 1000 | data line period |
| `SWEEP_EVERY_MS` | 10000 | four-colour sweep period |
| `DROP_FRACTION` | 0.06 | automatic t = 0: fall in `trans` between two unswept lines |
| `STIR_PCT` | 100 | stirrer duty |
| `FAST_LED` | 2 (green) | the LED left on between sweeps |
| motor PWM | 20 kHz, 8 bit | start: 250 ms at full, then 40 → 100 % in 5 % steps of 100 ms: about 1.55 s, during which the loop is blocked |
| ADC | 12 bit, 11 dB attenuation, `analogReadMilliVolts()` | |
| DS18B20 | 12 bit, `setWaitForConversion(false)` | read, then request the next |
| state at boot | stirrer **on**, auto t = 0 **on**, no blank, `t = −1` | |

## `18_selftest` constants
100 ms window (250 samples, 400 µs apart). Lock-in: 6 pairs by default, 40 ms settle each way.
Keys: `r` rerun, `d` diode check, `x` IR lock-in ×20, `c` colour walk, `g` `i` `v` toggle
green / IR / violet, `m` motor 1.5 s, `M` motor on, `o` motor off.

## Radio
| setting | value |
|---|---|
| transport | ESP-NOW, unencrypted, broadcast `FF:FF:FF:FF:FF:FF` |
| channel | 1, `WIFI_SECOND_CHAN_NONE`, interface `WIFI_IF_STA` |
| Wi-Fi mode | `WIFI_STA`, never associated |
| hardening, both boards | `WiFi.persistent(false)`, `setAutoReconnect(false)`, `disconnect(false, true)`, `esp_wifi_set_ps(WIFI_PS_NONE)`, channel re-checked every second |
| forbidden | `WiFi.begin()` on either board: association moves the channel |
| XIAO MAC | `68:EE:8F:50:27:E8` |
| BOX-3 MAC | `80:45:6B:64:89:18` |
| rate | one 36-byte packet a second; commands are single bytes |

## BOX-3 face
| setting | value |
|---|---|
| display | `Arduino_ILI9342`, rotation 0, no inversion, on `Arduino_ESP32SPI` (default host and clock) |
| reset | library given **no** reset pin; GPIO48 driven high 20 ms then held low |
| framebuffer | `Arduino_Canvas` 320×240 RGB565 in PSRAM, flushed once per frame |
| frame rate | 20 fps with the radio up |
| backlight | 255 normally, **40 while a run is active** (the screen sits inside the optics) |
| palette | `#FF7A18` eyes, `#FFB24D` highlight, `#8A3B00` dim, black background only |
| link timeout | 5 s without a packet = no link |
| button | mute, GPIO1: tap = stirrer; hold 1.2 s = next step (blank → start → stop) |

## Android
Package `peel_app`, target device Galaxy A16 (SM-A165M), Android 15 / SDK 35.
`android/app/src/main/res/xml/device_filter.xml` vendor ids: 12346 (`0x303A` Espressif), 4292
(`0x10C4`), 6790 (`0x1A86`). Manifest declares USB host and the device-attached intent.
APK: `build/app/outputs/flutter-apk/app-debug.apk`.
