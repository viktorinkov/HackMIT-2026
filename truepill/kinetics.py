"""Dissolution kinetics: fit A(t) = A_inf * (1 - exp(-k t)) per channel.

The equilibrium spectrum A_inf is the spectral fingerprint (what drug);
the rate constant k is the dissolution fingerprint (does the tablet release
it properly).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import curve_fit

# A_inf below this (absorbance units) -> channel carries no analyte signal
# and is excluded from the pooled-k weighting.
MIN_CHANNEL_A_INF = 0.02
# Convergence: pooled A_inf changed by less than this fraction...
CONVERGENCE_TOL = 0.02
# ...across this many trailing readings.
CONVERGENCE_WINDOW = 5
# Minimum readings before a fit is attempted at all.
MIN_POINTS = 3
# A_inf is bounded to this multiple of the max observed absorbance: early in
# a run the exponential is still ~linear and A_inf is otherwise unconstrained
# (the fit happily returns A_inf -> inf, k -> 0). A tablet that has released
# >= 1/3 of its dose shows enough curvature to fit inside this bound.
A_INF_CAP_FACTOR = 3.0
# Fastest plausible rate constant (1/s); sub-second dissolution is noise.
K_MAX = 1.0

_EPS = 1e-12


def _model(t: np.ndarray, a_inf: float, k: float) -> np.ndarray:
    return a_inf * (1.0 - np.exp(-k * t))


@dataclass
class KineticsFit:
    a_inf: np.ndarray            # per-channel equilibrium absorbance
    k: np.ndarray                # per-channel rate constant (nan where fit failed)
    k_pooled: float | None       # SNR-weighted pooled rate constant
    r_squared: np.ndarray        # per-channel R^2 (0 where fit failed)
    residuals: np.ndarray        # (n_times, n_channels) data - model
    n_readings: int
    fitted_channels: np.ndarray = field(default_factory=lambda: np.array([], dtype=bool))
    # Estimation variance of each A_inf (curve_fit covariance). A run cut
    # before equilibrium extrapolates A_inf with real uncertainty; the
    # spectral match adds this to Σ so extrapolation error is not mistaken
    # for a counterfeit spectrum.
    a_inf_var: np.ndarray = field(default_factory=lambda: np.array([]))


@dataclass
class EarlyEstimate:
    a_inf: np.ndarray            # current best equilibrium spectrum
    k_pooled: float | None
    converged: bool
    n_readings: int
    fit: KineticsFit | None      # full fit on all data so far (None if < MIN_POINTS)


def _fit_channel(t: np.ndarray, y: np.ndarray) -> tuple[float, float, float] | None:
    """Fit one channel; returns (a_inf, k, a_inf_variance) or None on failure."""
    y_max = float(y.max(initial=0.0))
    if y_max < _EPS:
        return None
    # Initial guesses: endpoint for A_inf; k from the time to reach ~63% of max.
    t63 = t[np.argmax(y >= 0.63 * y_max)] if np.any(y >= 0.63 * y_max) else t[-1]
    k0 = min(1.0 / max(float(t63), _EPS), K_MAX)
    a_inf_cap = A_INF_CAP_FACTOR * y_max
    try:
        popt, pcov = curve_fit(
            _model,
            t,
            y,
            p0=[min(y_max, a_inf_cap), k0],
            bounds=([0.0, _EPS], [a_inf_cap, K_MAX]),
            maxfev=2000,
        )
    except (RuntimeError, ValueError):
        return None
    var = float(pcov[0, 0])
    if not np.isfinite(var):
        # Degenerate fit (e.g. railed at a bound): uncertainty is at least
        # the full extrapolation span.
        var = (a_inf_cap - y_max) ** 2
    return float(popt[0]), float(popt[1]), var


def fit_kinetics(t: np.ndarray, absorbance: np.ndarray) -> KineticsFit:
    """Fit the first-order dissolution model on every channel.

    t: (n_times,) seconds. absorbance: (n_times, n_channels).
    """
    t = np.asarray(t, dtype=float)
    A = np.atleast_2d(np.asarray(absorbance, dtype=float))
    n_times, n_channels = A.shape
    if t.shape != (n_times,):
        raise ValueError("t must have one entry per absorbance row")
    if n_times < MIN_POINTS:
        raise ValueError(f"need at least {MIN_POINTS} readings to fit kinetics, got {n_times}")

    a_inf = np.zeros(n_channels)
    k = np.full(n_channels, np.nan)
    r2 = np.zeros(n_channels)
    fitted = np.zeros(n_channels, dtype=bool)
    residuals = np.zeros_like(A)
    a_inf_var = np.zeros(n_channels)

    for c in range(n_channels):
        y = A[:, c]
        result = _fit_channel(t, y)
        if result is None:
            # No signal or fit failure: report the endpoint level, no rate.
            a_inf[c] = float(y[-1]) if n_times else 0.0
            residuals[:, c] = y - a_inf[c]
            a_inf_var[c] = float(np.var(y)) if n_times else 0.0
            continue
        a_inf[c], k[c], a_inf_var[c] = result
        fitted[c] = True
        pred = _model(t, a_inf[c], k[c])
        residuals[:, c] = y - pred
        ss_res = float(np.sum(residuals[:, c] ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2[c] = 1.0 - ss_res / ss_tot if ss_tot > _EPS else 0.0

    # Pooled k: weight channels by squared SNR (signal / residual noise).
    usable = fitted & (a_inf >= MIN_CHANNEL_A_INF)
    k_pooled: float | None = None
    if np.any(usable):
        resid_std = residuals[:, usable].std(axis=0)
        snr = a_inf[usable] / np.maximum(resid_std, _EPS)
        weights = snr**2
        k_pooled = float(np.sum(weights * k[usable]) / np.sum(weights))

    return KineticsFit(
        a_inf=a_inf,
        k=k,
        k_pooled=k_pooled,
        r_squared=r2,
        residuals=residuals,
        n_readings=n_times,
        fitted_channels=usable,
        a_inf_var=a_inf_var,
    )


def early_estimate(t: np.ndarray, absorbance: np.ndarray) -> EarlyEstimate:
    """Best current A_inf and k from partial data, with a convergence flag.

    Converged means the pooled A_inf estimate moved by less than
    CONVERGENCE_TOL (relative, L2) across each of the last CONVERGENCE_WINDOW
    readings — i.e. the projected endpoint has stopped drifting and the
    dashboard can trust it.
    """
    t = np.asarray(t, dtype=float)
    A = np.atleast_2d(np.asarray(absorbance, dtype=float))
    n = A.shape[0]

    if n < MIN_POINTS:
        current = A[-1] if n else np.zeros(A.shape[1])
        return EarlyEstimate(a_inf=current, k_pooled=None, converged=False, n_readings=n, fit=None)

    full = fit_kinetics(t, A)

    converged = False
    if n >= MIN_POINTS + CONVERGENCE_WINDOW:
        prev_norm: float | None = None
        converged = True
        for m in range(n - CONVERGENCE_WINDOW, n + 1):
            est = fit_kinetics(t[:m], A[:m]).a_inf
            norm = float(np.linalg.norm(est))
            if prev_norm is not None:
                denom = max(prev_norm, _EPS)
                if abs(norm - prev_norm) / denom >= CONVERGENCE_TOL:
                    converged = False
                    break
            prev_norm = norm

    return EarlyEstimate(
        a_inf=full.a_inf,
        k_pooled=full.k_pooled,
        converged=converged,
        n_readings=n,
        fit=full,
    )
