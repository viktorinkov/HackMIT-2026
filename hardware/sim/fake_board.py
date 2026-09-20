#!/usr/bin/env python3
"""A XIAO running 17_stream, in software, that can be broken on purpose.

Speaks the protocol in ../docs/PROTOCOL.md byte for byte: the same field names and rounding,
`null` where the firmware prints null, `#` notes, `\\r\\n` on the lines the firmware sends with
`println` and `\\n` on the ones it sends with `printf`, the same one-letter commands and the
same boot banner. `tools/peel_monitor.py` runs against it unchanged.

Serve it over TCP, over a pty, or write it to a file:

    python3 fake_board.py --tcp 9999
    python3 fake_board.py --pty                       # prints the slave device path
    python3 fake_board.py --stdout --for 20 --speed 50

Break it on purpose, with the ids from ../docs/FAULTS.md:

    python3 fake_board.py --tcp 9999 --fault MOTOR_COUPLING:dc
    python3 fake_board.py --tcp 9999 --fault LED_OPEN:blue --fault-at 5
    python3 fake_board.py --tcp 9999 --control 9998   # then send "fault LID_OPEN" a line at a time

Or replay a real capture with its real timing:

    python3 fake_board.py --tcp 9999 --replay ../data/session_full_cycle.jsonl

Standard library only, Python 3.10+.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import selectors
import socket
import sys
import time


# ---------------------------------------------------------------- what the board is made of
#
# Healthy numbers are an instrument in its enclosure: an optical path exists, the probe is
# quiet, the sweep is positive. Fault numbers come from ../docs/BASELINES.md and are named
# where they are used. Nothing here is fitted to anything; it is the shape of the signal.

CLEAR_T = 2460.0  # resting transmission with clear water, mV
CLEAR_S = 180.0  # resting scatter, mV
DARK_T = 128.0  # lid shut, all LEDs off: inside the 91-150 mV ADC floor (BASELINES.md)
DARK_S = 119.0
A_INF, K_RATE = 0.42, 1 / 90.0  # plateau absorbance and rate of the model tablet

COLOURS = ("ir", "red", "yellow", "green", "blue", "violet")
SWEEP_BASE = {"ir": 820.0, "red": 900.0, "yellow": 1300.0, "green": 2460.0,
              "blue": 1700.0, "violet": 1100.0}
# How strongly the model tablet absorbs each colour relative to green: a yellow compound
# eats blue. Only the shape matters.
SWEEP_GAIN = {"ir": 0.02, "red": 0.05, "yellow": 0.2, "green": 0.6, "blue": 2.2, "violet": 2.6}
SWEEP_SCATTER_FRACTION = 0.08  # the 90-degree sensor sees a little of every colour

# Forward-drop node voltage at ~70 uA, measured on this build (BASELINES.md).
DIODE_MV = {"ir": 246, "red": 547, "yellow": 624, "green": 1208, "blue": 1510, "violet": 1763}

REPORT_MS = 1000
SWEEP_EVERY_MS = 10000
STIR_PCT = 100
DROP_FRACTION = 0.06
FIRMWARE = "17_stream+diag"
VERSION = "1.1.0"
BUILD = "2026-09-20"
MAC = "34:85:18:91:2C:D4"

FAULT_IDS = (
    "MOTOR_COUPLING", "NOT_ASSEMBLED", "LED_OPEN", "LED_SHORT", "LED_SWAPPED",
    "SENSOR_UNPOWERED", "SENSOR_SATURATED", "SENSOR_NOISY", "LID_OPEN", "PROBE_MISSING",
    "PROBE_ERROR", "TEMP_JITTER", "BROWNOUT_RESET", "STREAM_STALE", "LINE_GAP",
    "RADIO_DRIFT", "RADIO_DOWN", "WRONG_FIRMWARE",
)


def fmt(value: float | None, places: int) -> str:
    """What `printNum` in the firmware prints: `null` for NaN and infinity."""
    if value is None or math.isnan(value) or math.isinf(value):
        return "null"
    return f"{value:.{places}f}"


class Board:
    """The state machine in 17_stream, plus the diagnostics of 18_selftest.

    Time is passed in, never read, so a test can run a session in milliseconds.
    """

    def __init__(self, faults: dict[str, str] | None = None, seed: int = 7,
                 diag: bool = True, assembled: bool = True) -> None:
        self.faults: dict[str, str] = dict(faults or {})
        self.rng = random.Random(seed)
        self.diag_enabled = diag
        self.assembled = assembled
        self.out: list[str] = []
        self.boot(reset_reason="POWERON")

    # ---------------------------------------------------------------- lines out
    def _printf(self, text: str) -> None:
        """A line the firmware prints with `Serial.printf`: it ends in \\n."""
        self.out.append(text + "\n")

    def _println(self, text: str = "") -> None:
        """A line the firmware prints with `Serial.println`: it ends in \\r\\n."""
        self.out.append(text + "\r\n")

    def drain(self) -> bytes:
        data = "".join(self.out).encode("latin-1")
        self.out.clear()
        return data

    def has(self, fault: str) -> bool:
        return fault in self.faults

    def arg(self, fault: str, default: str = "") -> str:
        return self.faults.get(fault) or default

    # ---------------------------------------------------------------- state
    def boot(self, reset_reason: str) -> None:
        self.reset_reason = reset_reason
        self.boot_ms = 0.0
        self.now_ms = 0.0
        self.last_report_ms = -REPORT_MS
        self.last_sweep_ms = -SWEEP_EVERY_MS
        self.blank_t: float | None = None
        self.blank_s: float | None = None
        self.zero_ms: float | None = None
        self.auto_zero = True
        self.stirring = True
        self.swept_this_line = False
        self.last_trans = 0.0
        self.sweep: dict[str, float | None] = {c: None for c in COLOURS}
        self.sweep_s: dict[str, float | None] = {c: None for c in COLOURS}
        self.dark = {"trans": None, "scat": None}
        self.loop_max_us = 1100
        self.radio_fail = 0
        self.radio_drift = 0
        self.stir_change_ms: float | None = None
        self.motor_before: dict[str, float] | None = None
        self.motor_after: dict[str, float] | None = None
        self.diag_pending = self.diag_enabled
        self.pending_gap_ms = 0.0
        self.reports = 0
        self.have_probe = not self.has("PROBE_MISSING")

        if self.has("WRONG_FIRMWARE"):
            self._println()
            self._printf("# 18_selftest ready. Commands: d diode check, l lock-in, n noise")
            return
        self._println()
        self._printf(
            f"# 17_stream ready. Fast channel = green LED. Stirrer {STIR_PCT}%. "
            f"Temperature probe: {'found' if self.have_probe else 'absent, reporting null'}")
        self._println("# commands: b blank, z mark t=0, a toggle auto t=0, s stop, m stirrer, d diagnostics")
        self._printf(f"# esp-now up on channel 1, this board is {MAC}")

    # ---------------------------------------------------------------- the signal
    def _noise(self, sd: float) -> float:
        return (self.rng.random() + self.rng.random() - 1) * sd

    @property
    def elapsed_s(self) -> float:
        return -1.0 if self.zero_ms is None else (self.now_ms - self.zero_ms) / 1000.0

    def _absorbance_now(self) -> tuple[float, float]:
        """Absorbance and cloudiness of the model tablet at this instant."""
        t = self.elapsed_s
        if t < 0:
            return 0.0, 0.0
        absorbance = A_INF * (1 - math.exp(-K_RATE * t))
        cloud = 0.30 * (t / 40) * math.exp(1 - t / 40) + 0.04 * (1 - math.exp(-K_RATE * t))
        return absorbance, cloud

    def _sensors(self) -> tuple[float, float]:
        """The two fast-channel readings this second, with every active fault applied."""
        absorbance, cloud = self._absorbance_now()
        trans = CLEAR_T * 10 ** -absorbance + self._noise(4)
        scat = CLEAR_S * 10 ** cloud + self._noise(2)

        if self.has("LID_OPEN"):
            # Room light on the sensors: an open bench reads 300-830 mV (BASELINES.md).
            trans += 420
            scat += 420
        if self.has("SENSOR_NOISY"):
            # Hand-held, loose jumper: 207-267 mV of spread on a still sensor.
            trans += self._noise(60)
            scat += self._noise(60)
        if self.stirring and self.has("MOTOR_COUPLING"):
            if self.arg("MOTOR_COUPLING", "erratic") == "dc":
                trans += 2000  # motor_coupling_dc.csv: both channels +2000 mV, steady
                scat += 2000
            else:
                trans += 150 + self._noise(60)  # session_full_cycle.csv, 52-58 s
                scat += 150 + self._noise(60)
        if self.swept_this_line:
            # Measured on seven of seven sweeps: trans collapses, scat rises.
            trans, scat = 66 + self._noise(80), 258 + self._noise(80)

        if self.has("SENSOR_UNPOWERED"):
            target = self.arg("SENSOR_UNPOWERED", "trans")
            if target in ("trans", "both"):
                trans = 12.0
            if target in ("scat", "both"):
                scat = 12.0
        if self.has("SENSOR_SATURATED"):
            target = self.arg("SENSOR_SATURATED", "trans")
            if target in ("trans", "both"):
                trans = 3100.0
            if target in ("scat", "both"):
                scat = 3100.0
        return max(0.0, trans), max(0.0, scat)

    def _temperature(self) -> float | None:
        if not self.have_probe:
            return None
        if self.has("PROBE_ERROR"):
            return -127.0 if self.arg("PROBE_ERROR", "-127") == "-127" else 85.0
        if self.has("TEMP_JITTER"):
            return 22.0 + self._noise(1.5)  # radio on: up to +-1.5 C between seconds
        return 22.0 + self._noise(0.05)  # radio off: steady to 0.06 C

    def _do_sweep(self) -> None:
        absorbance, _ = self._absorbance_now()
        dark_t, dark_s = DARK_T, DARK_S
        if self.has("LID_OPEN"):
            dark_t, dark_s = 620.0, 610.0
        self.dark = {"trans": round(dark_t + self._noise(4)), "scat": round(dark_s + self._noise(4))}
        for colour in COLOURS:
            if self.assembled and not self.has("NOT_ASSEMBLED"):
                lit = SWEEP_BASE[colour] * 10 ** (-absorbance * SWEEP_GAIN[colour]) + self._noise(5)
            else:
                # No optical path: every colour comes out negative (data/README.md).
                lit = -200 + self._noise(60)
            if self.has("LED_OPEN") and colour == self.arg("LED_OPEN", "blue"):
                lit = self._noise(6)  # the LED never lights, so the sweep sees only dark
            self.sweep[colour] = round(lit)
            self.sweep_s[colour] = round(lit * SWEEP_SCATTER_FRACTION + self._noise(4))
        self.swept_this_line = True

    def diode_check(self) -> dict[str, int]:
        drops = {c: DIODE_MV[c] + int(self._noise(6)) for c in COLOURS}
        if self.has("LED_OPEN"):
            drops[self.arg("LED_OPEN", "blue")] = 3300  # open or reversed
        if self.has("LED_SHORT"):
            drops[self.arg("LED_SHORT", "red")] = 21
        if self.has("LED_SWAPPED"):
            a, b = (self.arg("LED_SWAPPED", "green:blue").split(":") + ["blue"])[:2]
            drops[a], drops[b] = drops[b], drops[a]
        return drops

    # ---------------------------------------------------------------- commands
    def command(self, char: str) -> None:
        if self.has("WRONG_FIRMWARE"):
            if char == "d":
                self._printf("diode check: " + "  ".join(
                    f"{c} {mv} mV" for c, mv in self.diode_check().items()))
            return
        if char == "b":
            trans, scat = self._sensors()
            self.blank_t, self.blank_s = trans, scat
            self._printf(
                f"# blank stored: transmission {trans:.0f} mV, scatter {scat:.0f} mV")
        elif char == "z":
            self.zero_ms = self.now_ms
            self._println("# t = 0 marked")
        elif char == "a":
            self.auto_zero = not self.auto_zero
            self._printf(f"# auto t=0 {'on' if self.auto_zero else 'off'}")
        elif char == "s":
            self.zero_ms = None
            self._println("# run stopped")
        elif char == "m":
            self.stirring = not self.stirring
            self.stir_change_ms = self.now_ms
            self.motor_before = self._motor_means()
            self.motor_after = None
            self._println("# stirrer on" if self.stirring else "# stirrer off")
            if self.stirring:
                # The start ramp blocks the loop: one 2.2 s line gap, every time.
                self.pending_gap_ms += 1200
        elif char == "d":
            self.diag_pending = True

    def _motor_means(self) -> dict[str, float]:
        trans, scat = self._sensors()
        return {"trans": round(trans), "scat": round(scat)}

    # ---------------------------------------------------------------- the clock
    def advance_to(self, now_ms: float) -> None:
        """Run the loop up to `now_ms`, appending whatever the board would have printed."""
        while True:
            due = self.last_report_ms + REPORT_MS + self.pending_gap_ms
            sweep_due = self.last_sweep_ms + SWEEP_EVERY_MS
            if sweep_due <= min(due, now_ms):
                self.now_ms = sweep_due
                self.last_sweep_ms = sweep_due
                self._do_sweep()
                continue
            if due > now_ms:
                self.now_ms = now_ms
                return
            self.now_ms = due
            self.last_report_ms = due
            self.pending_gap_ms = 0.0
            self.reports += 1
            if self.has("LINE_GAP") and self.reports % 5 == 0:
                # Something blocked the loop for as long as the stirrer's start ramp does.
                self.pending_gap_ms += 1200
            self._report()

    def next_due_ms(self) -> float:
        return min(self.last_report_ms + REPORT_MS + self.pending_gap_ms,
                   self.last_sweep_ms + SWEEP_EVERY_MS)

    def _report(self) -> None:
        if self.has("STREAM_STALE"):
            return
        if self.has("WRONG_FIRMWARE"):
            trans, scat = self._sensors()
            temp = self._temperature()
            self._printf(f"trans {trans:4.0f} mV   scat {scat:4.0f} mV   "
                         f"tC {'--' if temp is None else f'{temp:.2f}'}")
            return
        if self.has("RADIO_DOWN"):
            # esp_now_send() keeps returning an error: the packets never leave this board.
            self.radio_fail += 5
        if self.has("RADIO_DRIFT") and self.radio_drift == 0:
            self.radio_drift = 1
            self._printf("# radio had drifted to channel 6, pulled back to 1")

        trans, scat = self._sensors()
        if not self.swept_this_line:
            if (self.auto_zero and self.zero_ms is None and self.blank_t is not None
                    and self.last_trans > 1 and trans < self.last_trans * (1 - DROP_FRACTION)):
                self.zero_ms = self.now_ms
                self._println("# t = 0 detected from the transmission drop")
            self.last_trans = trans

        if (self.stir_change_ms is not None and self.motor_after is None
                and self.now_ms - self.stir_change_ms >= 1000):
            self.motor_after = {"trans": round(trans), "scat": round(scat)}

        abs_t = self._abs(self.blank_t, trans)
        abs_s = self._abs(self.blank_s, scat)
        temp = self._temperature()

        parts = [f'"t":{self.elapsed_s:.1f}', f'"trans":{trans:.0f}', f'"scat":{scat:.0f}']
        if self.blank_t is not None:
            parts += [f'"absT":{fmt(abs_t, 4)}', f'"absS":{fmt(abs_s, 4)}']
        else:
            parts += ['"absT":null', '"absS":null']
        parts.append('"tC":null' if temp is None else f'"tC":{temp:.2f}')
        parts.append('"sweep":{' + ",".join(
            f'"{c}":{"null" if self.sweep[c] is None else f"{self.sweep[c]:.0f}"}'
            for c in COLOURS) + "}")
        parts.append('"sweepS":{' + ",".join(
            f'"{c}":{"null" if self.sweep_s[c] is None else f"{self.sweep_s[c]:.0f}"}'
            for c in COLOURS) + "}")
        parts.append('"dark":{' + ",".join(
            f'"{k}":{"null" if v is None else f"{v:.0f}"}' for k, v in self.dark.items()) + "}")
        parts.append(f'"stir":{STIR_PCT if self.stirring else 0}')
        parts.append(f'"swept":{"true" if self.swept_this_line else "false"}')
        self._printf("{" + ",".join(parts) + "}")

        self.swept_this_line = False
        if self.diag_pending:
            self.diag_pending = False
            self._emit_diag()

    @staticmethod
    def _abs(blank: float | None, now: float) -> float | None:
        if blank is None or blank <= 1 or now <= 1:
            return None
        return math.log10(blank / now)

    def _emit_diag(self) -> None:
        if not self.diag_enabled:
            return
        noise = 44 if not self.has("SENSOR_NOISY") else 212  # 100 ms means, peak to peak
        diag = {
            "fw": FIRMWARE, "ver": VERSION, "build": BUILD,
            "reset": self.reset_reason,
            "up": int(self.now_ms),
            "heap": 211000, "heapMin": 198500,
            "loopMax": self.loop_max_us,
            "gated": False,
            "dark": {"trans": self.dark["trans"], "scat": self.dark["scat"]},
            "diode": self.diode_check(),
            "noise": {"trans": noise, "scat": noise},
            "probe": {
                "present": self.have_probe,
                "count": 1 if self.have_probe else 0,
                "addr": "28FF641E8C1A03C7" if self.have_probe else None,
            },
            "radio": {
                "ch": 1,
                "fail": self.radio_fail,
                "drift": self.radio_drift,
                # Broadcasts are unacknowledged, so the only proof the face is alive is the
                # face talking back. It never does while the radio is down.
                "heard": None if self.has("RADIO_DOWN") else 1200,
            },
            "motor": {
                "stir": STIR_PCT if self.stirring else 0,
                "transBefore": None if self.motor_before is None else self.motor_before["trans"],
                "transAfter": None if self.motor_after is None else self.motor_after["trans"],
                "scatBefore": None if self.motor_before is None else self.motor_before["scat"],
                "scatAfter": None if self.motor_after is None else self.motor_after["scat"],
            },
        }
        self._printf(json.dumps({"diag": diag}, separators=(",", ":")))

    def brownout(self) -> None:
        """The supply sagged: the board resets and everything it was holding is gone."""
        self.faults.pop("BROWNOUT_RESET", None)
        self.boot(reset_reason="BROWNOUT")


class Replay:
    """The XIAO's side of a capture, played back with the timing it was recorded at."""

    def __init__(self, path: str, loop: bool = False) -> None:
        self.lines: list[tuple[float, str]] = []
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                entry = json.loads(raw)
                if entry.get("src") != "xiao" or entry.get("dir") != "rx":
                    continue
                self.lines.append((float(entry["t_host"]), entry["line"]))
        if not self.lines:
            raise SystemExit(f"{path}: no xiao lines to replay")
        self.loop = loop
        self.index = 0
        self.epoch_ms = 0.0

    def next_due_ms(self) -> float:
        if self.index >= len(self.lines):
            return math.inf
        return self.epoch_ms + self.lines[self.index][0] * 1000

    def advance_to(self, now_ms: float) -> bytes:
        out: list[str] = []
        while self.index < len(self.lines) and self.next_due_ms() <= now_ms:
            line = self.lines[self.index][1]
            # Notes were printed with println, data lines with printf.
            out.append(line + ("\r\n" if line.startswith("#") else "\n"))
            self.index += 1
            if self.index >= len(self.lines) and self.loop:
                self.index = 0
                self.epoch_ms = now_ms
        return "".join(out).encode("latin-1")


