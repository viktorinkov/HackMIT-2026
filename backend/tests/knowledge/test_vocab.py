"""Offline tests for backend.knowledge.vocab."""

from __future__ import annotations

import pytest

from backend.knowledge.vocab import (
    COLORS,
    MAX_COLORS,
    SHAPE_CODES,
    SHAPE_FAMILY,
    SHAPES,
    normalize_colors,
    normalize_score,
    normalize_shape,
    parse_size_mm,
    shape_family,
)


def test_vocab_tables_are_consistent() -> None:
    assert len(SHAPES) == 17
    assert set(SHAPES) == set(SHAPE_FAMILY)
    assert all(shape == shape.lower() for shape in SHAPES)
    assert all(color == color.lower() for color in COLORS)
    assert len(COLORS) == 12
    assert set(SHAPE_CODES.values()) <= set(SHAPES)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Pillbox splshape_text, verbatim.
        ("ROUND", "round"),
        ("OVAL", "oval"),
        ("CAPSULE", "capsule"),
        ("RECTANGLE", "rectangle"),
        ("TRIANGLE", "triangle"),
        ("HEXAGON (6 SIDED)", "hexagon"),
        ("PENTAGON (5 SIDED)", "pentagon"),
        ("OCTAGON (8 SIDED)", "octagon"),
        ("DIAMOND", "diamond"),
        ("SQUARE", "square"),
        ("BULLET", "bullet"),
        ("FREEFORM", "freeform"),
        ("TRAPEZOID", "trapezoid"),
        ("TEAR", "teardrop"),
        ("DOUBLE CIRCLE", "double_circle"),
        ("SEMI-CIRCLE", "semi_circle"),
        ("CLOVER", "clover"),
        # NCI/SPL shape codes.
        ("C48348", "round"),
        ("C48345", "oval"),
        ("C48336", "capsule"),
        ("c48353", "triangle"),
        # Vision free text.
        ("circular", "round"),
        ("disc", "round"),
        ("oblong", "oval"),
        ("elliptical", "oval"),
        ("caplet", "oval"),
        ("caplet-shaped", "oval"),
        ("oval-shaped", "oval"),
        ("football", "oval"),
        ("capsule-shaped", "capsule"),
        ("rectangular", "rectangle"),
        ("triangular", "triangle"),
        ("five-sided", "pentagon"),
        ("six-sided", "hexagon"),
        ("eight-sided", "octagon"),
        ("heart", "freeform"),
        ("shield", "freeform"),
        ("irregular", "freeform"),
        ("half moon", "semi_circle"),
        ("a small round white tablet", "round"),
    ],
)
def test_normalize_shape(value: str, expected: str) -> None:
    assert normalize_shape(value) == expected


@pytest.mark.parametrize("value", [None, "", "   ", "banana", "C99999", "zzz"])
def test_normalize_shape_fails_open(value: str | None) -> None:
    assert normalize_shape(value) is None
    assert shape_family(value) is None


@pytest.mark.parametrize(
    ("shape", "family"),
    [
        ("round", "round"),
        ("oval", "elongated"),
        ("capsule", "elongated"),
        ("bullet", "elongated"),
        ("rectangle", "quadrilateral"),
        ("square", "quadrilateral"),
        ("trapezoid", "quadrilateral"),
        ("diamond", "diamond"),
        ("triangle", "triangle"),
        ("pentagon", "polygon"),
        ("hexagon", "polygon"),
        ("octagon", "polygon"),
        ("teardrop", "irregular"),
        ("semi_circle", "irregular"),
        ("double_circle", "irregular"),
        ("clover", "irregular"),
        ("freeform", "irregular"),
        ("HEXAGON (6 SIDED)", "polygon"),
        ("oblong", "elongated"),
    ],
)
def test_shape_family(shape: str, family: str) -> None:
    assert shape_family(shape) == family


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("PINK;WHITE", ["pink", "white"]),
        ("BLUE;BLUE", ["blue"]),
        ("YELLOW;GREEN;RED;ORANGE", ["yellow", "green", "red"]),
        ("off-white", ["white"]),
        ("light blue", ["blue"]),
        ("dark blue", ["blue"]),
        ("peach", ["orange"]),
        ("cream", ["white"]),
        ("beige", ["brown"]),
        ("tan", ["brown"]),
        ("maroon", ["red"]),
        ("lavender", ["purple"]),
        ("teal", ["turquoise"]),
        ("clear", ["white"]),
        ("two-tone blue and white", ["blue", "white"]),
        ("blue/white", ["blue", "white"]),
        ("grey", ["gray"]),
        ("chartreuse", []),
        ("", []),
        (None, []),
    ],
)
def test_normalize_colors(value: str | None, expected: list[str]) -> None:
    out = normalize_colors(value)
    assert out == expected
    assert len(out) <= MAX_COLORS
    assert all(color in COLORS for color in out)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, 1),
        (2, 2),
        (3, 3),
        (4, 4),
        ("1", 1),
        ("4", 4),
        (2.0, 2),
        ("none", 1),
        ("unscored", 1),
        ("no score", 1),
        ("no line", 1),
        ("plain", 1),
        ("scored", 2),
        ("single score", 2),
        ("bisected", 2),
        ("scored once", 2),
        ("score line", 2),
        ("one line", 2),
        ("trisected", 3),
        ("three parts", 3),
        ("quadrisected", 4),
        ("cross-scored", 4),
        ("quartered", 4),
        ("double scored", 4),
    ],
)
def test_normalize_score(value: object, expected: int) -> None:
    assert normalize_score(value) == expected


@pytest.mark.parametrize("value", [None, "", "banana", 0, 5, -1, True, False, "0"])
def test_normalize_score_fails_open(value: object) -> None:
    assert normalize_score(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("16", 16.0),
        (16, 16.0),
        (16.0, 16.0),
        ("16 mm", 16.0),
        ("16mm", 16.0),
        ("1.6 cm", 16.0),
        ("8", 8.0),
    ],
)
def test_parse_size_mm(value: object, expected: float) -> None:
    assert parse_size_mm(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", [None, "", "banana", 0.5, "0.5", 41, "50 mm", "9 cm", True])
def test_parse_size_mm_rejects(value: object) -> None:
    assert parse_size_mm(value) is None
