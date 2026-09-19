"""openFDA drug enforcement (recalls) -> peel-regulatory.

The anchor source. FDA enforcement reports are the only corpus that pairs a
recall reason with the manufacturer's own lot codes, so they are what turns a
lot read off a bottle label into an exact verdict rather than a guess.
"""

from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from backend.knowledge import normalize
from backend.knowledge.fields import REGULATORY_INDEX, Reg
from backend.seed.base import SeedContext, Source
from backend.seed.http import download_file, fetch_json

SOURCE_NAME = "openfda_enforcement"
MANIFEST_URL = "https://api.fda.gov/download.json"
# Only used when the manifest is unreachable; the manifest lists the real parts.
FALLBACK_PARTITION = (
    "https://download.open.fda.gov/drug/enforcement/drug-enforcement-0001-of-0001.json.zip"
)
# The IRES product id is internal to accessdata and is absent from the enforcement
# record, so the openFDA query link is the only public URL we can derive.
RECORD_URL = 'https://api.fda.gov/drug/enforcement.json?search=recall_number:%22{}%22'

ATTRIBUTION = "U.S. Food and Drug Administration (openFDA)"
SOURCE_LICENSE = "Public domain (CC0)"
SOURCE_TERMS_URL = "https://open.fda.gov/terms/"

TITLE_CAP = 120
SUMMARY_CAP = 400
# body_semantic is the only embedded field: capped, and never fed code_info,
# because lot tables poison the vector space and burn inference (audit F2/F11).
SEMANTIC_CAP = 900

_MANIFEST_FILE = "manifest.json"

# A US ZIP+4 in the firm's address has exactly the shape of a 5-4 product NDC, so
# `Bethlehem, PA 18018-3524` was being indexed as ndc9 180183524 — including in
# ndc_from_description, the field reserved for NDCs that identify this record.
# Only the ZIP is dropped: requiring an `NDC` label instead would lose the real,
# unlabelled NDCs that ~1,000 cached descriptions write (e.g. `76045-0004-1`).
_ZIP4_RE = re.compile(
    r"\b(?:A[LKZR]|C[AOT]|D[EC]|FL|GA|HI|I[DLNA]|K[SY]|LA|M[EDAINSOT]|N[EVHJMYCD]"
    r"|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[TA]|W[AVIY])\s+\d{5}-\d{4}\b"
)


def _add(target: list[str], value: str | None) -> None:
    if value and value not in target:
        target.append(value)


def _strings(value: object) -> list[str]:
    """openfda.* fields are lists, but bare strings turn up in older records."""
    items = value if isinstance(value, list) else [value]
    return [text for text in (normalize.clean_text(item) for item in items) if text]


def _sentence(text: str) -> str:
    return text if not text or text[-1] in ".!?" else f"{text}."


def _compact(doc: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in doc.items() if value not in (None, "", [], {})}


