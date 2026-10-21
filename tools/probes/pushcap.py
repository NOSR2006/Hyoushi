"""Pin the live re-anchor's one-sided ceilings, and the two strategy numbers the panel ships.

The push ceiling comes from a single object rather than from a crash. 0056_03's 628th judged object
is a trace at chart +70.890 s whose x is the x the long before it ended on 0.65 ms earlier -- the
only trace-on-a-parked-finger hand-off in the library. Cutting the window's 87 runs of that chart by
the correction in force at that object: 17 runs at <= 0 ms broke it 0 times; 60 runs above 0 ms broke
it 13 times (22%, Fisher one-sided p=0.028), every break BAD or MISS on the FAST side, and the breaks
start at +8 ms rather than at any threshold -- so the only cut with clean support is the sign. The
shipped ceiling is 10 ms, a deliberate sliver of the risky side; the panel's 设置 page edits it, and
0 reproduces the sign cut. The ghost-clear special case for the same object (GHOST_CLEAR_MS) had
already taken the rate from 33% to 7%; what survived it is all on the positive side.

The abort cap is the other number 设置 owns: how many times one round may 重试 after a HUD-committed
break. It is a budget, not a threshold -- it only has to agree between the panel, the flag and the
run's own log line -- so PART 4 pins all three readers of both numbers.

PART 5 is the per-kind lead, which is a behaviour change rather than a budget, so it is pinned two
ways: the table has to agree between player, run.py's default and the panel's shipped values, and
applying it to one kind has to move **that kind's** presses and nothing else -- by exactly the number
of milliseconds named, on a real chart, with the all-zero table proven to reproduce today's schedule
to the microsecond. The direction is checked too: a positive number has to press *earlier*, which is
what every piece of copy in the panel and the run's log line says it is setting, and a flipped sign
would still pass any test that only counts moved actions.

PART 6 reads run.py as a name list: every `args.X` the file touches has to be a dest its own
`add_argument` calls produce, because g237 flew a whole song and then died one line before writing
its record over exactly such a name (`args.retry_cap`, where the flag is `--retry-on-break`).

PART 7 is what the ceiling says about itself at 0 ms. g237's eight agreeing late votes (+13..+35 ms)
all logged "inside deadband, kept", which is true of the target the ceiling produced and hides the
reason -- so the line names the bound instead, and the probe requires both the wording and the clock
staying where it was.

PART 8's sibling is PART 9: a retry cannot fix a systematic offset by replaying the clock (s291
broke on 0066_02 eight times, every attempt's votes asking for +17..+26 ms), so an aborted
attempt's own votes may shift the next attempt by one bounded step -- converging, since each
attempt re-measures the residual, and never written back to the recipe.

PART 13 is the 多人 side rule, i.e. the one part of the opening window that is not a threshold: in
多人 (`open_trust=True`, which `run.py` passes on `--multi` and nowhere else) a pair that reads the
other way from the correction already in place is refused instead of spending it back -- mp4's live
shape, where the +139 ms plateau landed the -45 ms the window had just taken back on 0. The control
is the same feed with the flag off, which must still spend the correction back: on a single-player
round the push ceiling is the sanctioned way to do that, and a rule that overrode it would be a
second, hidden ceiling.

No device and no recorded frames: PART 1-3 hand `LiveCorrector` a synthetic field built from the
project's own perspective constants (C_FIELD/VP_MOTION/EDGE_*), six notes on lanes 4 apart placed so
`vote_t0` can only read one start offset. Each case runs the same feed twice, once at the shipped
ceiling and once at 120 ms, so the clamp has to show a difference; PART 3 is the control, where it
must not.

Run from the repo root:  python tools/probes/pushcap.py
"""
import ast
import io
import inspect
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from compile import EDGE_LEFT_AT_0, EDGE_RIGHT_AT_0, EDGE_SLOPE, JUDGE_Y  # noqa: E402
from detect import C_FIELD, VP_MOTION  # noqa: E402
import player  # noqa: E402
import rlog  # noqa: E402

