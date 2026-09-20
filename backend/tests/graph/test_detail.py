"""`graph/detail.py` — hand-rolled fakes only, no network.

Mirrors `tests/graph/test_expand.py`'s `Ctx`/`FakeEs` style: a small stand-in
for the slice of `GraphContext` that `node_detail` actually touches.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest
from elastic_transport import ApiResponseMeta
from elasticsearch import NotFoundError

from backend.graph import models as graph_models
from backend.graph.detail import DEFAULT_RECORD_NEXT_STEP, RELATION_LABELS, node_detail
from backend.knowledge.client import KnowledgeError
from backend.knowledge.fields import Reg, Scan
from backend.pill import HARDWARE_MODEL

BANNED_WORDS = ("safe", "genuine", "verified", "authentic")


def _meta(status: int) -> ApiResponseMeta:
    return ApiResponseMeta(status=status, http_version="1.1", headers={}, duration=0.0, node=None)


class FakeEs:
    def __init__(self, *, get_response: Any = None, get_error: Exception | None = None) -> None:
        self.get_response = get_response
        self.get_error = get_error
        self.calls: list[dict[str, Any]] = []

    async def get(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.get_error is not None:
            raise self.get_error
        return self.get_response


class FakeScans:
    def __init__(self, docs: dict[str, dict[str, Any]] | None = None) -> None:
        self.docs = docs or {}

    async def get(self, scan_id: str) -> dict[str, Any] | None:
        return self.docs.get(scan_id)


class Ctx:
    """The slice of GraphContext that `node_detail` actually touches."""

    def __init__(
        self,
        *,
        es: Any = None,
        scans: Any = None,
        scan_docs: list[dict[str, Any]] | None = None,
    ) -> None:
        self.es = es or FakeEs()
        self.scans = scans or FakeScans()
        self.search = None
        self.settings = None
        self._scan_docs = scan_docs or []

    async def scan_docs(self, device_id: str, limit: int = 200) -> list[dict[str, Any]]:
        return list(self._scan_docs)


def _scan_doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        Scan.SCAN_ID: "scan-1",
        Scan.DEVICE_ID: "dev-1",
        Scan.DEMO: False,
        Scan.COUNTRY: "United States",
        Scan.STATUS: "complete",
        Scan.NORM: {
            "generic_name": "levothyroxine sodium",
            "strength": "200 mcg",
            "lot": "D2402430",
            "ndc9": "167290457",
            "manufacturer": "Accord Healthcare",
            "expiration": "2026-10-31",
            "expired": False,
        },
        Scan.HARDWARE: {
            "status": "substandard",
            "degraded": False,
            "model": HARDWARE_MODEL,
            "limitations": "Simulated result; no physical measurement was performed.",
        },
        Scan.RESEARCH: {
            "verdict": "recall_match",
            "risk_level": "high",
            "headline": "This lot is named in an FDA recall.",
            "findings": [
                {
                    "statement": "The label's lot matches an FDA recall exactly.",
                    "severity": "serious",
                    "evidence_type": "exact_lot_match",
                },
                {
                    "statement": "3 earlier scans matched this lot.",
                    "severity": "info",
                    "evidence_type": "prior_scan_signal",
                },
            ],
            "mismatches": [],
            "gaps": ["Live web research was disabled for this scan."],
            "next_steps": ["Set this bottle aside.", "Take it to a pharmacist."],
            "sources": [
                {
                    "id": "fda-enf-D-0785-2026",
                    "title": "FDA recall D-0785-2026",
                    "url": "https://api.fda.gov/drug/enforcement.json?x",
                    "source_org": "FDA",
                    "published_at": "2026-09-02",
                }
            ],
        },
        # Must never leak into the detail: the builder's own allow-list omits
        # these sub-objects, and detail.py must keep the same discipline.
        Scan.BOTTLE: {
            "rx_number": "RX 8827341",
            "pharmacy": "Ikeja Pharmacy",
            "other_label_text": "leaked bottle text should never appear",
        },
        Scan.IMPRINT: {"notes": "leaked imprint note should never appear"},
    }
    doc.update(overrides)
    return doc


def _record_source(**overrides: Any) -> dict[str, Any]:
    source: dict[str, Any] = {
        Reg.RECORD_ID: "who-mpa-f2d738e5-8445-45ab-9dc4-10bcb4f0afcd",
        Reg.SOURCE_ORG: "WHO",
        Reg.TITLE: "Medical Product Alert N°2/2025: Falsified HEALMOXY",
        Reg.SUMMARY: "A" * 500,
        Reg.RECENCY_DATE: "2025-03-01T00:00:00Z",
        Reg.CLASSIFICATION_RAW: "Falsified product alert",
        Reg.STATUS: "active",
        Reg.LOT_NUMBERS: [f"L{i}" for i in range(30)],
        Reg.COUNTRIES: ["Cameroon", "Central African Republic"],
        Reg.URL: "https://who.int/alerts/x",
        Reg.SEVERITY: "critical",
        Reg.BODY: "THE FULL REGULATOR BODY TEXT THAT MUST NEVER LEAK",
    }
    source.update(overrides)
    return source


# --------------------------------------------------------------------------- scan


async def test_scan_detail_reads_only_norm_research_and_hardware() -> None:
    ctx = Ctx(scans=FakeScans({"scan-1": _scan_doc()}))

    detail = await node_detail(ctx, "scan:scan-1", device_id="dev-1")

    assert detail.type == "scan"
    assert detail.demo is False
    assert "levothyroxine sodium" in detail.title
    assert detail.subtitle == "A recall or alert names this lot"
    assert "Simulated hardware" in detail.badges
    assert any(p.key == "expiration" and p.value == "2026-10-31" for p in detail.properties)
    assert detail.body == "This lot is named in an FDA recall."
    assert detail.next_steps == ["Set this bottle aside.", "Take it to a pharmacist."]
    assert detail.gaps == ["Live web research was disabled for this scan."]

    dumped = detail.model_dump_json()
    for leaked in ("RX 8827341", "Ikeja Pharmacy", "leaked bottle text", "leaked imprint note"):
        assert leaked not in dumped


async def test_scan_detail_keeps_prior_scan_signal_findings_when_not_demo() -> None:
    ctx = Ctx(scans=FakeScans({"scan-1": _scan_doc(**{Scan.DEMO: False})}))

    detail = await node_detail(ctx, "scan:scan-1", device_id="dev-1")

    kinds = {finding.evidence_type for finding in detail.findings}
    assert "prior_scan_signal" in kinds
    assert "exact_lot_match" in kinds


async def test_scan_detail_drops_prior_scan_signal_findings_when_demo() -> None:
    ctx = Ctx(scans=FakeScans({"scan-1": _scan_doc(**{Scan.DEMO: True})}))

    detail = await node_detail(ctx, "scan:scan-1", device_id="dev-1")

    assert detail.demo is True
    kinds = {finding.evidence_type for finding in detail.findings}
    assert "prior_scan_signal" not in kinds
    assert "exact_lot_match" in kinds


async def test_scan_detail_404s_for_another_device() -> None:
    ctx = Ctx(scans=FakeScans({"scan-1": _scan_doc(**{Scan.DEVICE_ID: "someone-else"})}))

    with pytest.raises(KnowledgeError) as excinfo:
        await node_detail(ctx, "scan:scan-1", device_id="dev-1")
    assert excinfo.value.status_code == 404


async def test_scan_detail_404s_for_a_missing_scan() -> None:
    with pytest.raises(KnowledgeError) as excinfo:
        await node_detail(Ctx(), "scan:does-not-exist", device_id="dev-1")
    assert excinfo.value.status_code == 404


# --------------------------------------------------------------------------- record


async def test_record_detail_bounds_the_body_and_never_returns_the_raw_body() -> None:
    es = FakeEs(get_response={"_source": _record_source()})
    ctx = Ctx(es=es)

    detail = await node_detail(ctx, "rec:who-mpa-f2d738e5-8445-45ab-9dc4-10bcb4f0afcd", device_id=None)

    assert detail.type == "record"
    assert detail.body is not None
    assert len(detail.body) <= 360
    assert "FULL REGULATOR BODY" not in (detail.body or "")
    assert "FULL REGULATOR BODY" not in detail.model_dump_json()
    assert detail.sources[0].attribution == "World Health Organization, CC BY-NC-SA 3.0 IGO"
    lots_property = next(p for p in detail.properties if p.key == "lots")
    assert len(lots_property.value.split(", ")) == 25
    assert detail.counts["lot_count"] == 30


async def test_record_detail_404s_via_knowledge_error() -> None:
    es = FakeEs(get_error=NotFoundError("missing", meta=_meta(404), body={}))
    ctx = Ctx(es=es)

    with pytest.raises(KnowledgeError) as excinfo:
        await node_detail(ctx, "rec:does-not-exist", device_id=None)
    assert excinfo.value.status_code == 404


async def test_record_next_steps_are_reused_from_a_scan_with_a_qualifying_alert() -> None:
    record_id = "fda-enf-D-0785-2026"
    es = FakeEs(
        get_response={
            "_source": _record_source(
                **{
                    Reg.RECORD_ID: record_id,
                    Reg.SOURCE_ORG: "FDA",
                    Reg.TITLE: "Levothyroxine recall",
                }
            )
        }
    )
    donor = {
        Scan.SCAN_ID: "scan-2",
        Scan.DEVICE_ID: "dev-1",
        Scan.EVIDENCE: {
            "evidence_pack": {
                "exact_lot_hits": [{"record_id": record_id, "match_kind": "exact_lot"}],
            }
        },
        Scan.RESEARCH: {"next_steps": ["Set this bottle aside.", "Ask a pharmacist."]},
    }
    ctx = Ctx(es=es, scan_docs=[donor])

    detail = await node_detail(ctx, f"rec:{record_id}", device_id="dev-1")

    assert detail.next_steps == ["Set this bottle aside.", "Ask a pharmacist."]


async def test_record_next_steps_default_when_no_scan_qualifies() -> None:
    record_id = "fda-enf-D-0785-2026"
    es = FakeEs(get_response={"_source": _record_source(**{Reg.RECORD_ID: record_id})})
    non_qualifying_donor = {
        Scan.SCAN_ID: "scan-2",
        Scan.DEVICE_ID: "dev-1",
        Scan.EVIDENCE: {
            "evidence_pack": {
                # A lot_only_match never qualifies for a red edge.
                "exact_lot_hits": [{"record_id": record_id, "match_kind": "lot_only_match"}],
            }
        },
        Scan.RESEARCH: {"next_steps": ["should not be used"]},
    }
    ctx = Ctx(es=es, scan_docs=[non_qualifying_donor])

    detail = await node_detail(ctx, f"rec:{record_id}", device_id="dev-1")

    assert detail.next_steps == [DEFAULT_RECORD_NEXT_STEP]


async def test_record_next_steps_default_without_a_device_id() -> None:
    es = FakeEs(get_response={"_source": _record_source()})
    detail = await node_detail(Ctx(es=es), "rec:who-mpa-f2d738e5-8445-45ab-9dc4-10bcb4f0afcd", device_id=None)
    assert detail.next_steps == [DEFAULT_RECORD_NEXT_STEP]


# --------------------------------------------------------------------------- graph-derived (lot/product/manufacturer/...)


def _alert_scan_doc(**overrides: Any) -> dict[str, Any]:
    """One scan whose lot is named in an FDA recall — the alert-owning scan."""
    doc: dict[str, Any] = {
        Scan.SCAN_ID: "scan-alert",
        Scan.DEVICE_ID: "dev-1",
        Scan.DEMO: False,
        Scan.COUNTRY: "United States",
        Scan.STATUS: "complete",
        Scan.CREATED_AT: "2026-09-01T00:00:00Z",
        Scan.NORM: {
            "generic_name": "levothyroxine sodium",
            "strength": "200 mcg",
            "lot": "D2402430",
            "ndc9": "167290457",
            "ndc_raw": "16729-0457-15",
            "manufacturer": "Accord Healthcare",
        },
        Scan.RESEARCH: {
            "verdict": "recall_match",
            "next_steps": ["Set this bottle aside.", "Take it to a pharmacist."],
        },
        Scan.EVIDENCE: {
            "evidence_pack": {
                "exact_lot_hits": [
                    {
                        "record_id": "fda-enf-D-0785-2026",
                        "match_kind": "exact_lot",
                        "source_org": "FDA",
                        "title": "Class II recall: Levothyroxine Sodium Tablets, USP, 200 mcg",
                        "recency_date": "2026-09-02T00:00:00Z",
                        "severity": "high",
                        "url": "https://api.fda.gov/drug/enforcement.json?search=recall_number:%22D-0785-2026%22",
                    }
                ]
            }
        },
    }
    doc.update(overrides)
    return doc


def _uncorroborated_scan_doc(**overrides: Any) -> dict[str, Any]:
    """One scan whose lot string only collides with an unrelated product's record."""
    doc: dict[str, Any] = {
        Scan.SCAN_ID: "scan-uncorroborated",
        Scan.DEVICE_ID: "dev-1",
        Scan.DEMO: False,
        Scan.COUNTRY: "Nigeria",
        Scan.STATUS: "complete",
        Scan.CREATED_AT: "2026-08-01T00:00:00Z",
        Scan.NORM: {
            "generic_name": "chlorpromazine",
            "strength": "100 mg",
            "lot": "Z400069",
            "ndc9": "111110001",
            "manufacturer": "Some Maker",
        },
        Scan.RESEARCH: {
            "verdict": "insufficient_evidence",
            "next_steps": ["should not be used"],
        },
        Scan.EVIDENCE: {
            "evidence_pack": {
                "exact_lot_hits": [
                    {
                        "record_id": "nafdac-17970",
                        "match_kind": "lot_only_match",
                        "source_org": "NAFDAC",
                        "title": "Alert about an unrelated product",
                        "recency_date": "2025-01-01T00:00:00Z",
                    }
                ]
            }
        },
    }
    doc.update(overrides)
    return doc


