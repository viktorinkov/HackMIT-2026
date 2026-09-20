"""One dissolution run: the readings since t = 0 and what can be read off them."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median

from .stream import COLOURS, Note, Reading


@dataclass
class Run:
    fast_led: str = "green"
    blank_sweep: dict[str, float] | None = None
    readings: list[Reading] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    _before: list[Reading] = field(default_factory=list, repr=False)

    def feed(self, item: Reading | Note) -> None:
        if isinstance(item, Note):
            self.notes.append(item.text)
            if item.fast_led:
                self.fast_led = item.fast_led
            return
        if not item.running:
            # The last complete sweep before the tablet goes in is the sweep's blank.
            self._before.append(item)
            del self._before[:-30]
            if item.sweep_complete and not item.swept:
                self.blank_sweep = {c: float(item.sweep[c]) for c in COLOURS}  # type: ignore[arg-type]
            return
        if self.readings and item.t is not None and item.t < self.readings[-1].t:  # type: ignore[operator]
            self.readings.clear()
        self.readings.append(item)

    @property
    def seconds(self) -> float:
        return self.readings[-1].t if self.readings else 0.0  # type: ignore[return-value]

    def curve(self) -> list[tuple[float, float]]:
        """(t, absorbance) on the fast channel, skipping seconds disturbed by a sweep."""
        return [
            (r.t, r.abs_t)  # type: ignore[misc]
            for r in self.readings
            if not r.swept and r.t is not None and r.abs_t is not None
        ]

    def plateau(self, window_s: float = 60.0, slope_tol: float = 0.0005) -> tuple[float, bool] | None:
        """Median absorbance over the last window, and whether the curve has flattened."""
        curve = self.curve()
        if not curve:
            return None
        last_t = curve[-1][0]
        recent = [p for p in curve if p[0] >= last_t - window_s]
        if len(recent) < 5:
            return median(a for _, a in recent), False
        slope = _slope(recent)
        return median(a for _, a in recent), abs(slope) <= slope_tol

    def release(self, plateau: float) -> list[tuple[float, float]]:
        if plateau <= 0:
            return []
        return [(t, 100.0 * a / plateau) for t, a in self.curve()]

    def time_to(self, percent: float, plateau: float) -> float | None:
        for t, pct in self.release(plateau):
            if pct >= percent:
                return t
        return None

    def released_at(self, at_s: float, plateau: float) -> float | None:
        points = [pct for t, pct in self.release(plateau) if t <= at_s]
        if not points or self.seconds < at_s:
            return None
        return points[-1]

    def turbidity(self, window_s: float = 30.0) -> float | None:
        values = [
            r.cloudiness
            for r in self.readings
            if r.cloudiness is not None and r.t is not None and r.t >= self.seconds - window_s
        ]
        return median(values) if values else None  # type: ignore[arg-type]

    def temperature(self) -> float | None:
        values = [r.temp_c for r in self.readings if r.temp_c is not None]
        return median(values) if values else None

    def sweep_absorbance(self) -> dict[str, float | None]:
        """log10(blank / now) per colour from the latest complete sweep in the run."""
        latest = next((r for r in reversed(self.readings) if r.sweep_complete), None)
        if latest is None or self.blank_sweep is None:
            return dict.fromkeys(COLOURS)
        out: dict[str, float | None] = {}
        for c in COLOURS:
            now, blank = latest.sweep[c], self.blank_sweep[c]
            out[c] = math.log10(blank / now) if now and blank and now > 1 and blank > 1 else None
        return out


def _slope(points: list[tuple[float, float]]) -> float:
    n = len(points)
    mean_t = sum(t for t, _ in points) / n
    mean_a = sum(a for _, a in points) / n
    var = sum((t - mean_t) ** 2 for t, _ in points)
    if var == 0:
        return 0.0
    return sum((t - mean_t) * (a - mean_a) for t, a in points) / var
