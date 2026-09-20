"""The way in (firmware lines -> result) and the way out (result -> backend)."""

from __future__ import annotations

import json

import numpy as np

from .. import classify_capture, load_library, parse_stream_line, to_pill_hardware_analysis, to_pill_hardware_result
from ..classification import ClassificationResult
from ..hardware import PEEL_BENCH_RIG as RIG
from .test_hardware import BLANK_MV, SPECTRA, _live_lines

LIBRARY = load_library()
# backend/src/backend/pill.py: PillStatus, and PillHardwareResult's fields.
BACKEND_STATUSES = {"real", "substandard", "fake", "unknown"}
BACKEND_RESULT_FIELDS = {"status", "spectrum", "pill_type", "degraded", "confidence"}


def _lines(mv: np.ndarray, n: int = RIG.sweeps_to_average) -> list[str]:
    """Firmware text lines carrying `n` fresh sweeps at the given levels, in
    the six-LED form main's 17_stream prints (extra keys, extra objects)."""
    red, yellow, green = (float(v) for v in mv)
    line = {"t": -1.0, "trans": 400, "scat": 60, "absT": None, "absS": None, "tC": None,
            "sweep": {"ir": 12, "red": red, "yellow": yellow, "green": green, "blue": -37, "violet": 5},
            "sweepS": {"ir": 1, "red": 2, "yellow": 2, "green": 3, "blue": 0, "violet": 1},
            "dark": {"trans": 3, "scat": 1}, "stir": 0, "swept": True}
    stale = dict(line, swept=False)
    return [json.dumps(stale), "# a firmware comment", json.dumps(line)] * n


# --- in --------------------------------------------------------------------------

def test_parse_stream_line_takes_what_a_serial_port_actually_gives():
    reading = '{"t":-1.0,"trans":434,"sweep":{"red":240,"yellow":118,"green":403},"swept":true}'
    assert parse_stream_line(reading)["trans"] == 434
    assert parse_stream_line(json.loads(reading))["trans"] == 434
    # the envelope hardware/tools' capture writes (hardware/data/*.jsonl)
    envelope = json.dumps({"t_host": 0.595, "src": "xiao", "dir": "rx", "line": reading})
    assert parse_stream_line(envelope)["trans"] == 434
    for junk in ("# 17_stream ready", "ESP-ROM:esp32s3-20210327", "", '{"t":-1.0,"tra', '{"displayReady":1}',
                 json.dumps({"src": "box3", "line": "# 20 fps, link UP"})):
        assert parse_stream_line(junk) is None, junk


def test_shipped_library_loads_for_the_rig():
    assert [e.name for e in LIBRARY] == ["advil", "pepto"]
    assert all(e.spectrum.shape == (len(RIG.channels),) for e in LIBRARY)
    assert np.allclose(LIBRARY[0].spectrum, SPECTRA["advil"], atol=1e-4)


def test_classify_capture_from_raw_firmware_text():
    sample = BLANK_MV * 10.0 ** (-SPECTRA["advil"])
    r = classify_capture(_lines(BLANK_MV), _lines(sample), LIBRARY, expected_drug="advil")
    assert (r.verdict, r.match_name, r.confidence) == ("PASS", "advil", "high"), r


def test_classify_capture_on_the_real_faulted_recording_is_refused():
    live = _live_lines()
    r = classify_capture(_lines(BLANK_MV), live, LIBRARY, expected_drug="advil")
    assert r.verdict == "INVALID_READING", r


def test_classify_capture_without_enough_sweeps_says_so():
    try:
        classify_capture(_lines(BLANK_MV, n=2), _lines(BLANK_MV), LIBRARY)
    except ValueError as e:
        assert "fresh sweeps" in str(e)
    else:
        raise AssertionError("expected ValueError")


# --- out -------------------------------------------------------------------------

def _result(verdict, match="advil", sim=0.99999, absorbance=(0.86, 0.99, 0.65)) -> ClassificationResult:
    return ClassificationResult(verdict=verdict, match_name=match, similarity=sim, confidence="high",
                                estimated_concentration=1.0, expected_concentration=1.0, concentration_ratio=1.0,
                                absorbance=None if absorbance is None else np.array(absorbance, dtype=float))


def test_every_verdict_maps_onto_a_backend_status():
    expected = {"PASS": "real", "DILUTED": "substandard", "OVER_CONCENTRATED": "substandard",
                "ADULTERATED": "fake", "UNKNOWN": "unknown", "NO_SIGNAL": "unknown", "INVALID_READING": "unknown"}
    for verdict, status in expected.items():
        out = to_pill_hardware_result(_result(verdict, match=None if status == "unknown" else "advil"), RIG.classifier)
        assert set(out) == BACKEND_RESULT_FIELDS
        assert out["status"] == status and out["status"] in BACKEND_STATUSES
        assert out["degraded"] is (status == "substandard")
        assert 0.0 <= out["confidence"] <= 1.0
        json.dumps(out)                                   # JSON-safe: no numpy scalars, no NaN


def test_a_rig_fault_is_never_reported_as_a_fake_pill():
    r = classify_capture(_lines(BLANK_MV), _live_lines(), LIBRARY, expected_drug="advil")
    out = to_pill_hardware_result(r, RIG.classifier)
    assert out["status"] == "unknown" and out["confidence"] == 0.0 and out["pill_type"] is None


def test_confidence_is_the_margin_over_the_threshold():
    t = RIG.classifier.match_threshold
    at = to_pill_hardware_result(_result("PASS", sim=t), RIG.classifier)["confidence"]
    mid = to_pill_hardware_result(_result("PASS", sim=(1 + t) / 2), RIG.classifier)["confidence"]
    top = to_pill_hardware_result(_result("PASS", sim=1.0), RIG.classifier)["confidence"]
    assert (at, top) == (0.0, 1.0) and abs(mid - 0.5) < 1e-9


def test_spectrum_is_json_safe_even_for_a_non_finite_reading():
    out = to_pill_hardware_result(_result("INVALID_READING", match=None, absorbance=(np.nan, 0.5, np.inf)))
    assert out["spectrum"] == [0.0, 0.5, 0.0]
    assert to_pill_hardware_result(_result("NO_SIGNAL", match=None, absorbance=None))["spectrum"] == []


def test_analysis_envelope_matches_the_backend_model():
    out = to_pill_hardware_analysis(_result("PASS"), RIG.classifier)
    assert set(out) == {"identification_method", "target", "model", "result"}
    assert (out["identification_method"], out["target"]) == ("hardware", "pill")
