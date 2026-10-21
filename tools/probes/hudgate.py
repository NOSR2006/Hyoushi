"""Offline regression for the HUD gate: replay the evidence corpus, then drive the live state machine.

Two halves, because the gate has two jobs and only one of them is visible in a log line.

Part 1 is the corpus. Every strip under evidence/hud/box/hud_<tag>_<row><n>.png is the digit box of
a judgement this thread once *committed* -- that is, a candidate that survived the persistence hold.
Each run's true counts are in research/results_full.jsonl (the untrimmed record; the 100-row window
ages rows out and a regression may not depend on when it runs), so the corpus is a labelled set: frames from
runs whose result page
reads non_perfect 0 are all false positives, and the counters in them must still read 0000. The
check is hudwatch's own sequence of gates 2-3-4-5, with hudwatch's own constants, applied in commit
order per row: gate two re-decides against the settled state, gate three against the darkest box
ever seen, gate four against how far left of the right-aligned digit column the repaint reaches,
gate five against whether the drawn glyph changed at all.

Part 2 drives HudWatch itself against a scripted frame source, because the corpus only contains
settle frames and cannot exercise the transitions: a sparkle that crosses the digit column has to
produce no event, and a counter that actually carries has to produce exactly one. It replays the
same script with the gates pinned off to show the checks have teeth. The second script is the s03
case the corpus cannot hold - the thread's very first frame has an effect sitting on the counter, so
the baseline is polluted and the return to 0000 looks like a carry. Gate three is the only thing
that stops it, because the baseline gate is comparing against the polluted frame itself. The third
script is g100, the one committed frame the corpus does hold that clears gates two and three on an
ALL PERFECT run: gate four is the only thing that stops it, so part 2c replays it against its own
resting counter and pins only gate four off. Gate five's teeth are in part 1 instead, because the
frame that would show it -- a parked flash arriving on a counter that reads 0 -- is by construction
not in the corpus: only what the thread held for HOLD seconds got saved. So part 1 replays the whole
corpus twice, once with the shipped threshold and once with gate five pinned off, and requires the
ALL PERFECT runs' lines to come back.
"""
import glob
import inspect
import re
import sys
import textwrap
import types
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hudwatch                                                        # noqa: E402
import rlog                                                            # noqa: E402
from hudwatch import (CARRY_LEFT_MIN, HOLD, INK_LIT, INK_MOVE_MIN, REBASE, ROWS,  # noqa: E402
                      SETTLE_DELTA, SETTLE_MIN_PX, X0, X1, ZERO_MIN_PX)

PAT = re.compile(r"hud_(.+?)_(great|good|bad|miss)(\d+)\.png")
Y = {r: (y0, y1) for r, y0, y1 in ROWS}

# The corpus lives in evidence/, not in research/: hudwatch reads exactly one rectangle of a frame
# (`img[y0:y1, X0:X1]`, one line), so the committed-event corpus is that crop and nothing else.
# Cropping it took 825 frames from 469 MB to 4 MB, which is what lets research/ be cleaned.
BOX_DIR = Path(rlog.RESEARCH).parent / "evidence" / "hud" / "box"
CROP_Y0 = min(y0 for _r, y0, _y1 in ROWS)


def box(img, row):
    """The row's digits, max over channels, from a full frame or from a corpus strip."""
    y0, y1 = Y[row]
    if img.shape[0] < 400:                                     # a strip: rows already start at CROP_Y0
        y0, y1 = y0 - CROP_Y0, y1 - CROP_Y0
    return img[y0:y1, :X1 - X0].max(axis=2).astype(np.int16)


def full_frame(strip):
    """Put a strip back where the thread would have met it. hudwatch cannot see past the box, so
    this is the same picture to it as the original screen -- which is what part 2 needs to drive."""
    img = np.zeros((720, 1280, 3), np.uint8)
    img[CROP_Y0:CROP_Y0 + strip.shape[0], X0:X1] = strip
    return img


def load(name):
    return np.array(Image.open(BOX_DIR / name).convert("RGB"))


def corpus():
    ev = defaultdict(list)
    for p in sorted(glob.glob(str(BOX_DIR / "hud_*.png"))):
        m = PAT.search(p.replace("\\", "/"))
        if not m:
            continue
        img = np.array(Image.open(p).convert("RGB"))
        ev[(m.group(1), m.group(2).upper())].append((int(m.group(3)), box(img, m.group(2).upper())))
    return ev


