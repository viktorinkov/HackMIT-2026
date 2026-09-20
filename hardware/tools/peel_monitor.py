#!/usr/bin/env python3
"""Live dashboard for the Peel rig. Reads the JSON stream from firmware/17_stream.

    python3 tools/peel_monitor.py [/dev/cu.usbmodemNNNN]

Shows transmission, scatter, absorbance, temperature, stirrer speed and the last four-colour
sweep, redrawn in place once a second. Every line is also appended to its own CSV under runs/,
so a run is recorded whether or not you were watching.

Close the Arduino Serial Monitor first: macOS lets only one program hold the port.

Type a command and press Enter. They are forwarded to the board:
    b   take a blank now (clear water in the container, cover on)
    z   mark t = 0 by hand
    a   toggle automatic t = 0 on a sudden transmission drop
    s   stop the run and reset the clock
    m   toggle the stirrer
    q   quit the monitor (the board keeps running)
"""
import glob
import json
import os
import queue
import sys
import threading
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial missing. Run: pip3 install pyserial")

ESC = "\033["
HOME, CLR_EOS, CLR_EOL = ESC + "H", ESC + "J", ESC + "K"
BOLD, DIM, OFF = ESC + "1m", ESC + "2m", ESC + "0m"
GREEN, RED, YELLOW, CYAN = ESC + "32m", ESC + "31m", ESC + "33m", ESC + "36m"

FULL_SCALE_MV = 3300          # the ADC ceiling, so bars are comparable between channels
BAR_WIDTH = 24
COLOURS = ["red", "yellow", "green", "blue"]


def bar(value, full=FULL_SCALE_MV, width=BAR_WIDTH):
    if value is None:
        return "?" * width
    n = int(max(0.0, min(1.0, value / full)) * width)
    return "█" * n + "·" * (width - n)


def fmt(value, unit="", places=0):
    if value is None:
        return "--"
    return f"{value:.{places}f}{unit}"


class Board(threading.Thread):
    """Reads the port in the background so the display never blocks on serial."""

    def __init__(self, port):
        super().__init__(daemon=True)
        self.ser = serial.Serial(port, 115200, timeout=2)
        self.q = queue.Queue()
        self.notes = []          # the board's own '#' lines, newest last

    def run(self):
        while True:
            try:
                raw = self.ser.readline().decode(errors="replace").strip()
            except Exception:
                time.sleep(0.5)
                continue
            if not raw:
                continue
            if raw.startswith("#"):
                self.notes.append(raw.lstrip("# ").strip())
                del self.notes[:-3]
                continue
            if raw.startswith("{"):
                try:
                    self.q.put(json.loads(raw))
                except ValueError:
                    pass

    def send(self, ch):
        try:
            self.ser.write(ch.encode())
        except Exception:
            pass


def render(d, board, port, rows, csv_path):
    t = d.get("t", -1)
    elapsed = "not started" if t is None or t < 0 else f"{t:.0f} s"
    absT, absS = d.get("absT"), d.get("absS")
    blanked = GREEN + "set" + OFF if absT is not None else YELLOW + "none yet, press b" + OFF
    stir = d.get("stir", 0)
    stir_txt = (GREEN + f"{stir} %" + OFF) if stir else (DIM + "off" + OFF)
    sweep = d.get("sweep", {}) or {}
    sat = d.get("swept")

    out = [
        f"{BOLD}PEEL{OFF}  live rig monitor{' ' * 8}{DIM}{port}   {time.strftime('%H:%M:%S')}{OFF}",
        "",
        f"  elapsed   {BOLD}{elapsed:<14}{OFF}  stirrer  {stir_txt}",
        f"  blank     {blanked:<24}  temp     {fmt(d.get('tC'), ' C', 2)}",
        "",
        f"  transmission  {fmt(d.get('trans'), ' mV'):>8}  {bar(d.get('trans'))}  "
        f"abs {fmt(absT, '', 3) if absT is not None else '--'}",
        f"  scatter       {fmt(d.get('scat'), ' mV'):>8}  {bar(d.get('scat'))}  "
        f"abs {fmt(absS, '', 3) if absS is not None else '--'}",
        "",
        "  sweep   " + "   ".join(
            f"{CYAN}{c}{OFF} {fmt(sweep.get(c), '', 0):>5}" for c in COLOURS
        ) + ("   " + DIM + "(sweeping)" + OFF if sat else ""),
        "",
        f"  {DIM}{rows} rows -> {csv_path}{OFF}",
    ]
    for note in board.notes:
        out.append(f"  {DIM}board: {note}{OFF}")
    out += [
        "",
        f"  {DIM}b blank  |  z t=0  |  a auto t=0  |  s stop  |  m stirrer  |  q quit{OFF}",
    ]
    sys.stdout.write(HOME + ("\n".join(line + CLR_EOL for line in out)) + "\n" + CLR_EOS)
    sys.stdout.flush()


def main():
    # usbmodem = native USB (XIAO, or the DevKitC's port marked USB). The usbserial/SLAB/wch
    # names are the DevKitC's other port, the one through the bridge chip marked UART.
    found = sum((sorted(glob.glob(g)) for g in ("/dev/cu.usbmodem*", "/dev/cu.usbserial*",
                                                "/dev/cu.SLAB_USBtoUART*", "/dev/cu.wchusbserial*")), [])
    port = sys.argv[1] if len(sys.argv) > 1 else (found + [None])[0]
    if not port:
        sys.exit("no board found: plug it in (DevKitC: the port marked USB), and close Serial Monitor")

    board = Board(port)
    board.start()

    here = os.path.dirname(os.path.abspath(__file__))
    run_dir = os.path.join(here, "..", "runs")
    os.makedirs(run_dir, exist_ok=True)
    csv_path = os.path.join(run_dir, time.strftime("run_%Y%m%d_%H%M%S.csv"))
    csv_rel = os.path.relpath(csv_path, os.path.join(here, ".."))

    keys = queue.Queue()

    def read_keys():
        for line in sys.stdin:
            for ch in line.strip():
                keys.put(ch)

    threading.Thread(target=read_keys, daemon=True).start()

    rows = 0
    last = None
    sys.stdout.write(ESC + "2J")
    with open(csv_path, "w") as f:
        f.write("wall,t_s,trans_mv,scat_mv,absT,absS,tC,stir_pct,"
                + ",".join(f"sweep_{c}" for c in COLOURS) + ",swept\n")
        while True:
            while not keys.empty():
                k = keys.get().lower()
                if k == "q":
                    sys.stdout.write(ESC + "2J" + HOME)
                    print(f"stopped. {rows} rows in {csv_rel}")
                    return
                if k in "bzasm":
                    board.send(k)

            try:
                d = board.q.get(timeout=1.0)
            except queue.Empty:
                if last:
                    render(last, board, port, rows, csv_rel)
                continue

            last = d
            rows += 1
            sweep = d.get("sweep", {}) or {}
            f.write(",".join(str(x if x is not None else "") for x in [
                time.strftime("%H:%M:%S"), d.get("t"), d.get("trans"), d.get("scat"),
                d.get("absT"), d.get("absS"), d.get("tC"), d.get("stir"),
                *[sweep.get(c) for c in COLOURS], d.get("swept"),
            ]) + "\n")
            f.flush()
            render(d, board, port, rows, csv_rel)


if __name__ == "__main__":
    main()
