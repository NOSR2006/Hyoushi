"""Calibrate raw event-node axes -> Android logical (display) coordinates.

Holds a touch down at a known raw (x, y), then reads the mapped coordinates straight out of
`dumpsys input` (TouchState/CursorState), so no UI guessing is involved.
"""
import re
import subprocess
import sys
import time

sys.path.insert(0, "tools")
from inject import ADB, DEVICE, TouchInjector  # noqa: E402


def dump_touch_state() -> str:
    return subprocess.run(
        [ADB, "-s", DEVICE, "shell", "dumpsys input"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout


def extract_pointer(out: str) -> list[dict]:
    """Pull every x/y/rawX/rawY/pressure tuple that belongs to an active pointer."""
    rows = []
    for m in re.finditer(
        r"\(\s*(?P<id>\d+)\)\s*Pointer\([^)]*\)\s*.*?toolType=(?P<tool>\w+).*?"
        r"id=(?P<pid>-?\d+).*?x=(?P<x>[\d.]+)\s+y=(?P<y>[\d.]+)\s+rawX=(?P<rx>-?[\d.]+)\s+rawY=(?P<ry>-?[\d.]+)",
        out,
        re.S,
    ):
        rows.append(m.groupdict())
    if rows:
        return rows
    # Fallback: the compact "TouchState" blocks list x= / y= lines per device.
    for block in re.findall(r"Xiaomi Touchscreen(.*?)(?=Device \d:|$)", out, re.S):
        nums = re.findall(r"(?:^|\s)(?:x|y|rawX|rawY|value)=(-?[\d.]+)", block)
        if nums:
            rows.append({"raw": nums})
    return rows


def main() -> None:
    pts = [(100, 100), (600, 1100)]
    if len(sys.argv) > 2:
        pts = [(int(sys.argv[1]), int(sys.argv[2]))]
    inj = TouchInjector()
    try:
        for rx, ry in pts:
            inj.touch_down(0, rx, ry, 1)
            time.sleep(1.2)
            out = dump_touch_state()
            inj.touch_up(0)
            time.sleep(0.4)
            rows = extract_pointer(out)
            print(f"raw({rx},{ry}) -> {rows if rows else 'no pointer rows; dumping grep lines'}")
            if not rows:
                for line in out.splitlines():
                    if re.search(r"Touch State|pointer\(|x=|rawX=", line, re.I):
                        print("   ", line.strip()[:160])
    finally:
        inj.close()


if __name__ == "__main__":
    main()
