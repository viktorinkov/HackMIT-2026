# Tuning the classification layer to the connected rig

Done 2026-09-20 against the bench rig itself. The classifier's noise
parameters and thresholds had only ever been validated against its own
simulator; this is the pass that measured them on hardware, and what it found.

## What is connected

| Port | Board | Role |
|---|---|---|
| `/dev/cu.usbmodem101` | ESP32-S3, firmware `17_stream` | the spectrometer |
| `/dev/cu.usbmodem2101` | ESP32-S3 | display only, fed over ESP-NOW |

The rig is not the instrument `classification.py` was written for:

| Simulator assumes | Rig does |
|---|---|
| 8 LEDs, 405-700 nm | a three-channel instrument: red / yellow / green |
| 12-bit ADC counts, full scale 4095 | **millivolts** (11 dB, 24-sample mean), ceiling ~3100 |
| host receives dark, blank, sample | sweep is dark-subtracted on the board; pass `dark = 0` |
| 90° sensor = fluorescence per LED | 90° sensor read only under the always-on green LED |
| read noise 3 counts, drift 1 % (guesses) | measured below |

## The rig is faulted today — read this before trusting any reading

Five minutes recorded untouched (`data/captures/2026-09-20_rig_static.jsonl`);
`python -m truepill.rig_characterize <that file>` reproduces all of it:

1. **Every sweep is negative** (29 of 29; mean −194 mV on all three colours,
   colours correlated at r = 0.99-1.00). The sweep carries no colour
   information at all.
2. **Cause: the detector is far slower than the firmware assumes.** 12 ms
   after a sweep the always-on channel reads 12 mV against a ~220 mV plateau —
   5 % recovered. Time constant ≈ 0.2-0.4 s, where `SETTLE_MS = 12` assumes
   microseconds. So "dark" is read while the detector is still falling, and
   comes out higher than every LED-on reading. That response time is a
   photoresistor's, not a TEMT6000's (PEEL_BUILD_PLAN.txt lists an LDR as the
   no-soldering-iron fallback). Fix: fit the TEMT6000, or raise `SETTLE_MS` to
   ~1500 and accept a ~6 s sweep.
3. **The light level is bistable**, flipping between ~160 and ~580 mV with
   the stirrer off and nothing switching (sd 54 %; it was 0.2-0.4 % on
   2026-09-16). Looks like an intermittent LED or sensor lead.

This repository's own recording shows the same state:
`hardware/data/session_full_cycle.jsonl` carries sweeps of
`yellow -359, green -120` mV.

**No identity threshold was fitted to today's capture** — it would be fitted
to noise. Today's data drives only the input gate, which exists because of
it. Fed today's real sweep, the untuned classifier answers
`ADULTERATED, match=pepto, confidence=high`. It now answers `INVALID_READING`.

## What the tuning is based on instead

The same rig, working: 53 fresh sweeps from a bench recording on 2026-09-16
(`data/captures/2026-09-16_healthy_sweeps.csv`), and the rig's own measured
library, advil and pepto, recorded 2026-09-10
(`data/library/peel_bench_rig.json`).
Noise is never simulated: thresholds are checked against real
(blank, sample) pairs cut from the recording, blank before sample, no sweep
shared. Sliding windows give 990 such pairs, but they overlap heavily: the
recording holds only **45 non-overlapping pairs**, and that, not 990, is the
evidence (see Verification).

Measured:

- Sweep noise is **6-8 % per channel and common-mode** (r = 0.92): the whole
  spectrum shifts by a flat 0.029 AU per sweep. The simulator's Σ is ~2.4×
  tighter (σ 0.0145 vs 0.035 AU per channel) and, more importantly, diagonal:
  it treats as three independent errors what is really one shared one.
- It is **autocorrelated** (0.55 at 10 s lag). Averaging 5 sweeps gives
  0.021 AU, not the 0.013 that √5 promises. Tuning that assumes independent
  sweeps is wrong by that factor — the first pass made that mistake, and it
  moved the thresholds.
- The stirrer matters: 0.017 AU off, 0.042 AU at 100 %. The firmware's
  current 30 % was never recorded.

## What changed

`classification.py` — tunables gathered into `ClassifierConfig`;
`classify(..., config=)`. Defaults are the old constants, so the simulator
path is untouched (the original simulator tests pass; Monte Carlo output
identical).
New verdict `INVALID_READING` behind `strict_inputs`, returned for a reading
the optics cannot have produced, rather than clipping it into shape:

