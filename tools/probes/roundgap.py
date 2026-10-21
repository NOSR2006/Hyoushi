"""演出间隔：间隔从「走回乐曲选择页」起算，「停止」要能立刻打断。

The feature looks two lines long -- sleep, then start the next round -- and every way of writing
those two lines gets one of three things wrong. Waiting from when run.py *exits* silently adds the
result walk and the record write onto every interval the user set (a "5 分钟" that is really 5:20).
Waiting without watching 停止 turns a two-second button press into a five-minute hang. And taking
the anchor from the log's prose about pages is unsound: the same page appears in two renderings, one
of which is "连续四次读不到变化" -- stuck, not arrived. So run.py reports the arrival on its own
machine channel (`#ATSELECT#`, only on a successful walk-back), and the panel counts from there.

PART 1: `panel_core.gap_wait` -- the arithmetic, without a window: 0 = 关, the interval minus what
        has already elapsed, never below the round's closing beat, and never a second full interval
        when the anchor is older than the interval.
PART 2: the field is read in two places on purpose -- the panel's own number field owns the clamp
        (`flet_gui.clamp_num`, because a text field happily holds "abc" and 999), and
        `RunOrchestrator.gap_min()` owns the hand-edited-state-file case. Both ends are measured
        here, without a window: the arithmetic of the clamp, and the value the run would really use.
PART 3: teeth on the two ways this rots -- the token emitted on a *failed* walk-back, and the anchor
        taken from log prose instead of the machine line, plus the per-round reset that stops a
        round which never walked home from borrowing the previous round's anchor.

The wait itself (停止 打断、收尾那一拍、倒计时) is measured in `fletpanel.py` PART 4, where there is
a real window and a real `stop_flag` -- 这里不重复那几条，两个探针各测各的。

Run from the repo root:  python tools/probes/roundgap.py
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

RUN_SRC = open(os.path.join(TOOLS, "run.py"), encoding="utf-8").read()
CORE_SRC = open(os.path.join(TOOLS, "panel_core.py"), encoding="utf-8").read()

FAILS: list[str] = []


def check(label, cond, extra=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(label)
    return cond


def part1(core):
    g, floor = core.gap_wait, core.GAP_FLOOR_S
    cases = [(g(0, 0), floor, "关"),
             (g(5, 0), 300.0, "整间隔"),
             (g(5, 60), 240.0, "已经过了 1 分钟"),
             (g(5, 360), floor, "锚点比间隔还旧：不再等第二个间隔"),
             (g(0.5, 0), 30.0, "收小数")]
    print("PART 1 gap_wait 的算术")
    for got, want, why in cases:
        check(f"{why}: {got:g} == {want:g}", abs(got - want) < 1e-6)
    return True


def part2(core, G):
    """字段的读法。夹取在视图层（`flet_gui.clamp_num`），容错在核心（`RunOrchestrator.gap_min`）
    —— 两件事两个地方，所以两处都要量。

    上界原本只活在 Qt 的 `QDoubleSpinBox.setRange` 上；Qt 删掉之后这条搬到了
    `flet_gui.NUM_RANGE` + `clamp_num`（它真的接在输入框上是 `fletpanel.py` PART 6 量），
    这里量的是算术本身与「核心最终拿到的那个数」。
    """
    print("PART 2 读字段")
    for text, want in (("7", 7.0), ("0", 0.0), ("0.5", 0.5), ("-4", 0.0),
                       ("999", float(core.GAP_MAX_MIN))):
        got = G.clamp_num("gap_min", text)
        check(f"输入框里写 {text} 分 -> 收成 {got:g}（应为 {want:g}）", got == want)
    check("读不成数字就落回给的兜底值（不是抛异常、也不是 0 硬编码）",
          G.clamp_num("gap_min", "abc", 3.5) == 3.5
          and G.clamp_num("gap_min", "", 0.0) == 0.0)
    # 手改过的状态文件：输入框不在场，容错只能由核心负责 —— 上下界两头都要兜住。
    c = core.RunOrchestrator(core.read_json(core.STATE, {}))
    keep = c.state.get("defaults")
    try:
        c.state["defaults"] = {**(keep or {}), "gap_min": "abc"}
        check("状态文件里写着 abc -> 核心读回 0.0 而不是抛异常",
              c.gap_min() == 0.0, f"{c.gap_min()!r}")
        c.state["defaults"] = {**(keep or {}), "gap_min": "-3"}
        check("状态文件里写着 -3 -> 核心读回 0.0", c.gap_min() == 0.0, f"{c.gap_min()!r}")
        c.state["defaults"] = {**(keep or {}), "gap_min": "999"}
        check("状态文件里写着 999 -> 核心也夹到 GAP_MAX_MIN（手改文件不许变成 999 分钟的等待）",
              c.gap_min() == float(core.GAP_MAX_MIN), f"{c.gap_min()!r}")
    finally:
        c.state["defaults"] = keep
    return True


def part3():
    print("PART 3 锚点来源与走页保证")
    # The token must sit in the success branch only: a walk-back that failed has not arrived, and
    # waiting off a false "arrived" would start the next round on top of a stuck screen. Since
    # 2026-10-03 the walk lives in `run.leave_at_select` (every way out of a round calls it, the
    # happy path and the `finally` alike), so this reads that function's own two branches.
    body = RUN_SRC[RUN_SRC.index("def leave_at_select"):][:2000]
    check("run.py 的 #ATSELECT# 只在「走回成功」那一支",
          bool(re.search(r"if start_live\(inj, log=log, timeout=timeout, stop_at_select=True"
                         r"(?:, multi=multi)?\):\s*\n"
                         r"\s*log\(\"#ATSELECT#\"\)\s*\n\s*return True\s*\n"
                         r"\s*log\(\"!! 没能走回选曲页", body)))
    # ... and every round must reach it: the happy path sets `left`, the `finally` walks when it
    # did not. A failure that skipped the walk left the game where it stopped, which is how one
    # bad round became two (g274 -> g275); `recoverwalk` drives the behaviour, and the guarantee
    # itself has to be on by default here.
    check("放弃的局也走回选曲页（finally 那道保证在，且默认开着）",
          bool(re.search(r"finally:\s*\n\s*if WALK_HOME_ON_ANY_EXIT and not args\.stay_on_result "
                         r"and not left:", RUN_SRC))
          and "\nWALK_HOME_ON_ANY_EXIT = True" in RUN_SRC)
    # 锚点从机器行来，不从「导航：乐曲选择页」那句散文来 —— 同一个页面在日志里还有一种写法是
    # 「连续四次读不到变化」，那是卡住不是到达。
    sets = re.findall(r"self\.at_select = (?!None)", CORE_SRC)
    check("面板里锚点只被赋值一处，且认的是 #ATSELECT# 这一行",
          len(sets) == 1 and 'if line == "#ATSELECT#":' in CORE_SRC, f"赋值 {len(sets)} 处")
    check("锚点不从导航措辞里取",
          not re.search(r"at_select = .*导航|at_select = .*NAV", CORE_SRC))
    # 每轮清零：一个从没走回选曲页的轮次不许借上一轮的锚点 —— 那会让「没走回去」看起来像
    # 「早就回去了」，于是间隔被整个跳过。
    check("每轮开始时锚点被清零", "self.at_select = None" in CORE_SRC)
    return True


def main():
    import panel_core as core

    tmp = tempfile.mkdtemp(prefix="bang_probe_gap_")
    real_state = core.STATE
    core.STATE = os.path.join(tmp, "gui_state.json")
    try:
        # 只 import 视图层拿 `clamp_num` 与 `NUM_RANGE`，不起窗口、不要桌面会话。
        import flet_gui as G

        part1(core)
        part2(core, G)
        part3()
    finally:
        core.STATE = real_state
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print(f"PART 探针 FAIL：{len(FAILS)} 项")
        for f in FAILS:
            print("  -", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
