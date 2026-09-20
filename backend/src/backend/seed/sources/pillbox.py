"""NLM Pillbox archive (frozen January 2021) -> peel-pills.

Socrata dataset crzr-uvwg: 83,925 rows, no app token needed at this volume.
Purely a physical-feature lookup catalog (imprint/shape/colour/size/score) —
no dates to rank by and no semantic_text field.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

from backend.knowledge import vocab
from backend.knowledge.fields import PILLS_INDEX, Pill
from backend.knowledge.normalize import clean_text, normalize_drug_name, normalize_imprint, parse_date, to_iso
from backend.seed.base import SeedContext, Source
from backend.seed.http import FetchError, get_with_retry

_URL = "https://datadiscovery.nlm.nih.gov/resource/crzr-uvwg.csv"
_PAGE_SIZE = 25000


def _row_count(text: str) -> int:
    reader = csv.reader(io.StringIO(text))
    next(reader, None)  # header
    return sum(1 for _ in reader)


def _pill_id(row: dict[str, str], row_index: int) -> str:
    # `spp` is Socrata's composite row key (setid + product_code + segment index)
    # and is unique across the whole dataset — verified against the live CSV.
    spp = clean_text(row.get("spp"))
    if spp:
        return spp
    parts = "|".join(clean_text(row.get(key)) or "" for key in ("setid", "product_code", "splimprint"))
    digest = hashlib.sha1(f"{parts}|{row_index}".encode()).hexdigest()
    return f"pillbox-{digest}"


def _ingredients(value: str | None) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    out: list[str] = []
    for piece in text.split(";"):
        name = piece.split("[", 1)[0].strip().lower()
        if name and name not in out:
            out.append(name)
    return out


def to_doc(row: dict[str, Any], *, row_index: int = 0) -> dict[str, Any] | None:
    """Pure CSV-row -> peel-pills document. No network, total, never raises."""
    imprint = normalize_imprint(row.get("splimprint"))
    shape = vocab.normalize_shape(row.get("splshape_text"))
    colors = vocab.normalize_colors(row.get("splcolor_text"))
    if imprint is None and shape is None and not colors:
        return None

    medicine_name = clean_text(row.get("medicine_name"))
    generic_name = normalize_drug_name(row.get("rxstring")) or normalize_drug_name(row.get("medicine_name"))
    strength = clean_text((row.get("spl_strength") or "").rstrip(";").strip() or None)
    dea_schedule = clean_text(row.get("dea_schedule_name")) or clean_text(row.get("dea_schedule_code"))
    marketing_status = clean_text(row.get("marketing_act_code"))

    pill_id = _pill_id(row, row_index)
    doc: dict[str, Any] = {
        "_id": pill_id,
        Pill.PILL_ID: pill_id,
        Pill.SETID: clean_text(row.get("setid")),
        Pill.SOURCE: "pillbox",
        Pill.SHAPE: shape,
        Pill.SHAPE_FAMILY: vocab.shape_family(shape),
        Pill.COLORS: colors or None,
        Pill.COLOR_RAW: clean_text(row.get("splcolor_text")),
        Pill.COLOR_COUNT: len(colors) or None,
        Pill.SCORE: vocab.normalize_score(row.get("splscore")),
        Pill.SIZE_MM: vocab.parse_size_mm(row.get("splsize")),
        Pill.MEDICINE_NAME: medicine_name,
        Pill.GENERIC_NAME: generic_name,
        Pill.STRENGTH: strength,
        Pill.INGREDIENTS: _ingredients(row.get("spl_ingredients")) or None,
        Pill.LABELER: clean_text(row.get("author")),
        Pill.RXCUI: clean_text(row.get("rxcui")),
        Pill.PRODUCT_NDC: clean_text(row.get("product_code")),
        Pill.NDC9: clean_text(row.get("ndc9")),
        Pill.DEA_SCHEDULE: dea_schedule.lower() if dea_schedule else None,
        Pill.MARKETING_STATUS: marketing_status.lower() if marketing_status else None,
        Pill.HAS_IMAGE: clean_text(row.get("has_image")) == "True",
        Pill.IMAGE_KEY: clean_text(row.get("splimage")),
        Pill.EFFECTIVE_TIME: to_iso(parse_date(row.get("effective_time"))),
        Pill.RAW: {k: v for k, v in row.items() if k != "spl_inactive_ing" and v not in (None, "")} or None,
    }
    if imprint is not None:
        doc[Pill.IMPRINT_RAW] = imprint.raw
        doc[Pill.IMPRINT_NORM] = imprint.norm
        doc[Pill.IMPRINT_SORTED] = imprint.sorted
        doc[Pill.IMPRINT_PARTS] = imprint.parts
        doc[Pill.IMPRINT_TEXT] = imprint.text
        doc[Pill.IMPRINT_LEN] = len(imprint.norm)
    return doc


class PillboxSource(Source):
    name: ClassVar[str] = "pillbox"
    index: ClassVar[str] = PILLS_INDEX
    description: ClassVar[str] = "NLM Pillbox archive (frozen Jan 2021): imprint/shape/colour/size lookup."
    semantic: ClassVar[bool] = False

    async def download(self, ctx: SeedContext) -> None:
        raw_dir = ctx.raw_dir(self.name)
        offset = 0
        while True:
            dest = raw_dir / f"page-{offset:06d}.csv"
            if dest.exists() and dest.stat().st_size > 0 and not ctx.refresh_cache:
                text = dest.read_text(encoding="utf-8")
            else:
                try:
                    response = await get_with_retry(
                        ctx.http,
                        _URL,
                        params={"$limit": _PAGE_SIZE, "$offset": offset, "$order": ":id"},
                        headers={"Accept": "text/csv"},
                    )
                except FetchError:
                    break  # one bad page must not sink the whole source
                text = response.text
                dest.write_text(text, encoding="utf-8")
            rows = _row_count(text)
            if rows == 0:
                break
            offset += _PAGE_SIZE
            if rows < _PAGE_SIZE or (ctx.limit is not None and offset >= ctx.limit):
                break

    def parse(self, ctx: SeedContext) -> Iterator[dict[str, Any]]:
        raw_dir = ctx.raw_dir(self.name)
        count = 0
        for path in sorted(Path(raw_dir).glob("page-*.csv")):
            with path.open("r", encoding="utf-8", newline="") as handle:
                for row_index, row in enumerate(csv.DictReader(handle)):
                    doc = to_doc(row, row_index=row_index)
                    if doc is None:
                        continue
                    yield doc
                    count += 1
                    if ctx.limit is not None and count >= ctx.limit:
                        return
