# Devin brief: every signal, and the means to tell when one is lying

## What Peel is
A tablet dissolves in a stirred vial. Six LEDs shine through it; one light sensor looks straight
through (transmission), one looks from the side (scatter); a probe reads the temperature. A
**Seeed XIAO ESP32-S3** runs the measurement and streams it over **USB to an Android phone**. An
**ESP32-S3-BOX-3** in the wall of the enclosure is the instrument's face, linked by ESP-NOW.

The electronics are built and running. Everything in `docs/` and `data/` was measured on them.

## Read first, in this order
1. `docs/HARDWARE.md`: the overview and the index to everything else
2. `docs/PROTOCOL.md`: the contract on the wire
3. `docs/SIGNALS.md`: what exists, and what is not on the wire yet
4. `docs/BASELINES.md` and `docs/FAULTS.md`: the numbers and the failure signatures
5. `data/README.md`: real captures, including a full session in the exact protocol format

Then as needed: `PINMAP.md`, `WIRING.md`, `POWER.md`, `SYSTEM_SETTINGS.md`, `BOX3.md`, `ENCLOSURE.md`.

## The job
Build the layer between the hardware and a UI that someone else will design later: **firmware
that exposes every signal the device has, a connection that survives the real world, and an
on-phone backend that knows when the electronics are misbehaving.** Wrap it in a **mock app**.

Three boundaries set by the project owner. They are firm.

1. **No frontend logic.** One plain debug screen: values, faults, command buttons. Material
   defaults, no theming, no charts, no navigation.
2. **Do not tune the readings.** No calibration, smoothing, filtering or curve fitting, and no
   "corrected" values. Report what the hardware says, raw, plus the evidence for whether it can
   be trusted.
3. **Connect to the design as it is.** Pins, wiring and the existing protocol are fixed. Add to
   them; do not rename, remove or rearrange anything.

## What exists
| piece | state |
|---|---|
| `firmware/17_stream` | Runs on the XIAO. 1 Hz JSON over USB, four-colour sweep every 10 s, stirrer, DS18B20, automatic t = 0, ESP-NOW broadcast of every reading, commands accepted over USB and radio. |
| `firmware/18_selftest` | Runs on the XIAO. Bench diagnostic and the **reference implementation for the electrical checks**: 100 ms averaging, lock-in LED response, diode check, noise spread. |
| `firmware/21_box3_face` | Runs on the BOX-3. Consumes the ESP-NOW packet and sends commands. **Not in scope; do not break it.** |
| `firmware/19_box3_link`, `22_box3_probe` | Bring-up tools, for reference. |
| `peel_app/` | Flutter app. Builds and runs on the target phone in demo mode. **Its USB path has not yet talked to the board.** `reading.dart` (parser), `link.dart` (`Link`, `UsbLink`, `DemoLink`), `session.dart`, a dashboard. `usb_serial` is vendored. |
| `peel_app/test/` | Written, **never run**. |
| `tools/peel_monitor.py`, `tools/capture.py` | Desktop serial clients that work against the XIAO. |
| `data/` | Real captures. `session_full_cycle.jsonl` is a complete idle → blank → start → stir → stop session with host timestamps and the commands sent. |

## 1. Firmware: put every signal on the wire
`docs/SIGNALS.md` has the full list under *Produced by the hardware but not on the wire yet*.
In short:

- **Sweep all six LEDs**, not four: add `ir` (GPIO1) and `violet` (GPIO2) beside the existing
  keys. For every colour report **both** sensors. Report the **dark reading** of both sensors.
- **Electrical health**, from the MCU's own pins: the six LED forward-drop voltages (diode
  check), sensor noise, reset reason, uptime, heap, DS18B20 presence/address/error sentinels,
  radio channel / send failures / drift corrections, worst-case loop period, firmware version.
- **Motor coupling**, measured by the firmware itself: both sensors' means for 1 s before and
  after every stirrer toggle.

How it goes on the wire:
- The existing data line is **additive only**. The BOX-3 and `peel_monitor.py` parse it today.
- Put health in a **second line type**, `{"diag":{…}}`: at boot, on a new command `d`, and
  whenever a health value crosses a threshold. The 1 Hz data line stays small.
- New single-letter commands are fine. `b z a s m` are taken.
- Leave `PeelPacket` version 1 alone. If health ever needs to reach the face, add a second packet
  type with a different magic byte.
- The diode check briefly turns a pin into an input: never run it during a sweep or while that
  LED is the fast channel, and restore the pin afterwards. `18_selftest` shows how.
- `docs/PROTOCOL.md` and `docs/SIGNALS.md` change in the same commit as the protocol.

Out of scope in firmware: sampling with the motor gated off. The owner will add that separately.
Reserve a boolean `gated` in `diag` and report `false`.

