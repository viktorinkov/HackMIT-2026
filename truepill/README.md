# TruePill — the spectral classification layer

Turns what the Peel bench rig measures into a verdict on the tablet: which
substance, how much of it, whether it matches the label. Tuned to the real
rig from real recordings ([HARDWARE_TUNING.md](HARDWARE_TUNING.md)).

The backend installs this package and calls `classify_capture()` from `POST /pill`.
The phone sends separate water and dissolved pill captures.
See [the API and capture workflow](../backend/pill-hardware.md).

## Use it

```python
from truepill import classify_capture, load_library, to_pill_hardware_result, PEEL_BENCH_RIG

library = load_library()                 # the rig's measured references (advil, pepto)

# 17_stream lines: ~50 s with clear water in the cup, then ~50 s once the
# tablet has dissolved. Raw serial text, parsed dicts, or the envelopes in
# hardware/data/*.jsonl all work; comments and torn lines are skipped.
result = classify_capture(blank_lines, sample_lines, library, expected_drug="advil")

result.verdict       # PASS | DILUTED | OVER_CONCENTRATED | ADULTERATED | UNKNOWN | NO_SIGNAL | INVALID_READING
result.flags         # why, in plain words

payload = to_pill_hardware_result(result, PEEL_BENCH_RIG.classifier)
# {"status": "real", "spectrum": [...], "pill_type": "advil", "degraded": False, "confidence": 0.94}
# -> PillHardwareResult(**payload) validates as-is
```

| Verdict | Backend `status` |
|---|---|
| `PASS` | `real` |
| `DILUTED`, `OVER_CONCENTRATED` | `substandard` (`degraded: true`) |
| `ADULTERATED` | `fake` |
| `UNKNOWN`, `NO_SIGNAL`, `INVALID_READING` | `unknown` |

A reading the rig could not take is `unknown`, never `fake`: nobody should be
told their medicine is counterfeit because a lead was loose. `confidence` is
how far the match cleared its threshold — a ranking score, not a probability.

Lower level: `classify(dark, blank, sample, library, config=...)` takes arrays
directly, and `match_spectrum()` is the Mahalanobis matcher the time-resolved
pipeline uses.

## Drop it in anywhere

Every import inside the package is relative, and data files are found
relative to the module that reads them. So the directory works at the repo
root, inside another package, or renamed, with no `sys.path` edits — and its
generically named modules (`models`, `noise`, `library`, `server`) cannot
collide with the backend's.

```bash
cp -r truepill backend/src/backend/truepill      # then: from backend.truepill import classify_capture
```

`tests/test_relocatable.py` proves this on every run: it copies the package
into a nested package and under a different name, and drives each copy from a
clean interpreter.

The backend declares a local dependency on this package.
Its locked installation includes NumPy, SciPy, and the measured library JSON.
`import truepill` does not import FastAPI.
The optional `truepill.server` module requires the additional dependencies in `requirements.txt`.

## Run the tests

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r truepill/requirements-dev.txt
python -m pytest truepill            # 71 tests, from the directory that holds truepill/
```

Python 3.10+. CI runs them on every change under `truepill/`
(`.github/workflows/truepill.yml`).

```bash
python -m truepill.rig_characterize truepill/data/captures/2026-09-20_rig_static.jsonl   # rig health check
python -m truepill.noise --threshold 4.0                                                  # Monte Carlo ROC
uvicorn truepill.server:app                                                               # time-resolved WebSocket server
```

## What is real and what is not

| | |
|---|---|
| The maths (absorbance, cosine match, NNLS, Mahalanobis, kinetics, f2) | real, standard, tested |
| Rig tuning (`hardware.py`) | **measured** on the rig; evidence is thin — 45 independent noise pairs, two library entries. Provisional. |
| Rig library (`data/library/`) | measured on the rig 2026-09-10; re-record before relying on it |
| Default library and the time-resolved path's references (`mock_data.py`) | **synthetic** Gaussian bands, invented to be distinguishable |
| The time-resolved pipeline (`kinetics`, `dissolution`, `verdict`, `server`) | works end to end **against its own simulator**. `17_stream` sends one channel at 1 Hz plus a sweep every 10 s, not the per-reading spectra this path consumes, so it is not fed by the rig today. |

Read [HARDWARE_TUNING.md](HARDWARE_TUNING.md) before quoting any accuracy
figure: when measured, the rig itself was faulted (slow detector, unstable
light level), the match margin is the fourth decimal of a cosine, and
composition analysis is close to blind on three channels.
[CHANGES.md](CHANGES.md) has the design rationale for the pipeline thresholds.

## Layout

```
__init__.py          the public API
classification.py    classify(), ClassifierConfig, match_spectrum()
hardware.py          the rig's measured profile; classify_capture(), load_library(), stream parsing
backend_bridge.py    ClassificationResult -> the backend's PillHardwareResult shape
noise.py             noise model, Sigma builder, Monte Carlo ROC
rig_characterize.py  rig health check + noise figures from a capture
kinetics.py dissolution.py verdict.py library.py models.py server.py   the time-resolved pipeline
mock_data.py         synthetic substances and simulated runs
data/captures/       real recordings off the rig (the tests run against them)
data/library/        the rig's measured reference spectra
tests/
```
