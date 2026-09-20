"""TruePill classification layer.

Pipeline (matches the architecture diagram):

    dark reading ─┐
    blank reading ─┼─> absorbance vector ─> L2 normalize ─> library match ─> result
    sample reading ┘

Hardware this expects (per the TruePill design): an ESP32-S3 time-sequences an
LED arc — one LED at a time — through the cuvette into TEMT6000 #1, so each
"reading" is a vector of ADC counts, one entry per LED channel. TEMT6000 #2
sits at 90° and reads fluorescence emission per excitation LED; when those
counts are provided (blank + sample), they're appended to the absorbance
vector as extra features before normalization, which separates substances
whose absorbance spectra look alike. No NIR/MAX30102 channels — that sensor
is not in the build.

The library match handles identification (which substance), concentration
estimation (how much of it, via Beer-Lambert scaling), dilution detection
(estimated vs. expected dose), and composition analysis (NNLS mixture
decomposition to catch fillers/adulterants).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import nnls

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Cosine similarity below this -> "unknown substance". Tuned so a broadband
# absorber (~0.92 vs the widest library band) is rejected while a heavily cut
# pill (~0.945 vs its active ingredient) is still identified.
MATCH_THRESHOLD = 0.935
# Cosine similarity above this -> high-confidence match
STRONG_MATCH_THRESHOLD = 0.97
# concentration ratio (estimated / expected) below this -> diluted
DILUTION_RATIO = 0.80
# concentration ratio above this -> over-concentrated (also a fail)
OVERCONC_RATIO = 1.25
# NNLS mixture components below this fraction are ignored as noise
COMPOSITION_MIN_FRACTION = 0.05
# a secondary component above this fraction -> flagged as adulterated
ADULTERANT_FRACTION = 0.10
# max absorbance below this -> too little signal to classify
MIN_SIGNAL_ABSORBANCE = 0.02
# (blank - dark) below this many ADC counts in a channel -> channel unusable
MIN_DYNAMIC_RANGE = 1.0

# ESP32-S3 ADC full scale; fluorescence counts are divided by this so the
# fluorescence block lands on the same O(0-1) scale as absorbance.
ADC_FULL_SCALE = 4095.0
# Relative weight of the fluorescence block in the combined feature vector.
FLUOR_WEIGHT = 1.0

_EPS = 1e-9


@dataclass(frozen=True)
class ClassifierConfig:
    """The snapshot-path tunables as one value, so a rig can carry its own.

    Defaults are the module constants above (tuned against the simulator's
    8-LED arc in ADC counts). Measured per-rig values live in hardware.py.
    """

    match_threshold: float = MATCH_THRESHOLD
    strong_match_threshold: float = STRONG_MATCH_THRESHOLD
    dilution_ratio: float = DILUTION_RATIO
    overconc_ratio: float = OVERCONC_RATIO
    composition_min_fraction: float = COMPOSITION_MIN_FRACTION
    adulterant_fraction: float = ADULTERANT_FRACTION
    min_signal_absorbance: float = MIN_SIGNAL_ABSORBANCE
    # Same units as the readings (ADC counts, or mV on rigs that report mV).
    min_dynamic_range: float = MIN_DYNAMIC_RANGE
    full_scale: float = ADC_FULL_SCALE
    fluor_weight: float = FLUOR_WEIGHT
    # Refuse (INVALID_READING) a reading the optics cannot have produced
    # instead of clipping it into shape: a non-finite value, any channel whose
    # blank lacks dynamic range, a sample at/below dark, or a sample brighter
    # than its blank by more than the noise floor. Off by default: the
    # simulator's noisy high-absorbance samples legitimately dip under dark,
    # and its 8-channel arc is meant to survive a zeroed channel.
    strict_inputs: bool = False


DEFAULT_CONFIG = ClassifierConfig()


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryEntry:
    """One reference substance in the spectral library."""

    name: str
    # Absorbance per LED channel, measured at `reference_concentration`.
    spectrum: np.ndarray
    # Concentration (e.g. mg per unit volume of the dissolved/prepared sample)
    # at which `spectrum` was recorded.
    reference_concentration: float
    # Expected label dose for a genuine pill of this drug, in the same units.
    expected_concentration: float
    is_active_ingredient: bool = True
    # Net fluorescence emission counts (TEMT6000 #2, blank-subtracted) per
    # excitation LED, at `reference_concentration`. None if not recorded.
    fluorescence: np.ndarray | None = None


@dataclass
class ClassificationResult:
    verdict: str                      # PASS | DILUTED | OVER_CONCENTRATED | ADULTERATED | UNKNOWN | NO_SIGNAL | INVALID_READING
    match_name: str | None
    similarity: float
    confidence: str                   # high | medium | none
    estimated_concentration: float | None
    expected_concentration: float | None
    concentration_ratio: float | None
    composition: dict[str, float] = field(default_factory=dict)  # name -> fraction of signal
    flags: list[str] = field(default_factory=list)
    absorbance: np.ndarray | None = None
    used_fluorescence: bool = False


# ---------------------------------------------------------------------------
# Stage 1: absorbance vector
# ---------------------------------------------------------------------------

def compute_absorbance(
    dark: np.ndarray,
    blank: np.ndarray,
    sample: np.ndarray,
    min_dynamic_range: float = MIN_DYNAMIC_RANGE,
) -> np.ndarray:
    """Dark-corrected absorbance: A = -log10((sample - dark) / (blank - dark)).

    Channels where the blank barely exceeds dark have no usable dynamic range
    and are zeroed out rather than allowed to blow up the log.
    """
    dark = np.asarray(dark, dtype=float)
    blank = np.asarray(blank, dtype=float)
    sample = np.asarray(sample, dtype=float)
    if not (dark.shape == blank.shape == sample.shape):
        raise ValueError("dark, blank, and sample readings must have the same shape")

    denom = blank - dark
    usable = denom > min_dynamic_range

    transmittance = np.ones_like(denom)
    np.divide(sample - dark, denom, out=transmittance, where=usable)
    # Clip: fully opaque floor, and allow slight >1 transmittance from noise.
    transmittance = np.clip(transmittance, 1e-6, None)

    absorbance = -np.log10(transmittance)
    # Negative absorbance is just noise around the blank level.
    absorbance = np.clip(absorbance, 0.0, None)
    absorbance[~usable] = 0.0
    return absorbance


def compute_net_fluorescence(fluor_blank: np.ndarray, fluor_sample: np.ndarray) -> np.ndarray:
    """Net emission per excitation LED, blank-subtracted (the water blank
    already carries dark level + stray-light baseline)."""
    net = np.asarray(fluor_sample, dtype=float) - np.asarray(fluor_blank, dtype=float)
    return np.clip(net, 0.0, None)


# ---------------------------------------------------------------------------
# Stage 2: L2 normalize
# ---------------------------------------------------------------------------

def l2_normalize(vec: np.ndarray) -> np.ndarray:
    """Unit-norm the vector so shape comparison ignores concentration."""
    vec = np.asarray(vec, dtype=float)
    norm = np.linalg.norm(vec)
    if norm < _EPS:
        return np.zeros_like(vec)
    return vec / norm


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(l2_normalize(a), l2_normalize(b)))


def build_feature_vector(
    absorbance: np.ndarray,
    net_fluorescence: np.ndarray | None,
    config: ClassifierConfig = DEFAULT_CONFIG,
) -> np.ndarray:
    """Absorbance channels, optionally with scaled fluorescence appended.

    Both blocks scale ~linearly with concentration (Beer-Lambert; dilute-limit
    fluorescence), so the concatenated vector stays concentration-invariant
    after L2 normalization.
    """
    if net_fluorescence is None:
        return np.asarray(absorbance, dtype=float)
    fluor = config.fluor_weight * np.asarray(net_fluorescence, dtype=float) / config.full_scale
    return np.concatenate([np.asarray(absorbance, dtype=float), fluor])


def _library_feature_vector(
    entry: LibraryEntry, with_fluor: bool, config: ClassifierConfig = DEFAULT_CONFIG
) -> np.ndarray:
    if with_fluor:
        fluor = entry.fluorescence
        if fluor is None:
            # Substance was never seen to fluoresce; treat as zero emission.
            fluor = np.zeros_like(entry.spectrum)
        return build_feature_vector(entry.spectrum, fluor, config)
    return np.asarray(entry.spectrum, dtype=float)


# ---------------------------------------------------------------------------
# Stage 3: library match
# ---------------------------------------------------------------------------

def _estimate_concentration(absorbance: np.ndarray, ref: LibraryEntry) -> float:
    """Beer-Lambert least-squares scale of the reference onto the sample.

    A_sample ≈ s * A_ref, and absorbance is linear in concentration, so the
    estimated concentration is s * reference_concentration. Uses absorbance
    only — it's the block with the clean linear law.
    """
    ref_spec = np.asarray(ref.spectrum, dtype=float)
    denom = float(np.dot(ref_spec, ref_spec))
    if denom < _EPS:
        return 0.0
    scale = float(np.dot(absorbance, ref_spec)) / denom
    return max(scale, 0.0) * ref.reference_concentration


def _decompose_composition(
    absorbance: np.ndarray,
    library: list[LibraryEntry],
    min_fraction: float = COMPOSITION_MIN_FRACTION,
) -> dict[str, float]:
    """Non-negative least squares mixture fit against the whole library.

    Returns each substance's fraction of the total explained signal.
    Absorbance-only: mixtures add linearly there.
    """
    basis = np.column_stack([l2_normalize(e.spectrum) for e in library])
    coeffs, _residual = nnls(basis, absorbance)
    total = coeffs.sum()
    if total < _EPS:
        return {}
    fractions = {
        entry.name: float(c / total)
        for entry, c in zip(library, coeffs)
        if c / total >= min_fraction
    }
    # Renormalize the surviving components so they sum to 1.
    s = sum(fractions.values())
    return {k: v / s for k, v in fractions.items()} if s > 0 else {}


@dataclass
class SpectralMatch:
    """Result of matching an equilibrium (A_inf) spectrum against the
    time-resolved reference library."""

    best_name: str | None
    cosine: float                       # cosine similarity to best entry
    mahalanobis: float                  # scale-invariant Mahalanobis to best entry
    scale: float                        # best-fit amplitude vs reference (≈ dose ratio)
    per_entry: dict[str, tuple[float, float]]   # name -> (cosine, mahalanobis)
    composition: dict[str, float]       # NNLS fractions (>= COMPOSITION_MIN_FRACTION)


def _scaled_mahalanobis(x: np.ndarray, mean: np.ndarray, cov: np.ndarray) -> tuple[float, float]:
    """Mahalanobis distance of x to the RAY {s * mean, s >= 0}.

    Identity is a question of spectral SHAPE; amplitude is dose. The
    generalized-least-squares scale s is fitted first, so a genuine pill at
    90% dose measures near-zero distance (its dose deviation is judged by
    the dissolution Q-test instead). Returns (scale, distance).
    """
    sol_mean = np.linalg.solve(cov, mean)
    denom = float(np.dot(mean, sol_mean))
    if denom < _EPS:
        return 0.0, float("inf")
    s = max(float(np.dot(x, sol_mean)) / denom, 0.0)
    diff = x - s * mean
    d = float(np.sqrt(max(np.dot(diff, np.linalg.solve(cov, diff)), 0.0)))
    return s, d


def match_spectrum(
    a_inf: np.ndarray,
    references: list,
    a_inf_var: np.ndarray | None = None,
) -> SpectralMatch:
    """Match an equilibrium spectrum against ReferenceEntry-like objects
    (need .name, .mean_a_inf, .covariance).

    The L2-normalized A_inf drives the cosine ranking (concentration-
    invariant shape match, as before); the Mahalanobis distance is computed
    scale-invariantly (best amplitude fitted first, see _scaled_mahalanobis),
    and the winner is the entry with the smallest distance. NNLS composition
    runs on the raw spectrum against the reference means, exactly like the
    snapshot path.

    `a_inf_var` is the per-channel estimation variance of the A_inf vector
    (from the kinetics fit). A run that ended before equilibrium extrapolates
    A_inf with real uncertainty; adding it to Σ keeps extrapolation error
    from reading as a counterfeit spectrum.
    """
    if not references:
        raise ValueError("reference library is empty")
    a_inf = np.asarray(a_inf, dtype=float)
    unit = l2_normalize(a_inf)
    extra = None
    if a_inf_var is not None and np.size(a_inf_var):
        extra = np.diag(np.clip(np.asarray(a_inf_var, dtype=float), 0.0, None))

    per_entry: dict[str, tuple[float, float]] = {}
    scales: dict[str, float] = {}
    for ref in references:
        cos = float(np.dot(unit, l2_normalize(ref.mean_a_inf)))
        cov = ref.covariance if extra is None else ref.covariance + extra
        s, d = _scaled_mahalanobis(a_inf, ref.mean_a_inf, cov)
        per_entry[ref.name] = (cos, d)
        scales[ref.name] = s

    best_name = min(per_entry, key=lambda n: per_entry[n][1])

    basis = np.column_stack([l2_normalize(r.mean_a_inf) for r in references])
    coeffs, _ = nnls(basis, a_inf)
    total = coeffs.sum()
    composition: dict[str, float] = {}
    if total > _EPS:
        fracs = {
            r.name: float(c / total)
            for r, c in zip(references, coeffs)
            if c / total >= COMPOSITION_MIN_FRACTION
        }
        s = sum(fracs.values())
        composition = {k: v / s for k, v in fracs.items()} if s > 0 else {}

    return SpectralMatch(
        best_name=best_name,
        cosine=per_entry[best_name][0],
        mahalanobis=per_entry[best_name][1],
        scale=scales[best_name],
        per_entry=per_entry,
        composition=composition,
    )


def classify(
    dark: np.ndarray,
    blank: np.ndarray,
    sample: np.ndarray,
    library: list[LibraryEntry],
    expected_drug: str | None = None,
    fluor_blank: np.ndarray | None = None,
    fluor_sample: np.ndarray | None = None,
    config: ClassifierConfig | None = None,
) -> ClassificationResult:
    """Run the full pipeline on one set of readings.

    dark/blank/sample: TEMT6000 #1 ADC counts, one entry per LED channel.
    fluor_blank/fluor_sample: optional TEMT6000 #2 counts per excitation LED
    (blank = water cuvette). When both are given, fluorescence joins the
    feature vector used for identification.
    `expected_drug` is what the pill is labeled as, if known; dilution and
    identity checks are made against it.
    `config` carries the tunables; omit it for the simulator defaults, pass a
    rig's measured config (hardware.py) for real captures.
    """
    if not library:
        raise ValueError("spectral library is empty")
    config = config or DEFAULT_CONFIG

    absorbance = compute_absorbance(dark, blank, sample, config.min_dynamic_range)

    use_fluor = fluor_blank is not None and fluor_sample is not None
    net_fluor = compute_net_fluorescence(fluor_blank, fluor_sample) if use_fluor else None

    # --- input validity gate -------------------------------------------------
    if config.strict_inputs:
        blank_net = np.asarray(blank, dtype=float) - np.asarray(dark, dtype=float)
        sample_net = np.asarray(sample, dtype=float) - np.asarray(dark, dtype=float)
        problems: list[str] = []
        if not (np.isfinite(blank_net).all() and np.isfinite(sample_net).all()):
            problems.append("non-finite value in the readings")
        elif (blank_net <= config.min_dynamic_range).any():
            # Every channel is required: zeroing one (the lenient path) bends
            # the spectrum's shape, which a few-channel rig cannot absorb.
            bad = np.flatnonzero(blank_net <= config.min_dynamic_range)
            problems.append(
                f"blank has no dynamic range on channel(s) {bad.tolist()} "
                f"(net {blank_net[bad].round(0).tolist()}, need > {config.min_dynamic_range:g}) - "
                "LED not reaching the detector, or the detector had not settled when dark was read"
            )
        elif (sample_net <= 0.0).any():
            bad = np.flatnonzero(sample_net <= 0.0)
            problems.append(
                f"sample at or below dark on channel(s) {bad.tolist()} - beam blocked, "
                "detector not settled, or sample opaque; clipping this would fake a saturated spectrum"
            )
        elif (np.log10(sample_net / blank_net) > config.min_signal_absorbance).any():
            bad = np.flatnonzero(np.log10(sample_net / blank_net) > config.min_signal_absorbance)
            problems.append(
                f"sample brighter than the blank beyond the noise floor on channel(s) {bad.tolist()} - "
                "the light level moved or the blank is stale; take a fresh blank"
            )
        if problems:
            return ClassificationResult(
                verdict="INVALID_READING",
                match_name=None,
                similarity=0.0,
                confidence="none",
                estimated_concentration=None,
                expected_concentration=None,
                concentration_ratio=None,
                flags=problems,
                absorbance=absorbance,
                used_fluorescence=use_fluor,
            )

    # --- signal quality gate -------------------------------------------------
    if float(absorbance.max(initial=0.0)) < config.min_signal_absorbance:
        return ClassificationResult(
            verdict="NO_SIGNAL",
            match_name=None,
            similarity=0.0,
            confidence="none",
            estimated_concentration=None,
            expected_concentration=None,
            concentration_ratio=None,
            flags=["absorbance below detection floor - empty cuvette or blank sample?"],
            absorbance=absorbance,
            used_fluorescence=use_fluor,
        )

    # --- identification via normalized shape match ---------------------------
    features = build_feature_vector(absorbance, net_fluor, config)
    unit = l2_normalize(features)
    sims = [
        (entry, float(np.dot(unit, l2_normalize(_library_feature_vector(entry, use_fluor, config)))))
        for entry in library
    ]
    best_entry, best_sim = max(sims, key=lambda t: t[1])

    flags: list[str] = []

    if best_sim < config.match_threshold:
        return ClassificationResult(
            verdict="UNKNOWN",
            match_name=None,
            similarity=best_sim,
            confidence="none",
            estimated_concentration=None,
            expected_concentration=None,
            concentration_ratio=None,
            composition=_decompose_composition(absorbance, library, config.composition_min_fraction),
            flags=[f"no library spectrum above match threshold (best: {best_entry.name} @ {best_sim:.4f})"],
            absorbance=absorbance,
            used_fluorescence=use_fluor,
        )

    confidence = "high" if best_sim >= config.strong_match_threshold else "medium"

    # --- identity vs. label --------------------------------------------------
    target = best_entry
    if expected_drug is not None and expected_drug != best_entry.name:
        flags.append(
            f"labeled as {expected_drug!r} but spectrum matches {best_entry.name!r} "
            f"(sim {best_sim:.3f})"
        )

    # --- concentration & dilution -------------------------------------------
    est_conc = _estimate_concentration(absorbance, target)
    exp_conc = target.expected_concentration
    ratio = est_conc / exp_conc if exp_conc > 0 else None

    # --- composition ---------------------------------------------------------
    composition = _decompose_composition(absorbance, library, config.composition_min_fraction)
    active_fraction = composition.get(target.name, 0.0)
    adulterants = {
        name: frac
        for name, frac in composition.items()
        if name != target.name and frac >= config.adulterant_fraction
    }

    # --- verdict -------------------------------------------------------------
    if expected_drug is not None and expected_drug != best_entry.name:
        verdict = "ADULTERATED"
        flags.append("identity mismatch with label")
    elif adulterants:
        verdict = "ADULTERATED"
        flags.append(
            "secondary components detected: "
            + ", ".join(f"{n} ({f:.0%})" for n, f in sorted(adulterants.items(), key=lambda t: -t[1]))
        )
    elif ratio is not None and ratio < config.dilution_ratio:
        verdict = "DILUTED"
        flags.append(f"estimated dose is {ratio:.0%} of expected")
    elif ratio is not None and ratio > config.overconc_ratio:
        verdict = "OVER_CONCENTRATED"
        flags.append(f"estimated dose is {ratio:.0%} of expected")
    else:
        verdict = "PASS"

    if active_fraction and active_fraction < 1.0 - config.composition_min_fraction and not adulterants:
        flags.append(f"active ingredient explains {active_fraction:.0%} of signal")

    return ClassificationResult(
        verdict=verdict,
        match_name=best_entry.name,
        similarity=best_sim,
        confidence=confidence,
        estimated_concentration=est_conc,
        expected_concentration=exp_conc,
        concentration_ratio=ratio,
        composition=composition,
        flags=flags,
        absorbance=absorbance,
        used_fluorescence=use_fluor,
    )
