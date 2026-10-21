# -*- coding: utf-8 -*-
"""Flet 面板的截图工具：把面板拍成 PNG，供 `probes/fletgui.py` 第 5 关与出口早闸判。

用法：
    .venv\\Scripts\\python.exe tools\\_flet_smoke.py --appearance dark --prefix flet
    .venv\\Scripts\\python.exe tools\\_flet_smoke.py --appearance light --prefix flet_light
    .venv\\Scripts\\python.exe tools\\_flet_smoke.py --appearance both     # 一个进程拍两套

它做三件事：① 把真实状态文件复制到 %TEMP% 再改 appearance（**绝不写用户的
research/gui_state.json**）；② 用 `flet_gui.Panel` 起一个真窗口；③ 逐页签
`page.take_screenshot()` 存到 evidence/view/。

**切页签之后要等 1.2 秒，不是 0.7**（2026-10-05，加了换页淡入之后实测的）：
`take_screenshot` 拿到的是**客户端已经呈现过的那一帧**，而淡入（`MOTION["page"]`
= medium2 = 300 ms）把「落定的那一帧」推后了。同一个进程里连拍四张时，0.7 s 与
0.8 s 都会拍到**空白页**（`history` 与 `settings` 两张**字节完全相同**，33920 B），
0.9 s 起才对。代价是每张等 1.2 s；`_flet_smoke.py` 与 `fletviewcheck.py` 的区别在
后者**每个面起一个独立进程**（所以它 0.8 s 就够）。
"""

import argparse
import asyncio
import io
import json
import logging
import os
import sys
import tempfile

import flet as ft

# Flet 默认把客户端那边报上来的错误交给 logging 就完了，没有 handler 就等于没有。
# 冒烟工具存在的意义就是「看得见」，所以这里把日志打开。
# 前缀 2026-10-20 从 BANG_ 改成 HYOUSHI_（旧写法照样认）
logging.basicConfig(level=(os.environ.get("HYOUSHI_FLET_LOG")
                           or os.environ.get("BANG_FLET_LOG") or "WARNING"),
                    format="%(levelname)s %(name)s: %(message)s")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

OUT_DIR = os.path.join(ROOT, "evidence", "view")
TABS = ("start", "multi", "log", "history", "settings")
# 切页签后的等待：见文件头 —— 0.7/0.8 s 会拍到空白页，0.9 s 起才对，留到 1.2 s。
SETTLE = 1.2

# 日志面的夹具语料：**`LOG_KIND` 的五个 kind 一个不落 + 一条长行 + 一条没有时间戳的**。
#
# 从前这里一行都不写，而 `log_view` 与空态都是 `expand=True` 的兄弟：那张「日志」基线于是停在
# 一个真机上只存在一两帧的状态（两个都可见、各占一半，空态落在下半格），而且**一条日志行都
# 没有** —— 时间戳那档灰、五种语义色、换行、错误行那层 12% 的底，像素上是零覆盖。
# 时间戳写字面量、不走 `time.strftime`：基线必须逐字节确定。
LOG_FIXTURE = (
    ("log_hdr", "10:00:00 随机选曲 → 0109_03 夢我夢中 EXPERT Lv26"),
    ("log", "10:00:01 链路校准：corr 0.0 ms，锚点 3 次一致"),
    ("log_ok", "10:00:02 ALL PERFECT 759/759 —— score 12081230，偏差 ≤ 23 ms"),
    ("log_dim", "10:00:03 结果已写入 research/results.jsonl"),
    ("log_err", "10:00:04 重锁失败：判定线置信度 0.31 低于 0.6，本轮仍按旧锚点走"),
    ("log", "10:00:05 曲中链路撞界：" + "偏移不再自适应，日志里给的是完整那份边界文本；" * 4),
    ("log_hdr", "面板已启动（Flet / Material 3）"),        # 没有时间戳的那一支
)