# ---------------------------------------------------------------- serving it
class Corrupter:
    """The transport, misbehaving: joins mid-line, one byte at a time, or nothing at all."""

    def __init__(self, chunk: int = 0, junk: bool = False) -> None:
        self.chunk = chunk
        self.junk = junk
        self.first = True

    def __call__(self, data: bytes) -> list[bytes]:
        if self.first:
            self.first = False
            if self.junk:
                # What joining a running board looks like: the tail of a line, then ROM noise.
                data = b'0,"swept":false}\n\xfe\x01ESP-ROM:esp32s3-20210327\n' + data
        if self.chunk <= 0:
            return [data]
        return [data[i:i + self.chunk] for i in range(0, len(data), self.chunk)]


class Runner:
    """Drives a board (or a replay) and one connection at a time."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.speed = args.speed
        self.faults = parse_faults(args.fault)
        self.delayed = {f: a for f, a in self.faults.items()} if args.fault_at else {}
        start_faults = {} if args.fault_at else self.faults
        self.board = Board(start_faults, seed=args.seed, diag=not args.no_diag,
                           assembled=not args.bench)
        self.replay = Replay(args.replay, loop=args.loop) if args.replay else None
        self.corrupter = Corrupter(args.chunk, args.junk)
        self.start = time.monotonic()
        self.brownout_at = args.brownout_at

    def board_ms(self) -> float:
        return (time.monotonic() - self.start) * 1000 * self.speed

    def pending(self) -> bytes:
        now = self.board_ms()
        if self.delayed and now >= self.args.fault_at * 1000:
            self.board.faults.update(self.delayed)
            self.board.have_probe = not self.board.has("PROBE_MISSING")
            self.delayed = {}
        if self.brownout_at is not None and now >= self.brownout_at * 1000:
            self.brownout_at = None
            self.board.brownout()
        if self.replay is not None:
            return self.replay.advance_to(now)
        self.board.advance_to(now)
        return self.board.drain()

    def next_due_ms(self) -> float:
        return (self.replay or self.board).next_due_ms()

    def on_bytes(self, data: bytes) -> None:
        for byte in data:
            char = chr(byte)
            if "a" <= char <= "z":
                self.board.command(char)

    def control(self, line: str) -> str:
        """The out-of-band channel a test uses to break the board mid-session."""
        words = line.split()
        if not words:
            return "?"
        verb, rest = words[0], words[1:]
        if verb == "fault" and rest:
            fault, _, arg = rest[0].partition(":")
            self.board.faults[fault] = arg
            self.board.have_probe = not self.board.has("PROBE_MISSING")
            return f"ok {fault}"
        if verb == "clear" and rest:
            self.board.faults.pop(rest[0], None)
            self.board.have_probe = not self.board.has("PROBE_MISSING")
            return f"ok {rest[0]}"
        if verb == "brownout":
            self.board.brownout()
            return "ok brownout"
        if verb == "quit":
            raise SystemExit(0)
        return "?"


def parse_faults(specs: list[str]) -> dict[str, str]:
    faults: dict[str, str] = {}
    for spec in specs:
        name, _, arg = spec.partition(":")
        if name not in FAULT_IDS:
            raise SystemExit(f"unknown fault {name!r}; known: {', '.join(FAULT_IDS)}")
        faults[name] = arg
    return faults


def serve_tcp(runner: Runner, port: int, control_port: int | None, run_for: float | None) -> None:
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(1)
    print(f"# fake_board listening on 127.0.0.1:{listener.getsockname()[1]}", flush=True)

    sel = selectors.DefaultSelector()
    sel.register(listener, selectors.EVENT_READ, "listen")
    control_listener = None
    if control_port is not None:
        control_listener = socket.socket()
        control_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        control_listener.bind(("127.0.0.1", control_port))
        control_listener.listen(1)
        print(f"# control on 127.0.0.1:{control_listener.getsockname()[1]}", flush=True)
        sel.register(control_listener, selectors.EVENT_READ, "control-listen")

    client: socket.socket | None = None
    control: socket.socket | None = None
    deadline = None if run_for is None else time.monotonic() + run_for
    disconnect_at = runner.args.disconnect_after

    while True:
        if deadline is not None and time.monotonic() > deadline:
            return
        timeout = max(0.0, min(0.05, (runner.next_due_ms() - runner.board_ms()) / 1000 / runner.speed))
        for key, _ in sel.select(timeout=timeout):
            if key.data == "listen":
                conn, _ = listener.accept()
                conn.setblocking(False)
                if client is not None:
                    client.close()
                client = conn
                runner.corrupter.first = True
                sel.register(conn, selectors.EVENT_READ, "client")
            elif key.data == "control-listen":
                conn, _ = control_listener.accept()  # type: ignore[union-attr]
                conn.setblocking(False)
                control = conn
                sel.register(conn, selectors.EVENT_READ, "control")
            elif key.data == "client":
                data = key.fileobj.recv(4096)  # type: ignore[union-attr]
                if not data:
                    sel.unregister(key.fileobj)
                    key.fileobj.close()  # type: ignore[union-attr]
                    client = None
                else:
                    runner.on_bytes(data)
            elif key.data == "control":
                data = key.fileobj.recv(4096)  # type: ignore[union-attr]
                if not data:
                    sel.unregister(key.fileobj)
                    key.fileobj.close()  # type: ignore[union-attr]
                    control = None
                else:
                    for line in data.decode("utf-8", "replace").splitlines():
                        reply = runner.control(line.strip())
                        if control is not None:
                            control.sendall((reply + "\n").encode())

        out = runner.pending()
        if out and client is not None:
            try:
                for chunk in runner.corrupter(out):
                    client.sendall(chunk)
            except OSError:
                sel.unregister(client)
                client.close()
                client = None
        if disconnect_at is not None and runner.board_ms() >= disconnect_at * 1000:
            disconnect_at = None
            if client is not None:
                sel.unregister(client)
                client.close()
                client = None


def serve_pty(runner: Runner, run_for: float | None) -> None:
    import tty

    master, slave = os.openpty()
    tty.setraw(master)
    print(f"# fake_board on {os.ttyname(slave)}", flush=True)
    sel = selectors.DefaultSelector()
    sel.register(master, selectors.EVENT_READ)
    deadline = None if run_for is None else time.monotonic() + run_for
    while True:
        if deadline is not None and time.monotonic() > deadline:
            return
        timeout = max(0.0, min(0.05, (runner.next_due_ms() - runner.board_ms()) / 1000 / runner.speed))
        for _ in sel.select(timeout=timeout):
            try:
                runner.on_bytes(os.read(master, 4096))
            except OSError:
                pass
        for chunk in runner.corrupter(runner.pending()):
            if chunk:
                os.write(master, chunk)


def serve_stdout(runner: Runner, run_for: float | None) -> None:
    deadline = None if run_for is None else time.monotonic() + run_for
    while deadline is None or time.monotonic() <= deadline:
        for chunk in runner.corrupter(runner.pending()):
            sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        time.sleep(min(0.02, max(0.0, (runner.next_due_ms() - runner.board_ms()) / 1000 / runner.speed)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tcp", type=int, metavar="PORT", help="serve on 127.0.0.1:PORT")
    parser.add_argument("--control", type=int, metavar="PORT",
                        help="out-of-band control port: 'fault ID', 'clear ID', 'brownout', 'quit'")
    parser.add_argument("--pty", action="store_true", help="serve on a pty and print its path")
    parser.add_argument("--stdout", action="store_true", help="write the stream to stdout")
    parser.add_argument("--fault", action="append", default=[], metavar="ID[:ARG]",
                        help=f"inject a fault from FAULTS.md: {', '.join(FAULT_IDS)}")
    parser.add_argument("--fault-at", type=float, metavar="S",
                        help="inject the faults S board-seconds after boot instead of at boot")
    parser.add_argument("--brownout-at", type=float, metavar="S", help="reset the board at S seconds")
    parser.add_argument("--disconnect-after", type=float, metavar="S",
                        help="drop the TCP connection at S seconds")
    parser.add_argument("--replay", metavar="JSONL", help="replay a capture instead of simulating")
    parser.add_argument("--loop", action="store_true", help="repeat the replay forever")
    parser.add_argument("--chunk", type=int, default=0, metavar="N",
                        help="write at most N bytes at a time, splitting lines")
    parser.add_argument("--junk", action="store_true",
                        help="start mid-line with boot ROM noise, as a real connection does")
    parser.add_argument("--bench", action="store_true",
                        help="no optical path, as on the bench: every sweep value negative")
    parser.add_argument("--no-diag", action="store_true", help="never print the diag line")
    parser.add_argument("--speed", type=float, default=1.0, help="run the board clock N times faster")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--for", dest="run_for", type=float, metavar="S", help="exit after S seconds")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    runner = Runner(args)
    if args.tcp is not None:
        serve_tcp(runner, args.tcp, args.control, args.run_for)
    elif args.pty:
        serve_pty(runner, args.run_for)
    else:
        serve_stdout(runner, args.run_for)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        # Ctrl-C, or the reader on the other end of the pipe went away.
        pass
