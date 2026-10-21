"""Read the LIVE playfield: capture frames, find note blobs, estimate the song clock.

Frame source is raw RGBA straight from `screencap` (no PNG encode), so the detector runs at the
capture rate. Notes are the bright bluish-white slabs inside the perspective field.
"""

from __future__ import annotations

import os
import struct
import subprocess
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compile import (EDGE_LEFT_AT_0, EDGE_RIGHT_AT_0,  # noqa: E402
                     EDGE_SLOPE, JUDGE_Y)

from locate import ADB, DEVICE, endpoint_gone, reconnect  # noqa: E402  路径集中探测：见 tools/locate.py

W, H = 1280, 720

# The horizon the notes converge to is *not* where the lane edges meet. Calibrated from the
# four stacked notes of burst3 frames 14-17 (chart t=6316/6632/6947/7263 ms): with vp=-320 the
# note rows fit s=1/(y-vp) linear in time to 0.3 px residual, giving C=998.5 host-seconds per
# unit of s. Near the judgment row that is ~1.3 ms per pixel.
# C is set by 节奏图示速度, currently 5.00. A 100-second no-input observation run extrapolated every
# blob it saw through this constant onto the chart and came back with k=1.000111 at 23 ms rms,
# which pins C to a couple of percent -- but moving that slider invalidates it.
VP_MOTION = -320.0
C_FIELD = 998.5

TOP_SCAN = 55          # notes fade in at the very top of the screen
# Stop above the judgment row. Notes keep falling after they pass it, and those passed
# notes are what made the "lowest band" jump around in earlier bursts.
BOTTOM_SCAN = 535
MIN_NOTE_PX = 25
MIN_NOTE_W = 40


# The GUI runs under pythonw (no console), and a console child spawned from a console-less
# parent gets its own fresh console window -- one flashing Windows Terminal per screencap while
# the result walk reads a frame several times a second.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# `screencap` in raw mode frames its pixels with a 16-byte header on Android 11+ (MuMu 15 emits
# it): width and height as u32 LE, then the pixel format and the colorspace. The payload behind it
# is byte for byte the picture the bare form carries -- measured 2026-10-06 on the 乐队确认 page,
# against the PNG decode of the same screen: mean 6.48/255 and 10.05% of pixels over 16, while two
# PNG captures taken the same way apart differ by 6.38/10.28% (that page's own animation). So the
# header is framing, not a different picture, and these two shapes are the only ones decoded.
SHOT_HEADER = 16
# HAL pixel formats whose bytes are R,G,B,A in that order (`RGBA_8888`, `RGBX_8888`) -- the byte
# order every colour key in this file was tuned on. Anything else is refused rather than misread.
SHOT_FORMATS = (1, 2)