def truth():
    # The untrimmed record, not the rolling window: research/results.jsonl keeps the newest 100
    # rows for the panel and ages everything else out, which is not something a regression may
    # depend on -- the first suite run after 2026-10-02's fourteen new rounds pushed g067/g100/g109
    # out of the window and this probe lost its teeth without a line of it changing.
    out = {}
    for j in rlog.read_records(rlog.HISTORY_FULL):
        if j.get("tag"):
            out[j["tag"]] = j
    return out


def script(steps):
    """[(frame, how many captures), ...] -> [(t, frame), ...] at the cadence the thread expects."""
    frames, t = [], 0.0
    for img, n in steps:
        for _ in range(n):
            t += 0.03
            frames.append((t, img))
    return frames


class _End(RuntimeError):
    """The script ran out; the thread's own capture-failed path takes it from there."""


def replay(frames, settle_min=SETTLE_MIN_PX, zero_min=ZERO_MIN_PX, left_min=CARRY_LEFT_MIN,
           ink_min=INK_MOVE_MIN, reseed_at=None):
    """Run the thread over the script with the gates pinned, so the sweep is honest.

    `reseed_at` is a script time: the source calls the watcher's reseed() the first time it serves
    a frame at or after it, which is where run.py calls it -- right after a 重试 put the counters
    back at zero.
    """
    hw = hudwatch.HudWatch(log=lambda *_: None, tag="gatecheck")

    class Scripted:
        def __init__(self, frames):
            self.frames = frames
            self.i = 0
            self.done = False

        def frame(self):
            if self.i >= len(self.frames):
                raise _End()
            t, img = self.frames[self.i]
            self.i += 1
            if reseed_at is not None and not self.done and t >= reseed_at:
                self.done = True
                hw.reseed()
            return t, img

    import types

    mod = types.ModuleType("mumucap")
    mod.frame = Scripted(frames).frame
    # The whole surface `_run` asks of the capture: `stalled_s` is the liveness question the script
    # answers with "every frame here is new", which is what the replay is actually testing.
    mod.stalled_s = lambda: 0.0
    sys.modules["mumucap"] = mod
    hudwatch.SETTLE_MIN_PX, hudwatch.ZERO_MIN_PX = settle_min, zero_min
    hudwatch.CARRY_LEFT_MIN, hudwatch.INK_MOVE_MIN = left_min, ink_min
    hw._run(0.0)                        # returns through its capture-failed path at the end
    for p in (glob.glob("research/hud_gatecheck_*.png")
              + glob.glob("research/hudreject_gatecheck_*.png")):
        Path(p).unlink()                # never let test frames into the corpus
    return hw


