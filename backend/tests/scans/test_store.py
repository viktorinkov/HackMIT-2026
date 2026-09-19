from __future__ import annotations

from typing import Any

import pytest
from elastic_transport import ApiResponseMeta
from elasticsearch import ApiError, NotFoundError

from backend.config import Settings
from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import SCANS_INDEX, Scan
from backend.photo_identification.bottle import BottlePhotoResult
from backend.pill import PillHardwareResult
from backend.scans.models import PhotoRef, ScanCreate
from backend.scans.store import ScanStore

SHA = "b" * 64


def _meta(status: int) -> ApiResponseMeta:
    return ApiResponseMeta(
        status=status, http_version="1.1", headers={}, duration=0.0, node=None
    )


def _api_error(status: int = 500) -> ApiError:
    return ApiError("boom", meta=_meta(status), body={})


def _not_found() -> NotFoundError:
    return NotFoundError("missing", meta=_meta(404), body={})


class FakeEs:
    """Records every call; each method returns the queued response or raises."""

    def __init__(self, **responses: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses

    async def _run(self, name: str, kwargs: dict[str, Any]) -> Any:
        self.calls.append((name, kwargs))
        value = self.responses.get(name)
        if isinstance(value, Exception):
            raise value
        return value

    async def index(self, **kwargs: Any) -> Any:
        return await self._run("index", kwargs)

    async def get(self, **kwargs: Any) -> Any:
        return await self._run("get", kwargs)

    async def update(self, **kwargs: Any) -> Any:
        return await self._run("update", kwargs)

    async def search(self, **kwargs: Any) -> Any:
        return await self._run("search", kwargs)

    def call(self, name: str) -> dict[str, Any]:
        return next(kwargs for called, kwargs in self.calls if called == name)


def settings(**kwargs: Any) -> Settings:
    return Settings(openai_api_key="test", **kwargs)


def store(es: FakeEs, **kwargs: Any) -> ScanStore:
    return ScanStore(es, settings(**kwargs))


def payload(**kwargs: Any) -> ScanCreate:
    fields: dict[str, Any] = {
        "device_id": "dev-1",
        "bottle": BottlePhotoResult(
            is_medication_container=True,
            generic_name="ibuprofen",
            lot_number="AB1234",
            ndc="16729-457-01",
            rx_number="RX-9",
            pharmacy="Corner Pharmacy",
            confidence=0.9,
        ),
        "photos": [PhotoRef(target="bottle", sha256=SHA, bytes=1024, media_type="image/png")],
    }
    fields.update(kwargs)
    return ScanCreate(**fields)


def hits(*sources: dict[str, Any], sort: list[Any] | None = None) -> dict[str, Any]:
    return {
        "hits": {
            "hits": [
                {"_source": source, "sort": sort or [source["created_at"], source["scan_id"]]}
                for source in sources
            ]
        }
    }


def source(scan_id: str, created_at: str = "2026-09-19T00:00:00Z") -> dict[str, Any]:
    return {
        Scan.SCAN_ID: scan_id,
        Scan.DEVICE_ID: "dev-1",
        Scan.CREATED_AT: created_at,
        Scan.UPDATED_AT: created_at,
        Scan.STATUS: "complete",
        Scan.REVISION: 2,
        Scan.DEMO: False,
    }


async def test_create_writes_a_pending_scan_and_waits_for_refresh() -> None:
    es = FakeEs(index={"result": "created"})
    doc = await store(es).create(payload())
    call = es.call("index")
    assert call["index"] == SCANS_INDEX
    assert call["refresh"] == "wait_for"
    assert call["id"] == doc[Scan.SCAN_ID] == call["document"][Scan.SCAN_ID]
    assert doc[Scan.SCAN_ID].startswith("scan-") and len(doc[Scan.SCAN_ID]) == 21
    assert doc[Scan.REVISION] == 1
    assert doc[Scan.STATUS] == "pending"
    assert doc[Scan.CREATED_AT] == doc[Scan.UPDATED_AT] == doc[Scan.RECENCY_DATE]
    assert doc[Scan.NORM]["lot"] == "AB1234"
    assert doc[Scan.PHOTOS] == [
        {"target": "bottle", "sha256": SHA, "bytes": 1024, "media_type": "image/png"}
    ]


async def test_create_never_stores_prescription_fields() -> None:
    es = FakeEs(index={"result": "created"})
    doc = await store(es).create(payload())
    assert "rx_number" not in doc[Scan.BOTTLE]
    assert "pharmacy" not in doc[Scan.BOTTLE]
    assert doc[Scan.BOTTLE]["rx_number_present"] is True


async def test_create_omits_blocks_the_scan_did_not_produce() -> None:
    es = FakeEs(index={"result": "created"})
    doc = await store(es).create(payload())
    assert Scan.IMPRINT not in doc
    assert Scan.HARDWARE not in doc


async def test_create_stores_the_hardware_block_when_present() -> None:
    es = FakeEs(index={"result": "created"})
    hardware = PillHardwareResult(
        status="real", spectrum=[0.5], pill_type="ibuprofen", degraded=False, confidence=0.9
    )
    doc = await store(es).create(payload(hardware=hardware, hardware_model="peel-nir-v1"))
    assert doc[Scan.HARDWARE]["model"] == "peel-nir-v1"


async def test_create_refuses_the_scan_when_elastic_is_down() -> None:
    es = FakeEs(index=_api_error(503))
    with pytest.raises(KnowledgeError) as excinfo:
        await store(es).create(payload())
    assert excinfo.value.status_code == 503


async def test_get_reads_realtime_and_returns_the_source() -> None:
    es = FakeEs(get={"_source": source("scan-1")})
    doc = await store(es).get("scan-1")
    assert es.call("get") == {"index": SCANS_INDEX, "id": "scan-1", "realtime": True}
    assert doc is not None and doc[Scan.SCAN_ID] == "scan-1"


async def test_get_returns_none_for_an_unknown_scan() -> None:
    assert await store(FakeEs(get=_not_found())).get("scan-x") is None


async def test_get_wraps_transport_failures() -> None:
    with pytest.raises(KnowledgeError):
        await store(FakeEs(get=_api_error())).get("scan-1")


async def test_apply_bumps_the_revision_in_one_scripted_update() -> None:
    es = FakeEs(update={"get": {"_source": {Scan.REVISION: 3}}})
    revision = await store(es).apply(
        "scan-1",
        status="partial",
        patch={"research": {"verdict": "recall_match"}},
        stage=("deterministic", {"status": "ok", "duration_ms": 12}),
    )
    call = es.call("update")
    params = call["script"]["params"]
    assert revision == 3
    assert call["refresh"] == "wait_for" and call["source"] is True
    assert "ctx._source.revision" in call["script"]["source"]
    assert params["status"] == "partial"
    assert params["patch"] == {"research": {"verdict": "recall_match"}}
    assert params["stage_name"] == "deterministic"
    assert params["stage"] == {"status": "ok", "duration_ms": 12}
    assert params["now"].endswith("Z")


async def test_apply_passes_nulls_when_nothing_is_supplied() -> None:
    es = FakeEs(update={"get": {"_source": {Scan.REVISION: 2}}})
    await store(es).apply("scan-1")
    params = es.call("update")["script"]["params"]
    assert params["status"] is None
    assert params["patch"] is None
    assert params["stage_name"] is None and params["stage"] is None


async def test_apply_falls_back_to_a_read_when_the_update_omits_the_source() -> None:
    es = FakeEs(update={"result": "updated"}, get={"_source": source("scan-1")})
    assert await store(es).apply("scan-1", status="complete") == 2


async def test_apply_reports_a_missing_scan_as_404() -> None:
    with pytest.raises(KnowledgeError) as excinfo:
        await store(FakeEs(update=_not_found())).apply("scan-x")
    assert excinfo.value.status_code == 404


async def test_list_filters_on_the_normalized_join_keys() -> None:
    es = FakeEs(search=hits(source("scan-1")))
    await store(es).list(device_id="dev-1", lot="AB1234", ndc9="167290457", limit=5)
    call = es.call("search")
    assert call["query"]["bool"]["filter"] == [
        {"term": {Scan.DEVICE_ID: "dev-1"}},
        {"term": {Scan.NORM_LOT: "AB1234"}},
        {"term": {Scan.NORM_NDC9: "167290457"}},
    ]
    assert call["sort"] == [{Scan.CREATED_AT: "desc"}, {Scan.SCAN_ID: "asc"}]
    assert call["size"] == 5
    assert call["search_after"] is None


async def test_list_without_filters_matches_everything() -> None:
    es = FakeEs(search=hits(source("scan-1")))
    await store(es).list()
    assert es.call("search")["query"] == {"match_all": {}}


async def test_list_returns_a_cursor_only_on_a_full_page() -> None:
    es = FakeEs(search=hits(source("scan-1"), source("scan-2")))
    docs, cursor = await store(es).list(limit=2)
    assert [doc[Scan.SCAN_ID] for doc in docs] == ["scan-1", "scan-2"]
    assert cursor is not None

    partial = FakeEs(search=hits(source("scan-1")))
    _, no_cursor = await store(partial).list(limit=2)
    assert no_cursor is None


async def test_list_round_trips_its_own_cursor() -> None:
    es = FakeEs(search=hits(source("scan-1")))
    _, cursor = await store(es).list(limit=1)
    resumed = FakeEs(search=hits(source("scan-2")))
    await store(resumed).list(limit=1, after=cursor)
    assert resumed.call("search")["search_after"] == ["2026-09-19T00:00:00Z", "scan-1"]


async def test_list_rejects_a_corrupt_cursor() -> None:
    with pytest.raises(KnowledgeError) as excinfo:
        await store(FakeEs()).list(after="!!!not-base64!!!")
    assert excinfo.value.status_code == 400


async def test_list_caps_the_page_size() -> None:
    es = FakeEs(search=hits(source("scan-1")))
    await store(es).list(limit=10_000)
    assert es.call("search")["size"] == 100


@pytest.mark.live
async def test_scripted_update_round_trips_on_the_real_cluster() -> None:
    """Serverless scripted updates were UNVERIFIED in design_C §5.4; this is the guard."""
    from backend.config import get_settings
    from backend.knowledge.client import build_client
    from backend.knowledge.indices import ensure_indices

    live_settings = get_settings()
    es = build_client(live_settings)
    scan_id = ""
    try:
        await ensure_indices(es, (SCANS_INDEX,))
        live = ScanStore(es, live_settings)
        doc = await live.create(payload(device_id="pytest-live", demo=True))
        scan_id = doc[Scan.SCAN_ID]

        assert await live.apply(scan_id, status="partial", stage=("normalize", {"ok": True})) == 2
        assert await live.apply(scan_id, status="complete", patch={"research": {"verdict": "x"}}) == 3

        fetched = await live.get(scan_id)
        assert fetched is not None
        assert fetched[Scan.STATUS] == "complete"
        assert fetched[Scan.REVISION] == 3
        assert fetched[Scan.STAGES]["normalize"] == {"ok": True}
        assert fetched[Scan.RESEARCH] == {"verdict": "x"}

        rows, _ = await live.list(device_id="pytest-live", lot="AB1234", limit=5)
        assert any(row[Scan.SCAN_ID] == scan_id for row in rows)
    finally:
        if scan_id:
            await es.delete(index=SCANS_INDEX, id=scan_id, refresh="wait_for")
        await es.close()
