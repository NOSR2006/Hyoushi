"""夜间看门狗：一批局卡住时把它救回来（用户 m28899 的第 ③ 条）。

面板起的每一局都是一个 `tools/run.py` 子进程。它正常时每几秒就有一行日志；卡住时
可以**一声不响**地挂十几分钟 —— `pc5504` 静默 14 分钟（python 82% 一核、游戏在渲染、
走查认不出自己刚开的 LIVE），`mp8` 在匹配弹窗上坐了 15 分钟。面板侧从前只有
`force_kill()` 这把刀，没有「多久没动静算卡死」的尺子，也没有「卡死之后怎么把游戏弄
回来」的动作。这里给三样东西：

1. `StallWatch` —— **纯逻辑**（不碰设备、不读全局时钟）：一批里「多久没新输出算卡死」、
   「这批还能救几次」、「两次救之间至少隔多久」。面板每收到一行就 `note()`，监控线程
   隔几秒 `due()` 问一次。
2. `game_component()` / `restart_game()` —— 卡死之后把游戏**重开**：先问
   `dumpsys window` 认出前台那个 App（认不出就不动，宁可这一轮不救），确认它不是
   系统/桌面（`NEVER`）再 `am force-stop` + `am start`。
3. `walk_home()` —— 重开之后跑 `tools/run.py --walk-home`，让它自己走回 楽曲選択
   （`run.leave_at_select`；那条路对「开打」按钮只观望，见 AGENTS.md）。

**边界**（与 AGENTS.md 的红线同向）：只收我们自己起的子进程（由 `panel_core` 做）与
「前台那个不是系统 App 的 App」；`NEVER` 里的包一律不碰；认不出前台就不救；每批最多
救 `MAX_RECOVER` 次、两次之间至少隔 `RECOVER_GAP_S`。面板的 `force_kill()` 仍是一条
用户手里的刀，这里不碰它。

回归：`tools/probes/watchdog.py`（纯逻辑 + 假 adb + 源码接线，带三颗牙）。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time

from locate import ADB, DEVICE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 多久没有新输出算卡死。一局正常时每几秒就有一行（走页 verdict、HUD、投票），
# 而 mp8 在匹配弹窗上静默 15 分钟、pc5504 在 LIVE 起点静默 14 分钟 —— 10 分钟
# 既在两者之下，又远在「一局正常的最长静默」之上（结算页读数最长 60 s）。
STALL_S = 600.0
# 一批最多救几次。mp8 那一夜整批 11 局全废；救三次仍然卡，说明不是「偶发冻住」。
MAX_RECOVER = 3
# 两次救之间至少隔这么久：重开游戏 + 走回乐曲選択本身要 ~1 分钟，
# 连着救会把「游戏还在启动」当成第二次卡死。
RECOVER_GAP_S = 120.0
# 重开之后等游戏起来（CriWare 片头）再让 run.py 去走页。
BOOT_S = 15.0
# `--walk-home` 的预算。它只走页、不打局，45 s 的 `leave_at_select` 之外再留余量。
WALK_S = 150.0

# `mCurrentFocus=Window{2a3b4c u0 com.ournotes/com.ournotes.MainActivity}`
# 以及它的兄弟 `mFocusedApp=AppWindowToken{... token=Token{... ActivityRecord{... u0 pkg/cls}}}`。
FOCUS_RE = re.compile(r"mCurrentFocus=Window\{[^}]*?\s([A-Za-z][\w.]*)/([\w.$]+)\}")
APP_RE = re.compile(r"mFocusedApp=.*?\s([A-Za-z][\w.]*)/([\w.$]+)")

# 绝不强杀的前台包：系统 UI、桌面、模拟器自己的壳。游戏不在前台时（用户切去别的
# App、系统弹窗）这一条是唯一的安全带 —— 认错了就杀错东西。
NEVER = ("android", "com.android.", "com.google.android.", "app.lawnchair",
         "com.mumu.", "com.nemu.", "com.miui.", "com.sec.android.")


def _adb(*args, timeout=20.0):
    """跑一条 adb 命令（探针会把它换成记账的替身）。"""
    return subprocess.run([ADB, "-s", DEVICE, *args], capture_output=True, text=True,
                          timeout=timeout, creationflags=CREATE_NO_WINDOW,
                          encoding="utf-8", errors="replace")


def _run(cmd, timeout):
    """跑一条主机命令（`walk_home` 用；探针同样会换掉）。"""
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def is_system(pkg):
    """这个包是不是「绝不该被看门狗强杀」的那一类。"""
    p = (pkg or "").lower()
    return any(p == n or p.startswith(n) for n in NEVER)


class StallWatch:
    """一批局里的「卡死判定 + 救场额度」。纯逻辑，时钟一律由调用方传进来。"""

    def __init__(self, stall_s=STALL_S, max_recover=MAX_RECOVER, gap_s=RECOVER_GAP_S):
        self.stall_s = float(stall_s)
        self.max_recover = int(max_recover)
        self.gap_s = float(gap_s)
        self.recoveries = 0
        self.last = 0.0
        self.last_recover = None

    def begin(self, now):
        """新一轮开跑：静默计时从这一刻起。"""
        self.last = float(now)

    def note(self, now):
        """子进程又吐了一行。"""
        self.last = float(now)

    def quiet_for(self, now):
        return max(0.0, float(now) - self.last)

    def claimable(self, now):
        """还有额度、且离上一次救够远。"""
        now = float(now)
        if self.recoveries >= self.max_recover:
            return False
        return self.last_recover is None or now - self.last_recover >= self.gap_s

    def due(self, now):
        """该不该终止这一局：静默超过 stall_s，且这一批还救得起。"""
        return self.quiet_for(now) >= self.stall_s and self.claimable(now)

    def claim(self, now):
        """领一次救场额度，返回第几次（0 = 不给）。"""
        now = float(now)
        if not self.claimable(now):
            return 0
        self.recoveries += 1
        self.last_recover = now
        self.last = now
        return self.recoveries


def game_component(log=print):
    """认前台那个 App 的 `(包, 活动)`。认不出返回 `(None, None)`。

    只读：`dumpsys window` 是纯查询。**认不出就不救** —— 宁可这一轮白丢，
    也不去猜一个包名然后 `force-stop` 它。
    """
    try:
        out = _adb("shell", "dumpsys", "window")
    except Exception as e:                                        # noqa: BLE001
        log(f"  watchdog: 问不到前台窗口：{e!r}")
        return None, None
    text = f"{out.stdout or ''}{out.stderr or ''}"
    for rx in (FOCUS_RE, APP_RE):
        m = rx.search(text)
        if m:
            return m.group(1), m.group(2)
    log("  watchdog: dumpsys window 里没有前台窗口（mCurrentFocus=null？）")
    return None, None


def restart_game(log=print, boot_s=BOOT_S, sleeper=None):
    """强杀前台那个 App 再重新拉起。返回 `(ok, 包名)`。

    先认包、再杀 —— 顺序不能反：`force-stop` 之后前台就换了，`mCurrentFocus` 再也
    指不回那个 App。`NEVER` 里的包一律不动（认成系统/桌面就放弃这一次）。
    """
    sleeper = sleeper or time.sleep
    pkg, act = game_component(log=log)
    if not pkg:
        return False, None
    if is_system(pkg):
        log(f"  watchdog: 前台是 {pkg}（系统/桌面），不碰它 —— 这一次不救")
        return False, None
    log(f"  watchdog: 强杀 {pkg} 并重开")
    try:
        _adb("shell", "am", "force-stop", pkg)
    except Exception as e:                                        # noqa: BLE001
        log(f"  watchdog: force-stop 没跑完：{e!r}")
        return False, pkg
    sleeper(1.5)
    try:
        if act:
            r = _adb("shell", "am", "start", "-n", f"{pkg}/{act}")
        else:
            # 认不出活动名时退到 launcher intent：对「重开一个 App」足够，
            # 而且不需要知道它的入口类名。
            r = _adb("shell", "monkey", "-p", pkg, "-c",
                     "android.intent.category.LAUNCHER", "1")
    except Exception as e:                                        # noqa: BLE001
        log(f"  watchdog: 重开没跑完：{e!r}")
        return False, pkg
    said = [ln.strip() for ln in f"{r.stdout or ''}{r.stderr or ''}".splitlines() if ln.strip()]
    if said:
        log(f"  watchdog: {said[-1][:120]}")
    sleeper(boot_s)
    return True, pkg


def walk_home(log=print, timeout=WALK_S):
    """重开之后把游戏走回 楽曲選択（`tools/run.py --walk-home`）。

    那条路就是 `run.leave_at_select`：对「开打」按钮只观望、只按返回/关闭，
    所以它不会替用户误开一局。
    """
    cmd = [sys.executable, os.path.join(ROOT, "tools", "run.py"), "--walk-home"]
    try:
        r = _run(cmd, timeout)
    except Exception as e:                                        # noqa: BLE001
        log(f"  watchdog: 走回楽曲選択没跑完：{e!r}")
        return False
    for ln in [x.strip() for x in (r.stdout or "").splitlines() if x.strip()][-6:]:
        log(f"  watchdog| {ln[:140]}")
    return r.returncode == 0


def recover(log=print, walk=True, boot_s=BOOT_S, sleeper=None, clear_title=True):
    """救场一次：重开游戏（必要时再走回楽曲選択）。返回「救回来了」。

    `clear_title`：冷启动会停在 TAP TO START，`screen()` 把它读成 `result`，走查在那一页
    上按的是结算页那颗靠右下的键、按不动（用户 m54615：最后是用户自己点进去的）。所以
    先让 `calib.clear_title` 点正中、等它落到别的页面，再走。老机器上没有那一页也无害
    （第一次 grab 就不是标题页，立刻返回）。
    """
    ok, _pkg = restart_game(log=log, boot_s=boot_s, sleeper=sleeper)
    if not ok:
        return False
    if walk:
        if clear_title:
            try:
                import calib
                calib.clear_title(log=log)
            except Exception as e:                               # noqa: BLE001
                log(f"  watchdog: 点标题页没跑成：{e!r}")
        return walk_home(log=log)
    return True
