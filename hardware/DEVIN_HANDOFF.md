# Devin handoff: have the signal path ready before the board arrives

## The situation

Peel reads a dissolving tablet with light. An **ESP32-S3-DevKitC-1** measures it and
streams one JSON reading a second over USB. An **Android phone** running the Flutter app
in `peel_app/` receives that stream and shows it live.

We are hardware-bottlenecked: the DevKitC is checked out but hasn't been in our hands long
enough to test against. **The goal is that when Leo plugs the board into the phone, the app
opens, connects and shows live readings, with no code changes on the day.** Everything
that can be proven without the physical board should be proven now, in simulation.

This is the plumbing, not the product. UI work, the backend link and classification come
later. Get the signals from the right place, correctly and robustly.

Read, in order: `docs/PROTOCOL.md` (the contract), `docs/HARDWARE.md` (parts, pins,
the USB chain), then this file.

## What exists, and what has actually been verified

| piece | state |
|---|---|
| `firmware/17_stream/17_stream.ino` | **Compiles** for the DevKitC (`esp32:esp32:esp32s3:CDCOnBoot=cdc,PSRAM=opi,FlashSize=8M`) and for `esp32:esp32:XIAO_ESP32S3`. Earlier versions ran on a XIAO bench rig. **Never run on a DevKitC.** |
| `peel_app/` | **Builds** a debug APK and **ran on the target phone** (Galaxy A16, Android 15) in Demo mode. **The USB path has never talked to a real board.** |
| `peel_app/test/widget_test.dart` | Parser tests against real firmware lines, a demo-protocol round trip, a widget test of a full demo run at 360 dp. **Written but never run.** |
| `peel_app/packages/usb_serial` | `usb_serial` 0.5.2, vendored. Its `build.gradle` used `jcenter()`, which Gradle 9 removed; the build file was rewritten and the Java is untouched. |
| `tools/peel_monitor.py` | Desktop reference client for the same stream (pyserial). Known to work against the XIAO. |

App layout: `reading.dart` (protocol parser), `link.dart` (`Link` interface, `UsbLink`,
`DemoLink`), `session.dart` (connection lifecycle, run tracking, CSV), `dashboard.dart`
(UI), `chart.dart` (dependency-free chart).

## Tasks, in order

Every task has an acceptance test. Don't mark a task done on reasoning alone; show it
running.

### 1. Get the existing tests green
Run `flutter test` in `peel_app/`. Fix real bugs in the code rather than loosening the
tests. If a test itself is wrong, say which one and why.
**Done when:** `flutter test` passes and `flutter analyze` is clean.