def seed_log(panel):
    """给日志面铺一份确定的夹具语料（见 `LOG_FIXTURE`）。

    `_write_line` 只改 Python 侧那份控件表 —— 推给客户端是泵的活（真入口里 `pump_loop` 每
    `PUMP_MS` 推一次 `log_view`）。这两条拍照路径都没有泵，所以自己推一次，否则拍到的还是
    空列表（那正是从前那张基线的问题：日志面里一条日志行都没有）。
    """
    for kind, text in LOG_FIXTURE:
        panel._write_line(text, kind)
    try:
        panel.log_view.update()
    except Exception:                                        # noqa: BLE001
        pass


# Flutter 的 ErrorWidget 底色：整块异常界面就是 `#C0C0C0` 按 α≈0.94 合成上去的，
# 深色主题下量到 `#b6b6b6`、浅色主题下量到 `#c4c4c4`（那次它盖住了整个结算区、
# 1.59 M 像素）。
#
# 判的是「**一整片**近似灰」，不是「近似灰像素的**总数**」—— 2026-10-05 实测被文字
# 反锯齿骗过一次：去掉结算表的难度底色之后，历史页的灰字在页面上留下 1628 px 的孤立
# 反锯齿像素（`#b3b2b9` 1537 / `#bdbcc3` 42 / `#c1c1c2` 33 / `#b7b7b8` 16），按总数判
# 会把一张好图拦下；而腐蚀量测说它们最长只连成 8 px、四邻皆灰的 0 px、3×3 全灰的 0 块。
# 所以这里与 PART 5 用同一把尺子（`_greyish`：三通道近似相等 + 落在异常灰的亮度带里），
# 但数的是**单个颜色最多出现多少像素**：真正的 ErrorWidget 是一片平色（那次 1.59 M），
# 反锯齿摊在几十种色阶上，单色最多几百（本次最大 33）。
#
# 权威判据是 `tools/probes/fletgui.py` 的 PART 5（它按 0.1% = 约 1900 px 判灰、还正向
# 要求表头行与行首竖条都在）。这里把预算压到 **1500**，比它更紧 —— 这样从这里出去的图
# 一定能过 PART 5，两个判据不会各说各话。这里是**出口**上的早闸（坏图根本不许落地），
# PART 5 是**回归**（承认过的证据也被钉住）。PART 10 给这道闸装了牙：空白帧、`α=0.943`
# 的异常灰屏必须拦下，合成的「反锯齿灰字」必须放行。
GREY_LO, GREY_HI = 0xA8, 0xD0             # 与 `probes/fletgui.py` PART 5 同一把尺子
ERROR_GREY_BUDGET = 1500                  # 上限是「一个颜色一片有多大」，不是总面积
BODY_BOX = (300, 76, 1898, 1086)          # 内容区（跳过左侧导航栏、页眉与页脚）1280×800 ⇒ 1898×1144
BODY_MIN_COLOURS = 100                    # 空白页只有 24 色；真实的三个面是 500 上下


def _greyish(c):
    """近似灰：三通道互差 ≤3、亮度落在异常灰那一带。与 PART 5 逐字同一把尺子。"""
    r, g, b = c
    return abs(r - g) <= 3 and abs(g - b) <= 3 and GREY_LO <= r <= GREY_HI


def audit(png):
    """对着一张截图问两个问题：是不是 Flutter 的异常灰屏？内容区是不是空的？

    这两个都是**真的发生过**的坏证据形态 —— 灰块（Wrap 里塞 `Expanded` 那次）和空白页
    （截图拿到旧帧那次）。返回一句人话，没问题就返回 None。
    """
    from collections import Counter
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    # 用 tobytes 自己切三通道：`getdata()` 在 Pillow 12 上已经是弃用 API，而这两遍遍历
    # 本来也就是逐像素的，换成 bytes 切片反而更快。
    raw = im.tobytes()
    cnt = Counter(zip(raw[0::3], raw[1::3], raw[2::3]))
    grey = max((n for c, n in cnt.items() if _greyish(c)), default=0)
    if grey > ERROR_GREY_BUDGET:
        return (f"看到一片 {grey} px 的 Flutter 异常灰（单色上限 {ERROR_GREY_BUDGET}）"
                f" —— 整块界面被 ErrorWidget 顶掉了")
    box = im.crop(BODY_BOX).tobytes()
    n = len(set(zip(box[0::3], box[1::3], box[2::3])))
    if n < BODY_MIN_COLOURS:
        return f"内容区只有 {n} 种颜色（下限 {BODY_MIN_COLOURS}）—— 这一页是空的"
    return None


