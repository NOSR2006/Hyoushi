"""Walk the game's song list to a chosen song (and difficulty), verifying every step.

The list is a Flutter ListView. Its gesture mapping is *not* a ruler, so nothing here trusts a
gesture:

  * one measured drag moves one row -- 500 -> 350 in 0.30 s measured +1 (6 of 6), 560 -> 700 in
    0.45 s measured -1 (4 of 6) -- but the same gesture is occasionally swallowed outright, and
    once Flutter's fling physics take over the distance goes wild: the *same* 200 px gesture
    measured +2 at 0.60 s and +24 at 0.30 s, and a 336 px drag at 0.30 s moved nothing at all.
  * a drag that starts inside the selected row's art band (y 303..410 at x 213..313, the enlarged
    cover of the highlighted row) does not scroll at all, so both gestures keep their start point
    clear of it.
  * 2026-10-09, measured with 2.5 s of rest between gestures: **duration is the handle, not
    distance**. 150 px in 0.15 s flung the list 59 rows; the same 150 px in 0.50 s moved exactly
    one; 100 px in 0.50 s one; 60 px and 30 px in 0.50 s nothing; 150 px in 0.50 s the other way
    one back. `FWD`/`BACK` therefore drag over 0.55 s -- the old 0.30 s sat on the fling edge, which
    is how the walk ping-ponged between 100021 and 100105 for four and a half minutes.

So the loop is a proposal-and-check: one drag, then `gameread.read_song_select()` decides what
actually happened (it reports `musicId` with >= 0.99 confidence once the list has settled). A
stalled drag is retried, the direction is recomputed from the manifest every step, and an
overshoot is corrected by the next step -- the manifest's `songs` order was measured to match the
game's list order, but it is only ever used as a direction hint.

    from songpick import select_chart
    select_chart("100056", "expert")      # 0056_03 EXPERT
"""

from __future__ import annotations

import json
import os
import time

import detect
import gameread
import inject

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "research", "charts", "manifest.json")

DRAG_X = 360                      # clear of the covers (x 213..313) and of the right panel (x 738+)
FWD = (500, 350, 0.55)            # (from_y, to_y, seconds) -- measured +1 row (2026-10-09)
BACK = (560, 700, 0.55)           # measured -1 row; 0.30 s / 0.45 s flung the list instead
HOLD_S = 0.15                     # pause on the destination before lifting: damps the fling
SETTLE_S = 1.0                    # the list snaps, then read_song_select needs a settled frame
STALL_RETRIES = 3                 # a swallowed drag is retried this many times before giving up
DRIFT_LIMIT = 4                   # steps without getting closer than `best` before we call it lost
FLING_SETTLE_S = 2.0              # after a fling the list coasts on; wait it out before the next drag
WALK_ATTEMPTS = 2                 # a fling can leave the target straddled; a fresh walk usually lands

DIFF_Y = 556                      # the difficulty pills' band is y 527..585, x 741..1265
DIFF_PILLS = {                    # four equal 131 px quarters, measured
    "easy": 806,
    "normal": 937,
    "hard": 1068,
    "expert": 1199,
}

_LAST: dict = {}                  # the last select-page read, which is what pill_y() reads


