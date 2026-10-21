"""开工前看一眼宿主内存：紧了就地回收，别等它把一整局打崩。

为什么需要：`research/runs/*.out` 里 2140 局的读数显示可用物理内存按 **0.3–0.8 GB / 10 局**
往下走（最长的连续批 10-13 那趟 17.2 h / 209 局，15.9 → 8.2 GB；最低一次读到 1.8 GB），
而每一次 +10~17 GB 的回升都对应一次手工重启模拟器。g377/g378/g380 就是这么死的：
`MemoryError: Unable to allocate 2.64 MiB for an array with shape (720, 1280, 3)` —— 一帧。

三档，**只在一局开工前跑**（曲子里绝不动手）：

==========  ========================  ====================================================
档位        触发（可用物理内存）       动作
==========  ========================  ====================================================
soft        低于 `SOFT_MB`(6 GB)      `am kill-all` + `pm trim-caches` —— 只清缓存后台，
                                      前台（游戏）不受影响，可拿回 1–2 GB
hard        低于 `HARD_MB`(3 GB)      再给游戏发 `am send-trim-memory`（回收 java 堆）
red         低于 `RED_MB`(1.5 GB)     才重开游戏（`watchdog.restart_game` + `walk_home`）
==========  ========================  ====================================================

multi（激奏演出）**不做 red 那一档**：重开游戏等于退出房间，宁可让它叫一声也不替用户把房间丢了。

一个反直觉的细节：这里的「可用」取的是 `ullAvailPhys`（含 standby 可回收页），不是任务管理器
那个「空闲」—— 后者在长跑之后会被文件缓存压到 2–3 GB，看着像要死了，其实一大半能立刻回收。
"""
import ctypes
import time

import watchdog

SOFT_MB = 6000.0
HARD_MB = 3000.0
RED_MB = 1500.0

# 认不出前台包名时的兜底（`watchdog.game_component` 认不出就不杀，这里只用来发 trim）
PKG = "com.ournotes"

_LEVELS = ((1, "soft"), (2, "hard"), (3, "red"))


