"""探针：Flet 面板「跑一局」的那条管道，端到端 —— 八关。

`tools/probes/panelfly.py` 的 PART 1–5 直接驱动 `panel_core.RunOrchestrator`，**与视图无关**
（Flet 版同样被覆盖）；原先只覆盖 Qt 视图那一半的 PART 6 已随 Qt 一起删掉。
**Flet 视图从来没有任何东西端到端跑过**，而「换界面框架时唯一被重写的东西」恰恰就是它：

    `core.q` 里的事件 ──pump_loop──> `_on_message` ──> 各控件的 value

这条缝坏掉的样子是「面板看起来一切正常，结果永远不动」—— 静态读源码看不出来，而且它**不需要
模拟器**就能验：`tools/_fake_runner.py` 是长相与 `tools/run.py` 标准输出契约一致的替身。

八关：

  1. **泵真的在跑**。真入口 `flet_gui.main(page)` 起面板，然后往 `core.q` 里塞一条只有泵才能
     搬走的事件 —— 它出现在 `log_store` 里才算数（不是「任务被创建了」，是「事件真的动了」）。
  2. **替身收到的命令是对的**：`OURNOTES_PANEL=1`（漏了它，面板跑的一局会被记两次）、`--tag`、
     谱面路径。证据取自替身自己写的 `argv.json`。
  3. **日志被分对了类**：原生库横幅（`product …`）必须被丢掉；`!! 断键` 必须判成错误行且把 `!!`
     剥掉；普通行原样留下。
  4. **进度与阶段真的推到了页脚控件上**：跑的时候采到过 `progress > 0` 与 `正在演奏`，跑完回到
     `0.0` 与 `空闲`。
  5. **结算行真的落进了历史**：`RESULT` → `_hist_upsert` → `hist.recs` 里出现这个 tag，而且夹具的
     `results.jsonl` 真的多了一行（这一条同时证明 `OURNOTES_PANEL=1` 起了作用）。
  6. **关窗／重启要收掉正在演奏的子进程**。Windows 上父进程退出**不**带走子进程，所以「关掉面板」
     曾经等于「把一局留在后台继续往游戏里注触摸」。两种答案都要量：说「取消」不许收掉，说「确定」
     必须收掉，而且要在窗消失之前收。判据是替身的心跳文件还长不长 —— 这是唯一不依赖 tasklist 的
     证据。
  7. **隔离**：真实 `research/` 下的记录文件一个都没被这一趟碰过。
  8. **跑完不留孤儿**：`--child` 的最后是 `os._exit(0)`（不陪 Flet 做退场），而 Flutter 客户端是
     **另一个进程**，所以收尾必须先把窗口真的关掉再硬退；否则每跑一次就留下一个 ~170 MB 的
     `flet.exe` —— 这次会话里攒到 6 个，把 `maskfast` 挤成 `ArrayMemoryError`、让 `fletviewcheck`
     的子进程产不出截图。父进程在跑前跑后各数一遍 `tasklist` 里的 `flet.exe`，多出来即 FAIL。

**它不碰模拟器、不写真实语料，但需要桌面会话**（Flet 桌面客户端是一个真 Flutter 窗口，没有离屏
模式），所以它和 `fletviewcheck` / `fletpanel` / `fletfont` 一样不在「零设备零联网」那批里。一次约 25 s。

Run from the repo root:  python tools/probes/fletfly.py
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)


def _utf8_console():
    """把本进程的 stdout/stderr 掰成 UTF-8（Windows 控制台默认 cp936，中文判据一印就炸）。"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                      # noqa: BLE001 —— 被换成非文本流时就算了
            pass


_utf8_console()

import fletviewcheck as F  # noqa: E402  （夹具语料与隔离机器与截图回归共用一份）

SELF = os.path.abspath(__file__)
CHILD_TIMEOUT = 240


# ---------------------------------------------------------------- 子进程（真面板 + 真替身）

