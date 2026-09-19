"""openFDA NDC directory -> peel-ndc.

A single-partition bulk zip (~27 MB, 138k records, no dates besides marketing
dates). No semantic field: `peel-ndc` is pure keyword/lexical lookup used to
answer "is this NDC a real registered product, and is its listing expired?"
"""

from __future__ import annotations

import json
import zipfile
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.knowledge import normalize
from backend.knowledge.fields import NDC_INDEX, Ndc
from backend.seed.base import SeedContext, Source
from backend.seed.http import FetchError, download_file, fetch_json

MANIFEST_URL = "https://api.fda.gov/download.json"
ARCHIVE_NAME = "drug-ndc.json.zip"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def to_doc(
    record: dict[str, Any],
    *,
    now: datetime | None = None,
    dup_product_ndcs: set[str] | None = None,
) -> dict[str, Any] | None:
    product_ndc = normalize.clean_text(record.get("product_ndc"))
    if not product_ndc:
        return None
    now = now or datetime.now(UTC)
    dup_product_ndcs = dup_product_ndcs or set()
    spl_id = normalize.clean_text(record.get("spl_id"))
    doc_id = f"{product_ndc}-{spl_id}" if product_ndc in dup_product_ndcs and spl_id else product_ndc

    ndc_forms = normalize.normalize_ndc(product_ndc)

    package_ndcs = _dedupe(
        [normalize.clean_text(p.get("package_ndc")) or "" for p in (record.get("packaging") or [])]
    )
    ndc11: list[str] = []
    for package_ndc in package_ndcs:
        forms = normalize.normalize_ndc(package_ndc)
        if forms and forms.ndc11:
            ndc11.append(forms.ndc11)
    ndc11 = _dedupe(ndc11)

    active_names: list[str] = []
    strengths: list[str] = []
    for ingredient in record.get("active_ingredients") or []:
        name = normalize.clean_text(ingredient.get("name"))
        if name:
            active_names.append(name.lower())
        strength = normalize.clean_text(ingredient.get("strength"))
        if strength:
            strengths.append(strength)
    active_names = _dedupe(active_names)
    strengths = _dedupe(strengths)

    dosage_form = normalize.clean_text(record.get("dosage_form"))
    route = _dedupe([(normalize.clean_text(r) or "").lower() for r in (record.get("route") or [])])

    listing_expiration = normalize.parse_date(record.get("listing_expiration_date"))
    is_expired = None if listing_expiration is None else listing_expiration < now

    openfda = record.get("openfda") or {}
    spl_set_ids = openfda.get("spl_set_id") or []

    doc: dict[str, Any] = {
        "_id": doc_id,
        Ndc.PRODUCT_NDC: product_ndc,
        Ndc.NDC9: ndc_forms.ndc9 if ndc_forms else None,
        Ndc.PACKAGE_NDCS: package_ndcs,
        Ndc.NDC11: ndc11,
        Ndc.BRAND_NAME: normalize.clean_text(record.get("brand_name")),
        Ndc.GENERIC_NAME: normalize.clean_text(record.get("generic_name")),
        Ndc.LABELER_NAME: normalize.clean_text(record.get("labeler_name")),
        Ndc.ACTIVE_INGREDIENT_NAMES: active_names,
        Ndc.STRENGTHS: strengths,
        Ndc.DOSAGE_FORM: dosage_form.lower() if dosage_form else None,
        Ndc.ROUTE: route,
        Ndc.PRODUCT_TYPE: normalize.clean_text(record.get("product_type")),
        Ndc.MARKETING_CATEGORY: normalize.clean_text(record.get("marketing_category")),
        Ndc.MARKETING_START_DATE: normalize.to_iso(normalize.parse_date(record.get("marketing_start_date"))),
        Ndc.MARKETING_END_DATE: normalize.to_iso(normalize.parse_date(record.get("marketing_end_date"))),
        Ndc.LISTING_EXPIRATION_DATE: normalize.to_iso(listing_expiration),
        Ndc.IS_LISTING_EXPIRED: is_expired,
        Ndc.RXCUI: _dedupe([normalize.clean_text(r) or "" for r in (openfda.get("rxcui") or [])]),
        Ndc.UNII: _dedupe([normalize.clean_text(u) or "" for u in (openfda.get("unii") or [])]),
        Ndc.SPL_SET_ID: normalize.clean_text(spl_set_ids[0]) if spl_set_ids else None,
        Ndc.PHARM_CLASS: _dedupe([normalize.clean_text(p) or "" for p in (record.get("pharm_class") or [])]),
        Ndc.DEA_SCHEDULE: normalize.clean_text(record.get("dea_schedule")),
        Ndc.FINISHED: record.get("finished"),
    }
    return {k: v for k, v in doc.items() if k == "_id" or v not in (None, "", [])}


class OpenFdaNdcSource(Source):
    name = "openfda_ndc"
    index = NDC_INDEX
    description = "openFDA NDC directory (every registered US product listing)"
    semantic = False

    async def download(self, ctx: SeedContext) -> None:
        dest = ctx.raw_dir(self.name) / ARCHIVE_NAME
        if dest.exists() and dest.stat().st_size > 0 and not ctx.refresh_cache:
            return
        manifest = await fetch_json(ctx.http, MANIFEST_URL)
        partitions = manifest.get("results", {}).get("drug", {}).get("ndc", {}).get("partitions", [])
        if not partitions:
            raise FetchError("openFDA download manifest has no drug.ndc partitions")
        await download_file(ctx.http, partitions[0]["file"], dest, refresh=ctx.refresh_cache)

    def parse(self, ctx: SeedContext) -> Iterator[dict[str, Any]]:
        archive = ctx.raw_dir(self.name) / ARCHIVE_NAME
        if not archive.exists():
            return
        results = _read_results(archive)
        counts = Counter(r.get("product_ndc") for r in results)
        dup_product_ndcs = {ndc for ndc, count in counts.items() if count > 1}
        # Newest listings first, matching every other source's recency-first order.
        results.sort(key=lambda r: r.get("marketing_start_date") or "", reverse=True)

        yielded = 0
        for record in results:
            doc = to_doc(record, now=ctx.now, dup_product_ndcs=dup_product_ndcs)
            if doc is None:
                continue
            yield doc
            yielded += 1
            if ctx.limit is not None and yielded >= ctx.limit:
                return


def _read_results(archive: Path) -> list[dict[str, Any]]:
    try:
        with zipfile.ZipFile(archive) as bundle:
            inner_name = bundle.namelist()[0]
            with bundle.open(inner_name) as handle:
                payload = json.load(handle)
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, IndexError):
        return []
    results = payload.get("results")
    return results if isinstance(results, list) else []
