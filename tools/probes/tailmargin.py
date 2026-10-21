"""The tail margin is one number in one place, and the release really moves with it.

`player.TAIL_MARGIN_MS` (2026-10-09) is how long a hold is kept down past its own tail. The release
is scheduled at `tail + margin` in compiled chart time, and the link judges a press ~6 ms before the
action it was scheduled for (a tap's action is planned at note - 20 while the clean rounds' `chain
cal` reads -26 ms), so 20 keeps the finger down ~14 ms *past* the hold's last judged object -- #111's
rule puts that object exactly on the tail. A same-night raise to 45 was reverted: its premise ("the
release lands 22 ms before the object") was a 45 ms timebase artifact in
`research/experiments/objmap.py`'s ref_of(), and 45 puts the release at +39 ms, i.e. 11 ms from the
±50 wall, for no measured gain (40 nominal rounds at 45 lost 8/35 single notes; the margin-20 rounds
lost 2/6; the 123-round g* baseline at 20 lost 13/123). The constant has to be reachable from the CLI
so a margin A/B can be run inside one night (`--tail-margin`), which is how that was measured.

What this pins, in both directions:

  PART 1  the constant is 20.0, and it is actually *used*: `build_actions`' long branch, the intro
          shotgun's targets, and `run.py`'s `--tail-margin` (argument + the write into the module
          global + the default kept for the log line). Five mutants must each turn it red.
  PART 2  the release moves with it: on 0056_03, 141 of the 506 releases change and the last action
          moves +25.0 ms, while the action count and the slot bookkeeping do not change at all --
          and forcing the constant back to 20 reproduces the old chart byte for byte (so the
          instrument is reading the constant, not something else).
  PART 3  the ghost side effect is exactly the two moves in 0071_03 that AGENTS.md claims, the
          library-wide sweep sees them and nothing else, and the trigger is the margin (raising
          `GHOST_CLEAR_MS` past any tail removes them again).
  PART 4  the tail flick of a hold carries its own lead (`player.TAIL_FLICK_LEAD_MS`, shipped
          10.0 since 2026-10-19 -- the game reads that one gesture ~20 ms SLOW and half of it is
          compensated; 20.0 was the first cut, the user asked for 10). The two lateral steps really
          move (`tail - 10 + 2 / + 16`), the release really moves with them and still lands after
          its own flick node, the trail point the swipe replaces is accounted for, and four
          mutants (constant, the lead in the tail clock, the CLI switch, run.py's write into the
          module global) each turn it red.

No device, no live, no window.  Run from the repo root:  python tools/probes/tailmargin.py
"""
import ast
import contextlib
import io
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import player                                                # noqa: E402
import rlog                                                  # noqa: E402

CHARTS = Path(rlog.CHARTS)
PLAYER_SRC = Path(ROOT / "tools" / "player.py").read_text(encoding="utf-8")
RUN_SRC = Path(ROOT / "tools" / "run.py").read_text(encoding="utf-8")

# the four sites the constant has to reach, as literal source lines
SITES = (
    ('end = max(h["end_ms"] + TAIL_MARGIN_MS, start + MIN_HOLD_MS)', "build_actions 的长条抬手"),
    ('max(h["end_ms"] + TAIL_MARGIN_MS - lead,', "开场霰弹枪的 targets"),
    ("player.TAIL_MARGIN_MS = float(args.tail_margin)", "run.py 写进模块全局"),
    ('ap.add_argument("--tail-margin"', "run.py 的开关"),
)

MUTANTS = (
    ("TAIL_MARGIN_MS = 20.0", "TAIL_MARGIN_MS = 45.0", "把常量改成 45"),
    ('end = max(h["end_ms"] + TAIL_MARGIN_MS, start + MIN_HOLD_MS)',
     'end = max(h["end_ms"] + 20.0, start + MIN_HOLD_MS)', "长条抬手写死成 20、不再读常量"),
    ('max(h["end_ms"] + TAIL_MARGIN_MS - lead,', 'max(h["end_ms"] + 20.0 - lead,',
     "霰弹枪 targets 写死成 20、不再读常量"),
    ("player.TAIL_MARGIN_MS = float(args.tail_margin)",
     "player.TAIL_MARGIN_MS = TAIL_MARGIN_DEFAULT", "run.py 不再采纳 --tail-margin"),
    ('ap.add_argument("--tail-margin"', 'ap.add_argument("--tail-margin-x"', "开关改名"),
)