def _child(fixture):
    """子进程里的那一半：真入口起面板，真起一个替身，量事件有没有走到控件上。

    判词一边跑一边落盘（`verdicts.jsonl`，每条 flush）—— PART 6 会把窗口关掉，之后的代码能不能
    继续跑不由我们说了算，所以**不能**把结论攒到最后再写。
    """
    F._point(fixture)
    import asyncio
    from types import SimpleNamespace

    import flet as ft
    import flet_gui as G

    vpath = os.path.join(fixture, "verdicts.jsonl")

    def v(name, ok, detail=""):
        with io.open(vpath, "a", encoding="utf-8") as f:
            f.write(json.dumps({"name": name, "ok": bool(ok), "detail": str(detail)},
                               ensure_ascii=False) + "\n")
            f.flush()
        print(("  ok   " if ok else "  FAIL ") + name + (("  " + str(detail)) if detail else ""),
              flush=True)

    def hb_size(p):
        try:
            return os.path.getsize(p)
        except OSError:
            return 0

    def hb_growing(p, wait=0.7):
        n1 = hb_size(p)
        time.sleep(wait)
        return n1, hb_size(p)

    def hb_stopped(p, settle=5.0, window=0.7):
        """等心跳停下来，返回 (停住时的字节数, 再等 `window` 秒之后的字节数)。"""
        last = hb_size(p)
        t0 = time.time()
        while time.time() - t0 < settle:
            time.sleep(0.5)
            n = hb_size(p)
            if n == last:
                break
            last = n
        time.sleep(window)
        return last, hb_size(p)

    async def entry(page: ft.Page):
        seen = {}
        orig = G.Panel

        class Rec(orig):
            """只为把面板实例捞出来。不改 `flet_gui.py` 一个字节 —— 真入口照常跑。"""

            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                seen["p"] = self

        G.Panel = Rec
        try:
            G.main(page)                       # 真入口：建面板 + `page.run_task(pump_loop)`
        finally:
            G.Panel = orig
        panel = seen.get("p")
        v("真入口起出了面板", panel is not None)
        if panel is None:
            os._exit(1)
        await asyncio.sleep(1.0)

        # ---- PART 1 泵真的在跑 -------------------------------------------------
        v("启动那行日志在", ("log_hdr", "面板已启动（Flet / Material 3）") in panel.log_store,
          f"{len(panel.log_store)} 行")
        before_n = len(panel.log_store)
        panel.core.q.put(("log_ok", "泵自检 PING"))
        t0 = time.time()
        while time.time() - t0 < 3.0 and ("log_ok", "泵自检 PING") not in panel.log_store:
            await asyncio.sleep(0.05)
        v("泵把队列里的事件搬到了控件上", ("log_ok", "泵自检 PING") in panel.log_store,
          f"{before_n} -> {len(panel.log_store)} 行")
        v("夹具的曲目列表是活的", len(panel.songs) == 3, f"{len(panel.songs)} 首")

        # ---- 选一首（绕过画面核对：`force=True` 那条路本来就不看游戏） -------------
        ev = SimpleNamespace(control=SimpleNamespace(data="100001"))
        panel.on_song_select(ev)
        v("选中了夹具里的谱面 0001_03", panel.selected_chart_id() == "0001_03",
          repr(panel.selected_chart_id()))

        # ---- PART 2–5 起一局替身，看它怎么走到控件上 ------------------------------
        d1 = os.path.join(fixture, "fake_ok")
        os.environ["HYOUSHI_FAKE_SCENARIO"] = "ok"
        os.environ["HYOUSHI_FAKE_DIR"] = d1
        os.environ["HYOUSHI_FAKE_STEPS"] = "40"          # 每步 0.01 s → 约 0.4 s，够采到中间值
        os.environ.pop("HYOUSHI_FAKE_TAG", None)
        real_ask, G.ask = G.ask, (lambda *a, **k: None)   # force=True 本来也不问，锁住以防万一
        try:
            panel.start_run(force=True)
        finally:
            G.ask = real_ask

        progs, phases = [], []
        t0 = time.time()
        while time.time() - t0 < 60:
            progs.append(panel._footer_progress.value)
            phases.append(panel._footer_phase.value)
            if not panel.core.busy() and time.time() - t0 > 1.0:
                break
            await asyncio.sleep(0.03)
        await asyncio.sleep(0.6)                      # 让 `done` 那一条也泵出去
        progs.append(panel._footer_progress.value)
        phases.append(panel._footer_phase.value)

        av = os.path.join(d1, "argv.json")
        argv = {}
        for _ in range(20):                           # 替身写文件与面板读是两条线，等一下
            if os.path.exists(av):
                try:
                    argv = json.loads(io.open(av, encoding="utf-8").read())
                    break
                except ValueError:
                    pass
            await asyncio.sleep(0.1)
        opts = argv.get("opts") or {}
        pos = argv.get("positional") or []
        v("替身收到了命令行（argv.json）", bool(argv), f"{len(opts)} 个选项")
        v("传了 OURNOTES_PANEL=1（漏了会把一局记两次）", argv.get("ournotes_panel") == "1",
          repr(argv.get("ournotes_panel")))
        v("谱面路径是夹具里的 .hits.json",
          bool(pos) and str(pos[0]).endswith(".hits.json") and os.path.abspath(pos[0])
          .startswith(os.path.abspath(fixture)), f"{pos[:1]}")
        tag = opts.get("--tag")
        v("带上了 --tag", bool(tag), repr(tag))
        v("cwd 是仓库根", os.path.abspath(argv.get("cwd") or "") == os.path.abspath(ROOT),
          repr(argv.get("cwd")))

        texts = [t for _k, t in panel.log_store]
        v("原生库横幅被丢掉了（product nemu_connect）",
          not any("nemu_connect" in t for t in texts))
        v("`!!` 那行被判成错误行且剥掉了标记",
          any(k == "log_err" and "断键，第 12 条" in t for k, t in panel.log_store)
          and not any("!!" in t for t in texts))
        v("普通行原样留下（导航：乐曲选择页）",
          any("导航：乐曲选择页" in t for t in texts))
        v("`#ATSELECT#` 那类机器行没进日志",
          not any(t.startswith("#") or "ATSELECT" in t for t in texts))

        def mx(vals):
            nums = [x for x in vals if isinstance(x, (int, float))]
            return max(nums) if nums else None

        v("进度条真的被推到过 > 0", (mx(progs) or 0) > 0, f"峰值 {mx(progs)}")
        v("阶段行真的显示过「正在演奏」",
          any("正在演奏" in str(p) for p in phases), repr(sorted({str(p) for p in phases})[:4]))
        v("跑完进度回到 0.0", panel._footer_progress.value in (0, 0.0),
          repr(panel._footer_progress.value))
        v("跑完阶段回到「空闲」", panel._footer_phase.value == "空闲",
          repr(panel._footer_phase.value))
        v("强制开始那条警告也进了日志",
          any(k == "log_err" and "强制开始" in t for k, t in panel.log_store))

        recs = getattr(panel.hist, "recs", {}) or {}
        v("结算行落进了历史（hist.recs 里有这个 tag）", bool(tag) and tag in recs, f"tag={tag}")
        rendered = len(panel.hist_table.rows or [])
        v("历史表也重画了", rendered >= 1, f"{rendered} 行")
        v("页脚统计里有结算记录", "结算记录" in str(getattr(panel, "tally", None)
                                                    and panel.tally.value),
          repr(getattr(getattr(panel, "tally", None), "value", None)))
        res_path = os.path.join(fixture, "results.jsonl")
        rows = [json.loads(x) for x in io.open(res_path, encoding="utf-8").read().splitlines()
                if x.strip()]
        v("夹具 results.jsonl 真的多了一行（OURNOTES_PANEL=1 起了作用）",
          any(r.get("tag") == tag for r in rows), f"{len(rows)} 行")

        # ---- PART 6 关窗／重启要收掉正在演奏的子进程 ------------------------------
        async def _no_destroy():
            seen["destroyed"] = True

        patched = True
        real_destroy = None
        try:
            real_destroy = panel.page.window.destroy      # 收尾要还回去，用来真的关窗（见第 8 关）
            panel.page.window.destroy = _no_destroy
        except Exception as e:                                       # noqa: BLE001
            patched = False
            print(f"  （窗口 destroy 没法猴补：{e!r}）", flush=True)

        async def fly(prefix):
            t0 = time.time()
            while panel.core.busy() and time.time() - t0 < 15:
                await asyncio.sleep(0.05)
            d = os.path.join(fixture, prefix)
            os.environ["HYOUSHI_FAKE_SCENARIO"] = "stuck"
            os.environ["HYOUSHI_FAKE_DIR"] = d
            real = G.ask
            G.ask = lambda *a, **k: None
            try:
                panel.start_run(force=True)
            finally:
                G.ask = real
            hb = os.path.join(d, "heartbeat")
            t0 = time.time()
            while not os.path.exists(hb) and time.time() - t0 < 15:
                await asyncio.sleep(0.05)
            return hb

        hb6 = await fly("fake_close")
        v("替身在呼吸（心跳文件出现了）", os.path.exists(hb6), hb6)

        asked = []
        G.ask = lambda page_, tk_, title, body, on_ok, ok_label="确定", danger=False: \
            asked.append(title)                                      # 只记不问 = 用户按了「取消」
        try:
            await panel._on_window_event(SimpleNamespace(type=ft.WindowEventType.CLOSE))
        finally:
            pass
        n1, n2 = hb_growing(hb6)
        v("关窗时问了用户（不是默默动手）", bool(asked), f"{asked}")
        v("说「取消」不收掉那一局（心跳还在长）", n2 > n1, f"心跳 {n1} -> {n2} 字节")

        def ok_ask(page_, tk_, title, body, on_ok, ok_label="确定", danger=False):
            asked.append(title)
            on_ok()                                                  # 用户按了「确定」

        G.ask = ok_ask
        before = hb_size(hb6)
        await panel._on_window_event(SimpleNamespace(type=ft.WindowEventType.CLOSE))
        await asyncio.sleep(0.2)
        n1, n2 = hb_stopped(hb6)
        v("说「确定」收掉了子进程（心跳不再长）", n2 == n1,
          f"心跳 {n1} -> {n2} 字节" + ("（子进程还活着）" if n2 != n1 else ""))
        v("收得干脆（不是拖到几秒之后才死）", n2 - before <= 4,
          f"关窗后又写了 {n2 - before} 字节（不收的话 1.2 秒会写十几个）")
        v("关窗前先杀了那一局，再关窗", bool(seen.get("destroyed")) or not patched,
          f"destroyed={bool(seen.get('destroyed'))} patched={patched}")
        v("那个孩子已经不在 `proc` 上",
          panel.core.proc is None or panel.core.proc.poll() is not None)

        # 重启：先起新的，再收掉旧的（新的那个 Popen 只记一笔，真起会在探针机器上留一个没人管的窗）
        hb7 = await fly("fake_restart")
        v("重启前又起了一局替身", os.path.exists(hb7), hb7)
        spawned = []
        real_popen = subprocess.Popen
        G.ask = ok_ask
        try:
            subprocess.Popen = lambda *a, **k: spawned.append(a) or None
            panel.restart_panel()
        finally:
            subprocess.Popen = real_popen
        await asyncio.sleep(1.2)                    # `bye()` 先睡 0.3 s 再 `_shutdown()`
        n1, n2 = hb_stopped(hb7, settle=4.0)
        v("重启确实去起了新进程", bool(spawned), f"{len(spawned)} 次 Popen")
        v("重启也收掉了子进程（心跳不再长）", n2 == n1,
          f"心跳 {n1} -> {n2} 字节" + ("（子进程还活着）" if n2 != n1 else ""))

        # 收尾：线程必须在子进程退出前真的结束，否则它会拿夹具路径去写。
        panel.core.stop_flag.set()
        if panel.core.worker is not None:
            await asyncio.to_thread(panel.core.worker.join, 15)
        v("退出前那一局的线程也收干净了", not panel.core.busy(),
          f"worker={panel.core.worker is not None} proc={panel.core.proc is not None}")

        # 「跑到最后」这件事**先落盘**：关窗之后这个 python 可能立刻被 Flet 收走
        # （实测：`await window.destroy()` 一关掉最后一个窗口，会话就结束了，这一行之后的代码
        # 不再执行），所以标记必须在关窗之前写。关窗成功与否由父进程数 `flet.exe` 来判（第 8 关）。
        with io.open(vpath, "a", encoding="utf-8") as f:
            f.write(json.dumps({"name": "__end__", "ok": True, "detail": ""}) + "\n")
            f.flush()

        # ---- PART 8 收尾：把窗口真的关掉，别留下孤儿 Flutter 客户端 -------------------
        # `os._exit(0)` 只是把这个 python 拽走；Flutter 客户端是**另一个进程**，不告诉它就留成孤儿
        # （每个 ~170 MB）。PART 6 把 `destroy` 猴补成了「只记一笔」，这里还回去。
        try:
            if real_destroy is not None:
                panel.page.window.destroy = real_destroy
            await panel.page.window.destroy()
            await asyncio.sleep(0.5)                     # 让客户端把退出处理完（父进程那边还会复核）
        except Exception as e:                                       # noqa: BLE001
            print(f"  （窗口没关成：{e!r}）", flush=True)
        os._exit(0)                                  # 硬退：不陪 Flet 做退场

    ft.run(entry, view=ft.AppView.FLET_APP)