def part1():
    ev = corpus()
    tr = truth()
    # The state the counters were in before any of these events: the modal box over the whole
    # corpus, which is 0000 because the anchor restarts every run with nothing judged.
    by_row = {r: np.stack([c for (t, rr), e in ev.items() if rr == r for _, c in e]) for r in Y}
    canon = {r: np.median(by_row[r], axis=0) for r in Y}
    # Gate three's reference in the live thread is the darkest state ever seen in the box, which
    # under the restart anchor is the all-zeros counter. The corpus holds hundreds of those frames,
    # so its minimum is the same picture - and a real carry has to depart from it too, or the
    # thread is reporting a counter that still reads zero.
    zero = {r: by_row[r].min(axis=0) for r in Y}
    def funnel(ink_min):
        """Replay hudwatch's gates 2-3-4-5 in commit order per row. Gate one is already spent:
        every frame here is one the live thread held still for HOLD seconds before saving it."""
        kept, rej, unzeroed, wholebox, unmoved = defaultdict(int), defaultdict(int), 0, 0, 0
        mins, maxs, margins, lefts, inks = [], [], [], [], []
        for (t, r), events in ev.items():
            base = canon[r]
            for n, c in sorted(events):
                d = int(np.count_nonzero(np.abs(c - base) > SETTLE_DELTA))
                if d < SETTLE_MIN_PX:
                    rej[t] += 1
                    maxs.append(d)
                    continue
                away = np.abs(c - zero[r]) > SETTLE_DELTA
                m = int(np.count_nonzero(away))
                if m < ZERO_MIN_PX:
                    unzeroed += 1
                    continue
                cols = np.flatnonzero(away.any(axis=0))
                if cols.size and int(cols[0]) < CARRY_LEFT_MIN:
                    # Gate four: the repaint reaches the dim leading-zero padding at the left edge
                    # of the window. A carry cannot do that; a flash crossing the column can.
                    wholebox += 1
                    rej[t] += 1
                    continue
                ink = int(np.count_nonzero((c > INK_LIT) ^ (base > INK_LIT)))
                if ink < ink_min:
                    # Gate five: the brightness moved but the drawn glyph did not. Every frame that
                    # lands here is a counter still showing the number it showed before.
                    unmoved += 1
                    rej[t] += 1
                    continue
                kept[t] += 1
                base = c
                mins.append(d)
                margins.append(m)
                lefts.append(int(cols[0]))
                inks.append(ink)
        return dict(kept=kept, rej=rej, unzeroed=unzeroed, wholebox=wholebox, unmoved=unmoved,
                    mins=mins, maxs=maxs, margins=margins, lefts=lefts, inks=inks)

    def lo(vals):
        return min(vals) if vals else 0

    f = funnel(INK_MOVE_MIN)
    kept, rej = f["kept"], f["rej"]
    print(f"corpus: {sum(len(e) for e in ev.values())} committed candidates over "
          f"{len({t for t, _ in ev})} runs")
    print(f"  gate two keeps {len(f['mins']) + f['unzeroed'] + f['wholebox'] + f['unmoved']} "
          f"(smallest carry {lo(f['mins'])} px), rejects {len(f['maxs'])} "
          f"(largest {max(f['maxs']) if f['maxs'] else 0} px)")
    print(f"  gate three keeps {len(f['mins']) + f['wholebox'] + f['unmoved']} "
          f"(all-zeros separation {lo(f['margins'])} px), rejects {f['unzeroed']}")
    print(f"  gate four keeps {len(f['lefts']) + f['unmoved']} (leftmost changed column starts at "
          f"{lo(f['lefts'])} of {X1 - X0}), rejects {f['wholebox']}")
    print(f"  gate five keeps {len(f['inks'])} (ink moved {lo(f['inks'])} px above {INK_LIT}), "
          f"rejects {f['unmoved']}")
    bad = []
    silent = 0
    for t in sorted({t for t, _ in ev}):
        res = tr.get(t)
        npf = None if res is None else res.get("non_perfect")
        if kept[t] and npf == 0:
            bad.append(t)
        if not kept[t]:
            silent += 1
            continue
        print(f"  {t:6s} kept {kept[t]:3d} of {kept[t] + rej[t]:3d}   "
              f"result page non_perfect="
              f"{npf if npf is not None else 'no result (bounded run)'}")
    print(f"  {silent} runs go silent")
    # Gate five's teeth, in the one place they can be honest. The arrival frame of a parked flash is
    # not in the corpus -- only what the thread held for HOLD seconds got saved -- so this cannot be
    # driven through HudWatch without inventing pixels. What it can do is put the log lines back.
    off = funnel(0)["kept"]
    back = sorted(t for t in off if off[t] and (tr.get(t) or {}).get("non_perfect") == 0)
    moved_back = sum(off[t] - kept[t] for t in back)
    print(f"  gate five pinned off: {moved_back} event(s) come back on "
          + (", ".join(f"{t} ({off[t]} kept)" for t in back) or "no run")
          + " -- runs whose result page reads ALL PERFECT")
    ok = not bad and bool(back) and moved_back > 0
    print("PART 1 " + ("FAIL: events kept on an ALL PERFECT run: " + ",".join(bad) if bad
                       else "PASS" if ok
                       else "FAIL: gate five has no teeth -- pinning it off changes nothing"))
    return ok


