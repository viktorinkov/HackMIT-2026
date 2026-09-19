"""MHRA (UK) medicines recall notifications -> fields.REGULATORY_INDEX.

Two-step, no Firecrawl: gov.uk Search API for discovery (588 medicines-recall
items), then the gov.uk Content API per item for the alert body.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from backend.knowledge import normalize as norm
from backend.knowledge.fields import REGULATORY_INDEX, Reg
from backend.seed.base import SeedContext, Source
from backend.seed.http import FetchError, fetch_json, get_with_retry, map_limited

_SEARCH_API = "https://www.gov.uk/api/search.json"
_CONTENT_API = "https://www.gov.uk/api/content"
_COUNT = 200
_SEARCH_FIELDS = ("title", "link", "public_timestamp", "description", "alert_type", "content_id")

_BODY_CAP = 30_000
_SEMANTIC_CAP = 1500
_SUMMARY_CAP = 400
_LOT_TEXT_CAP = 1000

_CLASS_TITLE_RE = re.compile(
    r"^\s*(?:update:\s*)?"
    r"(class\s+\d+\s+medicines\s+(?:recall|defect\s+notification|defect\s+information))\s*:\s*(.*)$",
    re.I,
)
_COMPANY_LED_RE = re.compile(r"^\s*(company[- ]led\s+medicines?\s+recall)\s*:\s*(.*)$", re.I)
_ALERT_NUM_RE = re.compile(r"\b[A-Z]{2,5}\s*\(\s*\d{2}\s*\)\s*[A-Za-z]?\s*/\s*\d+\b")
_LOT_HEADING_RE = re.compile(r"affected\s+lot\s+batch\s+numbers.*", re.I | re.S)


def _search_index_path(raw_dir: Path) -> Path:
    return raw_dir / "search-index.json"


def _complete_marker(raw_dir: Path) -> Path:
    return raw_dir / "search-index.complete"


def _content_cache_path(raw_dir: Path, item: dict[str, Any]) -> Path:
    content_id = item.get("content_id") or norm.url_hash(str(item.get("link", "")))
    return raw_dir / f"content-{content_id}.json"


class _TableLotParser(HTMLParser):
    """Pulls the batch/lot column out of every `<table>` in an MHRA body.

    Keyword-based prose extraction (`extract_batches_from_prose`) misses these:
    the codes live in a data-only table column under a `Batch No.` header, never
    next to the word "batch" in running text.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lots: list[str] = []
        self._row_index = -1
        self._lot_col: int | None = None
        self._cells: list[str] = []
        self._cell_chunks: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag == "table":
            self._row_index = -1
            self._lot_col = None
        elif tag == "tr":
            self._row_index += 1
            self._cells = []
        elif tag in ("td", "th"):
            self._cell_chunks = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell_chunks is not None:
            self._cells.append(" ".join(self._cell_chunks).strip())
            self._cell_chunks = None
        elif tag == "tr":
            self._process_row()

    def handle_data(self, data: str) -> None:
        if self._cell_chunks is not None:
            self._cell_chunks.append(data)

    def _process_row(self) -> None:
        if self._row_index == 0:
            for index, cell in enumerate(self._cells):
                if re.search(r"\bbatch|\blot\b", cell, re.I):
                    self._lot_col = index
                    break
            return
        if self._lot_col is None or self._lot_col >= len(self._cells):
            return
        code = norm.normalize_lot(self._cells[self._lot_col])
        if code:
            self.lots.append(code)


def _table_lots(html: str) -> list[str]:
    parser = _TableLotParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup must never abort a seed run
        pass
    return parser.lots


def _split_title(title: str) -> tuple[str | None, str]:
    match = _CLASS_TITLE_RE.match(title)
    if match:
        return match.group(1), match.group(2)
    match = _COMPANY_LED_RE.match(title)
    if match:
        return match.group(1), match.group(2)
    return None, title


def _alert_number(title: str) -> str | None:
    found = list(_ALERT_NUM_RE.finditer(title))
    if not found:
        return None
    return re.sub(r"\s+", "", found[-1].group(0))


