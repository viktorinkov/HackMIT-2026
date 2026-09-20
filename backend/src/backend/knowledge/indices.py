"""Index mappings for the Peel knowledge base.

The cluster is an Elastic Cloud Serverless VectorDB project: no shard settings,
no ML nodes (vector search only through semantic_text), and float arrays of 32+
elements auto-map to dense_vector unless mappings are strict. Normalisation is
done in Python (knowledge.normalize), so no custom analyzers are declared here.
"""

from __future__ import annotations

from typing import Any

from elasticsearch import AsyncElasticsearch

from backend.knowledge.fields import (
    ALL_INDICES,
    DATE_FORMAT,
    INFERENCE_ID,
    NDC_INDEX,
    PILLS_INDEX,
    REGULATORY_INDEX,
    REPORTS_INDEX,
    SCANS_INDEX,
    WEB_PAGES_INDEX,
    Ndc,
    Pill,
    Reg,
    Report,
    Scan,
    Web,
)

KW: dict[str, Any] = {"type": "keyword", "ignore_above": 1024}
TEXT: dict[str, Any] = {"type": "text"}
BOOL: dict[str, Any] = {"type": "boolean"}
DATE: dict[str, Any] = {"type": "date", "format": DATE_FORMAT}
RAW: dict[str, Any] = {"type": "object", "enabled": False}
# Kept in _source only: never searched, never aggregated.
STORED_KW: dict[str, Any] = {"type": "keyword", "index": False, "doc_values": False}
STORED_TEXT: dict[str, Any] = {"type": "text", "index": False}
GEO: dict[str, Any] = {"type": "geo_point"}
KW_TXT: dict[str, Any] = {**KW, "fields": {"txt": {"type": "text"}}}
TEXT_KW: dict[str, Any] = {
    "type": "text",
    "fields": {"kw": {"type": "keyword", "ignore_above": 512}},
}


def _semantic(chunk_words: int) -> dict[str, Any]:
    return {
        "type": "semantic_text",
        "inference_id": INFERENCE_ID,
        "chunking_settings": {
            "strategy": "recursive",
            "max_chunk_size": chunk_words,
            "separator_group": "markdown",
        },
    }


def _regulatory() -> dict[str, Any]:
    return {
        Reg.RECORD_ID: KW,
        Reg.SOURCE: KW,
        Reg.SOURCE_ORG: KW,
        Reg.DOC_TYPE: KW,
        Reg.COUNTRY_OF_AUTHORITY: KW,
        Reg.COUNTRIES: KW,
        Reg.TITLE: TEXT_KW,
        Reg.SUMMARY: TEXT,
        Reg.BODY: TEXT,
        Reg.BODY_SEMANTIC: _semantic(300),
        Reg.REASON: TEXT,
        Reg.PRODUCT_DESCRIPTION: TEXT,
        Reg.DRUG_NAMES: KW_TXT,
        Reg.DRUG_NAMES_EXTRACTED: KW_TXT,
        Reg.MANUFACTURER: KW_TXT,
        Reg.RECALLING_FIRM: KW_TXT,
        Reg.RXCUI: KW,
        Reg.NDC9: KW,
        Reg.NDC11: KW,
        Reg.NDC_RAW: KW,
        Reg.NDC_FROM_DESCRIPTION: KW,
        Reg.LOT_NUMBERS: KW,
        Reg.LOT_TEXT: TEXT,
        Reg.COVERS_ALL_LOTS: BOOL,
        Reg.EVENT_ID: KW,
        Reg.ALERT_NUMBER: KW,
        Reg.DOSAGE_FORM: KW,
        Reg.SEVERITY: KW,
        Reg.SEVERITY_RANK: {"type": "byte"},
        Reg.CLASSIFICATION_RAW: KW,
        Reg.STATUS: KW,
        Reg.PUBLISHED_AT: DATE,
        Reg.EVENT_DATE: DATE,
        Reg.RECENCY_DATE: DATE,
        Reg.DATE_PRECISION: KW,
        Reg.INDEXED_AT: DATE,
        Reg.URL: KW,
        Reg.ATTACHMENT_URLS: KW,
        Reg.HAS_SEMANTIC: BOOL,
        Reg.ATTRIBUTION: KW,
        Reg.SOURCE_LICENSE: KW,
        Reg.SOURCE_TERMS_URL: KW,
        Reg.SOURCE_DISCLAIMER: STORED_TEXT,
        Reg.SOURCE_EXPORT_DATE: DATE,
        Reg.RAW: RAW,
    }


