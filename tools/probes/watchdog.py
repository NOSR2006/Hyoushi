"""夜间看门狗（`tools/watchdog.py` + `panel_core` / `run.py` 的接线）。

用户 m28899 的第 ③ 条：一批局卡住时把游戏救回来。这里钉四件事 ——

1. **卡死判定**：`StallWatch` 只在「静默 ≥ `STALL_S` 且这批还救得起」时点头；
   额度每批 `MAX_RECOVER` 次、两次之间至少 `RECOVER_GAP_S`；`note()` 一有输出就归零。
2. **救场动作**：先认前台（`dumpsys window` 的 `mCurrentFocus`，退一步 `mFocusedApp`），
   `NEVER` 里的系统/桌面包一律不碰，认不出就不救；认出来才 `am force-stop` + `am start`。
3. **接线**：`panel_core.__init__` 建 `self.watch`、`_spawn_run` 起监控线程（静默超时收掉
   子进程）、`_run_loop` 在那一轮收尾时 `claim()` + `watchdog.recover()`；
   `run.py` 有 `--walk-home`（重开之后走回 楽曲選択、不开局）。
4. **牙**：把 `due()` 的静默条件拆掉、把监控线程摘掉、把 `NEVER` 守卫拆掉 ——
   同一套判据必须变红。

零设备、零窗口、零联网：adb 与子进程全部换成记账替身。
"""
from __future__ import annotations

import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import panel_core  # noqa: E402
import watchdog  # noqa: E402
import memguard  # noqa: E402

FAILS = []


def say(label, good):
    print(("  ok  " if good else "  FAIL ") + label)
    if not good:
        FAILS.append(label)
    return bool(good)


def load(src, name="watchdog_mut"):
    """把一段模块源码 exec 成一个新命名空间（牙用；不碰真模块）。"""
    ns = {"__name__": name, "__file__": watchdog.__file__}
    exec(compile(src, "<mutant>", "exec"), ns)          # noqa: S102 -- 探针自己的变异体
    return ns


class FakeAdb:
    """记账替身：按 `(子命令…)` 回话，记下每一条真被发出的 adb argv。"""

    def __init__(self, window_text=""):
        self.window_text = window_text
        self.calls = []

    def __call__(self, *args, timeout=20.0):
        self.calls.append(list(args))

        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        r = R()
        if args[:2] == ("shell", "dumpsys"):
            r.stdout = self.window_text
        elif args[:2] == ("shell", "am"):
            r.stdout = "Starting: Intent { ... }\n"
        return r


FOCUS = ("mCurrentFocus=Window{2a3b4c u0 com.example.game/com.example.game.MainActivity}\n"
         "mFocusedApp=AppWindowToken{9d8e7f token=Token{1a2b ActivityRecord{3c4d u0 "
         "com.example.game/com.example.game.MainActivity t42}}}\n")
FOCUS_APP_ONLY = "mCurrentFocus=null\nmFocusedApp=AppWindowToken{9d8e7f u0 com.example.game/.Main}\n"
FOCUS_SYSTEM = "mCurrentFocus=Window{55 u0 com.android.systemui/com.android.systemui.keyguard}\n"


def part1_logic():
    print("PART 1 卡死判定（纯逻辑）")
    W = watchdog.StallWatch
    w = W()
    w.begin(0.0)
    say("刚开跑 599 s 不算卡死", w.due(599.0) is False)
    say("静默到 600 s 点头", w.due(600.0) is True)
    w.note(700.0)
    say("来了一行就重新计时", w.due(1299.0) is False and w.due(1300.0) is True)

    w = W()
    w.begin(0.0)
    say("第一次领额度拿到 1", w.claim(600.0) == 1)
    say("刚救过 100 s，还不到间隔", w.claimable(700.0) is False)
    say("过了间隔又能领", w.claim(720.0) == 2)
    say("第三次", w.claim(900.0) == 3)
    say("额度用完就不给", w.claim(5000.0) == 0)
    say("额度用完就不再点头", w.due(9000.0) is False)

    w = W()
    w.begin(0.0)
    say("还没卡死就不该点头（额度不是理由）", w.due(1.0) is False)
    say("一分钟的静默不算卡死", w.due(60.0) is False)
    say("十分钟的静默才算", w.due(600.0) is True)

    # 牙：拆掉静默条件，空等一秒也必须点头
    src = inspect.getsource(watchdog)
    mut = src.replace("return self.quiet_for(now) >= self.stall_s and self.claimable(now)",
                      "return self.claimable(now)")
    say("牙：拆掉静默条件后同一段判据必须变假",
        mut != src and load(mut)["StallWatch"]().due(1.0) is True)
    return not FAILS


