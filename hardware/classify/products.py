"""What the classifier knows about each product it can check.

Only coloured actives are here. A colourless tablet gives no absorbance on any
of the rig's LEDs, and the classifier says so instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    key: str
    name: str
    label_mg: float
    channel: str = "blue"  # the LED the active absorbs
    volume_ml: float = 1000.0  # what the tablet is dissolved into
    dilution: float = 1.0  # extra dilution before the vial
    dose_band: tuple[float, float] = (0.90, 1.10)  # fraction of label that passes the screen
    min_absorbance: float = 0.02  # below this the active is not seen at all
    max_absorbance: float = 1.0  # above this the sensor is into its non-linear range
    turbidity_max: float = 0.15  # cloudiness on the scatter channel that voids a read
    off_channel_max: float = 0.08  # absorbance allowed on colours the active does not absorb
    off_channels: tuple[str, ...] = ("red", "yellow")
    # Illustrative comparator only. USP <2040> asks 75 % of riboflavin in 1 h, in
    # 0.1 N HCl at 37 C; the rig runs room-temperature water.
    release_pct: float | None = 75.0
    release_at_s: float | None = 3600.0

    @property
    def expected_mg_l(self) -> float:
        return self.label_mg * 1000.0 / self.volume_ml / self.dilution

    def dose_fraction(self, mg_l: float) -> float:
        return mg_l / self.expected_mg_l


RIBOFLAVIN = Product(
    key="riboflavin",
    name="riboflavin (vitamin B2) 100 mg",
    label_mg=100.0,
    channel="blue",
    # Riboflavin saturates near 0.1 g/L, so a 100 mg tablet goes into a litre of warm
    # water and the vial is filled from a 1:4 dilution (about 25 mg/L, A ~ 0.7 at 1 cm).
    volume_ml=1000.0,
    dilution=4.0,
)

PRODUCTS: dict[str, Product] = {p.key: p for p in (RIBOFLAVIN,)}
