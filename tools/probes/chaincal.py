"""Pin what the chain calibration is allowed to say about itself, offline.

`update_chain_cal` has three outcomes that all look the same in a log line and are opposite in
kind: the loop moving the offset, the loop voting every run and being refused by a bound every run,
and the rule deciding a run is already where it wants to be. g214-g224 are the second -- eight
consecutive runs asking to press ~19 ms later, each collecting the floor's answer, each leaving a
line that reads like a decision. Since 2026-10-02 a refusal that repeats is announced, and
announced only when it repeats, so this probe has to test both directions of that error bar: no
alarm while the loop is still settling, and no alarm left standing once a run actually moves.

The third outcome arrived the same day, with the rule that a run which lost nothing and judged
early is the target, not the error (fast is the forgiving side; only the AP rate is ours to
protect, and the score that centring would buy is the game's 养成 deciding). It has to be
distinguished from the first two in both directions: four clean early runs in a row must not arm
the bound alarm, and a clean run arriving while the alarm is armed must end it.

It also pins the file's contract with the panel. Since the 运行策略卡 and 链路标定卡 were deleted
(2026-10-03) the panel has no card to hover: it reads `pinned` -- the full sentence, reason
included -- straight into the log page, which has the room the card never had. That is only safe
while the full sentence still *starts with* the short one, so the last part calls `saturation()`
itself and asserts the prefix, in both directions (the streak floor included).

Nothing here touches a device, a live, or the real research/chain_cal.json -- every case runs
against a temp file.

Run from the repo root:  python tools/probes/chaincal.py
"""

import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import run  # noqa: E402

TMP = os.path.join(tempfile.gettempdir(), "chaincal_probe.json")


def _rec(p_fast, p_slow, off=0, judged=None):
    """A result-page record: the split PERFECT pair, plus the counts the flood gate reads."""
    n = p_fast + p_slow
    return {"split": {"p": [p_fast, p_slow], "g": [0, 0], "gd": [0, 0], "b": [0, 0]},
            "perfect": judged if judged is not None else n, "great": 0, "good": 0, "bad": 0,
            "miss": 0, "non_perfect": off}


