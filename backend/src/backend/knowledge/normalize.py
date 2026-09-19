"""Shared normalizers for Peel: seed adapters, the search builder and the scan
pipeline all call these so that a value written at index time and a value read
off a photo at query time are produced by the same code.

Every function is pure, offline and total: garbage in returns ``None`` or an
empty container, never an exception.
"""

from __future__ import annotations

import calendar
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dateutil import parser as _dateutil

from backend.knowledge.fields import SEVERITY_RANKS

MAX_LOTS = 500
MIN_YEAR = 1990
MAX_YEAR = 2100

_NULLISH = {"", "n/a", "na", "none", "null", "nil", "--", "-", "unknown", "not applicable"}
_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]")


def clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = _WS_RE.sub(" ", str(value)).strip()
    return None if text.casefold() in _NULLISH else text


def _squash(text: str) -> str:
    """NFKC, unify dashes and quotes, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans({"–": "-", "—": "-", "−": "-", "’": "'", "‘": "'"}))
    return _WS_RE.sub(" ", text).strip()


# --------------------------------------------------------------------------- lots


@dataclass(frozen=True)
class ExtractedCodes:
    lot_numbers: list[str]
    covers_all_lots: bool
    ndc_raw: list[str]


_LOT_PREFIX_RE = re.compile(
    r"^[^A-Z0-9]*(?:LOTS?|BATCH(?:ES)?|B/N|BN|NOS?|NUMBERS?|CODES?)(?![A-Z0-9])[^A-Z0-9]*"
)
_YYYYMMDD_RE = re.compile(r"(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])")
_CODE_STOPWORDS = {"EXP", "LOT", "LOTS", "BATCH", "NDC", "UPC", "ALL", "NA"}
_M = r"JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC"
_MF = r"JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER"
# "90-count", "12CTBOTTLE", "1000TABLETS", "500MG", "10ML" — pack sizes and
# strengths, never lot numbers.
# The digit run is capped at 4: a pack size is small, while a date-coded lot that
# happens to end in a unit is long (`070717ML` and `010518G` are real lots).
_PACK_UNIT_RE = re.compile(
    r"\d{1,4}(?:MG|MCG|ML|KG|IU"
    r"|COUNT|CT|TABLETS?|TABS?|CAPSULES?|CAPS?|BOTTLES?|VIALS?|UNITS?|PACKS?|PK|EACH|EA)+"
)
# Bare `G` only in prose; it is far too common a lot suffix for extract_lots.
_STRENGTH_UNIT_RE = re.compile(r"\d{1,4}G")
# ddMMMyy / ddMMMyyyy / MMMyyyy, tested against the [^A-Z0-9]-stripped token.
_MONTH_DATE_RE = re.compile(rf"\d{{1,2}}(?:{_M})[A-Z]*\d{{0,4}}|(?:{_M})[A-Z]*(?:19|20)\d{{2}}")


def normalize_lot(value: str | None) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    text = _squash(text).upper()
    while True:
        stripped = _LOT_PREFIX_RE.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    cleaned = _NON_ALNUM_RE.sub("", text)
    return cleaned if 3 <= len(cleaned) <= 32 else None


def _ok_code(token: str, *, dateish: bool = False) -> str | None:
    """Design B §1.1b `_ok()`: a usable lot/batch code or nothing.

    `dateish` is set once an explicit LOT label has been seen — a labelled
    `Lot# 20240524` is a real lot even though it reads as a date.
    """
    norm = normalize_lot(token)
    if norm is None or norm in _CODE_STOPWORDS:
        return None
    if not any(c.isdigit() for c in norm):
        return None
    if _PACK_UNIT_RE.fullmatch(norm):
        return None
    if norm.isdigit() and (len(norm) < 5 or (not dateish and _YYYYMMDD_RE.fullmatch(norm))):
        return None
    return norm


def _ok_batch(token: str) -> str | None:
    """Stricter filter for prose: regulators write batches next to expiry dates
    and strengths, so date and unit shapes must not survive."""
    norm = _ok_code(token)
    if norm is None or _MONTH_DATE_RE.fullmatch(norm) or _STRENGTH_UNIT_RE.fullmatch(norm):
        return None
    return norm

# One alternation, scanned left to right: the longest/leftmost date shape wins so
# that `t12-07-2016@97` is examined as `12-07-2016` (and then spared by the
# boundary guard) instead of being chopped at `07-2016`.
_DATE_RE = re.compile(
    "|".join(
        (
            r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}",
            r"\d{4}[/\-]\d{1,2}[/\-]\d{1,2}",
            rf"\d{{1,2}}[\s\-]?(?:{_M})[A-Z]*[\s\-,]?\s?(?:\d{{4}}|\d{{2}})(?![0-9])",
            rf"(?:{_MF})\s+\d{{1,2}},?\s*\d{{4}}",
            rf"(?:{_MF}|{_M})\.?\s+\d{{4}}",
            r"(?:0?[1-9]|1[0-2])[/\-]\d{2}(?:\d{2})?",
        )
    ),
    re.I,
)
_NDC3_RE = re.compile(r"(?<![-\w])\d{4,5}-\d{3,4}-\d{1,2}(?![-\w])")
_NDC_LABELLED_RE = re.compile(r"(?<![-\w])NDC\s*:?\s*(\d{4,5}-\d{3,4})(?![-\w])", re.I)
_UPC_RE = re.compile(r"\(\d{2}\)\d{10,20}")

_LOT_LABEL = (
    r"lot\s*(?:codes?|numbers?|nos?\.?|#)?s?"
    r"|batch(?:es)?(?:\s*(?:nos?\.?|numbers?|#))?"
    r"|chargennummer|pack\s*numbers?|control\s*(?:nos?\.?|numbers?|#)|[bl]\s*/\s*n"
)
_EXP_LABEL = (
    r"exp(?:iry|iration|ires?)?\.?(?:\s*dates?)?|best\s*(?:use\s*dates?|before|by)|b\.?u\.?d\.?"
    r"|discard\s*(?:by|after)|use\s*by|made\s*on|compounded\s*on"
    r"|mfg\.?(?:\s*dates?)?|manufactur(?:ed|ing)\s*(?:on|dates?)"
)
_OTH_LABEL = (
    r"ndc|upc|gtin|product\s*codes?|item\s*(?:codes?|nos?\.?)|skus?|rx\s*#?'?s?"
    r"|disp\s*id|caps\s*rx|warennummer|application\s*numbers?"
)
_TOKEN = r"[A-Za-z0-9][A-Za-z0-9@:._/\-]*"

_SCAN_RE = re.compile(
    rf"(?P<lot>(?<![A-Za-z0-9])(?:{_LOT_LABEL})(?![A-Za-z]))"
    # (?<!no ) keeps "No Expiration Date on product: a) 224010" in LOT scope.
    rf"|(?P<exp>(?<![A-Za-z0-9])(?<!no )(?:{_EXP_LABEL})(?![A-Za-z]))"
    rf"|(?P<oth>(?<![A-Za-z0-9])(?:{_OTH_LABEL})(?![A-Za-z]))"
    # `;` and `)` close an expiry/other aside; they never end the record's lot list.
    rf"|(?P<brk>[;)])"
    rf"|(?P<tok>{_TOKEN})",
    re.I,
)
_ALL_LOTS_RE = re.compile(
    r"\ball\s+(?:\w+\s+){0,3}?(?:lots?|batch(?:es)?|codes?|lot\s*numbers?|product\s*codes?)\b"
    r"|\bevery\s+(?:\w+\s+){0,2}?(?:lot|batch)s?\b"
    r"|\b(?:lots?|batch(?:es)?|codes?)\s*[:#]?\s*all\b",
    re.I,
)


def _mask(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def extract_lots(text: str | None) -> ExtractedCodes:
    """openFDA `code_info` free text -> lots + NDCs (design B §1.1b)."""
    raw = clean_text(text)
    if not raw:
        return ExtractedCodes([], False, [])
    body = _squash(raw)
    covers_all = bool(_ALL_LOTS_RE.search(body))

    ndcs: list[str] = []
    for match in _NDC_LABELLED_RE.finditer(body):
        ndcs.append(match.group(1))
    for match in _NDC3_RE.finditer(body):
        ndcs.append(match.group(0))
    for pattern in (_NDC_LABELLED_RE, _NDC3_RE, _UPC_RE):
        while True:
            match = pattern.search(body)
            if match is None:
                break
            body = _mask(body, *match.span())

    # Boundary-guarded date masking: a date-shaped run glued to a word character
    # on either side is part of a lot (`t12-07-2016@97`), not a date.
    for match in list(_DATE_RE.finditer(body)):
        start, end = match.span()
        before = body[start - 1] if start else ""
        after = body[end] if end < len(body) else ""
        if (before and (before.isalnum() or before == "_")) or (after and (after.isalnum() or after == "_")):
            continue
        body = _mask(body, start, end)

    # Lot collection is the record's base state. EXP/OTHER labels open a transient
    # aside that closes at the next label, `;` or `)`.
    lots: list[str] = []
    seen: set[str] = set()
    labelled = False
    aside: str | None = None
    for match in _SCAN_RE.finditer(body):
        kind = match.lastgroup
        if kind == "lot":
            labelled, aside = True, None
        elif kind in ("oth", "exp"):
            aside = kind
        elif kind == "brk":
            aside = None
        elif kind == "tok" and aside is None:
            code = _ok_code(match.group(0), dateish=labelled)
            if code and code not in seen and len(lots) < MAX_LOTS:
                seen.add(code)
                lots.append(code)

    return ExtractedCodes(lots, covers_all, _dedupe(ndcs))


_PROSE_KEYWORD_RE = re.compile(
    r"\b(?:batch(?:es)?|lots?|serial)\b\s*(?:numbers?|nos?\.?|codes?)?\s*[:#]?\s*", re.I
)
_PROSE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/]*")
# A run continues over commas, slashes, "and" or plain whitespace; a full stop or
# any other punctuation ends it.
_PROSE_SEP_RE = re.compile(r"\s*(?:,|;|/|&|\band\b)\s*|\s+", re.I)
_PROSE_SECOND_RE = re.compile(r"\b[A-Z]{2,4}\d{3,8}[A-Z]?\b")


def extract_batches_from_prose(text: str | None) -> list[str]:
    """WHO / NAFDAC / MHRA prose and PDF table text -> batch numbers.

    After a batch/lot keyword, consume the run of batch-shaped tokens and stop at
    the first token that is not one (a word, a date, a strength) or at a sentence
    end — the run is what recovers `Batch numbers: AVT50 FNR06 SGL04`.
    """
    raw = clean_text(text)
    if not raw:
        return []
    body = _squash(raw)
    out: list[str] = []
    for keyword in _PROSE_KEYWORD_RE.finditer(body):
        pos = keyword.end()
        while pos < len(body):
            token = _PROSE_TOKEN_RE.match(body, pos)
            if token is None:
                break
            code = _ok_batch(token.group(0))
            if code is None:
                break
            out.append(code)
            pos = token.end()
            separator = _PROSE_SEP_RE.match(body, pos)
            if separator is None or separator.end() == pos:
                break
            pos = separator.end()
    # Recall-boosting second pass, scoped to sentences that talk about batches.
    for sentence in re.split(r"[.!?]\s|\.{2,}", body):
        if not re.search(r"falsifi|batch", sentence, re.I):
            continue
        for hit in _PROSE_SECOND_RE.findall(sentence):
            code = _ok_batch(hit)
            if code:
                out.append(code)
    return _dedupe(out)[:MAX_LOTS]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


# --------------------------------------------------------------------------- NDC


@dataclass(frozen=True)
class NdcForms:
    raw: str
    product_ndc: str | None
    ndc9: str | None
    ndc11: str | None


_NDC_ANY_RE = re.compile(r"(?<![-\w])(?:\d{4,5}-\d{3,4}-\d{1,2}|\d{4,5}-\d{3,4})(?![-\w])")
_NDC_PARSE_RE = re.compile(r"(\d{4,5})-(\d{3,4})(?:-(\d{1,2}))?")


def extract_ndcs(text: str | None) -> list[str]:
    body = clean_text(text)
    if not body:
        return []
    return _dedupe([m.group(0) for m in _NDC_ANY_RE.finditer(_squash(body))])


def normalize_ndc(value: str | None) -> NdcForms | None:
    raw = clean_text(value)
    if not raw:
        return None
    raw = _squash(raw)
    match = _NDC_PARSE_RE.search(raw)
    if match:
        labeler, product, package = match.group(1), match.group(2), match.group(3)
        total = len(labeler) + len(product) + (len(package) if package else 0)
        if (package and total in (10, 11)) or (not package and total in (8, 9)):
            ndc9 = f"{labeler:0>5}{product:0>4}"
            ndc11 = f"{ndc9}{package:0>2}" if package else None
            return NdcForms(raw, f"{labeler}-{product}", ndc9, ndc11)
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11:
        return NdcForms(raw, f"{digits[:5]}-{digits[5:9]}", digits[:9], digits)
    if len(digits) == 9:
        return NdcForms(raw, f"{digits[:5]}-{digits[5:]}", digits, None)
    if len(digits) == 10:
        # 4-4-2 / 5-3-2 / 5-4-1 are indistinguishable without hyphens.
        return NdcForms(raw, None, None, None)
    return None


# --------------------------------------------------------------------------- imprint


@dataclass(frozen=True)
class ImprintForms:
    raw: str
    norm: str
    sorted: str
    parts: list[str]
    text: str


_IMPRINT_SPLIT_RE = re.compile(r"[;|,\s]+")
_IMPRINT_BLANK = {
    "none", "no imprint", "blank", "n/a", "na", "no marking", "no markings",
    "nothing", "unmarked", "not visible", "--",
}


def normalize_imprint(value: str | None) -> ImprintForms | None:
    raw = clean_text(value)
    if not raw or raw.casefold() in _IMPRINT_BLANK:
        return None
    squashed = _squash(raw)
    parts = [p for p in (_NON_ALNUM_RE.sub("", s.upper()) for s in _IMPRINT_SPLIT_RE.split(squashed)) if p]
    if not parts:
        return None
    return ImprintForms(
        raw=squashed,
        norm="".join(parts),
        sorted="".join(sorted(parts)),
        parts=parts,
        text=" ".join(parts),
    )


# --------------------------------------------------------------------------- dates

_YMD_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_YM_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})$")
_MY_RE = re.compile(r"^(\d{1,2})[-/.](\d{4})$")
_MYY_RE = re.compile(r"^(\d{1,2})[-/.](\d{2})$")
_NAME_Y_RE = re.compile(r"^([A-Za-z]{3,9})\.?[\s\-]*(\d{2,4})$")
_EXP_PREFIX_RE = re.compile(
    r"^(?:exp(?:iry|iration|ires?)?\.?\s*(?:dates?)?|use\s+by|best\s+(?:by|before)|bbe?)\b[\s.:#\-]*",
    re.I,
)
_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9


def _utc(value: datetime) -> datetime | None:
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value if MIN_YEAR <= value.year <= MAX_YEAR else None


def parse_date(value: object) -> datetime | None:
    """Anything a source hands us -> tz-aware UTC datetime, or None. Epoch is
    deliberately not accepted (audit finding 11)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, date):
        return _utc(datetime(value.year, value.month, value.day))
    text = clean_text(value)
    if not text:
        return None
    text = _squash(text)

    if text.isdigit():
        match = _YMD_RE.match(text)
        if not match:
            return None
        year, month, day = (int(g) for g in match.groups())
        try:
            return _utc(datetime(year, month, day))
        except ValueError:
            return None
    parts = _month_year(text)
    if parts:
        year, month = parts
        return _utc(datetime(year, month, 1))
    try:
        return _utc(datetime.fromisoformat(text))
    except ValueError:
        pass
    try:
        parsed = _dateutil.parse(text, dayfirst=False, default=datetime(1900, 1, 1))
    except (ValueError, OverflowError, TypeError):
        return None
    return _utc(parsed)


