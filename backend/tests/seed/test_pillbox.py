from __future__ import annotations

from typing import Any

from backend.seed.sources.pillbox import to_doc

# Trimmed real rows (crzr-uvwg.csv, offset 0) — only the columns to_doc reads.
_TWO_PART_IMPRINT: dict[str, Any] = {
    "spp": "471fa2f1-73a0-49be-89f3-d3e2cfdaeca0-0603-5892-0",
    "setid": "471fa2f1-73a0-49be-89f3-d3e2cfdaeca0",
    "splimprint": "5892;V",
    "splshape_text": "CAPSULE",
    "splcolor_text": "PINK",
    "splsize": "16",
    "splscore": "1",
    "spl_strength": "TEMAZEPAM 15 mg;",
    "spl_ingredients": "TEMAZEPAM[TEMAZEPAM];",
    "rxstring": "",
    "medicine_name": "Temazepam",
    "rxcui": "",
    "product_code": "0603-5892",
    "ndc9": "006035892",
    "author": "Qualitest Pharmaceuticals",
    "dea_schedule_name": "CIV",
    "dea_schedule_code": "C48677",
    "marketing_act_code": "completed",
    "has_image": "False",
    "splimage": "",
    "effective_time": "20160406",
}

_MULTI_COLOR: dict[str, Any] = {
    "spp": "a7baa9ea-6cd5-4a86-8936-8e47ed794db5-63739-375-0",
    "setid": "a7baa9ea-6cd5-4a86-8936-8e47ed794db5",
    "splimprint": "R2666",
    "splshape_text": "CAPSULE",
    "splcolor_text": "YELLOW;BROWN",
    "splsize": "19",
    "splscore": "1",
    "spl_strength": "GABAPENTIN 300 mg;",
    "spl_ingredients": "GABAPENTIN[GABAPENTIN];",
    "rxstring": "gabapentin 300 MG Oral Capsule",
    "medicine_name": "Gabapentin",
    "rxcui": "310431",
    "product_code": "63739-375",
    "ndc9": "637390375",
    "author": "McKesson Packaging Services a business unit of McKesson Corporation",
    "dea_schedule_name": "",
    "dea_schedule_code": "",
    "marketing_act_code": "active",
    "has_image": "True",
    "splimage": "637390375",
    "effective_time": "20140203",
}

_HEXAGON: dict[str, Any] = {
    "spp": "b1c6c994-234a-4832-8c98-620c0328237f-41250-252-0",
    "setid": "b1c6c994-234a-4832-8c98-620c0328237f",
    "splimprint": "RT",
    "splshape_text": "HEXAGON (6 SIDED)",
    "splcolor_text": "PINK",
    "splsize": "8",
    "splscore": "1",
    "spl_strength": "RANITIDINE HYDROCHLORIDE 75 mg;",
    "spl_ingredients": "RANITIDINE HYDROCHLORIDE[RANITIDINE];",
    "rxstring": "",
    "medicine_name": "acid relief",
    "rxcui": "",
    "product_code": "41250-252",
    "ndc9": "412500252",
    "author": "Meijer Distribution Inc",
    "dea_schedule_name": "",
    "dea_schedule_code": "",
    "marketing_act_code": "active",
    "has_image": "False",
    "splimage": "",
    "effective_time": "20190502",
}

# Blank imprint but shape+color present -> kept (rare but real).
_MISSING_IMPRINT: dict[str, Any] = {
    "spp": "bc2c847b-b895-499f-bce9-adcc1c5786b0-54973-2957-0",
    "setid": "bc2c847b-b895-499f-bce9-adcc1c5786b0",
    "splimprint": "",
    "splshape_text": "ROUND",
    "splcolor_text": "WHITE",
    "splsize": "5",
    "splscore": "1",
    "spl_strength": "VIBURNUM OPULUS BARK 2 [hp_X];",
    "spl_ingredients": "VIBURNUM OPULUS BARK[VIBURNUM OPULUS BARK];",
    "rxstring": "",
    "medicine_name": "PMS",
    "rxcui": "",
    "product_code": "54973-2957",
    "ndc9": "549732957",
    "author": "Hyland's",
    "dea_schedule_name": "",
    "dea_schedule_code": "",
    "marketing_act_code": "active",
    "has_image": "False",
    "splimage": "",
    "effective_time": "20140226",
}

