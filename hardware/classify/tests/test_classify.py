from __future__ import annotations

from classify import sim
from classify.bridge import hardware_result
from classify.calibration import fit
from classify.classify import classify
from classify.products import RIBOFLAVIN
from classify.run import Run
from classify.stream import Note, Reading, parse_line

LINE = ('{"t":12.0,"trans":1830,"scat":140,"absT":0.1240,"absS":-0.0430,"tC":37.02,'
        '"sweep":{"red":1200,"yellow":900,"green":2400,"blue":1700},"stir":100,"swept":false}')


def test_parse_data_and_note_lines() -> None:
    reading = parse_line(LINE)
    assert isinstance(reading, Reading)
    assert reading.t == 12.0 and reading.abs_t == 0.124 and reading.cloudiness == 0.043
    assert reading.sweep["blue"] == 1700 and reading.sweep_complete
    note = parse_line("# 17_stream ready. Fast channel = blue LED. Stirrer 100%.\r\n")
    assert isinstance(note, Note) and note.fast_led == "blue"
    assert parse_line("rst:0x1 (POWERON)") is None
    assert parse_line(LINE.replace("0.1240", "nan")).abs_t is None
    assert parse_line('{"t":-1.0,"trans":2460,"scat":180}').running is False


def test_fit_recovers_a_line() -> None:
    cal = fit([(0, 0.01), (10, 0.28), (20, 0.55), (30, 0.82)], "riboflavin", "blue", blank_sd=0.002)
    assert abs(cal.slope - 0.027) < 1e-6
    assert cal.r2 > 0.9999
    assert abs(cal.concentration(0.55) - 20) < 1e-6
    assert abs(cal.lod() - 3.3 * 0.002 / 0.027) < 1e-9


def _run(**kwargs) -> Run:
    run = Run()
    kwargs.setdefault("seconds", 600)
    for line in sim.lines(**kwargs):
        run.feed(parse_line(line))
    return run


CAL = fit([(0, 0.0), (12.5, 0.35), (25, 0.7)], "riboflavin", "blue")


def test_full_dose_passes_and_half_dose_is_referred() -> None:
    full = classify(_run(plateau=0.7), CAL, RIBOFLAVIN)
    assert full.status == "pass_screen"
    assert 0.95 < full.dose_fraction < 1.05
    assert full.settled and full.t80_s is not None
    half = classify(_run(plateau=0.35), CAL, RIBOFLAVIN)
    assert half.status == "refer_to_lab"
    assert "below" in half.reasons[-1]


def test_no_absorbance_and_cloudy_reads() -> None:
    nothing = classify(_run(plateau=0.0), CAL, RIBOFLAVIN)
    assert nothing.status == "refer_to_lab" and not nothing.analyte_seen
    assert hardware_result(nothing)["status"] == "fake"
    cloudy = classify(_run(plateau=0.7, cloud=0.4, seconds=60), CAL, RIBOFLAVIN)
    assert cloudy.status == "cannot_verify"
    assert hardware_result(cloudy)["status"] == "unknown"


def test_backend_mapping() -> None:
    passed = hardware_result(classify(_run(plateau=0.7), CAL, RIBOFLAVIN), r2=CAL.r2)
    assert passed["status"] == "real" and passed["pill_type"] == "riboflavin"
    assert len(passed["spectrum"]) == 4 and passed["confidence"] == 0.9
    uncalibrated = classify(_run(plateau=0.7), None, RIBOFLAVIN)
    assert uncalibrated.status == "cannot_verify"