def _frame_from_raw(raw: bytes) -> np.ndarray:
    """Decode one `screencap` payload into HxWx4, or raise. Never guesses.

    Two shapes are legal: the bare RGBA payload, and that payload behind the 16-byte header above.
    A header that does not name exactly {W}x{H} in an RGB-order format is refused, not sliced: a
    header is the emulator *telling* us the frame is a different picture, and every constant here
    (the perspective trapezoid, JUDGE_Y, the hue keys) is tuned for {W}x{H}. A payload of any
    other length is refused too, including one that is merely longer -- `raw[:need]` on a larger
    device used to reshape the first 3.69 MB of an 8.3 MB frame, which is a wrong picture, not an
    error.
    """
    need = H * W * 4
    if len(raw) == need + SHOT_HEADER:
        w, h, fmt = struct.unpack_from("<III", raw, 0)
        if (w, h) != (W, H) or fmt not in SHOT_FORMATS:
            raise RuntimeError(
                f"screencap's header says {w}x{h} format {fmt}, not {W}x{H} in RGBA order -- "
                f"every geometry constant here is tuned for {W}x{H}, so this is refused instead "
                f"of misread (把模拟器分辨率设成 {W}x{H}，见 README「支持矩阵」；别改这里的常数)")
        raw = raw[SHOT_HEADER:]
    elif len(raw) == need:
        # A `need`-byte payload whose first 16 bytes parse as this device's own header is a
        # headered frame whose payload is short by exactly the header's length: 16 + (need - 16)
        # == need, so size cannot tell the two apart, and decoding it as a bare frame shifts the
        # whole picture four pixels left -- the same class of silent misread this function exists
        # to stop. What gives it away: the high byte of each of those header words is 0, while a
        # real payload here is opaque (measured on a live frame: alpha min = max = 255), so a bare
        # frame cannot carry those four zero bytes.
        w, h, fmt = struct.unpack_from("<III", raw, 0)
        if ((w, h) == (W, H) and fmt in SHOT_FORMATS
                and not (raw[3] or raw[7] or raw[11] or raw[15])):
            raise RuntimeError(
                f"screencap returned {need} bytes that begin with a {W}x{H} format {fmt} header "
                f"-- that is a headered frame whose payload is 16 bytes short, and it cannot be "
                f"told apart from a bare frame by size alone; refused instead of read four "
                f"pixels off")
    if len(raw) != need:
        raise RuntimeError(
            f"screencap returned {len(raw)} bytes, expected exactly {need} ({W}x{H} RGBA) -- "
            f"the emulator is not running at {W}x{H}; every geometry constant here is tuned for "
            f"that resolution, so this is refused instead of misread"
            f" (把模拟器分辨率设成 {W}x{H}，见 README「支持矩阵」；别改这里的常数)"
            + (" (一个更大的画面会被当成 1280x720 读错，这就是要拒绝的原因)" if len(raw) > need
               else ""))
    return np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 4)


def capture(serial: str = DEVICE) -> np.ndarray:
    """One screencap, as HxWx4. Fails loudly rather than reading the wrong picture.

    Three things this used to get wrong, all silent. There was no `timeout=`, so a wedged emulator
    or a dropped adb endpoint blocked the caller forever -- and `capture` backs the screencap
    fallback that every walk, the relock vote and the result-page read use, with only the
    operator's own 900 s to bound it. The size test only rejected payloads that were too *small*:
    `raw[:need]` on a larger device reshaped the first 3.69 MB of an 8.3 MB frame, which is a wrong
    picture, not an error -- every constant in this file is tuned for exactly 1280x720, so a
    wrong-sized frame is not something to play a chart on. And the test demanded the bare payload
    exactly, so the 16-byte header this emulator's `screencap` has carried since MuMu 15 read as
    "the emulator is not running at 1280x720" and stopped every real round at the first frame.
    AGENTS.md names the first of those as the release blocker "静默读错帧"; `_frame_from_raw` is the
    mechanism that keeps all three honest.

    `_screencap` adds the fourth, 2026-10-16: the frame path had no endpoint repair (see there).
    """
    return _frame_from_raw(_screencap(serial))


def _screencap(serial: str) -> bytes:
    """One `exec-out screencap`, healing a dropped adb endpoint once.

    Same repair `MTouch._adb` has had since the g165/g166 rounds: a restarted emulator leaves
    `emulator-5554` in `adb devices` but drops the TCP registration, so every `-s 127.0.0.1:16384`
    call answers "device ... not found". The taps healed that; the *frame* reads never did -- and
    that is the whole of 「普通的开始演奏按钮不会重连模拟器」 (2026-10-16): the panel's start button
    reads the game screen to verify the chart before it starts, got `CalledProcessError`, and
    reported 「没有画面」 and did nothing -- while 开始演出, which reads no screen and lets run.py's own
    MTouch heal at construction, went ahead. `stderr=` is captured for that judgement and nothing
    else; when the repair does not help the caller still gets adb's own first failure. One retry,
    written out rather than recursive.
    """
    cmd = [ADB, "-s", serial, "exec-out", "screencap"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       creationflags=CREATE_NO_WINDOW, timeout=15)
    if (r.returncode != 0
            and endpoint_gone((r.stderr or b"").decode("utf-8", "replace"))
            and reconnect(serial)):
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           creationflags=CREATE_NO_WINDOW, timeout=15)
    if r.returncode != 0:
        # The same type `check=True` used to raise, so callers' handling is unchanged.
        raise subprocess.CalledProcessError(r.returncode, cmd, output=r.stdout, stderr=r.stderr)
    return r.stdout