def _month_year(text: str) -> tuple[int, int] | None:
    for pattern, order in ((_YM_RE, "ym"), (_MY_RE, "my"), (_MYY_RE, "myy")):
        match = pattern.match(text)
        if not match:
            continue
        a, b = int(match.group(1)), int(match.group(2))
        year, month = (a, b) if order == "ym" else (b, a)
        if order == "myy":
            year += 2000
        if 1 <= month <= 12 and MIN_YEAR <= year <= MAX_YEAR:
            return year, month
    match = _NAME_Y_RE.match(text)
    if match:
        month = _MONTHS.get(match.group(1).lower())
        year = int(match.group(2))
        year += 2000 if year < 100 else 0
        if month and MIN_YEAR <= year <= MAX_YEAR:
            return year, month
    return None


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _utc(value).strftime("%Y-%m-%dT%H:%M:%SZ") if _utc(value) else None


def parse_expiration(value: str | None) -> datetime | None:
    """Bottle-label expiry. A month with no day means the last day of it."""
    text = clean_text(value)
    if not text:
        return None
    text = _EXP_PREFIX_RE.sub("", _squash(text)).strip(" .:-")
    if not text:
        return None
    parts = _month_year(text)
    if parts:
        year, month = parts
        return datetime(year, month, calendar.monthrange(year, month)[1], tzinfo=UTC)
    return parse_date(text)


