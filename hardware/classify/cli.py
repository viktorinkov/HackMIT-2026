"""Command line for the classification layer.

    python3 -m classify.cli calibrate --product riboflavin
    python3 -m classify.cli run --product riboflavin --post http://localhost:8000
    python3 -m classify.cli replay --product riboflavin --csv ../runs/run_x.csv
    python3 -m classify.cli sim --dose 0.5 > half.jsonl

Run from the hardware/ directory.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import mean, pstdev

from .bridge import post_scan, scan_payload
from .calibration import Calibration, fit
from .classify import classify
from .products import PRODUCTS
from .run import Run
from .stream import Board, Note, Reading, find_port, read_csv, read_log
from . import sim

HERE = Path(__file__).resolve().parent
CALIBRATIONS = HERE / "calibrations"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="classify")
    sub = parser.add_subparsers(dest="command", required=True)

    cal = sub.add_parser("calibrate", help="read standards on the live rig and fit a line")
    _common(cal)
    cal.add_argument("--seconds", type=float, default=10.0, help="averaging window per standard")

    run = sub.add_parser("run", help="watch a live run and classify it")
    _common(run)
    run.add_argument("--blank", action="store_true", help="take the blank first (water in the vial)")
    run.add_argument("--max-seconds", type=float, default=900.0)
    run.add_argument("--min-seconds", type=float, default=30.0)
    _output(run)

    replay = sub.add_parser("replay", help="classify a recorded run")
    replay.add_argument("--product", default="riboflavin", choices=sorted(PRODUCTS))
    replay.add_argument("--calibration", type=Path)
    src = replay.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", type=Path, help="a peel_monitor.py recording")
    src.add_argument("--log", type=Path, help="a raw serial capture or a sim output")
    _output(replay)

    fake = sub.add_parser("sim", help="print a synthetic run in the firmware's format")
    fake.add_argument("--dose", type=float, default=1.0, help="fraction of label")
    fake.add_argument("--plateau", type=float, default=0.7, help="absorbance at 100 %% of label")
    fake.add_argument("--seconds", type=int, default=300)
    fake.add_argument("--cloud", type=float, default=0.0)
    fake.add_argument("--fast-led", default="blue")

    args = parser.parse_args(argv)
    return {
        "calibrate": _calibrate,
        "run": _run,
        "replay": _replay,
        "sim": _sim,
    }[args.command](args)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--product", default="riboflavin", choices=sorted(PRODUCTS))
    parser.add_argument("--port", help="serial port; found automatically when omitted")
    parser.add_argument("--calibration", type=Path, help="defaults to calibrations/<product>.json")


def _output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", type=Path, help="write the result JSON here")
    parser.add_argument("--post", metavar="URL", help="POST the scan to this backend")
    parser.add_argument("--device-id", default="peel-rig")
    parser.add_argument("--bottle", type=Path, help="BottlePhotoResult JSON to include in the scan")
    parser.add_argument("--imprint", type=Path, help="ImprintPhotoResult JSON to include in the scan")
    parser.add_argument("--demo", action="store_true")


def _board(args: argparse.Namespace) -> Board:
    port = args.port or find_port()
    if not port:
        sys.exit("no board found: plug in the DevKitC's port marked USB, or pass --port")
    print(f"listening on {port}", file=sys.stderr)
    return Board(port)


def _calibration_path(args: argparse.Namespace) -> Path:
    return args.calibration or CALIBRATIONS / f"{args.product}.json"


def _calibrate(args: argparse.Namespace) -> int:
    product = PRODUCTS[args.product]
    board = _board(args)
    run = Run()
    stream = board.lines()

    input("Clear water in the vial, lid on. Enter to take the blank... ")
    board.send("b")
    blank_values = _average(stream, run, product.channel, args.seconds)
    blank_sd = pstdev(blank_values) if len(blank_values) > 1 else None
    print(f"blank: {len(blank_values)} reads, sd {blank_sd if blank_sd is None else round(blank_sd, 4)} AU")

    points: list[tuple[float, float]] = []
    while True:
        text = input("Standard concentration in mg/L (empty to finish): ").strip()
        if not text:
            break
        mg_l = float(text)
        input("Standard in the vial, lid on. Enter to read... ")
        values = _average(stream, run, product.channel, args.seconds)
        if not values:
            print("no absorbance readings; is the blank stored?")
            continue
        absorbance = mean(values)
        points.append((mg_l, absorbance))
        print(f"  {mg_l:g} mg/L -> {absorbance:.4f} AU ({len(values)} reads)")
    if len(points) < 2:
        print("need at least two standards", file=sys.stderr)
        return 1
    calibration = fit(points, product.key, product.channel, blank_sd)
    path = _calibration_path(args)
    calibration.save(path)
    print(f"slope {calibration.slope:.5f} AU per mg/L, intercept {calibration.intercept:.4f}, "
          f"R2 {calibration.r2:.4f}, LOD {calibration.lod() or float('nan'):.3f} mg/L -> {path}")
    return 0


def _average(stream, run: Run, channel: str, seconds: float) -> list[float]:
    """Absorbance on the product's channel for the next `seconds`, after a short settle."""
    values: list[float] = []
    started = time.monotonic()
    for item in stream:
        run.feed(item)
        if not isinstance(item, Reading):
            continue
        if time.monotonic() - started < 3.0:
            continue
        value = _channel_value(run, item, channel)
        if value is not None:
            values.append(value)
        if time.monotonic() - started >= seconds + 3.0:
            break
    return values


