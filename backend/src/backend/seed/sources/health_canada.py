"""Health Canada recalls and safety alerts -> peel-regulatory.

The bulk JSON export covers every recall category (food, vehicles, toys, ...);
only "Drugs" and "Natural health products" are kept. It also carries no lot
numbers, so the newest kept records get a capped, cached detail-page fetch
that parses the page's "Affected products" table for lots/DINs/manufacturer.
Older page vintages render that table differently (nested <p> per cell, no
`id` attribute, extra columns) — the row parser tolerates all of that and
simply yields no lots when a page doesn't match at all.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from backend.knowledge import normalize
from backend.knowledge.fields import REGULATORY_INDEX, Reg
from backend.seed.base import SeedContext, Source
from backend.seed.http import download_file, map_limited

BULK_URL = "https://recalls-rappels.canada.ca/sites/default/files/opendata-donneesouvertes/HCRSAMOpenData.json"
KEPT_CATEGORIES = {"Drugs", "Natural health products"}
DEFAULT_DETAIL_LIMIT = 600
BODY_SEMANTIC_CAP = 900
SUMMARY_CAP = 400

ATTRIBUTION = "Health Canada — Recalls and Safety Alerts"
SOURCE_LICENSE = "Open Government Licence – Canada"
SOURCE_TERMS_URL = "https://open.canada.ca/en/open-government-licence-canada"

_LOT_SPLIT_RE = re.compile(r"[,;/\s]+")
# `Lot #: FA2B6004A Expiry: 2029/04/19` — the value right after an expiry label
# belongs to that field, not to the lot column ('2029'). Lot/batch labels are
# deliberately NOT in this set: `Canadian lots: 3213779` puts a real lot there.
_EXPIRY_LABEL_RE = re.compile(r"^(?:exp|exp\.|expiry|expiration|expires)[\s#:.]*$", re.I)


def _text(value: object) -> str | None:
    """HTML-entity-unescape + collapse whitespace (the JSON carries raw `&nbsp;`)."""
    if value is None:
        return None
    return normalize.clean_text(normalize.html_to_text(str(value)))


# --------------------------------------------------------------- detail table


class _TableCollector(HTMLParser):
    """Collects every <table> inside <main> as {id, rows}, tolerant of tags
    (e.g. <p>) nested inside a cell — a plain html_to_text() pass on the whole
    table loses the column alignment when cells are <p>-wrapped (verified on
    real pages), so this walks td/th boundaries directly instead."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict[str, Any]] = []
        self._in_main = 0
        self._table: dict[str, Any] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "main":
            self._in_main += 1
            return
        if not self._in_main:
            return
        if tag == "table":
            self._table = {"id": dict(attrs).get("id") or "", "rows": []}
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "main" and self._in_main:
            self._in_main -= 1
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(normalize.clean_text("".join(self._cell)) or "")
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table["rows"].append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _select_table_rows(html: str) -> list[dict[str, str]]:
    """Pick the "Affected products" table and return header-mapped rows.
    Degrades to [] rather than raising when the page has no such table."""
    collector = _TableCollector()
    try:
        collector.feed(html)
        collector.close()
    except Exception:  # noqa: BLE001 - a malformed page must never abort a seed run
        return []
    candidates = [t for t in collector.tables if len(t["rows"]) >= 2]
    if not candidates:
        return []
    chosen = next((t for t in candidates if "affected_products" in t["id"].lower()), None)
    if chosen is None:
        chosen = next(
            (t for t in candidates if any("lot" in cell.lower() for cell in t["rows"][0])),
            None,
        )
    if chosen is None:
        chosen = candidates[0]
    headers = [h.strip().lower() for h in chosen["rows"][0]]
    rows: list[dict[str, str]] = []
    for raw_row in chosen["rows"][1:]:
        if not any(raw_row):
            continue
        rows.append({headers[i] if i < len(headers) else f"col{i}": v for i, v in enumerate(raw_row)})
    return rows


@dataclass(frozen=True)
class _DetailInfo:
    lot_numbers: list[str]
    lot_text: str
    manufacturers: list[str]
    covers_all_lots: bool = False