# --------------------------------------------------------------------------- names

_STRENGTH_RE = re.compile(
    r"\b\d+(?:[.,]\d+)*\s*(?:%|(?:mg|mcg|µg|ug|kg|g|ml|l|iu|units?|meq)\b)"
    r"(?:\s*/\s*\d*(?:\.\d+)?\s*(?:mg|mcg|ml|g|l|units?|hr)\b)?",
    re.I,
)
_FORM_WORDS = (
    "tablets", "tablet", "caplets", "caplet", "capsules", "capsule", "softgels", "softgel",
    "injections", "injection", "injectable", "solutions", "solution", "suspensions", "suspension",
    "syrups", "syrup", "elixirs", "elixir", "creams", "cream", "ointments", "ointment",
    "gels", "gel", "powders", "powder", "patches", "patch", "drops", "sprays", "spray",
    "inhalers", "inhaler", "inhalation", "suppositories", "suppository", "lozenges", "lozenge",
    "vials", "vial", "ampoules", "ampoule", "ampules", "ampule", "prefilled", "syringes", "syringe",
    "oral", "topical", "ophthalmic", "otic", "nasal", "rectal", "vaginal", "intravenous",
    "sublingual", "transdermal", "chewable", "effervescent", "delayed", "extended", "immediate",
    "release", "film", "coated", "sterile", "lyophilized", "concentrate", "kit", "usp", "bp",
    "nf", "rx", "only", "single", "use", "dose", "unit",
)
_FORM_RE = re.compile(rf"\b(?:{'|'.join(_FORM_WORDS)})\b", re.I)
_NUMERIC_TOKEN_RE = re.compile(r"^[\d.,]+$")