def to_doc(
    record: dict[str, Any],
    *,
    indexed_at: str | None = None,
    disclaimer: str | None = None,
    terms_url: str = SOURCE_TERMS_URL,
    export_date: str | None = None,
) -> dict[str, Any] | None:
    recall_number = normalize.clean_text(record.get("recall_number"))
    if not recall_number:
        return None
    published = normalize.to_iso(normalize.parse_date(record.get("report_date")))
    event_date = normalize.to_iso(normalize.parse_date(record.get("recall_initiation_date")))
    recency = published or event_date
    if not recency:
        return None  # decay ranking silently drops documents with no recency_date

    product = normalize.clean_text(record.get("product_description")) or ""
    reason = normalize.clean_text(record.get("reason_for_recall")) or ""
    code_info = normalize.clean_text(record.get("code_info")) or ""
    distribution = normalize.clean_text(record.get("distribution_pattern")) or ""
    recalling_firm = normalize.clean_text(record.get("recalling_firm"))
    classification = normalize.clean_text(record.get("classification"))
    status = normalize.clean_text(record.get("status"))
    openfda = record.get("openfda") or {}

    codes = normalize.extract_lots(code_info)
    severity, severity_rank = normalize.severity_for("FDA", classification)

    # openfda.product_ndc/package_ndc enumerate every SIBLING strength of the
    # product line (audit P4), so the NDCs written in this record's own text are
    # kept apart in ndc_from_description; those are the ones that identify a lot.
    ndc_raw: list[str] = []
    ndc9: list[str] = []
    ndc11: list[str] = []
    ndc_from_description: list[str] = []
    own = normalize.extract_ndcs(_ZIP4_RE.sub(" ", f"{product} {code_info}"))
    siblings = _strings(openfda.get("product_ndc")) + _strings(openfda.get("package_ndc"))
    for raw, from_own_text in [(v, True) for v in own] + [(v, False) for v in siblings]:
        forms = normalize.normalize_ndc(raw)
        if forms is None:
            continue
        _add(ndc_raw, forms.raw)
        _add(ndc9, forms.ndc9)
        _add(ndc11, forms.ndc11)
        if from_own_text:
            _add(ndc_from_description, forms.ndc9)

    drug_names: list[str] = []
    for value in (
        _strings(openfda.get("generic_name"))
        + _strings(openfda.get("brand_name"))
        + _strings(openfda.get("substance_name"))
    ):
        _add(drug_names, normalize.normalize_drug_name(value))

    countries: list[str] = []
    for name in normalize.extract_countries(distribution):
        _add(countries, name)
    if "nationwide" in distribution.casefold():
        _add(countries, "United States")
    for name in normalize.extract_countries(record.get("country")):
        _add(countries, name)

    label = f"{classification} recall" if classification else "Drug recall"
    head = normalize.truncate_on_sentence(product, TITLE_CAP)
    title = f"{label}: {head}" if head else f"{label} {recall_number}"
    summary = normalize.truncate_on_sentence(
        " ".join(part for part in (_sentence(reason), product) if part), SUMMARY_CAP
    )
    firm_line = ", ".join(
        part
        for part in (
            recalling_firm,
            normalize.clean_text(record.get("city")),
            normalize.clean_text(record.get("state")),
            normalize.clean_text(record.get("country")),
        )
        if part
    )
    body = "\n".join(
        part
        for part in (
            product,
            f"Reason for recall: {reason}" if reason else "",
            f"Codes: {code_info}" if code_info else "",
            f"Distribution: {distribution}" if distribution else "",
            f"Recalling firm: {firm_line}" if firm_line else "",
        )
        if part
    )
    body_semantic = normalize.truncate_on_sentence(
        " ".join(part for part in (_sentence(title), _sentence(reason), product) if part),
        SEMANTIC_CAP,
    )

    return _compact(
        {
            "_id": f"fda-enf-{recall_number}",
            Reg.RECORD_ID: f"fda-enf-{recall_number}",
            Reg.SOURCE: SOURCE_NAME,
            Reg.SOURCE_ORG: "FDA",
            Reg.DOC_TYPE: "recall",
            Reg.COUNTRY_OF_AUTHORITY: "United States",
            Reg.COUNTRIES: countries,
            Reg.TITLE: title,
            Reg.SUMMARY: summary,
            Reg.BODY: body,
            Reg.BODY_SEMANTIC: body_semantic,
            Reg.HAS_SEMANTIC: bool(body_semantic),
            Reg.REASON: reason,
            Reg.PRODUCT_DESCRIPTION: product,
            Reg.DRUG_NAMES: drug_names,
            Reg.DRUG_NAMES_EXTRACTED: normalize.extract_drug_names(product),
            Reg.MANUFACTURER: next(iter(_strings(openfda.get("manufacturer_name"))), recalling_firm),
            Reg.RECALLING_FIRM: recalling_firm,
            Reg.RXCUI: _strings(openfda.get("rxcui")),
            Reg.NDC9: ndc9,
            Reg.NDC11: ndc11,
            Reg.NDC_RAW: ndc_raw,
            Reg.NDC_FROM_DESCRIPTION: ndc_from_description,
            Reg.LOT_NUMBERS: codes.lot_numbers,
            Reg.LOT_TEXT: code_info,
            Reg.COVERS_ALL_LOTS: codes.covers_all_lots,
            Reg.EVENT_ID: normalize.clean_text(record.get("event_id")),
            Reg.DOSAGE_FORM: normalize.normalize_dosage_form(product),
            Reg.SEVERITY: severity,
            Reg.SEVERITY_RANK: severity_rank,
            Reg.CLASSIFICATION_RAW: classification,
            Reg.STATUS: status.casefold() if status else None,
            Reg.PUBLISHED_AT: published,
            Reg.EVENT_DATE: event_date,
            Reg.RECENCY_DATE: recency,
            Reg.DATE_PRECISION: "published",
            Reg.INDEXED_AT: indexed_at,
            Reg.URL: RECORD_URL.format(recall_number),
            Reg.ATTRIBUTION: ATTRIBUTION,
            Reg.SOURCE_LICENSE: SOURCE_LICENSE,
            Reg.SOURCE_TERMS_URL: terms_url or SOURCE_TERMS_URL,
            Reg.SOURCE_DISCLAIMER: disclaimer,
            Reg.SOURCE_EXPORT_DATE: export_date,
            Reg.RAW: record,
        }
    )


