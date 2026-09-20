from __future__ import annotations

from typing import Any


def complete_scan(**kwargs: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "scan_id": "scan-1",
        "device_id": "dev-1",
        "revision": 1,
        "status": "complete",
        "demo": True,
        "created_at": "2026-09-19T00:00:00Z",
        "updated_at": "2026-09-19T00:01:00Z",
        "bottle": {
            "is_medication_container": True,
            "generic_name": "acetaminophen",
            "brand_name": "Tylenol",
            "strength": "500 mg",
            "form": "tablet",
            "confidence": 0.9,
        },
        "imprint": {"is_pill": True, "imprint": "L484"},
        "hardware": {
            "status": "real",
            "pill_type": "ibuprofen",
            "degraded": False,
            "confidence": 0.92,
            "model": "mock-spectrometry",
        },
        "norm": {"dosage_form": "tablet", "generic_name": "acetaminophen"},
        "evidence": {
            "pill_candidates": [
                {"generic_name": "ibuprofen", "strength": "200 mg", "form": "tablet"}
            ]
        },
        "research": {
            "verdict": "mismatch_found",
            "risk_level": "medium",
            "headline": "The label and the reference records do not agree.",
            "findings": [],
            "mismatches": [],
            "gaps": [],
            "next_steps": [],
            "sources": [],
        },
    }
    doc.update(kwargs)
    return doc
