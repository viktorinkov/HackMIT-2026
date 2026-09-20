"""Turn a run into a verdict.

Three outcomes. PASS_SCREEN: the dose is inside the label band and every quality gate
held. REFER_TO_LAB: the rig saw the active but the dose or the release is off.
CANNOT_VERIFY: the read is not trustworthy (cloudy, saturated, wrong colour, too
short) and no dose is reported. Never anything stronger: the device measures
absorbance, not intent.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Literal

from .calibration import Calibration
from .products import Product
from .run import Run
from .stream import COLOURS

Status = Literal["pass_screen", "refer_to_lab", "cannot_verify"]

MIN_SECONDS = 5.0


@dataclass
class Result:
    product: str
    status: Status = "cannot_verify"
    reasons: list[str] = field(default_factory=list)
    absorbance: float | None = None
    settled: bool = False
    analyte_seen: bool = False
    dose_mg_l: float | None = None
    dose_fraction: float | None = None
    slow_release: bool = False
    t80_s: float | None = None
    released_pct: float | None = None
    released_at_s: float | None = None
    turbidity: float | None = None
    sweep: dict[str, float | None] = field(default_factory=lambda: dict.fromkeys(COLOURS))
    temp_c: float | None = None
    seconds: float = 0.0
    n: int = 0
    channel: str = ""

    def to_json(self, **extra: object) -> str:
        return json.dumps({**asdict(self), **extra}, indent=2)


def classify(run: Run, calibration: Calibration | None, product: Product) -> Result:
    result = Result(product=product.key, channel=product.channel, n=len(run.readings))
    if not run.readings:
        return _cannot(result, "no readings after t = 0")
    result.seconds = run.seconds
    result.turbidity = run.turbidity()
    result.temp_c = run.temperature()
    result.sweep = run.sweep_absorbance()

    if run.fast_led == product.channel:
        plateau = run.plateau()
        if plateau is None:
            return _cannot(result, "no absorbance yet; was a blank taken?")
        result.absorbance, result.settled = plateau
    else:
        # The fast channel is lit by another colour; fall back to the slow sweep.
        result.absorbance = result.sweep.get(product.channel)
        result.settled = True
        result.reasons.append(
            f"{product.channel} read from the sweep; the fast channel is {run.fast_led}"
        )
        if result.absorbance is None:
            return _cannot(result, f"no {product.channel} sweep against a blank yet")

    if result.seconds < MIN_SECONDS:
        return _cannot(result, f"only {result.seconds:.0f} s of readings")
    if result.turbidity is not None and result.turbidity > product.turbidity_max:
        return _cannot(result, f"cloudy: scatter {result.turbidity:.2f} AU; filter and re-read")
    if result.absorbance > product.max_absorbance:
        return _cannot(result, f"absorbance {result.absorbance:.2f} is above the linear range; dilute")
    off = {c: result.sweep.get(c) for c in product.off_channels}
    if any(a is not None and a > product.off_channel_max for a in off.values()):
        seen = ", ".join(f"{c} {a:.2f}" for c, a in off.items() if a is not None)
        return _cannot(result, f"absorbance on colours {product.name} does not absorb ({seen})")

    result.analyte_seen = result.absorbance >= product.min_absorbance
    if not result.analyte_seen:
        result.status = "refer_to_lab"
        result.reasons.append(f"no {product.name} absorbance on the {product.channel} LED")
        return result
    if calibration is None:
        result.reasons.append("active seen, but no calibration on file for a dose")
        return _cannot(result, "not calibrated")

    result.dose_mg_l = calibration.concentration(result.absorbance)
    result.dose_fraction = product.dose_fraction(result.dose_mg_l)
    lo, hi = product.dose_band
    pct = 100 * result.dose_fraction
    if not result.settled:
        result.reasons.append("still dissolving; dose is provisional")
    if result.dose_fraction < lo:
        result.status = "refer_to_lab"
        result.reasons.append(f"dose {pct:.0f} % of label, below {100 * lo:.0f} %")
    elif result.dose_fraction > hi:
        result.status = "refer_to_lab"
        result.reasons.append(f"dose {pct:.0f} % of label, above {100 * hi:.0f} %")
    else:
        result.status = "pass_screen"
        result.reasons.append(f"dose {pct:.0f} % of label")

    if result.settled:
        result.t80_s = run.time_to(80.0, result.absorbance)
    if product.release_at_s is not None and product.release_pct is not None:
        result.released_at_s = product.release_at_s
        result.released_pct = run.released_at(product.release_at_s, result.absorbance)
        if result.released_pct is not None and result.released_pct < product.release_pct:
            result.slow_release = True
            result.status = "refer_to_lab"
            result.reasons.append(
                f"{result.released_pct:.0f} % released at {product.release_at_s:.0f} s, "
                f"below {product.release_pct:.0f} %"
            )
    return result


def _cannot(result: Result, reason: str) -> Result:
    result.status = "cannot_verify"
    result.reasons.append(reason)
    return result
