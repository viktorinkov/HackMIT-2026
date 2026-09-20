"""Reference library for time-resolved TruePill entries.

Each entry stores the equilibrium spectrum statistics (mean A_inf + Σ), the
mean dissolution profile with per-point spread, and the mean rate constant —
everything the classifier and dissolution comparison need.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .kinetics import fit_kinetics
from .dissolution import percent_released, resample_profile
from .noise import NoiseParams, build_covariance


@dataclass
class ReferenceEntry:
    name: str
    wavelengths: np.ndarray
    mean_a_inf: np.ndarray          # mean equilibrium absorbance spectrum
    covariance: np.ndarray          # Σ (model ⊕ empirical shrinkage blend)
    profile_t: np.ndarray           # dissolution profile time grid (s)
    profile_pct_mean: np.ndarray    # mean percent released at each grid point
    profile_pct_std: np.ndarray     # per-point std across repeat runs
    mean_k: float                   # mean pooled rate constant (1/s)
    expected_concentration: float = 0.0
    is_active_ingredient: bool = True
    n_runs: int = 0
    metadata: dict = field(default_factory=dict)


def build_entry_from_runs(
    name: str,
    wavelengths: np.ndarray,
    runs: list[tuple[np.ndarray, np.ndarray]],   # [(t, absorbance(n_t, n_ch)), ...]
    blank_counts: np.ndarray,
    noise_params: NoiseParams | None = None,
    expected_concentration: float = 0.0,
    is_active_ingredient: bool = True,
    profile_grid: np.ndarray | None = None,
) -> ReferenceEntry:
    """Build a library entry from N repeat dissolution runs of a known-good
    sample.

    Per run: fit kinetics for A_inf and pooled k. Across runs: mean A_inf,
    empirical covariance of A_inf (when N >= 3), and the mean/std percent-
    released profile on a common grid. Σ blends the physics noise model with
    the empirical covariance (shrinkage weight in `noise_params`).
    """
    if not runs:
        raise ValueError("need at least one run to build a library entry")
    noise_params = noise_params or NoiseParams()

    fits = [fit_kinetics(t, A) for t, A in runs]
    a_inf_stack = np.vstack([f.a_inf for f in fits])
    mean_a_inf = a_inf_stack.mean(axis=0)

    ks = [f.k_pooled for f in fits if f.k_pooled is not None]
    if not ks:
        raise ValueError(f"no run of {name!r} produced a usable rate constant")
    mean_k = float(np.mean(ks))

    empirical_cov = np.cov(a_inf_stack, rowvar=False) if len(runs) >= 3 else None
    covariance = build_covariance(mean_a_inf, blank_counts, empirical_cov, noise_params)

    # Mean dissolution profile: each run's percent released against the
    # entry's own mean A_inf, resampled onto a shared grid.
    if profile_grid is None:
        t_max = min(float(t[-1]) for t, _ in runs)
        profile_grid = np.linspace(0.0, t_max, 50)
    profiles = []
    for t, A in runs:
        pct = percent_released(A, mean_a_inf)
        profiles.append(resample_profile(t, pct, profile_grid))
    profiles = np.vstack(profiles)

    return ReferenceEntry(
        name=name,
        wavelengths=np.asarray(wavelengths, dtype=float),
        mean_a_inf=mean_a_inf,
        covariance=covariance,
        profile_t=profile_grid,
        profile_pct_mean=profiles.mean(axis=0),
        profile_pct_std=profiles.std(axis=0),
        mean_k=mean_k,
        expected_concentration=expected_concentration,
        is_active_ingredient=is_active_ingredient,
        n_runs=len(runs),
    )
