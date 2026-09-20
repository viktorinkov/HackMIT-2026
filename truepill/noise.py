"""Physics-based noise model for the TruePill spectrometer.

Per-channel absorbance variance from three sources:

  shot noise   — Poisson counting noise on the detector, variance ∝ intensity;
  read noise   — Gaussian electronics noise, constant in counts;
  LED drift    — slow random-walk of LED output, scaled by how far the drive
                 current sits from the reference current used for the library.

Counts-domain noise is propagated into absorbance units via
A = -log10(I/I_blank)  =>  sigma_A ≈ sigma_I / (I * ln10).

The per-entry covariance Σ used by the Mahalanobis distance is this model
blended with the empirical covariance from repeat scans (shrinkage).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

import numpy as np

_LN10 = np.log(10.0)
_EPS = 1e-12

# np.trapz was renamed np.trapezoid in NumPy 2.0 (the old name still works but
# warns); take whichever this install has.
_trapezoid = getattr(np, "trapezoid", None) or np.trapz


@dataclass(frozen=True)
class NoiseParams:
    # Counts of read noise (std) per channel per reading.
    read_noise_counts: float = 3.0
    # Shot noise: variance in counts = shot_factor * intensity_counts.
    # 1.0 for an ideal Poisson detector; >1 for excess noise.
    shot_factor: float = 1.0
    # LED drift: absorbance-domain random-walk std per unit relative
    # current deviation from the reference drive current.
    drift_per_current_frac: float = 0.01
    # Reference LED drive current the library was recorded at.
    reference_current_mA: float = 20.0
    # Shrinkage weight: Σ = w * Σ_model + (1 - w) * Σ_empirical.
    shrinkage_weight: float = 0.5
    # Std of an absorbance offset shared by EVERY channel of one spectrum
    # (source brightness / coupling wobble between the blank and the sample:
    # a gain g on all channels is -log10(g) added to all of them). Enters Σ as
    # the rank-1 block sd^2 * 1 1^T, so channels are correlated, not
    # independent. 0 keeps the original diagonal model.
    common_mode_abs_sd: float = 0.0


def absorbance_variance(
    a_inf: np.ndarray,
    blank_counts: np.ndarray,
    led_current_mA: float,
    params: NoiseParams,
) -> np.ndarray:
    """Per-channel absorbance variance for a spectrum at the given intensity."""
    a_inf = np.asarray(a_inf, dtype=float)
    blank = np.maximum(np.asarray(blank_counts, dtype=float), 1.0)

    intensity = blank * 10.0 ** (-np.clip(a_inf, 0.0, 6.0))  # counts at detector
    shot_var_counts = params.shot_factor * intensity
    read_var_counts = params.read_noise_counts**2

    # d A / d I = -1 / (I ln10); both sample and blank intensities are noisy,
    # so include the blank's term too.
    var_from_sample = (shot_var_counts + read_var_counts) / (intensity * _LN10) ** 2
    var_from_blank = (params.shot_factor * blank + read_var_counts) / (blank * _LN10) ** 2

    current_frac = abs(led_current_mA - params.reference_current_mA) / params.reference_current_mA
    drift_var = (params.drift_per_current_frac * (1.0 + current_frac)) ** 2

    return var_from_sample + var_from_blank + drift_var


def model_covariance(
    a_inf: np.ndarray,
    blank_counts: np.ndarray,
    led_current_mA: float,
    params: NoiseParams,
) -> np.ndarray:
    """Physics-model covariance: independent per-channel variance on the
    diagonal, plus the common-mode offset shared across channels (if any)."""
    sigma = np.diag(absorbance_variance(a_inf, blank_counts, led_current_mA, params))
    if params.common_mode_abs_sd > 0.0:
        sigma = sigma + params.common_mode_abs_sd**2 * np.ones_like(sigma)
    return sigma


def build_covariance(
    a_inf: np.ndarray,
    blank_counts: np.ndarray,
    empirical_cov: np.ndarray | None,
    params: NoiseParams,
    led_current_mA: float | None = None,
) -> np.ndarray:
    """Shrinkage blend of the physics model and the empirical covariance.

    With no empirical covariance (too few repeat scans) the model is used
    alone. A small ridge keeps Σ invertible.
    """
    current = params.reference_current_mA if led_current_mA is None else led_current_mA
    sigma_model = model_covariance(a_inf, blank_counts, current, params)
    if empirical_cov is None:
        sigma = sigma_model
    else:
        empirical_cov = np.asarray(empirical_cov, dtype=float)
        if empirical_cov.shape != sigma_model.shape:
            raise ValueError("empirical covariance shape does not match spectrum length")
        w = float(np.clip(params.shrinkage_weight, 0.0, 1.0))
        sigma = w * sigma_model + (1.0 - w) * empirical_cov
    return sigma + np.eye(sigma.shape[0]) * _EPS


def mahalanobis_distance(x: np.ndarray, mean: np.ndarray, cov: np.ndarray) -> float:
    """Mahalanobis distance of spectrum x from a library entry (mean, Σ)."""
    diff = np.asarray(x, dtype=float) - np.asarray(mean, dtype=float)
    solved = np.linalg.solve(cov, diff)
    return float(np.sqrt(max(np.dot(diff, solved), 0.0)))


# ---------------------------------------------------------------------------
# Scalar Kalman filter for LED intensity drift
# ---------------------------------------------------------------------------

class KalmanDriftCorrector:
    """Tracks the LED gain g (output relative to blank-time output) so
    absorbance can be corrected before classification.

    Measured intensity I_meas = g * I_true, so A_meas = A_true - log10(g)
    and the correction is A_corr = A_meas + log10(g_hat).

    The measurement proxy for g is the drive-current ratio (LED output is
    ~linear in current over the small deviations we see); the process model
    is a random walk (thermal drift).
    """

    def __init__(
        self,
        reference_current_mA: float,
        process_var: float = 1e-5,
        measurement_var: float = 1e-4,
    ) -> None:
        self.ref_current = reference_current_mA
        self.q = process_var
        self.r = measurement_var
        self.g = 1.0
        self.p = 1e-2

    def update(self, led_current_mA: float) -> float:
        """Ingest one reading's drive current; returns the current gain estimate."""
        # Predict (random walk: state unchanged, uncertainty grows)
        self.p += self.q
        # Update with the current-ratio measurement
        z = led_current_mA / self.ref_current
        k_gain = self.p / (self.p + self.r)
        self.g += k_gain * (z - self.g)
        self.p *= 1.0 - k_gain
        return self.g

    def correct_absorbance(self, absorbance: np.ndarray) -> np.ndarray:
        return np.asarray(absorbance, dtype=float) + np.log10(max(self.g, _EPS))