def part2_recovery():
    print("PART 2 救场动作（假 adb）")
    real_adb, real_run = watchdog._adb, watchdog._run
    real_sleep = watchdog.time.sleep
    try:
        fake = FakeAdb(FOCUS)
        watchdog._adb = fake
        watchdog.time.sleep = lambda s: None
        pkg, act = watchdog.game_component(log=lambda s: None)
        say("mCurrentFocus 认得出包与活动",
            (pkg, act) == ("com.example.game", "com.example.game.MainActivity"))

        fake = FakeAdb(FOCUS_APP_ONLY)
        watchdog._adb = fake
        pkg2, act2 = watchdog.game_component(log=lambda s: None)
        say("没有 mCurrentFocus 时退到 mFocusedApp", (pkg2, act2) == ("com.example.game", ".Main"))

        fake = FakeAdb("")
        watchdog._adb = fake
        said = []
        say("问不出前台就答 (None, None) 并说一句",
            watchdog.game_component(log=said.append) == (None, None) and bool(said))

        fake = FakeAdb(FOCUS)
        watchdog._adb = fake
        ok, pkg = watchdog.restart_game(log=lambda s: None, boot_s=0.0)
        seq = [c[1:] for c in fake.calls if c[:2] == ["shell", "am"]]
        say("重开 = force-stop 再 am start",
            ok is True and pkg == "com.example.game"
            and seq == [["am", "force-stop", "com.example.game"],
                        ["am", "start", "-n", "com.example.game/com.example.game.MainActivity"]])
        say("认包在杀之前（dumpsys 先于 force-stop）",
            [c[1] for c in fake.calls] == ["dumpsys", "am", "am"])

        fake = FakeAdb(FOCUS_SYSTEM)
        watchdog._adb = fake
        said = []
        ok, pkg = watchdog.restart_game(log=said.append, boot_s=0.0)
        say("前台是系统 UI 就一个字节都不杀",
            ok is False and pkg is None and not [c for c in fake.calls if c[1] == "am"])
        say("并说明为什么没救", any("系统/桌面" in s for s in said))

        fake = FakeAdb("")
        watchdog._adb = fake
        say("认不出前台就不杀", watchdog.restart_game(log=lambda s: None) == (False, None)
            and not [c for c in fake.calls if c[1] == "am"])

        fake = FakeAdb(FOCUS)
        watchdog._adb = fake
        seen = []

        def fake_run(cmd, timeout):
            seen.append((list(cmd), timeout))

            class R:
                returncode = 0
                stdout = "  导航：乐曲选择页\n#ATSELECT#\n"
                stderr = ""
            return R()
        watchdog._run = fake_run
        say("recover(walk=True) 会去走回选曲页",
            watchdog.recover(log=lambda s: None, boot_s=0.0) is True
            and seen and seen[0][0][-1] == "--walk-home")
        say("走页有预算（不是无限等）", seen and seen[0][1] == watchdog.WALK_S)

        def fake_run_bad(cmd, timeout):
            class R:
                returncode = 1
                stdout = ""
                stderr = ""
            return R()
        watchdog._run = fake_run_bad
        say("走不回去就不算救回来", watchdog.recover(log=lambda s: None, boot_s=0.0) is False)

        say("recover(walk=False) 只重开不走页",
            watchdog.recover(log=lambda s: None, walk=False, boot_s=0.0) is True)
    finally:
        watchdog._adb, watchdog._run = real_adb, real_run
        watchdog.time.sleep = real_sleep
    return not FAILS


def _p_loop_recover(src):
    """`_run_loop` 里那一块救场还在不在（PART 3 与牙共用）。"""
    return "if self._stalled:" in src and "watchdog.recover(" in src


