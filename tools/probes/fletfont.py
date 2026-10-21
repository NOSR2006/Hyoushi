# -*- coding: utf-8 -*-
"""探针：字体档位真的落在机器上、设置页里切一下真的当场换掉。

这是原 `qtfont.py` 的**存活部分**的继任者。Qt 那一半（`PreferNoHinting` 的灰度级数、
次像素彩边、墨量、行高、`font_aa_compare.png`）量的是 Qt 的栅格化旋钮，Flutter 里没有对应的
东西 —— 那一半随 Qt 一起消失，不假装搬得过来。搬过来的是与视图框架无关的两件事：

PART 1 三款设计字体（正文 / 中等 / 等宽）本机装着、默认档解析到的是它自己（不是回退）、
       字号阶梯就是 s/n/b/t 四档。
PART 6 两档（鸿蒙 / 澎湃）键与标签一一对应、家族链首格就是声明的那款、链尾兜底一定装得上、
       装不上就回退且**说得出来**；在设置页那一格上切一下：状态文件、页面的 `Theme.font_family`、
       提示小字、面板日志**当场**都跟着动；状态里写了不认识的档位名也不许炸。

需要真实桌面会话（要看设置页那一格、要真的 `page.theme` 换掉），与 `fletviewcheck` /
`fletfly` / `fletpanel` 同类。

跑（仓库根）：  python tools/probes/fletfont.py
牙（手工）：    python tools/probes/fletfont.py --teeth
                —— 四条守卫逐个改回修前的原文（临时副本上），每条必须**只**点亮自己那条判据。
                注：牙咬的是**视图层的布线**（`flet_gui.py`）；`m3_theme.py` 里的字体表与阶梯
                是数据，不在这里变异。
"""

import argparse
import asyncio
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)