# Six notes, lanes 4 apart. vote_t0 matches a blob to every note within lane_tol=2.5 of its lane,
# so 4 is the smallest spacing that leaves each blob exactly one candidate; with one candidate per
# blob the histogram is a single bin and the peak/runner-up test is decided by construction.
NOTES = [(0.15 + 0.15 * i, 4.0 * i) for i in range(6)]
FRAMES = (0.0, 0.02)             # two frames of six blobs: vote once, then agree and commit
SJ = 1.0 / (JUDGE_Y - VP_MOTION)
NUDGE, LATE = -0.010, 0.040      # a small early pull, then a vote that wants 40 ms of push.
# 40, not 60: it has to stay inside CORR_TRUST_MS so PART 1-2 measure the push ceiling and not
# the drift rail (PART 12 is the rail; a vote past 50 ms is refused by it now, whatever the cap).

# One note of each kind, a second apart and far apart in x: no slot is ever asked for twice, and no
# long here is short enough to register a ghost, so each kind's action sequence is its own -- which
# is the only way to say "exactly this kind moved, by exactly this much".
FIXTURE = [
    {"kind": "tap", "t_ms": 1000.0, "x": 300.0},
    {"kind": "long", "t_ms": 2000.0, "x": 500.0, "end_ms": 2400.0,
     "path": [{"t_ms": 2000.0, "x": 500.0}, {"t_ms": 2400.0, "x": 500.0}]},
    {"kind": "flick", "t_ms": 3000.0, "x": 700.0},
    {"kind": "trace", "t_ms": 4000.0, "x": 1600.0},
]
# Actions per note, for the kinds whose sequence has a fixed shape (a long's depends on its path).
KIND_NACT = {"tap": 2, "flick": 4, "trace": 2}
LEAD = 15.0                       # ms of per-kind offset this probe names, same order as the risky side
FLICK_T = {3000.0 - 20.0, 3002.0, 3016.0, 3030.0}    # the fixture flick's four action times


def feed_plan(push):
    """Per frame, where each note's sprite sits if the field really runs `push` seconds late."""
    out = []
    for t in FRAMES:
        row = []
        for nt, lane in NOTES:
            # cross = t + C*(1/(y-vp) - sj) has to equal nt + push for the vote to name `push`.
            y = VP_MOTION + 1.0 / (SJ + (nt + push - t) / C_FIELD)
            lo = EDGE_LEFT_AT_0 - EDGE_SLOPE * y
            hi = EDGE_RIGHT_AT_0 + EDGE_SLOPE * y
            row.append((y, lo + (hi - lo) * (lane / 24.0)))
        out.append((t, row))
    return out


def run(steps, cap_ms, open_trust=False):
    """Feed one (push, frames) group at a time; each group is one vote-and-commit cycle."""
    lines = []
    lc = player.LiveCorrector(NOTES, 0.0, lines.append, max_corr_up=cap_ms / 1000.0,
                              open_trust=open_trust)
    for push, frames in steps:
        for t, row in feed_plan(push)[:frames]:
            lc.feed(t, row)
    return lc, lines


def part1():
    """The shipped ceiling: the pull back stops at exactly the ceiling, and the notice says so.

    NUDGE first, because a positive vote against a correction that is already 0 lands inside the
    6 ms deadband and would prove nothing -- the clamp only shows when there is something to move.
    """
    cap = player.LIVE_PUSH_MS
    lc, lines = run([(NUDGE, 2), (LATE, 2)], cap)
    capped = [l for l in lines if "capped at" in l]
    ok = (lc.committed == 2 and abs(lc.corr - cap / 1000.0) < 1e-9 and lc.corr <= cap / 1000.0
          and len(capped) == 1 and "+40 ms" in capped[0]
          and f"capped at +{cap:.0f} ms" in capped[0])
    print(f"pull {NUDGE * 1000:+.0f} then vote {LATE * 1000:+.0f}, cap {cap:.0f}: "
          f"commits={lc.committed} corr={lc.corr * 1000:+.1f} ms capped={len(capped)}")
    print("PART 1 " + ("PASS" if ok else "FAIL"))
    return ok, lines


