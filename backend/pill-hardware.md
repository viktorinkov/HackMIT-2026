# Pill hardware

`POST /pill` classifies real water and pill captures through the installed `truepill` package.
It returns model `truepill-snapshot`.
The endpoint does not generate readings or accept a requested status.

## Phone capture

Connect the instrument to the Android phone with a USB data cable.
Fill the cup with clear water.
Close the lid.
Tap Water ready.
Wait for five fresh color sweeps, about 50 seconds.
Add the pill.
Tap Start stirrer.
After the pill dissolves, tap Pill dissolved.
Keep the lid closed during the sample capture.

The app records five fresh red, yellow, and green sweeps after the dissolution confirmation.
It requests a stop after 60 seconds, but only after five complete sweeps arrive.
It waits for the instrument to report that the run stopped before it calls `/pill`.
Cached sweep values do not count.
A disconnect, restart, changed water baseline, or incomplete run requires a new water capture.

`PEEL_RUN_SECONDS=0` enables manual stopping after five sample sweeps.
A shorter positive duration still waits for five sweeps.
The full raw run stays in the phone session log.
Skip hardware omits hardware from the scan and does not call `/pill`.

## Request

The JSON body contains `rig`, `pill_type`, `blank`, and `sample`.
`rig` is `peel-bench-17_stream`.
`blank` and `sample` each contain exactly five objects with this shape:

```json
{"swept": true, "sweep": {"red": 116.0, "yellow": 137.0, "green": 400.0}}
```

These numbers illustrate the format only.
Use actual millivolt readings from separate water and dissolved pill captures.
The firmware already subtracts the dark reading.
Do not subtract it again.
Do not send the single-channel `absT` series as a color spectrum.

The endpoint accepts Advil or ibuprofen, and Pepto, Pepto-Bismol, or bismuth subsalicylate as label names.
It returns `unknown` for an absent or unsupported label.
Missing, incomplete, stale, or non-finite sweeps return HTTP 422.
Physically invalid sweeps return `unknown` with verdict `INVALID_READING`.
The endpoint does not average a faulted sweep into a successful reading.

The response retains the existing `model` and `result` fields.
It adds `verdict`, `flags`, and `limitations` to explain the classification.
The app submits the returned result and model to `/scans`.
It also sends up to 256 aligned sensor samples across the full run, plus the original sample count.
Research and voice receive bounded measurements alongside the classification.
The three-color spectrum is not treated as a time trace.
Peel states the verdict first and explains the report without sensor numbers unless asked.
The research pipeline also compares the recorded time trace with synthetic reference curves.
These comparisons remain separate from the measured three-color classifier and do not establish chemical identity.

## Local setup

Use a full checkout of `codex/real-pill-integration`.
The sibling `truepill/` directory is required by the backend dependency lockfile.
From the repository root, run:

```bash
cd backend
uv sync --locked --python 3.13
```

Supply the normal backend credentials as described in [Setup](README.md#setup).
Then start the API:

```bash
uv run backend
```

The existing Runpod startup script installs the classifier through `uv sync --locked`.
This branch does not deploy or change a Runpod resource.
An older phone build that sends only `pill_type` to `/pill` receives HTTP 422.
Build the phone app from this branch when you update the backend.
The new app refuses responses from the old mock endpoint.

## Limits

The measured library contains two reference products.
The thresholds use a small set of recordings from the bench rig.
The recorded September 20 rig fault produces `unknown`, not a counterfeit finding.
Repair the detector and unstable light source before a physical acceptance test.
See [the measurements and limitations](../truepill/HARDWARE_TUNING.md).

The confidence value is a match score, not a probability.
The result does not prove authenticity or measure dose in milligrams.
The API uses the measured snapshot classifier, not the synthetic dissolution server.
Automated tests do not establish accuracy on repaired hardware.