# Set by mumucap.install() or hostcap.install() to a zero-arg callable returning (perf_counter
# time, RGB device frame). Three tiers, all measured 2026-10-06 on this machine: MuMu's renderer SDK
# 8.41 ms a frame (8.13 ms median interval, ~123 fps), Windows.Graphics.Capture on the emulator
# window 16.7 ms (60 fps), and `screencap` a 257 ms round trip that does not parallelise (36 ms of
# it is adb's own process spawn) -- ~3.9 fps, so on its own it caps the whole harness. That is what
# decides whether the anchor finishes before note 1 is due.
SOURCE = None


def frames(timeout=0.25):
    """(timestamp, RGB device frame). The stamp is when those pixels reached us, not when we asked.

    `timeout` is how long the source may block for a frame. The firing loop hands it the time left
    before the next action, so a source that waits for the next vsync can never be the reason an
    action is late.
    """
    if SOURCE is not None:
        return SOURCE(timeout)
    import time

    t = time.perf_counter()
    return t, capture()[:, :, :3]


def grab():
    """RGB device frame, no timestamp."""
    return frames()[1]


def frame_key(img):
    """A number that says *this picture is not the one I just saw* -- 25 µs for a 720p frame.

    Two loops turn pixels into samples: the opening vote appends what each frame's detector found
    into `dets` and histograms the lot, and the mid-song corrector does the same on its own feed. A
    capture that hands back the same composited buffer twice makes both of them pay for a new sample
    without getting its information -- `sprite_blobs` is 11.9 ms a frame, so a stalled renderer read
    at ~100/s spends the loop's entire budget re-detecting one frozen instant while `dets` grows and
    every vote re-histogramms the lot. The duplicates also spread the histogram: `peak <= runner` and
    the vote margin are how a lock refuses to be a guess, and junk votes from a stale frame lift the
    runner-up around the truth.

    What they cannot do is *fake* a lock, and PART 3 of tools/probes/freshfeed.py measured that
    instead of assuming it: an implied start is `stamp - flight(y)`, so duplicates stamped at
    advancing times land in different bins and the peak stays where the real evidence put it. The
    exposure is CPU and dilution, which are the sampling loop's own business.

    Every 4th row and 8th column of one channel is 3% of the frame, and it answers the question that
    is actually being asked, because the repeats this guards are *bit-identical*: the same buffer,
    handed back twice. A change small enough to fall between every sampled pixel reads as no change
    -- a "did the world move" test, not an image comparison. Hashing whole frames is exact and costs
    1.2 ms, an eighth of the 9 ms capture being watched, for precision no sampling loop uses.
    """
    return hash(np.ascontiguousarray(img)[::4, ::8, 1].tobytes())


# note_mask 的三条通道窗口与 b-r 差值，写成 cv2.inRange 要的闭区间。原来的表达式是
# `abs(c-中值) < 容差`，严格不等式在整数上就是 ±(容差-1)；这里从同一组常数推出来，
# 所以改常数只需要改一处。
NOTE_MID = (193, 216, 228)
NOTE_TOL = (22, 16, 14)
NOTE_BR_MINUS_R = 25
_NOTE_LO = tuple(m - t + 1 for m, t in zip(NOTE_MID, NOTE_TOL))
_NOTE_HI = tuple(m + t - 1 for m, t in zip(NOTE_MID, NOTE_TOL))


def _rgb(img: np.ndarray) -> np.ndarray:
    """The frame as three channels, without copying when it already is.

    Both masks below used to take whatever they were handed. The numpy predicates they replaced
    indexed `img[..., 0/1/2]` explicitly and so worked on 4-channel input; `cv2.inRange` does not
    -- it raises `(-209) The lower boundary is neither an array ... nor a scalar` -- and
    `capture()` returns RGBA. That made `python tools/detect.py` (whose both branches build RGBA)
    and `probes/burst.py` dead on arrival, while the run path stayed healthy because `frames()`
    and `grab()` slice `[:, :, :3]`. maskfast.py only ever fed 3-channel frames, so "bit-for-bit
    identical" was proven and the domain change was not. Normalising here fixes the callers and
    means the next person to hand a mask a screencap frame gets the right answer, not an exception
    three modules away.
    """
    if img.ndim != 3:
        raise ValueError(f"a frame must be HxWx(C>=3), got shape {img.shape}")
    if img.shape[2] < 3:
        raise ValueError(f"a frame needs at least R,G,B, got {img.shape[2]} channel(s)")
    return img if img.shape[2] == 3 else img[:, :, :3]


