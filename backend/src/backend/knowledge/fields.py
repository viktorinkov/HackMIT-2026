"""Single source of truth for Peel's Elasticsearch index and field names.

Mappings, seed adapters, the search builder and the Agent Builder ES|QL tool
strings all import from here, so a rename happens in exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass

REGULATORY_INDEX = "peel-regulatory"
PILLS_INDEX = "peel-pills"
NDC_INDEX = "peel-ndc"
WEB_PAGES_INDEX = "peel-web-pages"
SCANS_INDEX = "peel-scans"
REPORTS_INDEX = "peel-reports"
ALL_INDICES = (
    REGULATORY_INDEX,
    PILLS_INDEX,
    NDC_INDEX,
    WEB_PAGES_INDEX,
    SCANS_INDEX,
    REPORTS_INDEX,
)

# One embedding model everywhere (matches the existing peel-drug-facts index).
INFERENCE_ID = ".jina-embeddings-v5-text-small"
RERANK_INFERENCE_ID = ".jina-reranker-v3.5"

DATE_FORMAT = "strict_date_optional_time||yyyyMMdd"


class Reg:
    """peel-regulatory: recalls and alerts from every regulator."""

    RECORD_ID = "record_id"
    SOURCE = "source"
    SOURCE_ORG = "source_org"
    DOC_TYPE = "doc_type"
    COUNTRY_OF_AUTHORITY = "country_of_authority"
    COUNTRIES = "countries"
    TITLE = "title"
    SUMMARY = "summary"
    BODY = "body"
    BODY_SEMANTIC = "body_semantic"
    REASON = "reason"
    PRODUCT_DESCRIPTION = "product_description"
    DRUG_NAMES = "drug_names"
    DRUG_NAMES_EXTRACTED = "drug_names_extracted"
    MANUFACTURER = "manufacturer"
    RECALLING_FIRM = "recalling_firm"
    RXCUI = "rxcui"
    NDC9 = "ndc9"
    NDC11 = "ndc11"
    NDC_RAW = "ndc_raw"
    NDC_FROM_DESCRIPTION = "ndc_from_description"
    LOT_NUMBERS = "lot_numbers"
    LOT_TEXT = "lot_text"
    COVERS_ALL_LOTS = "covers_all_lots"
    EVENT_ID = "event_id"
    ALERT_NUMBER = "alert_number"
    DOSAGE_FORM = "dosage_form"
    SEVERITY = "severity"
    SEVERITY_RANK = "severity_rank"
    CLASSIFICATION_RAW = "classification_raw"
    STATUS = "status"
    PUBLISHED_AT = "published_at"
    EVENT_DATE = "event_date"
    RECENCY_DATE = "recency_date"
    DATE_PRECISION = "date_precision"
    INDEXED_AT = "indexed_at"
    URL = "url"
    ATTACHMENT_URLS = "attachment_urls"
    HAS_SEMANTIC = "has_semantic"
    ATTRIBUTION = "attribution"
    SOURCE_LICENSE = "source_license"
    SOURCE_TERMS_URL = "source_terms_url"
    SOURCE_DISCLAIMER = "source_disclaimer"
    SOURCE_EXPORT_DATE = "source_export_date"
    RAW = "raw"


class Pill:
    """peel-pills: NLM Pillbox archive (frozen January 2021). No vectors."""

    PILL_ID = "pill_id"
    SETID = "setid"
    SOURCE = "source"
    IMPRINT_RAW = "imprint_raw"
    IMPRINT_NORM = "imprint_norm"
    IMPRINT_SORTED = "imprint_sorted"
    IMPRINT_PARTS = "imprint_parts"
    IMPRINT_TEXT = "imprint_text"
    IMPRINT_LEN = "imprint_len"
    SHAPE = "shape"
    SHAPE_FAMILY = "shape_family"
    COLORS = "colors"
    COLOR_RAW = "color_raw"
    COLOR_COUNT = "color_count"
    SCORE = "score"
    SIZE_MM = "size_mm"
    MEDICINE_NAME = "medicine_name"
    GENERIC_NAME = "generic_name"
    STRENGTH = "strength"
    INGREDIENTS = "ingredients"
    LABELER = "labeler"
    RXCUI = "rxcui"
    PRODUCT_NDC = "product_ndc"
    NDC9 = "ndc9"
    DEA_SCHEDULE = "dea_schedule"
    MARKETING_STATUS = "marketing_status"
    HAS_IMAGE = "has_image"
    IMAGE_KEY = "image_key"
    EFFECTIVE_TIME = "effective_time"
    RAW = "raw"


class Ndc:
    """peel-ndc: openFDA NDC directory. No vectors."""

    PRODUCT_NDC = "product_ndc"
    NDC9 = "ndc9"
    PACKAGE_NDCS = "package_ndcs"
    NDC11 = "ndc11"
    BRAND_NAME = "brand_name"
    GENERIC_NAME = "generic_name"
    LABELER_NAME = "labeler_name"
    ACTIVE_INGREDIENT_NAMES = "active_ingredient_names"
    STRENGTHS = "strengths"
    DOSAGE_FORM = "dosage_form"
    ROUTE = "route"
    PRODUCT_TYPE = "product_type"
    MARKETING_CATEGORY = "marketing_category"
    MARKETING_START_DATE = "marketing_start_date"
    MARKETING_END_DATE = "marketing_end_date"
    LISTING_EXPIRATION_DATE = "listing_expiration_date"
    IS_LISTING_EXPIRED = "is_listing_expired"
    RXCUI = "rxcui"
    UNII = "unii"
    SPL_SET_ID = "spl_set_id"
    PHARM_CLASS = "pharm_class"
    DEA_SCHEDULE = "dea_schedule"
    FINISHED = "finished"
    RAW = "raw"


class Web:
    """peel-web-pages: every page fetched live through Firecrawl."""

    PAGE_ID = "page_id"
    URL = "url"
    DOMAIN = "domain"
    SOURCE_TIER = "source_tier"
    SOURCE_ORG = "source_org"
    TITLE = "title"
    DESCRIPTION = "description"
    CONTENT = "content"
    PAGE_SEMANTIC = "page_semantic"
    DRUG_NAMES = "drug_names"
    LOT_NUMBERS = "lot_numbers"
    NDC9 = "ndc9"
    NDC11 = "ndc11"
    MANUFACTURER = "manufacturer"
    COUNTRIES = "countries"
    FLAGS = "flags"
    IS_RECALL = "is_recall"
    IS_ALERT = "is_alert"
    LANGUAGE = "language"
    STATUS_CODE = "status_code"
    PUBLISHED_AT = "published_at"
    FETCHED_AT = "fetched_at"
    FIRST_SEEN_AT = "first_seen_at"
    LAST_CHANGED_AT = "last_changed_at"
    RECENCY_DATE = "recency_date"
    DATE_PRECISION = "date_precision"
    CONTENT_HASH = "content_hash"
    REVISION = "revision"
    STALE = "stale"
    QUERY_KEY = "query_key"
    QUERIES = "queries"
    SCAN_IDS = "scan_ids"
    FIRECRAWL_CREDITS = "firecrawl_credits"
    VIA = "via"
    RAW = "raw"


class Scan:
    """peel-scans: past scans per device. Dotted paths address sub-objects."""

    SCAN_ID = "scan_id"
    DEVICE_ID = "device_id"
    COUNTRY = "country"
    REVISION = "revision"
    STATUS = "status"
    DEMO = "demo"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    RECENCY_DATE = "recency_date"
    BOTTLE = "bottle"
    IMPRINT = "imprint"
    NORM = "norm"
    HARDWARE = "hardware"
    RESEARCH = "research"
    EVIDENCE = "evidence"
    STAGES = "stages"
    PHOTOS = "photos"
    RAW = "raw"

    NORM_LOT = "norm.lot"
    NORM_NDC9 = "norm.ndc9"
    NORM_NDC11 = "norm.ndc11"
    NORM_IMPRINT = "norm.imprint_norm"
    NORM_SHAPE = "norm.shape"
    NORM_GENERIC_NAME = "norm.generic_name"
    RESEARCH_VERDICT = "research.verdict"
    RESEARCH_RISK_LEVEL = "research.risk_level"


class Report:
    """peel-reports: one report per scan, keyed by scan_id."""

    REPORT_ID = "report_id"
    SCAN_ID = "scan_id"
    CONCERN_TYPE = "concern_type"
    SUMMARY = "summary"
    USER_DESCRIPTION = "user_description"
    SELLER = "seller"
    PURCHASED_ON = "purchased_on"
    PURCHASE_LOCATION = "purchase_location"
    SNAPSHOT = "snapshot"
    CREATED_AT = "created_at"


# Controlled values shared by seed adapters, search and the agent tools.
DOC_TYPES = ("recall", "falsified_alert", "substandard_alert", "safety_alert")
SEVERITY_RANKS = {"critical": 4, "high": 3, "moderate": 2, "unknown": 1}
SOURCE_TIERS = ("regulator", "reference", "news", "other")
DATE_PRECISIONS = ("published", "updated", "fetched")
SCAN_STATUSES = ("pending", "partial", "complete", "error")


@dataclass(frozen=True)
class DecayProfile:
    """Gauss decay with a floor: floor + (1 - floor) * gauss(age)."""

    offset_days: int
    scale_days: int
    floor: float

    @property
    def half_life_days(self) -> float:
        # ES|QL tools emulate the same curve with POW(0.5, age / half_life).
        return float(self.scale_days)


REGULATORY_DECAY = DecayProfile(offset_days=30, scale_days=730, floor=0.35)
WEB_DECAY = DecayProfile(offset_days=1, scale_days=7, floor=0.20)