def normalize_drug_name(value: str | None) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    text = _squash(text).casefold()
    text = _STRENGTH_RE.sub(" ", text)
    text = _FORM_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9%\-+' ]", " ", text)
    tokens = [t.strip("-'") for t in text.split()]
    tokens = [t for t in tokens if t and not _NUMERIC_TOKEN_RE.match(t)]
    name = " ".join(tokens).strip(" -")
    return name or None


_HEAD_CUT_RE = re.compile(
    r",?\s*(?:rx\s+only|otc|distributed\s+by|manufactured\s+(?:by|for)|mfd\s+by|mfg\s+by"
    r"|packaged\s+by|repackaged\s+by|ndc\b)|\(",
    re.I,
)


def extract_drug_names(product_description: str | None) -> list[str]:
    """Leading drug name(s) from an openFDA `product_description` (design B §1.1a)."""
    text = clean_text(product_description)
    if not text:
        return []
    head = _squash(text)
    cut = _HEAD_CUT_RE.search(head)
    if cut:
        head = head[: cut.start()]
    limits = [m.start() for m in (_STRENGTH_RE.search(head), _FORM_RE.search(head)) if m]
    if limits:
        head = head[: min(limits)]
    out: list[str] = []
    for piece in head.split("/"):
        name = normalize_drug_name(piece)
        if name and len(name) >= 3 and name not in out:
            out.append(name)
    return out[:5]


