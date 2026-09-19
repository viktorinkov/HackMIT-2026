"""WHO Medical Product Alerts -> peel-regulatory.

The OData news feed carries metadata only, so the prose comes from the alert
page and the batch tables come from the annex PDFs on cdn.who.int. Both are
plain anonymous GETs. Parsing the annexes is what makes WHO lot-matchable:
most alerts say "refer to the Annex" and carry no batch number inline.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pypdf

from backend.knowledge.fields import REGULATORY_INDEX, Reg
from backend.knowledge.normalize import (
    classify_doc_type,
    clean_text,
    extract_batches_from_prose,
    extract_countries,
    html_to_text,
    normalize_dosage_form,
    normalize_drug_name,
    normalize_lot,
    parse_date,
    severity_for,
    to_iso,
    truncate_on_sentence,
)
from backend.seed.base import SeedContext, Source
from backend.seed.http import download_file, fetch_json, get_with_retry, map_limited

LISTING_URL = "https://www.who.int/api/news/newsitems"
LISTING_PARAMS: list[tuple[str, Any]] = [
    ("$filter", "contains(UrlName,'medical-product-alert')"),
    ("$orderby", "PublicationDateAndTime desc"),
    ("$top", "100"),
    ("$count", "true"),
]
PAGE_BASE = "https://www.who.int/news/item"

MAX_PDF_BYTES = 15 * 1024 * 1024
BODY_CAP = 60_000
SEMANTIC_CAP = 1800
SUMMARY_CAP = 400
LOT_TEXT_CAP = 4000

ATTRIBUTION = "World Health Organization"
SOURCE_LICENSE = "CC BY-NC-SA 3.0 IGO"
SOURCE_TERMS_URL = "https://www.who.int/about/policies/publishing/copyright"

_ARTICLE_RE = re.compile(r"<article\b[^>]*>(.*?)</article>", re.S | re.I)
_ANCHOR_RE = re.compile(r"<a\b[^>]*?\bhref=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.S | re.I)
_PDF_HREF_RE = re.compile(r"^https?://cdn\.who\.int/[^\s]+?\.pdf(?:\?|$)", re.I)
_ALERT_NUMBER_RE = re.compile(r"N[°ºo]\s*(\d+\s*/\s*\d{4})", re.I)

# pypdf logs a multi-line fontTools advisory for every embedded Type1 font. The
# text layer extracts fine without fontTools, and 83 annexes would otherwise bury
# the seed run's own output.
logging.getLogger("pypdf._cmap").setLevel(logging.ERROR)


class WhoAlertsSource(Source):
    name = "who_alerts"
    index = REGULATORY_INDEX
    description = "WHO Medical Product Alerts (falsified/substandard) with annex PDFs."
    semantic = True

    async def download(self, ctx: SeedContext) -> None:
        root = ctx.raw_dir(self.name)
        listing_path = root / "listing.json"
        if ctx.refresh_cache or not listing_path.exists():
            payload = await fetch_json(ctx.http, LISTING_URL, params=LISTING_PARAMS)
            listing_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        items = _items(listing_path, ctx.limit)

        pages = root / "pages"
        pages.mkdir(parents=True, exist_ok=True)

        async def page(item: dict[str, Any]) -> None:
            dest = pages / f"{item['Id']}.html"
            if dest.exists() and dest.stat().st_size > 0 and not ctx.refresh_cache:
                return
            response = await get_with_retry(ctx.http, _page_url(item))
            dest.write_text(response.text, encoding="utf-8")

        await map_limited(items, page, ctx.concurrency)

        pdfs = root / "pdfs"
        pdfs.mkdir(parents=True, exist_ok=True)
        urls = sorted({url for item in items for url in _annex_urls(_read(pages / f"{item['Id']}.html"))})

        async def annex(url: str) -> None:
            dest = pdfs / _pdf_name(url)
            if dest.exists() and dest.stat().st_size > 0 and not ctx.refresh_cache:
                return
            if await _too_big(ctx, url):
                return
            await download_file(ctx.http, url, dest, refresh=ctx.refresh_cache)
            if dest.stat().st_size > MAX_PDF_BYTES:
                dest.unlink(missing_ok=True)

        await map_limited(urls, annex, ctx.concurrency)

    def parse(self, ctx: SeedContext) -> Iterator[dict[str, Any]]:
        root = ctx.raw_dir(self.name)
        pages = root / "pages"
        pdfs = root / "pdfs"
        yielded = 0
        for item in _items(root / "listing.json", None):
            html = _read(pages / f"{item['Id']}.html")
            if not html:
                continue
            article = _ARTICLE_RE.search(html)
            page_text = html_to_text(article.group(1)) if article else ""
            urls = _annex_urls(html)
            annex_text = "\n\n".join(filter(None, (_pdf_text(pdfs / _pdf_name(url)) for url in urls)))
            doc = to_doc(
                item,
                page_text=page_text,
                annex_text=annex_text,
                attachment_urls=urls,
                indexed_at=ctx.now,
            )
            if doc is None:
                continue
            yield doc
            yielded += 1
            if ctx.limit is not None and yielded >= ctx.limit:
                return


# --------------------------------------------------------------------------- mapping


def to_doc(
    item: dict[str, Any],
    *,
    page_text: str,
    annex_text: str = "",
    attachment_urls: Sequence[str] = (),
    indexed_at: datetime | None = None,
) -> dict[str, Any] | None:
    """One OData item plus its already-extracted text -> a peel-regulatory doc."""
    record_id = clean_text(item.get("Id"))
    title = clean_text(item.get("Title"))
    published = to_iso(parse_date(item.get("PublicationDateAndTime")))
    if not record_id or not title or not published:
        return None

    page = (page_text or "").strip()
    annex = _strip_boilerplate(annex_text)
    doc_type = _doc_type(title, page)
    severity, severity_rank = severity_for("WHO", None, doc_type)

    lots, lot_text = _lots(page, annex)
    rows = _annex_field(annex, r"product\s+names?")
    rows += _annex_field(annex, r"declared\s+active\s+ingredients?")
    description = clean_text(" | ".join(rows))

    body = truncate_on_sentence(page + ("\n\nANNEX\n" + annex if annex else ""), BODY_CAP)
    drug_names = _drug_names(title)

    doc: dict[str, Any] = {
        "_id": f"who-mpa-{record_id}",
        Reg.RECORD_ID: f"who-mpa-{record_id}",
        Reg.SOURCE: "who_medical_product_alert",
        Reg.SOURCE_ORG: "WHO",
        Reg.DOC_TYPE: doc_type,
        Reg.TITLE: title,
        Reg.SUMMARY: _summary(page, title),
        Reg.BODY: body,
        Reg.BODY_SEMANTIC: truncate_on_sentence(f"{title}. {page}", SEMANTIC_CAP),
        Reg.HAS_SEMANTIC: True,
        Reg.PRODUCT_DESCRIPTION: description,
        Reg.DRUG_NAMES: drug_names,
        Reg.DRUG_NAMES_EXTRACTED: _extracted_names(rows, drug_names),
        Reg.MANUFACTURER: _manufacturer(annex, page),
        Reg.LOT_NUMBERS: lots,
        Reg.LOT_TEXT: lot_text,
        Reg.ALERT_NUMBER: _alert_number(title),
        Reg.DOSAGE_FORM: normalize_dosage_form(title) or normalize_dosage_form(description),
        Reg.COUNTRIES: extract_countries(f"{page}\n{annex}"),
        Reg.SEVERITY: severity,
        Reg.SEVERITY_RANK: severity_rank,
        Reg.CLASSIFICATION_RAW: clean_text(item.get("NewsType")),
        Reg.PUBLISHED_AT: published,
        Reg.RECENCY_DATE: published,
        Reg.DATE_PRECISION: "published",
        Reg.INDEXED_AT: to_iso(indexed_at),
        Reg.URL: _page_url(item),
        Reg.ATTACHMENT_URLS: list(attachment_urls),
        Reg.ATTRIBUTION: ATTRIBUTION,
        Reg.SOURCE_LICENSE: SOURCE_LICENSE,
        Reg.SOURCE_TERMS_URL: SOURCE_TERMS_URL,
        Reg.RAW: item,
    }
    return {key: value for key, value in doc.items() if value not in (None, "", [], {})}


def _doc_type(title: str, page_text: str) -> str:
    # Every annex repeats "substandard and falsified medical products" in its
    # letterhead, so the title decides and only an unmarked title falls back.
    return classify_doc_type(title, default="") or classify_doc_type(page_text)


def _alert_number(title: str) -> str | None:
    match = _ALERT_NUMBER_RE.search(title)
    return re.sub(r"\s+", "", match.group(1)) if match else None


def _summary(page_text: str, title: str) -> str | None:
    lines = page_text.split("\n")
    while lines and (not lines[0].strip() or _is_heading(lines[0], title)):
        lines.pop(0)
    return truncate_on_sentence(" ".join(" ".join(lines).split()), SUMMARY_CAP) or None


_HEADINGS = {"alert summary", "summary", "background", "introduction"}


def _is_heading(line: str, title: str) -> bool:
    stripped = line.strip()
    return stripped.casefold() in _HEADINGS or stripped.casefold() == title.casefold()


# --------------------------------------------------------------------------- names

_TITLE_PREFIX_RE = re.compile(r"^.*?\balert\b\s*(?:n[°ºo]\s*\d+\s*/\s*\d{4})?\s*[:\-]\s*", re.I)
_QUALIFIER_RE = re.compile(
    r"^(?:falsified|substandard|contaminated|unregistered|counterfeit|spurious|degraded|"
    r"suspected|confirmed)\s+",
    re.I,
)
_PRODUCT_WORD_RE = re.compile(r"\bproducts?\b", re.I)
_PARENS_RE = re.compile(r"\(([^)]{2,60})\)")
_BRAND_RE = re.compile(r"\b[A-Z][A-Z0-9][A-Z0-9\-]{1,}\b")
# Acronyms that share the all-caps shape of a brand name but never are one.
_NOT_BRANDS = {
    "WHO", "IVD", "USP", "NRA", "API", "USA", "UK", "EU", "US", "AND", "THE", "FOR",
    "MG", "ML", "IU", "HIV", "TB", "COVID", "SARS", "PDF", "BP", "NF", "AL",
}


def _drug_names(title: str) -> list[str]:
    head = _QUALIFIER_RE.sub("", _TITLE_PREFIX_RE.sub("", title).strip(), count=1)
    head = _PRODUCT_WORD_RE.sub(" ", head)
    names = [match.group(1) for match in _PARENS_RE.finditer(head)]
    outside = _PARENS_RE.sub(" ", head)
    names += [token for token in _BRAND_RE.findall(outside) if token not in _NOT_BRANDS]
    if not names:
        names = [outside]
    return _dedupe(normalize_drug_name(name) for name in names)[:8]


def _extracted_names(rows: list[str], already: list[str]) -> list[str]:
    known = set(already)
    names = (_collapse(normalize_drug_name(row)) for row in rows)
    return [name for name in _dedupe(names) if name not in known][:8]


def _collapse(name: str | None) -> str | None:
    """An annex row spanning table columns repeats itself ("jakavi ruxolitinib
    jakavi ruxolitinib"); one copy of each word is the useful part."""
    return " ".join(_dedupe(name.split())) if name else None


def _dedupe(values: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


# --------------------------------------------------------------------------- annex rows

_STOP_LABELS = (
    r"identified\s+in|batch|lot|expiry|expiration|manufactur\w*\s+date|product\s+name|"
    r"declared|available|photograph|stated|strength|presentation|quantity|serial"
)


def _annex_field(text: str, label: str) -> list[str]:
    """Values of a one-line annex table row such as `Product Name HEALMOXY ...`.

    pypdf sometimes splits a two-word label across lines ("Stated \\nmanufacturer"),
    so the label may span whitespace while the value never leaves its line.
    """
    pattern = re.compile(rf"\b{label}\s*:?[ \t]*([^\n]+)", re.I)
    out: list[str] = []
    for match in pattern.finditer(text):
        value = re.split(rf"\s+(?:{_STOP_LABELS})\b", match.group(1), maxsplit=1, flags=re.I)[0]
        value = clean_text(value.strip(" :|-"))
        if value and len(value) > 1:
            out.append(value)
    return _dedupe(out)[:8]


_GENUINE_MFR_RE = re.compile(
    r"genuine\s+manufacturer[,\s]*\(?\s*([A-Z][A-Za-z0-9&.\- ]{2,60}?)\s*\)?[,\s]*"
    r"(?:has|have|also|confirmed|reported)",
)


def _manufacturer(annex: str, page_text: str) -> str | None:
    stated = _annex_field(annex, r"stated\s+manufacturers?")
    if stated:
        return stated[0][:256]
    match = _GENUINE_MFR_RE.search(page_text) or _GENUINE_MFR_RE.search(annex)
    return clean_text(match.group(1))[:256] if match else None


# --------------------------------------------------------------------------- lots

# A leading run of punctuation covers the private-use bullet glyphs ("")
# that pypdf emits for Symbol-font list markers.
_BATCH_ROW_RE = re.compile(
    r"^[^0-9A-Za-z]*(?:batch(?:es)?|lot)\b[ \t]*"
    r"(?:nos?\.?|n[°º]\.?|numbers?|codes?|#)?[ \t]*:?[ \t]*",
    re.I,
)
_OTHER_ROW_RE = re.compile(
    r"^[^0-9A-Za-z]*(?:expiry|expiration|exp\.?|manufactur\w*|product\s+name|declared|"
    r"available|photograph|identified\s+in|stated|strength|presentation|quantity|"
    r"dosage|marketing|page\b|ref\.)",
    re.I,
)
# Names of neighbouring table columns / row labels: everything after one of these
# belongs to another field, not to the batch.
_COLUMN_LABEL_RE = re.compile(
    r"\b(?:expiry|expiration|exp|manufactur\w*|identified|countr\w+|dates?|product|"
    r"strength|quantit\w+|serial|presentation|dosage|declared|available|photograph)\b",
    re.I,
)
_DATE_TOKEN_RE = re.compile(
    r"^(?:\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2}"
    r"|\d{1,2}[/.\-]\d{2,4}|\d{4}[/.\-]\d{1,2})$"
)
_MONTH = r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
# Bare month, and the "28FEB16" / "Oct-12" expiry shapes WHO annexes print.
_MONTH_TOKEN_RE = re.compile(
    rf"^(?:\d{{1,2}}[-\s]?)?(?:{_MONTH})[a-z]*\.?(?:[-\s]?\d{{2,4}})?$", re.I
)
_STRENGTH_TOKEN_RE = re.compile(r"^\d+(?:[.,]\d+)?\s*(?:mg|mcg|ug|g|kg|ml|l|iu|units?|%)$", re.I)
_YMD8_RE = re.compile(r"^(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])$")
_CODE_SHAPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-/.]{2,31}$")
_CODE_STOPWORDS = {"EXP", "LOT", "LOTS", "BATCH", "BATCHES", "NDC", "ALL", "NA", "N0", "NO"}
_LOT_SENTENCE_RE = re.compile(r"\b(?:batch|lot)\b", re.I)
_TABLE_LOOKAHEAD = 3


def _code(token: str) -> str | None:
    """A batch-column token that is really a code: not a date, not a strength."""
    token = token.strip(",;|()[]<>\"'")
    if not token or not _CODE_SHAPE_RE.match(token):
        return None
    if _DATE_TOKEN_RE.match(token) or _MONTH_TOKEN_RE.match(token) or _STRENGTH_TOKEN_RE.match(token):
        return None
    code = normalize_lot(token)
    if code is None or code in _CODE_STOPWORDS or not any(c.isdigit() for c in code):
        return None
    # Bare digits are only a batch because of the column they sit in, so keep the
    # shapes real batches use and drop years, page numbers and packed dates.
    if code.isdigit() and (len(code) < 5 or len(code) > 14 or _YMD8_RE.match(code)):
        return None
    return code


def _codes_in(text: str, *, first_only: bool = False) -> list[str]:
    codes = [code for code in (_code(token) for token in text.split()) if code]
    return codes[:1] if first_only else codes


def _is_date_token(token: str) -> bool:
    token = token.strip(",;|()[]")
    return bool(_DATE_TOKEN_RE.match(token) or _MONTH_TOKEN_RE.match(token))


# A wide table whose batch column is not its first: `Product Batch Expiry`.
_TRAILING_DATE_HEADER_RE = re.compile(
    r"\b(?:batch(?:es)?|lot)\b(?:\s*(?:nos?\.?|numbers?|codes?))?\s+"
    r"(?:expiry|expiration|exp)\b\.?(?:\s*dates?)?\s*$",
    re.I,
)


def _trailing_code(line: str) -> str | None:
    """`ACCUPAQUE 300 mg USB 10x100 ml 17333581 07-Nov-28` -> 17333581.

    The row must actually end in a date; that is what pins down which token is
    the batch when the product column has a variable number of words.
    """
    tokens = line.split()
    end = len(tokens)
    while end and _is_date_token(tokens[end - 1]):
        end -= 1
    if end in (0, len(tokens)):
        return None
    return _code(tokens[end - 1])


def _batch_cell(tail: str) -> str:
    """The part of a row that still belongs to the batch column.

    `Batch Number: UH301AA; Expiry Date: 28FEB16` must not donate its expiry.
    """
    cell = re.split(r"[;|]", tail, maxsplit=1)[0]
    label = _COLUMN_LABEL_RE.search(cell)
    return cell[: label.start()] if label else cell


def extract_batches_from_tables(text: str) -> list[tuple[str, str]]:
    """Batch codes from annex tables, as (code, source line).

    pypdf flattens a table row to one line, so a row whose label starts the line
    hands over its whole batch cell (`Batch  023011 023011 H02605`), while a bare
    header takes the column underneath it instead. When that header names other
    columns too (`Lot number Expiry Date Identified In`) the rows below are
    multi-column, so only their leading cell is a batch. Anchoring on the line
    start is what keeps a bare number like `023011` from being mined out of
    prose, quantities or dates.
    """
    lines = text.split("\n")
    found: list[tuple[str, str]] = []
    for position, line in enumerate(lines):
        match = _BATCH_ROW_RE.match(line)
        if not match:
            if _TRAILING_DATE_HEADER_RE.search(line):
                found += _trailing_date_rows(lines[position + 1 :])
            continue
        tail = line[match.end() :]
        codes = _codes_in(_batch_cell(tail))
        if codes:
            found += [(code, line.strip()) for code in codes]
            continue
        multi_column = bool(_COLUMN_LABEL_RE.search(tail))
        for following in lines[position + 1 : position + 1 + _TABLE_LOOKAHEAD]:
            if not following.strip():
                continue
            if _OTHER_ROW_RE.match(following) or _BATCH_ROW_RE.match(following):
                break
            column = _codes_in(_batch_cell(following), first_only=multi_column)
            if not column:
                break
            found += [(code, following.strip()) for code in column]
    return found


def _trailing_date_rows(lines: list[str]) -> list[tuple[str, str]]:
    """Rows under a `... Batch Expiry` header, until one stops looking like a row."""
    out: list[tuple[str, str]] = []
    for line in lines:
        if not line.strip():
            continue
        code = _trailing_code(line)
        if code is None:
            break
        out.append((code, line.strip()))
    return out


def _drop_fragments(table_codes: set[str], lots: list[str]) -> list[str]:
    """pypdf sometimes splits a code mid-token ("UH301AA" -> "UH 301AA"), leaving
    a tail that is a strict suffix of the real code. Prefixes are NOT dropped:
    H02605 and H026051 are two genuine HEALMOXY batches."""
    return [
        lot
        for lot in lots
        if not (lot in table_codes and any(other != lot and other.endswith(lot) for other in lots))
    ]


def _lots(page_text: str, annex_text: str) -> tuple[list[str], str | None]:
    codes: list[str] = []
    snippets: list[str] = []
    from_tables: set[str] = set()
    for text in (page_text, annex_text):
        if not text:
            continue
        codes += extract_batches_from_prose(text)
        for code, line in extract_batches_from_tables(text):
            codes.append(code)
            from_tables.add(code)
            snippets.append(line)
    lots = _drop_fragments(from_tables, _dedupe(codes))
    if not lots:
        return [], None
    for text in (page_text, annex_text):
        for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
            if _LOT_SENTENCE_RE.search(sentence) and any(code in sentence.upper() for code in lots):
                snippets.append(sentence.strip())
    return lots, truncate_on_sentence("\n".join(_dedupe(snippets)), LOT_TEXT_CAP) or None


# --------------------------------------------------------------------------- raw artifacts

_BOILERPLATE_RE = re.compile(
    r"WHO Global Surveillance and Monitoring System"
    r"|Please visit:\s*https?://"
    r"|^\s*Ref\.\s"
    r"|AVENUE APPIA|GENEVA 27|TEL CENTRAL|FAX CENTRAL|WWW\.WHO\.INT"
    r"|^\s*Page \d+ of \d+\s*$",
    re.I | re.M,
)


def _strip_boilerplate(text: str) -> str:
    """Drop the letterhead repeated on every annex page: it is noise for BM25 and
    its Geneva address otherwise lands in `countries`."""
    kept = [line for line in (text or "").split("\n") if not _BOILERPLATE_RE.search(line)]
    return "\n".join(kept).strip()


def _items(listing_path: Path, limit: int | None) -> list[dict[str, Any]]:
    try:
        payload = json.loads(listing_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = [item for item in payload.get("value", []) if item.get("Id")]
    items.sort(key=lambda item: item.get("PublicationDateAndTime") or "", reverse=True)
    return items[:limit] if limit else items


def _page_url(item: dict[str, Any]) -> str:
    path = str(item.get("ItemDefaultUrl") or "")
    return PAGE_BASE + (path if path.startswith("/") else "/" + path)


def _annex_urls(html: str) -> list[str]:
    """Annex PDFs linked from the article, keyed on the anchor having visible text:
    WHO occasionally leaves an empty anchor pointing at the *previous* alert's
    annex (seen on N°3/2026), and following it would import another drug's batches.
    """
    article = _ARTICLE_RE.search(html or "")
    if not article:
        return []
    out: list[str] = []
    for href, inner in _ANCHOR_RE.findall(article.group(1)):
        if not _PDF_HREF_RE.match(href) or not html_to_text(inner).strip():
            continue
        out.append(href.split("?", 1)[0])
    return _dedupe(out)


def _pdf_name(url: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", url.rsplit("/", 1)[-1])
    return stem if stem.lower().endswith(".pdf") else stem + ".pdf"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _pdf_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        reader = pypdf.PdfReader(str(path))
    except Exception:  # noqa: BLE001 - an unreadable annex must not sink the alert
        return ""
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - scanned pages have no text layer
            pages.append("")
    return "\n".join(pages).strip()


async def _too_big(ctx: SeedContext, url: str) -> bool:
    try:
        response = await ctx.http.head(url)
        return int(response.headers.get("content-length", 0)) > MAX_PDF_BYTES
    except Exception:  # noqa: BLE001 - HEAD is only an early-out; the size is rechecked
        return False
