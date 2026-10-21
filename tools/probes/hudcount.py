"""The in-song HUD counter reader keeps reading what it read when the evidence was pinned.

`hudread` is a new judgement: it decodes the five live counters out of the frame `hudwatch` saves at
each event, which is how a lost key gets an ordinal ("the 628th judged object") instead of a 121 ms
guess. Nothing decoded those digits before today, so the corpus is pinned the same way the page
recogniser's is -- crops in `evidence/hud/counters/`, the values they must keep producing in
`MANIFEST.json`, chosen only from frames where the pixel read and the watcher's own tally agree.

Two directions, because a reader that always answers is indistinguishable from a reader that is
broken:
  PART 1  every pinned crop re-reads to exactly the recorded five values and ordinal.
  PART 2  slide the crop by a few pixels and the answer must move -- if it did not, the geometry
          constants would be decoration and PART 1 would be testing nothing.

No device, no live, no window.

Run from the repo root:  python tools/probes/hudcount.py
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hudread                                               # noqa: E402
import rlog                                                  # noqa: E402

DIR = Path(rlog.EVIDENCE) / "hud" / "counters"
MANIFEST = DIR / "MANIFEST.json"


def canvas(name, offset, dy=0):
    """Paste a crop back onto a black 1280x720 at its recorded origin, optionally shifted."""
    im = Image.open(DIR / name).convert("RGB")
    out = Image.new("RGB", (1280, 720), (0, 0, 0))
    out.paste(im, (offset[0], offset[1] + dy))
    return np.asarray(out)


def part1():
    man = json.load(open(MANIFEST, encoding="utf-8"))
    bad = []
    for name, rec in sorted(man.items()):
        c = hudread.counters_arr(canvas(name, rec["offset"]))
        if c != rec["counters"] or hudread.ordinal(c) != rec["ordinal"]:
            bad.append((name, rec["counters"], c))
    print(f"pinned crops: {len(man)}, 读回不一致 {len(bad)}")
    for b in bad[:4]:
        print(f"   {b[0]}: 记录 {b[1]}  现在 {b[2]}")
    print("PART 1 " + ("PASS" if man and not bad else "FAIL"))
    return bool(man) and not bad


def part2():
    """The digits must be where the constants say they are."""
    man = json.load(open(MANIFEST, encoding="utf-8"))
    moved = 0
    for name, rec in sorted(man.items()):
        for dy in (-3, 3):
            if hudread.counters_arr(canvas(name, rec["offset"], dy)) != rec["counters"]:
                moved += 1
                break
    ok = moved >= len(man) - 1        # one stubborn crop may survive a 3 px shift; a whole set may not
    print(f"shifted by +-3 px 后读数改变的 crop: {moved}/{len(man)}")
    print("PART 2 " + ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    sys.exit(0 if (part1() and part2()) else 1)
