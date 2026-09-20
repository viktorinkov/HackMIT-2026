"""Pure key helpers: raw regulator prose -> the node keys in `graph.models`.

Everything here is offline, total and deterministic. Garbage in returns `None`,
never an exception, because the strings come from OCR, PDF tables and regulator
titles rather than from a schema.

The two interesting ones are `drug_key` and `company_key`. Both exist because the
corpus has no normalizer for them:

- `Accord Healthcare Inc.`, `Accord Healthcare, Inc.,`, `Accord Healthcare
  Limited` and `Accord Healthcare Limited - Losartan Potassium 50mg Film-coated
  Tablets` are one firm, and a node per spelling is a graph nobody can read.
- A NAFDAC `manufacturer` can be a whole sentence. Rather than label a node with
  a sentence, `company_key` refuses to mint one at all.
"""

from __future__ import annotations

import re

from backend.knowledge import normalize

__all__ = [
    "SALT_TOKENS",
    "LEGAL_SUFFIXES",
    "slug",
    "drug_key",
    "company_key",
    "lot_key",
    "product_key",
    "imprint_key",
    "country_key",
    "regulator_key",
    "web_key",
    "topic_of",
    "cluster_key",
]

# Trailing salt forms. `levothyroxine sodium` and `levothyroxine` are the same
# medicine to a person holding the bottle; RxNav rewrites one into the other
# between scans, so the key has to survive that.
SALT_TOKENS: frozenset[str] = frozenset(
    {
        "sodium",
        "potassium",
        "calcium",
        "hydrochloride",
        "hcl",
        "besylate",
        "mesylate",
        "maleate",
        "succinate",
        "tartrate",
        "trihydrate",
        "monohydrate",
    }
)

# `drug_names_extracted` is a title fragment on non-FDA records: "and losartan
# potassium", "batches of healmoxy".
_LEADING_STOPWORDS: frozenset[str] = frozenset(
    {"and", "or", "the", "a", "an", "of", "batch", "batches", "lot", "lots", "with", "in", "for"}
)

# Names that identify nothing. A node for them is a hub joining unrelated scans.
_DRUG_DENYLIST: frozenset[str] = frozenset(
    {
        "various products",
        "various product",
        "various",
        "products",
        "product",
        "unknown",
        "drug",
        "drugs",
        "medicine",
        "medicines",
        "medication",
        "medications",
    }
)

LEGAL_SUFFIXES: frozenset[str] = frozenset(
    {
        "inc",
        "llc",
        "ltd",
        "limited",
        "corp",
        "corporation",
        "co",
        "company",
        "plc",
        "gmbh",
        "pvt",
        "pte",
        "sa",
        "nv",
        "bv",
        "ag",
        "usa",
    }
)

# Everything from the first of these onwards is an aside, a product description
# or a second firm, never part of the name.
_COMPANY_CUTS: tuple[str, ...] = (",", ";", "(", " - ", " – ", " with ", " dba ", " and all ")

MAX_COMPANY_TOKENS = 4
MIN_COMPANY_CHARS = 3

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_PUNCT_STRIP = ".,;:'\"()[]{}/\\&"


def slug(value: str | None, *, max_len: int = 64) -> str | None:
    """`Health Canada` -> `health-canada`. The key half of an id, never a label."""
    text = normalize.clean_text(value)
    if not text:
        return None
    out = _SLUG_RE.sub("-", text.casefold()).strip("-")
    return out[:max_len].strip("-") or None


# --------------------------------------------------------------------------- drugs


def drug_key(value: str | None) -> str | None:
    """A medicine key that survives salt drift and regulator title fragments."""
    name = normalize.normalize_drug_name(value)
    if not name:
        return None
    tokens = [token.strip(_PUNCT_STRIP) for token in name.split()]
    tokens = [token for token in tokens if token]
    # Leading stopwords first: "batches of healmoxy" -> "healmoxy".
    while tokens and tokens[0] in _LEADING_STOPWORDS:
        tokens.pop(0)
    # Then trailing salts, but only while a real name is left behind. That is
    # what keeps `sodium chloride` intact while collapsing `losartan potassium`.
    while len(tokens) > 1 and tokens[-1] in SALT_TOKENS:
        if not any(len(token) >= 4 for token in tokens[:-1]):
            break
        tokens.pop()
    key = " ".join(tokens).strip()
    if not key or key in _DRUG_DENYLIST or len(key) < 3:
        return None
    return key


# --------------------------------------------------------------------------- firms


