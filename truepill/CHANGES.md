# TruePill: time-resolved dissolution pipeline

> Design notes from the original build, kept for the rationale behind each
> threshold. Two things from that build are **not in this repository**: the
> published reference spectra with `spectral_db.py` (licence terms unchecked
> for a public repo) and a Supabase migration (this project stores in
> Elastic). Commands below are in package form; run them from the directory
> that holds `truepill/`. For the rig tuning see HARDWARE_TUNING.md.

## What changed

The pipeline moved from a single snapshot scan to a ~1 Hz time series taken
while the tablet dissolves. One run now yields **two fingerprints**:

1. **Spectral (what drug):** the equilibrium spectrum `A_inf`, extrapolated
   from the kinetics fit — not a raw snapshot — is L2-normalized and matched
   against the reference library (cosine ranking + Mahalanobis distance +
   NNLS unmixing, unchanged logic otherwise).
2. **Kinetic (does it release properly):** the first-order rate constant `k`
   from `A(t) = A_inf · (1 − e^(−kt))`, plus the percent-released profile
   compared to the reference via the FDA f2 similarity factor and a Q-test.

The empirical noise estimate is replaced by a physics model (shot + read +
LED-drift), blended with empirical covariance from repeat scans (shrinkage),
and that Σ drives the Mahalanobis distance.

## Data flow

```
firmware ──WS──> server.py            start_run / reading / end_run  (legacy "scan" still accepted)
                   │  per reading
                   ├─ kinetics.early_estimate ──> partial_result {A_inf, k, converged, %released}
                   │  on end_run / max duration
                   └─ verdict.evaluate_run
                        ├─ kinetics.fit_kinetics        A_inf, per-channel k, pooled k, R²
                        ├─ classification.match_spectrum cosine + Mahalanobis(Σ) + NNLS on A_inf
                        ├─ dissolution.compare_profiles  %released, f2, Q-test vs matched reference
                        └─ final_result {verdict, reference, distance, k, f2, %@T_q, reasons[]}
```

Legacy single-scan payloads become a run with one reading: they classify
spectrally as before and skip the dissolution checks (verdict limited to
MATCH / FALSIFIED / UNKNOWN).

## Verdicts

| Verdict | Meaning |
|---|---|
| `MATCH` | Spectral match **and** dissolution equivalent |
| `SUBSTANDARD` | Right drug, wrong release: f2 < cutoff or Q-test fails |
| `FALSIFIED` | Spectral distance beyond threshold (or label/spectrum mismatch) |
| `UNKNOWN` | Far from every library entry, or no signal |

## Tunable thresholds

| Knob | Default | Where |
|---|---|---|
| Mahalanobis spectral threshold | 4.0 | `verdict.PipelineConfig.mahalanobis_threshold` |
| UNKNOWN cosine floor (far from everything) | 0.935 | `verdict.PipelineConfig.unknown_cosine_floor` |
| f2 equivalence cutoff | 50 | `verdict.PipelineConfig.f2_cutoff` |
| Q (percent released required) | 80% | `verdict.PipelineConfig.q_percent` |
| T_q (when Q is checked) | 1800 s | `verdict.PipelineConfig.t_q_seconds` |
| Shrinkage weight (Σ = w·model + (1−w)·empirical) | 0.5 | `noise.NoiseParams.shrinkage_weight` |
| Convergence: A_inf change / window | <2% over 5 readings | `kinetics.CONVERGENCE_TOL/WINDOW` |
| f2 reference cutoff (FDA 85% rule) | 85% | `dissolution.F2_RELEASE_CUTOFF` |

Validate any threshold change with the Monte Carlo CLI:

```
python -m truepill.noise --threshold 4.0
```

prints the ROC and FPR/FNR at the active threshold using synthetic draws
from each library entry's noise model vs. out-of-library spectra.

## New / changed modules

- `models.py` — Pydantic `Reading`, `DissolutionRun`, legacy `ScanEvent`
  (+ `as_run()`), WebSocket message schemas.
- `kinetics.py` — bounded per-channel `curve_fit`, SNR²-weighted pooled k,
  R², residuals; `early_estimate()` with the convergence flag. A_inf is
  bounded to 3× the max observed absorbance so early, still-linear data
  can't send the extrapolation to infinity.
