"""The detectors changed engine, not eye: cv2 in the frame loop, numpy as the oracle.

`note_mask` used to cast the whole 1280x720 frame to int16 three times to compare each channel
against a window, and `sprite_strips` reduced the frame with `min(axis=2)`. Both are one fused cv2
call now -- 12.2 -> 6.2 ms and 49.6 -> 17.4 ms per frame end to end, which is what puts the relock
vote back inside the 33 ms the device needs to deliver a frame (it was spending more time per frame
than the emulator takes to paint one, and a busy frame went to 127 ms).

Speed bought this way is only free if the *population* is unchanged: the vote, the anchor and the
pin all reason about which blobs exist, and the red line on this file is that the tuned predicates
do not move. So the numpy predicate is kept here, verbatim, as the thing to agree with -- derived
from the same constants detect.py exports, so changing a constant moves both sides while changing
the *shape* of the test (a `<` becoming a `<=`, dropping the b-r term) is what this catches.

PART 1: `note_mask` agrees bit-for-bit with the oracle, on synthetic boundary frames and on every
        committed 1280x720 frame.
PART 2: `sprite_strips` agrees with the oracle pipeline (oracle mask -> detect's own labeller ->
        the same size filters).
PART 3: end to end: `note_blobs` and `sprite_blobs` return the same blob sets.
PART 4: teeth -- the synthetic frames must actually sit on the boundaries, or parts 1-3 pass
        vacuously: each boundary is shown from the inside (the pixel one below passes, the one at
        the threshold does not).
PART 5: the point of the change: measured in this process, the shipped path is faster than the
        oracle path by a margin, on the same frames.

Run from the repo root:  python tools/probes/maskfast.py
"""

import glob
import os
import sys
import time

import numpy as np
from PIL import Image

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../tools
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
import detect  # noqa: E402


# ---- the oracle: the predicate as it was written before cv2, from detect's own constants -------

def ref_note_mask(img):
    r = img[..., 0].astype(np.int16)
    g = img[..., 1].astype(np.int16)
    b = img[..., 2].astype(np.int16)
    (mr, mg, mb), (tr, tg, tb), d = detect.NOTE_MID, detect.NOTE_TOL, detect.NOTE_BR_MINUS_R
    return (abs(r - mr) < tr) & (abs(g - mg) < tg) & (abs(b - mb) < tb) & ((b - r) > d)


def ref_sprite_mask(img):
    return (img.min(axis=2) > detect.SPRITE_BRIGHT_MIN) & detect.field_mask()


def ref_sprite_strips(img):
    out = []
    for cy, cx, npx, w, h in detect._components(ref_sprite_mask(img)):
        if (detect.SPRITE_MIN_W <= w <= detect.SPRITE_MAX_W and detect.SPRITE_MIN_H <= h <=
                detect.SPRITE_MAX_H and npx >= detect.SPRITE_MIN_PX):
            out.append((cy, cx))
    return out


def ref_note_blobs(img):
    m = ref_note_mask(img) & detect.field_mask()
    out = []
    for y0, y1 in detect.bands(m):
        x0, x1 = detect.widest_run(m, y0, y1)
        if x1 - x0 + 1 >= detect.MIN_NOTE_W:
            out.append(((y0 + y1) / 2.0, (x0 + x1) / 2.0))
    return out


def ref_sprite_blobs(img):
    """detect.sprite_blobs, with the oracle's masks -- the dedup tolerance included, so PART 3
    compares the whole public surface rather than the pieces."""
    out = ref_note_blobs(img)
    for y, x in ref_sprite_strips(img):
        if any(abs(y - by) <= 22 and abs(x - bx) <= 30 for by, bx in out):
            continue
        out.append((y, x))
    return out


# ---- synthetic frames: every boundary of the predicate, drawn inside the field ----------------

def _bar(img, y, x0, x1, colour):
    img[y:y + 5, x0:x1] = colour


