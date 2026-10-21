# -*- coding: utf-8 -*-
"""探针：Flet 面板真的组起来、泵真的把事件搬到控件上、按键与路径都对、数字框夹得住。

这是原 `panelqt.py` 的 Flet 继任者。Qt 面板连文件一起删了，但它量过的**行为**一条没少，
逐条搬过来（同时把 `logclass.py` 第 5 关的日志窗口不变量也接了过来）：

PART 1 组窗与泵：真入口 `flet_gui.main(page)` 起面板，断言三页、谱面库首数、历史表行列数；
       往 `core.q` 灌 phase/progress/log_hdr/result 四种事件，验证泵把它们变成状态行、进度条
       与表格行；再灌一条坏事件（`("result", None)`）验证泵仍工作并记成「面板内部错误」。
       还钉**显示条数**（用户原话：「一下展示三百条太卡了」）：默认档取状态文件的 `hist_limit`、
       下拉档位就是 `core.HIST_LIMITS`、把上限压到 3 时表上只画 3 行而 `hist.tags` 仍是全部
       8 行（筛选与「导出 CSV」读的就是它 —— 顺手截了会静默丢行）、页脚把「表上画几局」说出来、
       手改状态文件写坏的字面量退回默认、改档位真的写回 `gui_state.json` 并重画。
       还钉**行底色**（用户原话：「把这些列表项背景色去了吧」）：未选中的行 `color is None`、
       任何一行都不许用八个难度容器色（从前 expert 两档占了整页 48.7%）、难度只由「难度」那一格
       的字色（`tk.diff_letter`）承担、「判定」那一格与行首竖条同色、选中/刚结算那一行**只抬容器**
       （官方 `row-item-selected-container-color = surface_container_highest`，格子语义色一个不改）。
PART 2 策略文案：开关关掉时那句话必须自己说出来（只看框里的数字会骗人）。
PART 3 「本轮」筛选按**行号**（`run_start`）判，不是按行上盖的 tag。
PART 4 演出间隔的收尾拍：间隔关着也等那一拍、锚点比间隔还旧只等一拍且**不许**报「演出间隔」、
       `stop_flag` 已置时立刻返回并说「未开始下一轮」。
PART 5 链路撞到边界要说一声：记一条 `log_err`、格子里写简写、**悬停给完整那份**、同一边界
       只报一次、回到「未撞」时悬停清空**且去重状态复位**、没有文件时不报也不炸。
PART 6 数字框夹取（M3 的表单数字是 TextField，没有 spinbox 那样的 `setRange`：区间不写在
       `NUM_RANGE` 上，手打一个 999 就真的等 999 分钟）、排序真的动了行序、连奏上限与
       `AGENTS.md` 同数、一局结算之后 AP 集合真的重算。
PART 7 快捷键（F5 / Ctrl+R / Ctrl+L）接在活上；外观路径只有一处（`m3_theme` 不再自己存状态）。
PART 8 日志窗口与存储上限：存储留 `LOG_KEEP`、视图只留 `LOG_WINDOW`、最新在底、最老那行被裁掉、
       `run_start` 跟着退、`log_info` 的计数对得上，且逐行 append 足够快。后半段是日志页改进的
       **行为**判据（真 `Panel` 实例）：关键词一搜就少画行、「没有日志」与「没有匹配」互斥、
       计数行自己推给客户端（不靠泵）、「自动滚动」开关跟着真实钉住状态走、清屏当场说话。
PART 9 隔离：真实的 `research/` 一个字节不动，而夹具里的状态文件确实被写过；`guard()` 证明
       写入跟随的是模块全局而不是常量快照。
PART 10 弹性布局：两页的分栏真的是 `ResponsiveRow` 12 栏栅格（没有写死栏宽的常量），并且
       连像素一起量 —— 窗口 1280 → 1560 时两块卡片之间那条留白必须跟着右移、**设置页与多人页
       都是左右两栏**（设置页两张卡各 6 栏铺满内容区、两栏等宽；2026-10-10 用户 m13525 定；
       从前设置页是各 7 栏居中、其实是上下堆着，更早是 470 + 300 写死的 770 px 靠左上角）；
       缩到 760 时必须自己叠成一栏（中间那条留白消失）；导航轨**任何宽度下都是收起轨**
       （用户 m18525 定的版式，官方 token 的 `container-width` 就是 80）。
PART 11 选曲列表：界面写的是**原文歌名**（不是排序字段那串罗马音）、副行给「罗马音 · 乐队」、
       AP 进度在行尾而不是塞进标题、筛选器跟着窗口走而不是写死 140、「显示 N / M 首」的
       数字与筛出来的实数对得上；按罗马音和拼音首字母都还搜得到（搜索口径与显示语言分开）。
       难度是**官方 M3 分段控件**（一行四段、等宽、两端胶囊、1 px outline 描边、选中铺
       `secondary_container` 并带对勾；形状与描边交给 Flutter 默认、颜色与字阶交给
       `T.segmented_button_theme`，控件自己 `style` 留空），段上写短式「名字 等级」、
       `Lv` 只留在悬停里，计数行与「难度」标签居中；这一关连像素一起量 —— 三条内部隔线
       等距（每段宽 = 组宽/4）、只有选中那一段是实心块、整组左右外沿与卡片内容边界
       （搜索框、列表容器那两条竖线）重合、两端圆角把角上的描边让开。
       运行卡同一套对半分行（四个按钮与四个勾选框各自两列），「连续 N 轮」那行留 wrap。

需要真实桌面会话（Flet 客户端是一个真的 Flutter 窗口，没有离屏模式），所以它和
`fletviewcheck` / `fletfly` 一样不在「零设备零联网」那批里。

跑（仓库根）：  python tools/probes/fletpanel.py
牙（手工）：    python tools/probes/fletpanel.py --teeth
                —— 把五十二颗牙逐个改回**修前的原文**（临时副本上），每个都必须只点亮自己那一关。
                   每颗牙 = 一次完整的十一关重放（实测约 31 s，其中 PART 10 11.4 s、PART 4
                   5.6 s、PART 11 5.5 s、PART 1 4.1 s，其余是窗口起势），所以串行全拆约 15 min。
                   `--jobs N`（默认 4）让 N 颗牙同时在跑：判据一条不少、重放规矩不变，只是把
                   等窗口的时间叠起来（`--jobs 1` 是严格串行的老行为）。默认值就是实测上限：
                   4 并发全拆 52 颗约 7 min 全绿（384 s 是 43 颗时的实测），6 并发会把 PART 10 那几条窗口尺寸判据挤成假红。
                python tools/probes/fletpanel.py --teeth rowbg
                —— 只拆一条（控制组 35 s + 这一颗 31 s）。分档验证的 B 档走这条：一轮只动
                   一两条守卫时没必要把另外二十几条也重放一遍。控制组仍然先跑一遍 —— 「拆了守卫
                   还全绿 = 判据是装饰」这句话只有在控制组是绿的前提下才有意义。
快（手工）：    python tools/probes/fletpanel.py --upto 6
                —— 只跑到第 6 关为止（**前缀语义**：前几关会给后面的关留现场，单跑一关会
                   UnboundLocalError）。实测 --upto 3 = 6.5 s、--upto 6 = 15.2 s、
                   --upto 10 = 30 s、全跑 36 s。`--teeth` 会自动把重放收窄到那颗牙自己那一关。
"""

import argparse
import asyncio
import inspect
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
PARTS = ("PART 1", "PART 2", "PART 3", "PART 4", "PART 5",
         "PART 6", "PART 7", "PART 8", "PART 9", "PART 10", "PART 11")

# `--only`：只跑指定的几关（2026-10-21 用户 m53748「很小的改动你都进行大范围的测试」之后
# 开的口子）。每一关的正文都被 `if _want(...)` 包住，没选中的关**一条判据都不写** ——
# 分档验证时只跑自己动到的那一关，不再为一句文案等整组。
UPTO = None


def _want(label):
    """这一关要不要跑：`UPTO is None` = 全跑（默认），否则跑到 `UPTO` 那一关为止。

    为什么是**前缀**而不是「只跑这一关」：各关的正文不只有判据，还给后面的关留下现场
    （`panel.policy_spins` 里的控件、窗口尺寸、选中行…）。实测 `--only 6` 会
    `UnboundLocalError: gap_spin` —— 那个控件是 PART 3 那一关取出来的。前缀永远是对的，
    而且早关的耗时本来就短。
    """
    return UPTO is None or PARTS.index(label) <= PARTS.index(UPTO)


def log_row_text(c):
    """把一条日志行控件里的**可见文字**拼回来（界面上的那串，不是存储里的那串）。

    日志行从 m11676 那一轮起不再是「一段 `ft.Text` 挂两段 span」：整行带得靠 `ft.Container` 包住
    整行（`ListView` 的孩子是松约束、`expand` 无效），行内是 `SelectionArea` 包 `Row`，时间戳与
    正文各是一条 `ft.Text`（时间戳是固定宽的独立一栏，折行的续行才有悬挂缩进）。所以取文本不能再
    只看 `.spans` —— 那是旧结构的手艺，现在会把每一行都读成空串，判据就变成永远为真的装饰。

    用鸭子类型走 `value` / `spans` / `content` / `controls`（不 import flet，也不认具体类）：
    控件树怎么套都读得出来，往后再加一层容器也不必回来改这里。
    """
    out = []
    seen = set()

    def walk(node):
        if node is None or id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, str):
            out.append(node)
            return
        if isinstance(node, (list, tuple)):
            for x in node:
                walk(x)
            return
        v = getattr(node, "value", None)
        if isinstance(v, str):
            out.append(v)
        for s in (getattr(node, "spans", None) or []):
            t = getattr(s, "text", None)
            if isinstance(t, str):
                out.append(t)
        walk(getattr(node, "content", None))
        walk(getattr(node, "controls", None))

    walk(c)
    return "".join(out)


def log_view_texts(view):
    """整个日志列表的可见文字，一行一条（`log_row_text` 的列表版）。"""
    return [log_row_text(c) for c in view.controls]

# 牙：每条改回修前的原文，只对**临时副本**用（提交的字节一个不碰）。
TEETH = {
    "runfilter": ("PART 3", [("            return i >= self.run_start",
                             "            return True")]),
    "clamp": ("PART 6", [("        v = max(lo, v)", "        v = v")]),
    # 2026-10-09 用户 m11451/m11595（数字列不留空、占位符与真数必须分明）：把压暗判据退回只认
    # 真 0（占位符走正常字色），以及把排序退回「哨兵元组 + reverse=」（降序时缺数行翻到最前）。
    "blankdim": ("PART 6", [(
        "        return core.hist_num(self.recs[tag], core.NUM_COL.get(name, name)) in (None, 0)",
        "        return core.hist_num(self.recs[tag], core.NUM_COL.get(name, name)) == 0")]),
    "orderflip": ("PART 6", [(
        "        kept = core.hist_order(kept, self.sort_col, self.sort_desc)",
        "        kept.sort(key=lambda r: (core.hist_value(r, self.sort_col) is None,\n"
        "                                 core.hist_value(r, self.sort_col)\n"
        "                                 if core.hist_value(r, self.sort_col) is not None else \"\"),\n"
        "                  reverse=bool(self.sort_desc))")]),
    # 这条从前指着已随「链路标定卡」删掉的 `pcell.tooltip`（`--teeth` 全套因此长期 FAIL）。
    # 卡删了之后「完整那份边界」只能进日志 ⇒ 改指 `refresh_cfg_info` 那一行：摘掉 `{pinned}`
    # 但保留「不再自适应」，于是只点亮「日志里给完整那份边界（含「板顶住 96 ms」）」。
    "pinnedtxt": ("PART 5", [(
        '            self._write_line(f"链路标定已达边界：{pinned} —— 偏移不再自适应", "log_err")',
        '            self._write_line("链路标定已达边界 —— 偏移不再自适应", "log_err")')]),
    "reset": ("PART 5", [("        elif not pinned:", "        elif False:")]),
    "trim": ("PART 8", [
        ("            del self.log_view.controls[:len(self.log_view.controls) - core.LOG_WINDOW]",
         "            pass")]),
    # 选曲列表两条：歌名给谁看、筛选器多宽。
    "romaname": ("PART 11", [(
        '            title=txt(core.song_label(s), self.tk, "n", color=ink),',
        '            title=txt(core.song_name(s), self.tk, "n", color=ink),')]),
    "pickshape": ("PART 11", [(
        '        self.cat_box = dropdown(self.tk, [("", "全部")], "", self._on_cat,\n'
        '                                expand=True, tooltip="按乐队筛选")\n'
        '        self.sort_box = dropdown(self.tk, [(m, m) for m in core.SORT_MODES],\n'
        '                                 self.state.get("sort_mode") or core.SORT_DEFAULT,\n'
        '                                 self._on_sort, expand=True, tooltip="排序方式")',
        '        self.cat_box = dropdown(self.tk, [("", "全部")], "", self._on_cat, width=140)\n'
        '        self.sort_box = dropdown(self.tk, [(m, m) for m in core.SORT_MODES],\n'
        '                                 self.state.get("sort_mode") or core.SORT_DEFAULT,\n'
        '                                 self._on_sort, width=140)')]),
    # 分段控件那条：把段上的**长式标签**改回短式（`EXPERT 26`）—— 用户 m20246 定的是长式
    # （选中段不再画 18 dp 对勾，段内可用宽 112.7 dp 装得下 ≈90 dp 的 `EXPERT Lv26`）
    # ⇒ 只点亮 PART 11 的「段上写长式」那条。
    "diffgrid": ("PART 11", [(
        '                label=ft.Text(f"{name or \'?\'} Lv{core.lv(d)}", style=T.type_style("labelLarge")),',
        '                label=ft.Text(f"{name or \'?\'} {core.lv(d)}", style=T.type_style("labelLarge")),')]),
    # 分段控件的形状那条：给控件自己塞一个 `style.shape` —— `SegmentedButton` 默认按
    # `itemShape(index, count)` 画首尾半圆、中间直角，一给 shape 就四段同形、两端胶囊没了
    # ⇒ 只点亮 PART 11 的「样式交给主题（`style is None`）」与像素层「两端圆角把角上的描边让开」。
    "segshape": ("PART 11", [(
        '        height=T.SEGMENT_H, on_change=on_change, tooltip=tooltip)',
        '        height=T.SEGMENT_H, on_change=on_change, tooltip=tooltip,\n'
        '        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=T.radius("small"))))')]),
    # 选中对勾那条：把 `show_selected_icon` 打开 —— 两家参考实现的默认就是画（选中段内容变成
    # 「18 的勾 + 8 的间距 + 文字」再居中），会把选中段的文字右推 11.1 dp、长式标签就成省略号
    # ⇒ 只点亮 PART 11 的「不画对勾」那条（像素那三条量的是隔线、选中块与外沿，勾不改它们）。
    "segcheck": ("PART 11", [(
        '        segments=segs, selected=selected, show_selected_icon=False,',
        '        segments=segs, selected=selected, show_selected_icon=True,')]),
    # 2026-10-10 用户 m13266（结算记录页加单人／多人筛选）：把来源那一段从 `rebuild` 的判据里
    # 摘掉 —— 只点亮 PART 11 的「熄掉「单人」之后一条单人局都不剩」那几条。
    "srcoff": ("PART 11", [(
        "                if core.hist_mode(r) in self.sources and core.hist_kept_for(r, self.filter)]",
        "                if core.hist_kept_for(r, self.filter)]")]),
    # 隐形命中带那条：把 `fill()` 那层 `hit48` 摘掉，回到修前「一个 40 高的 Container」
    # ⇒ 只点亮 PART 11 的动作区三条（可点高 48 / 带与按钮同动作 / 每格的可点高）。
    "hitband": ("PART 11", [(
        '    return hit48(ft.Container(content=ctl, height=BTN_H), on_click=band_cb, expand=True)',
        '    return ft.Container(content=ctl, expand=True, height=BTN_H)')]),
    # 禁用态那条：命中带不再问 `ctl.disabled` —— 禁用中的按钮还能从带里点着
    # ⇒ 只点亮 PART 11 的「带跟着按钮的禁用态走」。
    "hitdis": ("PART 11", [(
        '        if getattr(ctl, "disabled", False):\n            return\n',
        '        if False:\n            return\n')]),

    # 开关包壳那条（用户 m21537/m21635）：把「乐曲识别」那颗的 `hit_switch()` 摘掉（= 开关裸着，
    # 可点高只剩 40）⇒ 只点亮 PART 11 的「十一颗开关都补到可点 48」与「点包壳就是点开关」。
    "swwrap": ("PART 11", [(
        '            _line(_tile(ft.Icons.FOLLOW_THE_SIGNS, "乐曲识别", hit_switch(self.follow_chk)),',
        '            _line(_tile(ft.Icons.FOLLOW_THE_SIGNS, "乐曲识别", self.follow_chk),')]),
    # 包壳的转切那条：`on_click=_tap` 摘掉 —— 壳还在、内边距还是 4+4，可点区照旧 48，只是落在
    # 内边距上的那一按不再切换 ⇒ 只点亮「点包壳就是点开关」。
    "swtap": ("PART 11", [(
        "    return ft.Container(content=sw,\n"
        "                        padding=ft.Padding(T.SPACE[\"none\"], HIT_PAD,\n"
        "                                           T.SPACE[\"none\"], HIT_PAD),\n"
        "                        on_click=_tap)",
        "    return ft.Container(content=sw,\n"
        "                        padding=ft.Padding(T.SPACE[\"none\"], HIT_PAD,\n"
        "                                           T.SPACE[\"none\"], HIT_PAD))")]),
    # chip 只补上下那条：把日志页那一排 chip 的包壳摘掉（= chip 可点高只剩官方的 32）
    # ⇒ 只点亮「两排筛选 chip 只补上下」。锚点连上面两行注释一起写 —— 结算页那一排是同一句，
    # 单锚会命中两次。
    "chipband": ("PART 11", [(
        "            # chip 只补上下：它的宽本来就 ≥48（最短的标签两个字 ≈60），补横向会与 8 的官方\n"
        "            # chip-set 间距叠成负空隙（两条可点区互相压住，谁赢由命中顺序决定）。\n"
        "            btns.append(hit_pad(b, pad_x=0, pad_y=HIT_PAD_CHIP))",
        "            btns.append(b)")]),
    # 按钮补 48 那条：把「帮助」那颗图标按钮的包壳摘掉（= 40×40 的可点区）
    # ⇒ 只点亮「四颗图标按钮与九个页面按钮都补到可点 48」。
    "btnband": ("PART 11", [(
        "            actions=[self.tally, hit_pad(self.help_btn)],",
        "            actions=[self.tally, self.help_btn],")]),
    # 键盘那条：把 `Alt+↓` 那一支掏空（= 方向键挪不动选中行）⇒ 只点亮键盘那条。
    "keydown": ("PART 11", [(
        "        elif alt and key in KEY_DOWN:\n            self._step_focus(1)\n",
        "        elif alt and key in KEY_DOWN:\n            pass\n")]),
    # `expand` 那条：把 `hit48` 的缺省值改回**显式传**（= 修前那行）。**不能拿 `hit_pad` 做
    # 变异体** —— 它是设置页那排 wrap 按钮的包壳，一改整页 ErrorWidget，PART 10 的设置页像素
    # 判据会跟着红（一颗牙就不干净了）；`hit48` 只在动作区用、那里恒 `expand=True`，所以这条
    # 变异体只让「缺省值里不许有 expand」那一半变假 ⇒ 只点亮「包壳只在真要展开时才写 expand」。
    "wrapexpand": ("PART 11", [(
        "    return ft.Container(content=col, **_exp(expand))",
        "    return ft.Container(content=col, expand=expand)")]),
    # 显示条数那条：把「只画前 N 行」摘掉 ⇒ 表上又画全量（几百行就卡）⇒ 只点亮 PART 1。
    "histlimit": ("PART 1", [(
        "        rows = [self._hist_row(i, t) for i, t in enumerate(self.hist.shown())]",
        "        rows = [self._hist_row(i, t) for i, t in enumerate(self.hist.tags)]")]),
    # 行底色那条：把未选中行的底色又铺成难度容器色（= 修前的那片红）⇒ 只点亮 PART 1 的那几条。
    "rowbg": ("PART 1", [(
        "        bg = self.tk.surface_container_highest if hi else None",
        "        bg = self.tk.surface_container_highest if hi else self.tk.diff_container(3)")]),
    # 状态行那条（2026-10-07 用户 m20852「完善一下整个GUI的动画效果」）：把 `_fade_phase` 改回
    # 修前那版 —— **挂着** `MOTION["phase"]` 的动画把不透明度按到 0，于是「瞬时压下去」这半拍
    # 没了（`animate_opacity` 不是 None），补间只走四成又被反向 ⇒ 只点亮 PART 1 的状态行那条。
    "phasefade": ("PART 1", [(
        '        ph.animate_opacity = None\n        ph.opacity = 0.0\n',
        '        ph.opacity = 0.0\n')]),
    # 选曲列表那条：`reload_songs(fade=True)` 不再淡（回到修前「离散换内容、硬切」）
    # ⇒ 只点亮 PART 1 的选曲列表那条。
    "songfade": ("PART 1", [(
        '        if fade:\n            self._song_fade()\n',
        '        if False:\n            self._song_fade()\n')]),
    # 曲中提示行那条：从藏到显不再走 `_fade_in`（回到修前「一出现就是满不透明」）
    # ⇒ 只点亮 PART 1 的提示行那条。
    "hintfade": ("PART 1", [(
        '        if text and not was and self._motion():\n'
        '            self.page.run_task(self._fade_in, self.ingame_hint)\n'
        '            return\n',
        '        if False:\n'
        '            self.page.run_task(self._fade_in, self.ingame_hint)\n'
        '            return\n')]),
    # `_fade_in` 第一拍那条：不再摘掉 `animate_opacity`（回到修前「1.0 → 0 自己就是一段补间、
    # 等 60 ms 抬回 1.0 时它才走到两三成」的闪一下）⇒ 只点亮 PART 1 的提示行那条
    # （它的第一拍断言 `animate_opacity is None`）。
    "infade": ("PART 1", [(
        '        ctl.animate_opacity = None\n        ctl.opacity = 0.0\n',
        '        ctl.opacity = 0.0\n')]),
    # 弹性布局两条：各自改回**修前那种写死栏宽的原文**（不是手写的弱化版）。
    # 设置页从前是「运行策略 + 面板」并排 7/5，后来是「面板」与「资源」两张卡各占 7 栏且**居中**
    # （栅格换行 ⇒ 其实是上下堆着）；2026-10-10 用户 m13525 改成**左右布局**（各 6 栏、正好铺满
    # 整行）。牙把它换成写死 470 的 `Row` —— 卡既不跟着窗口变宽、两段卡也不再铺满整行，
    # 像素层那几条（两栏等宽 / 铺满内容区 / 留白跟着窗口长）当场变假。
    "grid": ("PART 10", [(
        '        self._settings_row = ft.ResponsiveRow([\n'
        '            ft.Container(content=panel_card, col={"xs": 12, "md": 6}),\n'
        '            ft.Container(content=res_card, col={"xs": 12, "md": 6}),\n'
        '        ], spacing=T.SPACE["sm"], run_spacing=T.SPACE["sm"],\n'
        '            vertical_alignment=ft.CrossAxisAlignment.START)',
        '        self._settings_row = ft.Row([\n'
        '            ft.Container(content=panel_card, width=470),\n'
        '            ft.Container(content=res_card, width=470),\n'
        '        ], spacing=T.SPACE["md"],\n'
        '            vertical_alignment=ft.CrossAxisAlignment.START)')]),
    # 「资源」那张卡被从栅格里摘掉：卡在场的判据与「两张各占 6 栏」一起变假（都在第 10 关）。
    # 资源卡两件新控件：把「逐张核对」的初值改成开着 ⇒ 「两件都在栅格里 + 初值都是关」变假。
    "verifystart": ("PART 10", [(
        "        self.verify_chk = toggle(\n            self.tk, 0, None,\n",
        "        self.verify_chk = toggle(\n            self.tk, 1, None,\n")]),
    "resgrid": ("PART 10", [(
        '            ft.Container(content=res_card, col={"xs": 12, "md": 6}),\n',
        '')]),
    # 开始页从前是「选曲 + 运行」对「日志」的 5/7，现在是两张各半栏的栏（`col={"xs":6}`）；
    # 牙把栅格换成写死 470 的 `Row`（修前设置页那种写法）—— 两栏之间的留白不再随窗口右移，
    # 窄窗口也不叠起来（换挡那一套挂在 `_apply_window_class` 上，改坏它由下面的 `stackoff` 牙盯）。
    "startfixed": ("PART 10", [(
        '        self._start_cols = ft.ResponsiveRow([\n'
        '            ft.Container(content=self._left_col, col={"xs": 6}),\n'
        '            ft.Container(content=self._right_col, col={"xs": 6}),\n'
        '        ], spacing=T.SPACE["sm"], run_spacing=T.SPACE["sm"],\n'
        '            vertical_alignment=ft.CrossAxisAlignment.STRETCH)',
        '        self._start_cols = ft.Row([\n'
        '            ft.Container(content=self._left_col, width=470),\n'
        '            ft.Container(content=self._right_col, width=470),\n'
        '        ], spacing=T.SPACE["md"],\n'
        '            vertical_alignment=ft.CrossAxisAlignment.START)')]),
    # 换挡那条：把「窄过 STACK_W 就叠成一栏」变成**永远不叠**。窄窗口下两栏并排 +
    # 一屏装不下 ⇒ 中间那条留白还在（像素层）、`col` 也没换成整行（控件层）。
    "stackoff": ("PART 10", [(
        '        stacked = int(width or 0) < STACK_W',
        '        stacked = False')]),
    # 导轨形态那条（用户 m18525 定「永远收起」）：把视图层改回「按窗口宽展开」—— 就是修前那个效果
    # （2026-10-10 之前这里抄的是修前原码 `T.window_class(...) in ("expanded", …)`；那个函数随清死
    # 代码删了，变异体改写成等价的效果）。1560 宽下 `extended` 变 True（标签也不压在图标下了），
    # 第 10 关那两条（宽窗 / 窄窗都得是收起轨）一起变假；两条都在 PART 10 ⇒ 只点亮这一关。
    "railexpand": ("PART 10", [(
        "        self._rail.extended = False\n"
        "        self._rail.label_type = ft.NavigationRailLabelType.ALL\n",
        "        self._rail.extended = True\n"
        "        self._rail.label_type = None\n")]),
    # 「最近」那条：把页框高度常数打到 0 ⇒ 默认窗也以为地方多得是 ⇒ 条数那两条当场变假。
    "lastneed": ("PART 10", [("CHROME_H = 128", "CHROME_H = 0")]),
    # 用户 m12311 第二问（左右宽度的依据）→ 用户 m13525（「多人模式面板改两栏等宽」）：多人页
    # 现在 6/12 + 6/12。5/7 的历史：992 那档一格 ≈151 正好压在「开关 52 + 空档 4 + 数框 96 =
    # 152」这条线上，6/6 只剩 ≈127 ⇒ 当时 5/7 是承重的；2026-10-10 用户 m12749 把那枚
    # 「断连重试」从多人页拆掉 ⇒ 算术不再逼着选 5/7，m13525 定成等宽。这条判据钉两半：
    # ① 最窄并排档放得下最宽的一枚控件（96）；② 两栏等宽。牙咬的是后一半，变异点必须是
    # `_apply_window_class` 里那份 `m_spans` —— 运行时会用它覆盖 `_multi_cols` 的 `col`，
    # 改 `_build_multi` 那份没用。
    "multi66": ("PART 10", [(
        '({"xs": 12, "md": 6}, {"xs": 12, "md": 6}))',
        '({"xs": 12, "md": 5}, {"xs": 12, "md": 7}))')]),
    # 去嵌套底色那条（m06279 用户点名）：把 `field` 淡底又铺回瓦片格上 ⇒「没有二次嵌套底色」变假。
    "nestedbg": ("PART 11", [(
        "            return ft.Row([ft.Container(content=c, expand=True) for c in tiles],",
        "            return ft.Row([ft.Container(content=c, expand=True,\n"
        "                                        bgcolor=self.tk.field) for c in tiles],")]),
    # 2-4-2 那条：第二行少一枚瓦片（变成 2/3/2）⇒ 排布那条变假。
    "tile3": ("PART 11", [(
        '                  _tile(ft.Icons.SHUFFLE, "随机乐曲", hit_switch(self.random_chk)),\n',
        "")]),
    # 火力门瓦片那条：把「LB监测」那枚摘掉（第二行回到 2/3/2）⇒ 排布与标签两条一起变假。
    "firetile": ("PART 11", [(
        '                  _tile(ft.Icons.LOCAL_FIRE_DEPARTMENT, "LB监测", hit_switch(self.fire_chk)),\n',
        "")]),
    # 四字全名那条：把「正推限制」压回 m06279 之前那个 2 字缩写 ⇒ 标签那条变假。
    # （锚点是 `_line(_tile(...` 同一行开头那截 —— 第三行两枚瓦片就是这么写的。）
    "label4": ("PART 11", [(
        '            _line(_tile(ft.Icons.SPEED, "正推限制", hit_switch(self.push_chk),',
        '            _line(_tile(ft.Icons.SPEED, "正推", self.push_chk,')]),
    # 数框同宽那条：`num_field` 的默认宽度退回 104（m06279 之前的默认）⇒ 同宽那条变假。
    "fieldw": ("PART 11", [(
        'width=96, decimals=2',
        'width=104, decimals=2')]),
    # 「最近」那行的几何那条（m09165）：把行高退回「72 减一个行距」= 64（用户看到长方形的
    # 那一版）⇒ 56 的封面装不下，「封面 56 + 上下 8 = 容器 72」那条变假。
    "artbox": ("PART 11", [(
        'height=RECENT_ROW_H,',
        'height=RECENT_ROW_H - T.SPACE["sm"],')]),
    # 开关那条：`toggle()` 退回勾选框（m06250 换掉的那颗）⇒「六颗都是 M3 开关」那条变假。
    "swtch": ("PART 11", [(
        "    return ft.Switch(value=bool(value), on_change=on_change,\n"
        "                     tooltip=tooltip, **switch_colors(tk))",
        "    return ft.Checkbox(value=bool(value), on_change=on_change, tooltip=tooltip)")]),
    # 「最近」封面那条：把封面缩回 40（= 从前那个尺寸）⇒「元素放宽」那条变假。
    "recart": ("PART 11", [("RECENT_ART = 56", "RECENT_ART = 40")]),
    # 用户 m12311 第一问：多人页那张卡的上限退回 6 ⇒ 「上限分档」那条当场变假。
    # （第一跑是「一条都没亮」：判据当时只拿模块常量比视图，两边一起动 ⇒ 现在那条里写死了
    # 6/15 两个字面量 + 一条 `MULTI > POOL` 的跨常数关系。m14172 一度改成 10、m14308 又改回 15。）
    "pool15": ("PART 11", [("RECENT_POOL_MULTI = 15", "RECENT_POOL_MULTI = 6")]),
    # 种类偏移那四枚框（用户 m15057，m15291 改名）：把框的 on_change 接回 `_save_defaults`
    # （= 谁哪天顺手接错，框里改的数不进状态）⇒「白键晚 30 ms 写进 defaults['kind_lead']」
    # 那条当场变假。
    # 判据走的是 `tap_spin.on_change(None)`（控件自己的回调），不是直接调方法 —— 直接调方法
    # 这颗牙咬不动。
    "kindwire": ("PART 6", [(
        'num_field(self.tk, int(kd.get(k, 0.0) or 0.0), self._save_kind_lead,',
        'num_field(self.tk, int(kd.get(k, 0.0) or 0.0), self._save_defaults,')]),
    # 尾判滑键那格（用户 m52916）：同一个坑，接错一个回调那格就是摆设 ——
    # 「尾滑 0 写进 defaults['tail_flick_lead']」当场变假。
    "tailwire": ("PART 6", [(
        'self._save_tail_lead, suffix=" ms", decimals=0, width=None)',
        'self._save_defaults, suffix=" ms", decimals=0, width=None)')]),
    # 尾滑那格**排进卡里**这一半：写了控件却不往卡里放，界面上根本没有它。
    "tailplace": ("PART 6", [("], tail_tile),", "]),")]),
    # 贴底那条：`SPACE_BETWEEN` 退回 `START`（= 按钮跟着设置区往上跑，卡底又空一块）⇒ 变假。
    "sbact": ("PART 11", [(
        '        body = ft.Column([_top, _acts], spacing=T.SPACE["sm"], expand=True,\n'
        '                         alignment=ft.MainAxisAlignment.SPACE_BETWEEN,',
        '        body = ft.Column([_top, _acts], spacing=T.SPACE["sm"], expand=True,\n'
        '                         alignment=ft.MainAxisAlignment.START,')]),
    # 四个动作按钮那条：把 `fill()` 的 `expand` 摘掉（= 修前四个按钮 226/157/98/82 px 参差的样子）
    # ⇒「同一行两个半格」与「等宽等高撑满」两条当场变假。
    "btnfill": ("PART 11", [(
        "    return hit48(ft.Container(content=ctl, height=BTN_H), on_click=band_cb, expand=True)",
        "    return hit48(ft.Container(content=ctl, height=BTN_H), on_click=band_cb, expand=False)")]),
    # 图标那条：把「强制开始」的图标拿掉（= 修前只有 filled 主按钮带 ▶ 的样子）⇒ 变假。
    "btnicon": ("PART 11", [(
        '                                kind="tonal", icon=ft.Icons.FAST_FORWARD,',
        '                                kind="tonal",')]),
    # danger 那条（审查报告第 6 节）：把「强制终止」的 error 角色摘掉（= 与「本轮停止」长得
    # 一模一样的样子）⇒ 新加的那条判据当场变假。
    "killdanger": ("PART 11", [(
        'kind="outlined", icon=ft.Icons.CANCEL, danger=True,',
        'kind="outlined", icon=ft.Icons.CANCEL,')]),
    # 用户 m07990「强制停止为什么常亮」：把 danger 的**逐档**写法收回平铺写法（= 修前那种
    # 「禁用也照样发红」的样子）⇒ 新加的「禁用态压到 38% / 12%」那条当场变假。
    "killdim": ("PART 11", [(
        "                   ft.ControlState.DISABLED: tk.disabled(tk.text)},",
        "                   ft.ControlState.DEFAULT: tk.danger},")]),
}

