"""Every line of the runner's log gets the level it deserves -- and only one `!!` per line.

The panel had two log problems reported on 2026-10-03. First, colour: the runner's lines arrived as
one flat block. The only severity the panel looked at was a line *starting* with `!!` -- and every
runner line starts with its stamp, so that branch was dead for all of them (the 断键 lines missed on
a second count, being indented sub-lines of the round that raised them). A lost key therefore
reached the log in ordinary ink with a literal `!!` still glued to it, while 142 HUD-candidate lines
a run shouted in the same colour as a conclusion. Second, spacing: the stamp added its own space in
front of lines that already open with an indent, so the text started at two different columns. That
was corrected once (顶格 1 格、子行 2 格) and corrected again the same day -- the user
wanted the left edge *aligned*, so the column now takes exactly one space and the runner's indent is
dropped at display time; what the indent used to say is said by the dim level.

Both are fixed at the one place the runner's text enters the panel (`panel_core.child_line`) and at
the one place the stamp is written (`rlog.stamp`), and both are graded by shape rather than by asking
the runner to declare a level per line -- the wording is already shared between the two sides
through rlog's RENDER table, so a shape is a stable key.

PART 1: a table of representative lines (one per family the runner actually prints) lands on the
        level the panel colours: hdr / ok / err / dim / default.
PART 2: the whole local corpus replayed -- no payload keeps a `!!`, no line arrives ungraded, and
        the process families really do sink to dim (the point is that a night of watching the log
        leaves only conclusions in normal ink).
PART 3: teeth -- the old prefix test is replayed on the same lines and is shown to miss the
        indented severity marker and to leave it printed.
PART 4: the stamp column -- exactly one space after the time for every line, indent gone, body
        otherwise untouched; the corpus re-stamped to prove it, and both earlier formatters replayed
        (three gaps, then two) to show the check has teeth.
PART 5 曾经在这里：一行日志落到屏幕上的代价与「视图自己裁到 LOG_WINDOW」。它量的是一个 Qt
        文本控件（`maximumBlockCount`），随 Qt 一起消失 —— 搬过来的那几条不变量（存储上限
        LOG_KEEP、视图上限 LOG_WINDOW、最新在底、最老被裁、`run_start` 跟着退、每行 < 0.5 ms）
        现在在 `fletpanel.py` PART 8，那里有真面板、量的也是真控件。

Parts 1-4 need no window: they read panel_core.child_line and rlog.stamp, plus the .out files the
runner left behind (skipped with a note when they are not there -- they are not committed).

Run from the repo root:  python tools/probes/logclass.py
"""

import glob
import os
import re
import sys

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../tools
ROOT = os.path.dirname(TOOLS)                                          # the repo root
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(TOOLS, "probes"))
import panel_core as core  # noqa: E402
import rlog  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

STAMP = re.compile(r"^\d\d:\d\d:\d\d")