def _falsified_scan_doc(**overrides: Any) -> dict[str, Any]:
    """A falsified-product alert names a manufacturer only as the victim on the label."""
    doc: dict[str, Any] = {
        Scan.SCAN_ID: "scan-falsified",
        Scan.DEVICE_ID: "dev-1",
        Scan.DEMO: False,
        Scan.COUNTRY: "Cameroon",
        Scan.STATUS: "complete",
        Scan.CREATED_AT: "2026-03-01T00:00:00Z",
        Scan.NORM: {
            "generic_name": "healmoxy",
            "strength": "500 mg",
            "lot": "H02605",
            "ndc9": "222220002",
        },
        Scan.RESEARCH: {
            "verdict": "recall_match",
            "next_steps": ["Set this bottle aside.", "Ask a pharmacist."],
        },
        Scan.EVIDENCE: {
            "evidence_pack": {
                "exact_lot_hits": [
                    {
                        "record_id": "who-mpa-healmoxy",
                        "match_kind": "exact_lot",
                        "source_org": "WHO",
                        "title": "Medical Product Alert: Falsified HEALMOXY",
                        "recency_date": "2025-03-01T00:00:00Z",
                        "doc_type": "falsified_alert",
                        "manufacturer": "Maxheal Pharmaceuticals",
                    }
                ]
            }
        },
    }
    doc.update(overrides)
    return doc


