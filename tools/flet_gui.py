# -*- coding: utf-8 -*-
"""Hyoushi 面板（Flet / Material 3）。

  - 业务逻辑**一行不改**，全在 `tools/panel_core.py`（它不 import 任何 GUI 框架）；
  - 本文件是**视图层**：把状态画出来、把事件转成 core 调用、把 `core.q` 里的消息画出来；
  - 设计语言是 Material 3。唯一的 token 出处是 `tools/m3_theme.py`，它的值来自
    `tools/m3_tokens.json`，由 `tools/gen_m3_tokens.py` 用 M3 规范的种子算法算出 ——
    所以这里**不写死任何颜色、字号、圆角、间距**，一律 `T.xxx`。

下面这份名单是这个面板的方法面，`tools/probes/fletgui.py` 第 6 关逐个钉住：

    build / _build_start / _build_pick / _build_last_run / _build_run / _build_log /
    _build_history / _build_settings /
    show_tab / load_manifest / reload_songs /
    selected_chart_id / _render_diffs / select_diff / refresh_start_state / _save_defaults /
    refresh_policy / _save_appearance / _refresh_font_hint / _save_font / _save_autoclean /
    refresh_data / refresh_cfg_info / load_history / update_tally / set_hist_filter /
    _on_hist_select / open_shot / open_diag / export_history / _write_line / set_log_filter /
    clear_log /
    pump_loop / _set_phase / _notify_result / _refresh_ap_marks / auto_clean / start_run /
    force_kill / _confirm_stop_round / _follow_target / _verify_target / cleanup_junk。

五页：**单人演出**（左栏只有选曲；右栏是运行 + 「最近演出」卡，卡里按余量放 N 条）、**多人演出**、**运行日志**、**结算记录**、**设置**
（只剩面板自己的事）。运行日志从前是开始页的右半栏 —— 一局跑起来之后日志是「看着」的东西，
挤在操作旁边只会两样都变小。开始页**自适应、不滚**：左栏的选曲卡吃满整栏、里面的列表
跟着窗口长；右栏的运行卡吃余量，「最近演出」卡按当前页高能放几条放几条，下沿与左卡齐。

原先还有「运行策略」与「链路标定」两张卡（都从设置页搬过来过），2026-10-05 按用户要求
拆掉：三个策略数（正推限制上限 / 每轮断连重试上限 / 演出间隔）直接编进运行卡，链路标定整个
显示不要了 —— 撞到边界的告警照旧落在运行日志页，只是日志里给的是**完整那份**边界文本，
从前得把鼠标停在卡片上的格子上才看得到。每类键提前量那四个输入框也一并删了（读数在
面板里验不了），发射侧的表与 CLI 的 `--kind-lead` 原样留在 `panel_core` / `run.py` 里。

布局走 M3 的窗口尺寸类：expanded（≥840）用「导航栏 + 内容」，medium（600–839）把导航栏
收成只有图标的窄轨，compact（<600）把开始页的两栏叠成一栏。
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
import queue
import subprocess
import sys
import time
import traceback

import flet as ft

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import m3_theme as T          # noqa: E402
import panel_core as core     # noqa: E402
import retention              # noqa: E402
import rlog                   # noqa: E402

# 泵的节拍。run.py 的输出节奏比这慢得多，120ms 只是「看起来是实时的」。
PUMP_MS = 120

# 「自动滚动」开关翻面之后，等客户端把新元素树挂上再复位位置的那一拍（毫秒）。见 `_build_log`
# 里的 `_auto`：`auto_scroll` 会换掉滚动控件的元素树形状（多/少一层 `NotificationListener`），
# 子树重建会把滚动位置丢掉。复位必须晚于那一帧，早于肉眼能分辨的一跳 —— 80ms ≈ 5 帧。
LOG_PIN_SETTLE_MS = 80

# 日志行的语义色。键就是 core.q 里那些 kind。
LOG_KIND = {
    "log": "text",
    "log_err": "danger",
    "log_ok": "ok",
    "log_hdr": "accent",
    "log_dim": "zero_dim",
}

# 产品名（2026-10-20 用户 m52256/m52273 定：就叫 Hyoushi，**不加副标题**，细节看 docs/）。
# 窗口标题与侧边栏标题都从这里取，别再写裸字符串。
APP_NAME = "Hyoushi"
APP_TITLE = f"{APP_NAME} · 自动演奏"

# 页签下标：单人演出 0 / 多人演出 1 / 运行日志 2 / 结算记录 3 / 设置 4。
# 2026-10-08（用户 m02832）之前只有四页（开始 / 日志 / 结算记录 / 设置），多人演出插在单人
# 演出之后 ⇒ 后三页整体后移一位。**键盘与 `_search_box` 之类的地方不许再写裸数字**：
# 这一份是唯一的口径，`fletviewcheck.TABS` / `fletpanel` 第 10 关照着它改。
TAB_SOLO, TAB_MULTI, TAB_LOG, TAB_HIST, TAB_SET = range(5)

TABS = (("单人演出", ft.Icons.PLAY_CIRCLE_OUTLINE, ft.Icons.PLAY_CIRCLE),
        ("多人演出", ft.Icons.GROUPS_OUTLINED, ft.Icons.GROUPS),
        ("运行日志", ft.Icons.ARTICLE_OUTLINED, ft.Icons.ARTICLE),
        ("结算记录", ft.Icons.TABLE_ROWS_OUTLINED, ft.Icons.TABLE_ROWS),
        ("设置", ft.Icons.TUNE_OUTLINED, ft.Icons.TUNE))

# 「本局」读数带的四格：(键, 标签, tooltip)。键就是 `player.play` 经 `#STATUS#` 发出来的那些
# 名字（见 `rlog.Log.status` 与 `player.play` 里那处 `status(...)`）—— 界面只认键，不认日志。
# 该带的用意：一次运行进行到哪、跑得正不正，从前只能去日志流里读那句「演奏 1200/3157 @曲内
# 34.2s … 修正 -45 ms」；数字本来就有，缺的只是**放在眼睛会看的地方**。
STAT_METRICS = (
    ("actions", "动作", "已发动作 / 本局动作总数（动作数不是音符数：长条与滑键各占多个动作）"),
    ("corr", "修正", "实时修正的当前值（正 = 往晚推，负 = 往早拉）"),
    ("late", "迟到", "最近 400 个动作的迟到 p50 —— 这是**调度**误差，不是判定"),
    ("left", "剩余", "本曲还剩多少时间（按末一个动作的曲内时刻算，不是按曲长）"),
)

# 「迟到」那一格什么时候换成告警色。5 ms 与 `player.STALL_MS` 是同一条线 —— 超过它就算迟发，
# 而迟发是「后面每个音都会晚」的唯一前置信号（这比日志里那句「stalls N」早得多地看得见）。
STATS_LATE_WARN = 5.0

# 版式一律走弹性布局：页面的分栏交给 `ft.ResponsiveRow` 的 12 栏栅格（`col={"xs": …, "lg": …}`），
# 宽度由窗口算、窄了自己叠起来；不再有「某个栏写死多少像素」这种只在某个窗口尺寸下才对的做法。

# 换页淡入时插在「透明」与「不透明」两拍之间的一觉。Flet 的属性变化是补丁，客户端下一帧才画 ——
# 两拍落在同一帧里，客户端只看见 1 → 1，动画不会开始。60 ms 在任何刷新率下都够画一帧。
AWAIT_FRAME = 0.06

# 数字框的可接受区间。这里**必须**有这一份：M3 的表单数字是 TextField（`num_field` 那支没有
# 任何 min/max），区间一旦只活在别处，用户手打一个 999 就会真的让 core 等 999 分钟。
# `tools/probes/roundgap.py` 第 2 关与 `fletpanel.py` 第 6 关都盯着这张表。
# 按钮的统一高度。面板里的「按钮」分两族，高度都取官方给的那一个：动作区那四个（`fill()`）取
# filled-button 的容器高 40，选曲卡的难度选择器是 M3 分段控件、取 `T.SEGMENT_H`（也是 40）。
# 出处不同，所以各留各的常量（难度选择器的高度另取 `T.SEGMENT_H`，两者都是 40）。
# **可点区域比可视高大**：两族都套 `hit48()` —— 上下各垫一条 `HIT_PAD` 高的隐形带，可点高
# `T.HIT_MIN`(48)。为什么必须自己补（官方两档目标尺寸 48/44 + Windows 上框架不给那 8 个像素）
# 见 `m3_theme.py` 里 `HIT_MIN` 的注释。
# 两栏并排 → 叠成一栏的**窗口**宽度，取 M3 的 `lg`（桌面档起点 992）。
# 栅格自己的断点**不参与**这个判断：它量的既不是窗口宽度也不是内容宽度，实测同一条
# 换挡路径上翻面点会随「`col` 有没有被重新下发」在 1000~1120 之间飘 —— 于是
# `_apply_window_class` 干脆两边都把 `col` 写死（并排 `{"xs":6}`、叠起来 `{"xs":12}`，
# `xs` 任何宽度都命中）。猜错一点点的代价是实打实的：栅格叠成一栏、我还按并排留着
# `expand`，一屏装不下就切。
STACK_W = 992
# 页面横向被吃掉多少（**实测**，逻辑像素）：导轨 80 + 左右页边距各 `SPACE["lg"]`(16) = 112。
# 谁要用「页宽」推「卡宽」都得先减它：卡宽 = (页宽 − 112 − 列间距 8) × 份数/12。
MULTI_CHROME_W = 112
# 多人页那几枚瓦片里**最宽的一枚控件**要多宽：`opt_tile` 的控件行里最宽的是 `num_field` 的 96
# （「连续演出」「演出间隔」那两枚；开关的轨道 52 比它窄）。
# 一枚瓦片的宽度 = (运行卡宽 − 卡内边距 2×16 − 行内间距) / 这一行的枚数，运行卡宽 =
# (页宽 − `MULTI_CHROME_W` − 列间距 8) × 份数/12。最窄的并排档正好是 `STACK_W`(992)：那时
# 6/12 那侧一格 ≈196（每行两枚、中间一道 12 的间距）—— 放得下 96，余量很宽。
# **历史**：2026-10-09（用户 m12311）这里算的是 152 = 「开关 52 + 空档 4 + 数框 96」，那枚瓦片是
# 「断连重试」，而 992 处 7/12 一格只有 ≈151（差的那 1 px 吃掉 12 的列间距）、6/6 只有 ≈127 ⇒
# 当时 5/12 + 7/12 是**承重**的分法。2026-10-10（用户 m12749）那枚瓦片从多人页拆掉了（房间局
# 不能中途重开），最宽的一枚退成数框 96 ⇒ 算术不再逼着选 5/7；同一天用户 m13525 定「两栏等宽」
# ⇒ 多人页与设置页都改成 6/12 + 6/12。`tools/probes/fletpanel.py` PART 10 仍按这几个数算
# （最窄并排档必须放得下最宽的一枚控件），并把「两栏等宽」钉住。
TILE_MIN_W = 96
BTN_H = 40
# 隐形命中带的高度：上下各一条，把可点区域从 `BTN_H`(40) 补到 `T.HIT_MIN`(48)。见上面那段注释。
# 开关也用它（`hit_switch`）：开关的可视高本来就是官方的 40，补可点区**不能**靠给 `ft.Switch`
# 写 `height` —— 那是等比放大（见 `switch()` 的注释）。
HIT_PAD = (T.HIT_MIN - BTN_H) // 2
# chip 的可视高是官方 `FilterChipTokens.ContainerHeight = 32.0.dp`（视图层不写死高度，这里只是
# 算「补到 48 还差多少」）。它横向**不用补**：最短的标签两个字，chip 本身就有 ≈60 宽 > 48。
CHIP_H = 32
HIT_PAD_CHIP = (T.HIT_MIN - CHIP_H) // 2

# 「最近演出」那两张卡能放几条用的**实测**常数，单位是逻辑像素（本机 DPR 1.4814）：
# `CHROME_H` 是一页被顶栏 / 页边距 / 页脚吃掉的高度（`page.height` − 两栏真正拿到的高度），
# `RUN_NATURAL_H` 是运行卡的自然高度（参数与开关并排之后量的），`RECENT_CHROME_H` 是「最近演出」
# 那张卡自己的标题行与上下内边距，`RECENT_ROW_H` 是一条记录**占**的高度（行自己就是 72，
# 列表行距 0 —— 从前是「64 的行 + 8 的行距」，加起来一样是 72，但那 64 会把 56 的封面压扁），
# `RECENT_POOL` / `RECENT_POOL_MULTI` 是最多建几条（放几条由 `_sync_last_cards` 按当前页高算，
# 所以这只是**上限**，不是屏上真会出现的条数）：单人页 6、多人页 15 —— 多人页左边那张卡与单人页
# 同一张，只是列另一半记录，条数上限分开定：2026-10-09（用户 m12311）定 15，2026-10-10（用户
# m14172「既然加滑动条那还是把上限改成10吧」）曾改成 10，同一天（用户 m14308「还是改回15吧」）
# 改回 15 —— 那张卡现在是撑满 + 自己滚的，条数只决定列表有多长，不再决定「看得见几条」。
# 实测：128（1180×780 上 `page.height` 742.67 − 右栏 615.25，被页框吃掉 127.67 → 128）
# / 464 / 64 / 72。`RUN_NATURAL_H` 最近一次是 2026-10-05 从 376 提到 448：密度改回 `STANDARD`
# 之后四枚数框从 48 逻辑长到官方 56，运行卡内容实测长高 28.4 逻辑（两枚发丝线 y560 → y602），
# 卡的自然后高约 442 —— 旧的 376 会让「最近演出」卡照旧占 2 行、运行卡只剩 412 逻辑，
# 实拍第二行按钮被裁掉 19 px（不是挤小）。2026-10-07（用户 m20246）动作区两行各套了上下
# `HIT_PAD` 的隐形命中带（可点高 48、可视仍 40）⇒ 卡又长高 2×8 = 16，448 → **464**。
# 2026-10-07（用户 m21537/m21635）运行卡里那六颗开关也按 2 级「触摸目标 48」补可点区
# （可视仍是官方的 40 —— 包壳加的是上下各 4 的内边距，开关自己一个高度都不给）⇒ 第 ② 行
# 那四枚瓦片各长高 8，464 → **472**。
# 判错的代价不对称：报小了会把按钮裁掉，
# 报大了只是少显示一条记录（看不出来）。一律向上取整，取 8 的倍数。
CHROME_H = 128
RUN_NATURAL_H = 472
RECENT_CHROME_H = 64
# 一条记录的**定高** = 官方两行列表项的容器高（`list-item-two-line-container-height`）：
# `_sync_last_cards` 用整除算条数，每行就是这么多（行距 0，行本身定高 `RECENT_ROW_H`）。
RECENT_ROW_H = 72
RECENT_POOL = 6
RECENT_POOL_MULTI = 15
# 「最近演出」每行左边那格封面：取 M3 列表里「leading image」那一档 56（图片与头像在规范里是两档，
# 40 那档是头像、给的是选曲列表的 `T.AVATAR`）—— 56 × 56 加上下各 8 内边距正好是 72 的行框
# （官方那对常数就是这么配的：两行项 72 / leading image 56）。
RECENT_ART = 56
# 设置页上面那两张卡（「面板」/「资源」）**并排时**的等高：右卡内容比左卡少，不钉高就是一高一低
# （2026-10-10 用户 m15291 要「横平竖直贴边对齐」；实测左卡自然高 380.0 逻辑、右卡 315.2 ——
# 下沿差 64.8）。为什么不走 `vertical_alignment=STRETCH`：那一页的外层 Column 是**可滚的**
# （`scroll=ScrollMode.AUTO`）⇒ 主轴无界，ResponsiveRow 一拉伸整页就渲染不出来（实拍
# `research/frames/set_now.png` 只剩 96.73% 的页面底色，两张卡连一个像素都没画出来）。
# 所以改成钉一个实测高度，**叠栏时撤掉**（`_apply_window_class` 换挡那一处）：纵向堆叠时一高一低
# 看不出来，而窄窗里文字会换行、钉死反而会溢出。
# 代价：这是跟着内容走的常量 —— 两张卡里加/减一行、或者换字体，都要重新量
# （`research/experiments/cardspan.py <png> <x0> <x1>` 逐行数卡片色）。
SET_CARD_H = 380
NUM_RANGE = {
    "runs": (1.0, float(core.RUNS_MAX)),
    "push_cap_ms": (0.0, float(core.PUSH_OFF_MS)),
    "retry_cap": (0.0, 20.0),
    "gap_min": (0.0, float(core.GAP_MAX_MIN)),
    # 每类键的提前量（用户 m15057）。±60 是**按判定窗定的**：PERFECT 只有 ±50 ms，
    # 再往两头挪就不是「微调」而是换一种打法了；面板上那四个框是带符号的整数毫秒。
    "kind_tap": (-60.0, 60.0),
    "kind_flick": (-60.0, 60.0),
    "kind_long": (-60.0, 60.0),
    "kind_trace": (-60.0, 60.0),
    # 尾判滑键（用户 m52916）：**只往早的方向**（0..60）—— 负数会把那一记滑键推到尾巴之后，
    # 那不是微调而是另一种打法；0 是有意义的一档（关掉这段提前量，回到 2026-10-19 之前）。
    "tail_lead": (0.0, 60.0),
}

# 多人演出页那颗难度分段控件的取值 —— 就是 `tools/run.py --diff` 认的四个词，顺序也照它
# （`run.py` 的 `choices=("easy","normal","hard","expert")`）。视图层不许 import `run.py`
# 或 `gameread`（那两个是会碰设备/语料的那半边），所以这里自己列一份。
MULTI_DIFFS = ("easy", "normal", "hard", "expert")

# 种类偏移的四枚瓦片（用户 m15057「把四种都放出来」；2026-10-10 用户 m15291 从「演奏提前量」
# 改名「分类偏移」，2026-10-21 用户 m53176 再改 **「种类偏移」** —— 前一个名字与选曲页那个
# 「分类」下拉（乐队分类筛选）撞名，会被读成「按曲目分类调偏移」）。顺序与 `core.KIND_LEAD_MS` 一致，键名也就是状态里
# `defaults["kind_lead"]` 的键名与 `--kind-lead` 认的种类名（命令行那个参数名没改，改名只改
# 人看的字）。
# **正数 = 更早按下**（`player.build_actions` 的 `seq = [(t - lead, …)]`），所以 tooltip 必须
# 把方向说出来 —— 这个符号方向靠猜是猜不出来的。
KIND_TILES = (
    ("tap", ft.Icons.TOUCH_APP, "白键 tap",
     "白键的偏移（ms）。正数 = 更早按下，负数 = 更晚。\n"
     "整类的每一次按下一起动，不会只动某一颗。"),
    ("flick", ft.Icons.SWIPE, "滑键 flick",
     "滑键的偏移（ms）。正数 = 更早，负数 = 更晚。\n"
     "整条序列（按下 → 两段滑 → 抬手）一起动。"),
    ("long", ft.Icons.HORIZONTAL_RULE, "长条 long",
     "长条的偏移（ms）。正数 = 更早，负数 = 更晚。\n"
     "整条序列（头 → 每个航点 → 尾判抬手）一起动，不会把尾判留在原地。"),
    ("trace", ft.Icons.GESTURE, "引导 trace",
     "引导键的偏移（ms）。正数 = 更早，负数 = 更晚。"),
)


def clamp_num(key, raw, fallback=0.0):
    """把输入框里的字面值收进 `NUM_RANGE`；读不成数字就用 fallback。返回值一定是 float。"""
    lo, hi = NUM_RANGE.get(key, (None, None))
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return float(fallback)
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return float(v)


# ---------------------------------------------------------------- 小件

def txt(value, tk, role="n", color=None, weight=None, selectable=False, **kw):
    """M3 文本阶梯里的一格。role 是面板自己的四档：s / n / b / t（见 m3_theme.FONT_ROLE）。

    **也可以直接给规范里的角色名**（`"titleSmall"`、`"bodyMedium"`…）—— 结算表的表头与格子就是
    官方那两档、不在面板自己的四档里（`T.HIST_HEAD_FONT` / `T.HIST_CELL_FONT`）。

    **不写家族名**：让 `ft.Theme.font_family` 决定它，设置页换字体才能立刻生效
    （写死家族名的 TextStyle 不再看主题了）。等宽的日志行是唯一例外，见 `_log_line`。
    """
    st = T.type_style(T.FONT_ROLE.get(role, role))
    st.color = tk.text if color is None else color
    if weight is not None:
        st.weight = weight
    return ft.Text(value, style=st, selectable=selectable, **kw)


def card(tk, content, title=None, padding=None, box=None, icon=None, **kw):
    """M3 的 **elevated card**：`surface_container_low` + level-1 高度 + 12 圆角。

    **容器色与高度是配对的，不能只挑一半**：M3 三种卡分别是 filled（`surface_container_highest`
    配 0 高度）、elevated（`surface_container_low` 配 level 1）、outlined（`surface` 配
    `outline_variant` 描边）。从前这里是「`surface_container_low` + 无边 + 无高度」—— 三种
    一种都不算（docstring 却写着 filled），`m3_theme.ELEVATION` 那一层也因此从没被用过。
    现在走真控件 `ft.Card`，高度取 `T.elevation("level1")`。

    内边距取 **16**：官方 cards specs 的表里就是 `Left/right padding 16dp`（从前写的是 12，照
    用户 m08726「严格按照官方的设计参数」改回）。卡与卡之间的间距同理 —— `ft.Card` 自带 4 的
    margin，与栅格的 12 叠成实测 20，规范写的是 `Padding between cards 8dp max` ⇒ 这里把 margin
    归零，间距完全交给外层栅格 / Column 的那一档（现在是 8）。

    `ft.Card` **没有 `padding` 字段**，所以内边距留在里面那层 Container 上；`**kw` 也归那层
    （可点、墨迹、tooltip 都是内容的属性），要写给卡片本身的东西（`expand` 这类）走 `box`。

    `icon` 是卡片标题左边那个小图标（M3 的卡片标题常带一个 leading 图标）。每张卡各给一个，
    整页就有了「一眼认出这张卡是干什么的」的锚点；尺寸取 24 —— 官方 list 的 leading-icon 就是
    24（`T.ICON_LG`，探针第 6 关逐格对过），从前写的是 20。

    **卡名要解释什么，写在 `content` 的第一行（支持文本），不要塞进标题行**（2026-10-21 用户
    m53608「这个说明放这里有没有违反 M3 标准，感觉有点奇怪」）：M3 的卡片解剖是「标题 + 支持
    文本**上下叠**」，标题行只放**标题与尾部动作（图标按钮）**。把一整句说明横在标题右边既不是
    规范里的版式，也把正文挤到标题那一档字高上、还被省略号截断 —— 读起来就是「贴了个便签」。
    支持文本用 `txt(..., "n", color=tk.text_dim)`（bodySmall + `onSurfaceVariant`），跟 `kind_hint`
    一类同档；它比标题行多占一档行高 + 8 的间距，够不够得看那页的余量（设置页 2026-10-21 量过：
    并掉一整行瓦片之后富余约 57 逻辑，放得下）。
    """
    pad = padding if padding is not None else T.SPACE["lg"]
    kids = []
    if title:
        head = [txt(title, tk, "t", color=tk.text)]
        if icon is not None:
            head.insert(0, ft.Icon(icon, size=T.ICON_LG, color=tk.accent))
        kids.append(ft.Row(head, spacing=T.SPACE["sm"],
                           vertical_alignment=ft.CrossAxisAlignment.CENTER))
    kids.append(content)
    inner = ft.Container(
        content=ft.Column(kids, spacing=T.SPACE["sm"], tight=True) if title else content,
        padding=ft.Padding(pad, pad, pad, pad),
        **kw)
    opts = {"margin": 0}
    opts.update(box or {})
    return ft.Card(
        content=inner,
        variant=ft.CardVariant.ELEVATED,
        elevation=T.elevation("level1"),
        bgcolor=tk.card,
        shape=ft.RoundedRectangleBorder(radius=T.radius("card")),
        **opts)


def field_label(text, tk):
    return txt(text, tk, "n", color=tk.text_dim)


def hairline(tk, horizontal=True):
    return (ft.Divider(height=1, thickness=1, color=tk.border) if horizontal
            else ft.VerticalDivider(width=1, thickness=1, color=tk.border))


def nudge(ctl):
    """把控件的变化推给 Flutter；控件已经不在页面上就什么都不做（返回 False）。

    `Control.update()` 在控件脱离页面时会抛
    `RuntimeError('Control must be added to the page first')`。退场动画是 `await` 之后才收尾的
    （`_fade_out_card` 要睡 `MOTION["card_out"]` = 200 ms），这中间若碰上整页重建
    （换页 / 换挡 / 换主题 / 刷新清单），那颗卡或那一行可能已经不在树里。
    真窗口里几乎撞不到，但撞到时它是一条从 Future 回调里冒出来的 traceback，
    这一趟淡出就会半途而废（淡到 0 却没有收走）—— 吞掉更干净。

    这不是判据，是接线上的保险：控件不在台上，本来就没有「推给 Flutter」这件事可做。
    """
    try:
        ctl.update()
        return True
    except RuntimeError:
        return False


def scroll_when_needed():
    """滚动条只在滚动 / 悬停时露面（**别再用 `ScrollMode.ADAPTIVE`**）。

    `ScrollMode.ADAPTIVE` 在 Flet 里映射成
    `ft.Scrollbar(thumb_visibility=page.web or not page.platform.is_mobile())`
    ⇒ 面板跑的是 Windows 桌面（既不是 web 也不是手机），这一条**恒为 True**，
    那条 8dp 的拇指就永远挂在边上 —— 用户 m14308 看到的「这个滚动条怎么常显的，
    太丑了」就是它（`ScrollMode.ALWAYS` 的等价物）。`ScrollMode.AUTO` 不带这个
    覆盖，可它又会在手机上把条加粗成 4dp；所以这里给显式配置。

    `thumb_visibility=False` 回到 Flutter `RawScrollbar` 的默认行为：滚动时淡入、
    停手约 600ms 淡出、鼠标悬停也出现 —— 滚动本身照旧（内容装得下就不滚）。
    厚度 / 颜色 / 圆角仍由主题层 `scrollbar_theme` 一处说了算，这里不重复。
    每个用到的地方都得**新建一个**（Flet 控件不能挂到两个父节点上）。
    """
    return ft.Scrollbar(thumb_visibility=False)


def input_border(tk):
    """M3 输入框的描边：静息 `outline` 1dp、聚焦 `primary` 2dp（androidx
    `OutlinedTextFieldTokens.kt`：`OutlineColor=Outline` / `OutlineWidth=1.0.dp`、
    `FocusOutlineColor=Primary` / `FocusOutlineWidth=2.0.dp`，形状 `ContainerShape=CornerExtraSmall`
    = 我们的 4dp）。

    **别拿 `tk.border` 当输入框描边** —— 那是 `outline_variant`，M3 里给分界线用
    （`DividerTokens.Color = OutlineVariant`，本文件的 `hairline()` 正是这么用的）。从前静息态写的是
    `tk.border`，实拍（DPR 1.5、480×380 裸窗）描边 `#45464f` / `#c6c5d0` = outline_variant，
    与官方 `Outline`（`#90909a` / `#767680`）不是一档；聚焦态也只换色没换宽（两枚框的描边像素数
    完全一样 ⇒ 都只有 1dp），官方聚焦要 2dp。

    **不要用 `border_color` / `focused_border_color` / `border_radius`** —— 这三个字段在 Flet 里
    已经标注为 deprecated（`flet/controls/material/form_field_control.py:234-306` 的
    `Annotated[..., deprecated(...)]`，官方给的替代就是 `border=OutlineInputBorder(...)`
    与按 `ControlState` 分状态给边框）。**运行时一条警告都不报**（实测 `warnings.catch_warnings`
    收不到任何东西），所以这一条是「照规范写」，不是「修报错」。
    """
    r = T.radius("field")
    return {
        ft.ControlState.DEFAULT: ft.OutlineInputBorder(
            side=ft.BorderSide(1, tk.outline), border_radius=r),
        ft.ControlState.FOCUSED: ft.OutlineInputBorder(
            side=ft.BorderSide(2, tk.accent), border_radius=r),
    }


def num_field(tk, value, on_change, step=1.0, suffix="", width=96, decimals=2):
    """数字输入。用 TextField 而不是 Stepper：M3 没有独立的数字步进器，
    表单里的数字就是 text field（`keyboard_type` 给数字键盘）。

    **不给 `bgcolor`**：这里的边框是 `OutlineInputBorder`，那就是 M3 的 **outlined** 变体，
    规范里 outlined 输入框不铺底（铺底的是 filled 变体，而 filled 只留一条底线）。从前这里
    给 outlined 描边又铺 `surface_container_highest` 的底，两种变体各取一半。

    **不写 `dense=True`**：规范给 outlined 输入框的容器高就是 **56**
    （`OutlinedTextFieldTokens.ContainerHeight = 56.0`，规格表 `Container height 56dp`）。
    `dense` 是 Flutter 收内边距的开关，会把 56 压到 48（实拍 48.6）；照 m08726 去掉。

    **字号也照官方点名**：官方 `OutlinedTextFieldTokens.InputFont = TypographyKeyTokens.BodyLarge`
    （源文件第 161-162 行），标签也是 BodyLarge、辅助文字是 BodySmall。这一档不是口味问题：
    Flet 画出来的盒子高 = 文字行高 + 上下 16 内边距，`bodyMedium`（行高 20）只画到 52
    （实拍 53.3，多出的 1.35 是描边反锯齿），`bodyLarge`（行高 24）正好 56，与 `T.FIELD_H`
    对得上。下拉与选曲搜索框同一档。

    **宽度不是规范量**（用户 m09165「输入框应该再长一点点」）：`OutlinedTextFieldTokens` 里只有容器高、内边距、字号与图标尺寸，**没有 width** —— 宽度由版式定。四枚数框一律 96，让 ` ms` / ` 轮` 这些后缀跟数字不在同一格里挤；最宽的一枚瓦片 52 + 4 + 96 = 152，仍装得进两栏分界处那半格（`m3tokens.py` 冻的 `HALF_CELL_MIN = 160`）。
    """
    return ft.TextField(
        value=(f"{value:.{decimals}f}" if decimals else str(value)),
        suffix=(ft.Text(suffix, style=T.type_style("bodySmall")) if suffix else None),
        width=width,
        height=T.FIELD_H,
        text_align=ft.TextAlign.END,
        keyboard_type=ft.KeyboardType.NUMBER,
        border=input_border(tk),
        text_style=T.type_style("bodyLarge"),
        on_change=on_change,
    )


def switch_colors(tk):
    """M3 开关的四色（规范：选中手柄 `on_primary`、选中轨道 `primary`、未选中手柄
    `outline`、未选中轨道 `surfaceContainerHighest`）。

    **只写 `active_color` 是不够的** —— 那只是手柄色，轨道交给了 Flutter 的默认推导：
    实测开态轨道会画成 primary 的 **50% 透明度**（#b7c4ff 叠在暗底上 = #696f90），而手册要的
    是不透明 `primary`。四色都点名之后，开态与关态都与手册一致（关态本来就与 Flutter 的 M3
    默认相同，写出来只是不让它随版本漂）。几何出自 androidx `SwitchTokens.kt`（轨道 52×32、
    触摸目标 48），四色字段名与这条算式由 `tools/probes/m3tokens.py` 第 7、10 关钉住。
    """
    return {
        "active_color": tk.on_accent,
        "active_track_color": tk.accent,
        "inactive_thumb_color": tk.outline,
        "inactive_track_color": tk.field,
    }


def switch(tk, label, value, on_change, tooltip=None):
    """带文字的 M3 开关。**这里一个高度都不给**：开关可视就是官方的 40（轨道 52×32）。

    2026-10-07（用户 m21537/m21635）给开关写过 `height=T.HIT_MIN`(48) 想补可点区，实测**不
    成立**：Flet 把 `height` 当缩放目标，整个开关按 `48/40` 等比放大（真窗口量：轨道从官方
    52×32 变成 61.33×37.33 逻辑；`height=40` 才与自然态逐像素同级）⇒ 补可点区只能在布局点
    包一层（`hit_switch`）。Windows 上 Flutter 本来取 `shrinkWrap` 档、只给 40
    （`theme_data.dart:400-409`），而 Flet 的 `Switch` 没有 `MaterialTapTargetSize` 那一类字段
    （`get_api("Switch")` 里没有），没法让框架自己补。理由与出处见 `m3_theme.HIT_MIN`。
    """
    return ft.Switch(label=label, value=bool(value), on_change=on_change,
                     tooltip=tooltip, label_text_style=T.type_style("bodyMedium"),
                     **switch_colors(tk))


def toggle(tk, value, on_change, tooltip=None):
    """不带文字的 M3 **开关**（m06250 把五颗勾选框都换成了它）。

    文字由调用方摆在自己那一格的最左边：`ft.Switch` 与 `ft.Checkbox` 一样是贪心控件，
    单独放进一行就把宽度全吃掉，所以设置行的写法是「图标 + 标签 + 弹性空隙 + 开关」。

    颜色一律走 `switch_colors()`（四色点名，见那里的注释）。

    高度一个都不给（理由见 `switch()`：给了就是等比放大，不是补可点区）—— 可点高由布局点
    那层 `hit_switch()` 补。
    """
    return ft.Switch(value=bool(value), on_change=on_change,
                     tooltip=tooltip, **switch_colors(tk))


def dropdown(tk, options, value, on_select, width=None, expand=False, tooltip=None):
    """``width`` 是给「宽度本来就固定」的窄控件用的；能跟着窗口走的场合一律 ``expand=True``
    —— 选曲那两个下拉从前写死 140，宽窗口下也是 140，白占一行还挤。

    与 `num_field` 同一条：outlined 变体不铺底、不写 `dense=True`、字取官方
    `InputFont = BodyLarge`（容器高 56 就是这一档撑出来的，见那里的注释）。
    """
    return ft.Dropdown(
        options=[ft.DropdownOption(key=k, text=v) for k, v in options],
        value=value,
        width=width,
        height=T.FIELD_H,
        **_exp(expand),
        tooltip=tooltip,
        border=input_border(tk),
        text_style=T.type_style("bodyLarge"),
        on_select=on_select,
    )


def button(tk, label, on_click, kind="text", icon=None, tooltip=None, disabled=False,
           danger=False):
    """M3 的三种按钮：filled（主操作）/ tonal（次操作）/ outlined / text（第三级）。

    **`danger=True` 换 error 角色**（描边 + 字色）：M3 不用 primary 表达「会毁掉东西」的动作。
    从前「本轮停止」与「强制终止」长得一模一样，看不出哪一个更狠（审查报告第 6 节）。
    **字色与描边逐档写**（`DEFAULT` = error、`DISABLED` = 规范给禁用态那两档）—— 平铺一个
    值会被当成「所有状态都用它」，禁用时照样发红（用户 m07990：「强制停止为什么常亮」）。
    """
    kw = dict(content=label, on_click=on_click, tooltip=tooltip, disabled=disabled)
    if icon:
        kw["icon"] = icon
    if kind == "filled":
        ctl = ft.FilledButton(**kw)
    elif kind == "tonal":
        ctl = ft.FilledTonalButton(**kw)
    elif kind == "outlined":
        ctl = ft.OutlinedButton(**kw)
    else:
        ctl = ft.TextButton(**kw)
    if danger:
        # 这两个字段是 `ControlStateValue`：只给一个值等于「所有状态都用它」（Flet 把它包成
        # MaterialStatePropertyAll），于是按钮 `disabled=True` 时照样写红字、描红边 —— 空闲时
        # 「强制终止」看着一直是亮的（实测暗色 #ffb4ab / 浅色 #ba1a1a 一直挂着，而同一批被
        # 禁用的「本轮停止」已经压到 on_surface 38%）。DISABLED 两档取规范给禁用态的 38% / 12%。
        ctl.style = ft.ButtonStyle(
            color={ft.ControlState.DEFAULT: tk.danger,
                   ft.ControlState.DISABLED: tk.disabled(tk.text)},
            side={ft.ControlState.DEFAULT: ft.BorderSide(1, tk.danger),
                  ft.ControlState.DISABLED: ft.BorderSide(
                      1, tk.state(tk.text, "disabled_container"))})
    return ctl


def chip_button(tk, label, selected, on_click, tooltip=None):
    """M3 filter chip。

    **选中状态写在控件上**（`selected=` + `selected_color`），不是建完再手刷底色：手刷的时候
    控件与无障碍树都不知道自己选没选中，M3 的选中勾（`show_checkmark`）也就画不出来 ——
    从前这里 `show_checkmark=False`、选中态靠改 `bgcolor`/`border_side` 顶出来。文字色同理：
    在 `secondary_container` 上写 `on_surface` 是不配对的一对，M3 要 `on_secondary_container`。
    未选中态不铺底（透明）配 `outline_variant` 描边 —— 从前铺 `surface_container_highest`，
    比它所在的卡片还高一档，看着像按钮而不是筛选器。

    内边距取 **8**：官方 `Chip.kt` 的 `ContentPadding = 8.dp`（规格表 chip 也是 8；从前写 12）。
    高 32 不写死 —— 框架按 `ContainerHeight = 32.0` 自己给（标准密度档下）。

    **未选中不铺底、选中不描边**（两处都照官方）：官方 `_FilterChipDefaultsM3` 里 `color` 在 flat
    变体未选中时返回 `null`（= 透明），`side` 在选中时返回 `Colors.transparent`；
    `FilterChipTokens.kt` 也只有 `FlatSelectedContainerColor` 与 `FlatUnselectedOutlineColor` 两条，
    正好对上。Flet 的 `border_side` 是**单个** `BorderSide`（不是按状态分档的值），所以建的时候与
    `paint_chip` 两处都得跟着 `selected` 换 —— 统一走 `tk.chip_side()`；选中态给「透明 1dp」而不是
    `None`，为的是**不动布局**（描边占位一样宽，只把颜色隐掉）。「不铺底」那句写在 `chip_theme`
    的 `bgcolor` 上（视图层不许出现 `ft.Colors`，所以透明也由令牌层给）。
    """
    return ft.Chip(
        label=ft.Text(label, style=T.type_style("labelLarge"),
                      color=tk.on_secondary_container if selected else tk.text_dim),
        selected=bool(selected),
        selected_color=tk.secondary_container,
        on_click=on_click,
        tooltip=tooltip,
        show_checkmark=True,
        check_color=tk.on_secondary_container,
        border_side=tk.chip_side(selected),
        shape=ft.RoundedRectangleBorder(radius=T.radius("chip")),
        label_text_style=T.type_style("labelLarge"),
        padding=ft.Padding(T.SPACE["sm"], 0, T.SPACE["sm"], 0),
    )


def paint_chip(tk, chip, on):
    """把一个 filter chip 画成选中/未选中 —— 与 `chip_button` 建的时候同一套口径。

    改状态的地方（日志筛选、结算筛选、计数刷新）都走这里，免得三处各刷一套颜色又慢慢走散。
    """
    chip.selected = bool(on)
    chip.label.color = tk.on_secondary_container if on else tk.text_dim
    chip.border_side = tk.chip_side(on)


def slot(ctl, align=None):
    """把一个控件放进「与同排其它格子均分一行」的格子里。

    等宽不靠写死宽度，靠父级 Row 把宽度平分（`expand=True`）—— 于是同一列的按钮、复选框、
    难度格、开关行的左右边界永远对得上；`align` 缺省是**居中**（用户 m05361 要的「善用居中
    与均分」）。两个 `slot` 是两半，三个 `slot` 就是三等分 —— 行里没有一处写死的宽度，所以
    窗口多宽都是同一套比例。
    """
    return ft.Container(content=ctl, expand=True,
                        alignment=align if align is not None else ft.Alignment.CENTER)


def half(ctl, align=None):
    """`slot` 的老名字（原来只会对半分）：两个并成一行。"""
    return slot(ctl, align)


def _hit_band(on_click, tooltip=None):
    """一条**隐形**的命中带：`HIT_PAD` 高、没有底色、没有内容，点下去就是 `on_click`。

    为什么会有这种东西：官方给的可点目标最小 48（触屏档；鼠标/笔档 44，见 `T.HIT_MIN`），而面板
    里真按钮的可视高是 40 —— 差的 8 个逻辑像素本来该由框架的 `MaterialTapTargetSize` 补，但
    Flutter 只在 android/fuchsia/iOS 选 `padded`、Windows 选 `shrinkWrap`（`theme_data.dart
    :400-409`），Flet 也没把这个开关暴露出来。于是自己垫：**可视仍是 40**，可点区域上下各多 4。
    """
    return ft.Container(on_click=on_click, tooltip=tooltip, height=HIT_PAD)


def _exp(flag):
    """`expand` 只在**为真**时才写进 kwargs（本项目踩过的一次全页灰屏）。

    Flet 只要看到显式传了 `expand`（哪怕 `False`）就在客户端给这一层包一个 `Flexible`；
    而 `ft.Row(wrap=True)` 在 Flutter 侧是 `Wrap`，它的 parentData 是 `WrapParentData`、
    不是 `FlexParentData` ⇒ 整页被 ErrorWidget 顶掉（2026-10-07 真窗口实测：`type
    'WrapParentData' is not a subtype of type 'FlexParentData' in type cast`，设置页
    「立即清理 / 重启面板」那一排 `hit_pad` 按钮就是触发点）。不传与传 `False` 语义相同。
    """
    return {"expand": True} if flag else {}


def hit48(ctl, on_click=None, tooltip=None, expand=False):
    """把 `ctl` 包成「可视原样、可点高 `T.HIT_MIN`(48)」的一列（上下各一条隐形带）。

    `on_click` 缺省取 `ctl.on_click` —— 动作区那四个按钮走的就是这条路：点上下那两条带与点按钮
    是同一件事（三条的命中区互不重叠，Flutter 的手势竞技场只会有一次生效）。带宽靠父级
    `STRETCH` 撑满，视觉与从前一模一样。用户 m20246 先只给条目点名的那两处套（动作区四按钮 +
    难度分段控件）；2026-10-07 用户 m21537/m21635 把范围扩到**面板里每一个可点控件** ——
    图标按钮与按钮走 `hit_pad`（四边各 4），chip 只补上下（`HIT_PAD_CHIP`），开关走
    `hit_switch`（开关不能写 `height`，那是等比放大）。
    """
    cb = on_click if on_click is not None else getattr(ctl, "on_click", None)
    col = ft.Column([_hit_band(cb, tooltip), ctl, _hit_band(cb, tooltip)],
                    spacing=T.SPACE["none"], tight=True,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    return ft.Container(content=col, **_exp(expand))


def hit_pad(ctl, pad=None, pad_x=None, pad_y=None, on_click=None, tooltip=None,
            expand=False):
    """把 `ctl` 包成「可视原样、可点区域四边各多一圈内边距」的一层。

    与 `hit48` 是同一件事的两种做法：`hit48` 往一列里叠上下两条 `HIT_PAD` 高的**空带**（给
    动作区那四颗要等宽、要 `expand` 的按钮用），这里改用 `padding` —— 一层就够，四边都能补，
    宽度本来不到 48 的控件（图标按钮 40）也能一起补齐。`pad` 给四边同值，`pad_x`/`pad_y` 可
    分开给（chip 只补上下：它的宽本来就 ≥48）。

    `pad` 缺省 `HIT_PAD`(4)：真按钮 40 → 48、图标按钮 40×40 → 48×48。`on_click` 缺省取
    `ctl.on_click`、`tooltip` 缺省取 `ctl.tooltip` —— 点在内边距那一圈上与点控件本体是同一件
    事（内层控件自己的手势优先，只有落在这一圈上才走这里），提示语也不会只有本体有。

    为什么不直接改控件高度：官方那几档高度是**可视**尺寸（按钮 40、chip 32），规范要的是
    **可点**区域 ≥48（2 级「Touch and pointer target sizes」：触屏 48 / 鼠标笔 44，都是
    consider；`foundations/layout/grids-spacing/density` 那句「Accessible targets should
    retain a minimum of 48x48dp」是 should）。`ft.Container` 只有 `ink=True` 才画水波纹 ⇒
    这一层不留视觉痕迹、也不加悬停动画（本项目的红线）。
    """
    px = HIT_PAD if pad_x is None else int(pad_x)
    py = HIT_PAD if pad_y is None else int(pad_y)
    if pad is not None:
        px = py = int(pad)
    cb = on_click if on_click is not None else getattr(ctl, "on_click", None)
    tip = tooltip if tooltip is not None else getattr(ctl, "tooltip", None)
    return ft.Container(content=ctl, padding=ft.Padding(px, py, px, py),
                        on_click=cb, tooltip=tip, **_exp(expand))


def hit_switch(sw):
    """给开关补「可点 48」（可视仍是官方的 40）。

    开关与按钮不同：`ft.Switch(height=T.HIT_MIN)` **不是**只加可点区，而是把整个开关按 `48/40`
    等比放大（2026-10-07 真窗口实测：轨道 52×32 → 61.33×37.33 逻辑；`height=40` 与自然态逐像素
    同级）。所以只能包一层 `padding`：上下各 `HIT_PAD`(4)、横向不动（开关宽本来就 ≥48）。

    落在上下那 4 上的点击要**自己转成一次切换**：开关本体吃自己的手势（手势竞技场里更深那个
    先赢），包壳只管这一圈。合成的不是真事件，所以按本项目两种处理器的读法各喂一次能用的形状
    —— `_save_defaults(self, *_a)` 读 `self.<attr>.value`、`_save_motion(self, e)` 读
    `e.control.value` ⇒ 先改 `sw.value` 再以 `control=sw` 的事件调原 `on_change`。
    禁用态现问现判（`refresh_start_state` 每轮改 `disabled`）。
    """
    def _tap(_e):
        if getattr(sw, "disabled", False):
            return
        sw.value = not bool(sw.value)
        try:
            sw.update()
        except Exception:                                        # noqa: BLE001
            # 还没挂到页上（离线自检）时只改值 —— 与 `refresh_policy` 同一条规矩。
            pass
        cb = getattr(sw, "on_change", None)
        if cb is not None:
            cb(type("E", (), {"control": sw})())
    return ft.Container(content=sw,
                        padding=ft.Padding(T.SPACE["none"], HIT_PAD,
                                           T.SPACE["none"], HIT_PAD),
                        on_click=_tap)


def fill(ctl):
    """把一个控件铺满自己那格，高矮给死 `BTN_H`，**可点高**再垫到 `T.HIT_MIN`（动作区四个按钮）。

    与 `slot` 的差别只在 `alignment`：`slot` 写了 `CENTER`，Flutter 那边 `Align` 会把
    约束**放松**成固有尺寸 —— 孩子按自己的文字宽窄收窄（实测四个动作按钮因此差成
    226 / 157 / 98 / 82 px）；这里**不给 alignment**，`Container` 把紧约束直接转给孩子，
    控件于是被撑到格子大小。用户 m06156：「把这四个按钮做成难度按钮一样的」—— 四个等宽等高、
    四边对齐的格子（难度选择器 2026-10-07 换成官方分段控件之后，这句「一样」指的是**等宽等高**
    这件事，不再是同一类控件）。

    外面那层 `hit48` 是用户 m20246 要的：可视高仍是 `BTN_H`(40)，可点高 48。`expand=True`
    给的是**宽度**（这一列是动作区 `Row` 的孩子，要靠它分半格）。带上的回调每次现问一次
    `ctl.disabled` —— 四个按钮的禁用态是动态的（`refresh_start_state` 每轮改），绑死回调的话
    禁用中的按钮还能从带里点着。
    """
    def band_cb(e):
        if getattr(ctl, "disabled", False):
            return
        cb = getattr(ctl, "on_click", None)
        if cb is not None:
            cb(e)

    return hit48(ft.Container(content=ctl, height=BTN_H), on_click=band_cb, expand=True)


def diff_seg(segs, selected, on_change, tooltip=None):
    """难度选择：M3 的**分段控件**（segmented button），一行四段、等宽、单选。

    官方值一个不落，而且**全由控件自己画**：整组是 corner-full 的胶囊（首尾半圆、中间段直角，
    Flutter 按 `itemShape(index, count)` 现算）、描边 1dp `outline`（选中段也留着）、未选中不
    铺底 + `on_surface` 字、选中 `secondary_container` + `on_secondary_container` 字、字阶
    label-large、段高 40 —— 颜色与字阶写在 `T.theme()` 的 `segmented_button_theme` 里
    （出处见 `m3_theme.py` 那段注释），这里只搭结构。样式里
    **绝不能给 `shape`**：`style.shape` 是整组的外框，一给就四段同形、胶囊没了。

    等宽靠父级：`_build_pick` 把这一条放进 `horizontal_alignment=STRETCH` 的 Column，
    Flutter 在紧宽度下按 `maxWidth / childCount` 分（`segmented_button.dart:958-971`）。

    `allow_empty_selection=True` 是必须的：Flutter 断言 `selected.isNotEmpty || emptySelectionAllowed`
    （`segmented_button.dart:146-148`），而「还没选曲目」那一态本来就没有选中项。单选语义由
    `_on_diff_change` 守 —— 它拒绝把选中项点空。

    用户 m19421「都可以，完全按照官方的来」：排布从自绘的 2×2 换成官方的一行四段。
    **选中对勾不画**（用户 m20246）：官方那条勾的规则前提是「段里同时有图标和文字」，面板四段
    是纯文字，画了只会把文字右推 11.1 dp（实测），所以 `show_selected_icon=False` —— 顺带段上
    标签放回长式「EXPERT Lv26」（撤掉勾之后 112.7 dp 的段内可用宽装得下；全名与等级仍在
    tooltip 与卡底那行曲目信息里）。

    可点高 48 由外面那层壳给（可视仍是 `T.SEGMENT_H` 40）：`_rebuild_diff_hit` 在这个控件
    上下各放一排 `HIT_PAD` 高的隐形命中带，格宽与段宽都平分，点第 k 格就是 `select_diff(k)`。
    """
    return ft.SegmentedButton(
        segments=segs, selected=selected, show_selected_icon=False,
        allow_empty_selection=True, allow_multiple_selection=False,
        height=T.SEGMENT_H, on_change=on_change, tooltip=tooltip)


def opt_tile(tk, icon, label, *trail):
    """运行卡里的一枚瓦片：标签行（小图标 + 名字）在上，控件行在下，两行都从本格左沿起排。

    m06279 重构（用户：去掉运行卡里的二次嵌套底色、允许完全重构内部组件）。原来一行
    是「标签贴左、控件贴右」的清单行，装在一块 `field` 底色的嵌套面板里：半格在 1180
    窗宽下只有 204 逻辑，却要并下 图标 + 标签 + 开关 + 84 宽的数框 ⇒ 窗口一窄就溢出
    （实测窗口 1024 时第三行第二格的数框被挤出窗口，审查报告 P0 那条）。
    竖着排之后最宽的一枚控件是 `num_field` 的 96 逻辑（数框 2026-10-07 由用户要求从 84 加长
    到 96，见 `num_field`）—— 这段算术就是 `TILE_MIN_W` 那段注释（那里记着 2026-10-10 用户
    m12749 拆掉「断连重试」之后，5/12 + 7/12 从「承重」退成「可读性选择」、以及用户 m13525
    定「两栏等宽」这件事）。
    标签也就用回四字全名（「正推限制」「断连重试」），不必再靠 tooltip 猜。

    2026-10-08 从 `_build_run` 的局部函数提到模块级：多人演出页的运行卡用的是同一套
    （`_build_multi_run`），一处定义两处用。
    """
    head = ft.Row([ft.Icon(icon, size=T.ICON_SM, color=tk.text_dim),
                   field_label(label, tk)], spacing=T.SPACE["xs"],
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)
    row = ft.Row(list(trail), spacing=T.SPACE["xs"],
                 vertical_alignment=ft.CrossAxisAlignment.CENTER)
    return ft.Column([head, row], spacing=T.SPACE["xs"], tight=True,
                     horizontal_alignment=ft.CrossAxisAlignment.START)


def opt_line(*tiles):
    """一行里的几枚瓦片：每枚是 `Container(expand=True)`，均分这一行。

    **不给 alignment** —— 给了就被放松成固有宽度居中，格里的空档会漏到格与格之间
    （用户 m05361：宁可内部空白，不许外部空白）。控件行贴着本格左沿，所以三行的控件
    落在同一条竖线上，整块读起来是一个网格而不是三块面板。
    """
    return ft.Row([ft.Container(content=c, expand=True) for c in tiles],
                  spacing=T.SPACE["md"],
                  vertical_alignment=ft.CrossAxisAlignment.START)



def badge(tk, text, kind):
    """结算记录里的判定徽标。色从语义名走：AP=primary、FC=tertiary、漏键=success、异常=error。

    **底色与字色是配对的一对**：`chip_np` 是 `success`，字就得是 `on_success` —— 从前写
    `on_surface`（那是「在 surface 上」的字色），铺在 success 上既不配对，也不保证对比度。
    """
    bg = {"ap": tk.chip_ap, "fc": tk.chip_fc, "np": tk.chip_np, "err": tk.chip_err}.get(kind)
    fg = tk.on_primary if kind == "ap" else (
        tk.on_tertiary if kind == "fc" else (
            tk.on_error if kind == "err" else tk.on_ok))
    if bg is None:
        return ft.Text(text, style=T.type_style("bodySmall"), color=tk.text_dim)
    return ft.Container(
        content=ft.Text(text, style=T.type_style("labelSmall"), color=fg),
        bgcolor=bg, border_radius=T.radius("chip"),
        # 竖向也是 4dp：从前写 1，那个数不在 4dp 栅格上（横向本来就在栅格上）。
        padding=ft.Padding(T.SPACE["xs"], T.SPACE["xs"], T.SPACE["xs"], T.SPACE["xs"]))


def ask(page, tk, title, body, on_ok, ok_label="确定", danger=False, on_cancel=None,
        scrollable=False):
    """M3 的确认对话框。Flet 的对话框不是阻塞的 —— 所以调用方把「确定之后干什么」传进来。

    容器角色 `surface_container_high`、高度 level3（规范给浮起组件的档），圆角 `dialog`（28）。
    `danger=True` 时确认按钮换成 `error` **字色** —— 破坏性操作在 M3 里不用 primary，而且
    对话框的动作是文字按钮（不铺底、不描边，官方 `_md-comp-dialog.scss`）。
    `on_cancel` 只有「有人正等这一按」的场合才用得上（上游比对完等确认的更新链路）；
    `scrollable=True` 交给 Flutter 自己滚（正文长到一屏放不下时用，见规范里的 dialog 一节）。
    """
    def _ok(_e):
        page.pop_dialog()
        on_ok()

    def _cancel(_e):
        page.pop_dialog()
        if on_cancel is not None:
            on_cancel()
    # 对话框的动作是**文字按钮**：官方 `_md-comp-dialog.scss` 的 action-label-text-color =
    # primary、label-large —— 层级交给容器与标题，动作一律退到文字档（从前这里是 filled）。
    confirm = button(tk, ok_label, _ok, kind="text")
    if danger:
        # 破坏性动作在文字档里只换 error **字色**：铺底或描边会把文字档抬成 outlined。DISABLED
        # 一档取规范给禁用态的 38%（同 `button(danger=True)` 那条的理由）。
        confirm.style = ft.ButtonStyle(
            color={ft.ControlState.DEFAULT: tk.danger,
                   ft.ControlState.DISABLED: tk.disabled(tk.text)})
    page.show_dialog(ft.AlertDialog(
        modal=True,
        title=txt_spec(title, tk, "headlineSmall", color=tk.text),
        content=ft.Container(content=txt_spec(body, tk, "bodyMedium", color=tk.text_dim),
                             width=460, padding=ft.Padding(0, T.SPACE["sm"], 0, 0)),
        actions=[hit_pad(button(tk, "取消", _cancel)), hit_pad(confirm)],
        actions_alignment=ft.MainAxisAlignment.END,
        bgcolor=tk.dialog,
        elevation=T.elevation("level3"),
        shape=ft.RoundedRectangleBorder(radius=T.radius("dialog")),
        scrollable=scrollable,
    ))


def toast(page, tk, text, kind="info"):
    """M3 的 snackbar。

    容器是**反色面**（`inverse_surface` / `on_inverse_surface`）—— 规范给 tooltip 与 snackbar
    的就是同一对角色；错误态例外，那是个 error 容器，用 `error` 配 `on_error`。从前 info 用
    `surface_container`（比页面底还暗，看着像塌下去的一个框），错误态用 `error` 底配 `on_surface`
    字（不配对）。
    """
    info = kind == "info"
    page.show_dialog(ft.SnackBar(
        content=ft.Text(text, style=T.type_style("bodyMedium"),
                        color=tk.snack_fg if info else tk.on_error),
        bgcolor=tk.snack_bg if info else tk.danger,
        behavior=ft.SnackBarBehavior.FLOATING,
        elevation=T.elevation("level3"),
        shape=ft.RoundedRectangleBorder(radius=T.radius("snackbar")),
        duration=4000))


def txt_spec(value, tk, spec, color=None, **kw):
    """直接取规范阶梯里的一档。`txt()` 那四档桥（s/n/b/t）不够用时走这里 —— 例如顶部应用栏的
    标题是 `titleLarge`，桥里没有这一档。"""
    st = T.type_style(spec)
    st.color = tk.text if color is None else color
    return ft.Text(value, style=st, **kw)


def empty_state(tk, icon, text, hint=None):
    """空态：居中的图标 + 一句话（+ 一句「接下来怎么办」）。

    三个列表都有空的时候。从前是往容器里塞一行灰字 —— 贴在左上角，看着像没画完。M3 没有
    「空态」这个组件，但列表与设置页的通用做法就是居中、留白、给一句下一步。

    **两行字各就各位**（2026-10-09 M3 审查）：主句是这一段的主内容 ⇒ `on_surface`（`txt` 的
    默认色）；提示句是支撑文字 ⇒ `on_surface_variant`。两行都取 `bodySmall`（`"n"`）——
    从前提示句写的是 `"s"`，那是 `labelSmall`，字阶里给标签（按钮、页签、chip）用的，
    拿来排一整句话是把「标签」当「正文」用；主句从前也铺 `text_dim`，于是整张空态里
    一个 `on_surface` 都没有、主次分不出来。
    """
    # 图标坐在一枚 64dp 的 `secondary_container` 圆上：单个线框图标浮在卡片上没有重量，也与页面
    # 上别处的「有色容器」（chip、进度轨、导航指示条）不是一个语汇；图标色换成官方配对的
    # `on_secondary_container`（同一个角色，见 `SEMANTIC`）。
    kids = [ft.Container(content=ft.Icon(icon, size=T.EMPTY_ICON, color=tk.on_secondary_container),
                         width=T.EMPTY_BADGE, height=T.EMPTY_BADGE, shape=ft.BoxShape.CIRCLE,
                         bgcolor=tk.secondary_container, alignment=ft.Alignment.CENTER),
            txt(text, tk, "n", text_align=ft.TextAlign.CENTER)]
    if hint:
        kids.append(txt(hint, tk, "n", color=tk.text_dim, text_align=ft.TextAlign.CENTER))
    return ft.Container(
        content=ft.Column(kids, spacing=T.SPACE["sm"], tight=True,
                          horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        alignment=ft.Alignment.CENTER, expand=True,
        # 三处空态共用同一档动效：从藏到显时淡入（入口见 `Panel._toggle_empty`）。
        animate_opacity=T.animation("card"))


# 封面缩略图目录。与 `tools/gameread.py` 的 `JACKET_DIR` 是**同一个**目录（那边是给识别器
# 用的 128x128 缩略图）；这里不 import gameread —— 它 import 时会碰 adb，视图层不该拖上它。
JACKET_DIR = os.path.join(core.ROOT, "research", "charts", "jackets")
_JACKETS = {}


def jacket_src(mid):
    """封面文件的绝对路径；没有这个文件就 None。

    **只缓存「有」**：每敲一个搜索字符都会重建整列行，87 次 `os.path.exists` 不必每次都问一遍
    —— 但「没有」不能缓存。面板是长寿命进程，而封面库会在它活着的时候被 `fetch_charts.py`
    补上新歌：从前把 None 也记进 `_JACKETS`，那首歌就永远只显示兜底图标，直到面板重启
    （用户 m28348 报的「新歌封面识别不出来」有这一路）。
    """
    key = str(mid)
    got = _JACKETS.get(key)
    if got:
        return got
    p = os.path.join(JACKET_DIR, key + ".png")
    if os.path.exists(p):
        _JACKETS[key] = p
        return p
    return None


def song_music_id(manifest, label):
    """结算记录里只存了歌名，封面要 `musicId` —— 过一遍清单（87 首）把它找回来。"""
    for s in manifest.get("songs") or []:
        if core.song_label(s) == label:
            return s.get("musicId")
    return None


def jacket_art(src, tk, size=RECENT_ART):
    """「最近演出」卡左边那一格封面（没有封面时退回一个音符图标）。

    **尺寸取 `RECENT_ART`(56)，不是 `T.AVATAR`(40)**：官方 list 的 leading image 就是 56（`tools/probes/m3tokens.py` 的 `OFFICIAL_LIST["leading-image"]`，与两行列表项容器高 72配成一对；40 那一档是选曲列表的头像位 `T.AVATAR`）。从前这里写死 40，只是因为外面那层槽是 56x56 的**紧约束**才被 Flutter 拉满成 56 —— 槽一被压就露馅（用户 m09165 看到的「长方形」正是这一路，见 `_build_run_card`）。
    """
    if src:
        return ft.Image(src=src, width=size, height=size, fit=ft.BoxFit.COVER)
    # 官方 list 的 leading icon 就是 **24**（`ListTokens.ItemLeadingIconSize`），照它取。
    return ft.Icon(ft.Icons.MUSIC_NOTE, size=T.ICON_LG, color=tk.text_dim)


def song_leading(tk, song, rank):
    """选曲列表每行的 leading（M3 list 的 40dp 头像位）：有封面就给封面，没有就退回乐队标识块。

    封面是绝对路径直给 —— 实测 Flet 1.0.3 的桌面客户端认本地绝对路径（同一张图放在
    `src_base64` / 不存在的路径旁边对比过：绝对路径那一格 1948 种颜色、错路径那一格只有底色）。
    """
    src = jacket_src(song.get("musicId"))
    band = str(song.get("bandZh") or song.get("band") or "")
    if src is None:
        return band_avatar(tk, band, rank)
    return ft.Container(
        content=ft.Image(src=src, width=T.AVATAR, height=T.AVATAR, fit=ft.BoxFit.COVER),
        width=T.AVATAR, height=T.AVATAR, border_radius=T.radius("chip"),
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS)


def band_avatar(tk, band, rank):
    """选曲列表每行左边那个乐队标识块（M3 list 的 40dp leading 位）。

    规范没有给「乐队配色」。这里取难度四色的容器 / 反色对（扩展色里唯一现成的四组**配对**
    容器色），按乐队在清单里的次序取一色 —— 只做「一眼看出这是哪个团」的标识，不承载判定含义。
    """
    i = int(rank or 0) % 4
    return ft.Container(
        content=ft.Text((band or "?")[:1], style=T.type_style("labelLarge"),
                        color=tk.diff_on_container(i)),
        width=T.AVATAR, height=T.AVATAR, bgcolor=tk.diff_container(i),
        border_radius=T.radius("chip"), alignment=ft.Alignment.CENTER)


# 键盘清单。`_on_key` 与 `shortcuts_dialog` 读的是同一份 —— 弹窗里念的就是真在管用的那几个。
# 短文案一律往**二字 / 四字**收（用户 m05745 点名的原则）：几个字一行都一样宽，栏与栏、
# 卡与卡才容易对齐成一条线。
SHORTCUTS = (
    ("F5", "开始演奏 / 开始演出"),
    ("F1", "快捷按键"),
    ("Ctrl+1 / 2 / 3 / 4 / 5", "单人演出 / 多人演出 / 运行日志 / 结算记录 / 设置"),
    ("Alt+1 / 2 / 3 / 4", "切换难度"),
    ("Ctrl+F", "聚焦搜索"),
    ("Ctrl+R", "重读数据"),
    ("Ctrl+L", "清空日志"),
    ("Esc", "清空搜索"),
    ("Alt+↑ / ↓", "移动选中行"),
    ("Alt+Enter", "打开截图"),
)

# 方向键与回车的 `KeyboardEvent.key` 拼写。Flet 转发的是 Flutter 的 `keyLabel`
# （`LogicalKeyboardKey.keyLabel` 查 `_keyLabels` 表）—— 实测 Flutter stable 的
# `packages/flutter/lib/src/services/keyboard_key.g.dart`（`_keyLabels` 起于第 3050 行）：
# `0x00100000304: 'Arrow Up'`、`0x00100000301: 'Arrow Down'`、`0x0010000000d: 'Enter'`。
# 其余几种写法（不带空格的、小键盘回车）一并收进来：少认一个拼写的代价是「按下去没反应」。
# **没有做真实键盘事件注入实测**（用户 m21635 定的范围：只加代码与登记）。
KEY_UP = ("Arrow Up", "ArrowUp", "Up")
KEY_DOWN = ("Arrow Down", "ArrowDown", "Down")
KEY_ENTER = ("Enter", "Numpad Enter", "NumpadEnter")


def shortcuts_dialog(page, tk):
    """快捷键一览。M3 的对话框：`surface_container_high` + level3 + 28 圆角，动作只有一个「明白」。"""
    rows = []
    for key, what in SHORTCUTS:
        rows.append(ft.Row([
            ft.Container(content=ft.Text(key, style=T.type_style("labelMedium"),
                                         color=tk.on_secondary_container),
                         bgcolor=tk.secondary_container, border_radius=T.radius("chip"),
                         padding=ft.Padding(T.SPACE["sm"], T.SPACE["xs"],
                                            T.SPACE["sm"], T.SPACE["xs"])),
            txt_spec(what, tk, "bodyMedium", color=tk.text),
        ], spacing=T.SPACE["md"], vertical_alignment=ft.CrossAxisAlignment.CENTER))
    page.show_dialog(ft.AlertDialog(
        modal=True,
        title=txt_spec("快捷按键", tk, "headlineSmall", color=tk.text),
        content=ft.Container(content=ft.Column(rows, spacing=T.SPACE["sm"], tight=True),
                             width=420, padding=ft.Padding(0, T.SPACE["sm"], 0, 0)),
        actions=[hit_pad(button(tk, "明白", lambda _e: page.pop_dialog(), kind="text"))],
        actions_alignment=ft.MainAxisAlignment.END,
        bgcolor=tk.dialog,
        elevation=T.elevation("level3"),
        shape=ft.RoundedRectangleBorder(radius=T.radius("dialog")),
    ))


def save_log(page, tk, store):
    """把面板日志全量写到 `research/logs/panel_<时间戳>.log`。

    运行日志页只画最近 `core.LOG_WINDOW` 行、内存里也只留 `core.LOG_KEEP` 行，所以「导出」导的是
    `log_store` 里的**全部**（与页脚那句「共 N 行」同一个数），不是屏幕上那一段。目录走
    `research/`（`.gitignore` 里 `research/*` 已忽略），不会把导出物带进仓库。
    """
    rows = [line for _kind, line in store]
    if not rows:
        toast(page, tk, "还没有日志可导出", kind="err")
        return
    out_dir = os.path.join(core.ROOT, "research", "logs")
    name = "panel_%s.log" % time.strftime("%Y%m%d_%H%M%S")
    try:
        os.makedirs(out_dir, exist_ok=True)
        with io.open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="") as f:
            f.write("\n".join(rows) + "\n")
    except OSError as e:
        toast(page, tk, "导出日志失败：%r" % (e,), kind="err")
        return
    toast(page, tk, "已导出 %d 行 -> research/logs/%s" % (len(rows), name))


def read_game_screen():
    """读游戏当前画面认谱（乐曲识别 / 画面核对）。找不到 gameread 就明说 —— 不静默降级成
    「看起来一致」：那会让一次没核对的跑法长得像核对过的。

    与旧 PySide6 版（`tools/gui.py`，已随 Qt 删掉）的同名函数逐字同义 —— 它留在模块层、不在
    panel_core 里，因为它要 import gameread，而 gameread 会碰 adb。
    """
    try:
        import gameread
        return gameread.read_song_select()
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "why": f"读画面不可用：{e!r}"}


# ---------------------------------------------------------------- 结算表的模型

class HistModel:
    """结算表的**模型层**：筛选、排序、派生一行的值。它不认识颜色，也不认识控件。

    这是旧 `tools/qt_history.py`（已随 Qt 删掉）的 `HistoryModel` 的同一套逻辑 —— 包括三条容易
    在移植里丢掉的取舍：全量重算、`None` 排到最后、排序键用显式哨兵元组。
    """

    def __init__(self):
        self.recs = {}                 # tag -> record
        self.tags = []                 # 当前可见的顺序（**全部**筛出来的行）
        self.limit = core.HIST_LIMIT_DEFAULT   # 表上最多画几行（0 = 全部）
        self.sort_col = "time"
        self.sort_desc = True
        self.filter = "all"
        self.sources = {k for k, _ in core.HIST_SOURCES}   # 来源：默认两半都列
        self.cells = {}                # tag -> 14 格文本（第 0 格永远是空串）
        self.kinds = {}                # tag -> ap / fc / np / err / none
        self.letters = {}              # tag -> e / n / h / x / u

    def set_records(self, recs):
        self.recs = dict(recs)
        self.rebuild()

    def upsert(self, rec):
        self.recs[rec.get("tag", "?")] = rec
        self.rebuild()

    def set_filter(self, key):
        self.filter = key
        self.rebuild()

    def set_source(self, key, on=None):
        """点亮／熄灭一枚来源 chip（`solo` / `multi`）。`on=None` 就是翻向。

        2026-10-10 用户 m13266：结算记录页要能只看单人、只看多人。两枚 chip 各自独立
        （官方 filter chip 的多选语义），**两个都不亮就是什么都不列** —— 那一态由表上的空态
        接住（与筛选到「异常」而一条都没有时同一条路）。`on` 是给判据用的显式态。
        """
        if key not in dict(core.HIST_SOURCES):
            return
        want = (key not in self.sources) if on is None else bool(on)
        if want:
            self.sources.add(key)
        else:
            self.sources.discard(key)
        self.rebuild()

    def set_limit(self, n):
        """表上最多画几行。**不改 `tags`**：筛选与导 CSV 仍按全部行来（见 `shown`）。"""
        self.limit = core.clamp_hist_limit(n)
        return self.limit

    def shown(self):
        """真正要画进 `DataTable` 的那一段 —— 全量筛出行按当前排序取前 `limit` 行。"""
        return self.tags if not self.limit else self.tags[:self.limit]

    def recent_tags(self, n, mode=None):
        """`mode` 那一半里按**时间**倒序的前 n 条 tag —— 与当前筛选、当前排序**无关**。

        「最近演出」卡的名字就是这个意思：它是「我刚打的最后几局」。用户 m08235 审出来的是这张卡
        从前直接读 `self.tags`（= 当前筛选 + 当前排序的结果），于是把结算记录页的筛选改成
        「AP」、或把排序改成「按分数」，这张卡就跟着变成「AP 里最新的几局」「分数最高的几局」——
        卡名说「最近」，内容说的却是另一件事。缺时间戳的排到最后（与表上同一条规矩）。

        `mode`（2026-10-09 用户 m10950）：单人页那张只列单人局、多人页那张只列多人局 ——
        `None` / `"all"` 才是两半都要（结算记录页与导出 CSV 走的就是那一条）。
        """
        if n <= 0:
            return []
        rows = [r for r in self.recs.values() if core.hist_mode_ok(r, mode)]
        rows = core.hist_order(rows, "time", True)
        return [r.get("tag", "?") for r in rows[:n]]

    def set_sort(self, col, desc=None):
        """同列且不给方向 -> 翻向；换列 -> 采用给定方向（不给就保持当前方向）。"""
        if col == self.sort_col and desc is None:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col = col
            if desc is not None:
                self.sort_desc = desc
        self.rebuild()

    def rebuild(self):
        """筛选 + 排序 + 派生一行的值。全量重算：语料是 230 行，比增量维护便宜得多，
        也不会出现「表格和真实值不一致」那类只在某些路径下才现形的问题。"""
        kept = [r for r in self.recs.values()
                if core.hist_mode(r) in self.sources and core.hist_kept_for(r, self.filter)]
        # 缺数据的行两个方向都排最后 —— 由 `core.hist_order` 保证（从前这里用
        # `(v is None, v)` 当 key 再 `reverse=`，降序时哨兵跟着一起翻，占位符全跑到最前面：
        # 2026-10-09 用户 m11595 报的就是这个）。
        kept = core.hist_order(kept, self.sort_col, self.sort_desc)
        self.tags = [r.get("tag", "?") for r in kept]
        self.cells, self.kinds, self.letters = {}, {}, {}
        for r in kept:
            t = r.get("tag", "?")
            self.cells[t] = core.hist_cells(r)
            self.kinds[t] = core.hist_kind(r)
            self.letters[t] = core.DIFF_LETTER.get((r.get("diff") or "").upper(), "u")

    def is_muted(self, tag, col):
        """这一格该压暗：**真 0** 与**没有读数**（占位符 `—`）都压暗，真数不压。col 是视图列号
        （0 是竖条列）。

        2026-10-09 用户 m11451/m11595：数字列不留空，占位符要与真数分得开。字形（`—` vs `0`）
        与字色（压暗 vs 正常）各承担一半 —— 从前只判 `== 0`，于是占位符走的是**正常字色**，
        看上去和真数一样（那就是用户说的「差距太小」）。
        """
        if not (1 <= col <= len(core.HIST_COLS)):
            return False
        name = core.HIST_COLS[col - 1]
        if name not in ("P", "G", "GD", "B", "M", "combo", "score", "np", "reopen"):
            return False
        return core.hist_num(self.recs[tag], core.NUM_COL.get(name, name)) in (None, 0)

    def row_of_tag(self, tag):
        try:
            return self.tags.index(tag)
        except ValueError:
            return -1

    def counts(self):
        out = {k: 0 for k, _ in core.HIST_FILTERS}
        for r in self.recs.values():
            for k, _label in core.HIST_FILTERS:
                if core.hist_kept_for(r, k):
                    out[k] += 1
        return out

    def tally(self):
        """页脚的两个数字：可见行数与 AP 行数（按当前筛选口径）。"""
        return len(self.tags), sum(1 for t in self.tags if self.kinds.get(t) == "ap")


# ---------------------------------------------------------------- 「最近演出」那两张卡

class RecentCard:
    """一张「最近演出」卡的家什：列哪一半记录、建了哪些行、进出场那两个计数器。

    2026-10-09（用户 m10950）之前这些字段直接挂在 `Panel` 上（`recent_rows` / `recent_card` /
    `_recent_seq`…），因为只有单人页那一张。现在多人页左侧也放一张（只列多人记录），同一套字段
    变成两份 —— 打包成这个对象，两张卡各持一个实例，而逻辑（`_build_last_run` /
    `_sync_last_cards` / `refresh_last_run` / `_fade_out_card`）仍然只有一份。

    `mode` 同时是「列哪一半记录」与「这张卡挂在哪个页面」：`"solo"` / `"multi"` —— 正是
    `core.hist_mode_ok` 认的那两个词。`rows` 里每一项是 `_build_run_card` 交回来的那本字典。
    `pool` 是这张卡最多建几行（单人页 `RECENT_POOL` 6、多人页 `RECENT_POOL_MULTI` 15）。

    `fill` = 这张卡**独占一栏**、要撑满那一栏（多人页左侧那张）：右栏的运行卡本来就是撑满的，
    卡底对齐才不显「缺一块」；撑满多出来的高度交给列表自己滚，所以能放几条就放几条。单人页
    那张挤在运行卡**下面**、按行数自然高，`fill=False`（用户 m13783）。
    """

    def __init__(self, mode):
        self.mode = mode
        self.title = "最近演出"
        self.pool = RECENT_POOL if mode == "solo" else RECENT_POOL_MULTI
        self.fill = mode == "multi"
        self.rows = []
        self.body = None
        self.card = None
        self.shown = 0
        self.seq = 0                 # 进出场：新的一次要能作废在飞的那次退场
        self.hiding = False          # 整卡退场已排队（同一次退场不许排两遍）


# ---------------------------------------------------------------- 面板

class Panel:
    """整个面板。一个实例 = 一个窗口。"""

    def __init__(self, page: ft.Page):
        self.page = page

        # 状态文件与 core 的所有权：读一次、写回由 core.save_state 负责。
        self.state = core.read_json(core.STATE, {}) or {}
        self.core = core.RunOrchestrator(self.state)

        self.appearance = T.resolve_appearance(self.state.get("appearance"))
        self.tk = T.tokens(self.appearance)
        self.font_key = T.resolve_font(self.state.get("font"))

        # 日志：store 是全部（最多 LOG_KEEP），view 只挂筛过的那部分（最多 LOG_WINDOW）。
        self.log_store = []
        self.log_filter = "all"
        self.log_query = ""        # 运行日志页自己的关键词（大小写不敏感的子串，见 `_log_pass`）
        self.run_start = 0
        # 三样都写死在这里（不是随手加的参数）：
        # `scroll=ADAPTIVE` —— 不给这一个字段，Flutter **一条滚动条都不画**（实测：溢出 60 行
        #   时右边缘 26 列一个非白像素都没有）。2000 行的日志既看不出自己在哪儿、也拖不动，
        #   而「桌面上要那条轨」正是规范的默认期待。
        # `auto_scroll_animation=0` —— 默认是 1 秒 ease，泵每 `PUMP_MS`（120 ms）来一行会把
        #   上一条的滑动打断，永远追不上底。官方 docstring 对「高速逐条追加」正是建议给 0
        #   （瞬时跳到底、钉住不松）。
        # `on_scroll` —— 用户在往回翻时，框架本来就会暂停钉住、滚回底部自动恢复（同一条
        #   docstring），但「自动滚动」开关停在「开」上就是在说谎。这个回调只把真实状态说给
        #   开关听（见 `_on_log_scroll`；事件只在**用户滚**时来，程序自己钉住不会打自己）。
        # 行距：一节 24dp = 正文盒 16 + `spacing` 4 + 上下两端各 8（面板那 8 见 `_build_log`）。
        # 从前节距是 20dp（`spacing` 0），两千行挤成一堵墙；4 是 4dp 栅格上最小的一档。
        self.log_view = ft.ListView(expand=True, spacing=T.SPACE["xs"], auto_scroll=True,
                                    auto_scroll_animation=0,
                                    scroll=scroll_when_needed(),
                                    on_scroll=self._on_log_scroll,
                                    padding=ft.Padding(0, T.SPACE["sm"], 0, T.SPACE["sm"]))
        self.log_info = txt("", self.tk, "n", color=tk_dim(self.tk))
        # 开关翻面时用来把位置接回来的两个账（用户 m10610）：
        # `_log_pixels` = `_on_log_scroll` 报上来的真实位置（翻之前记住它）；`_log_pin` =
        # 「这一拍是我们在复位」的闸门 —— 复位自己发出的滚动事件不许去掰开关（否则「贴着底
        # 关掉」会被镜像逻辑立刻掰回「开」）。
        self._log_pixels = 0.0
        self._log_pin = False

        self.manifest = {}
        self.songs = []
        self._lib_status = ""      # load_manifest() 那句谱面库概况；页脚还没建好之前先存着
        self.sel = None            # 选中的歌（manifest 里那一条 dict）
        self.diffs = []            # 选中歌的 difficulties
        self.diff_idx = -1
        self.native_ids = set()
        self.band_rank = {}
        self.cat_map = {}
        self.ap = set()

        self.tab = 0
        self.phase = ""
        self._pct = 0.0
        # 「本局」读数带（见 `_build_stats`）：两张运行卡各建一份格子，`_set_stats` 一次更新两份；
        # `run_stats` 留最近一次的原值 —— 一局打完读数不该立刻消失，它正是「这一局怎么跑的」。
        # 名字避开 `band`：这一份代码里 band 已经被「命中带」「AP 档」用过两回了。
        self.stat_bands = []
        self.run_stats = {}
        self._pinned = None        # 链路标定「撞到边界」的去重状态（见 refresh_cfg_info）
        self._flash_tag = None     # 刚结算那一行（强调一秒多）
        self._flash_seq = 0        # 挨得近的两次结算，靠序号防止前一次的收尾擦掉后一次
        self._progress_seq = 0     # 同上：进度补间的后一次要能作废前一次
        self._phase_seq = 0
        # 两张「最近演出」卡（2026-10-09 用户 m10950：单人页只列单人局、多人页只列多人局）。
        # 字段从前直接挂在这里，现在各自打包进 `RecentCard` —— 逻辑仍然只有一份。
        self.recent = RecentCard("solo")
        self.m_recent = RecentCard("multi")
        self._page_seq = 0         # 换页两拍：连点页签时后一次要能作废在飞的那一次

        self.pages = []
        self.diff_segs = []          # 四个 `ft.Segment`（难度分段控件的那一段一段）
        self.diff_label = None       # 难度分段控件上方那个居中标签
        self.diff_seg = None         # M3 分段控件本体（一行四段、等宽、单选）
        self.diff_hit = None         # 难度那一条的外壳：可视 40、可点 48（上下各一排四格带）
        self.search_clear = None     # 搜索框的有内容才出现的清空按钮
        self.count_text = None       # 「显示 N / M 首 · K 张谱 · 已 AP J 首」
        self._pick_body = None       # 选曲卡的 Column（探针第 11 关核对控件顺序）
        self._run_body = None        # 运行卡的 Column（探针第 11 关核对动作区两行等宽对齐）
        self._rail = None
        self._body = None
        self._footer_status = None
        self._footer_phase = None
        self._footer_progress = None
        self._footer_pct = None
        self._settings_row = None

    # ------------------------------------------------------------ 构建

    def build(self) -> ft.Control:
        T.apply(self.page, self.appearance, self.font_key)
        self.page.bgcolor = self.tk.page
        self.page.padding = 0
        self.page.spacing = 0
        self.page.title = APP_TITLE

        self.load_manifest()

        # 五页，顺序就是导航轨的顺序：单人演出 / 多人演出 / 运行日志 / 结算记录 / 设置。
        # 运行日志从前挤在开始页右栏，只有 7 栏宽还得跟左边的选曲抢高度；单开一页之后整页都是它的，
        # 行也就不用再截断着看。多人演出（用户 m02832）排在单人演出之后：它只发 `--multi`，
        # 面板不选曲 —— 房间自己抽（见 `_build_multi`）。
        self.pages = [self._build_start(), self._build_multi(), self._build_log(),
                      self._build_history(), self._build_settings()]
        self._fill_cats()          # 分类下拉框的选项来自 cat_map，而 cat_map 是 load_manifest 算的
        self._body = ft.Container(content=self.pages[0], expand=True,
                                  padding=ft.Padding(T.SPACE["lg"], T.SPACE["md"],
                                                     T.SPACE["lg"], T.SPACE["md"]))
        # 「过渡动画」关掉时所有动画函数都直接落终态，所以这个属性留着也不会动 —— 见 `show_tab` / `_set_phase`。
        self._body.animate_opacity = T.animation("page")
        self._rail = self._build_rail()
        # 数据必须在控件建好之后再灌：`reload_songs` / `load_history` 都是「控件不在就早退」，
        # 先调它们等于首帧两张表都是空的（这条踩过 —— 结算页曾经 0 行、曲目列表也是空的）。
        self.reload_songs()
        self.load_history()
        self.refresh_start_state()
        self.update_tally()
        self.refresh_cfg_info()
        self.refresh_last_run()

        self.page.on_resize = self._on_resize
        self.page.on_keyboard_event = self._on_key
        self.page.window.prevent_close = True
        self.page.window.on_event = self._on_window_event

        shell = ft.Column([
            self._build_header(),
            hairline(self.tk),
            ft.Row([self._rail, self._body], expand=True, spacing=T.SPACE["none"]),
            hairline(self.tk),
            self._build_footer(),
        ], spacing=T.SPACE["none"], expand=True,
            # 撑满：`Column` 默认的 START 只给孩子松约束，`ft.AppBar` 会按自己的固有宽度收窄
            # —— 顶部栏缩成标题那么宽、右边空一片（与选曲卡里搜索框那条是同一个坑）。
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

        # `load_manifest()` 跑在页脚建出来之前，那会儿 `_set_status` 是空操作（控件还不存在），
        # 谱面库概况就此丢掉 —— 页脚会一直空着。这里补一次。
        self._set_status(self._lib_status)

        self._apply_window_class(self.page.width or T.WINDOW_DEFAULT[0])
        return shell

    def _build_header(self):
        """M3 顶部应用栏（top app bar）：高 64dp、容器角色 `surface`、标题 `titleLarge`。

        从前这里是自制的 `ft.Container(bgcolor=tk.card)`：高度跟着内容走（≠ 规范的 64），容器色
        比页面底还高一档（app bar 用的角色是 `surface`，不是 `surface_container_low`），标题用
        titleMedium(16) 而不是 titleLarge(22)。现在走真控件 `ft.AppBar`，高度取 `T.APPBAR_H`。
        """
        self.tally = txt("", self.tk, "s", color=self.tk.text_dim)
        self.help_btn = ft.IconButton(
            icon=ft.Icons.KEYBOARD_OUTLINED, icon_size=T.ICON_LG,
            icon_color=self.tk.text_dim, tooltip="键盘快捷键（F1）",
            on_click=lambda _e: shortcuts_dialog(self.page, self.tk))
        return ft.AppBar(
            toolbar_height=T.APPBAR_H,
            bgcolor=self.tk.surface,
            color=self.tk.text,
            elevation=T.elevation("level0"),
            automatically_imply_leading=False,
            leading=ft.Container(
                content=ft.Icon(ft.Icons.MUSIC_NOTE, color=self.tk.accent, size=T.ICON_LG),
                alignment=ft.Alignment.CENTER),
            title_spacing=T.SPACE["md"],
            # 标题取 `titleLarge`（规范给顶部应用栏的就是这一档，22/28）。从前用的是桥里那档
            # titleMedium（16/24），在 64 dp 高的栏里小了一号；副标题留在 labelSmall 做补充。
            title=ft.Row([
                txt_spec(APP_NAME, self.tk, "titleLarge", color=self.tk.text),
                txt("自动演奏", self.tk, "s", color=self.tk.text_dim),
            ], spacing=T.SPACE["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            actions=[self.tally, hit_pad(self.help_btn)],
        )

    def _build_rail(self):
        dests = []
        for name, icon, sel_icon in TABS:
            dests.append(ft.NavigationRailDestination(icon=icon, selected_icon=sel_icon, label=name))
        return ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            destinations=dests,
            on_change=self._on_tab,
            # 轨道容器是 `surface`（与 app bar 同层），条目最小宽 80 —— 官方默认
            # （`_NavigationRailDefaultsM3.minWidth`，material-web 的 `container-width` 也是 80），
            # 从前写的是 `surface_container_low` 与 88 / 200。导轨**永不展开**（用户 m18525），
            # 所以这里不传 `min_extended_width`：留着一个没人用的旋钮只会误导（256 仍绑在主题层）。
            bgcolor=self.tk.surface,
            indicator_color=self.tk.secondary_container,
            indicator_shape=ft.RoundedRectangleBorder(radius=T.radius("nav_indicator")),
            group_alignment=-1.0,          # 条目靠上排（-1 = 顶）
            min_width=T.NAV_MIN_W,
            leading=ft.Container(height=T.SPACE["md"]),
        )

    def _build_footer(self):
        # 页脚那盏状态灯：颜色跟着状态行那句话走（`_snap_phase` 一起刷），一眼看出
        # 「在跑 / 成功 / 出错 / 空闲」—— 从前只有一句话，状态色藏在字里。
        self._footer_dot = ft.Container(width=T.DOT, height=T.DOT,
                                        border_radius=T.DOT // 2, bgcolor=self.tk.outline)
        self._footer_status = txt("", self.tk, "n", color=self.tk.text_dim, expand=True,
                                  max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._footer_phase = txt("空闲", self.tk, "b", color=self.tk.text_dim, width=200,
                                 text_align=ft.TextAlign.END, max_lines=1,
                                 overflow=ft.TextOverflow.ELLIPSIS)
        self._footer_phase.animate_opacity = T.animation("phase")
        self._footer_progress = ft.ProgressBar(
            value=0.0, width=180, bar_height=T.PROGRESS_H,
            color=self.tk.accent, bgcolor=self.tk.trough,
            border_radius=T.PROGRESS_R)
        self._footer_pct = txt("  0%", self.tk, "s", color=self.tk.text_dim, width=44)
        lamp = ft.Row([self._footer_dot, self._footer_status], spacing=T.SPACE["sm"],
                      vertical_alignment=ft.CrossAxisAlignment.CENTER, expand=True)
        return ft.Container(
            content=ft.Row([lamp, self._footer_phase,
                            self._footer_progress, self._footer_pct],
                           spacing=T.SPACE["md"],
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
            # 与 app bar、导航轨同层（`surface`）—— 从前是 `surface_container_low`，于是窗口
            # 上下各压一条比页面底高一档的带子，中间的页面反倒显得是「凹」进去的。
            bgcolor=self.tk.surface,
            padding=ft.Padding(T.SPACE["lg"], T.SPACE["sm"], T.SPACE["lg"], T.SPACE["sm"]),
        )

    # ---------------- 页面：开始 ----------------

    def _build_start(self):
        """开始页：左栏只有选曲，右栏是运行（含三个策略数）与「最近演出」卡，两栏各 6 栏，**自适应**。

        并排时整块吃满一页高：左卡的列表与右栏的运行卡**各自吃掉本栏的余量**（`expand`），
        两栏的上下沿因此齐平，中间不留空洞；窄到 `STACK_W` 以下两栏叠成一栏，一屏装不下，
        这时候才整页滚（换挡在 `_apply_window_class`）。
        两栏都靠 `vertical_alignment=STRETCH` 拿到**紧**高度约束：没有它，`expand` 无处可依，
        整页又会退回「按内容堆、堆不下就得滚」。
        两栏的 `col` 给的是 `{"xs": 6}`（不是 `{"xs":12,"lg":6}`）：`xs` 任何宽度都命中，
        于是「两栏还是 一栏」只由 `STACK_W` 说了算，不再有第二个判据来跟它打架。

        链路标定的那张卡删了：它每次占一整张卡却只有一行数要说，撞界的告警照旧落在运行日志页。
        每类键提前量也删了（读数没法在面板里验，只能靠 CLI 的 `--kind-lead`）。
        """
        # 两栏里再套一层 `Column` 之后，卡片拿到的是**松**宽度约束，会缩到自己的固有宽度
        # （右边缘比另一栏短一截）。`STRETCH` 让这层 Column 取满栏宽 —— 与卡内那两个 body
        # 同一条教训；这里还多一层用处：栏高也是紧的，卡里的 `expand` 才有东西可吃。
        self._left_col = ft.Column([self._build_pick()], spacing=T.SPACE["md"],
                                   horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                   expand=True)
        # 右栏不留空档：中间那个 `Container(expand=True)` 在窗口变高时会张成一大块空洞，
        # 两张卡被顶到两头（「上下左右对齐」就是这么丢的）。现在运行卡吃本栏余量（余量摊在它
        # 自己的设置区与动作区之间），上沿与左卡齐、下沿与「最近演出」卡齐，四边都对上。
        # 「最近演出」卡里放几条由 `_sync_last_cards` 按余量决定：一条都放不下时整张卡
        # `visible=False`、**不占高度**。这一张只列**单人**局（`_build_last_run("solo")`）。
        self._right_col = ft.Column([self._build_run(), self._build_last_run("solo")],
                                    spacing=T.SPACE["sm"],
                                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                    expand=True)
        self._start_cols = ft.ResponsiveRow([
            ft.Container(content=self._left_col, col={"xs": 6}),
            ft.Container(content=self._right_col, col={"xs": 6}),
        ], spacing=T.SPACE["sm"], run_spacing=T.SPACE["sm"],
            vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        return ft.Column([self._start_cols], spacing=T.SPACE["none"], expand=True,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    # ------------------------------------------------------------- 多人演出

    def _build_multi(self):
        """多人演出页（用户 m02832：侧边栏「开始」改名「单人演出」，它下面插一项「多人演出」）。

        与单人页同构 —— 两栏、左「最近演出」右运行、窄过 `STACK_W` 叠成一栏 —— 但左边**不是
        选曲卡**：多人局（激奏演出）打哪张谱是**房间抽的**，面板给不出谱面，只有 `run.py` 走到
        準備 页时靠 `gameread.read_prep` 认出抽中的那一首。所以这一页要设的只有难度与那几颗策略
        开关，曲目列表、筛选、排序一概不在这儿（用户 m01214 只定了难度与结算页两件事）。

        左边那张是**同一张**「最近演出」卡，只是 `mode="multi"`：只列激奏演出的局（用户
        m10950「复制替换多人演出的左侧模块，相对的多人模式仅展示多人记录」）。它替换掉了原先
        的「激奏演出」说明卡 —— 那四条规矩（房间抽签 / 难度按这一页发 / 匹配两次 / 打完回房间）
        从此只留在 `docs/panel_spec.md` 与 `AGENTS.md` 里，界面上不再复述。
        """
        self._multi_left = ft.Column([self._build_last_run("multi")], spacing=T.SPACE["md"],
                                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                     expand=True)
        self._multi_right = ft.Column([self._build_multi_run()], spacing=T.SPACE["sm"],
                                      horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                      expand=True)
        # 两栏**等宽**（各 6/12）：2026-10-10 用户 m13525 定。5/12 + 7/12 曾经是算出来的
        # （运行卡第三行那枚「开关 + 数框」的瓦片只有 7/12 那侧放得下），m12749 把那枚「断连重试」
        # 拆掉之后最宽的一枚退成数框 96，6/12 在 992 那一档也放得下（算术见 `TILE_MIN_W`）。
        # 左边那张是「最近演出」记录卡，条数上限 `RECENT_POOL_MULTI`。`xs` 让任何宽度都命中，
        # 所以「两栏还是一栏」只由 `STACK_W` 说了算（与开始页同一条规矩）。
        self._multi_cols = ft.ResponsiveRow([
            ft.Container(content=self._multi_left, col={"xs": 12, "md": 6}),
            ft.Container(content=self._multi_right, col={"xs": 12, "md": 6}),
        ], spacing=T.SPACE["sm"], run_spacing=T.SPACE["sm"],
            vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        return ft.Column([self._multi_cols], spacing=T.SPACE["none"], expand=True,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def _build_multi_run(self):
        """多人演奏的运行卡：难度 + 三行策略 + 三颗键。

        单人那张运行卡（`_build_run`）的骨架照搬。**选曲相关的只留一枚**：曲目跟随（= 乐曲识别）
        不在 —— 谱面是房间从五个人的提名里抽的，不是画面上那一首；正推限制也不在（多人局恒 0，
        见 `core.MULTI_PUSH_CAP_MS`，面板不给开关）。留的是**随机乐曲**：面板能做的只是
        「每轮随机提名一首」（`--random`），打哪首由房间决定。
        """
        d = self.state.get("multi") or {}
        dflt = self.state.get("defaults") or {}
        self.m_diff = str(d.get("diff") or "expert")
        if self.m_diff not in MULTI_DIFFS:
            self.m_diff = "expert"
        # 难度：与选曲卡上那颗是同一个控件（`diff_seg`），只是标签不带等级 —— 多人局的等级由
        # 房间定，面板报不出来，写个「Lv26」只会是假的。
        self.m_diff_segs = [ft.Segment(value=k,
                                       label=ft.Text(k.upper(),
                                                     style=T.type_style("labelLarge")),
                                       tooltip=k.upper())
                            for k in MULTI_DIFFS]
        self.m_diff_seg = diff_seg(self.m_diff_segs, [self.m_diff], self._on_multi_diff,
                                   tooltip="本局演奏难度。\n"
                                           "与房间难度不一致时，将在 乐曲选择 页改为所选难度；"
                                           "无法修改时按页面难度完成本局")

        def _bands():
            # 可视 40、可点 48：上下各一条隐形带（与选曲卡那颗同一套做法）。
            cells = [ft.Container(expand=True, height=HIT_PAD,
                                  on_click=lambda _e, k=i: self.select_multi_diff(k))
                     for i in range(len(MULTI_DIFFS))]
            return ft.Row(cells, spacing=T.SPACE["none"], tight=True)

        # `expand=True` 是必须的（2026-10-12 用户 m27155 报「空的，只有一个标题」时查出来的）：
        # `opt_tile` 把 trail 放进一个**裸 `ft.Row`**，而 Row 给非 flex 孩子的宽度约束是
        # **无界**的；下面这个 Column 用 `horizontal_alignment=STRETCH`，按 `diff_seg` 的
        # docstring 它需要**有界**宽度（Flutter 在紧宽度下按 `maxWidth / childCount` 分段宽）。
        # 无界时四个段一个像素都画不出来 —— 真机上那一行只剩「难度」两个字，占位约 93 px 全空
        # （`research/experiments/multiprof.py` 的行剖面：y 211..304 零内容像素，而同页
        # 「连续演出」「演出间隔」的数字框、「AP终止」「随机乐曲」的开关都正常）。
        # `expand=True` 让父 Row 用 `Expanded` 给出**有界的紧宽度**，与选曲卡那颗
        # （`_rebuild_diff_hit`，父级本来就是有界 Column）等价。
        self.m_diff_hit = ft.Container(
            content=ft.Column([_bands(), self.m_diff_seg, _bands()],
                              spacing=T.SPACE["none"], tight=True,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            expand=True)

        self.m_n_field = num_field(self.tk, int(dflt.get("runs", 1)), self._save_multi,
                                   width=96, decimals=0, suffix=" 轮")
        self.m_gap_spin = num_field(self.tk, int(dflt.get("gap_min", 0.0)), self._save_multi,
                                    suffix=" 分", decimals=0, width=96)
        self.m_gap_spin.tooltip = ("演出间隔（分）：返回房间的 乐曲选择 页后等待该时长，"
                                   "再开始下一轮")
        self.m_stop_ap = toggle(self.tk, int(dflt.get("stop_on_ap", 1)), self._save_multi,
                                tooltip="达成 ALL PERFECT 后不再开始下一轮")
        # 多人页**没有**「断连重试」（2026-10-10 用户 m12749 问出来的）：那条能力的机制是
        # 「暂停 LIVE → 按暂停面板的 重试 → 确定」把**同一首**从头再打一遍
        # （`calib.restart_to_t0`），是单人 LIVE 才有的东西；房间局是一屋子人同时打同一首，
        # 重开要么走不通、要么把这一轮直接作废（`run.py` 的 `_to_t0` 走不出去就 `return 1`，
        # 比「丢了 AP 但把这轮打完」更亏）。面板把它塞进多人页，本来就是我 m02832 设计那一页
        # 时照单人卡抄的，没有任何依据 —— 现在三层都不放行：这里不建控件、
        # `panel_core._spawn_run` 在 multi 下不发 `--retry-on-break`、`run.py` 见到 `--multi`
        # 就把这一项归零。单人页那枚照旧（`_build_run` 里的 `self.break_chk`）。
        # 多人页**没有**「LB监测」开关（2026-10-16 用户 m27959：换成「随机乐曲」）：火力门本身
        # 照旧对多人局生效 —— `core.start` 从 `defaults["fire_gate"]` 读，和单人页那颗共用一份
        # 状态，多人页只是不再提供入口（摘要行 `refresh_multi_policy` 会把它的当前状态念出来，
        # 免得这里藏着一件在这一页改不了的事）。
        self.m_random_chk = toggle(self.tk, int(d.get("random", 0)), self._save_multi,
                                   tooltip="每一轮在 楽曲選択 页随机挑一首作为**提名**，"
                                           "房间再从五个人的提名里抽一首（面板决定不了打哪首）。\n"
                                           "关闭时面板不碰选曲页：提名页面上停着的那一首。")
        self.m_policy_info = txt("", self.tk, "n", color=self.tk.text_dim)

        self.m_btn_start = button(self.tk, "开始演出", lambda _e: self.start_multi_run(),
                                  kind="filled", icon=ft.Icons.PLAY_ARROW,
                                  tooltip="F5（多人演出页）")
        self.m_btn_stop = button(self.tk, "本轮停止", lambda _e: self.stop_run(),
                                 kind="outlined", icon=ft.Icons.STOP_CIRCLE, disabled=True)
        self.m_btn_kill = button(self.tk, "强制终止", lambda _e: self.force_kill(),
                                 kind="outlined", icon=ft.Icons.CANCEL, danger=True,
                                 tooltip="立即终止正在运行的 run.py")

        grid = ft.Column([
            opt_line(opt_tile(self.tk, ft.Icons.LAYERS, "难度", self.m_diff_hit)),
            hairline(self.tk),
            opt_line(opt_tile(self.tk, ft.Icons.SYNC, "连续演出", self.m_n_field),
                     opt_tile(self.tk, ft.Icons.TIMER, "演出间隔", self.m_gap_spin)),
            hairline(self.tk),
            opt_line(opt_tile(self.tk, ft.Icons.CHECK_CIRCLE, "AP终止",
                              hit_switch(self.m_stop_ap)),
                     opt_tile(self.tk, ft.Icons.SHUFFLE, "随机乐曲",
                              hit_switch(self.m_random_chk))),
        ], spacing=T.SPACE["sm"], tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        top = ft.Column([grid, self.m_policy_info, self._build_stats()],
                        spacing=T.SPACE["sm"], tight=True,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        acts = ft.Column([hairline(self.tk),
                          ft.Row([fill(self.m_btn_start)], spacing=T.SPACE["sm"]),
                          ft.Row([fill(self.m_btn_stop), fill(self.m_btn_kill)],
                                 spacing=T.SPACE["sm"])],
                         spacing=T.SPACE["sm"], tight=True,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        body = ft.Column([top, acts], spacing=T.SPACE["sm"], expand=True,
                         alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.m_run_body = body
        self.m_run_card = card(self.tk, body, title="运行",
                               icon=ft.Icons.PLAY_CIRCLE_OUTLINE, box={"expand": True})
        self.refresh_multi_policy()
        return self.m_run_card

    def _build_run_card(self, index, mode):
        """「最近演出」卡里的一行（`index` = 那一半记录里按时间第 `index` 新的一局）。

        不另算一份摘要的理由很实在：另算就多一条可能与结算表说法不一致的路。这里只是把表里
        那一行拆开念一遍，整行可点 ⇒ 跳「结算记录」并选中那一行。最多建 `rc.pool` 行
        （单人页 6、多人页 15）、放几行由 `_sync_last_cards` 按余量算，这一支只管「一行长什么样」。

        `mode` 随行带着走：点哪一张卡里的行，跳过去就得选中**那一半**里对应的那一局
        （`_open_run_row` 与 `HistModel.recent_tags` 读的是同一个口径）。
        """
        t = txt("还没有记录", self.tk, "b", color=self.tk.text)
        # 一行只有一句副题（从前是两行）：行高低全靠它，写满会把这行撑高一截。
        sub = txt("", self.tk, "n", color=self.tk.text_dim, max_lines=1,
                  overflow=ft.TextOverflow.ELLIPSIS)
        chips = ft.Row([], spacing=T.SPACE["xs"],
                       vertical_alignment=ft.CrossAxisAlignment.CENTER)
        # 左边一格封面（没有记录时是一个音符图标）：摘要卡因此与选曲列表同一个视觉语言。
        art = ft.Container(width=RECENT_ART, height=RECENT_ART,
                           border_radius=T.radius("chip"),
                           clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                           bgcolor=self.tk.field, content=jacket_art(None, self.tk),
                           animate_opacity=T.animation("card"))
        info = ft.Column([t, sub], spacing=T.SPACE["none"], tight=True, expand=True,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        row = ft.Row([art, info, chips], spacing=T.SPACE["sm"],
                     vertical_alignment=ft.CrossAxisAlignment.CENTER)
        # 可点的范围从「整张卡」降到「一行」—— 卡里现在有很多行，每行跳自己那一局。
        box = ft.Container(content=row,
                           on_click=lambda _e, i=index, m=mode: self._open_run_row(i, m),
                           ink=True, border_radius=T.radius("field"),
                           # 行定高 = `RECENT_ROW_H`(72) = 官方两行列表项的容器高：上下各 8
                           # 内边距之后正好装下 56 的封面（`RECENT_ART`），行自己不再随窗口
                           # 伸缩。从前这里减了 `T.SPACE["sm"]` 当行距，内容区只剩 48 ⇒ 56 的
                           # 封面被 Flutter 的紧约束夹成 56x48，看着就是个长方形（用户
                           # m09165 报的）；行距改由列表自己出（0），与官方列表项齐平一致。
                           height=RECENT_ROW_H,
                           padding=ft.Padding(T.SPACE["sm"], T.SPACE["sm"],
                                              T.SPACE["sm"], T.SPACE["sm"]),
                           # 放出来 / 收回去时淡入（`MOTION["card"]`，入口在 `_sync_last_cards`）。
                           animate_opacity=T.animation("card"))
        return {"box": box, "title": t, "sub": sub, "chips": chips, "art": art}

    def _build_last_run(self, mode):
        """一张「最近演出」卡：一卡装 N 条，条目数由 `_sync_last_cards` 按余量算。

        `mode` 是这张卡**列哪一半**记录（`"solo"` / `"multi"`）：单人演出页那张只列单人局、
        多人演出页那张只列多人局（用户 m10950）。两张卡各持一个 `RecentCard`，逻辑同一份。

        从前是「最近一局」+「上一局」两张卡：卡自己的标题行与上下内边距各花一次，余量只够
        一局时第二张要么整个不显示、要么把运行卡挤瘦。合成一张之后省下的高度全给条目 ——
        用户要的「只保留一个卡片，但里面的条目数只要高度余量满足即增加」。

        `rc.fill`（多人页左侧那张）：卡**撑满那一栏**、列表在卡内自己滚（见 `_sync_last_cards`）。
        单人页那张挤在运行卡下面，按行数自然高、不撑不滚。
        """
        rc = self.recent if mode == "solo" else self.m_recent
        fill = rc.fill
        rc.rows = [self._build_run_card(i, mode) for i in range(rc.pool)]
        for r in rc.rows[1:]:
            r["box"].visible = False
        # 行距 0：每行自己就是官方的 72（含上下 8 内边距），两条之间不再留缝 ——
        # 官方列表项本来也是齐平的（从前是 64 的行 + 8 的行距，加起来同样是 72，
        # 但 64 那一档把 56 的封面压成了长方形）。
        #
        # `tight=True`（MainAxisSize.min）与 `expand` 打架：min 时那个 `expand` 的列表拿不到
        # 「剩下的那一截」、按自己的内容长（选曲列表踩过同一个坑，见 `_build_songs`）。
        rc.body = ft.Column([r["box"] for r in rc.rows],
                            spacing=T.SPACE["none"], tight=not fill, expand=fill,
                            # 撑满之后多出来的高度给列表自己滚：不滚的话行还是从顶上排下去、
                            # 卡底空出一大截 —— 正是用户 m13783 看到的「缺一块」（2026-10-10
                            # 实测：左卡自然高 572.4 逻辑、那一栏高 643.2 ⇒ 底下空 70.8）。
                            scroll=scroll_when_needed() if fill else None,
                            horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        rc.card = card(self.tk, rc.body, title=rc.title, icon=ft.Icons.INSIGHTS,
                       # 卡自己撑满那一栏，里面那层 Container 也得撑（`card()` 的 `**kw`
                       # 正是给里面那层的）—— 否则内容还是从顶上排、卡底留白。
                       box={"expand": True} if fill else None,
                       **({"expand": True} if fill else {}))
        rc.card.animate_opacity = T.animation("card")
        rc.shown = 0
        return rc.card

    def _open_run_row(self, index, mode):
        """点摘要卡里的一行：跳结算记录页，选中表里**同一局**那一行（不是 `_on_hist_select` —— 那是开关）。

        卡里的第 index 行是「**这一半**里按时间第 index 新」的那局（`HistModel.recent_tags`），
        跳过去必须选中同一局 —— 从前卡与这里都读 `hist.tags`，口径是隐式对齐的；m08235 把卡改成
        按时间取之后，这一处得跟着改，否则点第 1 行跳到表上选中的可能是另一局。
        """
        rc = self.recent if mode == "solo" else self.m_recent
        tags = self.hist.recent_tags(len(rc.rows), mode)
        tag = tags[index] if len(tags) > index else None
        if tag is not None:
            self.hist_row_tag = tag
            self._render_history()
        self.show_tab(TAB_HIST)

    def _recent_room(self, rc):
        """这张「最近演出」卡在当前这一档窗口下能占多高（`_sync_last_cards` 拿它算放几条）。

        单人页那张挤在运行卡**下面**：余量 = 页高 − 顶栏/页边距/页脚 − 运行卡自然高 − 卡间距
        − 卡自己的标题行与内边距。多人页那张独占左栏（右边才是运行卡），只扣顶栏与卡自己那截。
        叠成一栏时单人页那张照旧一条都不放（那一栏自己就不够高）；多人页那张落在运行卡下面、
        整页可滚，竖方向不再是稀缺资源 ⇒ 直接给满这张卡上限（`rc.pool`，多人页 15）行的位置。
        """
        page_h = self.page.height or 0
        if getattr(self, "_stacked", False):
            return 0.0 if rc.mode == "solo" else float(rc.pool * RECENT_ROW_H)
        if rc.mode == "solo":
            return (page_h - CHROME_H - RUN_NATURAL_H
                    - T.SPACE["sm"] - RECENT_CHROME_H)
        return page_h - CHROME_H - T.SPACE["sm"] - RECENT_CHROME_H

    def _sync_last_cards(self):
        """两张「最近演出」卡各放几条：按当前页高**能塞下几条就放几条**。

        余量见 `_recent_room`；**整除（floor）取条数**，所以每行只会比 `RECENT_ROW_H` 高、
        不会更矮（行是定高的），剩下那点零头（一定小于一行）留给运行卡的 `SPACE_BETWEEN` 去摊
        —— 卡里不留白。放不下还硬放，运行卡里的分组空隙会被吃光、最后两行按钮被**裁掉**（不是
        挤小）；所以常数一律**向上取整** —— 少放一条看不出来，多放一条按钮就没了。窗口一变就
        重判：拉高自己多出几条，缩回去自己收起来。进出场都是淡的（用户 m09421）：出现走
        `_fade_in`，消失先淡出、淡完再让出高度（`_fade_out_card`），`rc.seq`／`rc.hiding` 作废
        在飞的那一次 —— 连续拖窗口时既不能把该显示的卡藏掉，也不能让同一次退场排两遍。
        """
        hist = getattr(self, "hist", None)
        if hist is None or self.page is None:
            return
        for rc in (self.recent, self.m_recent):
            rows = rc.rows
            card_ = rc.card
            if not rows or card_ is None:
                continue
            room = self._recent_room(rc)
            fit = int(room // RECENT_ROW_H) if RECENT_ROW_H > 0 else 0
            # 一条记录都没有时也留一行（那一行写「还没有记录」），不然空库看着像卡没了。
            # 这里只数**这一半**（单人页那张不该被激奏演出的局撑起来）。
            have = max(1, sum(1 for r in hist.recs.values()
                              if core.hist_mode_ok(r, rc.mode)))
            # 撑满那一栏的卡（多人页）里列表自己会滚 ⇒ 有多少放多少，滚得到；单人页那张
            # 是自然高、不会滚 ⇒ 只能放当前余量装得下的整行（多放一行就把运行卡挤瘦）。
            show = max(0, min(have, rc.pool)) if rc.fill else max(0, min(fit, have, rc.pool))
            body = getattr(self, "_body", None)
            if show > 0:
                # 在飞的那次整卡退场作废（`_fade_out_card`，用户 m09421）：拖窗口时「淡出还没
                # 播完又要显示」必须能撤销，否则卡片会停在半透明甚至隐藏上。
                was_hiding = rc.hiding
                rc.hiding = False
                rc.seq += 1
                fresh = not card_.visible or was_hiding
                if fresh:
                    # 整卡从透明淡进来（`MOTION["card"]` = 250 ms）。这一路里行**不再各淡一次**
                    # —— 两层淡叠起来曲线会变成平方，看着比 250 ms 慢半拍。
                    card_.visible = True
                    for r in rows:
                        r["box"].opacity = 1.0
                    if body is not None:
                        self.page.run_task(self._fade_in, card_)
                for i, r in enumerate(rows):
                    box = r["box"]
                    want = i < show
                    if box.visible == want:
                        continue
                    r["seq"] = r.get("seq", 0) + 1      # 这一行在飞的那次退场作废
                    if want:
                        box.visible = True
                        r["out"] = False
                        if not fresh and body is not None:
                            # 卡已经在台上了、只是行数变了：这时才轮到行自己淡入。
                            self.page.run_task(self._fade_in, box)
                    elif body is not None and self._motion():
                        if not r.get("out"):
                            r["out"] = True
                            self.page.run_task(self._fade_out_row, r, r["seq"])
                    else:
                        r["out"] = False
                        box.visible = False
            elif card_.visible and body is not None and not rc.hiding:
                # 收起：先整卡淡出、淡完再让出高度（`_fade_out_card`）。行跟着卡一起走 —— 中途把
                # 行抽掉，卡会先缩一截再淡，等于多跳一下。
                rc.hiding = True
                rc.seq += 1
                self.page.run_task(self._fade_out_card, rc, rc.seq)
            rc.shown = show

    def refresh_last_run(self):
        """把两张「最近演出」卡里的 N 行各刷成**自己那一半**里按时间最新的 N 局。

        与结算表读同一个模型，但**不跟表上的筛选/排序走** —— 卡名说「最近」，内容就得是最近的
        （用户 m08235 审出来的口径问题，原委写在 `HistModel.recent_tags` 的 docstring 里）；
        也不跟对方那一半走（用户 m10950：单人页只列单人局、多人页只列多人局）。

        三处会调它：`build()` 首帧、每落一局（`_hist_upsert`）、重读记录（`load_history`）。
        """
        for rc in (self.recent, self.m_recent):
            recent = self.hist.recent_tags(len(rc.rows), rc.mode)
            for i, c in enumerate(rc.rows):
                tag = recent[i] if len(recent) > i else None
                rec = self.hist.recs.get(tag) if tag else None
                if not rec:
                    # 第一行没记录时写「还没有记录」+ 一句下一步；其余行留空（它们本来就被藏着）。
                    c["title"].value = "还没有记录" if i == 0 else ""
                    c["sub"].value = "完成一局后在此显示结果摘要" if i == 0 else ""
                    c["chips"].controls = []
                    self._set_card_art(c, None)
                    continue
                cells = core.hist_cells(rec)
                song, diff, ts = cells[2], cells[3], cells[1]
                # 分数与连击**从记录里读数**、不从 `cells` 里读字：结算表从 2026-10-09（用户
                # m11451/m11595）起「没有读数就印 `—`」，而这张卡只写真有的东西（`0 分` /
                # `0 combo` 不写）—— 两边口径不同，所以这里不能借表格的占位符。
                score = core.hist_num(rec, "score")
                combo = core.hist_num(rec, "combo")
                c["title"].value = (f"{song}  {diff}" if diff else str(song))
                bits = []
                if score:
                    bits.append(f"{score:,} 分")
                # 0 连击不写（中途崩掉的那种局）：与 `score` 一样只写真有的东西。
                if combo:
                    bits.append(f"{combo} combo")
                if ts:
                    bits.append(str(ts))
                c["sub"].value = " · ".join(bits) or "—"
                chips = [badge(self.tk, cells[4], self.hist.kinds.get(tag))]
                npf = core.hist_num(rec, "non_perfect")
                if npf:
                    chips.append(txt(f"漏 {npf}", self.tk, "s", color=self.tk.text_dim))
                retries = core.hist_num(rec, "aborts")
                if retries:
                    chips.append(txt(f"重开 {retries}", self.tk, "s", color=self.tk.text_dim))
                c["chips"].controls = chips
                # 封面：记录里只有歌名，过清单换成 musicId 再找缩略图（没装封面就退回音符图标）。
                self._set_card_art(c, jacket_src(song_music_id(self.manifest, song)))
        self._sync_last_cards()

    def _set_card_art(self, c, src):
        """摘要卡的封面槽换成 `src`（`None` = 退回音符图标）；**真换了一张**才淡一次。

        `refresh_last_run` 有三处调用（首帧、每落一局、重读记录），重读那一次会把同一张图再
        赋一遍 —— 每次都淡一遍看着像在闪，所以按 `src` 记住上次是谁。
        动画用 `_fade_in`（同一套两拍 + `MOTION["card"]`），槽自己带 `animate_opacity`。
        """
        if c.get("art_src") == src:
            return
        c["art_src"] = src
        c["art"].content = jacket_art(src, self.tk)
        c["art"].bgcolor = None if src else self.tk.field
        if getattr(self, "_body", None) is not None:
            self.page.run_task(self._fade_in, c["art"])

    def _build_pick(self):
        """选曲卡：**控件顺序就是用的顺序** —— 搜 → 筛 → 计数 → 列表 → 难度 → 信息。

        从前搜索框排在两个下拉**下面**、下拉写死 140 宽（横向一宽它俩还是 140）、列表固定
        260 高把整卡撑满；列表行又把 AP 进度当 `🌟n/m` 前缀塞在曲名前，曲名取的是排序字段
        （罗马音）—— 于是「看着全是英文名」。这里名字换原文（`core.song_label`）、进度挪到
        尾部、筛选控件改成跟窗口走；列表矮一截，计数行与「难度」标签居中，整卡反而更短。
        难度 2026-10-07（用户 m19421）换成官方的一行四段 `ft.SegmentedButton`：段上写**长式**
        「EXPERT Lv26」（同一天用户 m20246 撤掉了选中对勾，长式就不再被省略号截掉），全名
        留在 tooltip 里。
        """
        self.search_clear = ft.IconButton(
            icon=ft.Icons.CLOSE, icon_size=T.ICON_LG, visible=False,
            icon_color=self.tk.text_dim, tooltip="清空搜索",
            on_click=self._clear_search)
        self.search = ft.TextField(
            hint_text="歌名 / 罗马音 / 拼音 / 乐队",
            height=T.FIELD_H,
            border=input_border(self.tk),
            text_style=T.type_style("bodyLarge"),
            prefix_icon=ft.Icons.SEARCH, suffix=hit_pad(self.search_clear),
            on_change=self._on_search)
        self.cat_box = dropdown(self.tk, [("", "全部")], "", self._on_cat,
                                expand=True, tooltip="按乐队筛选")
        self.sort_box = dropdown(self.tk, [(m, m) for m in core.SORT_MODES],
                                 self.state.get("sort_mode") or core.SORT_DEFAULT,
                                 self._on_sort, expand=True, tooltip="排序方式")
        self.desc_btn = ft.IconButton(
            icon=ft.Icons.ARROW_UPWARD, selected_icon=ft.Icons.ARROW_DOWNWARD,
            selected=bool(self.state.get("sort_desc")),
            # 提示语不能说死一头：从前恒写「倒序」，可已经倒序时点它其实是正序。
            tooltip="排序方向（升序 / 降序）", on_click=self._toggle_desc,
            icon_color=self.tk.text_dim, selected_icon_color=self.tk.accent)
        self.count_text = txt("", self.tk, "n", color=self.tk.text_dim,
                              text_align=ft.TextAlign.CENTER)
        self.song_list = ft.ListView(expand=True, spacing=T.SPACE["none"], auto_scroll=False)
        self.song_empty = empty_state(self.tk, ft.Icons.SEARCH_OFF, "没有曲目",
                                      "请更换关键词，或将乐队筛选恢复为「全部」")
        self.song_empty.visible = False
        # 难度：标签居中放在分段控件上方。控件本身就是 M3 的 segmented button —— 一行四段、
        # 等宽、单选，形状/描边/选中色/字阶全按官方（见 `diff_seg` 与 `m3_theme.py`）。
        # 构造时先给一段占位：Flutter 断言 `segments.length > 0`，而这时曲目还没选。
        self.diff_label = txt("难度", self.tk, "n", color=self.tk.text_dim,
                              text_align=ft.TextAlign.CENTER)
        self.diff_seg = diff_seg(
            [ft.Segment(value="", label=txt("请先选择曲目", self.tk, "s",
                                            color=self.tk.text_dim))],
            [], self._on_diff_change, tooltip="难度")
        # 难度那一条的外壳：可视高仍是 `T.SEGMENT_H`(40)，**可点高** 48 —— 上下各垫一排四格
        # 隐形命中带，格宽与段宽都靠 `expand=True` 平分，点第 k 格就是 `select_diff(k)`
        # （用户 m20246；理由与官方两档目标尺寸见 `T.HIT_MIN`）。内容在 `_rebuild_diff_hit`
        # 里按当前难度数重建 —— 这里先挂上占位那一段。
        self.diff_hit = ft.Container(content=self.diff_seg)
        # 底部这行曲目信息用 `"t"`（titleMedium，比正文大一档）而且**只占一行**：两行的时候
        # 它把列表挤矮、卡底还留一截空白（m05745 点名的「底部空白」有它一份）。
        self.chart_info = txt("未选择曲目", self.tk, "t", color=self.tk.text,
                              text_align=ft.TextAlign.CENTER, max_lines=1,
                              overflow=ft.TextOverflow.ELLIPSIS)
        self.ingame_hint = txt("", self.tk, "s", color=self.tk.text_dim,
                               text_align=ft.TextAlign.CENTER, max_lines=1,
                               # 有话说的时候淡进来（与三处空态同一档 `MOTION["card"]`；
                               # 入口见 `Panel._set_hint`）。
                               animate_opacity=T.animation("card"))
        # 没话说就收起来（`_set_hint`）：空着也占一行的话，卡底又要留一截空白。
        self.ingame_hint.visible = False

        body = ft.Column([
            self.search,
            ft.Row([self.cat_box, self.sort_box, hit_pad(self.desc_btn)],
                   spacing=T.SPACE["sm"],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(content=self.count_text, alignment=ft.Alignment.CENTER),
            # 列表不再写死 240 高：窗口多高它就多高（开始页「自适应」的那一半）。
            ft.Container(content=ft.Column([self.song_list, self.song_empty], expand=True),
                         expand=True, border_radius=T.radius("field"),
                         border=ft.Border.all(1, self.tk.border), bgcolor=self.tk.field,
                         padding=ft.Padding(T.SPACE["xs"], T.SPACE["xs"],
                                            T.SPACE["xs"], T.SPACE["xs"])),
            hairline(self.tk),
            ft.Container(content=self.diff_label, alignment=ft.Alignment.CENTER),
            self.diff_hit,
            ft.Container(content=self.chart_info, alignment=ft.Alignment.CENTER,
                         padding=ft.Padding(0, T.SPACE["xs"], 0, T.SPACE["xs"])),
            self.ingame_hint,
            # `tight=True`（MainAxisSize.min）与 `expand` 打架：min 时那个 `expand` 的列表
            # 拿不到「剩下的那一截」，它按**自己的内容**长 —— 87 首就是 4000+ 逻辑像素，
            # 卡片装不下，后面的难度按钮与曲目信息全被切在卡外（实测整条列表一直铺到卡底，
            # 用户看到的「列表变得无限长」就是它）。去掉 `tight` 之后列表只吃余量。
        ], spacing=T.SPACE["sm"], expand=True,
            # 子控件一律撑满卡片宽度。Column 默认的 START 只给孩子「最宽到多少」的松约束，
            # 孩子会按自己的固有宽度收窄 —— 搜索框于是只到提示字那么宽（实测比下面的列表
            # 短 88 px），右边缘与列表、难度块对不上，整卡片看着就是「没对齐」。
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self._pick_body = body               # 探针第 11 关用来核对控件顺序（搜索框必须最上面）
        # `expand=True`（卡片本身）＋ body 也 expand：整张卡吃满左栏，列表跟着窗口长。
        return card(self.tk, body, title="选曲", icon=ft.Icons.LIBRARY_MUSIC,
                    box={"expand": True})

    def _build_run(self):
        d = self.state.get("defaults") or {}
        # 「轮」写进输入框自己的 `suffix`（Flet 的 suffix 是**另一个控件**，`field.value` 里
        # 仍然只有数字 —— `_clamp_field` 的 `float(raw)` 照旧读得动）。单位不再单占一个控件，
        # 「连续演出」那一格才装得下自己的数字框（第一行按用户点名只放连续 / 演出间隔两件事）。
        self.n_field = num_field(self.tk, int(d.get("runs", 1)), self._save_defaults,
                                 width=96, decimals=0, suffix=" 轮")
        # 六颗**开关**（m06250：勾选框换成 M3 Switch）—— 名字与回调一个没动，探针照旧认。
        # 全名（ALL PERFECT）与「只在上限之内往正推」这些解释都留在 tooltip 里。
        self.stop_ap = toggle(self.tk, int(d.get("stop_on_ap", 1)), self._save_defaults,
                              tooltip="达成 ALL PERFECT 后不再开始下一轮")
        # 「乐曲识别」与「随机乐曲」互斥（用户 m14282）：旧存档里两个都开着时按「随机」收口 ——
        # 与 `start_run` 里 `rnd` 的分支排在 `follow` 前面的老行为一致（那时跟随是静默被忽略的）。
        rnd_on = int(d.get("random", 0))
        follow_on = 0 if rnd_on else int(self.state.get("follow_game", 1))
        self.random_chk = toggle(self.tk, rnd_on, self._save_defaults,
                                 tooltip="每轮由游戏「随机选曲」抽取曲目，难度取游戏当前难度。\n"
                                         "与「乐曲识别」互斥：启用本项将关闭该项")
        # 火力门（用户 m13786；2026-10-11 用户 m26442 改成「拨档」）：开关放在「随机乐曲」后面，
        # 代价照规矩写进 tooltip。它现在不再拖长一局的时长，但它会**替用户改游戏里的 消耗LB 档位**，
        # 而那一档是粘的（下一次 Live 也沿用）—— 这两件事都得写清楚。
        self.fire_chk = toggle(self.tk, int(d.get("fire_gate", 0)), self._save_defaults,
                               tooltip="开始前读右上角加成火力，把 消耗LB 拨到该去的那一档："
                                       "≥3 点拨 3 档（消耗 3 点、奖励 ×15），不足 3 点拨 0 档"
                                       "（不烧火），然后照常开始演奏 —— 不再等待。\n"
                                       "3 档只在读得出够 3 点时才拨：弹窗自己写着「如果持有数量未达到"
                                       "设置的消耗数量，将消耗持有的全部数量」。\n"
                                       "这一档是粘的：游戏会沿用到之后的 Live，直到手动改回来。\n"
                                       "读数失败时不动 消耗LB，直接开始（不确定时也可演奏，损失有限）。")
        self.follow_chk = toggle(self.tk, follow_on, self._save_follow,
                                 tooltip="按游戏当前停留的曲目与难度演奏，无需在面板选择。\n"
                                         "与「随机乐曲」互斥：启用本项将关闭该项")
        self.push_chk = toggle(self.tk, int(d.get("push_cap", 1)), self._save_defaults,
                               tooltip="正推限制：仅当提前量小于上限时执行正向修正，避免单次修正过大")
        self.break_chk = toggle(self.tk, int(d.get("retry_on_break", 0)), self._save_defaults,
                                tooltip="断连重试：HUD 检测到断点后中途重开本局，每轮上限 N 次")
        # 运行策略的三个数并进这张卡（原「运行策略」卡已删）：开跑前要设、跑完要看，
        # 隔着一页的代价就是每改一次都得先翻页再翻回来。
        # 三个数现在跟管它们的开关**同排**（见下面 body）：格子只有半栏宽，所以框窄一点、
        # 格子里不再竖着堆标签，单位靠 ` ms` / ` 分` 后缀，全名挂在 tooltip 上
        # （`num_field` 不收 tooltip，建完补一笔）。
        self.policy_spins = {}
        for key, tip, suffix, dec, init, w in (
                ("push_cap_ms", "正推限制上限（ms）", " ms", 0,
                 int(d.get("push_cap_ms", core.PUSH_ON_MS)), 96),
                ("retry_cap", "每轮断连重试上限（次）", " 次", 0,
                 int(d.get("retry_cap", core.RETRY_CAP)), 96),
                ("gap_min", "演出间隔（分）", " 分", 0, int(d.get("gap_min", 0.0)), 96)):
            sp = num_field(self.tk, init, self._save_defaults, suffix=suffix, decimals=dec,
                           width=w)
            sp.tooltip = tip
            self.policy_spins[key] = sp
        self.policy_info = txt("", self.tk, "n", color=self.tk.text_dim)
        self.btn_start = button(self.tk, "开始演奏", lambda _e: self.start_run(False),
                                kind="filled", icon=ft.Icons.PLAY_ARROW, tooltip="F5")
        self.btn_force = button(self.tk, "强制开始", lambda _e: self.start_run(True),
                                kind="tonal", icon=ft.Icons.FAST_FORWARD,
                                tooltip="跳过画面核对，按面板所选谱面直接演奏")
        self.btn_stop = button(self.tk, "本轮停止", lambda _e: self.stop_run(),
                               kind="outlined", icon=ft.Icons.STOP_CIRCLE, disabled=True)
        self.btn_kill = button(self.tk, "强制终止", lambda _e: self.force_kill(),
                               kind="outlined", icon=ft.Icons.CANCEL, danger=True,
                               tooltip="立即终止正在运行的 run.py")

        # 瓦片与行的搭法在模块级（`opt_tile` / `opt_line`，2026-10-08 从这儿提上去的）——
        # 多人演出页那张运行卡用的是同一套，所以这里只留两个薄别名，下面的调用点一个字不改。
        def _tile(icon, label, *trail):
            return opt_tile(self.tk, icon, label, *trail)

        _line = opt_line

        # 三行设置项，顺序还是用户 m05361 点名的那个：
        #   ① 连续演出 / 演出间隔 —— 两枚瓦片，各带自己管的那个数框
        #   ② 乐曲识别 / 随机乐曲 / LB监测 / AP终止 —— 四枚均分瓦片，各带自己的开关
        #      （m14282：前两枚互斥，同一时刻只亮一颗；两颗都关 = 用面板列表里选中的那首）
        #   ③ 正推限制 + 上限 / 断连重试 + 每轮次数 —— 两枚瓦片，开关与数框并在控件行
        # 一件嵌套底色都没有（m06279 点名去掉）：行与行之间只用发丝线分节，瓦片靠对齐成组。
        # 宽度一处都不写死（`_line` 里那层 `Container(expand=True)` 均分），窗口多宽都是同一
        # 套比例；`spacing=md` 是瓦片之间的横向空档，属于**格里**，不会漏到格与格之间。
        self.opt_grid = ft.Column([
            _line(_tile(ft.Icons.SYNC, "连续演出", self.n_field),
                  _tile(ft.Icons.TIMER, "演出间隔", self.policy_spins["gap_min"])),
            hairline(self.tk),
            _line(_tile(ft.Icons.FOLLOW_THE_SIGNS, "乐曲识别", hit_switch(self.follow_chk)),
                  _tile(ft.Icons.SHUFFLE, "随机乐曲", hit_switch(self.random_chk)),
                  _tile(ft.Icons.LOCAL_FIRE_DEPARTMENT, "LB监测", hit_switch(self.fire_chk)),
                  _tile(ft.Icons.CHECK_CIRCLE, "AP终止", hit_switch(self.stop_ap))),
            hairline(self.tk),
            _line(_tile(ft.Icons.SPEED, "正推限制", hit_switch(self.push_chk),
                        self.policy_spins["push_cap_ms"]),
                  _tile(ft.Icons.RESTART_ALT, "断连重试", hit_switch(self.break_chk),
                        self.policy_spins["retry_cap"])),
        ], spacing=T.SPACE["sm"], tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.opt_panel = self.opt_grid     # 探针第 11 关用的老名字（同一个对象）
        # 设置区在上、动作区贴卡底：中间那段余量交给 `SPACE_BETWEEN` 摊到两区之间 ——
        # 余量一定小于一行摘要（`_sync_last_cards` 是整除取条数的），所以「开始按钮下面
        # 一大块空位」没有了，按钮落在卡底、与左栏的下沿对齐。
        _top = ft.Column([self.opt_panel, self.policy_info, self._build_stats()],
                         spacing=T.SPACE["sm"],
                         tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        # 两行动作按钮：四个都带图标、都铺满自己那半格（`fill`，与难度格同一套骨架）——
        # 从前只有 filled 的主按钮配了 ▶，宽度还各按文字收窄，四个不像一组（用户 m06156）。
        _acts = ft.Column([
            hairline(self.tk),
            ft.Row([fill(self.btn_start), fill(self.btn_force)], spacing=T.SPACE["sm"],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([fill(self.btn_stop), fill(self.btn_kill)], spacing=T.SPACE["sm"],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=T.SPACE["sm"], tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        body = ft.Column([_top, _acts], spacing=T.SPACE["sm"], expand=True,
                         alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self._run_body = body            # 探针第 11 关用它核对选项行与两行动作按钮
        # 并排时运行卡吃本栏剩下的高度（`body` 那份 `expand` + `SPACE_BETWEEN` 把余量摊在
        # 设置区与动作区之间）；窄到叠成一栏时 `_apply_window_class` 把这两处 `expand` 一起
        # 撤掉 —— 页一滚，竖方向就没有紧约束了。
        self.run_card = card(self.tk, body, title="运行", icon=ft.Icons.PLAY_CIRCLE_OUTLINE,
                             box={"expand": True})
        # 摘要句首帧就要有字：`refresh_policy` 从前只在 `_save_defaults`（动一下选项）时跑，
        # 于是刚打开面板时那行是空串、白占一行。这里按默认值先写成人话；`.update()` 在还没
        # 挂到页上时会抛，它自己 try/except 吞了（值已经设好，首帧就画得出来）。
        self.refresh_policy()
        return self.run_card

    def _build_log(self):
        """运行日志页：整页一张卡。

        从前它是开始页右栏的一张卡（7 栏宽，还得跟左边的选曲抢高度）。单开一页之后整页都是
        它的，`log_view` 本来就是 `expand=True` 的 `ListView`，行不用再截断着看。

        头两行：第一行 56（搜索框那一档 `T.FIELD_H`），第二行 48 —— 开关与三个按钮 2026-10-07
        按 2 级「触摸目标 48」补齐（用户 m21537/m21635；**可视高度没变**，补的是可点区）。
        第一行 chips + 关键词框 + 计数，第二行 开关 + 回顶 + 导出 + 清空。**关键词框是那一轮
        加的** —— 视图里最多留 `LOG_WINDOW`（2000）行，翻找某一次「重锁失败」靠翻页是不现实的；
        **回顶那颗是用户 m10610 加的**（关掉自动滚动不许把视图带走，另给一颗独立的回顶按钮）。
        """
        self.log_btns = {}
        btns = []
        for key, label in core.LOG_FILTERS:
            # 初始选中跟 `self.log_filter` 走，不写死 "all" —— 写死的话，将来任何一次重建
            # （或先被别处设过筛选）都会让 chip 的选中态与真正在筛的那个键**对不上**。
            b = chip_button(self.tk, label, key == self.log_filter,
                            lambda _e, k=key: self.set_log_filter(k),
                            tooltip=core.LOG_FILTER_TIPS[key])
            self.log_btns[key] = b
            # chip 只补上下：它的宽本来就 ≥48（最短的标签两个字 ≈60），补横向会与 8 的官方
            # chip-set 间距叠成负空隙（两条可点区互相压住，谁赢由命中顺序决定）。
            btns.append(hit_pad(b, pad_x=0, pad_y=HIT_PAD_CHIP))
        self.log_info = txt("", self.tk, "n", color=self.tk.text_dim)
        # 关键词框照选曲页那一枚写（`T.FIELD_H` + `input_border` + `bodyLarge`）：同一套控件
        # 在两页上就该长得一样。清空按钮按选曲页的规矩「有字才出现」。
        self.log_search_clear = ft.IconButton(
            icon=ft.Icons.CLOSE, icon_size=T.ICON_LG, visible=False,
            icon_color=self.tk.text_dim, tooltip="清空关键词",
            on_click=self._clear_log_search)
        self.log_search = ft.TextField(
            hint_text="关键词 / 时间戳", expand=True,
            height=T.FIELD_H, border=input_border(self.tk),
            text_style=T.type_style("bodyLarge"),
            prefix_icon=ft.Icons.SEARCH, suffix=hit_pad(self.log_search_clear),
            on_change=self._on_log_search)

        async def _pin_back(on, px):
            """翻面之后把位置接回来（`_auto` 的收尾，来路见它的 docstring）。

            **必须等一拍**：`auto_scroll` 换掉的是滚动控件的**元素树形状**，重建发生在客户端下一
            帧，复位发早了会打在即将被丢掉的那棵树上（`LOG_PIN_SETTLE_MS`）。复位期间 `_log_pin`
            立着：`scroll_to` 自己发出来的滚动事件只记位置、不许去掰开关（否则「贴着底关掉」会
            被镜像逻辑当场掰回「开」）。
            """
            self._log_pin = True
            try:
                await asyncio.sleep(LOG_PIN_SETTLE_MS / 1000.0)
                await self.log_view.scroll_to(offset=(-1.0 if on else px), duration=0)
                await asyncio.sleep(LOG_PIN_SETTLE_MS / 1000.0)
            except Exception as ex:                              # noqa: BLE001
                self._write_line(f"日志定位失败：{ex!r}", "log_err")
            finally:
                self._log_pin = False

        def _auto(e):
            """「自动滚动」开关翻面：**关掉不带走视图、打开落到底部**（用户 m10610）。

            从前只有一句 `self.log_view.auto_scroll = bool(e.control.value)`。这个属性在客户端
            换掉的是滚动控件的元素树形状（`scrollable_control.dart` 的 `build()` 只在它为真时把
            列表包进一层 `NotificationListener`）⇒ 子树重建、滚动位置丢掉 ⇒ **关掉那一刻整屏
            日志跳回顶部**（真面板实测：翻面前后两张截图 mean 差 6.86、7 万个像素变了）。
            所以这里自己把位置接回来：翻之前记下 `_log_pixels`，翻完交给 `_pin_back` 复位；打开
            那一侧按用户要求仍落到底部（`offset=-1` = 从末尾算 1 px，官方 docstring 就这么写的）。

            这一路是同步的：`hit_switch` 的补边带用 `cb(SimpleNamespace(control=sw))` 直接调它，
            协程函数在那里不会被 await（补边带上点一下会静默失效）⇒ 异步那半截交给 `run_task`。
            """
            on = bool(e.control.value)
            px = max(0.0, float(self._log_pixels or 0.0))
            self.log_view.auto_scroll = on
            self._push_ctl(self.log_view)
            self.page.run_task(_pin_back, on, px)

        self.log_autoscroll = switch(self.tk, "自动滚动", True, _auto,
                                     tooltip="新日志自动滚动到底部；关闭后可停留在当前位置翻阅")
        # 回顶：工具栏里的 M3 **图标按钮**（图标色 `on_surface_variant`、24 图标、48 可点区由
        # `hit_pad` 补齐 —— 与搜索框那枚清空按钮同一套）。它与开关是两件事：开关管「新行来不
        # 来拉我」，这一颗只管「现在回到第一行」，所以按用户 m10610 做成**独立**的一颗，而不是
        # 塞进开关的语义里。放在右簇（导出/清屏那边）也是为了不让它读成开关的附件。
        self.log_top_btn = ft.IconButton(
            icon=ft.Icons.VERTICAL_ALIGN_TOP, icon_size=T.ICON_LG,
            icon_color=self.tk.text_dim, tooltip="回到第一行",
            on_click=self._log_to_top)
        head = ft.Column([
            # chip 之间 8：官方 chip set 的间距就是 8（material-web
            # `chips/internal/_chip-set.scss` 的 `:host { gap: 8px }`），从前写 4。
            ft.Row(btns + [self.log_search, self.log_info],
                   spacing=T.SPACE["sm"],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            # 间距取 `sm`(8)：两个按钮各补了 4 的横向内边距，再留 4 的话两条可点区会叠 4 px
            # （M3 也说目标之间留 8 以上）。从前的 `xs`(4) 是没补内边距时的写法。
            ft.Row([
                hit_switch(self.log_autoscroll),
                ft.Container(expand=True),
                hit_pad(self.log_top_btn),
                hit_pad(button(self.tk, "导出日志",
                               lambda _e: save_log(self.page, self.tk, self.log_store),
                               icon=ft.Icons.SAVE_ALT,
                               tooltip="将全部日志导出到 research/logs/ 目录")),
                hit_pad(button(self.tk, "清屏", lambda _e: self.clear_log(),
                               icon=ft.Icons.CLEAR_ALL, tooltip="清空日志（Ctrl+L）")),
            ], spacing=T.SPACE["sm"],
                vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=T.SPACE["xs"])
        self.log_empty = empty_state(self.tk, ft.Icons.ARTICLE_OUTLINED, "没有日志",
                                     "开始一轮演奏后，日志将实时显示在此处")
        # 第二种空：库里明明有行，只是被页签或关键词筛没了。两种空的原因不同，文案就不许混
        # ——「没有日志」压在「显示 0 / 共 412 行」底下是自相矛盾。
        self.log_none = empty_state(self.tk, ft.Icons.SEARCH_OFF, "没有匹配",
                                    "请更换关键词，或将筛选恢复为「全部」")
        # 控制台面板：列表与两张空态都住在这个「下沉一档」的凹面里。M3 的五级 surface container
        # 里，卡片是 `surface_container_low`（`CardTokens.ElevatedContainerColor`），再往下一档
        # 就是基面 `surface` —— 日志正是一屏字，用基面才读得出一块「屏」。圆角取 `card`（官方
        # `CornerMedium` = 12dp）；`clip_behavior` 必须给：整行带是方的，不裁会顶出面板的圆角。
        self.log_pane = ft.Container(
            content=ft.Column([self.log_view, self.log_empty, self.log_none],
                              spacing=T.SPACE["sm"], expand=True),
            bgcolor=self.tk.surface, border_radius=T.radius("card"),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS, expand=True)
        # 工具行与控制台之间一条分界线（官方 `DividerTokens.Color = OutlineVariant`，厚 1dp）：
        # 从前工具栏直接贴着第一行日志，两边都是一行字，分不出哪块是哪块。
        body = ft.Column([head, hairline(self.tk), self.log_pane],
                         spacing=T.SPACE["sm"], expand=True)
        # **首帧就把排他关系算出来**：`log_view` 与两张空态都是 `expand=True`，两个都可见就是
        # 各占一半。从前的日志基线拍的正是那个「两个都可见」的状态（空态落在下半格），而真机上
        # 它只存在一两帧 —— 因为 `_refresh_log_info` 要等第一条日志才被调用。见 probes/README.md。
        self._refresh_log_info()
        return card(self.tk, body, title="运行日志", icon=ft.Icons.ARTICLE_OUTLINED,
                    box={"expand": True})

    # ---------------- 页面：结算记录 ----------------

    def _build_history(self):
        self.hist = HistModel()
        self.hist.set_limit(core.hist_limit(self.state))
        self.hist_filter = "all"
        self.hist_btns = {}
        self.hist_src_btns = {}
        self.hist_row_tag = None
        self._flash_tag = None
        self._flash_seq = 0
        # 双击判定的上一击（`_on_hist_select`）；Flet 的 `DataRow` 只有 `on_select_change`。
        self._hist_click_tag = None
        self._hist_click_at = 0.0

        btns = []
        for key, label in core.HIST_FILTERS:
            b = chip_button(self.tk, label, key == "all",
                            lambda _e, k=key: self.set_hist_filter(k),
                            tooltip=core.HIST_FILTER_TIPS[key])
            self.hist_btns[key] = b
            btns.append(hit_pad(b, pad_x=0, pad_y=HIT_PAD_CHIP))
        # 来源那两枚（2026-10-10 用户 m13266）：与判定那五枚同一排、中间用 1dp 竖线分开 ——
        # 两枚可以同时点亮（都亮 = 两半都列），所以它们不跟判定那组互斥。竖线取 `tk.border`
        # （= 主题的 `divider_color`，outline-variant），高度就是 chip 自己的 32。
        src = []
        for key, label in core.HIST_SOURCES:
            b = chip_button(self.tk, label, key in self.hist.sources,
                            lambda _e, k=key: self.set_hist_source(k),
                            tooltip=core.HIST_SOURCE_TIPS[key])
            self.hist_src_btns[key] = b
            src.append(hit_pad(b, pad_x=0, pad_y=HIT_PAD_CHIP))
        self.hist_info = txt("", self.tk, "n", color=self.tk.text_dim)
        # 显示条数：几百行时 `DataTable` 会明显卡，所以表上只画前 N 行。档位 = 预设 + 当前值
        # （手改过状态文件时把当前值补进 options —— 值不在 options 里 Flet 的 Dropdown 会断言失败）。
        lim_opts = list(core.HIST_LIMITS)
        if self.hist.limit not in lim_opts:
            lim_opts.append(self.hist.limit)
        lim_opts.sort(key=lambda n: (n == 0, n))
        self.hist_limit_box = dropdown(
            self.tk, [(str(n), core.hist_limit_label(n)) for n in lim_opts],
            str(self.hist.limit), self._on_hist_limit,
            tooltip="表格最多绘制多少行（记录较多时客户端会卡顿）。仅影响表格绘制行数 —— "
                    "筛选计数、「导出 CSV」与页脚统计仍按全部记录计算。")
        # 两行、都不换行：**会换行的 `Row` 里不能放 `expand=True` 的孩子** —— Flutter 的 `Wrap`
        # 收到 `Expanded` 孩子会在布局期抛异常，整个内容区被错误控件盖成一片 `#C0C0C0`
        # （量过：`#C0C0C0` @ α=0.943 在暗底 `#121318` 上正好是 `#b6b6b6`）。
        head = ft.Column([
            ft.Row(btns + [ft.Container(width=1, height=CHIP_H, bgcolor=self.tk.border)]
                   + src + [ft.Container(expand=True), self.hist_info],
                   spacing=T.SPACE["sm"],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([
                field_label("显示条数", self.tk),
                self.hist_limit_box,
                ft.Container(expand=True),
                hit_pad(button(self.tk, "重新读取", lambda _e: self.refresh_data(),
                               icon=ft.Icons.REFRESH,
                               tooltip="重读谱面库与结算记录（Ctrl+R）")),
                hit_pad(button(self.tk, "这一局", lambda _e: self.open_diag(),
                               icon=ft.Icons.INSIGHTS,
                               tooltip="把选中的那一局压成几行读数（谱面／链路／锚定／修正／投递）")),
                hit_pad(button(self.tk, "打开截图", lambda _e: self.open_shot(),
                               icon=ft.Icons.IMAGE,
                               tooltip="打开这一局的 HUD 截图")),
                hit_pad(button(self.tk, "取证目录", lambda _e: self._open_dir("evidence"),
                               icon=ft.Icons.FOLDER_OPEN,
                               tooltip="打开 research/frames 与 evidence 所在目录")),
                # 四个里只有它「产出一个东西」，给它 tonal 这一档：M3 里同一行按钮要有主次。
                hit_pad(button(self.tk, "导出 CSV", lambda _e: self.export_history(),
                               kind="tonal", icon=ft.Icons.DOWNLOAD,
                               tooltip="将当前筛选结果导出为 CSV")),
            ], spacing=T.SPACE["sm"],
                vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=T.SPACE["xs"])

        # 列集与列宽按窗口宽现算（用户 m12075：「表单宽度应与窗口宽度保持同步」）。`_hist_sig`
        # 是这份预算的指纹：resize 时只有指纹变了才重建 columns/rows（见 `_sync_hist_cols`）。
        self._hist_cols, self._hist_w = self._hist_layout(self.page.width)
        self._hist_sig = self._hist_sig_of(self._hist_cols, self._hist_w)
        self.hist_table = ft.DataTable(
            columns=self._build_hist_cols(self._hist_cols, self._hist_w), rows=[],
            column_spacing=T.SPACE["md"],
            horizontal_margin=T.SPACE["sm"],
            heading_row_height=T.HIST_HEAD_H,
            data_row_min_height=T.HIST_ROW_H, data_row_max_height=T.HIST_ROW_H,
            # 行分隔线：官方 `row-item-outline-color = outline-variant`、`row-item-outline-width =
            # 1px` —— 那条线就是主题里的 `divider` 色（本项目 = `outline_variant`）。从前撤掉它的
            # 理由（「Flet 不暴露这条线的颜色」）是错的，真凭据在 `tools/probes/README.md`：那一趟
            # 截图里的 1628 px「异常灰」量出来是**灰字的反锯齿**，与分隔线无关。
            divider_thickness=T.HIST_OUTLINE_W,
            horizontal_lines=ft.BorderSide(T.HIST_OUTLINE_W, self.tk.border),
            # 外框：官方 `outline-color = outline-variant`、`outline-width = 1px`。这 1 px 落在数据表
            # 自己的 `horizontal_margin`(8) 里 ⇒ 列宽预算不用加它（`_hist_demand` 一行没动）。
            border=ft.Border(top=ft.BorderSide(T.HIST_OUTLINE_W, self.tk.border),
                             right=ft.BorderSide(T.HIST_OUTLINE_W, self.tk.border),
                             bottom=ft.BorderSide(T.HIST_OUTLINE_W, self.tk.border),
                             left=ft.BorderSide(T.HIST_OUTLINE_W, self.tk.border)),
            # 表头底色 = **官方 `header-container-color`**：就是 `surface`，与页面同色 —— 于是表头那一带
            # 只靠表头下边那条 1 px `row-item-outline` 与 `titleSmall` 的字分界（从前取
            # `surface_container_high` 抬一档，是为了「别糊进页面底色」，但那是本项目自己的判断，
            # 已从 `DEVIATIONS` 里撤掉：用户 m12800 要的是照官方）。
            heading_row_color=self.tk.surface,
            heading_text_style=T.type_style(T.HIST_HEAD_FONT),
            data_text_style=T.type_style(T.HIST_CELL_FONT),
            border_radius=T.radius("card"),
        )
        self.hist_empty = empty_state(self.tk, ft.Icons.INBOX, "没有记录",
                                      "请调整筛选条件，或先完成一局")
        self.hist_empty.visible = False
        # 纵向滚：行数由「显示条数」压着（几百行时 `DataTable` 每个格子都是一个控件、客户端会卡）。
        # 横向也留着能滚，但它只是兜底：列集已经按窗口宽现算过（`_hist_layout`），只有窗口窄到
        # 连必留的五列都摆不下才用得上 —— 正常尺寸下这张表是**正好**铺满内容区的。
        box = ft.Column([ft.Row([self.hist_table], scroll=ft.ScrollMode.AUTO)],
                        scroll=ft.ScrollMode.AUTO, expand=True)
        self.hist_box = box
        body = ft.Column([head, box, self.hist_empty], spacing=T.SPACE["sm"], expand=True)
        return ft.Container(content=body, expand=True)

    # ---------------- 结算表：列宽跟着窗口走 ----------------

    @staticmethod
    def _hist_sig_of(cols, widths):
        """这份列预算的指纹：列集 + 每列宽。用来判「resize 之后要不要重排」。"""
        return tuple((c, widths[c]) for c in cols)

    def _hist_demand(self, cols, widths):
        """整张表的自然宽（逻辑 px）：色条列 + 每列(列宽 + 可排序列预留的箭头那一格)
        + 列间距 + 两端 `horizontal_margin`。

        `widths` 是视图层这份预算里的列宽（可能与 `core.HIST_WIDTHS` 不同 —— 「歌曲」列会吃掉
        余量）。第 0 列（色条）没有 `on_sort`，不算 `T.HIST_ARROW_W`。探针拿它反推每一列的左沿
        与实拍对（`fletpanel.py` 第 1 关）—— 所以这个式子只许有一处，不许在别处再写一遍。
        """
        cells = core.CHIP_W + sum(widths[c] + T.HIST_ARROW_W for c in cols)
        return cells + T.SPACE["md"] * len(cols) + 2 * T.SPACE["sm"]

    def _hist_avail(self, width):
        """内容区可用宽（逻辑 px）：窗口宽 − 导航栏 − 页面左右内边距。

        导航轨**永远收起**（用户 m18525 定的版式，见 `m3_theme.DEVIATIONS` 最后一条）：屏幕上只有
        `NAV_MIN_W`(80) 这一档，所以这里也只减它 —— 与 `_apply_window_class` 里把 `rail.extended`
        写死 False 的是**同一个决定**，否则表会按一个屏幕上并不存在的宽度排版。窗口宽拿不到时按
        `WINDOW_DEFAULT` 兜底。
        """
        w = float(width or 0) or float(T.WINDOW_DEFAULT[0])
        return w - T.NAV_MIN_W - 2 * T.SPACE["lg"]

    def _hist_layout(self, width):
        """按窗口宽挑可见列、定列宽。

        可用宽见 `_hist_avail`。必留的 `T.HIST_FIT_ALWAYS` 先占位，再按 `T.HIST_FIT_ORDER` 依次
        加，加不下的不画；余量全给「歌曲」列，但按 `SPACE["xl"]` 取整 —— 每次 resize 都重排整张表
        的话，拖动窗口时客户端会一帧一帧地重算上百行格子（`_apply_window_class` 里「只在换挡那一
        下动版面」是同一个坑）。

        列宽的底子取 `T.hist_width(core.HIST_HEADS[c][1])`：`HIST_WIDTHS` 是按 9pt 量的，字号已经
        抬到官方那两档（`T.HIST_HEAD_FONT` / `T.HIST_CELL_FONT`），换算只有那一个出处。
        """
        w = float(width or 0) or float(T.WINDOW_DEFAULT[0])
        avail = self._hist_avail(w)
        base = {c: T.hist_width(core.HIST_HEADS[c][1]) for c in core.HIST_COLS}
        cols = [c for c in core.HIST_COLS if c in T.HIST_FIT_ALWAYS]
        for c in T.HIST_FIT_ORDER:
            if c not in cols and self._hist_demand(cols + [c], base) <= avail:
                cols.append(c)
        cols = [c for c in core.HIST_COLS if c in cols]        # 回到阅读顺序（挑列的次序不是它）
        widths = dict(base)
        slack = avail - self._hist_demand(cols, base)
        if slack > T.SPACE["xl"]:
            widths["song"] = int(base["song"] + slack // T.SPACE["xl"] * T.SPACE["xl"])
        return cols, widths

    def _build_hist_cols(self, cols, widths):
        """表头：第 0 列是行首色条（不排序、不给 tooltip），其余每列都可排序（点表头排序）。

        表头字取官方的 `header-headline = title-small`（`T.HIST_HEAD_FONT`），对齐跟着这一列的
        数据走：数值列（`core.HIST_RIGHT`，1 基列号）右对齐并 `numeric=True`，居中列居中，其余左
        对齐 —— 官方数据表里表头与数值共用一条对齐轴。`HIST_RIGHT`/`HIST_CENTER` 存的是**1 基列
        号**，这里的 `c` 是列名 ⇒ 先换算回列号（照抄 `_hist_row` 的写法）。
        """
        out = [ft.DataColumn(label=ft.Container(
            content=txt(core.HIST_TITLES[0], self.tk, T.HIST_HEAD_FONT, color=self.tk.text_dim),
            width=core.CHIP_W, alignment=ft.Alignment.CENTER_LEFT))]
        for c in cols:
            title = core.HIST_HEADS[c][0]
            n = core.HIST_COLS.index(c) + 1
            right = n in core.HIST_RIGHT
            align = (ft.Alignment.CENTER_RIGHT if right
                     else (ft.Alignment.CENTER if n in core.HIST_CENTER
                           else ft.Alignment.CENTER_LEFT))
            out.append(ft.DataColumn(
                label=ft.Container(content=txt(title, self.tk, T.HIST_HEAD_FONT,
                                               color=self.tk.text_dim),
                                   width=widths[c], alignment=align),
                numeric=right,
                heading_row_alignment=ft.MainAxisAlignment.END if right else None,
                on_sort=lambda _e, k=c: self._on_hist_sort(k),
                tooltip=f"按「{title.strip()}」排序"))
        return out

    def _sync_hist_cols(self, width):
        """窗口宽变了就重挑列（`_apply_window_class` 每次 resize 都会喊一声）。

        只有指纹变了才重建 `columns` 并重画：每个 resize 事件都重排一次的话，拖动窗口时客户端会
        一帧一帧地重算上百行格子（`_apply_window_class` 里「只在换挡那一下动版面」是同一个教训）。
        列宽变了也必须重建行 —— 每个格子的宽度是写在 `Container.width` 上的。
        """
        if getattr(self, "hist_table", None) is None:
            return
        cols, widths = self._hist_layout(width)
        sig = self._hist_sig_of(cols, widths)
        if sig == getattr(self, "_hist_sig", None):
            return
        self._hist_sig = sig
        self._hist_cols, self._hist_w = cols, widths
        self.hist_table.columns = self._build_hist_cols(cols, widths)
        self._render_history()

    def _hist_row(self, i, tag):
        cells = self.hist.cells[tag]
        letter = self.hist.letters[tag]
        kind = self.hist.kinds[tag]
        hi = (tag == self.hist_row_tag) or (tag == self._flash_tag)
        # 选中与「刚结算」共用同一套 M3 高亮：整行抬成官方数据表的
        # `row-item-selected-container-color = surface_container_highest`（700 ms 之后 `_flash_tick`
        # 自己退回去）。**行底色不铺难度色**（用户原话：「把这些列表项背景色去了吧」）—— 行与行靠
        # 官方那条 `row-item-outline`（`divider_thickness`/`horizontal_lines`，见 `_build_history`）
        # 与行首竖条分开，不铺斑马线（M3 的数据表本来也不铺）；难度只由「难度」那一格的字色承担、
        # 结果由行首竖条与「判定」那一格承担。
        #
        # 选中态**只动容器**、不重染格子：官方那条 token 是容器色，配的字色是
        # `row-item-selected-label-text-color = on_surface`（就是未选中行用的同一个 `tk.text`），
        # 而「难度」那一格与「判定」那一格是本项目自己的**状态色**（不是 label）—— 它们在
        # `surface_container_highest` 这种中性抬升面上仍是各自对的那一对颜色，所以点一行不会把这一
        # 行的难度色/结果色点没。2026-10-06 之前这里铺的是 `secondary_container` + 反色字，那条
        # 偏离记在 `DEVIATIONS` 里、用户 m16213 让改回官方，条目已撤。
        ink = self.tk.text
        # 行底色照官方数据表：未选中那一档是 `row-item-unselected-container-color = surface`，而
        # Flutter 那层的默认行底色本来就是 `surface` ⇒ 这里干脆不写（`None`，让默认生效）。
        bg = self.tk.surface_container_highest if hi else None
        chip = {"ap": self.tk.chip_ap, "fc": self.tk.chip_fc,
                "np": self.tk.chip_np, "err": self.tk.chip_err}.get(kind)
        out = [ft.DataCell(ft.Container(
            content=(ft.Container(width=core.CHIP_W - 2, bgcolor=chip,
                                  border_radius=T.radius("extraSmall"))
                     if chip else None),
            width=core.CHIP_W, height=20))]
        diff_col = core.HIST_COLS.index("diff") + 1
        badge_col = core.HIST_COLS.index("badge") + 1
        # 只画这一档窗口选中的列（`_hist_cols`）；格子里的颜色/对齐/「是不是 0」仍按
        # `core.HIST_COLS` 里的 1 基列号算 —— 列被丢掉时那些编号不该跟着挪。
        for name in self._hist_cols:
            c = core.HIST_COLS.index(name) + 1
            v = cells[c]
            if c == diff_col:
                color = self.tk.diff_letter(letter)          # 难度：字色，不是底色
            elif c == badge_col:
                color = chip or ink                          # 结果：与行首竖条同一个色
            elif v != "" and self.hist.is_muted(tag, c):
                color = self.tk.zero_dim
            else:
                color = ink
            align = (ft.Alignment.CENTER if c in core.HIST_CENTER
                     else (ft.Alignment.CENTER_RIGHT if c in core.HIST_RIGHT
                           else ft.Alignment.CENTER_LEFT))
            out.append(ft.DataCell(ft.Container(
                content=txt(str(v), self.tk, T.HIST_CELL_FONT, color=color, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                width=self._hist_w[name], alignment=align)))
        # 悬停态层：官方数据表**只有 hover 这一档**行状态层（`row-item-unselected-hover-state-layer-color`
        # 与 `row-item-selected-hover-state-layer-color` 都是 `on-surface`，opacity 就是 8%），而
        # `DataRow.color` 只吃平色 ⇒ 先在令牌层把「行底色 + 状态层」合成熟色（`T.hover_fill`）。
        # `HOVERED` 写在 `DEFAULT` 前头：指针压在表上那一行取悬停色，没被指到的行落 DEFAULT
        # （`ControlState.DEFAULT` 的语义就是「未声明的状态一律用它」）。`T.HOVER_STATE` 是拍照与
        # 探针路径的开关 —— 窗口开在鼠标底下，不关掉的话基线会随鼠标位置变（见它的注释）。
        # 悬停关着时未选中行的 `color` 就是 `None`：官方 `row-item-unselected-container-color` 也是
        # `surface`，而 Flutter 那层的默认值本来就是它 —— 让默认生效比写死一个同色更好（`fletpanel`
        # 第 1 关也是靠 `color is None` 认出「这一行没铺底色」的）。
        color = bg
        if T.HOVER_STATE:
            color = {ft.ControlState.HOVERED: self.tk.hover_fill(bg or self.tk.surface),
                     ft.ControlState.DEFAULT: bg or self.tk.surface}
        return ft.DataRow(cells=out, color=color,
                          on_select_change=(lambda _e, t=tag: self._on_hist_select(t)))

    def _render_history(self):
        """把模型的当前状态画到表上。筛选、排序、选中、改显示条数、新落一局，五条路都过这里。

        画的是 `hist.shown()`（前 `limit` 行）而不是 `hist.tags` —— 但**只画**这一层受限：
        页脚与 CSV 导出读的仍是 `hist.tags`（全部筛出行）。
        """
        # 排序箭头：Flutter 只在 `sort_column_index` 指到某一列时才画那一列的箭头 —— 而列宽
        # 里那 18 px（`T.HIST_ARROW_W`）是它先占下的，从前一直白占着不画（`_DataTableDefaultsM3`
        # 的实据）。排序列被这一档窗口挤掉时不指回去，宁可没有箭头也不指错列。
        if self.hist.sort_col in self._hist_cols:
            self.hist_table.sort_column_index = self._hist_cols.index(self.hist.sort_col) + 1
        else:
            self.hist_table.sort_column_index = None
        self.hist_table.sort_ascending = not self.hist.sort_desc
        rows = [self._hist_row(i, t) for i, t in enumerate(self.hist.shown())]
        self.hist_table.rows = rows
        vis, _ap = self.hist.tally()
        empty = vis == 0
        self.hist_table.visible = not empty
        # 空的时候把整个滚动区也收起来：它与空态都是 `expand=True`，留着会各占一半，
        # 空态就贴在页面的下半截而不是居中。
        self.hist_box.visible = not empty
        self._toggle_empty(self.hist_empty, empty)
        self.update_tally()
        try:
            self.page.update()
        except Exception:                                        # noqa: BLE001
            pass

    # ---------------- 页面：设置 ----------------

    def _build_settings(self):
        """设置页：**上面两张卡左右并排** —— 左「面板」（一次性的偏好：外观 / 字体 / 动画 /
        清理 / 重启）、右「资源」（联网更新谱面库：先比对上游目录，再补下载缺失的谱面）；
        **下面一行是「种类偏移」**（四类键各一个带符号的毫秒框，用户 m15057，m15291 改名），
        独占整行。

        运行策略与链路标定搬去了开始页（那两张是「开跑前后要扫一眼」的）。这里走 12 栏栅格、
        每张卡占 **6 栏**：两张 6/12 正好铺满整行，窄过 `STACK_W` 时各自撑满一栏、上下叠起来
        （换挡在 `_apply_window_class` —— 基础值带 `md` 断点，而窗口下限 800 已越过 768，
        不换挡就会停在 6/12 缩成窄栏）。2026-10-10 用户 m13525 把原来的「各占 7 栏、居中」
        改成左右布局：那时两张 7/12 加起来 14 栏、栅格自己换行，其实是**上下**堆着的。

        2026-10-10 用户 m15291「优化设置界面的美观度，横平竖直贴边对齐」之后，这一页的三条
        硬规矩是：① 上面两张卡**等高** —— 各钉同一个实测高度 `SET_CARD_H`（`box={"height": …}`），
        **不走 `CrossAxisAlignment.STRETCH`**：这一页外层 Column 可滚 ⇒ 主轴无界，实测整页只剩
        96.73% 页面底色（`research/frames/set_now.png`），两张卡各 `expand` 也救不回来；
        ② 下面那张卡的四枚框**铺满各自那一格**（`expand=True`，四栏左右都贴到卡的内沿）；
        ③ 行距与列距**同档**（都是 `SPACE["sm"]` = 8），整页是一个网格。
        """
        self.appearance_box = dropdown(
            self.tk, list(zip(core.APPEARANCE_KEYS, core.APPEARANCE_CHOICES)),
            self.state.get("appearance") or "auto", self._save_appearance, width=140)
        self.font_box = dropdown(
            self.tk, [(k, T.FONTS[k]["label"]) for k in T.FONT_KEYS],
            self.font_key, self._save_font, width=140)
        self.font_hint = txt("", self.tk, "s", color=self.tk.text_dim, max_lines=3)
        # 统一用 M3 开关（m06250 把运行卡那五颗勾选框换成开关，这一页跟着换 —— 同一个应用里
        # 两种「开关」并存会让人以为是两种东西）。开关不带文字（见 `toggle` 的 docstring），
        # 所以标签回到左边那一列，和上面「外观 / 字体」两行同一个版式；全名进 tooltip。
        self.motion_chk = toggle(
            self.tk, int(self.state.get("motion", 1)), self._save_motion,
            tooltip="过渡动画：新结算行的强调效果；关闭后立即完成，不播放动画")
        self.autoclean_chk = toggle(
            self.tk, int(self.state.get("auto_clean", 1)), self._save_autoclean,
            tooltip="每轮结束自动清理：删除调试截图、过期取证与脚本缓存（不删除录像）")
        self.panel_card = card(self.tk, ft.Column([
            ft.Row([field_label("外观", self.tk), ft.Container(expand=True),
                    self.appearance_box], spacing=T.SPACE["sm"],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([field_label("字体", self.tk), ft.Container(expand=True), self.font_box],
                   spacing=T.SPACE["sm"], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.font_hint,
            ft.Row([field_label("过渡动画", self.tk), ft.Container(expand=True),
                    hit_switch(self.motion_chk)], spacing=T.SPACE["sm"],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([field_label("自动清理", self.tk), ft.Container(expand=True),
                    hit_switch(self.autoclean_chk)], spacing=T.SPACE["sm"],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([hit_pad(button(self.tk, "立即清理", lambda _e: self.cleanup_junk())),
                    hit_pad(button(self.tk, "重启面板", lambda _e: self.restart_panel()))],
                   spacing=T.SPACE["sm"], wrap=True),
        ], spacing=T.SPACE["sm"], tight=True), title="面板", icon=ft.Icons.SETTINGS,
            box={"height": SET_CARD_H})

        # ---- 资源卡：联网更新谱面库 ----
        # Tk 版的设置页本来就有「联网更新 + 强制重下 + 首选目录 + 读数」这一组，面板全面转
        # PySide6 时整组被删了，只剩视图层那两个处理器没人喂事件（`upstream` / `charts_done`），
        # 而 `_after_check` 那句「可在设置里联网更新」指向一个不存在的按钮 —— 用户报「设置里的
        # 资源更新不见了」（m06894）。这里按 M3 的语义重建：次操作按钮（tonal）+ 两枚开关 +
        # 一个下拉 + 一行读数。
        # 两枚开关**都不落盘**：一次 `--force` 会把全部谱面重新下载并重编译，一次 `--verify`
        # 是一张一个请求，都不该跟着面板一起开机生效（Tk 版也是当场读活变量）。首选目录落盘 ——
        # 它只决定先问哪一边，改一次就长期有效。
        self.update_btn = button(
            self.tk, "联网更新", lambda _e: self.start_update(), kind="tonal",
            icon=ft.Icons.DOWNLOAD,
            tooltip="先比对上游谱面库是否有新曲、新难度或被改动的谱面（一小时内的比对结果不"
                    "重复请求），再补下载缺失的谱面与封面并重新编译。\n"
                    "已存在的文件不会重复下载；已演奏的谱面即使被重新编译，其原有字节也会放回"
                    "原处（新字节进入重学队列）。更新期间无法开始演奏。")
        self.force_chk = toggle(
            self.tk, 0, None,
            tooltip="强制重下：忽略本地已有文件，全部重新下载并重新编译（含已演奏的谱面）。\n"
                    "已演奏的谱面用 evidence/pins 中的字节放回原处，编译器新要求的字节进入重学"
                    "队列。每次启动面板均默认为关闭状态。")
        self.source_box = dropdown(
            self.tk, list(zip(core.SOURCE_KEYS, core.SOURCE_CHOICES)),
            core.preferred_source(self.state), self._save_source, width=140,
            tooltip="首选目录（决定优先查询哪一方的目录表）\n"
                    "MoeNotes：先查询 GitHub 上的 master 表；若未变动则不再查询 archive（默认）。\n"
                    "Haneoka：直接查询 archive —— 逐张核对字节时必须查询它"
                    "（仅它提供可编译字节）。")
        self.verify_chk = toggle(
            self.tk, 0, None,
            tooltip="逐张核对：默认仅比较目录报告的「判定物数」（noteCount / 等级），"
                    "而 noteCount 可能在改谱后保持不变 —— 纯几何改动只有把点名的谱面真正下载"
                    "并按 sha 比对一次才能发现（下载到 research/upstream/，不修改谱面库）。\n"
                    "较慢：一张谱面一次请求，仅在怀疑上游改过谱面时启用。每次启动面板均默认为关闭状态。")
        self.res_hint = txt("", self.tk, "s", color=self.tk.text_dim, max_lines=2)
        self.res_card = card(self.tk, ft.Column([
            ft.Row([field_label("谱面库", self.tk), ft.Container(expand=True),
                    hit_pad(self.update_btn)], spacing=T.SPACE["sm"],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([field_label("首选目录", self.tk), ft.Container(expand=True),
                    self.source_box], spacing=T.SPACE["sm"],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([field_label("强制重下", self.tk), ft.Container(expand=True),
                    hit_switch(self.force_chk)], spacing=T.SPACE["sm"],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([field_label("逐张核对", self.tk), ft.Container(expand=True),
                    hit_switch(self.verify_chk)], spacing=T.SPACE["sm"],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            self.res_hint,
        ], spacing=T.SPACE["sm"], tight=True), title="资源", icon=ft.Icons.CLOUD_DOWNLOAD,
            box={"height": SET_CARD_H})

        # ---- 种类偏移卡（用户 m15057「把四种都放出来」；m15291 改名「分类偏移」，
        #      2026-10-21 用户 m53176 改成「种类偏移」）----
        # 每类键一个**带符号的整数毫秒**框：正数 = 更早按下，负数 = 更晚。四个框 2026-10-05
        # 被删过（那时面板里没法验读数），现在按用户要求回到**设置页**（原来长在运行策略卡
        # 上）。放这一页而不是运行卡：它是一次调好、之后基本不动的标定值，与「开跑前要扫一眼」
        # 的那三个数不是一类。整张卡 12 栏独占一行，塞进上面那个 6/12 + 6/12 的栅格会被
        # `_apply_window_class` 一起压成 6/12。
        #
        # **框宽由版式定**（用户 m15291「横平竖直贴边对齐」）：从前四枚一律 `width=96`，而每格
        # 有 275 逻辑 —— 于是框只占三分之一，第四枚右沿离卡片内沿还差 180 逻辑，看着是四个小
        # 盒子漂在四栏里。现在每枚 `expand=True` 铺满自己那一格，四栏左右都贴到卡的内沿
        # （`num_field` 的 docstring 早写着「宽度不是规范量，宽度由版式定」）。
        kd = (self.state.get("defaults") or {}).get("kind_lead") or {}
        self.kind_spins = {}
        for k, icon, label, tip in KIND_TILES:
            sp = num_field(self.tk, int(kd.get(k, 0.0) or 0.0), self._save_kind_lead,
                           suffix=" ms", decimals=0, width=None)
            sp.expand = True
            sp.tooltip = tip
            self.kind_spins[k] = sp
        # 尾判滑键（用户 m52916「能否将尾滑偏移加入设置」）。它不是一个种类，而是
        # 「长条尾巴上挂着 flick」这一种**手势位置**，与上面「长条 long」那一格叠加
        # （`player.build_actions` 的 `end_flick` 分支）。
        # 2026-10-21 用户 m53338 要求「确保设置页不出现滚动」⇒ 从**单独一行**并进同一行：
        # 那一行值 68 逻辑（瓦片 = 标签行 + 控件行），是这一页唯一能省的整行。
        # 「它不是第五类键」这件事改由标签（「尾判滑键」而不是「flick」）、tooltip 和卡名底下
        # 那句支持文本承担 —— 版式上一行五格，控件仍然对齐在同一条竖线上。
        raw_tail = (self.state.get("defaults") or {}).get("tail_flick_lead")
        self.tail_lead_spin = num_field(
            self.tk, int(clamp_num("tail_lead", raw_tail, core.TAIL_FLICK_LEAD_DEFAULT)),
            self._save_tail_lead, suffix=" ms", decimals=0, width=None)
        self.tail_lead_spin.expand = True
        self.tail_lead_spin.tooltip = (
            "长条末尾那一记滑键的偏移（ms）。正数 = 更早，0 = 不提前。\n"
            "与上面「长条 long」叠加：那一格把整条（头 → 每个航点 → 尾部抬手）一起动，\n"
            "这一格只把尾巴上的那两段横滑往前挪，头与航点不动。出厂 10 ms。")
        tail_tile = opt_tile(self.tk, ft.Icons.SUBDIRECTORY_ARROW_RIGHT, "尾判滑键 tail",
                             self.tail_lead_spin)
        self.kind_hint = txt("", self.tk, "n", color=self.tk.text_dim, max_lines=3)
        # 卡名底下那句**支持文本**（2026-10-21 用户 m53176「种类偏移+点明」）：这张卡改的是
        # **音符种类**的提前量，与选曲页那个「分类」下拉（乐队分类筛选）毫无关系 —— 名字与面板里
        # 已有的控件撞字，就得在卡面上自己说清楚，不能靠改一次名就完事。
        # **位置按 M3 卡片解剖来**：标题 + 支持文本上下叠，所以在 `content` 的第一行，不塞标题行
        # （2026-10-21 用户 m53608 指出横在标题右边「感觉有点奇怪」—— 那确实不是规范里的版式）。
        # 代价是一档行高 + 8 间距；够不够由设置页的余量决定，`research/experiments/setnoise.py`
        # 量着（1280×800 与 1560×900 都滚不动才算过）。
        self.kind_note = txt(
            "按音符种类调提前量 —— 与选曲页那个「分类」筛选（乐队分类）无关。",
            self.tk, "n", color=self.tk.text_dim, max_lines=2)
        kind_card = card(self.tk, ft.Column([
            self.kind_note,
            opt_line(*[opt_tile(self.tk, icon, label, self.kind_spins[k])
                       for k, icon, label, _tip in KIND_TILES], tail_tile),
            self.kind_hint,
        ], spacing=T.SPACE["sm"], tight=True), title="种类偏移", icon=ft.Icons.TUNE)

        self._refresh_font_hint()
        self._refresh_res_hint()
        self.refresh_kind_hint()
        # 两张各 6 栏 ⇒ 正好铺满整行（中间只留一条 `SPACE["sm"]` 的列间距），**不再需要居中**
        # —— 从前各 7 栏、栅格换行时那两张是上下堆着的，靠 `alignment=CENTER` 让窄卡居中。
        # 窄窗叠栏时两栏都是 12/12，同样铺满。第 10 关拿开始页那张铺满内容区的栅格当尺子，
        # 量设置页两段卡的宽与中间那条留白。
        #
        # 两张卡**等高**（用户 m15291「横平竖直贴边对齐」）：两张卡的内容行数不同（面板 5 行、
        # 资源 4 行 + 一行读数），从前是自然高 ⇒ **下沿一高一低**（实拍 564 与 468 px，差 96）。
        # 等高不走 `vertical_alignment=STRETCH`（那一页外层可滚 ⇒ 主轴无界，一拉伸整页就画不出来，
        # 见 `SET_CARD_H` 那段），而是给两张卡钉同一个实测高度；叠栏时在 `_apply_window_class`
        # 里撤掉（纵向堆叠看不出一高一低，且窄窗换行后钉死会溢出）。
        self._settings_row = ft.ResponsiveRow([
            ft.Container(content=self.panel_card, col={"xs": 12, "md": 6}),
            ft.Container(content=self.res_card, col={"xs": 12, "md": 6}),
        ], spacing=T.SPACE["sm"], run_spacing=T.SPACE["sm"],
            vertical_alignment=ft.CrossAxisAlignment.START)
        # 「种类偏移」独占一行、恒 12 栏（用户 m15057）：它是四枚等宽瓦片，挤进 6/12 那一栏
        # 每个框只剩 96 逻辑宽都不到；也**不能**放进上面那个 Row —— `_apply_window_class` 会把
        # 那一行里的每一份都改成 `s_span`。
        self._kind_row = ft.ResponsiveRow([
            ft.Container(content=kind_card, col={"xs": 12}),
        ], spacing=T.SPACE["sm"], run_spacing=T.SPACE["sm"],
            vertical_alignment=ft.CrossAxisAlignment.START)
        # 行距与列距同档（`SPACE["sm"]` = 8，与上面那一行的列间距、多人页两栏的间距同一个数）：
        # 整页是一个 8 的网格，不再出现「横 8 竖 12」两种节奏（用户 m15291「横平竖直」）。
        return ft.Column([self._settings_row, self._kind_row], spacing=T.SPACE["sm"],
                         scroll=ft.ScrollMode.AUTO, expand=True,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    # ------------------------------------------------------------ 导航与尺寸

    def show_tab(self, i):
        self.tab = i
        self._sync_rail(i)
        if not self._motion():
            # 关掉「过渡动画」时直接落终态：`opacity`／`scale` 都拉回 1（前一次换页可能把它们留在
            # 半路），而且**不带渐变** —— 终态与开着时逐像素相同（`fletviewcheck` 的十面就是这么量的）。
            self._body.animate_opacity = None
            self._body.animate_scale = None
            self._body.opacity = 1.0
            self._body.scale = 1.0
            self._body.content = self.pages[i]
            self._body.update()
            return
        self._page_seq += 1                      # 连点页签：在飞的那一次两拍都作废
        self.page.run_task(self._fade_page, i, self._page_seq)

    def _sync_rail(self, i):
        """导航轨跟着页面走。

        程序化换页（点「最近演出」卡里的一行跳结算、以后加别的快捷跳转）从前只换 `self._body.content`，
        不改 `selected_index` —— 页面换了而轨道高亮还停在旧选项上，看着像点错了。
        """
        if self._rail is None:
            return
        self._rail.selected_index = i
        try:
            self._rail.update()
        except Exception:                                        # noqa: BLE001
            pass

    def _set_hint(self, text):
        """选曲卡底部那行「游戏画面」提示：有话说才占一行，没话说就**收起来**。

        从前它空着也占一行 —— 加上 `chart_info` 本来就是两行，卡片底部就多出约 40 逻辑像素
        的空白（m05745 用户点名的「底部空白」）。空串直接 `visible=False`，那一截还给列表。

        显的那一路走 `_fade_in`（`MOTION["card"]`，与三处空态同一个装置）；**藏的那一路仍然
        瞬时**（理由与 `_toggle_empty` 一样：高度得立刻还回去，淡出会露一帧「位子已经让出来、
        影子还挂着」）。只在「从藏到显」那一次排动画 —— 已经在台上时换字就当场换。
        """
        was = bool(self.ingame_hint.visible)
        self.ingame_hint.value = text
        self.ingame_hint.visible = bool(text)
        if text and not was and self._motion():
            self.page.run_task(self._fade_in, self.ingame_hint)
            return
        self._push_ctl(self.ingame_hint)

    def _push_ctl(self, *ctls):
        """把改过属性的控件推给客户端（`None` 跳过，没挂到页上就静静地不算数）。

        `Control.update()` **不是**「整页重画」：它走 `page.update(self)` →
        `session.patch_control(自己)`，只补丁被点名的那一棵子树
        （`.venv/Lib/site-packages/flet/controls/base_control.py`）。所以「值算好了、兄弟没推」
        在客户端就是**继续画旧值** —— 实测两行字都改成新值、只推其中一行，两张截图字节不同
        （`%TEMP%\bang_probe2_sib_{stale,push}.png`）。泵里只推 `log_view`，计数行与空态就得
        各自推一次，否则「显示 N / 共 M 行」和空态的样子会停在上一拍。
        """
        for ctl in ctls:
            if ctl is None:
                continue
            try:
                ctl.update()
            except Exception:                                    # noqa: BLE001
                pass

    def _toggle_empty(self, ctl, empty):
        """空态的显与藏：从藏到显时淡入（`MOTION["card"]`），藏起来直接落终态。

        藏的那一半不做动画是**故意**的：空态一出来就占位、一收就还位，跟着它一起动的是列表
        的高度，淡出会让「位置已经让出来、影子还挂着」露一帧。但**推**是两边都要的 ——
        `visible` 改了不推等于没改（见 `_push_ctl`）；显的那一路由 `_fade_in` 的全量刷新兜着，
        藏的这路从前一声不吭。
        """
        if ctl is None:
            return
        show = bool(empty)
        if bool(ctl.visible) == show:
            return                       # 状态没变：既不排动画，也不推一份没变的补丁
        ctl.visible = show
        if show and getattr(self, "_body", None) is not None:
            self.page.run_task(self._fade_in, ctl)
        else:
            self._push_ctl(ctl)

    async def _fade_in(self, ctl):
        """内容出现：从透明淡进来（`MOTION["card"]` = medium1 / emphasized_decelerate）。

        两拍的理由和 `_fade_page` 一样 —— `opacity=0` 那一帧必须先画出去，否则客户端只看见
        1 → 1，动画根本不会开始。第一拍还要**先把 `animate_opacity` 摘掉**（与 `_fade_box` 同型）：
        这些控件建的时候就挂着 `MOTION["card"]`，不摘的话「1.0 → 0」自己就是一段补间，等
        `AWAIT_FRAME`(60 ms) 抬回 1.0 时它才走到两三成 —— 于是变成「闪一下」而不是从透明淡进来
        （三处空态、封面槽与曲中提示行都是「先前不透明、藏起来又显示」的控件，会走这一支；
        第二拍再把 `MOTION["card"]` 挂回去，五个调用点都按这一档建的）。
        关掉「过渡动画」时直接落终态，一次刷新。
        """
        if ctl is None:
            return
        if not self._motion():
            ctl.opacity = 1.0
            self.page.update()
            return
        ctl.animate_opacity = None
        ctl.opacity = 0.0
        self.page.update()
        await asyncio.sleep(AWAIT_FRAME)
        ctl.animate_opacity = T.animation("card")
        ctl.opacity = 1.0
        self.page.update()

    async def _fade_reflow(self):
        """换挡（并排 ↔ 叠成一栏）时整页从半透明淡回来。

        只到 0.35 而不是 0：叠栏那一下版面本来就大改，全透明会像闪屏。落 0.35 这一拍**不带动画**
        （先把起点画出去），第二拍才挂上 `MOTION["page"]` 让 0.35 → 1 是插值的 —— 与 `_fade_page`
        同一个道理：起点必须在上一帧就画出来，否则客户端只会看见 1 → 1。`animate_opacity` 在这里
        显式重挂一遍，因为关掉过「过渡动画」时 `show_tab` 会把它摘掉。
        """
        if not self._motion():
            return
        self._body.animate_opacity = None
        self._body.opacity = 0.35
        self.page.update()
        await asyncio.sleep(AWAIT_FRAME)
        self._body.animate_opacity = T.animation("page")
        self._body.opacity = 1.0
        self.page.update()

    async def _fade_out_card(self, rc, seq):
        """「最近演出」卡整卡退场：先淡出（`MOTION["card_out"]` = 200 ms **加速**），淡完再 `visible=False`。

        退场取的是规范那一对里的加速档（emphasized accelerate = 「exit the screen」），不是进场那一档：
        「慢慢停下」是进场的样子，退场要「加速离开」（m3.material.io「Easing and duration」那张表）。
        挂 `animate_opacity` 的动作必须在落 `opacity` **之前** —— 隐式动画只认「改属性」那一下，
        控件自带的是进场档（`card`），不换档的话退场就是 decelerate。

        为什么要等：Flet 的隐式动画只管 `opacity`／`offset`／`scale` 这些**绘制**属性，布局高度的
        变化没有插值 —— 卡一 `visible=False`，运行卡那一帧就把高度吃回去。所以先让卡在台上淡掉、
        结束时再一次性收走（那一下仍是瞬跳，这是框架边界，不是取舍）。行跟着卡一起收。
        `seq` 防拖窗口的竞态：中途又要显示（`_sync_last_cards` 会把 `rc.seq` 加一）就直接
        返回，绝不把该显示的卡藏起来。关掉「过渡动画」时直接落终态。`rc` 是哪一张卡（单人 / 多人）。
        """
        card_ = rc.card
        rows = rc.rows or []
        if card_ is None or not card_.visible:
            return
        if self._motion():
            card_.animate_opacity = T.animation("card_out")
            card_.opacity = 0.0
            nudge(card_)
            await asyncio.sleep(T.motion_ms("card_out") / 1000.0)
        if seq != rc.seq:
            return                      # 期间又要显示：这一路作废（淡入由那边负责）
        for r in rows:
            r["box"].visible = False
        card_.visible = False
        card_.animate_opacity = T.animation("card")     # 进场档挂回去，下次出现才从 0 淡进来
        card_.opacity = 1.0             # 复原
        nudge(card_)

    async def _fade_out_row(self, r, seq):
        """「最近演出」卡里**一行**退场：同样是「先淡出、淡完再收」，见 `_fade_out_card`。

        卡在台上、只是行数变少（拖窗口）时走这一路；整卡退场时行不单独动。
        """
        box = r["box"]
        if not box.visible:
            r["out"] = False
            return
        if self._motion():
            box.animate_opacity = T.animation("card_out")
            box.opacity = 0.0
            nudge(box)
            await asyncio.sleep(T.motion_ms("card_out") / 1000.0)
        if seq != r.get("seq") or not box.visible:
            r["out"] = False
            return
        box.visible = False
        box.animate_opacity = T.animation("card")
        box.opacity = 1.0
        r["out"] = False
        nudge(box)

    async def _fade_page(self, i, seq):
        """换页：M3 的 **fade-through** —— 旧页先淡出，新页再淡入、同时从 `PAGE_SCALE_IN` 放大回 1。

        官方 `flutter/packages/animations` 里的 `fade_through_transition.dart`（Google 自家实现）：
        前 30% 旧页淡出（`_outCurve = Cubic(0.4,0,1,1)` = emphasized accelerate），后 70% 新页淡入
        （`_inCurve = Cubic(0,0,0.2,1)` = emphasized decelerate）并从 0.92 抬到 1.0 —— 文档原话
        「Scale is only applied to incoming elements to emphasize new content over old」。本项目按
        两拍实现：`MOTION["page_out"]`(short2=100) + `MOTION["page"]`(short4=200) = `medium2`=300，
        与从前那一档的总时长相同；换内容的那一帧正好落在 30% 上，与官方的分界重合。

        两拍之间的那一觉是必须的：Flet 把「属性变了」当补丁发给客户端，客户端在**下一帧**才画；
        把 `opacity=0`、换内容、`opacity=1` 塞进同一次刷新，客户端只看见 1 → 1，动画根本不会开始
        （`take_screenshot` 那次「改了状态但连拍五张字节相同」也是同一个道理）。缩放同理，而且更要
        小心：`scale` 必须先挂 `animate_scale=None` 落到 0.92、画出去，再挂上动画抬回 1.0 —— 否则
        客户端会把「1.0 → 0.92」当成一次缩一下，那正是 fade-through 要避免的形状。

        `seq` 防连点页签：第二拍之前又换了一次就直接返回，绝不让前一次把新页画成半透明或缩小态。
        """
        self._body.animate_opacity = T.animation("page_out")
        self._body.opacity = 0.0
        self._body.update()
        await asyncio.sleep(T.motion_ms("page_out") / 1000.0)
        if seq != self._page_seq:
            return
        self._body.content = self.pages[i]
        self._body.animate_scale = None           # 不带动画地落到起始缩放（这一帧要先画出去）
        self._body.scale = T.PAGE_SCALE_IN
        self._body.animate_opacity = T.animation("page")
        self._body.opacity = 1.0
        self._body.update()
        await asyncio.sleep(AWAIT_FRAME)
        if seq != self._page_seq:
            return
        self._body.animate_scale = T.animation("page")
        self._body.scale = 1.0
        self._body.update()

    def _on_tab(self, e):
        self.show_tab(int(e.control.selected_index))

    def _on_resize(self, e):
        self._apply_window_class(self.page.width or 0)

    def _apply_window_class(self, width):
        """窗口尺寸类只决定**分栏方向与滚不滚**；导航轨恒为「窄轨 + 图标」
        （用户 m18525 定「永远收起」，官方 token 的 `container-width` 就是 80）。

        `extended` 与 `label_type` **不能同时给**：Flutter 那边有断言
        `assert(!extended || labelType == null || labelType == none)` —— 两个都给会直接抛成
        一张红屏（第一次冒烟拍到的就是它）。

        分栏方向与**滚不滚**都在这里换挡：并排（≥ `STACK_W`）时两栏 `col={"xs":6}`、
        整块吃满一页高，两个 `expand` 各有余量可分，一页装得下所以不滚；窄过 `STACK_W`
        时两栏写成 `col={"xs":12}`，一屏必然装不下，才让整页滚。
        两个方向都写死 `col`（`xs` 断点任何宽度都命中），所以这里说并排就是并排 ——
        不再让栅格自己按某个飘来飘去的断点再判一次。
        设置页那两张 6/12 的卡**同样在这里换挡**（叠栏 ⇒ `{"xs":12}`，并排 ⇒ 基础那份
        `{"xs":12,"md":6}`）：它的基础值带 `md` 断点，而窗口下限已经越过 768（m09466 的
        800×600），不在这里改就会停在 6/12 —— 卡片缩成窄栏（第 10 关实拍抓到）。
        叠起来时那几个 `expand` 必须同时撤掉 —— 页一滚，竖方向就没有紧约束，带着
        `expand` 的孩子会直接抛成一张红屏（第二轮冒烟那张 ErrorWidget 就是这么来的）。
        """
        stacked = int(width or 0) < STACK_W
        # 只在换挡那一下动版面：每次 resize 都重写 `col`，客户端会在窗口还没落定的时候
        # 重新算一次断点，反而看走眼（实测窗口 1100 明明够两栏，却被算成一栏）。
        if getattr(self, "_stacked", None) != stacked:
            was = getattr(self, "_stacked", None)
            self._stacked = stacked
            span = {"xs": 12} if stacked else {"xs": 6}
            for cont in self._start_cols.controls:
                if cont.col != span:
                    cont.col = span
            # 设置页那两张 6/12 的卡也要跟着换挡：基础 `col={"xs":12,"md":6}` 里的 `md` 只在 768
            # 以上命中，而窗口下限已经是 **800**（m09466）—— 光靠基础值，800 那一档会停在 6/12：
            # 卡片缩成一条窄栏、两侧空出小半屏。叠栏时整份换成 `{"xs":12}`（断点回落取最近的更小
            # 档 ⇒ 任何宽度都命中），并排时还原成基础那份。
            s_span = {"xs": 12} if stacked else {"xs": 12, "md": 6}
            s_row = getattr(self, "_settings_row", None)
            for cont in (s_row.controls if s_row is not None else []):
                if cont.col != s_span:
                    cont.col = s_span
            # 那两张卡并排时等高（`SET_CARD_H`，理由见那个常量）：叠栏时把高度撤掉 —— 纵向堆叠
            # 看不出一高一低，而窄窗里文字会换行，钉死高度反而会把内容挤出卡片。
            for c in (getattr(self, "panel_card", None), getattr(self, "res_card", None)):
                if c is not None:
                    c.height = None if stacked else SET_CARD_H
            # 多人演出页那两栏同一套换挡：并排是 6/12 + 6/12（左边「最近演出」记录卡、右边运行卡，
            # 2026-10-10 用户 m13525 定两栏等宽；5/7 的历史见 `TILE_MIN_W` 那段注释），
            # 叠栏时两份都换成 `{"xs":12}`。基础值带 `md` 断点，而窗口下限 800 已经越过 768
            # ⇒ 不在这里换挡，窄窗会停在 6/12 缩成一条窄栏。
            m_cols = getattr(self, "_multi_cols", None)
            if m_cols is not None:
                m_spans = (({"xs": 12}, {"xs": 12}) if stacked
                           else ({"xs": 12, "md": 6}, {"xs": 12, "md": 6}))
                for cont, sp in zip(m_cols.controls, m_spans):
                    if cont.col != sp:
                        cont.col = sp
            for ctl in (self._start_cols, self._left_col, self._right_col, self.run_card,
                        self._run_body, m_cols, getattr(self, "_multi_left", None),
                        getattr(self, "_multi_right", None), getattr(self, "m_run_card", None),
                        getattr(self, "m_run_body", None),
                        # 多人页那张「最近演出」卡（`rc.fill`）也撑满那一栏 ⇒ 三层都要跟着换挡：
                        # 卡自己、卡里那层 Container（`card()` 的 content）、列表。叠栏时页面是
                        # 可滚的、高度不定，撑满的控件在那底下会炸 —— 所以一处都不能漏。
                        self.m_recent.card, getattr(self.m_recent.card, "content", None),
                        self.m_recent.body):
                if ctl is not None:
                    ctl.expand = not stacked
            if self.pages:
                want = ft.ScrollMode.AUTO if stacked else None
                # 多人演出页也要跟着滚/不滚（叠栏时它同样一屏装不下）。
                roll = [self.pages[0]]
                if len(self.pages) > TAB_MULTI:
                    roll.append(self.pages[TAB_MULTI])
                for pg in roll:
                    if pg.scroll != want:
                        pg.scroll = want
            # 整页淡回来（`_body` 自带 `animate_opacity`，所以是插值不是闪）：并排 ↔ 叠栏是
            # 大幅重排，给一点过渡。首次定档（`_stacked` 原本是 None）是开窗那一次，跳过。
            if was is not None and self._motion() and getattr(self, "_body", None) is not None:
                self.page.run_task(self._fade_reflow)
        # 「上一局」那张卡**每次** resize 都重判（不跟着换挡那一下走）：窗口拉高就放出来、
        # 缩回去就收起来 —— 它只改自己的 `visible`，不会反过来动窗口尺寸，没有循环。
        self._sync_last_cards()
        # 结算表的列集与列宽也跟着窗口走（用户 m12075「表单宽度应与窗口宽度保持同步」）。
        # 和上面那张卡同一条理由：每次 resize 都喊一声，但只有「这一档摆得下的列变了、或者余量
        # 变了」才真的重排（`_hist_sig` 去抖）—— 拖窗口时不会每帧重算上百行格子。
        self._sync_hist_cols(width)
        if self._rail is None:
            return
        # 导轨**永远收起**（用户 m18525）：`extended` 恒 False、标签压在图标下（label_type ALL）。
        # 官方 token 的 `container-width` 就是 80，所以 80 这一档本身完全合规范；不展开是版式取舍
        # （展开档每行只有一个小胶囊加两个字，右边近 170 逻辑全是空白，内容区还白少 176），记在
        # `m3_theme.DEVIATIONS` 最后一条，`fletpanel` 第 10 关在 1560 与 760 两个宽度下都盯着。
        self._rail.extended = False
        self._rail.label_type = ft.NavigationRailLabelType.ALL
        try:
            self.page.update()
        except Exception:                                        # noqa: BLE001
            pass

    def _on_key(self, e):
        """键盘：F5 开跑、F1 看这份清单、Ctrl+1..5 换页、Alt+1..4 选难度、Alt+↑/↓ 移动选中行、
        Alt+Enter 打开选中那局的截图、Ctrl+F 聚焦搜索、Ctrl+R 重读、Ctrl+L 清日志、Esc 清搜索词。
        清单与模块级的 `SHORTCUTS` 是同一份 —— 弹窗念的就是真在管用的那几个，不是另抄一遍。

        搜索框、Esc 与 Alt+↑/↓ **按当前页签走**：运行日志页从前没有搜索框，Ctrl+F 却只认选曲页那
        一个（在运行日志页按下去，焦点会飞到一个看不见的框上）；方向键同理 —— 开始页挪选曲列表、
        结算记录页挪表格。

        方向键给的是**修饰键 + 方向**：`_on_key` 是页面级的，搜索框有焦点时也会进来（Alt 组合
        不与打字冲突）。键名拼写见 `KEY_UP`/`KEY_DOWN`/`KEY_ENTER` 上面那段。"""
        key = (getattr(e, "key", "") or "")
        ctrl = bool(getattr(e, "ctrl", False))
        alt = bool(getattr(e, "alt", False))
        if key == "F5":
            # F5 是「开始」：在哪一页就开哪一种局 —— 多人演出页上开多人局（用户 m02832），
            # 别的页签上照旧是单人局。
            if self.tab == TAB_MULTI:
                self.start_multi_run()
            else:
                self.start_run(False)
        elif key == "F1":
            shortcuts_dialog(self.page, self.tk)
        elif alt and key in ("1", "2", "3", "4"):
            # 难度格从前只有鼠标这条路（审查报告：`ink=True` 的 Container 不是可聚焦节点，
            # Tab 走不到）。键盘这一条补在这里：Alt+1..4 选第 N 个难度，越界由 `select_diff` 挡。
            self.select_diff(int(key) - 1)
        elif alt and key in KEY_UP:
            self._step_focus(-1)
        elif alt and key in KEY_DOWN:
            self._step_focus(1)
        elif alt and key in KEY_ENTER and self.tab == TAB_HIST:
            # 与表格里的双击同一条出口（`open_shot` 读 `hist_row_tag`）；别的页签不响应，
            # 免得在开始页按下去却打开了上次选中的那一局。
            self.open_shot()
        elif ctrl and key in ("1", "2", "3", "4", "5"):
            self.show_tab(int(key) - 1)
        elif ctrl and key == "F":
            self._focus_search()
        elif ctrl and key == "R":
            self.refresh_data()
        elif ctrl and key == "L":
            self.clear_log()
        elif key in ("Escape", "Esc"):
            # Esc 清**当前页**的关键词；另一页的词别莫名其妙抹掉（两页都空就什么都不做）。
            box = self._search_box()
            if box is not None and (box.value or ""):
                if self.tab == TAB_LOG:
                    self._clear_log_search()
                else:
                    self._clear_search()

    def _search_box(self):
        """当前页签上的搜索框（运行日志页是关键词框，别处是选曲页那一个）。"""
        if self.tab == TAB_LOG:
            return getattr(self, "log_search", None)
        return getattr(self, "search", None)

    def _focus_search(self):
        box = self._search_box()
        if box is not None:
            box.focus()

    def _step_focus(self, delta):
        """Alt+↑/↓：把光标在当前页签的列表里挪一格（开始页是选曲列表，结算记录页是表格）。

        键盘这条通路与 Alt+1..4 同源（审查报告：`ink=True` 的 Container 不是可聚焦节点、
        Tab 走不到），所以「选中哪一行」仍由视图层自己的状态说了算。
        """
        if self.tab == TAB_HIST:
            self._hist_step(delta)
        elif self.tab == TAB_SOLO:
            self._song_step(delta)

    def _song_step(self, delta):
        """选曲列表挪一格。**复用 `on_song_select` 那唯一入口**：行的身份是 `ft.ListTile.data`
        （musicId），它正是按这个回查 `self.songs` 的 —— 这里只合成一个带 `control.data` 的
        事件，选中态、难度、行内字色一条都不重复（与 `reload_songs` 末尾那句是同一个写法）。
        """
        rows = list(self.song_list.controls or []) if getattr(self, "song_list", None) else []
        if not rows:
            return
        cur = next((i for i, c in enumerate(rows) if bool(getattr(c, "selected", False))), -1)
        if cur < 0:
            idx = 0 if delta > 0 else len(rows) - 1
        else:
            idx = min(max(cur + delta, 0), len(rows) - 1)
        self.on_song_select(type("E", (), {"control": rows[idx]})())

    def _hist_step(self, delta):
        """结算表挪一格。画在表上的顺序就是 `hist.shown()`（`_render_history` 用的是同一份），
        光标落在 `self.hist_row_tag` 上，挪完重画一次。
        """
        tags = list(self.hist.shown())
        if not tags:
            return
        cur = tags.index(self.hist_row_tag) if self.hist_row_tag in tags else -1
        if cur < 0:
            idx = 0 if delta > 0 else len(tags) - 1
        else:
            idx = min(max(cur + delta, 0), len(tags) - 1)
        self.hist_row_tag = tags[idx]
        self._render_history()

    async def _on_window_event(self, e):
        if e.type == ft.WindowEventType.CLOSE:
            if self.core.busy():
                ask(self.page, self.tk, "正在演奏",
                    "正在演奏，关闭窗口将结束本局。\n确定关闭？", self._close_confirmed,
                    ok_label="关闭", danger=True)
            else:
                await self._shutdown()

    def _close_confirmed(self):
        """用户在「演奏进行中」那个对话框上按了「确定」。

        `ask()` 的回调是**同步**调用的（就是按钮那一按），而 `_shutdown` 是协程 —— 把协程函数
        直接交给 `ask()`，只会造出一个**从未被 await 的协程**：窗不关、子进程也不收，正好是
        「关掉面板等于把一局留在后台继续往游戏里注触摸」那件事。所以这里 `run_task` 一下，
        与 `restart_panel` 里的 `bye` 同一招。
        """
        self.page.run_task(self._shutdown)

    async def _shutdown(self):
        if self.core.busy():
            self.core.force_kill()
        await self.page.window.destroy()

    # ------------------------------------------------------------ 谱面库

    def load_manifest(self):
        self.manifest = core.read_json(core.MANIFEST, {}) or {}
        summary = core.library_summary(self.manifest)
        if summary:
            self._lib_status = (f"谱面库 {summary['songs']}／{summary['charts']}　"
                                f"钉子 {summary['pins']}　待重学 {summary['relearn']}　"
                                f"抓取于 {summary['fetched']}")
        else:
            self._lib_status = "暂无谱面库：请先执行一次 tools/fetch_charts.py"
        self.songs = self.manifest.get("songs") or []
        self.cat_map, self.native_ids, self.band_rank = core.categories(self.manifest)
        self.ap = core.ap_ids()
        # 页脚那句谱面库概况**在这里就落到位**（审查报告 P1-③）：从前只有建页时补一次，
        # `refresh_data()`（Ctrl+R）重算完不回写，页脚会一直念旧数。建页那一次 `_footer_status`
        # 还不存在，`_set_status` 自己会跳过，随后由 `main()` 里那次补上 —— 一处写、两条路都对。
        self._set_status(self._lib_status)

    def _set_status(self, text):
        if self._footer_status is not None:
            self._footer_status.value = text

    def _fill_cats(self, keep=None):
        """分类下拉框的选项 = `core.categories()` 的 {标签: bandId}，标签即选项的 key。

        与旧版同构（那边是 `cat_box.addItems(list(cat_map))` + `cat_map.get(currentText())`）。
        选项的 key 用**标签**而不是 bandId：bandId 在本清单里是 int，而 `ft.Dropdown` 的
        `value`/`DropdownOption.key` 走的是字符串通道。

        `keep` 是「换表**之前**那个选择对应的 bandId」（`None` = 「全部」）。标签里带着每队的
        曲数，所以清单一变（新歌进来）标签就跟着变，重读之后必须按 bandId 把选中项接回来 ——
        否则挑中的是个已经不在表里的旧标签，`reload_songs` 那句 `cat_map.get()` 拿到 None，
        筛选就静默退回「全部」（用户 m28348：Mujica 筛选不起作用）。
        """
        if not hasattr(self, "cat_box"):
            return
        self.cat_box.options = [ft.DropdownOption(key=k, text=k) for k in self.cat_map]
        if keep is not None:
            label = next((k for k, v in self.cat_map.items() if v == keep), None)
            if label is not None:
                self.cat_box.value = label
                return
        if self.cat_box.value not in self.cat_map:
            self.cat_box.value = next(iter(self.cat_map), None)

    def reload_songs(self, fade=False):
        """筛选 + 排序后的曲目列表。与旧版同一条契约：光标放回原来那首，找不到选第 0 首。

        `fade=True` 只给**离散**那几路（换分类／换排序／翻方向／清空搜索／重新读取）：整列行被
        换掉、行数一变的高度跳高没有插值，靠 `_fade_box` 那一次淡出淡入盖住 —— 与结算表的
        筛选／排序／改条数同一套装置。**敲关键词那一路不许传 `fade=True`**（`_on_search`）：
        每敲一个字都闪一下就没法打字，这条与运行日志页 `_reload_log_view` 的规矩是同一条。
        """
        prev = self.selected_chart_id()
        query = (self.search.value or "") if hasattr(self, "search") else ""
        # 分类下拉框的值是**标签**，要过 `cat_map` 换成 bandId —— 与旧版逐字同一条：
        # `cat_map.get(currentText())`。「全部」在表里映射成 `None`，而 `filtered_songs`
        # 把 `cat is not None` 当成「必须等于这个 bandId」，所以直接递空串会一首都不剩
        # （bandId 是 int，`"" != 1`）—— 这条踩过，曲目列表曾经永远是空的。
        cat = self.cat_map.get(self.cat_box.value) if hasattr(self, "cat_box") else None
        mode = (self.sort_box.value or core.SORT_DEFAULT) if hasattr(self, "sort_box") else core.SORT_DEFAULT
        desc = bool(self.desc_btn.selected) if hasattr(self, "desc_btn") else False
        got = core.filtered_songs(self.manifest, query, cat, self.native_ids, self.band_rank,
                                  self.ap, mode, desc)
        self.songs = got
        if not hasattr(self, "song_list"):
            return
        if fade:
            self._song_fade()
        rows = []
        ap_songs = 0
        charts = 0
        for s in got:
            n_ap, n_all = core.song_ap(s, self.ap)
            charts += n_all
            ap_songs += 1 if core.song_all_ap(s, self.ap) else 0
            rows.append(self._song_tile(s, n_ap, n_all))
        self.song_list.controls = rows
        empty = not rows
        self._toggle_empty(self.song_empty, empty)
        self.song_list.visible = not empty
        if self.count_text is not None:
            all_songs = self.manifest.get("songs") or []
            self.count_text.value = (f"显示 {len(got)} / {len(all_songs)} 首 · {charts} 张谱"
                                     f" · 已 AP {ap_songs} 首")
            try:
                self.count_text.update()
            except Exception:                                    # noqa: BLE001
                pass
        # 光标放回原来那首
        idx = 0
        for i, s in enumerate(got):
            if prev and any(core.chart_id(d) == prev for d in (s.get("difficulties") or [])):
                idx = i
                break
        if got:
            self.on_song_select(type("E", (), {"control": rows[idx]})())
        else:
            self.sel, self.diffs, self.diff_idx = None, [], -1
            self._render_diffs(None)

    def _song_tile(self, s, n_ap, n_all):
        """列表里的一行：**原文歌名**打头，副行「罗马音 · 乐队」，尾巴是 AP 进度。

        M3 的列表项就是「主行 + 支撑行 + 尾部」，三件事各就各位；从前 AP 进度被当
        `🌟3/4 ` 前缀塞进标题、标题取的是排序字段 `song_name()`（罗马音），两条一叠就是
        「这些歌怎么全是英文名」。歌名走 `core.song_label()`，与排序/搜索口径分开。

        行高交给框架：M3 的两行列表项就是 **72**（`ListTokens.ItemTwoLineContainerHeight`），
        从前挂的 `dense=True` + 4dp 竖向内边距把它压到约 57 —— 照 m08726 去掉这两条。
        图标与文字的间距取官方 `LeadingContentEndPadding = 16`。
        """
        roma = core.song_romaji(s)
        band = str(s.get("bandZh") or s.get("band") or "")
        sub = " · ".join(x for x in (roma, band) if x)
        if core.song_all_ap(s, self.ap):
            tail = badge(self.tk, f"AP {n_ap}/{n_all}", "ap")
        else:
            tail = txt(f"{n_ap}/{n_all}", self.tk, "s", color=self.tk.text_dim)
        tail.tooltip = f"已 AP {n_ap} / {n_all} 张"
        sel = bool(self.sel and self.sel.get("musicId") == s.get("musicId"))
        # 选中行铺 `secondary_container`，主行与支撑行就都配 `on_secondary_container`
        # （M3 的配对；用户 m08235 点名）。未选中仍走 on_surface / on_surface_variant。
        ink = self.tk.on_secondary_container if sel else self.tk.text
        sub_ink = self.tk.on_secondary_container if sel else self.tk.text_dim
        return ft.ListTile(
            # M3 list 的 leading 位（40dp）：封面缩略图（没有就退回乐队标识块），
            # 列表左边因此有了一条整齐的、认得出是哪首的图形列。
            leading=song_leading(self.tk, s, self.band_rank.get(s.get("bandId"), 0)),
            title=txt(core.song_label(s), self.tk, "n", color=ink),
            subtitle=txt(sub, self.tk, "s", color=sub_ink) if sub else None,
            trailing=tail,
            horizontal_spacing=T.SPACE["lg"],
            selected=sel,
            selected_tile_color=self.tk.secondary_container,
            data=s.get("musicId"),
            on_click=self.on_song_select)

    def _on_search(self, _e=None):
        """搜索框动一下：清空按钮跟着显隐（空搜索时留着它只是噪音），再重筛一次。"""
        if self.search_clear is not None:
            self.search_clear.visible = bool(self.search.value)
            try:
                self.search_clear.update()
            except Exception:                                    # noqa: BLE001
                pass
        self.reload_songs()

    def _clear_search(self, _e=None):
        self.search.value = ""
        if self.search_clear is not None:
            self.search_clear.visible = False
        try:
            self.search.update()
        except Exception:                                        # noqa: BLE001
            pass
        self.reload_songs(fade=True)                             # 清空是离散的一下，淡

    def selected_chart_id(self):
        if self.sel and 0 <= self.diff_idx < len(self.diffs):
            return core.chart_id(self.diffs[self.diff_idx])
        return None

    def on_song_select(self, e):
        mid = getattr(e.control, "data", None)
        s = next((x for x in self.songs if str(x.get("musicId")) == str(mid)), None)
        if s is None:
            return
        self.sel = s
        self._render_diffs(s)
        for c in self.song_list.controls:
            on = str(c.data) == str(mid)
            c.selected = on
            # 行是按选中态写的字色（`_song_tile`），而这里只翻 `selected`、不重建行 ——
            # 不当场补字色，换选一行就会留下上一行的反色字。主行与副行各取各的那档。
            c_ink = self.tk.on_secondary_container if on else self.tk.text
            c_sub = self.tk.on_secondary_container if on else self.tk.text_dim
            if isinstance(getattr(c, "title", None), ft.Text):
                c.title.color = c_ink
            if isinstance(getattr(c, "subtitle", None), ft.Text):
                c.subtitle.color = c_sub
        try:
            self.song_list.update()
        except Exception:                                        # noqa: BLE001
            pass

    def _render_diffs(self, s, select_idx=None):
        self.diffs = (s.get("difficulties") or []) if s else []
        self.diff_segs = []
        if not s:
            # 占位：一段、禁用、没有选中项（`allow_empty_selection=True` 就是为这一态留的）。
            self.diff_seg.segments = [ft.Segment(
                value="", disabled=True,
                label=txt("请先选择曲目", self.tk, "s", color=self.tk.text_dim))]
            self.diff_seg.selected = []
            self.chart_info.value = "未选择曲目"
            self._rebuild_diff_hit()
            self._update_diffs()
            return
        by = (self.state.get("diff_by_song") or {}).get(str(s.get("musicId")))
        want = by or self.state.get("last_diff_dd")
        idx = select_idx
        if idx is None:
            idx = next((i for i, d in enumerate(self.diffs) if d.get("dd") == want), 0)
        for d in self.diffs:
            name = (d.get("name") or "").upper()
            # 段上写**长式**（`EXPERT Lv26`）：用户 m20246 定 —— 选中段不再画 18 dp 的对勾，
            # 段内可用宽回到 112.7 dp（实测），`EXPERT Lv26` 那 ≈90 dp 装得下。全名与等级同时
            # 留在悬停与卡底那行曲目信息里。
            self.diff_segs.append(ft.Segment(
                value=core.chart_id(d),
                label=ft.Text(f"{name or '?'} Lv{core.lv(d)}", style=T.type_style("labelLarge")),
                tooltip=f"{name or '?'} Lv{core.lv(d)}"))
        self.diff_seg.segments = self.diff_segs
        self.diff_idx = idx if self.diffs else -1
        self._paint_diffs()
        self._paint_chart_info()
        self._rebuild_diff_hit()
        self._update_diffs()

    def _rebuild_diff_hit(self):
        """把难度分段控件重新包成「可视 40、可点 48」的一列：上下各一排隐形命中带。

        每排的格数与难度数一样、格宽与段宽都用 `expand=True` 平分 ⇒ 点分段控件上方或下方那 4 个
        逻辑像素，落到的正是它**正上方 / 正下方**那一段（用户 m20246 要的 48 命中目标）。格数与
        回调都得跟着当前难度走，所以曲目/难度一变就重建一次（挂在 `self.diff_hit` 这个常驻壳里，
        只换 `content`，不动选曲卡 Column 的孩子顺序）。
        """
        n = max(len(self.diffs), 1)

        def bands():
            cells = []
            for i in range(n):
                cb = (lambda _e, k=i: self.select_diff(k)) if self.diffs else None
                cells.append(ft.Container(expand=True, height=HIT_PAD, on_click=cb))
            return ft.Row(cells, spacing=T.SPACE["none"], tight=True)

        self.diff_hit.content = ft.Column(
            [bands(), self.diff_seg, bands()], spacing=T.SPACE["none"], tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def _update_diffs(self):
        try:
            self.diff_seg.update()
            self.chart_info.update()
            self.diff_hit.update()
        except Exception:                                        # noqa: BLE001
            pass

    def _paint_diffs(self):
        """选中态唯一的入口：换难度只走这里。

        底/描边/字色不在这里画 —— 官方那套配色写在 `T.theme()` 的 `segmented_button_theme`
        里，控件自己按 `SELECTED` 状态取（`secondary_container` + `on_secondary_container`）；
        这里只把「选中哪一段」写进去。
        """
        d = self.diffs[self.diff_idx] if 0 <= self.diff_idx < len(self.diffs) else None
        self.diff_seg.selected = [core.chart_id(d)] if d is not None else []

    def _paint_chart_info(self):
        # 选曲一变，上一条「画面一致」就不成立了 —— 底部那行提示收起来（空着不占行）。
        if getattr(self, "ingame_hint", None) is not None:
            self._set_hint("")
        if not self.sel or not (0 <= self.diff_idx < len(self.diffs)):
            self.chart_info.value = "未选择曲目"
            return
        d = self.diffs[self.diff_idx]
        band = self.sel.get("bandZh") or self.sel.get("band") or "?"
        label = core.song_label(self.sel)
        roma = core.song_romaji(self.sel)
        # **一行**写全：原文歌名（罗马音不一样才附括号）· 难度 · 乐队 —— 与列表同一套语言，
        # 从前这里写 `title`、列表写 `titleRomaji`，同一首歌上下两处两个名字；而把它折成
        # 两行换来的只是卡底那截空白，横平竖直反倒没了（m05745）。
        self.chart_info.value = (
            f"{f'{label}（{roma}）' if roma else label}"
            f" · {(d.get('name') or '').upper()} Lv{core.lv(d)} · {band}")

    def select_diff(self, i):
        if not self.sel or not (0 <= i < len(self.diffs)):
            return
        self.diff_idx = i
        d = self.diffs[i]
        self.state.setdefault("diff_by_song", {})[str(self.sel.get("musicId"))] = d.get("dd")
        self.state["last_diff_dd"] = d.get("dd")
        core.save_state(self.state)
        self._paint_diffs()
        self._paint_chart_info()
        self._update_diffs()

    def _on_diff_change(self, e):
        """分段控件的回调：把选中的那一段（值 = `core.chart_id(d)`）翻成下标。

        控件开着 `allow_empty_selection`（「还没选曲目」那一态得能没有选中项），所以点已经选中
        的那一段会让它变空 —— 这里把空点当没发生、把原值写回去：M3 的单选分段控件永远有且只有
        一个选中项。
        """
        picked = list(getattr(e.control, "selected", None) or [])
        i = None
        if picked:
            i = next((k for k, d in enumerate(self.diffs)
                      if core.chart_id(d) == picked[0]), None)
        if i is None:
            self._paint_diffs()
            self._update_diffs()
            return
        self.select_diff(i)

    def _on_cat(self, _e):
        self.reload_songs(fade=True)

    def _on_sort(self, _e):
        self.state["sort_mode"] = self.sort_box.value
        core.save_state(self.state)
        self.reload_songs(fade=True)

    def _toggle_desc(self, _e):
        # 状态写在 `selected` 上（`icon` / `selected_icon` 在建立时给死）—— 从前是改 `icon` 再
        # 改 `icon_color`，控件与无障碍树都不知道这是个「开着/关着」的开关。
        desc = not bool(self.desc_btn.selected)
        self.desc_btn.selected = desc
        self.state["sort_desc"] = 1 if desc else 0
        core.save_state(self.state)
        self.reload_songs(fade=True)
        try:
            self.desc_btn.update()
        except Exception:                                        # noqa: BLE001
            pass

    def _option_widgets(self):
        """运行卡里那十件「只在一局开始时读一次」的控件：四个数框 + 六颗开关。

        忙的时候改它们**不会生效** —— `core.start()` 在开局那一刻就把这些值快照给 `_run_loop`
        （`n` / `stop_ap` / `random` / `retry_break` / `push_cap` / `retry_cap` / `push_ms` /
        `gap_min` / `fire_gate`），照旧能点只会静默地白改一把（用户 m08235 审出来的 P3）。灰掉它们，
        「现在动的这些都归下一局」就不必再用嘴说。选曲与筛选/排序不在此列：它们不影响这一局。

        用 `getattr` 兜底：这个方法可能比设置页/运行卡的构造更早被调到（首帧就调一次）。
        """
        spins = getattr(self, "policy_spins", None) or {}
        out = [getattr(self, k, None) for k in ("n_field", "follow_chk", "random_chk",
                                                "stop_ap", "push_chk", "break_chk", "fire_chk")]
        out += [spins.get(k) for k in ("push_cap_ms", "retry_cap", "gap_min")]
        # 多人演出页那五件（难度 / 轮数 / 演出间隔 / AP终止 / 随机乐曲）
        # 是同一性质：多人局开跑时也一次性快照给 `_run_loop`，忙时照旧能点只会白改一把。
        out += self._multi_widgets()
        return [c for c in out if c is not None]

    def refresh_start_state(self):
        busy = self.core.busy()
        # 单人页那四颗与多人页那三颗一起翻：`busy()` 是整台面板的（一个 worker），两页上的键
        # 落在同一个 core 上，哪一页上按都得是同一套可用性。
        pairs = ((self.btn_start, not busy), (self.btn_force, not busy),
                 (self.btn_stop, busy), (self.btn_kill, busy),
                 (getattr(self, "m_btn_start", None), not busy),
                 (getattr(self, "m_btn_stop", None), busy),
                 (getattr(self, "m_btn_kill", None), busy))
        for b, on in pairs:
            if b is not None:
                b.disabled = not on
        for c in self._option_widgets():
            c.disabled = busy
        # 更新谱面库那条链路也占着 `busy()`（同一个 worker、会重写 `research/charts/`），
        # 所以「联网更新」跟着一起禁用 —— 忙时按它只会被 core 拒掉。
        upd = getattr(self, "update_btn", None)
        if upd is not None:
            upd.disabled = busy
        for b in ([x for x, _ in pairs] + [upd] + self._option_widgets()):
            if b is None:
                continue
            try:
                b.update()
            except Exception:                                    # noqa: BLE001
                pass

    def _refresh_ap_marks(self):
        self.ap = core.ap_ids()
        self.reload_songs(fade=True)

    # ------------------------------------------------------------ 设置

    def _appearance_label(self):
        want = self.state.get("appearance")
        if want in core.APPEARANCE_KEYS and want != "auto":
            return core.APPEARANCE_CHOICES[core.APPEARANCE_KEYS.index(want)]
        return core.APPEARANCE_CHOICES[0]

    def _clamp_field(self, key, field, cast, fallback, int_only=False):
        """把框里的字面值收进 `NUM_RANGE`。**真的被夹过就把框里的字面量改回去** ——
        只收状态不管框，用户看到的数和实际等的东西就会不一致（框里 999、其实等 120）。
        读不成数字时不动框（打字打到一半是常态），只让状态走 fallback。

        `int_only`（用户 m03411「给输入框里补上单位且仅允许整数」）：运行卡上那几个数框
        只收整数 —— 打进 `10.5` 就当场回写成 `10`。单位在 `suffix` 里（` 轮` / ` ms` /
        ` 次` / ` 分`），数字部分不带小数点。"""
        raw = getattr(field, "value", None)
        v = clamp_num(key, raw, fallback)
        try:
            raw_v = float(raw)
        except (TypeError, ValueError):
            raw_v = None
        if int_only:
            v = float(int(round(v)))
        if raw_v is not None and abs(raw_v - v) > 1e-9:
            try:
                field.value = str(int(v)) if int_only else f"{v:g}"
                field.update()
            except Exception:                                    # noqa: BLE001
                pass
        return cast(v)

    def _exclusive_modes(self, keep):
        """「乐曲识别」与「随机乐曲」互斥（用户 m14282）：刚打开的那颗胜出，另一颗当场关掉。

        从前两个都开时是**静默**按「随机」跑的（`start_run` 里 `rnd` 的分支排在 `follow` 前面），
        可面板上两颗都亮着 —— 用户看到的状态与真实跑法不一致。现在同一时刻只亮一颗，两颗都关
        仍是合法的第三态（用面板列表里选中的那首）。`keep` 是刚被打开的那一颗（`"follow"` /
        `"random"`），由两个 on_change 各自进门喊一声；谁没开着就直接返回，所以可以无条件调。
        """
        follow = getattr(self, "follow_chk", None)
        rnd = getattr(self, "random_chk", None)
        if follow is None or rnd is None:
            return
        this = follow if keep == "follow" else rnd
        other = rnd if keep == "follow" else follow
        if not this.value or not other.value:
            return
        other.value = False
        try:
            other.update()
        except Exception:                                        # noqa: BLE001
            pass
        # 两个键住在两处（`follow_game` 在顶层、`random` 在 defaults 里）：被关掉的那颗得跟着
        # 落盘，否则下次开面板它又亮回来。落到盘上由调用方那一次 `core.save_state` 一起写。
        self.state["follow_game"] = 1 if follow.value else 0
        self.state.setdefault("defaults", {})["random"] = 1 if rnd.value else 0

    def _save_defaults(self, *_a):
        d = self.state.setdefault("defaults", {})

        # 六颗开关共用这个回调，「随机乐曲」那颗的 on_change 也是它 ⇒ 进门先喊一声自己这颗；
        # 「乐曲识别」若还亮着，`_exclusive_modes` 会把它关掉（互斥）。
        self._exclusive_modes("random")
        d["runs"] = self._clamp_field("runs", self.n_field, int, 1, int_only=True)
        d["stop_on_ap"] = 1 if self.stop_ap.value else 0
        d["random"] = 1 if self.random_chk.value else 0
        d["fire_gate"] = 1 if self.fire_chk.value else 0
        d["push_cap"] = 1 if self.push_chk.value else 0
        d["retry_on_break"] = 1 if self.break_chk.value else 0
        for k, sp in getattr(self, "policy_spins", {}).items():
            # 三枚数框都只收整数（m03411）：ms / 次 / 分 都是整数单位。
            d[k] = self._clamp_field(k, sp, float, d.get(k, 0), int_only=True)
        core.save_state(self.state)
        self.refresh_policy()

    def _save_follow(self, *_a):
        # 「乐曲识别」这颗的 on_change：开的时候先把「随机乐曲」关掉（互斥），再落盘。
        self._exclusive_modes("follow")
        self.state["follow_game"] = 1 if self.follow_chk.value else 0
        core.save_state(self.state)

    def _save_autoclean(self, *_a):
        self.state["auto_clean"] = 1 if getattr(self, "autoclean_chk", None) and \
            self.autoclean_chk.value else 0
        core.save_state(self.state)

    def _save_kind_lead(self, *_a):
        """设置页那四枚提前量框的 on_change：夹进 `NUM_RANGE` 后写进 `defaults["kind_lead"]`。

        与 `_save_defaults` 分开：那是运行卡那六颗开关与三枚数框的共用回调（里面还有「随机乐曲
        与乐曲识别互斥」这种只属于那边的处理），这一页的四个框跟它们不是一组。

        存的是**完整四个键**的 dict（不是只存改过的）：`core.kind_lead()` 会按 `KIND_LEAD_MS`
        补缺，两种写法等价，但四个键都写下来，状态文件读起来就是「当时那四个框里是什么」。
        """
        d = self.state.setdefault("defaults", {})
        kd = dict(d.get("kind_lead") or {})
        for k in core.KIND_LEAD_MS:
            sp = (getattr(self, "kind_spins", {}) or {}).get(k)
            if sp is None:
                continue
            kd[k] = self._clamp_field("kind_" + k, sp, float, kd.get(k, 0.0), int_only=True)
        d["kind_lead"] = kd
        core.save_state(self.state)
        self.refresh_kind_hint()

    def _save_tail_lead(self, *_a):
        """设置页那枚「尾判滑键」框的 on_change：夹进 `NUM_RANGE` 后写进 `defaults["tail_flick_lead"]`。

        与 `_save_kind_lead` 分开，虽然两个框在同一张卡里：这一格**不是第五类键**，而是「长条
        尾巴上挂着 flick」这一种手势位置（与 `long` 那一格叠加），所以既不能塞进 `kind_lead`
        那个 dict（`run.py` 的 `parse_kind_lead` 遇到不认识的名字会拒绝整局），也不能按种类
        名去写 `--kind-lead`。面板发给 `run.py` 的是另一个参数 `--tail-flick-lead`。
        """
        d = self.state.setdefault("defaults", {})
        sp = getattr(self, "tail_lead_spin", None)
        if sp is not None:
            d["tail_flick_lead"] = self._clamp_field("tail_lead", sp, float,
                                                     core.TAIL_FLICK_LEAD_DEFAULT,
                                                     int_only=True)
        core.save_state(self.state)
        self.refresh_kind_hint()

    def refresh_kind_hint(self):
        """把五个框写成人话。

        只说两件事：**改的是哪几个、往哪个方向**（正数 = 更早、负数 = 更晚 —— 这个符号方向
        靠猜猜不出来，必须写在界面上），以及「其余种类一个毫秒都不动」这个实测性质。
        「尾判滑键」只在离开出厂值时才提 —— 它默认就在做事（出厂 10 ms），每局都念一遍
        「尾判滑键 早 10 ms」会把真正的改动淹没。
        """
        spins = getattr(self, "kind_spins", None) or {}
        parts = []
        for k, _icon, label, _tip in KIND_TILES:
            sp = spins.get(k)
            if sp is None:
                continue
            v = int(clamp_num("kind_" + k, sp.value, 0.0))
            if v:
                parts.append(f"{label} {'早' if v > 0 else '晚'} {abs(v)} ms")
        sp_t = getattr(self, "tail_lead_spin", None)
        if sp_t is not None:
            tv = int(clamp_num("tail_lead", sp_t.value, core.TAIL_FLICK_LEAD_DEFAULT))
            if tv != int(core.TAIL_FLICK_LEAD_DEFAULT):
                parts.append("尾判滑键" + (f" 早 {tv} ms" if tv else "关闭"))
        self.kind_hint.value = (
            "全零为出厂值：四类共用同一时钟（正数表示更早，负数表示更晚；"
            f"尾判滑键按出厂 {core.TAIL_FLICK_LEAD_DEFAULT:g} ms）"
            if not parts else
            "仅调整以下项：" + " · ".join(parts) + "；其余不作调整")
        try:
            self.kind_hint.update()
        except Exception:                                        # noqa: BLE001
            pass

    def _spin(self, key, cast, fallback):
        f = (getattr(self, "policy_spins", {}) or {}).get(key)
        if f is None:
            return fallback
        return cast(clamp_num(key, f.value, fallback))

    def refresh_policy(self):
        """把「开关 + 数字」一起读出来写成人话。

        只看框里的数字会骗人：一次悄悄以两侧 120 ms 放开的跑法，在设置页上看起来和按框里
        数字限制的一模一样。所以开关关掉时，这句话必须自己说出来。
        """
        if not getattr(self, "policy_spins", None):
            return
        cap = bool(self.push_chk.value)
        brk = bool(self.break_chk.value)
        push = self._spin("push_cap_ms", float, core.PUSH_ON_MS) if cap else core.PUSH_OFF_MS
        retry = int(self._spin("retry_cap", float, core.RETRY_CAP)) if brk else 0
        gap = self._spin("gap_min", float, 0.0)
        self.policy_info.value = (
            f"延后最多 +{push:.0f} ms" + ("" if cap else "（「正推限制」已关闭，双向放开）")
            + f" · 中途重开最多 {retry} 次" + ("" if brk else "（「断连重试」已关闭）")
            + f" · 演出间隔 {gap:g} 分" + ("" if gap else "（已关闭）"))
        try:
            self.policy_info.update()
        except Exception:                                        # noqa: BLE001
            pass

    # ---- 多人演出页的状态与动作（用户 m02832）----------------------------------

    def _save_multi(self, *_a):
        """多人页那几件控件的 on_change：难度与「随机乐曲」存 `state["multi"]`，策略数字与单人页
        共用 `state["defaults"]`。

        为什么共用：`core.start` 是从 `defaults` 里读 `push_ms` / `gap_min` / `fire_gate` 的
        （`panel_core.py` 那几个取数函数），另存一份数字的话面板上改了也不会生效
        —— 那才是真的骗人。难度与随机乐曲不共用：单人局的难度写在 `--song` 的 `:难度` 后缀里、
        随机选曲由单人页那颗「随机乐曲」管（发 `--random`），多人局发的是 `--diff` 与
        `--multi`（再加 `--random` 就是「随机提名」），两个词面不同、语义也不同。
        `retry_on_break` / `retry_cap` 从前也在这里写，现在**只归单人页**（用户 m12749：
        房间局不能中途重开）；`fire_gate` 也**只归单人页**（2026-10-16 用户 m27959 把多人页
        那枚「LB监测」换成了「随机乐曲」）—— 多人页不再碰这两个键，单人页那边的值因此不会被
        多人页改掉。
        """
        m = self.state.setdefault("multi", {})
        m["diff"] = self.m_diff
        m["random"] = 1 if self.m_random_chk.value else 0
        d = self.state.setdefault("defaults", {})
        d["runs"] = self._clamp_field("runs", self.m_n_field, int, 1, int_only=True)
        d["stop_on_ap"] = 1 if self.m_stop_ap.value else 0
        d["gap_min"] = self._clamp_field("gap_min", self.m_gap_spin, float, 0.0,
                                         int_only=True)
        core.save_state(self.state)
        self.refresh_multi_policy()
        # 数字与开关是两份控件共用一份状态 ⇒ 单人页那行话也得跟着重算，否则它念的是旧数。
        self.refresh_policy()

    def _on_multi_diff(self, e):
        """难度分段控件的回调：与选曲卡那颗同一个坑 —— 点已选中的那一段会让它变空。"""
        picked = list(getattr(e.control, "selected", None) or [])
        if not picked or picked[0] not in MULTI_DIFFS:
            self.m_diff_seg.selected = [self.m_diff]
            try:
                self.m_diff_seg.update()
            except Exception:                                    # noqa: BLE001
                pass
            return
        self.select_multi_diff(MULTI_DIFFS.index(picked[0]))

    def select_multi_diff(self, i):
        """选中第 `i` 个难度（隐形可点带与分段控件都走这里）。"""
        if not (0 <= i < len(MULTI_DIFFS)):
            return
        self.m_diff = MULTI_DIFFS[i]
        # 选中态只写 `selected`：底/描边/字色由官方那套 `segmented_button_theme` 按
        # `SELECTED` 状态取（与 `_paint_diffs` 同一条规矩）。
        self.m_diff_seg.selected = [self.m_diff]
        try:
            self.m_diff_seg.update()
        except Exception:                                        # noqa: BLE001
            pass
        self._save_multi()

    def _multi_widgets(self):
        """多人页那几件「开局才读一次」的控件（`refresh_start_state` 忙时一起禁用）。"""
        out = [getattr(self, k, None) for k in
               ("m_diff_seg", "m_n_field", "m_gap_spin", "m_stop_ap", "m_random_chk")]
        return [c for c in out if c is not None]

    def refresh_multi_policy(self):
        """多人页那行人话：把难度与开关念一遍（与 `refresh_policy` 同一个理由 —— 只看框里的
        数字会骗人，开关关掉时这句话必须自己说出来）。"""
        if not getattr(self, "m_policy_info", None):
            return
        gap = clamp_num("gap_min", self.m_gap_spin.value, 0.0)
        n = int(clamp_num("runs", self.m_n_field.value, 1))
        # 「LB监测」在这一页没有开关（用户 m27959 换成了「随机乐曲」），但火力门对多人局照旧
        # 生效（`core.start` 从 `defaults["fire_gate"]` 读，与单人页那颗共用一份状态）——
        # 所以这句话必须念出来，否则这一页就藏着一件改不了的事。
        fire = bool(getattr(self, "fire_chk", None) and self.fire_chk.value)
        self.m_policy_info.value = (
            f"{self.m_diff.upper()} · 最多 {n} 轮"
            + f" · 演出间隔 {gap:g} 分" + ("" if gap else "（已关闭）")
            + (" · ALL PERFECT 后停" if self.m_stop_ap.value else "")
            + (" · 每轮随机提名一首" if self.m_random_chk.value else " · 提名页面上那一首")
            + " · 消耗LB 拨档跟单人页「LB监测」走" + ("（当前开）" if fire else "（当前关）")
            + " · 房间对局不支持中途重开，故没有「断连重试」")
        try:
            self.m_policy_info.update()
        except Exception:                                        # noqa: BLE001
            pass

    def start_multi_run(self):
        """多人局的开跑：确认一次，再 `core.start(..., multi=难度)`。

        谱面交给房间抽（`chart_id=None`）：`core` 那一支发的是 `--multi`（而不是谱面文件路径），
        正推上限也按 `MULTI_PUSH_CAP_MS`（0）发死 —— 这正是 mp9/mp10 两轮全 PERFECT 的配方。
        「随机乐曲」开着时多一条 `--random`：那是**提名**，面板在 楽曲選択 页随机挑一首
        （`run.py` 的 `on_select_multi` 那一支），打哪首仍由房间抽。

        `retry_break` 一律发 `False`（用户 m12749）：中途重开要「暂停 → 重试 → 确定」把同一首
        从头再打，那是单人 LIVE 的动作；房间局重开要么走不通、要么直接把这一轮作废。
        """
        if self.core.busy():
            self._busy_notice()
            return
        diff = str(self.m_diff)
        n = max(1, min(core.RUNS_MAX, int(clamp_num("runs", self.m_n_field.value, 1))))
        stop_ap = bool(self.m_stop_ap.value)
        rnd = bool(self.m_random_chk.value)
        # 火力门在多人页没有开关了（用户 m27959），但 `core.start` 仍按单人页那颗的设置发
        # `--min-fire` —— 确认框里照实说，别让人以为多人局不拨档。
        fire = bool(getattr(self, "fire_chk", None) and self.fire_chk.value)
        gap = float(clamp_num("gap_min", self.m_gap_spin.value, 0.0))
        body = ("曲目由房间抽取，面板不选曲；抽中的曲目要到 準備 页才能识别。\n"
                + ("每轮在 楽曲選択 页随机提名一首（打哪首由房间抽）\n" if rnd
                   else "提名页面上停着的那一首（面板不碰选曲页）\n")
                + f"难度 {diff.upper()}（与房间不一致时在 乐曲选择 页修改）\n"
                f"最多 {n} 轮" + (f"，演出间隔 {gap:g} 分" if gap else "") + "\n"
                + ("达成 ALL PERFECT 后停止\n" if stop_ap else "")
                + ("加成火力不足 3 点时把 消耗LB 切到 0 档、够 3 点时切到 3 档，然后开始"
                   "（跟单人页「LB监测」那颗的设置走）\n" if fire else "")
                + "每局结束后返回房间的 乐曲选择 页。")

        def go():
            self.run_start = len(self.log_store)
            self._reset_stats()          # 新一局：四格回到「—」，别让上一局的读数冒充这一局
            ok = self.core.start(None, "房间抽曲", diff, n, stop_ap, rnd, False, False,
                                 multi=diff)
            if ok:
                self.show_tab(TAB_LOG)
            else:
                toast(self.page, self.tk, "没能开始")
            self.refresh_start_state()

        ask(self.page, self.tk, "开始多人演出", body, go, ok_label="开始")

    def refresh_cfg_info(self):
        """链路标定那张卡已经删了，**但撞界这件事必须说出来**。

        三处提前量现在只有 CLI 能改，面板能做的只剩一条：`chain_cal.json` 的修正撞到边界、
        偏移不再自适应时，往运行日志页写一行错误。同一个边界只报一次（`_pinned` 去重），回到
        「未撞」时复位 —— 否则第二次同样的边界会被永久静音。
        """
        cal = core.read_json(rlog.CHAIN_CAL, {}) or {}
        pinned = cal.get("pinned")
        if pinned and pinned != self._pinned:
            # 完整那份（含「板顶住多少 ms」的括注）现在只能写进日志：面板上没有格子可悬停了。
            self._write_line(f"链路标定已达边界：{pinned} —— 偏移不再自适应", "log_err")
            self._pinned = pinned
        elif not pinned:
            # 回到「未撞」必须复位去重状态，否则下一次同样的边界会被永久静音。
            self._pinned = None
        try:
            self.page.update()
        except Exception:                                        # noqa: BLE001
            pass

    def refresh_data(self):
        # 分类下拉框的选项 key 是**带计数的标签**（"Ave Mujica（24）"），清单一变标签就跟着变：
        # 先把当前选择译回 bandId，换完表再按它选回新标签（`_fill_cats(keep=...)`）。不这么做，
        # `load_manifest()` 换掉 `cat_map` 之后下拉框里剩的是旧标签，`reload_songs` 那句
        # `cat_map.get()` 拿到 None，筛选静默退回「全部」—— 用户 m28348 报的
        # 「Mujica 筛选不起作用」就是这一路（面板活过了一次联网更新）。
        keep = self.cat_map.get(self.cat_box.value) if hasattr(self, "cat_box") else None
        self.load_manifest()
        self._fill_cats(keep=keep)
        self.reload_songs(fade=True)
        self.load_history()
        self.refresh_cfg_info()
        self._refresh_res_hint()
        self._write_line("已重新读取：谱面库与结算记录", "log_ok")
        try:
            self.page.update()
        except Exception:                                        # noqa: BLE001
            pass

    def _save_appearance(self, e):
        key = e.control.value
        self.state["appearance"] = key
        core.save_state(self.state)
        label = self._appearance_label()
        self._write_line(f"外观：{label}（重启面板后生效）", "log_dim")
        toast(self.page, self.tk, f"外观：{label}（重启面板后生效）")

    def _refresh_font_hint(self):
        if not hasattr(self, "font_hint"):
            return
        self.font_hint.value = T.font_hint(self.font_key)
        self.font_hint.tooltip = ("家族链：" + "、".join(T.FONTS[self.font_key]["chain"])
                                  + "\n安装字体后重启面板即可选用（双击 ttf 文件即可安装）")
        try:
            self.font_hint.update()
        except Exception:                                        # noqa: BLE001
            pass

    def _refresh_res_hint(self):
        """资源卡那一行读数（谱面库 / 更新于 / 重学队列）。没读到谱面库时 `library_summary`
        返回 None —— 那就不再画一堆「0 首」，直接说清去哪儿找。"""
        if not hasattr(self, "res_hint"):
            return
        s = core.library_summary(self.manifest)
        if not s:
            self.res_hint.value = "未读取到谱面库：research/charts/manifest.json 不在工作目录下"
            self.res_hint.tooltip = None
        else:
            self.res_hint.value = (f"谱面库 {s['songs']} / {s['charts']}　更新于 {s['fetched']}"
                                   f"　重学队列 {s['relearn']}")
            self.res_hint.tooltip = (f"钉子：{s['pins']}\n"
                                     "「已变」表示编译器当前所需的字节与已演奏版本不同；已演奏的几何"
                                     "不会被自动替换，新字节进入重学队列。")
        try:
            self.res_hint.update()
        except Exception:                                        # noqa: BLE001
            pass

    def start_update(self):
        """设置页「联网更新」：忙的时候只说一句，空闲就把整条链路交给 core。

        确认框**排在比对之后**（原 Tk 版 `_after_check()` 就是这个顺序）：「上游改了我们两张
        谱」是唯一能改变这个决定的事实，值得等这一秒。这里只起链路，问话在 `_after_check()`。
        """
        if self.core.busy():
            toast(self.page, self.tk, "正在忙")
            return
        self._run_update()

    def _run_update(self):
        """把「先比对、再（问过之后）下载」整条链路交给 core。

        「强制重下」与「逐张核对」都是**当场读**的（不落盘）：一次 `--force` 会把全部谱面重新
        下载并重编译，一次 `--verify` 是一张一个请求，都不该跟着面板开机生效。
        """
        verify = bool(getattr(self, "verify_chk", None) is not None and self.verify_chk.value)
        source = core.preferred_source(self.state)
        if not self.core.update_charts(force=bool(self.force_chk.value), verify=verify,
                                       source=source):
            toast(self.page, self.tk, "正在忙")
            return
        toast(self.page, self.tk, "开始更新")
        self.refresh_start_state()

    def _save_source(self, e):
        """首选目录落盘（`research/gui_state.json` 的 `preferred_source`；Tk 版就在这个键上）。

        只决定「先问哪一边的目录表」：MoeNotes 说没动就根本不碰 archive；逐张核对字节时一定
        问 archive（只有它有能编译的字节）。
        """
        self.state["preferred_source"] = core.preferred_source(
            {"preferred_source": getattr(e.control, "value", None)})
        core.save_state(self.state)
        toast(self.page, self.tk, "目录已存")

    def _save_font(self, e):
        key = e.control.value
        self.font_key = T.resolve_font(key)
        self.state["font"] = self.font_key
        core.save_state(self.state)
        fam, _fam_b, fell = T.apply_font(self.font_key)
        T.apply(self.page, self.appearance, self.font_key)
        self._refresh_font_hint()
        note = f"，未安装 {T.FONTS[self.font_key]['family']}，已回退" if fell else ""
        self._write_line(f"字体：{T.FONTS[self.font_key]['label']}（{fam}）{note}", "log_ok")
        toast(self.page, self.tk, f"字体：{T.FONTS[self.font_key]['label']}（{fam}）{note}")

    def _motion(self):
        """「过渡动画」开着没有。缺键、写坏、写 None 都当**开** （缺键、写坏、写 None 都当开）。"""
        try:
            return bool(int(self.state.get("motion", 1)))
        except (TypeError, ValueError):
            return True

    def _save_motion(self, e):
        on = bool(e.control.value)
        self.state["motion"] = int(on)
        core.save_state(self.state)
        if not on and self._flash_tag:
            self._flash_tag = None
            self._render_history()

    def _open_dir(self, *parts):
        p = os.path.join(core.ROOT, *parts)
        if os.path.isdir(p):
            try:
                os.startfile(p)                                  # noqa: S606
            except OSError as e:
                self._write_line(f"打不开目录：{e!r}", "log_err")

    def restart_panel(self):
        """关掉本窗、起一个新进程 —— 这是改完外观（以及任何代码改动）之后不回到启动器的唯一
        办法。**先起新的，等它活着再销毁旧的**：起不来时面板还在，能说一句，总比一个死掉的
        窗口加一个没人看得见的错误好（pythonw 没有控制台）。"""
        def spawn():
            exe = sys.executable
            pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(pyw):
                exe = pyw
            try:
                subprocess.Popen([exe, os.path.abspath(__file__)], cwd=core.ROOT,
                                 creationflags=core.CREATE_NO_WINDOW)
            except Exception as e:                               # noqa: BLE001
                self._write_line(f"重启失败：{e!r}", "log_err")
                ask(self.page, self.tk, "重启失败", repr(e), lambda: None, ok_label="明白")
                return

            async def bye():
                await asyncio.sleep(0.3)
                await self._shutdown()
            self.page.run_task(bye)
        self._confirm_stop_round("演奏进行中", "正在演奏，重启会先结束本局。\n确定重启？", spawn)

    # ------------------------------------------------------------ 结算记录

    def load_history(self):
        self.hist.set_records(core.read_history_records())
        self._render_history()
        self.refresh_last_run()

    def update_tally(self):
        counts = self.hist.counts()
        for key, b in self.hist_btns.items():
            label = dict(core.HIST_FILTERS)[key]
            # Chip 的文字在 `label` 上，不在 `content` 上（Flet 的 Chip 没有 content 字段）。
            # 选中态交给 `paint_chip`（`selected=` + 标签色），不再手刷 bgcolor/border_side。
            b.label.value = f"{label} {counts[key]}"
            paint_chip(self.tk, b, key == self.hist_filter)
        # 来源那两枚：标签上不带数（它们的数就是 info 行里的「筛出 N 局」），只刷选中态。
        for key, b in self.hist_src_btns.items():
            paint_chip(self.tk, b, key in self.hist.sources)
        vis, ap = self.hist.tally()
        shown = len(self.hist.shown())
        if hasattr(self, "hist_info"):
            info = (f"共 {len(self.hist.recs)} 局，筛出 {vis} 局，"
                    f"其中 AP {ap} 局；表上画 {shown} 局")
            # 「表按什么排的」常显（`_render_history` 只在排序列还在表上时画箭头）；排序键被这一档
            # 窗口挤掉时那行也没有落点，所以在后面加一句「该列未显示」。
            cols = getattr(self, "_hist_cols", None)
            info += (f"；按「{core.HIST_HEADS[self.hist.sort_col][0]}」"
                     f"{'降序' if self.hist.sort_desc else '升序'}")
            if cols is not None and self.hist.sort_col not in cols:
                info += "（该列未显示）"
            self.hist_info.value = info
        if getattr(self, "tally", None) is not None:
            self.tally.value = f"结算记录 {len(self.hist.recs)} 局／AP {counts['ap']}"
        try:
            self.page.update()
        except Exception:                                        # noqa: BLE001
            pass

    def _fade_box(self, box):
        """一整块内容要「换掉」时，先把它压到透明、下一帧再淡回来（`MOTION["page"]` = short4）。

        「先落 0、下一帧再挂动画淡回来」的两拍理由与 `_fade_page` 一样：同一帧里改完内容又淡
        回来，客户端只会看见 1 → 1，等于没动。用在两处**离散**的换内容上：结算表的筛选／排序／
        改条数（三条路径都会重建行，行数一变的高度跳高没有任何插值）、运行日志页点筛选 chip（整列
        行换掉）。**敲关键词那一路故意不淡** —— 每敲一个字都闪一下没法打字（见 `_on_log_search`）；
        点表格一行选中、双击开图、拖窗口换列集也都不走这里，那些本来就该是瞬时的。
        关掉「过渡动画」或那一块不在台上时什么都不做。传进来的必须是**不自带底色**的容器
        （`hist_box`／`log_view` 都是），否则淡到 0 会把卡片底色一起擦掉、闪一下。
        """
        if box is None or not getattr(box, "visible", False) or not self._motion():
            return
        box.animate_opacity = None
        box.opacity = 0.0
        self._push_ctl(box)
        self.page.run_task(self._fade_box_back, box)

    async def _fade_box_back(self, box):
        await asyncio.sleep(AWAIT_FRAME)
        box.animate_opacity = T.animation("page")
        box.opacity = 1.0
        self._push_ctl(box)

    def _hist_fade(self):
        """结算表整块：改筛选 / 换排序 / 改条数之前调一次（见 `_fade_box`）。"""
        self._fade_box(getattr(self, "hist_box", None))

    def _song_fade(self):
        """选曲列表整列：换分类 / 换排序 / 翻方向 / 清空搜索 / 重新读取之前调一次。

        与结算表同一套（见 `_fade_box`）；淡的是 `song_list` 本身而不是外面那层带底色的
        `Container`（`bgcolor=tk.field`）—— 淡带底色的容器会把那块底一起擦掉、闪一下。
        敲关键词那一路**不调**这里（见 `reload_songs`）。
        """
        self._fade_box(getattr(self, "song_list", None))

    def set_hist_filter(self, key):
        self._hist_fade()
        self.hist_filter = key
        self.hist.set_filter(key)
        self._render_history()

    def set_hist_source(self, key, on=None):
        """点亮／熄灭一枚来源 chip（单人 / 多人）：与判定筛选同一条路径（淡一下、重建行）。

        `on=None` 翻向（chip 点击就是这一路），给了 `True`/`False` 就直接设成那个态 ——
        探针要能显式摆态，不必靠「数一数现在亮着几枚」去凑。
        """
        self._hist_fade()
        self.hist.set_source(key, on)
        self._render_history()

    def _on_hist_limit(self, e):
        """改显示条数：写回 `gui_state.json`（缺键/写坏都退回默认），再重画表。"""
        self._hist_fade()
        n = self.hist.set_limit(e.control.value)
        self.state[core.HIST_LIMIT_KEY] = n
        core.save_state(self.state)
        self._render_history()

    def _on_hist_sort(self, col):
        self._hist_fade()
        self.hist.set_sort(col)
        self._render_history()

    def _on_hist_select(self, tag):
        """点一行 = 选中／再点同一行 = 取消选中；**同一行 500 ms（`T.DBLCLICK_S`）内点第二下** =
        打开这一局的 HUD 截图（`open_shot`）。

        Flet 的 `DataRow` 只有 `on_select_change`、没有 `on_double_tap`（`datatable.py` 里就那几个
        字段），所以双击只能自己按时间判。第二下保留选中态 —— 用户要的是「双击 = 打开」，不是
        「打开并把选中取消掉」。
        """
        now = time.monotonic()
        dbl = (tag == getattr(self, "_hist_click_tag", None)
               and now - getattr(self, "_hist_click_at", 0.0) <= T.DBLCLICK_S)
        self._hist_click_tag, self._hist_click_at = tag, now
        if dbl:
            self.hist_row_tag = tag
            self._render_history()
            self.open_shot()
            return
        self.hist_row_tag = None if tag == self.hist_row_tag else tag
        self._render_history()

    def open_shot(self):
        tag = self.hist_row_tag
        if not tag:
            ask(self.page, self.tk, "打开截图", "请先在表格中选择一局。", lambda: None,
                ok_label="明白")
            return
        cands = [os.path.join(rlog.RESULT, f"result_{tag}.png")]
        for p in cands:
            if os.path.exists(p):
                os.startfile(p)                                  # noqa: S606
                return
        try:
            names = sorted(os.listdir(rlog.FRAMES))
        except OSError:
            names = []
        for n in names:
            if n.startswith(f"hud_{tag}_") or n.startswith(f"hud_{tag}-"):
                os.startfile(os.path.join(rlog.FRAMES, n))       # noqa: S606
                return
        ask(self.page, self.tk, "打开截图", f"{tag} 未找到结算页或 HUD 截图。", lambda: None,
            ok_label="明白")

    def open_diag(self):
        """结算记录页：把选中的那一局压成一张「这一局」卡片。

        表上十三个列答的是「结果」，卡片答的是「过程」—— 时钟锁在哪儿、曲中改了几次、
        最后一次投递遥测长什么样、哪几条告警。**没有新的测量通道**：全部读那一局的
        `<tag>.out`（与 `detail.log` 的锚定那一行），解析在 `core.round_diag` 里。

        为什么放在**按钮**上而不是双击：双击已经是「打开 HUD 截图」（`_on_hist_select`），
        同一个手势挂两件事会让人不敢点。
        """
        tag = self.hist_row_tag
        if not tag:
            ask(self.page, self.tk, "这一局", "请先在表格中选择一局。", lambda: None,
                ok_label="明白")
            return
        hist = getattr(self, "hist", None)
        rec = (hist.recs.get(tag) if hist is not None else None) or None
        diag = core.round_diag(tag, rec)
        if not diag.get("ok"):
            ask(self.page, self.tk, "这一局", f"{tag}：{diag.get('why') or '读不到'}",
                lambda: None, ok_label="明白")
            return
        body = "\n".join(f"{k}：{v}" for k, v in diag["rows"])
        ask(self.page, self.tk, f"这一局 · {tag}", body, lambda: None, ok_label="关闭")

    def export_history(self):
        rows = [self.hist.recs[t] for t in self.hist.tags]
        if not rows:
            ask(self.page, self.tk, "导出 CSV", "当前筛选没有可导出的行。", lambda: None,
                ok_label="明白")
            return
        path = os.path.join(core.ROOT, "research", "results_export.csv")
        cols = ["tag", "ts", "song", "diff"] + list(core.NUM_COL.values())
        try:
            with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(cols)
                for r in rows:
                    w.writerow([r.get(c, "") for c in cols])
        except OSError as e:
            toast(self.page, self.tk, "导出失败：%r" % (e,), kind="err")
            return
        rel = os.path.relpath(path, core.ROOT)
        self._write_line(f"已导出 {len(rows)} 行 -> {rel}", "log_ok")
        # 用户在结算页上按的，结果就说在结算页上 —— 运行日志页这时候看不见。
        toast(self.page, self.tk, f"已导出 {len(rows)} 行 -> {rel}")

    # ------------------------------------------------------------ 运行日志

    def _log_pass(self, i, kind, text=""):
        """这一行进不进视图：关键词（大小写不敏感的子串）+ 页签（全部 / 只看错误 / 本轮）。

        关键词连时间戳一起搜 —— `10:14` 这样的前缀因此能直接定位到某一段。行号 `i` 是**存储**
        里的下标，「本轮」按它比（不是按行上盖的 tag，见 `run_start`）。
        """
        if self.log_query and self.log_query.lower() not in text.lower():
            return False
        if self.log_filter == "err":
            return kind == "log_err"
        if self.log_filter == "run":
            return i >= self.run_start
        return True

    def _log_line(self, text, kind):
        """一行日志：整行带（可选）+ 固定宽的时间戳栏 + 会自己折行的正文栏。

        三样都有出处，别再退回「一段 `ft.Text` 挂两段 span」：

        * **整行带**。从前底色铺在 `ft.Text` 自己那个盒子上，只有文字那么宽（实测 41 %），看着
          像「选中了这段字」。`ListView` 的孩子拿到的是松约束（`expand=True` 在它上面无效：实测
          那一行仍是 x349..968、619 px），所以这里靠 `ft.Container` 包一个 `ft.Row` —— `Row` 的
          `mainAxisSize` 默认就是 max，宽度因此铺满整行。
        * **时间戳是独立一栏**（`T.LOG_TS_W` = 68dp：8 位等宽数字墨迹 57.6 + 尾随空格 7.2）。
          从前两段是同一个 `ft.Text` 的 span，折行会回卷到行首、骑在时间戳底下；分栏之后续行有
          悬挂缩进。`ts` 取前 9 个字符（含那个空格），与 `msg` 拼起来仍等于原文。
        * **整行一个选区**。两段 `ft.Text` 各自 `selectable=True` 会各开一个选区、拖选被截断，
          改用 `ft.SelectionArea` 包住整行 —— 复制出来还是完整一行。
        """
        has_ts = bool(core.LOG_TS.match(text))
        ts, rest = text[:9], text[9:]
        color = getattr(self.tk, LOG_KIND.get(kind, "text"))
        # 等宽家族显式给（日志列要对齐，故意不跟着设置页换字体走）；颜色走参数 —— 从前是拿
        # `T.TYPES["bodySmall"][0]` 自己拼 TextStyle，把行高、字距、字重三样全丢了。
        gut = ft.Text(ts if has_ts else "", width=T.LOG_TS_W, no_wrap=True,
                      style=T.type_style("bodySmall", T.FONT_MONO, color=self.tk.zero_dim))
        msg = ft.Text(rest if has_ts else text, expand=True, no_wrap=False,
                      style=T.type_style("bodySmall", T.FONT_MONO, color=color))
        row = ft.SelectionArea(content=ft.Row([gut, msg], spacing=T.SPACE["xs"],
                                              vertical_alignment=ft.CrossAxisAlignment.CENTER))
        band = None
        if kind == "log_err":
            # 严重度不能只靠颜色。红绿型色觉障碍下 `danger` 与 `ok` 这两档的**亮度**几乎一样
            # （最容易混的一对），只换字色是分不出来的；铺一层底是面积线索，「有没有底色」
            # 在灰度上也成立。透明度取 `STATE_OPACITY["disabled_container"]`，不写字面量。
            band = self.tk.state(self.tk.danger, "disabled_container")
        # **只有错误行铺底**。分段行（`log_hdr`，「面板已启动」「第 N 轮」「随机选曲：」）曾经也
        # 铺一格 `tk.field`（官方 filled card 的容器色），看着像「这行被选中了」——用户 m11974
        # 原话「蓝字 Log 那行会带灰色背景」。分段已经由 `accent` 字色 + 冒号承担，不再加底；
        # 层次靠表面分层与字色，不靠给每类行刷一块背景。
        # 没有底色的行也走同一个 `ft.Container`：行高、左右两端、可选中的范围三样都得一样，
        # 否则有带子的行与普通行之间行距会跳。带子铺到控制台面板两端（面板自己留上下内边距），
        # 所以这里左右不缩进 —— 正文因此仍与工具行那排 chip 的左边缘对齐。
        return ft.Container(content=row, bgcolor=band)

    def _write_line(self, text, kind="log"):
        i = len(self.log_store)
        self.log_store.append((kind, text))
        if len(self.log_store) > core.LOG_KEEP:
            drop = len(self.log_store) - core.LOG_KEEP
            del self.log_store[:drop]
            # 「本轮」筛选是按行号比的：从头上丢几行，起点就得跟着退几行，否则下一轮日志
            # 一多，上一轮的尾巴就会被算进「本轮」。
            self.run_start = max(0, self.run_start - drop)
            i -= drop
        if not self._log_pass(i, kind, text):
            self._refresh_log_info()
            return
        self.log_view.controls.append(self._log_line(text, kind))
        if len(self.log_view.controls) > core.LOG_WINDOW:
            del self.log_view.controls[:len(self.log_view.controls) - core.LOG_WINDOW]
        self._refresh_log_info()

    def _reload_log_view(self):
        """按「当前关键词 + 当前页签」把视图整个重画（改关键词、换页签都走这里）。"""
        rows = [(i, k, t) for i, (k, t) in enumerate(self.log_store)
                if self._log_pass(i, k, t)]
        self.log_view.controls = [self._log_line(t, k)
                                  for _i, k, t in rows[-core.LOG_WINDOW:]]
        self._refresh_log_info()
        self._push_ctl(self.log_view)

    def _on_log_scroll(self, e):
        """用户自己滚了：把「自动滚动」开关掰到跟真实钉住状态一致。

        框架那半边本来就是智能的（`ScrollableControl.auto_scroll` 的 docstring：用户往上滚时
        钉住自动暂停、滚回底部自动恢复），但开关停在「开」上就是在说谎 —— 它显示的是「我允许
        钉住」，用户读到的是「我正在跟着走」。滚到底留 4 px 余量：`pixels` 与
        `max_scroll_extent` 都是浮点，取整差一点会让开关贴着底闪。框架自己的自动钉住不发事件，
        所以这里不会跟它打架；**我们自己发的**两处（`_pin_back` 的复位、`_log_to_top` 的回顶）
        走 `_log_pin` 闸门 —— 事件照记位置，只是不掰开关。

        **这里只掰开关，一个字节都不写 `auto_scroll`**（用户 m27254：从底部上滑解除自动滚动，
        整屏照样被拉回顶部）。翻它换掉的是客户端的**元素树形状** ⇒ 子树重建、位置丢掉 ⇒ 跳顶；
        而这一侧的暂停/恢复本来就不用我们做 —— Flet 1.0.3 的 `ScrollableControl.auto_scroll`
        docstring 写着「Pinning is suspended while the user has scrolled away from the end, and
        resumes once they scroll back」。开关只负责把这件事说出来。

        **而且只在用户要跟的时候说**：`auto_scroll` 还是 True 时「不在底部」= 框架把钉住暂停了，
        开关该说「没在跟」；用户自己关掉过（`auto_scroll` 已经是 False）那就是他的设置，开关一个
        字节都不许动 —— 不然滚回底部时会把它悄悄掰回来。
        """
        ctl = getattr(self, "log_autoscroll", None)
        if ctl is None:
            return
        pixels = float(getattr(e, "pixels", 0) or 0)
        extent = float(getattr(e, "max_scroll_extent", 0) or 0)
        # 位置账：开关翻面时要用它把视图接回原处（用户 m10610）。**记在闸门之前** —— 复位自己
        # 发出的那一串事件也必须入账，否则下一次翻面会拿着旧位置去复位。
        self._log_pixels = pixels
        if self._log_pin:
            # 这一拍是 `_pin_back` 在复位，不是用户在滚：只记位置，不许掰开关。
            return
        at_bottom = pixels >= extent - 4
        if self.log_view.auto_scroll and bool(ctl.value) != at_bottom:
            ctl.value = at_bottom
            self._push_ctl(ctl)

    async def _log_to_top(self, _e=None):
        """回顶：把控制台拉回第一行（工具栏那颗图标按钮，用户 m10610）。

        `offset=0` 是绝对位置；`duration=0` 要的是瞬时（框架默认有 1 s 补间，回顶不该慢悠悠）。
        位置账当场记 0：已经在顶上时这次调用一个事件都不会发，不记的话下一次翻开关会拿着旧位置
        把用户拽回底下。开关那边**故意不动** —— 它反映的是真实钉住态，而 `scroll_to` 自己发出的
        事件会走 `_on_log_scroll`（未立闸门）把「离开底部」这件事如实报给开关。
        """
        self._log_pixels = 0.0
        try:
            await self.log_view.scroll_to(offset=0, duration=0)
        except Exception as ex:                                  # noqa: BLE001
            self._write_line(f"日志回顶失败：{ex!r}", "log_err")

    def _on_log_search(self, _e=None):
        """关键词动一下：清空按钮跟着显隐，再按新词重筛（口径与选曲页搜索一致）。

        **敲字这一路不淡**（`set_log_filter` 那条 chip 路径才淡）：每敲一个字都把整列行淡出
        再淡入，一是看着像闪屏、二是把输入反馈推到 300 ms 之后，打字就没法打了。
        """
        self.log_query = (self.log_search.value or "").strip()
        if self.log_search_clear is not None:
            self.log_search_clear.visible = bool(self.log_search.value)
            self._push_ctl(self.log_search_clear)
        self._reload_log_view()

    def _clear_log_search(self, _e=None):
        self.log_search.value = ""
        self.log_query = ""
        if self.log_search_clear is not None:
            self.log_search_clear.visible = False
        self._push_ctl(self.log_search, self.log_search_clear)
        self._reload_log_view()

    def _refresh_log_info(self):
        n = len(self.log_view.controls)
        self.log_info.value = f"显示 {n} / 共 {len(self.log_store)} 行"
        if getattr(self, "log_empty", None) is not None:
            # 一行都没有的时候给一张空态，而不是一整页空白 —— 但**两种空不一样**：库里真没行
            # ⇒「没有日志」；库里 412 行、只是被页签或关键词筛没了 ⇒「没有匹配」。
            self.log_view.visible = n > 0
            no_match = n == 0 and bool(self.log_store)
            self._toggle_empty(self.log_empty, n == 0 and not no_match)
            self._toggle_empty(getattr(self, "log_none", None), no_match)
        # 计数行不是 `log_view` 的子控件，泵推不到它 —— 自己推，否则那句「显示 N / 共 M 行」
        # 会一直停在上一拍的数（见 `_push_ctl`）。
        self._push_ctl(self.log_info)

    def set_log_filter(self, key):
        self._fade_box(getattr(self, "log_view", None))   # 整列行换掉：淡出淡入盖住跳变
        self.log_filter = key
        for k, b in self.log_btns.items():
            paint_chip(self.tk, b, k == key)
        # 选中视觉长在几枚 chip 自己身上，而 `_reload_log_view` 只推 `log_view`、`_refresh_log_info`
        # 只推计数行 ⇒ 不推 chip 的话，**行换了、选中态还停在旧的那一枚**（用户报的就是这个：
        # 「点了的确会切换但选中效果不变」）。逐枚 `Control.update()` 只补丁自己那棵子树，
        # 别用 `page.update()` 把整页刷回来（那跟「算好的东西自己推」是相反的口径）。
        self._push_ctl(*self.log_btns.values())
        self._reload_log_view()

    def clear_log(self):
        n = len(self.log_store)
        self.log_store = []
        self.log_view.controls = []
        self.run_start = 0
        self._refresh_log_info()
        self._push_ctl(self.log_view)
        # 「按下去必须当场说话」：清空是破坏性的（内存里那份没了、导出也救不回来），一声不吭
        # 等于按了没反应。句子写全（2/4 字只管标签，提示语照旧写完整句）。
        try:
            toast(self.page, self.tk, f"已清空 {n} 行日志" if n else "日志当前为空")
        except Exception:                                        # noqa: BLE001
            pass

    # ------------------------------------------------------------ 运行

    def _set_phase(self, text):
        self.phase = text
        # 整屏只有这一行说「现在在干什么」，颜色必须能分开（AGENTS.md：运行状态要一眼可辨）：
        # 全 AP 绿、真出事红、待命/收尾/轮间长等灰、即将开打用 warn、其余进行态（演奏中/重试）
        # 用 accent。从前「等待下一轮 …」与「倒计时 …」都掉进最后的 else，和演奏中同色。
        # 「连续两次」那半句是冗余的（panel_core 推的是「连续两次失败，已停止」，本来就含「失败」）。
        color = self.tk.accent
        if text.startswith("ALL"):
            color = self.tk.ok
        elif "失败" in text or "错误" in text or "异常" in text:
            color = self.tk.danger
        elif text.startswith(("空闲", "已停止", "更新", "等待")):
            color = self.tk.text_dim
        elif text.startswith("倒计时"):
            color = self.tk.warn
        # **文字立刻到位**，淡入只负责让它看得见 —— 旧版就是先 `setText` 再 `fade_in`。
        # 把换字押在淡出的第二拍上曾经让状态行永远停在上一句：泵每几十毫秒推一次进度，
        # 比那一拍还快的更新会把每一次淡入在 `await` 里作废掉（`fletfly.py` 第 4 关抓到的
        # 就是它 —— 整局只采到过「空闲」）。文字真的变了才淡，否则每 30 ms 重启一次动画，
        # 行会一直停在半透明（旧版注释里同一个坑）。
        fade = self._motion() and text != self._footer_phase.value
        self._phase_seq += 1                       # 无论走哪条路，在飞的那一次都作废
        if not fade:
            self._footer_phase.opacity = 1.0       # 被作废的那次不会自己还原不透明度
        self._snap_phase(text, color)
        if fade:
            self.page.run_task(self._fade_phase, self._phase_seq)

    async def _fade_phase(self, seq):
        """状态行变了要看得见：新字**瞬时**压到透明，下一帧挂上 `MOTION["phase"]` 淡回来。

        文字在 `_set_phase` 里已经落到新值了（那边为什么不能把换字押到第二拍，见 `_set_phase`
        的注释），所以这一拍只负责让它**看得见** —— 与 `_fade_box` 同一个两拍：先把
        `animate_opacity` 摘掉、把不透明度**不带动画**地按到 0（起点必须在这一帧就画出去），
        下一帧再挂上 `T.animation("phase")`（short3 / standard_decelerate = 150 ms）淡回 1。

        从前这里是「挂着动画压到 0、等 `AWAIT_FRAME`（60 ms）就抬回 1」：补间刚走到四成就被
        反向，实际只是一次 60 ms 的凹陷 —— `phase` 这档令牌等于没用上，而终态一样，`fletfly.py`
        那一类只看终态/只读文字的探针看不出区别（`fletpanel.py` 第 1 关现在按两拍采样）。
        关掉动画时这一路根本不排（见 `_set_phase`）。
        """
        ph = self._footer_phase
        ph.animate_opacity = None
        ph.opacity = 0.0
        ph.update()
        await asyncio.sleep(AWAIT_FRAME)
        if seq != self._phase_seq:
            return
        ph.animate_opacity = T.animation("phase")
        ph.opacity = 1.0
        ph.update()

    def _snap_phase(self, text, color):
        self._footer_phase.value = text
        self._footer_phase.style.color = color
        self._footer_dot.bgcolor = color          # 状态灯与那句话同色
        # 窗口标题跟着状态走：任务栏与 Alt-Tab 里也能看出在不在跑。只在真的变了的时候推一次
        # （`page.title` 是页面属性，改它要整页推一次补丁，不能每句话都推）。
        want = f"{APP_NAME} · {text}" if self.core.busy() else APP_TITLE
        if self.page.title != want:
            self.page.title = want
            try:
                self.page.update()
            except Exception:                                    # noqa: BLE001
                pass
        try:
            self._footer_phase.update()
            self._footer_dot.update()
        except Exception:                                        # noqa: BLE001
            pass

    def _set_progress(self, value):
        target = max(0.0, min(1.0, float(value)))
        cur = self._pct
        # 先作废在飞的那条补间，再决定「补间还是直接落」：收尾那一跳（1.0 → 0.0）走的是直接落
        # 这条路，原先它不碰 `_progress_seq`，于是还在跑的那条向上补间会按自己的 seq 一路走到
        # 终点、把刚落下的 0 再抬回 1.0 —— 读数停在 1.0 就是这么来的（`fletfly.py` 抓到的）。
        self._progress_seq += 1
        if (not self._motion() or target <= cur
                or target - cur < T.MOTION_MIN_PROGRESS):
            self._snap_progress(target)
            return
        self.page.run_task(self._tween_progress, self._progress_seq, cur, target)

    async def _tween_progress(self, seq, cur, target):
        """进度：向上跳变插一段补间，**向下直接落**（收尾那一跳回 0 不该慢慢缩）。

        规范的曲线在客户端，这里是在 Python 里一格一格推的，所以缓动自己按 `EASE_OUT_CUBIC`
        的形状算：`1-(1-t)^3`。步长 16 ms（一帧），总时长取 `MOTION["progress"]` 那一档。
        """
        steps = max(1, int(T.motion_ms("progress") / 16))
        for k in range(1, steps + 1):
            await asyncio.sleep(16 / 1000.0)
            if seq != self._progress_seq:
                return
            t = k / steps
            self._snap_progress(cur + (target - cur) * (1 - (1 - t) ** 3))
        self._snap_progress(target)

    def _snap_progress(self, value):
        self._pct = max(0.0, min(1.0, float(value)))
        self._footer_progress.value = self._pct
        self._footer_pct.value = f"{int(round(self._pct * 100)):3d}%"
        try:
            self._footer_progress.update()
            self._footer_pct.update()
        except Exception:                                        # noqa: BLE001
            pass

    # ------------------------------------------------------------ 本局读数带

    def _build_stats(self):
        """「本局」读数带：四格数字（动作 / 修正 / 迟到 / 剩余），由 `player.play` 的机器行喂。

        两张运行卡各建一份，每份的四个 `ft.Text` 记在 `self.stat_bands` 里，`_set_stats` 一次更新
        全部 —— 同一时刻只有一页看得见，而「正在跑的这一局」与它是哪一页开的无关，两份写同一批
        数最省事。**不放进页脚**：页脚是**全局**的（哪一页都在，说的是「面板在干什么」），这四个
        数是「这一局跑得怎么样」，属于运行卡 —— 与开始/停止同处一块，改主意时眼睛不用跨屏。

        四个数原本都有，只是散在日志流里那句「演奏 1200/3157 @曲内 34.2s … 修正 -45 ms」上；
        界面不该去正则化一句中文，所以 `rlog.Log.status` 多了一条机器通道（`#STATUS#`），
        `player.play` 每 400 个动作发一次。
        """
        cells = {}
        items = []
        for key, label, tip in STAT_METRICS:
            val = txt("—", self.tk, "n", color=self.tk.text_dim)
            cells[key] = val
            items.append(ft.Row([txt(label, self.tk, "s", color=self.tk.text_dim), val],
                                spacing=T.SPACE["xs"], tight=True,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                tooltip=tip))
        self.stat_bands.append(cells)
        return ft.Row(items, spacing=T.SPACE["md"], tight=True,
                      vertical_alignment=ft.CrossAxisAlignment.CENTER)

    @staticmethod
    def _stat_text(key, raw):
        """机器行里的原值是**已经格式化好的短串**（`-45`、`+0.0`、`1200/3157`、`42`），
        这里只补单位、把秒换成 m:ss —— 值本身不重算，界面与日志因此不会各说一套。"""
        if key == "left":
            try:
                sec = max(0.0, float(raw))
            except (TypeError, ValueError):
                return str(raw)
            return f"{int(sec) // 60}:{int(sec) % 60:02d}"
        if key in ("corr", "late"):
            return f"{raw} ms"
        return str(raw)

    def _set_stats(self, payload):
        """`#STATUS#` 上除 `phase`/`progress` 之外的那些键，落到四个格子上。

        迟到过了 `STATS_LATE_WARN` 就换成告警色：队列没排完时后面每个音都会晚，这是**在判定
        变坏之前**唯一看得见的信号。其余格子一律正文色 —— 一格里同时有颜色和数字，读数会先被
        颜色抢走注意力。
        """
        self.run_stats.update(payload)
        for cells in self.stat_bands:
            for key, raw in payload.items():
                cell = cells.get(key)
                if cell is None:
                    continue
                cell.value = self._stat_text(key, raw)
                bad = False
                if key == "late":
                    try:
                        bad = float(raw) > STATS_LATE_WARN
                    except (TypeError, ValueError):
                        bad = False
                cell.style.color = self.tk.error if bad else self.tk.text
                try:
                    cell.update()
                except Exception:                                # noqa: BLE001
                    pass                  # 还没挂到页上：值已设好，首帧画得出来

    def _reset_stats(self):
        """开新一局前把四格清回「—」。**一局打完不清** —— 停在原地的那组数就是这一局的读数。"""
        self.run_stats = {}
        for cells in self.stat_bands:
            for cell in cells.values():
                cell.value = "—"
                cell.style.color = self.tk.text_dim
                try:
                    cell.update()
                except Exception:                                # noqa: BLE001
                    pass

    def _notify_result(self, rec):
        song = rec.get("song", "?")
        npf = core.hist_num(rec, "non_perfect")
        if rec.get("rc"):
            self._write_line(f"演奏中断：{song} 未完成", "log_err")
        elif npf == 0:
            self._write_line(f"ALL PERFECT：{song} {rec.get('tag','')}", "log_ok")
        else:
            self._write_line(f"失去 AP：{song} 漏键 {npf}", "log_err")

    def auto_clean(self):
        """每轮结束后的自动清理：垃圾照删、取证桶按保留集压、顺带把重复文件换成硬链接。

        2026-10-19（用户「优化磁盘空间管理」）起，这一趟不再自己写一份删除循环 —— 直接交给
        `retention.auto()`：同一套判据、同一张预算表、同样的三道保险（被跟踪的 / 受保护的 /
        十分钟内新写的），而且**超上限时它真的动手**（从前只报一句「超了，去跑 retention.py」，
        于是 `research/frames` 就那样顶在 150 MB 上面没人动）。**录像与归档仍然不在自动范围
        内** —— 删老录像是判断，留给人按（`cleanup_junk` 会列出来让人自己决定）。
        """
        if self.core.busy():
            return
        try:
            res = retention.auto()
        except Exception as e:                                   # noqa: BLE001
            self._write_line(f"自动清理失败：{e!r}", "log_err")
            return
        ded = res.get("dedupe") or {}
        if res.get("deleted") or ded.get("linked"):
            bits = []
            if res.get("deleted"):
                bits.append(f"删 {res['deleted']} 项 {core.fmt_size(res['freed'])}")
            if ded.get("linked"):
                bits.append(f"去重 {ded['linked']} 个链接 {core.fmt_size(ded['freed'])}")
            self._write_line("自动清理：" + "、".join(bits)
                             + f"；research/ 现 {retention.fmt(res.get('total') or 0)}", "log_dim")
        # 自动清理之后仍然超上限的桶：都是 report / media 那一档（谱面库、录像、归档），
        # 工具不自己动 —— 说清楚哪一桶、用什么开关，别让人再猜。
        for r in res.get("over") or []:
            if r["rule"] == "report":
                self._write_line(
                    f"落盘预算：{r['label']} {retention.fmt(r['size'])} 超过上限 "
                    f"{retention.fmt(r['cap'])} —— 这一桶只量不删，得人来看", "log_err")
            else:
                self._write_line(
                    f"落盘预算：{r['label']} {retention.fmt(r['size'])} 超过上限 "
                    f"{retention.fmt(r['cap'])} —— 删老录像是判断，"
                    f"自己跑 tools/retention.py --go --media", "log_err")

    async def pump_loop(self):
        """core.q 的消费端。逐条对应 —— 这里少一条，界面就会卡在某个中间态。"""
        while True:
            while True:
                try:
                    kind, payload = self.core.q.get_nowait()
                except queue.Empty:
                    break
                except Exception as e:                           # noqa: BLE001
                    self._write_line(f"面板内部错误：{e!r}", "log_err")
                    break
                try:
                    self._on_message(kind, payload)
                except Exception as e:                           # noqa: BLE001
                    tb = traceback.extract_tb(sys.exc_info()[2])
                    where = f" @ {os.path.basename(tb[-1].filename)}:{tb[-1].lineno}" if tb else ""
                    self._write_line(f"面板内部错误：{e!r}{where}", "log_err")
            try:
                self.log_view.update()
            except Exception:                                    # noqa: BLE001
                pass
            await asyncio.sleep(PUMP_MS / 1000.0)

    def _on_message(self, kind, payload):
        if kind in LOG_KIND:
            self._write_line(payload, kind)
        elif kind == "phase":
            self._set_phase(payload)
        elif kind == "progress":
            self._set_progress(payload)
        elif kind == "status":
            # 「本局」读数带（`player.play` 每 400 个动作发的一批数字）。它不写日志 —— 同一条
            # 信息在日志里另有一句话，两处都写会变成两种说法。
            self._set_stats(payload)
        elif kind == "result":
            rec = payload["record"]
            self._hist_upsert(rec)
            self.update_tally()
            self.refresh_cfg_info()
            self._notify_result(rec)
            self._refresh_ap_marks()
        elif kind == "upstream":
            self._after_check(payload)
        elif kind == "charts_done":
            self.refresh_data()
            self.refresh_start_state()
            # 用户 m07179 那一轮补：这里是更新链路的终点，收尾必须把起点那四个按钮刷回「空闲」
            # 那一版。更新占着 `busy()`，`refresh_start_state()` 在期间把 开始/强制开始/联网更新
            # 按灰、停止/强制终止 点亮；不收尾的话更新结束后「开始演奏」一直是灰的，用户得先去
            # 按「强制终止」才恢复（原 Tk 版在 `charts_done` 里显式 `state="normal"` 恢复按钮）。
            ok_done = payload == 0
            self._set_phase("更新完成" if ok_done else "更新有失败")
            toast(self.page, self.tk, "更新完成" if ok_done else "更新失败",
                  kind="info" if ok_done else "danger")
        elif kind == "update_abort":
            # 比对完在确认框上按了「取消」：这一次更新到此为止，面板回到空闲（原 Tk 版在这里
            # 把「联网更新」按钮恢复成 `state="normal"` 并把阶段写回「空闲」）。
            self._set_progress(0.0)
            self.refresh_start_state()
            self._set_phase("空闲")
        elif kind == "done":
            self._set_progress(0.0)
            self.refresh_cfg_info()
            self.refresh_start_state()
            self._set_phase("已停止" if getattr(self.core, "stop_flag", None) is not None
                            and self.core.stop_flag.is_set() else "空闲")
            if int(self.state.get("auto_clean", 1)):
                self.auto_clean()

    def _hist_upsert(self, rec):
        self.hist.upsert(rec)
        tag = rec.get("tag")
        if tag and self._motion():
            self._flash_seq += 1
            self._flash_tag = tag
            self.page.run_task(self._flash_tick, self._flash_seq)
        self._render_history()
        self.refresh_last_run()      # 摘要卡与结算表读同一个模型，新落一局两边一起变

    async def _flash_tick(self, seq):
        """新落一局那一行的强调：亮一会儿之后自己退回去。

        带序号是为了「两次结算挨得近」时不被前一次的收尾提前擦掉（旧面板用动画对象做同一件
        事）。关掉过渡动画时根本不排这一拍。

        **这一处与旧版不完全同义**：旧版把那一行的一段色带淡出来（700 ms 的动画），Flet 这边
        是「整块高亮按 `MOTION["flash"]`（extended1 = 700 ms）按住再退回」—— 因为
        `_render_history` 每次都重建整张表的行对象，没有能跨帧存在的控件可以挂动画，
        而背景色又不是 `animate_*` 支持的那些属性。时长这一半是对的，形状那一半是静止的。
        """
        await asyncio.sleep(T.motion_ms("flash") / 1000.0)
        if seq != self._flash_seq:
            return
        self._flash_tag = None
        self._render_history()

    def _after_check(self, payload):
        """上游比对的答案：**先说话，再问，最后才让 core 下载**（原 Tk 版 `_after_check()` 的
        顺序，用户 m07356 那一轮点名要搬回来）。

        「上游改了我们两张谱」是唯一能改变「强制重下」这个决定的事实，所以它进确认框的正文
        —— 从前是先弹一个泛泛的警告，等用户点了「重下」才去比对，那个框问的是空气。
        报告不是这一趟写成的（`fresh=False`）就一个字都不当证据用。
        """
        rc = payload.get("rc")
        rep = payload.get("report") or {}
        fresh = bool(payload.get("fresh"))
        force = bool(payload.get("force"))
        # `rc == 0` 且报告是这一趟写的，才算「手里有证据」。
        weighed = fresh and rc == 0 and bool(rep)
        if force:
            ask_body = ["忽略本地已有文件，全部重新下载并重编译（含已飞过的谱面）。"]
            if not weighed:
                ask_body.append("上游检查未完成（可能无法联网），以下判断不包含新证据。")
            else:
                moved = sorted(set(rep.get("fields_changed") or {})
                               & (payload.get("validated") or set()))
                ask_body.append(
                    f"上游目录现状：新增 {len(rep.get('new') or [])} 张，"
                    f"下架 {len(rep.get('gone') or [])} 张，"
                    f"字段变动 {len(rep.get('fields_changed') or {})} 张。")
                if moved:
                    ask_body.append(
                        f"其中 {len(moved)} 张已演奏过，线上版本与本地存盘不一致："
                        f"{' '.join(moved[:6])}" + (" 等" if len(moved) > 6 else "") + "。\n"
                        "重新编译后已演奏的字节会原样放回，新的一份进入重学队列；"
                        "建议先挑一张做一次有界测试，再用 --pin 由成绩决定是否替换。")
            ask_body.append(
                "这一步可回滚：已飞过的谱面即使被重编，盘上原来那份会原样放回，编译器新写的"
                "那份进重学队列等一次有界测试；--pin 还会把飞过的字节压缩存进 evidence/pins"
                "（已提交）。确实要让某一张现在就换，请单独执行 --recompile <谱面号>，"
                "配一次有界测试后重新 --pin。")
            ask(self.page, self.tk, "强制重下", "\n\n".join(ask_body),
                lambda: self.core.answer_update(True, force=True),
                ok_label="重下", danger=True, scrollable=True,
                on_cancel=lambda: self.core.answer_update(False))
            return
        # 普通更新不弹框：只在有话说的时候说一句（版本一致时不要每天弹一次）。
        if rc != 0:
            self._write_line(f"上游检查退出码 {rc}", "log_dim")
            return
        if not fresh:
            self._write_line("上游检查报告未更新，本次判断不包含新证据", "log_dim")
            return
        new = rep.get("new") or []
        moved = rep.get("fields_changed") or {}
        if new or moved:
            self._write_line(f"上游有 {len(new)} 张新谱、{len(moved)} 张改动，接着补下载", "log_ok")
        else:
            self._write_line("上游检查：本地谱面库已是最新", "log_dim")
        # 下架：本地那几张不会替用户删（是他唯一的一份），但要让他知道线上没有了。
        gone = rep.get("gone") or []
        if gone:
            self._write_line(f"上游下架 {len(gone)} 张（本地保留、不删）：{' '.join(gone[:6])}"
                             + (" 等" if len(gone) > 6 else ""), "log_dim")

    def _verify_target(self, s, d):
        """乐曲识别关闭时：面板是真理，画面只被核对。返回确认框里那行字；任何失败都返回 None
        —— 于是不放行（**没有覆盖开关**：打错谱就是一整首 MISS）。"""
        try:
            res = read_game_screen()
        except Exception as e:                                   # noqa: BLE001
            res = {"ok": False, "why": f"读画面失败：{e!r}"}
        if not res.get("ok"):
            ask(self.page, self.tk, "没有画面",
                f"未开始演奏。\n面板选择 {s.get('title','?')} {(d.get('name') or '').upper()} "
                f"Lv{core.lv(d)}\n原因：{res.get('why','?')}", lambda: None, ok_label="明白")
            return None
        if (str(res.get("musicId")) == str(s.get("musicId"))
                and res.get("diff") == d.get("name")):
            self._set_hint(f"画面一致 {s.get('title','?')} {(d.get('name') or '').upper()}")
            return (f"画面核对：与游戏画面一致，相似度 {res.get('score', 0):.2f}，"
                    f"领先 {res.get('gap', 0):.2f}")
        got = None
        for song in self.manifest.get("songs", []):
            if str(song.get("musicId")) == str(res.get("musicId")):
                got = song
                break
        got_name = got.get("title", "?") if got else f"musicId={res.get('musicId')}"
        self._set_hint("画面与选择不一致，已暂停")
        ask(self.page, self.tk, "画面不符",
            f"未开始演奏。\n游戏画面 {got_name} {(res.get('diff') or '?').upper()}\n"
            f"面板选择 {s.get('title','?')} {(d.get('name') or '').upper()} Lv{core.lv(d)}",
            lambda: None, ok_label="明白")
        return None

    def _follow_target(self, res):
        mid = str(res.get("musicId"))
        for s in self.manifest.get("songs", []):
            if str(s.get("musicId")) == mid:
                dd = res.get("diff")
                d = next((x for x in (s.get("difficulties") or [])
                          if x.get("dd") == dd or (x.get("name") or "").upper() == str(dd).upper()), None)
                if d is None:
                    return None, None, ""
                self.sel = s
                self._render_diffs(s, select_idx=(s.get("difficulties") or []).index(d))
                return s, d, f"乐曲识别：{s.get('title','')} {d.get('name','').upper()}"
        self._set_hint("曲目未收录，已暂停")
        return None, None, ""

    def _busy_notice(self):
        """忙的时候按开跑键：一句 snackbar 说清为什么不动。

        审查报告 A7：这一刻按钮是 disabled 的，可键盘（F5）照样触发，按下去像面板死了。
        M3 给的是 snackbar —— 一句反色面上的话。单人页与多人页共用这一句（用户 m02832 的多人页
        也是同一个忙法），所以只有这一处写文案。
        """
        toast(self.page, self.tk, "已在演奏")

    def start_run(self, force=False):
        if self.core.busy():
            self._busy_notice()
            return
        rnd = bool(self.random_chk.value)
        follow = bool(self.follow_chk.value)
        cid, s, d, line = None, None, None, ""
        if force and not rnd:
            if not self.selected_chart_id():
                ask(self.page, self.tk, "未选择曲目", "请先在左侧选择曲目与难度。", lambda: None,
                    ok_label="明白")
                return
            cid, s, d = self.selected_chart_id(), self.sel, self.diffs[self.diff_idx]
            self._set_hint("强制开始：未核对游戏画面")
            self._write_line("强制开始：跳过画面核对，按面板所选谱面直接演奏", "log_err")
            line = "强制开始：未核对游戏画面，游戏内实际曲目或难度不一致时整轮会全部 MISS"
        elif rnd:
            line = "每轮由游戏随机选曲"
        elif follow:
            res = read_game_screen()
            if not res.get("ok"):
                self._set_hint("未读取到游戏画面，已暂停")
                ask(self.page, self.tk, "没有画面",
                    f"未读取到游戏画面，未开始演奏。\n原因：{res.get('why','?')}", lambda: None,
                    ok_label="明白")
                return
            s, d, line = self._follow_target(res)
            if s is None:
                return
            cid = core.chart_id(d)
        else:
            if not self.selected_chart_id():
                ask(self.page, self.tk, "未选择曲目", "请先在左侧选择曲目与难度。", lambda: None,
                    ok_label="明白")
                return
            cid, s, d = self.selected_chart_id(), self.sel, self.diffs[self.diff_idx]
            line = self._verify_target(s, d)
            if line is None:
                return

        n = max(1, min(core.RUNS_MAX, int(self.n_field.value or 1)))
        retry_cap = int((self.state.get("defaults") or {}).get("retry_cap", core.RETRY_CAP))
        cap = bool(self.push_chk.value)
        cap_ms = float((self.state.get("defaults") or {}).get("push_cap_ms", core.PUSH_ON_MS))
        gap_min = float((self.state.get("defaults") or {}).get("gap_min", 0.0))
        brk = bool(self.break_chk.value)
        stop_ap = bool(self.stop_ap.value)
        fire = bool(self.fire_chk.value)

        if rnd:
            head = (f"随机乐曲，连续 {n} 次\n"
                    f"每轮由游戏「随机选曲」抽一首，难度取游戏当前难度")
        else:
            head = (f"{s.get('title','?')} {(d.get('name') or '').upper()} Lv{core.lv(d)}\n"
                    f"连续 {n} 次\n{line}")
        body = "\n".join([
            head,
            (f"断连重试：开，HUD 检测到断点后中途重开本局，每轮上限 {retry_cap} 次" if brk
             else "断连重试：关，本局出现漏键也演奏到底，等待下一轮"),
            (f"实时修正正推：限 +{cap_ms:.0f} ms" if cap
             else f"实时修正正推：两侧 {core.PUSH_OFF_MS:.0f} ms"),
            (f"演出间隔：回到选曲页后 {gap_min:g} 分钟" if gap_min
             else "演出间隔：关，返回选曲页后立即开始下一局"),
            ("ALL PERFECT 后停止：开，任一轮零 GREAT／GOOD／BAD／MISS 就不再开始下一轮" if stop_ap
             else "ALL PERFECT 后停止：关，按设定轮数跑满"),
            (f"LB监测：开，开始前按右上角加成火力拨 消耗LB —— ≥{core.FIRE_MIN} 点拨 3 档、"
             "不足就拨 0 档，然后照常开始（不再等待；读数失败时不动 消耗LB）" if fire
             else "LB监测：关，不动 消耗LB，火力不足时也正常开始"),
        ])

        def go():
            self.run_start = len(self.log_store)
            self._reset_stats()          # 新一局：四格回到「—」，别让上一局的读数冒充这一局
            ok = self.core.start(cid, (s or {}).get("title", "?"), (d or {}).get("name", ""),
                                 n, stop_ap, rnd, brk, cap)
            if not ok:
                ask(self.page, self.tk, "已在演奏", "已有一条演奏进程在运行。", lambda: None,
                    ok_label="明白")
            self.refresh_start_state()

        if force:
            go()
        else:
            ask(self.page, self.tk, "开始演奏", body, go, ok_label="开始")

    def stop_run(self):
        """「本轮停止」：请求本局收尾（`stop_graceful` 是**协作式**的，本局会打到该停的地方）。

        审查报告 A2：从前这一按只往运行日志页写一行灰字，页脚还停在「演奏中」，看着像没按到。
        这里当场把状态行与状态灯推到「正在停止」，再给一条 snackbar —— 收尾完成的正式状态由泵
        随后推上来，会自然盖掉这一句。
        """
        if not self.core.busy():
            return
        self.core.stop_graceful()
        self._set_phase("正在停止")
        toast(self.page, self.tk, "正在停止")

    def force_kill(self):
        """「强制终止」：杀掉正在跑的 run.py。

        审查报告 A1：确认之后**什么都不说** —— `force_kill` 只往日志写一行灰字（还要切到运行日志页
        才看得见），页脚、状态灯、四个按钮一律不动，按下去像没生效。这里在确认回调里当场把状态行
        推到「正在终止」、给一条 snackbar，并把四个按钮的启用态立刻刷一遍。
        """

        def go():
            self.core.force_kill()
            self._set_phase("正在终止")
            toast(self.page, self.tk, "正在终止")
            self.refresh_start_state()

        ask(self.page, self.tk, "强制终止",
            "立即终止正在运行的 run.py？\n游戏内本局将判定失败，下一轮会重新进入 LIVE。",
            go, ok_label="终止", danger=True)

    def _confirm_stop_round(self, title, body, on_ok):
        if not self.core.busy():
            on_ok()
            return

        def go():
            self.core.force_kill()
            on_ok()
        ask(self.page, self.tk, title, body, go, ok_label="确定", danger=True)

    def cleanup_junk(self):
        """手动清理：把每一类「几项、约多大」先摆出来，再让人按。

        与自动清理的分工：自动只碰固定的三类；手动**列出**录像媒体（但不删）—— 删老录像是
        判断，留给人按。文字日志处处豁免。
        """
        if self.core.busy():
            ask(self.page, self.tk, "正在演奏", "演奏进行中，结束当前轮后再清理。",
                lambda: None, ok_label="明白")
            return
        cats = core.collect_junk()
        n_all = sum(len(c["files"]) for c in cats)
        if n_all == 0:
            ask(self.page, self.tk, "清理垃圾", "没有可清理的文件。", lambda: None,
                ok_label="明白")
            return
        total = sum(c["size"] for c in cats)

        def go():
            n, freed = 0, 0
            for c in cats:
                if c["key"] == "media":
                    continue                                 # 删老录像是判断，留给人按
                for p in c["files"]:
                    sz = core.path_size(p)
                    try:
                        if os.path.isdir(p):
                            import shutil
                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            os.remove(p)
                    except OSError:
                        continue
                    n += 1
                    freed += sz
            self._write_line(f"清理垃圾：删除 {n} 项，释放 {core.fmt_size(freed)}", "log_dim")
            toast(self.page, self.tk, f"清理完成：删除 {n} 项，释放 {core.fmt_size(freed)}")
        ask(self.page, self.tk, "清理垃圾",
            f"共 {n_all} 项，约 {core.fmt_size(total)}\n"
            + "\n".join(f"· {c['label']}：{len(c['files'])} 项 约 {core.fmt_size(c['size'])}"
                        for c in cats)
            + "\n\n录像媒体与文字日志不在默认清理范围内。", go, ok_label="清理",
            danger=True)


def tk_dim(tk):
    return tk.text_dim


# ---------------------------------------------------------------- 入口

def main(page: ft.Page):
    page.enable_screenshots = True
    # 窗口的开局尺寸与下限都取自规范（`m3_theme.WINDOW_DEFAULT` / `WINDOW_MIN`），
    # 不写第二份。此前只有冒烟工具设过尺寸，真入口一个都没设 —— 面板实际开在 Flet 的
    # 默认窗口上，`WINDOW_MIN` 也就从来没生效过（窗口能缩进 compact 档把版式挤坏）。
    page.window.width, page.window.height = T.WINDOW_DEFAULT
    page.window.min_width, page.window.min_height = T.WINDOW_MIN
    panel = Panel(page)
    page.add(panel.build())
    page.update()
    panel._write_line("面板已启动（Flet / Material 3）", "log_hdr")
    page.run_task(panel.pump_loop)


def run():
    ft.run(main, view=ft.AppView.FLET_APP)


if __name__ == "__main__":
    run()
