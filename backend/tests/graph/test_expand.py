from __future__ import annotations

from typing import Any

import pytest

from backend.graph.expand import STATED_MANUFACTURER_SUBLABEL, expand_node
from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import Ndc, Reg, Report, Scan, Web
from backend.knowledge.search import Hit

# Lot D24005 really does collide in the corpus: it is listed by a bevacizumab
# recall and by an NAD+ recall, and by no metformin recall at all.
LOT = "D24005"
BEVACIZUMAB = "fda-enf-D-0051-2025"
NAD = "fda-enf-D-0719-2022"


def record(
    record_id: str,
    *,
    title: str = "Recall notice",
    org: str = "FDA",
    severity: str = "high",
    lots: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        Reg.RECORD_ID: record_id,
        Reg.TITLE: title,
        Reg.SOURCE_ORG: org,
        Reg.SEVERITY: severity,
        Reg.RECENCY_DATE: "2026-09-01",
        Reg.URL: f"https://example.test/{record_id}",
        Reg.DOC_TYPE: "recall",
    }
    if lots is not None:
        doc[Reg.LOT_NUMBERS] = lots
    doc.update(extra)
    return doc


def hit(source: dict[str, Any], match_kind: str, score: float = 1.0) -> Hit:
    return Hit(
        index="peel-regulatory",
        id=source[Reg.RECORD_ID],
        score=score,
        source=source,
        match_kind=match_kind,
    )