def part2():
    """A sparkle crossing the column must be silent; a real carry must fire once; and a baseline
    captured under an overlay must not turn the return to zero into a judgement (s03)."""
    clean = full_frame(load("hud_g076_miss1.png"))      # every row 0000
    carried = full_frame(load("hud_g076_miss8.png"))    # MISS reads 1
    yy0, yy1 = Y["MISS"]
    rng = np.random.default_rng(7)

    def sparkle():
        s = clean.copy()
        s[yy0:yy1, X0:X1] = np.clip(s[yy0:yy1, X0:X1].astype(np.int16)
                                    + rng.integers(90, 255, (yy1 - yy0, X1 - X0, 3)), 0, 255)
        return s

    sparks = [sparkle() for _ in range(3)]

    crossing = script([(clean, 5),
                       (sparks[0], 1), (sparks[1], 1), (sparks[2], 1),
                       (clean, 8),                    # an effect crosses the column and leaves
                       (carried, 9),                  # a real MISS: 0 -> 1 and it stays
                       (sparks[0], 1), (sparks[1], 1), (sparks[2], 1),
                       (carried, 8)])                 # the same effect, counter unchanged
    # The HUD slides in under an effect, so the thread's first snapshot of the box is not the
    # counter. Every later clean frame then departs from that baseline by a wide margin.
    polluted = script([(sparks[0], 2), (sparks[1], 2), (clean, 10), (carried, 9)])
    # Gate four's teeth: g100, 迷路日々 EXPERT 1322/1322 ALL PERFECT -- the one committed frame in
    # the corpus that clears gates two and three without a judgement behind it. Its GREAT box is
    # replayed the way the thread would have met it: first the all-zeros counter as it is at rest
    # (the per-pixel minimum over every GREAT box ever committed, which is what gate three measures
    # against), then that frame with the hit flash on it. Everything between them is g100's own
    # pixels; only the reconstruction of the resting frame is synthetic, and only the GREAT row
    # moves, so neither the >=3-rows screen-effect clause nor another gate is what stops it.
    gy0, gy1 = Y["GREAT"]
    g100 = full_frame(load("hud_g100_great1.png"))
    greats = [box(load(Path(p).name), "GREAT")
              for p in sorted(glob.glob(str(BOX_DIR / "hud_*_great*.png")))]
    rest = g100.copy()
    # A grey patch whose max-over-channels is exactly the resting box, which is all the thread reads.
    zmin = np.stack(greats).min(axis=0)
    rest[gy0:gy1, X0:X1] = np.stack([zmin] * 3, axis=-1)
    flashed = script([(rest, 5), (g100, 9)])

    both = (SETTLE_MIN_PX, ZERO_MIN_PX)
    none = (0, 0, 0, 0)
    cross = replay(crossing, *both)
    rows = [r for _, _, r in cross.events]
    old = replay(crossing, *none)           # every gate off: what persistence alone gave
    pol = replay(polluted, *both)
    pol_off = replay(polluted, SETTLE_MIN_PX, 0)   # gate two alone: the s03 false GREAT
    fla = replay(flashed, *both)
    fla_off = replay(flashed, SETTLE_MIN_PX, ZERO_MIN_PX, 0)   # gates two+three only: g100
    hudwatch.SETTLE_MIN_PX, hudwatch.ZERO_MIN_PX = both
    hudwatch.CARRY_LEFT_MIN, hudwatch.INK_MOVE_MIN = CARRY_LEFT_MIN, INK_MOVE_MIN

    # The round-start quad: g452, g457, g467, g468 and g469 all show it -- the four counter boxes
    # are drawn at once, the thread logs "4 rows changed at once ... - screen effect, ignored", and
    # then reports four judgements anyway (four identical frames on disk). g468 is the proof they
    # are false: its HUD tally reads MISS 1 while the result page reads MISS 0 / ALL PERFECT.
    # Each row's digits come from the committed corpus, one row at a time, so the only thing this
    # frame has in common with a real sparkle is the part the thread reads.
    def quad_frame():
        img = clean.copy()
        for r in ("GREAT", "GOOD", "BAD", "MISS"):
            p = sorted(glob.glob(str(BOX_DIR / ("hud_*_%s*.png" % r.lower()))))[-1]
            y0, y1 = Y[r]
            img[y0:y1, X0:X1] = load(Path(p).name)[y0 - CROP_Y0:y1 - CROP_Y0, :X1 - X0]
        return img

    quad = replay(script([(clean, 6), (quad_frame(), 14), (clean, 6)]), *both)
    quad_rows = [r for _, _, r in quad.events]

    ok = (rows == ["MISS"] and cross.unverified >= 2
          and [r for _, _, r in pol.events] == ["MISS"] and pol.unzeroed >= 1
          and len(pol_off.events) == 2
          and fla.events == [] and fla.wholebox == 1
          and [r for _, _, r in fla_off.events] == ["GREAT"]
          and quad_rows == [])
    print(f"part 2a (sparkle crossing + real carry): events {rows}, "
          f"{cross.unverified} settles rejected by the counter, {cross.rebased} rebaselines")
    print(f"  same script with every gate off: {len(old.events)} events "
          f"({[r for _, _, r in old.events]}) - that is the 2026-09-30 bug in three frames")
    print(f"part 2b (baseline captured under an overlay): events {[r for _, _, r in pol.events]} "
          f"at {[round(lo, 2) for lo, _, _ in pol.events]}, "
          f"{pol.unzeroed} reads back as all-zeros")
    print(f"  same script without gate three: {len(pol_off.events)} events at "
          f"{[round(lo, 2) for lo, _, _ in pol_off.events]} - the first is the s03 false tick")
    print(f"part 2c (a hit flash parked on a counter that never moved): "
          f"{fla.wholebox} rejected at the left edge, {len(fla.events)} events")
    print(f"  same script without gate four: {[r for _, _, r in fla_off.events]} "
          f"- that is the g100 false tick on an ALL PERFECT run")
    print(f"part 2d (all four boxes drawn at once, the round-start quad): {len(quad.events)} events "
          f"{quad_rows} - g468's result page reads MISS 0, so any event here is a false one")
    print("PART 2 " + ("PASS" if ok else f"FAIL: {rows} / {[r for _, _, r in pol.events]} "
                                       f"/ unzeroed {pol.unzeroed} / unguarded {len(pol_off.events)} "
                                       f"/ 2c {fla.events} {fla.wholebox} {fla_off.events} "
                                       f"/ 2d {quad_rows}"))
    return ok


