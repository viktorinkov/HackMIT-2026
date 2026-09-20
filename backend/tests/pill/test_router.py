from __future__ import annotations

import copy
import math

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.pill import HARDWARE_LIMITATION, REAL_HARDWARE_MODEL, router
from backend.research.evidence import _hardware
from backend.scans.models import ScanCreate
from backend.scans.normalizer import hardware_doc

app = FastAPI()
app.include_router(router)
client = TestClient(app)

# Test signals derived from the measured library, not evidence of rig accuracy.
REFERENCES = {"advil": [0.8577, 0.9941, 0.6472], "pepto": [1.0567, 1.16, 0.8725]}


def capture(drug="advil", scale=1.0, label="ibuprofen"):
    blank = dict(zip(("red", "yellow", "green"), (116.0, 137.0, 400.0)))
    sample = {k: v * 10 ** (-scale * a) for (k, v), a in zip(blank.items(), REFERENCES[drug])}
    return {
        "rig": "peel-bench-17_stream",
        "pill_type": label,
        "blank": [{"swept": True, "sweep": dict(blank)} for _ in range(5)],
        "sample": [{"swept": True, "sweep": dict(sample)} for _ in range(5)],
    }


@pytest.mark.parametrize(("drug", "scale", "label", "status"), [
    ("advil", 1.0, "ibuprofen", "real"),
    ("advil", 1.0, " AdViL ", "real"),
    ("pepto", 1.0, "bismuth subsalicylate", "real"),
    ("advil", 0.5, "ibuprofen", "substandard"),
    ("advil", 1.5, "ibuprofen", "substandard"),
    ("pepto", 1.0, "ibuprofen", "fake"),
    ("advil", 1.0, "acetaminophen", "unknown"),
    ("advil", 1.0, None, "unknown"),
])
def test_real_classifier(drug, scale, label, status):
    response = client.post("/pill", json=capture(drug, scale, label))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model"] == REAL_HARDWARE_MODEL
    assert body["result"]["status"] == status
    assert body["limitations"] == HARDWARE_LIMITATION
    assert all(math.isfinite(v) for v in body["result"]["spectrum"])
    assert body["result"]["degraded"] is (status == "substandard")
    if status == "unknown":
        assert body["result"]["pill_type"] is None
        assert body["result"]["confidence"] == 0
    else:
        assert body["result"]["spectrum"] == pytest.approx(
            [v * scale for v in REFERENCES[drug]]
        )


@pytest.mark.parametrize("payload", [{}, {"status": "real"}, {"pill_type": "advil"}])
def test_no_capture_cannot_get_a_generated_result(payload):
    assert client.post("/pill", json=payload).status_code == 422


@pytest.mark.parametrize("change", ["short", "long", "stale", "missing", "infinite", "status", "rig"])
def test_rejects_invalid_contract(change):
    payload = capture()
    if change == "short":
        payload["blank"].pop()
    elif change == "long":
        payload["sample"].append(copy.deepcopy(payload["sample"][0]))
    elif change == "stale":
        payload["sample"][0]["swept"] = False
    elif change == "missing":
        del payload["sample"][0]["sweep"]["red"]
    elif change == "infinite":
        payload["sample"][0]["sweep"]["red"] = "Infinity"
    elif change == "status":
        payload["status"] = "real"
    else:
        payload["rig"] = "different-device"
    assert client.post("/pill", json=payload).status_code == 422


@pytest.mark.parametrize("value", [-194, 0])
def test_faulted_sweeps_are_unknown(value):
    payload = capture()
    for sweep in payload["sample"]:
        sweep["sweep"] = dict.fromkeys(("red", "yellow", "green"), value)
    response = client.post("/pill", json=payload)
    assert response.status_code == 200
    assert response.json()["verdict"] == "INVALID_READING"
    assert response.json()["result"]["status"] == "unknown"
    assert response.json()["result"]["confidence"] == 0


def test_real_result_survives_scan_storage_and_is_not_marked_simulated():
    body = client.post("/pill", json=capture()).json()
    scan = ScanCreate(device_id="test", hardware=body["result"], hardware_model=body["model"])
    stored = hardware_doc(scan.hardware, scan.hardware_model)
    evidence = _hardware({"hardware": stored})
    assert evidence["simulated"] is False
    assert evidence["limitations"] == HARDWARE_LIMITATION
    assert evidence["status"] == "real"


def test_one_faulted_sweep_cannot_be_hidden_by_averaging():
    payload = capture()
    payload["sample"][0]["sweep"]["red"] = -1
    body = client.post("/pill", json=payload).json()
    assert body["verdict"] == "INVALID_READING"
    assert body["result"]["status"] == "unknown"
