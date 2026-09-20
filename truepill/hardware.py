"""Measured profile of the bench rig, and the classifier tuning that follows.

classification.py's defaults were tuned against mock_data's simulator: an
8-LED 405-700 nm arc read in 12-bit ADC counts. The rig that exists is not
that instrument, so its numbers live here rather than overwriting the
simulator's. Every figure below is measured; the provenance is in
HARDWARE_TUNING.md, and rig_characterize.py reproduces them from a capture.

The rig (ESP32-S3, firmware 17_stream):

  - reports MILLIVOLTS (analogReadMilliVolts, 11 dB, 24-sample mean), not
    ADC counts;
  - is a three-channel instrument: red / yellow / green, swept on the
    transmission sensor every 10 s and dark-subtracted ON THE BOARD, so the
    host passes dark = 0. Everything here is tuned for exactly these three.
    The firmware's sweep object carries other keys too (main's 17_stream
    prints ir / red / yellow / green / blue / violet); channels are read by
    name, so whatever else is in there never reaches the classifier;
  - reads the 90-degree sensor only under the always-on green LED, so there
    is no per-LED fluorescence block to give classify().
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .classification import ClassificationResult, ClassifierConfig, LibraryEntry, classify
from .noise import NoiseParams

# The rig's own measured reference spectra, shipped beside this module so the
# package finds them wherever it is dropped.
DEFAULT_LIBRARY_PATH = Path(__file__).parent / "data" / "library" / "peel_bench_rig.json"


@dataclass(frozen=True)
class RigProfile:
    name: str
    # The instrument's channels, as firmware sweep keys in sweep order. Only
    # these keys are read from a sweep; anything else in it is not this rig's.
    channels: tuple[str, ...]
    # Nominal only. The LEDs are unbinned ELEGOO kit parts with no datasheet;
    # "green" may be 525 nm InGaN or 570 nm GaP. classify() never uses these.
    nominal_wavelengths_nm: tuple[float, ...]
    # Sweeps to average for the blank and again for the sample. The sweep
    # noise is autocorrelated (0.55 at 10 s lag), so this buys less than
    # sqrt(n): 0.028 -> 0.021 AU measured, and one sweep is not enough to
    # hold the match threshold below.
    sweeps_to_average: int
    classifier: ClassifierConfig
    noise: NoiseParams


PEEL_BENCH_RIG = RigProfile(
    name="peel-bench-17_stream",
    channels=("red", "yellow", "green"),
    nominal_wavelengths_nm=(625.0, 590.0, 525.0),
    sweeps_to_average=5,
    classifier=ClassifierConfig(
        # Three all-positive channels put EVERY spectrum within cosine ~0.98
        # of every other, so the simulator's 0.935 rejects nothing: a grey
        # filter scored 0.9934 "high confidence". Measured over 990 real
        # (blank, sample) noise pairs at 5-sweep averaging: worst genuine
        # 0.99975, best wrong drug 0.99930, best grey filter 0.99418.
        match_threshold=0.9995,
        # Genuine p1 = 0.99980.
        strong_match_threshold=0.9998,
        # The common-mode offset is a FLAT spectrum, and the flatter library
        # entry soaks it up in the NNLS fit: genuine advil reads as up to 41%
        # "pepto" across the 0.80-1.25 dose band, and the simulator's 0.10
        # called 43% of genuine pills adulterated. 0.42 clears every genuine
        # reading. The price: NNLS composition is close to blind here. A true
        # 50/50 advil+pepto mixture matches pepto and is flagged only ~33% of
        # the time on composition; it is caught reliably (99.5%) only when the
        # label says advil and the identity check fires. Three near-collinear
        # channels (basis condition number 36) cannot do better.
        composition_min_fraction=0.42,
        adulterant_fraction=0.42,
        # Water against water reaches 0.083 AU (p99 of the largest channel);
        # the simulator's 0.02 is inside one sigma on this rig.
        min_signal_absorbance=0.10,
        # mV. 5x the ~10 mV sweep-to-sweep sd of the weakest healthy channel.
        min_dynamic_range=50.0,
        # mV. Calibrated ceiling of the ESP32-S3 ADC at 11 dB attenuation.
        full_scale=3100.0,
        # This rig has emitted all-negative sweeps (detector unsettled when
        # dark was read); clipped, those become a saturated flat spectrum
        # that matches the library. Refuse them instead.
        strict_inputs=True,
    ),
    noise=NoiseParams(
        # mV, not counts: blank_counts passed alongside must be mV too.
        # Floor of a 24-sample mean; not separately measured, and it barely
        # matters next to the term below.
        read_noise_counts=1.0,
        # The per-channel noise left after the common-mode part is removed is
        # PROPORTIONAL to the signal (1.4-1.9 % at 116, 137 and 400 mV alike),
        # not shot-like, so it is carried by the absorbance-domain term below.
        # Forcing it into shot_factor (0.12, a first attempt) made Sigma
        # 1.6-2x too wide: genuine samples sat at d = 0.66 where chi(2) says
        # 1.18, and the wrong drug fell inside the 4.0 cutoff 12.8 % of the time.
        shot_factor=0.0,
        # Independent absorbance sd per channel of one spectrum (a blank/sample
        # pair, each a 5-sweep mean). There is no LED current telemetry on
        # this rig, so the current-deviation scaling this field was named for
        # never engages; it is simply the model's per-channel AU term.
        drift_per_current_frac=0.0082,
        # The dominant term: sweep channels move together (r = 0.92), a flat
        # 0.029 AU per sweep, 0.028 AU for one spectrum as defined above (the
        # MEASURED figure; sqrt(n) averaging would wrongly promise 0.018).
        # Calibration, checked on a held-out recording too: genuine d median
        # 1.01 / p95 2.35 against chi(2)'s 1.18 / 2.45; wrong drug d >= 5.1.
        common_mode_abs_sd=0.028,
    ),
)


def sweep_vector(line: dict, rig: RigProfile = PEEL_BENCH_RIG) -> np.ndarray | None:
    """The rig's channel values (mV, already dark-subtracted) from one parsed
    17_stream JSON line, or None if that line carries no fresh sweep.

    The firmware repeats the last sweep on every line; only `swept: true`
    lines are new measurements.
    """
    if not line.get("swept"):
        return None
    sweep = line.get("sweep") or {}
    values = [sweep.get(c) for c in rig.channels]
    if any(v is None for v in values):
        return None
    return np.asarray(values, dtype=float)


def average_sweeps(lines: list[dict], rig: RigProfile = PEEL_BENCH_RIG) -> np.ndarray:
    """Mean of the most recent `sweeps_to_average` fresh sweeps in `lines`,
    ready to hand to classify() as `blank` or `sample` (with dark = 0)."""
    sweeps = [v for v in (sweep_vector(ln, rig) for ln in lines) if v is not None]
    if len(sweeps) < rig.sweeps_to_average:
        raise ValueError(
            f"need {rig.sweeps_to_average} fresh sweeps, got {len(sweeps)} "
            f"(the firmware sweeps every 10 s)"
        )
    return np.mean(sweeps[-rig.sweeps_to_average:], axis=0)



def parse_stream_line(raw: str | dict) -> dict | None:
    """One 17_stream reading as a dict, or None for anything else.

    Accepts the firmware's own JSON line, or the envelope hardware/tools'
    capture writes around it ({"src": ..., "line": "<firmware JSON>"}), as
    text or already parsed. Comment lines ('# ...'), boot noise and torn
    lines give None rather than raising: a serial stream is never clean.
    """
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw.startswith("{"):
            return None
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None
    if "line" in raw and "sweep" not in raw:
        return parse_stream_line(raw["line"]) if isinstance(raw["line"], str) else None
    return raw if "sweep" in raw else None


def load_library(path: str | Path | None = None, rig: RigProfile = PEEL_BENCH_RIG) -> list[LibraryEntry]:
    """Reference spectra for `rig` from a JSON file (default: the rig's own
    measured library). Each entry's spectrum is keyed by channel NAME, so a
    file recorded with more channels than the rig reads still loads."""
    with open(path or DEFAULT_LIBRARY_PATH) as f:
        doc = json.load(f)
    entries = []
    for name, e in doc["library"].items():
        missing = [c for c in rig.channels if c not in e["absorbance"]]
        if missing:
            raise ValueError(f"library entry {name!r} has no value for channel(s) {missing}")
        entries.append(LibraryEntry(
            name=name,
            spectrum=np.array([e["absorbance"][c] for c in rig.channels], dtype=float),
            reference_concentration=float(e.get("reference_concentration", 1.0)),
            expected_concentration=float(e.get("expected_concentration", 1.0)),
            is_active_ingredient=bool(e.get("is_active_ingredient", True)),
        ))
    if not entries:
        raise ValueError("library file has no entries")
    return entries


def classify_capture(
    blank_lines: list,
    sample_lines: list,
    library: list[LibraryEntry],
    expected_drug: str | None = None,
    rig: RigProfile = PEEL_BENCH_RIG,
) -> ClassificationResult:
    """Classify one measurement straight from the firmware's output.

    `blank_lines`: 17_stream lines recorded with clear water in the cup;
    `sample_lines`: lines recorded once the sample has dissolved. Each needs
    `rig.sweeps_to_average` fresh sweeps (50 s at the firmware's 10 s cadence).
    Lines may be raw text, parsed dicts or capture envelopes; anything that is
    not a reading is skipped. Take the blank in the same session: this rig's
    light level moves, and a stale blank is refused as INVALID_READING.
    """
    blank = average_sweeps([ln for ln in map(parse_stream_line, blank_lines) if ln], rig)
    sample = average_sweeps([ln for ln in map(parse_stream_line, sample_lines) if ln], rig)
    dark = np.zeros_like(blank)                  # the firmware already dark-subtracts the sweep
    return classify(dark, blank, sample, library, expected_drug=expected_drug, config=rig.classifier)