def part2():
    """The same feed with the ceiling at 120 ms: the vote gets past the ceiling, to the step limit."""
    lc, lines = run([(NUDGE, 2), (LATE, 2)], 120.0)
    ok = (lc.committed == 2 and lc.corr * 1000 > player.LIVE_PUSH_MS
          and not any("capped" in l for l in lines))
    print(f"same feed, cap +120: commits={lc.committed} corr={lc.corr * 1000:+.1f} ms "
          f"(> the shipped ceiling is exactly what it forbids)")
    print("PART 2 " + ("PASS" if ok else "FAIL"))
    return ok


def part3():
    """The control: -34 ms is the earlier side, and neither ceiling has an opinion about it."""
    capped, open_ = run([(-0.034, 2)], player.LIVE_PUSH_MS), run([(-0.034, 2)], 120.0)
    ok = (capped[0].committed == 1 and open_[0].committed == 1
          and abs(capped[0].corr + 0.034) < 1e-9 and abs(open_[0].corr + 0.034) < 1e-9
          and not any("capped" in l for l in capped[1] + open_[1]))
    print(f"early only: capped run corr={capped[0].corr * 1000:+.0f} ms, "
          f"open run {open_[0].corr * 1000:+.0f} ms")
    print("PART 3 " + ("PASS" if ok else "FAIL"))
    return ok