- `dissolution.py` — percent released (least-squares projection onto the
  matched reference's A_inf), common-grid resampling, f2 (with the 85%
  truncation rule), Q-test.
- `noise.py` — physics noise model, Σ builder with shrinkage,
  `mahalanobis_distance`, Monte Carlo ROC (function + CLI), and an optional
  scalar Kalman LED-drift corrector (`KalmanDriftCorrector`).
- `library.py` — `ReferenceEntry` (mean A_inf, Σ, dissolution profile ± std,
  mean k) and `build_entry_from_runs()` for N repeat runs.
- `classification.py` — **additive only**: new `match_spectrum()` for the
  A_inf path; all previous public functions unchanged (old tests still pass).
- `verdict.py` — `PipelineConfig`, `evaluate_run()`, `partial_payload()`,
  the four-way `Verdict` enum, JSON-safe result payload.
- `server.py` — FastAPI WebSocket: incremental readings, `partial_result`
  after each, `final_result` on `end_run` or max duration; legacy `scan`
  message handled inline. Run: `uvicorn truepill.server:app`.

## Battle-test hardening (post-initial-build)

Adversarial testing (hostile inputs, 150-run verdict confusion matrix, dose/
rate/noise sweeps, WebSocket protocol abuse, 1 Hz latency budget) drove these
changes:

- **Scale-invariant Mahalanobis.** Identity is judged on spectral shape: the
  best amplitude is fitted first (GLS), then distance is measured on the
  residual. Dose deviation therefore flows to the Q-test/f2 (→ SUBSTANDARD,
  per WHO terminology) instead of inflating spectral distance (→ FALSIFIED).
  The best-fit scale is reported as an estimated dose ratio in `reasons[]`.
- **Fit uncertainty widens Σ.** The kinetics fit's per-channel A_inf variance
  (curve_fit covariance) is added to Σ before the Mahalanobis test, so a run
  ended before equilibrium — where A_inf is extrapolated — cannot read as a
  counterfeit. Slow-release and early-cut runs now land on SUBSTANDARD/MATCH
  correctly (previously ~8% false FALSIFIED in those scenarios).
- **Q-test projection.** If the run ends before T_q, percent released at T_q
  is projected from the fitted kinetics instead of clamping to the last
  observation; the reason string says "[projected from fitted kinetics]".
- **Run-relative time.** `evaluate_run` normalizes t to t − t[0], so firmware
  stamping epoch/boot seconds works; a zero-time-span burst of readings falls
  back to the snapshot path instead of crashing.
- **Ingestion validation.** `Reading` rejects NaN/inf in any field with a
  clear Pydantic error; the WebSocket handler catches evaluation errors and
  replies `{"type": "error"}` instead of dropping the connection.

Measured behavior at defaults (mock data): 150/150 correct verdicts across
genuine / underdosed / slow-release / wrong-drug / cut / counterfeit
scenarios; dose boundary MATCH within 85–110% of label; genuine pills robust
to 8× default noise; partial_result ≤ 130 ms at 3600 readings (1 Hz budget is
1000 ms); Monte Carlo AUC 0.997, FPR 1% / FNR 2.3% at threshold 4.0.

## Published reference spectra

The original build also carried `spectral_db.py`, which built `ReferenceEntry`s
from measured NIST and PhotochemCAD spectra. It is not in this repository
(see the note at the top). Its one finding that still matters here: on a
visible-only LED arc, acetaminophen, caffeine and aspirin cannot be seen at
all - their absorption stops in the UV.

## Tests

`tests/test_pipeline.py` (23) — kinetics recovery (k within 10%, A_inf
within 5% at default noise), f2 identities and the 15%-shift failure case,
all four verdicts, legacy payload compatibility, noise-model sanity, Monte
Carlo separation, Kalman drift tracking, partial payload shape, a full
WebSocket run flow, and the battle-test regressions (early-cut runs, slow
release never FALSIFIED, ±10% dose passes, epoch timestamps, NaN rejection,
socket survives bad messages). `tests/test_classification.py` (15) — the
snapshot layer, unchanged and still green.

`tests/test_hardware.py` (20), `tests/test_usage.py` (10) and
`tests/test_relocatable.py` (3) came with the rig tuning and the packaging;
HARDWARE_TUNING.md and README.md cover them. Run everything with
`python -m pytest truepill` .
