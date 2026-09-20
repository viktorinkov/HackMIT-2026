"""A synthetic run in the firmware's own line format, for replays and tests.

Mirrors peel_app's DemoLink: a first-order rise to a plateau on the fast channel,
a turbidity bump on the scatter channel, and a four-colour sweep every ten seconds.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Iterator

CLEAR_TRANS = 2460.0
CLEAR_SCAT = 180.0
SWEEP_BASE = {"red": 900.0, "yellow": 1300.0, "green": 2460.0, "blue": 1700.0}
# How strongly each colour is absorbed relative to the fast channel.
SWEEP_GAIN = {"red": 0.02, "yellow": 0.05, "green": 0.15, "blue": 1.0}


def lines(
    plateau: float = 0.7,
    k: float = 1 / 90.0,
    seconds: int = 300,
    cloud: float = 0.0,
    fast_led: str = "blue",
    lead_s: int = 12,
    noise: float = 0.003,
    seed: int = 7,
) -> Iterator[str]:
    rng = random.Random(seed)
    yield f"# 17_stream ready. Fast channel = {fast_led} LED. Stirrer 100%. Temperature probe: found"
    yield "# commands: b blank, z mark t=0, a toggle auto t=0, s stop, m stirrer"
    sweep: dict[str, float | None] = dict.fromkeys(SWEEP_BASE)
    blank = None
    for tick in range(lead_s + seconds):
        if tick == 3:
            blank = (CLEAR_TRANS, CLEAR_SCAT)
            yield f"# blank stored: transmission {CLEAR_TRANS:.0f} mV, scatter {CLEAR_SCAT:.0f} mV"
        if tick == lead_s:
            yield "# t = 0 detected from the transmission drop"
        t = tick - lead_s
        abs_t = 0.0 if t < 0 else plateau * (1 - math.exp(-k * t))
        cloudiness = 0.0 if t < 0 else cloud * (t / 40) * math.exp(1 - t / 40)
        trans = CLEAR_TRANS * 10 ** -(abs_t + rng.gauss(0, noise))
        scat = CLEAR_SCAT * 10 ** (cloudiness + rng.gauss(0, noise))
        swept = tick % 10 == 0
        if swept:
            gain = {c: SWEEP_GAIN[c] * (1.0 if fast_led == "blue" else 1 / SWEEP_GAIN["green"]) for c in SWEEP_BASE}
            sweep = {c: round(SWEEP_BASE[c] * 10 ** -(abs_t * gain[c])) for c in SWEEP_BASE}
        yield json.dumps(
            {
                "t": float(t) if t >= 0 else -1.0,
                "trans": round(trans),
                "scat": round(scat),
                "absT": None if blank is None else round(math.log10(blank[0] / trans), 4),
                "absS": None if blank is None else round(math.log10(blank[1] / scat), 4),
                "tC": round(22.0 + rng.gauss(0, 0.05), 2),
                "sweep": sweep,
                "stir": 100,
                "swept": swept,
            },
            separators=(",", ":"),
        )