def synth_frames():
    """One frame per boundary of the predicate, each drawn inside the field so the trapezoid does
    not hide it. Expectations are pixel counts of the masked result: a bar is 5 rows x 60 cols.

    Two things are easy to get wrong here and both are why the table is explicit. The tap's pale
    blue is *also* bright, so every note-window case is a sprite pixel too (min channel 216 > 160).
    And `abs(c-mid) < tol` is strict, so the last pixel inside is mid±(tol-1) -- `mid-tol` is
    already outside.
    """
    mr, mg, mb = detect.NOTE_MID
    tr, tg, tb = detect.NOTE_TOL
    d = detect.NOTE_BR_MINUS_R
    k = detect.SPRITE_BRIGHT_MIN
    y, x0 = 400, 300                       # comfortably inside the trapezoid
    bright = "any"                          # min channel above the sprite threshold
    cases = [
        ("窗内", (mr, mg, mb), "any", bright),
        ("r下界内", (mr - tr + 1, mg, mb), "any", bright),
        ("r下界外", (mr - tr, mg, mb), 0, bright),
        ("r上界外", (mr + tr, mg, mb), 0, bright),
        ("g下界外", (mr, mg - tg, mb), 0, bright),
        ("b下界外", (mr, mg, mb - tb), 0, bright),
        ("b-r=25", (mr, mg, mr + d), 0, bright),          # the cross-channel term's own edge
        ("b-r=26", (mr, mg, mr + d + 1), "any", bright),
        ("sprite=160", (k, k, k), 0, 0),                  # too dark for the note window anyway
        ("sprite=161", (k + 1, k + 1, k + 1), 0, "any"),
    ]
    out = {}
    for name, colour, want_n, want_s in cases:
        img = np.full((detect.H, detect.W, 3), (20, 24, 30), np.uint8)
        _bar(img, y, x0, x0 + 60, colour)
        out[name] = (img, want_n, want_s)
    # 场外的亮块必须被 field_mask 挡掉：同样的两条杠，一根在道内一根在道外，只剩 300 px
    wide = np.full((detect.H, detect.W, 3), (20, 24, 30), np.uint8)
    _bar(wide, y, 20, 80, (mr, mg, mb))                   # outside the lane edges
    _bar(wide, y, x0, x0 + 60, (mr, mg, mb))              # inside
    out["场外美术"] = (wide, 300, 300)
    return out


def real_frames():
    out = []
    for pat in ("evidence/detect/*.png", "evidence/nav/*.png", "evidence/proof/*.png",
                "research/frames/*.png"):
        for p in sorted(glob.glob(os.path.join(ROOT, pat))):
            try:
                if Image.open(p).size == (detect.W, detect.H):
                    out.append(np.asarray(Image.open(p).convert("RGB")))
            except Exception:                          # noqa: BLE001  (a truncated png)
                pass
    return out


def part1(frames):
    bad = [f"第 {i} 帧 note_mask 与 oracle 不等 ({int((detect.note_mask(x) != ref_note_mask(x)).sum())} px)"
           for i, x in enumerate(frames) if not np.array_equal(detect.note_mask(x), ref_note_mask(x))]
    print(f"PART 1 note_mask 逐位相等：{len(frames)} 帧 -> "
          + ("PASS" if not bad else "FAIL " + "; ".join(bad[:3])))
    return not bad


def part2(frames):
    bad = []
    for i, x in enumerate(frames):
        a, b = sorted(detect.sprite_strips(x)), sorted(ref_sprite_strips(x))
        if a != b:
            bad.append(f"第 {i} 帧 判定物 {len(a)} vs {len(b)}")
    print(f"PART 2 sprite_strips 判定物集合相等：{len(frames)} 帧 -> "
          + ("PASS" if not bad else "FAIL " + "; ".join(bad[:3])))
    return not bad


def part3(frames):
    bad = []
    for i, x in enumerate(frames):
        for name, got, want in (("note_blobs", detect.note_blobs(x), ref_note_blobs(x)),
                                ("sprite_blobs", detect.sprite_blobs(x), ref_sprite_blobs(x))):
            if sorted(got) != sorted(want):
                bad.append(f"第 {i} 帧 {name}: {len(got)} vs {len(want)}")
    print(f"PART 3 端到端 blob 集合相等：{len(frames)} 帧 -> "
          + ("PASS" if not bad else "FAIL " + "; ".join(bad[:3])))
    return not bad


