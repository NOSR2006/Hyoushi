"""探针：面板跑一局的那条管道，端到端。

**它不碰模拟器、不碰语料。** 它把 `OURNOTES_RUNNER` 指向 `tools/_fake_runner.py` —— 一个只会
照 run.py 的标准输出契约说话的替身 —— 于是

    起进程 → 逐行读标准输出 → 分出机器行与日志行 → 收 RESULT → 写 results.jsonl

这条链路能在没有模拟器时被真跑一遍。这条链路是换界面框架时**唯一被重写**的东西，而它坏掉的
样子是「面板看起来一切正常，结果永远不动」，所以它必须有一条会失败的回归。

三道隔离，缺一不可：

  * `panel_core.STATE` → 临时文件（否则探针会把用户的面板设置重写掉）；
  * `panel_core.RESULTS` → 临时文件（否则假局的结算记录会混进真实账本）；
  * `panel_core.RUN_OUT_DIR` → 临时目录（否则 `research/g9xx.out` 会变成一条假的记录来源）。

判定：任一 PART FAIL → 退出码 1。PART 4 是「带牙」的那一条 —— 把 `_spawn_run` 的异常收尾去掉，
它会立刻变成 FAIL，因为留在盘上的心跳会继续长。

一个已知的假阳性来源：PART 4 用心跳判「子进程还活着」。它不读 tasklist，所以与用户的面板、
与并发的一局 CLI 都无关；它只看那个探针自己起的替身有没有在继续呼吸。

「关窗／重启要收掉正在演奏的子进程」那一关**不在这个文件里**：它要一个真窗口，量的是视图层
（`QMessageBox` 换成 Flet 的 `ask()`），现在归 `fletfly.py` 的第 6 关（关窗问用户、说取消不收拾、
说确定就收拾干净、重启先起新的再收旧的）。这里只剩不依赖视图的五关。
"""

from __future__ import annotations

import importlib.util
import io
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

FAILS: list[str] = []