def part4(cap_line):
    """One number, three readers -- twice: the push ceiling and the abort cap."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 这两个常量现在住在 tools/panel_core.py（视图无关的业务层），面板只负责把它们显示出来。
    core_src = io.open(os.path.join(root, "panel_core.py"), encoding="utf-8").read()
    runp = io.open(os.path.join(root, "run.py"), encoding="utf-8").read()
    m = re.search(r"PUSH_ON_MS, PUSH_OFF_MS, RETRY_CAP = ([\d.]+), ([\d.]+), (\d+)", core_src)
    a = re.search(r'--retry-on-break", nargs="\?", type=int, const=(\d+)', runp)
    default = inspect.signature(player.play).parameters["push_cap"].default
    shown = next((fn(pat.search(cap_line)) for pat, fn in rlog.RENDER if pat.search(cap_line)),
                 None)
    ok = (m is not None and default == player.LIVE_PUSH_MS
          and float(m.group(1)) == player.LIVE_PUSH_MS and float(m.group(2)) == 120.0
          and a is not None and int(a.group(1)) == int(m.group(3))
          and shown is not None and shown != cap_line)
    print(f"player={player.LIVE_PUSH_MS} play default={default} panel={m.groups() if m else None} "
          f"run.py abort const={a.group(1) if a else None} 面板文案={shown!r}")
    print("PART 4 " + ("PASS" if ok else "FAIL"))
    return ok


def _key(a):
    """(t, op, x, y) -- the slot is left out on purpose: a shifted window can legitimately hand a
    note to a different finger, and that is not what a per-kind lead claims to change."""
    return a[0], a[1], a[3], a[4]


def _acts(hits, lead):
    return player.build_actions(hits, player.JUDGE_Y, 20.0, 45.0, 90, 0, lead)[0]


def _diff(a, b):
    """What `a` has that `b` lost, and what `b` has that `a` lacks, as multisets."""
    ca, cb = Counter(_key(x) for x in a), Counter(_key(x) for x in b)
    return ca - cb, cb - ca


def _refuses(fn, text):
    try:
        fn(text)
    except SystemExit:
        return True
    return False


def part5():
    """One table three readers share, and a shift that touches exactly the kind it names.

    A count alone would pass with a reversed sign, so every case also checks the direction: a
    positive per-kind offset has to land `ms` **earlier** than the shared clock, which is what the
    panel's 「种类偏移」 boxes and the run's log line say they are setting.
    """
    import run

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    core_src = io.open(os.path.join(root, "panel_core.py"), encoding="utf-8").read()
    m = re.search(r"^KIND_LEAD_MS = \{([^}]*)\}", core_src, re.M)
    panel = {k: float(v) for k, v in re.findall(r'"(\w+)": (-?[\d.]+)', m.group(1))} if m else None
    default = run.parse_kind_lead("")
    refused = sum(_refuses(run.parse_kind_lead, b)
                  for b in ("xyz=5", "tap5", "flick", "flick=15 tap=-5"))
    ok_tab = (panel == default == player.KIND_LEAD_MS and set(default) == set(player.KINDS)
              and not any(default.values()) and refused == 4
              and run.parse_kind_lead("flick=15,tap=-5")
                  == {**player.KIND_LEAD_MS, "flick": 15.0, "tap": -5.0})

    hits = json.load(io.open(os.path.join(rlog.CHARTS, "0056_03.hits.json"), encoding="utf-8"))
    base = _acts(hits, None)
    ok_zero = base == _acts(hits, player.KIND_LEAD_MS) and len(base) > 1000

    gone, arrived = _diff(_acts(FIXTURE, None), _acts(FIXTURE, {"flick": LEAD}))
    ok_fx = (len(gone) == len(arrived) == KIND_NACT["flick"]
             and sorted((t + LEAD, op, x, y) for t, op, x, y in arrived) == sorted(gone)
             and all(t in FLICK_T for t, _, _, _ in gone))

    cases = {}
    for kind, ms in (("tap", LEAD), ("flick", LEAD), ("trace", LEAD), ("flick", -LEAD)):
        moved = _acts(hits, {kind: ms})
        lost, gained = _diff(base, moved)
        want = sum(1 for h in hits if h["kind"] == kind) * KIND_NACT[kind]
        cases[(kind, ms)] = (len(lost) == len(gained) == want
                             and sorted((t + ms, op, x, y) for t, op, x, y in gained) == sorted(lost)
                             and len(moved) == len(base), len(lost))
    ok_real = all(ok for ok, _ in cases.values())

    ok = ok_tab and ok_zero and ok_fx and ok_real
    print(f"table: player={sorted(player.KIND_LEAD_MS.items())} 面板={panel} "
          f"坏输入被拒={refused}/4")
    print(f"0056_03: {len(base)} 个动作，全零表与不传参数逐毫秒相同={ok_zero}；"
          f"合成谱上只有滑键的 {len(gone)} 个动作动了={ok_fx}")
    for (kind, ms), (ok_case, n) in cases.items():
        print(f"  {kind}{ms:+g} ms -> 动了 {n} 个（{KIND_NACT[kind]} × 该种音符数），"
              f"每个正好差 {ms:+g} ms={ok_case}")
    print("PART 5 " + ("PASS" if ok else "FAIL"))
    return ok


def part6():
    """Every `args.NAME` run.py reads has to be a name its own parser produces.

    g237 flew all 3206 actions of 0056_03 and then died one line before the record, because the cfg
    dict asked for `args.retry_cap` -- the flag is `--retry-on-break`, so the number existed in the
    panel, in the parser and in the log line, and only not in the one place that read it. No offline
    test could have seen it by running: the path needs a whole live song. Read as a name against the
    parser's own dests, it costs a millisecond.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, "run.py"), encoding="utf-8").read()
    declared = _arg_dests(ast.parse(src))
    missing = sorted(_arg_reads(ast.parse(src)) - declared)
    # The counterfactual is the bug itself, verbatim: the check has to name it.
    broken = ast.parse(src.replace("args.retry_on_break,", "args.retry_cap,", 1))
    teeth = sorted(_arg_reads(broken) - declared) == ["retry_cap"]
    ok = not missing and teeth
    print(f"run.py 读 {len(_arg_reads(ast.parse(src)))} 个 args.*，"
          f"自己的 parser 给不出来的：{missing or '没有'}；把 bug 抄回去则报 {teeth}")
    print("PART 6 " + ("PASS" if ok else "FAIL"))
    return ok


def _arg_reads(tree):
    return {n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id == "args"}


