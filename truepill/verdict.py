"""Run evaluation and the four-way verdict.

    spectral distance beyond threshold        -> FALSIFIED
    ... and far from EVERY library entry      -> UNKNOWN
    spectral match, but f2 < 50 or Q fails    -> SUBSTANDARD
    spectral match and dissolution passes     -> MATCH

Single-reading (legacy snapshot) runs skip the dissolution checks — there is
no kinetics to judge — and can only yield MATCH / FALSIFIED / UNKNOWN.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from .classification import MATCH_THRESHOLD, SpectralMatch, match_spectrum
from .dissolution import (
    DEFAULT_Q_PERCENT,
    DEFAULT_T_Q_SECONDS,
    F2_EQUIVALENCE,
    DissolutionComparison,
    compare_profiles,
    percent_released,
)
from .kinetics import EarlyEstimate, early_estimate
from .library import ReferenceEntry
from .models import DissolutionRun


class Verdict(str, Enum):
    MATCH = "MATCH"
    SUBSTANDARD = "SUBSTANDARD"
    FALSIFIED = "FALSIFIED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PipelineConfig:
    """All tunable thresholds in one place (documented in CHANGES.md)."""

    # Mahalanobis distance above this -> not the matched drug.
    mahalanobis_threshold: float = 4.0
    # Cosine similarity below this against EVERY entry -> UNKNOWN
    # (far from everything, can't even name what it isn't).
    unknown_cosine_floor: float = MATCH_THRESHOLD
    # f2 below this -> dissolution profiles not equivalent.
    f2_cutoff: float = F2_EQUIVALENCE
    # Q-test: >= q_percent released by t_q_seconds.
    t_q_seconds: float = DEFAULT_T_Q_SECONDS
    q_percent: float = DEFAULT_Q_PERCENT


@dataclass
class RunResult:
    verdict: Verdict
    matched_reference: str | None
    spectral_distance: float | None      # Mahalanobis to matched entry
    spectral_cosine: float | None
    confidence: str                      # high | medium | none
    k: float | None                      # pooled dissolution rate constant
    f2: float | None
    percent_released_at_t_q: float | None
    converged: bool
    reasons: list[str] = field(default_factory=list)
    composition: dict[str, float] = field(default_factory=dict)
    a_inf: np.ndarray | None = None
    comparison: DissolutionComparison | None = None

    def payload(self) -> dict[str, Any]:
        """JSON-safe result for the WebSocket / dashboard."""
        return {
            "verdict": self.verdict.value,
            "matched_reference": self.matched_reference,
            "spectral_distance": self.spectral_distance,
            "spectral_cosine": self.spectral_cosine,
            "confidence": self.confidence,
            "k": self.k,
            "f2": self.f2,
            "percent_released_at_t_q": self.percent_released_at_t_q,
            "converged": self.converged,
            "reasons": self.reasons,
            "composition": self.composition,
            "a_inf": None if self.a_inf is None else [float(v) for v in self.a_inf],
        }


def _run_arrays(run: DissolutionRun) -> tuple[np.ndarray, np.ndarray]:
    t = np.array([r.t_seconds for r in run.readings], dtype=float)
    A = np.array([r.absorbance for r in run.readings], dtype=float)
    if not np.isfinite(A).all() or not np.isfinite(t).all():
        raise ValueError("run contains non-finite readings")
    # Firmware may stamp absolute time (epoch/boot seconds); kinetics and the
    # dissolution comparison work in run-relative time.
    if t.size:
        t = t - t[0]
    return t, A


def evaluate_run(
    run: DissolutionRun,
    references: list[ReferenceEntry],
    config: PipelineConfig | None = None,
) -> RunResult:
    """Full evaluation of a (finished) run: kinetics -> spectral match on
    A_inf -> dissolution comparison -> verdict."""
    config = config or PipelineConfig()
    if not run.readings:
        raise ValueError("run has no readings")

    t, A = _run_arrays(run)
    # Kinetics/dissolution need real time coverage; a burst of readings at
    # (nearly) one instant is treated as a snapshot.
    time_resolved = len(run.readings) >= 3 and float(t[-1] - t[0]) > 0.0

    # --- kinetics: A_inf is the spectral fingerprint --------------------------
    if time_resolved:
        est: EarlyEstimate = early_estimate(t, A)
        a_inf = est.a_inf
        k = est.k_pooled
        converged = est.converged
    else:
        # Legacy snapshot (or too-short run): the reading IS the spectrum.
        a_inf = A[-1]
        k = None
        converged = False

    reasons: list[str] = []
    if time_resolved and not converged:
        reasons.append("run ended before the A_inf estimate converged; endpoint is extrapolated")

    if float(np.max(a_inf, initial=0.0)) < 1e-3:
        return RunResult(
            verdict=Verdict.UNKNOWN,
            matched_reference=None,
            spectral_distance=None,
            spectral_cosine=None,
            confidence="none",
            k=k,
            f2=None,
            percent_released_at_t_q=None,
            converged=converged,
            reasons=["no absorbance signal - empty cuvette or blank sample?"],
            a_inf=a_inf,
        )

    # --- spectral identification ----------------------------------------------
    a_inf_var = est.fit.a_inf_var if time_resolved and est.fit is not None else None
    match: SpectralMatch = match_spectrum(a_inf, references, a_inf_var=a_inf_var)
    ref = next(r for r in references if r.name == match.best_name)
    best_cosine_anywhere = max(cos for cos, _ in match.per_entry.values())

    spectral_ok = match.mahalanobis <= config.mahalanobis_threshold

    if not spectral_ok:
        if best_cosine_anywhere < config.unknown_cosine_floor:
            reasons.append(
                f"spectrum far from every library entry "
                f"(best cosine {best_cosine_anywhere:.3f} < {config.unknown_cosine_floor})"
            )
            return RunResult(
                verdict=Verdict.UNKNOWN,
                matched_reference=None,
                spectral_distance=match.mahalanobis,
                spectral_cosine=match.cosine,
                confidence="none",
                k=k,
                f2=None,
                percent_released_at_t_q=None,
                converged=converged,
                reasons=reasons,
                composition=match.composition,
                a_inf=a_inf,
            )
        reasons.append(
            f"spectral distance {match.mahalanobis:.2f} exceeds threshold "
            f"{config.mahalanobis_threshold} (closest: {match.best_name})"
        )
        return RunResult(
            verdict=Verdict.FALSIFIED,
            matched_reference=match.best_name,
            spectral_distance=match.mahalanobis,
            spectral_cosine=match.cosine,
            confidence="none",
            k=k,
            f2=None,
            percent_released_at_t_q=None,
            converged=converged,
            reasons=reasons,
            composition=match.composition,
            a_inf=a_inf,
        )

    confidence = "high" if match.mahalanobis <= 0.5 * config.mahalanobis_threshold else "medium"
    reasons.append(
        f"spectral match: {match.best_name} "
        f"(Mahalanobis {match.mahalanobis:.2f}, cosine {match.cosine:.3f})"
    )
    if abs(match.scale - 1.0) > 0.20:
        reasons.append(f"estimated dose ~{match.scale:.0%} of reference")

    # Label mismatch is a spectral-identity failure, not a dissolution one.
    expected = run.sample.expected_drug
    if expected and expected != match.best_name:
        reasons.append(f"labeled as {expected!r} but spectrum matches {match.best_name!r}")
        return RunResult(
            verdict=Verdict.FALSIFIED,
            matched_reference=match.best_name,
            spectral_distance=match.mahalanobis,
            spectral_cosine=match.cosine,
            confidence=confidence,
            k=k,
            f2=None,
            percent_released_at_t_q=None,
            converged=converged,
            reasons=reasons,
            composition=match.composition,
            a_inf=a_inf,
        )

    # --- dissolution comparison -------------------------------------------------
    if not time_resolved:
        reasons.append("single-reading run: dissolution checks skipped")
        return RunResult(
            verdict=Verdict.MATCH,
            matched_reference=match.best_name,
            spectral_distance=match.mahalanobis,
            spectral_cosine=match.cosine,
            confidence=confidence,
            k=None,
            f2=None,
            percent_released_at_t_q=None,
            converged=False,
            reasons=reasons,
            composition=match.composition,
            a_inf=a_inf,
        )

    pct = percent_released(A, ref.mean_a_inf)
    comparison = compare_profiles(
        t, pct, ref.profile_t, ref.profile_pct_mean,
        t_q_seconds=config.t_q_seconds, q_percent=config.q_percent,
    )

    # Q-test: if the run ended before T_q, project percent released at T_q
    # from the fitted kinetics instead of clamping to the last observation —
    # a genuine tablet in a short run must not fail Q for lack of waiting.
    pct_at_tq = comparison.percent_at_t_q
    projected_q = False
    if float(t[-1]) < config.t_q_seconds and k is not None:
        pct_at_tq = 100.0 * match.scale * (1.0 - float(np.exp(-k * config.t_q_seconds)))
        projected_q = True
    q_pass = pct_at_tq >= config.q_percent

    dissolution_ok = comparison.f2 >= config.f2_cutoff and q_pass
    if comparison.f2 < config.f2_cutoff:
        reasons.append(f"f2 {comparison.f2:.1f} < {config.f2_cutoff}: release profile not equivalent")
    if not q_pass:
        reasons.append(
            f"Q-test failed: {pct_at_tq:.0f}% released at "
            f"{config.t_q_seconds:.0f}s (need >= {config.q_percent:.0f}%)"
            + (" [projected from fitted kinetics]" if projected_q else "")
        )
    if dissolution_ok:
        reasons.append(
            f"dissolution equivalent (f2 {comparison.f2:.1f}, "
            f"{pct_at_tq:.0f}% released at {config.t_q_seconds:.0f}s"
            + (", projected from fitted kinetics)" if projected_q else ")")
        )

    return RunResult(
        verdict=Verdict.MATCH if dissolution_ok else Verdict.SUBSTANDARD,
        matched_reference=match.best_name,
        spectral_distance=match.mahalanobis,
        spectral_cosine=match.cosine,
        confidence=confidence,
        k=k,
        f2=comparison.f2,
        percent_released_at_t_q=pct_at_tq,
        converged=converged,
        reasons=reasons,
        composition=match.composition,
        a_inf=a_inf,
        comparison=comparison,
    )


def partial_payload(run: DissolutionRun, references: list[ReferenceEntry]) -> dict[str, Any]:
    """Live `partial_result` for the dashboard after each reading."""
    t, A = _run_arrays(run)
    est = early_estimate(t, A)

    pct_curve: list[float] | None = None
    projected: str | None = None
    if est.fit is not None and float(np.max(est.a_inf, initial=0.0)) > 1e-3:
        match = match_spectrum(est.a_inf, references)
        projected = match.best_name
        ref = next(r for r in references if r.name == match.best_name)
        pct_curve = [float(v) for v in percent_released(A, ref.mean_a_inf)]

    return {
        "type": "partial_result",
        "n_readings": est.n_readings,
        "a_inf_estimate": [float(v) for v in np.atleast_1d(est.a_inf)],
        "k_estimate": est.k_pooled,
        "converged": est.converged,
        "projected_match": projected,
        "t_seconds": [float(v) for v in t],
        "percent_released": pct_curve,
    }