def _utf8_console():
    """把本进程的 stdout/stderr 掰成 UTF-8（Windows 控制台默认 cp936，中文判据一印就炸）。"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                      # noqa: BLE001 —— 被换成非文本流时就算了
            pass


_utf8_console()

SELF = os.path.abspath(__file__)
PARTS = ("PART 1", "PART 6")

# 牙：`(判据里的关键词, [(原文, 改成)])`。关键词只用来**认**那条判据，不用来改代码。
TEETH = {
    "hint": (["提示小字说清了"], [
        ("        self.font_hint.value = T.font_hint(self.font_key)",
         '        self.font_hint.value = ""')]),
    "state": (["状态文件里记下了这一档"], [
        ('        self.state["font"] = self.font_key',
         '        self.state["font"] = self.state.get("font")')]),
    "paget": (["页面主题当场换成解析出来的家族"], [
        ("        fam, _fam_b, fell = T.apply_font(self.font_key)\n"
         "        T.apply(self.page, self.appearance, self.font_key)",
         "        fam, _fam_b, fell = T.apply_font(self.font_key)\n"
         "        pass")]),
    # 锚点必须连 `self._write_line(` 一起写：同一句 f-string 还给了下面的 `toast(...)`（切字体
    # 时弹的那条 snackbar），只锚 f-string 会命中 2 次、牙当场自己报「原文里出现 2 次」。
    # 判据量的是 `panel.log_store`（`texts()` 只读日志行），所以改日志行这一句就能让它变假。
    "log": (["面板日志里说了一声"], [
        ("        self._write_line(f\"字体：{T.FONTS[self.font_key]['label']}（{fam}）{note}\", \"log_ok\")",
         "        self._write_line(f\"字形：{T.FONTS[self.font_key]['label']}（{fam}）{note}\", \"log_ok\")")]),
}


class _E:
    """控件事件的替身：`_save_font` 只读 `e.control.value`。"""

    def __init__(self, control):
        self.control = control


def _run_child(fixture, out, mutant=None):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if mutant:
        env["FLETPANEL_MUTANT"] = mutant
    limit = float(os.environ.get("FLETPANEL_TIMEOUT", "240"))
    try:
        p = subprocess.run([sys.executable, SELF, "--child", fixture, out],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=ROOT, env=env, timeout=limit)
    except subprocess.TimeoutExpired:
        return 124, f"子进程 {limit:g} s 没退"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _v(vpath, row):
    with io.open(vpath, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


# ---------------------------------------------------------------- 子进程

def _child(fixture, out):
    sys.path.insert(0, TOOLS)
    mutant = os.environ.get("FLETPANEL_MUTANT")
    if mutant:
        sys.path.insert(0, mutant)

    import flet as ft
    import fletviewcheck as FV

    before = FV._corpus()
    FV._point(fixture)
    ok_guard = FV.guard()

    import m3_theme as T
    import panel_core as core

    # `tools/panel_core.py:35` 在 import 时会把 `tools/` 又插到 `sys.path` 最前，把上面那次
    # 插入顶掉；不在这儿再压一次，变异体就被真面板遮住，「牙」会静默失效。
    if mutant:
        sys.path.insert(0, mutant)
    import flet_gui as G

    print(f"[fletfont] flet_gui = {G.__file__}  mutant = {mutant}", flush=True)
    if mutant and not os.path.abspath(G.__file__).startswith(os.path.abspath(mutant)):
        raise RuntimeError(f"变异体没生效：加载的是 {G.__file__}（想要 {mutant}）")

    inst = {}

    class ProbePanel(G.Panel):
        def __init__(self, page):
            super().__init__(page)
            inst["p"] = self

    vpath = os.path.join(fixture, "verdicts.jsonl")

    async def app(page):
        page.enable_screenshots = False
        G.Panel = ProbePanel
        G.main(page)
        panel = inst["p"]
        state0 = (os.path.getmtime(core.STATE), os.path.getsize(core.STATE))
        try:
            await _parts(panel, vpath, T, core, fixture)
        except Exception:                                        # noqa: BLE001
            _v(vpath, {"part": "PART 0", "label": "探针自己炸了", "ok": False,
                       "extra": traceback.format_exc(limit=6)})
        try:
            state1 = (os.path.getmtime(core.STATE), os.path.getsize(core.STATE))
            payload = {"guard": ok_guard, "iso": FV._corpus() == before,
                       "state_written": state1 != state0}
            with io.open(out, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(payload, ensure_ascii=False, indent=1))
        finally:
            try:
                await page.window.destroy()
                await asyncio.sleep(0.5)
            finally:
                os._exit(0)

    ft.run(app, view=ft.AppView.FLET_APP)


async def _parts(panel, vpath, T, core, fixture):
    def check(part, label, ok, extra=""):
        _v(vpath, {"part": part, "label": label, "ok": bool(ok), "extra": str(extra)})

    def texts():
        return [t for _k, t in panel.log_store]

    # ---- PART 1 三款字体真的落在本机、默认档不是回退
    have = T.installed_families() or set()
    check("PART 1", "问得出这台机器装了哪些字体（不然这一关量的是空气）",
          isinstance(T.installed_families(), set) and len(have) > 50, f"{len(have)} 个字体")
    for role, fam in (("正文", T.FONTS[T.FONT_DEFAULT]["family"]),
                      ("中等（强调）", T.FONTS[T.FONT_DEFAULT]["medium"]),
                      ("等宽（日志）", T.FONT_MONO)):
        check("PART 1", f"{role}字体 {fam} 装在本机", fam in have,
              "" if fam in have else "没装 —— 面板会无声地回落到别的字体")
    T.apply_font(T.FONT_DEFAULT)
    st0 = T.font_status(T.FONT_DEFAULT)
    check("PART 1", "默认档解析出来的是它自己（不是回退）",
          st0["missing"] is False and T.font_family() == st0["want"],
          f"想要 {st0['want']}、得到 {st0['family']}，提示「{T.font_hint()}」")
    check("PART 1", "字号就是那四档，没有第五个数字",
          sorted(T.FONT_ROLE) == ["b", "n", "s", "t"]
          and all(isinstance(T.TYPES[T.FONT_ROLE[k]][0], int)
                  and 11 <= T.TYPES[T.FONT_ROLE[k]][0] <= 16 for k in T.FONT_ROLE),
          f"{ {k: T.TYPES[T.FONT_ROLE[k]][0] for k in T.FONT_ROLE} }"
          "（M3 阶梯很大，面板只取它的下端 11–16，是记在 DEVIATIONS 里的偏离）")

    # ---- PART 6 两档都在、链首链尾站得住、设置页切一下就当场换
    check("PART 6", "两档字体的标签与键一一对应，一个不多一个不少",
          T.FONT_KEYS == tuple(T.FONTS)
          and T.FONT_CHOICES == tuple(T.FONTS[k]["label"] for k in T.FONT_KEYS)
          and len(T.FONT_KEYS) == 2,
          f"{list(zip(T.FONT_KEYS, T.FONT_CHOICES))}")
    for key, spec in T.FONTS.items():
        check("PART 6", f"{spec['label']}档：家族链首格就是它自己（回退不许悄悄换掉首选）",
              spec["chain"][0] == spec["family"]
              and spec["chain_medium"][0] == spec["medium"],
              f"{spec['chain'][0]} / {spec['chain_medium'][0]}")
        check("PART 6", f"{spec['label']}档的链尾兜底字体本机装了（回退不会落到空气上）",
              spec["chain"][-1] in have and spec["chain_medium"][-1] in have,
              f"{spec['chain'][-1]} / {spec['chain_medium'][-1]}")
        st = T.font_status(key)
        check("PART 6", f"{spec['label']}档：没装就回退，装了就用它自己",
              (not st["missing"]) == (spec["family"] in have),
              f"声明 {st['want']}、实际 {st['family']}、提示「{T.font_hint(key)}」")
        check("PART 6", f"{spec['label']}档回退目标真的装了（不是解析成一个不存在的名字）",
              st["family"] in have, st["family"])

    check("PART 6", "设置页的字体格显示的是当前档",
          panel.font_box.value == panel.font_key == T.resolve_font(),
          f"格子里是 {panel.font_box.value!r}、面板认的是 {panel.font_key!r}")

    home = panel.font_key
    other = next(k for k in T.FONT_KEYS if k != home)
    olabel = T.FONTS[other]["label"]

    panel.font_box.value = other
    panel._save_font(_E(panel.font_box))
    await asyncio.sleep(0.2)
    st = T.font_status(other)
    check("PART 6", f"切到{olabel}：状态文件里记下了这一档（重开面板会记住）",
          core.read_json(core.STATE, {}).get("font") == other,
          f"font={core.read_json(core.STATE, {}).get('font')!r}")
    check("PART 6", f"切到{olabel}：解析出来的家族就是它（没装则回退到链上第一格装了的）",
          T.font_family() == st["family"], f"{T.font_family()}")
    check("PART 6", f"切到{olabel}：页面主题当场换成解析出来的家族（不是等下次启动）",
          getattr(panel.page.theme, "font_family", None) == T.font_family(),
          f"page.theme.font_family={getattr(panel.page.theme, 'font_family', None)!r}"
          f" 解析={T.font_family()!r}")
    check("PART 6", f"切到{olabel}：提示小字说清了是回退还是真装上了",
          panel.font_hint.value == T.font_hint(other) and bool(panel.font_hint.value),
          f"「{panel.font_hint.value}」")
    check("PART 6", f"切到{olabel}：面板日志里说了一声",
          any("字体" in t for t in texts()),
          next((t for t in texts() if "字体" in t), "没有这一行"))

    # 回退挡着「切了就换」这条路：链上第一格装不上时，解析结果不变，页面本来也不该变。
    # 所以再拿一个**本机装了、且和当前解析结果不同**的家族临时顶上，让解析结果真的变一次。
    real_chain = T.FONTS[other]["chain"]
    third = next((f for f in sorted(have)
                  if f != T.font_family() and f != T.FONTS[home]["family"]), None)
    if third is None:
        check("PART 6", "本机还有第三个装了的家族可以试（不然这条是空过）", False, "找不到")
    else:
        try:
            T.FONTS[other]["chain"] = (third, real_chain[-1])
            panel.font_box.value = home
            panel._save_font(_E(panel.font_box))
            panel.font_box.value = other
            panel._save_font(_E(panel.font_box))
            check("PART 6", "解析结果换了家族时，家族名当场就换（不是等下次启动）",
                  T.font_family() == third, f"{T.font_family()!r} 想要 {third!r}")
        finally:
            T.FONTS[other]["chain"] = real_chain

    panel.font_box.value = home
    panel._save_font(_E(panel.font_box))
    check("PART 6", f"切回{home}：解析出来的家族回到它",
          T.font_family() == T.FONTS[home]["family"], f"{T.font_family()}")
    check("PART 6", "状态里写了不认识的档位名 → 退回默认档（不抛、不画成别的字体）",
          T.resolve_font("comic") == T.FONT_DEFAULT
          and T.resolve_font(None) in T.FONT_KEYS,
          f"{T.resolve_font('comic')!r}")


# ---------------------------------------------------------------- 主流程

def _report(payload):
    res = payload["res"]
    bad = [r for r in res if not r["ok"]]
    # 探针自己炸了会写成 "PART 0" —— 不在 PARTS 里也必须打出来，不然失败被静默吞掉。
    for part in list(PARTS) + sorted({r["part"] for r in res} - set(PARTS)):
        rows = [r for r in res if r["part"] == part]
        nf = sum(0 if r["ok"] else 1 for r in rows)
        print(f"  {'ok  ' if not nf else 'FAIL'} {part}  {len(rows)} 条"
              f"{'' if not nf else f'，{nf} 条 FAIL'}")
        for r in rows:
            if not r["ok"]:
                print(f"      - {r['label']}  {r['extra']}")
    rc = payload.get("rc", 0)
    if rc != 0:
        last = res[-1] if res else None
        print(f"  FAIL 子进程退出码 {rc}，最后写出的判据："
              f"{last['label'] if last else '一条都没有'}")
    print(f"  guard() 写入跟随模块全局 = {payload['guard']}")
    print(f"  隔离：真实 research/ 未变 = {payload['iso']}")
    print(f"  夹具状态文件被写过 = {payload['state_written']}")
    ok = (not bad and payload["guard"] and payload["iso"]
          and payload["state_written"] and rc == 0)
    return ok, bad


def _once(mutant=None):
    import fletviewcheck as FV

    fixture = tempfile.mkdtemp(prefix="fletfont-")
    try:
        FV._fixture(fixture, "light")
        out = os.path.join(fixture, "verdicts.json")
        vpath = os.path.join(fixture, "verdicts.jsonl")
        rc, log = _run_child(fixture, out, mutant)
        rows = []
        if os.path.exists(vpath):
            with io.open(vpath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        payload = {"res": rows, "guard": False, "iso": False, "state_written": False}
        if os.path.exists(out):
            with io.open(out, encoding="utf-8") as f:
                payload.update(json.load(f))
        payload["rc"] = rc
        return payload, log
    finally:
        shutil.rmtree(fixture, ignore_errors=True)


def _teeth():
    payload, log = _once()
    ok, _bad = _report(payload)
    if not ok:
        print(f"TEETH FAIL：控制组没过，先修它\n{log[-2000:]}")
        return 1
    print("控制组 ALL PASS，开始逐条拆牙")
    allok = True
    for name, (keys, subs) in TEETH.items():
        d = tempfile.mkdtemp(prefix=f"fletfont-tooth-{name}-")
        try:
            text = io.open(os.path.join(TOOLS, "flet_gui.py"), encoding="utf-8").read()
            for old, new in subs:
                if text.count(old) != 1:
                    print(f"  FAIL 牙 {name}：原文里 {old[:60]!r} 出现 {text.count(old)} 次")
                    allok = False
                    break
                text = text.replace(old, new)
            else:
                with io.open(os.path.join(d, "flet_gui.py"), "w", encoding="utf-8",
                             newline="\n") as f:
                    f.write(text)
            payload, log = _once(d)
            failed = [r["label"] for r in payload["res"] if not r["ok"]]
            hit = [k for k in keys if any(k in lab for lab in failed)]
            if payload.get("rc") != 0:
                print(f"  FAIL 牙 {name}  子进程退出码 {payload['rc']}：{log[-400:]}")
                allok = False
            elif hit == keys and len(failed) == len(keys):
                print(f"  ok   牙 {name}  只点亮 {failed[0]!r}")
            else:
                print(f"  FAIL 牙 {name}  期望只点亮 {keys}，实际 {failed}"
                      f"（拆了守卫还全绿 = 判据是装饰）")
                allok = False
        finally:
            shutil.rmtree(d, ignore_errors=True)
    print("TEETH PASS" if allok else "TEETH FAIL")
    return 0 if allok else 1


def main():
    argv = sys.argv[1:]
    if argv[:1] == ["--child"]:
        if len(argv) < 3:
            raise SystemExit("用法：--child <fixture> <out.json>")
        _child(argv[1], argv[2])
        return 0

    ap = argparse.ArgumentParser(description="Flet 面板：字体档位与设置页切换")
    ap.add_argument("--teeth", action="store_true",
                    help="四条守卫逐个改回修前的原文（临时副本），每条只点亮自己那条判据")
    args = ap.parse_args()

    t0 = time.time()
    if args.teeth:
        print("fletfont --teeth  四条守卫逐个拆掉重放")
        return _teeth()

    print("fletfont  三款字体落在本机、两档切换当场生效（真窗口）")
    payload, log = _once()
    if not payload["res"]:
        print(f"  FAIL 子进程一条判据都没写出来（退出码 {payload['rc']}）：\n{log[-2000:]}")
        return 1
    if log.strip():
        print("  （子进程输出）" + log.strip().replace("\n", "\n  "))
    ok, bad = _report(payload)
    if not ok:
        print(f"PART fletfont FAIL：{len(bad)} 条判据没守住")
        return 1
    print(f"ALL PASS（{time.time() - t0:.1f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