class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memory():
    """`{'avail','total','commit','limit'}`（MB），宿主不肯说时返回 `None`。"""
    try:
        st = _MemStatus()
        st.dwLength = ctypes.sizeof(_MemStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return None
        return {"avail": st.ullAvailPhys / 1048576.0,
                "total": st.ullTotalPhys / 1048576.0,
                "commit": (st.ullTotalPageFile - st.ullAvailPageFile) / 1048576.0,
                "limit": st.ullTotalPageFile / 1048576.0}
    except Exception:                                          # noqa: BLE001
        return None


def _gb(mb):
    return f"{mb / 1024.0:.1f} GB"


def _adb(*args, timeout=20):
    """跑一条 adb；失败只返回空串（内存这种事不值得让一整局失败）。"""
    try:
        r = watchdog._adb(*args, timeout=timeout)
    except Exception:                                          # noqa: BLE001
        return ""
    return f"{r.stdout or ''}{r.stderr or ''}"


def _game_pkg():
    """前台那个 App 的包名，认不出就用 `PKG`。**只读**（`dumpsys window`）。"""
    try:
        pkg, _act = watchdog.game_component(log=lambda _s: None)
    except Exception:                                          # noqa: BLE001
        return PKG
    if not pkg or watchdog.is_system(pkg):
        return PKG
    return pkg


def trim_background(log=print):
    """第 1 档：清缓存后台 + 清系统缓存。前台不受影响。"""
    said = []
    out = _adb("shell", "am", "kill-all").strip()
    if out:
        said.append(out.splitlines()[-1][:80])
    out = _adb("shell", "pm", "trim-caches", "4G").strip()
    if out:
        said.append(out.splitlines()[-1][:80])
    log("  内存：顺手清掉缓存后台（am kill-all + pm trim-caches）")
    return said


def trim_game(log=print, pkg=None):
    """第 2 档：让游戏自己回收 java 堆。不重启、不打断。"""
    pkg = pkg or _game_pkg()
    out = _adb("shell", "am", "send-trim-memory", str(pkg), "RUNNING_MODERATE").strip()
    log(f"  内存：让 {pkg} 回收自己的堆（send-trim-memory）")
    return out.splitlines()[-1][:80] if out else ""


def guard(log=print, soft=SOFT_MB, hard=HARD_MB, red=RED_MB,
          restart=False, walk=True, sleeper=None, dry=False):
    """一局开工前跑一次。返回 `{'level','before','after','acted','why'}`。

    `restart` 才允许第 3 档重开游戏（multi 由调用方传 False —— 重开等于退房间）。
    `dry` 只报告「会做什么」，一条 adb 都不发。
    """
    before = memory()
    rep = {"level": 0, "before": before, "after": before, "acted": [], "why": ""}
    if before is None:
        rep["why"] = "宿主不报内存"
        log("  内存：宿主不报可用量，跳过回收")
        return rep
    if before["avail"] >= soft:
        log(f"  内存：可用 {_gb(before['avail'])} / {_gb(before['total'])}"
            f"（提交 {_gb(before['commit'])} / {_gb(before['limit'])}），不用收")
        return rep

    def note(what):
        rep["acted"].append(what + ("(dry)" if dry else ""))
        rep["level"] = len(rep["acted"])

    log(f"  内存：可用只剩 {_gb(before['avail'])} / {_gb(before['total'])}"
        f"（提交 {_gb(before['commit'])} / {_gb(before['limit'])}）")
    if not dry:
        trim_background(log=log)
    note("trim-background")

    now = memory() or before
    if now["avail"] < hard:
        if not dry:
            trim_game(log=log)
        note("trim-game")
        now = memory() or now

    if now["avail"] < red:
        if restart:
            if dry:
                log("  内存：还会重开游戏（dry，没真做）")
            else:
                log(f"  内存：只剩 {_gb(now['avail'])}，重开游戏（重开后再走回楽曲選択）")
                try:
                    ok, pkg = watchdog.restart_game(log=log, sleeper=sleeper)
                except Exception as e:                         # noqa: BLE001
                    ok, pkg = False, None
                    log(f"  内存：重开没跑完：{e!r}")
                if ok and walk:
                    # 重开之后第一站是开屏动画，第二站是 TAP TO START（`screen()` 把它读成
                    # result），走查在那一页上按过结算页那颗靠右下的键、什么也没发生
                    # （用户 m54615）。这一步点正中、按住 0.15 s，等它真的落到别的页面。
                    try:
                        import calib
                        calib.clear_title(log=log)
                    except Exception as e:                     # noqa: BLE001
                        log(f"  内存：点标题页没跑完：{e!r}")
                    try:
                        watchdog.walk_home(log=log)
                    except Exception as e:                     # noqa: BLE001
                        log(f"  内存：走回楽曲選択没跑完：{e!r}")
                note("restart-game")
        else:
            rep["why"] = "只剩 %s，重开游戏这一档没开（多人局会把房间丢掉）" % _gb(now["avail"])
            log("  ！！内存：" + rep["why"] + " —— 这一局可能打得动，建议顺手重启一次游戏")
        now = memory() or now

    rep["after"] = now
    if rep["acted"]:
        if dry:
            log(f"  内存：（dry）会做 {'/'.join(rep['acted'])}，可用 {_gb(now['avail'])}")
        else:
            log(f"  内存：回收完成，可用 {_gb(now['avail'])}（进来时 {_gb(before['avail'])}），"
                f"做了 {'/'.join(rep['acted'])}")
    return rep


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="看一眼宿主内存，紧了就地回收（默认只报告）")
    ap.add_argument("--go", action="store_true", help="真动手（不加就是 dry）")
    ap.add_argument("--soft", type=float, default=SOFT_MB)
    ap.add_argument("--hard", type=float, default=HARD_MB)
    ap.add_argument("--red", type=float, default=RED_MB)
    ap.add_argument("--restart", action="store_true", help="到红档时重开游戏")
    args = ap.parse_args(argv)
    rep = guard(soft=args.soft, hard=args.hard, red=args.red,
                restart=args.restart, dry=not args.go)
    print(f"level={rep['level']} acted={rep['acted']} why={rep['why']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