def _pills() -> dict[str, Any]:
    return {
        Pill.PILL_ID: KW,
        Pill.SETID: KW,
        Pill.SOURCE: KW,
        Pill.IMPRINT_RAW: KW,
        Pill.IMPRINT_NORM: KW,
        Pill.IMPRINT_SORTED: KW,
        Pill.IMPRINT_PARTS: KW,
        Pill.IMPRINT_TEXT: TEXT,
        Pill.IMPRINT_LEN: {"type": "short"},
        Pill.SHAPE: KW,
        Pill.SHAPE_FAMILY: KW,
        Pill.COLORS: KW,
        Pill.COLOR_RAW: KW,
        Pill.COLOR_COUNT: {"type": "byte"},
        Pill.SCORE: {"type": "byte"},
        Pill.SIZE_MM: {"type": "float"},
        Pill.MEDICINE_NAME: KW_TXT,
        Pill.GENERIC_NAME: KW_TXT,
        Pill.STRENGTH: TEXT,
        Pill.INGREDIENTS: KW_TXT,
        Pill.LABELER: KW_TXT,
        Pill.RXCUI: KW,
        Pill.PRODUCT_NDC: KW,
        Pill.NDC9: KW,
        Pill.DEA_SCHEDULE: KW,
        Pill.MARKETING_STATUS: KW,
        Pill.HAS_IMAGE: BOOL,
        Pill.IMAGE_KEY: KW,
        Pill.EFFECTIVE_TIME: DATE,
        Pill.RAW: RAW,
    }


def _ndc() -> dict[str, Any]:
    return {
        Ndc.PRODUCT_NDC: KW,
        Ndc.NDC9: KW,
        Ndc.PACKAGE_NDCS: KW,
        Ndc.NDC11: KW,
        Ndc.BRAND_NAME: KW_TXT,
        Ndc.GENERIC_NAME: KW_TXT,
        Ndc.LABELER_NAME: KW_TXT,
        Ndc.ACTIVE_INGREDIENT_NAMES: KW_TXT,
        Ndc.STRENGTHS: KW,
        Ndc.DOSAGE_FORM: KW,
        Ndc.ROUTE: KW,
        Ndc.PRODUCT_TYPE: KW,
        Ndc.MARKETING_CATEGORY: KW,
        Ndc.MARKETING_START_DATE: DATE,
        Ndc.MARKETING_END_DATE: DATE,
        Ndc.LISTING_EXPIRATION_DATE: DATE,
        Ndc.IS_LISTING_EXPIRED: BOOL,
        Ndc.RXCUI: KW,
        Ndc.UNII: KW,
        Ndc.SPL_SET_ID: KW,
        Ndc.PHARM_CLASS: KW,
        Ndc.DEA_SCHEDULE: KW,
        Ndc.FINISHED: BOOL,
        Ndc.RAW: RAW,
    }


def _web_pages() -> dict[str, Any]:
    return {
        Web.PAGE_ID: KW,
        Web.URL: KW,
        Web.DOMAIN: KW,
        Web.SOURCE_TIER: KW,
        Web.SOURCE_ORG: KW,
        Web.TITLE: TEXT_KW,
        Web.DESCRIPTION: TEXT,
        Web.CONTENT: TEXT,
        Web.PAGE_SEMANTIC: _semantic(300),
        Web.DRUG_NAMES: KW_TXT,
        Web.LOT_NUMBERS: KW,
        Web.NDC9: KW,
        Web.NDC11: KW,
        Web.MANUFACTURER: KW,
        Web.COUNTRIES: KW,
        Web.FLAGS: KW,
        Web.IS_RECALL: BOOL,
        Web.IS_ALERT: BOOL,
        Web.LANGUAGE: KW,
        Web.STATUS_CODE: {"type": "short"},
        Web.PUBLISHED_AT: DATE,
        Web.FETCHED_AT: DATE,
        Web.FIRST_SEEN_AT: DATE,
        Web.LAST_CHANGED_AT: DATE,
        Web.RECENCY_DATE: DATE,
        Web.DATE_PRECISION: KW,
        Web.CONTENT_HASH: KW,
        Web.REVISION: {"type": "integer"},
        Web.STALE: BOOL,
        Web.QUERY_KEY: KW,
        Web.QUERIES: KW,
        Web.SCAN_IDS: KW,
        Web.FIRECRAWL_CREDITS: {"type": "short"},
        Web.VIA: KW,
        Web.RAW: RAW,
    }