def shipped(src, name="TAIL_MARGIN_MS"):
    """The module-level `<name> = <number>` a source declares, or None."""
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            if isinstance(node.value, ast.Constant):
                return float(node.value.value)
    return None


def wired(player_src=PLAYER_SRC, run_src=RUN_SRC):
    """True when the constant is declared as 20.0 and every site reads it."""
    if shipped(player_src) != 20.0:
        return False
    for line, _what in SITES:
        src = player_src if line in PLAYER_SRC else run_src
        if line not in src:
            return False
    return True


def part1():
    ok = wired()
    print(f"常量 {shipped(PLAYER_SRC)}（要 20.0）＋ 四个使用点都在 = {ok}")
    teeth = []
    for old, new, why in MUTANTS:
        src = PLAYER_SRC if old in PLAYER_SRC else RUN_SRC
        other = RUN_SRC if src is PLAYER_SRC else PLAYER_SRC
        assert old in src, why
        mutant = src.replace(old, new, 1)
        if src is PLAYER_SRC:
            red = not wired(mutant, RUN_SRC)
        else:
            red = not wired(PLAYER_SRC, mutant)
        teeth.append((why, red))
        print(f"  牙：{why} → {red}（要 True）")
    ok = ok and all(red for _w, red in teeth)
    print("PART 1 " + ("PASS" if ok else "FAIL"))
    return ok


def load(cid):
    with io.open(CHARTS / (cid + ".hits.json"), encoding="utf-8") as fh:
        return json.load(fh)


def build(hits, margin, ghost=None, lead=None):
    old_m, old_g, old_l = player.TAIL_MARGIN_MS, player.GHOST_CLEAR_MS, player.TAIL_FLICK_LEAD_MS
    player.TAIL_MARGIN_MS = margin
    if ghost is not None:
        player.GHOST_CLEAR_MS = ghost
    if lead is not None:
        player.TAIL_FLICK_LEAD_MS = lead
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            acts = player.build_actions(hits, player.JUDGE_Y, 20.0, 45.0, 90)[0]
    finally:
        player.TAIL_MARGIN_MS, player.GHOST_CLEAR_MS = old_m, old_g
        player.TAIL_FLICK_LEAD_MS = old_l
    return acts, buf.getvalue()


def releases(acts):
    return sorted(t for t, op, *_ in acts if op == "up")


def part2():
    hits = load("0056_03")
    a20, t20 = build(hits, 20.0)
    a45, t45 = build(hits, 45.0)
    r20, r45 = releases(a20), releases(a45)
    moved = sum(1 for a, b in zip(r20, r45) if abs(a - b) > 1e-6)
    last20, last45 = max(t for t, *_ in a20), max(t for t, *_ in a45)
    # 3206, the same count as before the tail-flick lead existed: at 10 ms no trail point of this
    # chart falls inside the window the swipe replaces (the 20 ms first cut dropped 25 of them).
    counts = len(a20) == len(a45) == 3206 and len(r20) == len(r45) == 506
    clean = "slot" not in t20 and "slot" not in t45
    shift = abs((last45 - last20) - 25.0) < 1e-6
    # 150 rather than the 141 this pinned before the tail-flick lead: the release is now
    # `max(end - 10, tail + 30, start + MIN_HOLD)`, so nine more holds are pinned by their own
    # flick node instead of the margin and stop moving with it.
    moves = moved == 150
    # tooth: a stray module value must not leak into the instrument (build() sets the constant
    # itself), and the global must come back untouched
    old = player.TAIL_MARGIN_MS
    player.TAIL_MARGIN_MS = 45.0
    try:
        a_old, _t = build(hits, 20.0)
        leaked = player.TAIL_MARGIN_MS != 45.0
    finally:
        player.TAIL_MARGIN_MS = old
    back = a_old == a20 and not leaked
    print(f"0056_03：动作 {len(a20)}→{len(a45)}（要 3206）、抬手 {len(r20)}→{len(r45)}（要 506）、"
          f"overrun 0/0、末动作 {last20:.1f}→{last45:.1f}（要 +25.0）")
    print(f"   随留白移动的抬手 {moved}/506（要 150）；模块里先塞 45 也照样复现留白 20 的谱面 = {back}"
          "（要 True）")
    ok = counts and clean and shift and moves and back
    print("PART 2 " + ("PASS" if ok else "FAIL"))
    return ok


