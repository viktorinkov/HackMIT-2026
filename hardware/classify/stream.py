"""Parse what the 17_stream firmware prints: one JSON line a second plus '#' notes.

The line format is frozen (docs/PROTOCOL.md). Anything that does not parse is
dropped rather than raised, because a USB stream can start mid-line.
"""

from __future__ import annotations

import csv
import glob
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

COLOURS = ("red", "yellow", "green", "blue")

# Older firmware printed a bare nan for a dark sensor. Lose the field, not the line.
_NON_FINITE = re.compile(r":\s*-?(?:nan|inf(?:inity)?)\b", re.IGNORECASE)
_FAST_LED = re.compile(r"Fast channel = (\w+) LED")


@dataclass
class Reading:
    t: float | None
    trans: float
    scat: float
    abs_t: float | None = None
    abs_s: float | None = None
    temp_c: float | None = None
    sweep: dict[str, float | None] = field(default_factory=lambda: dict.fromkeys(COLOURS))
    stir: int = 0
    swept: bool = False

    @property
    def running(self) -> bool:
        return self.t is not None

    @property
    def cloudiness(self) -> float | None:
        # The firmware reports log10(blank / now) on the scatter sensor too, which goes
        # negative as the liquid clouds. Flip it so turbidity reads upward.
        return None if self.abs_s is None else -self.abs_s

    @property
    def sweep_complete(self) -> bool:
        return all(self.sweep.get(c) is not None for c in COLOURS)


@dataclass
class Note:
    text: str

    @property
    def fast_led(self) -> str | None:
        match = _FAST_LED.search(self.text)
        return match.group(1) if match else None


def parse_line(raw: str) -> Reading | Note | None:
    line = raw.strip()
    if not line:
        return None
    if line.startswith("#"):
        return Note(line[1:].strip())
    if not line.startswith("{"):
        return None
    try:
        data = json.loads(_NON_FINITE.sub(":null", line))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    trans, scat = _num(data.get("trans")), _num(data.get("scat"))
    if trans is None or scat is None:
        return None
    t = _num(data.get("t"))
    sweep = data.get("sweep") if isinstance(data.get("sweep"), dict) else {}
    return Reading(
        t=None if t is None or t < 0 else t,
        trans=trans,
        scat=scat,
        abs_t=_num(data.get("absT")),
        abs_s=_num(data.get("absS")),
        temp_c=_num(data.get("tC")),
        sweep={c: _num(sweep.get(c)) for c in COLOURS},
        stir=int(_num(data.get("stir")) or 0),
        swept=data.get("swept") is True,
    )


def read_log(path: str | Path) -> Iterator[Reading | Note]:
    """A raw capture of the serial stream, one firmware line per line."""
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            item = parse_line(raw)
            if item is not None:
                yield item


def read_csv(path: str | Path) -> Iterator[Reading]:
    """A run recorded by tools/peel_monitor.py."""
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t = _cell(row.get("t_s"))
            yield Reading(
                t=None if t is None or t < 0 else t,
                trans=_cell(row.get("trans_mv")) or 0.0,
                scat=_cell(row.get("scat_mv")) or 0.0,
                abs_t=_cell(row.get("absT")),
                abs_s=_cell(row.get("absS")),
                temp_c=_cell(row.get("tC")),
                sweep={c: _cell(row.get(f"sweep_{c}")) for c in COLOURS},
                stir=int(_cell(row.get("stir_pct")) or 0),
                swept=(row.get("swept") or "").strip().lower() == "true",
            )


class Board:
    """A live board on USB serial. pyserial is imported here so replays need no driver."""

    def __init__(self, port: str, baud: int = 115200) -> None:
        try:
            import serial
        except ImportError as exc:
            raise SystemExit("pyserial missing. Run: pip3 install pyserial") from exc
        self._ser = serial.Serial(port, baud, timeout=2)

    def lines(self) -> Iterator[Reading | Note]:
        while True:
            try:
                raw = self._ser.readline().decode(errors="replace")
            except Exception:  # noqa: BLE001
                continue
            item = parse_line(raw) if raw else None
            if item is not None:
                yield item

    def send(self, command: str) -> None:
        self._ser.write(command[:1].encode())

    def close(self) -> None:
        self._ser.close()


def find_port() -> str | None:
    patterns = (
        "/dev/cu.usbmodem*",
        "/dev/cu.usbserial*",
        "/dev/cu.SLAB_USBtoUART*",
        "/dev/cu.wchusbserial*",
        "/dev/ttyACM*",
        "/dev/ttyUSB*",
    )
    found = sorted(p for pattern in patterns for p in glob.glob(pattern))
    return found[0] if found else None


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _cell(text: str | None) -> float | None:
    if text is None or not text.strip():
        return None
    try:
        return float(text)
    except ValueError:
        return None
