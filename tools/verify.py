#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/verify.py —— 把几档验收串成一条命令。

档位定义照 `AGENTS.md` 的「改动怎么验：带牙 + 按需」（2026-10-21 起**默认不跑探针**，
只有四个触发才跑：改了判据/守卫/牙、改了某模块的核心行为、用户说「验一下」、发版），
这里不新增任何判据，只是把它们变成一条命令。**不带参数 = F 档。**

    F 档（开工自检，2026-10-18 用户 m28899；m29273 按用户要求提速）
        py_compile ＋ scopes / paths / hudgate / chartpin：约 13 秒，不拍图、不拆牙、
        不碰窗口/设备/截图。开批次之前手动跑一下最省事，红了就别开工 —— 它挡的是
        「静默活了好几天」的那一类：`wait_result()` 里读 `args` 的 NameError（每局都在结算页崩）
        2 秒就能抓到；`_stream_tool` 的 argv 193（面板「联网更新」从 2026-10-06 起就没工作过）
        由 panelfly 那条重的兜底。
        `--deep` 再加两条重的（panelfly 40 s ＋ 离线全链重放 111 s，合计约 165 s）：
        改过 `panel_core` / `run.py` / `calib.py` 的接线时用，日常不必。
    C 档（发版；约 11 分钟）
        py_compile ＋ 重拍八个视图面 ＋ 全套 35 条探针 ＋ 两处 `--teeth`
        （`fletpanel` 全拆、`fletfont`）

    （像素基线 2026-10-21 退役，用户 m53748：`fletviewcheck` 只留夹具与「_point()」那套
    隔离机器给别的探针复用，它的十二面比对不再是门 —— 理由见 `tools/probes/README.md`。）

用法：

    .venv\\Scripts\\python.exe tools\\verify.py                    # F 档（默认）
    .venv\\Scripts\\python.exe tools\\verify.py --deep             # F 档 + panelfly + 全链重放
    .venv\\Scripts\\python.exe tools\\verify.py --tier C --list     # 只看发版那一趟

为什么要它：这些步骤以前是手打的 `for` 循环加一串单独命令 —— 一次要敲六七条，还容易漏掉
某条牙或某一面基线。这个脚本跑的每一条都是探针自己的入口（命令原样打印），输出原样落进
`research/logs/verify_<时间戳>/<步骤>.log`（`research/logs/` 是 gitignored 的），最后只给一张表：
步骤 / 退出码 / 墙钟 / 那条日志的最后一行 —— 看最后一行就够了。

两条纪律写死在代码里：

* **没有一局在飞**才动设备/窗口：起跑前看 `research/runs` 与 `research/frames` 里最新文件的时间，
  太新（默认 120 s 内）就拒绝，`--force` 才继续 —— 这是启发式，不是保证，它把用到的证据打印出来。