### 2. A virtual board that speaks the protocol exactly
`hardware/sim/fake_board.py`, stdlib only. It emits exactly what 17_stream emits (field
names, rounding, `null`s, `#` notes, `\r\n` on `println` lines) and obeys `b z a s m`,
including auto t = 0 on a 6 % transmission drop after a blank. Serve it:
- over **TCP** (for the app's tests), and
- over a **pseudo-terminal** (so `tools/peel_monitor.py /dev/pts/N` works against it unchanged).

Scripted scenarios, selectable by flag: normal dissolution run; stir on/off; no DS18B20
(`tC: null`); dark sensor (`absT: null`, and a `nan` variant for old firmware); boot noise
and a mid-line join; board resets mid-run (boot notes reappear, `t` back to -1);
disconnect mid-run; silence (the board hung).
**Done when:** `peel_monitor.py` shows a live run against the pty, and a test diffs the
simulator's output against `docs/PROTOCOL.md`.

### 3. A TCP transport in the app, tested against the virtual board
Add `TcpLink implements Link` (host and port). It is how we test on a VM, and it is also
the likely future **Wi-Fi** path, since the ESP32 has Wi-Fi. Keep `UsbLink` the default;
TCP is a developer option, hidden in the overflow menu.
**Done when:** a `flutter test` integration test drives `Session` over `TcpLink` against
`fake_board.py` for every scenario in task 2, and asserts what the user would see:
readings arrive, `run` resets on a new t = 0, a disconnect clears state with a clear
error, silence trips the stale warning, a board reset is survived.

### 4. Make `UsbLink`'s byte handling testable without USB
Separate the "bytes in → lines out" logic from the `UsbPort` so it can be fed fake chunks.
Test chunks split mid-line and mid-`\r\n`, one byte at a time, 64-byte USB packets,
more than 4 KB with no newline, latin-1 junk, and the port's stream closing.
**Done when:** those tests pass, and the real `UsbLink` uses the same tested code.

### 5. Make the USB path right for this specific board
Review `UsbLink` and `Session` against the actual hardware:
- **Driver selection** for all three possible devices: `0x303A` (native, CDC-ACM),
  CP210x `0x10C4`, CH34x `0x1A86`. The code tries auto-detect, then falls back to CDC.
  Confirm the vendored driver (felHR85 UsbSerial 6.1.0) actually handles the ESP32-S3's
  CDC interface (it also exposes a vendor-specific JTAG interface).
- **DTR/RTS**: the order and final state must never leave RTS asserted with DTR
  deasserted, because that resets an ESP32. Check what the driver does on `open()` itself.
- **Auto-connect** when the board is plugged in; `android/app/src/main/res/xml/device_filter.xml`
  has the vendor IDs. Handle the permission dialog, including denial, with a clear message.
- **Unplug and replug**: recovers without restarting the app.
- **Phone power**: if the board browns out when the stirrer starts, the user sees why, not just "No data".

**Done when:** each point is either covered by a test or written up in
`docs/PLUG_IN_DAY.md` as a thing to check on the day, with the expected result.

### 6. Firmware: ready for photoresistors, compiled in CI
- The build uses photoresistors (see `docs/HARDWARE.md`), which need about 600 ms to
  settle. The sweep's `SETTLE_MS = 12` was tuned for a TEMT6000. Add a compile-time sensor
  switch (for example `#define SENSOR_LDR 1`) that sets the sweep's settle time per colour.
  **Do not change the JSON line format**, and don't slow the 1 Hz fast channel.
- Compile for both FQBNs in CI.
- Stretch goal: run the real firmware in **Espressif's QEMU fork** (`qemu-system-xtensa
  -machine esp32s3`). Build with `CDCOnBoot=default` so `Serial` goes to UART0, which
  QEMU emulates (it doesn't emulate the native USB), expose UART0 over TCP, and point the
  task 3 tests at it. The ADC reads won't be meaningful; the point is proving the real
  binary boots, prints this protocol, and obeys commands. If it isn't achievable in
  reasonable time, write down what blocked it and stop.

### 7. CI
Add `.github/workflows/hardware.yml`, triggered only by changes under `hardware/**`. It
runs `flutter analyze`, `flutter test`, `flutter build apk --debug` (upload the APK as an
artifact), the simulator tests, and the firmware compiles.
**Done when:** it runs green on the branch.

### 8. Plug-in-day checklist
`docs/PLUG_IN_DAY.md`: every step from a bare DevKitC to a live reading on the phone.
That covers flashing from a Mac, the exact cable chain, which port, the permission
dialog, taking a blank, and the first run. At each step, give what you should see (the
board's `#` notes, the app's status) and what to do if you don't. Include wireless adb
for when the phone's USB port is busy hosting the board.

## Constraints

- **Do not edit the repository root `README.md`.** It says so, and it belongs to the team.
- Stay inside `hardware/`; the only exception is the one CI workflow file. The other
  folders (`backend/`, `docs/`, ...) belong to teammates.
- **The JSON line format is frozen.** The firmware, `peel_monitor.py` and the app all
  depend on it.
- Minimal UI changes. The UI gets built properly later.
- Avoid new Flutter plugins with native Android code. The stack is Flutter 3.47 /
  Gradle 9.3.1 / AGP 9, which broke `usb_serial`. Any new native plugin needs a
  `flutter build apk` proof.
- The Android emulator probably won't run on your VM (no KVM). That's fine: prove the
  logic with `flutter test` plus the virtual board, and prove the Android build compiles
  in CI.

## Environment

Flutter 3.47.5 stable, Gradle 9.3.1, AGP 9, JDK 21. Android `minSdk` is Flutter's
default; the target phone is SDK 35. Firmware: `arduino-cli` with the `esp32:esp32` core
and the `OneWire` and `DallasTemperature` libraries.

## Working agreement

- Branch off `hardware-component`, and open a PR back into `hardware-component`.
- One PR is fine, with one commit per task, so each can be reviewed alone.
- In the PR description, list what was verified by running it and what was not, and why.
  If something only a physical board can prove, say so plainly; don't fake it.
- If you are blocked on something only Leo can answer, ask; don't guess.