def _arg_dests(tree):
    """The dests every `add_argument` in the file produces (positional names included)."""
    out = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument"):
            continue
        for k in node.keywords:
            if k.arg == "dest" and isinstance(k.value, ast.Constant):
                out.add(k.value.value)
        for a in node.args:
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                s = a.value
                out.add(s.lstrip("-").replace("-", "_") if s.startswith("-") else s)
    return out


def part7():
    """The ceiling at 0 ms: a late field must not move the clock, and must not blame the deadband.

    g237 flew 0056_03 with 正推上限 0, and all eight of its agreeing votes (+13..+35 ms) logged
    "inside deadband, kept". That is true of the *target* the ceiling produced, and it hides the
    reason: at 0 ms it is the bound that keeps the clock, so a reader who believes the deadband goes
    hunting for votes that never agree. The line now says which of the two it was -- and the panel
    still keeps both kinds off the log page.
    """
    lc, lines = run([(NUDGE, 2), (LATE, 2), (LATE, 2)], 0.0)
    sealed = [l for l in lines if "已封" in l]
    capped = [l for l in lines if "capped at" in l]
    ok = (lc.committed == 2 and abs(lc.corr) < 1e-9 and lc.corr <= 1e-9
          and len(capped) == 1 and "+0 ms" in capped[0]
          and len(sealed) == 1 and "+0.040s" in sealed[0] and "+0 ms 已封" in sealed[0]
          and "inside deadband" not in sealed[0])
    print(f"cap 0: 提交 {lc.committed} 次（先 -10 再回到 0），corr={lc.corr * 1000:+.1f} ms，"
          f"「capped at」句 {len(capped)}、「已封」句 {len(sealed)}")
    for l in capped + sealed:
        print("  " + l.strip())
    print("PART 7 " + ("PASS" if ok else "FAIL"))
    return ok


def part8():
    """The vote margin: how much evidence a pair needs depends on how big a move it asks for.

    Two witnesses from the corpus, and one from the other side of the boundary. g239's first pass:
    six blobs voted -150 ms (5 vs 3), the pool carried them into the next vote, and that one
    "agreed" at -152 ms with the runner-up family one vote behind (11 vs 10). 2026-10-07's g458 was
    the same shape with three votes: 12 against a runner-up of 9 agreed on -163 ms, committed the
    full -45 ms step, and the remaining 204 judged objects all landed GREAT-FAST. Both asked for
    >= 100 ms, and both are refused by VOTE_MARGIN_BIG. The third witness is the small side: a 6 ms
    move with the same weak margin is *allowed*, because the corpus's useful corrections are all
    <= 23 ms and three of them (g392 +6, g393 0, g425 -6) do not clear their runner-up by 4 at all --
    and a 6 ms step is inside the noise that decides a one-object round (g452, g457). Forcing the
    flat margin to 1, or the big margin back to 2, is the counterfactual in each direction.
    """
    real = (player.vote_t0, player.VOTE_MARGIN, player.VOTE_MARGIN_BIG)
    cases = (("thin", [(0.040, 5, 3), (0.040, 11, 10)]),        # 1 vote clear, big move
             ("g458", [(0.040, 5, 3), (0.040, 12, 9)]),         # 3 clear, big move
             ("weak_big", [(0.040, 5, 3), (0.040, 11, 9)]),     # 2 clear, big move
             ("decisive", [(0.040, 5, 3), (0.040, 12, 8)]),     # 4 clear, big move
             ("small", [(0.006, 5, 3), (0.006, 11, 9)]))        # 2 clear, 6 ms move
    out = {}
    try:
        for margin, big in ((player.VOTE_MARGIN, player.VOTE_MARGIN_BIG), (1, 1),
                            (player.VOTE_MARGIN, 2)):
            player.VOTE_MARGIN, player.VOTE_MARGIN_BIG = margin, big
            for name, script in cases:
                queue = list(script)
                player.vote_t0 = (lambda dets, notes, lo, hi, q=queue: (*q.pop(0), None))
                lines = []
                lc = player.LiveCorrector([(1.0, 12.0)], 0.0, lines.append, max_corr_up=0.120)
                for _ in range(len(script)):
                    lc.feed(0.0, [(100.0, 300.0)] * 6)
                out[(margin, big, name)] = (lc.committed, round(lc.corr * 1000))
    finally:
        player.vote_t0, player.VOTE_MARGIN, player.VOTE_MARGIN_BIG = real
    shipped = (player.VOTE_MARGIN, player.VOTE_MARGIN_BIG)
    ok = (out[shipped + ("thin",)] == (0, 0)
          and out[shipped + ("g458",)] == (0, 0)
          and out[shipped + ("weak_big",)] == (0, 0)
          and out[shipped + ("decisive",)] == (1, 40)
          and out[shipped + ("small",)] == (1, 6)
          and out[(1, 1, "thin")] == (1, 40)
          and out[(player.VOTE_MARGIN, 2, "g458")] == (1, 40))
    print(f"40 ms 的移动（大票要 {player.VOTE_MARGIN_BIG} 票、小票要 {player.VOTE_MARGIN} 票）："
          f"领先 1 票 {out[shipped + ('thin',)]}、3 票（g458 那一对）{out[shipped + ('g458',)]}、"
          f"2 票 {out[shipped + ('weak_big',)]}、4 票 {out[shipped + ('decisive',)]}；"
          f"6 ms 的移动领先 2 票 {out[shipped + ('small',)]}；"
          f"把两档都压到 1：领先 1 票 {out[(1, 1, 'thin')]}；"
          f"只把大票那档退回 2：g458 那一对 {out[(player.VOTE_MARGIN, 2, 'g458')]}"
          "（提交数, corr ms）")
    print("PART 8 " + ("PASS" if ok else "FAIL"))
    return ok


