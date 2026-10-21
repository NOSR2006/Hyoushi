"""一次冻结的捕获，不许被数成两个样本。

`anchor_vote` 把每帧看到的 blob 追加进 `dets`，对整份 `dets` 做直方图；中段修正器在自己的喂入上干同
一件事。两者数的都是**样本**。所以当渲染器把同一块合成缓冲交回来两次（`mumucap.frame()` 停更时正是这
样：合法的帧、新的时间戳、旧的像素），循环就会为一个新样本付全额的价钱，却拿不到它的信息：
`sprite_blobs` 一帧 11.9 ms，停更的 1.2 s 里检测器白跑几十次，而重复票把直方图摊薄——`peak <= runner`
和票差正是"锁不许是猜"的那道 tests。

写这条之前我以为最坏的形状是"冻结冒充两次一致的锁"。**PART 3 量下来它不成立**：隐含起点是
`时间戳 - 该 y 的飞行时间`，同一帧在不同时间戳下会落到不同的箱里，峰不会因此抬高。所以这里钉住的是
CPU 与不被摊薄的直方图，不是假锁——这句话留在探针里，因为它是被证据改过一次的说法。

上一件（`framewriter.py` PART 6/7）给快采装了新鲜度读数；这一件管**读数有没有人听**：投票与中段修正
两条采样路现在都问 `detect.frame_key`，画面没变的那一帧不进门。

PART 1: `frame_key` 本身的性质与代价（同一块缓冲同键；页面级的变化换键；一帧 <0.1 ms）。
PART 2: 真录像回放（0056_03 开场 49 帧、它自己的时间戳）：闸门必须让投票照样锁在录音自己的 t0 上，
        ±30 ms 以内——正常路一点便宜都不许占。
PART 3: 牙：同一帧永远交回来。发货代码只让检测器跑一次；把新鲜度判据换成"每帧都新"，同一段里检测器
        白跑几十次、dets 涨十倍，而两边都不许锁（那句"冻结冒充不了锁"就是从这里来的）。
PART 4: `calib.restart_to_t0` 的暂停面板：按过暂停之后画面还是 LIVE，要再按一次并走到 确定；
        连续读不到面板才认输（补按上限一次），并且"面板本来就在"的局不多按一次。
PART 5: 走查的 `page()` over 真帧：那张让 g296/g300 整局放弃的暂停面板，现在必须读 'pause'；把暂停
        判据拿掉（=旧顺序）它就掉进 `_modal_close` 读成 'rewards' —— 那两局就是这么死的。
PART 6: 无重试钟那一局的开场钟（2026-10-07，用户 m23372：协作模式没有暂停、也没有重试）：开场投票的
        喂料必须是 sprite，锁必须落在第一次按压之前；同一段素材换回 tap 掩码就锁不上。0056_03 的开场
        八颗全是 long/trace、一颗 tap 都没有 —— g291-g295 五局就是这么丢的，它们回得来只因为重试钟
        把 LIVE 重开了一次。同一个录音，第二个问题。

Run from the repo root:  python tools/probes/freshfeed.py
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import calib                                                   # noqa: E402
import detect                                                  # noqa: E402
from detect import anchor_vote, frame_key, sprite_blobs         # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "research" / "charts" / "0056_03.hits.json"
ARCHIVE = ROOT / "research" / "archive" / "media" / "our_survival_open_0930"
PLAYER = ROOT / "tools" / "player.py"
# The recording's own t0, voted from its tap era (spritebars.py 用的是同一份）。
T0_REC = 687914.412
WINDOW = (0.4, 1.93)           # the seconds after t0 the relock actually samples on this chart
BLOB_MS = 11.9                 # one sprite_blobs pass over a 720p frame, measured by maskfast.py
# PART 6's four numbers. `meta.json` stamps this recording's field 0.332 s *after* its t0 -- it is a
# fresh LIVE, not a restarted one, so the relock's own +0.045 window centre does not describe it and
# the field stamp is the only thing the intro vote gets to place its window with.
T_LIVE = 687914.7444111
FIRST_NOTE = 2.356             # 0056_03's first note, a long; the eight around it are long/trace
PRE = 0.020                    # player.play's default: the press is scheduled this much before it
PRESS_DUE = FIRST_NOTE - PRE   # the clock has to be in hand by here or note 1 is gone (2.336 s)
FIELD_LAGS = (0.0, 0.2, 0.4)   # what the walk's own 'live' poll can add before field_seen is stamped
# The shipped tight window, mirrored here so a widened one cannot pass unnoticed: `player.play`
# votes `[field_seen - WIN_LO, field_seen + 0.6]` with `margin=MARGIN`. WIN_LO=1.2 is the 2026-10-07
# value (was 2.0) and MARGIN=3 (was 1): 0056_03's real rounds locked 1.88 s early (g453/g454, both
# 370-390 MISS) because the alias won the margin by 2 while the true locks won by 6 and 3.
WIN_LO = 1.2
MARGIN = 3
ALIAS = 1.5                    # note shift that manufactures that alias for this recording: the
#                                candidate lands at field-1.83, where g453/g454 actually locked


def replay_frames():
    """(host stamp, RGB) for the recording's opening window, in its own cadence."""
    meta = json.load(open(ARCHIVE / "meta.json", encoding="utf-8"))["frames"]
    out = []
    for m in meta:
        if not WINDOW[0] <= m["t"] - T0_REC <= WINDOW[1]:
            continue
        out.append((m["t"], np.asarray(Image.open(ARCHIVE / f"{m['seq']:05d}.jpg").convert("RGB"))))
    return out