DOSAGE_FORMS = (
    "tablet", "capsule", "injection", "solution", "suspension", "syrup", "cream", "ointment",
    "gel", "powder", "patch", "drops", "spray", "inhaler", "suppository", "other",
)
_FORM_MAP: dict[str, str] = {
    "solution for injection": "injection", "powder for injection": "injection",
    "prefilled syringe": "injection", "pre filled syringe": "injection",
    "film coated tablet": "tablet", "sugar coated tablet": "tablet", "coated tablet": "tablet",
    "chewable tablet": "tablet", "orally disintegrating tablet": "tablet",
    "extended release tablet": "tablet", "delayed release tablet": "tablet",
    "soft capsule": "capsule", "hard capsule": "capsule", "soft gel": "capsule",
    "gel cap": "capsule", "gelcap": "capsule", "softgel": "capsule",
    "transdermal system": "patch", "transdermal patch": "patch",
    "metered dose inhaler": "inhaler", "inhalation powder": "inhaler",
    "nasal spray": "spray", "eye drops": "drops", "ear drops": "drops",
    "tablet": "tablet", "tablets": "tablet", "tab": "tablet", "tabs": "tablet",
    "caplet": "tablet", "caplets": "tablet", "pill": "tablet", "troche": "other",
    "capsule": "capsule", "capsules": "capsule", "cap": "capsule", "caps": "capsule",
    "injection": "injection", "injectable": "injection", "vial": "injection",
    "ampoule": "injection", "ampule": "injection", "ampoules": "injection",
    "syringe": "injection", "intravenous": "injection", "infusion": "injection",
    "solution": "solution", "oral solution": "solution", "concentrate": "solution",
    "suspension": "suspension", "oral suspension": "suspension",
    "syrup": "syrup", "elixir": "syrup",
    "cream": "cream", "ointment": "ointment", "salve": "ointment",
    "gel": "gel", "jelly": "gel",
    "powder": "powder", "granules": "powder", "sachet": "powder",
    "patch": "patch", "drops": "drops", "drop": "drops",
    "spray": "spray", "aerosol": "spray",
    "inhaler": "inhaler", "inhalation": "inhaler",
    "suppository": "suppository", "suppositories": "suppository", "pessary": "suppository",
    "lozenge": "other", "implant": "other", "kit": "other", "film": "other",
    "emulsion": "other", "lotion": "other", "paste": "other", "enema": "other",
    "liquid": "other", "wafer": "other",
}
_FORM_KEYS = sorted(_FORM_MAP, key=len, reverse=True)