# ---------------------------------------------------------------- 主流程

def _run_child(fixture):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["OURNOTES_RUNNER"] = os.path.join(TOOLS, "_fake_runner.py")
    p = subprocess.run([sys.executable, SELF, "--child", fixture],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=ROOT, env=env, timeout=CHILD_TIMEOUT)
    return p


def _flet_pids():
    """系统里所有 `flet.exe`（Flet 的 Flutter 客户端）的 PID，`None` = 这台机器上数不了。"""
    if os.name != "nt":
        return None
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq flet.exe", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=30)
    except Exception:                                                # noqa: BLE001
        return None
    out = r.stdout or ""
    if "flet.exe" not in out.lower():
        return set()                                                 # 「找不到进程」也是一种答复
    pids = set()
    for row in csv.reader(io.StringIO(out)):
        if len(row) >= 2 and row[0].strip().lower() == "flet.exe" and row[1].strip().isdigit():
            pids.add(int(row[1]))
    return pids


def _verdicts(fixture):
    path = os.path.join(fixture, "verdicts.jsonl")
    out = []
    if os.path.exists(path):
        for line in io.open(path, encoding="utf-8").read().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    return out


def main():
    print("PART Flet 面板的「跑一局」管道（泵 → 控件 → 结算行 → 收子进程）")
    before = F._corpus()
    fixture = tempfile.mkdtemp(prefix="fletfly-")
    ok_child, note = False, ""
    try:
        F._fixture(fixture, "dark")
        # 面板会把这条路径递给替身，替身不读它，但路径要真的存在（`start_run` 会先核谱面）。
        with io.open(os.path.join(fixture, "charts", "0001_03.hits.json"), "w",
                     encoding="utf-8", newline="\n") as f:
            f.write("{}\n")
        flets_before = _flet_pids()
        try:
            p = _run_child(fixture)
        except subprocess.TimeoutExpired:
            note = f"子进程 {CHILD_TIMEOUT}s 没退出"
            p = None

        # 第 8 关（父进程这半边）：`--child` 是硬退的，跑完不该多出任何 `flet.exe`。
        if flets_before is not None:
            new_flets = set()
            for _ in range(8):                           # 客户端退出要一点时间
                new_flets = (_flet_pids() or set()) - flets_before
                if not new_flets:
                    break
                time.sleep(0.5)
            with io.open(os.path.join(fixture, "verdicts.jsonl"), "a",
                         encoding="utf-8", newline="\n") as f:
                f.write(json.dumps({
                    "name": "退出后没留下孤儿 Flutter 客户端",
                    "ok": not new_flets,
                    "detail": ("没有新的 flet.exe" if not new_flets else
                               f"新留下 {len(new_flets)} 个：{sorted(new_flets)}"),
                }, ensure_ascii=False) + "\n")
        else:
            print("  （数不了 flet.exe，跳过孤儿检查）", flush=True)
        if p is not None:
            print(p.stdout or "", end="")
            if p.stderr:
                print("  --- 子进程 stderr ---")
                print(p.stderr, end="")
            ok_child = p.returncode == 0
            if not ok_child:
                note = f"子进程退出码 {p.returncode}"

        vs = _verdicts(fixture)
        fails = [x for x in vs if not x["ok"]]
        ended = any(x["name"] == "__end__" for x in vs)
        if not ended:
            print(f"  FAIL 子进程没跑到最后（{len(vs)} 条判词）"
                  + (f"：{note}" if note else ""))
        print()
        iso_ok = F._iso(before, F._corpus())
    finally:
        shutil.rmtree(fixture, ignore_errors=True)

    print()
    # 子进程退出码也要算数：`__end__` 现在写在关窗之前（关窗会把这个 python 一起收走），
    # 所以「跑到最后」不再蕴含「退得干净」，得单看 returncode。
    if fails or not ended or not iso_ok or not ok_child:
        print(f"探针 FAIL：{len(fails)} 项" + ("" if ended else "（子进程没跑到最后）")
              + ("" if ok_child else f"（子进程退出码非 0：{note}）"))
        for x in fails:
            print(f"  - {x['name']}  {x['detail']}")
        return 1
    print(f"ALL PASS（{len(vs) - 1} 条判词）")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        _child(sys.argv[2])
    else:
        t0 = time.time()
        rc = main()
        print(f"（{time.time() - t0:.1f}s）")
        sys.exit(rc)
