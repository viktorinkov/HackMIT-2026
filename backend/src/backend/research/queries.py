"""Live-web search queries built from one scan.

Only whitelisted label fields ever reach a query string. An Rx number, a
pharmacy name or free-text directions must never be sent to a third-party
search API, so this module reads `norm` and a fixed list of `bottle` keys and
nothing else (audit_redteam §5.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.knowledge import normalize

# A term longer than this is OCR noise, not a drug or a manufacturer.
MAX_TERM_CHARS = 60

# Social, video and forum domains: a Facebook post about a recall is never the
# evidence we want, and a scraped one costs the same credit as an FDA notice.
EXCLUDED_DOMAINS: tuple[str, ...] = (
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "reddit.com",
    "pinterest.com",
    "linkedin.com",
)
EXCLUSIONS = " ".join(f"-site:{domain}" for domain in EXCLUDED_DOMAINS)


@dataclass(frozen=True)
class WebQuery:
    text: str
    key: str
    tbs: str | None
    purpose: str

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "key": self.key, "tbs": self.tbs, "purpose": self.purpose}


def build_web_queries(scan_doc: dict[str, Any], *, max_queries: int) -> list[WebQuery]:
    """Priority-ordered web queries for one scan (design C §4.2).

    Without a drug name and without a lot there is nothing specific enough to
    search for, and a generic query would spend credits on noise.
    """
    if max_queries <= 0:
        return []
    label = _label(scan_doc)
    drug = label["generic"] or label["brand"]
    lot = label["lot"]
    if not drug and not lot:
        return []

    candidates: list[WebQuery | None] = []
    if lot:
        tail = f" {drug}" if drug else ""
        candidates.append(
            _query(f'"{lot}"{tail} recall OR batch', tbs=None, purpose="lot_recall")
        )
    if drug:
        maker = f" {label['manufacturer']}" if label["manufacturer"] else ""
        candidates.append(
            _query(
                f"{drug}{maker} counterfeit OR falsified OR substandard",
                tbs="qdr:y",
                purpose="counterfeit_reports",
            )
        )
        name = label["brand"] or drug
        strength = f" {label['strength']}" if label["strength"] else ""
        country = f" {label['country']}" if label["country"] else ""
        candidates.append(
            _query(f"{name}{strength} recall{country}", tbs="qdr:m", purpose="product_recall")
        )

    out: list[WebQuery] = []
    seen: set[str] = set()
    for query in candidates:
        if query is None or query.key in seen:
            continue
        seen.add(query.key)
        out.append(query)
        if len(out) >= max_queries:
            break
    return out


def _label(scan_doc: dict[str, Any]) -> dict[str, str | None]:
    """The only label fields a web query is allowed to carry."""
    norm = scan_doc.get("norm") or {}
    bottle = scan_doc.get("bottle") or {}
    return {
        "generic": _term(norm.get("generic_name") or bottle.get("generic_name")),
        "brand": _term(norm.get("brand_name") or bottle.get("brand_name")),
        "lot": normalize.normalize_lot(norm.get("lot") or bottle.get("lot_number")),
        "manufacturer": _term(norm.get("manufacturer") or bottle.get("manufacturer")),
        "strength": _term(norm.get("strength") or bottle.get("strength")),
        "country": _term(scan_doc.get("country")),
    }


def _term(value: object) -> str | None:
    text = normalize.clean_text(value)
    if not text:
        return None
    # Quotes and boolean operators in OCR output would rewrite the query.
    text = text.replace('"', " ").replace("(", " ").replace(")", " ")
    text = " ".join(text.split())[:MAX_TERM_CHARS].strip()
    return text or None


def _query(text: str, *, tbs: str | None, purpose: str) -> WebQuery | None:
    """`key` is computed before the exclusions so cache keys stay readable.

    The `-site:` operators are a fetch-time filter, not part of the question, so
    adding one must not invalidate every page cached under the old key.
    """
    cleaned = normalize.clean_text(text)
    if not cleaned:
        return None
    return WebQuery(
        text=f"{cleaned} {EXCLUSIONS}",
        key=normalize.query_key(cleaned),
        tbs=tbs,
        purpose=purpose,
    )