## 2. Simulator: a board you can break on purpose
`hardware/sim/fake_board.py`, stdlib only, speaking the protocol **exactly**: field names,
rounding, nulls, `#` notes, `\r\n` on `println` lines, every command, the boot banner. Serve it
over **TCP** and over a **pty** so `tools/peel_monitor.py` runs against it unchanged.

- It can **replay `data/session_full_cycle.jsonl`** with its real timing.
- It can **inject every fault in `docs/FAULTS.md`** with the measured signature: motor coupling
  (both channels +150 mV erratic, or +2000 mV steady), brownout (banner reappears, blank lost),
  LED open (3300 mV), LED swapped, sensor unpowered, saturated, noisy, lid open, probe missing,
  probe error sentinels, temperature jitter, stale stream, line gap, wrong firmware, and mid-line
  joins and disconnects.
- A test diffs the simulator's healthy output against the real capture's line format.

## 3. Backend on the phone
"Backend" means the on-device data layer. No server.

- A typed model of **every** signal, parsed tolerantly: unknown keys ignored, `nan`/`inf` mapped
  to null field by field, fragments and boot noise dropped.
- A **fault engine**: pure functions from signal history to a list of active faults. Each has a
  stable id from `docs/FAULTS.md`, a severity, a one-line plain-English message, and its
  evidence (the values and the threshold). All thresholds live in one file, each with a comment
  naming the measurement in `docs/BASELINES.md` it came from. Do not invent thresholds.
- A **session log**: every raw line, parsed reading and fault transition to one JSONL file per
  session, exportable. It is how a bad demo gets diagnosed afterwards.
- A public API (streams or a repository) a future UI can consume without knowing USB exists.

## 4. Connection
- `UsbLink` on the XIAO's native USB: VID `0x303A`, CDC-ACM. The chip also exposes a JTAG
  interface; pick the right one. DTR then RTS; **never RTS asserted with DTR deasserted**, it
  holds the chip in reset. Check what the vendored driver does by itself on `open()`.
- Auto-connect on attach, the permission dialog including denial, unplug and replug without
  restarting the app, and a board reset in the middle of a session.
- "Bytes in → lines out" separated from the port and tested with fake chunks: split mid-line and
  mid-`\r\n`, one byte at a time, 64-byte packets, 4 KB with no newline, Latin-1 junk.
- `TcpLink` against the simulator, as a developer option only.

## 5. The mock app
Built on `peel_app/`. One screen: connection state, every signal with its raw value and age, the
active faults with their evidence, a button per command, export log. Nothing else.

## Proving it without hardware
- Every fault has a test driving `Session` over `TcpLink` against the simulator, asserting the
  engine raises exactly that fault and no other.
- Replaying `data/session_full_cycle.jsonl` raises only what is really in it: `NOT_ASSEMBLED`,
  `SWEPT_LINE` handling, `MOTOR_COUPLING` during 52–58 s, `TEMP_JITTER`, one `LINE_GAP`.
- Firmware compiles in CI for `esp32:esp32:XIAO_ESP32S3`, and `firmware/21_box3_face` still
  compiles for `esp32:esp32:esp32s3box`.
- `.github/workflows/hardware.yml`, triggered by `hardware/**` only: analyze, test, APK as an
  artifact, simulator tests, firmware compiles.
- Stretch: run the firmware in Espressif's QEMU fork with `Serial` on UART0. If it takes more
  than a couple of hours, write down what blocked it and stop.

## `docs/PLUG_IN_DAY.md`
From a bare XIAO to readings and faults on the phone: flash command, cable, the permission dialog,
wireless adb (the phone's one port is busy hosting the board), what each step should show and
what to do when it does not. End with a table: **fault shown → what to check on the breadboard**,
using the hole names in `docs/WIRING.md`.

## Constraints
- **Do not edit the repository root `README.md`.**
- Stay inside `hardware/`, except the one CI workflow file.
- **Never call `WiFi.begin()`** in any firmware: it moves the radio off channel 1 and the
  ESP-NOW link dies. Keep the channel-hold code as it is.
- Do not move pins. Do not change `firmware/21_box3_face`.
- No new Flutter plugin with native code unless `flutter build apk` proves it on this toolchain
  (Flutter 3.47.5, Gradle 9.3.1, AGP 9, JDK 21).
- The Android emulator will not run on your VM. Prove logic with `flutter test` against the
  simulator, and the build in CI.

## Order of work
There is a fixed budget. Finish each stage before starting the next; each is useful alone.
1. Firmware signals and the `diag` line. Compiles; protocol docs updated.
2. Simulator with replay and fault injection.
3. Backend: parser, fault engine, session log, tests green against the simulator.
4. `UsbLink` hardening and the mock screen. APK builds.
5. CI, then `PLUG_IN_DAY.md`.

## Working agreement
- Branch off `hardware-component`, PR back into it, one commit per stage, short messages.
- In the PR, list what was verified by running it and what was not, and why. If only a physical
  board can prove something, say so plainly.
- If blocked on something only Leo can answer about the hardware, ask. Do not guess.