_EMPTY_DETAIL = _DetailInfo([], "", [])


def _cell_lots(cell: str) -> list[str]:
    """Lot-column cell -> the codes in it, gated by the same test the FDA
    `code_info` path uses. Splitting and calling `normalize_lot` directly let
    neighbouring words ('EXPIRY', 'CANADIAN') and date fragments ('2029')
    through, and they are exact-matchable in Reg.LOT_NUMBERS."""
    out: list[str] = []
    after_expiry = False
    for token in _LOT_SPLIT_RE.split(cell):
        if not token:
            continue
        if _EXPIRY_LABEL_RE.match(token):
            after_expiry = True
            continue
        if after_expiry:
            after_expiry = False
            continue
        code = normalize.lot_code(token)
        if code and code not in out:
            out.append(code)
    return out


def _extract_detail(html: str | None) -> _DetailInfo:
    if not html:
        return _EMPTY_DETAIL
    rows = _select_table_rows(html)
    if not rows:
        return _EMPTY_DETAIL
    lots: list[str] = []
    lot_cells: list[str] = []
    manufacturers: list[str] = []
    covers_all = False
    for row in rows:
        lot_key = next((k for k in row if "lot" in k), None)
        if lot_key and row[lot_key]:
            lot_cells.append(row[lot_key])
            # "All lots" is a coverage statement, not the lot code 'ALL'.
            covers_all = covers_all or normalize.mentions_all_lots(row[lot_key])
            for code in _cell_lots(row[lot_key]):
                if code not in lots:
                    lots.append(code)
        man_key = next((k for k in row if "manufactur" in k), None)
        if man_key and row[man_key]:
            name = normalize.clean_text(row[man_key])
            if name and name not in manufacturers:
                manufacturers.append(name)
    return _DetailInfo(lots, " | ".join(lot_cells), manufacturers, covers_all)


# ------------------------------------------------------------------- to_doc


def to_doc(
    record: dict[str, Any],
    *,
    now: datetime | None = None,
    detail_html: str | None = None,
) -> dict[str, Any] | None:
    nid = normalize.clean_text(record.get("NID"))
    if not nid:
        return None
    now = now or datetime.now(UTC)
    published = normalize.parse_date(record.get("Last updated"))
    if published is None:  # recency_date is mandatory
        return None

    title = _text(record.get("Title")) or ""
    issue = _text(record.get("Issue"))
    product = _text(record.get("Product"))
    what_to_do = _text(record.get("What you should do"))
    classification_raw = normalize.clean_text(record.get("Recall class"))
    severity, severity_rank = normalize.severity_for("Health Canada", classification_raw)
    doc_type = normalize.classify_doc_type(f"{title} {issue or ''}", default="recall")

    detail = _extract_detail(detail_html)
    body = "\n\n".join(p for p in (title, product, issue, what_to_do, detail.lot_text) if p)
    lot_numbers = list(dict.fromkeys([*detail.lot_numbers, *normalize.extract_batches_from_prose(body)]))

    summary = normalize.truncate_on_sentence(f"{title}. {issue}" if issue else title, SUMMARY_CAP)
    semantic_src = f"{title}. {issue or ''} {product or ''}".strip()
    body_semantic = normalize.truncate_on_sentence(semantic_src, BODY_SEMANTIC_CAP)

    drug_names_extracted: list[str] = []
    for part in (product.split(";") if product else [title]):
        for name in normalize.extract_drug_names(part):
            if name not in drug_names_extracted:
                drug_names_extracted.append(name)
    if not drug_names_extracted:
        for name in normalize.extract_drug_names(title):
            if name not in drug_names_extracted:
                drug_names_extracted.append(name)

    doc: dict[str, Any] = {
        "_id": f"hc-{nid}",
        Reg.RECORD_ID: f"hc-{nid}",
        Reg.SOURCE: "health_canada_recalls",
        Reg.SOURCE_ORG: "Health Canada",
        Reg.DOC_TYPE: doc_type,
        Reg.COUNTRY_OF_AUTHORITY: "Canada",
        Reg.COUNTRIES: ["Canada"],
        Reg.TITLE: title,
        Reg.SUMMARY: summary,
        Reg.BODY: body,
        Reg.BODY_SEMANTIC: body_semantic,
        Reg.HAS_SEMANTIC: bool(body_semantic),
        Reg.REASON: issue,
        Reg.PRODUCT_DESCRIPTION: product,
        Reg.DRUG_NAMES_EXTRACTED: drug_names_extracted,
        Reg.MANUFACTURER: detail.manufacturers,
        Reg.LOT_NUMBERS: lot_numbers,
        Reg.LOT_TEXT: detail.lot_text or None,
        # Only ever True: `recalls_covering_all_lots` terms on it, and an
        # explicit False on every other record would bloat the index for nothing.
        Reg.COVERS_ALL_LOTS: True if detail.covers_all_lots else None,
        Reg.CLASSIFICATION_RAW: classification_raw,
        Reg.SEVERITY: severity,
        Reg.SEVERITY_RANK: severity_rank,
        Reg.STATUS: "archived" if record.get("Archived") == "1" else None,
        Reg.PUBLISHED_AT: normalize.to_iso(published),
        Reg.DATE_PRECISION: "updated",
        Reg.RECENCY_DATE: normalize.to_iso(published),
        Reg.INDEXED_AT: normalize.to_iso(now),
        Reg.URL: normalize.clean_text(record.get("URL")),
        Reg.ATTRIBUTION: ATTRIBUTION,
        Reg.SOURCE_LICENSE: SOURCE_LICENSE,
        Reg.SOURCE_TERMS_URL: SOURCE_TERMS_URL,
        Reg.RAW: record,
    }
    return {k: v for k, v in doc.items() if k == "_id" or v not in (None, "", [])}


