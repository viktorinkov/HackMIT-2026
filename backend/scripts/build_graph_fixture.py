"""Authoring aid: writes the four committed graph fixtures and validates them.

Run from `backend/` with `uv run python <this file>`. The content is hand-written
below; this script only keeps the JSON consistent and model-valid.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.graph.models import (
    ExpandResponse,
    GraphResponse,
    NodeDetail,
    SearchGraphResponse,
    clip_label,
)

OUT = Path(__file__).resolve().parents[1] / "src" / "backend" / "graph" / "fixtures"
DEVICE = "peel-graph-demo"
INDEX_DATE = "2026-09-19"
NOTICE = (
    "Peel checks published records only. It cannot tell you what is inside a tablet — "
    "if anything looks or feels wrong, ask a pharmacist."
)

FDA_LINK_LABEL = "openFDA record (JSON)"
WHO_ATTRIBUTION = "World Health Organization, CC BY-NC-SA 3.0 IGO"
NAFDAC_ATTRIBUTION = "NAFDAC Nigeria — summarised and linked"
FDA_ATTRIBUTION = "U.S. Food and Drug Administration (openFDA), public domain"

RECALL_NEXT_STEPS = [
    "Set this medicine aside in its original packaging and keep the packaging.",
    "Take the bottle and this result to a pharmacist promptly and ask them to compare "
    "the lot number on the label with the recall notice.",
    "Ask the pharmacist what to do next before you change anything about how you take it.",
]
CONTEXT_NEXT_STEP = "Shown for context. This record does not name the lot on your label."

REC_LEVO = "rec:fda-enf-D-0785-2026"
REC_CHLOR = "rec:fda-enf-D-0361-2025"
REC_NAFDAC_VARIOUS = "rec:nafdac-17970"
REC_WHO_HEALMOXY = "rec:who-mpa-f2d738e5-8445-45ab-9dc4-10bcb4f0afcd"
REC_NAFDAC_HEALMOXY = "rec:nafdac-18658"

URL_LEVO = "https://api.fda.gov/drug/enforcement.json?search=recall_number:%22D-0785-2026%22"
URL_CHLOR = "https://api.fda.gov/drug/enforcement.json?search=recall_number:%22D-0361-2025%22"
URL_NAFDAC_VARIOUS = (
    "https://nafdac.gov.ng/public-alert-no-11-2025-recall-of-various-products-by-sun-pharma-"
    "glenmark-and-zydus-pharmaceuticals-over-manufacturing-issues/"
)
URL_WHO_HEALMOXY = (
    "https://www.who.int/news/item/23-04-2025-medical-product-alert-n-2-2025--falsified-"
    "healmoxy-(amoxicillin)-capsules-500mg"
)
URL_NAFDAC_HEALMOXY = (
    "https://nafdac.gov.ng/public-alert-no-17-2025-alert-on-falsified-batches-of-healmoxy-"
    "capsules-500mg-found-in-cameroon-and-central-african-republic-car/"
)
WEB_WHO = "web:62a8176ee4a9b3b015e7d3df9fc32aec"
WEB_NAFDAC = "web:c11b7a335f8a05143ffb6a1de847bd43"
PILLREF_TEMAZEPAM = "pillref:471fa2f1-73a0-49be-89f3-d3e2cfdaeca0-0603-5892-0"

SCAN_LEVO = "scan:demo-levo-d2402430"
SCAN_LEVO_SIB = "scan:demo-levo-d2402999"
SCAN_CHLOR = "scan:demo-chlorpromazine-z400069"
SCAN_HEALMOXY = "scan:demo-healmoxy-h02605"
SCAN_IBU = "scan:demo-ibuprofen-i2"
SCAN_MISMATCH = "scan:demo-ibuprofen-5892v"

# Crowd reports. Every seller here is invented and says so; the cities and
# countries are real ones that match the scan they hang off. A report is one
# person's account of a purchase, so none of these edges is ever strong and
# none of them ever alerts, whatever the scan's verdict says.
PLACE_COLUMBUS = "place:columbus|ohio|united-states"
PLACE_DOUALA = "place:douala|littoral|cameroon"
PLACE_BOSTON = "place:boston|massachusetts|united-states"
SELLER_RIVERSIDE = "seller:riverside demo pharmacy|columbus|ohio|united-states"
SELLER_MARCHE = "seller:pharmacie du marché demo|douala|littoral|cameroon"
CROWD_RIVERSIDE = f"cluster:{SELLER_RIVERSIDE}|reports"

REPORT_BODY = (
    "This comes from a report you filed. Peel has not checked it, and it says nothing "
    "about what the seller did."
)

nodes: list[dict] = []
links: list[dict] = []


def node(node_id: str, node_type: str, label: str, **kwargs) -> dict:
    doc = {"id": node_id, "type": node_type, "label": clip_label(label)}
    doc.update(kwargs)
    nodes.append(doc)
    return doc


def link(source: str, kind: str, target: str, **kwargs) -> dict:
    doc = {"id": f"{source}>{kind}>{target}", "source": source, "target": target, "kind": kind}
    doc.update(kwargs)
    links.append(doc)
    return doc


def strong(source: str, kind: str, target: str, weight: float, **kwargs) -> dict:
    return link(source, kind, target, strong=True, weight=weight, **kwargs)


def weak(source: str, kind: str, target: str, weight: float, **kwargs) -> dict:
    return link(source, kind, target, strong=False, weight=weight, **kwargs)


# --------------------------------------------------------------------------- scans

node(
    SCAN_LEVO,
    "scan",
    "Levothyroxine 200 mcg",
    sublabel="Scanned 18 Sep 2026",
    val=3.4,
    personal=True,
    expandable=True,
    date="2026-09-18T09:12:00Z",
    verdict="recall_match",
    risk_level="high",
    status="complete",
    demo=True,
    scan_ids=[SCAN_LEVO],
    attrs={
        "headline": "A recall names this lot number.",
        "verdict_label": "A recall or alert names this lot",
        "expired": False,
        "gaps_n": 1,
        "hardware": {
            "status": "substandard",
            "degraded": True,
            "simulated": True,
            "model": "mock-spectrometry",
        },
        "lot": "D2402430",
        "ndc9": "167290457",
    },
)
node(
    SCAN_LEVO_SIB,
    "scan",
    "Levothyroxine 200 mcg",
    sublabel="Scanned 18 Sep 2026",
    val=3.0,
    personal=True,
    expandable=True,
    date="2026-09-18T09:20:00Z",
    verdict="no_adverse_findings",
    risk_level="low",
    status="complete",
    demo=True,
    scan_ids=[SCAN_LEVO_SIB],
    attrs={
        "headline": "No recall names this lot number.",
        "verdict_label": "Nothing found in the records searched",
        "expired": False,
        "gaps_n": 1,
        "hardware": {
            "status": "real",
            "degraded": False,
            "simulated": True,
            "model": "mock-spectrometry",
        },
        "lot": "D2402999",
        "ndc9": "167290457",
    },
)
node(
    SCAN_CHLOR,
    "scan",
    "Chlorpromazine 10 mg",
    sublabel="Scanned 12 Sep 2026",
    val=3.4,
    personal=True,
    expandable=True,
    date="2026-09-12T18:40:00Z",
    verdict="recall_match",
    risk_level="high",
    status="complete",
    demo=True,
    scan_ids=[SCAN_CHLOR],
    attrs={
        "headline": "A recall names this lot number.",
        "verdict_label": "A recall or alert names this lot",
        "expired": False,
        "gaps_n": 1,
        "hardware": {
            "status": "real",
            "degraded": False,
            "simulated": True,
            "model": "mock-spectrometry",
        },
        "lot": "Z400069",
        "ndc9": "707101129",
    },
)
node(
    SCAN_HEALMOXY,
    "scan",
    "Healmoxy amoxicillin 500 mg",
    sublabel="Scanned 8 Sep 2026 · Cameroon",
    val=3.6,
    personal=True,
    expandable=True,
    date="2026-09-08T11:05:00Z",
    verdict="recall_match",
    risk_level="high",
    status="complete",
    demo=True,
    scan_ids=[SCAN_HEALMOXY],
    attrs={
        "headline": "Two regulators name this batch number.",
        "verdict_label": "A recall or alert names this lot",
        "expired": False,
        "gaps_n": 2,
        "hardware": {
            "status": "fake",
            "degraded": True,
            "simulated": True,
            "model": "mock-spectrometry",
        },
        "lot": "H02605",
    },
)
node(
    SCAN_IBU,
    "scan",
    "Ibuprofen 200 mg",
    sublabel="Scanned 3 Sep 2026",
    val=2.8,
    personal=True,
    expandable=True,
    date="2026-09-03T08:30:00Z",
    verdict="no_adverse_findings",
    risk_level="low",
    status="complete",
    demo=True,
    scan_ids=[SCAN_IBU],
    attrs={
        "headline": "No recall or alert was found in the records searched.",
        "verdict_label": "Nothing found in the records searched",
        "expired": False,
        "gaps_n": 2,
        "hardware": {
            "status": "real",
            "degraded": False,
            "simulated": True,
            "model": "mock-spectrometry",
        },
        "imprint": "I2",
    },
)
node(
    SCAN_MISMATCH,
    "scan",
    "Ibuprofen 200 mg",
    sublabel="Scanned 31 Aug 2026",
    val=3.2,
    personal=True,
    expandable=True,
    date="2026-08-31T20:15:00Z",
    verdict="mismatch_found",
    risk_level="medium",
    status="complete",
    demo=True,
    scan_ids=[SCAN_MISMATCH],
    attrs={
        "headline": "The imprint on the tablet does not match the label.",
        "verdict_label": "The label and the reference do not agree",
        "expired": True,
        "gaps_n": 2,
        "hardware": {
            "status": "real",
            "degraded": False,
            "simulated": True,
            "model": "mock-spectrometry",
        },
        "imprint": "5892V",
    },
)

# --------------------------------------------------------------------------- medicines

node("med:levothyroxine", "medicine", "Levothyroxine", val=2.6, personal=True, expandable=True,
     count=2, attrs={"aliases": ["levothyroxine sodium"], "brand": False})
node("med:chlorpromazine", "medicine", "Chlorpromazine", val=2.2, personal=True, expandable=True,
     count=1, attrs={"aliases": ["chlorpromazine hydrochloride"], "brand": False})
node("med:amoxicillin", "medicine", "Amoxicillin", val=2.2, personal=True, expandable=True,
     count=1, attrs={"aliases": ["amoxicillin"], "brand": False})
node("med:healmoxy", "medicine", "HEALMOXY", sublabel="brand name on the label", val=2.0,
     personal=True, expandable=True, count=1, attrs={"aliases": ["healmoxy"], "brand": True})
node("med:ibuprofen", "medicine", "Ibuprofen", val=2.4, personal=True, expandable=True,
     count=2, attrs={"aliases": ["ibuprofen"], "brand": False})
node("med:temazepam", "medicine", "Temazepam", sublabel="from the imprint, not the label",
     val=2.0, personal=True, expandable=True, count=1,
     attrs={"aliases": ["temazepam"], "brand": False})

# --------------------------------------------------------------------------- products

node("product:167290457", "product", "Levothyroxine 200 mcg · Accord", val=2.4, personal=True,
     expandable=True, count=2,
     attrs={"product_ndc": "16729-457", "dosage_form": "tablet", "listing_expired": False})
node("product:707101129", "product", "Chlorpromazine 10 mg · Zydus", val=2.2, personal=True,
     expandable=True, count=1,
     attrs={"product_ndc": "70710-1129", "dosage_form": "tablet", "listing_expired": False})

# --------------------------------------------------------------------------- lots

node("lot:D2402430", "lot", "Lot D2402430", sublabel="on your levothyroxine bottle", val=2.6,
     personal=True, expandable=True, scan_ids=[SCAN_LEVO], attrs={"lot": "D2402430"})
node("lot:D2402999", "lot", "Lot D2402999", sublabel="on your second levothyroxine bottle",
     val=2.2, personal=True, expandable=True, scan_ids=[SCAN_LEVO_SIB],
     attrs={"lot": "D2402999"})
node("lot:Z400069", "lot", "Lot Z400069", sublabel="on your chlorpromazine bottle", val=2.6,
     personal=True, expandable=True, scan_ids=[SCAN_CHLOR], attrs={"lot": "Z400069"})
node("lot:H02605", "lot", "Lot H02605", sublabel="on your amoxicillin pack", val=2.8,
     personal=True, expandable=True, scan_ids=[SCAN_HEALMOXY], attrs={"lot": "H02605"})

# --------------------------------------------------------------------------- manufacturers

node("mfr:accord healthcare", "manufacturer", "Accord Healthcare", val=2.8, personal=True,
     expandable=True, count=2,
     attrs={"variants": ["Accord Healthcare Inc.", "ACCORD HEALTHCARE, INC."]})
node("mfr:zydus pharmaceuticals", "manufacturer", "Zydus Pharmaceuticals", val=2.2,
     personal=True, expandable=True, count=1,
     attrs={"variants": ["Zydus Pharmaceuticals (USA) Inc."]})
node("mfr:maxheal pharmaceuticals", "manufacturer", "Maxheal Pharmaceuticals",
     sublabel="name printed on the label", val=2.4, personal=True, expandable=True, count=2,
     attrs={
         "variants": [
             "MAXHEAL PHARMACEUTICALS (India) Limited",
             "Maxheal Pharmaceuticals (India), with batch numbers 023011 and H02605, "
             "found in Cameroon and H02605 in the Central African Republic (CAR)",
         ],
         "stated_only": True,
     })

# --------------------------------------------------------------------------- records

node(REC_LEVO, "record", "Class II recall: Levothyroxine 200 mcg",
     sublabel="FDA · 2 Sep 2026 · Subpotent Drug", val=3.2, personal=True, expandable=True,
     date="2026-09-02T00:00:00Z", url=URL_LEVO, severity="high", source_org="FDA",
     freshness="this_month", match_tier="match", scan_ids=[SCAN_LEVO, SCAN_LEVO_SIB],
     attrs={"doc_type": "recall", "lot_count": 4, "covers_all_lots": False, "age_days": 17,
            "event_id": "99584", "classification_raw": "Class II",
            "link_label": FDA_LINK_LABEL})
node(REC_CHLOR, "record", "Class II recall: Chlorpromazine 10 mg",
     sublabel="FDA · 16 Apr 2025 · Nitrosamine impurity", val=3.0, personal=True,
     expandable=True, date="2025-04-16T00:00:00Z", url=URL_CHLOR, severity="high",
     source_org="FDA", freshness="older", match_tier="match", scan_ids=[SCAN_CHLOR],
     attrs={"doc_type": "recall", "lot_count": 1, "covers_all_lots": False, "age_days": 521,
            "event_id": "96626", "classification_raw": "Class II",
            "link_label": FDA_LINK_LABEL})
node(REC_NAFDAC_VARIOUS, "record", "NAFDAC 11/2025: various product recall",
     sublabel="NAFDAC · 29 Apr 2025 · lot number only", val=2.4, personal=True, expandable=True,
     date="2025-04-29T15:25:16Z", url=URL_NAFDAC_VARIOUS, severity="high", source_org="NAFDAC",
     freshness="older", match_tier="context", scan_ids=[SCAN_CHLOR],
     attrs={"doc_type": "recall", "lot_count": 1, "covers_all_lots": False, "age_days": 508,
            "attribution": NAFDAC_ATTRIBUTION,
            "uncorroborated": "This record does not name your product."})
node(REC_WHO_HEALMOXY, "record", "WHO N°2/2025: Falsified HEALMOXY",
     sublabel="WHO · 23 Apr 2025 · falsified product", val=3.4, personal=True, expandable=True,
     date="2025-04-23T08:46:11Z", url=URL_WHO_HEALMOXY, severity="critical", source_org="WHO",
     freshness="older", match_tier="match", scan_ids=[SCAN_HEALMOXY],
     attrs={"doc_type": "falsified_alert", "lot_count": 3, "covers_all_lots": False,
            "age_days": 514, "attribution": WHO_ATTRIBUTION})
node(REC_NAFDAC_HEALMOXY, "record", "NAFDAC 17/2025: Falsified Healmoxy",
     sublabel="NAFDAC · 1 Jun 2025 · falsified product", val=3.2, personal=True,
     expandable=True, date="2025-06-01T00:38:19Z", url=URL_NAFDAC_HEALMOXY, severity="critical",
     source_org="NAFDAC", freshness="older", match_tier="match", scan_ids=[SCAN_HEALMOXY],
     attrs={"doc_type": "falsified_alert", "lot_count": 3, "covers_all_lots": False,
            "age_days": 475, "attribution": NAFDAC_ATTRIBUTION})

# --------------------------------------------------------------------------- regulators

node("reg:fda", "regulator", "FDA", sublabel="U.S. Food and Drug Administration", val=4.0,
     personal=True, expandable=True, count=17963, source_org="FDA",
     attrs={"seeded": True, "attribution": FDA_ATTRIBUTION})
node("reg:who", "regulator", "WHO", sublabel="World Health Organization", val=3.6,
     personal=True, expandable=True, count=83, source_org="WHO",
     attrs={"seeded": True, "attribution": WHO_ATTRIBUTION})
node("reg:nafdac", "regulator", "NAFDAC", sublabel="Nigeria", val=3.6, personal=True,
     expandable=True, count=403, source_org="NAFDAC",
     attrs={"seeded": True, "attribution": NAFDAC_ATTRIBUTION})

# --------------------------------------------------------------------------- countries

node("country:united-states", "country", "United States", val=1.8, personal=True,
     expandable=True, count=3)
node("country:cameroon", "country", "Cameroon", val=1.8, personal=True, expandable=True, count=3)
node("country:central-african-republic", "country", "Central African Republic", val=1.6,
     personal=True, expandable=True, count=2)
node("country:nigeria", "country", "Nigeria", val=1.6, personal=True, expandable=True, count=2)
node("country:india", "country", "India", val=1.6, personal=True, expandable=True, count=3)

# --------------------------------------------------------------------------- web pages

node(WEB_WHO, "web_page", "WHO alert page: HEALMOXY", sublabel="who.int", val=1.6,
     personal=True, expandable=True, url=URL_WHO_HEALMOXY, date="2025-04-23T08:46:11Z",
     source_org="WHO", freshness="older", scan_ids=[SCAN_HEALMOXY],
     attrs={"domain": "who.int", "source_tier": "regulator", "flags": ["falsified"],
            "attribution": WHO_ATTRIBUTION})
node(WEB_NAFDAC, "web_page", "NAFDAC alert page: Healmoxy", sublabel="nafdac.gov.ng", val=1.6,
     personal=True, expandable=True, url=URL_NAFDAC_HEALMOXY, date="2025-06-01T00:38:19Z",
     source_org="NAFDAC", freshness="older", scan_ids=[SCAN_HEALMOXY],
     attrs={"domain": "nafdac.gov.ng", "source_tier": "regulator", "flags": ["falsified"],
            "attribution": NAFDAC_ATTRIBUTION})

# --------------------------------------------------------------------------- imprints / pills

node("imprint:I2", "imprint", "Imprint I2", val=1.8, personal=True, expandable=True,
     scan_ids=[SCAN_IBU], attrs={"rung": 1, "shape_relaxed": False, "candidates_n": 3})
node("imprint:5892V", "imprint", "Imprint 5892 V", val=2.0, personal=True, expandable=True,
     scan_ids=[SCAN_MISMATCH], attrs={"rung": 1, "shape_relaxed": False, "candidates_n": 1})
node(PILLREF_TEMAZEPAM, "pill_ref", "Temazepam 15 mg · Qualitest", val=1.6, personal=True,
     attrs={"match_kind": "imprint_exact", "shape": "capsule", "colors": ["pink"],
            "product_ndc": "0603-5892"})

# --------------------------------------------------------------------------- topics

node("topic:subpotent", "topic", "Subpotent", val=1.8, personal=True, expandable=True, count=1)
node("topic:impurity-nitrosamine", "topic", "Impurity", val=1.8, personal=True, expandable=True,
     count=1)
node("topic:falsified", "topic", "Falsified product", val=2.0, personal=True, expandable=True,
     count=2)

# --------------------------------------------------------------------------- reports

node(SELLER_RIVERSIDE, "seller", "Riverside Demo Pharmacy",
     sublabel="Columbus, United States", val=2.4, personal=True, expandable=True, count=2,
     date="2026-09-02", demo=True, scan_ids=[SCAN_LEVO, SCAN_LEVO_SIB],
     attrs={"reports": 2, "first_purchased_on": "2026-08-20",
            "last_purchased_on": "2026-09-02", "city": "Columbus", "region": "Ohio",
            "country": "United States", "variants": ["Riverside Demo Pharmacy"]})
node(SELLER_MARCHE, "seller", "Pharmacie du Marché Demo",
     sublabel="Douala, Cameroon", val=2.4, personal=True, expandable=True, count=1,
     date="2026-08-30", demo=True, scan_ids=[SCAN_HEALMOXY],
     attrs={"reports": 1, "first_purchased_on": "2026-08-30",
            "last_purchased_on": "2026-08-30", "city": "Douala", "region": "Littoral",
            "country": "Cameroon", "variants": ["Pharmacie du Marché Demo"]})
node(PLACE_COLUMBUS, "place", "Columbus, United States", val=1.8, personal=True, count=2,
     date="2026-09-02", demo=True, scan_ids=[SCAN_LEVO, SCAN_LEVO_SIB],
     attrs={"reports": 2, "first_purchased_on": "2026-08-20",
            "last_purchased_on": "2026-09-02", "city": "Columbus", "region": "Ohio",
            "country": "United States"})
node(PLACE_DOUALA, "place", "Douala, Cameroon", val=1.8, personal=True, count=1,
     date="2026-08-30", demo=True, scan_ids=[SCAN_HEALMOXY],
     attrs={"reports": 1, "first_purchased_on": "2026-08-30",
            "last_purchased_on": "2026-08-30", "city": "Douala", "region": "Littoral",
            "country": "Cameroon"})
# A report that named a town but no shop: the scan reaches the place directly.
node(PLACE_BOSTON, "place", "Boston, United States", val=1.6, personal=True, count=1,
     date="2026-08-28", demo=True, scan_ids=[SCAN_IBU],
     attrs={"reports": 1, "first_purchased_on": "2026-08-28",
            "last_purchased_on": "2026-08-28", "city": "Boston", "region": "Massachusetts",
            "country": "United States"})

# --------------------------------------------------------------------------- clusters

# Counts only, and only counts the live code can publish: four other people, of
# whom two scanned something with a finding and two did not. A split with a
# group of one on either side is suppressed (`expand._publishable_flagged`), so
# a fixture must not show one either.
node(CROWD_RIVERSIDE, "cluster", "Named by 4 other people", val=1.2, count=4,
     expandable=False, demo=True,
     attrs={"relation": "reports", "parent": SELLER_RIVERSIDE, "count": 4, "flagged": 2})
node("cluster:reg:fda|records", "cluster", "+17,961 more FDA records", val=1.4, count=17961,
     expandable=True, attrs={"relation": "records", "parent": "reg:fda"})
node("cluster:reg:who|records", "cluster", "+82 more WHO records", val=1.2, count=82,
     expandable=True, attrs={"relation": "records", "parent": "reg:who"})
node(f"cluster:{REC_LEVO}|lots", "cluster", "+3 more lots in this recall", val=1.2, count=3,
     expandable=True, attrs={"relation": "lots", "parent": REC_LEVO})

# =========================================================================== links

# (a) levothyroxine 200 mcg, lot D2402430 -> the FDA recall
strong(SCAN_LEVO, "names", "med:levothyroxine", 0.8, scan_ids=[SCAN_LEVO])
strong(SCAN_LEVO, "labelled_ndc", "product:167290457", 0.8, scan_ids=[SCAN_LEVO])
strong(SCAN_LEVO, "labelled_lot", "lot:D2402430", 0.8, scan_ids=[SCAN_LEVO])
strong(SCAN_LEVO, "labelled_maker", "mfr:accord healthcare", 0.6, scan_ids=[SCAN_LEVO])
weak(SCAN_LEVO, "scanned_in", "country:united-states", 0.1, scan_ids=[SCAN_LEVO])
strong("lot:D2402430", "exact_lot", REC_LEVO, 1.0, alert=True, match_kind="exact_lot",
       scan_ids=[SCAN_LEVO])

# (b) the sibling bottle: same NDC, lot D2402999, no alert anywhere
strong(SCAN_LEVO_SIB, "names", "med:levothyroxine", 0.8, scan_ids=[SCAN_LEVO_SIB])
strong(SCAN_LEVO_SIB, "labelled_ndc", "product:167290457", 0.8, scan_ids=[SCAN_LEVO_SIB])
strong(SCAN_LEVO_SIB, "labelled_lot", "lot:D2402999", 0.8, scan_ids=[SCAN_LEVO_SIB])
strong(SCAN_LEVO_SIB, "labelled_maker", "mfr:accord healthcare", 0.6, scan_ids=[SCAN_LEVO_SIB])
weak(SCAN_LEVO_SIB, "scanned_in", "country:united-states", 0.1, scan_ids=[SCAN_LEVO_SIB])
# The same record node, reached weakly from the product line by both bottles.
weak("product:167290457", "ndc_in_description", REC_LEVO, 0.5, match_kind="ndc_in_description",
     count=2, scan_ids=[SCAN_LEVO, SCAN_LEVO_SIB])
strong("product:167290457", "contains", "med:levothyroxine", 0.6, count=2,
       scan_ids=[SCAN_LEVO, SCAN_LEVO_SIB])
strong("product:167290457", "registered_to", "mfr:accord healthcare", 0.6, count=2,
       scan_ids=[SCAN_LEVO, SCAN_LEVO_SIB])
strong(REC_LEVO, "issued_by", "reg:fda", 0.5)
strong(REC_LEVO, "about", "med:levothyroxine", 0.5)
strong(REC_LEVO, "names_maker", "mfr:accord healthcare", 0.5)
strong(REC_LEVO, "affects", "country:united-states", 0.3)
weak(REC_LEVO, "topic", "topic:subpotent", 0.2)
weak(REC_LEVO, "more", f"cluster:{REC_LEVO}|lots", 0.1)

# (c) chlorpromazine: one exact lot match and one lot-string-only match
strong(SCAN_CHLOR, "names", "med:chlorpromazine", 0.8, scan_ids=[SCAN_CHLOR])
strong(SCAN_CHLOR, "labelled_ndc", "product:707101129", 0.8, scan_ids=[SCAN_CHLOR])
strong(SCAN_CHLOR, "labelled_lot", "lot:Z400069", 0.8, scan_ids=[SCAN_CHLOR])
strong(SCAN_CHLOR, "labelled_maker", "mfr:zydus pharmaceuticals", 0.6, scan_ids=[SCAN_CHLOR])
weak(SCAN_CHLOR, "scanned_in", "country:united-states", 0.1, scan_ids=[SCAN_CHLOR])
strong("product:707101129", "contains", "med:chlorpromazine", 0.6, scan_ids=[SCAN_CHLOR])
strong("product:707101129", "registered_to", "mfr:zydus pharmaceuticals", 0.6,
       scan_ids=[SCAN_CHLOR])
strong("lot:Z400069", "exact_lot", REC_CHLOR, 1.0, alert=True, match_kind="exact_lot",
       scan_ids=[SCAN_CHLOR])
weak("lot:Z400069", "lot_only_match", REC_NAFDAC_VARIOUS, 0.2, match_kind="lot_only_match",
     scan_ids=[SCAN_CHLOR])
strong(REC_CHLOR, "issued_by", "reg:fda", 0.5)
strong(REC_CHLOR, "about", "med:chlorpromazine", 0.5)
strong(REC_CHLOR, "names_maker", "mfr:zydus pharmaceuticals", 0.5)
strong(REC_CHLOR, "affects", "country:united-states", 0.3)
weak(REC_CHLOR, "topic", "topic:impurity-nitrosamine", 0.2)
strong(REC_NAFDAC_VARIOUS, "issued_by", "reg:nafdac", 0.5)
strong(REC_NAFDAC_VARIOUS, "affects", "country:nigeria", 0.3)
strong(REC_NAFDAC_VARIOUS, "affects", "country:united-states", 0.3)
strong(REC_NAFDAC_VARIOUS, "affects", "country:india", 0.3)

# (d) HEALMOXY: WHO and NAFDAC converge on one batch; the firm is only named
strong(SCAN_HEALMOXY, "names", "med:amoxicillin", 0.8, scan_ids=[SCAN_HEALMOXY])
strong(SCAN_HEALMOXY, "names", "med:healmoxy", 0.8, scan_ids=[SCAN_HEALMOXY])
strong("med:healmoxy", "brand_of", "med:amoxicillin", 0.6, scan_ids=[SCAN_HEALMOXY])
strong(SCAN_HEALMOXY, "labelled_lot", "lot:H02605", 0.8, scan_ids=[SCAN_HEALMOXY])
strong(SCAN_HEALMOXY, "labelled_maker", "mfr:maxheal pharmaceuticals", 0.6,
       scan_ids=[SCAN_HEALMOXY])
weak(SCAN_HEALMOXY, "scanned_in", "country:cameroon", 0.1, scan_ids=[SCAN_HEALMOXY])
strong("lot:H02605", "exact_lot", REC_WHO_HEALMOXY, 1.0, alert=True, match_kind="exact_lot",
       scan_ids=[SCAN_HEALMOXY])
strong("lot:H02605", "exact_lot", REC_NAFDAC_HEALMOXY, 1.0, alert=True, match_kind="exact_lot",
       scan_ids=[SCAN_HEALMOXY])
strong(REC_WHO_HEALMOXY, "issued_by", "reg:who", 0.5)
strong(REC_WHO_HEALMOXY, "about", "med:amoxicillin", 0.5)
strong(REC_WHO_HEALMOXY, "about", "med:healmoxy", 0.5)
link(REC_WHO_HEALMOXY, "stated_manufacturer", "mfr:maxheal pharmaceuticals", strong=False,
     weight=0.5)
strong(REC_WHO_HEALMOXY, "affects", "country:cameroon", 0.3)
strong(REC_WHO_HEALMOXY, "affects", "country:central-african-republic", 0.3)
strong(REC_WHO_HEALMOXY, "affects", "country:india", 0.3)
weak(REC_WHO_HEALMOXY, "topic", "topic:falsified", 0.2)
strong(REC_NAFDAC_HEALMOXY, "issued_by", "reg:nafdac", 0.5)
strong(REC_NAFDAC_HEALMOXY, "about", "med:healmoxy", 0.5)
link(REC_NAFDAC_HEALMOXY, "stated_manufacturer", "mfr:maxheal pharmaceuticals", strong=False,
     weight=0.5)
strong(REC_NAFDAC_HEALMOXY, "affects", "country:cameroon", 0.3)
strong(REC_NAFDAC_HEALMOXY, "affects", "country:central-african-republic", 0.3)
strong(REC_NAFDAC_HEALMOXY, "affects", "country:nigeria", 0.3)
strong(REC_NAFDAC_HEALMOXY, "affects", "country:india", 0.3)
weak(REC_NAFDAC_HEALMOXY, "topic", "topic:falsified", 0.2)
weak(SCAN_HEALMOXY, "fetched_for", WEB_WHO, 0.3, scan_ids=[SCAN_HEALMOXY])
weak(SCAN_HEALMOXY, "fetched_for", WEB_NAFDAC, 0.3, scan_ids=[SCAN_HEALMOXY])
strong(WEB_WHO, "lists_lot", "lot:H02605", 0.5, scan_ids=[SCAN_HEALMOXY])
strong(WEB_NAFDAC, "lists_lot", "lot:H02605", 0.5, scan_ids=[SCAN_HEALMOXY])
strong(WEB_WHO, "published_by", "reg:who", 0.4)
strong(WEB_NAFDAC, "published_by", "reg:nafdac", 0.4)

# (e) the clean ibuprofen scan
strong(SCAN_IBU, "names", "med:ibuprofen", 0.8, scan_ids=[SCAN_IBU])
strong(SCAN_IBU, "observed_imprint", "imprint:I2", 0.6, scan_ids=[SCAN_IBU])
weak(SCAN_IBU, "scanned_in", "country:united-states", 0.1, scan_ids=[SCAN_IBU])
strong("imprint:I2", "identifies_as", "med:ibuprofen", 0.6, match_kind="imprint_exact",
       scan_ids=[SCAN_IBU])

# (f) the mismatch scan
strong(SCAN_MISMATCH, "names", "med:ibuprofen", 0.8, scan_ids=[SCAN_MISMATCH])
strong(SCAN_MISMATCH, "observed_imprint", "imprint:5892V", 0.6, scan_ids=[SCAN_MISMATCH])
weak(SCAN_MISMATCH, "scanned_in", "country:united-states", 0.1, scan_ids=[SCAN_MISMATCH])
strong("imprint:5892V", "identifies_as", "med:temazepam", 0.6, match_kind="imprint_exact",
       scan_ids=[SCAN_MISMATCH])
weak("imprint:5892V", "related", PILLREF_TEMAZEPAM, 0.25, match_kind="imprint_exact",
     scan_ids=[SCAN_MISMATCH])
weak(PILLREF_TEMAZEPAM, "identifies_as", "med:temazepam", 0.25, scan_ids=[SCAN_MISMATCH])
strong("med:temazepam", "conflicts_with", "med:ibuprofen", 0.7, match_kind="imprint",
       scan_ids=[SCAN_MISMATCH])

# (g) what the person said about where the medicines came from. Never strong,
# never an alert, even on the two scans whose verdict is recall_match.
weak(SCAN_LEVO, "bought_from", SELLER_RIVERSIDE, 0.3, scan_ids=[SCAN_LEVO])
weak(SCAN_LEVO_SIB, "bought_from", SELLER_RIVERSIDE, 0.3, scan_ids=[SCAN_LEVO_SIB])
weak(SELLER_RIVERSIDE, "located_in", PLACE_COLUMBUS, 0.3, count=2,
     scan_ids=[SCAN_LEVO, SCAN_LEVO_SIB])
weak(PLACE_COLUMBUS, "located_in", "country:united-states", 0.3, count=2,
     scan_ids=[SCAN_LEVO, SCAN_LEVO_SIB])
weak(SCAN_HEALMOXY, "bought_from", SELLER_MARCHE, 0.3, scan_ids=[SCAN_HEALMOXY])
weak(SELLER_MARCHE, "located_in", PLACE_DOUALA, 0.3, scan_ids=[SCAN_HEALMOXY])
weak(PLACE_DOUALA, "located_in", "country:cameroon", 0.3, scan_ids=[SCAN_HEALMOXY])
weak(SCAN_IBU, "bought_in", PLACE_BOSTON, 0.3, scan_ids=[SCAN_IBU])
weak(PLACE_BOSTON, "located_in", "country:united-states", 0.3, scan_ids=[SCAN_IBU])
weak(SELLER_RIVERSIDE, "also_reported", CROWD_RIVERSIDE, 0.3, count=4)

# structure
weak("reg:fda", "more", "cluster:reg:fda|records", 0.1)
weak("reg:who", "more", "cluster:reg:who|records", 0.1)

counts: dict[str, int] = {}
for item in nodes:
    counts[item["type"]] = counts.get(item["type"], 0) + 1

graph = {
    "nodes": nodes,
    "links": links,
    "meta": {
        "device_id": DEVICE,
        "scans": 6,
        "generated_at": "2026-09-19T23:30:00Z",
        "source": "demo",
        "demo": True,
        "truncated": False,
        "index_date": INDEX_DATE,
        "notice": NOTICE,
        "counts": counts,
        "timeline": [
            {"year": 2025, "total": 3, "by_org": {"FDA": 1, "WHO": 1, "NAFDAC": 1}},
            {"year": 2026, "total": 1, "by_org": {"FDA": 1}},
        ],
    },
}

# =========================================================================== details


def prop(key: str, label: str, value: str) -> dict:
    return {"key": key, "label": label, "value": value}


def source(sid: str, title: str, url: str, org: str, published: str, attribution: str,
           link_label: str | None = None) -> dict:
    doc = {"id": sid, "title": title, "url": url, "source_org": org,
           "published_at": published, "attribution": attribution}
    if link_label:
        doc["link_label"] = link_label
    return doc


SRC_LEVO = source(REC_LEVO, "Class II recall: Levothyroxine Sodium Tablets, USP, 200 mcg",
                  URL_LEVO, "FDA", "2026-09-02", FDA_ATTRIBUTION, FDA_LINK_LABEL)
SRC_CHLOR = source(REC_CHLOR, "Class II recall: chlorproMAZINE Hydrochloride Tablets, USP 10 mg",
                   URL_CHLOR, "FDA", "2025-04-16", FDA_ATTRIBUTION, FDA_LINK_LABEL)
SRC_NAFDAC_VARIOUS = source(
    REC_NAFDAC_VARIOUS,
    "Public Alert No. 11/2025 – Recall of Various Products by Sun Pharma, Glenmark, and Zydus",
    URL_NAFDAC_VARIOUS, "NAFDAC", "2025-04-29", NAFDAC_ATTRIBUTION, "NAFDAC alert page")
SRC_WHO = source(
    REC_WHO_HEALMOXY,
    "Medical Product Alert N°2/2025: Falsified HEALMOXY (Amoxicillin) Capsules 500mg",
    URL_WHO_HEALMOXY, "WHO", "2025-04-23", WHO_ATTRIBUTION, "WHO alert page")
SRC_NAFDAC_HEALMOXY = source(
    REC_NAFDAC_HEALMOXY,
    "Public Alert No. 17/2025 – Alert on Falsified Batches of Healmoxy Capsules 500mg",
    URL_NAFDAC_HEALMOXY, "NAFDAC", "2025-06-01", NAFDAC_ATTRIBUTION, "NAFDAC alert page")


def backlink(node_id: str, node_type: str, label: str, relation: str,
             scan_id: str | None = None) -> dict:
    doc = {"node_id": node_id, "type": node_type, "label": label, "relation": relation}
    if scan_id:
        doc["scan_id"] = scan_id
    return doc


details: dict[str, dict] = {}


def detail(node_id: str, node_type: str, title: str, **kwargs) -> None:
    doc = {"id": node_id, "type": node_type, "title": title, "notice": NOTICE}
    doc.update(kwargs)
    details[node_id] = doc


detail(
    SCAN_LEVO, "scan", "Levothyroxine Sodium 200 mcg tablets",
    subtitle="Scanned 18 September 2026 · United States",
    badges=["A recall or alert names this lot", "Simulated hardware reading",
            "Hardware reading degraded"],
    properties=[
        prop("lot", "Lot on the label", "D2402430"),
        prop("ndc", "NDC", "16729-457-15"),
        prop("manufacturer", "Manufacturer on the label", "Accord Healthcare"),
        prop("strength", "Strength", "200 mcg"),
        prop("expiration", "Expires", "October 2026"),
        prop("hardware", "Instrument reading", "substandard (simulated, no physical measurement)"),
    ],
    body="An FDA Class II recall issued on 2 September 2026 lists lot D2402430 of this "
         "product as subpotent.",
    findings=[
        {"statement": "FDA recall D-0785-2026 lists lot D2402430 of NDC 16729-457.",
         "severity": "serious", "evidence_type": "exact_lot_match"},
        {"statement": "The recall reason on the record is \"Subpotent Drug\".",
         "severity": "caution", "evidence_type": "regulatory_record"},
    ],
    gaps=["Live web research was disabled for this demo scan."],
    next_steps=RECALL_NEXT_STEPS,
    sources=[SRC_LEVO],
    backlinks=[
        backlink("lot:D2402430", "lot", "Lot D2402430", "lot on this label", SCAN_LEVO),
        backlink("product:167290457", "product", "Levothyroxine 200 mcg · Accord",
                 "product line", SCAN_LEVO),
        backlink(REC_LEVO, "record", "Class II recall: Levothyroxine 200 mcg",
                 "names this lot", SCAN_LEVO),
    ],
    counts={"records": 1, "alerts": 1},
    demo=True,
)

detail(
    SCAN_LEVO_SIB, "scan", "Levothyroxine Sodium 200 mcg tablets",
    subtitle="Scanned 18 September 2026 · United States",
    badges=["Nothing found in the records searched", "Simulated hardware reading"],
    properties=[
        prop("lot", "Lot on the label", "D2402999"),
        prop("ndc", "NDC", "16729-457-15"),
        prop("manufacturer", "Manufacturer on the label", "Accord Healthcare"),
        prop("strength", "Strength", "200 mcg"),
        prop("hardware", "Instrument reading", "real (simulated, no physical measurement)"),
    ],
    body="A recall exists for this product line, but it does not list this lot number. "
         "The edge to that recall is shown faint for exactly that reason.",
    findings=[
        {"statement": "FDA recall D-0785-2026 names this product line but not lot D2402999.",
         "severity": "info", "evidence_type": "regulatory_record"},
    ],
    gaps=["Live web research was disabled for this demo scan."],
    next_steps=[
        "Keep the medicine in its original packaging with the label and lot number intact.",
        "Ask a pharmacist to check the medicine together with its packaging.",
    ],
    sources=[SRC_LEVO],
    backlinks=[
        backlink("lot:D2402999", "lot", "Lot D2402999", "lot on this label", SCAN_LEVO_SIB),
        backlink("product:167290457", "product", "Levothyroxine 200 mcg · Accord",
                 "product line", SCAN_LEVO_SIB),
    ],
    counts={"records": 1, "alerts": 0},
    demo=True,
)

detail(
    SCAN_CHLOR, "scan", "Chlorpromazine Hydrochloride 10 mg tablets",
    subtitle="Scanned 12 September 2026 · United States",
    badges=["A recall or alert names this lot", "Simulated hardware reading"],
    properties=[
        prop("lot", "Lot on the label", "Z400069"),
        prop("ndc", "NDC", "70710-1129-1"),
        prop("manufacturer", "Manufacturer on the label", "Zydus Pharmaceuticals"),
        prop("strength", "Strength", "10 mg"),
        prop("hardware", "Instrument reading", "real (simulated, no physical measurement)"),
    ],
    body="An FDA Class II recall lists lot Z400069 of this product. A NAFDAC notice lists the "
         "same lot string without naming the product, so that second edge stays uncorroborated.",
    findings=[
        {"statement": "FDA recall D-0361-2025 lists lot Z400069 of NDC 70710-1129.",
         "severity": "serious", "evidence_type": "exact_lot_match"},
        {"statement": "NAFDAC 11/2025 lists the same lot string but names no product.",
         "severity": "caution", "evidence_type": "regulatory_record"},
    ],
    gaps=["Live web research was disabled for this demo scan."],
    next_steps=RECALL_NEXT_STEPS,
    sources=[SRC_CHLOR, SRC_NAFDAC_VARIOUS],
    backlinks=[
        backlink("lot:Z400069", "lot", "Lot Z400069", "lot on this label", SCAN_CHLOR),
        backlink(REC_CHLOR, "record", "Class II recall: Chlorpromazine 10 mg",
                 "names this lot", SCAN_CHLOR),
        backlink(REC_NAFDAC_VARIOUS, "record", "NAFDAC 11/2025: various product recall",
                 "lot number only", SCAN_CHLOR),
    ],
    counts={"records": 2, "alerts": 1},
    demo=True,
)

detail(
    SCAN_HEALMOXY, "scan", "HEALMOXY (Amoxicillin) 500 mg capsules",
    subtitle="Scanned 8 September 2026 · Cameroon",
    badges=["A recall or alert names this lot", "Simulated hardware reading",
            "Hardware reading degraded"],
    properties=[
        prop("lot", "Batch on the pack", "H02605"),
        prop("manufacturer", "Name printed on the pack", "Maxheal Pharmaceuticals"),
        prop("strength", "Strength", "500 mg"),
        prop("country", "Scanned in", "Cameroon"),
        prop("hardware", "Instrument reading", "fake (simulated, no physical measurement)"),
    ],
    body="Two regulators published falsified-product alerts naming batch H02605 of HEALMOXY "
         "500 mg capsules in Cameroon and the Central African Republic.",
    findings=[
        {"statement": "WHO Medical Product Alert N°2/2025 lists batch H02605.",
         "severity": "serious", "evidence_type": "exact_lot_match"},
        {"statement": "NAFDAC Public Alert No. 17/2025 lists the same batch.",
         "severity": "serious", "evidence_type": "exact_lot_match"},
        {"statement": "Both notices describe a falsified product, so the firm named on the "
                      "pack is the firm whose name was copied.",
         "severity": "caution", "evidence_type": "regulatory_record"},
    ],
    gaps=["Live web research was disabled for this demo scan.",
          "Pill identification did not run: no imprint was read."],
    next_steps=RECALL_NEXT_STEPS,
    sources=[SRC_WHO, SRC_NAFDAC_HEALMOXY],
    backlinks=[
        backlink("lot:H02605", "lot", "Lot H02605", "batch on this pack", SCAN_HEALMOXY),
        backlink(REC_WHO_HEALMOXY, "record", "WHO N°2/2025: Falsified HEALMOXY",
                 "names this batch", SCAN_HEALMOXY),
        backlink(REC_NAFDAC_HEALMOXY, "record", "NAFDAC 17/2025: Falsified Healmoxy",
                 "names this batch", SCAN_HEALMOXY),
    ],
    counts={"records": 2, "alerts": 2, "regulators": 2},
    demo=True,
)

detail(
    SCAN_IBU, "scan", "Ibuprofen 200 mg tablets",
    subtitle="Scanned 3 September 2026 · United States",
    badges=["Nothing found in the records searched", "Simulated hardware reading"],
    properties=[
        prop("imprint", "Imprint read from the tablet", "I 2"),
        prop("strength", "Strength", "200 mg"),
        prop("shape", "Shape and colour", "round, brown"),
        prop("hardware", "Instrument reading", "real (simulated, no physical measurement)"),
    ],
    body="No recall or safety alert matching this medicine was found in the FDA, WHO and "
         "NAFDAC records searched, which are current to 19 September 2026. That is not a "
         "confirmation about the medicine itself.",
    findings=[
        {"statement": "The imprint I 2 matches ibuprofen 200 mg in the pill reference.",
         "severity": "info", "evidence_type": "imprint_reference"},
    ],
    gaps=["Live web research was disabled for this demo scan.",
          "The pill reference is a US archive frozen in January 2021."],
    next_steps=[
        "Keep the medicine in its original packaging with the label and lot number intact.",
        "Ask a pharmacist to check the medicine together with its packaging.",
    ],
    sources=[],
    backlinks=[
        backlink("imprint:I2", "imprint", "Imprint I2", "read from the tablet", SCAN_IBU),
        backlink("med:ibuprofen", "medicine", "Ibuprofen", "named on the label", SCAN_IBU),
    ],
    counts={"records": 0, "alerts": 0},
    demo=True,
)

detail(
    SCAN_MISMATCH, "scan", "Ibuprofen 200 mg label, unmatched tablet",
    subtitle="Scanned 31 August 2026 · United States",
    badges=["The label and the reference do not agree", "Past its expiry date",
            "Simulated hardware reading"],
    properties=[
        prop("imprint", "Imprint read from the tablet", "5892 V"),
        prop("label", "Name on the label", "Ibuprofen 200 mg"),
        prop("shape", "Shape and colour", "capsule, pink"),
        prop("expiration", "Expires", "March 2026"),
        prop("hardware", "Instrument reading", "real (simulated, no physical measurement)"),
    ],
    body="The imprint 5892 V is listed in the pill reference as temazepam 15 mg, not as "
         "ibuprofen. The label and the tablet disagree.",
    findings=[
        {"statement": "Imprint 5892 V matches temazepam 15 mg (Qualitest) in the reference.",
         "severity": "serious", "evidence_type": "imprint_reference"},
    ],
    mismatches=["The label says ibuprofen 200 mg; the imprint matches temazepam 15 mg."],
    gaps=["The pill reference is a US archive frozen in January 2021."],
    next_steps=[
        "Set this medicine aside in its original packaging and keep the packaging.",
        "Take the bottle and this result to a pharmacist and ask them to identify the tablet.",
    ],
    sources=[],
    backlinks=[
        backlink("imprint:5892V", "imprint", "Imprint 5892 V", "read from the tablet",
                 SCAN_MISMATCH),
        backlink("med:temazepam", "medicine", "Temazepam", "the imprint's reference",
                 SCAN_MISMATCH),
        backlink("med:ibuprofen", "medicine", "Ibuprofen", "named on the label", SCAN_MISMATCH),
    ],
    counts={"records": 0, "alerts": 0, "mismatches": 1},
    demo=True,
)

detail(
    REC_LEVO, "record", "Class II recall: Levothyroxine Sodium Tablets, USP, 200 mcg",
    subtitle="FDA · recall · 2 September 2026",
    badges=["High severity", "Class II", "Ongoing"],
    properties=[
        prop("recall_number", "Recall number", "D-0785-2026"),
        prop("reason", "Reason", "Subpotent Drug"),
        prop("classification", "Classification", "Class II"),
        prop("status", "Status", "ongoing"),
        prop("lots", "Lots named", "D2402430, D2402431, D2402432, D2500180"),
        prop("lot_count", "Number of lots", "4"),
        prop("firm", "Recalling firm", "Accord Healthcare, Inc."),
        prop("countries", "Countries", "United States"),
        prop("age", "Published", "17 days ago"),
        prop("attribution", "Source", FDA_ATTRIBUTION),
    ],
    body="Subpotent Drug. Levothyroxine Sodium Tablets, USP, 200 mcg (0.2 mg), packaged in "
         "90-count bottles (NDC 16729-457-15) and 1000-count bottles (NDC 16729-457-17).",
    findings=[
        {"statement": "Lot D2402430 on your label is one of the four lots named.",
         "severity": "serious", "evidence_type": "exact_lot_match"},
    ],
    next_steps=RECALL_NEXT_STEPS,
    sources=[SRC_LEVO],
    backlinks=[
        backlink("lot:D2402430", "lot", "Lot D2402430", "names this lot", SCAN_LEVO),
        backlink("product:167290457", "product", "Levothyroxine 200 mcg · Accord",
                 "names this product line", SCAN_LEVO_SIB),
        backlink(SCAN_LEVO, "scan", "Levothyroxine 200 mcg", "your scan", SCAN_LEVO),
    ],
    counts={"lots": 4, "scans": 2},
)

detail(
    REC_CHLOR, "record", "Class II recall: chlorproMAZINE Hydrochloride Tablets, USP 10 mg",
    subtitle="FDA · recall · 16 April 2025",
    badges=["High severity", "Class II", "Ongoing"],
    properties=[
        prop("recall_number", "Recall number", "D-0361-2025"),
        prop("reason", "Reason",
             "CGMP deviations: N-Nitroso-Desmethyl Chlorpromazine impurity above the "
             "recommended interim limit"),
        prop("classification", "Classification", "Class II"),
        prop("lots", "Lots named", "Z400069"),
        prop("firm", "Recalling firm", "Zydus Pharmaceuticals (USA) Inc."),
        prop("countries", "Countries", "United States"),
        prop("age", "Published", "521 days ago"),
        prop("attribution", "Source", FDA_ATTRIBUTION),
    ],
    body="CGMP deviations: presence of N-Nitroso-Desmethyl Chlorpromazine impurity above the "
         "recommended interim limit. Chlorpromazine Hydrochloride Tablets, USP 10 mg, "
         "NDC 70710-1129-1.",
    findings=[
        {"statement": "Lot Z400069 on your label is the lot named in this recall.",
         "severity": "serious", "evidence_type": "exact_lot_match"},
    ],
    next_steps=RECALL_NEXT_STEPS,
    sources=[SRC_CHLOR],
    backlinks=[
        backlink("lot:Z400069", "lot", "Lot Z400069", "names this lot", SCAN_CHLOR),
        backlink(SCAN_CHLOR, "scan", "Chlorpromazine 10 mg", "your scan", SCAN_CHLOR),
    ],
    counts={"lots": 1, "scans": 1},
)

detail(
    REC_NAFDAC_VARIOUS, "record",
    "Public Alert No. 11/2025 – Recall of Various Products by Sun Pharma, Glenmark and Zydus",
    subtitle="NAFDAC · recall · 29 April 2025",
    badges=["High severity", "Lot number only"],
    properties=[
        prop("reason", "Reason", "Manufacturing issues"),
        prop("lots", "Lots named", "Z400069"),
        prop("countries", "Countries", "Nigeria, United States, India"),
        prop("products", "Products named", "not specified in the notice"),
        prop("age", "Published", "508 days ago"),
        prop("attribution", "Source", NAFDAC_ATTRIBUTION),
    ],
    body="NAFDAC notified the public of the recall of various products by three drug "
         "manufacturing companies in the United States. Summary only; read the notice at the "
         "link below.",
    findings=[
        {"statement": "This notice lists the lot string Z400069 but does not name a product, "
                      "so it neither confirms nor rules out your bottle.",
         "severity": "caution", "evidence_type": "regulatory_record"},
    ],
    next_steps=[CONTEXT_NEXT_STEP],
    sources=[SRC_NAFDAC_VARIOUS],
    backlinks=[
        backlink("lot:Z400069", "lot", "Lot Z400069", "lot number only", SCAN_CHLOR),
    ],
    counts={"lots": 1, "scans": 1},
)

detail(
    REC_WHO_HEALMOXY, "record",
    "Medical Product Alert N°2/2025: Falsified HEALMOXY (Amoxicillin) Capsules 500mg",
    subtitle="WHO · falsified product alert · 23 April 2025",
    badges=["Critical severity", "Falsified product"],
    properties=[
        prop("batches", "Batches named", "023011, H02605, H026051"),
        prop("countries", "Countries", "Cameroon, Central African Republic, India"),
        prop("stated_manufacturer", "Name printed on the packs",
             "MAXHEAL PHARMACEUTICALS (India) Limited"),
        prop("age", "Published", "514 days ago"),
        prop("attribution", "Source", WHO_ATTRIBUTION),
    ],
    body="This WHO Medical Product Alert refers to four batches of falsified HEALMOXY "
         "Capsules 500mg detected in Cameroon and the Central African Republic and reported "
         "to WHO in March 2025. Summary only; read the alert at the link below.",
    findings=[
        {"statement": "Batch H02605 on your pack is named in this alert.",
         "severity": "serious", "evidence_type": "exact_lot_match"},
        {"statement": "The firm named is the firm whose name appears on the falsified packs.",
         "severity": "caution", "evidence_type": "regulatory_record"},
    ],
    next_steps=RECALL_NEXT_STEPS,
    sources=[SRC_WHO],
    backlinks=[
        backlink("lot:H02605", "lot", "Lot H02605", "names this batch", SCAN_HEALMOXY),
        backlink("mfr:maxheal pharmaceuticals", "manufacturer", "Maxheal Pharmaceuticals",
                 "name printed on the label", SCAN_HEALMOXY),
        backlink(SCAN_HEALMOXY, "scan", "Healmoxy amoxicillin 500 mg", "your scan",
                 SCAN_HEALMOXY),
    ],
    counts={"lots": 3, "countries": 3, "scans": 1},
)

detail(
    REC_NAFDAC_HEALMOXY, "record",
    "Public Alert No. 17/2025 – Falsified Batches of Healmoxy Capsules 500mg",
    subtitle="NAFDAC · falsified product alert · 1 June 2025",
    badges=["Critical severity", "Falsified product"],
    properties=[
        prop("batches", "Batches named", "023011, H02605, HO26051"),
        prop("countries", "Countries", "Nigeria, India, Cameroon, Central African Republic"),
        prop("stated_manufacturer", "Name printed on the packs", "Maxheal Pharmaceuticals"),
        prop("age", "Published", "475 days ago"),
        prop("attribution", "Source", NAFDAC_ATTRIBUTION),
    ],
    body="NAFDAC notified the public of falsified batches of Healmoxy Capsules 500mg, with "
         "batch numbers 023011 and H02605, found in Cameroon and the Central African "
         "Republic. Summary only; read the notice at the link below.",
    findings=[
        {"statement": "Batch H02605 on your pack is named in this alert.",
         "severity": "serious", "evidence_type": "exact_lot_match"},
    ],
    next_steps=RECALL_NEXT_STEPS,
    sources=[SRC_NAFDAC_HEALMOXY],
    backlinks=[
        backlink("lot:H02605", "lot", "Lot H02605", "names this batch", SCAN_HEALMOXY),
        backlink("mfr:maxheal pharmaceuticals", "manufacturer", "Maxheal Pharmaceuticals",
                 "name printed on the label", SCAN_HEALMOXY),
    ],
    counts={"lots": 3, "countries": 4, "scans": 1},
)

detail(
    "lot:D2402430", "lot", "Lot D2402430",
    subtitle="Read from the label of one of your scans",
    badges=["Named in a recall"],
    properties=[
        prop("lot", "Lot as read", "D2402430"),
        prop("product", "On your label", "Levothyroxine 200 mcg, NDC 16729-457-15"),
        prop("records", "Records naming this lot", "1"),
    ],
    body="A lot number identifies a production run only together with its product. This one "
         "matched a recall for the same product line and NDC.",
    next_steps=RECALL_NEXT_STEPS,
    sources=[SRC_LEVO],
    backlinks=[
        backlink(SCAN_LEVO, "scan", "Levothyroxine 200 mcg", "lot on this label", SCAN_LEVO),
        backlink(REC_LEVO, "record", "Class II recall: Levothyroxine 200 mcg",
                 "names this lot", SCAN_LEVO),
    ],
    counts={"records": 1, "scans": 1},
)

detail(
    "lot:D2402999", "lot", "Lot D2402999",
    subtitle="Read from the label of one of your scans",
    badges=["Not named in any record searched"],
    properties=[
        prop("lot", "Lot as read", "D2402999"),
        prop("product", "On your label", "Levothyroxine 200 mcg, NDC 16729-457-15"),
        prop("records", "Records naming this lot", "0"),
    ],
    body="The recall on this product line names four other lots. This one is not among them, "
         "which is why the only edge from this bottle to that recall runs through the product "
         "node and is drawn faint.",
    next_steps=[CONTEXT_NEXT_STEP],
    sources=[SRC_LEVO],
    backlinks=[
        backlink(SCAN_LEVO_SIB, "scan", "Levothyroxine 200 mcg", "lot on this label",
                 SCAN_LEVO_SIB),
    ],
    counts={"records": 0, "scans": 1},
)

detail(
    "lot:Z400069", "lot", "Lot Z400069",
    subtitle="Read from the label of one of your scans",
    badges=["Named in a recall", "Also a lot-string collision"],
    properties=[
        prop("lot", "Lot as read", "Z400069"),
        prop("product", "On your label", "Chlorpromazine 10 mg, NDC 70710-1129-1"),
        prop("records", "Records naming this lot string", "2"),
    ],
    body="One record names this lot together with your product. The other lists the same "
         "string without naming a product, so it stays uncorroborated.",
    next_steps=RECALL_NEXT_STEPS,
    sources=[SRC_CHLOR, SRC_NAFDAC_VARIOUS],
    backlinks=[
        backlink(SCAN_CHLOR, "scan", "Chlorpromazine 10 mg", "lot on this label", SCAN_CHLOR),
        backlink(REC_CHLOR, "record", "Class II recall: Chlorpromazine 10 mg",
                 "names this lot", SCAN_CHLOR),
        backlink(REC_NAFDAC_VARIOUS, "record", "NAFDAC 11/2025: various product recall",
                 "lot number only", SCAN_CHLOR),
    ],
    counts={"records": 2, "scans": 1},
)

detail(
    "lot:H02605", "lot", "Lot H02605",
    subtitle="Read from the pack of one of your scans",
    badges=["Named by two regulators"],
    properties=[
        prop("lot", "Batch as read", "H02605"),
        prop("product", "On your pack", "HEALMOXY (Amoxicillin) 500 mg capsules"),
        prop("records", "Records naming this batch", "2"),
        prop("regulators", "Regulators", "WHO, NAFDAC"),
    ],
    body="Two regulators in two formats published alerts about the same batch number. They "
         "converge on this one node.",
    next_steps=RECALL_NEXT_STEPS,
    sources=[SRC_WHO, SRC_NAFDAC_HEALMOXY],
    backlinks=[
        backlink(SCAN_HEALMOXY, "scan", "Healmoxy amoxicillin 500 mg", "batch on this pack",
                 SCAN_HEALMOXY),
        backlink(REC_WHO_HEALMOXY, "record", "WHO N°2/2025: Falsified HEALMOXY",
                 "names this batch", SCAN_HEALMOXY),
        backlink(REC_NAFDAC_HEALMOXY, "record", "NAFDAC 17/2025: Falsified Healmoxy",
                 "names this batch", SCAN_HEALMOXY),
    ],
    counts={"records": 2, "regulators": 2, "scans": 1},
)

detail(
    "reg:fda", "regulator", "U.S. Food and Drug Administration",
    subtitle="17,963 enforcement records in this index",
    badges=["Public domain"],
    properties=[
        prop("records", "Records indexed", "17,963"),
        prop("formats", "Format", "openFDA enforcement JSON API"),
        prop("index_date", "Index current to", "19 September 2026"),
        prop("attribution", "Source", FDA_ATTRIBUTION),
    ],
    body="FDA drug enforcement reports. Each record's source link is an openFDA API query, "
         "so it opens as JSON rather than as a web page.",
    sources=[SRC_LEVO, SRC_CHLOR],
    backlinks=[
        backlink(REC_LEVO, "record", "Class II recall: Levothyroxine 200 mcg", "issued by"),
        backlink(REC_CHLOR, "record", "Class II recall: Chlorpromazine 10 mg", "issued by"),
    ],
    counts={"records": 17963, "in_your_graph": 2},
)

detail(
    "reg:who", "regulator", "World Health Organization",
    subtitle="83 medical product alerts in this index",
    badges=["CC BY-NC-SA 3.0 IGO"],
    properties=[
        prop("records", "Records indexed", "83"),
        prop("formats", "Format", "Medical Product Alert web pages"),
        prop("index_date", "Index current to", "19 September 2026"),
        prop("attribution", "Source", WHO_ATTRIBUTION),
    ],
    body="WHO Medical Product Alerts about falsified and substandard medicines. Summaries "
         "only; each alert links back to who.int.",
    sources=[SRC_WHO],
    backlinks=[
        backlink(REC_WHO_HEALMOXY, "record", "WHO N°2/2025: Falsified HEALMOXY", "issued by"),
    ],
    counts={"records": 83, "in_your_graph": 1},
)

detail(
    "reg:nafdac", "regulator", "NAFDAC (Nigeria)",
    subtitle="403 public alerts in this index",
    badges=["Summarised and linked"],
    properties=[
        prop("records", "Records indexed", "403"),
        prop("formats", "Format", "Public alert web pages"),
        prop("index_date", "Index current to", "19 September 2026"),
        prop("attribution", "Source", NAFDAC_ATTRIBUTION),
    ],
    body="NAFDAC public alerts. NAFDAC publishes no licence, so Peel stores a short summary "
         "and always links back to the notice.",
    sources=[SRC_NAFDAC_HEALMOXY, SRC_NAFDAC_VARIOUS],
    backlinks=[
        backlink(REC_NAFDAC_HEALMOXY, "record", "NAFDAC 17/2025: Falsified Healmoxy",
                 "issued by"),
        backlink(REC_NAFDAC_VARIOUS, "record", "NAFDAC 11/2025: various product recall",
                 "issued by"),
    ],
    counts={"records": 403, "in_your_graph": 2},
)

detail(
    SELLER_RIVERSIDE, "seller", "Riverside Demo Pharmacy",
    subtitle="Named in your report as where you bought it",
    properties=[
        prop("reports", "Reports you filed", "2"),
        prop("purchased_between", "You said you bought it between",
             "Aug 20, 2026 – Sep 2, 2026"),
        prop("place", "Place", "Columbus, United States"),
    ],
    # Every number on a seller note is this person's own. Other people's
    # reports are the cluster below, which has a note of its own.
    body=REPORT_BODY,
    backlinks=[
        backlink(SCAN_LEVO, "scan", "Levothyroxine 200 mcg",
                 "Where you said you bought it", SCAN_LEVO),
        backlink(SCAN_LEVO_SIB, "scan", "Levothyroxine 200 mcg",
                 "Where you said you bought it", SCAN_LEVO_SIB),
        backlink(PLACE_COLUMBUS, "place", "Columbus, United States", "Located in"),
        backlink(CROWD_RIVERSIDE, "cluster", "Named by 4 other people",
                 "Other people's reports"),
    ],
    counts={"reports": 2, "scans": 2},
    demo=True,
)

detail(
    SELLER_MARCHE, "seller", "Pharmacie du Marché Demo",
    subtitle="Named in your report as where you bought it",
    properties=[
        prop("reports", "Reports you filed", "1"),
        prop("purchased_on", "You said you bought it", "Aug 30, 2026"),
        prop("place", "Place", "Douala, Cameroon"),
    ],
    body=REPORT_BODY,
    backlinks=[
        backlink(SCAN_HEALMOXY, "scan", "Healmoxy amoxicillin 500 mg",
                 "Where you said you bought it", SCAN_HEALMOXY),
        backlink(PLACE_DOUALA, "place", "Douala, Cameroon", "Located in"),
    ],
    counts={"reports": 1, "scans": 1},
    demo=True,
)

PLACE_BODY = (
    "This is the city or country you gave in a report you filed. Peel has not checked "
    "it, and it says nothing about the medicines sold there."
)

detail(
    PLACE_COLUMBUS, "place", "Columbus, United States",
    subtitle="The place you named in your report",
    properties=[
        prop("reports", "Reports you filed", "2"),
        prop("purchased_between", "You said you bought it between",
             "Aug 20, 2026 – Sep 2, 2026"),
    ],
    body=PLACE_BODY,
    backlinks=[
        backlink(SELLER_RIVERSIDE, "seller", "Riverside Demo Pharmacy", "Located in"),
        backlink("country:united-states", "country", "United States", "Located in"),
    ],
    counts={"reports": 2},
    demo=True,
)

detail(
    PLACE_DOUALA, "place", "Douala, Cameroon",
    subtitle="The place you named in your report",
    properties=[
        prop("reports", "Reports you filed", "1"),
        prop("purchased_on", "You said you bought it", "Aug 30, 2026"),
    ],
    body=PLACE_BODY,
    backlinks=[
        backlink(SELLER_MARCHE, "seller", "Pharmacie du Marché Demo", "Located in"),
        backlink("country:cameroon", "country", "Cameroon", "Located in"),
    ],
    counts={"reports": 1},
    demo=True,
)

detail(
    PLACE_BOSTON, "place", "Boston, United States",
    subtitle="The place you named in your report",
    properties=[
        prop("reports", "Reports you filed", "1"),
        prop("purchased_on", "You said you bought it", "Aug 28, 2026"),
    ],
    body=PLACE_BODY,
    backlinks=[
        backlink(SCAN_IBU, "scan", "Ibuprofen 200 mg", "Where you said you bought it",
                 SCAN_IBU),
        backlink("country:united-states", "country", "United States", "Located in"),
    ],
    counts={"reports": 1},
    demo=True,
)

# The shape `detail._report_cluster_detail` really returns: a title, a subtitle
# and a body. The two counts the panel shows are read off the cluster NODE
# (`count`, `attrs.flagged`), so the note itself carries no properties — there
# is nothing else about those people that it is allowed to say.
detail(
    CROWD_RIVERSIDE, "cluster", "Other people's reports",
    subtitle="Counts from other people's reports",
    body="Other people filed reports naming the same place of purchase. Peel shows how "
         "many, and nothing else about them: no dates, no locations, no scans. Peel has "
         "not checked any of these reports, and they say nothing about what anyone did.",
)

# =========================================================================== expansions


def expand_meta(**kwargs) -> dict:
    doc = {
        "device_id": DEVICE,
        "scans": 6,
        "generated_at": "2026-09-19T23:30:00Z",
        "source": "demo",
        "demo": True,
        "truncated": False,
        "index_date": INDEX_DATE,
        "notice": NOTICE,
    }
    doc.update(kwargs)
    return doc


def sibling_lot(lot: str, sublabel: str) -> dict:
    return {"id": f"lot:{lot}", "type": "lot", "label": f"Lot {lot}", "sublabel": sublabel,
            "val": 1.6, "expandable": True, "attrs": {"lot": lot}}


expansions = {
    "lot:D2402430": {
        "anchor": "lot:D2402430",
        "nodes": [
            sibling_lot("D2402431", "also named in this recall"),
            sibling_lot("D2402432", "also named in this recall"),
            sibling_lot("D2500180", "also named in this recall"),
        ],
        "links": [
            {"id": f"lot:D2402431>lot_listed>{REC_LEVO}", "source": "lot:D2402431",
             "target": REC_LEVO, "kind": "lot_listed", "strong": False, "alert": False,
             "weight": 0.2, "match_kind": "lot_listed"},
            {"id": f"lot:D2402432>lot_listed>{REC_LEVO}", "source": "lot:D2402432",
             "target": REC_LEVO, "kind": "lot_listed", "strong": False, "alert": False,
             "weight": 0.2, "match_kind": "lot_listed"},
            {"id": f"lot:D2500180>lot_listed>{REC_LEVO}", "source": "lot:D2500180",
             "target": REC_LEVO, "kind": "lot_listed", "strong": False, "alert": False,
             "weight": 0.2, "match_kind": "lot_listed"},
        ],
        "meta": expand_meta(counts={"records": 1, "lots": 4, "prior_scans": 1}),
    },
    "lot:D2402999": {
        "anchor": "lot:D2402999",
        "nodes": [],
        "links": [],
        "meta": expand_meta(counts={"records": 0, "web_pages": 0, "prior_scans": 1}),
    },
    "lot:Z400069": {
        "anchor": "lot:Z400069",
        "nodes": [],
        "links": [
            {"id": f"lot:Z400069>exact_lot>{REC_CHLOR}", "source": "lot:Z400069",
             "target": REC_CHLOR, "kind": "exact_lot", "strong": True, "alert": True,
             "weight": 1.0, "match_kind": "exact_lot", "scan_ids": [SCAN_CHLOR]},
            {"id": f"lot:Z400069>lot_only_match>{REC_NAFDAC_VARIOUS}", "source": "lot:Z400069",
             "target": REC_NAFDAC_VARIOUS, "kind": "lot_only_match", "strong": False,
             "alert": False, "weight": 0.2, "match_kind": "lot_only_match",
             "scan_ids": [SCAN_CHLOR]},
        ],
        "meta": expand_meta(counts={"records": 2, "corroborated": 1, "prior_scans": 1}),
    },
    "lot:H02605": {
        "anchor": "lot:H02605",
        "nodes": [sibling_lot("023011", "also named in both alerts")],
        "links": [
            {"id": f"lot:023011>lot_listed>{REC_WHO_HEALMOXY}", "source": "lot:023011",
             "target": REC_WHO_HEALMOXY, "kind": "lot_listed", "strong": False, "alert": False,
             "weight": 0.2, "match_kind": "lot_listed"},
            {"id": f"lot:023011>lot_listed>{REC_NAFDAC_HEALMOXY}", "source": "lot:023011",
             "target": REC_NAFDAC_HEALMOXY, "kind": "lot_listed", "strong": False,
             "alert": False, "weight": 0.2, "match_kind": "lot_listed"},
            {"id": f"{WEB_WHO}>lists_lot>lot:H02605", "source": WEB_WHO, "target": "lot:H02605",
             "kind": "lists_lot", "strong": True, "alert": False, "weight": 0.5},
            {"id": f"{WEB_NAFDAC}>lists_lot>lot:H02605", "source": WEB_NAFDAC,
             "target": "lot:H02605", "kind": "lists_lot", "strong": True, "alert": False,
             "weight": 0.5},
        ],
        "meta": expand_meta(counts={"records": 2, "regulators": 2, "web_pages": 2,
                                    "prior_scans": 1}),
    },
    SELLER_RIVERSIDE: {
        "anchor": SELLER_RIVERSIDE,
        # Counts only: no foreign scan id, no report id, no date, no location.
        "nodes": [
            {"id": CROWD_RIVERSIDE, "type": "cluster", "label": "Named by 4 other people",
             "val": 1.2, "count": 4, "expandable": False, "demo": True,
             "attrs": {"relation": "reports", "parent": SELLER_RIVERSIDE, "count": 4,
                       "flagged": 2}},
        ],
        "links": [
            {"id": f"{SELLER_RIVERSIDE}>also_reported>{CROWD_RIVERSIDE}",
             "source": SELLER_RIVERSIDE, "target": CROWD_RIVERSIDE, "kind": "also_reported",
             "strong": False, "alert": False, "weight": 0.3, "count": 4,
             "match_kind": "also_reported"},
        ],
        "meta": expand_meta(counts={"other_reports": 4, "flagged": 2}),
    },
    "reg:fda": {
        "anchor": "reg:fda",
        "nodes": [
            {"id": "cluster:reg:fda|records", "type": "cluster",
             "label": "+17,961 more FDA records", "val": 1.4, "count": 17961,
             "expandable": True, "attrs": {"relation": "records", "parent": "reg:fda"}},
            {"id": "topic:subpotent", "type": "topic", "label": "Subpotent", "val": 1.8,
             "expandable": True, "count": 1},
            {"id": "topic:impurity-nitrosamine", "type": "topic", "label": "Impurity",
             "val": 1.8, "expandable": True, "count": 1},
        ],
        "links": [
            {"id": "reg:fda>more>cluster:reg:fda|records", "source": "reg:fda",
             "target": "cluster:reg:fda|records", "kind": "more", "strong": False,
             "weight": 0.1},
            {"id": f"{REC_LEVO}>issued_by>reg:fda", "source": REC_LEVO, "target": "reg:fda",
             "kind": "issued_by", "strong": True, "weight": 0.5},
            {"id": f"{REC_CHLOR}>issued_by>reg:fda", "source": REC_CHLOR, "target": "reg:fda",
             "kind": "issued_by", "strong": True, "weight": 0.5},
        ],
        "meta": expand_meta(counts={"records": 17963, "in_your_graph": 2, "class_ii": 2}),
    },
}

# =========================================================================== search

search = {
    "query": "subpotent thyroid tablets",
    "nodes": [],
    "links": [],
    "hits": [
        {"node_id": REC_LEVO, "score": 1.0,
         "highlight": "Subpotent Drug — Levothyroxine Sodium Tablets, USP, 200 mcg"},
        {"node_id": "topic:subpotent", "score": 0.62,
         "highlight": "Subpotent: the reason on 1 record in your graph"},
        {"node_id": REC_CHLOR, "score": 0.31,
         "highlight": "CGMP deviations: N-Nitroso-Desmethyl Chlorpromazine impurity"},
    ],
    # The path from the best hit back to the bottle this person owns.
    "highlight": [REC_LEVO, "lot:D2402430", SCAN_LEVO],
    "meta": expand_meta(
        counts={"hits": 3, "paths": 1},
        source="demo",
    ),
}


def dump(name: str, payload: object) -> None:
    path = OUT / name
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path} ({path.stat().st_size} bytes)")


GraphResponse.model_validate(graph)
for key, value in details.items():
    parsed = NodeDetail.model_validate(value)
    assert parsed.id == key, key
for key, value in expansions.items():
    parsed_expand = ExpandResponse.model_validate(value)
    assert parsed_expand.anchor == key, key
SearchGraphResponse.model_validate(search)

ids = {item["id"] for item in nodes}
for item in links:
    assert item["source"] in ids, item["source"]
    assert item["target"] in ids, item["target"]
assert len(ids) == len(nodes), "duplicate node id"
assert len({item["id"] for item in links}) == len(links), "duplicate link id"
for item in nodes:
    assert len(item["label"]) <= 40, item

OUT.mkdir(parents=True, exist_ok=True)
dump("demo_graph.json", graph)
dump("demo_nodes.json", details)
dump("demo_expansions.json", expansions)
dump("demo_search.json", search)
print(f"{len(nodes)} nodes, {len(links)} links, {len(details)} details")