def prepare_state(appearance):
    """状态文件走临时副本 —— 绝不写用户的 `research/gui_state.json`。"""
    real = os.path.join(ROOT, "research", "gui_state.json")
    tmp = os.path.join(tempfile.gettempdir(), "bang_flet_smoke_state.json")
    st = {}
    try:
        with io.open(real, "r", encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        pass
    if appearance:
        st["appearance"] = appearance
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.environ["OURNOTES_STATE"] = tmp
    return tmp


def walk_controls(root):
    """把整棵控件树摊平（Flet 的控件都是 dataclass，容器字段就是 `content` / `controls` /
    `actions` 这些），不写死任何一种控件的形状。"""
    import dataclasses

    stack, seen = [root], set()
    while stack:
        c = stack.pop()
        if c is None or id(c) in seen or not isinstance(c, ft.Control):
            continue
        seen.add(id(c))
        yield c
        try:
            fs = dataclasses.fields(c)
        except TypeError:
            continue
        for f in fs:
            v = getattr(c, f.name, None)
            if isinstance(v, ft.Control):
                stack.append(v)
            elif isinstance(v, (list, tuple)):
                stack.extend(x for x in v if isinstance(x, ft.Control))


def tooltips(root):
    """树上还挂着 `tooltip` 的控件（拍照前必须是空的，见 `strip_tooltips`）。"""
    return [c for c in walk_controls(root) if getattr(c, "tooltip", None) is not None]


def strip_tooltips(root):
    """把整棵控件树上的 `tooltip` 摘干净 —— **截图必须与鼠标在哪儿无关**。

    2026-10-05 撞上的真事故：窗口正好开在鼠标底下，Flutter 就给光标下面那个控件弹了
    默认 tooltip（浅色 `#6f6f70`、暗色 `#e9e9e9`，一行反色文字），于是**同一份代码**拍出来
    的 `start` 那两张基线里各嵌了一个 **534×38** 的方块；鼠标一移开，控制组立刻报
    `start_dark 20014 px / 预算 38 px`、`start_light 18134 px` —— 两张**新图互相逐字节相同**，
    只有基线多那一块，说明脏的是基线而不是渲染。

    tooltip 只在悬停时才画，所以摘掉它**不改变静止帧**，却让截图不再取决于物理光标在哪。
    返回摘掉几个；拍照那边拿它当守卫（摘了 0 个、或摘完还剩，都当场硬退）。
    """
    n = 0
    for c in walk_controls(root):
        if getattr(c, "tooltip", None) is not None:
            n += 1
        try:
            c.tooltip = None
        except Exception:                            # 只读字段就跳过，不值得为此炸掉拍照
            pass
    return n


async def shoot_pass(page, appearance, prefix, prev):
    """一个外观一整遍：改临时状态 → **重建面板** → 逐页签拍图。

    `--appearance both` 靠这段在同一个进程里拍两套主题（省一次 Flet 客户端冷启动）。换外观
    必须重建面板：颜色是在**建控件的时候**就从 token 取走的，光改 `theme_mode` 只会让 Flutter
    自己那层主题变，已经建好的控件还挂着旧色。`page.clean()` 之后重建一份就干净了。

    `prev` 是**跨外观**传下去的上一张图 —— 这样第一张浅色图如果与最后一张暗色图逐字节相同，
    就说明外观根本没切过去（比只在同一外观内部比对更严）。
    """
    prepare_state(appearance)      # 重写同一个临时状态文件：Panel 建的时候会重新读它
    import flet_gui as G
    import m3_theme as T
    # 行悬停态（结算表行）会随鼠标位置变 —— 窗口开在光标底下，不动它的话上一张图拍到的是
    # 「光标恰好在某一行上」的色，下一张换个光标位置就报像素差。建面板前关掉（`_hist_row`
    # 建表时就读它）。见 `m3_theme.HOVER_STATE`。
    T.HOVER_STATE = False
    page.clean()
    panel = G.Panel(page)
    root = panel.build()
    n_tips = strip_tooltips(root)  # 见函数注释：窗口开在鼠标底下会多出一块默认 tooltip
    left = tooltips(root)
    if n_tips == 0 or left:
        sys.stderr.write(
            f"SHOOT-FAIL {prefix}: 摘 tooltip 这道闸没起作用"
            f"（摘了 {n_tips} 个，摘完还剩 {len(left)} 个："
            f"{[type(c).__name__ for c in left][:6]}）—— 截图会跟着鼠标位置变。\n")
        sys.stderr.flush()
        os._exit(1)
    page.add(root)
    page.update()
    await asyncio.sleep(SETTLE)                      # 等首帧落定
    os.makedirs(OUT_DIR, exist_ok=True)
    for i, name in enumerate(TABS):
        if name == "log":
            seed_log(panel)              # 日志面必须有行，见 `LOG_FIXTURE`
        panel.show_tab(i)
        await asyncio.sleep(SETTLE)
        png = await page.take_screenshot()
        # 三个面必须长得不一样：字节相同只可能是截图返回了同一张旧帧（这条真发生过 ——
        # 0.7 s 等待时 history 与 settings 是同一串字节，33920 B 的空白页）。静默写下一份
        # 假证据比报错糟得多，所以这里直接硬退。
        if prev is not None and png == prev:
            sys.stderr.write(
                f"SHOOT-FAIL {name}: 与上一张截图**逐字节相同**（{len(png)} B）"
                f" —— 截到的是旧帧（换了外观也一样，说明外观没切过去）。把 SETTLE 调大再试。\n")
            sys.stderr.flush()
            os._exit(1)
        prev = png
        bad = audit(png)
        if bad:
            sys.stderr.write(f"SHOOT-FAIL {name}: {bad}\n")
            sys.stderr.flush()
            os._exit(1)
        path = os.path.join(OUT_DIR, f"{prefix}_{name}.png")
        with io.open(path, "wb") as f:
            f.write(png)
        print(f"shot {path} {len(png)}")
    return prev


async def main(page: ft.Page, args):
    import flet_gui as G

    page.enable_screenshots = True

    page.window.width, page.window.height = G.T.WINDOW_DEFAULT
    page.window.min_width, page.window.min_height = G.T.WINDOW_MIN

    passes = ((("dark", "flet"), ("light", "flet_light")) if args.prefix == "flet"
              else (("dark", args.prefix), ("light", args.prefix + "_light"))) \
        if args.appearance == "both" else ((args.appearance, args.prefix),)
    prev = None
    for appearance, prefix in passes:
        prev = await shoot_pass(page, appearance, prefix, prev)
    await page.window.destroy()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--appearance", default="dark", choices=("auto", "light", "dark", "both"))
    ap.add_argument("--prefix", default="flet")
    a = ap.parse_args()
    tmp = prepare_state(None if a.appearance == "both" else a.appearance)
    print(f"state -> {tmp}")

    # 必须是一个真正的协程函数：`ft.run(lambda page: main(page, a))` 只会拿到一个没人 await 的
    # 协程对象 —— 窗口开着，主函数一行都没跑（第一次冒烟就是这么空转的）。
    async def entry(page: ft.Page):
        await main(page, a)

    ft.run(entry, view=ft.AppView.FLET_APP)