# No imprint, no shape, no color -> useless, must be skipped.
_USELESS: dict[str, Any] = {
    "spp": "00000000-0000-0000-0000-000000000000-0000-000-0",
    "setid": "00000000-0000-0000-0000-000000000000",
    "splimprint": "",
    "splshape_text": "",
    "splcolor_text": "",
    "splsize": "",
    "splscore": "",
}


def test_two_part_imprint_splits_on_semicolon() -> None:
    doc = to_doc(_TWO_PART_IMPRINT)
    assert doc is not None
    assert doc["_id"] == doc["pill_id"] == "471fa2f1-73a0-49be-89f3-d3e2cfdaeca0-0603-5892-0"
    assert doc["imprint_raw"] == "5892;V"
    assert doc["imprint_parts"] == ["5892", "V"]
    assert doc["imprint_norm"] == "5892V"
    assert doc["imprint_sorted"] == "5892V"
    assert doc["imprint_text"] == "5892 V"
    assert doc["imprint_len"] == len("5892V")
    assert doc["shape"] == "capsule"
    assert doc["shape_family"] == "elongated"
    assert doc["colors"] == ["pink"]
    assert doc["color_count"] == 1
    assert doc["size_mm"] == 16.0
    assert doc["score"] == 1
    assert doc["dea_schedule"] == "civ"
    assert doc["marketing_status"] == "completed"
    assert doc["has_image"] is False
    assert doc["effective_time"] == "2016-04-06T00:00:00Z"
    assert doc["ingredients"] == ["temazepam"]
    assert doc["generic_name"] == "temazepam"


def test_multi_color_splits_dedupes_and_preserves_order() -> None:
    doc = to_doc(_MULTI_COLOR)
    assert doc is not None
    assert doc["colors"] == ["yellow", "brown"]
    assert doc["color_raw"] == "YELLOW;BROWN"
    assert doc["color_count"] == 2
    assert doc["has_image"] is True
    assert doc["image_key"] == "637390375"
    assert doc["generic_name"] == "gabapentin"  # rxstring preferred over medicine_name


def test_hexagon_shape_text_normalizes_parenthetical() -> None:
    doc = to_doc(_HEXAGON)
    assert doc is not None
    assert doc["shape"] == "hexagon"
    assert doc["shape_family"] == "polygon"


def test_missing_imprint_kept_when_shape_and_color_present() -> None:
    doc = to_doc(_MISSING_IMPRINT)
    assert doc is not None
    assert "imprint_raw" not in doc
    assert "imprint_norm" not in doc
    assert doc["shape"] == "round"
    assert doc["colors"] == ["white"]


def test_useless_row_with_no_imprint_shape_or_color_is_skipped() -> None:
    assert to_doc(_USELESS) is None


def test_size_mm_parsed_as_float_and_missing_size_is_none() -> None:
    assert to_doc(_TWO_PART_IMPRINT)["size_mm"] == 16.0
    row = dict(_TWO_PART_IMPRINT, splsize="")
    assert to_doc(row)["size_mm"] is None


def test_id_falls_back_to_sha1_when_spp_is_absent() -> None:
    row = dict(_TWO_PART_IMPRINT, spp="")
    doc = to_doc(row, row_index=3)
    assert doc is not None
    assert doc["_id"].startswith("pillbox-")
    assert len(doc["_id"]) == len("pillbox-") + 40  # sha1 hex digest

    # Same inputs -> same id (idempotent reruns); a different row index changes it.
    assert to_doc(row, row_index=3)["_id"] == doc["_id"]
    assert to_doc(row, row_index=4)["_id"] != doc["_id"]


def test_unmapped_fields_never_leak_into_the_document() -> None:
    from backend.knowledge.indices import mapped_fields
    from backend.knowledge.fields import PILLS_INDEX

    allowed = mapped_fields(PILLS_INDEX) | {"_id"}
    for row in (_TWO_PART_IMPRINT, _MULTI_COLOR, _HEXAGON, _MISSING_IMPRINT):
        doc = to_doc(row)
        assert doc is not None
        assert set(doc) <= allowed
