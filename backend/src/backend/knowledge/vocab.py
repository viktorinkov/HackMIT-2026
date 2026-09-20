"""Controlled vocabularies for pill physical features.

The same functions run over Pillbox's SPL text at seed time and over the vision
model's free text at query time — that symmetry is what makes a shape or colour
filter actually match (audit finding 7). Everything is lowercase, and an
unrecognised value returns ``None``/``[]`` so the caller filters on nothing
rather than on a wrong guess.
"""

from __future__ import annotations

import re

SHAPES: tuple[str, ...] = (
    "round", "oval", "capsule", "rectangle", "triangle", "square", "pentagon", "hexagon",
    "octagon", "diamond", "teardrop", "bullet", "semi_circle", "double_circle", "trapezoid",
    "clover", "freeform",
)

SHAPE_FAMILY: dict[str, str] = {
    "round": "round",
    "oval": "elongated",
    "capsule": "elongated",
    "bullet": "elongated",
    "rectangle": "quadrilateral",
    "square": "quadrilateral",
    "trapezoid": "quadrilateral",
    "diamond": "diamond",
    "triangle": "triangle",
    "pentagon": "polygon",
    "hexagon": "polygon",
    "octagon": "polygon",
    "teardrop": "irregular",
    "semi_circle": "irregular",
    "double_circle": "irregular",
    "clover": "irregular",
    "freeform": "irregular",
}

COLORS: tuple[str, ...] = (
    "white", "yellow", "orange", "red", "pink", "purple", "blue", "green", "brown", "gray",
    "black", "turquoise",
)

# NCI/SPL shape codes as they appear in raw SPL and some Pillbox exports.
SHAPE_CODES: dict[str, str] = {
    "C48335": "bullet",
    "C48336": "capsule",
    "C48337": "clover",
    "C48338": "diamond",
    "C48339": "double_circle",
    "C48340": "freeform",
    "C48341": "freeform",  # GEAR
    "C48342": "freeform",  # HEPTAGON (7 sided)
    "C48343": "hexagon",
    "C48344": "octagon",
    "C48345": "oval",
    "C48346": "pentagon",
    "C48347": "rectangle",
    "C48348": "round",
    "C48349": "semi_circle",
    "C48350": "square",
    "C48351": "teardrop",
    "C48352": "trapezoid",
    "C48353": "triangle",
}

_SHAPE_ALIASES: dict[str, str] = {
    "round": "round", "circular": "round", "circle": "round", "disc": "round", "disk": "round",
    "oval": "oval", "oblong": "oval", "elliptical": "oval", "ellipse": "oval",
    "egg shaped": "oval", "ovate": "oval", "caplet": "oval", "caplet shaped": "oval",
    "oval shaped": "oval", "football": "oval", "oblong oval": "oval",
    "capsule": "capsule", "capsule shaped": "capsule", "capsule shaped tablet": "capsule",
    "gelcap": "capsule", "gel cap": "capsule", "pill capsule": "capsule", "cap": "capsule",
    "rectangle": "rectangle", "rectangular": "rectangle", "bar": "rectangle",
    "oblong rectangle": "rectangle",
    "triangle": "triangle", "triangular": "triangle", "three sided": "triangle",
    "diamond": "diamond", "rhombus": "diamond", "rhomboid": "diamond", "kite": "diamond",
    "square": "square", "square shaped": "square",
    "pentagon": "pentagon", "pentagonal": "pentagon", "five sided": "pentagon",
    "5 sided": "pentagon",
    "hexagon": "hexagon", "hexagonal": "hexagon", "six sided": "hexagon", "6 sided": "hexagon",
    "octagon": "octagon", "octagonal": "octagon", "eight sided": "octagon",
    "8 sided": "octagon",
    "bullet": "bullet", "torpedo": "bullet",
    "trapezoid": "trapezoid", "trapezium": "trapezoid", "trapezoidal": "trapezoid",
    "tear": "teardrop", "teardrop": "teardrop", "tear drop": "teardrop", "pear": "teardrop",
    "pear shaped": "teardrop",
    "semi circle": "semi_circle", "semicircle": "semi_circle", "half circle": "semi_circle",
    "half moon": "semi_circle", "d shaped": "semi_circle",
    "double circle": "double_circle", "figure eight": "double_circle",
    "peanut": "double_circle",
    "clover": "clover", "cloverleaf": "clover", "four leaf": "clover",
    "freeform": "freeform", "free form": "freeform", "irregular": "freeform",
    "custom": "freeform", "odd": "freeform", "shield": "freeform", "heart": "freeform",
    "heart shaped": "freeform", "arrow": "freeform", "other": "freeform",
}

_PAREN_RE = re.compile(r"\([^)]*\)")
_NON_WORD_RE = re.compile(r"[^a-z0-9]+")
_CODE_RE = re.compile(r"^c\d{5}$")


def _flatten(value: str) -> str:
    text = _PAREN_RE.sub(" ", value.casefold())
    return _NON_WORD_RE.sub(" ", text).strip()


