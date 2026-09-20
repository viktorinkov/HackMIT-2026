"""Mock sensor data for testing the TruePill classification layer.

Simulates the actual TruePill optics: an LED arc fired one LED at a time
through the cuvette into TEMT6000 #1 (transmission, 12-bit ESP32 ADC counts),
and TEMT6000 #2 at 90° reading fluorescence emission per excitation LED.
No MAX30102/NIR channels — that sensor is not in the build.

Reference spectra are synthetic sums of Gaussian bands sampled at the discrete
LED wavelengths. Swap this file for real captures without touching
classification.py — the classifier only needs the count vectors and a library.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .classification import ADC_FULL_SCALE, LibraryEntry

# The LED arc: one wavelength per LED, in firing order.
LED_WAVELENGTHS = np.array([405.0, 450.0, 505.0, 530.0, 570.0, 617.0, 660.0, 700.0])  # nm

# Sensor simulation constants (12-bit ADC counts)
DARK_LEVEL = 60.0
BLANK_LEVEL = 3400.0
# Peak fluorescence counts for a strong emitter at reference concentration
FLUOR_SCALE = 1200.0
# Stray-light baseline TEMT6000 #2 sees even with a water blank
FLUOR_BASELINE = 40.0


def _gaussian_bands(bands: list[tuple[float, float, float]]) -> np.ndarray:
    """Absorbance at the LED wavelengths from (center_nm, width_nm, peak) bands."""
    spec = np.zeros_like(LED_WAVELENGTHS)
    for center, width, peak in bands:
        spec += peak * np.exp(-0.5 * ((LED_WAVELENGTHS - center) / width) ** 2)
    return spec


# Reference substances. `bands` shape the absorbance spectrum; `fluor` is
# (excitation_center_nm, excitation_width_nm, quantum_yield 0-1) or None for
# non-fluorescent substances. Shapes are synthetic but distinct.
_SUBSTANCES: dict[str, dict] = {
    "acetaminophen": {
        "bands": [(430, 25, 0.90), (540, 40, 0.35)],
        "fluor": None,
        "reference_concentration": 500.0,   # mg
        "expected_concentration": 500.0,
        "active": True,
    },
    "ibuprofen": {
        "bands": [(470, 30, 0.75), (620, 35, 0.50)],
        "fluor": None,
        "reference_concentration": 200.0,
        "expected_concentration": 200.0,
        "active": True,
    },
    "amoxicillin": {
        "bands": [(410, 20, 0.60), (500, 25, 0.80), (660, 30, 0.25)],
        "fluor": (405, 40, 0.35),
        "reference_concentration": 250.0,
        "expected_concentration": 250.0,
        "active": True,
    },
    "caffeine": {
        "bands": [(450, 60, 0.55), (580, 20, 0.65)],
        "fluor": None,
        "reference_concentration": 100.0,
        "expected_concentration": 100.0,
        "active": True,
    },
    # Common cutting agent / filler
    "lactose": {
        "bands": [(520, 90, 0.30)],
        "fluor": None,
        "reference_concentration": 500.0,
        "expected_concentration": 500.0,
        "active": False,
    },
    # Counterfeit lookalike: absorbance nearly identical to acetaminophen, but
    # strongly fluorescent under violet/blue excitation — only the 90°
    # fluorescence channel can tell them apart.
    "counterfeit_apap": {
        "bands": [(432, 26, 0.88), (542, 41, 0.34)],
        "fluor": (430, 45, 0.80),
        "reference_concentration": 500.0,
        "expected_concentration": 500.0,
        "active": False,
    },
}


def _fluor_reference(info: dict) -> np.ndarray | None:
    """Net emission counts per excitation LED at reference concentration."""
    if info["fluor"] is None:
        return None
    center, width, qy = info["fluor"]
    excitation = np.exp(-0.5 * ((LED_WAVELENGTHS - center) / width) ** 2)
    return qy * excitation * FLUOR_SCALE


def build_library() -> list[LibraryEntry]:
    return [
        LibraryEntry(
            name=name,
            spectrum=_gaussian_bands(info["bands"]),
            reference_concentration=info["reference_concentration"],
            expected_concentration=info["expected_concentration"],
            is_active_ingredient=info["active"],
            fluorescence=_fluor_reference(info),
        )
        for name, info in _SUBSTANCES.items()
    ]


def true_absorbance(composition: dict[str, float]) -> np.ndarray:
    """Ground-truth absorbance for {substance: concentration} (Beer-Lambert)."""
    total = np.zeros_like(LED_WAVELENGTHS)
    for name, conc in composition.items():
        info = _SUBSTANCES[name]
        total += (conc / info["reference_concentration"]) * _gaussian_bands(info["bands"])
    return total


def true_fluorescence(composition: dict[str, float]) -> np.ndarray:
    """Ground-truth net emission counts for a mixture (dilute-limit linear)."""
    total = np.zeros_like(LED_WAVELENGTHS)
    for name, conc in composition.items():
        info = _SUBSTANCES[name]
        ref = _fluor_reference(info)
        if ref is not None:
            total += (conc / info["reference_concentration"]) * ref
    return total


@dataclass
class Readings:
    """One scan's raw counts, matching the firmware event schema."""

    dark: np.ndarray          # TEMT6000 #1, all LEDs off
    blank: np.ndarray         # TEMT6000 #1, water cuvette, per LED
    sample: np.ndarray        # TEMT6000 #1, sample cuvette, per LED
    fluor_blank: np.ndarray   # TEMT6000 #2, water cuvette, per excitation LED
    fluor_sample: np.ndarray  # TEMT6000 #2, sample cuvette, per excitation LED