def normalize_dosage_form(value: str | None) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    text = re.sub(r"[^a-z0-9 ]+", " ", _squash(text).casefold())
    text = _WS_RE.sub(" ", text).strip()
    if not text:
        return None
    if text in _FORM_MAP:
        return _FORM_MAP[text]
    for key in _FORM_KEYS:
        if re.search(rf"\b{re.escape(key)}\b", text):
            return _FORM_MAP[key]
    return None


# --------------------------------------------------------------------------- severity

_CLASS_RE = re.compile(r"(?:class|type)\s*\.?\s*(iii|ii|iv|i|[1-4])\b", re.I)
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
_ORGS = {
    "fda": "FDA", "us fda": "FDA", "openfda": "FDA",
    "who": "WHO",
    "health canada": "Health Canada", "healthcanada": "Health Canada", "hc": "Health Canada",
    "mhra": "MHRA",
    "nafdac": "NAFDAC",
}
_FDA_LEVELS = {1: "critical", 2: "high", 3: "moderate"}
_HC_LEVELS = {1: "critical", 2: "high", 3: "moderate"}
_MHRA_LEVELS = {1: "critical", 2: "critical", 3: "high", 4: "moderate"}


def _class_levels(text: str) -> list[int]:
    out = []
    for raw in _CLASS_RE.findall(text):
        out.append(_ROMAN.get(raw.lower(), 0) or int(raw))
    return out


def severity_for(
    source_org: str,
    classification: str | None,
    doc_type: str | None = None,
) -> tuple[str, int]:
    """Cross-source severity (audit finding 5: critical=4 .. unknown=1)."""
    org = _ORGS.get((clean_text(source_org) or "").casefold(), clean_text(source_org) or "")
    raw = (clean_text(classification) or "").casefold()
    kind = (clean_text(doc_type) or "").casefold()
    severity = "unknown"

    if org in ("WHO", "NAFDAC"):
        blob = f"{kind} {raw}"
        if "falsified" in blob or "counterfeit" in blob or "fake" in blob:
            severity = "critical"
        elif "substandard" in blob or "recall" in blob:
            severity = "high"
        elif org == "NAFDAC" and "watchlist" in blob:
            severity = "moderate"
    elif org == "FDA":
        levels = _class_levels(raw)
        severity = _FDA_LEVELS.get(min(levels), "unknown") if levels else "unknown"
    elif org == "Health Canada":
        levels = _class_levels(raw)
        severity = _HC_LEVELS.get(min(levels), "unknown") if levels else "unknown"
    elif org == "MHRA":
        levels = _class_levels(raw)
        if levels:
            severity = _MHRA_LEVELS.get(min(levels), "unknown")
        elif "company-led" in raw or "company led" in raw:
            severity = "moderate"

    return severity, SEVERITY_RANKS[severity]


_DOC_TYPE_RULES = (
    (re.compile(r"falsifi|counterfeit|\bfake\b|spurious", re.I), "falsified_alert"),
    (
        re.compile(r"substandard|contaminat|out of specification|not of standard quality", re.I),
        "substandard_alert",
    ),
    (re.compile(r"recall|withdraw", re.I), "recall"),
)


def classify_doc_type(text: str | None, default: str = "safety_alert") -> str:
    body = clean_text(text)
    if not body:
        return default
    for pattern, doc_type in _DOC_TYPE_RULES:
        if pattern.search(body):
            return doc_type
    return default


# --------------------------------------------------------------------------- countries