async def test_a_lot_with_an_alert_edge_gets_the_recall_badge_the_owning_scans_next_steps_and_its_records_as_sources() -> None:
    ctx = Ctx(scan_docs=[_alert_scan_doc()])

    detail = await node_detail(ctx, "lot:D2402430", device_id="dev-1")

    assert detail.type == "lot"
    assert detail.title == "Lot D2402430"
    assert detail.subtitle == "Read from the label of one of your scans"
    assert "Named in a recall" in detail.badges
    assert detail.next_steps == ["Set this bottle aside.", "Take it to a pharmacist."]
    assert [source.id for source in detail.sources] == ["rec:fda-enf-D-0785-2026"]
    assert detail.sources[0].source_org == "FDA"
    assert any(p.key == "lot" and p.value == "D2402430" for p in detail.properties)
    assert any(p.key == "records" and p.value == "1" for p in detail.properties)
    assert detail.counts["alert"] >= 1


async def test_a_lot_with_only_uncorroborated_hits_says_so_and_offers_no_next_steps() -> None:
    ctx = Ctx(scan_docs=[_uncorroborated_scan_doc()])

    detail = await node_detail(ctx, "lot:Z400069", device_id="dev-1")

    assert detail.badges == ["Lot string seen elsewhere — not corroborated"]
    assert detail.next_steps == []
    assert "unconfirmed" in (detail.body or "")
    assert "Named in a recall" not in detail.badges


