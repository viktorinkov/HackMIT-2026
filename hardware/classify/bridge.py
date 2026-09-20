"""Hand a verdict to the backend as the scan's `hardware` observation.

The backend's PillHardwareResult speaks real / substandard / fake / unknown
(backend/mock-hardware-analysis.md). The mapping is fixed here so the two
vocabularies cannot drift apart silently.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .classify import Result
from .stream import COLOURS

HARDWARE_MODEL = "peel-photometer/1"


def hardware_result(result: Result, r2: float | None = None) -> dict[str, Any]:
    if result.status == "pass_screen":
        status = "real"
    elif result.status == "refer_to_lab":
        status = "substandard" if result.analyte_seen else "fake"
    else:
        status = "unknown"
    return {
        "status": status,
        "pill_type": result.product if result.analyte_seen else None,
        "degraded": result.slow_release,
        "confidence": _confidence(result, r2),
        "spectrum": [result.sweep.get(c) or 0.0 for c in COLOURS],
    }


def scan_payload(
    result: Result,
    device_id: str,
    *,
    r2: float | None = None,
    bottle: dict[str, Any] | None = None,
    imprint: dict[str, Any] | None = None,
    demo: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "device_id": device_id,
        "hardware": hardware_result(result, r2),
        "hardware_model": HARDWARE_MODEL,
        "demo": demo,
    }
    if bottle:
        payload["bottle"] = bottle
    if imprint:
        payload["imprint"] = imprint
    return payload


def post_scan(base_url: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        base_url.rstrip("/") + "/scans",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"backend answered {exc.code}: {exc.read().decode(errors='replace')}") from exc


def _confidence(result: Result, r2: float | None) -> float:
    if result.status == "cannot_verify":
        return 0.2
    if not result.analyte_seen:
        return 0.8
    score = 0.9 if (r2 or 0.0) >= 0.99 else 0.7
    if not result.settled:
        score -= 0.2
    return round(score, 2)
