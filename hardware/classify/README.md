# Peel: classification

Turns the rig's serial stream into the `hardware` observation the backend stores on a scan:
how much of a coloured active is in the vial, whether it released, and whether the read can
be trusted at all.

```
stream.py        parse the 17_stream lines (docs/PROTOCOL.md); live board, raw log or peel_monitor CSV
run.py           one run since t = 0: plateau, % released, t80, turbidity, four-colour absorbance
calibration.py   absorbance -> mg/L, a line fitted on standards read on this rig
products.py      per-product settings: label mg, volume, dilution, the LED the active absorbs
classify.py      the verdict: pass_screen / refer_to_lab / cannot_verify, with reasons
bridge.py        map that onto PillHardwareResult (real / substandard / fake / unknown) and POST /scans
sim.py           a synthetic run in the firmware's own format
cli.py           calibrate, run, replay, sim
```

Stdlib only; `pyserial` for a live board. Run everything from `hardware/`.

## Calibrate (once per rig, per product)

```bash
python3 -m classify.cli calibrate --product riboflavin
```

Takes a blank on water, then reads each standard you put in the vial and fits a line.
The result lands in `classify/calibrations/riboflavin.json` with the slope, R², and the
detection limit from the blank noise. Keep absorbance under 1.0: dilute rather than trust
the top of the curve.

## Run

```bash
python3 -m classify.cli run --product riboflavin --blank --post http://localhost:8000 \
    --bottle bottle.json --imprint imprint.json
```

Waits for t = 0 (the board detects the transmission drop when the sample goes in), watches
until the fast channel flattens, classifies, prints the result, and creates the scan with the
hardware observation alongside the photo results. Without `--post` it only prints. Ctrl-C
classifies whatever was read so far.

The active's colour must be the fast channel: riboflavin absorbs blue, so flash the firmware
with `-DFAST_LED=3`. If the fast LED is another colour the classifier falls back to the
30-second sweep and says so in `reasons`.

## Replay and simulate

```bash
python3 -m classify.cli replay --product riboflavin --csv ../runs/run_20260920_0110.csv
python3 -m classify.cli sim --dose 0.5 > half.jsonl && python3 -m classify.cli replay --log half.jsonl
```

## What the verdict means

| status | when |
|---|---|
| `pass_screen` | dose inside the label band (90–110 %) and every gate held |
| `refer_to_lab` | the active was seen but the dose is outside the band, or it released too slowly; or no absorbance at all for the claimed product |
| `cannot_verify` | cloudy vial, saturated read, absorbance on colours the active does not absorb, too short a run, or no calibration |

Gates and bands live on the `Product`. The release comparator (75 % at 1 h) is USP <2040>'s
number for riboflavin, quoted as a reference point only: the rig runs room-temperature water,
not the compendial medium.

```bash
python3 -m pytest classify/tests
```