def part3():
    """A 重试 must reseed the darkest-ever box (s260's 24 lost carries).

    s260's sixth attempt reported nothing while the game counted GREAT 3 -> 44: 24 candidates went
    to gate four in a row, and the abort fired only on the GOOD that ended the burst, ten seconds
    late. Rebuilt from every frame that round saved -- the true baseline can only be darker than
    that -- no frame's change could start left of column 8, so the live baseline must have been
    taught by frames it never kept, and a pause scrim dims the box by about half. The script plays
    that dimming, then the 重试 (reseed, exactly where run.py calls it), then a real carry: with
    the reseed the carry commits; without it, gate four eats it.

    The row decides whether the script can ask that at all. On the MISS row both paths report the
    carry (measured 2026-10-07), because that box's background is dark enough that the scrim does
    not register as a change; the counterfactual therefore runs on the BAD row, whose background
    gate four can see the scrim through. g076 kept no BAD digits of its own -- bad2/bad3/good2/
    great2 are byte-for-byte the all-0000 frame, which is the round-start quad 2d is about -- so
    the MISS digit is drawn onto the BAD row's own background: hudwatch reads one rectangle and
    cannot tell which row the ink came from.
    """
    clean = full_frame(load("hud_g076_miss1.png"))       # every row 0000
    carried = full_frame(load("hud_g076_miss8.png"))     # MISS reads 1
    scrim = np.clip(clean.astype(np.int16) * 0.4, 0, 255).astype(np.uint8)
    my0, my1 = Y["MISS"]
    by0, by1 = Y["BAD"]
    delta = carried[my0:my1, X0:X1].astype(np.int16) - clean[my0:my1, X0:X1].astype(np.int16)
    bcarried = clean.copy()
    bcarried[by0:by1, X0:X1] = np.clip(clean[by0:by1, X0:X1].astype(np.int16) + delta,
                                       0, 255).astype(np.uint8)
    frames = script([(clean, 5), (scrim, 30), (clean, 6), (carried, 9)])
    on = replay(frames, reseed_at=1.10)                  # the restart, on the clean screen
    off = replay(frames)                                 # no restart in this script
    on_rows = [r for _, _, r in on.events]
    off_rows = [r for _, _, r in off.events]
    bframes = script([(clean, 5), (scrim, 30), (clean, 6), (bcarried, 9)])
    bon = replay(bframes, reseed_at=1.10)
    boff = replay(bframes)
    bon_rows = [r for _, _, r in bon.events]
    boff_rows = [r for _, _, r in boff.events]
    # The MISS script's off side used to carry this counterfactual, but the quash bug was doing the
    # work: clearing the scrim seeded four candidates and two of them committed as GREAT and GOOD.
    # Those events are false for the same reason g468's tally MISS 1 is -- its result page reads
    # MISS 0 / ALL PERFECT -- and the frame is ignored outright now (hudwatch._run, pinned by 2d),
    # so this script no longer separates the two paths. It still pins that the restart's path
    # reports the carry and nothing else.
    ok = (on_rows == ["MISS"] and on.reseeded == 1 and on.wholebox == 0
          and off_rows == ["MISS"] and off.wholebox == 0
          and bon_rows == ["BAD"] and bon.reseeded == 1 and bon.wholebox == 0
          and boff_rows != ["BAD"] and boff.wholebox >= 1)
    print(f"遮罩剧本（0.4 倍暗 30 帧 → 重开 → 真 MISS）：重开后重算 {on.reseeded} 次，事件 {on_rows}"
          f"（左边闸门弃 {on.wholebox} 次）")
    print(f"  同剧本不重开：{off_rows}（左边闸门弃 {off.wholebox} 次）—— 遮罩清掉时不再自己造事件"
          f"（2026-10-07 的静默闸门，见 part 2d）")
    print(f"  同一剧本把真进位放进 BAD 行：重开后 {bon_rows}（左边闸门弃 {bon.wholebox} 次）；"
          f"不重开 {boff_rows}（左边闸门弃 {boff.wholebox} 次）—— 这就是 s260 丢的那 24 个进位")
    print("PART 3 " + ("PASS" if ok else f"FAIL: on={on_rows} off={off_rows} {off.wholebox} "
                                       f"/ BAD {bon_rows} {boff_rows} {boff.wholebox}"))
    return ok