async def test_a_manufacturer_reached_only_as_a_stated_manufacturer_is_described_as_the_name_on_the_label() -> None:
    ctx = Ctx(scan_docs=[_falsified_scan_doc()])

    detail = await node_detail(ctx, "mfr:maxheal pharmaceuticals", device_id="dev-1")

    assert detail.type == "manufacturer"
    assert detail.subtitle == "Name printed on the label"
    assert "victim" in (detail.body or "")
    haystack = " ".join([detail.subtitle or "", detail.body or ""]).lower()
    for word in BANNED_WORDS:
        assert word not in haystack


async def test_linked_mentions_put_alert_links_first_and_caption_every_link_kind() -> None:
    ctx = Ctx(scan_docs=[_alert_scan_doc()])

    detail = await node_detail(ctx, "lot:D2402430", device_id="dev-1")

    assert detail.backlinks, "expected at least one linked mention"
    assert detail.backlinks[0].type == "record"
    assert detail.backlinks[0].relation == RELATION_LABELS["exact_lot"]

    # Every LinkKind the contract defines has a plain-language caption.
    link_kinds = get_args(graph_models.LinkKind)
    assert link_kinds, "models.LinkKind should not be empty"
    for kind in link_kinds:
        assert kind in RELATION_LABELS, f"RELATION_LABELS is missing a caption for {kind!r}"
        assert RELATION_LABELS[kind]


