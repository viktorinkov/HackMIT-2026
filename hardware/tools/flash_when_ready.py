"""Wait for the XIAO's port to appear, flash 18_selftest onto it, then capture the results.

Run it, then plug the board in. Writes everything to /tmp/selftest.log and exits when it has
either 90 seconds of stream or a failure worth reporting.
"""
import glob, os, subprocess, sys, time

CLI = "/opt/homebrew/bin/arduino-cli"
SKETCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware", "18_selftest")
FQBN = "esp32:esp32:XIAO_ESP32S3"
LOG = "/tmp/selftest.log"
DEADLINE = time.time() + 20 * 60
CAPTURE_S = 90


def ports():
    out = []
    for pat in ("/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/cu.wchusbserial*", "/dev/cu.SLAB*"):
        out += glob.glob(pat)
    return sorted(out)


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def main():
    open(LOG, "w").close()
    log("waiting for the board...")
    while not ports():
        if time.time() > DEADLINE:
            log("GAVE UP: no serial port appeared in 20 minutes")
            return 2
        time.sleep(2)
    port = ports()[0]
    log(f"port appeared: {port}")
    time.sleep(1.5)

    r = subprocess.run([CLI, "compile", "--upload", "-p", port, "--fqbn", FQBN, SKETCH],
                       capture_output=True, text=True)
    log(f"upload exit={r.returncode}")
    tail = (r.stdout + r.stderr).strip().splitlines()[-12:]
    for t in tail:
        log("  " + t)
    if r.returncode != 0:
        return 1

    # the native-USB port re-enumerates after a reset, and may come back under a new name
    time.sleep(3)
    for _ in range(20):
        p = ports()
        if p:
            port = p[0]
            break
        time.sleep(1)
    log(f"reading {port} for {CAPTURE_S} s")

    import serial
    for attempt in range(10):
        try:
            ser = serial.Serial(port, 115200, timeout=1)
            break
        except Exception as e:
            log(f"  open failed ({e}); retrying")
            time.sleep(2)
    else:
        log("COULD NOT OPEN THE PORT")
        return 1
    ser.dtr = True
    ser.rts = True
    end = time.time() + CAPTURE_S
    with open(LOG, "a") as f:
        while time.time() < end:
            line = ser.readline().decode("utf-8", "replace").rstrip()
            if line:
                print(line, flush=True)
                f.write(line + "\n")
    ser.close()
    log("capture done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
