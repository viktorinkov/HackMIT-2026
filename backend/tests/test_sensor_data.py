from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.pill import PillHardwareResult
from backend.sensor_data import sensor_evidence
from backend.scans.normalizer import hardware_doc
from backend.research.contract import to_scan_context
from backend.research.evidence import _hardware, _hardware_finding
from backend.research.pipeline import _trimmed_hardware
from backend.deepgram.prompt import build_playground_prompt, PROMPT_LIMIT
from backend.deepgram.session import opening_messages_from_scan
from backend.knowledge.indices import ensure_indices
from backend.knowledge.fields import SCANS_INDEX


def payload():
    return dict(status="unknown", spectrum=[-.2, .3], degraded=False, confidence=0,
                sensor_sample_count=3, sensor_readings=[
        dict(t=0, trans=100, scat=20, absT=-.2, tC=-127, sweep={"red": -12, "blue": None}),
        dict(t=1, trans=999, scat=999, absT=9, swept=True),
        dict(t=2, trans=80, scat=30, absT=.3, tC=37),
    ])


def test_measurements_reach_research_and_voice_without_inventing_identity():
    doc = hardware_doc(PillHardwareResult(**payload()), "peel-xiao")
    evidence = sensor_evidence(doc)["measurements"]
    assert evidence["channels"]["trans"]["change"] == -20
    assert evidence["channels"]["trans"]["max"] == 100  # sweep isn't a normal sample
    assert evidence["channels"]["tC"]["count"] == 1
    assert evidence["sensor_readings"][0]["sweep"] == {"red": -12, "blue": None}
    assert evidence["duration_seconds"] == 2
    assert _trimmed_hardware(doc)["measurements"] == evidence
    block = _hardware({"hardware": doc})
    assert block["measurements"] == evidence
    assert "3 sensor samples" in _hardware_finding(block).statement
    scan = {"scan_id": "test", "hardware": doc}
    context = to_scan_context(scan)["hardware"]
    assert context["status"] == "measured"
    assert context["candidate"] is None
    assert context["reported_status"] == "unknown"
    assert context["degradation"]["status"] == "not_assessed"
    assert context["measurements"] == evidence
    assert "hardware result is unknown" in opening_messages_from_scan(scan)[2]
    prompt = build_playground_prompt(scan).prompt
    assert '"sensor_readings"' not in prompt
    assert '"absorbance_trace"' not in prompt


def test_context_is_bounded_and_keeps_first_and_last_samples():
    data = payload()
    data["sensor_readings"] = [dict(t=i, trans=i, scat=3) for i in range(256)]
    data["spectrum"] = list(range(4096))
    doc = hardware_doc(PillHardwareResult(**data), "peel-xiao")
    measurements = sensor_evidence(doc)["measurements"]
    assert len(measurements["sensor_readings"]) == 32
    assert measurements["sensor_readings"][-1]["t"] == 255
    assert len(measurements["absorbance_trace"]) == 32
    assert measurements["absorbance_trace"][-1] == 4095
    assert build_playground_prompt({"scan_id": "test", "hardware": doc}).character_count <= PROMPT_LIMIT


def test_legacy_simulation_is_not_presented_as_sensor_measurement():
    doc = hardware_doc(PillHardwareResult(**payload()), "mock-spectrometry")
    assert sensor_evidence(doc) == {}
    assert "measurements" not in to_scan_context({"hardware": doc})["hardware"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_nonfinite_sensor_payload_is_rejected(bad):
    data = payload()
    data["sensor_readings"][0]["trans"] = bad
    with pytest.raises(ValidationError):
        PillHardwareResult(**data)


async def test_existing_scan_index_gets_additive_sensor_mapping():
    client = AsyncMock()
    client.indices.exists.return_value = True
    assert await ensure_indices(client, (SCANS_INDEX,)) == []
    client.indices.put_mapping.assert_awaited_once()
    client.indices.delete.assert_not_called()


def test_mock_pill_endpoint_is_removed():
    from backend.app import app
    assert "/pill" not in app.openapi()["paths"]