# ---------------------------------------------------------------------------
# Monte Carlo classifier validation
# ---------------------------------------------------------------------------

@dataclass
class RocResult:
    thresholds: np.ndarray
    tpr: np.ndarray
    fpr: np.ndarray
    active_threshold: float
    fpr_at_active: float
    fnr_at_active: float
    n_positive: int
    n_negative: int
    auc: float = field(default=0.0)


def monte_carlo_roc(
    entries: list,                      # ReferenceEntry-like: .mean_a_inf, .covariance
    active_threshold: float,
    n_samples_per_entry: int = 200,
    n_out_of_library: int = 400,
    rng: np.random.Generator | None = None,
) -> RocResult:
    """Draw synthetic in-library and out-of-library spectra, score them with
    the min-Mahalanobis classifier, and report the ROC plus FPR/FNR at the
    active threshold.

    Score convention: lower = more in-library. A spectrum is accepted when its
    minimum distance across the library is <= threshold.
    """
    from .classification import _scaled_mahalanobis  # same scorer the classifier uses

    rng = rng or np.random.default_rng(0)
    means = [np.asarray(e.mean_a_inf, dtype=float) for e in entries]
    covs = [np.asarray(e.covariance, dtype=float) for e in entries]
    n_ch = means[0].size

    def min_distance(x: np.ndarray) -> float:
        return min(_scaled_mahalanobis(x, m, c)[1] for m, c in zip(means, covs))

    # Positives: draws from each entry's own model.
    pos_scores = []
    for m, c in zip(means, covs):
        draws = rng.multivariate_normal(m, c, size=n_samples_per_entry)
        pos_scores.extend(min_distance(x) for x in draws)
    pos_scores = np.array(pos_scores)

    # Negatives: out-of-library spectra — random convex mixtures of library
    # shapes with channel shuffles and scale jitter, i.e. plausible but wrong.
    neg_scores = []
    for _ in range(n_out_of_library):
        base = means[rng.integers(len(means))].copy()
        rng.shuffle(base)                                # destroy the shape
        mix = rng.random()
        other = means[rng.integers(len(means))]
        x = mix * base + (1 - mix) * other
        x = x * rng.uniform(0.5, 1.5) + rng.normal(0, 0.02, n_ch)
        neg_scores.append(min_distance(np.clip(x, 0.0, None)))
    neg_scores = np.array(neg_scores)

    thresholds = np.unique(np.concatenate([pos_scores, neg_scores, [active_threshold]]))
    tpr = np.array([(pos_scores <= t).mean() for t in thresholds])
    fpr = np.array([(neg_scores <= t).mean() for t in thresholds])
    order = np.argsort(fpr)
    auc = float(_trapezoid(tpr[order], fpr[order]))

    return RocResult(
        thresholds=thresholds,
        tpr=tpr,
        fpr=fpr,
        active_threshold=active_threshold,
        fpr_at_active=float((neg_scores <= active_threshold).mean()),
        fnr_at_active=float((pos_scores > active_threshold).mean()),
        n_positive=pos_scores.size,
        n_negative=neg_scores.size,
        auc=auc,
    )


def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Monte Carlo validation of the TruePill spectral classifier "
        "(uses the built-in mock reference library)."
    )
    parser.add_argument("--threshold", type=float, default=4.0, help="active Mahalanobis threshold")
    parser.add_argument("--samples", type=int, default=200, help="synthetic samples per library entry")
    parser.add_argument("--negatives", type=int, default=400, help="out-of-library samples")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    from .mock_data import build_reference_library

    entries = build_reference_library()
    roc = monte_carlo_roc(
        entries,
        active_threshold=args.threshold,
        n_samples_per_entry=args.samples,
        n_out_of_library=args.negatives,
        rng=np.random.default_rng(args.seed),
    )
    print(f"library entries : {len(entries)}")
    print(f"positives/negatives : {roc.n_positive}/{roc.n_negative}")
    print(f"AUC : {roc.auc:.4f}")
    print(f"at threshold {roc.active_threshold:g}: FPR={roc.fpr_at_active:.3f}  FNR={roc.fnr_at_active:.3f}")
    print("\nROC (threshold  FPR  TPR):")
    idx = np.linspace(0, roc.thresholds.size - 1, min(15, roc.thresholds.size)).astype(int)
    for i in idx:
        print(f"  {roc.thresholds[i]:8.3f}  {roc.fpr[i]:.3f}  {roc.tpr[i]:.3f}")


if __name__ == "__main__":
    _cli()