async def test_a_node_outside_the_personal_graph_falls_back_to_a_titled_context_note() -> None:
    ctx = Ctx(scan_docs=[_alert_scan_doc()])

    detail = await node_detail(ctx, "lot:doesnotexist", device_id="dev-1")

    assert detail.title == "doesnotexist"
    assert detail.notice
    assert "context" in detail.notice.lower()
    assert any(p.key == "id" and p.value == "lot:doesnotexist" for p in detail.properties)


# --------------------------------------------------------------------------- generic


async def test_unknown_node_types_get_a_generic_detail_from_the_id() -> None:
    detail = await node_detail(Ctx(), "med:levothyroxine", device_id=None)

    assert detail.type == "medicine"
    assert detail.id == "med:levothyroxine"
    assert detail.title == "Levothyroxine"
    assert any(p.key == "id" and p.value == "med:levothyroxine" for p in detail.properties)


async def test_a_malformed_or_unknown_prefix_404s() -> None:
    with pytest.raises(KnowledgeError) as excinfo:
        await node_detail(Ctx(), "not-a-real-id", device_id=None)
    assert excinfo.value.status_code == 404

    with pytest.raises(KnowledgeError):
        await node_detail(Ctx(), "zzz:something", device_id=None)


# --------------------------------------------------------------------------- wording


async def test_wording_never_uses_the_banned_assurance_words() -> None:
    # Every string detail.py/licensing.py author themselves — not data that
    # merely passed through them (a stored report has its own guardrails
    # tested elsewhere; this is about copy this module is responsible for).
    import backend.graph.detail as detail_module
    import backend.graph.licensing as licensing_module

    haystack = " ".join(
        [
            detail_module.DEFAULT_NOTICE,
            detail_module.DEFAULT_RECORD_NEXT_STEP,
            detail_module.CONTEXT_NOTICE,
            *detail_module.VERDICT_LABELS.values(),
            *detail_module.RELATION_LABELS.values(),
            *detail_module.SUBTITLES.values(),
            *detail_module.BADGES.values(),
            *detail_module.BODY_TEXT.values(),
            *detail_module.PROPERTY_LABELS.values(),
            *licensing_module.ATTRIBUTION.values(),
            licensing_module.DEFAULT_ATTRIBUTION,
            *licensing_module.LINK_LABEL.values(),
            licensing_module.DEFAULT_LINK_LABEL,
        ]
    ).lower()
    for word in BANNED_WORDS:
        assert word not in haystack, f"banned word {word!r} leaked into detail/licensing copy"
    # No positive/assurance framing either ("low risk", "all clear").
    for phrase in ("low risk", "all clear"):
        assert phrase not in haystack, f"banned phrase {phrase!r} leaked into detail/licensing copy"


async def test_generic_detail_title_and_scan_badges_avoid_the_banned_words_too() -> None:
    scan_detail = await node_detail(
        Ctx(scans=FakeScans({"scan-1": _scan_doc()})), "scan:scan-1", device_id="dev-1"
    )
    generic_detail = await node_detail(Ctx(), "mfr:accord-healthcare", device_id=None)
    haystack = " ".join([scan_detail.subtitle or "", *scan_detail.badges, generic_detail.title]).lower()
    for word in BANNED_WORDS:
        assert word not in haystack