def check(label, cond, extra=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(label)
    return cond


def read_json(path):
    import json
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                             # noqa: BLE001
        return {}


def drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


def texts(ev):
    return [p for k, p in ev if isinstance(p, str)]


def main():
    import panel_core as core

    tmp = tempfile.mkdtemp(prefix="bang_probe_fly_")
    real_state, real_results, real_out = core.STATE, core.RESULTS, core.RUN_OUT_DIR
    real_env = {k: os.environ.get(k) for k in
                ("OURNOTES_RUNNER", "HYOUSHI_FAKE_DIR", "HYOUSHI_FAKE_SCENARIO", "HYOUSHI_FAKE_STEPS")}
    fake = os.path.join(TOOLS, "_fake_runner.py")
    hits = os.path.join(core.rlog.CHARTS, "0074_00.hits.json")
    pre_out = set(n for n in core.listdir(os.path.join(ROOT, "research"))
                  if n.endswith(".out"))
    leaked_pid = None

    core.STATE = os.path.join(tmp, "gui_state.json")
    core.RESULTS = os.path.join(tmp, "results.jsonl")
    core.RUN_OUT_DIR = os.path.join(tmp, "out")
    os.makedirs(core.RUN_OUT_DIR, exist_ok=True)
    os.environ["OURNOTES_RUNNER"] = fake
    os.environ["HYOUSHI_FAKE_STEPS"] = "3"

    def spawn(orch, tag, scenario, **kw):
        d = os.path.join(tmp, "fake_" + tag)
        os.environ["HYOUSHI_FAKE_DIR"] = d
        os.environ["HYOUSHI_FAKE_SCENARIO"] = scenario
        rc, rec = orch._spawn_run(hits, tag, **kw)
        return rc, rec, read_json(os.path.join(d, "argv.json")), d

    try:
        state = {"last_chart": "0074_00", "defaults": {}}
        orch = core.RunOrchestrator(state)

        print("PART 1 命令契约：面板到底发出了什么命令")
        rc, rec, A, _ = spawn(orch, "g900", "ok",
                              random_mode=False, retry_break=True, push_cap=True,
                              retry_cap=3, push_ms=10.0)
        ev1 = drain(orch.q)
        opts, pos = A.get("opts", {}), A.get("positional", [])
        check("位置参数就是那张谱", pos == [hits], f"{pos}")
        check("--fastcap / --retry-anchor / --watch-hud 都在",
              all(k in opts for k in ("--fastcap", "--retry-anchor", "--watch-hud")))
        # `--host` 是 `--fastcap` 的兜底（`run.py` 同时收到两者时先试 SDK，SDK 装不上才去装窗口
        # 抓帧）。它必须是个**裸开关**：带了值就说明谁把它当成带参选项了。2026-10-06 加。
        check("--host 也在，而且是个裸开关（--fastcap 的兜底）",
              opts.get("--host") is True, f"{opts.get('--host')!r}")
        check("--offset 55.0", opts.get("--offset") == "55.0", f"{opts.get('--offset')!r}")
        check("--live-push-cap 10.0", opts.get("--live-push-cap") == "10.0",
              f"{opts.get('--live-push-cap')!r}")
        check("--tag g900", opts.get("--tag") == "g900", f"{opts.get('--tag')!r}")
        check("勾了断AP重试才发 --retry-on-break 3",
              opts.get("--retry-on-break") == "3", f"{opts.get('--retry-on-break')!r}")
        # 火力门（用户 m13786）。两半各管一段：**这里**管面板发出的那条参数（关着时命令行必须与
        # 从前逐字相同，开着时值就是面板那个常数），游戏侧「不足就停在确认页等」在 calib.start_live。
        check("火力门关着时一个字都不多发", "--min-fire" not in opts, f"{opts.get('--min-fire')!r}")
        _rcf, _recf, B, _ = spawn(orch, "g901", "ok", random_mode=False, retry_break=False,
                                  push_cap=True, retry_cap=3, push_ms=10.0, fire_gate=True)
        drain(orch.q)
        check("火力门开着时发 --min-fire 3",
              B.get("opts", {}).get("--min-fire") == str(core.FIRE_MIN),
              f"{B.get('opts', {}).get('--min-fire')!r}")
        # 种类偏移（用户 m15057 把四个框放回设置页，m15291 改名）：**全零时一个字都不多发**
        # （命令行与从前逐字相同），有值时按 `种类=毫秒` 发、只列非零的那几类。
        check("种类偏移全零时一个字都不多发（命令行与从前逐字相同）",
              "--kind-lead" not in opts, f"{opts.get('--kind-lead')!r}")
        _rck, _reck, K, _ = spawn(orch, "g907", "ok", random_mode=False, retry_break=False,
                                  push_cap=True, retry_cap=3, push_ms=10.0,
                                  kind_lead={"tap": -30.0, "long": 0.0, "flick": 5.0,
                                             "trace": 0.0})
        drain(orch.q)
        karg = (K.get("opts", {}) or {}).get("--kind-lead")
        kd = dict(p.split("=", 1) for p in (karg or "").split(",") if p)
        check("有值时发 --kind-lead，只列非零的那几类（正数 = 更早）",
              kd == {"tap": "-30", "flick": "5"}, f"{karg!r}")
        check("OURNOTES_PANEL=1（否则面板跑的一局会被记两次）",
              A.get("ournotes_panel") == "1", f"{A.get('ournotes_panel')!r}")
        check("PYTHONIOENCODING=utf-8（否则一行中文就能把子进程打死）",
              A.get("pythonioencoding") == "utf-8", f"{A.get('pythonioencoding')!r}")
        check("工作目录是仓库根", os.path.normcase(A.get("cwd") or "") == os.path.normcase(ROOT),
              f"{A.get('cwd')!r}")
        # 尾判滑键（用户 m52916「能否将尾滑偏移加入设置」）：与出厂值相同时一个字都不多发
        # （命令行与从前逐字相同）；0 也**要发** —— 0 是有意义的一档（关掉这段提前量），
        # 所以判的是「与出厂值不同」而不是「非零」。
        check("尾判滑键按出厂值时一个字都不多发（命令行与从前逐字相同）",
              "--tail-flick-lead" not in opts, f"{opts.get('--tail-flick-lead')!r}")
        _rct, _rect, TL, _ = spawn(orch, "g908", "ok", random_mode=False, retry_break=False,
                                   push_cap=True, retry_cap=3, push_ms=10.0, tail_lead=0.0)
        drain(orch.q)
        tlo = TL.get("opts", {}) or {}
        check("尾滑改成 0 时发 --tail-flick-lead 0（0 = 关掉这段提前量，不是「没设」）",
              tlo.get("--tail-flick-lead") == "0", f"{tlo.get('--tail-flick-lead')!r}")
        _rct2, _rect2, TL2, _ = spawn(orch, "g908", "ok", random_mode=False, retry_break=False,
                                      push_cap=True, retry_cap=3, push_ms=10.0, tail_lead=25.0)
        drain(orch.q)
        check("尾滑改成 25 时发 --tail-flick-lead 25（整数不带小数点）",
              (TL2.get("opts", {}) or {}).get("--tail-flick-lead") == "25",
              f"{(TL2.get('opts', {}) or {}).get('--tail-flick-lead')!r}")

        # 多人局（用户 m02832 在面板上加了「多人演出」页）：谱面交给房间抽 ⇒ 不发位置参数、也不发
        # `--random`，发的是 `--multi` 与 `--diff`；正推上限按 `core.MULTI_PUSH_CAP_MS`（0）发死
        # —— 这正是 mp9/mp10 两轮全 PERFECT 的配方，面板不给这个开关。
        _rcm, _recm, M, _ = spawn(orch, "g904", "ok", random_mode=False, retry_break=False,
                                  push_cap=False, retry_cap=3, push_ms=10.0, multi="expert")
        drain(orch.q)
        mo, mp = M.get("opts", {}), M.get("positional", [])
        check("多人局不发位置参数（谱面由房间抽）", mp == [], f"{mp}")
        check("多人局不发 --random", "--random" not in mo, f"{mo.get('--random')!r}")
        check("多人局发 --multi 与 --diff expert",
              mo.get("--multi") is True and mo.get("--diff") == "expert",
              f"{mo.get('--multi')!r}/{mo.get('--diff')!r}")
        check("多人局的正推上限恒 0（core.MULTI_PUSH_CAP_MS）",
              mo.get("--live-push-cap") == str(core.MULTI_PUSH_CAP_MS),
              f"{mo.get('--live-push-cap')!r}")
        check("多人局照旧带 --fastcap/--host/--retry-anchor/--watch-hud/--offset",
              all(k in mo for k in ("--fastcap", "--host", "--retry-anchor", "--watch-hud",
                                    "--offset")),
              f"{sorted(mo)}")
        check("单人局一个 --multi/--diff 都不发（两种局不串味）",
              "--multi" not in opts and "--diff" not in opts, f"{sorted(opts)}")

        # 「随机乐曲」（2026-10-16 用户 m27959 把多人页那枚「LB监测」换成它）：多人局的谱面仍是
        # 房间从五个人的提名里抽的，面板这一枚只是**随机提名一首** ⇒ 在 `--multi --diff` 之外
        # 多一条 `--random`（`run.py` 的 `on_select_multi` 在 楽曲選択 页挑一首当提名）。
        _rcm3, _recm3, M3, _ = spawn(orch, "g908", "ok", random_mode=True, retry_break=False,
                                     push_cap=False, retry_cap=3, push_ms=10.0, multi="expert")
        drain(orch.q)
        m3, mp3 = M3.get("opts", {}), M3.get("positional", [])
        check("多人局开「随机乐曲」：多一条 --random（提名），位置参数照旧不发",
              m3.get("--random") is True and mp3 == []
              and m3.get("--multi") is True and m3.get("--diff") == "expert",
              f"--random={m3.get('--random')!r} pos={mp3} "
              f"multi={m3.get('--multi')!r}/{m3.get('--diff')!r}")
        # 牙：把 `_spawn_run` 里那两行 `--random` 摘掉 —— 同一句判据必须在变异体上变红。
        tooth_rnd = tempfile.mkdtemp(prefix="panelfly-random-")
        try:
            os.makedirs(os.path.join(tooth_rnd, "tools"), exist_ok=True)
            src_rnd = io.open(os.path.join(TOOLS, "panel_core.py"), encoding="utf-8").read()
            old_rnd = ('            if random_mode:\n'
                       '                # 多人页那颗「随机乐曲」')
            if old_rnd not in src_rnd:
                check("牙：多人局那条 --random 拆掉之后，同一句判据变红", False,
                      "锚点不在 tools/panel_core.py 里了（判据该跟着改）")
            else:
                cut = src_rnd.replace('                cmd += ["--random"]\n',
                                      "                pass\n", 1)
                io.open(os.path.join(tooth_rnd, "tools", "panel_core.py"), "w",
                        encoding="utf-8").write(cut)
                spec_r = importlib.util.spec_from_file_location(
                    "panelfly_mutant_random", os.path.join(tooth_rnd, "tools", "panel_core.py"))
                mod_r = importlib.util.module_from_spec(spec_r)
                spec_r.loader.exec_module(mod_r)
                mod_r.RUN_OUT_DIR = core.RUN_OUT_DIR
                os.environ["HYOUSHI_FAKE_DIR"] = os.path.join(tmp, "fake_tooth_rnd")
                os.environ["HYOUSHI_FAKE_SCENARIO"] = "ok"
                mod_r.RunOrchestrator({"last_chart": "", "defaults": {}})._spawn_run(
                    hits, "g909", random_mode=True, retry_break=False, push_cap=False,
                    retry_cap=3, push_ms=10.0, multi="expert")
                tr = read_json(os.path.join(tmp, "fake_tooth_rnd", "argv.json")).get("opts", {})
                check("牙：多人局那条 --random 拆掉之后，同一句判据变红",
                      "--random" not in tr,
                      f"变异体在多人局发的 --random={tr.get('--random')!r}")
        finally:
            shutil.rmtree(tooth_rnd, ignore_errors=True)

        # 用户 m12749：多人局**没有**「断连重试」—— 中途重开是「暂停 LIVE → 重试 → 确定」把同一首
        # 从头再打（`calib.restart_to_t0`），房间局要么走不通、要么把这一轮作废。面板上三层都不
        # 放行，这里量第一层（发出去的 argv）与第二层（`_run_loop` 那行表头）。
        _rcm2, _recm2, M2, _ = spawn(orch, "g905", "ok", random_mode=False, retry_break=True,
                                     push_cap=False, retry_cap=3, push_ms=10.0, multi="expert")
        drain(orch.q)
        check("多人局即使勾了断AP重试也不发 --retry-on-break（单人局照发，两半一起判）",
              "--retry-on-break" not in M2.get("opts", {})
              and opts.get("--retry-on-break") == "3",
              f"多人={M2.get('opts', {}).get('--retry-on-break')!r} "
              f"单人={opts.get('--retry-on-break')!r}")
        # 这一趟会真走完一轮（`record_round` 要落一行），所以账本与状态临时另指一处 ——
        # PART 3 数的是 `core.RESULTS` 里的行数，这一轮的记录不许混进去。
        keep_results, keep_state = core.RESULTS, core.STATE
        core.RESULTS = os.path.join(tmp, "hdr_results.jsonl")
        core.STATE = os.path.join(tmp, "hdr_state.json")
        try:
            hdr_orch = core.RunOrchestrator({"last_chart": "", "defaults": {}})
            os.environ["HYOUSHI_FAKE_DIR"] = os.path.join(tmp, "fake_hdr")
            os.environ["HYOUSHI_FAKE_SCENARIO"] = "ok"
            hdr_orch._run_loop(None, "房间抽曲", "expert", 1, False, False, True, False, 3,
                               10.0, 0.0, False, multi="expert")
            hdrs = [p for k, p in drain(hdr_orch.q) if k == "log_hdr"]
        finally:
            core.RESULTS, core.STATE = keep_results, keep_state
        check("多人局的表头也不许念「断AP立即重试」（勾着进来也不念）",
              bool(hdrs) and all("断AP立即重试" not in t for t in hdrs)
              and any("房间自己抽曲" in t for t in hdrs), f"{hdrs}")

        # 牙：把 `_spawn_run` 里那句 `and not multi` 拆掉 —— 同一句判据必须在变异体上变红。
        tooth = tempfile.mkdtemp(prefix="panelfly-retry-")
        try:
            os.makedirs(os.path.join(tooth, "tools"), exist_ok=True)
            src = io.open(os.path.join(TOOLS, "panel_core.py"), encoding="utf-8").read()
            old_gate = "        if retry_break and not multi:\n"
            if old_gate not in src:
                check("牙：多人局那道闸门拆掉之后，同一句判据变红", False,
                      "锚点不在 tools/panel_core.py 里了（判据该跟着改）")
            else:
                io.open(os.path.join(tooth, "tools", "panel_core.py"), "w",
                        encoding="utf-8").write(src.replace(old_gate, "        if retry_break:\n", 1))
                spec = importlib.util.spec_from_file_location(
                    "panelfly_mutant_retry", os.path.join(tooth, "tools", "panel_core.py"))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.RUN_OUT_DIR = core.RUN_OUT_DIR
                os.environ["HYOUSHI_FAKE_DIR"] = os.path.join(tmp, "fake_tooth")
                os.environ["HYOUSHI_FAKE_SCENARIO"] = "ok"
                mod.RunOrchestrator({"last_chart": "", "defaults": {}})._spawn_run(
                    hits, "g906", random_mode=False, retry_break=True, push_cap=False,
                    retry_cap=3, push_ms=10.0, multi="expert")
                to = read_json(os.path.join(tmp, "fake_tooth", "argv.json")).get("opts", {})
                check("牙：多人局那道闸门拆掉之后，同一句判据变红",
                      to.get("--retry-on-break") == "3",
                      f"变异体在多人局发的 --retry-on-break={to.get('--retry-on-break')!r}")
        finally:
            shutil.rmtree(tooth, ignore_errors=True)

        print("PART 2 解析契约：机器行、日志行、噪声行各归各位")
        ts = texts(ev1)
        check("机器行没有变成日志行", not any("#STATUS#" in t or "#ATSELECT#" in t for t in ts))
        check("#STATUS# phase 推到了状态标签",
              ("phase", "正在演奏 1/3") in ev1 and ("phase", "正在演奏 3/3") in ev1,
              f"{[p for k, p in ev1 if k == 'phase']}")
        progs = [p for k, p in ev1 if k == "progress"]
        check("进度值单调且收在 1.0",
              bool(progs) and progs == sorted(progs) and abs(progs[-1] - 1.0) < 1e-9, f"{progs}")
        check("#ATSELECT# 记成了轮间锚点", orch.at_select is not None)
        check("原生库横幅被丢掉",
              not any("nemu_connect" in t or "connect not same day" in t for t in ts))
        errs = [p for k, p in ev1 if k == "log_err"]
        check("!! 行判成错误行", any("断键" in t for t in errs), f"{errs}")
        check("!! 标记被剥掉", not any("!!" in t for t in errs))
        check("链路校准行判成抬头",
              any("链路校准" in p for k, p in ev1 if k == "log_hdr"))
        check("ALL PERFECT 行判成结论",
              any("ALL PERFECT" in p for k, p in ev1 if k == "log_ok"))
        check("导航行判成过程",
              any("导航" in p for k, p in ev1 if k == "log_dim"))
        check("时间戳留在文本里", any(t.startswith("12:00:") for t in ts))
        check("rc = 0", rc == 0, f"rc={rc}")
        check("RESULT 被解析成记录", isinstance(rec, dict) and rec.get("tag") == "g900")

        out_file = os.path.join(core.RUN_OUT_DIR, "g900.out")
        body = ""
        if os.path.exists(out_file):
            with open(out_file, encoding="utf-8") as f:
                body = f.read()
        check("<tag>.out 落在指定目录", os.path.exists(out_file))
        check("<tag>.out 里没有机器行与原生库横幅",
              "#STATUS#" not in body and "#ATSELECT#" not in body and "nemu_connect" not in body)
        check("<tag>.out 里有那两条日志行",
              "导航：乐曲选择页" in body and "断键" in body)

        print("PART 3 结算：一轮只落一行")
        row = orch.record_round("g900", "假谱", "EXPERT", rec, rc)
        rows = core.rlog.read_records(core.RESULTS)
        check("结算记录只落一行", len(rows) == 1, f"{len(rows)} 行")
        check("这一行带着 tag 与 chart",
              bool(rows) and rows[0].get("tag") == "g900" and rows[0].get("chart") == "0074_00",
              f"{rows[0].get('tag') if rows else None}")
        check("RESULT 的字段被合并进来", bool(rows) and rows[0].get("perfect") == 174)
        check("返回的就是落盘的那一行",
              row.get("tag") == "g900" and row.get("score") == 4140060)

        print("PART 4 异常路径不许留下活着的子进程")
        # 让 <tag>.out 打不开：把「输出目录」指向一个**文件**。这是真实会发生的形状 ——
        # 磁盘满、杀软锁住、目录被别的东西占了 —— 而且它发生在子进程已经起来之后。
        blocked = os.path.join(tmp, "blocked")
        with open(blocked, "w", encoding="utf-8") as f:
            f.write("not a directory\n")
        core.RUN_OUT_DIR = blocked
        rc4, rec4, A4, d4 = spawn(orch, "g903", "stuck",
                                  random_mode=False, retry_break=False, push_cap=True,
                                  retry_cap=3, push_ms=10.0)
        leaked_pid = A4.get("pid")
        check("写不进 <tag>.out 时这一轮如实失败", rc4 == -1, f"rc={rc4}")
        check("失败原因进了日志",
              any("启动 run.py 失败" in p for k, p in drain(orch.q) if k == "log_err"))
        hb = os.path.join(d4, "heartbeat")
        t0 = time.time()
        while not os.path.exists(hb) and time.time() - t0 < 8:
            time.sleep(0.05)
        n1 = os.path.getsize(hb) if os.path.exists(hb) else 0
        time.sleep(0.7)
        n2 = os.path.getsize(hb) if os.path.exists(hb) else 0
        # 证据要自己说清是哪一种情形：收掉得足够快时替身连 argv 都没写完，那不是「判据成立」，
        # 那只是「它根本没活到能被判」。两种都算通过，但读的人要知道自己看的是哪一种。
        started = os.path.exists(os.path.join(d4, "argv.json"))
        check("子进程已经被收掉（心跳不再长）", n2 == n1,
              f"替身{'起来过' if started else '没来得及写 argv'}，心跳 {n1} -> {n2} 字节"
              + ("（子进程还活着）" if n2 != n1 else ""))

        print("PART 5 没有 RESULT 行的一局")
        os.environ["HYOUSHI_FAKE_SCENARIO"] = "fail"
        os.environ["HYOUSHI_FAKE_DIR"] = os.path.join(tmp, "fake_g902")
        core.RUN_OUT_DIR = os.path.join(tmp, "out")
        rc5, rec5 = orch._spawn_run(hits, "g902", random_mode=False, retry_break=False,
                                    push_cap=True, retry_cap=3, push_ms=10.0)
        drain(orch.q)
        check("退出码如实回报", rc5 == 3, f"rc={rc5}")
        check("没有 RESULT 行就没有记录", rec5 is None, f"{rec5!r}")
        row5 = orch.record_round("g902", "假谱", "EXPERT", rec5, rc5)
        check("异常局照样落一行（带 rc，不带假字段）",
              row5.get("rc") == 3 and row5.get("all_perfect") is None, f"{row5}")

        print("PART 7 更新那条管道：交给 Popen 的 argv 起得来吗")
        # 用户 m09816 报「更新功能损坏了」：`_update_loop` 传的是 `[脚本路径, …]` 这种形状，而
        # `_stream_tool` 从前只在 `isinstance(cmd, str)` 时补解释器 ⇒ Windows 直接去执行那个 .py，
        # `CreateProcess` 报 `OSError(8, '%1 不是有效的 Win32 应用程序。', None, 193, None)`
        # （193 = ERROR_BAD_EXE_FORMAT）。面板上「联网更新」自 2026-10-06（`ace8e77a` 全面转 Flet
        # 那一笔）起两趟都起不来 —— PART 1 那种「命令行里有没有这个词」的判据看不见它，所以这一关
        # 量的是**真 argv**。不联网、不起真进程：把 `subprocess.Popen` 换成一个只记账的替身。
        seen: list = []

        class _FakePopen:
            def __init__(self, cmd, **kw):
                seen.append((list(cmd), dict(kw)))
                self.stdout = iter(())          # 空输出：`_pump_child` 立刻收工
                self.pid = 0

            def wait(self, timeout=None):
                return 0

            def kill(self):
                pass

        def argv_of(mod, call):
            """跑 `call(mod)`，返回它交给 Popen 的 argv（Popen 立刻换回来）。"""
            del seen[:]
            real = mod.subprocess.Popen
            mod.subprocess.Popen = _FakePopen
            try:
                call(mod)
            finally:
                mod.subprocess.Popen = real
            return [c for c, _ in seen]

        def updatable(up):
            """这一关的判据本身 —— 牙要拿同一句话去量变异体。"""
            return (len(up) == 2 and up[0][0] == sys.executable
                    and up[0][1].endswith("check_upstream.py")
                    and up[1][0] == sys.executable
                    and up[1][1].endswith("fetch_charts.py"))

        up = argv_of(core, lambda m: m.RunOrchestrator({})._update_loop(False))
        check("「联网更新」两趟都真的起得来（比对 + 补下载）", updatable(up),
              "；".join(" ".join(os.path.basename(x) for x in a) for a in up) or "一次 Popen 都没有")
        shapes = argv_of(core, lambda m: [m.RunOrchestrator({})._stream_tool(s, "形状")
                                          for s in (os.path.join(TOOLS, "check_upstream.py"),
                                                    [os.path.join(TOOLS, "check_upstream.py")],
                                                    [os.path.join(TOOLS, "check_upstream.py"),
                                                     "--verify"])])
        check("三种形状（str / 单元素列表 / 带选项）都补上解释器",
              len(shapes) == 3 and all(a[0] == sys.executable for a in shapes)
              and [os.path.basename(a[-1]) for a in shapes]
              == ["check_upstream.py", "check_upstream.py", "--verify"],
              "、".join(" ".join(os.path.basename(x) for x in a) for a in shapes))
        check("起子进程的两个条件还在：cwd 是仓库根、编码钉成 UTF-8",
              len(seen) == 3 and all(k.get("cwd") == ROOT
                                     and (k.get("env") or {}).get("PYTHONIOENCODING") == "utf-8"
                                     for _, k in seen),
              f"{len(seen)} 次 Popen")

        # 牙：把归一化拆回修前的样子（只认 `str`）—— 同一句判据必须在变异体上变红。变异体放在
        # `<tmp>/tools/panel_core.py`，于是它自己算出来的 ROOT 也是 `<tmp>`（形状与真身一致）。
        tooth = tempfile.mkdtemp(prefix="panelfly-tooth-")
        try:
            os.makedirs(os.path.join(tooth, "tools"), exist_ok=True)
            src = io.open(os.path.join(TOOLS, "panel_core.py"), encoding="utf-8").read()
            old = ('        if isinstance(cmd, str):\n'
                   '            cmd = [cmd]\n'
                   '        cmd = [str(x) for x in cmd]\n'
                   '        if cmd and cmd[0].lower().endswith(".py"):\n'
                   '            cmd = [sys.executable, *cmd]\n')
            new = ('        if isinstance(cmd, str):\n'
                   '            cmd = [sys.executable, cmd]\n')
            if old not in src:
                check("牙：拆掉归一化之后，同一份判据在变异体上变红", False,
                      "锚点不在 tools/panel_core.py 里了（判据该跟着改）")
            else:
                io.open(os.path.join(tooth, "tools", "panel_core.py"), "w",
                        encoding="utf-8").write(src.replace(old, new))
                spec = importlib.util.spec_from_file_location(
                    "panelfly_mutant_core", os.path.join(tooth, "tools", "panel_core.py"))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                up2 = argv_of(mod, lambda m: m.RunOrchestrator({})._update_loop(False))
                check("牙：拆掉归一化之后，同一份判据在变异体上变红",
                      bool(up2) and up2[0][0].lower().endswith(".py") and not updatable(up2),
                      f"变异体交给 Popen 的是 "
                      f"{os.path.basename(up2[0][0]) if up2 else '（一次都没起）'}")
        finally:
            shutil.rmtree(tooth, ignore_errors=True)

        print("PART 6 隔离：真实状态与真实账本没被碰过")
        check("真实 gui_state.json 的 mtime 未变",
              os.path.getmtime(real_state) == BEFORE_STATE_MTIME)
        added = set(n for n in core.listdir(os.path.join(ROOT, "research"))
                    if n.endswith(".out")) - pre_out
        check("research/ 下没有多出 .out", not added, f"{sorted(added)}")
        real_rows = core.rlog.read_records(real_results)
        leaked = [r.get("tag") for r in real_rows
                  if r.get("tag") in ("g900", "g901", "g902", "g903", "g904", "g907",
                                      "g908", "g909")]
        check("假局没有写进真实 results.jsonl", not leaked, f"{leaked}")
    finally:
        core.STATE, core.RESULTS, core.RUN_OUT_DIR = real_state, real_results, real_out
        for k, v in real_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # 泄漏的替身必须在探针退出前收掉，否则它会一直呼吸到重启。
        if leaked_pid:
            try:
                subprocess.run(["taskkill", "/PID", str(leaked_pid), "/F"],
                               capture_output=True, timeout=20,
                               creationflags=core.CREATE_NO_WINDOW)
            except Exception:                                     # noqa: BLE001
                pass
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print(f"探针 FAIL：{len(FAILS)} 项")
        for f in FAILS:
            print("  -", f)
        return 1
    print("ALL PASS")
    return 0


BEFORE_STATE_MTIME = None

if __name__ == "__main__":
    import panel_core as _c
    try:
        BEFORE_STATE_MTIME = os.path.getmtime(_c.STATE)
    except OSError:
        BEFORE_STATE_MTIME = None
    t0 = time.time()
    rc = main()
    print(f"（{time.time() - t0:.1f}s）")
    sys.exit(rc)