def _scans() -> dict[str, Any]:
    bottle = {
        "is_medication_container": BOOL,
        "brand_name": KW_TXT,
        "generic_name": KW_TXT,
        "strength": KW,
        "form": KW,
        "quantity": KW,
        "ndc": KW,
        "manufacturer": KW_TXT,
        "expiration": KW,
        "lot_number": KW,
        "imprint_on_label": KW,
        "visible_warnings": TEXT,
        "other_label_text": STORED_TEXT,
        "confidence": {"type": "float"},
        "notes": STORED_TEXT,
        # Sensitive label fields are dropped unless scans_store_sensitive is on.
        "rx_number_present": BOOL,
        "pharmacy_present": BOOL,
        "directions_present": BOOL,
        "rx_number": STORED_KW,
        "pharmacy": STORED_KW,
        "directions": STORED_TEXT,
    }
    imprint = {
        "is_pill": BOOL,
        "imprint": KW,
        "color": KW,
        "shape": KW,
        "form": KW,
        "score": KW,
        "size_mm": {"type": "float"},
        "additional_markings": TEXT,
        "confidence": {"type": "float"},
        "notes": STORED_TEXT,
    }
    # Single-valued on purpose: ES|QL `==` silently fails on multi-valued fields.
    norm = {
        "lot": KW,
        "ndc9": KW,
        "ndc11": KW,
        "ndc_raw": KW,
        "imprint_norm": KW,
        "imprint_sorted": KW,
        "shape": KW,
        "shape_family": KW,
        "primary_color": KW,
        "colors": KW,
        "score": {"type": "byte"},
        "size_mm": {"type": "float"},
        "drug_names": KW,
        "generic_name": KW,
        "brand_name": KW,
        "rxcui": KW,
        "strength": KW,
        "dosage_form": KW,
        "manufacturer": KW,
        "expiration": DATE,
        "expired": BOOL,
    }
    hardware = {
        "status": KW,
        "pill_type": KW,
        "degraded": BOOL,
        "confidence": {"type": "float"},
        "model": KW,
        # Plain floats round-trip exactly; dense_vector would be stored as bfloat16.
        "spectrum": {"type": "float", "index": False, "doc_values": False},
        "sensor_readings": {"type": "object", "enabled": False},
        "sensor_sample_count": {"type": "integer"},
        "reference_match": {"type": "object", "enabled": False},
        "limitations": STORED_TEXT,
    }
    research = {
        "verdict": KW,
        "risk_level": KW,
        "headline": TEXT,
        "agent_used": BOOL,
    }
    evidence = {
        "recall_record_ids": KW,
        "web_page_ids": KW,
        "firecrawl_credits_used": {"type": "short"},
        "conversation_id": KW,
    }
    photos = {
        "target": KW,
        "sha256": KW,
        "bytes": {"type": "integer"},
        "media_type": KW,
    }
    return {
        Scan.SCAN_ID: KW,
        Scan.DEVICE_ID: KW,
        Scan.COUNTRY: KW,
        Scan.REVISION: {"type": "integer"},
        Scan.STATUS: KW,
        Scan.DEMO: BOOL,
        Scan.CREATED_AT: DATE,
        Scan.UPDATED_AT: DATE,
        Scan.RECENCY_DATE: DATE,
        Scan.BOTTLE: {"properties": bottle},
        Scan.IMPRINT: {"properties": imprint},
        Scan.NORM: {"properties": norm},
        Scan.HARDWARE: {"properties": hardware},
        # dynamic:false keeps the full report in _source without mapping every leaf.
        Scan.RESEARCH: {"dynamic": False, "properties": research},
        Scan.EVIDENCE: {"dynamic": False, "properties": evidence},
        Scan.STAGES: RAW,
        Scan.PHOTOS: {"properties": photos},
        Scan.RAW: RAW,
    }


def _reports() -> dict[str, Any]:
    location = {
        "label": TEXT_KW,
        "city": KW,
        "region": KW,
        "country": KW,
        "coordinates": GEO,
    }
    return {
        Report.REPORT_ID: KW,
        Report.SCAN_ID: KW,
        Report.PURCHASED_ON: DATE,
        Report.PURCHASE_LOCATION: {"properties": location},
        Report.SELLER: TEXT_KW,
        Report.CREATED_AT: DATE,
    }


_BUILDERS = {
    REGULATORY_INDEX: _regulatory,
    PILLS_INDEX: _pills,
    NDC_INDEX: _ndc,
    WEB_PAGES_INDEX: _web_pages,
    SCANS_INDEX: _scans,
    REPORTS_INDEX: _reports,
}


def mappings_for(index: str) -> dict[str, Any]:
    return {"dynamic": "strict", "properties": _BUILDERS[index]()}


def mapped_fields(index: str) -> set[str]:
    """Top-level field names; seed adapters assert against this before bulk."""
    return set(_BUILDERS[index]())


async def ensure_indices(
    client: AsyncElasticsearch,
    names: tuple[str, ...] = ALL_INDICES,
) -> list[str]:
    created: list[str] = []
    for name in names:
        if await client.indices.exists(index=name):
            if name == SCANS_INDEX:
                # Additive migration: retain existing scans and strict mappings.
                await client.indices.put_mapping(index=name, properties={"hardware": {"properties": {
                    "sensor_readings": {"type": "object", "enabled": False},
                    "sensor_sample_count": {"type": "integer"},
                    "reference_match": {"type": "object", "enabled": False},
                }}})
            continue
        await client.indices.create(index=name, mappings=mappings_for(name))
        created.append(name)
    return created


async def recreate_index(client: AsyncElasticsearch, name: str) -> None:
    if name not in _BUILDERS:
        raise ValueError(f"Refusing to recreate unknown index {name!r}")
    await client.indices.delete(index=name, ignore_unavailable=True)
    await client.indices.create(index=name, mappings=mappings_for(name))
