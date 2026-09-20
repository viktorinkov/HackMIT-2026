"""Tests for the time-resolved TruePill pipeline.

Run with pytest, or directly: python -m truepill.tests.test_pipeline
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from ..dissolution import f2_similarity
from ..kinetics import early_estimate, fit_kinetics
from ..mock_data import (
    LED_WAVELENGTHS,
    build_reference_library,
    simulate_dissolution_arrays,
    simulate_dissolution_run,
    true_absorbance,
)
from ..models import ScanEvent
from ..noise import KalmanDriftCorrector, NoiseParams, absorbance_variance, monte_carlo_roc
from ..verdict import PipelineConfig, Verdict, evaluate_run, partial_payload

LIBRARY = build_reference_library()
CONFIG = PipelineConfig()


# --- kinetics ----------------------------------------------------------------

def test_kinetics_recovers_known_parameters():
    # Synthetic runs at default noise: k within 10%, A_inf within 5%.
    true_k = 1 / 300.0
    comp = {"acetaminophen": 500.0}
    true_a = true_absorbance(comp)
    strong = true_a >= 0.05  # judge A_inf accuracy where there is signal

    for seed in range(5):
        t, A = simulate_dissolution_arrays(comp, k=true_k, rng=np.random.default_rng(seed))
        fit = fit_kinetics(t, A)
        assert fit.k_pooled is not None
        assert abs(fit.k_pooled - true_k) / true_k < 0.10, f"seed {seed}: k off by >10%"
        rel = np.abs(fit.a_inf[strong] - true_a[strong]) / true_a[strong]
        assert rel.max() < 0.05, f"seed {seed}: A_inf off by {rel.max():.1%}"


def test_early_estimate_converges_with_data():
    t, A = simulate_dissolution_arrays({"caffeine": 100.0}, rng=np.random.default_rng(1))
    early = early_estimate(t[:6], A[:6])       # 3 minutes in: endpoint still moving
    late = early_estimate(t, A)                # full 40-minute run
    assert not early.converged
    assert late.converged
    assert late.k_pooled is not None


def test_early_estimate_handles_too_few_points():
    t, A = simulate_dissolution_arrays({"caffeine": 100.0})
    est = early_estimate(t[:2], A[:2])
    assert est.fit is None
    assert not est.converged


# --- dissolution / f2 ----------------------------------------------------------

def test_f2_of_profile_against_itself_is_100():
    pct = np.array([10.0, 30, 50, 70, 82])
    assert np.isclose(f2_similarity(pct, pct), 100.0)


def test_f2_of_15_percent_shift_fails():
    ref = np.array([10.0, 30, 50, 70, 82])
    shifted = ref - 15.0
    assert f2_similarity(ref, shifted) < 50.0


def test_f2_truncates_after_reference_hits_85():
    # Points after the reference passes 85% must not influence f2.
    ref = np.array([20.0, 50, 80, 90, 95, 99])
    test_a = np.array([20.0, 50, 80, 90, 0, 0])     # differs only after cutoff+1
    assert np.isclose(f2_similarity(ref, test_a), 100.0)


# --- verdict logic -------------------------------------------------------------

def test_verdict_match():
    run = simulate_dissolution_run(
        "run-match", {"acetaminophen": 500.0},
        expected_drug="acetaminophen", rng=np.random.default_rng(2),
    )
    r = evaluate_run(run, LIBRARY, CONFIG)
    assert r.verdict == Verdict.MATCH, r.reasons
    assert r.matched_reference == "acetaminophen"
    assert r.f2 is not None and r.f2 >= 50
    assert r.converged


def test_verdict_substandard_slow_release():
    # Right drug, right dose, but releases 6x too slowly -> f2/Q failure.
    run = simulate_dissolution_run(
        "run-slow", {"acetaminophen": 500.0},
        expected_drug="acetaminophen", k=1 / 1800.0, rng=np.random.default_rng(3),
    )
    r = evaluate_run(run, LIBRARY, CONFIG)
    assert r.verdict == Verdict.SUBSTANDARD, r.reasons
    assert r.matched_reference == "acetaminophen"


def test_verdict_falsified_wrong_drug():
    # Labeled acetaminophen, actually ibuprofen: spectral identity mismatch.
    run = simulate_dissolution_run(
        "run-wrong", {"ibuprofen": 200.0},
        expected_drug="acetaminophen", rng=np.random.default_rng(4),
    )
    r = evaluate_run(run, LIBRARY, CONFIG)
    assert r.verdict == Verdict.FALSIFIED, r.reasons
    assert r.matched_reference == "ibuprofen"


def test_verdict_unknown_substance():
    # Flat broadband absorber: far from every library entry.
    n = LED_WAVELENGTHS.size
    t = np.arange(0, 2400.0, 30.0)
    A = np.outer(1.0 - np.exp(-t / 300.0), np.full(n, 0.4))
    from ..models import DissolutionRun, Reading
    run = DissolutionRun(run_id="run-unknown", wavelengths=list(LED_WAVELENGTHS))
    for i, ti in enumerate(t):
        run.add_reading(Reading(
            t_seconds=float(ti), absorbance=[float(v) for v in A[i]],
            dark=[60.0] * n, blank_ref=[3400.0] * n, temperature=23.0, led_current_mA=20.0,
        ))
    r = evaluate_run(run, LIBRARY, CONFIG)
    assert r.verdict == Verdict.UNKNOWN, r.reasons


def test_verdict_payload_fields():
    run = simulate_dissolution_run("run-payload", {"caffeine": 100.0}, rng=np.random.default_rng(5))
    p = evaluate_run(run, LIBRARY, CONFIG).payload()
    for key in ("verdict", "matched_reference", "spectral_distance", "confidence",
                "k", "f2", "percent_released_at_t_q", "converged", "reasons"):
        assert key in p, key


# --- legacy path -----------------------------------------------------------------

def test_legacy_single_scan_still_classifies():
    a_inf = true_absorbance({"amoxicillin": 250.0})
    scan = ScanEvent(
        scan_id="legacy-1",
        timestamp=datetime.now(timezone.utc),
        wavelengths=list(LED_WAVELENGTHS),
        absorbance=[float(v) for v in a_inf],
        dark=[60.0] * LED_WAVELENGTHS.size,
        blank_ref=[3400.0] * LED_WAVELENGTHS.size,
        temperature=23.0,
    )
    r = evaluate_run(scan.as_run(), LIBRARY, CONFIG)
    assert r.verdict == Verdict.MATCH, r.reasons
    assert r.matched_reference == "amoxicillin"
    assert r.f2 is None and r.k is None
    assert any("dissolution checks skipped" in s for s in r.reasons)


# --- noise model -------------------------------------------------------------------

def test_noise_variance_grows_with_absorbance():
    # Darker sample -> fewer photons -> more absorbance noise.
    params = NoiseParams()
    blank = np.full(4, 3400.0)
    low = absorbance_variance(np.full(4, 0.1), blank, 20.0, params)
    high = absorbance_variance(np.full(4, 1.5), blank, 20.0, params)
    assert np.all(high > low)


def test_monte_carlo_roc_separates_library_from_junk():
    roc = monte_carlo_roc(
        LIBRARY, active_threshold=CONFIG.mahalanobis_threshold,
        n_samples_per_entry=50, n_out_of_library=100,
        rng=np.random.default_rng(0),
    )
    assert roc.auc > 0.95, f"classifier barely separates in/out of library (AUC {roc.auc:.3f})"
    assert roc.fnr_at_active < 0.2
    assert roc.fpr_at_active < 0.2


def test_kalman_tracks_led_drift():
    kf = KalmanDriftCorrector(reference_current_mA=20.0)
    for _ in range(200):
        kf.update(21.0)  # LED running 5% hot
    assert abs(kf.g - 1.05) < 0.01
    corrected = kf.correct_absorbance(np.array([0.5]))
    assert corrected[0] > 0.5  # brighter LED faked a lower absorbance


# --- streaming ----------------------------------------------------------------------

def test_partial_payload_shape():
    run = simulate_dissolution_run("run-partial", {"acetaminophen": 500.0},
                                   rng=np.random.default_rng(6))
    # Simulate mid-run: only first 10 readings.
    run.readings = run.readings[:10]
    p = partial_payload(run, LIBRARY)
    assert p["type"] == "partial_result"
    assert p["n_readings"] == 10
    assert p["projected_match"] == "acetaminophen"
    assert len(p["percent_released"]) == 10


def test_websocket_run_flow():
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # httpx not installed
        return
    from ..server import app
    run = simulate_dissolution_run("ws-run", {"caffeine": 100.0}, rng=np.random.default_rng(7))
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({
                "type": "start_run", "run_id": "ws-run",
                "wavelengths": list(LED_WAVELENGTHS),
                "sample": {"expected_drug": "caffeine"},
            })
            assert ws.receive_json()["type"] == "run_started"
            for reading in run.readings[:5]:
                ws.send_json({"type": "reading", "reading": reading.model_dump()})
                msg = ws.receive_json()
                assert msg["type"] == "partial_result"
            ws.send_json({"type": "end_run"})
            final = ws.receive_json()
            assert final["type"] == "final_result"
            assert final["matched_reference"] == "caffeine"


# --- battle-test regressions -----------------------------------------------------

def test_early_cut_run_still_matches():
    # A genuine run ended long before equilibrium must not read as FALSIFIED
    # (extrapolated A_inf carries fit uncertainty) nor fail Q for lack of
    # waiting (percent at T_q is projected from the fitted kinetics).
    for dur in (120.0, 300.0, 600.0):
        run = simulate_dissolution_run(
            "early-cut", {"acetaminophen": 500.0},
            expected_drug="acetaminophen", duration_s=dur, rng=np.random.default_rng(7),
        )
        r = evaluate_run(run, LIBRARY, CONFIG)
        assert r.verdict == Verdict.MATCH, (dur, r.verdict, r.reasons)


def test_slow_release_never_reads_as_falsified():
    # Slow release means the run ends far from equilibrium; that fit
    # uncertainty must widen Σ, not fake a counterfeit spectrum.
    for seed in range(10):
        rng = np.random.default_rng(seed)
        drug = ["acetaminophen", "ibuprofen", "amoxicillin", "caffeine"][seed % 4]
        dose = {"acetaminophen": 500.0, "ibuprofen": 200.0,
                "amoxicillin": 250.0, "caffeine": 100.0}[drug]
        from ..mock_data import DISSOLUTION_K
        run = simulate_dissolution_run(
            "slow", {drug: dose}, expected_drug=drug,
            k=DISSOLUTION_K[drug] / 6.0, rng=rng,
        )
        r = evaluate_run(run, LIBRARY, CONFIG)
        assert r.verdict == Verdict.SUBSTANDARD, (seed, drug, r.verdict, r.reasons)


def test_normal_dose_variation_passes():
    # USP-style +/-10% manufacturing variation must not trip any failure.
    for pct in (0.9, 0.95, 1.05, 1.1):
        run = simulate_dissolution_run(
            "dose", {"ibuprofen": 200.0 * pct},
            expected_drug="ibuprofen", rng=np.random.default_rng(8),
        )
        r = evaluate_run(run, LIBRARY, CONFIG)
        assert r.verdict == Verdict.MATCH, (pct, r.verdict, r.reasons)


def test_absolute_timestamps_normalized():
    # Firmware stamping epoch/boot seconds instead of run-relative time.
    run = simulate_dissolution_run("epoch", {"caffeine": 100.0},
                                   expected_drug="caffeine", rng=np.random.default_rng(9))
    for r_ in run.readings:
        r_.t_seconds += 1.7e9
    r = evaluate_run(run, LIBRARY, CONFIG)
    assert r.verdict == Verdict.MATCH, r.reasons


def test_nonfinite_reading_rejected():
    from pydantic import ValidationError
    from ..models import Reading
    try:
        Reading(t_seconds=0, absorbance=[float("nan")] * LED_WAVELENGTHS.size,
                dark=[60.0] * LED_WAVELENGTHS.size, blank_ref=[3400.0] * LED_WAVELENGTHS.size,
                temperature=23.0, led_current_mA=20.0)
    except ValidationError:
        return
    raise AssertionError("NaN absorbance must be rejected by Reading validation")


def test_websocket_survives_bad_messages():
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        return
    from ..server import app
    n = LED_WAVELENGTHS.size
    good = {"t_seconds": 10.0, "absorbance": [0.2] * n, "dark": [60.0] * n,
            "blank_ref": [3400.0] * n, "temperature": 23.0, "led_current_mA": 20.0}
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "reading", "reading": good})       # before start_run
            assert ws.receive_json()["type"] == "error"
            ws.send_json({"type": "nonsense"})
            assert ws.receive_json()["type"] == "error"
            ws.send_json({"type": "start_run", "run_id": "abuse",
                          "wavelengths": list(LED_WAVELENGTHS)})
            assert ws.receive_json()["type"] == "run_started"
            ws.send_json({"type": "reading", "reading": good})
            assert ws.receive_json()["type"] == "partial_result"
            bad = dict(good, t_seconds=5.0)                          # out of order
            ws.send_json({"type": "reading", "reading": bad})
            assert ws.receive_json()["type"] == "error"
            ws.send_json({"type": "end_run"})                        # still usable
            assert ws.receive_json()["type"] == "final_result"


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