def _company_and_product(remainder: str) -> tuple[str | None, str | None]:
    text = _ALERT_NUM_RE.sub("", remainder).rstrip(", ").strip()
    if not text:
        return None, None
    if "," not in text:
        return None, norm.clean_text(text)
    company, _, product = text.partition(",")
    return norm.clean_text(company), norm.clean_text(product)


def _lot_context(body: str, lot_numbers: list[str]) -> str | None:
    if not lot_numbers:
        return None
    match = _LOT_HEADING_RE.search(body)
    if match:
        return norm.truncate_on_sentence(match.group(0), _LOT_TEXT_CAP)
    return norm.truncate_on_sentence("Batch numbers: " + ", ".join(lot_numbers), _LOT_TEXT_CAP)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _clean(doc: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in doc.items() if not (value is None or value == "" or value == [])}


class MhraSource(Source):
    name = "mhra"
    index = REGULATORY_INDEX
    description = "MHRA (UK) medicines recall notifications via gov.uk Search + Content APIs"
    semantic = True

    async def download(self, ctx: SeedContext) -> None:
        raw_dir = ctx.raw_dir(self.name)
        items = await self._discover(ctx, raw_dir)
        if ctx.limit is not None:
            items = items[: ctx.limit]

        targets = [
            item
            for item in items
            if item.get("link") and (ctx.refresh_cache or not _content_cache_path(raw_dir, item).exists())
        ]

        async def fetch_one(item: dict[str, Any]) -> None:
            try:
                response = await get_with_retry(ctx.http, f"{_CONTENT_API}{item['link']}")
            except FetchError:
                return
            _content_cache_path(raw_dir, item).write_text(response.text, encoding="utf-8")

        await map_limited(targets, fetch_one, concurrency=ctx.concurrency)

    async def _discover(self, ctx: SeedContext, raw_dir: Path) -> list[dict[str, Any]]:
        index_path = _search_index_path(raw_dir)
        if index_path.exists() and not ctx.refresh_cache:
            try:
                cached = json.loads(index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                cached = []
            # A listing written by a --limit run is truncated; only reuse it when
            # it is big enough for this run (an unlimited run always re-discovers
            # unless the cache was itself written by an unlimited run).
            complete = _complete_marker(raw_dir).exists()
            if cached and (complete or (ctx.limit is not None and len(cached) >= ctx.limit)):
                return cached

        items: list[dict[str, Any]] = []
        start = 0
        while True:
            params: list[tuple[str, Any]] = [
                ("filter_format", "medical_safety_alert"),
                ("filter_alert_type", "medicines-recall-notification"),
                ("count", _COUNT),
                ("start", start),
                ("order", "-public_timestamp"),
                *(("fields", field) for field in _SEARCH_FIELDS),
            ]
            try:
                payload = await fetch_json(ctx.http, _SEARCH_API, params=params)
            except FetchError:
                break
            results = payload.get("results", [])
            items.extend(results)
            total = payload.get("total", len(items))
            start += _COUNT
            if not results or start >= total:
                break
            if ctx.limit is not None and len(items) >= ctx.limit:
                break

        index_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        marker = _complete_marker(raw_dir)
        if ctx.limit is None:
            marker.touch()
        else:
            marker.unlink(missing_ok=True)
        return items

    def parse(self, ctx: SeedContext) -> Iterator[dict[str, Any]]:
        raw_dir = ctx.raw_dir(self.name)
        index_path = _search_index_path(raw_dir)
        if not index_path.exists():
            return
        try:
            items = json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        items.sort(key=lambda item: item.get("public_timestamp") or "", reverse=True)

        count = 0
        for item in items:
            content_path = _content_cache_path(raw_dir, item)
            if not content_path.exists():
                continue
            try:
                content = json.loads(content_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            doc = to_doc(item, content, now=ctx.now)
            if doc is None:
                continue
            yield doc
            count += 1
            if ctx.limit is not None and count >= ctx.limit:
                return


def to_doc(
    item: dict[str, Any],
    content: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """A gov.uk search hit + its content-API payload -> a peel-regulatory doc."""
    content_id = content.get("content_id") or item.get("content_id")
    if not content_id:
        return None
    title = norm.clean_text(content.get("title") or item.get("title"))
    if not title:
        return None

    details = content.get("details") or {}
    body_html = details.get("body") or ""
    body = norm.html_to_text(body_html)[:_BODY_CAP]

    metadata = details.get("metadata") or {}
    issued = norm.parse_date(metadata.get("issued_date"))
    published = (
        issued
        or norm.parse_date(item.get("public_timestamp"))
        or norm.parse_date(content.get("first_published_at"))
    )
    if published is None:
        return None  # recency_date is non-null; nothing to anchor decay on

    classification_raw, remainder = _split_title(title)
    alert_number = _alert_number(title)
    manufacturer, product = _company_and_product(remainder)
    drug_names_extracted = norm.extract_drug_names(product) if product else []
    dosage_form = norm.normalize_dosage_form(product) or norm.normalize_dosage_form(title)

    lot_numbers = _dedupe(_table_lots(body_html) + norm.extract_batches_from_prose(body))
    lot_text = _lot_context(body, lot_numbers)

    severity, severity_rank = norm.severity_for("MHRA", classification_raw)

    description = norm.clean_text(content.get("description") or item.get("description")) or ""
    summary = norm.truncate_on_sentence(description or body, _SUMMARY_CAP)
    semantic_source = f"{title}. {description} {product or ''}".strip()
    body_semantic = norm.truncate_on_sentence(semantic_source, _SEMANTIC_CAP)

    base_path = content.get("base_path") or item.get("link") or ""
    raw = {key: value for key, value in content.items() if key != "details"}
    if metadata:
        raw["metadata"] = metadata

    doc = {
        "_id": f"mhra-{content_id}",
        Reg.RECORD_ID: f"mhra-{content_id}",
        Reg.SOURCE: "mhra_alerts",
        Reg.SOURCE_ORG: "MHRA",
        Reg.DOC_TYPE: "recall",
        Reg.COUNTRY_OF_AUTHORITY: "United Kingdom",
        Reg.COUNTRIES: ["United Kingdom"],
        Reg.TITLE: title,
        Reg.SUMMARY: summary,
        Reg.BODY: body,
        Reg.BODY_SEMANTIC: body_semantic,
        Reg.HAS_SEMANTIC: True,
        Reg.REASON: description or None,
        Reg.PRODUCT_DESCRIPTION: product,
        Reg.DRUG_NAMES_EXTRACTED: drug_names_extracted,
        Reg.MANUFACTURER: manufacturer,
        Reg.RECALLING_FIRM: manufacturer,
        Reg.LOT_NUMBERS: lot_numbers,
        Reg.LOT_TEXT: lot_text,
        Reg.ALERT_NUMBER: alert_number,
        Reg.DOSAGE_FORM: dosage_form,
        Reg.CLASSIFICATION_RAW: classification_raw,
        Reg.STATUS: "withdrawn" if content.get("withdrawn_notice") else None,
        Reg.SEVERITY: severity,
        Reg.SEVERITY_RANK: severity_rank,
        Reg.PUBLISHED_AT: norm.to_iso(published),
        Reg.EVENT_DATE: norm.to_iso(issued),
        Reg.RECENCY_DATE: norm.to_iso(published),
        Reg.DATE_PRECISION: "published",
        Reg.INDEXED_AT: norm.to_iso(now) if now is not None else None,
        Reg.URL: "https://www.gov.uk" + base_path if base_path else None,
        Reg.ATTRIBUTION: "Medicines and Healthcare products Regulatory Agency (GOV.UK)",
        Reg.SOURCE_LICENSE: "Open Government Licence v3.0",
        Reg.SOURCE_TERMS_URL: "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
        Reg.RAW: raw,
    }
    return _clean(doc)
