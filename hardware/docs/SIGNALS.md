# Signals

Everything the instrument produces, where it comes from, and whether it is on the wire today.

## On the wire now (`firmware/17_stream`, one JSON line a second)

| key | source | unit | range seen | notes |
|---|---|---|---|---|
| `t` | `millis()` since t = 0 | s, 1 dp | −1.0, or 0 upward | −1.0 = no run in progress |
| `trans` | TEMT6000 on GPIO8, green LED on | mV | 0–3100 | mean of 24 ADC reads over ~6 ms. Floor ~91–150 mV |
| `scat` | TEMT6000 on GPIO9, green LED on | mV | 0–3100 | same |
| `absT` | `log10(blankT / trans)` | absorbance | null until a blank | null if either value ≤ 1 mV |
| `absS` | `log10(blankS / scat)` | absorbance | null until a blank | goes **negative** as turbidity rises; the app shows `−absS` |
| `tC` | DS18B20, 12-bit, non-blocking | °C, 2 dp | null if no probe | sentinels −127.0 and 85.0 are errors |
| `sweep.red` … `sweep.blue` | transmission under each LED minus dark | mV | negative with no optical path | every 10 s; null before the first |
| `stir` | firmware state | % | 0 or 100 | PWM duty, 20 kHz |
| `swept` | firmware state | bool | | true on the line a sweep ran in. **That line's `trans`/`scat` are disturbed** |

Notes (`# …` lines) carry events: boot banner, blank stored with its two values, t = 0 marked or
detected, auto t = 0 on/off, run stopped, stirrer on/off, radio up with channel and MAC, radio
channel drift. See `PROTOCOL.md`.

## Produced by the hardware but not on the wire yet

| signal | how to get it | reference implementation |
|---|---|---|
| IR and violet sweep values | pulse GPIO1 / GPIO2 like the other four | `18_selftest` drives all six |
| scatter under each LED | read GPIO9 during the sweep as well as GPIO8 | – |
| dark reading, both sensors | all LEDs off, read both; the sweep already does this for transmission and discards it | `17_stream` `doSweep()` |
| LED forward-drop voltages ×6 | pin to `INPUT_PULLUP`, read its own ADC channel | `18_selftest` command `d` |
| lock-in LED response | N on/off pairs, mean of differences | `18_selftest` `lockin()` |
| sensor noise | spread of consecutive 100 ms means | `18_selftest` `spread()` |
| reset reason | `esp_reset_reason()` | – |
| uptime, free heap, minimum free heap | `millis()`, `ESP.getFreeHeap()`, `ESP.getMinFreeHeap()` | – |
| DS18B20 presence, ROM address, device count | `DallasTemperature` | `18_selftest` |
| radio: channel, send failures, drift corrections | `esp_wifi_get_channel()`, `esp_now_send()` return, send callback | channel check is in `17_stream` `holdChannel()` |
| loop timing | time between reports; worst case | – |
| firmware identity | a version string and build date | – |

## Commands (one ASCII byte, over USB or ESP-NOW)

| byte | effect | note printed |
|---|---|---|
| `b` | store a blank from both sensors | `# blank stored: transmission N mV, scatter N mV` |
| `z` | mark t = 0 | `# t = 0 marked` |
| `a` | toggle automatic t = 0 (on at boot; 6 % drop in `trans` between two unswept lines, only after a blank) | `# auto t=0 on/off` |
| `s` | stop the run, `t` back to −1 | `# run stopped` |
| `m` | toggle the stirrer (on at boot) | `# stirrer on/off` |

## ESP-NOW packet (XIAO → BOX-3, once a second)

36 bytes, packed: `magic 'P'`, `version 1`, six floats `t trans scat absT absS tC` (NaN = null),
`uint16 sweep[4]` (0xFFFF = none; negative values wrap, so treat ≥ 0x8000 as invalid),
`uint8 stir`, `uint8 flags` (1 swept, 2 blank stored, 4 auto t = 0, 8 stirring).
