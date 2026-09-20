"""Deterministic nearest-curve matching against explicitly synthetic references.

These generated time-response curves are software fixtures, not measured spectra.
Labels demonstrate routing only; distances are not probabilities of drug identity.
"""
from __future__ import annotations

import math
from typing import Any

VERSION = 'synthetic-optical-v1'
POINTS = 32
MIN_SAMPLES = 8
MAX_DISTANCE = 0.12  # Demo heuristic in absorbance units, not a validated cutoff.


def reference_profiles() -> dict[str, list[float]]:
    x = [i / (POINTS - 1) for i in range(POINTS)]
    return {
        'Vitamin B12': [0.24 * t for t in x],
        'Acetaminophen': [0.055 * (1 - math.exp(-5 * t)) for t in x],
        'Vitamin C': [-0.20 * t for t in x],
        'Caffeine': [0.48 * t * t for t in x],
    }


def _finite(v: Any) -> bool:
    return isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v)


def match_readings(hardware: dict[str, Any] | None) -> dict[str, Any]:
    base = {'library': VERSION, 'reference_source': 'synthetic',
            'method': 'baseline-subtracted, progress-resampled absorbance RMSE',
            'distance_unit': 'absorbance', 'validated_identity': False}
    if not hardware or hardware.get('model') == 'mock-spectrometry':
        return {**base, 'status': 'no_data'}
    rows = hardware.get('sensor_readings') or []
    # Prefer aligned raw readings. Sweep measurements are a different illumination.
    values = [r.get('absT') for r in rows if isinstance(r, dict) and not r.get('swept')]
    if not any(_finite(v) for v in values):
        values = list(hardware.get('spectrum') or [])
    good = [(i, float(v)) for i, v in enumerate(values) if _finite(v)]
    if len(good) < MIN_SAMPLES or len(good) < 0.8 * len(values):
        return {**base, 'status': 'insufficient_data', 'sample_count': len(good)}
    if max(v for _, v in good) - min(v for _, v in good) < 0.005:
        return {**base, 'status': 'no_signal', 'sample_count': len(good)}
    # Interpolate along run progress, preserving missing sample positions and amplitude.
    first, last = good[0][0], good[-1][0]
    curve = []
    j = 0
    for n in range(POINTS):
        t = first + (last - first) * n / (POINTS - 1)
        while j < len(good) - 2 and good[j + 1][0] < t:
            j += 1
        a, b = good[j], good[j + 1]
        curve.append(a[1] + (b[1] - a[1]) * (t - a[0]) / (b[0] - a[0]) - good[0][1])
    scores = sorted((math.sqrt(sum((a - b) ** 2 for a, b in zip(curve, ref)) / POINTS), name)
                    for name, ref in reference_profiles().items())
    best, runner = scores[:2]
    margin = (runner[0] - best[0]) / max(runner[0], 1e-9)
    status = 'outside_library' if best[0] > MAX_DISTANCE else ('ambiguous' if margin < .15 else 'matched')
    return {**base, 'status': status, 'sample_count': len(good), 'closest_match': best[1],
            'distance': round(best[0], 6), 'relative_margin': round(margin, 6),
            'ranking': [{'name': name, 'distance': round(distance, 6)} for distance, name in scores]}


def match_sentence(match: dict[str, Any]) -> str:
    if not match.get('closest_match'):
        return ''
    qualifier = {'ambiguous': ' The nearest profiles are too close to separate.',
                 'outside_library': ' The readings are outside the reference range.'}.get(match['status'], '')
    return (f"Closest match: {match['closest_match']}. Synthetic reference library; "
            f"distance {match['distance']:.3f} absorbance.{qualifier}")
