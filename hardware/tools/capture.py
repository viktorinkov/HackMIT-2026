"""Talk to the board: optionally send a key, then print whatever comes back for N seconds.

    python3 tools/capture.py [seconds] [key]
"""
import glob, sys, time, serial

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 30
key = sys.argv[2] if len(sys.argv) > 2 else None
port = sorted(glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial*"))[0]
ser = serial.Serial(port, 115200, timeout=1)
ser.dtr = True
ser.rts = True
time.sleep(0.3)
ser.reset_input_buffer()
if key:
    ser.write(key.encode())
end = time.time() + secs
while time.time() < end:
    line = ser.readline().decode("utf-8", "replace").rstrip()
    if line:
        print(line, flush=True)
ser.close()
