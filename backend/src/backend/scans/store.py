"""Reads and writes for `peel-scans`."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from elasticsearch import ApiError, AsyncElasticsearch, NotFoundError
from fastapi import Depends

from backend.config import Settings, get_settings
from backend.knowledge import normalize
from backend.knowledge.client import KnowledgeError, get_es
from backend.knowledge.fields import SCANS_INDEX, Scan
from backend.scans.models import ScanCreate
from backend.scans.normalizer import build_norm, hardware_doc, imprint_doc, sanitize_bottle

MAX_LIMIT = 100

_UPDATE_SCRIPT = (
    "ctx._source.revision = (ctx._source.revision == null ? 0 : ctx._source.revision) + 1;"
    "ctx._source.updated_at = params.now;"
    "if (params.status != null) { ctx._source.status = params.status; }"
    "if (params.patch != null) {"
    " for (entry in params.patch.entrySet()) {"
    " ctx._source[entry.getKey()] = entry.getValue(); } }"
    "if (params.stage_name != null) {"
    " if (ctx._source.stages == null) { ctx._source.stages = [:]; }"
    " ctx._source.stages[params.stage_name] = params.stage; }"
)


class ScanStore:
    def __init__(self, es: AsyncElasticsearch, settings: Settings) -> None:
        self._es = es
        self._settings = settings

    async def create(self, payload: ScanCreate) -> dict[str, Any]:
        scan_id = f"scan-{uuid4().hex[:16]}"
        now = datetime.now(UTC)
        now_iso = normalize.to_iso(now)
        doc: dict[str, Any] = {
            Scan.SCAN_ID: scan_id,
            Scan.DEVICE_ID: payload.device_id,
            Scan.COUNTRY: payload.country,
            Scan.REVISION: 1,
            Scan.STATUS: "pending",
            Scan.DEMO: payload.demo,
            Scan.CREATED_AT: now_iso,
            Scan.UPDATED_AT: now_iso,
            Scan.RECENCY_DATE: now_iso,
            Scan.NORM: build_norm(
                payload.bottle,
                payload.imprint,
                imprint_size_mm=payload.imprint_size_mm,
                now=now,
            ),
            Scan.STAGES: {},
            Scan.PHOTOS: [photo.model_dump() for photo in payload.photos],
        }
        if payload.bottle is not None:
            doc[Scan.BOTTLE] = sanitize_bottle(
                payload.bottle, store_sensitive=self._settings.scans_store_sensitive
            )
        if payload.imprint is not None:
            doc[Scan.IMPRINT] = imprint_doc(payload.imprint, size_mm=payload.imprint_size_mm)
        if payload.hardware is not None:
            doc[Scan.HARDWARE] = hardware_doc(payload.hardware, payload.hardware_model)
        # Refuse the scan rather than accept one we cannot persist.
        with _api_errors("could not store the scan", status_code=503):
            await self._es.index(
                index=SCANS_INDEX, id=scan_id, document=doc, refresh="wait_for"
            )
        return doc

    async def get(self, scan_id: str) -> dict[str, Any] | None:
        """Realtime GET, so a 1 Hz poll sees stage writes before the index refreshes."""
        try:
            response = await self._es.get(index=SCANS_INDEX, id=scan_id, realtime=True)
        except NotFoundError:
            return None
        except ApiError as exc:
            raise _wrapped("could not read the scan", exc) from exc
        return dict(response["_source"])

    async def apply(
        self,
        scan_id: str,
        *,
        status: str | None = None,
        patch: dict[str, Any] | None = None,
        stage: tuple[str, dict[str, Any]] | None = None,
    ) -> int:
        """One scripted update: no read-modify-write race between pipeline stages.

        `patch` values replace their whole top-level key, so a caller changing one
        field of `norm` sends the merged `norm` object.
        """
        params: dict[str, Any] = {
            "now": normalize.to_iso(datetime.now(UTC)),
            "status": status,
            "patch": patch,
            "stage_name": stage[0] if stage else None,
            "stage": stage[1] if stage else None,
        }
        try:
            response = await self._es.update(
                index=SCANS_INDEX,
                id=scan_id,
                script={"source": _UPDATE_SCRIPT, "params": params},
                refresh="wait_for",
                source=True,
            )
        except NotFoundError as exc:
            raise KnowledgeError(f"scan {scan_id} not found", status_code=404) from exc
        except ApiError as exc:
            raise _wrapped("could not update the scan", exc) from exc
        revision = ((response.get("get") or {}).get("_source") or {}).get(Scan.REVISION)
        if revision is None:
            current = await self.get(scan_id)
            revision = (current or {}).get(Scan.REVISION, 0)
        return int(revision)

    async def list(
        self,
        *,
        device_id: str | None = None,
        lot: str | None = None,
        ndc9: str | None = None,
        limit: int = 20,
        after: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        size = max(1, min(limit, MAX_LIMIT))
        filters = [
            {"term": {field: value}}
            for field, value in (
                (Scan.DEVICE_ID, device_id),
                (Scan.NORM_LOT, lot),
                (Scan.NORM_NDC9, ndc9),
            )
            if value
        ]
        query = {"bool": {"filter": filters}} if filters else {"match_all": {}}
        # scan_id breaks created_at ties so search_after never skips or repeats a row.
        sort = [{Scan.CREATED_AT: "desc"}, {Scan.SCAN_ID: "asc"}]
        with _api_errors("could not list scans"):
            response = await self._es.search(
                index=SCANS_INDEX,
                query=query,
                sort=sort,
                size=size,
                search_after=_decode_cursor(after),
                track_total_hits=False,
            )
        hits = list(response["hits"]["hits"])
        docs = [dict(hit["_source"]) for hit in hits]
        cursor = _encode_cursor(hits[-1].get("sort")) if len(hits) == size and hits else None
        return docs, cursor


def get_scan_store(
    es: AsyncElasticsearch = Depends(get_es),
    settings: Settings = Depends(get_settings),
) -> ScanStore:
    return ScanStore(es, settings)


def _encode_cursor(sort_values: list[Any] | None) -> str | None:
    if not sort_values:
        return None
    raw = json.dumps(sort_values, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> list[Any] | None:
    if not cursor:
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        values = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, binascii.Error) as exc:
        raise KnowledgeError("invalid pagination cursor", status_code=400) from exc
    if not isinstance(values, list):
        raise KnowledgeError("invalid pagination cursor", status_code=400)
    return values


def _wrapped(message: str, exc: ApiError) -> KnowledgeError:
    return KnowledgeError(f"{message}: {exc.message}", status_code=502)


@contextmanager
def _api_errors(message: str, status_code: int = 502) -> Iterator[None]:
    try:
        yield
    except ApiError as exc:
        raise KnowledgeError(f"{message}: {exc.message}", status_code=status_code) from exc