def _read_manifest(raw_dir: Path) -> dict[str, Any]:
    path = raw_dir / _MANIFEST_FILE
    if not path.exists():
        return {"export_date": None, "files": [FALLBACK_PARTITION]}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"export_date": None, "files": [FALLBACK_PARTITION]}


def _read_zip(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".json")]
        if not names:
            return {}, []
        with archive.open(names[0]) as handle:
            payload = json.load(handle)
    results = payload.get("results") or []
    return payload.get("meta") or {}, [row for row in results if isinstance(row, dict)]


class OpenFdaEnforcementSource(Source):
    name = SOURCE_NAME
    index = REGULATORY_INDEX
    description = "FDA drug recall enforcement reports (bulk export, lot-level)."
    semantic = True

    async def download(self, ctx: SeedContext) -> None:
        raw_dir = ctx.raw_dir(self.name)
        manifest_path = raw_dir / _MANIFEST_FILE
        manifest: dict[str, Any] | None = None
        if manifest_path.exists() and not ctx.refresh_cache:
            manifest = _read_manifest(raw_dir)
        if manifest is None:
            manifest = await self._fetch_manifest(ctx)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        failure: Exception | None = None
        for url in manifest["files"]:
            dest = raw_dir / url.rsplit("/", 1)[-1]
            try:
                await download_file(ctx.http, url, dest, refresh=ctx.refresh_cache)
            except Exception as exc:  # one bad partition must not sink the source
                failure = exc
        if failure is not None and not any(raw_dir.glob("*.json.zip")):
            raise failure

    @staticmethod
    async def _fetch_manifest(ctx: SeedContext) -> dict[str, Any]:
        export_date: str | None = None
        files: list[str] = []
        try:
            payload = await fetch_json(ctx.http, MANIFEST_URL)
            block = payload["results"]["drug"]["enforcement"]
            export_date = block.get("export_date")
            files = [
                part["file"] for part in block.get("partitions") or [] if part.get("file")
            ]
        except Exception:  # noqa: BLE001 - the partition URL is stable enough to fall back on
            pass
        return {"export_date": export_date, "files": files or [FALLBACK_PARTITION]}

    def parse(self, ctx: SeedContext) -> Iterator[dict[str, Any]]:
        raw_dir = ctx.raw_dir(self.name)
        manifest = _read_manifest(raw_dir)
        export_date = normalize.to_iso(normalize.parse_date(manifest.get("export_date")))
        indexed_at = normalize.to_iso(ctx.now)

        meta: dict[str, Any] = {}
        records: list[dict[str, Any]] = []
        for path in sorted(raw_dir.glob("*.json.zip")):
            try:
                part_meta, part_records = _read_zip(path)
            except (OSError, ValueError, zipfile.BadZipFile):
                continue
            meta = meta or part_meta
            records.extend(part_records)

        disclaimer = normalize.clean_text(meta.get("disclaimer"))
        terms_url = normalize.clean_text(meta.get("terms")) or SOURCE_TERMS_URL
        # report_date is YYYYMMDD, so a string sort is a date sort.
        records.sort(key=lambda row: str(row.get("report_date") or ""), reverse=True)

        emitted = 0
        for record in records:
            doc = to_doc(
                record,
                indexed_at=indexed_at,
                disclaimer=disclaimer,
                terms_url=terms_url,
                export_date=export_date,
            )
            if doc is None:
                continue
            yield doc
            emitted += 1
            if ctx.limit is not None and emitted >= ctx.limit:
                return
