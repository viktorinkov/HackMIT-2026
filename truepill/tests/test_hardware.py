"""Tests for the bench-rig tuning, driven by real captures in data/captures/.

  2026-09-20_rig_static.jsonl    5 min off the connected rig, nothing touched.
                                 Every sweep is negative: the rig's fault state.
  2026-09-16_healthy_sweeps.csv  53 fresh sweeps from the same rig working,
                                 used as REAL noise (autocorrelated, common-mode).

The library spectra are the rig's own measured advil / pepto absorbances
(tools/pill_library.json, 2026-09-10), red / yellow / green only.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

from ..classification import LibraryEntry, classify, cosine_similarity
from ..hardware import PEEL_BENCH_RIG, average_sweeps, sweep_vector
from ..noise import NoiseParams, model_covariance

CAPTURES = Path(__file__).parent.parent / "data" / "captures"
RIG = PEEL_BENCH_RIG
CFG = RIG.classifier
N_AVG = RIG.sweeps_to_average

SPECTRA = {
    "advil": np.array([0.8577, 0.9941, 0.6472]),
    "pepto": np.array([1.0567, 1.1600, 0.8725]),
}
LIBRARY = [LibraryEntry(name, spec, 1.0, 1.0) for name, spec in SPECTRA.items()]
BLANK_MV = np.array([911.5, 740.75, 1409.0])     # water blank stored with that library
DARK = np.zeros(3)                                # the firmware dark-subtracts the sweep


def _live_lines() -> list[dict]:
    with open(CAPTURES / "2026-09-20_rig_static.jsonl") as f:
        return [json.loads(line) for line in f]


def _healthy_gain_blocks() -> np.ndarray:
    """Real per-channel gain wobble, averaged over consecutive N_AVG sweeps."""
    with open(CAPTURES / "2026-09-16_healthy_sweeps.csv") as f:
        sw = np.array([[float(r[c]) for c in ("red_mv", "yellow_mv", "green_mv")] for r in csv.DictReader(f)])
    rel = sw / sw.mean(axis=0)
    return np.array([rel[i:i + N_AVG].mean(axis=0) for i in range(len(rel) - N_AVG + 1)])


def _real_noise_pairs():
    """(blank gain, sample gain) drawn from the recording: blank first,
    sample later, no sweep shared between them."""
    blocks = _healthy_gain_blocks()
    return [(blocks[i], blocks[j]) for i in range(len(blocks)) for j in range(len(blocks)) if j - i >= N_AVG]


def _measure(spectrum: np.ndarray, g_blank: np.ndarray, g_sample: np.ndarray, **kw):
    return classify(DARK, BLANK_MV * g_blank, BLANK_MV * 10.0 ** (-spectrum) * g_sample, LIBRARY, config=CFG, **kw)


# --- the rig as it is connected today ------------------------------------------

def test_live_capture_is_the_fault_state_this_tuning_guards_against():
    sweeps = [v for v in (sweep_vector(ln) for ln in _live_lines()) if v is not None]
    assert len(sweeps) == 29
    assert all((s < 0).all() for s in sweeps), "premise: every sweep in the capture is negative"


def test_live_sweep_is_refused_not_matched():
    sample = average_sweeps(_live_lines())
    r = classify(DARK, BLANK_MV, sample, LIBRARY, expected_drug="advil", config=CFG)
    assert r.verdict == "INVALID_READING", r
    assert r.match_name is None and r.confidence == "none"


def test_simulator_defaults_call_the_same_live_sweep_a_confident_match():
    # Why the rig needs its own config: untuned, garbage in -> "pepto, high".
    r = classify(DARK, BLANK_MV, average_sweeps(_live_lines()), LIBRARY, expected_drug="advil")
    assert r.match_name == "pepto" and r.confidence == "high", r


def test_live_sweep_as_blank_is_refused():
    live = average_sweeps(_live_lines())
    r = classify(DARK, live, live, LIBRARY, config=CFG)
    assert r.verdict == "INVALID_READING", r
    assert "no dynamic range" in r.flags[0]


def _genuine_advil_mv() -> np.ndarray:
    return BLANK_MV * 10.0 ** (-SPECTRA["advil"])


def test_one_weak_channel_is_refused_not_zeroed():
    # The lenient path zeroes the channel and reports UNKNOWN @ 0.81: safe,
    # but it blames the pill for the rig. All three channels are required.
    blank = BLANK_MV.copy()
    blank[0] = 40.0                                           # under the 50 mV floor
    sample = _genuine_advil_mv()
    sample[0] = 40.0 * 10.0 ** (-SPECTRA["advil"][0])
    r = classify(DARK, blank, sample, LIBRARY, expected_drug="advil", config=CFG)
    assert r.verdict == "INVALID_READING", r
    assert "channel(s) [0]" in r.flags[0]


def test_non_finite_reading_is_refused_not_a_crash():
    sample = _genuine_advil_mv()
    sample[1] = np.nan
    r = classify(DARK, BLANK_MV, sample, LIBRARY, config=CFG)
    assert r.verdict == "INVALID_READING", r


def test_sample_brighter_than_blank_means_a_stale_blank():
    # This rig's light level has been seen to jump ~3.6x between readings. An
    # upward jump after the blank reads as negative absorbance; clipped to
    # zero it would pass for clear water.
    r = classify(DARK, BLANK_MV, BLANK_MV * 1.4, LIBRARY, config=CFG)
    assert r.verdict == "INVALID_READING", r
    assert "fresh blank" in r.flags[0]


def test_light_level_dropping_after_the_blank_is_not_a_match():
    # The downward jump is a flat absorbance of log10(3.6) on every channel.
    r = classify(DARK, BLANK_MV, _genuine_advil_mv() / 3.6, LIBRARY, expected_drug="advil", config=CFG)
    assert r.verdict != "PASS", r


def test_only_the_rigs_three_channels_are_read_from_a_sweep():
    # The firmware's sweep object has keys that are not channels of this
    # instrument, as null or as numbers depending on the build. Channels are
    # read by name, so neither form reaches the classifier.
    assert RIG.channels == ("red", "yellow", "green")
    line = {"swept": True, "sweep": {"red": 140, "yellow": 118, "green": 403, "blue": -37}}
    assert sweep_vector(line).tolist() == [140.0, 118.0, 403.0]
    line["sweep"]["blue"] = None
    assert sweep_vector(line).tolist() == [140.0, 118.0, 403.0]


def test_average_sweeps_needs_enough_fresh_sweeps():
    lines = [ln for ln in _live_lines() if ln["swept"]][: N_AVG - 1]
    try:
        average_sweeps(lines)
    except ValueError as e:
        assert "fresh sweeps" in str(e)
    else:
        raise AssertionError("expected ValueError")


# --- the rig working, under its real noise --------------------------------------

def test_three_channel_geometry_defeats_the_simulator_threshold():
    flat = np.ones(3)
    assert all(cosine_similarity(flat, s) > 0.98 for s in SPECTRA.values())
    assert cosine_similarity(SPECTRA["advil"], SPECTRA["pepto"]) > 0.998


def test_genuine_pills_pass_under_real_noise():
    for name, spectrum in SPECTRA.items():
        for g_blank, g_sample in _real_noise_pairs():
            r = _measure(spectrum, g_blank, g_sample, expected_drug=name)
            assert r.match_name == name, f"{name}: {r}"
            assert r.verdict == "PASS", f"{name}: {r}"


def test_noise_is_not_read_as_an_adulterant_across_the_pass_band():
    # The common-mode offset is flat and looks like the flatter library entry.
    for dose in (0.80, 1.25):
        for g_blank, g_sample in _real_noise_pairs():
            r = _measure(dose * SPECTRA["advil"], g_blank, g_sample, expected_drug="advil")
            assert r.verdict != "ADULTERATED", f"dose {dose}: {r}"


def test_half_and_half_mixture_is_caught_through_the_label_only():
    mix = 0.5 * SPECTRA["advil"] + 0.5 * SPECTRA["pepto"]

    def caught(label):
        results = [_measure(mix, gb, gs, expected_drug=label) for gb, gs in _real_noise_pairs()]
        return np.mean([r.verdict == "ADULTERATED" for r in results])

    # The mixture matches pepto, so a label of advil trips the identity check.
    assert caught("advil") > 0.97
    # KNOWN LIMIT of this rig, pinned so nobody quotes it as working: with no
    # label to contradict, composition alone misses most 50/50 mixtures.
    assert caught(None) < 0.5


def test_wrong_drug_is_never_accepted_as_labelled():
    for g_blank, g_sample in _real_noise_pairs():
        r = _measure(SPECTRA["advil"], g_blank, g_sample, expected_drug="pepto")
        assert r.verdict in ("ADULTERATED", "UNKNOWN"), r


def test_grey_filter_not_in_library_is_unknown():
    # Open-set rejection, the case HANDOFF §4.2 says is untested.
    for g_blank, g_sample in _real_noise_pairs():
        r = _measure(np.full(3, 0.8), g_blank, g_sample)
        assert r.verdict == "UNKNOWN", r


def test_water_against_water_is_no_signal():
    for g_blank, g_sample in _real_noise_pairs():
        r = _measure(np.zeros(3), g_blank, g_sample)
        assert r.verdict == "NO_SIGNAL", r


# --- noise model -----------------------------------------------------------------

def test_common_mode_term_correlates_channels():
    a = SPECTRA["advil"]
    sigma = model_covariance(a, BLANK_MV, RIG.noise.reference_current_mA, RIG.noise)
    d = np.sqrt(np.diag(sigma))
    corr = sigma / np.outer(d, d)
    assert (corr[np.triu_indices(3, 1)] > 0.5).all(), corr
    # and the default model is still diagonal
    base = model_covariance(a, BLANK_MV, 20.0, NoiseParams())
    assert np.allclose(base, np.diag(np.diag(base)))


def test_sigma_is_calibrated_not_merely_wide():
    # A too-wide Sigma hides inside "genuine never rejected". With the scale
    # fitted out, genuine distances must follow chi(dof=2): median 1.18.
    from ..classification import _scaled_mahalanobis

    def distances(true, against):
        sigma = model_covariance(SPECTRA[against], BLANK_MV, RIG.noise.reference_current_mA, RIG.noise)
        return np.array([
            _scaled_mahalanobis(-np.log10(10.0 ** (-SPECTRA[true]) * gs / gb), SPECTRA[against], sigma)[1]
            for gb, gs in _real_noise_pairs()
        ])

    genuine = np.concatenate([distances(k, k) for k in SPECTRA])
    wrong = np.concatenate([distances("advil", "pepto"), distances("pepto", "advil")])
    assert 0.8 < np.median(genuine) < 1.6, np.median(genuine)
    assert genuine.max() < 4.0, genuine.max()            # verdict.PipelineConfig.mahalanobis_threshold
    assert wrong.min() > 4.0, wrong.min()


def test_model_sigma_covers_the_measured_spread():
    blocks = _healthy_gain_blocks()
    pairs = _real_noise_pairs()
    measured = np.array([-np.log10(gs / gb) for gb, gs in pairs]).std(axis=0)
    healthy_levels = np.array([136.8, 115.8, 399.9])          # mV, the recording's mean sweep
    modelled = np.sqrt(np.diag(model_covariance(np.zeros(3), healthy_levels, 20.0, RIG.noise)))
    assert len(blocks) > 40
    assert (modelled >= 0.9 * measured).all(), (modelled, measured)
    assert (modelled <= 2.0 * measured).all(), (modelled, measured)
