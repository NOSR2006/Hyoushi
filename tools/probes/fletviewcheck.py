"""探针：Flet 面板的十二个面（六页 × 两套皮肤）与提交的基线逐像素比。

**六页**：`start` / `multi` / `log` / `log_empty` / `history` / `settings`。`multi` 是 2026-10-08
用户 m02832 新加的「多人演出」页（侧边栏「开始」改名「单人演出」、其下插一项）。日志占两个面是
有原因的 ——
`log` 走夹具语料（`_flet_smoke.LOG_FIXTURE`，五种语义 kind 各一行 + 长行 + 无时间戳那支），
`log_empty` 则故意一行都不写：日志页的 `log_view` 与两张空态都是 `expand=True` 的兄弟，谁显谁
隐决定了整页版式。从前只有一个「日志」面、而且一行语料都不铺，拍到的正是「两个都可见、各占
一半」那个真机上只存在一两帧的状态（空态落在下半格），把空态的正确位置（整卡居中）挡在了
基线之外。

**为什么存在**：`fletgui` 量的是源码与规范表，它看不见面板长什么样。2026-10-05 那个
「结算页整片被一块 `#C0C0C0` 盖住」的 bug（Flutter 的 `Wrap` 收到 `Expanded` 孩子 →
布局抛异常 → 外层容器被错误控件替掉）就是只有拍照才能发现的：`fletgui` 的 PART 1 现在能静态
拦住它，但**当时**谁也没想到要去拦。这个文件接的是原 `tools/probes/qtviewcheck.py`（已随 Qt 删掉）：
沿用它三个**已经证明过**的设计，不重新发明：

  * **夹具语料，不是活的 `research/`** —— 截图不许随用户的谱面库、结算记录、链路标定变；
  * **每个 (页, 皮肤) 一个全新进程** —— 一条 Flet 会话的窗口、字体缓存与 DPR 会互相带；
    更要紧的是 `page.take_screenshot()` **会返回旧帧**（实测：同一个会话里改了状态不制造一次
    可见变化，连拍五张的字节完全相同），一页一个进程 + 切一次页签正好绕开它；
  * **每通道 `DELTA = 24`、差异像素按实测标定** —— 前者远高于抗锯齿抖动、远低于「控件换了
    颜色」；后者见下面的 `BUDGET`。

**它需要真实桌面会话**（Flet 客户端是一个真的 Flutter 窗口，没有离屏模式），所以它**不属于**
零设备零联网那一批 —— 与 `fletpanel.py` / `fletfont.py` / `fletfly.py` 同类。它不碰模拟器、不起 `run.py`、不写真实语料。

**关于 2026-10-05 那次重采基线**（`settings` 两面，`start`/`history` 四面当时仍是 0 px，所以
只可能动了这两个）：补上「过渡动画」后，`_body` 挂了一个隐式不透明度动画
（`tools/flet_gui.py:430` 的 `self._body.animate_opacity = T.animation("page")`），于是整块内容
被 Flutter 合成进一个不透明度图层，**同一个几何位置上的抗锯齿会差一点点**。实测三件事：
① 拆掉这一行 → `settings` 两面回到 **0 px**；② 拆掉 `_footer_phase` 那一行没影响（不是它）；
③ 两块图里光强调色的包围盒**逐段相同**（`y 380/452/522`、`x 1083..1106` 与 `x 1093..1193`），
即控件**没有挪**。差得最多的 72/90 px 全落在三个复选框的**勾**（画布路径）边缘上（单通道最多
53）；文字与色块边缘只差 2~4，低于 `DELTA=24`，所以 `start`/`history` 两面根本量不到。
**这是图层合成的亚像素重采样，不是布局或配色变了** —— 谁要再看到它，先做上面这三步，别改面板。

**关于 m12800 那一轮（结算表表头底色照官方改回 `surface`）**：空跑只差 **2 px**（`history`
两面），因为 `DELTA = 24`，而官方 `surface`(`#121318`) 与相邻一档的 `surface_container_high`
(`#292a2f`) **每通道正好差 23** —— 阈值高一步。**逐像素比对这类「官方色 ↔ 相邻一档容器色」的
改动结构性看不见**，所以补了一条**自指**判据 `header_fill_fault`：拍下结算面之后当场用结构锚
找到表，量「表头那一条带」里有没有整档容器色（官方口径 0 px，表头若抬一档就是十几万 px），
并要求它的最常见颜色就是页面底色。它不跟基线比，因此不受 `DELTA` 限制；牙见
`_teeth_header_fill`（`--teeth` 的第二条）。token 层与源码层的证据仍由
`tools/probes/m3tokens.py` 第 10 关 ⑯ 与 `fletgui.py` PART 5 承担（后者也已从表头底色改成
量 1 px 行间线与外框）。

判定：任一 (页, 皮肤) 与基线不符 → 退出码 1。
Run from the repo root:  python tools/probes/fletviewcheck.py

**2026-10-21 退役（用户 m53748）**：十二面像素比对不再是门 —— 预算 `BUDGET` 只有 43 px，
改一句文案就超，而它从 2026-10-09 起一直是红的（没人重拍、也没拦过东西）。它**继续留着**
的只有两件事，别的探针在 import 它：① `_point()` 那套语料重绑 + `_inside()` 断言；
② `guard()`（往诱饵写一笔真 `save_state`）；③ `_corpus()` / `_fixture` / `_run_child`
（`fletpanel`、`fletfont`、`fletfly` 共用）。版式改由 `fletpanel` 第 1/6/10 关的几何判据
守（数字，不受文案影响）。本文件仍可手动跑（`--update` 重拍），但**不进** `verify.py`。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)


def _utf8_console():
    """把本进程的 stdout/stderr 掰成 UTF-8。

    Windows 控制台默认 cp936：中文判据一印就 UnicodeEncodeError（重定向到文件时也一样），
    所以以前每次跑探针都得先设 `PYTHONIOENCODING=utf-8`。探针自己掰一次，这个前置条件就没了。
    """
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                      # noqa: BLE001 —— 被换成非文本流时就算了
            pass


_utf8_console()

SELF = os.path.abspath(__file__)
BASE = os.path.join(ROOT, "evidence", "view", "flet_baselines")
RESEARCH = os.path.join(ROOT, "research")

import m3_theme as _T  # noqa: E402  （TOOLS 刚进 sys.path）

PAGES = ("start", "multi", "log", "log_empty", "history", "settings")
# 页签下标：0 单人演出 / 1 多人演出 / 2 日志 / 3 结算记录 / 4 设置（2026-10-08 用户 m02832 在
# 「开始」下面插了「多人演出」，后三页整体后移一位 —— 这是**独立于源码**的那份钉子）。
TABS = {"start": 0, "multi": 1, "log": 2, "log_empty": 2, "history": 3, "settings": 4}
MODES = ("light", "dark")
# 窗口尺寸直接取规范（`m3_theme.WINDOW_DEFAULT`）—— 真面板（`flet_gui.main`）就是用这一对
# 开的窗，探针要是另用一套尺寸，量到的就不是用户看见的那一版。（此前这里是写死的 1280×860，
# 而真入口压根没设过窗口尺寸，两边量的都是「当时碰巧的样子」。）
SIZE = _T.WINDOW_DEFAULT
DELTA = 24
BUDGET = 0.00002

WATCH = ("gui_state.json", "results.jsonl", "results_full.jsonl", "chain_cal.json",
         os.path.join("charts", "manifest.json"), os.path.join("charts", "validated.json"))


# ---------------------------------------------------------------- 夹具语料

BANDS = ({"bandId": 1, "name": "MyGO!!!!!"}, {"bandId": 2, "name": "Ave Mujica"})
_SONGS = (
    ("100001", "迷星叫", "Mayoiuta", 1, "0001", "mi xing jiao", "mxj"),
    ("100002", "壱空", "Hitoshizuku", 1, "0002", "yi kong", "yk"),
    ("100003", "廻廻夢", "Kaikaimu", 2, "0003", "hui hui meng", "hhm"),
)
_DDS = (("easy", "00", 9, 342), ("normal", "01", 13, 408), ("hard", "02", 20, 600),
        ("expert", "03", 26, 843))

# 六条记录覆盖结果竖条的每一种：AP / FC / 漏键 / 中断 / 读取失败 / 无漏键但非 AP。
_RECORDS = (
    {"ts": "01-01 09:02", "tag": "s001", "song": "迷星叫", "diff": "expert", "rc": 0,
     "all_perfect": True, "full_combo": True, "non_perfect": 0, "score": 11914173,
     "aborts": 0, "perfect": 787, "great": 0, "good": 0, "bad": 0, "miss": 0, "combo": 787},
    {"ts": "01-01 09:11", "tag": "s002", "song": "迷星叫", "diff": "hard", "rc": 0,
     "all_perfect": False, "full_combo": True, "non_perfect": 4, "score": 9814402,
     "aborts": 0, "perfect": 596, "great": 3, "good": 1, "bad": 0, "miss": 0, "combo": 600},
    {"ts": "01-01 09:24", "tag": "s003", "song": "壱空", "diff": "normal", "rc": 0,
     "all_perfect": False, "full_combo": False, "non_perfect": 12, "score": 6402331,
     "aborts": 0, "perfect": 388, "great": 9, "good": 2, "bad": 1, "miss": 0, "combo": 251},
    {"ts": "01-01 09:38", "tag": "s004", "song": "壱空", "diff": "easy", "rc": 1,
     "all_perfect": False, "full_combo": False, "non_perfect": None, "score": 0,
     "aborts": 2, "perfect": 0, "great": 0, "good": 0, "bad": 0, "miss": 0, "combo": 0},
    {"ts": "01-01 09:52", "tag": "s005", "song": "廻廻夢", "diff": "expert", "rc": 0,
     "all_perfect": False, "full_combo": False, "non_perfect": None, "score": 0,
     "aborts": 0, "perfect": 0, "great": 0, "good": 0, "bad": 0, "miss": 0, "combo": 0,
     "error": "结算页读不出来"},
    {"ts": "01-01 10:06", "tag": "s006", "song": "廻廻夢", "diff": "hard", "rc": 0,
     "all_perfect": False, "full_combo": False, "non_perfect": 0, "score": 8123010,
     "aborts": 1, "perfect": 600, "great": 0, "good": 0, "bad": 0, "miss": 0, "combo": 600},
    {"ts": "01-01 10:19", "tag": "s007", "song": "壱空", "diff": "normal", "rc": 0,
     "all_perfect": True, "full_combo": True, "non_perfect": 0, "score": 7120455,
     "aborts": 0, "perfect": 408, "great": 0, "good": 0, "bad": 0, "miss": 0, "combo": 408},
    {"ts": "01-01 10:33", "tag": "s008", "song": "迷星叫", "diff": "expert", "rc": 0,
     "all_perfect": False, "full_combo": False, "non_perfect": 23, "score": 10330412,
     "aborts": 3, "perfect": 741, "great": 18, "good": 3, "bad": 2, "miss": 0, "combo": 190},
)

# 两条钉子都**不写 `at.asof`**：`pin_state` 于是直接答 `unrecorded`，一次 `fingerprint()` 都不调
# —— 那会去读 `tools/compile.py` 的字节，基线就会随「谁改了一行编译器」而变。
_VALIDATED = {
    "schema": 2, "updated": "2026-10-02 00:00:00",
    "charts": {
        "0001_03": {"best": {"np": 0, "tag": "s001", "score": 11914173, "ts": "01-01 09:02"}},
        "0002_02": {"best": {"np": 12, "tag": "s007"}},
    },
}
_RELEARN = {"updated": "2026-10-02 00:00:00",
            "queue": {"0003_01": {"at": "2026-10-02 00:00:00", "candidate": "0003_01"}}}
_CHAIN = {"updated": "2026-10-02 00:00:00", "corr_ms": -10.0, "pinned": False,
          "pinned_brief": "+0.328 s / 35 票", "history": []}


def _manifest():
    songs = []
    for mid, title, roma, band, book, py, ini in _SONGS:
        diffs = [{"name": name, "dd": dd, "level": lv, "sortLevel": lv, "noteCount": nc,
                  "book": book,
                  "raw": f"research/charts/{book}_{dd}.raw.json",
                  "hits": f"research/charts/{book}_{dd}.hits.json"}
                 for name, dd, lv, nc in _DDS]
        songs.append({"musicId": mid, "title": title, "titleRomaji": roma, "bandId": band,
                      "band": BANDS[band - 1]["name"], "bandZh": BANDS[band - 1]["name"],
                      "py": py, "pyJoin": py.replace(" ", ""), "pyInitials": ini,
                      "difficulties": diffs})
    return {"server": "intl", "fetched_at": "2026-10-02 00:00:00",
            "bands": [dict(b) for b in BANDS], "songs": songs}


def _state(mode):
    return {
        "appearance": mode, "sort_mode": "乐队优先", "sort_desc": 0,
        "next_index": 7, "last_chart": "0001_03", "last_diff_dd": "03",
        "diff_by_song": {"100001": "03"}, "auto_clean": 1, "follow_game": 1,
        "defaults": {"runs": 3, "stop_on_ap": 1, "random": 0, "retry_on_break": 1,
                     "push_cap": 1, "retry_cap": 5, "push_cap_ms": 0.0, "gap_min": 0.0},
    }


def _wj(path, obj):
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def _fixture(root, mode):
    """在临时目录里造一棵完整 research/。每个 (页, 皮肤) 各造一次 —— 面板会往
    `gui_state.json` 里写 `diff_by_song`/`last_diff_dd`，下一张照片不该看见上一张的脚印。"""
    for d in ("charts", "runs", "frames", "result", os.path.join("archive", "runs")):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    _wj(os.path.join(root, "charts", "manifest.json"), _manifest())
    _wj(os.path.join(root, "charts", "validated.json"), _VALIDATED)
    _wj(os.path.join(root, "charts", "_relearn.json"), _RELEARN)
    _wj(os.path.join(root, "chain_cal.json"), _CHAIN)
    _wj(os.path.join(root, "gui_state.json"), _state(mode))
    rows = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in _RECORDS)
    for name in ("results.jsonl", "results_full.jsonl"):
        with io.open(os.path.join(root, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(rows)


# ---------------------------------------------------------------- 隔离

def _point(fixture):
    """把面板会读会写的每一个路径指到夹具里。这份清单原来是 `qtviewcheck._point` 的（那个探针已随 Qt 删掉），`panel_core` 的路径常量一个都没变。"""
    import panel_core as core
    import rlog

    rlog.retarget(fixture)
    rlog.PINS = os.path.join(fixture, "pins")
    rlog.PINS_INDEX = os.path.join(rlog.PINS, "INDEX.json")
    rlog.RELEARN = os.path.join(rlog.CHARTS, "_relearn")
    rlog.RELEARN_INDEX = os.path.join(rlog.CHARTS, "_relearn.json")
    rlog.SOURCES = os.path.join(rlog.CHARTS, "_sources", "state.json")

    core.STATE = os.path.join(fixture, "gui_state.json")
    core.RESULTS = rlog.RESULTS
    core.MANIFEST = rlog.MANIFEST
    core.VALIDATED = rlog.VALIDATED
    core.UPSTREAM_REPORT = os.path.join(fixture, "upstream_check.json")
    core.RUN_OUT_DIR = fixture
    core.RUN_DIRS = (rlog.RESULT, rlog.RUNS, fixture, os.path.join(fixture, "archive", "runs"))
    _inside(fixture)


def _inside(fixture):
    import panel_core as core
    import rlog

    rootdir = os.path.abspath(fixture)
    root = rootdir + os.sep

    def under(p):
        a = os.path.abspath(p)
        return a == rootdir or a.startswith(root)

    watched = {
        "panel_core.STATE": core.STATE, "panel_core.RESULTS": core.RESULTS,
        "panel_core.MANIFEST": core.MANIFEST, "panel_core.VALIDATED": core.VALIDATED,
        "panel_core.RUN_OUT_DIR": core.RUN_OUT_DIR,
        "panel_core.UPSTREAM_REPORT": core.UPSTREAM_REPORT,
        "rlog.RESEARCH": rlog.RESEARCH, "rlog.MANIFEST": rlog.MANIFEST,
        "rlog.VALIDATED": rlog.VALIDATED, "rlog.RESULTS": rlog.RESULTS,
        "rlog.HISTORY_FULL": rlog.HISTORY_FULL, "rlog.CHAIN_CAL": rlog.CHAIN_CAL,
        "rlog.RELEARN_INDEX": rlog.RELEARN_INDEX, "rlog.SOURCES": rlog.SOURCES,
        "rlog.PINS": rlog.PINS,
    }
    leak = {k: v for k, v in watched.items() if not under(v)}
    leak.update({f"panel_core.RUN_DIRS[{i}]": p
                 for i, p in enumerate(core.RUN_DIRS) if not under(p)})
    if leak:
        raise SystemExit("夹具没关严，这些常量还指着真实语料：" + ", ".join(sorted(leak)))


def _digest(path):
    try:
        with io.open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def guard():
    """带牙的隔离护栏：把 `panel_core.STATE` 指到诱饵上，同一笔 `save_state` 必须落到诱饵里，
    而真实的 `research/gui_state.json` 摘要一位不变。没有这一关，「我们重定向了 STATE」
    只是代码里的一句声明。"""
    import panel_core as core

    real = core.STATE
    tmp = tempfile.mkdtemp(prefix="fletviewguard-")
    decoy = os.path.join(tmp, "decoy_state.json")
    before = _digest(real)
    try:
        core.STATE = decoy
        core.save_state({"probe": "fletviewcheck", "aimed_at": decoy})
        landed = _digest(decoy) is not None
        after = _digest(real)
    finally:
        core.STATE = real
        shutil.rmtree(tmp, ignore_errors=True)
    ok = bool(landed and before is not None and before == after)
    print(f"  夹具状态 {real}；把它指到诱饵后同一笔写入落到诱饵={landed}，"
          f"真文件摘要未变={before == after}")
    print(f"  {'ok  ' if ok else 'FAIL'} GUARD")
    return ok


# ---------------------------------------------------------------- 拍照（子进程）

def _shoot(page_name, mode, fixture, out):
    """子进程里的那一半：一间干净的屋子，一个窗口，一张照片。

    **一页一个进程**是刻意的：`page.take_screenshot()` 会把上一次的帧还给你，除非这中间
    发生过一次可见变化。一个进程只拍一页，切页签那一下就是那次变化（`start` 那页则是窗口
    第一次画出来）。
    """
    _point(fixture)
    import asyncio

    import flet as ft
    import flet_gui as G

    async def main(page: ft.Page):
        page.enable_screenshots = True
        page.window.width = SIZE[0]
        page.window.height = SIZE[1]
        page.window.min_width = G.T.WINDOW_MIN[0]
        page.window.min_height = G.T.WINDOW_MIN[1]
        # 行悬停态会随鼠标位置变（窗口就开在光标底下）⇒ 基线必须量静止帧：建面板**之前**关掉
        # （`_hist_row` 是在建表的时候读它的）。见 `m3_theme.HOVER_STATE` 的注释。
        G.T.HOVER_STATE = False
        panel = G.Panel(page)
        root = panel.build()
        # 窗口开在鼠标底下时 Flutter 会给光标下的控件弹默认 tooltip，把一块反色方块拍进
        # 基线（2026-10-05 实测：`start_*` 两张基线各多一块 534×38，鼠标一移开就报
        # 20014 px）。tooltip 只在悬停时画，摘掉它不改变静止帧。见 `_flet_smoke.strip_tooltips`。
        from _flet_smoke import strip_tooltips, tooltips
        n_tips = strip_tooltips(root)
        left = tooltips(root)
        if n_tips == 0 or left:
            sys.stderr.write(
                f"SHOOT-FAIL {page_name}/{mode}: 摘 tooltip 这道闸没起作用"
                f"（摘了 {n_tips} 个，摘完还剩 {len(left)} 个）—— 截图会跟着鼠标位置变。\n")
            sys.stderr.flush()
            os._exit(1)
        page.add(root)
        page.update()

        # 「曲目列表是活的」这一条必须在这里断言，不能只靠像素比对：2026-10-05 测出来的真
        # bug —— 分类下拉框从来没被 `cat_map` 填过、它的值是空串，而 `filtered_songs` 把
        # 空串当成「必须等于这个 bandId」（bandId 是 int）→ **一首都不剩**。面板从第一帧起
        # 就是空的，六个面的基线也全都把空列表拍了进去 —— 像素比对看不出「少了一整块」，
        # 因为基线本身少的就是同一块。夹具里的歌是全部通过筛选的，所以这里要求逐一对上。
        want = len(panel.manifest.get("songs") or [])
        got = len(panel.songs)
        shown = len(panel.song_list.controls)
        cat = getattr(panel, "cat_box", None)
        if want == 0 or got != want or shown != want:
            sys.stderr.write(
                f"SHOOT-FAIL {page_name}/{mode}: 曲目列表不对 "
                f"（manifest {want} 首 / panel.songs {got} / 渲染 {shown} 行，"
                f"分类下拉 value={getattr(cat, 'value', None)!r} "
                f"options={len(getattr(cat, 'options', []) or [])}）\n")
            sys.stderr.flush()
            os._exit(1)                              # 硬退：异常在 Flet 的任务里只会被记一行日志

        # 日志面分两个：`log` 铺夹具语料（没有它，基线里的日志页一条日志行都没有），
        # `log_empty` 故意不铺 —— 空态自己的位置与排他要有个面钉住。
        if page_name == "log":
            from _flet_smoke import seed_log
            seed_log(panel)

        await asyncio.sleep(1.2)                     # 等首帧落定
        panel.show_tab(TABS[page_name])
        # 再等动效落定 —— 最长的一档是 `MOTION["flash"]` = extended1 = 700 ms，而设置页上
        # 确实有一次**较晚**的文字刷新会走 `_set_phase` 的淡入。`FLET_SETTLE` 是给
        # 「到底是我拍在半路上，还是它真的在周期性地动」留的旋钮（默认 0.8 s = 老值）。
        await asyncio.sleep(float(os.environ.get("FLET_SETTLE", "0.8")))
        png = await page.take_screenshot()
        # 结算面的表头底色：逐像素比对看不见「官方色 ↔ 相邻一档容器色」（差 23 < DELTA 24），
        # 所以在拍下这一帧之后**当场**用自指判据量一遍，不靠基线。见 `header_fill_fault`。
        if page_name == "history":
            fault = header_fill_fault(png, mode)
            if fault:
                sys.stderr.write(f"SHOOT-FAIL {page_name}/{mode}: {fault}\n")
                sys.stderr.flush()
                os._exit(1)
            print(f"header-fill ok {page_name}/{mode}")
        with io.open(out, "wb") as f:
            f.write(png)
        print(f"shot {page_name}/{mode} {len(png)} bytes -> {out}")
        await page.window.destroy()

    ft.run(main, view=ft.AppView.FLET_APP)


def _run_child(page, mode, fixture, out):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, SELF, "--shoot", page, mode, fixture, out],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT, env=env)
    if p.returncode != 0:
        raise SystemExit(f"子进程 {page}/{mode} 退出码 {p.returncode}：\n{p.stdout}\n{p.stderr}")
    return p.stdout or ""          # 子进程里那些「当场自证」的行（表头底色）要能进父进程的日志
    return p.stdout or ""


# ---------------------------------------------------------------- 比对

def _diff(a, b):
    # 两边都并到 RGB：`take_screenshot()` 给的是 RGBA，而 `_corrupt` 动过的那张是 RGB
    # （第一次做牙时就是在这里撞的 `could not be broadcast together`）。
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    if ia.size != ib.size:
        return -1, f"尺寸 {ia.size} vs {ib.size}"
    d = np.abs(np.asarray(ia, dtype=np.int16) - np.asarray(ib, dtype=np.int16)).max(axis=2)
    bad = int((d > DELTA).sum())
    budget = int(BUDGET * ia.size[0] * ia.size[1])
    return bad, f"{bad} px / 预算 {budget} px"


def _corrupt(path):
    """弄坏一张基线的 24×24 像素块：挑**内容最花**的那一块，原样挪开 40 像素。

    挑「最花」而不是随手取中间：挪一块纯背景**一个像素都不会变**，那样的牙是假的。
    只对临时副本用，见 `--teeth`。
    """
    im = Image.open(path).convert("RGB")
    a = np.asarray(im.convert("L"), dtype=np.float64)
    h, w = a.shape
    k = 24
    best, bs = (w // 3, h // 3), -1.0
    for y in range(0, h - k, k):
        for x in range(0, w - k, k):
            s = float(a[y:y + k, x:x + k].std())
            if s > bs:
                bs, best = s, (x, y)
    x, y = best
    im.paste(im.crop((x, y, x + k, y + k)), (x + 40, y + 40))
    im.save(path, "PNG")
    return bs, best


# ---------------------------------------------------------------- 表头底色（像素层）

BAND_STEP_MAX = 2000        # 表头带里整档容器色的允许上限（官方口径下实测 0 px）


def _rgb(s):
    """`"#1a1b21"` -> `np.int16[3]`（令牌给的是十六进制字符串）。"""
    s = str(s).lstrip("#")
    return np.array([int(s[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.int16)


def _anchor_lines(a, line_rgb):
    """在结算面里用结构找表：两条竖边框 + 若干横线。返回 `(left, right, [(y0,y1)...])`，找不到 None。

    全是几何锚，不写死坐标 —— 基线是 1898×1144（客户端区 ×1.48 的 DPR），换台机器缩放
    不同也照样找得到。**锚按线的颜色找（`outline_variant`），不按「和底色不一样」找**：
    表的横线、竖边框都是 `outline_variant`（实测 y=96 与 x=408/1865 各有 678~1898 px 命中），
    而表头若被抬成一档容器色，那一整带都会「和底色不一样」—— 用底色当判据的话，判据会被
    它要抓的那个毛病自己搞瞎。线是 1 px 核心 + 一条抗锯齿的过渡行，所以连续行并成一条。
    """
    h, w = a.shape[:2]
    hit = np.abs(a.astype(np.int16) - line_rgb).max(axis=2) <= 2
    cols = hit.sum(axis=0)
    vx = np.nonzero(cols > 0.30 * h)[0]
    if len(vx) < 2:
        return None
    left, right = int(vx.min()), int(vx.max())
    if right - left < 0.30 * w:
        return None
    rows = hit[:, left + 2:right - 1].sum(axis=1)
    ys = [y for y in range(h) if rows[y] > 0.50 * (right - left)]
    if len(ys) < 3:
        return None
    lines, y0 = [], ys[0]
    for i in range(1, len(ys)):
        if ys[i] != ys[i - 1] + 1:
            lines.append((y0, ys[i - 1]))
            y0 = ys[i]
    lines.append((y0, ys[-1]))
    if len(lines) < 3:
        return None
    return left, right, lines


def header_fill_fault(png, mode):
    """结算表表头那一条带的底色必须就是页面底色（官方 `header-container-color = surface`）。

    这是像素层**唯一**能看见「官方色 ↔ 相邻一档容器色」的地方：`DELTA = 24`，而 `surface`
    与相邻一档 `surface_container_high` 每通道正好差 23 —— 逐像素比对结构性看不见（见文件头）。
    所以这条判据**不跟基线比**，它自指：在历史面里用结构锚找到表（`_anchor_lines`），取
    「上边框之下、第一条行分隔线之上」那一条带，然后要求

      A) 带子里没有整档容器色（`surface_container_low`/`_container`/`_high`/`_highest`
         合计 ≤ `BAND_STEP_MAX` px）。官方口径下这一带只有页面底色与文字，实测 **0 px**；
         表头若用 `surface_container_high`（m12800 之前的真样子），这一带多出十几万 px。
      B) 带子里最常见的颜色就是整幅最常见的颜色（页面底色）。A) 只挡四个令牌档，B) 把
         「这一带就是页面底色」推广到任意颜色 —— 两条件一起，A) 管灵敏度（十几万 px 的
         余量），B) 管「它凭什么算底色」。

    返回故障说明；空串 = 过。**它需要真实桌面**（由 `_shoot` 在拍完那一帧之后当场调用）。

    一个前提：夹具里的结算表**没有选中行**（`hist_row_tag = None`），所以这一带里出现
    `surface_container_highest`（选中行的官方容器色）就算故障 —— 实测 0 px。哪天夹具改成
    默认选中一行，这条判据要把 `_highest` 从禁色表里去掉，同时换一条别的证据钉表头。
    """
    a = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"))
    flat = a.reshape(-1, 3)
    page = tuple(Counter(map(tuple, flat)).most_common(1)[0][0])
    tk = _T.tokens(mode)
    anch = _anchor_lines(a, _rgb(tk.outline_variant))
    if anch is None:
        return "找不到结算表的结构锚（两条竖边框 + ≥3 条横线）—— 这条判据的锚丢了"
    left, right, lines = anch
    band = a[lines[0][1] + 2:lines[1][0] - 1, left + 2:right - 1]
    if band.size == 0:
        return f"表头带取空了（上边框 y={lines[0]}、第一条行线 y={lines[1]}）"
    hit = 0
    for role in ("surface_container_low", "surface_container",
                 "surface_container_high", "surface_container_highest"):
        rgb = _rgb(getattr(tk, role))
        hit += int((np.abs(band.astype(np.int16) - rgb).max(axis=2) <= 2).sum())
    if hit > BAND_STEP_MAX:
        return (f"表头带（y {lines[0][1] + 2}..{lines[1][0] - 2}、x {left + 2}..{right - 2}）里有 "
                f"{hit} px 整档容器色（上限 {BAND_STEP_MAX}）—— 官方 header-container-color 是 "
                f"surface（页面底色），这一带不该出现容器色")
    top, _n = Counter(map(tuple, band.reshape(-1, 3))).most_common(1)[0]
    if tuple(top) != page:
        return (f"表头带最常见的颜色 #{top[0]:02x}{top[1]:02x}{top[2]:02x} 不是页面底色 "
                f"#{page[0]:02x}{page[1]:02x}{page[2]:02x}")
    return ""


def _teeth_header_fill():
    """表头底色那条判据的牙：拿真基线改一版（离线，不开窗），判据必须变红；没改的那版必须过。

    改法是**只涂这条带的上半**（= 表头自己那 56 dp，下半是头一行数据）—— 这样带子的
    **最常见颜色仍然是页面底色**，B) 照样过、只有 A) 会红：证明干活的是「数整档容器色」
    那一条，而不是「多数决」。顺带钉住 `_shoot` 真的调了它 —— 判据写得再对，没人调就是装饰。
    """
    import inspect
    if "header_fill_fault(png" not in inspect.getsource(_shoot):
        return False, "_shoot 里没有调 header_fill_fault(png, mode) —— 判据没人用就是装饰"
    src = os.path.join(BASE, "history_dark.png")
    if not os.path.exists(src):
        return False, f"没有基线可改：{src}"
    tmp = tempfile.mkdtemp(prefix="fletviewband-")
    try:
        good = os.path.join(tmp, "good.png")
        shutil.copyfile(src, good)
        with io.open(good, "rb") as f:
            msg0 = header_fill_fault(f.read(), "dark")
        if msg0:
            return False, f"没改过的真基线就报故障：{msg0}"
        a = np.asarray(Image.open(good).convert("RGB")).copy()
        anch = _anchor_lines(a, _rgb(_T.tokens("dark").outline_variant))
        if anch is None:
            return False, "结构锚丢了，改不动这条基线"
        left, right, lines = anch
        mid = lines[0][1] + 2 + max(1, (lines[1][0] - lines[0][1]) // 2)
        a[lines[0][1] + 2:mid, left + 2:right - 1] = _rgb(_T.tokens("dark").surface_container_high)
        bad = os.path.join(tmp, "bad.png")
        Image.fromarray(a).save(bad, "PNG")
        with io.open(bad, "rb") as f:
            msg1 = header_fill_fault(f.read(), "dark")
        if not msg1:
            return False, "把表头上半涂成 surface_container_high 之后判据还全绿"
        return True, f"真基线过；表头涂成 surface_container_high 后报「{msg1}」"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 隔离验收

def _stat(rel):
    p = os.path.join(RESEARCH, rel)
    try:
        st = os.stat(p)
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns, _digest(p) if rel == "gui_state.json" else None)


def _corpus():
    return {rel: _stat(rel) for rel in WATCH}


def _iso(before, after):
    changed = [rel for rel in WATCH if before[rel] != after[rel]]
    g = after["gui_state.json"]
    sha = (g[2] or "—")[:16]
    print(f"  隔离验收  research/gui_state.json  sha256 {sha}…  mtime {g[1] if g else '—'}  "
          f"（前后一致={before['gui_state.json'] == g}）")
    if changed:
        for rel in changed:
            print(f"  FAIL 隔离  research/{rel}  被这一趟改动了："
                  f"{before[rel]} -> {after[rel]}")
        return False
    print(f"  ok   隔离  另 {len(WATCH) - 1} 个记录文件 size+mtime 未变")
    return True


# ---------------------------------------------------------------- 主流程

def _shots(only):
    pages = [only] if only else list(PAGES)
    return [(page, mode) for mode in MODES for page in pages]


def _run(base, only, update):
    os.makedirs(base, exist_ok=True)
    out = {}
    for page, mode in _shots(only):
        name = f"{page}_{mode}"
        bpath = os.path.join(base, f"{name}.png")
        fixture = tempfile.mkdtemp(prefix=f"fletview-{name}-")
        try:
            _fixture(fixture, mode)
            shot = os.path.join(fixture, "shot.png")
            try:
                clog = _run_child(page, mode, fixture, shot)
            except SystemExit as e:
                print(f"  FAIL {name}  {e}")
                out[name] = (False, str(e), -1)
                continue
            # 子进程里当场做的自证（结算面的表头底色，见 `header_fill_fault`）：它过了才轮到
            # 逐像素比对，所以这一行是「这条判据真的在跑」的现场证据，不能只留在子进程里。
            for ln in clog.splitlines():
                if ln.startswith("header-fill"):
                    print("  " + ln.strip())
            if update:
                shutil.copyfile(shot, bpath)
                kb = os.path.getsize(bpath) / 1024.0
                with Image.open(bpath) as im:
                    size = im.size
                print(f"  baseline written  {name}  {size[0]}x{size[1]}  {kb:.1f} KB")
                out[name] = (True, "written", 0)
                continue
            if not os.path.exists(bpath):
                extra = f"没有基线（先跑 --update）{bpath}"
                print(f"  FAIL {name}  {extra}")
                out[name] = (False, extra, -1)
                continue
            bad, extra = _diff(bpath, shot)
            with Image.open(bpath) as im:
                budget = int(BUDGET * im.size[0] * im.size[1])
            ok = bad >= 0 and bad <= budget
            print(f"  {'ok  ' if ok else 'FAIL'} {name}  {extra}")
            out[name] = (ok, extra, bad)
        finally:
            shutil.rmtree(fixture, ignore_errors=True)
    return out


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == "--shoot":
        if len(argv) < 5:
            raise SystemExit("用法：--shoot <page> <mode> <fixture> <out>")
        _shoot(argv[1], argv[2], argv[3], argv[4])
        return 0

    import argparse
    ap = argparse.ArgumentParser(description="Flet 面板的十二个面与提交基线逐像素比")
    ap.add_argument("--update", action="store_true", help="重新拍照并采认为基线")
    ap.add_argument("--only", choices=PAGES, help="只跑一页（两套皮肤都跑）")
    ap.add_argument("--teeth", action="store_true",
                    help="在基线的临时副本上故意弄坏一块，证明这段比对会 FAIL")
    args = ap.parse_args()
    if args.teeth and args.update:
        raise SystemExit("--teeth 与 --update 不能同时用")

    t0 = time.time()
    print("fletviewcheck  Flet 面板十二个面（六页 × 两套皮肤）与提交基线逐像素比")

    before = _corpus()
    base = BASE
    teeth_name = None
    if args.teeth:
        base = tempfile.mkdtemp(prefix="fletviewteeth-")
        for page in PAGES:
            for mode in MODES:
                src = os.path.join(BASE, f"{page}_{mode}.png")
                if os.path.exists(src):
                    shutil.copyfile(src, os.path.join(base, f"{page}_{mode}.png"))
        page, mode = _shots(args.only)[0]
        teeth_name = f"{page}_{mode}"
        victim = os.path.join(base, f"{teeth_name}.png")
        if not os.path.exists(victim):
            raise SystemExit(f"--teeth 要先有基线：{victim} 不存在（先跑一次 --update）")
        bs, (bx, by) = _corrupt(victim)
        print(f"  teeth  {teeth_name}  最花的一块 24×24 在 ({bx},{by})（std {bs:.1f}）"
              f"已挪开 40 像素；只动了临时副本 {base}")

    ok_guard = guard()
    results = _run(base, args.only, args.update)
    ok_iso = _iso(before, _corpus())
    if args.teeth:
        shutil.rmtree(base, ignore_errors=True)

    fails = [n for n, (ok, _e, _b) in results.items() if not ok]
    nfail = len(fails) + (0 if ok_guard else 1) + (0 if ok_iso else 1)

    if teeth_name:
        bad = results.get(teeth_name, (False, "", -1))[2]
        teeth_ok = fails == [teeth_name] and bad > int(BUDGET * SIZE[0] * SIZE[1])
        print(f"  {'ok  ' if teeth_ok else 'FAIL'} TEETH  {teeth_name}  {bad} px "
              f"（阈值 DELTA={DELTA}）")
        band_ok, band_txt = _teeth_header_fill()
        print(f"  {'ok  ' if band_ok else 'FAIL'} TEETH  header-fill  {band_txt}")
        if teeth_ok and band_ok:
            print(f"TEETH PASS（{time.time() - t0:.1f}s）")
            return 0
        if not teeth_ok:
            print(f"TEETH FAIL：弄坏的那一张没报差异，或连坐了别的行 {fails}")
        if not band_ok:
            print("TEETH FAIL：表头底色那条自指判据的牙没咬住")
        return 1

    if nfail:
        print(f"PART fletviewcheck FAIL：{nfail} 项")
        for n in fails:
            print(f"  - {n}  {results[n][1]}")
        if not ok_guard:
            print("  - GUARD  写入没有跟随模块全局（隔离是声明，不是事实）")
        if not ok_iso:
            print("  - 隔离  真实 research/ 被这一趟动过")
        return 1

    print(f"ALL PASS（{time.time() - t0:.1f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