def _open(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _feed(recs, start=0.0):
    """Push records through the shipped updater, one per run, and return (corr, file, log)."""
    run.CHAIN_CAL = TMP
    if os.path.exists(TMP):
        os.remove(TMP)
    lines = []
    corr = start
    for i, rec in enumerate(recs):
        corr = run.update_chain_cal(rec, corr, f"p{i:03d}", lines.append)
    return corr, _open(TMP), lines


def part1():
    """A bound that keeps refusing is announced, once per run, in both lengths.

    The runs lean early while losing notes off the early side (``off=5`` -- inside the flood gate,
    outside the clean rule). That is a real measurement asking to move; a run that lost nothing
    would now be kept instead, and would say nothing about the bound at all.
    """
    corr, st, lines = _feed([_rec(900, 30, off=5)] * 4)   # lean ~0.94 -> est ~ -26 every run
    pinned, brief = st.get("pinned"), st.get("pinned_brief")
    said = [l for l in lines if "板顶住" in l]
    ok = (corr == run.CORR_FLOOR and pinned and brief and brief in pinned
          and len(said) == 1 and said[0].startswith("chain cal: ")
          and "96 ms" in pinned and "96 ms" not in brief      # the reason is the tip's, not the card's
          and "校准器没电" in pinned)
    print(f"corr={corr} brief={brief!r}")
    print(f"announced on {len(said)}/4 runs (the 4th; the first two are still settling)")
    print("PART 1 " + ("PASS" if ok else "FAIL"))
    return ok


def part2():
    """No alarm while the loop is still moving, and none below the streak floor."""
    # A lean small enough to move the correction: the loop is working, so it must stay quiet.
    _, st_a, lines_a = _feed([_rec(600, 330, off=5)] * 2)
    # Two refusals are not a pattern: PINNED_ALARM is 3, and crying wolf here is what would make
    # the line get ignored.
    _, st_b, lines_b = _feed([_rec(900, 30, off=5)] * 2)
    ok = (st_a["pinned"] is None and not any("板顶住" in l for l in lines_a)
          and st_b["pinned"] is None and not any("板顶住" in l for l in lines_b))
    print(f"moving: pinned={st_a['pinned']!r}; 2 refusals: pinned={st_b['pinned']!r}")
    print("PART 2 " + ("PASS" if ok else "FAIL"))
    return ok


def part3():
    """A run that moves clears the alarm: it cannot outlive its own evidence.

    The alarm is armed first -- without that, "no alarm line" would pass on a build that never
    announces anything. 380/550 then leans the other way by enough to clear the 3 ms no-move rule.
    """
    _corr, st1, lines1 = _feed([_rec(900, 30, off=5)] * 4)
    armed = bool(st1["pinned"]) and any("板顶住" in l for l in lines1)
    run.CHAIN_CAL = TMP
    moved = []
    corr = run.update_chain_cal(_rec(380, 550), run.load_chain_corr()[0], "p900", moved.append)
    st2 = _open(TMP)
    ok = (armed and not any("板顶住" in l for l in moved)
          and st2["pinned"] is None and st2["pinned_brief"] is None and corr > run.CORR_FLOOR)
    print(f"armed first: {armed}; after a run that moves: corr={corr} "
          f"pinned={st2['pinned']!r}, alarm lines={sum('板顶住' in l for l in moved)}")
    print("PART 3 " + ("PASS" if ok else "FAIL"))
    return ok


def part4():
    """A flooded run is refused before the bound question, and says nothing about bounds."""
    corr, st, lines = _feed([_rec(900, 30, off=5)] * 3, start=0.0)
    run.CHAIN_CAL = TMP
    kept = run.update_chain_cal(_rec(900, 30, off=200), run.load_chain_corr()[0], "p999",
                                lines.append)
    ok = kept == corr and not any("板顶住" in l for l in lines[-1:])
    print(f"flooded run: corr kept {kept}, last line={lines[-1][:34]}...")
    print("PART 4 " + ("PASS" if ok else "FAIL"))
    return ok


def part5():
    """A clean run on the early side is the target, not the error -- and keeping is not a bound.

    Four directions of one rule: it must not move the clock (a), it must not be reported as a
    bound refusing a vote (a again -- four no-moves in a row used to be exactly what armed the
    alarm), it must not apply when the run leans late, where centring toward fast is the whole
    point (c), and it must not fire on a result page that never reported its 非 PERFECT count (d).
    """
    # (a) four clean early runs: nothing moves, nothing is claimed about bounds.
    corr, st, lines = _feed([_rec(900, 30)] * 4, start=-5.0)
    hist = st["history"]
    quiet = (corr == -5.0 and all(e.get("kept") == "clean" for e in hist)
             and all(e["corr_before"] == e["corr_after"] for e in hist)
             and st["pinned"] is None and st["pinned_brief"] is None
             and sum("偏早正是要的位置" in l for l in lines) == 4)

    # (b) an armed floor streak ends the moment a run is kept: the loop stopped voting, so a
    # sentence about a bound refusing votes is no longer true.
    _, st1, _ = _feed([_rec(900, 30, off=5)] * 3, start=run.CORR_FLOOR)
    armed = bool(st1["pinned"])
    run.CHAIN_CAL = TMP
    kept = run.update_chain_cal(_rec(900, 30), run.load_chain_corr()[0], "p900", lambda *_: None)
    st2 = _open(TMP)
    broke = armed and st2["pinned"] is None and kept == run.CORR_FLOOR

    # (c) clean and LATE is an error: it moves toward the fast side and logs an ordinary fold.
    corr_c, st_c, lines_c = _feed([_rec(300, 900)], start=0.0)
    toward_fast = (corr_c > 0.0 and "clean" not in str(st_c["history"][0])
                   and not any("偏早" in l for l in lines_c))

    # (d) a result page whose 非 PERFECT count failed to read is not a claim of 全 PERFECT: the
    # panel prints 读取失败 for exactly this, and the rule must not upgrade it to evidence.
    corr_d, st_d, lines_d = _feed([_rec(900, 30, off=None)], start=0.0)
    unread = (corr_d < 0.0 and st_d["history"][0].get("kept") is None
              and not any("偏早" in l for l in lines_d))

    print(f"(a) kept 4x: corr={corr} alarm={st['pinned']!r} hist_kept={[e.get('kept') for e in hist]}")
    print(f"(b) armed={armed} -> after a kept run: corr={kept} alarm={st2['pinned']!r}")
    print(f"(c) clean-late: corr={corr_c:+.1f} (toward fast)")
    print(f"(d) count unread: corr={corr_d:+.1f} kept={st_d['history'][0].get('kept')!r}")
    print("PART 5 " + ("PASS" if (quiet and broke and toward_fast and unread) else "FAIL"))
    return quiet and broke and toward_fast and unread


def _refusal_streak(n):
    """`n` runs in the record asking to move and being refused by the floor -- what saturation() reads."""
    return [{"est_ms": -4.0, "corr_before": run.CORR_FLOOR, "corr_after": run.CORR_FLOOR}
            for _ in range(n)]


def part6():
    """The panel reads the one key run.py still writes for it, reports the bound once, and owns no
    arithmetic.

    Two lengths because there were two readers: the panel's 运行配置 card showed the short one and
    the hover tip the long one. Both cards are gone (AGENTS.md: 「运行策略卡与链路标定卡已删」), so
    the panel reads `pinned` -- the long one -- into the log, which has the room. What makes that
    safe is that `saturation()`'s long sentence *starts with* the short one: nothing the card used
    to show is missing. (c) below calls the shipped function for that, rather than reading the `+`
    out of the source, and pins the streak floor too, so the two lengths cannot drift apart behind
    the panel's back.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "flet_gui.py")
    src = open(path, encoding="utf-8").read()
    reads_full = 'cal.get("pinned")' in src
    # 报了才叫「读」：把值取出来放在一个变量里、不告诉用户，用户看到的是成绩开始飘而不知道
    # 为什么。这一句同时钉住「只在变化时报一次」—— 通知整段删掉，这个比较也就没了。
    reports = "pinned != self._pinned" in src
    # 「不复制算术」判的是**定义**，不是提到：面板可以在注释里说明这个边界是 run.py 的，
    # 但不能自己再定义一次 —— 定义出来就意味着多了一条会漂移的真相。
    dup = re.search(r"^\s*CORR_(FLOOR|CEIL)\s*=", src, re.M)
    # (c) 长短两句是同一句话的两截，且「连续几局」这条门槛还在：两局不算数、三局才算。
    brief, full = run.saturation(_refusal_streak(3))
    quiet_b, quiet_f = run.saturation(_refusal_streak(2))
    prefix = bool(brief) and bool(full) and full.startswith(brief) and "顶住" in brief
    streak = quiet_b is None and quiet_f is None
    spoken = "链路标定已达边界" in src
    ok = reads_full and reports and dup is None and prefix and streak and spoken
    print(f"panel: full key={reads_full}, 报一次={reports}, "
          f"bounds defined={dup.group(0).strip() if dup else None}, 撞界文案={spoken}")
    print(f"长短两句：3 局拒绝 -> brief={brief!r}；2 局 -> {quiet_b!r}；前缀关系={prefix}")
    print("PART 6 " + ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    try:
        allok = all([part1(), part2(), part3(), part4(), part5(), part6()])
    finally:
        if os.path.exists(TMP):
            os.remove(TMP)
    sys.exit(0 if allok else 1)