def normalize_shape(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if _CODE_RE.match(raw.casefold()):
        return SHAPE_CODES.get(raw.upper())
    text = _flatten(raw)
    if not text:
        return None
    if text.replace(" ", "_") in SHAPE_FAMILY:
        return text.replace(" ", "_")
    if text in _SHAPE_ALIASES:
        return _SHAPE_ALIASES[text]
    words = text.split()
    for size in range(min(3, len(words)), 0, -1):
        for start in range(len(words) - size + 1):
            phrase = " ".join(words[start : start + size])
            if phrase in _SHAPE_ALIASES:
                return _SHAPE_ALIASES[phrase]
    return None


def shape_family(shape: str | None) -> str | None:
    canonical = normalize_shape(shape)
    return SHAPE_FAMILY.get(canonical) if canonical else None


_COLOR_ALIASES: dict[str, str] = {
    "white": "white", "offwhite": "white", "cream": "white", "ivory": "white", "bone": "white",
    "eggshell": "white", "colorless": "white", "colourless": "white", "clear": "white",
    "yellow": "yellow", "gold": "yellow", "golden": "yellow", "mustard": "yellow",
    "buff": "yellow", "lemon": "yellow",
    "orange": "orange", "peach": "orange", "apricot": "orange", "salmon": "orange",
    "amber": "orange", "tangerine": "orange",
    "pink": "pink", "rose": "pink", "magenta": "pink", "fuchsia": "pink", "fuschia": "pink",
    "blue": "blue", "navy": "blue", "royal": "blue", "sky": "blue", "periwinkle": "blue",
    "brown": "brown", "tan": "brown", "beige": "brown", "caramel": "brown", "bronze": "brown",
    "khaki": "brown", "chocolate": "brown",
    "green": "green", "mint": "green", "olive": "green", "lime": "green", "emerald": "green",
    "red": "red", "maroon": "red", "burgundy": "red", "crimson": "red", "scarlet": "red",
    "purple": "purple", "violet": "purple", "lavender": "purple", "lilac": "purple",
    "plum": "purple", "indigo": "purple", "mauve": "purple",
    "gray": "gray", "grey": "gray", "silver": "gray", "slate": "gray", "charcoal": "gray",
    "turquoise": "turquoise", "teal": "turquoise", "aqua": "turquoise", "cyan": "turquoise",
    "aquamarine": "turquoise",
    "black": "black", "jet": "black",
}
_COLOR_MODIFIERS = {
    "light", "dark", "pale", "deep", "bright", "medium", "pastel", "off", "two", "tone",
    "toned", "and", "or", "with", "the", "a", "colored", "coloured", "color", "colour",
    "shade", "shaded", "very", "soft",
}
_COLOR_SPLIT_RE = re.compile(r"[^a-z0-9]+")
MAX_COLORS = 3


def normalize_colors(value: str | None) -> list[str]:
    if value is None:
        return []
    out: list[str] = []
    for token in _COLOR_SPLIT_RE.split(str(value).casefold()):
        if not token or token in _COLOR_MODIFIERS:
            continue
        base = _COLOR_ALIASES.get(token)
        if base and base not in out:
            out.append(base)
            if len(out) == MAX_COLORS:
                break
    return out


_SCORE_PHRASES: tuple[tuple[int, tuple[str, ...]], ...] = (
    (4, ("quadrisect", "quadrisected", "cross score", "cross scored", "crossscored", "cross",
         "quartered", "quarter", "quadrant", "quadrants", "four parts", "four segments",
         "double scored", "double score", "two lines", "four pieces")),
    (3, ("trisect", "trisected", "three parts", "three lines", "three pieces")),
    (1, ("unscored", "no score", "not scored", "no scoring", "no line", "no lines",
         "no markings", "none", "plain", "smooth", "unmarked")),
    (2, ("bisect", "bisected", "single score", "one score", "scored once", "score line",
         "one line", "one groove", "split in half", "half", "scored", "score")),
)


def normalize_score(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number if 1 <= number <= 4 else None
    text = _NON_WORD_RE.sub(" ", str(value).casefold()).strip()
    if not text:
        return None
    if text.isdigit():
        number = int(text)
        return number if 1 <= number <= 4 else None
    for score, phrases in _SCORE_PHRASES:
        if any(re.search(rf"\b{re.escape(phrase)}\b", text) for phrase in phrases):
            return score
    return None


_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mm|cm|millimet\w*|centimet\w*|in|inch\w*)?", re.I)
MIN_SIZE_MM = 1.0
MAX_SIZE_MM = 40.0


def parse_size_mm(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        size = float(value)
    else:
        match = _SIZE_RE.search(str(value))
        if not match:
            return None
        size = float(match.group(1))
        unit = (match.group(2) or "mm").lower()
        if unit.startswith(("cm", "centimet")):
            size *= 10
        elif unit.startswith(("in", "inch")):
            size *= 25.4
    return size if MIN_SIZE_MM <= size <= MAX_SIZE_MM else None
