"""One full attempt: walk into the LIVE, play the whole chart, read the result page, walk back.

The result page is the only place that reports PERFECT/GREAT/GOOD/BAD/MISS exactly, so the run
takes its screenshot there instead of trying to read a live counter -- and then continues the walk
it was already making on every earlier round, one step further, until the game sits on 乐曲选择
again (`--stay-on-result` keeps the old park-on-result behaviour).

Everything happens in one process with one injector on purpose. The anchor needs ~6 s of falling
notes before it can name the clock, and note 1 of this chart arrives at 6.3 s, so every hundredth
of a second between "the field appeared" and "the vote started" is notes we get to hit. Spawning
player.py cost interpreter start, numpy imports and a minitouch launch -- about 3 s, which was the
difference between catching the opening burst and skipping it.
"""
import argparse
import functools
import glob
import json
import os
import statistics
import subprocess
import sys
import time

# pythonw 起的面板没有控制台，这条脚本就在它底下跑（面板每局拉一次）——
# 拉子进程一律挂这个标志，别在用户桌面弹出黑框（用户 m50302）。
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calib import (EXP_RETRY, FIELD_TO_AUDIO, MODAL_CLOSE, RANDOM_BTN, SELECT_BACK,  # noqa: E402
                   SELECT_BACK_HOLD, SELECT_BACK_SETTLE, SELECT_BACK_TRIES, SPLIT_TOGGLE,
                   STORY_CLOSE, field_back_up, page, pause_if_live, relock, restart_to_t0, screen,
                   start_live, tap)
from compile import tick_to_ms  # noqa: E402
from detect import frames, grab, note_blobs  # noqa: E402
from mtouch import MTouch, adb_tap  # noqa: E402
from player import (ABORTED, KINDS, KIND_LEAD_MS, LIVE_PUSH_MS, play,  # noqa: E402
                    raise_timer_resolution)
import player  # noqa: E402  -- module handle: --tail-margin writes player.TAIL_MARGIN_MS
TAIL_MARGIN_DEFAULT = player.TAIL_MARGIN_MS  # the shipped value, kept for the log line
TAIL_FLICK_LEAD_DEFAULT = player.TAIL_FLICK_LEAD_MS  # ditto for --tail-flick-lead
from rlog import (CHAIN_CAL, FRAMES, MANIFEST, RESULT, RESULTS, RUNS,  # noqa: E402
                  RunLog, append_record, fingerprint, subdir, write_json)
import locate  # noqa: E402  -- 路径集中探测与启动校验（见 tools/locate.py）
import memguard  # noqa: E402  -- 开工前看一眼宿主内存，紧了就地回收（见 tools/memguard.py）

# Piping a run into `tee` block-buffers stdout, and a buffered line lands after the output of
# whatever ran next, which makes the log chronology read backwards.
print = functools.partial(print, flush=True)

# A song title can carry characters no console code page has (100050's †, 100034's 🜁), and the
# panel only survives those because it forces utf-8 on its children. A bare shell run inherited
# the GBK console instead and rnd2 died mid-walk formatting a random pick's own log line. Every
# string in this file is log-shaped, so make the stream utf-8 regardless of how it was started.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):                  # not a TextIOWrapper; leave it
    pass


class Watch:
    """Keep looking at the field while the firing loop waits between actions.

    Most of a song is idle time in that loop, and the frames it leaves unobserved are exactly the
    evidence missing when a run starts clean and ends in MISS: a single locked t0 cannot tell a
    wrong start from a clock that drifts, but residuals against the chart over 88 s can.
    """

    def __init__(self):
        self.dets = []

    def __call__(self, budget):
        try:
            t, img = frames(timeout=min(budget, 0.05))
        except Exception:
            time.sleep(min(budget, 0.02))
            return
        for y, x in note_blobs(img):
            self.dets.append((t, y, x))


# The press->judgement latency is a property of the machine's input and audio path, and it
# drifts (tonight it delivers presses ~42 ms earlier than the +55 offset was calibrated on, so
# every judged note sits at -42 ms and the whole margin to the GREAT wall is 8 ms). The offset
# flag stays the nominal constant; this file keeps the measured deviation from it, updated once
# per finished run from the judgement histogram the result page already splits into FAST and
# SLOW -- but only when `--read-split` asked for that extra read, so by default the file is read
# and never written. 0 on file (or no file) leaves every run behaving exactly as the recipe does.
# rlog.CHAIN_CAL, because a working directory that happens not to hold that file reads as corr 0
# and quietly fires the whole chart 10 ms late.


def load_chain_corr():
    """The persisted chain correction in ms, and the state dict it came from."""
    try:
        with open(CHAIN_CAL, encoding="utf-8") as f:
            st = json.load(f)
        return float(st.get("corr_ms", 0.0)), st
    except (OSError, ValueError, TypeError):
        return 0.0, {}


def estimate_delta_ms(rec):
    """Estimate the run's mean judgement delta (ms, negative = FAST) from the split page.

    The split view is the only per-side evidence a finished run leaves and it is a histogram, so
    this is deliberately crude -- a +-15 ms claim, not a measurement: an all-PERFECT run brackets
    the mean inside (-50, 0), read as -28 ms at full FAST lean; any GREAT/GOOD/BAD puts the mean
    past its window and the deepest populated bucket says how far. Crude but monotone, and the
    histogram is re-taken every run, so a wrong bucket costs damping, not the calibration.
    """
    rows = (rec or {}).get("split") or {}
    if not rows:
        return None
    v = {}
    for k in ("p", "g", "gd", "b"):
        pair = rows.get(k)
        if not pair or None in pair:
            return None
        v[k] = pair
    if sum(f + s for f, s in v.values()) < 120:
        return None
    heavy = sum(v[k][0] + v[k][1] for k in ("g", "gd", "b"))
    if heavy == 0:
        f, s = v["p"]
        return -28.0 * (f - s) / max(1, f + s)
    f = sum(v[k][0] for k in ("g", "gd", "b"))
    s = sum(v[k][1] for k in ("g", "gd", "b"))
    mag = 52.0
    if v["gd"][0] + v["gd"][1]:
        mag += 20.0
    if v["b"][0] + v["b"][1]:
        mag += 45.0
    return -mag * (f - s) / heavy


# How far down this file is willing to move the offset. The chain wanted ~42 ms tonight, but the
# offset is not a free parameter on every chart: 焚音打's L12 flick-chain section docks when the
# presses sit late enough that a flick's swipe (or the tap before it) lands inside the *next* tap's
# ~96 ms credit window -- 8 deterministic GOODs at +20 (t17/t18/t21: 1769/0/8/0/0), clear at +55
# (t22/t23 AP). The boundary falls out of the geometry at ~+36 (flick up = note+30, tap up =
# note+45, next tap at +105), so the floor keeps the effective offset at 45+ -- 9 ms of clearance
# against a model whose window width is only bounded to 96..115 by the old runs. 0 on file leaves
# the validated +55 recipe untouched; the mid-song corrector (LiveCorrector) is what carries the
# rest of a fast chain, and it does not move this geometry.
CORR_FLOOR, CORR_CEIL = -10.0, 40.0
# How far one finished run may move the correction, and how many refusals by the same bound make
# it worth saying out loud. One is a correction too small to move 3 ms, which is normal; three is
# the loop repeating itself, which is what reads as "calibrating" when all it does is vote.
CORR_DAMP, PINNED_ALARM = 0.7, 3


def _refused(entry):
    """Which bound refused this history entry's update, or None if the update went through.

    Derived from the entry instead of stored in it, so the 40 runs already on file answer the
    same question as the next one. An entry that moved is the loop working, not a refusal.
    """
    try:
        est, before, after = entry["est_ms"], entry["corr_before"], entry["corr_after"]
    except KeyError:
        return None
    if entry.get("kept"):
        return None         # the rule chose not to move; that is not a bound refusing one
    if abs(after - before) >= 3.0:
        return None
    if after <= CORR_FLOOR + 0.01 and est < 0:
        return "floor"
    if after >= CORR_CEIL - 0.01 and est > 0:
        return "ceil"
    return None


def saturation(hist):
    """What a bound that has refused run after run has to say: (brief, full), or (None, None).

    Without this the only line a pinned run leaves is the ordinary one, which reads like a
    calibration that keeps deciding not to move: g214-g224 are eight consecutive runs asking to
    press ~19 ms later and collecting the floor's answer each time. That is a property of the
    recipe, not of the loop, and telling them apart matters to whoever reads a log mid-run.

    Two lengths because there were two readers: the panel's 运行配置 card had room for the short
    one, the log for the reason. The card is gone (the 运行策略卡 and 链路标定卡 were deleted on
    2026-10-03), so the panel now reads `pinned` -- the long one -- into the log page, which has the
    room; the short one stays because it is the long one's prefix, and `chaincal.py` PART 6 holds
    that relation and the streak floor still with a real call. Neither reader re-derives the other's
    text: the bounds and the damping are this file's policy, so a second reader of chain_cal.json
    would be a second opinion on them.
    """
    bound, wants = None, []
    for e in reversed(hist or []):
        r = _refused(e)
        if r is None or (bound is not None and r != bound):
            break
        bound = r
        wants.append(abs(float(e["est_ms"])))
    if bound is None or len(wants) < PINNED_ALARM:
        return None, None
    floor = bound == "floor"
    held = CORR_FLOOR if floor else CORR_CEIL
    # The history is a 40-run rolling window, so a streak that fills it is older than the file and
    # the count is a floor, not a total: g214-g224's eight are the tail of a run of 40+.
    brief = (f"连续 {len(wants)}{'+' if len(wants) >= len(hist) else ''} 局想再往"
             f"{'后' if floor else '前'}按 ~{CORR_DAMP * sum(wants) / len(wants):.0f} ms，"
             f"被 {held:+.0f} {'底' if floor else '顶'}板顶住")
    why = "（焚音打 L12 的 flick 按晚就落进下一颗 tap 的 96 ms credit 窗）" if floor else ""
    return brief, brief + why + " —— 这是配方的边界，不是校准器没电"


def update_chain_cal(rec, corr, tag, log, nominal=55.0):
    """Fold one finished run's delta estimate into the persisted correction (damped).

    A run that flooded is not a measurement of the chain. Off-window counts past ~2% of the
    judged objects mean the histogram is describing a failure -- a bad mid-run commit, a dock, a
    bad draw -- and its lean is that failure's own bias. g118 (110 MISS) read "+117 ms -> -10 ->
    +40" on 2026-09-30 and the very next run flooded 401 GREATs at the raised offset: one bad
    run steered the chain, which is what the damping was there to prevent. 4 of the 83 graded
    runs in the record are past the line, and the two largest are exactly that cascade.
    """
    est = estimate_delta_ms(rec)
    if est is None:
        log("chain cal: 没读 split（--read-split 关着）- correction 保持不动")
        return corr
    judged = sum(rec.get(k) or 0 for k in ("perfect", "great", "good", "bad", "miss"))
    off = rec.get("non_perfect") or 0
    if off > max(10, 0.02 * judged):
        log(f"chain cal: {off}/{judged} 判定物在窗口外（{100 * off / max(1, judged):.0f}%）"
            f"，这是故障的直方图，不是链路的钟差，correction 保持 {corr:+.0f} ms")
        return corr
    new = max(CORR_FLOOR, min(CORR_CEIL, corr + CORR_DAMP * est))
    if abs(new - corr) < 3.0:
        new = corr
    kept = None
    if rec.get("non_perfect") == 0 and est <= 0:
        # A clean run on the early side is not an error to correct. On an all-PERFECT round
        # estimate_delta_ms can only report the FAST/SLOW lean, so "est = -27 ms" here means
        # "every note was hit ~27 ms early" -- which is where this recipe wants them: early is the
        # forgiving side (a late press eats the long/trace hand-off margin, and can dock a flick
        # into the next tap's credit window), and the score that centring would win is the game's
        # 养成 deciding, not our timing -- the 63 clean rounds on file span 2.8x in score at the
        # same non_perfect 0. So the run is recorded, and nothing moves.
        kept, new = "clean", corr
    try:
        with open(CHAIN_CAL, encoding="utf-8") as f:
            hist = json.load(f).get("history", [])
    except (OSError, ValueError, TypeError):
        hist = []
    at = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = {"tag": tag, "est_ms": round(est, 1), "corr_before": round(corr, 1),
             "corr_after": round(new, 1), "at": at}
    if kept:
        entry["kept"] = kept
    hist.append(entry)
    hist = hist[-40:]
    # Written to the file as well as logged: it describes the state of the whole history, so the
    # panel can show the same sentence without owning the bounds, and it goes away on its own the
    # moment a run moves the correction.
    brief, pinned = saturation(hist)
    # Through rlog's atomic writer, not a bare open(): this file steers the *next* round's clock,
    # and a kill inside the dump would leave it unparseable -- load_chain_corr then reads corr 0
    # and fires the whole next chart 45 ms off the tuned recipe (see its comment at the top).
    write_json(CHAIN_CAL, {"corr_ms": round(new, 1), "updated": at, "pinned": pinned,
                           "pinned_brief": brief, "history": hist})
    if kept:
        log(f"chain cal: 全 PERFECT、判定偏早（{est:+.0f} ms 的早侧偏向）—— 偏早正是要的位置，"
            f"不拿去当误差修；correction 保持 {corr:+.0f} ms")
    else:
        log(f"chain cal: judged {est:+.0f} ms -> correction {corr:+.0f} -> {new:+.0f} ms "
            f"(tag {tag}; next run fires at {nominal + new:+.0f} on the nominal {nominal:+.0f})")
    if pinned:
        log(f"chain cal: {pinned}")
    return new


