"""Read the in-song HUD counters out of a frame the watcher already saved.

`hudwatch` counts *changes* (it must, cheaply, at hundreds of frames a second) and so never decodes
what the digits say. The result page reader does decode digits, and the two are the same font family
at different sizes -- which is all that stood between this file and a new instrument: the classifier
normalizes a glyph onto a 24x28 canvas before matching, so the HUD's ~14 px digits match the
templates cut from the result page's ~31 px ones once the height floor is allowed to come down
(`resultread.read_cell(min_h=...)`).

Why it matters: the counter values are the **ordinal** of the judgement that made the frame. A
non-PERFECT event's *time* cannot name the note it belongs to (measured: 121 ms of spread against an
80-160 ms note grid, and a MISS is only counted when the note leaves the window, so its time is
late by construction). The five counters summed says "this was the Nth judged object", exactly the
number that made 0056_03's 628 findable by hand -- except read from the frame the watcher saved at
the time, for every round whose frames are still on disk, with nothing new to capture.

Run from the repo root:  python tools/hudread.py [frame ...]
"""
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hudwatch                                              # noqa: E402
import resultread as rr                                      # noqa: E402

# The four non-PERFECT rows are hudwatch's; PERFECT sits one 23 px pitch above GREAT. The constant
# used to be `ROWS[0][1] - PITCH - 1 .. + 15` = (132, 148), which is wrong twice over, and the
# measurement below is what settles it. Measured over 60 saved event frames, the lit band of each
# row (x 1148..1190, `min(RGB) > 220`, the mode of the first and last lit row):
#
#     PERFECT 136..149   GREAT 159..172   GOOD 182..195   BAD 205..217   MISS 228..240
#
# -- so the bands are 14 rows tall on a 23 px pitch, and hudwatch's own windows (GREAT 156..174)
# pad the band by 3 above and 2 below. Hudread's *PERFECT* window was built from the bottom row
# upward and came out as 132..148: four rows of padding wasted at the top and the band's last row
# (149) **clipped**, on every single read. That is the row whose value feeds `ordinal`, the number
# the #111 counting study reads, and a clipped glyph misreads silently (`_num` -> None).
#
# Derived from the measured band start rather than from PITCH arithmetic, so it cannot drift off the
# glyph again: 136 is the first lit row, 135 is the last dark one above it, and the window then has
# to cover the band. The sibling rows keep hudwatch's conventions untouched (hudgate pins those).
_PERFECT_TOP = 136
PERFECT_ROW = ("PERFECT", _PERFECT_TOP - 1, _PERFECT_TOP + 15)
ROWS = [PERFECT_ROW] + [(r, y0, y1) for r, y0, y1 in hudwatch.ROWS]
# A JUST 激奏空間 round draws a sixth row above PERFECT (user m28650). The block stays top-anchored
# at 136, so JUST takes the window PERFECT had and every other row moves down one 23 px pitch --
# read with the five-row bands, that round reports JUST as PERFECT, PERFECT as GREAT, ... and MISS
# as nothing at all (measured on g1684: the five-row read gives MISS 1 where the result page says
# BAD 1 / MISS 0; the six-row read agrees with the page on both). Same detector as the watcher's.
JUST_ROWS = ([("JUST", PERFECT_ROW[1], PERFECT_ROW[2])]
             + [(r, y0 + hudwatch.JUST_SHIFT, y1 + hudwatch.JUST_SHIFT) for r, y0, y1 in ROWS])
# The HUD's leading zeros are drawn dim, so the threshold does two jobs at once: keep the lit
# digits, drop the padding (a row that never moved then reads as nothing, which is the correct
# answer -- zero). Measured over the 189 saved event frames: at 190 not one frame yields a complete
# five-row read (the dim zeros come back as '?'), at 220 114 do and 110 of those agree with the
# count the log already claimed, at 230 it collapses to 51. 220 is where the lit digits live.
INK = 220
MIN_H_HUD = 8          # the result page's floor of 16 px rejects a 14 px HUD glyph outright


def counters_arr(im, templates=None):
    """{row: value} from an RGB array; a row that reads nothing is 0, one that reads '?' is None."""
    arr = np.asarray(im)
    rows = JUST_ROWS if hudwatch.just_layout(arr) else ROWS
    mn = arr.min(axis=2)
    tpl = templates if templates is not None else rr.load_templates()
    out = {}
    for name, y0, y1 in rows:
        s, _det = rr.read_cell(mn > INK, y0, y1 + 1, hudwatch.X0, hudwatch.X1, tpl,
                               min_h=MIN_H_HUD)
        out[name] = 0 if s == "" else rr._num(s)
    return out


def counters(path, templates=None):
    """counters_arr for a saved frame. One of research/frames' pngs is truncated; that reads as
    all-None rather than raising, because callers sweep hundreds of frames and a bad png is not a
    finding."""
    try:
        im = Image.open(path).convert("RGB")
    except (OSError, ValueError):
        # Which layout it would have been cannot be read off a frame that will not open; answer
        # with every row either layout has, all None -- `ordinal` then says "unknown", not zero.
        return {name: None for name, _, _ in JUST_ROWS + ROWS}
    return counters_arr(im, templates)


def ordinal(c):
    """Which judged object this frame caught: the sum of the five (six with JUST) running counters.

    A JUST is a judged object like any other -- the result page folds it into its PERFECT row, and
    the game's own judgement count includes it -- so it is summed in, not dropped.

    None unless every row read -- a missing row is not a zero, and guessing zero would silently
    invent an ordinal that the seam analysis downstream would trust.
    """
    return None if any(v is None for v in c.values()) else sum(c.values())


def main(argv):
    tpl = rr.load_templates()
    paths = argv or sorted(
        os.path.join(hudwatch.FRAMES, f) for f in os.listdir(hudwatch.FRAMES)
        if f.startswith("hud_") and f.endswith(".png"))[:12]
    for p in paths:
        c = counters(p, tpl)
        print(f"{os.path.basename(p):<26} " + " ".join(f"{k}={v}" for k, v in c.items())
              + f"   第 {ordinal(c)} 个判定物")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