REC = {"ts": "01-01 11:00", "tag": "probe_flet", "song": "迷星叫", "diff": "expert", "rc": 0,
       "all_perfect": True, "full_combo": True, "non_perfect": 0, "score": 1234567,
       "aborts": 0, "perfect": 787, "great": 0, "good": 0, "bad": 0, "miss": 0, "combo": 787}


def set_upto(labels):
    """把 `--upto` 的写法归一成 `PART n`（`"6"` 与 `"PART 6"` 都认）；多个取最大的那个。"""
    global UPTO
    if not labels:
        UPTO = None
        return []
    got, bad = [], []
    for raw in labels:
        raw_s = str(raw).strip().upper().replace("PART", "").strip()
        lab = ("PART " + raw_s) if raw_s.isdigit() else ""
        (got if lab in PARTS else bad).append(lab or raw)
    UPTO = max(got, key=PARTS.index) if got else None
    return bad


def _run_child(fixture, out, mutant=None):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if mutant:
        env["FLETPANEL_MUTANT"] = mutant
    limit = float(os.environ.get("FLETPANEL_TIMEOUT", "240"))
    try:
        p = subprocess.run([sys.executable, SELF, "--child", fixture, out]
                           + (["--upto", UPTO] if UPTO else []),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=ROOT, env=env, timeout=limit)
    except subprocess.TimeoutExpired:
        return 124, f"子进程 {limit:g} s 没退（窗口没起来？还是一关卡住了？）"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# ---------------------------------------------------------------- 子进程

class _K:
    """键盘事件的替身。只带 `_on_key` 真读过的那两个字段。"""

    def __init__(self, key, ctrl=False):
        self.key = key
        self.ctrl = ctrl


class _C:
    """控件替身：只带 `.value`（回调里只读这一项）。"""

    def __init__(self, value):
        self.value = value


class _E:
    """通用事件替身：只带 `.control`。下拉这类回调签名是 `(e)`。"""

    def __init__(self, control):
        self.control = control


def _child(fixture, out):
    sys.path.insert(0, TOOLS)
    mutant = os.environ.get("FLETPANEL_MUTANT")
    if mutant:
        sys.path.insert(0, mutant)              # 变异体优先，提交的字节没动

    import flet as ft
    import fletviewcheck as FV

    before = FV._corpus()                       # 真实 research/ 的快照（本进程是唯一的写者）
    FV._point(fixture)
    ok_guard = FV.guard()

    import m3_theme as T
    import panel_core as core
    import rlog

    # `tools/panel_core.py:35`（`m3_theme` 也一样）在 import 时会把 `tools/` 又插到 `sys.path`
    # 最前，把上面那次插入顶掉 —— 于是变异体被真面板遮住，「牙」静默失效：拆了守卫还全绿，
    # 看起来像判据没事。所以这里**再压一次**，并且核对真的加载到了变异体。
    if mutant:
        sys.path.insert(0, mutant)
    import flet_gui as G

    # 这一行是给「牙」用的：拆守卫时能一眼看出子进程到底加载的是哪一份面板。
    print(f"[fletpanel] flet_gui = {G.__file__}  mutant = {mutant}", flush=True)
    if mutant and not os.path.abspath(G.__file__).startswith(os.path.abspath(mutant)):
        raise RuntimeError(f"变异体没生效：加载的是 {G.__file__}（想要 {mutant}）")

    inst = {}

    class ProbePanel(G.Panel):
        """只是把实例捞出来 —— 面板自己的源码一个字节不改。"""

        def __init__(self, page):
            super().__init__(page)
            inst["p"] = self

    vpath = os.path.join(fixture, "verdicts.jsonl")

    async def app(page):
        page.enable_screenshots = False
        # 行悬停态层（J）在真面板里是开着的，但探针跑在**关掉**的那一档：与基线同一个口径
        # （窗口开在光标底下，开着的话同一份断言会随鼠标位置变），而且第 1 关「未选中行
        # `color is None`」这条只有在关掉时才严格成立。悬停那一档另有三条判据临时开回来量。
        T.HOVER_STATE = False
        G.Panel = ProbePanel
        G.main(page)
        panel = inst["p"]
        state0 = (os.path.getmtime(core.STATE), os.path.getsize(core.STATE))
        try:
            await _parts(panel, vpath, G, core, T, rlog, fixture)
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
            # 先落盘再关窗：一关掉最后一个窗口，Flet 会话就结束了，这行之后的代码不再执行。
            try:
                await page.window.destroy()
                await asyncio.sleep(0.5)
            finally:
                os._exit(0)

    ft.run(app, view=ft.AppView.FLET_APP)


