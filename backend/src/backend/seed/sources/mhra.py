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

# gov.uk writes the class prefix with a colon OR a comma, sometimes with a
# qualifier word ("Class 2 FMD Medicines Recall"), and says "Notification" as
# often as "Defect Notification" — 49 of 588 cached alerts fail the narrow form.
_CLASS_TITLE_RE = re.compile(
    r"^\s*(?:update:\s*)?"
    r"(class\s+\d+\s+[\w\s]*?medicines\s+(?:recall|notification|defect[\w\s]*?))\s*[:,]\s*(.*)$",
    re.I,
)
_CLASS_ANYWHERE_RE = re.compile(r"\bclass\s*[1-4]\b", re.I)
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


_HEADER_LOT_RE = re.compile(r"\bbatch|\blot\b", re.I)
# "From 5000879 to 5000964" under a "Batch number range from and to inclusive"
# header: one cell standing for every batch between the two endpoints.
_RANGE_RE = re.compile(r"\bfrom\s+(\S+)\s+to\s+(\S+)", re.I)
# The interior is only expanded for a small run; `_table_lots` has no MAX_LOTS
# cap of its own and a wide range would flood the exact-match lot field.
_MAX_RANGE = 200
# How many data rows are read before the header's column choice is trusted.
_VALIDATE_ROWS = 5
# `ER 4824` — one batch code printed with a space between a short letter prefix
# and its digits. Deliberately narrow, so a product name never glues into a lot.
_SPLIT_CODE_RE = re.compile(r"^([A-Za-z]{1,4})\s+(\d{3,}[A-Za-z0-9\-/._]*)$")


def _range_codes(cell: str) -> list[str]:
    """`From 5000879 to 5000964` -> both endpoints, and the batches between them
    when the range is numeric, equal-width and short enough to enumerate."""
    match = _RANGE_RE.search(cell)
    if match is None:
        return []
    low = norm.code_token(match.group(1))
    high = norm.code_token(match.group(2))
    if not (low and high):
        return [code for code in (low, high) if code]
    if low.isdigit() and high.isdigit() and len(low) == len(high):
        span = int(high) - int(low)
        if 0 < span < _MAX_RANGE:
            return [str(value).zfill(len(low)) for value in range(int(low), int(high) + 1)]
    return [low, high]


def _cell_codes(cell: str) -> list[str]:
    """Every batch code in one table cell.

    The whole cell used to go through `normalize_lot`, which strips punctuation
    and joins what is left: `T43157 (Almus)` became the un-matchable lot
    `T43157ALMUS`, and a range cell became `FROM5000879TO5000964`.
    """
    codes = _range_codes(cell) or norm.code_tokens(cell)
    if codes:
        return codes
    glued = _SPLIT_CODE_RE.match(cell.strip())
    if glued:  # `ER 4824` — one code with a space inside it
        code = norm.code_token(glued.group(1) + glued.group(2))
        return [code] if code else []
    return []


class _TableLotParser(HTMLParser):
    """Pulls the batch/lot column out of every `<table>` in an MHRA body.

    Keyword-based prose extraction (`extract_batches_from_prose`) misses these:
    the codes live in a data-only table column under a `Batch No.` header, never
    next to the word "batch" in running text.

    Rows are buffered to the end of the table because gov.uk does not always
    follow its own header order (CLDA(16)A/05 has `Batch no | Product | Expiry`
    over rows of `Product | Batch | Expiry`), and a header trusted blindly there
    indexes product names as lot numbers.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lots: list[str] = []
        self._row_index = -1
        self._lot_col: int | None = None
        self._rows: list[list[str]] = []
        self._cells: list[str] = []
        self._cell_chunks: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag == "table":
            self._flush()
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
        elif tag == "table":
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._cell_chunks is not None:
            self._cell_chunks.append(data)

    def close(self) -> None:
        super().close()
        self._flush()

    def _process_row(self) -> None:
        if self._row_index == 0:
            for index, cell in enumerate(self._cells):
                if _HEADER_LOT_RE.search(cell):
                    self._lot_col = index
                    break
            return
        if any(self._cells):
            self._rows.append(self._cells)
        self._cells = []

    @staticmethod
    def _validated_column(rows: list[list[str]], lot_col: int) -> int | None:
        """The header's column unless the data contradicts it.

        Only re-picked when the header column holds no code at all in any of the
        sampled rows AND exactly one other column holds one in most of them; a
        table where nothing qualifies yields no lots, leaving the prose pass to
        cover it rather than indexing whatever the header pointed at.
        """
        sample = rows[:_VALIDATE_ROWS]

        def has_code(row: list[str], column: int) -> bool:
            return column < len(row) and bool(_cell_codes(row[column]))

        if any(has_code(row, lot_col) for row in sample):
            return lot_col
        width = max(len(row) for row in sample)
        alternatives = [
            column
            for column in range(width)
            if column != lot_col and sum(has_code(row, column) for row in sample) * 2 > len(sample)
        ]
        return alternatives[0] if len(alternatives) == 1 else None

    def _flush(self) -> None:
        rows, lot_col = self._rows, self._lot_col
        self._row_index, self._lot_col, self._rows, self._cells = -1, None, [], []
        if lot_col is None or not rows:
            return
        column = self._validated_column(rows, lot_col)
        if column is None:
            return
        for row in rows:
            if column >= len(row):
                continue
            for code in _cell_codes(row[column]):
                if code not in self.lots and len(self.lots) < norm.MAX_LOTS:
                    self.lots.append(code)


def _table_lots(html: str) -> list[str]:
    parser = _TableLotParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup must never abort a seed run
        try:  # markup that aborted mid-table still has its buffered rows
            parser._flush()
        except Exception:  # noqa: BLE001
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

    # A "Class N" title must never fall to 'unknown' (severity_rank 1, below
    # moderate) just because gov.uk wrote the prefix in a shape _split_title
    # cannot cut — build_lot_query sorts on severity_rank. The title feeds
    # severity only, so manufacturer/classification_raw stay honest.
    severity_source = classification_raw or (
        title if _CLASS_ANYWHERE_RE.search(title) else None
    )
    severity, severity_rank = norm.severity_for("MHRA", severity_source)

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