def part12():
    """The trusted-drift rail: an alias that *wins* its margin is still refused, and says so.

    g458's shape again, but with a decisive margin (12 vs 2): the margin rail passes it, so only the
    drift rail can stop it. The corpus's useful corrections are all <= 23 ms and the two that wrecked
    their runs wanted 160 ms, so a pair agreeing on -163 ms is the field pointing at the neighbouring
    step of a 157 ms staircase. Refused, counted, and logged -- never silently kept, because "kept"
    and "the votes never agreed" read identically in the log. Forcing the rail open has to make the
    same pair commit, which is the counterfactual.
    """
    real_vote, real_trust = player.vote_t0, player.CORR_TRUST_MS
    out = {}
    try:
        for trust in (player.CORR_TRUST_MS, 1e9):
            player.CORR_TRUST_MS = trust
            queue = [(-0.163, 12, 2), (-0.163, 12, 2)]
            player.vote_t0 = (lambda dets, notes, lo, hi, q=queue: (*q.pop(0), None))
            lines = []
            lc = player.LiveCorrector([(1.0, 12.0)], 0.0, lines.append, max_corr_up=0.120)
            for _ in range(2):
                lc.feed(0.0, [(100.0, 300.0)] * 6)
            out[trust] = (lc.committed, round(lc.corr * 1000), lc.refused, list(lines))
    finally:
        player.vote_t0, player.CORR_TRUST_MS = real_vote, real_trust
    shipped = out[player.CORR_TRUST_MS]
    forced = out[1e9]
    told = [l for l in shipped[3] if "trusted drift" in l and "refused" in l]
    ok = (shipped[:3] == (0, 0, 1) and forced[:3] == (1, -45, 0)
          and len(told) == 1 and "-163 ms" in told[0] and "-120 ms" in told[0]
          and f"({player.CORR_TRUST_MS:.0f} ms)" in told[0])
    print(f"12 比 2 的一对都指向 -163 ms：现规则 {shipped[:3]}（提交, corr ms, 不采次数），"
          f"把可信带拆掉后 {forced[:3]}；说明句「{told[0].strip() if told else '没打'}」")
    print("PART 12 " + ("PASS" if ok else "FAIL"))
    return ok