def _counters_up(img):
    """True while the in-song HUD counters are on screen: five rows of near-white digits.

    The song-end finale frame that a38 mistook for 演出失败 is full of them (~1.6k pixels at full
    brightness); the failure page's overlay has the HUD dimmed away.
    """
    import numpy as np

    c = img[125:250, 1060:1280]
    return int(np.count_nonzero(np.all(c > 190, axis=2))) > 300


def _moved(a, b):
    """True when more than 1% of the frame changed between two grabs: 演出失败 is a still page,
    while the finale flash animates (sparkles, the judgement word fading)."""
    import numpy as np

    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return int(np.count_nonzero(np.any(d > 8, axis=2))) > 0.01 * a.shape[0] * a.shape[1]


def _select_read(budget=5.0, step=0.35, differs=None):
    """The game's 乐曲选择 selection, once that page is up and still: {'ok', 'musicId', ...}.

    Two reads with a gap have to name the same song before the answer counts. A read taken while
    the list is still moving has named the wrong jacket at ncc 0.72, under the 0.80 gate (roll
    probe), while a landed pick settles in 0.6 s and reads 0.83-0.97; agreement is what tells a
    settled page from a mutating one. These reads are also the only signal trusted here, because
    a screencap taken in the first frames after an adb tap came back classified as 演出失败 on a
    healthy select page (2026-09-29): pixel tests judge those frames wrong, the reads do not --
    a page that is not 乐曲选择 never produces two agreeing reads at all (结算 reads 0.27).

    With `differs`, a read naming that musicId is not an answer yet: that is a press that has
    not landed, or a roll still showing the song that was on the page before it.

    None when nothing settles within `budget` seconds, which is a normal answer, not an error.
    """
    import gameread

    end = time.perf_counter() + budget
    while True:
        a = gameread.read_song_select()
        time.sleep(0.3)
        b = gameread.read_song_select()
        if a.get("ok") and b.get("ok") and a["musicId"] == b["musicId"] \
                and (differs is None or str(a["musicId"]) != differs):
            return b
        if time.perf_counter() >= end:
            return None
        time.sleep(step)


def pick_random(log=print, rolls=5, confirm=5.0, settle=0.35, roll_wait=10.0, state=None):
    """Press 随机选曲 until the game lands on a chart the local library can fire -- in order.

    The pill only answers to `adb shell input tap` (minitouch is inert on it, see mtouch.adb_tap)
    and the game's pick is the truth, so the choice is read back off the screen. The press is the
    last step of a roll, never the first: whatever the page already shows is read and evaluated
    first, because a roll that settled after an earlier call's read timed out is a decided pick,
    and pressing on top of it re-rolls a song that was already chosen. `state` (one dict per
    round, shared across the walk's retries) remembers the song on the page when this process
    first saw 乐曲选择 -- 再次演出 leaves the last round's song selected, so that one is never
    accepted without a press -- and every id already evaluated and found unusable. A press is
    followed by up to `roll_wait` s of waiting for the selection to change and come to rest,
    which is what the roulette's own animation costs; a page that stops answering stays unpressed
    and goes back to the walk ("wait"), whose own loop is built to classify whatever it finds.

    Returns {'musicId', 'title', 'diff', 'cid', 'hits', 'path'}, "wait", or None. `hits` is the
    loaded list; `path` is the file it came from, because the chart's event table (skill points,
    fever windows, tempo changes) is read off the `.raw.json` next to it -- 2026-10-07: the caller
    passed `hits` itself to `chart_events`, and every `--random` round died on the LIVE it had
    already started with `AttributeError: 'list' object has no attribute 'replace'`.
    """
    import gameread

    if state is None:
        state = {}
    sel = _select_read(confirm, settle)
    if sel is None:
        # The walk only calls here when its own pixel test says 乐曲选择, and the jacket read is
        # the semantic answer to that question. A page wearing 确定's blue pill with no readable
        # song under it is not the select page, and no amount of waiting turns it into one -- so
        # the second failure in a row stops asking it, puts the frame on disk, and ends the round
        # instead of spending the walk's whole timeout on a page that cannot answer.
        n = state["unsettled"] = state.get("unsettled", 0) + 1
        if n < 2:
            log(f"random pick: no settled 乐曲选择 page within {confirm:.0f} s - "
                f"leaving the frame to the walk")
            return "wait"
        from PIL import Image
        path = f"{subdir(FRAMES)}/random_not_select.png"
        Image.fromarray(grab()).save(path)
        log(f"!! 走查认为是 乐曲选择，但封面读取连续 {n} 次认不出选曲界面，这一页不是选曲页"
            f"，取证 {path}，本轮放弃")
        return None
    state["unsettled"] = 0
    stale = state.setdefault("stale", str(sel["musicId"]))
    rejected = state.setdefault("rejected", set())
    why = "no roll was made"
    for roll in range(1, rolls + 1):
        mid = str(sel["musicId"])
        if mid == stale or mid in rejected:
            adb_tap(*RANDOM_BTN)
            log(f"  random roll {roll}: pressed 随机选曲")
            sel = _select_read(roll_wait, settle, differs=mid)
            if sel is None:
                log(f"  random roll {roll}: the selection had not settled on a new song after "
                    f"{roll_wait:.0f} s - leaving the frame to the walk")
                return "wait"
            mid = str(sel["musicId"])
        song, d = gameread.chart_for(mid, sel["diff"])
        if d is None:
            why = (f"{mid} {(sel.get('diff') or '?').upper()} is not in the local chart library")
            rejected.add(mid)
            log(f"  random roll {roll}: rolled {why} - rolling again")
            continue
        with open(d["hits"], encoding="utf-8") as f:
            hits = json.load(f)
        log(f"random pick: {song['title']} · {d['name'].upper()} · {len(hits)} notes")
        log(f"  roll {roll} of {rolls}, ncc {sel.get('score', 0):.2f}, gap {sel.get('gap', 0):.2f}")
        return {"musicId": sel["musicId"], "title": song["title"], "diff": d["name"],
                "cid": f"{d['book']}_{d['dd']}", "hits": hits, "path": d["hits"]}
    log(f"random pick failed after {rolls} rolls: {why}")
    return None


def record_cli(args, rec, log):
    """Append the line the panel would have written, for rounds flown straight from a shell.

    Only the panel ever wrote results.jsonl, so a CLI round left no trace -- and that file is what
    tools/audit_charts.py reads to decide what has been flown, which is how 唱 EXPERT came out as
    "never played" in front of three ALL PERFECTs. Same field order as gui._record, so the panel and
    a shell round land in the log indistinguishably.

    The chart is named from what the round actually flew, not from the positional `hits`: a 多人
    round has no such argument at all (the room draws the song), so every one of them landed with
    an empty `song`/`diff` until 2026-10-08 (user m04278: 「为什么所有多人模式记录都没有歌名和难度的
    数值」). `rec` carries the chart the run path resolved -- `--multi` through the 準備页 draw --
    and falls back to `args.hits` for the single-player rounds that do pass one.
    """
    cid = str(rec.get("chart") or "") or os.path.basename(args.hits or "").removesuffix(".hits.json")
    song = diff = ""
    try:
        man = json.load(open(MANIFEST, encoding="utf-8"))
        for s in man["songs"]:
            for d in s["difficulties"]:
                if f"{d['book']}_{d['dd']}" == cid:
                    song, diff = s["title"], d["name"]
    except Exception:                                           # noqa: BLE001 - a name is optional
        pass
    out = {"ts": time.strftime("%m-%d %H:%M"), "tag": args.tag, "song": song, "diff": diff,
           "rc": 0, "chart": cid}
    out.update(rec)              # a random round names the chart it actually rolled, not this one
    append_record(RESULTS, out)
    log(f"结果已写入 {RESULTS}（与面板同格式）")


# How much of an aborted attempt's own evidence may be carried into the next attempt's clock.
# A run that breaks in the same place with the same verdict is not variance: on 2026-10-02 s291
# flew 0066_02 eight times, every attempt's votes reading +17..+26 ms ("the notes are later than
# our presses"), which the panel's 正推上限 0 refused one attempt at a time. A retry can only
# replay the clock it just failed on, so it replayed the same mistake eight times -- the loop had
# no way to learn. The compensation is derived from the field's own measurement of the attempt
# that died, bounded, per round, and never written back into the recipe or the chain calibration.
RETRY_BOOST_MS = 20.0        # the most one aborted attempt may shift the next one
RETRY_BOOST_MAX_MS = 60.0    # the most one round may shift itself in total
RETRY_VOTES_MIN = 2          # fewer votes than this is not a pattern
RETRY_HINT_MS = 15.0         # the median vote that counts as "the field asked for it"
# ... and what to do when the attempt died *before* the corrector could say anything at all.
# s303 (0051_02, 2026-10-02) is the shape: nine attempts, every one killed at chart +3.9 s -- the
# song's opening long pair -- so no attempt ever produced a vote, the compensation had nothing to
# read, and the tenth (past the cap, allowed to play on) voted +30..+43 ms for the whole song into
# a push cap of 0: 312 misses. A break that repeats at the same place is its own evidence, so each
# repeat buys one bounded experiment, and a retry is free: walk both directions by one step each
# before touching the magnitude. Tried values are remembered per place and reset when the break
# moves, so "same place again" cannot loop on the same guess twice.
PLACE_STEPS = (20.0, -20.0, 40.0, -40.0, 60.0, -60.0)


def place_boost(same_place, tries):
    """The next untried direction for a break that keeps landing in the same spot, or None."""
    if not same_place:
        return None, []
    step = next((c for c in PLACE_STEPS if c not in tries), None)
    return step, (tries + [step] if step is not None else tries)


def retry_boost(votes_ms, boost):
    """The next attempt's clock shift in ms, from the attempt that just died.

    `votes_ms` are its votes (+ = the notes were later than the presses), `boost` what earlier
    aborts already shifted; the result is what to pass as `offset - boost` next time. It converges
    rather than accumulates: each attempt re-measures the residual against the moved clock, so an
    overshoot comes back as a negative median and stops the shift, and a still-positive one takes
    another step of at most RETRY_BOOST_MS. Fewer than RETRY_VOTES_MIN votes, or a median on the
    early side, leave the clock alone -- the corrector's own -120 ms side handles those.
    """
    votes = [v for v in (votes_ms or []) if v is not None]
    if len(votes) < RETRY_VOTES_MIN:
        return boost
    med = statistics.median(votes)
    if med < RETRY_HINT_MS:
        return boost
    return min(RETRY_BOOST_MAX_MS, boost + min(med, RETRY_BOOST_MS))


def parse_kind_lead(text):
    """--kind-lead "flick=15,tap=-5" -> {kind: ms}, anything unstated at the shipped default.

    An unknown kind stops the run rather than being ignored: a typo in a number that moves every
    press of one note type is exactly the mistake that should not ride along with a whole song.
    So does a value that is not a number.
    """
    out = dict(KIND_LEAD_MS)
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        k, sep, v = part.partition("=")
        if not sep or k not in KINDS:
            raise SystemExit(f"--kind-lead 看不懂 {part!r}（种类只能是 {', '.join(KINDS)}）")
        try:
            out[k] = float(v)
        except ValueError:
            raise SystemExit(f"--kind-lead 的 {part!r} 那个数读不出来"
                             "（要像 flick=15,tap=-5）") from None
    return out


# 等结算时每这么久说一句自己还在等、上一帧是什么页（见 `wait_result`）。
WAIT_NOTE_S = 15.0

# 结算流程走到 EXP 页时最多按几下 下一步/再次演出（见 `wait_result` 的 'exp' 分支）。
EXP_TAPS_MAX = 2

# 看着像 EXP 页时先「多看几眼」的上限：每眼都问一次读数器（`_result_here`），读到分数就收下。
# 2026-10-19 用户 m43177 的现场：这几局打出 S 评级，结算页右上角徽章换了样子，`screen()` 的
# result 门（徽章框白占比 > 0.12）认不出它，判决落到 exp —— 从前这里第一眼就按 下一步，整局
# 数字没了。四眼 ≈ 6 s，比丢一局便宜得多。
EXP_LOOKS_MAX = 4