def ghost_delta(hits, margin, ghost=1.0e9):
    """The moves the release ghost adds at this margin: (on - off) as a Counter."""
    off, _ = build(hits, margin, ghost=ghost)
    on, _ = build(hits, margin)
    return Counter(on) - Counter(off)


def part3():
    pinned45 = {
        "0056_03": Counter({(70919.398, "move", 2, 583.0, 570.0): 1,
                            (70953.283, "move", 2, 513.0, 570.0): 1}),
        "0071_03": Counter({(59790.638, "move", 1, 583.0, 570.0): 1,
                            (59797.638, "move", 1, 513.0, 570.0): 1}),
        # Added when 0111_03 entered the library: a trace whose head crosses two parked fingers at
        # 88.929 s, so both step off and back. Independent of the tail-flick lead (lead 0 counts
        # the same 4), i.e. corpus growth, not this change.
        "0111_03": Counter({(88929.371, "move", 0, 712.0, 570.0): 1,
                            (88929.371, "move", 1, 712.0, 570.0): 1,
                            (88936.371, "move", 0, 642, 570.0): 1,
                            (88936.371, "move", 1, 642, 570.0): 1}),
    }
    seen45, seen20, extra45 = {}, {}, []
    for name in sorted(os.listdir(CHARTS)):
        if not name.endswith(".hits.json"):
            continue
        cid = name[: -len(".hits.json")]
        try:
            hits = load(cid)
        except Exception:
            continue
        d45 = ghost_delta(hits, 45.0)
        if d45:
            seen45[cid] = d45
        if cid not in pinned45 and d45:
            extra45.append(cid)
        d20 = ghost_delta(hits, 20.0)
        if d20:
            seen20[cid] = d20
    named = all(seen45.get(c) == d for c, d in pinned45.items())
    only = not extra45
    pinned20 = seen20 == {"0056_03": pinned45["0056_03"]}
    print(f"让位 ghost 在留白 45：{sum(len(d) for d in seen45.values())} 个 move、"
          f"{len(seen45)} 张谱 {sorted(seen45)}（要 8 / 3 张，且就是 0056_03、0071_03 与 0111_03）")
    print(f"   留白 20：{sum(len(d) for d in seen20.values())} 个 move、{len(seen20)} 张谱 "
          f"{sorted(seen20)}（要 2 / 1 张）；两条钉住的 move 逐字对上 = {named}")
    ok = named and only and pinned20
    print("PART 3 " + ("PASS" if ok else "FAIL"))
    return ok


# ---- PART 4: the tail flick's own lead --------------------------------------------------------

# the four sites the new constant has to reach, as literal source lines
TF_SITES = (
    ('tail = ef["t_ms"] - TAIL_FLICK_LEAD_MS', "build_actions 的尾滑键时钟"),
    ("if TAIL_FLICK_LEAD_MS > 0.0:", "被滑键顶掉的那一帧 trail"),
    ('ap.add_argument("--tail-flick-lead"', "run.py 的开关"),
    ("player.TAIL_FLICK_LEAD_MS = float(args.tail_flick_lead)", "run.py 写进模块全局"),
)

