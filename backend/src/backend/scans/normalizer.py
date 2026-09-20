"""Turn vision and hardware results into the sub-objects `peel-scans` maps.

The scans mapping is strict, so every key produced here must already exist in
`knowledge.indices._scans()`. Two rules drive the rest of this module: personal
label data never reaches the index (audit_redteam §5.3), and everything under
`norm` stays single-valued so ES|QL `==` is safe on it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.knowledge import normalize, vocab
from backend.photo_identification.bottle import BottlePhotoResult
from backend.photo_identification.imprint import ImprintPhotoResult
from backend.pill import HARDWARE_MODEL, PillHardwareResult

TEXT_CAP = 500
MOCK_LIMITATION = "Simulated result; no physical measurement was performed."


def sanitize_bottle(bottle: BottlePhotoResult, *, store_sensitive: bool) -> dict[str, Any]:
    """Drop the label fields that re-identify a patient, keep a boolean that they existed.

    An Rx number plus a pharmacy name plus a timestamp is a re-identifiable record,
    and no research tool reads any of the three.
    """
    doc: dict[str, Any] = {
        "is_medication_container": bottle.is_medication_container,
        "brand_name": bottle.brand_name,
        "generic_name": bottle.generic_name,
        "strength": bottle.strength,
        "form": bottle.form,
        "quantity": bottle.quantity,
        "ndc": bottle.ndc,
        "manufacturer": bottle.manufacturer,
        "expiration": bottle.expiration,
        "lot_number": bottle.lot_number,
        "imprint_on_label": bottle.imprint_on_label,
        "visible_warnings": list(bottle.visible_warnings),
        "confidence": bottle.confidence,
        "rx_number_present": _present(bottle.rx_number),
        "pharmacy_present": _present(bottle.pharmacy),
        "directions_present": _present(bottle.directions),
    }
    if store_sensitive:
        doc["rx_number"] = bottle.rx_number
        doc["pharmacy"] = bottle.pharmacy
        doc["directions"] = bottle.directions
        # Free text a patient's name, address or pharmacy visit tends to end up
        # in: never index it unless the deployment opted into sensitive storage.
        doc["other_label_text"] = _capped(bottle.other_label_text)
        doc["notes"] = _capped(bottle.notes)
    return doc


def imprint_doc(
    imprint: ImprintPhotoResult, *, size_mm: float | None, store_sensitive: bool
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "is_pill": imprint.is_pill,
        "imprint": imprint.imprint,
        "color": imprint.color,
        "shape": imprint.shape,
        "form": imprint.form,
        "score": imprint.score,
        "size_mm": vocab.parse_size_mm(size_mm),
        "additional_markings": imprint.additional_markings,
        "confidence": imprint.confidence,
    }
    if store_sensitive:
        # notes is free text, same rationale as bottle.other_label_text/notes.
        doc["notes"] = _capped(imprint.notes)
    return doc


def build_norm(
    bottle: BottlePhotoResult | None,
    imprint: ImprintPhotoResult | None,
    *,
    imprint_size_mm: float | None,
    now: datetime,
) -> dict[str, Any]:
    """The single-valued join keys every retrieval path filters on."""
    ndc = normalize.normalize_ndc(bottle.ndc if bottle else None)
    # The imprint photo observes the pill; the label only claims what it should say.
    imprint_source = (imprint.imprint if imprint else None) or (
        bottle.imprint_on_label if bottle else None
    )
    forms = normalize.normalize_imprint(imprint_source)
    colors = vocab.normalize_colors(imprint.color if imprint else None)
    shape = vocab.normalize_shape(imprint.shape if imprint else None)
    generic = normalize.normalize_drug_name(bottle.generic_name if bottle else None)
    brand = normalize.normalize_drug_name(bottle.brand_name if bottle else None)
    dosage_form = normalize.normalize_dosage_form(
        (bottle.form if bottle else None) or (imprint.form if imprint else None)
    )
    expiration = normalize.parse_expiration(bottle.expiration if bottle else None)
    return {
        "lot": normalize.normalize_lot(bottle.lot_number if bottle else None),
        "ndc9": ndc.ndc9 if ndc else None,
        "ndc11": ndc.ndc11 if ndc else None,
        "ndc_raw": ndc.raw if ndc else None,
        "imprint_norm": forms.norm if forms else None,
        "imprint_sorted": forms.sorted if forms else None,
        "shape": shape,
        "shape_family": vocab.shape_family(shape),
        "primary_color": colors[0] if colors else None,
        "colors": colors,
        "score": vocab.normalize_score(imprint.score if imprint else None),
        "size_mm": vocab.parse_size_mm(imprint_size_mm),
        "drug_names": _dedupe([generic, brand]),
        "generic_name": generic,
        "brand_name": brand,
        "strength": normalize.clean_text(bottle.strength if bottle else None),
        "dosage_form": dosage_form,
        "manufacturer": normalize.clean_text(bottle.manufacturer if bottle else None),
        "expiration": normalize.to_iso(expiration),
        "expired": None if expiration is None else expiration < now,
    }


def hardware_doc(hardware: PillHardwareResult, model: str | None) -> dict[str, Any]:
    name = model or HARDWARE_MODEL
    doc: dict[str, Any] = {
        "status": hardware.status,
        "pill_type": hardware.pill_type,
        "degraded": hardware.degraded,
        "confidence": hardware.confidence,
        "model": name,
        "spectrum": [float(value) for value in hardware.spectrum],
    }
    if name == HARDWARE_MODEL:
        # The voice agent must never narrate a mock spectrum as a measurement.
        doc["limitations"] = MOCK_LIMITATION
    return doc


def _capped(value: str | None) -> str | None:
    text = normalize.clean_text(value)
    return normalize.truncate_on_sentence(text, TEXT_CAP) if text else None


def _present(value: str | None) -> bool:
    return normalize.clean_text(value) is not None


def _dedupe(values: list[str | None]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen
