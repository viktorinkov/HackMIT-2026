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
| `sweep.ir` … `sweep.violet` | transmission under each of the six LEDs minus dark | mV | negative with no optical path | every 10 s; null before the first |
| `sweepS.ir` … `sweepS.violet` | scatter under each LED minus dark | mV | a few percent of `sweep` when clear | same sweep, second sensor |
| `dark.trans`, `dark.scat` | both sensors, all LEDs off | mV | 91–150 lid shut, 300–830 lid open | measured at the start of every sweep |
| `stir` | firmware state | % | 0 or 100 | PWM duty, 20 kHz |
| `swept` | firmware state | bool | | true on the line a sweep ran in. **That line's `trans`/`scat` are disturbed** |

Notes (`# …` lines) carry events: boot banner, blank stored with its two values, t = 0 marked or
detected, auto t = 0 on/off, run stopped, stirrer on/off, radio up with channel and MAC, radio
channel drift. See `PROTOCOL.md`.

## Produced by the hardware but not on the wire yet

Everything below is now in the `{"diag":{…}}` line, printed once per `d` (see `PROTOCOL.md`):
LED forward drops ×6, sensor noise, dark readings, reset reason, uptime, heap, DS18B20
presence and address, radio channel / failures / drift, worst loop time, firmware identity,
and both sensors either side of the last stirrer toggle.

Still not on the wire:

| signal | how to get it | reference implementation |
|---|---|---|
| lock-in LED response | N on/off pairs, mean of differences | `18_selftest` `lockin()` |
| sampling with the motor gated off | stop the PWM, wait, sample, restart | – (`diag.gated` is reserved for it and reads `false`) |

## Commands (one ASCII byte, over USB or ESP-NOW)

| byte | effect | note printed |
|---|---|---|
| `b` | store a blank from both sensors | `# blank stored: transmission N mV, scatter N mV` |
| `z` | mark t = 0 | `# t = 0 marked` |
| `a` | toggle automatic t = 0 (on at boot; 6 % drop in `trans` between two unswept lines, only after a blank) | `# auto t=0 on/off` |
| `s` | stop the run, `t` back to −1 | `# run stopped` |
| `m` | toggle the stirrer (on at boot) | `# stirrer on/off` |
| `d` | print one diagnostics line after the next data line | – (the line itself is the answer) |

## ESP-NOW packet (XIAO → BOX-3, once a second)

36 bytes, packed: `magic 'P'`, `version 1`, six floats `t trans scat absT absS tC` (NaN = null),
`uint16 sweep[4]` — red, yellow, green, blue only, the four the version-1 packet has room for
(0xFFFF = none or negative, so treat ≥ 0x8000 as invalid) —
`uint8 stir`, `uint8 flags` (1 swept, 2 blank stored, 4 auto t = 0, 8 stirring).