def pill_y() -> int:
    """The y to tap a difficulty pill at, for the page the last read came from.

    The 多人 乐曲选择页 draws the same four pills 30 px lower (y 557..615: measured on the mp2
    recording and on the frame g486 died on, where tapping y 556 changed nothing three times).
    The row therefore comes from the read that named the difficulty, not from a constant; a read
    that never happened keeps DIFF_Y, which is the single-player row.
    """
    row = (_LAST.get("detail") or {}).get("row")
    return (int(row) + gameread.DIFF_ROW_H // 2) if row is not None else DIFF_Y


def load_order(path: str = MANIFEST) -> list[str]:
    """The manifest's song order, which is the game's list order (musicIds are strings)."""
    data = json.load(open(path, encoding="utf-8"))
    return [str(song["musicId"]) for song in data["songs"]]


ORDER = load_order()


def read_current(frame=None):
    """(musicId, difficulty, confidence) of the row the game currently has selected.

    Without a frame this takes one from `detect.grab()`, which is whatever capture source the
    round has installed (renderer SDK, window capture or screencap) -- a pick runs inside a round
    and must read the same pixels the walk does.

    (None, None, 0.0) when the page does not read at all. This used to index the read straight
    away, so a frame taken mid-transition raised KeyError out of the middle of a walk instead of
    letting the caller's own loop decide what a missing read means. The successful read is kept
    for pill_y(), which needs the row the difficulty came from.
    """
    if frame is None:
        frame = detect.grab()
    got = gameread.read_song_select(frame)
    _LAST.clear()
    _LAST.update(got)
    if not got.get("ok"):
        return None, None, 0.0
    return str(got["musicId"]), got["diff"], got["score"]


def _swipe(inj, y0: int, y1: int, seconds: float) -> None:
    rx, ry = inject.to_raw("device", DRAG_X, y0)
    inj.touch_down(0, rx, ry, 7)
    time.sleep(0.05)
    steps = max(5, int(seconds / 0.02))
    for k in range(1, steps + 1):
        ys = int(round(y0 + (y1 - y0) * k / steps))
        rx, ry = inject.to_raw("device", DRAG_X, ys)
        inj.touch_move(0, rx, ry)
        time.sleep(seconds / steps)
    time.sleep(HOLD_S)
    inj.touch_up(0)
    time.sleep(SETTLE_S)


def step(inj, forward: bool = True) -> None:
    """One drag: one row, as long as the gesture is slow enough not to fling.

    2026-10-09 (list at rest, 2.5 s between gestures): 150 px in 0.15 s moved **-59 rows** -- the
    fling took over -- while the same 150 px in 0.50 s moved **+1**, 100 px in 0.50 s **+1**, 60 px
    and 30 px in 0.50 s **nothing**, and 150 px in 0.50 s the other way **-1**. The old 0.30 s sat
    on that edge, so the same gesture sometimes flung the list ~57-60 rows (that is how the walk
    ping-ponged between 100021 and 100105) and sometimes moved nothing. Duration is the handle.
    """
    y0, y1, seconds = FWD if forward else BACK
    _swipe(inj, y0, y1, seconds)


def select_song(target: str, inj=None, log=print, budget: int | None = None) -> bool:
    """Walk to `target`. Returns True only when a fresh read says we are on it.

    `inj` may be an existing TouchInjector (a round keeps one open for the whole run); otherwise
    one is opened here. Note `inject.TouchInjector()` opens in its constructor -- calling
    `open()` again leaks a second writer and only one process can hold /dev/input/event4.
    """
    target = str(target)
    if target not in ORDER:
        log(f"  选曲：{target} 不在 manifest 的 {len(ORDER)} 首里，连方向都定不了")
        return False
    own = inj is None
    if own:
        inj = inject.TouchInjector()
    budget = budget or 2 * len(ORDER) + 4
    try:
        for attempt in range(WALK_ATTEMPTS):
            if _walk(target, inj, log, budget):
                return True
            if attempt + 1 < WALK_ATTEMPTS:
                log(f"  选曲：这一趟没走到 {target}，重走一趟（第 {attempt + 2} 次）")
        return False
    finally:
        if own:
            inj.close()


def _walk(target: str, inj, log, budget: int) -> bool:
    """One pass of propose-and-check from wherever the list happens to be."""
    cur, diff, conf = read_current()
    log(f"  选曲：现在 {cur}（{diff}，{conf:.3f}），目标 {target}")
    best = None                      # 离目标最近的一次（按行数），漂移判据挂在它上面
    stale = 0
    for i in range(budget):
        if cur == target:
            log(f"  选曲：到达 {target}（第 {i} 步）")
            return True
        want = True if cur not in ORDER else ORDER.index(target) > ORDER.index(cur)
        tries = 0
        while True:
            step(inj, forward=want)
            nxt, _d, _c = read_current()
            if nxt != cur:
                break
            tries += 1
            if tries >= STALL_RETRIES:
                log(f"  选曲：{cur} 连着 {tries} 次拖不动，放弃")
                return False
            log(f"  选曲：拖了一下没动（{cur}），重试 {tries}")
        if cur in ORDER and nxt in ORDER:
            dist = abs(ORDER.index(target) - ORDER.index(nxt))
            delta = ORDER.index(nxt) - ORDER.index(cur)
            log(f"  选曲 {i + 1}: {'上' if want else '下'} {cur} -> {nxt}"
                f"（{delta:+d}，还差 {dist}）" + (f" ×{tries + 1}" if tries else ""))
            if abs(delta) > 3:
                # 一拖该走一行。走了这么多行说明列表在甩；甩完它还会自己滑一段，先等它停，
                # 否则下一拖叠在惯性上，就变成一拖甩过去、一拖甩回来（2026-10-09 真机）。
                log(f"  选曲：这一拖走了 {delta:+d} 行 —— 列表在甩，等 {FLING_SETTLE_S:.1f} s")
                time.sleep(FLING_SETTLE_S)
            if best is None or dist < best:
                best, stale = dist, 0
            else:
                stale += 1
                if stale >= DRIFT_LIMIT:
                    log(f"  选曲：连着 {stale} 步没能靠近 {target}"
                        f"（最近一次 {best} 行，现在 {nxt}），放弃")
                    return False
        else:
            log(f"  选曲 {i + 1}: {cur} -> {nxt}（序号不可比）")
        cur = nxt
    log(f"  选曲：走了 {budget} 步还没到 {target}（现在 {cur}），放弃")
    return False


def set_difficulty(want: str, inj=None, log=print, tries: int = 3) -> bool:
    """Tap the difficulty pill for `want` and confirm it with a read.

    The four pills are fixed, but the *row* they sit on is not: pill_y() follows the read that
    named the current difficulty, so the 多人 page's row (30 px lower) is tapped on the row it is
    actually drawn on rather than 30 px above it.
    """
    want = str(want).lower()
    if want not in DIFF_PILLS:
        log(f"  难度：{want} 不是 {tuple(DIFF_PILLS)} 之一")
        return False
    own = inj is None
    if own:
        inj = inject.TouchInjector()
    try:
        for i in range(max(1, tries)):
            _cur, diff, _conf = read_current()
            if diff == want:
                log(f"  难度：已经是 {want}")
                return True
            y = pill_y()
            rx, ry = inject.to_raw("device", DIFF_PILLS[want], y)
            inj.touch_down(0, rx, ry, 7)
            time.sleep(0.08)
            inj.touch_up(0)
            time.sleep(0.6)
            log(f"  难度：第 {i + 1} 次点 {want}（原来是 {diff}，y={y}）")
        _cur, diff, _conf = read_current()
        ok = diff == want
        log(f"  难度：{'到达' if ok else '没到'} {want}（现在 {diff}）")
        return ok
    finally:
        if own:
            inj.close()


def select_chart(music_id: str, diff: str | None = None, inj=None, log=print) -> bool:
    """Select the song, then (if asked) its difficulty. True only when both reads agree."""
    if not select_song(music_id, inj=inj, log=log):
        return False
    if diff is None:
        return True
    return set_difficulty(diff, inj=inj, log=log)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="walk the game's song list to a chosen song")
    ap.add_argument("music_id")
    ap.add_argument("--diff", default=None, choices=sorted(DIFF_PILLS))
    args = ap.parse_args()
    raise SystemExit(0 if select_chart(args.music_id, args.diff) else 1)