def _channel_value(run: Run, reading: Reading, channel: str) -> float | None:
    if run.fast_led == channel:
        return None if reading.swept else reading.abs_t
    if run.blank_sweep is None or not reading.sweep_complete:
        return None
    now, blank = reading.sweep[channel], run.blank_sweep[channel]
    if not now or now <= 1 or blank <= 1:
        return None
    import math

    return math.log10(blank / now)


def _run(args: argparse.Namespace) -> int:
    product = PRODUCTS[args.product]
    calibration = _load_calibration(args)
    board = _board(args)
    run = Run()
    stream = board.lines()
    if args.blank:
        input("Clear water in the vial, lid on. Enter to take the blank... ")
        board.send("b")
    print("waiting for t = 0: drop the tablet, or swap in the sample vial (press z on the board to force)",
          file=sys.stderr)
    try:
        for item in stream:
            run.feed(item)
            if isinstance(item, Note):
                print(f"board: {item.text}", file=sys.stderr)
                continue
            if not item.running:
                continue
            plateau = run.plateau()
            flat = plateau[1] if plateau else False
            print(f"t={item.t:6.0f}s  abs={item.abs_t if item.abs_t is not None else float('nan'):.4f}"
                  f"  cloud={item.cloudiness if item.cloudiness is not None else float('nan'):.3f}"
                  f"  {'settled' if flat else ''}", file=sys.stderr)
            if run.seconds >= args.max_seconds or (flat and run.seconds >= args.min_seconds):
                break
    except KeyboardInterrupt:
        print("stopped early; classifying what was read", file=sys.stderr)
    return _finish(classify(run, calibration, product), calibration, args)


def _replay(args: argparse.Namespace) -> int:
    product = PRODUCTS[args.product]
    calibration = _load_calibration(args)
    run = Run()
    items = read_csv(args.csv) if args.csv else read_log(args.log)
    for item in items:
        run.feed(item)
    return _finish(classify(run, calibration, product), calibration, args)


def _sim(args: argparse.Namespace) -> int:
    for line in sim.lines(plateau=args.plateau * args.dose, seconds=args.seconds,
                          cloud=args.cloud, fast_led=args.fast_led):
        print(line)
    return 0


def _load_calibration(args: argparse.Namespace) -> Calibration | None:
    path = _calibration_path(args)
    if not path.exists():
        print(f"no calibration at {path}; doses will not be reported", file=sys.stderr)
        return None
    return Calibration.load(path)


def _finish(result, calibration: Calibration | None, args: argparse.Namespace) -> int:
    r2 = calibration.r2 if calibration else None
    text = result.to_json(hardware_model=scan_payload(result, args.device_id, r2=r2)["hardware_model"])
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    if args.post:
        payload = scan_payload(
            result,
            args.device_id,
            r2=r2,
            bottle=_read_json(args.bottle),
            imprint=_read_json(args.imprint),
            demo=args.demo,
        )
        answer = post_scan(args.post, payload)
        print(f"scan {answer.get('scan_id')} status {answer.get('status')} rev {answer.get('revision')}",
              file=sys.stderr)
    return 0


def _read_json(path: Path | None) -> dict | None:
    return json.loads(path.read_text()) if path else None


if __name__ == "__main__":
    sys.exit(main())