def company_key(value: str | None) -> str | None:
    """A manufacturer key, or `None` when the string is prose rather than a name."""
    text = normalize.clean_text(value)
    if not text:
        return None
    text = text.casefold()
    cut = len(text)
    for marker in _COMPANY_CUTS:
        found = text.find(marker)
        if found > 0:
            cut = min(cut, found)
    text = text[:cut]
    tokens = [token.strip(_PUNCT_STRIP) for token in text.split()]
    tokens = [token for token in tokens if token]
    # Truncate at the first legal suffix rather than only stripping trailing
    # ones: "accord healthcare inc. usa" must not keep the "usa".
    for index, token in enumerate(tokens):
        if index >= 1 and token in LEGAL_SUFFIXES:
            tokens = tokens[:index]
            break
    if not tokens or len(tokens) > MAX_COMPANY_TOKENS:
        return None
    key = " ".join(tokens).strip()
    if len(key) < MIN_COMPANY_CHARS:
        return None
    return key


# --------------------------------------------------------------------------- codes


def lot_key(value: str | None) -> str | None:
    return normalize.normalize_lot(value)


def product_key(value: str | None) -> str | None:
    """The ndc9, which is the product line a bottle belongs to."""
    forms = normalize.normalize_ndc(value)
    return forms.ndc9 if forms else None


def imprint_key(value: str | None) -> str | None:
    forms = normalize.normalize_imprint(value)
    return forms.norm if forms else None


def web_key(url_or_page_id: str | None) -> str | None:
    """A stored `page_id` passes through; a URL is hashed the way the seeder does."""
    text = normalize.clean_text(url_or_page_id)
    if not text:
        return None
    if re.fullmatch(r"[0-9a-f]{32}", text):
        return text
    return normalize.url_hash(text)


# --------------------------------------------------------------------------- context


def country_key(value: str | None) -> str | None:
    """Canonicalise through the shared country list before slugging."""
    text = normalize.clean_text(value)
    if not text:
        return None
    found = normalize.extract_countries(text)
    return slug(found[0]) if found else slug(text)


def country_label(value: str | None) -> str | None:
    text = normalize.clean_text(value)
    if not text:
        return None
    found = normalize.extract_countries(text)
    return found[0] if found else text


_ORG_SLUGS = {
    "fda": "fda",
    "us fda": "fda",
    "openfda": "fda",
    "who": "who",
    "world health organization": "who",
    "nafdac": "nafdac",
    "mhra": "mhra",
    "health canada": "health-canada",
    "hc": "health-canada",
}


def regulator_key(value: str | None) -> str | None:
    text = normalize.clean_text(value)
    if not text:
        return None
    return _ORG_SLUGS.get(text.casefold()) or slug(text)


# Alert doc types name their own topic; a recall's reason does not, so a small
# keyword rule buckets it. `other` is deliberately reachable.
_TOPIC_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"subpotent|below\s+specification|low\s+potency", re.I), "subpotent", "Subpotent"),
    (re.compile(r"superpotent|above\s+specification", re.I), "superpotent", "Superpotent"),
    (re.compile(r"steril|endotoxin|microbial", re.I), "sterility", "Sterility"),
    (
        re.compile(r"nitrosamin|n-nitroso|impurit", re.I),
        "impurity-nitrosamine",
        "Impurity",
    ),
    (re.compile(r"contaminat|foreign\s+(?:matter|substance)", re.I), "contamination", "Contamination"),
    (re.compile(r"mislabel|label\s*mix|wrong\s+label|mix-?up", re.I), "labeling-mixup", "Labelling mix-up"),
    (re.compile(r"cgmp|good\s+manufacturing", re.I), "cgmp", "Manufacturing practice"),
    (re.compile(r"dissolution", re.I), "dissolution", "Dissolution"),
)
_TOPIC_BY_DOC_TYPE = {
    "falsified_alert": ("falsified", "Falsified product"),
    "substandard_alert": ("substandard", "Substandard product"),
    "safety_alert": ("safety-alert", "Safety alert"),
}


def topic_of(doc_type: str | None, text: str | None) -> tuple[str, str] | None:
    """`(key, human label)` for the reason a record exists, or `None`."""
    kind = (normalize.clean_text(doc_type) or "").casefold()
    if kind in _TOPIC_BY_DOC_TYPE:
        return _TOPIC_BY_DOC_TYPE[kind]
    body = normalize.clean_text(text)
    if not body:
        return None
    for pattern, key, label in _TOPIC_RULES:
        if pattern.search(body):
            return key, label
    return None


def cluster_key(parent_id: str, relation: str) -> str:
    """`cluster:reg:fda|records` — the parent id is part of the key on purpose."""
    return f"{parent_id}|{relation}"