def part3_wiring():
    print("PART 3 接线（源码钉）")
    pc = inspect.getsource(panel_core)
    run_src = open(os.path.join(TOOLS, "run.py"), encoding="utf-8").read()
    init = inspect.getsource(panel_core.RunOrchestrator.__init__)
    spawn = inspect.getsource(panel_core.RunOrchestrator._spawn_run)
    loop = inspect.getsource(panel_core.RunOrchestrator._run_loop)

    say("panel_core 引了 watchdog", "import watchdog" in pc)
    say("__init__ 建 self.watch 与 self._stalled",
        "self.watch = watchdog.StallWatch()" in init and "self._stalled = False" in init)
    say("每批重新给额度", loop.count("self.watch = watchdog.StallWatch()") == 1)
    say("_spawn_run 起监控线程", "target=_stall_monitor" in spawn)
    say("监控线程按 due() 收子进程",
        "if self.watch.due(time.monotonic()):" in spawn and "child.kill()" in spawn)
    say("每行输出都 note()", "self.watch.note(time.monotonic())" in spawn)
    say("监控线程在 finally 里停",
        "stop_mon.set()" in spawn and spawn.index("stop_mon.set()") < spawn.index("self.proc = None"))
    say("_run_loop 领额度并救场",
        "self.watch.claim(time.monotonic())" in loop and "watchdog.recover(" in loop)
    say("救场额度用完了要说话", "救场额度用完了" in loop)
    say("run.py 有 --walk-home", '"--walk-home"' in run_src)
    say("--walk-home 走 leave_at_select 且不开局",
        "leave_at_select(inj, log=print, timeout=90.0, multi=args.multi)" in run_src
        and 'print("走回乐曲選択：成功"' in run_src)
    return not FAILS


def teeth():
    print("PART 4 牙")
    ok = True
    src = inspect.getsource(panel_core)
    cut = src.replace("            threading.Thread(target=_stall_monitor, args=(self.proc,), "
                      "daemon=True).start()\n", "")
    ok &= say("牙：摘掉监控线程的启动，接线判据必须变假",
              cut != src and "target=_stall_monitor" not in cut)

    wsrc = inspect.getsource(watchdog)
    mut = wsrc.replace("    if is_system(pkg):\n        log(f\"  watchdog: 前台是 {pkg}（系统/桌面），"
                       "不碰它 —— 这一次不救\")\n        return False, None\n",
                       "    if False:\n        pass\n")
    ok &= say("牙：拆掉系统包守卫后，系统 UI 也会被强杀",
              mut != wsrc and load(mut)["is_system"]("com.android.systemui") is True)

    loop_src = inspect.getsource(panel_core.RunOrchestrator._run_loop)
    noloop = loop_src.replace("            if self._stalled:\n", "            if False:\n", 1)
    ok &= say("牙：把救场分支关掉，_run_loop 判据必须变假",
              noloop != loop_src and _p_loop_recover(noloop) is False)
    return ok


def _title_ok(src):
    """重开之后必须先去点 TAP TO START（`recover` 那段）。"""
    return "calib.clear_title(log=log)" in src and "import calib" in src


def part4_title():
    """冷启动那一页「TAP TO START」：判据 + 接线（用户 m54615）。"""
    import numpy as np
    from PIL import Image

    import calib

    nav = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "evidence", "nav")

    def arr(name):
        return np.array(Image.open(os.path.join(nav, name)).convert("RGB"))

    say("标题页认得出（TAP TO START 那一帧）", calib.title_screen(arr("navgates_title_a.png")) is True)
    bad = ["mp_rank_a.png", "mp_exp_totals_a.png", "navgates_load_a.png",
           "nav_stuck_options.png", "navgates_event_home_a.png", "navgates_after_result_a.png"]
    say("别的六页都不算标题页", all(calib.title_screen(arr(n)) is False for n in bad))
    say("点的是屏幕正中（不是结算页那颗靠右下的键）",
        abs(calib.TITLE_TAP[0] - 640) <= 200 and abs(calib.TITLE_TAP[1] - 360) <= 200)
    say("按住 >=0.1 s（0.05 s 的点击游戏不认）", "hold=0.15" in inspect.getsource(calib.clear_title))
    rec = inspect.getsource(watchdog.recover)
    say("recover 重开之后先点标题页再走", _title_ok(rec) and rec.index("clear_title") < rec.index("walk_home"))
    mem = inspect.getsource(memguard.guard)
    say("memguard 红档也先点标题页", "calib.clear_title" in mem)
    mut = rec.replace("                calib.clear_title(log=log)" + chr(10), "", 1)
    say("牙：把点标题页那一步拆掉，接线判据必须变假", mut != rec and _title_ok(mut) is False)
    return True


def main():
    print(f"watchdog: STALL_S={watchdog.STALL_S:g} MAX_RECOVER={watchdog.MAX_RECOVER} "
          f"RECOVER_GAP_S={watchdog.RECOVER_GAP_S:g} NEVER={len(watchdog.NEVER)} 类")
    ok = part1_logic()
    ok = part2_recovery() and ok
    ok = part3_wiring() and ok
    ok = part4_title() and ok
    ok = teeth() and ok
    print("WATCHDOG " + ("PASS" if ok and not FAILS else "FAIL"))
    return 0 if ok and not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