# (line as the runner prints it, expected kind). The lines are copied from real 局 output.
EXPECT = (
    ("23:26:15 随机选曲：起死開戦 · HARD · 375 notes", "log_hdr"),
    ("23:26:15 链路校准：文件里 -10 ms（2026-10-03 09:17:06）→ 有效偏移 +45 ms（名义 +55）", "log_hdr"),
    ("23:30:02 锚定：重锁成功 t0=47618.053（確定 +0.347s，比 press+delta +97 ms，24 票）", "log_ok"),
    ("23:30:02 注入完成 2739/2739（通道断连 0 次）", "log_ok"),
    ("23:30:02 注入完成 2739/2739（通道断连 2 次）", "log"),
    ("23:30:02 HUD 计数器（总数仍以结果页为准）：GREAT 0 GOOD 0 BAD 0 MISS 0（80 个候选没站稳）", "log_ok"),
    ("23:30:02 HUD 计数器（总数仍以结果页为准）：GREAT 2 GOOD 0 BAD 0 MISS 0", "log"),
    ("23:30:02 ALL PERFECT（判定 843/843、combo 843、score 5168071）", "log_ok"),
    ("23:30:02 开打：t0=47618.008，偏移 +45 ms", "log"),
    ("23:30:02 谱面：375 音符 → 2739 动作 / 6 指位", "log"),
    ("23:30:02 已进入 LIVE（字段 47614.644）", "log"),
    ("23:30:02 曲终：穿过 LIVE FINISH", "log"),
    ("23:26:29 导航：乐曲选择页", "log_dim"),
    ("23:26:29 HUD 计数器变化 GREAT 第 3 次 @host 47680.1，全局第 121 个判定物 → D:\\x\\hud.png", "log_dim"),
    ("23:26:29 调度误差：min 0.0 p50 0.1 p90 0.3 max 1.2 ms", "log_dim"),
    ("23:26:29   fire 400/2739 @chart +12.4s  late p50 +0.0 max +3.1 ms  corr +10 ms", "log_dim"),
    ("23:26:29   hud: GREAT at host [47680.1, 47680.2] 被edge闸门弃掉 -> D:\\x\\hud.png", "log_dim"),
    ("23:26:29   screen: 选曲页", "log_dim"),
    ("23:26:29   random roll 3: pressed 随机选曲", "log_dim"),
    ("23:26:29 结算页 → D:\\CodeX\\Bang\\research\\result/result_s306.png", "log_dim"),
    ("23:26:29 结果已写入 D:\\CodeX\\Bang\\research\\results.jsonl（与面板同源）", "log_dim"),
    ("23:26:29   本轮中止的取证已改名 *-aN（dets/relock/hud）", "log_dim"),
    ("23:26:29 product: MuMuPlayer-12.0-240801", "log_dim"),
    ("23:26:29 connect not same day", "log_dim"),
    ("23:26:29   roll 3 of 5, ncc 0.18, gap 2.4", "log_dim"),
    ("23:26:29 !! 断AP：GREAT @host [47680.1, 47680.2]，第 2/9 次中途重开本局，免费", "log_err"),
    ("23:26:29   !! 断键（GREAT）@host 47680.1 = chart +65.6s，停发剩余 12 个动作", "log_err"),
    # 从 rlog.stamp 对齐之后，演奏器交出来的就是下面这些没有缩进的样子；上面那些带缩进的留着，
    # 因为判据要同时吃得住库里那 132 局历史文件。
    ("23:26:29 fire 400/2739 @chart +12.4s  late p50 +0.0 max +3.1 ms  corr +10 ms", "log_dim"),
    ("23:26:29 hud: GREAT at host [47680.1, 47680.2] 被edge闸门弃掉 -> D:\\x\\hud.png", "log_dim"),
    ("23:26:29 screen: 选曲页", "log_dim"),
    ("23:26:29 取证已改名 *-a1（dets/relock/hud）", "log_dim"),
    ("23:26:29 技能发动 3/5 @chart +43.9s", "log"),
    ("23:26:29 fever 2/3 起（到 +54.2s） @chart +43.9s", "log"),
    ("23:26:29 !! 断键（GREAT）@host 47680.1 = chart +65.6s，停发剩余 12 个动作", "log_err"),
)


def _strip(line):
    """_child_line is handed the line exactly as the runner printed it -- stamp and all."""
    return line


def _leaked(text):
    """Still opening with the severity marker. `!!` inside a title is not a marker: the band is
    called MyGO!!!!!, and the first corpus pass called every one of its rounds a leak."""
    return bool(re.match(r"^(?:\d\d:\d\d:\d\d )?\s*!!", text))


def part1():
    bad = []
    for line, want in EXPECT:
        got, text = core.child_line(_strip(line))
        if got != want:
            bad.append(f"{line[:38]}… -> {got}（应为 {want}）")
        if _leaked(text):
            bad.append(f"标记漏进正文：{text[:44]}…")
        if line.startswith("23:26:29   !!") and not text.startswith("23:26:29   "):
            bad.append(f"缩进被吃掉了：{text[:34]}…")
    print(f"PART 1 分级：{len(EXPECT)} 行样本，判错 {len(bad)}"
          + "".join("\n     " + b for b in bad[:6]))
    print("PART 1 " + ("PASS" if not bad else "FAIL"))
    return not bad


def _corpus():
    # 2026-10-20 目录收口：成批日志的落点是 research/runs/<tag>.out（旧的在 research/ 根上，
    # 一并读，兼容还没搬完的树）。
    return sorted(glob.glob(os.path.join(ROOT, "research", "*.out"))
                  + glob.glob(os.path.join(ROOT, "research", "runs", "*.out")))


