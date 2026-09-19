from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from backend.knowledge.fields import SCAN_STATUSES
from backend.photo_identification.bottle import BottlePhotoResult
from backend.scans.models import (
    PhotoRef,
    ScanCreate,
    ScanEnvelope,
    ScanStatus,
    ScanSummary,
)

SHA = "a" * 64


def _bottle(**kwargs: object) -> BottlePhotoResult:
    return BottlePhotoResult(is_medication_container=True, confidence=0.9, **kwargs)


def test_scan_status_matches_the_mapping_vocabulary() -> None:
    assert get_args(ScanStatus) == SCAN_STATUSES


def test_scan_create_requires_at_least_one_observation() -> None:
    with pytest.raises(ValidationError, match="at least one of bottle"):
        ScanCreate(device_id="dev-1")


def test_scan_create_accepts_a_bottle_alone() -> None:
    payload = ScanCreate(device_id="dev-1", bottle=_bottle(generic_name="ibuprofen"))
    assert payload.demo is False
    assert payload.photos == []


@pytest.mark.parametrize("device_id", ["", "x" * 129])
def test_scan_create_bounds_the_device_id(device_id: str) -> None:
    with pytest.raises(ValidationError):
        ScanCreate(device_id=device_id, bottle=_bottle())


def test_photo_ref_rejects_a_bad_digest() -> None:
    with pytest.raises(ValidationError):
        PhotoRef(target="bottle", sha256="nope", bytes=10, media_type="image/png")


def test_photo_ref_rejects_an_unknown_target() -> None:
    with pytest.raises(ValidationError):
        PhotoRef(target="blister", sha256=SHA, bytes=10, media_type="image/png")


def test_envelope_from_doc_defaults_missing_blocks() -> None:
    envelope = ScanEnvelope.from_doc(
        {
            "scan_id": "scan-1",
            "device_id": "dev-1",
            "status": "pending",
            "created_at": "2026-09-19T00:00:00Z",
        }
    )
    assert envelope.revision == 1
    assert envelope.norm == {} and envelope.evidence == {} and envelope.stages == {}
    assert envelope.bottle is None and envelope.research is None
    assert envelope.updated_at == envelope.created_at


def test_summary_from_doc_flattens_norm_and_research() -> None:
    summary = ScanSummary.from_doc(
        {
            "scan_id": "scan-1",
            "device_id": "dev-1",
            "revision": 3,
            "status": "complete",
            "demo": False,
            "created_at": "2026-09-19T00:00:00Z",
            "updated_at": "2026-09-19T00:01:00Z",
            "norm": {"lot": "ABC123", "ndc9": "167290457", "generic_name": "ibuprofen"},
            "research": {"verdict": "recall_match", "risk_level": "high", "headline": "hit"},
        }
    )
    assert (summary.lot, summary.ndc9, summary.generic_name) == (
        "ABC123",
        "167290457",
        "ibuprofen",
    )
    assert (summary.verdict, summary.risk_level, summary.headline) == (
        "recall_match",
        "high",
        "hit",
    )
