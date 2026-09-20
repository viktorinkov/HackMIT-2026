"""Map a ClassificationResult onto the backend's hardware-result contract.

The contract is backend/src/backend/pill.py: PillHardwareResult (status,
spectrum, pill_type, degraded, confidence) inside PillHardwareAnalysis. This
module returns plain dicts of exactly that shape and imports nothing from the
backend, so the package stays standalone and the backend keeps its own
dependency list; on the backend side it is one line:

    PillHardwareResult(**to_pill_hardware_result(result))

Today the backend fills that model from mock_hardware_result(). Nothing here
replaces it - wiring it in is the backend's call, and needs numpy and scipy
added there first.
"""

from __future__ import annotations

import math

from .classification import DEFAULT_CONFIG, ClassificationResult, ClassifierConfig

# What the backend reports in PillHardwareAnalysis.model (it says
# "mock-spectrometry" for the mock).
HARDWARE_MODEL = "truepill-snapshot"

# Seven verdicts onto the backend's four statuses. A reading the rig could not
# take (NO_SIGNAL, INVALID_READING) is "unknown", never "fake": the backend
# must not tell someone their medicine is counterfeit because a lead was loose.
_STATUS = {
    "PASS": "real",
    "DILUTED": "substandard",
    "OVER_CONCENTRATED": "substandard",
    "ADULTERATED": "fake",
    "UNKNOWN": "unknown",
    "NO_SIGNAL": "unknown",
    "INVALID_READING": "unknown",
}


def _confidence(result: ClassificationResult, config: ClassifierConfig) -> float:
    """How far the best match cleared the match threshold, on 0-1.

    0 at the threshold, 1 at a perfect shape match; 0 for any verdict that
    named no substance. A ranking score, NOT a probability: the rig's
    thresholds rest on ~45 independent noise pairs (HARDWARE_TUNING.md), which
    cannot support a calibrated one.
    """
    if result.match_name is None:
        return 0.0
    span = 1.0 - config.match_threshold
    if span <= 0.0:
        return 1.0
    return min(max((result.similarity - config.match_threshold) / span, 0.0), 1.0)


def to_pill_hardware_result(
    result: ClassificationResult,
    config: ClassifierConfig | None = None,
) -> dict:
    """The five PillHardwareResult fields, JSON-safe.

    `config` is the one the result was classified with (default: the
    simulator's); pass the rig's so confidence is scaled to its threshold.
    `pill_type` is what the spectrum MATCHED, which for a mislabelled pill is
    not what the bottle says.
    """
    config = config or DEFAULT_CONFIG
    status = _STATUS[result.verdict]
    spectrum = [] if result.absorbance is None else [
        float(v) if math.isfinite(v) else 0.0 for v in result.absorbance
    ]
    return {
        "status": status,
        "spectrum": spectrum,
        "pill_type": result.match_name,
        # Same rule as the backend's mock: degraded means substandard.
        "degraded": status == "substandard",
        "confidence": _confidence(result, config),
    }


def to_pill_hardware_analysis(
    result: ClassificationResult,
    config: ClassifierConfig | None = None,
) -> dict:
    """The full PillHardwareAnalysis envelope around to_pill_hardware_result()."""
    return {
        "identification_method": "hardware",
        "target": "pill",
        "model": HARDWARE_MODEL,
        "result": to_pill_hardware_result(result, config),
    }
