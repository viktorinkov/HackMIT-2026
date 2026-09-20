"""Per-regulator body and attribution policy for the `rec:` note panel.

design-data-api.md §6: a record's full `body` is never returned to the
client — only a short, per-source-capped `summary` — and every source line
carries an attribution string naming the licence (or the lack of one), so the
page can show that next to the link instead of implying every regulator's
text is equally free to reuse.

One rule, tested: **`body` is never the record's raw `body` field.** Every
policy below reads from `summary` (already short) or, for FDA, `reason`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.knowledge import normalize
from backend.knowledge.fields import Reg

# Per-org caps on the shown summary. Anything not listed falls back to
# `DEFAULT_MAX_BODY_CHARS` — generous, because MHRA/Health Canada summaries
# are usually already short and their licence is permissive.
MAX_BODY_CHARS: dict[str, int] = {
    "WHO": 360,
    "NAFDAC": 280,
}
DEFAULT_MAX_BODY_CHARS = 500

ATTRIBUTION: dict[str, str] = {
    "WHO": "World Health Organization, CC BY-NC-SA 3.0 IGO",
    "NAFDAC": "Summary with link; no published licence",
    "FDA": "openFDA (CC0) — see openFDA terms and disclaimer",
    "MHRA": "Contains public sector information licensed under the Open Government Licence v3.0",
    "Health Canada": "Open Government Licence – Canada",
}
DEFAULT_ATTRIBUTION = "Source: regulator record; see the source link for its own terms."

LINK_LABEL: dict[str, str] = {
    # Every FDA record's `url` is an `api.fda.gov` query, not a readable page.
    "FDA": "openFDA record (JSON)",
}
DEFAULT_LINK_LABEL = "Source record"


@dataclass(frozen=True)
class LicensedBody:
    body: str | None
    attribution: str
    link_label: str


def attribution_for(source_org: str | None) -> str:
    return ATTRIBUTION.get(source_org or "", DEFAULT_ATTRIBUTION)


def link_label_for(source_org: str | None) -> str:
    return LINK_LABEL.get(source_org or "", DEFAULT_LINK_LABEL)


def _capped(text: str | None, limit: int) -> str | None:
    cleaned = normalize.clean_text(text)
    if not cleaned:
        return None
    return normalize.truncate_on_sentence(cleaned, limit)


def licensed_body(source_org: str | None, record: dict[str, Any]) -> LicensedBody:
    """The body text a `rec:` node's detail may show for this record.

    Never reads `record[Reg.BODY]`. FDA's `summary` field is frequently
    empty, so FDA alone falls back to `reason` (the recall's own stated
    cause) — still capped, never the regulator's full text.
    """
    org = source_org or record.get(Reg.SOURCE_ORG) or ""
    limit = MAX_BODY_CHARS.get(org, DEFAULT_MAX_BODY_CHARS)
    body = _capped(record.get(Reg.SUMMARY), limit)
    if not body and org == "FDA":
        body = _capped(record.get(Reg.REASON), limit)
    return LicensedBody(body=body, attribution=attribution_for(org), link_label=link_label_for(org))