def part9():
    """The retry compensation: an attempt that died asking for the same side teaches the next.

    s291 flew 0066_02 eight times and broke every time, each attempt's votes reading +17..+26 ms
    ("the notes are later than our presses") while the panel's 正推上限 0 refused them one attempt
    at a time -- eight replays of the same clock, because the loop had nothing to learn from. The
    decision is a pure function so the shape of the learning can be pinned without a device: one
    vote is not a pattern, a median on the late side takes one bounded step, a residual takes
    another, an overshoot (negative median) stops it, an aliased outlier may not jump the bound,
    and no round may shift itself past the ceiling.
    """
    import run as run_mod

    cases = [([], 0.0, 0.0), ([30.0], 0.0, 0.0), ([18, 22, 26], 0.0, 20.0), ([17, 19], 20.0, 38.0),
             ([-12, -8], 40.0, 40.0), ([200, 210], 0.0, 20.0), ([20, 20], 50.0, 60.0)]
    got = [(v, b, run_mod.retry_boost(v, b)) for v, b, _ in cases]
    ok = all(round(g, 6) == want for (_, _, g), (_, _, want) in zip(got, cases))
    print("补偿决策（票中位, 已有补偿 -> 新补偿）: "
          + " | ".join(f"{v} +{b:.0f} -> {g:.0f}" for v, b, g in got))
    # The other half: an attempt that died too early to vote (s303: nine kills at +3.9 s, no vote
    # ever cast, the tenth -- past the cap -- voting +30..+43 for the whole song). The place it
    # keeps dying in is the evidence, one untried direction per repeat, both signs before any
    # magnitude, and never the same guess twice.
    tries, order = [], []
    for _ in range(len(run_mod.PLACE_STEPS) + 1):
        step, tries = run_mod.place_boost(True, tries)
        order.append(step)
    steps = order[:-1]
    ok_place = (steps == list(run_mod.PLACE_STEPS) and order[-1] is None
                and run_mod.place_boost(False, [20.0]) == (None, [])
                # both signs before any magnitude, and never a bigger guess than +-60
                and [abs(s) for s in steps].count(20.0) == 2
                and [abs(s) for s in steps].count(40.0) == 2
                and [abs(s) for s in steps].count(60.0) == 2)
    print(f"同点探路（断点不动就一路试）：{order}")
    print("PART 9 " + ("PASS" if ok and ok_place else f"FAIL: {ok} / {ok_place}"))
    return ok and ok_place


def part10():
    """The chart's own event table: skills, fever windows, tempo changes, in ms.

    run.py reads it out of the raw chart beside the hits and hands it to play(), which logs each
    line when the judgement clock reaches it -- the user asked for the skill line by name, and the
    other two ride along because they are the same table. Pinned here: the conversion goes through
    the compiler's own tick_to_ms (so a multi-tempo chart's events land where its notes do), the
    summary counts what it found, and a missing raw chart is no table at all -- never an error.
    """
    import json as _json
    import tempfile
    import run as run_mod

    tmp = tempfile.mkdtemp(prefix="evpin_")
    # 120 BPM for the first 960 ticks (1.0 s at 480 ticks/beat), then 60 BPM: a skill after the
    # change must take the new tempo, not the opening one -- 96 ticks later is 200 ms, not 100.
    _json.dump({"score": {"events": {"bpm": [{"t": 0, "bpm": 120}, {"t": 960, "bpm": 60}],
                                    "skill": [960, 1056], "fever": [[0, 960]]}}},
               open(f"{tmp}/x.raw.json", "w", encoding="utf-8"))
    open(f"{tmp}/x.hits.json", "w").write("[]")
    got = [(round(m), t) for m, t in run_mod.chart_events(f"{tmp}/x.hits.json")[0]]
    want = [(0, "fever 1/1 起（到 +1.0s）"), (1000, "变速 → 60 BPM"), (1000, "技能发动 1/2"),
            (1200, "技能发动 2/2")]
    sm = run_mod.chart_events(f"{tmp}/x.hits.json")[1]
    empty = run_mod.chart_events(f"{tmp}/none.hits.json")
    ok = (got == want and "技能 2 处（1.0/1.2 s）" in sm and "fever 1 段" in sm
          and empty == ([], ""))
    print(f"事件表：{got}; 摘要「{sm}」; 缺 raw 时 {empty}")
    print("PART 10 " + ("PASS" if ok else "FAIL"))
    return ok