_COUNTRIES: tuple[str, ...] = (
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Antigua and Barbuda", "Argentina",
    "Armenia", "Australia", "Austria", "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh",
    "Barbados", "Belarus", "Belgium", "Belize", "Benin", "Bhutan", "Bolivia",
    "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", "Bulgaria", "Burkina Faso",
    "Burundi", "Cabo Verde", "Cambodia", "Cameroon", "Canada", "Central African Republic",
    "Chad", "Chile", "China", "Colombia", "Comoros", "Costa Rica", "Cote d'Ivoire", "Croatia",
    "Cuba", "Cyprus", "Czechia", "Democratic Republic of the Congo", "Denmark", "Djibouti",
    "Dominica", "Dominican Republic", "Ecuador", "Egypt", "El Salvador", "Equatorial Guinea",
    "Eritrea", "Estonia", "Eswatini", "Ethiopia", "Fiji", "Finland", "France", "Gabon", "Gambia",
    "Georgia", "Germany", "Ghana", "Greece", "Grenada", "Guatemala", "Guinea", "Guinea-Bissau",
    "Guyana", "Haiti", "Honduras", "Hungary", "Iceland", "India", "Indonesia", "Iran", "Iraq",
    "Ireland", "Israel", "Italy", "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya", "Kiribati",
    "Kuwait", "Kyrgyzstan", "Laos", "Latvia", "Lebanon", "Lesotho", "Liberia", "Libya",
    "Liechtenstein", "Lithuania", "Luxembourg", "Madagascar", "Malawi", "Malaysia", "Maldives",
    "Mali", "Malta", "Marshall Islands", "Mauritania", "Mauritius", "Mexico", "Micronesia",
    "Moldova", "Monaco", "Mongolia", "Montenegro", "Morocco", "Mozambique", "Myanmar", "Namibia",
    "Nauru", "Nepal", "Netherlands", "New Zealand", "Nicaragua", "Niger", "Nigeria",
    "North Korea", "North Macedonia", "Norway", "Oman", "Pakistan", "Palau", "Palestine",
    "Panama", "Papua New Guinea", "Paraguay", "Peru", "Philippines", "Poland", "Portugal",
    "Qatar", "Republic of the Congo", "Romania", "Russia", "Rwanda", "Saint Kitts and Nevis",
    "Saint Lucia", "Saint Vincent and the Grenadines", "Samoa", "San Marino",
    "Sao Tome and Principe", "Saudi Arabia", "Senegal", "Serbia", "Seychelles", "Sierra Leone",
    "Singapore", "Slovakia", "Slovenia", "Solomon Islands", "Somalia", "South Africa",
    "South Korea", "South Sudan", "Spain", "Sri Lanka", "Sudan", "Suriname", "Sweden",
    "Switzerland", "Syria", "Tajikistan", "Tanzania", "Thailand", "Timor-Leste", "Togo", "Tonga",
    "Trinidad and Tobago", "Tunisia", "Turkey", "Turkmenistan", "Tuvalu", "Uganda", "Ukraine",
    "United Arab Emirates", "United Kingdom", "United States", "Uruguay", "Uzbekistan",
    "Vanuatu", "Vatican City", "Venezuela", "Vietnam", "Yemen", "Zambia", "Zimbabwe",
)
_COUNTRY_ALIASES: dict[str, str] = {
    "USA": "United States", "U.S.A.": "United States",
    "United States of America": "United States",
    "UK": "United Kingdom", "U.K.": "United Kingdom", "Great Britain": "United Kingdom",
    "Britain": "United Kingdom", "England": "United Kingdom", "Scotland": "United Kingdom",
    "Northern Ireland": "United Kingdom",
    "UAE": "United Arab Emirates",
    "DRC": "Democratic Republic of the Congo",
    "DR Congo": "Democratic Republic of the Congo",
    "Democratic Republic of Congo": "Democratic Republic of the Congo",
    "Congo-Kinshasa": "Democratic Republic of the Congo",
    "Zaire": "Democratic Republic of the Congo",
    "Congo": "Republic of the Congo", "Republic of Congo": "Republic of the Congo",
    "Congo-Brazzaville": "Republic of the Congo",
    "Ivory Coast": "Cote d'Ivoire", "Côte d'Ivoire": "Cote d'Ivoire",
    "Republic of Korea": "South Korea",
    "Democratic People's Republic of Korea": "North Korea", "DPRK": "North Korea",
    "Russian Federation": "Russia", "Syrian Arab Republic": "Syria",
    "Islamic Republic of Iran": "Iran", "Lao People's Democratic Republic": "Laos",
    "Viet Nam": "Vietnam", "Burma": "Myanmar", "Czech Republic": "Czechia",
    "The Netherlands": "Netherlands", "Holland": "Netherlands",
    "Türkiye": "Turkey", "Turkiye": "Turkey", "Cape Verde": "Cabo Verde",
    "Swaziland": "Eswatini", "East Timor": "Timor-Leste",
    "United Republic of Tanzania": "Tanzania", "Republic of Moldova": "Moldova",
    "Plurinational State of Bolivia": "Bolivia",
    "Bolivarian Republic of Venezuela": "Venezuela",
    "Federated States of Micronesia": "Micronesia", "Holy See": "Vatican City",
    "Vatican": "Vatican City", "State of Palestine": "Palestine",
    "Brunei Darussalam": "Brunei", "Macedonia": "North Macedonia",
    "The Bahamas": "Bahamas", "The Gambia": "Gambia",
    "São Tomé and Príncipe": "Sao Tome and Principe",
    # "Georgia" alone is a US state far more often than the country.
    "Republic of Georgia": "Georgia",
}
_COUNTRY_LOOKUP: dict[str, str] = {name.casefold(): name for name in _COUNTRIES if name != "Georgia"}
_COUNTRY_LOOKUP.update({alias.casefold(): canon for alias, canon in _COUNTRY_ALIASES.items()})
_COUNTRY_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(k) for k in sorted(_COUNTRY_LOOKUP, key=len, reverse=True)) + r")(?!\w)",
    re.I,
)