def part4():
    """The sixth row: a JUST 激奏空間 round draws JUST above PERFECT, and every row moves down a pitch.

    Read with the five-row bands, such a round reports JUST as PERFECT, PERFECT as GREAT, ... and
    MISS falls off the bottom -- which is what hudwatch did to g1684 (383 gate-rejected frames, user
    m28650). Part 4 pins the detector, the geometry, the reader's switch and the watcher's shift,
    and takes each guard away in turn to show the judgements have teeth.
    """
    import hudread

    ok = True

    def say(label, good):
        nonlocal ok
        ok = ok and bool(good)
        print(f"  {label}: {bool(good)}")

    PITCH = 23                              # what the two layouts are measured to differ by

    def canvas(blob=None):
        img = np.zeros((720, 1280, 3), np.uint8)
        if blob is not None:
            img[hudwatch.JUST_BAND[0]:hudwatch.JUST_BAND[1],
                hudwatch.JUST_BAND_X[0]:hudwatch.JUST_BAND_X[1]] = blob
        return img

    white = canvas(np.array([255, 255, 255], np.uint8))
    # The coloured blob is the min-vs-max lesson: with `max` across channels a blue glow counts as
    # ink (three five-row frames of g1765 read 335 that way and were taken for six-row).
    blue = canvas(np.array([0, 0, 255], np.uint8))
    say("第六行标签亮着 -> 六行", hudwatch.just_layout(white))
    say("空画布 -> 五行", not hudwatch.just_layout(canvas()))
    say("彩色辉光不算标签（min 不看 max）", not hudwatch.just_layout(blue))
    keep_ink = hudwatch.JUST_BAND_INK
    try:
        hudwatch.JUST_BAND_INK = 0
        say("牙：门槛抠成 0，空画布必须被读成六行", hudwatch.just_layout(canvas()))
    finally:
        hudwatch.JUST_BAND_INK = keep_ink

    # The geometry: hudread's own docstring measured these bands, so they are the contract.
    bands = {"JUST": (136, 149), "PERFECT": (159, 172), "GREAT": (182, 195),
             "GOOD": (205, 217), "BAD": (228, 240), "MISS": (251, 263)}
    six = {n: (y0, y1) for n, y0, y1 in hudread.JUST_ROWS}
    five = {n: (y0, y1) for n, y0, y1 in hudread.ROWS}
    say("六行窗口覆盖实测亮带",
        all(n in six and six[n][0] <= b[0] and b[1] <= six[n][1] for n, b in bands.items()))
    say("六行 = 五行各下移一个 pitch（JUST 占用原 PERFECT 的窗口）",
        hudwatch.JUST_SHIFT == PITCH
        and all(six[n] == (y0 + PITCH, y1 + PITCH) for n, (y0, y1) in five.items())
        and six["JUST"] == five["PERFECT"])

    # The reader switches on the layout, and the watcher's loop is what applies the shift.
    say("六行画布读六行（含 JUST）", set(hudread.counters_arr(white)) == set(bands))
    say("五行画布读五行", set(hudread.counters_arr(canvas())) == set(five))
    keep_detect = hudwatch.just_layout
    try:
        hudwatch.just_layout = lambda img: False
        say("牙：拆掉检测，六行画布必须退回五行（JUST 会被读成 PERFECT）",
            set(hudread.counters_arr(white)) == set(five))
    finally:
        hudwatch.just_layout = keep_detect
    say("看盘主循环按 shift 取窗口",
        "img[y0 + shift:y1 + shift, X0:X1]" in inspect.getsource(hudwatch.HudWatch._run))

    # End to end: a real strip (g076's MISS 0 -> 1) replayed the way a six-row round delivers it --
    # the same pixels one pitch lower, with the sixth label band lit. The paste uses the literal
    # pitch, not the constant, so the canvas stays a real six-row frame even while the constant is
    # being mutated for the tooth below.
    strip_clean = load("hud_g076_miss1.png")           # every row 0000
    strip_carry = load("hud_g076_miss8.png")           # MISS reads 1

    def six_frame(strip):
        out = canvas(np.array([255, 255, 255], np.uint8))
        h = strip.shape[0]
        out[CROP_Y0 + PITCH:CROP_Y0 + PITCH + h, X0:X1] = strip
        return out

    def run(clean, carried):
        return replay(script([(clean, 5), (carried, 9)]), SETTLE_MIN_PX, ZERO_MIN_PX,
                      CARRY_LEFT_MIN, INK_MOVE_MIN)

    five_rows = [r for _, _, r in run(full_frame(strip_clean), full_frame(strip_carry)).events]
    six_rows = [r for _, _, r in run(six_frame(strip_clean), six_frame(strip_carry)).events]
    hudwatch.SETTLE_MIN_PX, hudwatch.ZERO_MIN_PX = SETTLE_MIN_PX, ZERO_MIN_PX
    hudwatch.CARRY_LEFT_MIN, hudwatch.INK_MOVE_MIN = CARRY_LEFT_MIN, INK_MOVE_MIN
    say("五行画布：MISS 进位报成 MISS", five_rows == ["MISS"])
    say("六行画布：同一个进位也报成 MISS", six_rows == ["MISS"])
    keep_shift = hudwatch.JUST_SHIFT
    try:
        hudwatch.JUST_SHIFT = 0
        blind = [r for _, _, r in run(six_frame(strip_clean), six_frame(strip_carry)).events]
        say("牙：把 shift 抠成 0，六行画布的进位必须读不到", not blind)
    finally:
        hudwatch.JUST_SHIFT = keep_shift
        hudwatch.SETTLE_MIN_PX, hudwatch.ZERO_MIN_PX = SETTLE_MIN_PX, ZERO_MIN_PX
        hudwatch.CARRY_LEFT_MIN, hudwatch.INK_MOVE_MIN = CARRY_LEFT_MIN, INK_MOVE_MIN
    print("PART 4 " + ("PASS" if ok else f"FAIL: five={five_rows} six={six_rows}"))
    return ok


