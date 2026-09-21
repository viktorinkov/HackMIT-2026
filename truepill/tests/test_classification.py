"""Tests for the TruePill classification layer, using mock sensor data.

Run with pytest, or directly: python -m truepill.tests.test_classification
"""

from __future__ import annotations

import numpy as np

from ..classification import (
    ClassificationResult,
    classify,
    compute_absorbance,
    cosine_similarity,
    l2_normalize,
)
from ..mock_data import (
    LED_WAVELENGTHS,
    build_library,
    simulate_readings,
    true_absorbance,
)

LIBRARY = build_library()
RNG = np.random.default_rng(7)


def _run(composition, expected_drug=None, noise=8.0, fluor=True, rng=None) -> ClassificationResult:
    r = simulate_readings(composition, noise_counts=noise, rng=rng or RNG)
    kwargs = dict(fluor_blank=r.fluor_blank, fluor_sample=r.fluor_sample) if fluor else {}
    return classify(r.dark, r.blank, r.sample, LIBRARY, expected_drug=expected_drug, **kwargs)


# --- unit-level stages -------------------------------------------------------

def test_absorbance_recovers_ground_truth():
    comp = {"acetaminophen": 500.0}
    r = simulate_readings(comp, noise_counts=2.0, rng=RNG)
    recovered = compute_absorbance(r.dark, r.blank, r.sample)
    truth = true_absorbance(comp)
    assert cosine_similarity(recovered, truth) > 0.995, "recovered spectrum shape should match truth"
    assert abs(recovered.max() - truth.max()) < 0.05, "peak absorbance should be close to truth"


def test_l2_normalize():
    v = np.array([3.0, 4.0])
    n = l2_normalize(v)
    assert np.isclose(np.linalg.norm(n), 1.0)
    assert np.allclose(l2_normalize(np.zeros(5)), np.zeros(5)), "zero vector must not divide by zero"


def test_normalization_is_concentration_invariant():
    full = true_absorbance({"ibuprofen": 200.0})
    diluted = true_absorbance({"ibuprofen": 50.0})
    assert cosine_similarity(full, diluted) > 0.9999


def test_dead_channels_are_zeroed():
    n = LED_WAVELENGTHS.size
    dark = np.full(n, 60.0)
    blank = dark.copy()  # no light reaches the detector: zero dynamic range
    sample = dark + 1.0
    a = compute_absorbance(dark, blank, sample)
    assert np.all(a == 0.0), "channels with no dynamic range must not produce inf/nan"


# --- end-to-end scenarios ----------------------------------------------------

def test_genuine_pill_passes():
    r = _run({"acetaminophen": 500.0}, expected_drug="acetaminophen")
    assert r.verdict == "PASS", r
    assert r.match_name == "acetaminophen"
    assert r.confidence == "high"
    assert 0.9 < r.concentration_ratio < 1.1, r.concentration_ratio


def test_each_library_drug_identified():
    for entry in LIBRARY:
        r = _run({entry.name: entry.expected_concentration})
        assert r.match_name == entry.name, f"{entry.name} misidentified as {r.match_name}"
        assert r.similarity > 0.97


def test_diluted_pill_flagged():
    r = _run({"ibuprofen": 80.0}, expected_drug="ibuprofen")  # 40% of the 200 mg dose
    assert r.verdict == "DILUTED", r
    assert r.match_name == "ibuprofen"
    assert 0.3 < r.concentration_ratio < 0.5, r.concentration_ratio


def test_overconcentrated_pill_flagged():
    r = _run({"caffeine": 180.0}, expected_drug="caffeine")  # 180% of the 100 mg dose
    assert r.verdict == "OVER_CONCENTRATED", r
    assert r.concentration_ratio > 1.25


def test_cut_pill_detected_as_adulterated():
    # Half the acetaminophen replaced with lactose filler
    r = _run({"acetaminophen": 250.0, "lactose": 400.0}, expected_drug="acetaminophen")
    assert r.verdict == "ADULTERATED", r
    assert "lactose" in r.composition, r.composition
    assert r.composition["lactose"] > 0.10


def test_wrong_drug_in_bottle():
    # Labeled acetaminophen, actually ibuprofen
    r = _run({"ibuprofen": 200.0}, expected_drug="acetaminophen")
    assert r.verdict == "ADULTERATED", r
    assert r.match_name == "ibuprofen"
    assert any("labeled as" in f for f in r.flags), r.flags


def test_fluorescence_separates_lookalikes():
    # counterfeit_apap's absorbance is nearly identical to acetaminophen's;
    # only the 90-degree fluorescence channel distinguishes them.
    reads = simulate_readings({"counterfeit_apap": 500.0}, rng=np.random.default_rng(3))

    absorbance_only = classify(reads.dark, reads.blank, reads.sample, LIBRARY)
    apap_sim = cosine_similarity(
        absorbance_only.absorbance,
        next(e for e in LIBRARY if e.name == "acetaminophen").spectrum,
    )
    assert apap_sim > 0.99, "premise: lookalikes must be near-identical in absorbance"

    with_fluor = classify(
        reads.dark, reads.blank, reads.sample, LIBRARY,
        expected_drug="acetaminophen",
        fluor_blank=reads.fluor_blank, fluor_sample=reads.fluor_sample,
    )
    assert with_fluor.match_name == "counterfeit_apap", with_fluor
    assert with_fluor.verdict == "ADULTERATED", with_fluor
    assert with_fluor.used_fluorescence


def test_genuine_pill_passes_without_fluorescence_channel():
    # The classifier must still work if TEMT6000 #2 data is missing.
    r = _run({"caffeine": 100.0}, expected_drug="caffeine", fluor=False)
    assert r.verdict == "PASS", r
    assert not r.used_fluorescence


def test_unknown_substance():
    # A spectrum shape not in the library: flat broadband absorber
    reads = simulate_readings({}, rng=RNG)
    flat_sample = reads.dark + 0.4 * (reads.blank - reads.dark)  # ~0.4 absorbance everywhere
    r = classify(reads.dark, reads.blank, flat_sample, LIBRARY)
    assert r.verdict == "UNKNOWN", r
    assert r.match_name is None


def test_empty_sample_no_signal():
    r = _run({})  # blank in the sample position
    assert r.verdict == "NO_SIGNAL", r


def test_noise_robustness():
    # Genuine pill under heavy read noise should still identify correctly
    for seed in range(10):
        rng = np.random.default_rng(seed)
        r = _run({"amoxicillin": 250.0}, expected_drug="amoxicillin", noise=25.0, rng=rng)
        assert r.match_name == "amoxicillin", f"seed {seed}: {r}"
        assert r.verdict in ("PASS", "DILUTED"), f"seed {seed}: {r.verdict}"


ALL_TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    failed = 0
    for fn in ALL_TESTS:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
    print(f"\n{len(ALL_TESTS) - failed}/{len(ALL_TESTS)} tests passed")
    raise SystemExit(1 if failed else 0)
