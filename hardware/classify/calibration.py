"""A straight line from absorbance to concentration, fitted on standards read on this rig.

Literature absorptivities are only a sanity check; every dose the classifier
reports comes from a line measured on the same LED, sensor and vial.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class Calibration:
    product: str
    channel: str
    slope: float  # AU per mg/L
    intercept: float
    r2: float
    points: list[tuple[float, float]]  # (mg/L, absorbance)
    blank_sd: float | None = None
    made_at: str = ""

    def concentration(self, absorbance: float) -> float:
        return (absorbance - self.intercept) / self.slope

    def lod(self) -> float | None:
        """Detection limit in mg/L, 3.3 sigma of the blank over the slope."""
        return None if self.blank_sd is None else 3.3 * self.blank_sd / self.slope

    def loq(self) -> float | None:
        return None if self.blank_sd is None else 10 * self.blank_sd / self.slope

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(asdict(self), indent=2) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> Calibration:
        data = json.loads(Path(path).read_text())
        data["points"] = [tuple(p) for p in data["points"]]
        return cls(**data)


def fit(
    points: list[tuple[float, float]], product: str, channel: str, blank_sd: float | None = None
) -> Calibration:
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    if len(set(xs)) < 2:
        raise ValueError("need standards at two or more concentrations")
    n = len(points)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in points)
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in points)
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    r2 = 1.0 if ss_tot == 0 else 1 - ss_res / ss_tot
    if slope <= 0:
        raise ValueError("absorbance does not rise with concentration; check the channel and the blank")
    return Calibration(
        product=product,
        channel=channel,
        slope=slope,
        intercept=intercept,
        r2=r2,
        points=list(points),
        blank_sd=blank_sd,
        made_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