它自己不开窗、不碰设备、不写任何记录文件；`--list` 连子进程都不起。
"""
import argparse
import io
import os
import py_compile
import subprocess
import sys
import time
import warnings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
PROBES = os.path.join("tools", "probes")
# 面板是 pythonw（没有控制台），它每批之前都会在后台跑这条路；而每一步都是 `python.exe`
# —— 控制台程序，不挂这个标志就会在屏幕上连弹五个黑框（2026-10-19 用户 m50302 报的
# 「自检老是弹 CMD 窗口出来」就是这个）。子进程拿到的是一个没有窗口的控制台，它自己的
# 孙进程（探针再拉起的 python / adb / git）也跟着藏在里面。
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def teeth_count():
    """`fletpanel` 现在有几颗牙 —— 从它的 `TEETH` 字典里数，别在这里写死。

    这个数每加一颗牙就会变（29 → 34 → 38 …），写死过一次就再没人改：计划里那句
    「全拆 29 颗」在 38 颗的时候还在打印。数源码只花几毫秒，`--list` 也走这条路。
    """
    src = io.open(os.path.join(PROBES, "fletpanel.py"), encoding="utf-8").read()
    head = src.index("TEETH = {")
    block = src[head:src.index("\n}", head)]
    return block.count('": ("PART ')

# 全套 37 条（顺序照 AGENTS.md 的循环；**末尾四条要真 Flutter 窗口、必须真实桌面**：
# fletviewcheck / fletfly / fletpanel / fletfont —— 排在最后免得它们和别的探针抢桌面，一条一条来）
# scopes 是 2026-10-11 加的：纯静态（symtable）扫「函数读了它看不见的名字」，g647/g648 就是
# `wait_result()` 里写了 `args.read_split` 而 `args` 只活在 `main()` 里 —— py_compile 看不见。
# endpointheal 是 2026-10-16 加的：adb 端点自愈现在也在帧路径上（用户 m27658 的
# 「普通的开始演奏按钮不会重连模拟器」），adb 客户端全用替身，不碰设备。
SUITE = ("hudgate framewriter freshfeed chartpin navgates spritebars breakstop pushcap tailmargin "
         "paths endpointheal scopes chaincal hudcount logclass roundgap maskfast capreg srcfail "
         "recoverwalk "
         "counterrec "
         "mtdiag teethretry panelfly launchers paneldata m3tokens fieldstamp retention votereplay watchdog firepath "
         "fletgui fletpanel fletfont fletfly").split()
# A/B 档不给 --probes 时的默认：按「改的是面板视图层」算（AGENTS.md 的原话）
PANEL_DEFAULT = ("fletgui", "fletpanel")
# F 档（开工自检，2026-10-18 用户 m28899；m29273 按用户要求提速）的固定清单：约 13 秒、
# 不拍图、不拆牙、不碰窗口/设备。顺序按「最快红的先跑」：scopes 2 s、paths 1 s、
# hudgate 7 s、chartpin 2 s。
# 两条重的（panelfly 40 s 的面板命令契约、mpreplay 111 s 的离线全链重放）只在 `--deep`
# 时加 —— 它们值钱但太慢，日常开工用不着；改过 panel_core / run.py / calib.py 的接线时才跑。
FAST = ("scopes", "paths", "hudgate", "chartpin")
ROUND_FRESH = 120.0          # 秒；research/runs、research/frames 里的文件比这新就认为可能有一局在飞


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _newest(paths):
    best = (None, -1.0)
    for p in paths:
        for dirpath, _dirs, files in os.walk(p):
            for f in files:
                q = os.path.join(dirpath, f)
                try:
                    m = os.path.getmtime(q)
                except OSError:
                    continue
                if m > best[1]:
                    best = (q, m)
    return best


def _round_guard(force):
    """没有一局在飞才动窗口。启发式：看 research/runs 与 research/frames 里最新的文件有多新。"""
    q, m = _newest((os.path.join(ROOT, "research", "runs"),
                    os.path.join(ROOT, "research", "frames")))
    if q is None:
        print("  预检：research/runs 与 research/frames 里没有文件（无从判断，继续）")
        return True
    age = time.time() - m
    rel = os.path.relpath(q, ROOT)
    if age < ROUND_FRESH and not force:
        print(f"  预检 FAIL：{rel} 在 {age:.0f} s 前还被写过（阈值 {ROUND_FRESH:.0f} s）"
              f" —— 可能有一局在飞。等它跑完再来，或者确定没有就 --force。")
        return False
    print(f"  预检 ok：最新的记录是 {rel}，{age:.0f} s 前（阈值 {ROUND_FRESH:.0f} s）"
          f"{'，--force 忽略' if force else ''}")
    return True


class Step(object):
    def __init__(self, name, cmd, why, cwd=None, inproc=None):
        self.name = name
        self.cmd = list(cmd)
        self.why = why
        self.cwd = cwd or ROOT
        self.inproc = inproc          # 给 py_compile 用：返回 (rc, 文本)


def _pyc_step():
    files = []
    for base in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "probes")):
        for f in sorted(os.listdir(base)):
            if f.endswith(".py"):
                files.append(os.path.join(base, f))
    bad = []
    for p in files:
        try:
            # `SyntaxWarning`（例如普通字符串里写 `\d`）也要算失败：2026-10-07 这条步
            # 骤第一次真跑时，paneldata.py 的 docstring 里就有一个 `\d` —— py_compile
            # 只当警告放过了它，是探针运行时的 stderr 才把它喊出来的。
            with warnings.catch_warnings():
                warnings.simplefilter("error", SyntaxWarning)
                py_compile.compile(p, doraise=True, cfile=os.path.join(os.environ.get("TEMP", "."),
                                                                      "verify_pyc.pyc"))
        except (py_compile.PyCompileError, SyntaxWarning, SyntaxError) as e:
            bad.append((os.path.relpath(p, ROOT), str(e).strip().splitlines()[-1]))
    lines = [f"py_compile  {len(files)} 个文件"]
    for name, err in bad:
        lines.append(f"  FAIL {name}  {err}")
    lines.append(f"  {'ALL PASS' if not bad else 'FAIL %d 个' % len(bad)}")
    return (0 if not bad else 1), "\n".join(lines) + "\n"


def plan(tier, args):
    steps = [Step("py_compile", [], "全部 tools/*.py 与 tools/probes/*.py 过一遍编译器",
                  inproc=_pyc_step)]
    if tier == "F":
        # 开工自检：不拍图、不拆牙、不碰设备/窗口。默认只跑四条便宜的静态/纯逻辑探针（约 13 秒）；
        # `--deep` 才加两条重的：panelfly（面板命令契约，守着 `_stream_tool` 的 argv 形状 = 193
        # 那个 bug）与 mpreplay（离线全链重放，在 `research/experiments/` 下、不是探针，所以
        # 单独一条 Step）。用户 m29273：日常开工不该为这两条等两分半。
        for name in FAST:
            steps.append(Step("probe:" + name, [PY, os.path.join(PROBES, name + ".py")],
                              "探针 " + name))
        if getattr(args, "deep", False):
            steps.append(Step("probe:panelfly", [PY, os.path.join(PROBES, "panelfly.py")],
                              "探针 panelfly（面板命令契约；改过 panel_core/run.py 接线时用）"))
            steps.append(Step("replay:mpreplay",
                              [PY, os.path.join("research", "experiments", "mpreplay.py")],
                              "离线全链重放：多人走查 + 抽中曲 + 按键序列"))
        return steps
    # C 档 = 发版前那一整趟：重拍视图面 + 全套探针 + 两处牙（判据细节都在探针自己手里）
    steps.append(Step("shot", [PY, "tools/_flet_smoke.py", "--appearance", "both"],
                      "重拍 evidence/view/flet_*.png 八个面（fletgui 第 5 关读的就是它们）"))
    for name in SUITE:
        steps.append(Step("probe:" + name, [PY, os.path.join(PROBES, name + ".py")],
                          "探针 " + name))
    steps.append(Step("teeth:fletpanel",
                      [PY, os.path.join(PROBES, "fletpanel.py"), "--teeth",
                       "--jobs", str(args.jobs)],
                      "牙：全拆 %d 颗（并发 %d）" % (teeth_count(), args.jobs)))
    steps.append(Step("teeth:fletfont", [PY, os.path.join(PROBES, "fletfont.py"), "--teeth"],
                      "牙：字体那四处守卫"))
    return steps


def main():
    _utf8()
    ap = argparse.ArgumentParser(
        description="把开工自检（F）与发版那一趟（C）串成一条命令"
                    "（它自己不开窗、不碰设备；每条判据都还是探针自己的）")
    ap.add_argument("--tier", default="F", choices=("F", "C"),
                    help="走哪一档；不给就是 F（开工自检：约 13 秒、不碰窗口/设备）。"
                         "按 AGENTS.md「改动怎么验」，日常只有四个触发才跑探针，C 档留给发版")
    ap.add_argument("--deep", action="store_true",
                    help="F 档再加上两条重的：panelfly（面板命令契约，40 s）与离线全链重放"
                         "（111 s），合计约 165 s；改过 panel_core / run.py / calib.py 的接线时用")
    ap.add_argument("--jobs", type=int, default=4, metavar="N",
                    help="fletpanel --teeth 的并发（默认 4：实测 4 颗并发时 6 颗牙 94 s 全绿，"
                         "6 并发会把 PART 10 那几条窗口尺寸判据挤成假红）")
    ap.add_argument("--force", action="store_true", help="忽略「可能有一局在飞」的预检")
    ap.add_argument("--list", action="store_true", help="只打印计划，不执行")
    args = ap.parse_args()

    steps = plan(args.tier, args)
    print(f"verify.py  {args.tier} 档  {len(steps)} 步"
          f"（{'、'.join(s.name for s in steps)}）")
    for s in steps:
        print(f"  {s.name:22s} {s.why}")
        if s.cmd:
            print(f"  {'':22s} $ {' '.join(s.cmd)}")
    if args.list:
        return 0

    if not os.path.exists(PY):
        print(f"FAIL 没有解释器：{PY}（探针一律用 .venv 的 python）")
        return 1
    # F 档不看「有没有一局在飞」：它不碰窗口/设备/截图，而且它本来就是**起批次之前**跑的那一下
    # —— 上一局刚结束、research/runs 里还有一分钟内的文件，正是它该跑的时机。
    if args.tier != "F" and not _round_guard(args.force):
        return 1

    stamp = time.strftime("%Y%m%d-%H%M%S")
    outdir = os.path.join(ROOT, "research", "logs", "verify_" + stamp)
    os.makedirs(outdir, exist_ok=True)
    print(f"  日志：{os.path.relpath(outdir, ROOT)}/")

    # `HYOUSHI_PREFLIGHT=0` 让子进程里的 `panel_core.start()` 不再触发一次自检：探针里有调用
    # `core.start()` 的（`tools/probes/paths.py` 的 PART 3），没有这条就会
    # verify F → paths → start → verify F 地递归（实测第一次跑就是这么挂住的）。
    # 两个前缀都发：`locate.env` 认 `HYOUSHI_` 优先、`BANG_` 回落，发全了不依赖哪一版代码在被测。
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               HYOUSHI_PREFLIGHT="0", BANG_PREFLIGHT="0")
    rows, t0 = [], time.time()
    failed = False
    for s in steps:
        if s.name == "baseline:update" and failed:
            print(f"  SKIP {s.name}：前面已经有红的（基线不许在红的树上重拍）")
            rows.append((s.name, None, 0.0, "SKIP：前面有红的"))
            continue
        t1 = time.time()
        logpath = os.path.join(outdir, s.name.replace(":", "_") + ".log")
        if s.inproc is not None:
            rc, text = s.inproc()
            with io.open(logpath, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            sys.stdout.write(text)
        else:
            with io.open(logpath, "wb") as f:
                p = subprocess.run(s.cmd, cwd=s.cwd, env=env, stdout=f,
                                   stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW)
            rc = p.returncode
            with io.open(logpath, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            tail = [ln for ln in text.strip().splitlines() if ln.strip()]
            for ln in tail[-6:]:
                print("  | " + ln)
        wall = time.time() - t1
        last = ""
        for ln in reversed(text.strip().splitlines()):
            if ln.strip():
                last = ln.strip()
                break
        rows.append((s.name, rc, wall, last))
        if rc != 0:
            failed = True
            print(f"  FAIL {s.name}  rc={rc}  {wall:.1f}s  日志 {os.path.relpath(logpath, ROOT)}")

    print()
    print(f"verify.py {args.tier} 档结果（{time.time() - t0:.1f}s，日志在 "
          f"{os.path.relpath(outdir, ROOT)}/）")
    for name, rc, wall, last in rows:
        tag = "SKIP" if rc is None else ("ok  " if rc == 0 else "FAIL")
        print(f"  {tag} {name:22s} {wall:7.1f}s  {last[:110]}")
    print("VERIFY PASS" if not failed else "VERIFY FAIL")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