def extract_countries(text: str | None) -> list[str]:
    body = clean_text(text)
    if not body:
        return []
    body = _squash(body)
    return _dedupe([_COUNTRY_LOOKUP[m.group(0).casefold()] for m in _COUNTRY_RE.finditer(body)])


# --------------------------------------------------------------------------- urls / hashes

_TRACKING_PARAMS = {
    "fbclid", "gclid", "msclkid", "yclid", "ref", "ref_src", "referrer", "igshid",
    "mc_cid", "mc_eid", "_ga", "_gl", "spm",
}
_DEFAULT_PORTS = {"http": 80, "https": 443}


def canonical_url(url: str) -> str:
    raw = (clean_text(url) or "").strip()
    if not raw:
        return ""
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*://", raw):
        raw = "https://" + raw.lstrip("/")
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = host if port in (None, _DEFAULT_PORTS.get(scheme)) else f"{host}:{port}"
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower().startswith("utm_") or k.lower() in _TRACKING_PARAMS)
    ]
    return urlunsplit((scheme, netloc, path, urlencode(sorted(kept)), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()[:32]


def domain_of(url: str) -> str:
    raw = (clean_text(url) or "").strip()
    if not raw:
        return ""
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*://", raw):
        raw = "//" + raw.lstrip("/")
    host = (urlsplit(raw).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def content_hash(text: str) -> str:
    return hashlib.sha256(" ".join(str(text).split()).casefold().encode()).hexdigest()


def query_key(query: str) -> str:
    return " ".join(str(query).casefold().split())


# --------------------------------------------------------------------------- recency

_FRESHNESS = ((1, "today"), (7, "this_week"), (31, "this_month"), (365, "this_year"))


def age_days(recency: datetime | str | None, now: datetime | None = None) -> int | None:
    moment = parse_date(recency)
    if moment is None:
        return None
    reference = now if now is not None else datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return max(0, (reference - moment).days)


def freshness_label(age: int | None) -> str:
    if age is None:
        return "unknown"
    for limit, label in _FRESHNESS:
        if age <= limit:
            return label
    return "older"


# --------------------------------------------------------------------------- text

def truncate_on_sentence(text: str, cap: int) -> str:
    body = str(text)
    if cap <= 0:
        return ""
    if len(body) <= cap:
        return body
    window = body[:cap]
    keep = cap * 0.6
    stop = max(window.rfind(". "), window.rfind(".\n"))
    if stop >= 0 and (stop + 1) >= keep:
        return window[: stop + 1]
    head = (window.rsplit(" ", 1)[0] if " " in window else window).rstrip()
    # An unbroken run longer than the cap has no usable word boundary.
    return head if len(head) >= keep else window


_SKIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript"}
_BLOCK_TAGS = {
    "p", "div", "br", "tr", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "table",
    "thead", "tbody", "section", "article", "blockquote", "pre", "hr", "dl", "dt", "dd",
    "figcaption", "address", "main", "form",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip = 0
        self._cells = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "tr":
            self.chunks.append("\n")
            self._cells = 0
        elif tag in ("td", "th"):
            if self._cells:
                self.chunks.append(" | ")
            self._cells += 1
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif not self._skip and (tag in _BLOCK_TAGS or tag == "tr"):
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.chunks.append(re.sub(r"\s+", " ", data))


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(str(html))
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup must never abort a seed run
        pass
    lines = [re.sub(r" *\| *$", "", line).strip() for line in "".join(parser.chunks).split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()
