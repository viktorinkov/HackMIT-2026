"""Dissolution profile comparison: percent released, f2 similarity, Q-test.

Percent released at each time point is the least-squares projection of the
measured spectrum onto the matched reference's A_inf spectrum — the same
Beer-Lambert scale estimate used for concentration, expressed as a percent
of the reference endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# FDA guidance: use points up to (and including) the first where the
# REFERENCE profile exceeds this percent released.
F2_RELEASE_CUTOFF = 85.0
# f2 >= 50 -> profiles are considered equivalent.
F2_EQUIVALENCE = 50.0
# Q-test defaults: >= Q percent released by T_q seconds.
DEFAULT_T_Q_SECONDS = 1800.0
DEFAULT_Q_PERCENT = 80.0

_EPS = 1e-12


def percent_released(absorbance: np.ndarray, reference_a_inf: np.ndarray) -> np.ndarray:
    """Percent-released series for a run.

    absorbance: (n_times, n_channels); reference_a_inf: (n_channels,).
    Returns (n_times,) percent values (can exceed 100 for an over-dosed pill).
    """
    A = np.atleast_2d(np.asarray(absorbance, dtype=float))
    ref = np.asarray(reference_a_inf, dtype=float)
    denom = float(np.dot(ref, ref))
    if denom < _EPS:
        raise ValueError("reference A_inf spectrum is all zeros")
    scale = A @ ref / denom
    return 100.0 * np.clip(scale, 0.0, None)


def resample_profile(t: np.ndarray, pct: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Linear-interpolate a percent-released profile onto a common time grid."""
    t = np.asarray(t, dtype=float)
    pct = np.asarray(pct, dtype=float)
    return np.interp(np.asarray(grid, dtype=float), t, pct)


def common_grid(
    t_sample: np.ndarray, t_reference: np.ndarray, n_points: int = 50
) -> np.ndarray:
    """Common time grid over the overlap of the two profiles."""
    lo = max(float(np.min(t_sample)), float(np.min(t_reference)))
    hi = min(float(np.max(t_sample)), float(np.max(t_reference)))
    if hi <= lo:
        raise ValueError("sample and reference profiles do not overlap in time")
    return np.linspace(lo, hi, n_points)


def f2_similarity(reference_pct: np.ndarray, test_pct: np.ndarray) -> float:
    """f2 similarity factor between two profiles on the SAME time grid.

        f2 = 50 * log10( 100 / sqrt(1 + (1/n) * sum((R_t - T_t)^2)) )

    Only points up to and including the first where the reference exceeds
    F2_RELEASE_CUTOFF are used, per FDA guidance.
    """
    R = np.asarray(reference_pct, dtype=float)
    T = np.asarray(test_pct, dtype=float)
    if R.shape != T.shape:
        raise ValueError("profiles must be on the same time grid")
    over = np.nonzero(R > F2_RELEASE_CUTOFF)[0]
    if over.size:
        end = over[0] + 1  # include the first point past the cutoff
        R, T = R[:end], T[:end]
    if R.size == 0:
        raise ValueError("no usable points for f2")
    msd = float(np.mean((R - T) ** 2))
    return float(50.0 * np.log10(100.0 / np.sqrt(1.0 + msd)))


@dataclass
class DissolutionComparison:
    f2: float
    f2_equivalent: bool
    percent_at_t_q: float
    q_pass: bool
    t_q_seconds: float
    q_percent: float
    grid: np.ndarray
    sample_pct: np.ndarray
    reference_pct: np.ndarray


def compare_profiles(
    t_sample: np.ndarray,
    sample_pct: np.ndarray,
    t_reference: np.ndarray,
    reference_pct: np.ndarray,
    t_q_seconds: float = DEFAULT_T_Q_SECONDS,
    q_percent: float = DEFAULT_Q_PERCENT,
    n_grid: int = 50,
) -> DissolutionComparison:
    """Full comparison: resample both profiles, compute f2 and the Q-test."""
    grid = common_grid(t_sample, t_reference, n_points=n_grid)
    s = resample_profile(t_sample, sample_pct, grid)
    r = resample_profile(t_reference, reference_pct, grid)
    f2 = f2_similarity(r, s)

    # Percent released at T_q: interpolate; if the run ended before T_q, use
    # the last observed value (conservative — no extrapolated credit).
    pct_at_tq = float(np.interp(t_q_seconds, t_sample, sample_pct))

    return DissolutionComparison(
        f2=f2,
        f2_equivalent=f2 >= F2_EQUIVALENCE,
        percent_at_t_q=pct_at_tq,
        q_pass=pct_at_tq >= q_percent,
        t_q_seconds=t_q_seconds,
        q_percent=q_percent,
        grid=grid,
        sample_pct=s,
        reference_pct=r,
    )