def part5():
    """The evidence budget: one round spends DUMP_MAX frames / DUMP_BYTES_MAX bytes, then only counts.

    Until 2026-10-18 the reject path had no bound at all. One mis-read layout (the JUST sixth row,
    user m28650) wrote 2343 frames / 2.0 GB in a single night, one round 383 of them -- every
    judgement looked like a rejected candidate. The layout is fixed; this budget is what the *next*
    such bug costs. Both writers spend it through `_dump_room`, and running out stops the writing,
    never the counting: the round's judgement history is worth more than its pictures.
    """
    ok = True

    def say(label, good):
        nonlocal ok
        print(("  ok   " if good else "  FAIL ") + label)
        ok = ok and bool(good)

    # A cap of zero, of a night's worth, or a missing one is not a cap.
    say(f"预算是 60 张 / 48 MB（读到 {hudwatch.DUMP_MAX} / {hudwatch.DUMP_BYTES_MAX}）",
        0 < hudwatch.DUMP_MAX <= 200 and 0 < hudwatch.DUMP_BYTES_MAX <= 128 * 1024 * 1024)

    # The count half: the first DUMP_MAX draws are allowed, the next one is refused and not counted.
    w = hudwatch.HudWatch(log=lambda s: None)
    allowed = [w._dump_room() for _ in range(hudwatch.DUMP_MAX)]
    refused = w._dump_room()
    say("预算内全放行，第 61 张被拒且不再记账",
        all(allowed) and refused is False
        and w.dumped == hudwatch.DUMP_MAX and w.dump_over == 1)

    # The byte half: the writer sums the sizes, so a round can hit this one first.
    w2 = hudwatch.HudWatch(log=lambda s: None)
    w2.dump_bytes = hudwatch.DUMP_BYTES_MAX
    say("字节预算用尽也拒", w2._dump_room() is False and w2.dumped == 0)

    # Both writers ask, and the reset is wired: a budget nobody consults is a comment.
    src = inspect.getsource(hudwatch.HudWatch)
    say("_commit 与 _reject 都问预算", src.count("self._dump_room()") >= 2)
    say("start() 复位预算",
        "self.dumped, self.dump_bytes, self.dump_over, self._dump_said = 0, 0, 0, False"
        in inspect.getsource(hudwatch.HudWatch.start))

    # The reject path really stops drawing: with the budget spent it must not reach `_draw`.
    w3 = hudwatch.HudWatch(log=lambda s: None)
    w3.dumped = hudwatch.DUMP_MAX
    w3._reject("zero", "GREAT", 1, 0.0, 1.0, np.zeros((720, 1280, 3), np.uint8))
    say("预算用尽时 _reject 不再排帧（undrawn 不动）", w3.undrawn == 0 and w3.dump_over == 1)

    # Teeth: the guard is what makes the first three lines true.
    keep = hudwatch.HudWatch._dump_room
    try:
        hudwatch.HudWatch._dump_room = lambda self: True
        w4 = hudwatch.HudWatch(log=lambda s: None)
        over = [w4._dump_room() for _ in range(hudwatch.DUMP_MAX + 1)]
        say("牙：拆掉预算，第 61 张必须被放行", all(over))
    finally:
        hudwatch.HudWatch._dump_room = keep

    # A source-mutation tooth, not just a monkeypatch: the cap has to be the condition, not a name.
    text = textwrap.dedent(inspect.getsource(hudwatch.HudWatch._dump_room))
    mutant = text.replace("if self.dumped >= DUMP_MAX or self.dump_bytes >= DUMP_BYTES_MAX:",
                          "if False:")
    say("牙：源码里那条上限被抠掉（条件换成 if False:）", mutant != text and "if False:" in mutant)
    ns = dict(hudwatch.__dict__)
    exec(mutant, ns)                                             # noqa: S102 - a copy, in a dict
    m = hudwatch.HudWatch(log=lambda s: None)
    m.dumped = hudwatch.DUMP_MAX
    m._dump_room = types.MethodType(ns["_dump_room"], m)
    say("牙：抠掉上限后同一段代码必须放行第 61 张", m._dump_room() is True)

    # Said once, and it names both numbers: that line is the only trace of what was not written.
    said = []
    w5 = hudwatch.HudWatch(log=said.append)
    for _ in range(hudwatch.DUMP_MAX + 3):
        w5._dump_room()
    hits = [s for s in said if "证据帧预算用尽" in s]
    say("只喊一次，且把两个数字念出来",
        len(hits) == 1 and str(hudwatch.DUMP_MAX) in hits[0] and "48" in hits[0])

    print("PART 5 " + ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    print(f"constants: SETTLE_DELTA={SETTLE_DELTA} SETTLE_MIN_PX={SETTLE_MIN_PX} "
          f"INK_MOVE_MIN={INK_MOVE_MIN}@>{INK_LIT} CARRY_LEFT_MIN={CARRY_LEFT_MIN} "
          f"HOLD={HOLD} REBASE={REBASE} JUST_SHIFT={hudwatch.JUST_SHIFT} "
          f"DUMP_MAX={hudwatch.DUMP_MAX} DUMP_BYTES_MAX={hudwatch.DUMP_BYTES_MAX}")
    sys.exit(0 if (part1() and part2() and part3() and part4() and part5()) else 1)
