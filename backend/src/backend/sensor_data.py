"""Bounded, numeric sensor evidence shared by research and voice."""
from __future__ import annotations

import math
from typing import Any

CHANNELS = {"trans": "mV", "scat": "mV", "absT": "absorbance", "absS": "absorbance", "tC": "°C", "stir": "%", "darkTrans": "mV", "darkScat": "mV"}
COLORS = ("ir", "red", "yellow", "green", "blue", "violet")
MAX_CONTEXT_SAMPLES = 32


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _sample(values: list[Any]) -> list[Any]:
    if len(values) <= MAX_CONTEXT_SAMPLES:
        return values
    return [values[round(i * (len(values) - 1) / (MAX_CONTEXT_SAMPLES - 1))] for i in range(MAX_CONTEXT_SAMPLES)]


def _stats(values: list[float], unit: str) -> dict[str, Any]:
    return {"count": len(values), "unit": unit, "first": values[0], "last": values[-1],
            "min": min(values), "max": max(values), "mean": sum(values) / len(values),
            "change": values[-1] - values[0]}


def sensor_evidence(hardware: dict[str, Any] | None) -> dict[str, Any]:
    if not hardware or hardware.get("model") == "mock-spectrometry":
        return {}
    rows = []
    for source in (hardware.get("sensor_readings") or [])[:256]:
        if not isinstance(source, dict):
            continue
        row = {key: source.get(key) if _number(source.get(key)) else None for key in ("t", *CHANNELS)}
        row["swept"] = source.get("swept") is True
        for key in ("sweep", "sweepS"):
            source_sweep = source.get(key) or {}
            if not isinstance(source_sweep, dict):
                source_sweep = {}
            row[key] = {color: value if _number(value) else None for color, value in source_sweep.items() if color in COLORS}
        rows.append(row)
    # The classifier spectrum is indexed by color, not by time.
    trace_values = (
        [row["absT"] for row in rows if not row["swept"]]
        if hardware.get("model") == "truepill-snapshot"
        else (hardware.get("spectrum") or [])
    )
    trace = [v for v in trace_values[:4096] if _number(v)]
    if not rows and not trace:
        return {}
    channels = {}
    for key, unit in CHANNELS.items():
        values = [r[key] for r in rows if _number(r[key]) and (key in ("tC", "stir", "darkTrans", "darkScat") or not r["swept"])
                  and not (key == "tC" and r[key] in (-127, 85))]
        if values:
            channels[key] = _stats(values, unit)
    if trace and "absT" not in channels:
        channels["absT"] = _stats(trace, "absorbance")
    for key in ("sweep", "sweepS"):
        for color in COLORS:
            values = [r[key][color] for r in rows if _number(r[key].get(color))]
            if values:
                channels[f"{key}.{color}"] = _stats(values, "mV")
    times = [r["t"] for r in rows if _number(r["t"]) and r["t"] >= 0]
    return {"measurements": {
        "status": "recorded", "sample_count": hardware.get("sensor_sample_count") or len(rows) or len(trace),
        "stored_sensor_samples": len(rows), "duration_seconds": max(times) - min(times) if times else None,
        "channels": channels, "sensor_readings": _sample(rows), "absorbance_trace": _sample(trace),
        "context_sample_limit": MAX_CONTEXT_SAMPLES,
        "interpretation": "Measured optical response over time, not a calibrated drug identity, purity or potency result. Negative readings and missing channels are retained; investigate baseline and sensor quality when interpreting them.",
    }}


def measurement_sentence(measurements: dict[str, Any]) -> str:
    count = measurements.get("sample_count", 0)
    text = f"The hardware recorded {count} sensor samples."
    channels = measurements.get("channels") or {}
    for key, label in (("absT", "Transmission absorbance"), ("trans", "Transmission"), ("scat", "Scattering")):
        stats = channels.get(key)
        if stats:
            text += f" {label} changed from {stats['first']:.3g} to {stats['last']:.3g} {stats['unit']} (range {stats['min']:.3g}–{stats['max']:.3g})."
    return text
