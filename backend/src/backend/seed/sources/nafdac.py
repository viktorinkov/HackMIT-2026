"""NAFDAC (Nigeria) public alerts -> fields.REGULATORY_INDEX.

WordPress REST API, category 29 ("Public Alerts"): ``content.rendered`` already
carries the full alert body, so there is no PDF or Firecrawl fetch involved.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.knowledge import normalize as norm
from backend.knowledge.fields import REGULATORY_INDEX, Reg
from backend.seed.base import SeedContext, Source
from backend.seed.http import FetchError, get_with_retry

_API = "https://nafdac.gov.ng/wp-json/wp/v2/posts"
_CATEGORY = 29  # "Public Alerts"
_PER_PAGE = 100
_FIELDS = "id,date,date_gmt,modified,modified_gmt,link,title,content,excerpt"

_BODY_CAP = 30_000
_SEMANTIC_CAP = 2000
_SUMMARY_CAP = 400
_LOT_TEXT_CAP = 500

# The tail of `content.rendered` is a fixed sign-off + a feedback-widget SVG
# blob (design_B §1.6). `html_to_text` already drops <style>/<script>, so the
# only junk left in the extracted text is the sign-off and the widget labels.
# The sign-off's leader is U+2026 HORIZONTAL ELLIPSIS repeated, not ASCII dots.
_TAIL_RE = re.compile(r"NAFDAC[….\s]{2,}Customer-focused.*|Was this helpful\?.*", re.I | re.S)

_ALERT_NUM_RE = re.compile(r"public\s+alert\s+no[.:]?\s*(\d+/\d{4})", re.I)
_TITLE_PREFIX_RE = re.compile(r"^public\s+alert\s+no[.:]?\s*\d+/\d{4}\s*[-–—:]*\s*", re.I)
_TITLE_LEAD_RE = re.compile(r"^alert\s+on\s+(?:the\s+)?", re.I)
_TITLE_TRIGGER_RE = re.compile(
    r"(?:substandard\s+and\s+falsified|substandard|falsified|"
    r"confirmed\s+counterfeits?(?:\s+of)?|"
    r"counterfeits?(?:\s+of|\s+brands?\s+of)?(?:\s+products?\s+mimicking)?|"
    r"recalls?(?:\s+of|\s+specific\s+batches\s+of)?|unregistered|adulterated(?:\s+and\s+substandard)?)\s+",
    re.I,
)
_TITLE_STOP_RE = re.compile(
    r"\s+(?:in|by|due\s+to|found|recalled|with(?:\s+fake)?|as\s+endorsed|over)\b.*|\(.*",
    re.I,
)
_MANUFACTURER_RE = re.compile(r"(?:purportedly\s+)?manufactured\s+(?:by|for)\s+([^.\n]+)", re.I)


def _meta_path(raw_dir: Path) -> Path:
    return raw_dir / "_meta.json"


class NafdacSource(Source):
    name = "nafdac"
    index = REGULATORY_INDEX
    description = "NAFDAC (Nigeria) public alerts: falsified, substandard, recall, watchlist"
    semantic = True

    async def download(self, ctx: SeedContext) -> None:
        raw_dir = ctx.raw_dir(self.name)
        meta_path = _meta_path(raw_dir)
        total_pages: int | None = None
        if meta_path.exists() and not ctx.refresh_cache:
            try:
                total_pages = int(json.loads(meta_path.read_text(encoding="utf-8"))["total_pages"])
            except (json.JSONDecodeError, OSError, KeyError, ValueError):
                total_pages = None

        page = 1
        while total_pages is None or page <= total_pages:
            if ctx.limit is not None and (page - 1) * _PER_PAGE >= ctx.limit:
                return
            dest = raw_dir / f"page-{page:03d}.json"
            if dest.exists() and dest.stat().st_size > 0 and not ctx.refresh_cache:
                page += 1
                continue
            try:
                response = await get_with_retry(
                    ctx.http,
                    _API,
                    params={
                        "categories": _CATEGORY,
                        "per_page": _PER_PAGE,
                        "page": page,
                        "_fields": _FIELDS,
                    },
                )
            except FetchError:
                return
            dest.write_text(response.text, encoding="utf-8")
            if total_pages is None:
                total_pages = int(response.headers.get("x-wp-totalpages", "1") or "1")
                meta_path.write_text(json.dumps({"total_pages": total_pages}), encoding="utf-8")
            page += 1

    def parse(self, ctx: SeedContext) -> Iterator[dict[str, Any]]:
        raw_dir = ctx.raw_dir(self.name)
        posts: list[dict[str, Any]] = []
        for path in sorted(raw_dir.glob("page-*.json")):
            try:
                posts.extend(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        posts.sort(key=lambda post: post.get("date_gmt") or "", reverse=True)

        count = 0
        for post in posts:
            doc = to_doc(post, now=ctx.now)
            if doc is None:
                continue
            yield doc
            count += 1
            if ctx.limit is not None and count >= ctx.limit:
                return


def _lead_paragraph(body: str) -> str:
    for block in body.split("\n\n"):
        block = block.strip()
        if block:
            return block
    return body.strip()


def _lot_text(body: str) -> str | None:
    blocks = [b.strip() for b in body.split("\n\n") if b.strip()]
    hits: list[str] = []
    for i, block in enumerate(blocks):
        if len(block) < 60 and re.search(r"\bbatch|\blot\b", block, re.I):
            nxt = blocks[i + 1] if i + 1 < len(blocks) else ""
            hits.append(f"{block}: {nxt}" if nxt else block)
    if not hits:
        for block in blocks:
            if re.search(r"\bbatch|\blot\b", block, re.I):
                hits.append(block)
                break
    if not hits:
        return None
    return norm.truncate_on_sentence(" | ".join(hits), _LOT_TEXT_CAP)


def _drug_names_from_title(title: str) -> list[str]:
    stripped = _TITLE_PREFIX_RE.sub("", title)
    stripped = _TITLE_LEAD_RE.sub("", stripped)
    match = _TITLE_TRIGGER_RE.search(stripped)
    if not match:
        # No falsified/substandard/counterfeit/recall trigger word: titles like
        # "...Places Products...on Watchlist" don't name a specific product, so
        # guessing from arbitrary leading words produces noise, not a name.
        return []
    candidate = stripped[match.end() :]
    candidate = _TITLE_STOP_RE.sub("", candidate).strip(" .-–—")
    return norm.extract_drug_names(candidate) if candidate else []


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


def to_doc(post: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any] | None:
    """A NAFDAC WP-REST post -> a peel-regulatory doc, or None to skip it."""
    post_id = post.get("id")
    if not post_id:
        return None
    title = norm.clean_text(html_lib.unescape(post.get("title", {}).get("rendered") or ""))
    if not title:
        return None
    link = norm.clean_text(post.get("link"))
    if not link:
        return None

    content_html = post.get("content", {}).get("rendered") or ""
    full_text = norm.html_to_text(content_html)
    body = _TAIL_RE.split(full_text, maxsplit=1)[0].strip()[:_BODY_CAP]
    if not body:
        return None

    published = norm.parse_date(post.get("date_gmt") or post.get("date"))
    updated = norm.parse_date(post.get("modified_gmt") or post.get("modified"))
    recency = published or updated
    if recency is None:
        return None  # recency_date is non-null; nothing to anchor decay on

    # Title only, not body: every post's boilerplate "Reporting of Adverse
    # Events" footer says "...sale of substandard and falsified medicines...",
    # which would otherwise misclassify every single post as falsified_alert.
    doc_type = norm.classify_doc_type(title, default="safety_alert")
    # `doc_type` alone reproduces falsified/substandard/recall; pass the title
    # too so a "...on Watchlist..." post reaches severity_for's watchlist->moderate rule.
    severity, severity_rank = norm.severity_for("NAFDAC", title, doc_type)

    alert_match = _ALERT_NUM_RE.search(title)
    manufacturer_match = _MANUFACTURER_RE.search(body)
    countries = _dedupe(["Nigeria", *norm.extract_countries(body)])
    lead = _lead_paragraph(body)
    drug_names_extracted = _drug_names_from_title(title)

    summary = norm.truncate_on_sentence(lead, _SUMMARY_CAP)
    semantic_source = f"{title}. {summary} {' '.join(drug_names_extracted)}".strip()
    body_semantic = norm.truncate_on_sentence(semantic_source, _SEMANTIC_CAP)

    raw = {key: value for key, value in post.items() if key != "content"}

    doc = {
        "_id": f"nafdac-{post_id}",
        Reg.RECORD_ID: f"nafdac-{post_id}",
        Reg.SOURCE: "nafdac_alerts",
        Reg.SOURCE_ORG: "NAFDAC",
        Reg.DOC_TYPE: doc_type,
        Reg.COUNTRY_OF_AUTHORITY: "Nigeria",
        Reg.COUNTRIES: countries,
        Reg.TITLE: title,
        Reg.SUMMARY: summary,
        Reg.BODY: body,
        Reg.BODY_SEMANTIC: body_semantic,
        Reg.HAS_SEMANTIC: True,
        Reg.DRUG_NAMES_EXTRACTED: drug_names_extracted,
        Reg.MANUFACTURER: norm.clean_text(manufacturer_match.group(1)) if manufacturer_match else None,
        Reg.LOT_NUMBERS: norm.extract_batches_from_prose(body),
        Reg.LOT_TEXT: _lot_text(body),
        Reg.ALERT_NUMBER: alert_match.group(1) if alert_match else None,
        Reg.DOSAGE_FORM: norm.normalize_dosage_form(title),
        Reg.SEVERITY: severity,
        Reg.SEVERITY_RANK: severity_rank,
        Reg.PUBLISHED_AT: norm.to_iso(published),
        Reg.RECENCY_DATE: norm.to_iso(recency),
        Reg.DATE_PRECISION: "published" if published else "updated",
        Reg.INDEXED_AT: norm.to_iso(now) if now is not None else None,
        Reg.URL: link,
        Reg.ATTRIBUTION: "NAFDAC Nigeria",
        Reg.SOURCE_LICENSE: "No published licence — summarise and link",
        Reg.SOURCE_TERMS_URL: "https://nafdac.gov.ng/",
        Reg.RAW: raw,
    }
    return _clean(doc)