def part2():
    files = _corpus()
    if not files:
        print("PART 2 本地没有 research/runs/*.out（这些文件不进 git），跳过整库重放")
        return True
    from collections import Counter
    kinds, leaks, ungraded = Counter(), [], 0
    for f in files:
        for raw in open(f, encoding="utf-8", errors="replace"):
            line = _strip(raw.rstrip("\r\n"))
            if not line or line.startswith("#") or line.startswith("RESULT "):
                continue
            kind, text = core.child_line(line)
            kinds[kind or "log"] += 1
            if _leaked(text):
                leaks.append(line[:60])
            if kind not in ("log", "log_err", "log_ok", "log_hdr", "log_dim"):
                ungraded += 1
    tot = sum(kinds.values())
    dim = kinds["log_dim"] / tot
    err = kinds["log_err"]
    print(f"PART 2 重放 {len(files)} 局、{tot} 行："
          + "，".join(f"{k} {kinds[k]}" for k in
                      ("log_hdr", "log_ok", "log", "log_dim", "log_err"))
          + f"；过程行占 {dim:.0%}")
    bad = []
    if leaks:
        bad.append(f"{len(leaks)} 行仍带着 !! 标记，例如 {leaks[0]!r}")
    if ungraded:
        bad.append(f"{ungraded} 行落在未知等级")
    if dim < 0.4:
        bad.append(f"过程行只占 {dim:.0%} -- 分级没有把噪声压下去")
    if err == 0:
        bad.append("整库没有一行 err，严重度判据失效")
    print("PART 2 " + ("PASS" if not bad else "FAIL " + "; ".join(bad)))
    return not bad


def part3():
    """The old test, replayed: `text.startswith('!!')` on the whole line -- which never matched,
    because every runner line opens with its stamp. The indented 断键 lines missed on a second
    count. Both cases are shown here, so the check is seen to be about something."""
    def old(text):
        return ("log_err", text[2:].strip()) if text.startswith("!!") else ("log", text)

    flat = "23:26:29 !! 断AP：GREAT @host [47680.1, 47680.2]，第 2/9 次中途重开本局，免费"
    indented = "23:26:29   !! 断键（GREAT）@host 47680.1 = chart +65.6s，停发剩余 12 个动作"
    got = [(old(t), core.child_line(t)) for t in (flat, indented)]
    teeth = all(o[0] == "log" and _leaked(o[1]) and n[0] == "log_err" and not _leaked(n[1])
                for o, n in got)
    for (okind, otext), (nkind, ntext) in got:
        print(f"PART 3 旧判据 {okind} 且标记留着：{otext[:34]}…\n"
              f"        新判据 {nkind} 且标记剥掉、时间列与缩进不动：{ntext[:34]}…")
    print("PART 3 " + ("PASS" if teeth else "FAIL"))
    return teeth


def part4():
    """One column, one gap. The indent is the runner's, not the display's.

    Two previous formatters are replayed here as the teeth: the original added its own space in
    front of an indented line (three gaps), and the first fix let the line's depth through (two
    gaps at column 10, one at column 9 -- ragged). Both are shown to miss the one-column rule.
    """
    def gap(s):
        return len(re.match(r"^\d\d:\d\d:\d\d *", s).group(0)) - 8

    top, sub = "开打：t0=47618.008，偏移 +45 ms", "  fire 400/2739 @chart +12.4s"
    bad = []
    for label, out in (("顶格行", rlog.stamp(top)), ("子行", rlog.stamp(sub))):
        if gap(out) != 1:
            bad.append(f"{label}时间后 {gap(out)} 格（一律应为 1）")
        if out[9:10] == " ":
            bad.append(f"{label}的缩进没被吃掉：{out[:16]!r}")
    if rlog.stamp(sub)[9:] != sub.lstrip():     # 8 个字符的时钟 + 一格，正文从第 9 位开始
        bad.append("吃掉缩进的同时把正文也改了")
    ragged = 0
    for f in _corpus():
        for raw in open(f, encoding="utf-8", errors="replace"):
            line = raw.rstrip("\r\n")
            if not STAMP.match(line):
                continue
            if gap(line) != 1:
                ragged += 1                     # 历史文件：旧格式写的，不回头改
            if gap(rlog.stamp(line[9:])) != 1 or rlog.stamp(line[9:])[9:10] == " ":
                bad.append(f"重排后仍然不齐：{line[:40]!r}")
    old_first = f"23:26:29 {sub}"                                # 最初：戳 + 固定一格
    old_second = f"23:26:29{'' if sub[:1] == ' ' else ' '}{sub}"  # 第一版修法：戳 + 行自己的深度
    teeth = gap(old_first) == 3 and gap(old_second) == 2
    print(f"PART 4 时间列一律 1 格、缩进归零；两种旧写法对同一子行分别给出 {gap(old_first)} 格与 "
          f"{gap(old_second)} 格；库里不齐的历史行 {ragged} 行 -> "
          + ("PASS" if not bad and teeth else "FAIL " + "; ".join(bad)))
    return not bad and teeth


if __name__ == "__main__":
    sys.exit(0 if (part1() and part2() and part3() and part4()) else 1)