TF_MUTANTS = (
    ("TAIL_FLICK_LEAD_MS = 10.0", "TAIL_FLICK_LEAD_MS = 0.0", "把常量改成 0"),
    ('tail = ef["t_ms"] - TAIL_FLICK_LEAD_MS', 'tail = ef["t_ms"]', "尾滑键不再提前"),
    ('ap.add_argument("--tail-flick-lead"', 'ap.add_argument("--tail-flick-lead-x"', "开关改名"),
    ("player.TAIL_FLICK_LEAD_MS = float(args.tail_flick_lead)",
     "player.TAIL_FLICK_LEAD_MS = TAIL_FLICK_LEAD_DEFAULT", "run.py 不再采纳开关"),
)


def tf_wired(player_src=PLAYER_SRC, run_src=RUN_SRC):
    """True when the tail-flick lead is declared as 10.0 and every site reads it."""
    if shipped(player_src, "TAIL_FLICK_LEAD_MS") != 10.0:
        return False
    for line, _what in TF_SITES:
        src = player_src if line in PLAYER_SRC else run_src
        if line not in src:
            return False
    return True


def part4():
    ok = tf_wired()
    print(f"尾滑键常量 {shipped(PLAYER_SRC, 'TAIL_FLICK_LEAD_MS')}（要 10.0）＋ 四个使用点都在 = {ok}")
    for old, new, why in TF_MUTANTS:
        src = PLAYER_SRC if old in PLAYER_SRC else RUN_SRC
        assert old in src, why
        mutant = src.replace(old, new, 1)
        if src is PLAYER_SRC:
            red = not tf_wired(mutant, RUN_SRC)
        else:
            red = not tf_wired(PLAYER_SRC, mutant)
        print(f"  牙：{why} → {red}（要 True）")
        ok = ok and red

    hits = load("0056_03")
    tails = [h for h in hits if h.get("end_flick")]
    aN, _ = build(hits, 20.0, lead=10.0)
    a0, _ = build(hits, 20.0, lead=0.0)
    setN = {(round(t, 3), op, round(x, 1)) for t, op, _s, x, _y in aN}
    set0 = {(round(t, 3), op, round(x, 1)) for t, op, _s, x, _y in a0}
    upsN = {round(t, 3) for t, op, *_ in aN if op == "up"}
    hitN = hit0 = late = 0
    for h in tails:
        ef = h["end_flick"]
        sh = h.get("time_shift_ms", 0.0)
        fx0 = h["path"][-1]["x"]
        for dt, dx in ((2.0, 45.0), (16.0, 90.0)):
            t = round(ef["t_ms"] - 10.0 + dt + sh, 3)
            if (t, "move", round(fx0 + dx, 1)) in setN:
                hitN += 1
            if (round(ef["t_ms"] + dt + sh, 3), "move", round(fx0 + dx, 1)) in set0:
                hit0 += 1
        want = round(max(h["end_ms"] + 20.0 - 10.0, ef["t_ms"] - 10.0 + 30.0,
                         h["t_ms"] - 20.0 + player.MIN_HOLD_MS) + sh, 3)
        if want in upsN and want >= ef["t_ms"] + sh:
            late += 1
    # the tooth: the same probe on the lead-0 list must find none of the moved steps
    tooth = hitN == 2 * len(tails) and all(
        (round(h["end_flick"]["t_ms"] - 8.0 + h.get("time_shift_ms", 0.0), 3), "move",
         round(h["path"][-1]["x"] + 45.0, 1)) not in set0 for h in tails)
    dropped = len(a0) - len(aN)
    print(f"0056_03 的 {len(tails)} 根尾滑键：两脚步子提前 10 ms 都在 {hitN}/{2 * len(tails)}、"
          f"留白 0 时在旧位置的 {hit0}/{2 * len(tails)}")
    print(f"   抬手跟着走、且仍落在自己那颗 flick 之后 {late}/{len(tails)}；"
          f"被顶掉的 trail 帧 {dropped}；牙（提前 10 ms 的步子不许出现在 lead 0 里）= {tooth}")
    ok = ok and hitN == 2 * len(tails) and hit0 == 2 * len(tails) and late == len(tails) \
        and dropped == 0 and tooth
    print("PART 4 " + ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    sys.exit(0 if (part1() and part2() and part3() and part4()) else 1)