def _v(vpath, row):
    """判据**一边跑一边落盘**（每条 flush）：哪一关把子进程卡死了，父进程也看得见。"""
    with io.open(vpath, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()


async def _parts(panel, vpath, G, core, T, rlog, fixture):
    # `flet` 在这一关是**真控件**的判据（`isinstance(err_row, ft.Container)`、`ft.ResponsiveRow`…），
    # 所以要在函数**开头** import：这个函数后面还有一处 `import flet as ft`（PART 10 那截），
    # 只要函数体里有一处 import，`ft` 就是整个函数的局部名 —— 放在后面会让前面这些判据
    # `UnboundLocalError`（踩过：日志行那三条判据整关炸掉）。
    import flet as ft

    def check(part, label, ok, extra=""):
        _v(vpath, {"part": part, "label": label, "ok": bool(ok), "extra": str(extra)})

    def texts():
        return [t for _k, t in panel.log_store]

    def why():
        return f"log({len(panel.log_store)} 行) 尾部 {texts()[-3:]!r}"

    # ---- PART 1 组窗与泵
    if _want("PART 1"):
        check("PART 1", "五页都在（单人演出 / 多人演出 / 运行日志 / 结算记录 / 设置）",
              len(panel.pages) == 5, len(panel.pages))
        check("PART 1", "谱面库有歌", len(panel.songs) == 3, len(panel.songs))
        # 结算表的列集与列宽按窗口宽现算（用户 m12075：「表单宽度应与窗口宽度保持同步，目前在小窗口
        # 下表单超出宽度显示」）。从前是 13 个定宽列（自然宽 1155）铺进 1032 的内容区 —— 右边「分数」
        # 整列被裁在视口外。这里钉四件：① 表上真有的列就是预算法算出来的那一份（指纹自洽）；
        # ② 整表自然宽不超内容区；③ 每个表头的宽度就是预算里那一份（列宽变了不重建 `columns`，
        # 表头会与行对不上）；④ 排序箭头真指到排序列（`sort_column_index` 从前一律不设 ⇒ Flutter
        # 那 18 px 的箭头格一直白占着，一个箭头都不画）。
        hist_sig = panel._hist_sig_of(panel._hist_cols, panel._hist_w)
        check("PART 1", "历史表的列集/列宽 = 预算法算出来的那一份（指纹自洽）",
              hist_sig == panel._hist_sig
              and len(panel.hist_table.columns) == len(panel._hist_cols) + 1
              and panel._hist_cols == [c for c in core.HIST_COLS if c in panel._hist_cols],
              f"表 {len(panel.hist_table.columns)} 列 / 预算 {len(panel._hist_cols)} 列")
        check("PART 1", "结算表不溢出内容区（demand <= avail）",
              panel._hist_demand(panel._hist_cols, panel._hist_w)
              <= panel._hist_avail(panel.page.width or T.WINDOW_DEFAULT[0]),
              f"占宽 {panel._hist_demand(panel._hist_cols, panel._hist_w):.0f}"
              f" / 可用 {panel._hist_avail(panel.page.width or T.WINDOW_DEFAULT[0]):.1f}")
        check("PART 1", "必留的五列都在表上",
              all(c in panel._hist_cols for c in T.HIST_FIT_ALWAYS), f"{panel._hist_cols}")
        check("PART 1", "每个表头的宽度就是预算里那一份",
              [c.label.width for c in panel.hist_table.columns]
              == [core.CHIP_W] + [panel._hist_w[c] for c in panel._hist_cols])
        check("PART 1", "历史表有行", len(panel.hist.recs) == 8, len(panel.hist.recs))
        check("PART 1", "chip 列不排序",
              panel.hist_table.columns[0].on_sort is None
              and panel.hist_table.columns[0].tooltip is None)
        check("PART 1", "别的列都能排序",
              all(c.on_sort is not None for c in panel.hist_table.columns[1:]))
        check("PART 1", "排序箭头指向排序列（从前一律不画）",
              panel.hist_table.sort_column_index == panel._hist_cols.index(panel.hist.sort_col) + 1
              and panel.hist_table.sort_ascending == (not panel.hist.sort_desc),
              f"箭头列 {panel.hist_table.sort_column_index} / 排序列 {panel.hist.sort_col!r}")
        # ⑤ 表头高 / 行高 / 字号 / 行间线照官方数据表（`_MDCompDataTable` 的 `header-container-height`
        # 56、`row-item-container-height` 52、`header-headline` titleSmall、`row-item-label-text`
        # bodyMedium、`row-item-outline-width` 1）。这三个数在真 `DataTable` 上各是一个字段，写错哪个
        # 都只是「看起来小一号」，所以按控件属性认，不按源码文本认。
        check("PART 1", "结算表照官方：表头 56 / 行 52 / 字号 14 / 行间线 1",
              panel.hist_table.heading_row_height == T.HIST_HEAD_H == 56
              and panel.hist_table.data_row_min_height == T.HIST_ROW_H == 52
              and panel.hist_table.data_row_max_height == T.HIST_ROW_H
              and panel.hist_table.heading_text_style.size
              == T.type_style(T.HIST_HEAD_FONT).size == 14
              and panel.hist_table.data_text_style.size
              == T.type_style(T.HIST_CELL_FONT).size == 14
              and panel.hist_table.divider_thickness == T.HIST_OUTLINE_W == 1,
              f"表头 {panel.hist_table.heading_row_height} / 行 {panel.hist_table.data_row_min_height}"
              f" / 字 {panel.hist_table.heading_text_style.size}"
              f"+{panel.hist_table.data_text_style.size}")
        # ⑥ 双击一行 = 「选中 + 开截图」（用户 m12075 的 L 项）。`ft.DataRow` 只有 `on_select_change`、
        # 没有 `on_double_tap`，所以面板自己按 `T.DBLCLICK_S` 记住上一击的时刻：第一击只选中，同一行
        # 0.5 s 内再来一击才调 `open_shot()`，超出窗口的第三击回到普通的「取消选中」。这里在真控件上
        # 走一遍三击，并把选中状态与计时器复原 —— PART 5 的行底色判据要求第一行未被选中。
        shots = []
        orig_shot = panel.open_shot
        panel.open_shot = lambda: shots.append(1)
        try:
            tag0 = panel.hist.shown()[0]
            panel.hist_row_tag = None
            panel._hist_click_tag, panel._hist_click_at = None, 0.0
            panel._on_hist_select(tag0)
            once = panel.hist_row_tag == tag0 and not shots
            panel._on_hist_select(tag0)
            twice = panel.hist_row_tag == tag0 and len(shots) == 1
            panel._hist_click_at -= T.DBLCLICK_S + 1.0
            panel._on_hist_select(tag0)
            third = panel.hist_row_tag is None and len(shots) == 1
        finally:
            panel.open_shot = orig_shot
            panel.hist_row_tag = None
            panel._hist_click_tag, panel._hist_click_at = None, 0.0
            panel._render_history()
        check("PART 1", "双击一行 = 选中 + 开截图（一击只选中、0.5 s 内二击才开图、超时回到取消）",
              once and twice and third,
              f"一击 {once} / 双击 {twice} / 超时 {third} / 开图 {len(shots)} 次")
        # 换窄一档再换回来：列变少、表跟着窄（仍不溢出），箭头跟着新的列位挪；换回来列集复原。
        # 「换回来」要用**建表时那个宽度**（`page.width`，客户端实测 1265.33 这种），不能用
        # `T.WINDOW_DEFAULT[0]`（1280）—— 两个数落同一尺寸档、可用宽却差 15，歌曲那列的余量取整会
        # 差一格（踩过：这条判据因此红）。
        w0 = panel.page.width or T.WINDOW_DEFAULT[0]
        wide_cols = list(panel._hist_cols)
        wide_sig = panel._hist_sig
        panel._sync_hist_cols(T.WINDOW_MIN[0])
        check("PART 1", f"窗口缩到 {T.WINDOW_MIN[0]}：列变少、占宽跟着窄且仍不溢出",
              len(panel._hist_cols) < len(wide_cols)
              and panel._hist_cols == [c for c in core.HIST_COLS if c in panel._hist_cols]
              and panel._hist_demand(panel._hist_cols, panel._hist_w)
              <= panel._hist_avail(T.WINDOW_MIN[0]),
              f"{len(wide_cols)} 列 -> {len(panel._hist_cols)} 列（{' '.join(panel._hist_cols)}）")
        check("PART 1", "换档后箭头指向新的列位（列序变了就得跟着挪）",
              panel.hist_table.sort_column_index == panel._hist_cols.index(panel.hist.sort_col) + 1)
        panel._sync_hist_cols(w0)
        check("PART 1", "窗口换回来：列集与指纹复原（`_hist_sig` 去抖的基准）",
              list(panel._hist_cols) == wide_cols
              and panel._hist_sig == wide_sig
              and panel._hist_sig == panel._hist_sig_of(panel._hist_cols, panel._hist_w))

        # 显示条数：几百行时 `DataTable` 每个格子都是一个控件、客户端会卡，所以表上只画前 N 行。
        # **但上限只管「画多少」**：筛选计数、「导出 CSV」（读的就是 `hist.tags`）与页脚统计
        # 仍按全部记录算 —— 顺手把 `hist.tags` 也截了就会静默丢行，所以这里连这一点一起钉。
        lim_box = panel.hist_limit_box
        check("PART 1", "显示条数默认取状态文件（夹具里没这个键 -> HIST_LIMIT_DEFAULT）",
              panel.hist.limit == core.HIST_LIMIT_DEFAULT
              and str(lim_box.value) == str(core.HIST_LIMIT_DEFAULT),
              f"limit={panel.hist.limit} 下拉={lim_box.value!r} "
              f"（默认 {core.HIST_LIMIT_DEFAULT}）")
        check("PART 1", "档位就是 core.HIST_LIMITS，最后一档是「全部」",
              [str(o.key) for o in lim_box.options] == [str(n) for n in core.HIST_LIMITS]
              and lim_box.options[-1].text == "全部",
              f"{[(o.key, o.text) for o in lim_box.options]}")
        panel.hist.set_limit(3)
        panel._render_history()
        check("PART 1", "上限压到 3：表上画 3 行，hist.tags 仍是全部 8 行",
              len(panel.hist_table.rows) == 3 and len(panel.hist.tags) == 8,
              f"表 {len(panel.hist_table.rows)} 行 / tags {len(panel.hist.tags)} 行")
        check("PART 1", "页脚说清表上画了几局",
              "表上画 3 局" in str(panel.hist_info.value), repr(panel.hist_info.value))
        check("PART 1", "hist_limit 的容错：手改的字面量不炸、负数与超限各回各家",
              [core.clamp_hist_limit(x) for x in ("300", 300, "abc", None, "", -1, 99999)]
              == [300, 300, core.HIST_LIMIT_DEFAULT, core.HIST_LIMIT_DEFAULT,
                  core.HIST_LIMIT_DEFAULT, core.HIST_LIMIT_DEFAULT, core.HIST_LIMIT_MAX],
              f"{[core.clamp_hist_limit(x) for x in ('300', 300, 'abc', None, '', -1, 99999)]}")
        panel._on_hist_limit(_E(_C("200")))
        saved_state = json.load(io.open(core.STATE, encoding="utf-8"))
        check("PART 1", "改档位写回状态文件，表跟着重画",
              saved_state.get(core.HIST_LIMIT_KEY) == 200 and panel.hist.limit == 200
              and len(panel.hist_table.rows) == 8,
              f"状态 {saved_state.get(core.HIST_LIMIT_KEY)!r} / limit={panel.hist.limit}"
              f" / 表 {len(panel.hist_table.rows)} 行")
        panel.hist.set_limit(core.HIST_LIMIT_DEFAULT)          # 后面几关还要用这张表
        panel._render_history()

        # 行底色：从前每一行都铺该难度的容器色（expert 那一整片红就是这么来的）。现在**未选中的行没有
        # 底色**，难度只由「难度」那一格的字色承担、结果由行首竖条与「判定」那一格承担；选中/刚结算
        # 那一行**只抬容器** —— 官方 `row-item-selected-container-color = surface_container_highest`
        # （2026-10-06 从本项目的 `secondary_container` 改回官方，`DEVIATIONS` 那条随之撤掉）。两态一起
        # 钉：否则「去掉底色」很容易顺手把高亮也弄丢，而改回官方时又容易把格子语义色跟着重染一遍。
        def cell_ink(row, idx):
            """`ft.DataCell(Container(content=txt(...)))` 的字色。

            `txt()` 把颜色写在 `TextStyle.color` 上（`ft.Text.color` 留空是故意的 —— 留空才会跟着
            `ft.Theme` 走），所以两处都得看。
            """
            t = getattr(row.cells[idx].content, "content", None)
            return (getattr(t, "color", None)
                    or getattr(getattr(t, "style", None), "color", None))

        def strip_bg(row):
            """行首那根竖条的底色（`DataCell → 外层 Container → 内层 Container.bgcolor`）。"""
            inner = getattr(row.cells[0].content, "content", None)
            return None if inner is None else inner.bgcolor

        rows = list(panel.hist_table.rows)
        tags = list(panel.hist.shown())
        plain = [r for r in rows if r.color is None]
        check("PART 1", f"未选中的行一律没有底色（{len(plain)}/{len(rows)} 行）",
              len(rows) > 0 and len(plain) == len(rows),
              "；".join(f"{t}:{r.color}" for t, r in zip(tags, rows) if r.color is not None))
        conts = {getattr(panel.tk, k + s)
                 for k in T.DIFF_KEYS for s in ("_container", "_container_dim")}
        check("PART 1", f"任何一行都不许用难度的容器色（{len(conts)} 个 token）",
              all(r.color not in conts for r in rows),
              f"{sorted(str(r.color) for r in rows if r.color in conts)}")
        dcol = core.HIST_COLS.index("diff") + 1
        bcol = core.HIST_COLS.index("badge") + 1
        bad_diff = [(t, panel.hist.letters[t], cell_ink(r, dcol),
                     panel.tk.diff_letter(panel.hist.letters[t]))
                    for t, r in zip(tags, rows)
                    if cell_ink(r, dcol) != panel.tk.diff_letter(panel.hist.letters[t])]
        check("PART 1", "「难度」那一格的字色 = tk.diff_letter(该行难度)",
              not bad_diff, bad_diff[:3])
        chip_of = {"ap": panel.tk.chip_ap, "fc": panel.tk.chip_fc,
                   "np": panel.tk.chip_np, "err": panel.tk.chip_err}
        bad_badge = [(t, panel.hist.kinds[t], cell_ink(r, bcol), strip_bg(r))
                     for t, r in zip(tags, rows)
                     if cell_ink(r, bcol) != (chip_of.get(panel.hist.kinds[t]) or panel.tk.text)
                     or strip_bg(r) != chip_of.get(panel.hist.kinds[t])]
        check("PART 1", "「判定」那一格与行首竖条同色（几种结果都在夹具里）",
              not bad_badge and len({panel.hist.kinds[t] for t in tags}) >= 2, bad_badge[:3])
        inks_plain = {str(cell_ink(rows[0], c)) for c in range(1, len(rows[0].cells))}
        panel.hist_row_tag = tags[0]
        panel._render_history()
        hi_row = panel.hist_table.rows[0]
        hi_inks = {str(cell_ink(hi_row, c)) for c in range(1, len(hi_row.cells))}
        check("PART 1", "选中那一行只抬容器（官方 surface_container_highest），格子语义色一个不改",
              hi_row.color == panel.tk.surface_container_highest
              and hi_inks == inks_plain
              and panel.tk.surface_container_highest != panel.tk.secondary_container,
              f"底色 {hi_row.color} 字色 {sorted(hi_inks)}（未选中 {sorted(inks_plain)}）")
        panel.hist_row_tag = None
        panel._render_history()

        # 表头底色（K）：官方 `header-container-color` 就是 `surface`（与页面同色），从前取
        # `surface_container_high` 是本项目自己抬的那一档 —— 那条已经从 `DEVIATIONS` 撤掉了。
        check("PART 1", "表头底色 = 官方 header-container-color（surface，不再抬一档）",
              panel.hist_table.heading_row_color == panel.tk.surface
              and panel.hist_table.heading_row_color != panel.tk.surface_container_high,
              f"实测 {panel.hist_table.heading_row_color}")

        # 行悬停态层（J）：真面板里 `T.HOVER_STATE` 是开的（探针这一档关着，见 `app()`），所以这里
        # 临时开回来，直接找 `_hist_row` 要两种行：未选中那一行悬停后是「surface + `on_surface` @ 8%」，
        # 选中那一行是「surface_container_highest + 同一层」，而不是各自把底色换掉。官方数据表**只有 hover
        # 这一档**行状态层（`row-item-unselected-*` 与 `row-item-selected-hover-*` 都是 `on-surface`、
        # opacity 都是 8%），`HOVERED` 与 `DEFAULT` 两格都要在（缺 DEFAULT 就没接住未声明的状态）。
        T.HOVER_STATE = True
        try:
            plain_row = panel._hist_row(0, tags[0])
            panel.hist_row_tag = tags[0]
            sel_row = panel._hist_row(0, tags[0])
            want_plain = panel.tk.hover_fill(panel.tk.surface)
            want_sel = panel.tk.hover_fill(panel.tk.surface_container_highest)
            ok_hover = (isinstance(plain_row.color, dict) and isinstance(sel_row.color, dict)
                        and plain_row.color.get(ft.ControlState.HOVERED) == want_plain
                        and plain_row.color.get(ft.ControlState.DEFAULT) == panel.tk.surface
                        and sel_row.color.get(ft.ControlState.HOVERED) == want_sel
                        and sel_row.color.get(ft.ControlState.DEFAULT) == panel.tk.surface_container_highest
                        and want_plain != panel.tk.surface
                        and want_sel != panel.tk.surface_container_highest)
            check("PART 1", "行悬停态层 = 行底色 + on_surface @ 8%（选中行也只压状态层）",
                  ok_hover, f"未选中 {plain_row.color}；选中 {sel_row.color}")
        finally:
            T.HOVER_STATE = False
            panel.hist_row_tag = None
            panel._render_history()

        # 换页 **fade-through**（官方 30/70 分界）：旧页先淡到 0（`page_out` = short2 = 100 ms）→
        # 换内容并把缩放**不带动画**地落到 `PAGE_SCALE_IN` → 新页淡入（`page` = short4 = 200 ms）
        # 同时把缩放抬回 1。这里按 20 ms 采样把三拍各自的状态都收下来 —— 只看终态的话，
        # 「三拍」与「硬切」在断言上是同一件事（`opacity` 终态都是 1、`scale` 终态都是 1）。
        # 下面这几拍都要求「过渡动画」开着（关掉时 `show_tab` 直接落终态、`_hist_fade` 直接返回），
        # 所以先把开关在内存里按开、量完再放回去 —— 探针不改状态文件。
        saved_motion = panel.state.get("motion", 1)
        panel.state["motion"] = 1
        panel.show_tab(0)
        await asyncio.sleep(T.motion_ms("page") / 1000.0 + 0.3)
        seq0 = panel._page_seq
        tab0 = panel.tab
        panel.show_tab(2)
        seen = []
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            seen.append((round(float(panel._body.opacity), 3), round(float(panel._body.scale), 3),
                         panel._body.content is panel.pages[2]))
            if seen[-1][2] and seen[-1][1] == 1.0 and seen[-1][0] == 1.0:
                break
            await asyncio.sleep(0.02)
        check("PART 1", "换页第一拍：旧页先淡到 0（page_out = short2 = 100 ms）",
              (0.0, 1.0, False) in seen, seen[:6])
        check("PART 1", "换页第二拍：内容换成新页、缩放从不带动画的一帧落到 PAGE_SCALE_IN",
              (1.0, T.PAGE_SCALE_IN, True) in seen, seen[:10])
        check("PART 1", "换页第三拍：缩放挂动画抬回 1，且两拍记在同一个 seq 上（终态不透明、不缩放）",
              seen and seen[-1] == (1.0, 1.0, True) and panel._page_seq == seq0 + 1
              and float(panel._body.scale) == 1.0,
              f"末态 {seen[-1] if seen else None}；seq {seq0} -> {panel._page_seq}")
        panel.show_tab(tab0)
        await asyncio.sleep(T.motion_ms("page") / 1000.0 + 0.3)

        # 改筛选 / 换排序 / 改条数这三条路径会把整表压到透明再淡回来（两拍，行数一变的跳高没有
        # 插值，靠这一次淡出淡入盖住）；**拖窗口换列集不走这条路**（点一行选中、双击开图都该是
        # 瞬时的）—— 所以 `_sync_hist_cols` 里不许有 `_hist_fade`。
        a_frame = G.AWAIT_FRAME
        panel.hist_box.opacity = 1.0
        panel.set_hist_filter(panel.hist_filter)
        dip_filter = (float(panel.hist_box.opacity) == 0.0
                      and panel.hist_box.animate_opacity is None)
        await asyncio.sleep(a_frame + 0.3)
        back_filter = (float(panel.hist_box.opacity) == 1.0
                       and panel.hist_box.animate_opacity is not None)
        check("PART 1", "改筛选：整表先压到透明、下一拍挂动画淡回来（两拍）",
              dip_filter and back_filter,
              f"压下去 {dip_filter}／淡回来 {back_filter}")
        saved_sort = (panel.hist.sort_col, panel.hist.sort_desc)
        panel.hist_box.opacity = 1.0
        panel._on_hist_sort(panel.hist.sort_col)
        dip_sort = float(panel.hist_box.opacity) == 0.0
        await asyncio.sleep(a_frame + 0.3)
        panel.hist.sort_col, panel.hist.sort_desc = saved_sort
        panel.hist_box.opacity = 1.0
        panel._sync_hist_cols(panel.page.width)
        check("PART 1", "换排序也淡；换列集（拖窗口）不淡 —— 选中与开图同样不许淡",
              dip_sort and float(panel.hist_box.opacity) == 1.0
              and "_hist_fade" not in inspect.getsource(G.Panel._sync_hist_cols)
              and "_hist_fade" not in inspect.getsource(G.Panel._on_hist_select),
              f"排序时压下去 {dip_sort}；换列集后 {panel.hist_box.opacity}")
        panel.hist_box.opacity = 1.0
        panel._on_hist_limit(type("_Ev", (), {"control": panel.hist_limit_box})())
        dip_limit = float(panel.hist_box.opacity) == 0.0
        await asyncio.sleep(a_frame + 0.3)
        check("PART 1", "改显示条数也走同一次两拍淡出淡入",
              dip_limit and float(panel.hist_box.opacity) == 1.0
              and int(panel.hist.limit) == core.hist_limit(panel.state),
              f"压下去 {dip_limit}；条数 {panel.hist.limit}")
        panel.state["motion"] = saved_motion

        n_hist = len(panel.hist.recs)
        for ev in (("phase", "正在演奏 1/3"), ("progress", 0.42), ("log_hdr", "第三轮 g900"),
                   ("result", {"record": dict(REC), "tag": "probe_flet"})):
            panel.core.q.put(ev)
        await asyncio.sleep(T.motion_ms("progress") / 1000.0 + 0.4)

        check("PART 1", "状态行接到了阶段",
              "1/3" in str(panel._footer_phase.value), repr(panel._footer_phase.value))
        check("PART 1", "进度条落到 0.42",
              abs(float(panel._footer_progress.value) - 0.42) < 0.02,
              repr(panel._footer_progress.value))
        check("PART 1", "百分比跟着写",
              str(panel._footer_pct.value).strip() == "42%", repr(panel._footer_pct.value))
        check("PART 1", "日志行上了界面", any("第三轮 g900" in t for t in texts()), why())
        check("PART 1", "结算行进了表格",
              len(panel.hist.recs) == n_hist + 1 and panel.hist.row_of_tag("probe_flet") >= 0,
              f"{n_hist} -> {len(panel.hist.recs)}")

        # 日志页点筛选 chip 也走同一套两拍（整列行换掉）；**敲关键词那一路不淡** —— 每敲一个字都
        # 闪一下就没法打字了，所以 `_reload_log_view`（打字与 chip 共用）里不许有 `_fade_box`。
        # 这一段放在上面那组事件之后：`log_view` 此刻真有行、`visible` 为真（没行时 `_fade_box` 直接返回）。
        panel.state["motion"] = 1
        panel.log_view.opacity = 1.0
        panel.set_log_filter(panel.log_filter)
        dip_log = (float(panel.log_view.opacity) == 0.0
                   and panel.log_view.animate_opacity is None)
        await asyncio.sleep(a_frame + 0.3)
        check("PART 1", "点日志筛选 chip 也两拍淡出淡入；敲关键词与换筛选的共用路径不淡",
              dip_log and float(panel.log_view.opacity) == 1.0
              and panel.log_view.animate_opacity is not None
              and "_fade_box" not in inspect.getsource(G.Panel._reload_log_view)
              and "_fade_box" not in inspect.getsource(G.Panel._on_log_search),
              f"压下去 {dip_log}；回位 {panel.log_view.opacity}")

        # 状态行：换一句话时走 `_fade_phase` 的两拍 —— 新字在 `_set_phase` 里就已经落到新值（那边
        # 为什么不能把换字押到第二拍，见 `_set_phase` 的注释），这一拍只负责让它**看得见**：先把
        # `animate_opacity` 摘掉、**不带动画**地把不透明度按到 0（起点必须在这一帧就画出去），下一帧
        # 再挂上 `MOTION["phase"]`（short3 = 150 ms）淡回来。从前这里是「挂着动画压到 0、等
        # `AWAIT_FRAME`（60 ms）就抬回 1」：补间刚走到四成就被反向，`phase` 这档令牌等于没用上，
        # 而终态一样（都是不透明）⇒ 只量终态的探针看不出来，所以这里也按两拍采样。
        panel.state["motion"] = 1
        saved_phase = (panel.phase, panel._footer_phase.value, panel._footer_phase.style.color)
        panel._footer_phase.animate_opacity = T.animation("phase")
        panel._footer_phase.opacity = 1.0
        panel._set_phase("探针甲")
        await asyncio.sleep(0.01)              # `_fade_phase` 是 page.run_task 起的，第一拍在任务里
        dip_phase = (float(panel._footer_phase.opacity) == 0.0
                     and panel._footer_phase.animate_opacity is None
                     and panel._footer_phase.value == "探针甲")
        await asyncio.sleep(a_frame + 0.3)
        back_phase = (float(panel._footer_phase.opacity) == 1.0
                      and panel._footer_phase.animate_opacity is not None)
        check("PART 1", "换状态行：新字瞬时压到透明、下一拍挂 phase 动画淡回来（两拍，不是 60 ms 凹陷）",
              dip_phase and back_phase,
              f"压下去 {dip_phase}／淡回来 {back_phase}")
        panel.phase, ph_text, ph_color = saved_phase
        panel._footer_phase.opacity = 1.0
        panel._snap_phase(ph_text, ph_color)

        # 选曲列表：换分类 / 换排序 / 翻方向 / 清空搜索这几路是**离散**换内容，也走 `_fade_box`
        # （与结算表、日志列同一套两拍）；**敲关键词那一路不许淡** —— 每敲一个字都闪一下就没法打字。
        panel.state["motion"] = 1
        panel.song_list.visible = True
        panel.song_list.opacity = 1.0
        panel._on_sort(None)
        dip_songs = (float(panel.song_list.opacity) == 0.0
                     and panel.song_list.animate_opacity is None)
        await asyncio.sleep(a_frame + 0.3)
        check("PART 1", "换排序：选曲列表也两拍淡出淡入；敲关键词那一路不淡",
              dip_songs and float(panel.song_list.opacity) == 1.0
              and panel.song_list.animate_opacity is not None
              and "_song_fade" not in inspect.getsource(G.Panel._on_search)
              and "reload_songs(fade=True)" not in inspect.getsource(G.Panel._on_search),
              f"压下去 {dip_songs}；回位 {panel.song_list.opacity}")

        # 曲中提示行：从藏到显时淡入（`MOTION["card"]`，与三处空态同一档）；**收起来仍瞬时** ——
        # 高度得立刻还回去（与 `_toggle_empty` 一个道理）。第一拍必须把 `animate_opacity` 摘掉：
        # 这一支的控件是「先前不透明、藏起来又显示」，不摘的话 1.0 → 0 自己就是一段补间，
        # 抬回 1.0 时它才走到两三成，看着是闪一下而不是淡进来（`_fade_box` 同型）。
        panel.state["motion"] = 1
        panel.ingame_hint.visible = False
        panel.ingame_hint.opacity = 1.0
        panel._set_hint("探针：画面一致")
        await asyncio.sleep(0.01)              # `_fade_in` 也是 page.run_task 起的
        hint_dip = (float(panel.ingame_hint.opacity) == 0.0
                    and panel.ingame_hint.animate_opacity is None
                    and panel.ingame_hint.visible is True)
        await asyncio.sleep(a_frame + 0.3)
        panel._set_hint("")
        hint_back = (float(panel.ingame_hint.opacity) == 1.0
                     and panel.ingame_hint.animate_opacity is not None)
        check("PART 1", "曲中提示行从藏到显时淡入（第一拍不带动画地压到 0）；收起来仍瞬时（高度立刻还回去）",
              hint_dip and hint_back and panel.ingame_hint.visible is False,
              f"压下去 {hint_dip}／回位 {hint_back}／收起 {panel.ingame_hint.visible}")
        panel.state["motion"] = saved_motion

        panel.core.q.put(("result", None))                 # 坏事件
        panel.core.q.put(("log_ok", "泵还活着"))
        await asyncio.sleep(0.4)
        check("PART 1", "坏事件之后泵还活着", any("泵还活着" in t for t in texts()), why())
        errs = [t for k, t in panel.log_store if k == "log_err" and "面板内部错误" in t]
        check("PART 1", "坏事件被记成面板内部错误", bool(errs), repr(errs[-1:]))

    # ---- PART 2 策略文案
    if _want("PART 2"):
        gap_spin = panel.policy_spins["gap_min"]
        saved_gap = gap_spin.value
        panel.push_chk.value = False
        panel.break_chk.value = False
        gap_spin.value = "0"
        panel.refresh_policy()
        t1 = str(panel.policy_info.value)
        check("PART 2", "双向放开要说出来", "双向放开" in t1, t1)
        check("PART 2", "关掉的项要标「已关」", "已关" in t1, t1)
        panel.push_chk.value = True
        panel.break_chk.value = True
        gap_spin.value = "8"
        panel.refresh_policy()
        t2 = str(panel.policy_info.value)
        check("PART 2", "开着时写进数字", "8" in t2 and "已关" not in t2, t2)
        gap_spin.value = saved_gap
        panel.refresh_policy()

    # ---- PART 3 「本轮」筛选按行号
    if _want("PART 3"):
        panel.clear_log()
        panel._write_line("上一轮留下的行", "log")
        panel.run_start = len(panel.log_store)
        panel._write_line("本轮开始后的行", "log")

        def view_texts():
            """**看界面**，不看 `log_store` —— 存储里从来都是全量，筛的是视图。

            行结构是 `Container(SelectionArea(Row(Text, Text)))`（整行带 + 时间戳独立一栏），取文本走
            模块级的递归助手（`log_row_text`）；从前那句 `"".join(s.text for s in c.spans)` 只认旧结构。
            """
            return log_view_texts(panel.log_view)

        panel.set_log_filter("all")
        v_all = view_texts()
        panel.set_log_filter("run")
        v_run = view_texts()
        check("PART 3", "全部页签两条都在",
              any("上一轮留下的行" in t for t in v_all)
              and any("本轮开始后的行" in t for t in v_all), repr(v_all))
        check("PART 3", "本轮页签只剩本轮那条",
              any("本轮开始后的行" in t for t in v_run)
              and not any("上一轮留下的行" in t for t in v_run), repr(v_run))
        panel.set_log_filter("all")

    # ---- PART 4 演出间隔的收尾拍（`at_select` 是**单调钟**：core 拿 `time.monotonic()` 相减）
    if _want("PART 4"):
        c = panel.core
        c.stop_flag.clear()
        c.at_select = None
        panel.clear_log()
        t0 = time.time()
        ok = c._wait_before_next(0.0)
        held = time.time() - t0
        check("PART 4", "间隔关着也等那一拍",
              ok is True and core.GAP_FLOOR_S - 0.3 <= held <= core.GAP_FLOOR_S + 1.5,
              f"held={held:.2f}s 返回 {ok!r}")
        c.at_select = time.monotonic() - 3600.0            # 锚点比间隔还旧
        t0 = time.time()
        ok = c._wait_before_next(5.0)
        held = time.time() - t0
        await asyncio.sleep(0.3)
        check("PART 4", "锚点太旧只等一拍",
              ok is True and held <= core.GAP_FLOOR_S + 1.5, f"held={held:.2f}s")
        check("PART 4", "那一拍不许报「演出间隔」",
              not any("演出间隔" in t for t in texts()), why())
        c.at_select = time.monotonic() - 3.0
        t0 = time.time()
        ok = c._wait_before_next(0.1)
        held = time.time() - t0
        check("PART 4", "锚点 3 秒前、间隔 0.1 分 ≈ 3 秒",
              ok is True and 2.4 <= held <= 4.5, f"held={held:.2f}s")
        c.stop_flag.set()
        panel.clear_log()
        t0 = time.time()
        ok = c._wait_before_next(5.0)
        held = time.time() - t0
        await asyncio.sleep(0.3)
        check("PART 4", "停止立刻打断等待", ok is False and held < 1.5, f"held={held:.2f}s")
        check("PART 4", "停止时说「未开始下一轮」",
              any("未开始下一轮" in t for t in texts()), why())
        c.stop_flag.clear()

    # ---- PART 5 链路撞界
    if _want("PART 5"):
        cal_path = rlog.CHAIN_CAL

        def write_cal(pinned, brief, corr=40.0):
            with io.open(cal_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump({"corr_ms": corr, "updated": "01-01 00:00", "pinned": pinned,
                           "pinned_brief": brief, "history": []}, f, ensure_ascii=False)

        def alarms():
            return [t for t in texts() if "已达边界" in t]

        panel._pinned = None                 # 组窗时读过一次真的 chain_cal.json，先清掉
        write_cal("+40.0 ms 顶住上界（板顶住 96 ms）", "+40.0 ms 顶住上界")
        n0 = len(alarms())
        panel.refresh_cfg_info()
        check("PART 5", "撞界时记一条日志", len(alarms()) == n0 + 1, repr(alarms()))
        check("PART 5", "日志写明偏移不再自适应",
              bool(alarms()) and "不再自适应" in alarms()[-1], repr(alarms()[-1:]))
        check("PART 5", "链路标定那张卡已经删了（读数不再上面板）",
              not hasattr(panel, "cfg_vals") and not hasattr(G.Panel, "_build_calib_card"),
              f"cfg_vals={'在' if hasattr(panel, 'cfg_vals') else '没了'}、"
              f"卡={'在' if hasattr(G.Panel, '_build_calib_card') else '没了'}")
        # 从前「完整的那份」靠悬停才看得到；卡没了之后它只能写进日志，所以这条改成查日志。
        check("PART 5", "日志里给完整那份边界（含「板顶住 96 ms」）",
              "板顶住 96 ms" in alarms()[-1], repr(alarms()[-1:]))
        n1 = len(alarms())
        panel.refresh_cfg_info()
        check("PART 5", "同一个边界只报一次", len(alarms()) == n1,
              f"+{len(alarms()) - n1}")
        write_cal(False, "未撞", corr=0.0)
        panel.refresh_cfg_info()
        check("PART 5", "未撞时不报", len(alarms()) == n1, f"+{len(alarms()) - n1}")
        check("PART 5", "未撞时去重状态复位", panel._pinned is None, repr(panel._pinned))
        write_cal("+40.0 ms 顶住上界（板顶住 96 ms）", "+40.0 ms 顶住上界")
        n2 = len(alarms())
        panel.refresh_cfg_info()
        check("PART 5", "未撞之后同一个边界会重新报", len(alarms()) == n2 + 1,
              f"+{len(alarms()) - n2}（若为 0，就是被上一次的报过状态永久静音了）")
        write_cal("-30.0 ms 顶住下界（板顶住 0 ms）", "-30.0 ms 顶住下界")
        n3 = len(alarms())
        panel.refresh_cfg_info()
        check("PART 5", "换了边界要再报一次", len(alarms()) == n3 + 1, f"+{len(alarms()) - n3}")

    # ---- PART 6 夹取 / 排序 / 连奏上限 / AP 重算
    if _want("PART 6"):
        check("PART 6", "间隔上界是 GAP_MAX_MIN", G.clamp_num("gap_min", "999") == float(
            core.GAP_MAX_MIN), G.clamp_num("gap_min", "999"))
        check("PART 6", "间隔下界是 0", G.clamp_num("gap_min", "-4") == 0.0)
        check("PART 6", "轮数上界是 RUNS_MAX", G.clamp_num("runs", "9999") == float(
            core.RUNS_MAX))
        check("PART 6", "正推上限是 PUSH_OFF_MS",
              G.clamp_num("push_cap_ms", "999") == float(core.PUSH_OFF_MS))
        check("PART 6", "重开次数上界 20", G.clamp_num("retry_cap", "50") == 20.0)
        # 种类偏移（用户 m15057「把四种都放出来」，m15291 从「演奏提前量」改名）：四个框在
        # **设置页**、状态键是 `defaults["kind_lead"]`、框名 `kind_<种类>`、夹取档位 ±60
        # （判定窗 PERFECT 只有 ±50）。卡标题也钉住 —— 改名是用户看得到的那一半。
        check("PART 6", "四枚种类偏移框回来了（tap/flick/long/trace 各一个）",
              sorted(getattr(panel, "kind_spins", {}) or {}) == sorted(core.KIND_LEAD_MS)
              and all(("kind_" + k) in G.NUM_RANGE for k in core.KIND_LEAD_MS),
              f"框={sorted(getattr(panel, 'kind_spins', {}) or {})}")
        check("PART 6", "那张卡的标题就是「种类偏移」",
              _kind_card_title(panel) == "种类偏移", repr(_kind_card_title(panel)))
        _note = [t for t in _kind_card_texts(panel) if "无关" in t]
        check("PART 6", "卡面点明了「按音符种类、与分类筛选无关」（撞字要自己说清）",
              len(_note) == 1 and "分类" in _note[0] and "无关" in _note[0],
              repr(_note[:1]))
        check("PART 6", "种类偏移夹在 ±60",
              G.clamp_num("kind_tap", "999") == 60.0 and G.clamp_num("kind_tap", "-999") == -60.0,
              f"{G.clamp_num('kind_tap', '999')}/{G.clamp_num('kind_tap', '-999')}")
        check("PART 6", "读不成数字就用兜底", G.clamp_num("gap_min", "abc", 3.5) == 3.5)
        check("PART 6", "没登记的名字不夹", G.clamp_num("nope", "999") == 999.0)

        gap_spin.value = "999"
        panel._save_defaults()
        st = core.read_json(core.STATE, {}) or {}
        check("PART 6", "手打 999 写进状态的是 120",
              st.get("defaults", {}).get("gap_min") == float(core.GAP_MAX_MIN),
              repr(st.get("defaults", {}).get("gap_min")))
        check("PART 6", "框里的字面量也改回去", gap_spin.value == "120",
              repr(gap_spin.value))
        check("PART 6", "core 读到的是 120", panel.core.gap_min() == float(core.GAP_MAX_MIN),
              panel.core.gap_min())
        panel.n_field.value = "9999"
        panel._save_defaults()
        st = core.read_json(core.STATE, {}) or {}
        check("PART 6", "轮数被夹到 RUNS_MAX",
              st.get("defaults", {}).get("runs") == core.RUNS_MAX,
              repr(st.get("defaults", {}).get("runs")))
        check("PART 6", "轮数框也改回 RUNS_MAX", panel.n_field.value == str(core.RUNS_MAX),
              repr(panel.n_field.value))
        panel.n_field.value = "1"
        panel._save_defaults()
        got_abc = _gap_from(core, panel, "abc")
        got_neg = _gap_from(core, panel, "-3")
        check("PART 6", "状态文件被手改成 abc 也读 0.0", got_abc == 0.0, repr(got_abc))
        check("PART 6", "状态文件被手改成 -3 也读 0.0", got_neg == 0.0, repr(got_neg))
        panel._save_defaults()
        gap_spin.value = "0.0"

        # 种类偏移：打一个负数进去，状态里必须是那个负数（**不被夹成正数**），core 读出来一致，
        # 提示行把方向说出来，argv 里那一串由 `panelfly.py` 第 1 关盯。
        tap_spin = panel.kind_spins["tap"]
        tap_spin.value = "-30"
        tap_spin.on_change(None)          # 走**控件自己的回调**（牙 `kindwire` 换的就是它）
        st = core.read_json(core.STATE, {}) or {}
        kd = (st.get("defaults", {}) or {}).get("kind_lead") or {}
        check("PART 6", "白键晚 30 ms 写进 defaults['kind_lead']", kd.get("tap") == -30.0,
              repr(kd))
        check("PART 6", "core 读出来就是 -30（负号不许被吃掉）",
              panel.core.kind_lead().get("tap") == -30.0, repr(panel.core.kind_lead()))
        check("PART 6", "其余三类仍是 0（只动点名的那个）",
              all(panel.core.kind_lead().get(k) == 0.0
                  for k in core.KIND_LEAD_MS if k != "tap"),
              repr(panel.core.kind_lead()))
        check("PART 6", "提示行说清方向", "白键 tap 晚 30 ms" in (panel.kind_hint.value or ""),
              repr(panel.kind_hint.value))
        tap_spin.value = "999"
        tap_spin.on_change(None)
        check("PART 6", "打 999 夹到 60，框里也改回 60",
              tap_spin.value == "60"
              and panel.core.kind_lead().get("tap") == 60.0, repr(tap_spin.value))
        tap_spin.value = "0"
        tap_spin.on_change(None)
        check("PART 6", "全零时提示行说「出厂值」",
              "出厂值" in (panel.kind_hint.value or ""), repr(panel.kind_hint.value))

        # 尾判滑键（用户 m52916「能否将尾滑偏移加入设置」）：**另一格、另一个键**。打 0 进去
        # 状态里必须是 0（那是「关掉这段提前量」，不是「没设」——没设读出来是出厂值），
        # 夹取只往早的方向（打负数被夹回 0，打 999 夹到 60），提示行也要跟着点名。
        tls = panel.tail_lead_spin

        def _holds(ctl, want, depth=0):
            """`want` 这个控件是不是真的长在 `ctl` 底下（沿 controls / content 两层走）。

            只看「属性上挂着」不够：控件建了却不往卡里放，界面上根本没有它（牙 `tailplace`）。
            """
            if ctl is want:
                return True
            if depth > 12:
                return False
            kids = list(getattr(ctl, "controls", None) or [])
            c = getattr(ctl, "content", None)
            if c is not None:
                kids.append(c)
            return any(_holds(k, want, depth + 1) for k in kids)

        check("PART 6", "尾滑那格真的排在设置页那张卡里（不是只建了个控件）",
              _holds(panel._kind_row, tls))
        check("PART 6", "尾判滑键那格的初值是出厂值",
              tls is not None and int(float(tls.value)) == int(core.TAIL_FLICK_LEAD_DEFAULT),
              repr(getattr(tls, "value", None)))
        tls.value = "0"
        tls.on_change(None)               # 走**控件自己的回调**（牙 `tailwire` 换的就是它）
        st = core.read_json(core.STATE, {}) or {}
        check("PART 6", "尾滑 0 写进 defaults['tail_flick_lead']（不是 kind_lead 里）",
              (st.get("defaults", {}) or {}).get("tail_flick_lead") == 0.0
              and "tail" not in ((st.get("defaults", {}) or {}).get("kind_lead") or {}),
              repr((st.get("defaults", {}) or {}).get("tail_flick_lead")))
        check("PART 6", "core 读出来就是 0", panel.core.tail_flick_lead() == 0.0,
              repr(panel.core.tail_flick_lead()))
        check("PART 6", "提示行点名「尾判滑键关闭」",
              "尾判滑键关闭" in (panel.kind_hint.value or ""), repr(panel.kind_hint.value))
        tls.value = "-20"
        tls.on_change(None)
        check("PART 6", "打 -20 夹回 0（只往早的方向）",
              int(float(tls.value)) == 0 and panel.core.tail_flick_lead() == 0.0, repr(tls.value))
        tls.value = "999"
        tls.on_change(None)
        check("PART 6", "打 999 夹到 60，框里也改回 60",
              tls.value == "60" and panel.core.tail_flick_lead() == 60.0, repr(tls.value))
        tls.value = str(int(core.TAIL_FLICK_LEAD_DEFAULT))
        tls.on_change(None)

        ag = open(os.path.join(ROOT, "AGENTS.md"), encoding="utf-8").read()
        import re
        m = re.search(r"连续演出上限\s*\*{0,2}(\d+)\*{0,2}\s*轮", ag)
        check("PART 6", "连续演出上限与 AGENTS.md 同数",
              bool(m) and int(m.group(1)) == core.RUNS_MAX,
              f"AGENTS.md={m.group(1) if m else None} core={core.RUNS_MAX}")

        before_tags = list(panel.hist.tags)
        desc0 = panel.hist.sort_desc
        panel._on_hist_sort("P")
        check("PART 6", "换列排序：列名跟着换", panel.hist.sort_col == "P", panel.hist.sort_col)
        check("PART 6", "换列排序：方向不变", panel.hist.sort_desc is desc0)
        check("PART 6", "排序真的动了行序", panel.hist.tags != before_tags,
              f"{before_tags[:3]} -> {panel.hist.tags[:3]}")
        panel._on_hist_sort("P")
        check("PART 6", "同列再点翻向", panel.hist.sort_desc is (not desc0))

        # 缺数据的行**两个方向都排在最后**（2026-10-09 用户 m11595：「从大到小排序时为什么总是这些
        # 占位符排在最前面，并且这些占位符与正常数的差距还是太小了」）。夹具里 s004/s005 的
        # `non_perfect` 是 None（中断 / 读取失败）⇒ 按「漏键」那一列排序时它们必须在**两个方向**
        # 都落在最后；而表格里缺读数那几格画出来的字必须是占位符 `—`（不是 `0` —— `0` 是一个读数）。
        keep_sort = (panel.hist.sort_col, panel.hist.sort_desc)
        blank_tags = [t for t in panel.hist.tags
                      if core.hist_num(panel.hist.recs[t], "non_perfect") is None]
        check("PART 6", "夹具里真有缺读数的行（否则下面几条在量空气）", len(blank_tags) >= 2,
              f"{blank_tags}")
        for desc in (True, False):
            panel.hist.sort_col, panel.hist.sort_desc = "np", desc
            panel.hist.rebuild()
            panel._render_history()
            await asyncio.sleep(0.2)
            tags = list(panel.hist.tags)
            vals = [core.hist_num(panel.hist.recs[t], "non_perfect") for t in tags]
            have = [v for v in vals if v is not None]
            check("PART 6", f"漏键列{'降序' if desc else '升序'}：缺数据的行都排在最后",
                  len(vals) == len(tags) and vals[:len(have)] == sorted(have, reverse=desc)
                  and all(v is None for v in vals[len(have):]),
                  f"tags={tags} np={vals}")

        def cell_text(row, name):
            cols = list(panel._hist_cols)
            if name not in cols or row is None:
                return None
            i = 1 + cols.index(name)                      # 0 号格是行首那条判定竖条
            if i >= len(row.cells):
                return None
            inner = getattr(getattr(row.cells[i], "content", None), "content", None)
            return getattr(inner, "value", None)

        blank_row = panel.hist.row_of_tag(blank_tags[0])
        zero_tag = next((t for t in panel.hist.tags
                         if core.hist_num(panel.hist.recs[t], "non_perfect") == 0), None)
        zero_row = panel.hist.row_of_tag(zero_tag) if zero_tag else -1
        drawn_blank = cell_text(panel.hist_table.rows[blank_row] if blank_row >= 0 else None, "np")
        drawn_zero = cell_text(panel.hist_table.rows[zero_row] if zero_row >= 0 else None, "np")
        np_col = core.HIST_COLS.index("np") + 1
        check("PART 6", "真窗口：缺读数那一格画的是占位符 `—`",
              drawn_blank == core.HIST_BLANK, f"{blank_tags[0]} 的 np 格画出来 {drawn_blank!r}")
        check("PART 6", "真窗口：真 0 那一格画的仍是 `0`（占位符不是 0）",
              drawn_zero == "0", f"{zero_tag} 的 np 格画出来 {drawn_zero!r}")
        check("PART 6", "没读数与真 0 都压暗、真数不压暗（is_muted）",
              panel.hist.is_muted(blank_tags[0], np_col)
              and (zero_tag is None or panel.hist.is_muted(zero_tag, np_col))
              and not panel.hist.is_muted("s002", np_col),
              f"blank={panel.hist.is_muted(blank_tags[0], np_col)} "
              f"zero={None if zero_tag is None else panel.hist.is_muted(zero_tag, np_col)} "
              f"real={panel.hist.is_muted('s002', np_col)}")
        # 判定列**不借数字列那个占位符**（2026-10-09 用户 m11846：「仅完成未FC与AP的记录状态标为成功，
        # 现在的破折号有歧义」）：s003（漏键 12、既没 AP 也没 FC）那一格画出来必须是 `成功`，不是 `—`。
        badge_row = panel.hist.row_of_tag("s003")
        drawn_badge = cell_text(panel.hist_table.rows[badge_row] if badge_row >= 0 else None, "badge")
        check("PART 6", "真窗口：打完了但没 AP/FC 的判定格画的是「成功」",
              drawn_badge == core.hist_badge(panel.hist.recs["s003"]) == "成功",
              f"s003 的判定格画出来 {drawn_badge!r}")
        panel.hist.sort_col, panel.hist.sort_desc = keep_sort
        panel.hist.rebuild()
        panel._render_history()
        await asyncio.sleep(0.2)

        calls = {"n": 0}
        real_ids = core.ap_ids

        def counted(*a, **k):
            calls["n"] += 1
            return real_ids(*a, **k)

        core.ap_ids = counted
        old = getattr(panel, "ap", None)
        try:
            panel.core.q.put(("result", {"record": dict(REC, tag="probe_flet2"),
                                         "tag": "probe_flet2"}))
            await asyncio.sleep(0.4)
        finally:
            core.ap_ids = real_ids
        check("PART 6", "结算之后 AP 集合重算",
              calls["n"] >= 1 and getattr(panel, "ap", None) is not old,
              f"calls={calls['n']}")

    # ---- PART 7 快捷键与外观路径
    if _want("PART 7"):
        panel.clear_log()
        panel._on_key(_K("R", ctrl=True))
        await asyncio.sleep(0.2)
        check("PART 7", "Ctrl+R 重读谱面库与记录",
              any("已重新读取" in t for t in texts()), why())
        got = []
        real_start = panel.start_run
        panel.start_run = lambda force=False: got.append(force)
        try:
            panel._on_key(_K("F5"))
        finally:
            panel.start_run = real_start
        check("PART 7", "F5 走的是 start_run(force=False)", got == [False], repr(got))
        panel._on_key(_K("L", ctrl=True))
        check("PART 7", "Ctrl+L 清空日志", len(panel.log_store) == 0, len(panel.log_store))
        check("PART 7", "m3_theme 不再自己存一份状态路径",
              not hasattr(T, "STATE"))
        want = "dark" if T.resolve_appearance(None) != "dark" else "light"
        core.save_state({"appearance": want})
        check("PART 7", "外观只有一条路：状态文件说了算",
              T.resolve_appearance(None) == want, T.resolve_appearance(None))

    # ---- PART 8 日志窗口与存储上限
    if _want("PART 8"):
        panel.clear_log()
        panel.run_start = core.LOG_KEEP
        over = core.LOG_KEEP + 50
        t0 = time.time()
        for i in range(over):
            panel._write_line(f"行 {i}", "log")
        dt = time.time() - t0

        def span_text(c):
            # 行控件是 `Container(SelectionArea(Row(Text, Text)))`；取文本走模块级递归助手，别只看
            # `.spans`（那是 m11676 之前「一段 Text 挂两段 span」的旧结构）。
            return log_row_text(c)

        check("PART 8", "存储留 LOG_KEEP 行",
              len(panel.log_store) == core.LOG_KEEP, len(panel.log_store))
        check("PART 8", "视图只留 LOG_WINDOW 行",
              len(panel.log_view.controls) == core.LOG_WINDOW,
              len(panel.log_view.controls))
        check("PART 8", "最新一行在底",
              span_text(panel.log_view.controls[-1]) == f"行 {over - 1}",
              repr(span_text(panel.log_view.controls[-1])))
        check("PART 8", "最老一行正好被裁掉",
              span_text(panel.log_view.controls[0]) == f"行 {over - core.LOG_WINDOW}",
              repr(span_text(panel.log_view.controls[0])))
        check("PART 8", "run_start 跟着退",
              panel.run_start == core.LOG_KEEP - 50, panel.run_start)
        check("PART 8", "log_info 的计数对得上",
              panel.log_info.value == f"显示 {core.LOG_WINDOW} / 共 {core.LOG_KEEP} 行",
              repr(panel.log_info.value))
        check("PART 8", "逐行 append 比朴素重排快得多",
              dt / over < 0.0005, f"{dt / over * 1000:.3f} ms/行（{over} 行 {dt:.2f}s）")

    # ---- PART 8（续）日志页这一轮的**行为**判据。
    if _want("PART 8"):
        #
        # `fletgui.py` 那几条是源码级的（钉「代码长这样」），这里跑的是真 `Panel` 实例（钉「跑起来
        # 是这个结果」）：关键词真的少画行、两种空真的互斥、计数行真的被推出去、开关真的跟着真实
        # 钉住状态走、清屏真的说话。像素层那一半交给 `fletviewcheck.py` 的十个面。
        panel.clear_log()
        panel.log_query = ""
        panel.log_search.value = ""
        panel._refresh_log_info()
        check("PART 8", "空库时说「没有日志」、不说「没有匹配」",
              panel.log_empty.visible is True and panel.log_none.visible is False
              and panel.log_view.visible is False,
              f"日志={panel.log_empty.visible} 匹配={panel.log_none.visible} "
              f"视图={panel.log_view.visible}")

        push_seen = []
        real_push = panel._push_ctl
        panel._push_ctl = lambda *c: (push_seen.extend(c), real_push(*c))[1]
        panel._write_line("10:00:00 关键词探针：命中", "log")
        panel._write_line("10:00:01 别的行", "log")
        panel._push_ctl = real_push
        check("PART 8", "写入之后计数行自己推给客户端（不靠泵）",
              panel.log_info in push_seen, f"推了 {len(push_seen)} 个控件")

        panel.log_search.value = "命中"
        panel._on_log_search()
        check("PART 8", "关键词一搜就只剩命中的那几行",
              len(panel.log_view.controls) == 1
              and "命中" in span_text(panel.log_view.controls[0]),
              f"{len(panel.log_view.controls)} 行")
        panel.log_search.value = "说什么都不会命中"
        panel._on_log_search()
        check("PART 8", "库里有行、只是被筛没了 ⇒ 走「没有匹配」",
              panel.log_none.visible is True and panel.log_empty.visible is False
              and len(panel.log_view.controls) == 0,
              f"匹配={panel.log_none.visible} 日志={panel.log_empty.visible} "
              f"{len(panel.log_view.controls)} 行")
        panel._clear_log_search()
        check("PART 8", "清关键词把视图还原",
              len(panel.log_view.controls) == 2 and panel.log_query == ""
              and panel.log_search_clear.visible is False,
              f"{len(panel.log_view.controls)} 行 / query={panel.log_query!r}")

        class _S:                                # 滚动事件的替身：`_on_log_scroll` 只读这两项

            def __init__(self, pixels, max_scroll_extent):
                self.pixels, self.max_scroll_extent = pixels, max_scroll_extent

        panel.log_autoscroll.value = True
        panel.log_view.auto_scroll = True
        panel._on_log_scroll(_S(0.0, 800.0))     # 用户往上滚了
        # 开关要掰，但**钉住本身一个字都不许动**：翻 `auto_scroll` 换掉的是客户端的元素树形状 ⇒
        # 子树重建、位置丢掉 ⇒ 整屏被拉回顶部（用户 m27254）。这一侧的暂停/恢复 Flet 自己会做
        # （`ScrollableControl.auto_scroll` docstring：滚离末尾时暂停、滚回来自己恢复）。
        check("PART 8", "用户滚离底部，开关不再说「正在跟」，而钉住一个字都没动",
              panel.log_autoscroll.value is False and panel.log_view.auto_scroll is True,
              f"开关={panel.log_autoscroll.value} 钉住={panel.log_view.auto_scroll}")
        panel._on_log_scroll(_S(796.0, 800.0))   # 滚回底部（留 4 px 余量）
        check("PART 8", "滚回底部，钉住自己回来",
              panel.log_autoscroll.value is True and panel.log_view.auto_scroll is True,
              f"开关={panel.log_autoscroll.value} 钉住={panel.log_view.auto_scroll}")
        panel.log_autoscroll.value = False       # 用户自己把开关关掉过（`_auto` 那一侧关的）
        panel.log_view.auto_scroll = False
        panel._on_log_scroll(_S(796.0, 800.0))   # 再滚回底部：那是他的设置，不许被掰回来
        check("PART 8", "手动关掉过：滚回底部也不许把钉住掰回来",
              panel.log_autoscroll.value is False and panel.log_view.auto_scroll is False,
              f"开关={panel.log_autoscroll.value} 钉住={panel.log_view.auto_scroll}")

        said = []
        real_toast = G.toast
        G.toast = lambda *a, **k: said.append(a[2] if len(a) > 2 else "")
        panel.clear_log()
        G.toast = real_toast
        check("PART 8", "清屏当场说话（说了清掉几行）",
              bool(said) and "2 行" in said[-1], repr(said))

        # 用户 m11265 报的那一条：「点了的确会切换但选中效果不变」—— 行换了，chip 自己没被推出去
        # （改控件属性而不调它的 `.update()`，客户端照旧画旧值）。这里量的是**真控件**：点一次筛选，
        # 每一枚 chip 都得进「被推的名单」，而且选中那一枚的三件（selected / 描边 / 标签色）都得真换。
        panel.set_log_filter("all")
        chip_pushes = []
        real_push = panel._push_ctl
        panel._push_ctl = lambda *c: (chip_pushes.extend(c), real_push(*c))[1]
        try:
            panel.set_log_filter("run")
        finally:
            panel._push_ctl = real_push
        btns = list(panel.log_btns.values())
        pushed = [b for b in btns if b in chip_pushes]
        check("PART 8", "点筛选当场把每一枚 chip 推给客户端（行换了、选中态也得换）",
              bool(btns) and len(pushed) == len(btns),
              f"{len(pushed)}/{len(btns)} 枚被推，共推了 {len(chip_pushes)} 个控件")
        sel = panel.log_btns["run"]
        others = [b for k, b in panel.log_btns.items() if k != "run"]
        want_on, want_off = panel.tk.chip_side(True).color, panel.tk.chip_side(False).color
        check("PART 8", "选中那枚不描边、其余描 outline_variant，标签色走 on_secondary_container",
              want_on != want_off and sel.selected is True
              and sel.border_side.color == want_on
              and all(b.selected is False and b.border_side.color == want_off for b in others)
              and sel.label.color == panel.tk.on_secondary_container,
              f"选中={sel.border_side.color} 未选中={others[0].border_side.color if others else None}")
        panel.set_log_filter("all")

        # 用户 m11676「日志界面的美观度还能如何提升」那一轮的**行为**判据：真控件上量的，不是源码文本。
        #   ① 错误行的整行带挂在**包住整行**的 `ft.Container` 上 —— 旧结构挂在 `ft.Text` 自己那个
        #      盒子上，只有文字那么宽（实测 41 %），看着像「选中了这段字」；而 `ListView` 的孩子是松
        #      约束、`expand` 无效，所以要靠 `Row` 的 `mainAxisSize` 默认 max 铺满。
        #   ② 时间戳是独立一栏：固定宽、不折行；正文栏吃余量、自己折行（折行的续行因此有悬挂缩进）。
        #   ③ 两栏由**一个** `ft.SelectionArea` 包住：各自 `selectable` 会各开一个选区、拖选被截断。
        panel._write_line("10:00:02 这一行是错误", "log_err")
        panel._write_line("这一行没有时间戳", "log")
        err_row = panel.log_view.controls[-2]
        plain_row = panel.log_view.controls[-1]
        gut, msg = err_row.content.content.controls
        check("PART 8", "错误行的底挂在整行 Container 上（不是文字那么宽）",
              isinstance(err_row, ft.Container) and isinstance(err_row.content, ft.SelectionArea)
              and err_row.bgcolor == panel.tk.state(panel.tk.danger, "disabled_container"),
              f"{type(err_row).__name__} / {err_row.bgcolor!r}")
        check("PART 8", "时间戳独立一栏：固定宽 + 不折行，正文吃余量自己折行",
              gut.width == T.LOG_TS_W and gut.no_wrap is True and gut.value == "10:00:02 "
              and msg.expand is True and msg.no_wrap is False
              and (gut.value or "") + (msg.value or "") == "10:00:02 这一行是错误",
              f"gut={gut.value!r} w={gut.width} msg={msg.value!r}")
        check("PART 8", "没有时间戳的行仍占住那一栏（行高不跳）",
              plain_row.content.content.controls[0].value == ""
              and log_row_text(plain_row) == "这一行没有时间戳",
              repr(log_row_text(plain_row)))
        panel.clear_log()

    # ---- PART 9 隔离（真实 research/ 与夹具各写各的）
    if _want("PART 9"):
        check("PART 9", "状态文件落在夹具里",
              os.path.abspath(core.STATE).startswith(os.path.abspath(fixture)),
              core.STATE)
        check("PART 9", "链标定文件也落在夹具里",
              os.path.abspath(rlog.CHAIN_CAL).startswith(os.path.abspath(fixture)),
              rlog.CHAIN_CAL)

    # ---- PART 10 弹性布局：窗口变了版式跟着走，不是停在某个写死的宽度上
    if _want("PART 10"):
        #
        # 判据分两层：**控件层**（分栏真的是 12 栏栅格，且没有「写死栏宽」的常量）与
        # **像素层**（把窗口从 1280 拉到 1560，两块卡片之间那条留白必须跟着右移；缩到 760
        # 它必须自己叠起来 —— 中间那条留白消失）。原来设置页是 `Row(width=470 + width=300)`
        # 写死的 770 px：拉宽到 1560 它还是 770，右边一大片空地 —— 像素层量的就是这件事。
        from PIL import Image

        page = panel.page
        page.enable_screenshots = True
        await asyncio.sleep(0.2)

        def _cols(ctl):
            # 直接取 `col` 原值：不在栅格里的孩子身上它是 0 / None，写成 `dict(...)` 会炸
            # （拆牙时看到的正是这个 —— 探针自己炸掉会把「只点亮这一关」变成点亮 PART 0）。
            return [c.col for c in ctl.controls]

        check("PART 10", "两页的分栏都是 12 栏栅格",
              isinstance(panel._start_cols, ft.ResponsiveRow)
              and isinstance(panel._settings_row, ft.ResponsiveRow),
              f"{type(panel._start_cols).__name__} / {type(panel._settings_row).__name__}")
        # 两个方向都写死 `col`：并排 `{"xs":6}`、叠起来 `{"xs":12}`。`xs` 是 0 号断点，
        # 任何宽度都命中，所以「两栏还是 一栏」只由视图层的 `STACK_W` 说了算 ——
        # 从前写 `{"xs":12,"lg":6}` 时，栅格的 `lg` 断点会按一个既不是窗口宽也不是内容宽
        # 的参考宽再判一次，翻面点在 1000~1120 之间飘（实测）。
        check("PART 10", "开始页两栏各写死半栏（`xs` 断点，窄了由视图层换成整栏）",
              _cols(panel._start_cols) == [{"xs": 6}, {"xs": 6}],
              repr(_cols(panel._start_cols)))
        # 2026-10-10 用户 m13525：设置页改成**左右布局** —— 「面板」与「资源」两张卡各 6 栏并排
        # （从前各 7 栏 + `alignment=CENTER`，两张 7/12 加起来 14 栏 ⇒ 栅格换行、其实是上下堆着）。
        # 两张 6/12 正好铺满整行，居中也就没有意义了，所以那一行不再给 `alignment`。
        check("PART 10", "设置页两张卡左右并排、各占 6 栏（窄了各自撑满一栏）",
              _cols(panel._settings_row) == [{"xs": 12, "md": 6}, {"xs": 12, "md": 6}],
              repr(_cols(panel._settings_row)))
        check("PART 10", "设置页那一行不再靠居中来摆（两张 6/12 自己就铺满整行）",
              panel._settings_row.alignment == ft.MainAxisAlignment.START,
              repr(panel._settings_row.alignment))
        check("PART 10", "没有「写死的栏宽」这种常量了", not hasattr(G, "LEFT_W"))

        def _walk(ctl):
            """控件树遍历：Flet 没有 children API，`dataclasses.fields()` 是唯一通用入口。"""
            import dataclasses
            seen, stack = set(), [ctl]
            while stack:
                c = stack.pop()
                if not isinstance(c, ft.Control) or id(c) in seen:
                    continue
                seen.add(id(c))
                yield c
                try:
                    flds = dataclasses.fields(c)
                except TypeError:
                    continue
                for f in flds:
                    v = getattr(c, f.name, None)
                    if isinstance(v, ft.Control):
                        stack.append(v)
                    elif isinstance(v, (list, tuple)):
                        stack.extend(x for x in v if isinstance(x, ft.Control))

        # 「联网更新谱面库」这一组 Tk 版就有，面板全面转 PySide6 时整组被删，只剩视图层两个没人喂
        # 事件的处理器（`upstream` / `charts_done`）—— 用户 m06894 报「设置里的资源更新不见了」。
        # 三条：① 卡里的三件控件真的挂进了设置页栅格；② core 那一链的工具名/事件名/读数文件都在；
        # ③ 更新期间 `busy()` 为真（面板因此开不了局：`fetch_charts` 会重写 `research/charts/`）。
        _set_nodes = list(_walk(panel._settings_row))
        _in_grid = all(c in _set_nodes for c in (panel.update_btn, panel.force_chk, panel.res_hint))
        check("PART 10", "设置页「资源」卡在场：联网更新按钮 + 强制重下开关 + 一行读数都在栅格里",
              _in_grid and panel.update_btn.content == "联网更新"
              and any(isinstance(c, ft.Text) and c.value == "资源" for c in _set_nodes),
              f"{panel.update_btn.content!r} / 挂进栅格={_in_grid}")
        _u_src = inspect.getsource(core.RunOrchestrator.update_charts)
        _loop_src = inspect.getsource(core.RunOrchestrator._update_loop)
        _tool_src = inspect.getsource(core.RunOrchestrator._stream_tool)
        _pump_src = inspect.getsource(core.RunOrchestrator._pump_child)
        check("PART 10", "core 的更新链路：比对上游 → 补下载 → 发 `upstream` / `charts_done`",
              "self.busy()" in _u_src and "check_upstream.py" in _loop_src
              and "fetch_charts.py" in _loop_src and '"--force"' in _loop_src
              and '"upstream"' in _loop_src and '"charts_done"' in _loop_src
              and "UPSTREAM_REPORT" in _loop_src
              and "child_line" in _pump_src and "self.proc" in _tool_src,
              "")

        class _Held:
            """占住 `self.proc` 的假进程：让 `busy()` 为真而**不起真进程、不联网**。"""

            def poll(self):
                return None

        _o = core.RunOrchestrator({})
        _o.proc = _Held()
        _refused = _o.update_charts() is False
        check("PART 10", "更新期间面板开不了局（`update_charts` 被 `busy()` 挡回 False）",
              _refused, f"update_charts() -> {_refused}")
        _o.proc = None

        # 用户 m07356 那一轮的 P1/P2/P3：先比对再问、报告新鲜度、首选目录、逐张核对、真超时。
        _in_grid2 = all(c in _set_nodes for c in (panel.source_box, panel.verify_chk))
        check("PART 10", "「资源」卡多两件：首选目录下拉 + 逐张核对开关都在栅格里",
              _in_grid2 and panel.source_box.value == core.preferred_source(panel.state)
              and panel.verify_chk.value is False and panel.force_chk.value is False,
              f"挂进栅格={_in_grid2} / 首选={panel.source_box.value!r}")
        check("PART 10", "首选目录只认两个键，缺键/坏值一律回退 MoeNotes",
              core.SOURCE_KEYS == ("moenotes", "haneoka")
              and core.preferred_source({}) == "moenotes"
              and core.preferred_source({"preferred_source": "haneoka"}) == "haneoka"
              and core.preferred_source({"preferred_source": "whatever"}) == "moenotes",
              repr(core.preferred_source({"preferred_source": "whatever"})))
        _loop2 = inspect.getsource(core.RunOrchestrator._update_loop)
        check("PART 10", "比对那一趟：`--source=` / `--verify` 传下去，报告按 mtime 判新鲜",
              '"--source="' in _loop2 and '"--verify"' in _loop2 and "_mtime" in _loop2
              and "fresh = rc == 0" in _loop2 and '"fresh"' in _loop2
              and "_pinned_ids" in _loop2 and '"validated"' in _loop2
              and 'DECIDE_WAIT' in _loop2 and '"update_abort"' in _loop2,
              "")
        check("PART 10", "「强制重下」在比对之后等那一按（force 才等，每 0.25 s 看 stop_flag）",
              'self.decide_ev.wait(0.25)' in _loop2 and "self.stop_flag.is_set()" in _loop2
              and 'self.decide.get("ok")' in _loop2,
              "")
        _tool2 = inspect.getsource(core.RunOrchestrator._stream_tool)
        _pump2 = inspect.getsource(core.RunOrchestrator._pump_child)
        check("PART 10", "超时是真的：读输出另起线程，主线程 `wait(timeout)` 等得到",
              "child.wait(timeout=timeout)" in _tool2 and "subprocess.TimeoutExpired" in _tool2
              and "_pump_child" in _tool2 and "reader.join" in _tool2
              and "child.kill()" in _pump2 and "PROGRESS_RE" in _pump2,
              "")
        check("PART 10", "进度按 `[i/N]` 行头认出来（别的行照原样进日志）",
              core.PROGRESS_RE.match("[3/87] 草 paper Lv12 500 notes") is not None
              and core.PROGRESS_RE.match("[3/87]").group(1) == "3"
              and core.PROGRESS_RE.match("  谱面库 87 首") is None,
              "")
        _o2 = core.RunOrchestrator({})
        _blank = not _o2.decide_ev.is_set() and _o2.decide == {}
        _o2.answer_update(True, force=True)
        _yes = _o2.decide == {"ok": True, "force": True} and _o2.decide_ev.is_set()
        _o3 = core.RunOrchestrator({})
        _o3.answer_update(False)
        _no = _o3.decide == {"ok": False} and _o3.decide_ev.is_set()
        check("PART 10", "确认框那一按解得开等待：`ok`/`force` 落进 `decide`（取消也解得开）",
              _blank and _yes and _no, f"初始空={_blank} / 确定={_yes} / 取消={_no}")

        # 开始页在**宽窗**下自适应、不滚：左栏只有选曲（列表自己长），右栏是运行 + 一张「最近」
        # 卡（卡里按余量放 N 条记录，条数判据在下面）；两卡靠 `expand` 把本栏的余量分掉、四边
        # 因此对齐（中间那个 `Container(expand=True)`
        # 空档是上一版的东西：窗口一高它就张成一大块空洞，两张卡被顶到两头）。窄窗那一档
        # 反过来：叠成一栏 + 整页滚，判据在下面拍完 760 之后。
        # （Flet 1.0.3 的 `ft.ScrollMode` 只有 ADAPTIVE/ALWAYS/AUTO/HIDDEN，**没有 NONE** ——
        # 不滚就是 `scroll is None`；这里两种都认，只认 None 会在将来某个默认值上误报。）
        _sc = getattr(panel.pages[0], "scroll", None)
        check("PART 10", "宽窗下开始页整页不可滚（自适应）",
              _sc is None or str(_sc).endswith("NONE"),
              repr(_sc))
        check("PART 10", "开始页左栏只剩选曲卡（「最近」搬去右栏了）",
              [type(c).__name__ for c in panel._left_col.controls] == ["Card"],
              repr([type(c).__name__ for c in panel._left_col.controls]))
        check("PART 10", "开始页右栏是「运行 + 最近演出」两张卡（空档删了、记录不再一卡一局）",
              [type(c).__name__ for c in panel._right_col.controls] == ["Card", "Card"]
              and panel._right_col.controls[1] is panel.recent.card
              and len(panel.recent.rows) == G.RECENT_POOL,
              repr([type(c).__name__ for c in panel._right_col.controls]))
        # 四边对齐是靠「两张卡各自吃本栏余量」实现的：右栏第一张（运行）卡必须 expand，
        # 否则它只按内容高，下方空一截、下沿与左栏对不上。
        check("PART 10", "运行卡吃右栏余量（下沿才与左栏齐平）",
              panel.run_card.expand is True and panel.run_card is panel._right_col.controls[0],
              f"expand={getattr(panel.run_card, 'expand', None)}")
        check("PART 10", "选曲卡吃满左栏（卡片与卡内 body 都 expand）",
              panel._left_col.controls[0].expand is True and panel._pick_body.expand is True,
              f"card={panel._left_col.controls[0].expand} body={panel._pick_body.expand}")
        check("PART 10", "三个运行策略数都在运行卡里（原「运行策略」卡已删）",
              sorted(panel.policy_spins) == ["gap_min", "push_cap_ms", "retry_cap"]
              and not hasattr(G.Panel, "_build_policy_card")
              and all(any(c is sp for c in _walk(panel._run_body))
                      for sp in panel.policy_spins.values()),
              f"{sorted(panel.policy_spins)}、卡={'在' if hasattr(G.Panel, '_build_policy_card') else '没了'}")
        # 「余量够大就多显示几局」（m05026 第一句 + m05745 第一句）：一张「最近」卡里预建
        # `RECENT_POOL` 行，放几行由 `_sync_last_cards` 拿四个**实测**高度常数（`CHROME_H`/
        # `RUN_NATURAL_H`/`RECENT_CHROME_H`/`RECENT_ROW_H`）跟当前页高算出来 —— 放不下还硬放，
        # `expand` 的运行卡会被挤到内容以下、最后两行按钮被**裁掉**（不是挤小）。
        # 默认窗 800 高（页高 762.67）= **正好一条**：762.67 − 128 − 448 − 8 − 64 = 114.67，
        # 114.67 // 72 = 1 ⇒ 放一行、卡片还在。两个来源叠在一起：① m08726 把桌面密度改回官方
        # 标准档，四个数框从 48 长到官方 56，运行卡内容长高 28.4 ⇒ `RUN_NATURAL_H` 376 → 448；
        # ② m09165 用户把默认窗从 1180×780 改成 1280×800（16:9）。要两条得拉到 830 以上
        # （页高 792.67 ⇒ room 144.67），矮回 720 那档就一条都放不下（room 34.67 ⇒ 整卡不显示）。
        # 这条同时钉住「条数是算出来的、不是写死的显隐」：拉高窗口就多放（下面那一关）。
        check("PART 10", "「最近演出」卡的条数由实测常数算出（默认窗正好 1 条，不是写死的显隐）",
              G.CHROME_H > 100 and G.RUN_NATURAL_H > 400
              and G.RECENT_CHROME_H > 40 and G.RECENT_ROW_H > 40
              and panel.recent.card.visible is True and panel.recent.shown == 1
              and [r["box"].visible for r in panel.recent.rows]
              == [True, False, False, False, False, False],
              f"room={(panel.page.height or 0) - G.CHROME_H - G.RUN_NATURAL_H - T.SPACE['sm'] - G.RECENT_CHROME_H} "
              f"page.h={panel.page.height} shown={panel.recent.shown}")
        # 不是写死的条数：窗口一变 `_apply_window_class` 就重判。拉高立刻多出几条记录，
        # 缩回默认高它自己收回去（这两下都在这一关里走一遍真路径）。
        # 2026-10-05：这里原来只 `sleep(0.6)` 就去读条数，而条数是平台把新尺寸送到客户端、
        # 面板自己的 resize 处理器重算的 —— 机器上有重活（用户的面板 + 正在跑的一局）时 0.6 s
        # 到不了，`shown` 还是旧值，报出来的两处页高**一模一样**（`900 高 shown=2；默认
        # (1180, 780) shown=2`）⇒ 假 FAIL。改成轮询到页高真的变了，最多等 5 s；等不到就按
        # 实际值判（那才是 bug）。窗口高 → 客户端区高差 **37.33**（800 → 762.67，实测）。
        async def _resize(w, h):
            page.window.width, page.window.height = (w, h)
            page.update()
            want = h - 37.33
            for _ in range(50):
                await asyncio.sleep(0.1)
                if abs((panel.page.height or 0) - want) <= 3:
                    break
            panel._apply_window_class(w)
            await asyncio.sleep(0.15)
            return panel.page.height

        h_tall = await _resize(1180, 900)
        tall_n = panel.recent.shown
        h_default = await _resize(*T.WINDOW_DEFAULT)
        check("PART 10", "窗口拉高「最近演出」卡自己多放几条、缩回默认高自己收回去",
              tall_n >= 2 and tall_n > panel.recent.shown and panel.recent.shown == 1,
              f"900 高 page.h={h_tall} shown={tall_n}；"
              f"默认 {T.WINDOW_DEFAULT} page.h={h_default} shown={panel.recent.shown}")

        def _card_runs(path):
            """每一行采样：找**卡片色**（`tk.card`）的横段，以及「左右都紧挨着卡片色」的底色留白。

            为什么不再按页面底色数段：导航轨、顶栏、页脚现在与页面底是**同一个**角色（`surface`
            —— 规范如此），导轨上的图标会把「导轨那一带」切成好几段底色，段序全乱（第一版量出
            `[72]`/`[74]` 这种假留白，把已经叠成一栏的窄窗口读成两栏）。改成问两件事就干净了：
            ① 这一行有几段**卡片**？② 两段之间那条底色留白在哪个 x？后者再要求「留白左右紧挨着
            的都是卡片色」（跳过 2 px 抗锯齿），导轨与页边距自然被排除 —— 它们有一侧是页面内边距。

            返回 `(宽, 每行的 (卡片段列表, 真留白列表))`。容差仍然只给 2：浅色主题里卡片是
            `#f4f2fa`、页面是 `#faf8ff`，每通道只差 5~6，放到 6 就会把卡片本身当成底色。
            """
            im = Image.open(path).convert("RGB")
            w, h = im.size
            raw = im.tobytes()
            cc = tuple(int(panel.tk.card[i:i + 2], 16) for i in (1, 3, 5))
            bc = tuple(int(panel.tk.page[i:i + 2], 16) for i in (1, 3, 5))

            def _near(o, c):
                return (abs(raw[o] - c[0]) <= 2 and abs(raw[o + 1] - c[1]) <= 2
                        and abs(raw[o + 2] - c[2]) <= 2)

            rows = []
            for frac in (0.25, 0.35, 0.45, 0.55, 0.65):
                y = int(h * frac)
                kind = []
                for x in range(w):
                    o = (y * w + x) * 3
                    kind.append("c" if _near(o, cc) else ("b" if _near(o, bc) else "x"))
                cards, s = [], None
                for x in range(w):
                    if kind[x] == "c":
                        if s is None:
                            s = x
                    else:
                        if s is not None and x - s >= 6:
                            cards.append((s, x - 1))
                        s = None
                if s is not None and w - s >= 6:
                    cards.append((s, w - 1))
                gaps, s = [], None
                for x in range(w):
                    if kind[x] == "b":
                        if s is None:
                            s = x
                    else:
                        if s is not None:
                            if (x - s >= 8 and s - 3 >= 0 and x + 2 < w
                                    and kind[s - 3] == "c" and kind[x + 2] == "c"):
                                gaps.append((s, x - 1))
                            s = None
                rows.append((cards, gaps))
            return w, rows

        def _card_bottom(path, x0, x1, floor=200):
            """给定 x 带里**第一段**卡片色（`tk.card`）的下沿 y（带内每行至少 floor 个采样点）。

            只看第一段：设置页上面那两张卡之下还压着整行的「种类偏移」卡，从底往上找会一路
            找到那张卡的下沿，两张卡就「永远等高」了 —— 那不是判据，那是巧合。
            2026-10-10 用户 m15291「横平竖直贴边对齐」：上面那两张卡从前是一高一低
            （实拍 564 与 468 px，差 96），现在钉同一个实测高度 ⇒ 下沿必须落在同一条线上。
            """
            im = Image.open(path).convert("RGB")
            w, h = im.size
            raw = im.tobytes()
            cc = tuple(int(panel.tk.card[i:i + 2], 16) for i in (1, 3, 5))

            def _near(o):
                return (abs(raw[o] - cc[0]) <= 2 and abs(raw[o + 1] - cc[1]) <= 2
                        and abs(raw[o + 2] - cc[2]) <= 2)

            started, last = False, None
            for y in range(h):
                base = y * w
                n = 0
                for x in range(x0, x1, 2):
                    if _near((base + x) * 3):
                        n += 2
                if n >= floor:
                    started, last = True, y
                elif started:
                    break          # 卡片之间那道底色缝
            return last

        # 拍之前必须确认窗口**真的**变了：只睡固定 1.3 s 在忙的时候会拍到上一档的帧
        # （全拆十二条牙那轮就是这样：六张图全是 1560 的宽度，PART 10 六条判据一起亮，
        #  而这一关量的是栅格、与行底色毫无关系 —— 一次假耦合）。判据是「换了一档宽度、
        #  拍出来却和上一张一样宽」就重试，最多四拍。
        prev_shot = {"w": None, "arg": None}

        async def _shot(w, h, tab, tag, settle=1.3):
            png, im = None, None
            for attempt in range(4):
                page.window.width, page.window.height = w, h
                page.update()
                panel._apply_window_class(w)
                panel.show_tab(tab)
                await asyncio.sleep(settle if attempt == 0 else 0.7)
                png = await page.take_screenshot()
                im = Image.open(io.BytesIO(png))
                stuck = (prev_shot["w"] is not None and prev_shot["arg"] != w
                         and abs(im.size[0] - prev_shot["w"]) <= 4)
                if not stuck:
                    break
            prev_shot["w"], prev_shot["arg"] = im.size[0], w
            path = os.path.join(fixture, f"flex_{tag}.png")
            with io.open(path, "wb") as f:
                f.write(png)
            return path

        # 页签下标：0 单人演出 / 1 多人演出 / 2 日志 / 3 结算记录 / 4 设置（2026-10-08 用户 m02832
        # 在「开始」下面插了「多人演出」，后三页整体后移一位）。
        # 命名沿用 `s*` = **设置**页（tab 4）、`t*` = 单人演出页（tab 0）。
        s1280 = await _shot(1280, 860, 4, "set1280")
        s1560 = await _shot(1560, 900, 4, "set1560")
        s760 = await _shot(760, 560, 4, "set760")
        t1280 = await _shot(1280, 860, 0, "start1280")
        t1560 = await _shot(1560, 900, 0, "start1560")
        # 多人页那一张要**在 760 那两张之前**拍：`_shot` 会把窗口停在自己那一档，而下面
        # 1729 起那一串「窄窗换挡」判据读的是**当前**窗口（最后一张必须是 760）。
        mu1280 = await _shot(1280, 860, G.TAB_MULTI, "multi1280")
        t760 = await _shot(760, 560, 0, "start760")

        # 换挡本身（760 这一档，`_shot` 刚把窗口摆到这里）：`col` 写成整行、四个 `expand`
        # 全撤、整页才允许滚。三件必须一起发生 —— 少了前两件，一屏装不下的两栏带着 `expand`
        # 会直接抛成一张 ErrorWidget 红屏（第二轮冒烟那张就是这么来的）。
        check("PART 10", "窄窗换挡：两栏写成整行 + 撤掉所有 expand + 整页可滚",
              getattr(panel, "_stacked", None) is True
              and _cols(panel._start_cols) == [{"xs": 12}, {"xs": 12}]
              and panel._start_cols.expand is False and panel._left_col.expand is False
              and panel.run_card.expand is False
              and str(panel.pages[0].scroll).endswith("AUTO"),
              f"stacked={getattr(panel, '_stacked', None)} cols={_cols(panel._start_cols)} "
              f"exp={panel._start_cols.expand}/{panel._left_col.expand}/{panel.run_card.expand} "
              f"scroll={panel.pages[0].scroll}")
        # 多人演出页那两栏同一套换挡（2026-10-08 用户 m02832 新加的页）：它的基础 `col` 带 `md`
        # 断点，窗口下限 800 已经越过 768 ⇒ 不在这里换挡的话窄窗会停在 6/12 缩成一条窄栏。
        check("PART 10", "窄窗换挡（多人演出页）：两栏都写成整行 + expand 撤掉 + 整页可滚",
              _cols(panel._multi_cols) == [{"xs": 12}, {"xs": 12}]
              and panel._multi_cols.expand is False and panel._multi_left.expand is False
              and panel.m_run_card.expand is False and not panel.m_recent.card.expand
              and not getattr(panel.m_recent.card, "content", None).expand
              and str(panel.pages[G.TAB_MULTI].scroll).endswith("AUTO"),
              f"cols={_cols(panel._multi_cols)} exp={panel._multi_cols.expand}/"
              f"{panel._multi_left.expand}/{panel.m_run_card.expand}/{panel.m_recent.card.expand}/"
              f"{getattr(panel.m_recent.card, 'content', None).expand} "
              f"scroll={panel.pages[G.TAB_MULTI].scroll}")
        # 多人页左栏现在是**同一张**「最近演出」卡（`mode="multi"`），旧「激奏演出」说明卡已删（m10950）。
        # 卡片标题读的是页面上真画出来的字：`ft.Card` 自己没有 `title` 字段（`card()` 把标题建成
        # 内容 Column 里第一行 `ft.Row` 的最后一个 `ft.Text`），所以按那条结构取。
        def _title_of(ctrl):
            col = getattr(getattr(ctrl, "content", None), "content", None)
            row = (getattr(col, "controls", None) or [None])[0]
            cell = (getattr(row, "controls", None) or [None])[-1]
            return getattr(cell, "value", None)

        check("PART 10", "多人演出页左栏就是那张多人「最近演出」卡（说明卡已删）",
              len(panel._multi_left.controls) == 1
              and panel._multi_left.controls[0] is panel.m_recent.card
              and panel.m_recent.mode == "multi"
              and _title_of(panel.m_recent.card) == "最近演出"
              and _title_of(panel.recent.card) == "最近演出"
              and not hasattr(panel, "m_note_card")
              and not hasattr(panel, "_build_multi_note"),
              f"左栏 {[type(c).__name__ for c in panel._multi_left.controls]} "
              f"mode={panel.m_recent.mode!r} 标题={_title_of(panel.m_recent.card)!r}"
              f"/{_title_of(panel.recent.card)!r}")
        check("PART 10", "叠成一栏时整张「最近演出」卡都不放（这一栏自己就不够高）",
              panel.recent.card.visible is False and panel.recent.shown == 0,
              f"visible={panel.recent.card.visible} shown={panel.recent.shown} "
              f"stacked={getattr(panel, '_stacked', None)}")

        w1, k1 = _card_runs(t1280)          # k* = 开始页每行（卡片段, 真留白）
        w2, k2 = _card_runs(t1560)
        w3, k3 = _card_runs(t760)
        v1 = _card_runs(s1280)[1]           # v* = 设置页每行（卡片段, 真留白）
        v2 = _card_runs(s1560)[1]
        v3 = _card_runs(s760)[1]

        # 开始页：那一行里有**两段卡片**、中间夹着一条真留白 ⇒ 两栏并排；留白的 x 就是分栏线。
        s1 = [g[0][0] for _c, g in k1 if len(g) == 1]
        s2 = [g[0][0] for _c, g in k2 if len(g) == 1]
        # 内容区那把尺子：开始页两栏正好铺满内容区，所以「最左那张卡的左边缘」「最右那张卡的右边缘」
        # 就是内容区的左右边界（页面内边距以内的那一块）。设置页只有一张卡，拿它跟这把尺子比。
        def _pane(rows):
            cs = [c for c, _g in rows if c]
            if not cs:
                return None
            return min(c[0][0] for c in cs), max(c[-1][1] for c in cs)

        def _card(rows):
            cs = [c for c, _g in rows if c]
            if not cs:
                return None
            return min(c[0][0] for c in cs), max(c[-1][1] for c in cs)

        p1, p2, p3 = _pane(k1), _pane(k2), _pane(k3)
        q1, q2, q3 = _card(v1), _card(v2), _card(v3)

        # 设置页（2026-10-10 用户 m13525 改成左右布局）：每行**两段卡**（左「面板」右「资源」），
        # 中间夹一条真留白。卡片段会被行内文字切断（文字不是卡片色也不是页面底色），所以两段卡的
        # 边缘要按「留白左侧最左/最右、留白右侧最左/最右」取，不能要求一段一行。
        def _split(rows):
            """每行恰好一条真留白时，返回 (左卡宽, 右卡宽, 留白宽)。"""
            out = []
            for cards, gaps in rows:
                if len(gaps) != 1 or not cards:
                    continue
                g0, g1 = gaps[0]
                left = [c for c in cards if c[1] < g0]
                right = [c for c in cards if c[0] > g1]
                if not left or not right:
                    continue
                out.append((max(c[1] for c in left) - min(c[0] for c in left),
                            max(c[1] for c in right) - min(c[0] for c in right),
                            g1 - g0))
            return out

        t1, t2, t3 = _split(v1), _split(v2), _split(v3)
        v1g = [g[0][0] for _c, g in v1 if len(g) == 1]
        v2g = [g[0][0] for _c, g in v2 if len(g) == 1]
        # 叠成一栏那一档：卡**右边缘**到窗口右缘的留白（写死宽度的卡不会跟着窗口变）。
        m3 = [w3 - 1 - c[-1][1] for c, _g in v3 if c]

        check("PART 10", "窗口真的变了（否则下面这些图在量同一个尺寸）",
              w2 > w1 + 200 and w3 < w1, f"1280→{w1}px 1560→{w2}px 760→{w3}px")
        # 行数门槛取 2 而不是 3：1560 下左卡会矮一截（`font_hint` 在宽窗里折行更少），
        # 采样带里能同时看到两张卡的行就只有 2 条。判据要的是「有行是两段卡」，不是行数。
        check("PART 10", "设置页左右并排：1280/1560 下每一行都是两段卡 + 中间一条真留白",
              len(t1) >= 2 and len(t2) >= 2,
              f"1280 两段卡的行 {len(t1)}/{len(v1)}：{t1[:2]}；1560 {len(t2)}/{len(v2)}")
        check("PART 10", "设置页两栏等宽（各半栏，中间只留一条列间距）",
              bool(t1) and bool(t2) and all(abs(l - r) <= 8 for l, r, _g in t1 + t2)
              and all(6 <= g <= 20 for _l, _r, g in t1 + t2),
              f"1280 {t1[:2]}；1560 {t2[:2]}")
        check("PART 10", "设置页两段卡合起来铺满内容区（左右只留页面内边距，不是写死的宽度）",
              p1 is not None and q1 is not None and p2 is not None and q2 is not None
              and abs(q1[0] - p1[0]) <= 8 and abs(p1[1] - q1[1]) <= 8
              and abs(q2[0] - p2[0]) <= 8 and abs(p2[1] - q2[1]) <= 8,
              f"1280 卡 {q1} 内容区 {p1}；1560 卡 {q2} 内容区 {p2}")
        check("PART 10", "设置页分栏留白跟着窗口右移（卡宽由栅格算，不是写死的宽度）",
              bool(v1g) and bool(v2g) and min(v2g) >= max(v1g) + 100,
              f"{v1g} -> {v2g}")
        check("PART 10", "窄窗口（760）设置页两栏叠成一栏：中间那条留白没了",
              not t3 and not any(g for _c, g in v3),
              f"760 每行（卡片段, 真留白）全量 {v3}")
        check("PART 10", "窄窗口（760）设置页的卡撑满整行（右边只剩页面内边距）",
              bool(m3) and max(m3) <= 60, f"760 右边距 {m3}")

        def _bands(rows, pane):
            """从某一行的「两段卡 + 一条真留白」里取出左右两带（避开卡的圆角与那条缝）。"""
            for _c, g in rows:
                if len(g) == 1 and pane is not None:
                    g0, g1 = g[0]
                    return ((pane[0] + 20, g0 - 10), (g1 + 10, pane[1] - 20))
            return None

        q1b, q2b = _bands(v1, p1), _bands(v2, p2)
        bot1 = (_card_bottom(s1280, *q1b[0]), _card_bottom(s1280, *q1b[1])) if q1b else (None, None)
        bot2 = (_card_bottom(s1560, *q2b[0]), _card_bottom(s1560, *q2b[1])) if q2b else (None, None)
        check("PART 10", "设置页上面两张卡等高（下沿落在同一条线上，用户 m15291「横平竖直」）",
              all(b is not None for b in bot1 + bot2)
              and abs(bot1[0] - bot1[1]) <= 4 and abs(bot2[0] - bot2[1]) <= 4,
              f"1280 两张卡下沿 {bot1}；1560 {bot2}")
        check("PART 10", "开始页在 1280/1560 下两栏并排（两段卡片之间夹着一条真留白）",
              bool(s1) and bool(s2),
              f"并排行数 {len(s1)} / {len(s2)}；留白列 {s1} / {s2}")
        check("PART 10", "开始页分栏留白跟着窗口右移",
              bool(s1) and bool(s2) and min(s2) >= max(s1) + 100,
              f"{s1} -> {s2}")
        check("PART 10", "窄窗口（760）开始页两栏叠成一栏：中间那条留白没了",
              not any(g for _c, g in k3),
              f"每行（卡片段, 真留白）全量 {k3}")
        # 先把窗口放回 1560 再问导轨形态：`_shot` 里最后一张是 760 的那张，直接读会读到
        # 760 的结果（第一版就栽在这 —— 「1560 宽度下 extended=False」）。
        page.window.width, page.window.height = (1560, 900)
        page.update()
        panel._apply_window_class(1560)
        await asyncio.sleep(0.8)
        check("PART 10", "宽窗（1560）下导轨仍然收起：extended 恒 False、标签压在图标下",
              panel._rail.extended is False
              and panel._rail.label_type == ft.NavigationRailLabelType.ALL,
              f"1560 宽度下 extended={panel._rail.extended} label_type={panel._rail.label_type}")
        # 宽窗那一档要**换回来**：`col` 各半、几个 `expand` 回来、整页不滚。只测「760 叠了」
        # 不测「1560 并排」的话，一个「永远叠成一栏」的实现也能全绿。
        check("PART 10", "宽窗换挡：两栏各半 + expand 回来 + 整页不滚",
              getattr(panel, "_stacked", None) is False
              and _cols(panel._start_cols) == [{"xs": 6}, {"xs": 6}]
              and panel._start_cols.expand is True and panel.run_card.expand is True
              and panel.pages[0].scroll is None,
              f"stacked={getattr(panel, '_stacked', None)} cols={_cols(panel._start_cols)} "
              f"exp={panel._start_cols.expand}/{panel.run_card.expand} "
              f"scroll={panel.pages[0].scroll}")
        # 多人页左栏那张「最近演出」卡现在**自己撑满那一栏**（用户 m13783：默认高度下左卡底下空着
        # 70.8 逻辑 px，而右栏运行卡本来就撑满 —— 一栏高 643.2、左卡只有 572.4）。撑满这件事有两层：
        # 卡自己 `expand`（下面这条），以及 `card()` 里那层 `ft.Container` 也得 `expand`（否则内容
        # 还是从顶上排、卡底留白照旧）。列表同时改成 `scroll_when_needed()`（滚动条按需露面 ——
        # 2026-10-10 用户 m14308 报过 `ScrollMode.ADAPTIVE` 在桌面上拇指恒显）并把**全部**记录都摆进去
        # （`show = min(have, pool)`）—— 只按余量摆 7 条的话，第 8 条起永远滚不到。
        check("PART 10", "宽窗换挡（多人演出页）：两栏等宽 6/12 + expand 回来 + 整页不滚",
              _cols(panel._multi_cols) == [{"xs": 12, "md": 6}, {"xs": 12, "md": 6}]
              and panel._multi_cols.expand is True and panel._multi_left.expand is True
              and panel.m_run_card.expand is True and panel.m_recent.card.expand is True
              and getattr(panel.m_recent.card, "content", None).expand is True
              and panel.pages[G.TAB_MULTI].scroll is None,
              f"cols={_cols(panel._multi_cols)} exp={panel._multi_cols.expand}/"
              f"{panel.m_run_card.expand}/{panel.m_recent.card.expand}/"
              f"{getattr(panel.m_recent.card, 'content', None).expand} "
              f"scroll={panel.pages[G.TAB_MULTI].scroll}")
        # 用户看到的是**像素**：默认高度下左卡底边比右卡矮一大截。上面那串控件层判据能挡住
        # 「没撑」，但挡不住「撑了却因为 `tight=True` 之类还是从顶上排」—— 这一条直接量底边。
        # 两道 x 带都取在卡片本体里（左卡 ≈ 0.08..0.53、右卡 ≈ 0.55..0.99 个屏宽），逐列从
        # 下往上找第一个**卡片色**像素，两边的底边差不许超过 4 物理 px（≈2.7 逻辑）。
        def _card_bottoms(path, bands):
            im = Image.open(path).convert("RGB")
            w, h = im.size
            raw = im.tobytes()
            cc = tuple(int(panel.tk.card[i:i + 2], 16) for i in (1, 3, 5))
            out = []
            for x0f, x1f in bands:
                last = -1
                for y in range(h - 1, -1, -1):
                    for x in range(int(w * x0f), int(w * x1f), 3):
                        o = (y * w + x) * 3
                        if (abs(raw[o] - cc[0]) <= 2 and abs(raw[o + 1] - cc[1]) <= 2
                                and abs(raw[o + 2] - cc[2]) <= 2):
                            last = y
                            break
                    if last >= 0:
                        break
                out.append(last)
            return out

        bot_l, bot_r = _card_bottoms(mu1280, ((0.10, 0.45), (0.55, 0.95)))
        check("PART 10", "多人页左卡与右卡底边齐平（左卡撑满那一栏，底下不再空一块）",
              bot_l > 0 and bot_r > 0 and abs(bot_l - bot_r) <= 4,
              f"左卡底 {bot_l} px、右卡底 {bot_r} px（差 {abs(bot_l - bot_r)}，容差 4）"
              f" —— 修前是 968 vs 1073")
        # 用户 m12311 第二问「多人演出左右两边的宽度有什么依据」当时答的是「5/12 + 7/12 承重」：
        # 多人运行卡第三行中间那枚「断连重试」要「开关 52 + 空档 4 + 数框 96 = 152」，而并排**最窄**
        # 的那一档（`G.STACK_W` = 992）7/12 一格只有 ≈151（差的那 1 px 吃掉 12 的列间距）、6/6 只有 ≈127。
        # 2026-10-10（用户 m12749）那枚瓦片拆掉了（房间局不能中途重开）⇒ 最宽的一枚退成数框 96
        # （`G.TILE_MIN_W`），**算术不再逼着选 5/7**；同一天用户 m13525 定「多人模式面板改两栏等宽」。
        # 这条钉两件事：① 最窄并排档每格都放得下最宽的那枚控件；② 两栏等宽 6/12（改分法要连这条
        # 判据一起改，牙 `multi66` 咬这里）。
        # 算式：内容区 = 页宽 − `G.MULTI_CHROME_W`（导轨 80 + 左右页边距各 16），
        # 列宽 = (内容区 − 列间距) × 份数/12，瓦片宽 = (列宽 − 卡片内边距 2×16 − 行内间距 12) / 2
        # —— 最宽那枚控件（数框 96）住在每行两枚的那两行里。
        def _tile_share(col_md, page_w):
            col = (page_w - G.MULTI_CHROME_W - T.SPACE["sm"]) * col_md / 12.0
            return (col - 2 * T.SPACE["lg"] - T.SPACE["md"]) / 2.0

        tile_6 = _tile_share(6, G.STACK_W)
        check("PART 10", "多人页两栏等宽 6/12：并排最窄那档（992）两格都放得下最宽的一枚控件"
                         "（数框 96）",
              _cols(panel._multi_cols) == [{"xs": 12, "md": 6}, {"xs": 12, "md": 6}]
              and tile_6 >= G.TILE_MIN_W,
              f"992 处一格：6/12 {tile_6:.1f}，最宽一枚要 {G.TILE_MIN_W} "
              f"（MULTI_CHROME_W={G.MULTI_CHROME_W}）")
        page.window.width, page.window.height = (760, 560)
        page.update()
        panel._apply_window_class(760)
        await asyncio.sleep(0.8)
        check("PART 10", "窄窗口（760）下同样是收起轨（与宽窗那一档一个形态）",
              panel._rail.extended is False
              and panel._rail.label_type == ft.NavigationRailLabelType.ALL,
              f"extended={panel._rail.extended} label_type={panel._rail.label_type}")
        page.window.width, page.window.height = T.WINDOW_DEFAULT
        page.update()
        panel._apply_window_class(T.WINDOW_DEFAULT[0])
        await asyncio.sleep(0.5)


    # ---- PART 11 选曲列表：界面写原文、进度在行尾、筛选器跟着窗口走
    if _want("PART 11"):
        #
        # 用户那句「优化选曲面板，太乱了，特别是这些歌怎么全是英文名」就是这一关要钉的：列表
        # 标题从前取的是**排序字段** `song_name()`（`titleRomaji`，拉丁转写），而同一张卡底下的
        # 信息行写的是 `title`（原文）—— 同一首歌上下两个名字，整列看着像英文。这一关把「界面
        # 语言」与「排序/搜索口径」钉成两件事，顺带盯住 AP 进度不再挤在标题里、筛选器不再写死
        # 140、「显示 N / M 首」的数字与筛出来的实数对得上。（`ft` 是上面 PART 10 里 import 的。）
        #
        # 后半段是**像素层**：用户还要求「上下左右要对齐、元素分布要均匀、善用居中」—— 控件层
        # 只能证明「段数 / 单选 / `style` 留空 / 高取 `T.SEGMENT_H`」，证明不了渲染出来真的等宽、
        # 也证明不了整组的外边缘落在卡片内容边界上（Column 默认 `CrossAxisAlignment.START`
        # 只给孩子松约束，搜索框当初就比列表容器窄 88 px，正是「没对齐」的来源）。所以在默认窗口
        # 上再量一遍：三条内部隔线等距、只有选中那一段是实心块、整组左右外沿与卡片内容边界
        # （搜索框/列表容器那两条竖线）重合。
        body = panel._pick_body
        check("PART 11", "选曲卡里第一条就是搜索框",
              body is not None and bool(body.controls) and body.controls[0] is panel.search,
              f"{[type(c).__name__ for c in (body.controls if body is not None else [])]}")
        check("PART 11", "两个筛选下拉跟着窗口走（不再写死 140）",
              panel.cat_box.expand is True and panel.sort_box.expand is True
              and panel.cat_box.width is None and panel.sort_box.width is None,
              f"expand={panel.cat_box.expand}/{panel.sort_box.expand} "
              f"width={panel.cat_box.width}/{panel.sort_box.width}")

        rows = panel.song_list.controls
        by_mid = {str(s.get("musicId")): s for s in panel.songs}
        check("PART 11", "列表每行都对得上清单里的歌",
              len(rows) == 3 and all(str(r.data) in by_mid for r in rows),
              f"{[r.data for r in rows]}")

        def _tail_of(row):
            """行尾的 AP 徽标是 `Container(Text)`，没全 AP 时是裸 `Text` —— 两种都要取到字。"""
            ctl = row.trailing
            if ctl is None:
                return ""
            if isinstance(ctl, ft.Text):
                return str(ctl.value)
            return str(getattr(ctl.content, "value", ""))

        def _sub_of(row):
            return str(row.subtitle.value) if row.subtitle is not None else ""

        titles = [str(r.title.value) for r in rows]
        want_titles = [core.song_label(by_mid[str(r.data)]) for r in rows]
        check("PART 11", "行标题是原文歌名（不是罗马音）",
              titles == want_titles
              and all(any("\u4e00" <= ch <= "\u9fff" for ch in t) for t in titles),
              f"{titles}；排序字段那份是 {[core.song_name(by_mid[str(r.data)]) for r in rows]}")

        want_subs = []
        for r in rows:
            s = by_mid[str(r.data)]
            want_subs.append(" · ".join(x for x in (core.song_romaji(s),
                                                    str(s.get("bandZh") or s.get("band") or "")) if x))
        check("PART 11", "副行写「罗马音 · 乐队」",
              [_sub_of(r) for r in rows] == want_subs,
              f"{[_sub_of(r) for r in rows]} vs {want_subs}")

        want_tails = []
        for r in rows:
            s = by_mid[str(r.data)]
            n_ap, n_all = core.song_ap(s, panel.ap)
            want_tails.append(f"AP {n_ap}/{n_all}" if core.song_all_ap(s, panel.ap)
                              else f"{n_ap}/{n_all}")
        check("PART 11", "AP 进度在行尾、标题里没有",
              [_tail_of(r) for r in rows] == want_tails
              and all("🌟" not in t for t in titles)
              and all(str(getattr(r.trailing, "tooltip", "")) for r in rows),
              f"{[_tail_of(r) for r in rows]} vs {want_tails}")

        charts = sum(core.song_ap(s, panel.ap)[1] for s in panel.songs)
        ap_songs = sum(1 for s in panel.songs if core.song_all_ap(s, panel.ap))
        want_count = (f"显示 {len(rows)} / {len(panel.manifest.get('songs') or [])} 首"
                      f" · {charts} 张谱 · 已 AP {ap_songs} 首")
        check("PART 11", "计数行说的是筛出来的实数",
              panel.count_text.value == want_count,
              f"{panel.count_text.value!r} vs {want_count!r}")

        def _before(ctl):
            """`body.controls` 里排在 `ctl` 前面那一个（`Container` 就取它的内容）。

            用 `is` 逐个比，不用 `list.index` —— Flet 控件是 dataclass 式的对象，`==` 可能
            把两个字段相同的控件认成同一个，`index` 会指到别人身上。
            """
            prev = None
            for c in body.controls:
                if c is ctl:
                    return prev.content if isinstance(prev, ft.Container) else prev
                prev = c
            return None

        check("PART 11", "「难度」标签居中、自己一行压在分段控件上方",
              isinstance(panel.diff_label, ft.Text)
              and panel.diff_label.text_align == ft.TextAlign.CENTER
              and _before(panel.diff_hit) is panel.diff_label,
              f"{type(panel.diff_label).__name__} align={getattr(panel.diff_label, 'text_align', None)} "
              f"上一格={type(_before(panel.diff_hit)).__name__}")

        cnt = body.controls[2] if len(body.controls) > 2 else None
        check("PART 11", "计数行居中",
              isinstance(cnt, ft.Container) and cnt.content is panel.count_text
              and cnt.alignment == ft.Alignment.CENTER
              and panel.count_text.text_align == ft.TextAlign.CENTER,
              f"{type(cnt).__name__} align={getattr(cnt, 'alignment', None)}")

        # 难度：官方 M3 分段控件（一行四段、等宽、两端胶囊、1 px outline 描边、选中铺
        # `secondary_container`）。用户 m19421 的原话是「都可以，完全按照官方的来」：
        # 形状 / 描边 / 段间距全由 Flutter 的 `SegmentedButton` 默认画（`segmented_button.dart`
        # `:1273-1281 _SegmentedButtonDefaultsM3`：shape=StadiumBorder、side=outline、高 40、
        # 图标 18），颜色与字阶由主题 `T.segmented_button_theme` 给 ⇒ 控件自己的 `style` 必须留空，
        # 给了就把默认那套形状盖掉了。用户 m20246 又定：**不画选中对勾**（默认画，会把选中段的
        # 文字右推 11.1 dp、把长式标签挤成省略号）—— 撤掉勾之后段内可用宽 ≈112.7 dp 装得下
        # ≈90 dp 的 `EXPERT Lv26`，所以段上写**长式**；可点高 48 由外面的 `self.diff_hit` 壳给
        # （可视仍是 40，见下面两条）。
        segs = list(panel.diff_seg.segments)
        want_vals = [core.chart_id(d) for d in panel.diffs]
        want_lbls = [f"{(d.get('name') or '?').upper()} Lv{core.lv(d)}" for d in panel.diffs]
        check("PART 11", "难度是一行四段的官方分段控件（段数=难度数、单选、样式交给主题）",
              isinstance(panel.diff_seg, ft.SegmentedButton) and len(segs) == 4
              and panel.diff_seg.allow_multiple_selection is False
              and panel.diff_seg.allow_empty_selection is True
              and panel.diff_seg.show_selected_icon is False
              and panel.diff_seg.style is None,
              f"{type(panel.diff_seg).__name__} 段={len(segs)} "
              f"多选={getattr(panel.diff_seg, 'allow_multiple_selection', None)} "
              f"空选={getattr(panel.diff_seg, 'allow_empty_selection', None)} "
              f"对勾={getattr(panel.diff_seg, 'show_selected_icon', None)} "
              f"style={panel.diff_seg.style}")
        check("PART 11", "四段按清单顺序各对一个难度（value 是曲目 id）",
              [str(s.value) for s in segs] == want_vals,
              f"{[str(s.value) for s in segs]} vs {want_vals}")
        check("PART 11", "段上写长式「名字 Lv等级」（撤掉对勾后段内装得下，不再缩）",
              [str(s.label.value) for s in segs] == want_lbls
              and all("Lv" in str(s.label.value) for s in segs),
              f"{[str(s.label.value) for s in segs]} vs {want_lbls}")
        # 可点 48 的隐形带（用户 m20246 定的 A 案）：分段控件上下各一排 4 px 的带，格数 = 难度数、
        # 点第 k 格就是第 k 个难度。`diff_hit` 是选曲卡里**常驻**的壳（只换 `content`），所以
        # 选曲卡 Column 的孩子顺序不变、`_before()` 那套还成立。
        hit_col = panel.diff_hit.content if isinstance(panel.diff_hit, ft.Container) else None
        hit_rows = ([hit_col.controls[0], hit_col.controls[2]]
                    if isinstance(hit_col, ft.Column) and len(hit_col.controls) == 3 else [])
        check("PART 11", "难度那一条的外壳 = 一排隐形带 + 分段控件 + 一排隐形带（可视 40、可点 48）",
              isinstance(panel.diff_hit, ft.Container) and isinstance(hit_col, ft.Column)
              and hit_col.spacing == 0 and hit_col.tight is True
              and len(hit_rows) == 2
              and all(isinstance(r, ft.Row) and r.spacing == 0
                      and all(isinstance(c, ft.Container) and c.expand is True
                              and c.height == G.HIT_PAD and c.bgcolor is None
                              for c in getattr(r, "controls", []))
                      for r in hit_rows)
              and hit_col.controls[1] is panel.diff_seg
              and G.HIT_PAD * 2 + T.SEGMENT_H == T.HIT_MIN,
              f"{type(panel.diff_hit).__name__}/{type(hit_col).__name__} "
              f"带高={[c.height for r in hit_rows for c in getattr(r, 'controls', [])]} "
              f"HIT_PAD={G.HIT_PAD} SEGMENT_H={T.SEGMENT_H} HIT_MIN={T.HIT_MIN}")
        # 接线（不是真点，真点会写存档）：把 `select_diff` 换成只记下标的替身，逐格按一遍。
        _real_sel = panel.select_diff
        _picked = []
        panel.select_diff = lambda i: _picked.append(i)
        try:
            for r in hit_rows:
                for c in getattr(r, "controls", []):
                    if getattr(c, "on_click", None) is not None:
                        c.on_click(None)
        finally:
            panel.select_diff = _real_sel
        check("PART 11", "上下每排的格数=难度数、点第 k 格就是第 k 个难度",
              len(hit_rows) == 2
              and all(len(getattr(r, "controls", [])) == len(panel.diffs) for r in hit_rows)
              and _picked == list(range(len(panel.diffs))) * 2,
              f"格数={[len(getattr(r, 'controls', [])) for r in hit_rows]} "
              f"难度={len(panel.diffs)} 点到的={_picked}")
        check("PART 11", "段悬停里给全名与等级（缩进段里、全名不丢）",
              all("Lv" in str(s.tooltip) and ((d.get("name") or "").upper() in str(s.tooltip))
                  for s, d in zip(segs, panel.diffs)),
              f"{[s.tooltip for s in segs]}")
        _ls = T.type_style("labelLarge")
        check("PART 11", "段高取官方容器高 T.SEGMENT_H、字阶是 labelLarge",
              panel.diff_seg.height == T.SEGMENT_H
              and all(s.label.style.size == _ls.size and s.label.style.weight == _ls.weight
                      for s in segs),
              f"高={panel.diff_seg.height}（常量 {T.SEGMENT_H}）"
              f"字阶={[(s.label.style.size, s.label.style.weight) for s in segs]}")
        check("PART 11", "选中态只落在 selected 上（底色 / 描边全交给主题）",
              all(isinstance(s, ft.Segment) for s in segs)
              and 0 <= panel.diff_idx < len(panel.diffs)
              and panel.diff_seg.selected == [core.chart_id(panel.diffs[panel.diff_idx])],
              f"selected={panel.diff_seg.selected} idx={panel.diff_idx} "
              f"段类型={sorted({type(s).__name__ for s in segs})}")

        # 运行卡：设置区（一块 `field` 底色面板里的三行）在上、动作区（两行按钮）贴卡底 ——
        # 用户 m06250 的三个诉求（选项不够好看 / 开始按钮下面一大块空位 / 「最近」可以宽松些）挤在
        # 同一块高度里，所以这一关从「顶层两行」改成**递归**遍历：新结构把行藏在 面板 → Column →
        # 定高 Container → Row 与 动作区 → Column → Row 里，顶层只剩两个 Column。
        rb = panel._run_body
        nodes = []
        par = {}

        def _walk_all(ctl):
            nodes.append(ctl)
            kids = getattr(ctl, "controls", None)
            if kids is None:
                kids = [getattr(ctl, "content", None)]
            for k in kids or ():
                if k is not None:
                    par[id(k)] = ctl
                    _walk_all(k)

        if rb is not None:
            _walk_all(rb)
        rows_all = [n for n in nodes if isinstance(n, ft.Row)]

        def _sub(node):
            """`node` 子树里的所有控件（含自己）—— 面板那几条判据只数面板里的东西。"""
            out, stack = [], [node]
            while stack:
                c = stack.pop()
                out.append(c)
                kids = getattr(c, "controls", None)
                if kids is None:
                    kids = [getattr(c, "content", None)]
                stack.extend(k for k in (kids or ()) if k is not None)
            return out

        def _inside(ctl, node):
            """`ctl` 是不是在 `node` 里面（含 node 自己）。"""
            cur = ctl
            while cur is not None:
                if cur is node:
                    return True
                cur = par.get(id(cur))
            return False

        def _row_of_cell(ctl):
            """装 `ctl` 的**外层**那一行：孩子全是 `Container(expand=True)`（= 一行 N 个均分格）。"""
            cur = par.get(id(ctl))
            while cur is not None:
                if isinstance(cur, ft.Row):
                    kids = list(cur.controls)
                    if len(kids) >= 2 and all(isinstance(c, ft.Container) and c.expand is True
                                              for c in kids):
                        return cur
                cur = par.get(id(cur))
            return None

        def _cell_of(ctl):
            row = _row_of_cell(ctl)
            if row is None:
                return None
            return next((c for c in row.controls if _inside(ctl, c)), None)

        def _tile_of(ctl):
            """装 `ctl` 的那枚**瓦片**：外层行里那格 `Container(expand=True)`，内容是「标签行 + 控件行」。"""
            cell = _cell_of(ctl)
            col = cell.content if isinstance(cell, ft.Container) else None
            return col if isinstance(col, ft.Column) and len(col.controls) == 2 else None

        def _tile_parts(ctl):
            """一枚瓦片的解剖 → (标签行, 控件行)。"""
            col = _tile_of(ctl)
            if col is None:
                return None, None
            return col.controls[0], col.controls[1]

        def _tile_label(ctl):
            """瓦片标签行里那一条文本（四字全名那条判据要用）。"""
            head, _row = _tile_parts(ctl)
            if not isinstance(head, ft.Row):
                return None
            vals = [k.value for k in head.controls if isinstance(k, ft.Text)]
            return vals[0] if len(vals) == 1 else None

        pairs = ((panel.btn_start, panel.btn_force), (panel.btn_stop, panel.btn_kill))
        same_row = []
        for a, b in pairs:
            ra, rbb = _row_of_cell(a), _row_of_cell(b)
            same_row.append(ra is not None and ra is rbb and len(ra.controls) == 2)
        check("PART 11", "运行卡的两行按钮都是同一行两个半格（对上难度区那两条竖线）",
              rb is not None and all(same_row), f"{same_row}")

        # 四个动作按钮与难度选择器同一套骨架（用户 m06156「把这四个按钮做成难度按钮一样的」）：
        # ① 四个都带图标 —— 从前只有 filled 的主按钮配了 ▶，另三个光秃秃，看着不像一组；
        # ② 每格都是 `fill()`：`Container(expand=True, height=BTN_H)`、而且**不给
        #    alignment** —— 给了 alignment（或退回 `slot()`）Flutter 的 `Align` 会把约束放松
        #    成固有尺寸，四个按钮的宽度又变回 226 / 157 / 98 / 82 px 参差的样子。
        #    （难度选择器 2026-10-07 换成官方分段控件之后，「一样」指的是**等宽等高**这件事：
        #    两族的高度都是 40，但出处不同 —— 这里是 filled-button 的容器高，那边是分段控件的。）
        # ③ 2026-10-07（用户 m20067/m20246）：可视仍 40，但 `fill()` 外面套了 `hit48()` —— 上下
        #    各一条 4 px 的隐形带，可点高凑满规范那 48（`DEVIATIONS` 里那条因此撤掉）。所以这一格
        #    是「带 + 按钮 + 带」三段的 Column，量高度要量**它**，不是外层的 `height`。
        def _hit_h(cell):
            """一格的可点高：`hit48()` 那层壳把「带 + 控件 + 带」叠成一列，取三段高之和。"""
            c = cell.content if isinstance(cell, ft.Container) else None
            if isinstance(c, ft.Column):
                return sum((k.height or 0) for k in c.controls)
            return getattr(cell, "height", None)

        btns = (panel.btn_start, panel.btn_force, panel.btn_stop, panel.btn_kill)
        cells = [_cell_of(b) for b in btns]
        check("PART 11", "四个动作按钮都带图标（从前只有「开始演奏」有 ▶）",
              all(getattr(b, "icon", None) for b in btns)
              and len({str(getattr(b, "icon", None)) for b in btns}) == 4,
              f"{[str(getattr(b, 'icon', None)) for b in btns]}")
        check("PART 11", "四个动作按钮像难度选择器那样等宽等高、撑满各自半格（`fill`、不给 alignment）",
              all(c is not None and c.expand is True and c.alignment is None
                  and _hit_h(c) == T.HIT_MIN for c in cells),
              f"{[(c.expand, c.alignment, _hit_h(c)) for c in cells if c is not None]}")
        # 可点 48 那两条（用户 m20067）：可视仍是 40（`BTN_H`），多出来的 4+4 是两条**隐形**带。
        _band = (lambda c: c.content.controls[0] if isinstance(getattr(c, "content", None), ft.Column)
                 and len(c.content.controls) == 3 else None)
        check("PART 11", "动作区每格是「带 + 按钮 + 带」：可视仍 BTN_H、可点高 48、两条带隐形",
              all(isinstance(getattr(c, "content", None), ft.Column)
                  and [k.height for k in c.content.controls] == [G.HIT_PAD, G.BTN_H, G.HIT_PAD]
                  and c.content.controls[1].content is b
                  and c.content.spacing == 0 and c.content.tight is True
                  and c.content.controls[0].bgcolor is None
                  and c.content.controls[2].bgcolor is None
                  for c, b in zip(cells, btns)),
              f"{[(_hit_h(c), getattr(c, 'alignment', None)) for c in cells if c is not None]}")
        # 带与按钮接的是同一个动作，而且跟着按钮的禁用态走（真点一次数次数 —— Flet 各自包一层，
        # `band.on_click is btn.on_click` 这种身份比较不可靠）。这里只换 handler、不写存档。
        _hb = _band(cells[0]) if cells and cells[0] is not None else None
        _hit_calls = []
        if _hb is not None:
            _real_cb, _was = btns[0].on_click, btns[0].disabled
            btns[0].on_click = lambda e: _hit_calls.append("btn")
            try:
                btns[0].disabled = False
                _hb.on_click(None)          # 带点下去 = 按钮点下去
                btns[0].disabled = True
                _hb.on_click(None)          # 禁用中：带也不许响（`band_cb` 每次现问 disabled）
            finally:
                btns[0].on_click, btns[0].disabled = _real_cb, _was
        check("PART 11", "命中带与按钮接的是同一个动作，且跟着按钮的禁用态走",
              _hit_calls == ["btn"], f"点到的={_hit_calls}")

        # 可点区域补齐（2026-10-07 用户 m21537；范围照 m21635「完全按照 M3 规范要求，若无要求则
        # 不做」）。2 级 m3.material.io「Touch and pointer target sizes」：触屏 48 / 鼠标笔 44，
        # 都是 consider —— 官方那几档高度（按钮 40、chip 32、开关轨道 40）是**可视**尺寸，不是可点
        # 尺寸。手法一律「外层 `Container` + `padding`」：`hit_pad` 四边各 4、`hit_switch` 上下各 4、
        # 两排 chip 只补上下（补横向会与官方 8 的 chip-set 间距叠成负空隙）。这几条量的是**真窗口里
        # 那棵树**，不是源码文本 —— 包壳有没有真套上、套的是不是那一层，只有树说了算。
        #
        # 扫树的两条讲究：① 孩子不能只看 `controls`/`content` —— 包壳就套在 `TextField.suffix` 与
        # `AppBar.actions` 上；② **面板一次只挂一页**（`_body.content = pages[i]`），别的页是脱离的，
        # 所以按 `panel.pages` 逐棵扫（页对象一直在），再补扫一次 `panel.page`（应用栏不在 pages 里）。
        _pnodes, _ppar, _seen = [], {}, set()

        def _kids_of(c):
            out = []
            for v in list(vars(c).values()) + list(getattr(c, "_values", {}).values()):
                for x in (v if isinstance(v, (list, tuple)) else [v]):
                    if isinstance(x, ft.Control) and x is not c and not isinstance(x, ft.Page):
                        out.append(x)
            return out

        def _scan(root):
            stack = [root]
            while stack:
                c = stack.pop()
                if id(c) in _seen:
                    continue
                _seen.add(id(c))
                _pnodes.append(c)
                for k in _kids_of(c):
                    _ppar.setdefault(id(k), c)
                    stack.append(k)

        def _wrap_of(ctl):
            """`ctl` 外面那层「带内边距的 Container」→ (四边内边距, 那层壳)；没套就是 (None, None)。"""
            cur = _ppar.get(id(ctl))
            if isinstance(cur, ft.Container) and isinstance(cur.padding, ft.Padding):
                p = cur.padding
                return (p.left, p.top, p.right, p.bottom), cur
            return None, None

        def _btn_by_text(want):
            """按按钮上那行字找回控件（日志页/结算页/设置页的按钮都是现建的，没有成员变量）。"""
            for n in _pnodes:
                if isinstance(n, (ft.TextButton, ft.FilledButton, ft.FilledTonalButton,
                                  ft.OutlinedButton)):
                    c = n.content
                    if (c if isinstance(c, str) else getattr(c, "value", None)) == want:
                        return n
            return None

        for _pg in list(getattr(panel, "pages", []) or []):
            _scan(_pg)
        _scan(panel.page)

        # 只有**树上真有**的控件才要求补 48：页对象本身一直活着，而变异体可以把整张卡从栅格
        # 里摘掉（第 10 关的 `resgrid` 牙拆的就是「资源卡在场」）—— 那时卡上的控件只是离开控件
        # 树、属性还在。那种缺席归第 10 关的在场判据管，这里不重复判（否则一颗牙点亮两关）。
        _intree = {id(c) for c in _pnodes}

        _SW_NAMES = ("follow_chk", "random_chk", "fire_chk", "stop_ap", "push_chk", "break_chk",
                     "log_autoscroll", "motion_chk", "autoclean_chk", "force_chk", "verify_chk")
        _IB_NAMES = (("帮助", "help_btn"), ("清空搜索", "search_clear"),
                     ("排序方向", "desc_btn"), ("清空关键词", "log_search_clear"))
        _LB_TEXTS = ("导出日志", "清屏", "重新读取", "打开截图", "取证目录", "导出 CSV",
                     "立即清理", "重启面板", "联网更新")
        _wrap, _ibw, _lbw, _cww = {}, {}, {}, []
        for _n in _SW_NAMES:
            _c = getattr(panel, _n, None)
            if _c is not None:
                _wrap[_n] = _wrap_of(_c)
        for _n, _attr in _IB_NAMES:
            _c = getattr(panel, _attr, None)
            if _c is not None:
                _ibw[_n] = (_c, _wrap_of(_c))
        for _t in _LB_TEXTS:
            _b = _btn_by_text(_t)
            if _b is not None:
                _lbw[_t] = (_b, _wrap_of(_b))
        for _c in list(panel.log_btns.values()) + list(panel.hist_btns.values()):
            if all(x[0] is not _c for x in _cww):
                _cww.append((_c, _wrap_of(_c)))

        _four = (G.HIT_PAD, G.HIT_PAD, G.HIT_PAD, G.HIT_PAD)
        _vert = (0, G.HIT_PAD, 0, G.HIT_PAD)
        _chipv = (0, G.HIT_PAD_CHIP, 0, G.HIT_PAD_CHIP)
        # 底线 7 = 运行卡那 6 颗 + 日志页的「自动滚动」；设置页那 4 颗在「资源」卡上，卡缺席是第 10
        # 关的事（`resgrid` 牙），所以只要求树上这几颗都补上。
        _sw_here = [n for n in _SW_NAMES
                    if getattr(panel, n, None) is not None and id(getattr(panel, n)) in _intree]
        check("PART 11", "树上每一颗开关都补到可点 48（上下各 4 的隐形壳；开关自己一个高度都不给，"
                         "可视仍是官方的 40）",
              len(_sw_here) >= 7
              and all(_wrap.get(n) is not None and _wrap[n][0] == _vert
                      and getattr(getattr(panel, n, None), "height", None) is None
                      and _wrap[n][1].bgcolor is None and _wrap[n][1].ink is not True
                      for n in _sw_here)
              and G.HIT_PAD * 2 + 40 == T.HIT_MIN,
              f"{len(_sw_here)} 颗在树上："
              f"{[(n, (_wrap[n][0] if _wrap.get(n) else None)) for n in _SW_NAMES]}")

        # 开关本体吃自己的手势，包壳只管上下那 4 px —— 落在内边距上的一按得**自己转成一次切换**。
        # 这里换掉处理器数次数（不落盘），禁用态现问现判。
        _sw = panel.follow_chk
        _swbox = _wrap.get("follow_chk")
        _swbox = _swbox[1] if _swbox else None
        _tog = _dis = False
        _got = []
        _saved = (_sw.on_change, _sw.value, _sw.disabled)
        if _swbox is not None:
            _sw.on_change = lambda e: _got.append(getattr(e, "control", None))
            try:
                _sw.value, _sw.disabled = False, False
                try:
                    _swbox.on_click(None)            # 点在上边距那 4 px 上 = 切换一次
                except Exception:                    # noqa: BLE001 —— 变异体把壳的 on_click 摘了：
                    pass                             # 算「没切换」，别把探针自己炸了
                _tog = (_sw.value is True and _got == [_sw])
                _sw.disabled = True
                try:
                    _swbox.on_click(None)            # 禁用中：壳也不许响
                except Exception:                    # noqa: BLE001
                    pass
                _dis = (_sw.value is True and len(_got) == 1)
            finally:
                _sw.on_change, _sw.value, _sw.disabled = _saved
                _sw.update()
        check("PART 11", "点开关包壳的内边距就是点开关本身（切换一次、处理器收到 `control=sw`），"
                         "禁用态不响应",
              _tog and _dis, f"切换={_tog} 禁用后={_dis}")

        check("PART 11", "两排筛选 chip 只补上下（可点 48 = 官方的 32 + 8 + 8；补横向会与官方 8 的 "
                         "chip-set 间距叠成负空隙）",
              len(_cww) >= 2
              and all(w is not None and w[0] == _chipv and getattr(c, "height", None) is None
                      for c, w in _cww)
              and G.CHIP_H + 2 * G.HIT_PAD_CHIP == T.HIT_MIN,
              f"{len(_cww)} 枚：{sorted({str(w[0] if w else None) for _c, w in _cww})}")

        # 九个页面按钮里八个常驻（日志页 2 + 结算页 4 + 设置页 2），第九个「联网更新」在「资源」卡
        # 上 —— 与开关同一条规矩：缺席归第 10 关的在场判据。
        check("PART 11", "四颗图标按钮（40×40）与页面按钮都补到可点 48（四边各 4 的隐形壳，"
                         "可视仍是官方的 40）",
              len(_ibw) == 4 and len(_lbw) >= 8
              and all(w is not None and w[0] == _four and w[1].bgcolor is None
                      for _c, w in _ibw.values())
              and all(w is not None and w[0] == _four and w[1].bgcolor is None
                      for _c, w in _lbw.values())
              and G.HIT_PAD * 2 + 40 == T.HIT_MIN,
              f"图标={[(n, (w[0] if w else None)) for n, (_c, w) in _ibw.items()]} "
              f"按钮={[(t, (w[0] if w else None)) for t, (_c, w) in _lbw.items()]}")

        # 键盘通路（同一批）：`ink=True` 的 Container 与 `ListTile` 都不是可聚焦节点、Tab 走不到
        # （审查报告），所以本项目给手搓控件配的是**快捷键**。这条量 `_on_key` 真把 Alt+↑/↓ 与
        # Alt+Enter 路由到该去的地方（开始页挪选曲列表、结算页才开截图），以及清单里列着这两条。
        # 注意 `self.sel` 存的是**曲目 dict**（`on_song_select` 的入参），比的是它的 musicId。
        _key = (lambda k, alt=True, ctrl=False:
                type("E", (), {"key": k, "alt": alt, "ctrl": ctrl})())
        _mid = lambda: ((panel.sel or {}).get("musicId")
                        if isinstance(panel.sel, dict) else panel.sel)
        panel.show_tab(0)
        _rows = list(getattr(panel.song_list, "controls", None) or [])
        _sel_before, _tab_before = _mid(), panel.tab
        _down = _up = _guard = False
        _opened = []
        if len(_rows) >= 2:
            panel.on_song_select(type("E", (), {"control": _rows[0]})())
            panel._on_key(_key("Arrow Down"))
            _down = _mid() == getattr(_rows[1], "data", None)
            panel._on_key(_key("Arrow Up"))
            _up = _mid() == getattr(_rows[0], "data", None)
            _back = next((r for r in _rows if getattr(r, "data", None) == _sel_before), None)
            if _back is not None:
                panel.on_song_select(type("E", (), {"control": _back})())
        _real_open = panel.open_shot
        panel.open_shot = lambda: _opened.append(1)
        try:
            panel.show_tab(G.TAB_HIST)
            panel._on_key(_key("Enter"))
            _open_ok = len(_opened) == 1
            panel.show_tab(0)
            panel._on_key(_key("Enter"))
            _guard = len(_opened) == 1               # 别的页签不响应（免得开上次那一局）
        finally:
            panel.open_shot = _real_open
            panel.show_tab(_tab_before)
        _listed = (any("Alt+↑ / ↓" in k for k, _w in G.SHORTCUTS)
                   and any("Alt+Enter" in k for k, _w in G.SHORTCUTS))
        check("PART 11", "键盘：Alt+↑/↓ 在选曲列表里挪选中行、Alt+Enter 只在结算页打开截图"
                         "（快捷键清单里也列着这两条）",
              len(_rows) >= 2 and _down and _up and _open_ok and _guard and _listed,
              f"行数={len(_rows)} 下={_down} 上={_up} 截图={_open_ok} 换页不响应={_guard} "
              f"清单={_listed}")

        # `expand` 只在为真时才写进 kwargs（2026-10-07 实测的一次全页灰屏）：Flet 只要看到**显式
        # 传了** `expand`（哪怕 `False`）就在客户端给这一层包一个 `Flexible`，而 `ft.Row(wrap=True)`
        # 在 Flutter 侧是 `Wrap`（parentData 是 `WrapParentData`，不是 `FlexParentData`）⇒ 整页被
        # ErrorWidget 顶掉（设置页那排「立即清理 / 重启面板」正是 wrap 行 + `hit_pad` 的组合，实测
        # 465572 px 的异常灰）。所以两个包壳的缺省值里不许出现 `expand`，树上真有 wrap 行时它的
        # 孩子也一个都不许显式写。
        _btn_x = ft.TextButton(content="x")
        _hp0, _hp1 = G.hit_pad(_btn_x), G.hit_pad(_btn_x, expand=True)
        _h40, _h41 = G.hit48(ft.Text("x")), G.hit48(ft.Text("x"), expand=True)
        _wraps = [c for c in _pnodes if isinstance(c, ft.Row) and getattr(c, "wrap", False)]
        _wrap_kids = [k for w in _wraps for k in (w.controls or [])]
        _wrap_bad = [k for k in _wrap_kids if "expand" in getattr(k, "_values", {})]
        check("PART 11", "包壳只在真要展开时才写 expand（显式 expand=False 会把 wrap 行整页顶成 "
                         "ErrorWidget）",
              "expand" not in _hp0._values and _hp1._values.get("expand") is True
              and "expand" not in _h40._values and _h41._values.get("expand") is True
              and bool(_wraps) and not _wrap_bad,
              f"hit_pad {dict(_hp0._values)} / hit48 {dict(_h40._values)} / "
              f"wrap 行 {len(_wraps)} 行 {len(_wrap_kids)} 个孩子，显式写了 expand 的 "
              f"{len(_wrap_bad)} 个")

        # 按钮层级（审查报告第 6 节）：从前「本轮停止」与「强制终止」长得一模一样，看不出哪一个
        # 更狠。M3 用 **error 角色**表达「会毁掉东西」的动作 —— 终止那一颗单独描红边、写红字。
        def _slot(v, st):
            """`ControlStateValue` 取某一档：逐档写的取那一档（**缺这一档就是 None** —— 「只写
            DEFAULT」这种变异体要能被抓住），平铺写的两种状态取到同一个值。"""
            return v.get(st) if isinstance(v, dict) else v

        def _bs(x):
            return getattr(x, "color", x)

        ks = getattr(panel.btn_kill, "style", None)
        check("PART 11", "「强制终止」走 error 角色（描边与字色都是 tk.danger）",
              ks is not None
              and _slot(getattr(ks, "color", None), ft.ControlState.DEFAULT) == panel.tk.danger
              and _bs(_slot(getattr(ks, "side", None), ft.ControlState.DEFAULT)) == panel.tk.danger,
              f"{getattr(ks, 'side', None)!r} / {getattr(ks, 'color', None)!r}")
        # 用户 m07990「强制停止为什么常亮」：平铺一个 `color=`/`side=`，Flet 当成「所有状态都用
        # 它」，按钮 `disabled=True` 时照旧写红字、描红边 —— 空闲时这一颗看着一直是亮的，而同一
        # 批被禁用的「本轮停止」已经压到 on_surface 38%。所以要逐档：38% 字色 / 12% 描边。
        check("PART 11", "「强制终止」禁用态压到规范那两档（38% 字色 / 12% 描边）—— 不然空闲时一直发红",
              isinstance(getattr(ks, "color", None), dict)
              and _slot(getattr(ks, "color", None), ft.ControlState.DISABLED)
              == panel.tk.disabled(panel.tk.text)
              and _bs(_slot(getattr(ks, "side", None), ft.ControlState.DISABLED))
              == panel.tk.state(panel.tk.text, "disabled_container"),
              f"{_slot(getattr(ks, 'color', None), ft.ControlState.DISABLED)!r} / "
              f"{_bs(_slot(getattr(ks, 'side', None), ft.ControlState.DISABLED))!r}")

        # 设置区（m06279 用户点名：去掉运行卡内部的二次嵌套底色、允许完全重构内部组件）。三行的
        # 顺序还是用户 m05361 点名的那个，但每项改成一枚**瓦片**：「标签行在上（小图标 + 四字全名）、
        # 控件行在下（贴本格左沿）」。竖排之后最宽的一枚只要 `开关 52 + 空档 4 + 数框 84 = 140`
        # 逻辑，而两栏分界 992 处每格也有 ≈163 ⇒ 992–1102 那段响应式死区没了（审查报告 P0：从前半格
        # 要装 206 逻辑，窗口 1024 时第三行第二格的数框被挤出窗口）。嵌套的 `field` 底色一并去掉：
        # 行与行之间只留发丝线，成组靠对齐。
        toggles = (panel.follow_chk, panel.random_chk, panel.fire_chk, panel.stop_ap,
                   panel.push_chk, panel.break_chk)
        check("PART 11", "六颗选项都是 M3 开关、运行卡里一个勾选框都不剩（m06250 第二句）",
              all(isinstance(t, ft.Switch) for t in toggles)
              and not any(isinstance(n, ft.Checkbox) for n in nodes),
              f"{[type(t).__name__ for t in toggles]}")
        grid = getattr(panel, "opt_grid", None)
        grid_nodes = _sub(grid) if grid is not None else []
        rows3 = ([grid.controls[i] for i in (0, 2, 4)]
                 if grid is not None and len(grid.controls) == 5 else [])
        counts = [len(r.controls) for r in rows3 if isinstance(r, ft.Row)]
        divs_n = sum(1 for n in grid_nodes if isinstance(n, ft.Divider))
        check("PART 11", "三行瓦片按 2 / 4 / 2 排（行间两条发丝线），格子上没有二次嵌套底色",
              len(rows3) == 3 and all(isinstance(r, ft.Row) for r in rows3)
              and counts == [2, 4, 2] and divs_n == 2
              and all(isinstance(c, ft.Container) and c.expand is True
                      for r in rows3 for c in r.controls)
              and all(c.width is None for r in rows3 for c in r.controls)
              and not any(isinstance(n, ft.Container) and n.bgcolor == panel.tk.field
                          for n in grid_nodes),
              f"行={counts} 分隔线={divs_n} 底色="
              f"{[str(getattr(n, 'bgcolor', None)) for n in grid_nodes if isinstance(n, ft.Container)]}")

        def _inner(k):
            """穿透一层包壳：可点区域补齐（用户 m21537）之后，开关外面套了一层带上下内边距的
            `Container`（`hit_switch`），控件行里直接躺着的是那层壳。"""
            return k.content if isinstance(k, ft.Container) and k.content is not None else k

        fields = (panel.n_field, panel.policy_spins["gap_min"],
                  panel.policy_spins["push_cap_ms"], panel.policy_spins["retry_cap"])
        all_ctl = (*toggles, *fields)
        tiles = [_tile_of(c) for c in all_ctl]
        heads = [_tile_parts(c)[0] for c in all_ctl]
        ctl_rows = [_tile_parts(c)[1] for c in all_ctl]
        check("PART 11", "每枚瓦片 = 标签行（一图标 + 一名）+ 控件行，控件就在自己那一行里",
              all(t is not None for t in tiles)
              and all(isinstance(h, ft.Row)
                      and len([k for k in h.controls if isinstance(k, ft.Icon)]) == 1
                      and len([k for k in h.controls if isinstance(k, ft.Text)]) == 1
                      for h in heads)
              and all(isinstance(r, ft.Row) and r.spacing == T.SPACE["xs"]
                      and any(_inner(k) is c for k in r.controls)
                      for c, r in zip(all_ctl, ctl_rows)),
              f"瓦片={sum(1 for t in tiles if t is not None)}/{len(all_ctl)}")
        labels = [_tile_label(c) for c in all_ctl]
        check("PART 11", "标签用四字全名（「连续演出」「乐曲识别」「随机乐曲」等），不再靠 tooltip 猜",
              all(labels) and {"连续演出", "演出间隔", "乐曲识别", "随机乐曲",
                               "LB监测", "AP终止", "正推限制", "断连重试"}
              <= set(labels) and not ({"连续", "跟随游戏", "随机演奏", "正推", "重试",
                                       "连续演奏", "火力等待", "AP 停止", "AP 终止",
                                       "限制正推", "重开上限", "曲目跟随", "随机曲目"}
                                      & set(labels)),
              f"{labels}")
        check("PART 11", "瓦片两行一律贴本格左沿（控件的左边缘因此落在同一条竖线上）",
              all(c is not None and c.horizontal_alignment == ft.CrossAxisAlignment.START
                  for c in tiles),
              f"{[getattr(c, 'horizontal_alignment', None) for c in tiles]}")
        check("PART 11", "四个数框同宽（`num_field` 的默认宽度也收成 96，不再各写一个数）",
              all(f.width == 96 for f in fields)
              and inspect.signature(G.num_field).parameters["width"].default == 96,
              f"{[f.width for f in fields]}")
        r3 = (_tile_parts(panel.push_chk)[1], _tile_parts(panel.break_chk)[1])
        check("PART 11", "「正推限制 / 断连重试」各自跟它管的那个数同一行（开关在前、数框在后）",
              all(isinstance(r, ft.Row) and len(r.controls) == 2 for r in r3)
              and _inner(r3[0].controls[0]) is panel.push_chk
              and r3[0].controls[1] is panel.policy_spins["push_cap_ms"]
              and _inner(r3[1].controls[0]) is panel.break_chk
              and r3[1].controls[1] is panel.policy_spins["retry_cap"],
              f"{[[type(k).__name__ for k in r.controls] if isinstance(r, ft.Row) else r for r in r3]}")
        row_of = {id(c): _row_of_cell(c) for c in all_ctl}
        check("PART 11", "三行归属与 m05361 点名的一致（连续演出/演出间隔 · 乐曲识别/随机乐曲/LB监测/AP终止 · "
                         "正推限制/断连重试）",
              row_of[id(panel.n_field)] is not None
              and row_of[id(panel.n_field)] is row_of[id(panel.policy_spins["gap_min"])]
              and row_of[id(panel.follow_chk)] is row_of[id(panel.random_chk)]
              and row_of[id(panel.follow_chk)] is row_of[id(panel.stop_ap)]
              and row_of[id(panel.push_chk)] is row_of[id(panel.break_chk)]
              and len({id(row_of[id(c)]) for c in all_ctl}) == 3,
              f"行数={len({id(row_of[id(c)]) for c in all_ctl})}")

        # m14282：「乐曲识别」与「随机乐曲」互斥 —— 谁刚开谁胜出、另一颗当场关掉。两个键住在两处
        # （`follow_game` 在顶层、`random` 在 defaults 里），被关掉的那颗也得跟着落盘，不然下次开
        # 面板它又亮回来。这几条跑在夹具上（`core.STATE` 已被 `_point()` 指到夹具的状态文件）。
        f0, r0 = panel.follow_chk.value, panel.random_chk.value
        panel.random_chk.value = panel.follow_chk.value = True
        panel._save_follow()
        d0 = panel.state.get("defaults") or {}
        check("PART 11", u"「乐曲识别」与「随机乐曲」互斥：刚开的那颗胜出、另一颗当场关掉（跟随胜出）",
              panel.follow_chk.value is True and panel.random_chk.value is False,
              f"follow={panel.follow_chk.value} random={panel.random_chk.value}")
        check("PART 11", u"互斥之后两颗都按新值落盘（顶层 follow_game / defaults.random 各住一处）",
              panel.state.get("follow_game") == 1 and int(d0.get("random", -1)) == 0,
              f"follow_game={panel.state.get('follow_game')} random键={d0.get('random')}")
        panel.random_chk.value = panel.follow_chk.value = True
        panel._save_defaults()
        d1 = panel.state.get("defaults") or {}
        check("PART 11", u"「乐曲识别」与「随机乐曲」互斥：随机那颗胜出时跟随让位并落盘",
              panel.random_chk.value is True and panel.follow_chk.value is False
              and int(d1.get("random", -1)) == 1 and panel.state.get("follow_game") == 0,
              f"follow={panel.follow_chk.value} random={panel.random_chk.value} "
              f"follow_game={panel.state.get('follow_game')} random键={d1.get('random')}")
        # 第三态：两颗都关（用面板列表里选中的那首）合法 —— 互斥不许把这一态一起吃掉。
        panel.random_chk.value = panel.follow_chk.value = False
        panel._save_defaults()
        check("PART 11", u"两颗模式开关都关仍是合法的第三态（照面板列表里选中的那首跑）",
              panel.random_chk.value is False and panel.follow_chk.value is False,
              f"follow={panel.follow_chk.value} random={panel.random_chk.value}")
        panel.follow_chk.value, panel.random_chk.value = f0, r0    # 后面几条还在看这颗面板

        # 设置区在上、两行动作按钮贴卡底（m06250 第二句「开始按钮下面还有这么多空位」）：余量交给
        # `SPACE_BETWEEN` 摊在两区之间 ⇒ 按钮落卡底、与左栏下沿对齐，卡底不再留一块空。
        acts = rb.controls[-1] if rb is not None and rb.controls else None
        check("PART 11", "设置区在上、两行动作按钮贴卡底（`SPACE_BETWEEN` 把余量摊在两区之间）",
              rb is not None and rb.alignment == ft.MainAxisAlignment.SPACE_BETWEEN
              and rb.expand is True and len(rb.controls) == 2
              and all(_inside(b, acts) for b in btns),
              f"{getattr(rb, 'alignment', None)} {len(rb.controls) if rb is not None else None}")

        # m06250 第三句「最近选项卡的元素可以做宽松些」：行定高（`RECENT_ROW_H`）、封面
        # `RECENT_ART`、行距 0（官方列表项齐平，行自己就带满 72）、标题升到 labelLarge。
        # 2026-10-06 m09165 加一条**跨常数的等式**：`RECENT_ART + 2*sm == RECENT_ROW_H` —— 就是
        # 「56 的封面挤进 64 的行」那个长方形（用户报的）。每条都**同时**钉两条：一条是对常数的等式
        # （视图层不许自己另写一个尺寸），一条是**跨常数的不等式** —— 只留前者的话，把
        # `RECENT_ART` 从 56 改回 40 时左右两边一起动、判据照样成立（`recart` 那颗牙第一跑就是
        # 这样「一条都没亮」）。不等式钉的是设计意图本身：封面比选曲列表的 `T.AVATAR`(40) 大一档、
        # 行至少 56 逻辑高、标题不小于正文那一档。
        rr = panel.recent.rows
        rbody = panel.recent.body
        check("PART 11", "「最近演出」卡的元素放宽（行高、封面、行距、标题字号都跟着常数走）",
              len(rr) == G.RECENT_POOL and rbody is not None
              and rbody.spacing == T.SPACE["none"]
              and all(r["box"].height == G.RECENT_ROW_H
                      and r["box"].height >= 56 for r in rr)
              and all(r["art"].width == G.RECENT_ART
                      and r["art"].height == G.RECENT_ART
                      and r["art"].width + 2 * T.SPACE["sm"] == r["box"].height
                      and r["art"].width > T.AVATAR for r in rr)
              and all(r["title"].style.size == T.type_style(T.FONT_ROLE["b"]).size
                      and r["title"].style.size >= T.type_style(T.FONT_ROLE["n"]).size
                      for r in rr),
              f"行高={[r['box'].height for r in rr][:2]} 封面={[r['art'].width for r in rr][:2]}"
              f"x{[r['art'].height for r in rr][:2]} "
              f"行距={getattr(rbody, 'spacing', None)} 标题={[r['title'].style.size for r in rr][:2]}")

        # 两张卡各只列**自己那一半**（用户 m10950）：夹具里那九局全是单人局 ⇒ 多人卡此刻是空态；
        # 再从真事件口落一局多人，同一份模型立刻只喂给多人卡，单人卡那一行一个字都不许动。
        # （这里不点名 `probe_flet`：前面几关会重读记录文件，那一笔在 PART 11 时已经不在了。）
        check("PART 11", "两张「最近演出」卡各只列自己那一半（单人卡有记录、多人卡空态）",
              panel.recent.rows[0]["title"].value != "还没有记录"
              and panel.m_recent.rows[0]["title"].value == "还没有记录"
              and panel.hist.recent_tags(G.RECENT_POOL_MULTI, "multi") == []
              and len(panel.hist.recent_tags(G.RECENT_POOL, "solo")) >= 1,
              f"单人卡={panel.recent.rows[0]['title'].value!r} "
              f"多人卡={panel.m_recent.rows[0]['title'].value!r} "
              f"multi={panel.hist.recent_tags(G.RECENT_POOL_MULTI, 'multi')}")
        solo_head = panel.recent.rows[0]["title"].value
        # 用户 m12311：「多人演出的最近面板条目上限调整为15」（2026-10-10 用户 m14172 一度改成 10，
        # 同日用户 m14308「还是改回15吧」又回到 15：那张卡撑满之后条数只决定列表多长，不决定
        # 看得见几条）。两张卡同一个类、上限分档，
        # 三处（建行 / 算余量 / 算条数）都读这张卡自己的 `pool`。顺带把「提上去到底看得见几行」
        # 量出来：默认窗并排时多人卡那一栏的 room 只装得下 7 行（> 旧上限 6），叠栏档
        # room = pool × RECENT_ROW_H ⇒ 全出、整页滚。
        # 两条规矩（照 2582-2586 那段的写法）：① 每条等式都要配一条**跨常数**的关系，否则把
        # `RECENT_POOL_MULTI` 从 15 改回 6 时视图与判据一起动、一条都不亮（`pool15` 那颗牙第一跑
        # 就是这样「一条都没亮」）；② 用户点名的两个数（单人 6 / 多人 15）本身写死成字面量，
        # 那是这一问的验收对象，不许只跟着模块常量走。
        m_fit = int(panel._recent_room(panel.m_recent) // G.RECENT_ROW_H)
        check("PART 11", "「最近演出」上限分档（单人 6 / 多人 15）：两卡各按自己的 pool 建行，"
                         "默认窗并排那一档 room 装得下 7 行（比单人上限多、又装不下全部 15）",
              G.RECENT_POOL == 6 and G.RECENT_POOL_MULTI == 15
              and G.RECENT_POOL_MULTI > G.RECENT_POOL
              and len(panel.recent.rows) == G.RECENT_POOL
              and len(panel.m_recent.rows) == G.RECENT_POOL_MULTI
              and panel.recent.pool == G.RECENT_POOL
              and panel.m_recent.pool == G.RECENT_POOL_MULTI
              and m_fit >= G.RECENT_POOL
              and m_fit < G.RECENT_POOL_MULTI
              and panel.m_recent.shown <= G.RECENT_POOL_MULTI,
              f"单人 {len(panel.recent.rows)} 行 pool={panel.recent.pool}；"
              f"多人 {len(panel.m_recent.rows)} 行 pool={panel.m_recent.pool} "
              f"room={panel._recent_room(panel.m_recent):.0f} fit={m_fit} "
              f"可见={panel.m_recent.shown}")
        panel.core.q.put(("result", {"record": dict(REC, tag="probe_multi", song="多人歌",
                                                    multi=True), "tag": "probe_multi"}))
        await asyncio.sleep(T.motion_ms("card") / 1000.0 + 0.4)
        check("PART 11", "落一局多人：只有多人卡变、单人卡那一行一个字不动",
              "多人歌" in str(panel.m_recent.rows[0]["title"].value)
              and panel.recent.rows[0]["title"].value == solo_head
              and panel.hist.recent_tags(G.RECENT_POOL_MULTI, "multi") == ["probe_multi"],
              f"多人卡={panel.m_recent.rows[0]['title'].value!r} "
              f"单人卡={panel.recent.rows[0]['title'].value!r}（原来 {solo_head!r}）")

        # 来源筛选（2026-10-10 用户 m13266「记录界面加个单人多人的筛选」）：两枚 chip 与判定那五枚
        # 同一排、中间一条 1dp 竖线；默认两枚都亮（两半都列）。这里在真控件上走一遍：熄掉「单人」
        # 之后多人那一局必须还在、页脚跟着走；两枚都不亮要落到空态；再点亮回来必须复原。
        n_before = len(panel.hist.tags)
        check("PART 11", "来源两枚 chip：单人 / 多人，默认都亮着、标签上不带数",
              set(panel.hist_src_btns) == {k for k, _ in core.HIST_SOURCES}
              and [b.label.value for b in panel.hist_src_btns.values()]
              == [lbl for _, lbl in core.HIST_SOURCES]
              and all(b.selected for b in panel.hist_src_btns.values()),
              f"{[(k, b.label.value, b.selected) for k, b in panel.hist_src_btns.items()]}")
        panel.set_hist_source("solo", False)
        await asyncio.sleep(0.25)
        check("PART 11", "熄掉「单人」：多人那一局还在、单人那些一行不剩、页脚跟着说",
              "probe_multi" in panel.hist.tags
              and all(core.hist_mode(panel.hist.recs[t]) == "multi" for t in panel.hist.tags)
              and panel.hist_src_btns["solo"].selected is False
              and f"筛出 {len(panel.hist.tags)} 局" in str(panel.hist_info.value),
              f"tags={panel.hist.tags} info={panel.hist_info.value!r}")
        panel.set_hist_source("multi", False)
        await asyncio.sleep(0.25)
        check("PART 11", "两枚都不亮：表上一行都没有、落到空态",
              panel.hist.tags == [] and panel.hist_empty.visible is True,
              f"tags={panel.hist.tags} empty={panel.hist_empty.visible}")
        panel.set_hist_source("multi", True)
        panel.set_hist_source("solo", True)
        await asyncio.sleep(0.25)
        check("PART 11", "两枚都点亮回来：行数复原、空态收起来",
              "probe_multi" in panel.hist.tags and len(panel.hist.tags) == n_before
              and panel.hist_empty.visible is False
              and all(b.selected for b in panel.hist_src_btns.values()),
              f"{len(panel.hist.tags)} 行（熄之前 {n_before}）")

        roma_sel = core.song_romaji(panel.sel) if panel.sel else ""
        want_head = (f"{core.song_label(panel.sel)}（{roma_sel}）" if roma_sel
                     else core.song_label(panel.sel)) if panel.sel else ""
        check("PART 11", "选曲卡底部信息一行写全（原文名（罗马音）· 难度 · 乐队）",
              bool(panel.sel) and str(panel.chart_info.value).startswith(want_head + " ·")
              and "\n" not in str(panel.chart_info.value),
              f"{str(panel.chart_info.value)!r} vs {want_head!r}")
        _t_sz = getattr(T.type_style(T.FONT_ROLE["t"]), "size", None)
        _n_sz = getattr(T.type_style(T.FONT_ROLE["n"]), "size", None)
        check("PART 11", "选曲卡底部那行比正文大一档、自己只占一行（m05745 第二句）",
              panel.chart_info.max_lines == 1
              and getattr(panel.chart_info.style, "size", None) == _t_sz
              and (_t_sz or 0) > (_n_sz or 0),
              f"max_lines={panel.chart_info.max_lines} size="
              f"{getattr(panel.chart_info.style, 'size', None)} vs n={_n_sz}")
        check("PART 11", "游戏画面提示空着就收起来（不再白占一行）",
              panel.ingame_hint.visible is False
              and (panel._set_hint("x"), panel.ingame_hint.visible is True)[1]
              and (panel._set_hint(""), panel.ingame_hint.visible is False)[1],
              f"visible={panel.ingame_hint.visible}")

        panel.search.value = "mayoiuta"
        panel._on_search()
        await asyncio.sleep(0.25)
        q1 = [str(r.title.value) for r in panel.song_list.controls]
        check("PART 11", "按罗马音搜得到，标题仍是原文",
              q1 == [core.song_label(by_mid["100001"])], f"{q1}")
        check("PART 11", "搜索框有字时清空按钮才出现", panel.search_clear.visible is True,
              f"visible={panel.search_clear.visible}")
        panel.search.value = "mxj"
        panel._on_search()
        await asyncio.sleep(0.25)
        q2 = [str(r.title.value) for r in panel.song_list.controls]
        check("PART 11", "按拼音首字母也搜得到（搜的口径没被界面语言改掉）",
              q2 == [core.song_label(by_mid["100001"])], f"{q2}")
        panel._clear_search()
        await asyncio.sleep(0.25)
        check("PART 11", "清空之后回到全部、按钮收起来",
              len(panel.song_list.controls) == 3 and panel.search_clear.visible is False,
              f"{len(panel.song_list.controls)} 首 visible={panel.search_clear.visible}")

        label2 = next((k for k, v in panel.cat_map.items() if v == 2), None)
        panel.cat_box.value = label2
        panel._on_cat(None)
        await asyncio.sleep(0.25)
        rows2 = panel.song_list.controls
        check("PART 11", "切到某个乐队之后仍然显原文、计数跟着变",
              label2 is not None and len(rows2) == 1
              and str(rows2[0].title.value) == core.song_label(by_mid["100003"])
              and str(panel.count_text.value).startswith("显示 1 / 3 首"),
              f"{[str(r.title.value) for r in rows2]} / {panel.count_text.value!r}")
        panel.cat_box.value = "全部"
        panel._on_cat(None)
        await asyncio.sleep(0.25)

        # 像素层：一行四段。用户 m19421 定「完全按照官方的来」，官方分段控件在像素上留下三样能
        # 独立量的东西：① 每段自己带 1 px `outline` 描边（`segmented_button.dart:1273-1281` 的
        # `_SegmentedButtonDefaultsM3.side`）⇒ 四段之间是**三条等距竖线**；② 只有**选中那一段**是
        # 填色（主题里 `bgcolor` 的 SELECTED 那一档 `secondary_container`），未选中是透明底 ⇒
        # 整组里只有**一块**实心；③ 整组被 `horizontal_alignment=STRETCH` 拉满卡片内容宽，两端是
        # 胶囊（`shape` 留空时 Flutter 给 `StadiumBorder`）。控件层只能证明「段数 / 单选 / `style`
        # 留空」，证明不了渲染出来真的等宽、真的四段一行 —— 所以在默认窗口上再量一遍。
        # 卡片内容的左右边界从「卡片里唯一一类横贯的底色带」取 —— 搜索框、列表容器都落在同一对
        # 竖线上，取并集比取某一行稳（列表容器自己还有 1 px 边框与一圈内边距）。底色 = `tk.field`；
        # 深浅主题各取各的，不写死色值；夹具是浅色（`_once()` 里给 "light"）。
        # PART 8 往日志里灌了 4000+ 行（视图里也留着 LOG_WINDOW 行）—— 量版式之前先把视图收干净：
        # 几十个控件重排很快，几千个会把「窗口改尺寸」那一拍拖到 1.3 s 之外（实测踩过：变异体里
        # 截出来的还是 760 宽那张图，四个格子一个都量不到）。版式跟日志多少行无关，这一关不该
        # 跟 PART 8 耦在一起 —— 否则拆「日志窗口」那条守卫会顺带把它点亮，牙就白拆了。
        try:
            panel.log_view.controls = panel.log_view.controls[-20:]
            panel._refresh_log_info()
            panel.log_view.update()
        except Exception:
            pass
        await asyncio.sleep(0.4)

        gp = await _shot(T.WINDOW_DEFAULT[0], T.WINDOW_DEFAULT[1], 0, "grid11")
        gim = Image.open(gp).convert("RGB")
        gw, gh = gim.size
        graw = gim.tobytes()
        _os = tuple(int(panel.tk.on_surface[i:i + 2], 16) for i in (1, 3, 5))

        def _tok(names):
            """令牌色 + 两档状态层叠色（悬停 8%、按下 12% 的 `on_surface`）。

            窗口就开在光标下面、光标落点随版式变，量到的常常是叠色（实测选中那段
            `#dee1f9` → `#cfd1e8`）。这一关量的是**几何**（四段等宽、外沿贴卡片内容边界），
            悬停不该让它红，所以把这两档叠色也算进「同一种色」；**只多认这两档**，不加别的，
            免得把斜旁的行底色也当成填色。
            """
            out = []
            for n in names:
                c = tuple(int(getattr(panel.tk, n)[i:i + 2], 16) for i in (1, 3, 5))
                out.append(c)
                for a in (0.08, 0.12):
                    out.append(tuple(round(c[i] * (1 - a) + _os[i] * a) for i in range(3)))
            return out

        ftok = _tok(("field",))                  # 卡片里横贯的底色（搜索框 / 列表容器）
        stok = _tok(("secondary_container",))    # 选中那一段的填色
        otok = _tok(("outline",))                # 分段控件那 1 px 描边

        def _hit(tok, x, y):
            o = (y * gw + x) * 3
            return any(all(abs(graw[o + i] - c[i]) <= 4 for i in range(3)) for c in tok)

        def _runs(y, x0, x1, minw):
            out, s = [], None
            for x in range(x0, x1):
                if _hit(ftok, x, y):
                    if s is None:
                        s = x
                elif s is not None:
                    if x - s >= minw:
                        out.append((s, x - 1))
                    s = None
            if s is not None and x1 - s >= minw:
                out.append((s, x1 - 1))
            return out

        wide = []
        for y in range(0, gh, 2):
            rs = _runs(y, gw // 12, gw * 15 // 16, 300)
            if len(rs) == 1:
                wide.append((y, rs[0]))
        # 取**众数**而不是 min/max：窗口最底下（y≈1058）有一条整宽的浅色收边带，`#dfdde7` 与
        # field `#e3e1e9` 每通道只差 4、正踩在容差上 —— min/max 会被它一把拽到扫描边界上。
        tally = {}
        for r in wide:
            key = (r[1][0], r[1][1])
            tally[key] = tally.get(key, 0) + 1
        (cx0, cx1), _n = max(tally.items(), key=lambda kv: kv[1])
        list_bottom = max(r[0] for r in wide if (r[1][0], r[1][1]) == (cx0, cx1))

        # 选中那一段的填色块：文字刻在中间（字形把填色切开也不打紧 —— 填色从段左绕到段右），
        # 所以按**连通块**数，只留最大的一块。只扫到列表下方 300 px：再往下是「运行」那张卡，
        # 它的按钮同样是 `field` 色、会被误数。
        group_w = float(cx1 - cx0)
        seg_w = group_w / 4.0
        x_lo, x_hi = max(0, cx0 - 8), min(gw, cx1 + 9)
        y_hi = min(gh, list_bottom + 300)
        pts = {}
        for y in range(list_bottom + 8, y_hi, 2):
            for x in range(x_lo, x_hi, 2):
                if _hit(stok, x, y):
                    pts[(x, y)] = True
        blobs = []
        while pts:
            seed = next(iter(pts))
            stack, blob = [seed], []
            del pts[seed]
            while stack:
                x, y = stack.pop()
                blob.append((x, y))
                for nb in ((x + 2, y), (x - 2, y), (x, y + 2), (x, y - 2)):
                    if nb in pts:
                        del pts[nb]
                        stack.append(nb)
            if len(blob) >= 100:               # 零星杂色不算一块
                blobs.append({"x": (min(p[0] for p in blob), max(p[0] for p in blob)),
                              "y": (min(p[1] for p in blob), max(p[1] for p in blob))})
        blobs.sort(key=lambda r: -((r["x"][1] - r["x"][0]) * (r["y"][1] - r["y"][0])))

        _lbls = ("像素上一行四段：三条内部隔线等距，每段宽 = 组宽/4",
                 "像素上只有选中那一段是实心块：宽 = 组宽/4、与整组同高",
                 "整组左右外沿贴卡片内容边界、两端是胶囊（圆角把角上的描边让开了）")
        if not blobs:
            for lbl in _lbls:
                check("PART 11", lbl, False,
                      f"没量到选中那一段的填色块（卡片内容 {cx0}..{cx1}）")
        else:
            blk = blobs[0]
            blk_w = blk["x"][1] - blk["x"][0] + 1
            blk_h = blk["y"][1] - blk["y"][0] + 1
            yc = (blk["y"][0] + blk["y"][1]) // 2
            # 三条**内部**分隔线：竖直、几乎与整组同高。只认「竖着连成一条」的列 —— 胶囊两端
            # 那两条描边只在中间几行才存在（竖不满），字形的抗锯齿偶尔会撞上 outline 色，但绝
            # 竖不成一条。
            need = int(blk_h * 0.8)
            cols = [x for x in range(max(0, cx0 - 6), min(gw, cx1 + 7))
                    if sum(1 for y in range(blk["y"][0], blk["y"][1] + 1)
                           if _hit(otok, x, y)) >= need]
            lines = []
            for x in cols:
                if lines and x - lines[-1][-1] <= 2:
                    lines[-1].append(x)
                else:
                    lines.append([x])
            dividers = [sum(ln) / float(len(ln)) for ln in lines]
            gaps = [dividers[i + 1] - dividers[i] for i in range(len(dividers) - 1)]
            # 组框的上/下沿：在**第二段中间那一列**扫 outline —— 不能取组正中，那正好落在分隔线上。
            x_mid = cx0 + int(group_w * 3 // 8)
            yrows = [y for y in range(max(0, blk["y"][0] - 14), min(gh, blk["y"][1] + 15))
                     if _hit(otok, x_mid, y)]
            top, bot = (min(yrows), max(yrows)) if yrows else (blk["y"][0], blk["y"][1])
            group_h = bot - top + 1
            # 左右外沿：整组中线那一行里最靠左/最靠右的描边像素（胶囊的最左点就在中线高度上）。
            left = [x for x in range(max(0, cx0 - 8), min(gw, cx1 + 9)) if _hit(otok, x, yc)]
            lx, rx = (min(left), max(left)) if left else (cx0, cx1)
            # 圆角：再往上几行，胶囊的左描边会向右收进去（直角则贴着左沿）—— 顺手证明两端是胶囊。
            corner = [x for x in range(max(0, cx0 - 8), min(gw, cx1 + 9))
                      if _hit(otok, x, top + 4)]
            corner_x = min(corner) if corner else cx0

            check("PART 11", _lbls[0],
                  len(dividers) == 3 and all(abs(g - seg_w) <= 6 for g in gaps)
                  and abs(dividers[0] - (cx0 + seg_w)) <= 6,
                  f"隔线 {[round(d, 1) for d in dividers]} 间距 {[round(g, 1) for g in gaps]} "
                  f"应为 {round(seg_w, 1)}（卡片内容 {cx0}..{cx1}）")
            check("PART 11", _lbls[1],
                  len(blobs) == 1 and abs(blk_w - seg_w) <= 8 and blk_h >= group_h - 6,
                  f"{len(blobs)} 块，最大那块 {blk_w}x{blk_h}px（应为 ≈{round(seg_w)}x{group_h}），"
                  f"其余 {[(r['x'], r['y']) for r in blobs[1:]]}")
            check("PART 11", _lbls[2],
                  abs(lx - cx0) <= 6 and abs(rx - cx1) <= 6 and corner_x - cx0 >= 8,
                  f"组框 {lx}..{rx}（卡片 {cx0}..{cx1}）；上沿 {top}、下沿 {bot}、"
                  f"角上的描边从 {corner_x} 起（离左沿 {corner_x - cx0} px）")


def _kind_card_title(panel):
    """设置页那张「种类偏移」卡的标题字（用户 m15291 改名的那一半）。

    路径照 `card()` 的构造走：`_kind_row` 的每一份是 `Container(content=<Card>)`，Card 的
    content 是内层 `Container`，它的 content 是 `Column`，第一条就是标题 `Row`
    （`[Icon, Text]`；没给 icon 时只有 Text）。取不到就回 None —— 判据会当场变假，不会静默
    放过。
    """
    import flet as ft
    try:
        card_ = panel._kind_row.controls[0].content
        head = card_.content.content.controls[0]
        texts = [c for c in head.controls if isinstance(c, ft.Text)]
        return texts[0].value if texts else None
    except Exception:
        return None


def _kind_card_texts(panel):
    """设置页那张「种类偏移」卡里**所有**文字（用户 m53176「种类偏移+点明」）。

    只判 `panel.kind_note.value` 不够 —— 那个属性在不在树上都读得到。这里从 `_kind_row` 的
    控件树往下走，把真长在卡里的 `ft.Text` 全捞出来；卡面那句「与选曲页那个「分类」筛选
    （乐队分类）无关」必须从这棵树里出现，否则它只是面板上的一个属性。
    """
    import flet as ft
    out = []

    def walk(ctl, depth=0):
        if ctl is None or depth > 8:
            return
        if isinstance(ctl, ft.Text):
            out.append(ctl.value or "")
        for attr in ("controls", "content"):
            child = getattr(ctl, attr, None)
            if isinstance(child, list):
                for c in child:
                    walk(c, depth + 1)
            elif child is not None:
                walk(child, depth + 1)

    try:
        walk(panel._kind_row.controls[0].content)
    except Exception:
        return out
    return out


def _gap_from(core, panel, raw):
    """把状态文件里的 `gap_min` 手改成任意字面量（用户手改文件那条路），

    再看**面板下一次启动**时 core 读回什么 —— `RunOrchestrator` 的状态是构造时读进来的一份，
    所以这里得照面板启动的样子重造一个，而不是问旧实例（旧实例根本不会重读文件）。
    """
    st = core.read_json(core.STATE, {}) or {}
    st.setdefault("defaults", {})["gap_min"] = raw
    core.save_state(st)
    fresh = core.RunOrchestrator(core.read_json(core.STATE, {}))
    return fresh.gap_min()


# ---------------------------------------------------------------- 主流程

def _report(payload):
    res = payload["res"]
    bad = [r for r in res if not r["ok"]]
    # 探针自己炸了会写成 "PART 0" —— 不在 PARTS 里也必须打出来，不然失败被静默吞掉。
    for part in list(PARTS) + sorted({r["part"] for r in res} - set(PARTS)):
        rows = [r for r in res if r["part"] == part]
        if not rows and UPTO is not None and not _want(part):
            print(f"  --   {part}  跳过（--upto {UPTO}）")
            continue
        if not rows:
            rows = [{"label": "这一关一条判据都没有", "ok": False, "extra": ""}]
        nf = sum(0 if r["ok"] else 1 for r in rows)
        print(f"  {'ok  ' if not nf else 'FAIL'} {part}  {len(rows)} 条"
              f"{'' if not nf else f'，{nf} 条 FAIL'}")
        for r in rows:
            if not r["ok"]:
                print(f"      - {r['label']}  {r['extra']}")
    rc = payload.get("rc", 0)
    if rc != 0:
        last = res[-1] if res else None
        print(f"  FAIL 子进程退出码 {rc}（不是正常退到最后的）"
              f"，最后写出的判据：{last['part'] if last else '一条都没有'} / "
              f"{last['label'] if last else '-'}")
    print(f"  guard() 写入跟随模块全局 = {payload['guard']}")
    print(f"  隔离：真实 research/ 未变 = {payload['iso']}")
    print(f"  夹具状态文件被写过 = {payload['state_written']}")
    wrote = payload["state_written"]
    if UPTO is not None and not wrote:
        # `--only` 只跑一关时，那一关可能一个字节都不写状态文件（写它的是 PART 6/10 那几关）；
        # 隔离本身已由 `iso`（真实 research/ 快照一致）与 `guard()` 看着，这里不重复判。
        print("  （--upto：这一关没写状态文件，state_written 这一条不判）")
    ok = (not bad and payload["guard"] and payload["iso"]
          and (wrote or UPTO is not None) and rc == 0)
    return ok, bad


def _once(mutant=None):
    import fletviewcheck as FV

    fixture = tempfile.mkdtemp(prefix="fletpanel-")
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


def _teeth(only=None, jobs=1):
    """`only=None` = 全拆；给名字列表 = 只拆这几条（分档验证的 B 档走这条）。

    `jobs > 1` 时几颗牙同时在跑（`--jobs`）：每颗牙自己的临时变异体目录 + 自己的 Flet 会话，
    判据一条不少、重放规矩一个字不改，只是把「等窗口组起来」的时间叠起来 —— 一颗牙 ≈31 s
    里绝大部分是窗口起势与逐关的像素/布局等待（实测 PART 10 11.4 s、PART 4 5.6 s、PART 11
    5.5 s、PART 1 4.1 s），正是能叠的那部分。输出的每一颗牙是一个整块（整块拿锁打），所以
    并发不会把某颗牙的行拆到别人中间去。

    **实测并发上限是 4**（`--jobs` 的默认值也是 4）：全拆 4 并发全绿（384 s 是 43 颗时实测的，
    现在是 52 颗；31 颗时 2 并发 562.8 s，串行约 15.6 min）。再往上不行 —— 6 并发时 PART 10 的
    「设置页两栏等宽」「窗口拉高『最近』卡自己多放几条」两条会假红：要 900 高的窗口
    只拿到 `page.h = 862.67`，即 6 个 Flutter 窗口同时开时请求的窗口尺寸没落上。
    那是并发自己造出来的红，不是面板坏了 —— 别把默认值调过 4。
    """
    import concurrent.futures
    import threading

    names = list(TEETH) if not only else list(only)
    unknown = [n for n in names if n not in TEETH]
    if unknown:
        print(f"TEETH FAIL：没有这些牙 {unknown}\n现有：{'、'.join(TEETH)}")
        return 1
    payload, log = _once()
    ok, bad = _report(payload)
    if not ok:
        print(f"TEETH FAIL：控制组没过，先修它\n{log[-2000:]}")
        return 1
    print(f"控制组 ALL PASS，开始逐条拆牙（{len(names)}/{len(TEETH)} 条"
          f"{f'，并发 {jobs}' if jobs > 1 else ''}）")
    ctx_n = len(payload["res"])          # 控制组写了多少条判据（变异体不许少写）

    def one_tooth(name):
        """一颗牙：变异体跑一次（少写就重放），返回 (这颗牙守住了吗, 要打印的那一段)。"""
        part, subs = TEETH[name]
        lines = []
        ok_here = True

        def say(s):
            lines.append(s)

        def run_tooth(d):
            """变异体跑一次；**判据少写了就再放一次，以第二次为准**。

            2026-10-06 的全拆（29/29）里 `clamp`/`reset`/`trim` 三颗报「只写了 183/191 条、
            退出码 0」，单独重放同一颗牙全绿 —— 全套连拆时 Flutter 客户端偶发半路没了。
            真正会半路死的变异体是确定性的：它会连着两次少写，所以这一次重放不掩盖真问题，
            只去掉一个假 FAIL。退出码非 0 与「少写」都不在这里判，交给下面两条既有判据。
            """
            payload, log = _once(d)
            if payload.get("rc") == 0 and len(payload["res"]) != ctx_n:
                say(f"  ..  牙 {name}  变异体只写了 {len(payload['res'])}/{ctx_n} 条判据，重放一次")
                payload, log = _once(d)
            return payload, log

        d = tempfile.mkdtemp(prefix=f"fletpanel-tooth-{name}-")
        try:
            src = os.path.join(TOOLS, "flet_gui.py")
            text = io.open(src, encoding="utf-8").read()
            for old, new in subs:
                if text.count(old) != 1:
                    say(f"  FAIL 牙 {name}：原文里 {old!r} 出现 {text.count(old)} 次")
                    ok_here = False
                    break
                text = text.replace(old, new)
            else:
                with io.open(os.path.join(d, "flet_gui.py"), "w", encoding="utf-8",
                             newline="\n") as f:
                    f.write(text)
            payload, log = run_tooth(d)
            lit = {r["part"] for r in payload["res"] if not r["ok"]}
            if payload.get("rc") != 0:
                say(f"  FAIL 牙 {name}  子进程退出码 {payload['rc']}"
                    f"（变异体没跑完，不是「点亮」）：{log[-500:]}")
                ok_here = False
            elif len(payload["res"]) != ctx_n:
                # 子进程半路没了：少写的那几条没红，`lit` 可能正好是空的 —— 那不能读成
                # 「拆了守卫还全绿 = 判据是装饰」，这是**变异体没跑完**（m06250 的 `swtch`
                # 与 `recart` 两颗牙第一次拆时就是这么被误判的）。
                say(f"  FAIL 牙 {name}  变异体只写了 {len(payload['res'])}/{ctx_n} 条判据"
                    f"（子进程半路没了，不是「一条都没亮」）")
                ok_here = False
            elif lit == {part}:
                say(f"  ok   牙 {name}  只点亮 {part}"
                    f"（{sum(0 if r['ok'] else 1 for r in payload['res'] if r['part'] == part)}"
                    f" 条）")
            else:
                say(f"  FAIL 牙 {name}  期望只点亮 {part}，实际 {sorted(lit) or '一条都没亮'}"
                    f"（拆了守卫还全绿 = 判据是装饰）")
                # 多亮/少亮的那些判据自己说的话比猜测有用：把失败判据连 extra 一起打出来。
                for r in payload["res"]:
                    if not r["ok"]:
                        say(f"        {r['part']} {r['label']}  {r['extra'][:400]}")
                ok_here = False
        finally:
            shutil.rmtree(d, ignore_errors=True)
        return ok_here, "\n".join(lines)

    lock = threading.Lock()

    def work(name):
        ok_here, text = one_tooth(name)
        with lock:                       # 整颗牙一个块，别人的行不会插进来
            print(text, flush=True)
        return ok_here

    if jobs <= 1:
        verd = [work(n) for n in names]                  # 老行为：严格顺序、输出顺序固定
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
            verd = list(ex.map(work, names))             # 谁先跑完谁先打，颗数一条不少
    allok = all(verd)
    print("TEETH PASS" if allok else "TEETH FAIL")
    return 0 if allok else 1


def main():
    argv = sys.argv[1:]
    if argv[:1] == ["--child"]:
        if len(argv) < 3:
            raise SystemExit("用法：--child <fixture> <out.json> [--upto \"PART 6\"]")
        rest = argv[3:]
        if rest[:1] == ["--upto"]:
            set_upto(rest[1:])
        _child(argv[1], argv[2])
        return 0

    ap = argparse.ArgumentParser(description="Flet 面板：组窗 / 泵 / 按键 / 夹取 / 隔离")
    ap.add_argument("--teeth", nargs="*", metavar="名字",
                    help="把五十二颗牙逐个改回修前的原文（临时副本），每个必须只点亮自己那一关；"
                         "给名字（可多个）就只拆那几条，不给名字拆全部")
    ap.add_argument("--upto", nargs="*", metavar="关",
                    help="跑到第几关为止（写 6 或 'PART 6' 都行）。改动只落在某一关时用它，"
                         "控制组从 36 s 降到前缀的时间。给了 --teeth 名字时会自动收窄到"
                         "那颗牙自己那一关")
    ap.add_argument("--jobs", type=int, default=4, metavar="N",
                    help="--teeth 时几颗牙同时在跑（默认 4 = 实测上限；1 = 严格串行，"
                         "输出顺序与从前一样。4 并发全拆 52 颗约 7 min（43 颗时实测 384 s），2 并发（31 颗时 562.8 s），"
                         "串行约 15.6 min；6 并发会把 PART 10 那几条窗口尺寸判据挤成假红）")
    args = ap.parse_args()

    t0 = time.time()
    bad = set_upto(args.upto or [])
    if bad:
        print(f"FAIL 没有这些关 {sorted(str(b) for b in bad)}" + chr(10)
              + "现有：" + "、".join(PARTS))
        return 1
    if args.teeth is not None:
        only = args.teeth or None
        if only and UPTO is None:
            # 只拆一颗牙时，控制组也只跑那一关 —— 一颗牙从 7 min 降到 1 min 级。
            parts = sorted({TEETH[n][0] for n in only if n in TEETH}, key=PARTS.index)
            if parts:
                set_upto([parts[-1]])
                print(f"--upto 收窄到 {parts[-1]}（牙自己那一关）")
        print(f"fletpanel --teeth  {'、'.join(only) if only else '五十二颗牙逐个拆掉重放'}")
        return _teeth(only, jobs=max(1, args.jobs))

    print("fletpanel  Flet 面板真的组起来、泵真的搬事件、按键与路径都对（真窗口）"
          + (f"  [--upto {UPTO}]" if UPTO else ""))
    payload, log = _once()
    if not payload["res"]:
        print(f"  FAIL 子进程一条判据都没写出来（退出码 {payload['rc']}）：\n{log[-2000:]}")
        return 1
    if log.strip():
        print("  （子进程输出）" + log.strip().replace("\n", "\n  "))
    ok, bad = _report(payload)
    if not ok:
        print(f"PART fletpanel FAIL：{len(bad)} 条判据没守住")
        return 1
    print(f"ALL PASS（{time.time() - t0:.1f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