def part4():
    """The boundary cases have to bite, or parts 1-3 compare nothing but ordinary pixels."""
    bad = []
    for name, (img, want_n, want_s) in synth_frames().items():
        mn = int((detect.note_mask(img) & detect.field_mask()).sum())
        ms = int(((img.min(axis=2) > detect.SPRITE_BRIGHT_MIN) & detect.field_mask()).sum())
        for label, got, want in (("note", mn, want_n), ("sprite", ms, want_s)):
            ok = bool(got) if want == "any" else got == want
            if not ok:
                bad.append(f"{name} 的 {label} 掩码 {got} px，应为 {want}")
    print("PART 4 边界逐条咬住："
          + "，".join(f"{n} {int((detect.note_mask(i) & detect.field_mask()).sum())}/"
                      f"{int((i.min(axis=2) > detect.SPRITE_BRIGHT_MIN).sum())}"
                      for n, (i, _a, _b) in list(synth_frames().items())[:5])
          + " … -> " + ("PASS" if not bad else "FAIL " + "; ".join(bad)))
    return not bad


def part5(frames):
    f = frames[:25]

    def bench(fn):
        t = time.perf_counter()
        for x in f:
            fn(x)
        return (time.perf_counter() - t) * 1000 / len(f)

    new_n, old_n = bench(detect.note_blobs), bench(ref_note_blobs)
    new_s, old_s = bench(detect.sprite_blobs), bench(ref_sprite_blobs)
    bad = []
    if new_n * 1.5 > old_n:
        bad.append(f"note_blobs 只快 {old_n / new_n:.1f}×（{new_n:.1f} vs {old_n:.1f} ms）")
    if new_s * 1.5 > old_s:
        bad.append(f"sprite_blobs 只快 {old_s / new_s:.1f}×（{new_s:.1f} vs {old_s:.1f} ms）")
    print(f"PART 5 同一批帧：note_blobs {old_n:.1f} -> {new_n:.1f} ms/帧 "
          f"({old_n / new_n:.1f}×)，sprite_blobs {old_s:.1f} -> {new_s:.1f} ms/帧 "
          f"({old_s / new_s:.1f}×) -> " + ("PASS" if not bad else "FAIL " + "; ".join(bad)))
    return not bad


def part6():
    """PART 6: the mask's input *domain* -- a 4-channel frame must read the same as a 3-channel one.

    Parts 1-5 all feed 3-channel frames, which is exactly why the domain change went unnoticed when
    the engine became cv2: `inRange` refuses a 4-channel array (`(-209) The lower boundary is
    neither an array ... nor a scalar`), while the numpy oracle indexes `[..., 0/1/2]` and is happy.
    `detect.capture()` returns RGBA -- so `python tools/detect.py` built its frame, handed it to
    `note_mask`, and raised before printing anything. The tooth is the old spelling: with the
    normalisation removed, every case below must blow up rather than quietly agree.
    """
    bad = []
    syn = [img for img, _n, _s in synth_frames().values()]
    syn += real_frames()[:5]
    if not syn:
        return True
    for i, img in enumerate(syn):
        rgba = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
        for name, fn in (("note_mask", detect.note_mask), ("sprite_strips", detect.sprite_strips),
                         ("note_blobs", detect.note_blobs), ("sprite_blobs", detect.sprite_blobs)):
            try:
                got = fn(rgba)
            except Exception as e:                                 # noqa: BLE001
                bad.append(f"第 {i} 帧 {name}(RGBA) 抛 {type(e).__name__}")
                continue
            want = fn(img)
            if name in ("note_mask",):
                same = np.array_equal(got, want)
            else:
                same = sorted(got) == sorted(want)
            if not same:
                bad.append(f"第 {i} 帧 {name}(RGBA) 与 3 通道结果不同")
    print(f"PART 6 4 通道帧与 3 通道逐位同判：{len(syn)} 帧 x 4 个入口 -> "
          + ("PASS" if not bad else "FAIL " + "; ".join(bad[:3])))
    return not bad


if __name__ == "__main__":
    syn = [img for img, _n, _s in synth_frames().values()]
    real = real_frames()
    frames = syn + real
    print(f"帧：合成边界 {len(syn)} + 真实 {len(real)}")
    ok = (part1(frames) and part2(frames) and part3(frames) and part4() and part5(real or frames)
          and part6())
    sys.exit(0 if ok else 1)