| Input | Lenient (simulator) path | `strict_inputs` |
|---|---|---|
| sample at/below dark (today's rig) | clipped to A = 6 → "pepto, high" | refused |
| any one channel's blank under the floor | channel zeroed → `UNKNOWN @ 0.81`, blaming the pill | refused: all three channels are required |
| sample brighter than blank beyond the noise floor | clipped to 0 → "clear water" | refused: "take a fresh blank". This is what the rig's ~3.6× light-level jumps produce. |
| NaN / inf | **crashes** inside `nnls` | refused |

`noise.py` — `NoiseParams.common_mode_abs_sd`, a rank-1 term in Σ. Default 0.
Rig values: common-mode 0.028 AU, independent 0.0082 AU per channel, carried
as an absorbance-domain term because the measured residual is proportional to
signal, not shot-like.

`hardware.py` — `PEEL_BENCH_RIG`: the config, with each number's provenance
beside it.

| Tunable | Simulator | Rig | Why |
|---|---|---|---|
| `match_threshold` | 0.935 | **0.9995** | 3 all-positive channels put everything within cosine 0.98 of everything; a grey filter scored 0.9934 "high". Measured: worst genuine 0.99975, best wrong drug 0.99930. |
| `strong_match_threshold` | 0.97 | 0.9998 | genuine p1 |
| `min_signal_absorbance` | 0.02 | 0.10 | water vs water reaches 0.083 |
| `min_dynamic_range` | 1 count | 50 mV | 5σ of the weakest channel |
| `full_scale` | 4095 | 3100 mV | units |
| `adulterant_fraction` | 0.10 | 0.42 | see limits |
| sweeps averaged | 1 | 5 | one sweep accepts the wrong drug 1.1 % of the time |

## Verification

A second pass, done adversarially after the tuning, because the first tests
were tuned on the same 53 sweeps they checked. It found three defects, all
fixed; they are listed because the fixes changed shipped numbers.

| Check | Result |
|---|---|
| Default path vs the original git code, 2 × 3000 randomized readings, all six verdicts exercised | **0 mismatches, bit-exact.** Simulator behaviour is provably unchanged. |
| Fixtures vs the source recordings; test constants vs the measured library | identical |
| Shipped thresholds on a **held-out recording** (`run_20260916_221603`, never used for tuning), a split-half, and blank/sample drawn from different sessions | every verdict correct: genuine → PASS, wrong drug → ADULTERATED, grey filter → UNKNOWN, water → NO_SIGNAL |
| Σ calibration: scale-fitted Mahalanobis distance of genuine samples against chi(2) (median 1.18, p95 2.45) | **failed as first shipped** (median 0.66: Σ 1.6-2× too wide, and the wrong drug fell inside the pipeline's 4.0 cutoff 12.8 % of the time). Refitted: median 1.01 / p95 2.35; wrong drug d ≥ 5.1, and ≥ 6.9 on the holdout. |
| Input-gate probes | **three holes found** (weak single channel, NaN crash, sample brighter than blank); closed, see the table above |
| Dose estimate under real noise | +1.3 % bias, ±3.3 % (1σ). The 0.80-1.25 PASS band behaves; a pill within ~7 % of either edge can land on either side. |

**How much this proves.** Zero errors in 45 independent pairs bounds each
error rate at roughly **6 % (95 % confidence)**, not at zero — and the holdout
adds only 3 independent pairs. Two library entries, one ten-minute recording,
one stand-in for an unknown substance. The tuning is correct for the data that
exists; the data is thin. Treat the numbers as provisional until the repaired
rig has recorded more.

## Limits this exposed — do not quote past them

- **The margin is the fourth decimal of a cosine** (0.99930 vs 0.99975). It
  holds on the recording. It is not a comfortable instrument.
- **Composition is close to blind.** Common-mode noise is a flat spectrum, and
  the flatter library entry absorbs it: the old 10 % threshold called 43 % of
  genuine advil adulterated. At 0.42 no genuine reading is flagged, but a true
  50/50 advil+pepto mixture is caught on composition only ~33 % of the time
  (99.5 % if the label says advil, via the identity check). Pinned by
  `test_half_and_half_mixture_is_caught_through_the_label_only`.
- **Two library entries.** Open-set rejection is tested against one stand-in,
  a grey filter. A lookalike that is not in the library is, by definition,
  the case that matters, and it is barely tested.
- **This is a three-channel instrument by design**, so the thin margin and
  the near-blind composition above are properties of the instrument, not of
  today's fault: repairing the detector fixes the negative sweeps, it does
  not widen that margin. The host reads red / yellow / green by name; the
  firmware's sweep object carries other keys as well (`17_stream` on main
  prints six), and none of them reaches the classifier, as `null` or as a
  number. Pinned by `test_only_the_rigs_three_channels_are_read_from_a_sweep`.
  The route to more channels is the IR 940 and violet LEDs already wired on
  D0/D1, which the firmware already sweeps; adding them to `RigProfile.channels`
  would mean a new library and a full retune.
- Library from 09-10, noise from 09-16, and light levels have since dropped
  ~4×. **Once the detector and the loose lead are fixed, re-record the blank
  and library (three channels), re-run `rig_characterize.py`, and retune.**
- The time-resolved path (`match_spectrum`, `verdict.py`, the server) is not
  retuned: this firmware streams one channel at 1 Hz plus a sweep every 10 s,
  not the per-reading multi-channel vectors that path consumes.
- LED wavelengths are nominal; the parts are unbinned kit LEDs.

## Side effect of this work

Opening the serial ports reset both boards, twice (`rst:0x15
USB_UART_CHIP_RESET`), despite DTR/RTS held low. No blank was stored and no
run was active, so nothing was lost. Nothing was ever written to either port.