def notes(shift=0.0):
    hits = json.load(open(CHART, encoding="utf-8"))
    return [(float(h["t_ms"]) / 1000.0 + shift, h["lane"]) for h in hits]


def part1():
    a = np.full((720, 1280, 3), 40, np.uint8)
    b = a.copy()
    b[400:420, 600:640] = 240                                  # a note sprite appearing
    for _ in range(20):
        frame_key(a)
    t0 = time.perf_counter()
    for _ in range(300):
        frame_key(a)
    per = (time.perf_counter() - t0) / 300 * 1000
    ok = frame_key(a) == frame_key(a.copy()) and frame_key(a) != frame_key(b) and per < 0.1
    print(f"PART 1 同一块缓冲同键={frame_key(a) == frame_key(a.copy())}、场上多出一个色块就换键="
          f"{frame_key(a) != frame_key(b)}、{per * 1000:.0f} µs/帧（判据 <0.1 ms，捕获 9 ms）-> "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def vote_over(source, seconds=3.0, key=None, blobber=sprite_blobs):
    """anchor_vote on the shipped detector feed, with the freshness key optionally swapped out.

    The candidate window is wider than the relock's own +-0.22 s: PART 3 asks what a frozen frame
    does to the loop at all, and which t0 it would land on is not the question. Both cases get the
    same window, so the comparison stays honest.
    """
    real = detect.frame_key
    if key is not None:
        detect.frame_key = key
    try:
        return anchor_vote(source, notes(), seconds=seconds, blobber=blobber,
                           lo=T0_REC - 1.2, hi=T0_REC + 1.2, min_dets=3, min_votes=5,
                           stable=2, blob_every=0.04, vote_every=0.25, log=lambda *a: None)
    finally:
        detect.frame_key = real


def part2(frames):
    """The recording's own frames with the recording's own stamps -- the cadence is in the pixels.

    Stamps are served from the file rather than from this process's clock on purpose: `anchor_vote`
    takes both its blob cadence and its vote cadence from the stamps it is given, so resampling them
    against a wall clock here would measure this machine's JPEG decoding, not the gate.
    """
    i = [0]

    def source():
        k = min(i[0], len(frames) - 1)
        i[0] += 1
        time.sleep(0.009)                  # what the renderer costs; the loop must not spin hot
        return frames[k]

    t0, dets = vote_over(source, seconds=2.5)
    ok = t0 is not None and abs(t0 - T0_REC) <= 0.030
    print(f"PART 2 真开场 {len(frames)} 帧按录音自己的节奏回放：锁="
          f"{'没有' if t0 is None else f'{1000 * (t0 - T0_REC):+.1f} ms'} vs 录音自己的 t0，"
          f"喂进 {len(dets)} 个 blob -> {'PASS' if ok else 'FAIL'}")
    return ok


def part3(frames):
    """One picture, handed back forever -- and what refusing it actually buys, measured.

    The assumption going in was the loud one: a frozen capture fakes the two-votes-agreeing lock.
    It does not, and this part says so with the numbers: an implied start is `stamp - flight(y)`, so
    duplicates stamped at advancing times land in different bins and the peak never rises. What the
    freeze really costs is the quiet kind -- the detector re-running over the same pixels at the
    renderer's cadence, and the duplicate votes spreading the histogram the margin tests lean on.
    """
    stuck = frames[len(frames) // 2]
    wall = time.perf_counter()

    def source():
        time.sleep(0.009)          # the renderer's own cadence: a stall still answers ~100/s
        # Stamps in the recording's own era: the candidate window is stated in those terms, and a
        # source stamped from this process's clock would fail the window for reasons that have
        # nothing to do with the gate under test.
        return stuck[0] + (time.perf_counter() - wall), stuck[1]

    seen = []

    def counted(img):
        seen.append(1)
        return sprite_blobs(img)

    n = [0]
    t0, dets = vote_over(source, seconds=1.2, blobber=counted)
    shipped = len(seen)
    t0off, detsoff = vote_over(source, seconds=1.2, blobber=counted,
                               key=lambda img: n.__setitem__(0, n[0] + 1) or n[0])
    gate_off = len(seen) - shipped
    ok = (shipped <= 1 and gate_off > 10 * max(shipped, 1) and len(detsoff) > 10 * max(len(dets), 1)
          and t0 is None and t0off is None)
    print(f"PART 3 同一帧交回来 1.2 s：闸门收下 {shipped} 帧、检测器跑 {shipped} 次；"
          f"闸门关掉：检测器白跑 {gate_off} 次（{BLOB_MS * gate_off / 1000:.2f} s CPU 在同一帧上）、"
          f"dets {len(dets)} -> {len(detsoff)}；两边都没有锁（={t0 is None and t0off is None}）——"
          f"冻结冒充不了锁，这条闸门买的是 CPU 和不被摊薄的直方图 -> "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


class ShimTime:
    """calib's own clock, so the scripted walk does not really sleep 0.4 s a poll."""

    def __init__(self, real):
        self._real = real

    def perf_counter(self):
        return self._real.perf_counter()

    def sleep(self, s):
        return None


def restart_with(pages):
    """calib.restart_to_t0 over a scripted page reading; returns (t_ok, 按了几次暂停, 日志)."""
    lines, taps = [], []
    seq = list(pages)

    def page(*a, **k):
        return seq.pop(0) if seq else "live"

    def pause(inj, log=print):
        lines.append("暂停")
        return True

    old = (calib.page, calib.tap, calib.in_live, calib.pause_if_live, calib.time)
    try:
        calib.page = page
        calib.tap = lambda *a, **k: taps.append(a[:2])
        calib.in_live = lambda: True
        calib.pause_if_live = pause
        calib.time = ShimTime(time)
        t = calib.restart_to_t0(None, log=lines.append, rounds=8)
    finally:
        (calib.page, calib.tap, calib.in_live, calib.pause_if_live, calib.time) = old
    return t, lines.count("暂停"), "\n".join(lines)


def part4():
    """The pause panel is waited for, not assumed -- and the extra tap is bounded.

    `pause_if_live` sleeps and returns True whatever the screen did afterwards: it fires, it does
    not confirm. g291/g292/g293 each read `live` exactly once after that tap, took it as "nothing to
    restart from", fell back to the intro vote an already-running LIVE cannot win, and spent their
    first attempt on the 出生即废 fence. Script A is that screen: the panel shows up on the second
    poll. Script B is the case the bound exists for: a page that never pauses at all.
    """
    t, pauses, log = restart_with(["live", "pause", "confirm"])
    late = t is not None and pauses == 2 and "补按" in log
    t2, pauses2, log2 = restart_with(["live"] * 12)
    bounded = t2 is None and pauses2 == 2 and log2.count("nothing to restart") == 1
    t3, pauses3, log3 = restart_with(["pause", "confirm"])
    clean = t3 is not None and pauses3 == 1 and "补按" not in log3
    ok = late and bounded and clean
    print(f"PART 4 第一读还是 LIVE：补按一次后走到 确定={late}（暂停共按 {pauses} 次）；"
          f"永远不出现面板：认输且只按两次={bounded}（{pauses2} 次）；"
          f"面板本来就在：不补按={clean}（{pauses3} 次）-> {'PASS' if ok else 'FAIL'}")
    return ok


def part5():
    """The walk's own page reader over the frame that killed g296 and g300.

    `page()` is what `restart_to_t0` acts on, and it is more than `screen()`: a live field can wear
    three bright bars that look exactly like a dialog, so the dialog test only gets a vote once the
    field is confirmed. The paused round in `evidence/nav/navgates_pause_a.png` fell between those
    two -- `screen` answered 'rewards' (a wide pale bar under the 终止/重试/继续 row satisfies
    `_modal_close`), so `page()` never asked the dialog test at all, and the restart gave up.
    """
    img = np.asarray(Image.open(ROOT / "evidence" / "nav" / "navgates_pause_a.png").convert("RGB"))
    real = (calib.grab, calib._dialog)
    try:
        calib.grab = lambda: img
        shipped = calib.page()
        # The old ordering, replayed: take the pause claim away and the modal test wins the frame.
        calib._dialog = lambda im, *a, **k: None
        before = calib.page()
    finally:
        calib.grab, calib._dialog = real
    ok = shipped == "pause" and before == "rewards"
    print(f"PART 5 走查读这一张暂停帧：发货代码 page()={shipped!r}（要 'pause'）；"
          f"把暂停判据拿掉（=旧顺序）page()={before!r}（这就是 g296/g300 白丢一局的那一行）-> "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def intro_vote(frames, lag, blobber, seconds=12.0, shift=0.0, lo_pad=-WIN_LO):
    """The production intro vote over this recording: window [field_seen+lo_pad, field_seen+0.6].

    `player.play` calls exactly this (12 s, `stable=2, margin=MARGIN, min_votes=5, min_dets=3`) the
    moment a LIVE is up and no restart put a clock in its hands. Returns (t0, lock_chart_s, dets):
    the second is the stamp of the frame the loop last pulled, in chart seconds, which is the number
    the first press has to come after. `lag` is how much later than the field paint the walk stamps
    `field_seen` -- the one part of production this archive cannot show, so it is swept. `shift`
    moves every note later by that many seconds, which manufactures the self-similar alignment the
    2026-10-07 rounds locked on; `lo_pad` is the lower bound, so that alias can be voted with the
    shipped window and with the old -2.0 one, and the pair shows which of the two lets it through.
    """
    field_seen = T_LIVE + lag
    material = [f for f in frames if f[0] >= field_seen]
    i = [0]
    last = [0.0]

    def source():
        k = i[0]
        i[0] += 1
        if k < len(material):
            last[0] = material[k][0]
            time.sleep(0.009)                  # the renderer's cadence, as PART 2 does
            return material[k]
        # The material ends where the archive does. A live capture keeps handing over *new* frames;
        # this serves advancing stamps over the last one, which `frame_key` then refuses -- so a
        # lock that would need material past the archive cannot happen here, and a run that does not
        # lock is the honest answer instead of a stall.
        last[0] += 0.009
        return last[0], material[-1][1] if material else frames[-1][1]

    t0, dets = anchor_vote(source, notes(shift), seconds=seconds, blobber=blobber,
                           lo=field_seen + lo_pad, hi=field_seen + 0.6,
                           stable=2, margin=MARGIN, min_votes=5, min_dets=3,
                           blob_every=0.04, vote_every=0.25, log=lambda *a: None)
    return t0, last[0] - T0_REC, dets


def part6(frames):
    """The no-retry round's opening clock: the feed has to see long/trace, the lock has to land
    before the first press, and the 1.88 s self-similarity has to stay outside the window.

    协作模式没有暂停也没有重试（用户 m23372），所以没有 `restart_to_t0` 把 LIVE 拽回 t0 再重锁：开局
    那一票就是这一局唯一的钟。0056_03 的开场八颗全是 long/trace，`note_blobs`（tap 掩码）在第一次按压
    之前一个 blob 都看不到 —— 语料里 g291-g295 就是这么丢的，它们回得来只因为重试钟把 LIVE 重开了
    一次。这里用发货的检测器把同一段开场按三种 `field_seen` 延迟各投一次，再用 tap 掩码做对照。
    2026-10-07 的 g453/g454 锁在 field-1.813/-1.830（真值之前 1.88 s 的自相似对齐，两局 386/373 个
    MISS、开局四颗直接丢），所以最后两条把这份素材的谱面整体后移 `ALIAS` 秒、人为造出那个对齐：发货
    的窗必须把它挡在外面，而旧的 -2.0 窗必须放它进来 —— 挡住它的正是窗下界，不是别的什么。
    """
    src = PLAYER.read_text(encoding="utf-8")
    i = src.index("def vote(seconds, lo, hi, tag, **kw):")
    call = src[i:src.index("def stop_shot", i)]
    pinned = "blobber=sprite_blobs" in call
    # The call site lives in play(), past def stop_shot, so this one is pinned against the whole
    # file; the feed pin above stays inside the definition.
    win = (f'vote(12.0, field_seen - {WIN_LO:.1f}, field_seen + 0.6, "tight",' in src
           and f"stable=2, margin={MARGIN}, min_votes=5, min_dets=3)" in src)
    rows, ok = [], pinned and win
    for lag in FIELD_LAGS:
        t0, when, dets = intro_vote(frames, lag, sprite_blobs)
        good = t0 is not None and abs(t0 - T0_REC) <= 0.030 and when <= PRESS_DUE
        ok = ok and good
        rows.append(f"  field+{lag:.1f}s：锁="
                    + ("没有" if t0 is None else f"{1000 * (t0 - T0_REC):+.1f} ms")
                    + ("" if t0 is None else
                       f"，落在 chart +{when:.2f}s（余量 {PRESS_DUE - when:+.2f}s）")
                    + f"，{len(dets)} blob")
    t0tap, whentap, _ = intro_vote(frames, 0.0, None)
    control = t0tap is None or whentap > PRESS_DUE
    want = T0_REC - ALIAS
    t0new, _, _ = intro_vote(frames, 0.0, sprite_blobs, shift=ALIAS)
    out = t0new is None or abs(t0new - want) > 0.030
    t0old, _, _ = intro_vote(frames, 0.0, sprite_blobs, shift=ALIAS, lo_pad=-2.0)
    inside = t0old is not None and abs(t0old - want) <= 0.030
    alias = out and inside

    def where(t0):
        return "没锁上" if t0 is None else f"锁在 {1000 * (t0 - want):+.1f} ms"

    print(f"PART 6 无重试钟的开场钟（第一次按压在 chart +{PRESS_DUE:.3f}s）：\n" + "\n".join(rows)
          + f"\n  发货代码钉住 sprite 喂料={pinned}；发货窗 field-{WIN_LO:.1f} / margin {MARGIN} 与"
          + f"源码一致={win}"
          + f"\n  同一段素材换回 tap 掩码（对照）="
          + ("没锁上" if t0tap is None else f"锁在 chart +{whentap:.2f}s")
          + f"（必须晚于 +{PRESS_DUE:.2f}s，={control}）"
          + f"\n  谱面整体后移 {ALIAS:.1f}s（造出 g453/g454 锁的那个 1.88s 自相似）："
          + f"发货窗={where(t0new)}（必须在窗外，={out}）；旧窗 field-2.0={where(t0old)}"
          + f"（必须锁上，={inside}）"
          + f" -> {'PASS' if ok and control and alias else 'FAIL'}")
    return ok and control and alias


def main():
    if not ARCHIVE.exists():
        print(f"录音缺失：{ARCHIVE} -- 这条回归要的是真画面，不能拿合成帧顶")
        return 1
    frames = replay_frames()
    print(f"回放素材：{ARCHIVE.name} 的判定窗口 {WINDOW} 内 {len(frames)} 帧，"
          f"{frames[0][1].shape}；谱面 {CHART.name}\n")
    parts = [part1(), part2(frames), part3(frames), part4(), part5(), part6(frames)]
    print("\nfreshfeed " + ("PASS" if all(parts) else "FAIL"))
    return 0 if all(parts) else 1


if __name__ == "__main__":
    sys.exit(main())
