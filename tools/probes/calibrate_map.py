"""Calibrate event4 raw axes -> screen logical coords by recording what `input tap` writes."""
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from locate import ADB, DEVICE  # noqa: E402  路径集中探测：见 tools/locate.py

NODE = "/dev/input/event4"
ABS_X, ABS_Y, TRK, BTN_TOUCH = 0x35, 0x36, 0x39, 0x140


def tap(sx, sy):
    subprocess.run([ADB, "-s", DEVICE, "shell", "input", "tap", str(sx), str(sy)],
                   check=True, capture_output=True)


def main():
    probes = [(int(a), int(b)) for a, b in
              (p.split(",") for p in sys.argv[1:])] if len(sys.argv) > 1 else \
        [(100, 100), (640, 360), (1100, 600), (200, 650), (1200, 100)]

    proc = subprocess.Popen([ADB, "-s", DEVICE, "shell", f"getevent {NODE}"],
                            stdout=subprocess.PIPE, text=True, bufsize=1)
    events = []

    def drain():
        while True:
            line = proc.stdout.readline()
            if not line:
                return
            m = re.match(r"^\s*([0-9a-f]{4})\s+([0-9a-f]{4})\s+([0-9a-f]{4,8})", line.strip())
            if m:
                events.append((int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16)))

    import threading
    t = threading.Thread(target=drain, daemon=True)
    t.start()
    time.sleep(1.0)

    results = []
    for sx, sy in probes:
        before = len(events)
        tap(sx, sy)
        deadline = time.time() + 1.6
        while time.time() < deadline and not any(
                c == TRK and v == -1 for ty, c, v in events[before:]):
            time.sleep(0.05)
        down = [e for e in events[before:] if e[1] in (ABS_X, ABS_Y)]
        gx = [v for ty, c, v in down if c == ABS_X]
        gy = [v for ty, c, v in down if c == ABS_Y]
        results.append((sx, sy, gx[0] if gx else None, gy[0] if gy else None))
        time.sleep(0.2)

    proc.kill()
    print(f"{'screen_x':>8} {'screen_y':>8} {'raw_x':>8} {'raw_y':>8}")
    for sx, sy, rx, ry in results:
        print(f"{sx:>8} {sy:>8} {str(rx):>8} {str(ry):>8}")


if __name__ == "__main__":
    main()
