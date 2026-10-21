"""Offline regression for the relock vote's feed (`detect.sprite_blobs`).

The relock used to vote on the tap mask alone, and note_mask -- deliberately one flat pale blue
-- sees none of a long's head cap or a trace's node bar. On 0056_03, whose opening is long x4 +
trace x7 before the first tap at 6.91 s, that made the whole vote window empty by construction:
0 blobs in all 16 recorded runs (research/relock_dets_s0*.json, g118-g123), every one of them
playing the t_field fallback. The judged sprite of every kind is a bright bar carrying the centre
diamond, so `sprite_strips` keys on brightness instead of hue, and `sprite_blobs` adds those bars
to the tap population.

Part 1 replays the relock's vote arithmetic over every frame of one recorded 0056_03 opening
(research/archive/media/our_survival_open_0930, 2026-09-30, 477 frames at 31.8 fps). PASS needs:
the tap mask yields nothing to vote on over the window -- the failure itself, reproduced offline
-- and the new feed's first vote under the relock's cadence lands within +-30 ms of the
recording's own tap-voted t0 with two successive votes agreeing, a unanimous peak.

Part 2 is the pinned fixture replay (five frames of the same recording, kept as PNGs so this half
survives the archive being pruned): three kinds of sprite at three altitudes, one tap-era frame
where the union must keep every note_blob the old detector found, and no strip in the opening
window that cannot vote.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from detect import (C_FIELD, JUDGE_Y, VP_MOTION,  # noqa: E402
                    lane_at, note_blobs, sprite_blobs, vote_t0)


def cross_at(t, y, c_sec=C_FIELD, vp=VP_MOTION, judge_y=JUDGE_Y):
    """The instant a blob centre seen at (t, y) will cross the judgement row.

    Moved here 2026-10-10: the product's `detect.cross_at` had no caller under `tools/` outside
    this probe (`gatecheck.py`, the other probe that needs the geometry, keeps its own copy), so
    the copy lives with its only user.
    """
    return t + c_sec * (1.0 / (y - vp) - 1.0 / (judge_y - vp))


ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "research" / "charts" / "0056_03.hits.json"
ARCHIVE = ROOT / "research" / "archive" / "media" / "our_survival_open_0930"
# The recording's t0, voted from its own tap era (156k blob-note pairs, peak 628); the fixture
# host stamps below are perf_counter times of the same recording, so the vote replay runs on the
# real clock relationship, not a synthetic one.
T0_REC = 687914.412
# Chart seconds the relock actually samples for this chart: t_ok + 0.25 (prior) + 2.356 (first
# object) - 0.020 (pre) - 0.045 (offset) - 0.40 (the vote never thinks past this) - 0.30 (the
# recording's t0 minus its restart), i.e. relock()'s own deadline arithmetic with this chart's
# numbers.  Frames past it are the long/trace tail family the window drops by design.
WINDOW = (0.4, 1.93)
# (fixture, host stamp, what it is); the PNGs are seq 20/45/55/85/247 of the archive recording
FIXTURES = (
    ("spritebars_t0955.png", 687915.3673, "the first long's head cap, alone"),
    ("spritebars_t1736.png", 687916.1476, "both longs + the trace's split node bar"),
    ("spritebars_t2012.png", 687916.4239, "three kinds at once"),
    ("spritebars_t2895.png", 687917.3075, "both longs, one near the judgement line"),
    ("spritebars_t7960.png", 687922.3708, "taps + a long + a trace; the union keeps every tap"),
)
# Pinned from the fixture PNGs, tolerance +-3 px in the check.
PINS = {
    "spritebars_t0955.png": [(77.0, 710.0)],
    "spritebars_t1736.png": [(103.0, 554.5), (165.5, 617.5), (165.5, 661.5), (260.0, 827.5)],
    "spritebars_t2012.png": [(159.5, 518.0), (247.5, 608.5), (247.5, 670.5), (381.0, 903.0)],
    "spritebars_t2895.png": [(88.0, 717.0), (229.0, 500.5), (229.5, 445.5), (347.5, 598.0),
                             (347.5, 680.5), (350.5, 437.5), (351.0, 354.5), (431.5, 310.0),
                             (431.5, 379.5), (524.5, 283.5)],
    "spritebars_t7960.png": [(68.0, 661.5), (119.5, 672.5), (152.0, 522.5), (238.5, 581.0),
                             (295.5, 710.0), (365.0, 554.5), (448.0, 333.0), (121.5, 542.5),
                             (242.0, 815.5), (450.0, 597.5)],
}
TAP_ERA = FIXTURES[4][0]


def notes():
    with open(CHART, encoding="utf-8") as fh:
        return [(h["t_ms"] / 1000.0, h["lane"]) for h in json.load(fh)]


def fixture(name):
    path = ROOT / "evidence" / "detect" / name
    if not path.exists():
        return None
    return np.asarray(Image.open(path).convert("RGB"))


def part1():
    if not ARCHIVE.exists():
        print(f"archive recording missing: {ARCHIVE} -- restore it before trusting the feed")
        return False
    meta = json.load(open(ARCHIVE / "meta.json", encoding="utf-8"))["frames"]
    win = [m for m in meta if WINDOW[0] <= m["t"] - T0_REC <= WINDOW[1]]
    nt = notes()
    lo, hi = T0_REC - 0.22, T0_REC + 0.22
    old, new = [], []
    first_vote = None
    votes = []
    for i, m in enumerate(win):
        img = np.asarray(Image.open(ARCHIVE / f"{m['seq']:05d}.jpg").convert("RGB"))
        old.extend((m["t"], y, x) for y, x in note_blobs(img))
        new.extend((m["t"], y, x) for y, x in sprite_blobs(img))
        if (i + 1) % 8 == 0 and len(new) >= 5:          # the relock's 0.25 s vote cadence
            v = vote_t0(new, nt, lo=lo, hi=hi)
            votes.append(v)
            if first_vote is None and v[0] is not None:
                first_vote = v
    last = vote_t0(new, nt, lo=lo, hi=hi)
    ok = (len(old) < 5 and first_vote is not None and last[0] is not None
          and abs(first_vote[0] - T0_REC) <= 0.030 and abs(last[0] - T0_REC) <= 0.030
          and abs(first_vote[0] - last[0]) <= 0.030 and last[1] >= 30 and last[2] == 0)
    print(f"window frames: {len(win)}; tap-mask feed {len(old)} blobs, sprite feed {len(new)}")
    if first_vote is not None:
        print(f"first vote: {1000 * (first_vote[0] - T0_REC):+.1f} ms (peak {first_vote[1]})")
    print(f"last vote: {1000 * (last[0] - T0_REC):+.1f} ms vs recording t0, "
          f"peak {last[1]} second {last[2]}, {len(votes)} votes on the way")
    print("PART 1 " + ("PASS" if ok else "FAIL"))
    return ok


def part2():
    nt = notes()
    ok = True
    for name, t, what in FIXTURES:
        img = fixture(name)
        if img is None:
            print(f"missing fixture {name} -- restore from {ARCHIVE} (same seq number as the pin)")
            return False
        got = sprite_blobs(img)
        want = PINS[name]
        diffs = [min((abs(y - wy) + abs(x - wx) for y, x in got), default=9e9)
                 for wy, wx in want]
        kept = all(any(abs(y - by) <= 3 and abs(x - bx) <= 3 for y, x in got)
                   for by, bx in note_blobs(img))
        # No stray: any strip the window would take must land near the truth. A strip the window
        # drops (implied t0 outside +-0.22 s) is the long/trace tail family by design and is not
        # a stray. The tap-era frame is exempt: mid-song artwork is full of bright bars and the
        # relock never votes there.
        if name != TAP_ERA and t - T0_REC <= WINDOW[1]:
            strays = []
            for y, x in got:
                lane = lane_at(x, y)
                near = [t + cross_at(0.0, y) - T0_REC - tn for tn, nl in nt
                        if abs(nl - lane) <= 2.5]
                near = [d for d in near if abs(d) <= 0.22]
                if near and min(abs(d) for d in near) > 0.05:
                    strays.append((y, x))
        else:
            strays = []
        name_ok = len(got) == len(want) and all(d <= 3 for d in diffs) and kept and not strays
        ok &= name_ok
        print(f"{name}: {len(got)} strips, furthest pin off by {max(diffs):.0f} px, "
              f"taps kept {kept}, strays {len(strays)} -- {what}")
    print("PART 2 " + ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    sys.exit(0 if (part1() and part2()) else 1)