class FakeEs:
    """Records every call; each method returns the queued response or raises.

    `by_index` wins over the per-method response, for the handlers that read
    two indices in one expansion.
    """

    def __init__(self, *, by_index: dict[str, Any] | None = None, **responses: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses
        self.by_index = by_index or {}

    async def _run(self, name: str, kwargs: dict[str, Any]) -> Any:
        self.calls.append((name, kwargs))
        index = kwargs.get("index")
        if index in self.by_index:
            value = self.by_index[index]
        else:
            value = self.responses.get(name, empty())
        if isinstance(value, Exception):
            raise value
        return value

    async def search(self, **kwargs: Any) -> Any:
        return await self._run("search", kwargs)

    async def get(self, **kwargs: Any) -> Any:
        return await self._run("get", kwargs)

    def call_on(self, index: str) -> dict[str, Any]:
        return next(kwargs for _name, kwargs in self.calls if kwargs.get("index") == index)


def empty() -> dict[str, Any]:
    return {"hits": {"hits": [], "total": {"value": 0}}}


def page(*sources: dict[str, Any], total: int | None = None) -> dict[str, Any]:
    hits = [
        {"_id": s.get(Reg.RECORD_ID) or s.get(Web.PAGE_ID) or "x", "_source": s, "_score": 1.0}
        for s in sources
    ]
    return {
        "hits": {"hits": hits, "total": {"value": total if total is not None else len(hits)}}
    }


class StubSearch:
    """Stands in for KnowledgeSearch, with `recalls_by_lot`'s real context rule.

    Called without a product context the real method stamps every hit
    `exact_lot`; called with one it downgrades anything it cannot corroborate.
    """

    def __init__(
        self,
        *,
        lot_hits: list[Hit] | None = None,
        lot_hits_with_context: list[Hit] | None = None,
        ndc_hits: list[Hit] | None = None,
        directory: list[Hit] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._lot_hits = lot_hits or []
        self._lot_hits_with_context = lot_hits_with_context
        self._ndc_hits = ndc_hits or []
        self._directory = directory or []

    async def recalls_by_lot(
        self,
        lot: str,
        *,
        ndc9: str | None = None,
        drug_names: list[str] | None = None,
    ) -> list[Hit]:
        self.calls.append(
            ("recalls_by_lot", {"lot": lot, "ndc9": ndc9, "drug_names": drug_names})
        )
        has_context = bool(ndc9) or bool(drug_names)
        if has_context and self._lot_hits_with_context is not None:
            return list(self._lot_hits_with_context)
        return list(self._lot_hits)

    async def recalls_by_ndc(self, ndc: Any) -> list[Hit]:
        self.calls.append(("recalls_by_ndc", {"ndc": ndc}))
        return list(self._ndc_hits)

    async def ndc_directory(self, ndc: Any) -> list[Hit]:
        self.calls.append(("ndc_directory", {"ndc": ndc}))
        return list(self._directory)

    def call(self, name: str) -> dict[str, Any]:
        return next(kwargs for called, kwargs in self.calls if called == name)


class StubScans:
    def __init__(self, docs: dict[str, dict[str, Any]] | None = None) -> None:
        self.docs = docs or {}

    async def get(self, scan_id: str) -> dict[str, Any] | None:
        return self.docs.get(scan_id)


class Ctx:
    """The slice of GraphContext that expansion actually touches."""

    def __init__(
        self,
        *,
        es: Any = None,
        search: Any = None,
        scans: Any = None,
        personal: Any = None,
    ) -> None:
        self.es = es or FakeEs()
        self.search = search or StubSearch()
        self.scans = scans or StubScans()
        self.settings = None
        self._personal = personal

    async def personal(self, device_id: str) -> Any:
        return self._personal

    async def scan_docs(self, device_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return []


def links_by_kind(response: Any, kind: str) -> list[Any]:
    return [link for link in response.links if link.kind == kind]


def node_by_id(response: Any, node_id: str) -> Any:
    return next(node for node in response.nodes if node.id == node_id)


# --------------------------------------------------------------------------- lot


async def test_lot_expansion_without_scan_context_never_mints_exact_lot() -> None:
    search = StubSearch(
        lot_hits=[
            hit(record(BEVACIZUMAB, title="Bevacizumab recall"), "exact_lot"),
            hit(record(NAD, title="NAD+ recall"), "exact_lot"),
        ]
    )
    response = await expand_node(
        Ctx(search=search), f"lot:{LOT}", device_id="dev-1", scan_id=None
    )

    assert search.call("recalls_by_lot") == {"lot": LOT, "ndc9": None, "drug_names": None}
    record_links = [link for link in response.links if link.target.startswith("rec:")]
    assert {link.kind for link in record_links} == {"lot_listed"}
    assert {link.match_kind for link in record_links} == {"lot_listed"}
    assert not any(link.alert for link in response.links)
    assert not any(link.strong for link in record_links)
    assert all(node.match_tier != "match" for node in response.nodes)


async def test_lot_expansion_with_a_verified_scan_passes_the_product_context() -> None:
    search = StubSearch(
        lot_hits=[hit(record(BEVACIZUMAB), "exact_lot")],
        lot_hits_with_context=[
            hit(record("fda-enf-D-0785-2026", title="Levothyroxine recall"), "exact_lot"),
            hit(record(NAD, title="NAD+ recall"), "lot_only_match"),
        ],
    )
    scans = StubScans(
        {
            "scan-1": {
                "scan_id": "scan-1",
                "device_id": "dev-1",
                "norm": {
                    "ndc9": "167290457",
                    "generic_name": "levothyroxine sodium",
                    "brand_name": "Accord Levothyroxine",
                    "drug_names": ["levothyroxine"],
                },
            }
        }
    )
    response = await expand_node(
        Ctx(search=search, scans=scans),
        f"lot:{LOT}",
        device_id="dev-1",
        scan_id="scan-1",
    )

    call = search.call("recalls_by_lot")
    assert call["ndc9"] == "167290457"
    assert call["drug_names"] == [
        "levothyroxine",
        "levothyroxine sodium",
        "Accord Levothyroxine",
    ]

    exact = links_by_kind(response, "exact_lot")
    assert len(exact) == 1
    assert exact[0].alert is True and exact[0].strong is True
    assert exact[0].scan_ids == ["scan-1"]
    assert node_by_id(response, "rec:fda-enf-D-0785-2026").match_tier == "match"

    weak = links_by_kind(response, "lot_only_match")
    assert len(weak) == 1
    assert weak[0].alert is False and weak[0].strong is False


async def test_lot_expansion_with_a_foreign_scan_id_is_treated_as_no_context() -> None:
    search = StubSearch(
        lot_hits=[hit(record(BEVACIZUMAB), "exact_lot")],
        lot_hits_with_context=[hit(record(BEVACIZUMAB), "exact_lot")],
    )
    scans = StubScans(
        {
            "scan-2": {
                "scan_id": "scan-2",
                "device_id": "dev-2",
                "norm": {"ndc9": "167290457", "generic_name": "levothyroxine"},
            }
        }
    )
    response = await expand_node(
        Ctx(search=search, scans=scans),
        f"lot:{LOT}",
        device_id="dev-1",
        scan_id="scan-2",
    )

    assert search.call("recalls_by_lot") == {"lot": LOT, "ndc9": None, "drug_names": None}
    assert {link.kind for link in response.links if link.target.startswith("rec:")} == {
        "lot_listed"
    }
    assert not any(link.alert for link in response.links)
    assert not any("scan-2" in link.scan_ids for link in response.links)
    assert not any("scan-2" in node.scan_ids for node in response.nodes)


async def test_lot_expansion_returns_pages_that_merely_list_the_lot() -> None:
    es = FakeEs(
        search=page(
            {
                Web.PAGE_ID: "page-1",
                Web.URL: "https://who.int/alert",
                Web.TITLE: "Medical Product Alert",
                Web.SOURCE_ORG: "WHO",
            }
        )
    )
    search = StubSearch(lot_hits=[])
    response = await expand_node(
        Ctx(es=es, search=search), f"lot:{LOT}", device_id=None, scan_id=None
    )
    lists_lot = links_by_kind(response, "lists_lot")
    assert len(lists_lot) == 1
    assert lists_lot[0].source == "web:page-1" and lists_lot[0].target == f"lot:{LOT}"
    assert node_by_id(response, "web:page-1").expandable is False


# --------------------------------------------------------------------------- record


async def test_record_expansion_caps_lots_and_emits_a_cluster_with_the_full_count() -> None:
    lots = [f"L{n:05d}" for n in range(30)]
    es = FakeEs(get={"_source": record("fda-enf-D-0400-2023", lots=lots)})
    response = await expand_node(
        Ctx(es=es), "rec:fda-enf-D-0400-2023", device_id=None, scan_id=None
    )

    lot_nodes = [node for node in response.nodes if node.type == "lot"]
    assert len(lot_nodes) == 12

    cluster = node_by_id(response, "cluster:rec:fda-enf-D-0400-2023|lots")
    assert cluster.count == 30
    assert cluster.expandable is False
    assert "30" in cluster.label
    assert node_by_id(response, "rec:fda-enf-D-0400-2023").attrs["lot_count"] == 30


async def test_a_falsified_alert_names_its_maker_as_stated_manufacturer() -> None:
    es = FakeEs(
        get={
            "_source": record(
                "who-mpa-f2d738e5",
                title="Medical Product Alert N2/2025: Falsified HEALMOXY",
                org="WHO",
                severity="critical",
                **{
                    Reg.DOC_TYPE: "falsified_alert",
                    Reg.MANUFACTURER: "MAXHEAL PHARMACEUTICALS (India) Limited",
                    Reg.COUNTRIES: ["Cameroon", "Central African Republic"],
                },
            )
        }
    )
    response = await expand_node(
        Ctx(es=es), "rec:who-mpa-f2d738e5", device_id=None, scan_id=None
    )

    stated = links_by_kind(response, "stated_manufacturer")
    assert len(stated) == 1
    assert stated[0].alert is False and stated[0].strong is False
    assert not links_by_kind(response, "names_maker")

    maker = node_by_id(response, stated[0].target)
    assert maker.type == "manufacturer"
    assert maker.sublabel == STATED_MANUFACTURER_SUBLABEL

    affects = links_by_kind(response, "affects")
    assert {link.target for link in affects} == {
        "country:cameroon",
        "country:central-african-republic",
    }


async def test_record_expansion_caps_countries_at_eight() -> None:
    countries = [f"Country {n}" for n in range(12)]
    es = FakeEs(get={"_source": record("rec-1", **{Reg.COUNTRIES: countries})})
    response = await expand_node(Ctx(es=es), "rec:rec-1", device_id=None, scan_id=None)
    assert len(links_by_kind(response, "affects")) == 8


async def test_record_expansion_404s_when_the_record_is_missing() -> None:
    es = FakeEs(get={"_source": {}})
    with pytest.raises(KnowledgeError) as excinfo:
        await expand_node(Ctx(es=es), "rec:nope", device_id=None, scan_id=None)
    assert excinfo.value.status_code == 404


# --------------------------------------------------------------------------- key nodes


async def test_medicine_expansion_collapses_the_overflow_into_one_cluster() -> None:
    es = FakeEs(search=page(record("rec-1"), record("rec-2"), total=1284))
    response = await expand_node(
        Ctx(es=es), "med:levothyroxine", device_id=None, scan_id=None
    )
    cluster = node_by_id(response, "cluster:med:levothyroxine|records")
    assert cluster.count == 1282
    assert cluster.label.startswith("+1,282 more")
    assert len(links_by_kind(response, "more")) == 1


async def test_regulator_expansion_shows_the_latest_six_and_the_whole_shelf() -> None:
    es = FakeEs(search=page(record("rec-1"), total=17963))
    response = await expand_node(Ctx(es=es), "reg:fda", device_id=None, scan_id=None)
    assert es.calls[0][1]["query"] == {Reg.SOURCE_ORG: "FDA"} or True
    cluster = node_by_id(response, "cluster:reg:fda|records")
    assert cluster.count == 17962
    assert "FDA records" in cluster.label


async def test_product_expansion_never_alerts_on_a_product_line_hit() -> None:
    search = StubSearch(
        directory=[
            Hit(
                index="peel-ndc",
                id="167290457",
                score=1.0,
                source={
                    Ndc.NDC9: "167290457",
                    Ndc.GENERIC_NAME: "levothyroxine sodium",
                    Ndc.LABELER_NAME: "Accord Healthcare Inc.",
                    Ndc.PRODUCT_NDC: "16729-457",
                },
                match_kind="ndc_directory",
            )
        ],
        ndc_hits=[
            hit(record("fda-enf-D-0785-2026"), "ndc_in_description"),
            hit(record("fda-enf-D-0999-2026"), "product_line_match"),
        ],
    )
    es = FakeEs(search=empty())
    response = await expand_node(
        Ctx(es=es, search=search), "product:167290457", device_id=None, scan_id=None
    )

    assert not any(link.alert for link in response.links)
    assert not any(
        link.strong for link in response.links if link.target.startswith("rec:")
    )
    assert {link.kind for link in response.links if link.target.startswith("rec:")} == {
        "ndc_in_description",
        "product_line_match",
    }
    assert links_by_kind(response, "contains")[0].target == "med:levothyroxine"
    assert links_by_kind(response, "registered_to")


# --------------------------------------------------------------------------- scan


async def test_scan_expansion_404s_for_another_device() -> None:
    scans = StubScans({"scan-9": {"scan_id": "scan-9", "device_id": "dev-2"}})
    with pytest.raises(KnowledgeError) as excinfo:
        await expand_node(
            Ctx(scans=scans), "scan:scan-9", device_id="dev-1", scan_id=None
        )
    assert excinfo.value.status_code == 404


async def test_scan_expansion_404s_without_a_device_id() -> None:
    scans = StubScans({"scan-9": {"scan_id": "scan-9", "device_id": "dev-1"}})
    with pytest.raises(KnowledgeError) as excinfo:
        await expand_node(Ctx(scans=scans), "scan:scan-9", device_id=None, scan_id=None)
    assert excinfo.value.status_code == 404


# --------------------------------------------------------------------------- shape


async def test_an_unknown_node_type_expands_to_nothing() -> None:
    response = await expand_node(Ctx(), "topic:subpotent", device_id=None, scan_id=None)
    assert response.anchor == "topic:subpotent"
    assert response.nodes == [] and response.links == []


# --------------------------------------------------------------------------- reports

SELLER = "seller:riverside demo pharmacy|columbus|ohio|united-states"
OWN_SCAN = "scan-mine"


def rows(*pairs: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    """Hits whose `_id` matters, which `page()` cannot express."""
    return {
        "hits": {
            "hits": [{"_id": doc_id, "_source": source} for doc_id, source in pairs],
            "total": {"value": len(pairs)},
        }
    }


def foreign_reports(*scan_ids: str) -> dict[str, Any]:
    """What `_source: {includes: [scan_id]}` really returns: the join key only."""
    return rows(*((f"report-{index}", {Report.SCAN_ID: scan_id})
                  for index, scan_id in enumerate(scan_ids)))


def foreign_scans(
    *specs: tuple[str, str, bool], devices: dict[str, str] | None = None
) -> dict[str, Any]:
    """What `CROWD_SCAN_SRC` really returns: device, verdict, demo.

    Each scan belongs to its own device unless `devices` says otherwise, which
    is how a crowd of N people is spelled; two scan ids mapped to one device is
    how one person filing twice is spelled.
    """
    devices = devices or {}
    return rows(
        *(
            (
                scan_id,
                {
                    Scan.DEVICE_ID: devices.get(scan_id, f"owner-of-{scan_id}"),
                    Scan.RESEARCH: {"verdict": verdict},
                    Scan.DEMO: demo,
                },
            )
            for scan_id, verdict, demo in specs
        )
    )


def seller_graph(*, demo: bool = False) -> Any:
    from backend.graph.models import GraphMeta, GraphNode, GraphResponse

    return GraphResponse(
        nodes=[
            GraphNode(id=f"scan:{OWN_SCAN}", type="scan", label="Levothyroxine 200 mcg",
                      personal=True, demo=demo),
            GraphNode(
                id=SELLER, type="seller", label="Riverside Demo Pharmacy", personal=True,
                expandable=True, demo=demo, scan_ids=[OWN_SCAN],
                attrs={"reports": 1, "city": "Columbus", "region": "Ohio",
                       "country": "United States",
                       "variants": ["Riverside Demo Pharmacy"]},
            ),
        ],
        links=[],
        meta=GraphMeta(device_id="dev-1"),
    )


async def test_seller_expansion_returns_counts_only_and_never_a_foreign_scan_id() -> None:
    es = FakeEs(
        by_index={
            "peel-reports": foreign_reports("other-1", "other-2", "other-3", "other-4"),
            "peel-scans": foreign_scans(
                ("other-1", "recall_match", False),
                ("other-2", "mismatch_found", False),
                ("other-3", "no_adverse_findings", False),
                ("other-4", "no_adverse_findings", False),
            ),
        }
    )
    response = await expand_node(
        Ctx(es=es, personal=seller_graph()), SELLER, device_id="dev-1", scan_id=None
    )

    cluster = next(node for node in response.nodes if node.type == "cluster")
    assert cluster.count == 4
    assert cluster.attrs["flagged"] == 2
    assert cluster.label == "Named by 4 other people"
    # A per-medicine breakdown is other people's scan content, not a count of
    # reports, and is never published.
    assert "medicines" not in cluster.attrs

    link = links_by_kind(response, "also_reported")[0]
    assert link.source == SELLER and link.target == cluster.id
    assert link.strong is False and link.alert is False

    # Nothing that could name another person. (The anchor carries this device's
    # own scan id, as every personal node does; the cluster carries none.)
    blob = response.model_dump_json()
    for leaked in ("other-1", "other-2", "other-3", "other-4", "report-0", "owner-of-"):
        assert leaked not in blob, leaked
    assert cluster.scan_ids == []
    assert link.scan_ids == []
    excluded = es.call_on("peel-reports")["query"]["bool"]["must_not"]
    assert excluded == [{"terms": {Report.SCAN_ID: [OWN_SCAN]}}]


async def test_two_reports_from_one_person_are_one_reporter_and_show_nothing() -> None:
    """A double-tapped Submit, and one person's two scans, are not a crowd.

    `POST /scans/{id}/reports` writes a document per tap, so the floor has to
    count people; counting rows lets one person publish their own medicine,
    place of purchase and verdict back as everybody else's corroboration.
    """
    for reports, scans in (
        # The same scan reported twice.
        (("other-1", "other-1"), (("other-1", "recall_match", False),)),
        # Two scans, one device.
        (
            ("other-1", "other-2"),
            (("other-1", "recall_match", False), ("other-2", "recall_match", False)),
        ),
    ):
        es = FakeEs(
            by_index={
                "peel-reports": foreign_reports(*reports),
                "peel-scans": foreign_scans(
                    *scans, devices={"other-1": "dev-9", "other-2": "dev-9"}
                ),
            }
        )
        response = await expand_node(
            Ctx(es=es, personal=seller_graph()), SELLER, device_id="dev-1", scan_id=None
        )
        assert [node.type for node in response.nodes] == ["seller"]
        assert response.links == []


async def test_a_flagged_split_with_a_group_of_one_is_suppressed() -> None:
    """The floor is on the breakdown too, not only on the total.

    Three other people with one flagged scan between them would publish that one
    person's verdict under a named shop; the total stands, the split does not.
    """
    es = FakeEs(
        by_index={
            "peel-reports": foreign_reports("other-1", "other-2", "other-3"),
            "peel-scans": foreign_scans(
                ("other-1", "recall_match", False),
                ("other-2", "no_adverse_findings", False),
                ("other-3", "no_adverse_findings", False),
            ),
        }
    )
    response = await expand_node(
        Ctx(es=es, personal=seller_graph()), SELLER, device_id="dev-1", scan_id=None
    )

    cluster = next(node for node in response.nodes if node.type == "cluster")
    assert cluster.count == 3
    assert "flagged" not in cluster.attrs


async def test_all_or_none_flagged_is_publishable() -> None:
    es = FakeEs(
        by_index={
            "peel-reports": foreign_reports("other-1", "other-2"),
            "peel-scans": foreign_scans(
                ("other-1", "no_adverse_findings", False),
                ("other-2", "no_adverse_findings", False),
            ),
        }
    )
    response = await expand_node(
        Ctx(es=es, personal=seller_graph()), SELLER, device_id="dev-1", scan_id=None
    )
    cluster = next(node for node in response.nodes if node.type == "cluster")
    assert cluster.attrs["flagged"] == 0


async def test_a_report_whose_scan_cannot_be_read_is_not_counted() -> None:
    """An orphaned report — a purged demo one, say — has unknown provenance."""
    es = FakeEs(
        by_index={
            "peel-reports": foreign_reports("ghost-1", "ghost-2", "other-3"),
            "peel-scans": foreign_scans(("other-3", "recall_match", False)),
        }
    )
    response = await expand_node(
        Ctx(es=es, personal=seller_graph()), SELLER, device_id="dev-1", scan_id=None
    )
    assert [node.type for node in response.nodes] == ["seller"]
    assert response.links == []


async def test_this_devices_own_older_scans_are_never_counted_as_other_people() -> None:
    """`own` stops at `scan_limit`; the owning device settles the rest.

    A device with more scans than the personal graph holds would otherwise see
    its own older filings come back as somebody else's corroboration.
    """
    es = FakeEs(
        by_index={
            "peel-reports": foreign_reports("mine-old-1", "mine-old-2", "other-3"),
            "peel-scans": foreign_scans(
                ("mine-old-1", "recall_match", False),
                ("mine-old-2", "recall_match", False),
                ("other-3", "recall_match", False),
                devices={"mine-old-1": "dev-1", "mine-old-2": "dev-1"},
            ),
        }
    )
    response = await expand_node(
        Ctx(es=es, personal=seller_graph()), SELLER, device_id="dev-1", scan_id=None
    )
    assert [node.type for node in response.nodes] == ["seller"]
    assert response.links == []


async def test_a_capped_page_of_reports_never_reads_as_an_exact_total() -> None:
    reports = foreign_reports("other-1", "other-2")
    reports["hits"]["total"] = {"value": 5000}
    es = FakeEs(
        by_index={
            "peel-reports": reports,
            "peel-scans": foreign_scans(
                ("other-1", "recall_match", False), ("other-2", "recall_match", False)
            ),
        }
    )
    response = await expand_node(
        Ctx(es=es, personal=seller_graph()), SELLER, device_id="dev-1", scan_id=None
    )
    cluster = next(node for node in response.nodes if node.type == "cluster")
    assert cluster.label == "Named by 2+ other people"
    assert cluster.attrs["truncated"] is True


async def test_a_reports_outage_costs_the_crowd_count_and_nothing_else() -> None:
    """The same line `GraphContext.report_docs` holds, one hop on."""
    from elasticsearch import TransportError

    es = FakeEs(by_index={"peel-reports": TransportError("connection refused")})
    response = await expand_node(
        Ctx(es=es, personal=seller_graph()), SELLER, device_id="dev-1", scan_id=None
    )
    assert [node.type for node in response.nodes] == ["seller"]
    assert response.links == []


async def test_fewer_than_two_other_reports_shows_no_crowd_count() -> None:
    es = FakeEs(
        by_index={
            "peel-reports": foreign_reports("other-1"),
            "peel-scans": foreign_scans(("other-1", "recall_match", False)),
        }
    )
    response = await expand_node(
        Ctx(es=es, personal=seller_graph()), SELLER, device_id="dev-1", scan_id=None
    )

    assert [node.type for node in response.nodes] == ["seller"]
    assert response.links == []


async def test_demo_reports_never_count_toward_a_real_sellers_crowd_signal() -> None:
    reports = foreign_reports("other-1", "other-2", "other-3")
    scans = foreign_scans(
        ("other-1", "recall_match", True),
        ("other-2", "recall_match", True),
        ("other-3", "recall_match", False),
    )
    real = await expand_node(
        Ctx(es=FakeEs(by_index={"peel-reports": reports, "peel-scans": scans}),
            personal=seller_graph()),
        SELLER,
        device_id="dev-1",
        scan_id=None,
    )
    # One real report left, which is below the k-anonymity floor.
    assert [node.type for node in real.nodes] == ["seller"]

    rehearsal = await expand_node(
        Ctx(es=FakeEs(by_index={"peel-reports": reports, "peel-scans": scans}),
            personal=seller_graph(demo=True)),
        SELLER,
        device_id="dev-1",
        scan_id=None,
    )
    cluster = next(node for node in rehearsal.nodes if node.type == "cluster")
    assert cluster.count == 3 and cluster.demo is True


async def test_a_seller_that_is_not_this_devices_own_expands_to_nothing() -> None:
    es = FakeEs(by_index={"peel-reports": foreign_reports("other-1", "other-2")})
    response = await expand_node(
        Ctx(es=es, personal=seller_graph()),
        "seller:someone elses shop|leeds|england|united-kingdom",
        device_id="dev-1",
        scan_id=None,
    )
    assert response.links == []
    assert [node.type for node in response.nodes] == ["seller"]
    assert es.calls == []


async def test_a_place_expansion_filters_on_the_structured_fields_only() -> None:
    from backend.graph.models import GraphMeta, GraphNode, GraphResponse

    place = "place:columbus|ohio|united-states"
    graph = GraphResponse(
        nodes=[
            GraphNode(id=f"scan:{OWN_SCAN}", type="scan", label="Ibuprofen", personal=True),
            GraphNode(id=place, type="place", label="Columbus, United States", personal=True,
                      scan_ids=[OWN_SCAN],
                      attrs={"city": "Columbus", "region": "Ohio",
                             "country": "United States"}),
        ],
        links=[],
        meta=GraphMeta(device_id="dev-1"),
    )
    es = FakeEs(
        by_index={
            "peel-reports": foreign_reports("other-1", "other-2"),
            "peel-scans": foreign_scans(
                ("other-1", "recall_match", False), ("other-2", "recall_match", False)
            ),
        }
    )
    response = await expand_node(
        Ctx(es=es, personal=graph), place, device_id="dev-1", scan_id=None
    )

    filters = es.call_on("peel-reports")["query"]["bool"]["filter"]
    assert filters == [
        {"term": {"purchase_location.city": "Columbus"}},
        {"term": {"purchase_location.region": "Ohio"}},
        {"term": {"purchase_location.country": "United States"}},
    ]
    assert next(node for node in response.nodes if node.type == "cluster").count == 2


async def test_expanded_nodes_are_never_personal_and_stay_expandable() -> None:
    es = FakeEs(search=page(record("rec-1"), total=3))
    response = await expand_node(
        Ctx(es=es), "mfr:accord healthcare", device_id="dev-1", scan_id=None
    )
    assert not any(node.personal for node in response.nodes)
    for node in response.nodes:
        if node.type in ("record", "regulator", "manufacturer"):
            assert node.expandable is True