def part11():
    """`--retry-anchor` without `--fastcap` is refused, not downgraded to the stale constant.

    The anchor's press+delta is the number that wandered +95/+118 ms run to run (t14/t15: 995 GOOD
    on a chart that APs all morning), and only the relock vote can measure the truth -- which needs
    faster frames than `screencap` delivers. The run used to print "relock skipped" and play on that
    bad clock anyway. PART 11 runs the real `run.main` on both flag pairs against a nonexistent
    chart: the refused one has to stop at the guard with no round log written, the paired one has to
    get past it and die on the missing file.
    """
    import contextlib
    import io
    import os

    import run as run_mod

    def call(argv):
        tag = argv[argv.index("--tag") + 1]
        out = io.StringIO()
        real = sys.argv
        sys.argv = ["run.py"] + argv
        try:
            with contextlib.redirect_stdout(out):
                try:
                    rc = run_mod.main()
                except FileNotFoundError:
                    rc = "past-the-guard"
        finally:
            sys.argv = real
        made = [p for p in os.listdir(run_mod.RUNS) if p.startswith(tag + ".")]
        return rc, out.getvalue(), made

    refused, rtext, rlogs = call(["--retry-anchor", "nope.hits.json", "--tag", "pushcap11a"])
    paired, ptext, plogs = call(["--retry-anchor", "--fastcap", "nope.hits.json", "--tag", "pushcap11b"])
    for p in plogs:                                   # the round log the paired call opened, then died on
        os.remove(os.path.join(run_mod.RUNS, p))
    ok = (refused == 1 and "fastcap" in rtext and not rlogs
          and paired == "past-the-guard" and "本局不开始" not in ptext)
    print(f"只给 --retry-anchor：返回 {refused}、说了快帧要求={'fastcap' in rtext}、"
          f"留下文件 {rlogs or '无'}；一起给 --fastcap：走到读谱面才失败（={paired}）、"
          f"没被这道闸拦住 -> {'PASS' if ok else 'FAIL'}")
    return ok


def part13():
    """The 多人 side rule: with the window's flag on, a vote that spends the correction back is kept.

    mp4's shape, in miniature: a -34 ms correction is in place (the live rounds' opening window took
    -45 ms) and the field's later plateau then reads the other way (+139 ms there). With the flag off
    that pair commits the correction straight back -- at a 0 ms cap it lands on 0, which is exactly the
    undo the live round suffered -- while with the flag on the side is what bounds the correction and
    the pair is refused with a line saying so. The control matters as much as the guard: the same feed
    *without* the flag must still spend the correction back, because on a single-player round the push
    cap is the sanctioned way to do that and a rule overriding it would be a second, hidden cap.
    """
    fed = [(-0.034, 2), (LATE, 2)]
    guarded, glines = run(fed, 0.0, open_trust=True)
    plain, _ = run(fed, 0.0)
    kept = [l for l in glines if "opening window already took -> kept" in l]
    ok = (guarded.committed == 1 and abs(guarded.corr * 1000 + 34.0) < 1e-6
          and guarded.refused == 1 and len(kept) == 1
          and plain.committed == 2 and abs(plain.corr) < 1e-9)
    print(f"先 {fed[0][0] * 1000:+.0f} ms 再反向 {LATE * 1000:+.0f} ms、cap 0："
          f"窗口开 commits={guarded.committed} corr={guarded.corr * 1000:+.1f} ms "
          f"refused={guarded.refused}；窗口关 commits={plain.committed} "
          f"corr={plain.corr * 1000:+.1f} ms")
    print("PART 13 " + ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    ok1, lines1 = part1()
    _cap_line = next((l for l in lines1 if "capped at" in l), "")
    sys.exit(0 if (ok1 and part2() and part3() and part4(_cap_line) and part5() and part6()
                  and part7() and part8() and part9() and part10() and part11()
                  and part12() and part13()) else 1)