def simulate_readings(
    composition: dict[str, float],
    noise_counts: float = 8.0,
    rng: np.random.Generator | None = None,
) -> Readings:
    """Simulate one full scan for a given {substance: concentration} sample."""
    rng = rng or np.random.default_rng(42)
    n = LED_WAVELENGTHS.size

    dark = DARK_LEVEL + rng.normal(0, noise_counts * 0.25, n)
    blank = BLANK_LEVEL + rng.normal(0, noise_counts, n)

    transmittance = 10.0 ** (-true_absorbance(composition))
    sample = DARK_LEVEL + transmittance * (BLANK_LEVEL - DARK_LEVEL) + rng.normal(0, noise_counts, n)

    fluor_blank = FLUOR_BASELINE + rng.normal(0, noise_counts * 0.5, n)
    fluor_sample = (
        FLUOR_BASELINE + true_fluorescence(composition) + rng.normal(0, noise_counts * 0.5, n)
    )

    clip = lambda v: np.clip(v, 0.0, ADC_FULL_SCALE)
    return Readings(clip(dark), clip(blank), clip(sample), clip(fluor_blank), clip(fluor_sample))


# ---------------------------------------------------------------------------
# Time-resolved dissolution runs
# ---------------------------------------------------------------------------

# Typical first-order dissolution rate constants (1/s) for the mock drugs;
# ~5-15 minute characteristic times.
DISSOLUTION_K: dict[str, float] = {
    "acetaminophen": 1 / 300.0,
    "ibuprofen": 1 / 450.0,
    "amoxicillin": 1 / 350.0,
    "caffeine": 1 / 250.0,
    "lactose": 1 / 200.0,
    "counterfeit_apap": 1 / 300.0,
}

DEFAULT_LED_CURRENT = 20.0  # mA


def simulate_dissolution_arrays(
    composition: dict[str, float],
    k: float | None = None,
    duration_s: float = 2400.0,
    dt_s: float = 30.0,
    noise_absorbance: float = 0.005,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """(t, absorbance(n_t, n_ch)) for a tablet dissolving with rate k.

    A(t) = A_inf * (1 - exp(-k t)) plus Gaussian absorbance noise. If k is
    None, uses the concentration-weighted mean of the substances' typical
    rate constants.
    """
    rng = rng or np.random.default_rng(0)
    a_inf = true_absorbance(composition)
    if k is None:
        if composition:
            total = sum(composition.values())
            k = sum(DISSOLUTION_K[n] * c for n, c in composition.items()) / total
        else:
            k = 1 / 300.0
    t = np.arange(0.0, duration_s + dt_s / 2, dt_s)
    A = np.outer(1.0 - np.exp(-k * t), a_inf)
    A += rng.normal(0, noise_absorbance, A.shape)
    return t, np.clip(A, 0.0, None)


def simulate_dissolution_run(
    run_id: str,
    composition: dict[str, float],
    expected_drug: str | None = None,
    k: float | None = None,
    duration_s: float = 2400.0,
    dt_s: float = 30.0,
    noise_absorbance: float = 0.005,
    led_current_mA: float = DEFAULT_LED_CURRENT,
    rng: np.random.Generator | None = None,
):
    """A full `DissolutionRun` model, as the firmware would stream it."""
    from .models import DissolutionRun, Reading, SampleMetadata

    rng = rng or np.random.default_rng(0)
    t, A = simulate_dissolution_arrays(
        composition, k=k, duration_s=duration_s, dt_s=dt_s,
        noise_absorbance=noise_absorbance, rng=rng,
    )
    n = LED_WAVELENGTHS.size
    run = DissolutionRun(
        run_id=run_id,
        sample=SampleMetadata(expected_drug=expected_drug),
        wavelengths=list(LED_WAVELENGTHS),
    )
    for i, ti in enumerate(t):
        run.add_reading(Reading(
            t_seconds=float(ti),
            absorbance=[float(v) for v in A[i]],
            dark=[DARK_LEVEL] * n,
            blank_ref=[BLANK_LEVEL] * n,
            temperature=23.0 + float(rng.normal(0, 0.1)),
            led_current_mA=led_current_mA + float(rng.normal(0, 0.05)),
        ))
    return run


def build_reference_library(n_repeat_runs: int = 5, rng: np.random.Generator | None = None):
    """Time-resolved `ReferenceEntry` library built from simulated repeat runs
    of each known-good substance."""
    from .library import build_entry_from_runs
    from .noise import NoiseParams

    rng = rng or np.random.default_rng(11)
    blank_counts = np.full(LED_WAVELENGTHS.size, BLANK_LEVEL)
    entries = []
    for name, info in _SUBSTANCES.items():
        runs = [
            simulate_dissolution_arrays(
                {name: info["reference_concentration"]},
                k=DISSOLUTION_K[name] * float(rng.normal(1.0, 0.03)),
                rng=rng,
            )
            for _ in range(n_repeat_runs)
        ]
        entries.append(build_entry_from_runs(
            name=name,
            wavelengths=LED_WAVELENGTHS,
            runs=runs,
            blank_counts=blank_counts,
            noise_params=NoiseParams(reference_current_mA=DEFAULT_LED_CURRENT),
            expected_concentration=info["expected_concentration"],
            is_active_ingredient=info["active"],
        ))
    return entries
