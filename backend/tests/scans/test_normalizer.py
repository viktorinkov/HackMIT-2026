from __future__ import annotations

from datetime import UTC, datetime

from backend.knowledge.fields import SCANS_INDEX
from backend.knowledge.indices import mappings_for
from backend.photo_identification.bottle import BottlePhotoResult
from backend.photo_identification.imprint import ImprintPhotoResult
from backend.pill import HARDWARE_MODEL, PillHardwareResult
from backend.scans.normalizer import (
    MOCK_LIMITATION,
    TEXT_CAP,
    build_norm,
    hardware_doc,
    imprint_doc,
    sanitize_bottle,
)

NOW = datetime(2026, 9, 19, tzinfo=UTC)
SENSITIVE = {"rx_number", "pharmacy", "directions"}


def mapped(block: str) -> set[str]:
    return set(mappings_for(SCANS_INDEX)["properties"][block]["properties"])


def full_bottle(**kwargs: object) -> BottlePhotoResult:
    fields: dict[str, object] = {
        "is_medication_container": True,
        "brand_name": "Advil",
        "generic_name": "Ibuprofen 200 mg tablets",
        "strength": "200 mg",
        "form": "Tablet",
        "ndc": "16729-457-01",
        "manufacturer": "Accord",
        "expiration": "EXP 03/2024",
        "lot_number": "lot# ab-12 34",
        "pharmacy": "Downtown Pharmacy",
        "rx_number": "RX 8823410",
        "directions": "Take one tablet twice daily",
        "other_label_text": "Jane Doe " * 200,
        "confidence": 0.8,
    }
    fields.update(kwargs)
    return BottlePhotoResult(**fields)


def pill_imprint(**kwargs: object) -> ImprintPhotoResult:
    fields: dict[str, object] = {
        "is_pill": True,
        "imprint": "5892;V",
        "color": "light blue",
        "shape": "Oval",
        "form": "tablet",
        "score": "one score line",
        "confidence": 0.7,
    }
    fields.update(kwargs)
    return ImprintPhotoResult(**fields)


def test_sanitize_bottle_drops_personal_label_fields_by_default() -> None:
    doc = sanitize_bottle(full_bottle(), store_sensitive=False)
    assert SENSITIVE.isdisjoint(doc)
    assert doc["rx_number_present"] is True
    assert doc["pharmacy_present"] is True
    assert doc["directions_present"] is True


def test_sanitize_bottle_marks_absent_sensitive_fields_false() -> None:
    doc = sanitize_bottle(
        full_bottle(rx_number=None, pharmacy="  ", directions="n/a"),
        store_sensitive=False,
    )
    assert doc["rx_number_present"] is False
    assert doc["pharmacy_present"] is False
    assert doc["directions_present"] is False


def test_sanitize_bottle_keeps_sensitive_fields_when_opted_in() -> None:
    doc = sanitize_bottle(full_bottle(), store_sensitive=True)
    assert doc["rx_number"] == "RX 8823410"
    assert doc["pharmacy"] == "Downtown Pharmacy"
    assert doc["directions"] == "Take one tablet twice daily"


def test_sanitize_bottle_truncates_free_text() -> None:
    doc = sanitize_bottle(full_bottle(notes="n " * 400), store_sensitive=False)
    assert len(doc["other_label_text"]) <= TEXT_CAP
    assert len(doc["notes"]) <= TEXT_CAP


def test_sanitize_bottle_only_emits_mapped_keys() -> None:
    allowed = mapped("bottle")
    assert set(sanitize_bottle(full_bottle(), store_sensitive=False)) <= allowed
    assert set(sanitize_bottle(full_bottle(), store_sensitive=True)) <= allowed


def test_imprint_doc_only_emits_mapped_keys() -> None:
    doc = imprint_doc(pill_imprint(), size_mm=9.5)
    assert set(doc) <= mapped("imprint")
    assert doc["size_mm"] == 9.5


def test_imprint_doc_rejects_an_implausible_size() -> None:
    assert imprint_doc(pill_imprint(), size_mm=900.0)["size_mm"] is None


def test_build_norm_only_emits_mapped_keys() -> None:
    norm = build_norm(full_bottle(), pill_imprint(), imprint_size_mm=9.0, now=NOW)
    assert set(norm) <= mapped("norm")


def test_build_norm_normalizes_the_join_keys() -> None:
    norm = build_norm(full_bottle(), pill_imprint(), imprint_size_mm=9.0, now=NOW)
    assert norm["lot"] == "AB1234"
    assert norm["ndc9"] == "167290457"
    assert norm["ndc11"] == "16729045701"
    assert norm["ndc_raw"] == "16729-457-01"
    assert norm["imprint_norm"] == "5892V"
    assert norm["imprint_sorted"] == "5892V"
    assert norm["shape"] == "oval"
    assert norm["shape_family"] == "elongated"
    assert norm["primary_color"] == "blue"
    assert norm["colors"] == ["blue"]
    assert norm["score"] == 2
    assert norm["generic_name"] == "ibuprofen"
    assert norm["brand_name"] == "advil"
    assert norm["drug_names"] == ["ibuprofen", "advil"]
    assert norm["dosage_form"] == "tablet"


def test_build_norm_flags_an_expired_label() -> None:
    norm = build_norm(full_bottle(), None, imprint_size_mm=None, now=NOW)
    assert norm["expiration"] == "2024-03-31T00:00:00Z"
    assert norm["expired"] is True


def test_build_norm_leaves_expiry_unknown_when_unparseable() -> None:
    norm = build_norm(full_bottle(expiration=None), None, imprint_size_mm=None, now=NOW)
    assert norm["expiration"] is None
    assert norm["expired"] is None


def test_build_norm_falls_back_to_the_label_imprint() -> None:
    norm = build_norm(
        full_bottle(imprint_on_label="ADVIL 200"), None, imprint_size_mm=None, now=NOW
    )
    assert norm["imprint_norm"] == "ADVIL200"


def test_build_norm_survives_an_imprint_only_scan() -> None:
    norm = build_norm(None, pill_imprint(), imprint_size_mm=None, now=NOW)
    assert norm["imprint_norm"] == "5892V"
    assert norm["lot"] is None and norm["generic_name"] is None
    assert norm["drug_names"] == []


def test_hardware_doc_labels_the_mock_as_simulated() -> None:
    result = PillHardwareResult(
        status="substandard", spectrum=[0.1, 0.2], pill_type="ibuprofen",
        degraded=True, confidence=0.78,
    )
    doc = hardware_doc(result, None)
    assert doc["model"] == HARDWARE_MODEL
    assert doc["limitations"] == MOCK_LIMITATION
    assert set(doc) <= mapped("hardware")
    assert doc["spectrum"] == [0.1, 0.2]


def test_hardware_doc_omits_the_mock_caveat_for_real_devices() -> None:
    result = PillHardwareResult(
        status="real", spectrum=[], pill_type=None, degraded=False, confidence=0.9
    )
    doc = hardware_doc(result, "peel-nir-v1")
    assert doc["model"] == "peel-nir-v1"
    assert "limitations" not in doc
