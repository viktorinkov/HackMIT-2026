"""Health check and noise figures for the bench rig, from a 17_stream capture.

    python -m truepill.rig_characterize truepill/data/captures/2026-09-20_rig_static.jsonl
    python -m truepill.rig_characterize --port /dev/cu.usbmodem101 --seconds 300 --save out.jsonl

Leave the rig alone with clear water in the cup while it records. Capture is
passive (nothing is written to the port), but opening the port resets the
ESP32-S3, which drops any stored blank and stops a run in progress.

These are the numbers hardware.py is tuned from. Re-run after any change to
the optics, the LEDs, the detector or the firmware's SETTLE_MS, and retune.
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np

from .hardware import PEEL_BENCH_RIG, sweep_vector

FIRMWARE_SETTLE_S = 0.012        # 17_stream SETTLE_MS


def capture(port: str, seconds: int) -> list[dict]:
    import time

    import serial  # pyserial; only needed for live capture

    s = serial.Serial()
    s.port, s.baudrate, s.timeout, s.dtr, s.rts = port, 115200, 0.5, False, False
    s.open()
    lines, end = [], time.time() + seconds
    while time.time() < end:
        raw = s.readline().decode("utf-8", "replace").strip()
        if raw.startswith("{"):
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    s.close()
    return lines


def report(lines: list[dict]) -> bool:
    rig = PEEL_BENCH_RIG
    trans = np.array([ln["trans"] for ln in lines], dtype=float)
    swept = np.array([bool(ln.get("swept")) for ln in lines])
    sweeps = np.array([v for v in (sweep_vector(ln) for ln in lines) if v is not None])
    ok = True
    print(f"{len(lines)} lines, {len(sweeps)} fresh sweeps, channels {rig.channels}")
    if len(sweeps) < 10:
        print("FAULT  fewer than 10 sweeps: record for at least 2 minutes")
        return False

    # --- are the sweeps measuring LED light at all? ---------------------------
    print(f"\nsweep mean {sweeps.mean(0).round(1)} mV   sd {sweeps.std(0, ddof=1).round(1)} mV")
    nonpos = float((sweeps <= 0).mean())
    if nonpos > 0:
        ok = False
        print(f"FAULT  {nonpos:.0%} of sweep values are <= 0: the dark reading exceeds the LED-on reading.")
    floor = rig.classifier.min_dynamic_range
    weak = [c for c, m in zip(rig.channels, sweeps.mean(0)) if m <= floor]
    if weak:
        ok = False
        print(f"FAULT  channel(s) {weak} at or under the {floor:g} mV dynamic-range floor")

    # --- detector settling: fold the always-on channel on the sweep cycle -----
    idx = np.flatnonzero(swept)
    on_sweep = np.median(trans[idx])
    plateau = np.median([trans[i + p] for k, i in enumerate(idx[:-1]) for p in range(2, idx[k + 1] - i)])
    recovered = on_sweep / plateau if plateau > 0 else 0.0
    print(f"\nfast channel {FIRMWARE_SETTLE_S * 1000:.0f} ms after a sweep: {on_sweep:.0f} mV, plateau {plateau:.0f} mV ({recovered:.0%} recovered)")
    if recovered < 0.9:
        ok = False
        tau = -FIRMWARE_SETTLE_S / np.log(max(1.0 - recovered, 1e-9)) if recovered > 0 else float("inf")
        print(f"FAULT  detector has not settled in SETTLE_MS. Implied time constant >= {tau:.2f} s "
              f"(a TEMT6000 is microseconds; this is photoresistor-slow). Needs ~{4.6 * tau:.1f} s per LED for 1%.")

    # --- stability of the always-on channel away from sweeps -----------------
    calm = np.array([trans[i + p] for k, i in enumerate(idx[:-1]) for p in range(3, idx[k + 1] - i)])
    rel_sd = calm.std(ddof=1) / calm.mean() if calm.mean() > 0 else float("inf")
    print(f"\nfast channel away from sweeps: mean {calm.mean():.0f} mV, sd {rel_sd:.1%} (healthy reference: 0.2-0.4% still, ~1% stirring)")
    if rel_sd > 0.05:
        ok = False
        print(f"FAULT  light level is unstable (p10 {np.percentile(calm, 10):.0f} / p90 {np.percentile(calm, 90):.0f} mV): "
              "loose LED or sensor lead, or something moving in the beam")

    # --- noise figures for hardware.py (only meaningful on a healthy rig) -----
    if ok:
        rel = sweeps / sweeps.mean(0)
        common = np.log10(rel.mean(1))
        n = rig.sweeps_to_average
        blocks = np.array([common[i:i + n].mean() for i in range(0, len(common) - n + 1, n)])
        print(f"\ncommon-mode offset: {common.std(ddof=1):.4f} AU per sweep, "
              f"lag-1 autocorrelation {np.corrcoef(common[:-1], common[1:])[0, 1]:.2f}")
        if len(blocks) >= 4:
            print(f"  {n}-sweep mean: {blocks.std(ddof=1):.4f} AU  ->  common_mode_abs_sd = {np.sqrt(2) * blocks.std(ddof=1):.3f}")
        print(f"  channel correlation: {np.corrcoef(rel.T)[np.triu_indices(rel.shape[1], 1)].round(2)}")
        print(f"  independent residual sd (mV): {((rel - rel.mean(1, keepdims=True)) * sweeps.mean(0)).std(0, ddof=1).round(2)}")

    print("\n" + ("rig OK: figures above are fit to tune from" if ok else
                  "RIG FAULT: fix the hardware before tuning; any threshold fitted to this capture is fitted to noise"))
    return ok


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("capture", nargs="?", help="JSONL of 17_stream lines")
    p.add_argument("--port", help="record live instead, e.g. /dev/cu.usbmodem101")
    p.add_argument("--seconds", type=int, default=300)
    p.add_argument("--save", help="write the live capture here")
    args = p.parse_args()
    if args.port:
        lines = capture(args.port, args.seconds)
        if args.save:
            with open(args.save, "w") as f:
                f.writelines(json.dumps(ln, separators=(",", ":")) + "\n" for ln in lines)
    elif args.capture:
        with open(args.capture) as f:
            lines = [json.loads(ln) for ln in f if ln.startswith("{")]
    else:
        p.error("give a capture file or --port")
    sys.exit(0 if report(lines) else 1)


if __name__ == "__main__":
    main()