def free_memory():
    """(available, total) physical memory in MB, or None when the host will not say.

    Three rounds (g377/g378/g380) died on `MemoryError: Unable to allocate 2.64 MiB for an array
    with shape (720, 1280, 3)` -- one frame -- and the log held nothing else about it: the
    exception walked out through stderr and left an rc=1 with no explanation. The watermark at the
    top of a round is what tells a resource-starved host apart from a broken pipeline.
    """
    try:
        import ctypes

        class _MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = _MemStatus()
        st.dwLength = ctypes.sizeof(_MemStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
        return st.ullAvailPhys / 1048576.0, st.ullTotalPhys / 1048576.0
    except Exception:                                          # noqa: BLE001
        return None


def _say_result(rr, log):
    """One line of judgement counts plus the RESULT record, for every path that lands a score."""
    if "perfect" in rr:
        tot = sum(rr.get(k) or 0 for k in
                  ("perfect", "great", "good", "bad", "miss"))
        head = ("ALL PERFECT" if rr.get("all_perfect") else
                "FULL COMBO" if rr.get("full_combo") else "有漏键")
        log(f"{head}，判定 {rr['perfect']}/{tot}，combo {rr.get('combo')}，"
            f"score {rr.get('score')}，GREAT {rr.get('great')} GOOD {rr.get('good')} "
            f"BAD {rr.get('bad')} MISS {rr.get('miss')}"
            + ("，新纪录" if rr.get("new_record") else ""))
    log("RESULT " + json.dumps(rr, ensure_ascii=False))


def _result_here(img):
    """Read a score off a frame `screen()` did not call 结算 -- or say it is not one.

    The 结算 page and the EXP totals page wear the same two bottom buttons (a pale one on the
    left, the blue 再次演出/下一步 on the right), so `_exp_page` answers True on both and only
    the rank badge in the top-right corner tells them apart. When that badge renders dim the
    verdict falls through to 'exp' while the game is still sitting on the score page -- user
    m43137's report: the walk then stands there doing nothing and the log claims the result was
    missed. The score page is the only one of the two that yields numbers, so asking the reader
    is the honest test: on the pinned frames (2026-10-19) `result_g1878.png` reads 6171535 / 481
    while `mp_exp_totals_a.png` yields no score at all.
    """
    try:
        from resultread import read_array

        rr = read_array(img)
    except Exception:                                    # noqa: BLE001
        return None
    if rr.get("error") or rr.get("score") is None or "perfect" not in rr:
        return None
    return rr


def _badge_ink(img):
    """Ink fraction of the rank-badge box -- 0.35 on a 结算 page, 1.00 on the EXP totals page.

    `screen()`'s result gate reads the same box for *white*; when the badge changes shape (user
    m43177: the S rank) that number falls under the gate and the verdict lands on 'exp'. The ink
    fraction barely moves, so it is the cheap "this looks like a 结算 page" hint used only to
    decide whether a frame worth keeping should be dumped for later diagnosis.
    """
    import numpy as np

    a = np.asarray(img)[75 - 16:75 + 16, 1180 - 60:1180 + 60].reshape(-1, 3)
    return float((a.mean(1) < 120).mean())


def wait_result(tag, inj, timeout=150.0, log=print, extra=None, multi=False, read_split=False):
    """Hold until the score breakdown is up and save it, because that page is the measurement.

    `multi` only says which pages can be on screen: a solo round cannot be on the 匹配中弹窗, so a
    `matchpopup` verdict there is the 故事解锁 modal the game opens over the result page (user
    m10037, 2026-10-09) and its 关闭 is the only legal tap -- see `tools/calib.py`'s SOLO_MODAL_*.
    `read_split` is the caller's `--read-split`: this function has no access to the parsed argv, and
    reading it out of the module globals is what crashed g647/g648 (`NameError: name 'args'`).
    """
    from PIL import Image

    end = time.perf_counter() + timeout
    started = time.perf_counter()
    # 读不出数字的那份记录先留着：真正的结算页可能还在后面（多人曲终先出排名页，按了 下一步 才是
    # 单人结算流程），等到超时都没等到就把它交出去 —— 一条 error 记录总比什么都没有强。
    last_rr = None
    # 结算流程走到 EXP 页 = 结算页已经被错过了（g1880：曲终后 达成奖励列表 自己盖上来，关掉之后
    # 直接就是 EXP 总计页，150 s 全耗在这一页上，日志只剩一排「上一页 'exp'」，用户 m42830 报的
    # 就是这个）。这一页的 再次演出 / 下一步 是回 乐曲选择 的路（`calib.start_live` 的 'exp' 分支
    # 一直这么按；2026-10-08 用户确认多人也不会重新排局），所以这里按它有界、走掉了就收工。
    exp_taps = 0
    # 「看着像 exp」不算数：结算页淡入的那一帧、以及徽章不亮的结算页（2026-10-19 用户 m43177：
    # 这几局打出 S 评级，右上角徽章换了样子，`screen()` 的 result 门就认不出）都会落到这里。
    # 先连着问几眼读数器（上面那一块），真读不出分数才按 下一步 把这一局交回走查。
    exp_looks = 0
    guessed = False
    # 每 WAIT_NOTE_S 秒说一句自己还在等、上一帧是什么页：g416 在 演出结束 之后静默了 137 s
    # （下面每个分支都不命中时它只睡 1.5 s，一个字都不打），150 s 到点放弃，那一局的量测就丢了，
    # 事后完全看不出它卡在 exp、live 还是 loading 上。有了这行，下次直接读得出来。
    next_note = started + WAIT_NOTE_S
    while time.perf_counter() < end:
        img = grab()
        s = screen(img)
        if time.perf_counter() >= next_note:
            log(f"  等结算 {time.perf_counter() - started:.0f}s：上一页 {s!r}")
            next_note = time.perf_counter() + WAIT_NOTE_S
        if s == "result":
            # 一帧不是一页。mp7 的 13:19:19 是**淡入中的多人排名页**（band 还没到 rank 的门，
            # 于是被后面的 result 门接走），这里就按了 split、存了档，2 s 后抓到的已经是 rank，
            # 两张都读不出数字 —— 整局的量测定死在一条 error 记录上。所以动手之前先确认它还在。
            time.sleep(0.35)
            img = grab()
            s2 = screen(img)
            if s2 != "result":
                log(f"  结算页判决没站住（0.35 s 后是 {s2!r}）—— 不是结算页，交还给走查")
                continue
            path = f"{subdir(RESULT)}/result_{tag}.png"
            Image.fromarray(img).save(path)
            log(f"  result page -> {path}")
            # The FAST/SLOW split is a debugging instrument, not part of the workflow: reading it
            # costs a tap plus a 2 s settle and its only consumer is the chain calibration below
            # (which is inert while every round reads clean). So it is CLI-only and off by default
            # -- and it is *read*, never screenshotted: the numbers land in the record, no PNG.
            sp = None
            if read_split:
                tap(*SPLIT_TOGGLE, i=inj)
                time.sleep(2.0)
                sp = grab()
                if screen(sp) in ("rewards", "story"):
                    # The game auto-opens its reward list over the result page and the animation can
                    # land right in the split tap's window (t06's split came back as the 达成奖励列表).
                    log(f"  the {screen(sp)} modal opened over the split view - closing and retaking")
                    tap(*(MODAL_CLOSE if screen(sp) == "rewards" else STORY_CLOSE), i=inj)
                    time.sleep(1.5)
                    tap(*SPLIT_TOGGLE, i=inj)
                    time.sleep(2.0)
                    sp = grab()
            try:
                from resultread import merge, read_array, read_image

                def _one(fn):
                    try:
                        return fn()
                    except Exception as e:                        # noqa: BLE001
                        return {"error": repr(e)}

                rr = merge(_one(lambda: read_image(path)),
                           _one(lambda: read_array(sp)) if sp is not None else None)
            except Exception as e:                                # noqa: BLE001
                rr = {"error": repr(e)}
            if sp is not None:
                log(f"  FAST/SLOW split read in memory ({rr.get('views')})")
            if extra:
                # A random-mode run may only learn the chart here, and the panel's record has to
                # name the song it actually played, not the one left selected in the panel.
                rr.update(extra)
            if "error" in rr:
                # 读不出数字不等于这一局没有结算页：多人曲终先出排名页，真正的结算页要按了 下一步
                # 才来（mp7 是 13:20:12）。从前这里直接 return，把一条 error 记录当成这一局的成绩
                # 写了出去 —— 再等一等，走查会把 下一步 按下去。
                log(f"  !! 结算页读不出数字：{rr['error']} —— 再等一等，真正的结算页可能还在后面")
                last_rr = rr
                continue
            _say_result(rr, log)
            return rr
        if s == "rewards":
            # The game opens 达成奖励列表 over the result page by itself, and it hides the very
            # numbers this function exists to read. Only 关闭 is ever tapped on it.
            # 关掉之后**立刻**再看一眼（0.4 s 而不是循环末尾的 1.5 s）：g1880 就是这一眼慢了
            # ——关掉弹窗后游戏已经翻到 EXP 页，结算页那一瞬没被看见，整局没有数字。
            log("  closing the 达成奖励列表 the game opened over the result")
            tap(*MODAL_CLOSE, i=inj)
            time.sleep(0.4)
            continue
        if s == "story":
            # Same walk, same problem: 故事解锁 covers the result page, and only its 关闭 is legal.
            log("  closing the 故事解锁 the game opened over the result")
            tap(*STORY_CLOSE, i=inj)
            time.sleep(0.4)
            continue
        if s == "matchpopup" and not multi:
            # 单人局没有匹配（匹配只在激奏演出里），所以这一页不是匹配弹窗，而是同一个故事解锁
            # 弹窗 —— `_mp_matchpopup` 抢走了它、`_story_close` 对它又是 False（用户 m10037；
            # 普查与两道门见 tools/calib.py 的 SOLO_MODAL_*）。只按它的 关闭，别的什么都不按。
            log("  closing the 故事解锁 the game opened over the result")
            tap(*STORY_CLOSE, i=inj)
        if s in ("exp", "select", "other"):
            # 判决不可信的时候先问读数器：结算页与 EXP 总计页共用底下那两颗按钮（淡色在左、蓝的
            # 在右），徽章一暗 `screen()` 就把结算页叫成 exp —— 用户 m43137 的现场是「刚进入结算页
            # 就发呆什么都不点」，而日志说结算页错过了。读得出分数就按结算页收下，读不出才当它是
            # 真的 exp（`mp_exp_totals_a.png` 一个数字都读不出）。
            rr_here = _result_here(img)
            if rr_here is not None:
                path = f"{subdir(RESULT)}/result_{tag}.png"
                Image.fromarray(img).save(path)
                log(f"  这一帧被判成 {s!r}，但读得出分数 —— 按结算页收下 -> {path}")
                if extra:
                    rr_here.update(extra)
                _say_result(rr_here, log)
                return rr_here
            if not guessed and _badge_ink(img) < 0.6:
                # 读不出数字，但徽章框的墨迹像结算页（不是 EXP 总计页那种铺满的）—— 留一张现场，
                # 万一它真是结算页而我们没读懂，明天有据可查。每局最多一张。
                guessed = True
                path = f"{subdir(RESULT)}/scoreguess_{tag}.png"
                Image.fromarray(img).save(path)
                log(f"  这一帧判成 {s!r}、读不出数字，但徽章框像结算页 —— 留一张 {path}")
        if s == "exp":
            # 这一页不是「等得到的结算页」，是「结算页已经过去了」。见上面 exp_taps 的注释：
            # 按一下 下一步/再次演出 把这一局交回走查，别把 150 s 全花在「上一页 'exp'」上。
            if exp_looks < EXP_LOOKS_MAX:
                # 第一眼不算：结算页淡入的那一帧、以及右上角徽章不亮（比如这几局打出的 S 评级）
                # 的结算页都会落到这里。多等几眼、每眼都问一次读数器，读到分数就按结算页收下
                # （上面那一块）；真按错了代价是整局数字没了，多等 6 s 的代价是零。
                exp_looks += 1
                log(f"  看着像 EXP 页（第 {exp_looks} 眼）—— 先等一帧再看（结算页淡入/徽章不亮也会落到这里）")
                time.sleep(0.4)
                continue
            if exp_taps >= EXP_TAPS_MAX:
                log("  EXP 页按不走 —— 交回走查")
                return last_rr if last_rr is not None else False
            exp_taps += 1
            log(f"  结算流程已经走到 EXP 页（第 {exp_taps} 次）—— 结算页错过了，按 下一步/再次演出 交回走查")
            tap(*EXP_RETRY, i=inj)
            time.sleep(1.5)
            if screen(grab()) != "exp":
                if last_rr is not None:
                    log("  等到底也没等到能读出数字的结算页 —— 交回最后那份读不出的记录")
                    log("RESULT " + json.dumps(last_rr, ensure_ascii=False))
                    return last_rr
                log("  结算页没赶上（曲终之后直接是 EXP 页）—— 这一局没有结算数字")
                return False
        if s == "rank":
            # 多人：曲终先出排名页（五人的名次与分数，等 下一步），按下去才进单人结算流程。
            # 只按一次：这一页按一下就走，多按会落到它后面那页的按钮上。按下之后没变才补按。
            log("  多人排名页 -> 下一步")
            tap(1080, 660, i=inj)
            time.sleep(2.0)
            rank_seen = 0 if screen(grab()) != "rank" else 1
            if rank_seen:
                log("  排名页还在 —— 再按一次 下一步")
                tap(1080, 660, i=inj)
        if s == "finish":
            # The rank splash between the song and 结算 has no buttons, and it is exactly what a
            # 90-second timeout used to expire against.
            log("  tapping through the LIVE FINISH splash")
            tap(640, 400, i=inj)
        if s == "failed":
            # The song-end finale blows the field out and reads as this page for a beat: in a38
            # the live frame was saved here and 返回选曲 skipped the real score page -- the one
            # measurement the whole run exists to take. The real 演出失败 is a still menu with the
            # HUD dimmed away, so a look 1.2 s later has to still read as it, still, and with the
            # counters gone, before anything is tapped.
            time.sleep(1.2)
            img2 = grab()
            s2 = screen(img2)
            if s2 == "failed" and not _counters_up(img2) and not _moved(img, img2):
                path = f"{subdir(RESULT)}/failed_{tag}.png"
                Image.fromarray(img2).save(path)
                log(f"  演出失败 -> {path}")
                tap(924, 611, i=inj)          # 返回选曲
                return False
            log(f"  a 演出失败 look that did not hold up (now {s2!r}) - not tapping")
            continue
        time.sleep(1.5)
    if last_rr is not None:
        # 等到底也没等到能读出数字的那一页：把最后那份读不出的记录交出去（走查照常把这一局走回家，
        # 记录里带着 error 与清掉的旗子），总比什么都没有强。
        log("  等到底也没等到能读出数字的结算页 —— 交回最后那份读不出的记录")
        log("RESULT " + json.dumps(last_rr, ensure_ascii=False))
        return last_rr
    log("  no result page within the timeout")
    return False


class BreakHint:
    """The --retry-on-break trigger: the first judgement hudwatch commits ends the attempt.

    hudwatch's own contract calls its events hints -- "a tick here means go look at this frame;
    it never means the run is lost" -- and every commit has still passed its four gates. Acting
    on one is a bet: a false hint costs the rest of the song and one 重试 (free, no stamina),
    which is why the trigger is opt-in, capped per round, and the attempt that plays through is
    judged by the result page exactly as every run was before this existed. Only GREAT/GOOD/BAD/
    MISS are ever watched (hudwatch skips PERFECT), so any commit here is already a break of AP.
    """

    def __init__(self, hud):
        self.hud = hud
        self.hits = []

    def __call__(self):
        if self.hits:
            return self.hits[0]        # the decision is made; stay stable while play stops
        for lo, hi, row in list(self.hud.events):
            self.hits.append({"row": row, "lo": lo, "hi": hi})
            return self.hits[0]
        return None


def _park_attempt(tag, k, log):
    """Move an aborted attempt's artifacts aside so the replay's plain names cannot overwrite them.

    A replay writes dets_/relock_/hud_ under the same tag; without this the frames and the fired
    log of the attempt that triggered the abort -- the only evidence for judging whether the hint
    was true -- would be gone the moment the next attempt starts. `-a{k}` names them as attempt k
    of the round, matching the `!! 断AP ... 第 k/{N} 次` log line.
    """
    for name in (f"dets_{tag}.json", f"relock_dets_{tag}.json", f"relock_{tag}.json"):
        src = f"{RUNS}/{name}"
        if os.path.exists(src):
            # `[:-5]` strips ".json" only; the name here has no stem to drop (`relock_g317.json`),
            # and stripping one more character renamed it `relock_g31-a1.json` -- a tag nobody can
            # resolve back to its round.
            os.replace(src, f"{subdir(RUNS)}/{name[:-5]}-a{k}.json")
    # The HUD frames live in FRAMES, not RUNS: hudwatch writes them through `subdir(FRAMES)`, so
    # this glob never matched one. Measured on the corpus before the fix: 18 rounds with
    # `aborts > 0`, 0 frames parked -- while a replay's fresh HudWatch restarts its per-row
    # counter at 1 and therefore re-uses the same filenames, overwriting the only evidence of
    # whether the abort hint was true. That is the one thing this function exists to prevent.
    for pat in (f"hud_{tag}_*.png", f"hudreject_{tag}_*.png"):
        for src in glob.glob(f"{subdir(FRAMES)}/{pat}"):
            os.replace(src, src.replace(f"_{tag}_", f"_{tag}-a{k}_"))
    log(f"  本轮中止的取证已改名 *-a{k}（dets/relock/hud）")


def chart_identity(path):
    """(chart id, 曲名, 难度, 等级) for a hits file, from the library manifest.

    Every misfired run so far was a chart that did not belong to the field on screen (g005's EASY
    file into an EXPERT song), and the log could not show it because it never named what it was
    playing. This line is the one to compare against what the user sees on the emulator.
    """
    cid = os.path.basename(path).split(".")[0]
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            songs = json.load(f).get("songs", [])
    except (OSError, ValueError):
        return cid, "?", "?", "?"
    for s in songs:
        for d in s.get("difficulties", []):
            if f"{d.get('book')}_{d.get('dd')}" == cid:
                return cid, s.get("title", "?"), d.get("name", "?"), d.get("level", "?")
    return cid, "?", "?", "?"


def chart_events(hits_path):
    """The chart's own event table in ms -- skill points, fever windows, tempo changes.

    Read from the raw chart sitting next to the hits (the decoded upstream file) and converted with
    the compiler's own tick_to_ms, so a multi-tempo chart's events land where its notes do. Comes
    back as a sorted [(chart_ms, text), ...] for play() to log on the wall clock, plus the one-line
    summary that opens the round. ([], "") when the raw file is missing: the table is something to
    read, never a gate.
    """
    try:
        with open(hits_path.replace(".hits.json", ".raw.json"), encoding="utf-8") as f:
            ev = json.load(f)["score"]["events"]
    except (OSError, ValueError, KeyError):
        return [], ""
    bpm = ev.get("bpm") or [{"t": 0, "bpm": 120.0}]
    at = lambda t: tick_to_ms(t, bpm)                                # noqa: E731
    skills = sorted(at(t) for t in (ev.get("skill") or []))
    fever = [(at(a), at(b)) for a, b in (ev.get("fever") or [])]
    out = [(m, f"技能发动 {i}/{len(skills)}") for i, m in enumerate(skills, 1)]
    out += [(a, f"fever {i}/{len(fever)} 起（到 +{b / 1000:.1f}s）")
            for i, (a, b) in enumerate(sorted(fever), 1)]
    out += [(at(e["t"]), f"变速 → {e['bpm']:g} BPM") for e in bpm[1:]]
    bits = []
    if skills:
        bits.append("技能 %d 处（%s s）"
                    % (len(skills), "/".join(f"{m / 1000:.1f}" for m in skills)))
    if fever:
        bits.append(f"fever {len(fever)} 段")
    if len(bpm) > 1:
        bits.append(f"变速 {len(bpm) - 1} 处")
    return sorted(out), ("本局事件表：" + "、".join(bits) if bits else "")


# The `finally` in `main` walks the game home on every exit path, including the ones that give up
# (见 `leave_at_select`). Named so `recoverwalk` can turn the guarantee off and watch the difference
# -- a counterfactual built from `git show HEAD:` stops being one the moment the fix is committed.
WALK_HOME_ON_ANY_EXIT = True

# The difficulty a 多人 round plays the drawn chart at when nothing else says. The room draws the
# *song* after 匹配; the difficulty stays the player's own choice, and the 2026-10-08 answer to "what
# should it be" was "暂时默认EX". So `--diff` is the override and this is what it overrides -- a read
# of the 乐曲选择 page (`gameread.read_difficulty`, the same pills 30 px lower) still wins over it,
# because that row is what the game itself is about to use.
MULTI_DIFF_DEFAULT = "expert"


def leave_at_select(inj, log=print, timeout=90.0, multi=False):
    """Walk the game back to 乐曲選択 and say so on the machine channel.

    游戏原本停在结算页，得用户自己点出去。这一句把多轮时本来就要走的那段走到底：
    结算 →下一步→ EXP 页 →再次演出→ 乐曲選択。认出选曲页就停手，一次都不多点 ——
    在选曲页多按那一下就是又开一局。The arrival is also a machine line: it is the point the
    panel's 演出间隔 counts from, and prose about pages is not something to take a timestamp off.

    The timeout is 90 s, not 45, because a **cold-cache restart** freezes on the first visit to
    every page for a few seconds (user m54800): three pages of that is already 15 s, and the
    walk has to sit through them rather than give up on a page it never got to.

    `multi` is not decoration: on the 多人 结算 page the same 再次演出 button may re-queue a match
    instead of going home, so the walk watches that layout rather than pressing it (`calib`'s `exp`
    branch). Leaving it off here would walk a 多人 round home with the solo tap policy.

    Called on *every* way out of a round, including the ones that give up (`main`'s `finally`):
    a round that abandoned a LIVE used to leave the game wherever it stopped, so the next round
    failed at navigation too -- g274 gave up on 达成奖励列表 and g275 then died reading that page
    without playing a note, and two failures in a row stop the panel's queue.
    """
    if start_live(inj, log=log, timeout=timeout, stop_at_select=True, multi=multi):
        log("#ATSELECT#")
        return True
    log("!! 没能走回选曲页，游戏停在原处")
    return False


def parse_song(spec):
    """`100054` or `100054:hard` -> (musicId, difficulty or None), musicId as a string.

    The ids are strings everywhere the game and the manifest are read (gameread hands back what it
    decoded, the manifest stores JSON strings), and an int target never matches one -- the first
    prototype walked to a song it was already standing on and called it a failure.
    """
    import songpick                      # local: importing it reads the manifest, and --help must not

    mid, _, diff = str(spec).partition(":")
    mid = mid.strip()
    diff = diff.strip().lower() or None
    if diff is not None and diff not in songpick.DIFF_PILLS:
        raise SystemExit(f"!! --song 的难度 {diff!r} 不是 {tuple(songpick.DIFF_PILLS)} 之一")
    return mid, diff


def pick_song(spec, log=print, inj=None, state=None, confirm=5.0, settle=0.35):
    """Walk the 乐曲选择 list to the song `--song` names; same contract as pick_random.

    Returns {'musicId','title','diff','cid','hits','path'} so the caller resolves the chart exactly
    like a random pick does, "wait" to hand the page back to the walk, or None when the page is not
    the select page at all. The difference from `pick_random` is where the choice comes from: that
    one presses 随机选曲 and reads the game's answer off the screen, this one walks the list itself
    (tools/songpick.py) -- because the pill hands back a song the local library may not have, and a
    round that has to play a *particular* chart (the song the co-op room drew) cannot roll for it.

    The settled read at the end is the truth, not the walk's own target: the difficulty may have
    been changed after the song (which shifts nothing) or the game may have settled somewhere else,
    and a chart is only playable if the manifest has that musicId at that difficulty.
    """
    import gameread

    import songpick

    mid, want_diff = parse_song(spec)
    if mid not in songpick.ORDER:
        log(f"!! --song {mid} 不在 manifest 的 {len(songpick.ORDER)} 首里，连方向都定不了，本轮放弃")
        return None
    if state is None:
        state = {}
    sel = _select_read(confirm, settle)
    if sel is None:
        # Same rule as pick_random: the walk only calls here when its own pixel test says 乐曲选择,
        # and two failures in a row mean this page cannot answer -- park the frame and end the round
        # rather than spending the walk's timeout on it.
        n = state["unsettled"] = state.get("unsettled", 0) + 1
        if n < 2:
            log(f"song pick: no settled 乐曲选择 page within {confirm:.0f} s - "
                f"leaving the frame to the walk")
            return "wait"
        from PIL import Image
        path = f"{subdir(FRAMES)}/song_not_select.png"
        Image.fromarray(grab()).save(path)
        log(f"!! 走查认为是 乐曲选择，但封面读取连续 {n} 次认不出选曲界面，这一页不是选曲页"
            f"，取证 {path}，本轮放弃")
        return None
    state["unsettled"] = 0
    if not songpick.select_song(mid, inj=inj, log=log):
        # Not "wait": the walk already had a settled select page in hand and could not move off the
        # row it wanted, so another pass would spend the walk's whole timeout on the same list. The
        # game is left on 乐曲选择 with no LIVE started, and the frame says where it got stuck.
        from PIL import Image
        path = f"{subdir(FRAMES)}/song_not_reached.png"
        Image.fromarray(grab()).save(path)
        log(f"!! 没能走到 {mid}，取证 {path}，本轮放弃（游戏停在乐曲选择页，没有开打）")
        return None
    if want_diff is not None and not songpick.set_difficulty(want_diff, inj=inj, log=log):
        from PIL import Image
        path = f"{subdir(FRAMES)}/song_not_reached.png"
        Image.fromarray(grab()).save(path)
        log(f"!! {mid} 的难度没点到 {want_diff}，取证 {path}，本轮放弃（游戏停在乐曲选择页）")
        return None
    sel = _select_read(confirm, settle)
    if sel is None or str(sel["musicId"]) != mid:
        log(f"!! {mid} 选完之后页面没再读出它（读到 {(sel or {}).get('musicId', '无')}），本轮放弃")
        return None
    song, d = gameread.chart_for(mid, sel["diff"])
    if d is None:
        log(f"!! {mid} {(sel.get('diff') or '?').upper()} 不在本地谱库里，本轮放弃"
            f"（不点确定，没有开打）")
        return None
    with open(d["hits"], encoding="utf-8") as f:
        hits = json.load(f)
    log(f"song pick: {song['title']} · {d['name'].upper()} · {len(hits)} notes")
    log(f"  ncc {sel.get('score', 0):.2f}, diff {sel.get('diff')}")
    return {"musicId": mid, "title": song["title"], "diff": d["name"],
            "cid": f"{d['book']}_{d['dd']}", "hits": hits, "path": d["hits"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hits", nargs="?", default="research/archive/data/mayoiuta_ex.hits.json")
    ap.add_argument("--random", action="store_true",
                    help="pick the chart inside the run: on the 乐曲选择 page press 随机选曲, read "
                         "the game's choice off the screen and fire that chart. The positional hits "
                         "file is unused; --limit still trims whatever gets picked")
    ap.add_argument("--song", default=None, metavar="MUSIC_ID[:DIFF]",
                    help="pick the chart inside the run by walking the 乐曲选择 list to that song "
                         "(tools/songpick.py) instead of playing whatever is selected -- the game's "
                         "own list order is the manifest's, the list gestures are probabilistic, so "
                         "every drag is verified against a fresh read and a swallowed one is "
                         "retried. ':expert' also sets the difficulty. The positional hits file is "
                         "unused; --limit still trims whatever gets picked")
    ap.add_argument("--offset", type=float, default=55.0,
                    help="ms the press is moved earlier under the relock clock (fire t0 = vote - "
                         "offset/1000); +55 is the validated value (焚音打 AP x2, t22/t23). "
                         "The old -55 belonged to the pre-relock screencap+shotgun path")
    ap.add_argument("--tail-margin", type=float, default=None, metavar="MS",
                    help="ms a 长条 is held past its tail (player.TAIL_MARGIN_MS, shipped 45). "
                         "Only exists to A/B the tail margin inside one night: the link delivers "
                         "presses ~22 ms early, so 20 puts the release on the last judged object "
                         "and 45 puts it 23 ms past it. Default = whatever player.py ships.")
    ap.add_argument("--tail-flick-lead", type=float, default=None, metavar="MS",
                    help="ms EARLIER the 长条尾的滑键 swipe is played (player.TAIL_FLICK_LEAD_MS, "
                         "shipped 10). Default = whatever player.py ships; 0 restores the "
                         "pre-2026-10-19 timing, which is what an on-device A/B compares against.")
    ap.add_argument("--anchor-deadline", type=float, default=45.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--stay-on-result", action="store_true",
                    help="打完就停在结算页，不走回选曲页。默认会走完 结算 →下一步→ EXP →再次演出，"
                         "把游戏带回乐曲選択等着点下一首")
    ap.add_argument("--read-split", action="store_true",
                    help="【调试专用，仅 CLI】结算页多按一下 ⇄ 开关，把判定行读成 FAST/SLOW 两个数"
                         "（只在内存里读，不落盘），用来给跑间链路校准喂一局。默认不读：少按一次、"
                         "少等 2 s，corr 保持不动")
    ap.add_argument("--tag", default="run")
    ap.add_argument("--min-votes", type=int, default=7,
                    help="blob votes the anchor peak needs; 30 fps captures make each note count "
                         "many times over, so raising this is nearly free and guards the lock")
    ap.add_argument("--host", action="store_true",
                    help="grab the emulator window through Windows.Graphics.Capture instead of "
                         "screencap: measured 16.7 ms median (60 fps) against screencap's 257 ms, "
                         "and it keeps working when the window is covered. It is the MIDDLE tier, "
                         "not the fast one -- MuMu's own renderer SDK (--fastcap) runs at 8.4 ms a "
                         "frame -- so pass it together with --fastcap and it becomes that round's "
                         "fallback for when the SDK cannot be installed. On its own it is off by "
                         "default: a15 showed the delivery stalling for hundreds of ms through a "
                         "LIVE on a hot machine, and a stall while the anchor votes shifts every "
                         "press after it. It also fits the emulator window to a 1312x782 client "
                         "area so the surface is 1:1, and puts the window back when the "
                         "round ends (see tools/hostcap.py).")
    ap.add_argument("--fastcap", action="store_true",
                    help="MuMu's renderer SDK (~3 ms/frame, 300+ fps measured) for every frame the "
                         "anchor and probes read. screencap's 280 ms per frame with its ~46 ms "
                         "stamp jitter is why the vote's histogram peaked at 4 of 16 blobs on 焚音打 "
                         "and locked at chart +8 s; the renderer's even 3 ms cadence is what the "
                         "video replay used to predict a +1.7 s lock. The menu walk stays on "
                         "screencap -- its classifiers were tuned on those pixels -- and the source "
                         "is switched back for the result-page walk, which taps things.")
    ap.add_argument("--no-shotgun", action="store_true",
                    help="do not press the opening taps at both candidate alignments while the "
                         "vote is deciding; measure what the bare lock would have kept")
    ap.add_argument("--retry-anchor", action="store_true",
                    help="skip the intro vote: pause the LIVE it just walked into, 重试 it back "
                         "to chart t0, and fire on t0 = (确定 press) + --delta-retry. The restart "
                         "holds to ~10 ms over three retries (research/archive/media/retry_probe1.mp4), and it "
                         "is known seconds before note 1 instead of after it. Needs --fastcap and is "
                         "refused without it: press+delta is only the centre of the search -- the clock "
                         "itself comes from the relock vote, which needs faster frames than screencap")
    ap.add_argument("--delta-retry", type=float, default=0.25,
                    help="seconds from the 重试 确定 press to chart t0. 0.25 is the first guess "
                         "(t0 sat [field back up]+0.05 s in the probe, plus the button trip); "
                         "read the result page's FAST/SLOW split and nudge it between runs")
    ap.add_argument("--watch-hud", action="store_true",
                    help="stamp every judgement by watching the field HUD's PERFECT..MISS "
                         "counters on a side thread (renderer SDK, ~300 fps). The result page "
                         "totals a run but a BAD that repeats at only some candidate notes needs "
                         "its moment; the counters give it to a few ms")
    ap.add_argument("--record-counters", action="store_true",
                    help="把整局的 HUD 计数器裁片按快采节奏无损录下来（research/runs/<tag>."
                         ".counters.avi + 每帧时间戳 .jsonl）。这是 #111「一根长条贡献几个判定物」"
                         "唯一缺的输入：读数器现成，缺的是逐帧的像素。写手在自己的线程上"
                         "（FFV1 90x120 ≈ 0.73 ms/帧），采样线程只入队；队列满了丢帧并记数。"
                         "需要 --watch-hud 与 --fastcap")
    ap.add_argument("--retry-on-break", nargs="?", type=int, const=3, default=0, metavar="N",
                    help="断AP立即重试: the moment the HUD watcher commits a non-PERFECT "
                         "judgement, stop the attempt, 重试 it back to t=0 in place and fire "
                         "again -- up to N aborts per round (bare flag = 3, 0 = off). Needs "
                         "--watch-hud and --retry-anchor. The attempt that plays through is "
                         "judged by the result page as always, so a false hint (the watcher has "
                         "a false-positive history) costs one free restart at worst")
    ap.add_argument("--field-delta", type=float, default=FIELD_TO_AUDIO,
                    help="seconds from the restarted field stamp (magenta lines back) to chart t0. "
                         "The last-resort play clock when the relock vote cannot lock on any "
                         "attempt (唱 opens with long notes the blob mask cannot see, so its vote "
                         "window is structurally empty): t0 = t_field + this, instead of aborting")
    ap.add_argument("--live-push-cap", type=float, default=LIVE_PUSH_MS,
                     help="ms the mid-song re-anchor may move the not-yet-fired presses LATER at "
                         "most; the earlier side keeps its -120 ms clamp. The corpus cut that "
                         "separates cleanly is the sign (at 0056_03's 626 object, 17 runs at <= 0 ms "
                         "broke it 0 times and 60 above 0 broke it 13), so 10 is a sliver kept for "
                         "genuinely late charts: 0 reproduces the sign cut, 120 removes the bound")
    ap.add_argument("--mem-guard", action=argparse.BooleanOptionalAction, default=True,
                    help="一局开工前看一眼宿主内存：可用低于 6 GB 先清缓存后台（am kill-all + "
                         "pm trim-caches）、低于 3 GB 再让游戏回收自己的堆，低到 1.5 GB 才重开游戏"
                         "（多人局不重开 —— 那就等于退房间）。只在开工前跑，曲子里绝不动手；"
                         "--no-mem-guard 关掉")
    ap.add_argument("--kind-lead", default="",
                    help="per-kind offset in ms, as 'flick=15,tap=-5' (the panel's settings "
                         "page exposes this as 「种类偏移」). Each kind is pressed earlier than "
                         "the shared clock; anything unstated keeps the shipped default ("
                         + ", ".join(f"{k}={v:g}" for k, v in KIND_LEAD_MS.items()) + ") -- all "
                         "zero is the recipe every flown result was played on. A kind's whole "
                         "sequence moves together (head, every step, tail).")
    ap.add_argument("--min-fire", type=int, default=0, metavar="N",
                    help="加成火力 gate before LIVE START on 乐队确认, as a 消耗LB tier threshold: "
                         "a clean readout >= N sets tier 3 (spend 3, reward x15), below N sets tier 0 "
                         "(spend nothing) -- and the walk starts either way, no waiting (用户 m26442). "
                         "0 disables it and leaves 消耗LB alone. A readout that does not read is "
                         "played through without touching 消耗LB, not waited on")
    ap.add_argument("--multi", action="store_true",
                    help="多人（激奏演出）链路：入口换成 演出首页右方 激奏演出，乐队确认页按 自由对战，"
                         "并处理 匹配中弹窗 / 匹配页 / 准备页（按一次 准备）/ 曲终的排名页。"
                         "这一局打哪张谱由房间抽签决定，只有在准备页上才看得出来（gameread.read_prep），"
                         "所以 --song/--random 在多人里只是「我推荐的那首」，位置参数 hits 用不上；"
                         f"难度按 --diff > 乐曲选择页上读到的 > {MULTI_DIFF_DEFAULT} 的顺序定。"
                         "多人不消耗物资；路上不碰 购买、不碰 达成奖励。")
    ap.add_argument("--diff", default=None, metavar="DIFF",
                    choices=("easy", "normal", "hard", "expert"),
                    help="多人局指定这一局的难度（在 乐曲选择页上会去点它）；不给就用页面上读到的"
                         f"那个，读不到就用 {MULTI_DIFF_DEFAULT}。单人局的难度写在 --song 的 :难度"
                         "后缀里，不用这个参数")
    ap.add_argument("--walk-home", action="store_true",
                    help="只把游戏走回 楽曲選択 就退出、不开局。夜间看门狗救场用：它重开游戏之后"
                         "由这一条走回来；这条路对「开打」按钮只观望（run.leave_at_select）")
    args = ap.parse_args()
    # 路径集中校验放在最前面：adb 与 minitouch 是每一局都用的，缺了它们这一局会在第三分钟
    # 才以「走页停住」的样子失败。`tools/locate.py` 把五个写死的路径收在一处并留了环境变量
    # （HYOUSHI_ADB / HYOUSHI_MINITOUCH / …，旧的 BANG_ 前缀同样认），换机器只改环境、不改代码。
    if not locate.check(("adb", "minitouch"), log=print):
        return 1
    if args.walk_home:
        # 夜间看门狗的第二步（用户 m28899 的第 ③ 条）：游戏被重开之后，走回 楽曲選択 就退出。
        # 复用 `leave_at_select`：它只按返回/关闭，对「开打」按钮只观望，不会替用户开局。
        inj = MTouch(log=print)
        ok = leave_at_select(inj, log=print, timeout=90.0, multi=args.multi)
        print("走回乐曲選択：成功" if ok else "!! 走回乐曲選択失败", flush=True)
        return 0 if ok else 1
    if args.fastcap and locate.missing(("mumucap_dll",)):
        # 快采的 SDK 装不上时本来就自动落到窗口/adb 抓帧（见 --host 的 help），所以这里只提示
        # 一次、不拦：真正拦下来会让「SDK 没装但能用」的机器白丢一局。
        print(f"  快采：找不到 {locate.DLL_PATH}，本局自动落到窗口/adb 抓帧"
              f"（要指到别处就设 HYOUSHI_MUMUCAP_DLL 或 HYOUSHI_MUMU_ROOT）", flush=True)
    kind_lead = parse_kind_lead(args.kind_lead)
    if args.tail_margin is not None:
        # player.TAIL_MARGIN_MS is read at call time by build_actions() and by the intro shotgun, so
        # setting the module global here is enough -- play() needs no new parameter. The switch is
        # here to A/B the margin inside one night (see --tail-margin); the shipped value lives in
        # player.py and this only overrides it for the round that asked.
        player.TAIL_MARGIN_MS = float(args.tail_margin)
    if args.tail_flick_lead is not None:
        # Same shape as --tail-margin: build_actions() reads the module global at call time, so the
        # override needs no new parameter. The switch exists so the shipped tail-flick lead can be
        # A/B'd against 0 on the device without editing player.py between the two arms.
        player.TAIL_FLICK_LEAD_MS = float(args.tail_flick_lead)
    # `--retry-anchor` without `--fastcap` is a clock nobody should play a round on, so it is refused
    # rather than logged. The anchor's press+delta constant is exactly the thing that wandered
    # +95/+118 ms run to run (t14/t15 -- 995 GOOD on a chart that APs all morning), and the only
    # instrument that measures the truth is the relock vote, which needs better than screencap's
    # 280 ms a frame: a 2.2 s window holds ~8 of them, not the ~30 blob samples the lock is built
    # on. Until now the run printed "relock skipped" and played on the stale constant anyway. The
    # panel ships the two flags together, so this only bites a hand-written command line -- and
    # quietly installing the renderer here would be the same silent choice in the other direction.
    if args.retry_anchor and not args.fastcap:
        print("!! --retry-anchor 需要 --fastcap：重锁投票要快帧，只有 screencap 时锚点会退回"
              " 確定+0.25 s 那个常数（实测按局漂 +95…+118 ms），那是坏钟。本局不开始。", flush=True)
        return 1
    if args.diff is not None and not args.multi:
        # In single-player the difficulty is part of the 乐曲选择 pick (`--song 100056:hard`) and the
        # page's own read is what the chart is resolved against. 多人 is the one flow that has to be
        # told separately: there the 乐曲选择 page is read for the difficulty it shows (the same pill
        # row, 30 px lower) and this flag is the override for a read that comes back wrong.
        print("!! --diff 只给多人局用：单人局的难度写在 --song 的 :难度 后缀里。本局不开始。",
              flush=True)
        return 1
    if args.multi and not args.fastcap and args.diff is None:
        # Not a refusal, unlike the two guards around it: a 多人 round now has a difficulty to fall
        # back on (`MULTI_DIFF_DEFAULT`), so the missing SDK frames cost a page read, not the round.
        # Said once, before the walk, because the difference shows up two minutes later otherwise.
        print(f"  多人：没有 --fastcap，读不到 乐曲选择 页上的难度，本局按 {MULTI_DIFF_DEFAULT} 打"
              f"（要别的难度就给 --diff <easy|normal|hard|expert>）", flush=True)
    if args.record_counters and not (args.watch_hud and args.fastcap):
        # Same rule as above: a flag whose meaning depends on another one refuses rather than
        # silently recording something else. The sink is the watcher's frame stream, and the
        # cadence claim ("full rate") is fastcap's 9 ms; screencap's 278 ms would make the file a
        # slideshow that still reads like a recording.
        print("!! --record-counters 需要 --watch-hud 与 --fastcap：录的是看盘线程手上的帧，"
              "而「满帧率」以快采为准。本局不开始。", flush=True)
        return 1
    if args.random and args.song:
        # Both flags pick the chart inside the run, and the walk presses 确定 exactly once: the
        # second one to run would only overwrite what the first one chose. Refuse rather than
        # silently honouring one of them.
        print("!! --random 与 --song 都在乐曲选择页决定谱面，只能给一个。本局不开始。", flush=True)
        return 1

    raise_timer_resolution()
    # A tag is the name of this round's evidence (dets / relock / result / split / detail). Handing
    # run.py a tag that was already used silently overwrote the earlier round's pictures -- which is
    # how a diagnostic harness that read a number out of gui_state.json without reserving it lost a
    # flown round's screenshots (2026-10-03). The panel increments its own counter, so this only
    # ever fires on a hand-written --tag. Checked before RunLog exists: writing the refusal into
    # `<tag>.detail.log` would itself overwrite the round we are protecting.
    if os.path.exists(RESULTS):
        with open(RESULTS, encoding="utf-8") as fh:
            for ln in fh:
                try:
                    used = json.loads(ln).get("tag")
                except ValueError:
                    continue
                if used == args.tag:
                    print(f"!! 编号 {args.tag} 已经在 results.jsonl 里，本局不开始：它会覆盖那一局的"
                          f"证据。换一个 --tag（面板用的号在 gui_state.json 的 next_index）", flush=True)
                    return 1
    log = RunLog(args.tag)
    if args.retry_on_break and args.multi:
        # 房间局没有「把这一首从头再打一遍」这个动作：中途重开要暂停 LIVE、按暂停面板的 重试、
        # 再按确定（`calib.restart_to_t0`），那是单人 LIVE 的界面；在房间里它要么走不通、要么
        # 把这一轮直接作废（下面 `_to_t0` 走不出去就 `return 1`）。2026-10-10 用户 m12749 问
        # 出来的 —— 面板那两层（`flet_gui` 不发、`panel_core._spawn_run` 不发）已经不放行，
        # 这一层兜 CLI。
        log("--retry-on-break 在 --multi 下不生效（房间局不能把同一首从头再打，中途重开会把"
            "这一轮作废），本局按关闭处理")
        args.retry_on_break = 0
    if args.retry_on_break and not (args.watch_hud and args.retry_anchor):
        log("--retry-on-break 需要 --watch-hud 与 --retry-anchor（断点来自 HUD，重开走重试锚定），"
            "本局按关闭处理")
        args.retry_on_break = 0
    hit_pick = {}
    fly_cid = None                 # the chart whose bytes this round fires; random learns it late
    # Every flow that decides the chart *inside* the run: --random and --song at the 乐曲选择 page,
    # and --multi later still, at the 準備页 (the room's draw is only shown there). All three leave
    # the positional hits argument unused and hand the chart back through `hit_pick`.
    pick_mode = args.random or args.song or args.multi
    if pick_mode:
        if args.hits:
            log("--random/--song/--multi 在走查里自己决定谱面，位置参数给的 hits 用不上")
        all_hits = hits = None        # decided inside the walk
    else:
        all_hits = json.load(open(args.hits, encoding="utf-8"))
        hits = all_hits[: args.limit] if args.limit else all_hits
        cid, title, diff, level = chart_identity(args.hits)
        fly_cid = cid
        log(f"谱面 {cid} {title} {diff.upper()} Lv{level}，共 {len(all_hits)} 音符"
            + (f"，本局只打前 {len(hits)}" if args.limit else ""))
        log.song_len = max(h["t_ms"] for h in all_hits) / 1000.0

    corr, _cal = load_chain_corr()
    eff_offset = args.offset + corr
    if any(v for v in kind_lead.values()):
        # Said at the top as well as in the fire loop: whoever reads a log needs to see this before
        # deciding whether a round is comparable with the pinned ones, and the top line is what the
        # panel's live view shows first.
        log("种类偏移: " + " ".join(f"{k}{v:+g}ms" for k, v in sorted(kind_lead.items()) if v)
            + "（整段一起移，头/每一步/尾；全零才是钉子上那份配方）")
    if args.tail_margin is not None:
        # The one line that makes two arms of a tail-margin A/B comparable after the fact: the same
        # chart, the same offset, two different 长条 hold times.
        log(f"尾判留白: {player.TAIL_MARGIN_MS:.0f} ms（--tail-margin 覆盖，默认 {TAIL_MARGIN_DEFAULT:.0f}）")
    if args.tail_flick_lead is not None:
        # Same reason as the margin line: two arms of a tail-flick A/B must be readable from the log
        # alone, and the shipped value is the one every pinned round was played with.
        log(f"尾判滑键提前: {player.TAIL_FLICK_LEAD_MS:.0f} ms"
            f"（--tail-flick-lead 覆盖，默认 {TAIL_FLICK_LEAD_DEFAULT:.0f}）")
    free = free_memory()
    if free is not None:
        log(f"空闲物理内存 {free[0] / 1024:.1f} GB / {free[1] / 1024:.1f} GB"
            + ("（不足 2 GB：这一局很可能连帧都抢不到）" if free[0] < 2048 else ""))
    if args.mem_guard:
        # 长跑之后可用内存一路往下走（2140 局的读数：0.3–0.8 GB / 10 局，最长那趟 17.2 h /
        # 209 局 15.9 → 8.2 GB），紧到连一帧都抢不到时 g377/g378/g380 直接 MemoryError。
        # 只在这一局开工前动手；多人局不开「重开游戏」那一档 —— 那等于把房间丢掉。
        try:
            memguard.guard(log=log, restart=(not args.multi), walk=True)
        except Exception as e:                                  # noqa: BLE001
            log(f"  内存：回收没跑完（不影响这一局）：{e!r}")
    if args.min_fire > 0:
        # 用户 m26442（2026-10-11）：这扇门不再「等够」，而是把 消耗LB 拨到该去的那一档 ——
        # ≥N 拨 3 档、<N 拨 0 档，然后照常开打（时长因此不再被等火力拖长）。
        log(f"火力门：≥{args.min_fire} 点就把 消耗LB 拨 3 档、不足就拨 0 档，然后照常开打"
            + "（不再等待；读数读不出则不动 消耗LB、直接开打）")
    if corr:
        log(f"chain cal: {corr:+.0f} ms on file ({_cal.get('updated', '?')}) - "
            f"effective offset {eff_offset:.0f} ms (nominal {args.offset:+.0f})")
    hc = None
    # `--host` installs Windows.Graphics.Capture, but NOT here when `--fastcap` is also given:
    # installing it fits the emulator window to a 1312x782 client area (that is what makes the
    # surface 1:1), and there is no reason to resize the user's window for a round that is going to
    # read MuMu's own renderer anyway. It is installed below, in the branch where the SDK failed --
    # which is the case it is for.
    if args.host and not args.fastcap:
        import hostcap

        hc = hostcap.install(log=log)
    inj = MTouch(log=log)
    # Set once the round has walked the game back to 乐曲選択 on its own way out; until then the
    # `finally` below owns that walk (see `leave_at_select`). `rec` is the counter recorder, also
    # owned by the `finally` -- both are bound here so an early exit can still see them.
    left = False
    counter_rec = None

    pick_state = {}
    multi_sel = {}                 # 多人：乐曲选择页上读到的难度（打哪首由准备页的抽签决定）

    def on_select():
        """The 乐曲选择 page, for all three in-run pick flows (多人 has its own, below).

        `--random` presses 随机选曲 and reads the game's pick back; `--song` walks the list to the
        named song. Both hand back the chart the local library will fire, which is what a
        single-player round plays.
        """
        if args.multi:
            return on_select_multi()
        p = (pick_song(args.song, log=log, inj=inj, state=pick_state) if args.song
             else pick_random(log=log, state=pick_state))
        if p == "wait":
            return "wait"      # not a page to pick on; hand it back and let the walk keep reading
        if p is None:
            return False
        hit_pick.update(p)
        return True

    def on_select_multi():
        """多人 乐曲选择页: settle the *difficulty*, not the chart.

        The room draws the chart after 匹配 and the draw is only visible on the 準備页, so this page
        cannot name it. What it does name is the difficulty -- the same four pills, 30 px lower
        (gameread.DIFF_BANDS), which is the row `songpick.set_difficulty` now clicks -- and that is
        what the drawn chart gets resolved against. `--song`/`--random` still walk the page (the
        nominated song is one of the room's draw candidates), they just do not decide anything.

        Three ways to learn the difficulty, in that order: `--diff` says it outright; the page's own
        read says it (that needs frames -- see `--fastcap`); and if neither does, the round plays
        `MULTI_DIFF_DEFAULT` rather than stopping on a page that will not answer.

        A page that turns out to be the *single-player* 乐曲選択 (the room dissolved) is not played:
        the walk presses the top-left back arrow back to 演出首页 and re-enters a room (m04029).
        """
        import gameread

        import songpick

        want = args.diff               # the command line beats the page, the page beats the default
        if args.song or args.random:
            p = (pick_song(args.song, log=log, inj=inj, state=pick_state) if args.song
                 else pick_random(log=log, state=pick_state))
            if p == "wait":
                return "wait"
            if p is None:
                return False
            # The nominated song's own `:难度` is a difficulty the user stated, so it outranks the
            # default -- but only when nothing more direct was said.
            multi_sel["diff"] = want or p["diff"] or MULTI_DIFF_DEFAULT
            multi_sel["mine"] = p["musicId"]
            log(f"  多人：我推荐 {p['musicId']}（{p['diff']}）—— 打哪首由房间抽签决定")
            return True
        # The band alone, not `read_song_select`: the room draws the song, so all this page owes
        # the round is which band the lit pill sits in (solo row 527 / 多人 row 557) and the
        # difficulty name. `read_song_select` would first demand the jacket library and a matched
        # cover, and a page whose cover is scrolled out of its box would then go unread and the
        # walk would press 決定 on a page it had not identified -- the 2026-10-08 16:03 solo
        # performance. `read_band` goes through `detect.grab`, so it also reads on a round with no
        # `--fastcap` (user m04278 asked for that hole to be closed).
        got = gameread.read_band()
        if not got.get("ok"):
            # A page that will not answer at all is not worth stopping the round over: the walk is
            # about to leave it. `--diff` already settles the difficulty; without it, three
            # failures in a row mean the pixels are not coming (a dead capture, or this is not the
            # select page) and the round goes on at the default.
            n = multi_sel["unsettled"] = multi_sel.get("unsettled", 0) + 1
            log(f"  多人：乐曲选择页读不出难度（{got.get('why')}）")
            if want is not None:
                multi_sel["diff"] = want
                return True
            if n < 3:
                return "wait"
            multi_sel["diff"] = MULTI_DIFF_DEFAULT
            log(f"  多人：按默认难度 {MULTI_DIFF_DEFAULT} 打（要别的难度就给 --diff）")
            return True
        multi_sel["unsettled"] = 0
        # A 多人 room can dissolve between rounds: the other four leave, and the game drops back to
        # the *single-player* 乐曲选择 page. Both pages carry the same jacket and the same four
        # pills, and (1155,638) is 決定 on both, so the walk pressed it and started a solo
        # performance -- on 2026-10-08 16:03 that is exactly what happened (user: 「你在单人模式
        # 干什么」). What tells the two pages apart is which band the lit pill sits in: the solo
        # page's band starts at DIFF_BAND[0] (row 527), the 多人 one DIFF_SHIFT (30 px) lower (row
        # 557) -- measured over the whole corpus (navgates PART 15 pins both).
        #
        # The way out is the same top-left back arrow the 乐队确认页 uses (BAND_BACK, user m02645):
        # it returns to 演出首页, and from there the walk presses 激奏演出 and re-enters a room --
        # which is exactly what the user asked for (m04029: 「误入单人选曲页应该点左上角的返回按钮
        # 回到演出首页重新选择多人模式」). Measured on the real page 2026-10-08 16:20: with `tap`'s
        # default 0.12 s hold that arrow ignored the press, with SELECT_BACK_HOLD (0.30 s) the page
        # was 演出首页 1.2 s later. The walk is handed "wait" so that *it* re-reads the page -- it
        # must never press 決定 on a page it has not identified. Bounded by SELECT_BACK_TRIES:
        # after that the round stops instead of pressing anything else.
        row = got.get("row")
        if row is not None and row != gameread.DIFF_BANDS[1]:
            n = multi_sel["solo_back"] = multi_sel.get("solo_back", 0) + 1
            if n > SELECT_BACK_TRIES:
                log(f"  !! 乐曲选择页还是单人那一版（难度带 row {row}，多人是 "
                    f"{gameread.DIFF_BANDS[1]}）—— 左上角的返回箭头按了 {n - 1} 次都没回演出首页。"
                    f"本局不开始。")
                return False
            log(f"  多人：乐曲选择页是单人那一版（难度带 row {row}，多人是 "
                f"{gameread.DIFF_BANDS[1]}）—— 房间散了。按左上角的返回箭头回演出首页"
                f"（第 {n} 次）")
            tap(*SELECT_BACK, i=inj, hold=SELECT_BACK_HOLD)
            time.sleep(SELECT_BACK_SETTLE)
            return "wait"
        diff = got["diff"]
        if want is not None and want != diff:
            log(f"  多人：乐曲选择页是 {diff}，本局要 {want} —— 去点它")
            if songpick.set_difficulty(want, inj=inj, log=log):
                diff = want
            else:
                log(f"  !! 难度没点成 {want}，就按页面上的 {diff} 打（点错了整首都会崩）")
        multi_sel["diff"] = diff
        bx = got.get("block") or (0, 0)
        log(f"  多人：本局难度 {diff}（乐曲选择页读出 {got['diff']}，亮块 {bx[0]}..{bx[1]}，"
            f"难度带 row {row}）")
        return True

    def on_prep(got):
        """準備页: the room's draw is finally named here, and that is the chart this round fires.

        Called once by `calib.start_live` with what `gameread.read_prep` read off the page. If the
        chart cannot be resolved the round still walks into the LIVE -- the no-pick branch below
        restarts it, lets it run out unpressed and records rc=1, which is what a 多人 room needs
        anyway (leaving early would strand the other four players).
        """
        import gameread

        if not got.get("ok"):
            return
        mid = str(got["musicId"])
        diff = multi_sel.get("diff") or args.diff or MULTI_DIFF_DEFAULT
        song, d = gameread.chart_for(mid, diff)
        if d is None:
            log(f"  !! 抽中的 {mid} 没有 {diff} 的本地谱面，本局打不了")
            return
        with open(d["hits"], encoding="utf-8") as f:
            hits = json.load(f)
        hit_pick.update({"musicId": mid, "title": song["title"], "diff": d["name"],
                         "cid": f"{d['book']}_{d['dd']}", "hits": hits, "path": d["hits"]})
        log(f"  多人：抽中 {song['title']} · {d['name'].upper()} · {len(hits)} 音符"
            f"（ncc {got['score']:.3f}，次高差 {got['gap']:.3f}）")

    def use_fast_capture():
        """Point every read at MuMu's own renderer instead of `adb screencap`: 9 ms against 278 ms.

        This used to be installed only for the song, with both walks left on screencap because the
        result-page branches were "only ever validated on screencap pixels". That objection is
        answered: nemu_capture_display and screencap hand back the same picture, pixel for pixel
        (they were 4 columns apart until MuMu 15 shifted the two paths together, and
        mumucap.register() is therefore the identity), and tools/probes/capreg.py holds both facts
        down -- the two sources agree to within the fast source's own frame-to-frame noise, and of
        the 39 committed nav frames none changes page under the edge smear a live frame carries,
        while one (navgates_pause_a.png) changes page under the 4 columns the old correction used
        to add, which is why the correction is gone rather than guessed at.
        """
        nonlocal hc
        if not args.fastcap:
            return
        import detect
        import mumucap

        try:
            mumucap.install()
        except Exception as exc:                                     # noqa: BLE001
            # The DLL is an external component: a MuMu update or a second instance holding the
            # handle can make it fail, and that must not stop a round. The vote will say so by
            # locking late -- but the walk still works.
            #
            # `--host` is installed HERE rather than at the top of the round for exactly this
            # branch: the SDK was tried first, and the window capture is what a round falls back to
            # (16.7 ms a frame) when the SDK cannot be installed. `detect.SOURCE` is left alone
            # when `install()` returns None, so a failure here still lands on screencap.
            if args.host:
                import hostcap

                hc = hostcap.install(log=log)
                if hc is not None:
                    log(f"!! 快采不可用（{exc!r}），本局改用 --host 的窗口抓帧（16.7 ms/帧）")
                    return
            log(f"!! 快采不可用（{exc!r}），整局回落到 screencap（257 ms/帧，投票会锁得晚）")
            return
        detect.SOURCE = mumucap.source
        log(f"fast capture: {mumucap.frame()[0]:.3f} first frame")

    try:
        use_fast_capture()
        if not start_live(inj, log=log, on_select=on_select if pick_mode else None,
                          min_fire=args.min_fire, multi=args.multi,
                          on_prep=on_prep if args.multi else None):
            log("could not reach a LIVE"
                + (" (no random pick was confirmed)" if args.random else "")
                + (f" (--song {args.song} 没能选到)" if args.song else "")
                + (" (多人：没能走到 LIVE)" if args.multi else ""))
            return 1
        if pick_mode:
            if not hit_pick:
                # The walk can reach a LIVE with no pick at all when nothing on the way was a
                # select page (the game left on 难度选择 by an earlier round) -- typically a round
                # that was killed mid-flight. 2026-10-02: s291 was cut off by a batch timeout, the
                # live stayed up, and s292-s295 all spun on it, four rounds lost to a state a
                # human had to click away. The live is not ours to play (no chart is named for
                # what is on screen), but it is ours to clear: 重试 it back to t=0 with the
                # validated two taps, let it run out unpressed, and leave the result page to the
                # next round's walk.
                log("reached a LIVE without a chart"
                    + (" (多人：准备页上没读出抽中的曲子)" if args.multi
                       else " (no random pick was confirmed)")
                    + " - restarting it and waiting it out")
                if args.multi:
                    # 房间里的 LIVE 没有暂停按钮（2026-10-10 用户 m13106）：重开与暂停都按不到，
                    # 唯一的做法是停止注入、让它自己跑到结算页，下一轮的走查从那里接管。
                    log("  多人局没有暂停按钮：不重开、不按暂停，停止注入让它自己跑完")
                else:
                    t_ok = restart_to_t0(inj, log=log)
                    if t_ok is None:
                        log("  连重试都走不通，只能把它暂停后放弃")
                        pause_if_live(inj, log)
                        return 1
                    log(f"  已重开（{t_ok:.3f}）；让它空跑完再走：这一局没有结果，记 rc=1")
                for _ in range(60):                     # up to ~3 minutes, then hand it over
                    time.sleep(3)
                    if page() != "live":
                        break
                log(f"  空跑结束，屏幕上读到 {page()!r}；下一轮走查从这里接管")
                return 1
            all_hits = hit_pick["hits"]
            hits = all_hits[: args.limit] if args.limit else all_hits
            log.song_len = max(h["t_ms"] for h in all_hits) / 1000.0
        # What the chart itself schedules -- skill points, fever windows, tempo changes -- for the
        # fire loop to say out loud when they arrive. The user asked for the skill line by name;
        # the other two ride along because they are the same table and the log is where they are
        # read against breaks.
        # `--random`'s pick hands back both the loaded list and the file it came from, and this
        # table is read off the `.raw.json` sitting next to that file -- so the path is what goes
        # in, never the list. See pick_random's docstring for what passing the list cost.
        hits_path = hit_pick["path"] if pick_mode else args.hits
        events, ev_summary = chart_events(hits_path)
        if ev_summary:
            log("  " + ev_summary)
        # The fast capture was already installed before the walk in (use_fast_capture), so the
        # field stamp below and every page read on the way share one 9 ms source.
        # The number to compare against the vote's t0: it says how long the game takes from
        # drawing the field to starting the audio, which is the one latency no vision method can
        # see coming and the reason the opening notes are the hard part. Stamped off a live frame
        # rather than the wall clock, because the whole point is to tighten this bound.
        if args.multi:
            # 多人房间在开场前会先把场地画一次，再盖上「等待其他玩家」的黑罩（mp2 实测 4.4 s），
            # 而走查只认第一帧 live 就返回 —— 撞上黑罩前那一帧，t0 就早近 5 s，锚定窗口落在罩子上。
            # 所以多人的开场章要等判定线连续画着才盖（见 calib.field_back_up）；单人那一下不碰。
            field_seen = field_back_up(log=log)
        else:
            field_seen = frames()[0]
        log(f"LIVE field at host {field_seen:.3f}")
        def _to_t0(replay, offset_now):
            """Put the live in front of us back to a playable t0; return (t0_fixed, relocked).

            The same move opens every round and re-opens one after a break: 重试 the live (the
            startup walked into one, the abort left one running), then let the falling notes,
            not the press timestamp, name the clock. A replay that cannot even restart has no
            intro left to fall back to either -- returning None ends the round instead.

            多人的房间 LIVE 没有暂停按钮（见下面那段注释），所以 `args.multi` 一律不走这条路。
            """
            t0_fixed, relocked = None, False
            notes = [(h["t_ms"] / 1000.0, h["lane"]) for h in all_hits]
            # 多人房间里的 LIVE **没有暂停按钮**（2026-10-10 用户 m13106 口述：匹配完毕那一刻
            # 唯一的提前退出就是关掉游戏进程，否则必须打到 LIVE 结束、结算完毕）。所以
            # 「暂停 → 重试 → 确定」这条重开在房间里根本按不到 —— 从前每一局都要往右上角
            # (1247,38) 空按两下、白等两秒，再落到开场投票。这里直接落到开场投票，一个字节都
            # 不往房间里发。单人那一半一字不动（单人开局就是靠这次重开把时钟钉死的）。
            if args.multi:
                if replay:
                    log("  多人局没有暂停按钮，中途重开走不出去 —— 本局放弃，停止注入让它自己跑完")
                    return None
                log("  多人局：房间里的 LIVE 没有暂停按钮，不做重开，直接走开场投票")
                return None, False
            # One restart is not always enough to lock: t15's intro feed reached its eighth
            # blob sample only at +1.8 s, one answer fitted before the deadline, and the run
            # then played a clock ~95 ms stale into 995 GOODs. Restarting is free (no
            # stamina), so a failed lock buys another whole restart; three failures in a row
            # mean something is wrong, and aborting beats playing on a clock that by then is
            # known to be the thing that wanders.
            attempts = 3            # the entry guard makes `--retry-anchor` imply `--fastcap`
            for attempt in range(1, attempts + 1):
                if replay:
                    # t92: the device-side daemon died inside an abort's restart cycle, the
                    # rebuild surfaced only in play's opening probe, and its ~2 s bill landed
                    # inside the [確定 -> note 1] budget -- two attempts were born late and
                    # wasted. Probing out here pays any rebuild before 確定, where no note
                    # clock is running and a second 重试 is still free.
                    r0 = inj.respawns
                    inj.probe()
                    if inj.respawns > r0:
                        log(f"  重开前通道探活：注入通道重建了一次（respawns {inj.respawns}）")
                t_ok = restart_to_t0(inj, log=log)
                if t_ok is None and replay:
                    # The frame a mid-song abort lands on is whatever the last hit left behind,
                    # and 'live' is a strict magenta test that dips mid-pulse -- or under a
                    # trace's sweep: 0056_03's +70.9 s break read as 'options' and stranded the
                    # first abort. The field is up ~always this deep into a song, so the pause
                    # gets patient re-reads (~ms each on fastcap) before the round is written off.
                    for recheck in range(1, 9):
                        time.sleep(0.4)
                        st = page()
                        if st not in ("live", "pause", "confirm"):
                            continue
                        t_ok = restart_to_t0(inj, log=log)
                        if t_ok is not None:
                            log(f"  重开在读 {recheck} 次后走通（读到 {st!r}）")
                            break
                        log(f"  重开重读 {recheck}/8：读到 {st!r} 但没走通")
                if t_ok is None:
                    if replay:
                        log("  中途重开走不出去，暂停与重试都没成，本局放弃，下一轮走查接管")
                        return None
                    log("  restart anchor failed - falling back to the intro vote")
                    return t0_fixed, relocked
                t0_fixed = t_ok + args.delta_retry
                log(f"restart anchor: 确定 {t_ok:.3f} + {args.delta_retry:.3f}s "
                    f"-> t0 {t0_fixed:.3f}")
                # press+delta only centres the search now: the clock comes from the falling
                # notes, because the press timestamp cannot see the game's own restart
                # latency, which wandered +95/+118 ms on t15/t14 and turned the runs FAST.
                t0v, t_field = relock(notes, t_ok, delta=args.delta_retry,
                                      offset=offset_now, log=log,
                                      dump=f"{subdir(RUNS)}/relock_dets_{args.tag}.json")
                if t0v is not None:
                    t0_fixed = t0v
                    relocked = True
                # The field stamp needs no notes, so a chart whose opening objects the blob mask
                # cannot see (唱: two long notes at 3.64 s, the whole vote window empty on
                # g003/g004) still has a clock: t_field + the calibrated field->audio gap, the
                # same constant the vote window centres on. Its error class is the stamp's own
                # +-15 ms, against press+delta's +95-118 ms wander -- playing on it beats
                # aborting the run the user asked for, and the live drift probes still measure
                # it so a FAST/SLOW result stays diagnosable.
                fallback = t0v is None and t_field is not None and attempt == attempts
                if fallback:
                    t0_fixed = t_field + args.field_delta
                    log(f"  relock never locked - playing on the field stamp instead: "
                        f"t0 = t_field + {args.field_delta:.3f} = {t0_fixed:.3f}")
                with open(f"{subdir(RUNS)}/relock_{args.tag}.json", "w",
                          encoding="utf-8") as f:
                    json.dump({"t_ok": t_ok, "prior": t_ok + args.delta_retry,
                               "t_field": t_field, "t0_vote": t0v, "t0_used": t0_fixed,
                               "relocked": t0v is not None, "fallback": fallback,
                               "attempt": attempt, "attempts": attempts}, f, indent=1)
                if t0v is not None or fallback:
                    if replay:
                        # And the same probe on the way out: a channel that died between the
                        # restart taps and the lock would otherwise surface as play's opening
                        # rebuild -- born late all over again. A rebuild found here is still
                        # free: the clock can be re-locked, so redo the restart.
                        r0 = inj.respawns
                        inj.probe()
                        if inj.respawns > r0:
                            if attempt < attempts:
                                log(f"  重开后通道探活：注入通道又重建了一次"
                                    f"（respawns {inj.respawns}）- 这次重开作废，"
                                    f"重来一轮（{attempt}/{attempts}）")
                                continue
                            log(f"  !! 重开后通道探活：注入通道又重建了一次"
                                f"（respawns {inj.respawns}）- 重来次数已用尽，带着它开打")
                    break
                if attempt < attempts:
                    log(f"  relock did not lock (attempt {attempt}/{attempts}) - "
                        f"restarting the LIVE again to re-anchor")
                else:
                    log(f"  relock did not lock on any of {attempts} attempts and the field "
                        f"was never stamped - aborting (nothing left that measures t0)")
                    pause_if_live(inj, log)
                    return None
            return t0_fixed, relocked

        if not args.retry_anchor:
            t0_fixed, relocked = None, False
        else:
            r = _to_t0(0, eff_offset)
            if r is None:
                return 1
            t0_fixed, relocked = r
        watch = Watch() if hc is not None else None
        if args.record_counters:
            # One recorder per round, not per attempt: the counter resets a 重试 causes are part
            # of what the study has to see, and the stamps in its jsonl are host perf_counter
            # values -- the same clock every other line of this round's log is stamped with.
            from recorder import CountersRecorder

            # Not `rec`: that name is the round's result record everywhere else in this file, and
            # aliasing it here crashed the cleanup with 'dict' object has no attribute 'line' after
            # a perfectly good round (g314, whose recording was written and then lost its log line).
            counter_rec = CountersRecorder(f"{subdir(RUNS)}/{args.tag}.counters.avi",
                                           log=log).start()
            log(f"计数器实录：录到 {counter_rec.path}"
                f"（{counter_rec.box[2] - counter_rec.box[0]}x{counter_rec.box[3] - counter_rec.box[1]}，"
                f"无损 FFV1，每帧带时间戳）")
        # One round is up to (N aborts + 1) attempts when --retry-on-break is armed: an attempt
        # the HUD watcher flags as already lost is stopped, 重试ed back to t=0 in place and
        # re-fired from note 1. Only the attempt that plays through reaches the result page, so
        # records, chain cal and the panel's round count all see what they saw before this
        # existed; a false hint costs the rest of an attempt and one free restart, never a round.
        aborts = 0
        late_streak = 0              # consecutive 出生即废 aborts, reset by any real break
        boost = 0.0                  # ms this round has already shifted itself
        last_place, last_row = None, None     # where the last break landed, in chart seconds
        place_tries = []             # the PLACE_STEPS already tried at this place
        while True:
            hud, hint = None, None
            if args.watch_hud:
                from hudwatch import HudWatch

                hud = HudWatch(log=log, tag=args.tag,
                               sink=counter_rec.offer if counter_rec is not None else None)
                # The 确定 press resets every counter; the field's fade needs to clear before the
                # zero row can be baselined (the watcher re-baselines after any bright frame anyway).
                # After a relock the field has been up for a second-plus already, so only the
                # watcher's own spin-up needs waiting out.
                hud.start(delay=0.15 if relocked else (0.8 if t0_fixed is not None else 0.0))
                if args.retry_on_break and aborts < args.retry_on_break:
                    hint = BreakHint(hud)
            votes = {}
            # Collection stopped for the song: `late` p50 is 0.00 ms across ~2000 rounds, but its
            # tail (1.9% of 400-action windows above 5 ms) is the one pause we can take out of the
            # press clock ourselves. The guard restores the collector in its finally, so a round
            # that raises still leaves this process sane.
            with player.gc_guard(log=log):
                rc = play(hits, inj, log, vote=all_hits, field_seen=field_seen,
                          offset=eff_offset - boost,
                          anchor_deadline=args.anchor_deadline, min_votes=args.min_votes,
                          shotgun=not args.no_shotgun,
                          watch=watch, dump=f"{subdir(RUNS)}/dets_{args.tag}.json",
                          t0_fixed=t0_fixed,
                          stop=hint, late_fail=hint is not None, push_cap=args.live_push_cap,
                          kind_lead=kind_lead, vote_sink=votes, events=events,
                          open_trust=args.multi, status=log.status)
            if hud is not None:
                hud.stop()
                log(f"  hud tally: {hud.tally()} - {hud.dropped} 个候选没站稳、"
                    f"{hud.unverified} 个候选计数器未变、{hud.unzeroed} 个读回全零、"
                    f"{hud.wholebox} 个整窗被扫过、{hud.unmoved} 个数字没换，已弃"
                    + (f"；{hud.rebased} 次基线跟随" if hud.rebased else "")
                    + (f"；{hud.reseeded} 次重开后暗基线重算" if hud.reseeded else "")
                    + (f"  (!! {hud.error})" if hud.error else ""))
            if rc != ABORTED:
                break
            aborts += 1
            hit = hint.hits[0] if hint and hint.hits else None
            _park_attempt(args.tag, aborts, log)
            if hit is None:
                # 出生即废: the attempt was aborted by play's own fence, before it fired anything
                # (t92: the channel rebuild ate the [確定 -> note 1] budget). One is weather; two
                # in a row is a machine that needs a moment, so the restart cycle gets a bounded
                # settle before its pre-確定 probe. Bounded at 2 s and reset by any real break.
                late_streak += 1
                if late_streak >= 2:
                    settle = min(late_streak - 1, 2)
                    log(f"  连续 {late_streak} 次出生即废：重开前多等 {settle} s 让机器缓一口气")
                    time.sleep(settle)
                # Nothing was fired, so the line says that instead of naming a judgement that
                # never came.
                log(f"!! 重开晚到，出生即废、未发键，第 {aborts}/{args.retry_on_break} "
                    f"次中途重开本局，免费不耗火，下轮重开会先探活通道")
            else:
                late_streak = 0
                log(f"!! 断AP：{hit.get('row', '?')} @host [{hit.get('lo', 0.0):.3f}, "
                    f"{hit.get('hi', 0.0):.3f}]，第 {aborts}/{args.retry_on_break} 次中途重开本局"
                    f"，免费不耗火，若是误报，代价也只是这一次重开")
            # What the attempt that died was asking for, in its own words: the votes say how far
            # the field sat from our presses, and a run of them on one side is the shape a retry
            # cannot fix by itself. When it died too early to vote at all, the place it died in is
            # the evidence instead (see PLACE_STEPS). Either way: learn, then replay a *different*
            # clock -- never the same one nine times.
            place = None if hit is None else round(hit["lo"] - t0_fixed, 3)
            same = (place is not None and last_place is not None
                    and abs(place - last_place) <= 0.5 and hit.get("row") == last_row)
            if place is not None and not same:
                place_tries = []                     # the break moved; the old guesses are spent
            was = boost
            votes_ms = [v * 1000 for v in votes.get("votes", [])]
            why = ""
            if votes_ms:
                boost = retry_boost(votes_ms, boost)
                why = (f"被中止的这次 {len(votes_ms)} 票中位 {statistics.median(votes_ms):+.0f} ms"
                       f"（修正器想动，正推上限只有 {args.live_push_cap:.0f}）")
            else:
                step, place_tries = place_boost(same, place_tries)
                if step is not None:
                    boost = step
                    why = (f"两次都断在 chart +{place:.1f}s（{hit.get('row', '?')}），而这一局修正器"
                           f"一句话都没来得及说 —— 试第 {len(place_tries)} 个方向")
            if place is not None:
                last_place, last_row = place, hit.get("row")
            if boost != was:
                log(f"!! {why}：下一次重开整体偏移补 {was:.0f} -> {boost:.0f} ms"
                    f"（本轮内有效，不动配方，也不写进链路校准）")
            r = _to_t0(aborts, eff_offset - boost)
            if r is None:
                return 1
            t0_fixed, relocked = r
            if hud is not None:
                # The 重试 put the counters back at zero; the watcher's darkest-ever box (what
                # gates three and four measure against) describes the attempt we just gave up on,
                # and a pause scrim in between dims the box far enough to poison it. s260 lost 24
                # real GREAT carries in a row to exactly that. Cheap, and the next frames are the
                # zeros pattern by construction.
                hud.reseed()
        if hc is not None:
            log(f"capture: {hc.n} frames, {hc.stalls} gaps over 80 ms, worst {hc.worst * 1000:.0f} ms")
        # The walk back stays on the fast source too -- see use_fast_capture for why that is now
        # allowed. mumucap.uninstall() in the finally is what ends the session.
        fly_cid = hit_pick.get("cid") or fly_cid
        # What the fired bytes were built from, and which numbers this round played under, recorded
        # with the result instead of reconstructed at --pin time: the pin's promise is about the
        # inputs the round actually saw. A round whose chart never resolved carries neither -- the
        # absence is the finding, and pin_state reads it as "cannot tell", never as "unchanged".
        fly_extra = {"cfg": {"offset": args.offset, "corr": corr, "eff": eff_offset,
                             "push": args.live_push_cap, "retry": args.retry_on_break,
                             "limit": args.limit, "lead": kind_lead, "boost": boost},
                       # How ugly this round was, beside the recipe: a round that needed three
                       # restarts and one that played clean used to be indistinguishable in the
                       # record (s291 vs s301, 0066_02). Top level, not in cfg -- it is a fact
                       # about the round, not a number the round was played under.
                       "aborts": aborts}
        if fly_cid:
            fly_extra["chart"] = fly_cid
            # A random round's --hits is whatever the panel had selected last, not the chart it
            # actually rolled, so only a named run may fingerprint its own file; otherwise take the
            # library's copy of the chart this round really fired. 多人 sits on that side too: it has
            # no positional at all, and argparse hands back the default instead
            # (research/archive/data/mayoiuta_ex.hits.json -- a different song's chart), so mp17/mp18
            # were stamped with that file's hash while playing 0109_03 (user m04278's records fix).
            fly_extra["at"] = fingerprint(fly_cid, None if pick_mode else args.hits)
        if args.random or args.song or args.multi:
            # 多人 gets a stamp of its own: the room drew the chart, we did not nominate it. The
            # name was only ever filled in for the two pick modes, so every 多人 record until
            # 2026-10-08 carried an empty song/diff beside a real chart id (user m04278).
            fly_extra["multi" if args.multi else ("random" if args.random else "song")] = True
            if fly_cid:
                fly_extra.update({"song": hit_pick["title"], "diff": hit_pick["diff"]})
        rec = wait_result(args.tag, inj, log=log, extra=fly_extra, multi=args.multi,
                          read_split=args.read_split)
        if rec and hud is not None:
            # The HUD watcher is what decides to abort, so a judgement it never committed is a
            # break the machine flew straight through: g238's 24 lost carries were exactly that,
            # and until now nothing compared the two counts. One-sided on purpose -- the watcher
            # cannot over-count a *round* (any event aborts the attempt it belongs to), so only
            # "the result page saw more than the watcher" is a blind spot worth naming.
            judged = sum(int(rec.get(k) or 0) for k in ("great", "good", "bad", "miss"))
            seen = sum(hud.n[r] for r in ("GREAT", "GOOD", "BAD", "MISS"))
            if judged > seen:
                log(f"!! 结算页比 HUD 多 {judged - seen} 个非 PERFECT（HUD 只报 {seen}）："
                    f"断AP机制这一局漏了 {judged - seen} 个真事件，弃票统计见上一行 tally")
                rec["hud_missed"] = judged - seen
        if rec:
            if not os.environ.get("OURNOTES_PANEL"):
                # Spawns from the panel are recorded there; recording here too would double every row.
                record_cli(args, rec, log)
            if args.limit:
                # A trimmed run judges a third of the chart and MISSes the rest; its histogram is
                # not the chain's, and writing it would push the calibrated offset around.
                log("chain cal: 本局是 --limit 有界测试，跳过回写")
            else:
                update_chain_cal(rec, corr, args.tag, log, nominal=args.offset)
        if not args.stay_on_result:
            left = True
            leave_at_select(inj, log, multi=args.multi)
        return rc
    except MemoryError as e:
        # 三局（g377/g378/g380）死在宿主机内存耗尽上：一帧（720x1280x3 = 2.64 MiB）都分配不出来，
        # 异常从 `grab()` 穿出来，日志里只剩一行走 stderr 的 traceback 和一个没有解释的 rc=1。
        # 收成一行明白话；剩下的照旧 —— `finally` 仍然负责把游戏走回家。
        log(f"!! 内存不足：{e!r} —— 宿主机连一帧都分配不出来，本局判失败")
        return 1
    finally:
        if WALK_HOME_ON_ANY_EXIT and not args.stay_on_result and not left:
            # Whatever ended this round early -- the walk never found a LIVE, a restart could not
            # be walked out of, the re-lock never locked -- the game goes back to 乐曲選択 before
            # we let go of it. Leaving it where it stopped is what makes a *second* round fail:
            # g274 gave up with the game on 达成奖励列表 and g275 then died reading that page
            # ("连续四次读不到变化") without playing a note, which the panel reads as two
            # consecutive failures and stops the queue -- the difference between one bad round and
            # a dead night for an unattended run.
            try:
                leave_at_select(inj, log, multi=args.multi)
            except Exception as e:                             # noqa: BLE001
                log(f"!! 收尾时走回选曲页出错：{e!r}")
        if counter_rec is not None:
            # Said before close() so the numbers are the writer's final ones; a recorder that lost
            # frames says so here and not only in a file nobody opened.
            log(counter_rec.line())
            counter_rec.close()
        inj.close()
        if hc is not None:
            hc.stop()
        if args.watch_hud:
            try:
                import mumucap

                mumucap.uninstall()
            except Exception:                                  # noqa: BLE001
                pass
        if args.fastcap:
            import mumucap

            mumucap.uninstall()
        # 落盘预算（2026-10-19，用户「优化磁盘空间管理」）：每一局收尾顺手执行一遍无人值守
        # 那条 —— 垃圾照删、取证桶超上限就按保留集压、重复文件换硬链接（六小时一次）、
        # 并往 `research/logs/retention.log` 记一行。它不碰录像与归档（删老录像是判断）。
        # 放在 finally 里：一局在哪儿失败都该把这条走掉，它自己带三道保险，不会伤正在写的文件。
        try:
            import retention

            retention.auto()
        except Exception as e:                                 # noqa: BLE001
            print(f"落盘清理跳过：{e!r}", flush=True)
        log.close()


if __name__ == "__main__":
    sys.exit(main())