def note_mask(img: np.ndarray) -> np.ndarray:
    """Tap-note bars are a single flat pale blue, mean RGB (191,216,228) capped at
    (215,225,235). Matching that tightly rejects the stage artwork and the green/pink
    flick arrows, which a generic 'bright and bluish' test let through.

    The engine is cv2, the predicate is not: `inRange` fuses the three channel windows into one
    pass instead of casting the whole frame to int16 three times, and the cross-channel test is a
    saturated uint8 subtract -- b <= r lands on 0, which fails > 25 exactly as the signed version
    did. Measured over 45 recorded frames: 12.2 -> 5.6 ms, and the mask is bit-for-bit the same
    array (tools/probes/maskfast.py holds the numpy predicate as its oracle and says so per frame).
    """
    img = _rgb(img)
    return ((cv2.inRange(img, _NOTE_LO, _NOTE_HI) > 0)
            & (cv2.subtract(img[..., 2], img[..., 0]) > NOTE_BR_MINUS_R))


_FIELD_MASK = None


def field_mask() -> np.ndarray:
    """The trapezoid's inside, memoised: it depends on nothing but the constants above, and
    rebuilding its 720x1280 mgrid cost 28 ms a call -- with both detectors asking for it every
    frame that was most of the vote's sampling budget. Callers only ever read it (`&`), so the
    same array is handed out."""
    global _FIELD_MASK
    if _FIELD_MASK is None:
        ys, xs = np.mgrid[0:H, 0:W]
        lo = EDGE_LEFT_AT_0 - EDGE_SLOPE * ys
        hi = EDGE_RIGHT_AT_0 + EDGE_SLOPE * ys
        inside = (xs > lo + 12) & (xs < hi - 12)
        inside &= (ys >= TOP_SCAN) & (ys <= BOTTOM_SCAN)
        _FIELD_MASK = inside
    return _FIELD_MASK


