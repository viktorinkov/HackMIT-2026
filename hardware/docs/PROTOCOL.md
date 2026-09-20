# Board ↔ phone protocol

The firmware at `firmware/17_stream/17_stream.ino` is the source of truth. This page
describes what it prints today. If the two ever disagree, the firmware wins, and this
page is the bug.

## Transport

- USB serial, 115200 8N1. On the ESP32-S3's native USB port the baud rate is ignored; set it anyway.
- The board is a **Seeed XIAO ESP32-S3**. `Serial` is its native USB-Serial/JTAG, vendor ID
  `0x303A`, on its one USB-C port.
- Lines end in `\n`. Some lines are printed with `println`, which ends them in `\r\n`, so
  strip `\r`.
- The host opens the port the way a desktop serial monitor does: assert DTR, then assert
  RTS. On an ESP32 auto-reset circuit, RTS asserted with DTR deasserted holds the chip in
  reset. Never leave the lines in that state.
- The first line after connecting is often a fragment, because you joined mid-line. Drop
  anything that doesn't parse.

## Lines from the board

Two kinds of line. Anything else is noise: boot ROM output, fragments. Ignore it.

### Data line: one per second (`REPORT_MS = 1000`)

```json
{"t":12.0,"trans":1830,"scat":140,"absT":0.1240,"absS":-0.0430,"tC":37.02,
 "sweep":{"red":1200,"yellow":900,"green":2400,"blue":1700},"stir":100,"swept":false}
```

| field | type | meaning |
|---|---|---|
| `t` | number, 1 dp | Seconds since t = 0. **`-1.0` before a run starts** (or after `s`). |
| `trans` | number, whole mV | Transmission sensor: looks straight through the vial at the LEDs. Fast channel, lit continuously by the green LED. |
| `scat` | number, whole mV | Scatter sensor, 90° off the beam. |
| `absT` | number (4 dp) or `null` | `log10(blank / now)` on the transmission channel. `null` until a blank is taken, or if either value is ≤ 1 mV. |
| `absS` | number (4 dp) or `null` | Same formula, scatter channel. **Cloudier liquid scatters more light onto this sensor, so `absS` goes negative as turbidity rises.** The app plots `-absS` as "cloudiness". |
| `tC` | number (2 dp) or `null` | DS18B20 temperature in °C. `null` when no probe answered at boot. |
| `sweep` | object | Latest four-colour sweep: transmission mV under each LED, keys `red` `yellow` `green` `blue`. Each is `null` until the first sweep. Runs every `SWEEP_EVERY_MS = 10000`. |
| `stir` | integer | Stirrer PWM percent, or `0` when off. |
| `swept` | boolean | `true` if a sweep ran during this second. **That line's `trans` and `scat` are disturbed**: measured, `trans` falls to 0–218 mV from a 332 mV mean and `scat` rises to 197–386 mV from 54. Drop the line from any rate calculation. The firmware itself ignores swept lines for automatic t = 0. |

Parsers should still map a bare `nan` or `inf` to `null` field by field rather than reject the
line.

### Note line: human-readable, starts with `#`

| note | when |
|---|---|
| `# 17_stream ready. Fast channel = green LED. Stirrer 100%. Temperature probe: found` (or `absent, reporting null`) | boot |
| `# commands: b blank, z mark t=0, a toggle auto t=0, s stop, m stirrer` | boot |
| `# blank stored: transmission 2460 mV, scatter 180 mV` | after `b` |
| `# t = 0 marked` | after `z` |
| `# t = 0 detected from the transmission drop` | auto t = 0 fired |
| `# auto t=0 on` / `# auto t=0 off` | after `a` |
| `# run stopped` | after `s` |
| `# stirrer on` / `# stirrer off` | after `m` |

## Commands to the board

A single ASCII character. The board reads one character and discards anything else
waiting in the buffer, so send one command at a time.

| send | effect |
|---|---|
| `b` | Take a blank now: clear water in the vial, lid on. Enables `absT` / `absS`. |
| `z` | Mark t = 0 by hand. |
| `a` | Toggle auto t = 0. **On at boot.** Fires when transmission falls more than 6 % (`DROP_FRACTION`) between two **unswept** reports, and only after a blank. |
| `s` | Stop the run: `t` goes back to `-1`. |
| `m` | Toggle the stirrer. **Running at boot.** |

## State a host has to track itself

The board reports some state only through notes, so a host that connects mid-session can't
know it for sure:

- **auto t = 0**: assume on, as at boot, then follow the `auto t=0 on/off` notes.
- **blank**: known from the data line (`absT` is non-null).
- **run in progress**: known from the data line (`t >= 0`).

## The second link: ESP-NOW to the screen in the orange

The XIAO also broadcasts every reading over **ESP-NOW, channel 1, to `FF:FF:FF:FF:FF:FF`**, for
the ESP32-S3-BOX-3 that acts as the instrument's face. It is additive: the USB JSON above is
unchanged and remains the source of truth for the phone.

```c
struct __attribute__((packed)) PeelPacket {   // 36 bytes
  uint8_t  magic;        // 'P'
  uint8_t  version;      // 1
  float    t, trans, scat, absT, absS, tC;   // NAN where the JSON says null
  uint16_t sweep[4];     // red, yellow, green, blue in mV; 0xFFFF = not swept yet
  uint8_t  stir;         // percent
  uint8_t  flags;        // 1 swept, 2 blank stored, 4 auto t=0 on, 8 stirring
};
```

Commands come back the same way: **one ASCII byte**, the same letters as over USB
(`b z a s m`), broadcast. The XIAO feeds them into the same handler as serial input.

Rules that keep it alive: never call `WiFi.begin()` on either board; both hold the channel
(see `SYSTEM_SETTINGS.md`). If the packet ever has to change, bump `version` and update
`firmware/21_box3_face` in the same commit: it drops anything that is not version 1.

## Not in the protocol yet

The hardware has **six** LEDs (IR 940 on D0, violet on D1); `17_stream` sweeps four. The
diagnostics in `firmware/18_selftest` (diode check, lock-in, noise) are not reachable from
`17_stream`. `SIGNALS.md` lists every signal that exists but is not on the wire.

A real capture of this protocol, commands included, is in `../data/session_full_cycle.jsonl`.