# ------------------------------------------------------------------ Source


def _load_bulk(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _kept_newest_first(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = [r for r in records if r.get("Category") in KEPT_CATEGORIES]
    kept.sort(key=lambda r: r.get("Last updated") or "", reverse=True)
    return kept


class HealthCanadaSource(Source):
    name = "health_canada"
    index = REGULATORY_INDEX
    description = "Health Canada recalls & safety alerts (Drugs, Natural health products)"
    semantic = True

    async def download(self, ctx: SeedContext) -> None:
        raw_dir = ctx.raw_dir(self.name)
        bulk_path = raw_dir / "HCRSAMOpenData.json"
        await download_file(ctx.http, BULK_URL, bulk_path, refresh=ctx.refresh_cache)

        kept = _kept_newest_first(_load_bulk(bulk_path))
        detail_limit = int(ctx.options.get("hc_detail_limit", DEFAULT_DETAIL_LIMIT))
        if ctx.limit is not None:
            detail_limit = min(detail_limit, ctx.limit)
        detail_dir = raw_dir / "detail"

        async def fetch_one(record: dict[str, Any]) -> None:
            nid = normalize.clean_text(record.get("NID"))
            url = normalize.clean_text(record.get("URL"))
            if not nid or not url:
                return
            await download_file(ctx.http, url, detail_dir / f"{nid}.html", refresh=ctx.refresh_cache)

        await map_limited(kept[:detail_limit], fetch_one, ctx.concurrency)

    def parse(self, ctx: SeedContext) -> Iterator[dict[str, Any]]:
        raw_dir = ctx.raw_dir(self.name)
        bulk_path = raw_dir / "HCRSAMOpenData.json"
        if not bulk_path.exists():
            return
        detail_dir = raw_dir / "detail"
        yielded = 0
        for record in _kept_newest_first(_load_bulk(bulk_path)):
            nid = normalize.clean_text(record.get("NID"))
            detail_html = None
            if nid:
                detail_path = detail_dir / f"{nid}.html"
                if detail_path.exists():
                    try:
                        detail_html = detail_path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        detail_html = None
            doc = to_doc(record, now=ctx.now, detail_html=detail_html)
            if doc is None:
                continue
            yield doc
            yielded += 1
            if ctx.limit is not None and yielded >= ctx.limit:
                return