def bands(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous row ranges holding a note-width run, as (y0, y1) inclusive.

    A note bar is not a solid block -- the centre diamond and the shading split it into two or
    three bright rows with a dark gap between. Those gaps must be merged back, otherwise the
    landmark row depends on which fragment happened to be brightest.
    """
    counts = mask.sum(axis=1)
    runs = []
    y = TOP_SCAN
    while y <= BOTTOM_SCAN:
        if counts[y] < MIN_NOTE_PX:
            y += 1
            continue
        y0 = y
        while y <= BOTTOM_SCAN and counts[y] >= MIN_NOTE_PX:
            y += 1
        runs.append([y0, y - 1])
    out = []
    for r in runs:
        gap_ok = out and r[0] - out[-1][1] <= max(4, 0.05 * r[0])
        tall_ok = out and r[1] - out[-1][0] <= 0.12 * r[0] + 6
        if gap_ok and tall_ok:
            out[-1][1] = r[1]
        else:
            out.append(r)
    return [tuple(o) for o in out]


def widest_run(mask: np.ndarray, y0: int, y1: int) -> tuple[int, int]:
    xs = np.flatnonzero(mask[y0 : y1 + 1].any(axis=0))
    splits = np.flatnonzero(np.diff(xs) > 6)
    groups = np.split(xs, splits + 1)
    best = max(groups, key=len)
    return int(best[0]), int(best[-1])


def note_blobs(img):
    """Centres of every note-sized blob in the field, as (y, x) screen pixels.

    The centre, not the top edge: the game judges the sprite's middle reaching the band's middle,
    and the top edge is a constant half-sprite ahead of that -- 20-30 px, or 26-39 ms, most of a
    PERFECT window.
    """
    m = note_mask(img) & field_mask()
    out = []
    for y0, y1 in bands(m):
        x0, x1 = widest_run(m, y0, y1)
        if x1 - x0 + 1 >= MIN_NOTE_W:
            out.append(((y0 + y1) / 2.0, (x0 + x1) / 2.0))
    return out


# Every kind's judged sprite is a bright bar with the centre diamond: the tap's pale slab, a
# long's head cap, a trace's node bar. The palette drifts per kind and per song -- tap bar
# (193,216,228) flat, long cap (149..163, 173..186, 251..253) under a bright edge, trace node
# (148,120,246) violet with its white edge and diamond doing the lighting -- while the brightness
# does not: min channel > 160 on all of them, in every frame of the 2026-09-30 0056_03 opening
# recording (research/spritebars_*.png are five of its frames). note_mask stays one flat pale
# blue on purpose, which is why a chart whose opening is longs/traces -- 0056_03's long x4 +
# trace x7, 唱's two longs at 3.64 s -- had 0 blobs to vote on in all 16 recorded relocks.
SPRITE_BRIGHT_MIN = 160
SPRITE_MIN_W, SPRITE_MAX_W = 40, 420
SPRITE_MIN_H, SPRITE_MAX_H = 2, 42
SPRITE_MIN_PX = 60


def _components(mask):
    """4-connected components of `mask`, as (y_centre, x_centre, npx, w, h).

    Row runs unioned across adjacent rows, not a per-pixel flood fill: the bright mask runs to
    tens of thousands of pixels on a busy frame and the per-pixel fill cost 100-260 ms there,
    which at a 25/s vote cadence is dropped samples and a later lock. The run count stays in the
    dozens, so the union is cheap.
    """
    rows = {}
    for y in np.flatnonzero(mask.any(axis=1)):
        xs = np.flatnonzero(mask[y])
        splits = np.flatnonzero(np.diff(xs) > 1)
        segs = [(int(s[0]), int(s[-1])) for s in np.split(xs, splits + 1) if len(s)]
        if segs:
            rows[int(y)] = segs
    parent = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for y, segs in sorted(rows.items()):
        for i, (a0, a1) in enumerate(segs):
            node = (y, i)
            parent.setdefault(node, node)
            for j, (b0, b1) in enumerate(rows.get(y - 1, ())):
                if a0 <= b1 and b0 <= a1:
                    union((y - 1, j), node)
    groups = {}
    for y, segs in rows.items():
        for i, (a0, a1) in enumerate(segs):
            groups.setdefault(find((y, i)), []).append((y, a0, a1))
    out = []
    for comp in groups.values():
        ys = [c[0] for c in comp]
        x0 = min(c[1] for c in comp)
        x1 = max(c[2] for c in comp)
        out.append(((min(ys) + max(ys)) / 2.0, (x0 + x1) / 2.0,
                    sum(c[2] - c[1] + 1 for c in comp), x1 - x0 + 1, max(ys) - min(ys) + 1))
    return out


def sprite_strips(img):
    """Bar centres of every judged sprite in the field, as (y, x) screen pixels.

    The vote's tap-only population, and what the judged sprites of the other kinds add to it:
    across the recorded 0056_03 opening the implied crossings of these bars sat -8..-25 ms off
    the chart on the *same y-shaped curve* the tap blobs live on (tap medians -13/-1/-12/-21/-26/
    -27/-25 ms over y 40..520 in 60 px bands; long about 8 ms below, trace 6), so the vote's
    20 ms bins and 30 ms agreement see one population, not three. One strip per sprite per frame,
    and in the relock window every strip matched a real object with no stray (the tap mask saw
    0 px there); a trace node whose bar splits around its diamond yields two half-bars, each
    still inside the vote's 2.5-lane tolerance.
    """
    m = (cv2.inRange(_rgb(img), (SPRITE_BRIGHT_MIN + 1,) * 3, (255, 255, 255)) > 0) & field_mask()
    out = []
    for cy, cx, npx, w, h in _components(m):
        if (SPRITE_MIN_W <= w <= SPRITE_MAX_W and SPRITE_MIN_H <= h <= SPRITE_MAX_H
                and npx >= SPRITE_MIN_PX):
            out.append((cy, cx))
    return out


def sprite_blobs(img):
    """note_blobs plus the judged sprites no tap blob already covers.

    A tap is its own bar, so the strip detector re-finds it a few pixels from where note_blobs
    measured it; the tolerance keeps the validated tap population exactly as it was and adds
    only what the tap mask cannot see. Callers that vote on it get longs' head caps and traces'
    node bars for free; a caller that must not change its population keeps plain note_blobs.
    """
    out = note_blobs(img)
    for y, x in sprite_strips(img):
        if any(abs(y - by) <= 22 and abs(x - bx) <= 30 for by, bx in out):
            continue
        out.append((y, x))
    return out


def lane_at(x, y):
    lo = EDGE_LEFT_AT_0 - EDGE_SLOPE * y
    hi = EDGE_RIGHT_AT_0 + EDGE_SLOPE * y
    return (x - lo) / (hi - lo) * 24.0


def implied_votes(dets, notes, c_sec=C_FIELD, vp=VP_MOTION, judge_y=JUDGE_Y, lane_tol=2.5,
                  lo=None, hi=None):
    """Every (blob, note) pair's implied song start, restricted to the starts that could happen.

    This is the vote's whole geometry in one place: `vote_t0` turns these into an answer, and an
    experiment that wants to compare answers has to compare them over the *same* votes, or it is
    measuring its own arithmetic instead of the statistic.

    A blob matches every note within `lane_tol`, which in a dense chart is ~150 of them, so each
    blob also votes for a hundred wrong alignments spread over the whole song -- and where the chart
    repeats a section verbatim, one of those is a genuine second peak that can outvote the truth.
    `lo`/`hi` narrow the range to where the audio really could have begun, which is what makes the
    histogram trustworthy.
    """
    sj = 1.0 / (judge_y - vp)
    # Vectorised: with the fast renderer source the detector runs at hundreds of frames a second
    # and the blob count reaches four digits within seconds, and the per-pair Python loop was the
    # one part of the vote that could not keep up with its own frame rate.
    d = np.asarray(dets, dtype=np.float64)
    cross = d[:, 0] + c_sec * (1.0 / (d[:, 1] - vp) - sj)
    lo_e = EDGE_LEFT_AT_0 - EDGE_SLOPE * d[:, 1]
    hi_e = EDGE_RIGHT_AT_0 + EDGE_SLOPE * d[:, 1]
    lane = (d[:, 2] - lo_e) / (hi_e - lo_e) * 24.0
    nt = np.array([n[0] for n in notes])
    nlane = np.array([n[1] for n in notes])
    vv = cross[:, None] - nt[None, :]
    ok = np.abs(nlane[None, :] - lane[:, None]) <= lane_tol
    if lo is not None:
        ok &= vv >= lo
    if hi is not None:
        ok &= vv <= hi
    return vv[ok]


def vote_t0(dets, notes, c_sec=C_FIELD, vp=VP_MOTION, judge_y=JUDGE_Y, bin_s=0.020,
            lane_tol=2.5, lo=None, hi=None):
    """Histogram every implied song start; return
    (t0, votes_at_peak, votes_at_runner_up, runner_up_centre).

    Each blob implies "if this were note j, the song began at X". Scenery spreads its votes
    thinly over every candidate while real notes all pile onto the one true t0, so the peak is
    the answer and the ratio to the runner-up is a self-check the single-note extrapolation
    never had.
    """
    vals = implied_votes(dets, notes, c_sec=c_sec, vp=vp, judge_y=judge_y,
                         lane_tol=lane_tol, lo=lo, hi=hi)
    if len(vals) < 3:
        return None, 0, 0, None
    edges = np.arange(vals.min(), vals.max() + bin_s, bin_s)
    if len(edges) < 2:
        # Every vote landed inside one 20 ms bin. For the wide votes the old code answered "no
        # peak to find" -- but with the relock's one-note feed this is not a missing peak, it is
        # the peak: a dozen samples of one sprite agreeing to better than 20 ms. t12 died on
        # exactly this -- the window held the truth at +0.12 s and every vote still came back
        # None. Return it as a unanimous win; the caller's stable-count and min_votes apply.
        return float(vals.mean()), len(vals), 0, None
    counts, be = np.histogram(vals, bins=edges)
    k = int(np.argmax(counts))
    # The runner-up has to be a different peak. The bins either side of the winner are its own
    # shoulders, so counting them made every vote look like a coin flip.
    lo, hi = max(0, k - 3), min(len(counts), k + 4)
    elsewhere = np.concatenate([counts[:lo], counts[hi:]])
    if len(elsewhere):
        j = int(np.argmax(elsewhere))
        second = int(elsewhere[j])
        kb = j if j < lo else j + (hi - lo)
    else:
        second, kb = 0, None
    # Sub-bin: average the votes that landed in the winner's neighbourhood.
    centre = (be[k] + be[k + 1]) / 2.0
    near = vals[np.abs(vals - centre) <= 2.5 * bin_s]
    # The runner-up's own centre matters to the caller: on this chart the four identical intro
    # taps make the true start and its 316 ms echo tie, so the two leaders are both live answers
    # long before either can be confirmed.
    second_centre = None
    if kb is not None:
        c2 = (be[kb] + be[kb + 1]) / 2.0
        near2 = vals[np.abs(vals - c2) <= 2.5 * bin_s]
        if len(near2):
            second_centre = float(near2.mean())
    return float(near.mean()), int(counts[k]), second, second_centre


def anchor_vote(source, notes, seconds=16.0, judge_y=JUDGE_Y, c_sec=C_FIELD,
                vp=VP_MOTION, min_votes=7, stable=3, tol_s=0.030, max_age_s=20.0,
                lo=None, hi=None, margin=0, blob_every=0.04, vote_every=0.25, log=print,
                on_vote=None, min_dets=9, blobber=None):
    """Estimate the host time of chart t=0 from every blob seen since the LIVE began.

    This replaces the three-sample single-note extrapolation, which put t0 more than 100 ms apart
    on two runs of the same chart -- enough to turn a7's 417 misses into a8's 512. A hundred
    detections good to ~20 ms each is a different class of estimate, and because the errors are
    independent they average out: the ~70 ms of screencap-duration jitter that ruins a single
    landmark is worth ~2 ms here.

    Acceptance is by agreement across successive votes rather than by peak sharpness. On real
    frames the winning bin is only 1.2x the rest of the histogram even when it is exactly right, so
    a ratio gate never fires; three consecutive answers inside 30 ms, on the other hand, says the
    peak has settled, and a wrong lock moves by hundreds of milliseconds instead.

    `max_age_s` bounds what a lock is worth. With 449 notes and a 2.5-unit lane tolerance a blob is
    explainable by several alignments, and the early frames genuinely do pile up on a wrong one --
    one run sat on a t0 34 s in the past for three consecutive votes. An alignment that says the
    audio started more than `max_age_s` ago cannot be right, because the vote only begins once the
    field is already up; rejecting those is what lets the lock happen at +6 s instead of +10 s. A
    t0 in the *future* is the opposite case and is deliberately allowed: it means we anchored
    during the lead-in, which is the best possible outcome, not an error.

    `lo`/`hi` narrow the histogram itself, which is stronger than filtering the answer: with the
    whole song in play the plurality can sit on an alias and the truth is then simply invisible,
    whereas restricting the starts to the window the audio could actually have begun in makes the
    argmax the best candidate inside it.
    """
    import time

    if source is None:
        source = frames
    # `blobber` swaps the frame detector. The default is the tap mask -- what the mid-song probe
    # thread and the manual calibration tool use. Both clocks that decide a round pass sprite_blobs
    # (the relock, and the run path's own opening vote since 2026-10-07): a chart that opens on
    # longs/traces has no tap blobs to vote on, so the tap feed votes on an empty screen and locks
    # seconds after note 1 -- 0056_03 opens with eight of them, and probes/freshfeed.py PART 6 pins
    # the two feeds against each other on that recording.
    find = blobber or note_blobs
    dets = []
    seen = []
    start = time.perf_counter()
    end = start + seconds
    last_blob = last_vote = float("-inf")
    last_key, repeats = None, 0
    while time.perf_counter() < end:
        # The source stamps its own pixels. For `screencap` that has to be the moment the call
        # starts, because the call blocks ~356 ms and the framebuffer is already as of then;
        # stamping the return put every note ~356 ms behind where it was, four judgement windows
        # of pure error that varies by +-46 ms so the offset cannot absorb it.
        t, img = source()
        # A frame that says the same thing as the frame before it is not a second sample of the
        # world, and this loop pays twice for believing otherwise: the detector runs over the same
        # pixels again (11.9 ms of a ~9 ms budget) and `dets` grows junk that every later vote has
        # to be re-histogrammed against -- lifting the runner-up around the true peak, which is what
        # the margin tests are there to catch. `mumucap.frame()` can hand the same buffer back with
        # a fresh stamp when the renderer stalls, and `screencap` can on a page that is simply not
        # animating. See `frame_key` for what this does and does not protect.
        key = frame_key(img)
        if key == last_key:
            repeats += 1
            continue
        last_key = key
        # The blob and vote cadences only bind on the fast renderer source: at screencap's ~280 ms
        # a frame both thresholds pass for free, so the slow path behaves exactly as before. A
        # 480 fps source without them would append tens of thousands of near-duplicate blobs and
        # re-vote on every one of them; 25 blob samples a second is already ten times what a
        # 12-blob vote ran on for three sessions, and a 250 ms vote cadence keeps each answer in
        # the acceptance chain as independent of the last as it ever was on screencap.
        if t - last_blob >= blob_every:
            last_blob = t
            for y, x in find(img):
                dets.append((t, y, x))
        # Nine, not twelve: every blob votes for its own note too, so the true alignment is
        # structurally the plurality from the very first handful and the count here only needs
        # to be enough for the histogram to mean anything. At ~2.8 blobs a frame the old floor
        # cost a whole frame of lock time -- one intro note -- in a22 and a23.
        # `min_dets` overrides it: a caller whose window is narrow enough that the blobs can only
        # imply one alignment (焚音打's tight vote) can vote on far fewer, which is the difference
        # between locking after 5 screencaps and after 12.
        if len(dets) < min_dets:
            continue
        if t - last_vote < vote_every:
            continue
        last_vote = t
        t0, peak, second, second_t0 = vote_t0(dets, notes, c_sec, vp, judge_y, lo=lo, hi=hi)
        if t0 is None:
            continue
        age = t - t0
        # Logged before the bound is applied. A run that accepted nothing at all printed no votes
        # and left a 69-blob failure undiagnosable.
        log(f"  {len(dets)} blobs at +{t - start:.1f}s: t0={t0:.3f} peak={peak} "
            f"elsewhere={second} chart_age={age:+.2f}s"
            + (f"（{repeats} 张重复帧未计）" if repeats else ""))
        if on_vote is not None:
            # Fired for rejected votes too: the tie that fails the margin is exactly the moment
            # the caller needs both candidate alignments, and waiting for an accepted vote would
            # hand them over after the notes at stake were already due.
            on_vote(t0, second_t0, peak, second)
        if age > max_age_s:
            continue
        if peak < min_votes or peak < second + margin:
            # A vote that cannot clear the runner-up by `margin` is the chart answering itself
            # back -- this chart's intro is four identical taps at one lane, so its first frames
            # genuinely tie. A tied vote is evidence of nothing, and appending it would only
            # push the run of agreeing answers the lock waits for one frame later.
            continue
        seen.append(t0)
        if len(seen) >= stable:
            recent = np.array(seen[-stable:])
            if recent.max() - recent.min() <= tol_s:
                return float(recent.mean()), dets
    return None, dets


if __name__ == "__main__":
    from PIL import Image

    if len(sys.argv) > 1:
        img = np.asarray(Image.open(sys.argv[1]).convert("RGB"))
        img = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
    else:
        img = capture()
    m = note_mask(img) & field_mask()
    print("note px:", int(m.sum()))
    for y, x in note_blobs(img):
        print(f"  centre y={y:.1f} x={x:.1f} lane={lane_at(x, y):.2f}")
    for y0, y1 in bands(m):
        x0, x1 = widest_run(m, y0, y1)
        print(f"  band y=[{y0},{y1}] x=[{x0},{x1}] w={x1-x0+1}")
