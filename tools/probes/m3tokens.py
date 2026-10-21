"""探针：M3 口径 vs 官方导出 —— 「我们动的这一处，就是规范的这一档」（离线）。

这份表不是审美决定。判据分两类：

  **A. 重算**（`tools/gen_m3_tokens.py` 的同一套逻辑）—— 46 个颜色角色 + 6 组扩展色，用 Google 的
  参考实现 `material_color_utilities` 重算一遍，与 `tools/m3_tokens.json` 逐格比对。手改过表、
  换过 seed/variant、或升级了参考实现导致色值漂移，都会在这里红。

  **B. 冻结**（2026-10-05 用 `tools/webfetch.py` 实抓的官方导出）—— 字阶、形状、高程、状态层、
  动效时长与缓动、以及真正用到的组件几何（列表行高、封面图、按钮高…）逐格比。官方值连同出处
  冻在下面，探针**不联网**：这份表就是「规范当时说的是什么」，改它必须是一次显式改动。

为什么值得单独一个探针：`tools/m3_theme.py` 顶栏记了「`tools/probes/m3tokens.py` 拿参考实现重算
比对」这句承诺，而这个文件从前不存在 —— 也就是说偏离与否只能靠读注释。这里把它变成会红的判据。

官方源（都可用本机 python 直读，见 `tools/webfetch.py`）：

  颜色 / 字阶 / 形状 / 高程 / 动效 / 组件级 token:
    https://cdn.jsdelivr.net/gh/material-components/material-web@main/tokens/versions/v0_192/
    （文件头写着 `Design system display name: Google Material 3`；versioned 文件名**带前导下划线**，
      不带下划线是 404 —— 非 versioned 那层是 MWC 的适配层，会自己加 token、还会改 token 名，
      **按依据顺序不算依据**，别去引它。完整清单见 `docs/m3_sources.md`。）
  androidx Compose Material3 的经典档令牌源码（`StateTokens.kt`、`SwitchTokens.kt` 等在这里；
  只取与上面那份 `v0_192` 导出相符的档位，别的一律不采）:
    https://raw.githubusercontent.com/androidx/androidx/androidx-main/compose/material3/
    material3/src/commonMain/kotlin/androidx/compose/material3/tokens/
    （jsdelivr 对 `.kt` 返回 octet-stream，`web_fetch` 会拒收，要用本机 python 取。）

**它不联网、不起窗口、不写任何东西。** 判定：任一 PART FAIL → 退出码 1。
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import flet as ft                                  # noqa: E402  只为量「哪些 API 真的不存在」
import material_color_utilities as mcu             # noqa: E402  参考实现（0.2.6，故意留在 venv）
import gen_m3_tokens as GEN                        # noqa: E402  颜色表的出处 = 同一套逻辑
import m3_theme as T                               # noqa: E402  视图层唯一出处
import flet_gui as G                               # noqa: E402  面板常量（行高、封面图、按钮高）
import panel_core as core                          # noqa: E402  结算表的列清单（列宽换算要跟它比）
import gen_m3_sources as GS                        # noqa: E402  依据登记表的唯一清单（第 10 关 ㉑㉒）

FAILS: list[str] = []
COUNTS: dict[str, int] = {}


def check(part, label, cond, extra=""):
    COUNTS[part] = COUNTS.get(part, 0) + 1
    print(f"  {'ok  ' if cond else 'FAIL'} {part} {label}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(f"{part} {label}")
    return cond


# ---------------------------------------------------------------------------
# 官方值（冻在这里；出处见顶部）
# ---------------------------------------------------------------------------
SRC_WEB = "material-web@main/tokens/versions/v0_192/"
SRC_AND = "androidx-main compose/material3/.../tokens/"

# 字阶：官方文件里是 rem（1rem = 16px），这里存**原文**，换算在 _px() 里做。
OFFICIAL_TYPES = {
    "displayLarge": ("3.5625rem", "4rem", "-0.015625rem", "regular"),
    "displayMedium": ("2.8125rem", "3.25rem", "0rem", "regular"),
    "displaySmall": ("2.25rem", "2.75rem", "0rem", "regular"),
    "headlineLarge": ("2rem", "2.5rem", "0rem", "regular"),
    "headlineMedium": ("1.75rem", "2.25rem", "0rem", "regular"),
    "headlineSmall": ("1.5rem", "2rem", "0rem", "regular"),
    "titleLarge": ("1.375rem", "1.75rem", "0rem", "regular"),
    "titleMedium": ("1rem", "1.5rem", "0.009375rem", "medium"),
    "titleSmall": ("0.875rem", "1.25rem", "0.00625rem", "medium"),
    "bodyLarge": ("1rem", "1.5rem", "0.03125rem", "regular"),
    "bodyMedium": ("0.875rem", "1.25rem", "0.015625rem", "regular"),
    "bodySmall": ("0.75rem", "1rem", "0.025rem", "regular"),
    "labelLarge": ("0.875rem", "1.25rem", "0.00625rem", "medium"),
    "labelMedium": ("0.75rem", "1rem", "0.03125rem", "medium"),
    "labelSmall": ("0.6875rem", "1rem", "0.03125rem", "medium"),
}
WEIGHT_OF = {"regular": 400, "medium": 500}
# 同一批字阶，Google 自家另一份导出（androidx TypeScaleTokens.kt）只有这三处 tracking 不同。
# 本地跟的是 Web 那份（= 经典 M3 手册那套），所以这三处**必须**与 Web 一致、与 androidx 不同。
OFFICIAL_TYPE_DIVERGENCE = {"displayLarge": -0.2, "bodyMedium": 0.2, "titleMedium": 0.2}

# 形状 / 高程：本地键名与官方一一对应（官方 `corner-full` 是 9999px，本地 999，单独一条）。
OFFICIAL_SHAPE = {"none": 0.0, "extraSmall": 4.0, "small": 8.0, "medium": 12.0,
                  "large": 16.0, "extraLarge": 28.0}
OFFICIAL_SHAPE_FULL = 9999.0
OFFICIAL_ELEVATION = {"level0": 0.0, "level1": 1.0, "level2": 3.0,
                      "level3": 6.0, "level4": 8.0, "level5": 12.0}
# 状态层：前四条出自 1 级 `_md-sys-state.scss` 的 `hover/focus/pressed/dragged-state-layer-opacity`；
# 后两条出自 1 级的两条 opacity token。**3a 的 androidx `StateTokens.kt` 写 focus/pressed 各 0.1 ——
# 不采**（与 1 级不符；用户 m19222 定：按依据顺序跟 1 级）。
OFFICIAL_STATE = {"hover": 0.08, "focus": 0.12, "pressed": 0.12, "dragged": 0.16}
OFFICIAL_STATE_EXTRA = {"disabled": (0.38, "switch disabled-unselected-handle-opacity"),
                        "disabled_container": (0.12, "switch disabled-track-opacity")}

# 动效时长：16 档。本地 `extended1-4` 对应的官方令牌名是 `extra-long1-4`（另一处命名分歧）。
OFFICIAL_DURATION = {
    "short1": 50, "short2": 100, "short3": 150, "short4": 200,
    "medium1": 250, "medium2": 300, "medium3": 350, "medium4": 400,
    "long1": 450, "long2": 500, "long3": 550, "long4": 600,
    "extended1": 700, "extended2": 800, "extended3": 900, "extended4": 1000,
}
OFFICIAL_DURATION_NAME = {"extended1": "extra-long1", "extended2": "extra-long2",
                          "extended3": "extra-long3", "extended4": "extra-long4"}
# 缓动：官方这一版共 **10** 条 cubic-bezier；本地取非 legacy 的 7 条（Flet 只暴露命名曲线）。
OFFICIAL_EASING = {
    "emphasized": ("emphasized", (0.2, 0.0, 0.0, 1.0)),
    "emphasized_accelerate": ("emphasized-accelerate", (0.3, 0.0, 0.8, 0.15)),
    "emphasized_decelerate": ("emphasized-decelerate", (0.05, 0.7, 0.1, 1.0)),
    "standard": ("standard", (0.2, 0.0, 0.0, 1.0)),
    "standard_accelerate": ("standard-accelerate", (0.3, 0.0, 1.0, 1.0)),
    "standard_decelerate": ("standard-decelerate", (0.0, 0.0, 0.0, 1.0)),
    "linear": ("linear", (0.0, 0.0, 1.0, 1.0)),
}
OFFICIAL_EASING_LEGACY = {"legacy": (0.4, 0.0, 0.2, 1.0),
                          "legacy-accelerate": (0.4, 0.0, 1.0, 1.0),
                          "legacy-decelerate": (0.0, 0.0, 0.2, 1.0)}

# 组件几何：官方 token -> 面板真正用的常量。左边是官方值，右边是「谁在用它」。
# **只收 `versions/v0_192/` 那一层**（依据顺序见 `AGENTS.md`，完整清单见 `docs/m3_sources.md`）。
OFFICIAL_LIST = {                                   # versions/v0_192/_md-comp-list.scss
    "one-line": 56.0, "two-line": 72.0, "three-line": 88.0,
    "leading-space": 16.0, "trailing-space": 16.0,
    "divider-leading-space": 16.0, "divider-trailing-space": 16.0,
    "leading-icon-size": 24.0, "leading-avatar-size": 40.0, "leading-image": 56.0,
}
OFFICIAL_SWITCH = {                                 # versions/v0_192/_md-comp-switch.scss
    "track-width": 52.0, "track-height": 32.0, "track-outline-width": 2.0,
    "state-layer-size": 40.0, "unselected-handle": 16.0, "selected-handle": 24.0,
    "pressed-handle": 28.0, "with-icon-handle": 24.0,
    "disabled-track-opacity": 0.12, "disabled-unselected-handle-opacity": 0.38,
}
# **不是官方值**：1 级（`versions/v0_192/`）没定义，只在 MWC 适配层（非 versioned）里出现过，
# 按依据顺序算「本项目决定」。面板站得住（12 落在 4dp 栅格上、48 是触摸面下限），
# 但注释与文案里不许再写「官方 list / switch 要求」。
PROJECT_DECIDED = {"list-item-vertical-space": 12.0, "switch-touch-target": 48.0}
OFFICIAL_FILLED_BUTTON = {"container-height": 40.0}   # _md-comp-filled-button.scss
# 分段控件：**1 级没有这一份**（`_md-comp-segmented-button.scss` 与 `-outlined.scss` 两份都 404，
# 同一前缀下别的那 20 份都取得到）⇒ 按依据顺序算 **3a**，出处 androidx
# `tokens/OutlinedSegmentedButtonTokens.kt`（文件头 `// VERSION: v0_162`）。
OFFICIAL_SEGMENT = {                                  # androidx OutlinedSegmentedButtonTokens.kt
    "container-height": 40.0, "icon-size": 18.0, "outline-width": 1.0,
}
OFFICIAL_TEXT_FIELD = {                               # androidx OutlinedTextFieldTokens.kt
    "container-height": 56.0, "leading-icon-size": 24.0, "trailing-icon-size": 24.0,
    "outline-width": 1.0, "focus-outline-width": 2.0,
}
# 卡片（m3.material.io/components/cards/specs 的规格表原文，tavily 抓回来的）：圆角 12、
# **左右内边距 16**、**卡与卡之间 ≤8**。本地从前是内边距 12 + 栅格间距 12，再叠 Card 自带的
# 4+4 内边距 ⇒ 实测卡间距 20。
OFFICIAL_CARD = {"padding": 16.0, "gap": 8.0}
# 对话框（material-web `_md-comp-dialog.scss`）：标题 headline-small(24)、supporting text
# body-medium(14)、动作是文字按钮（`action-label-text-color = primary`、`action-label-text-font
# = label-large`）。面板 2026-10-06 从 titleMedium(16)/bodySmall(12) + filled 动作改回这一档。
OFFICIAL_DIALOG = {"title-font": "headlineSmall", "title-size": 24.0,
                   "supporting-font": "bodyMedium", "supporting-size": 14.0,
                   "action-label-text-color": "primary"}
# Chip（androidx `AssistChipTokens.kt` / `FilterChipTokens.kt`：容器高 32、图标 18；
# `Chip.kt` 的 `ContentPadding = 8.dp`、`HorizontalSpacing = 8.dp`）。
OFFICIAL_CHIP = {"container-height": 32.0, "icon-size": 18.0, "content-padding": 8.0}
# 数据表（material-web `tokens/versions/v0_192/_md-comp-data-table.scss`）：表头 56 / 行 52、
# 表头字 `header-headline = title-small`、格字 `row-item-label-text = body-medium`。
# 行与行之间那条线是 `row-item-outline-color = outline-variant` / `row-item-outline-width = 1px`，
# 整表外框是 `outline-color = outline-variant` / `outline-width = 1px`。m12075 那轮照抄的就是这几条；
# 表头底色 `header-container-color = surface` 与悬停态层那两条 token 是 m12800 补抄的；
# 选中行色 `row-item-selected-container-color = surface_container_highest` 是 2026-10-06 按用户
# m16213 的答复补抄的（此前本面板拿 `secondary_container` 顶，那条偏离已从 `DEVIATIONS` 撤掉）。
OFFICIAL_DATA_TABLE = {
    "header-container-height": 56.0, "row-item-container-height": 52.0,
    "header-headline": "titleSmall", "row-item-label-text": "bodyMedium",
    "row-item-outline-width": 1.0, "row-item-outline-color": "outline_variant",
    "outline-width": 1.0, "outline-color": "outline_variant",
    "header-container-color": "surface",
    "row-item-selected-container-color": "surface_container_highest",
    # 悬停态层：`row-item-hover-state-layer-color = on-surface`、`-opacity = 0.08`（表头那两条
    # 同理）。M3 的数据表只有 hover 这一档状态层，没有 focus/pressed 的 token —— 所以视图层
    # 只声明 HOVERED 与 DEFAULT 两格，不做别的状态。
    "row-item-hover-state-layer-color": "on_surface",
    "row-item-hover-state-layer-opacity": 0.08,
}
# 进度条：`ProgressIndicatorTokens.kt`(v0_4_0) 只给角色，几何在 `LinearProgressIndicatorTokens.kt`
# (v0_7_0) —— 活动段与停止点 = Primary、**轨道 = SecondaryContainer**（`TrackColor`），三者形状
# 都是 CornerFull；Height / TrackThickness / StopSize / TrackActiveSpace 四条全是 4.0dp。
OFFICIAL_PROGRESS = {
    "height": 4.0, "track-thickness": 4.0, "stop-size": 4.0, "track-active-space": 4.0,
    "active-role": "primary", "track-role": "secondary_container", "stop-role": "primary",
}
# 桌面密度档：`T.theme()` 里写的是 **`ft.VisualDensity.STANDARD`**。Flutter 按
# `baseSizeAdjustment = density × 4dp` 收控件，standard = (0,0) ⇒ 不动；COMPACT (-2,-2) 会让
# 每个容器的基准高各减 8dp（按钮 40→32、输入框 56→48）。那是 M2 时代的桌面偏好，规范里的
# 40 / 56 都是标准档的数 —— m08726 按官方改回标准档，所以这里减 0。**别**再调回 COMPACT。
DENSITY_ADJUST = 0.0
# 实测（2026-10-05 二轮，标准密度档）：设置页 / 开始页 1180×780 深色，DPR 1.4814，
# page.width 1165.33；进度条与输入框描边另用 480×380 裸窗（DPR 1.5：字段声明 140 → 210 px、
# 进度条 180 → 270 px，三处互证）。量法是连通块 + 竖列/横行色段，工具与算式记在
# tools/probes/README.md。单位逻辑像素。
# **注意容差**：连通块的 bbox 会把 1 px 描边的两侧反锯齿也算进来 ⇒ 实测值比真实容器高多
# 约 1.4（按钮/输入框/开关都是这个量级），所以第 10 关比官方值时容差取 ±1.5。
MEASURED_SETTINGS = {
    "button-height": 41.2,      # tonal「联网更新」y727..788 = 61 px（真实容器 40）
    "field-height": 57.4,       # 输入框/下拉 y187..272 = 85 px（真实容器 56）
    "switch-height": 33.1,      # 开关轨道 y421..470 = 49 px（真实轨道 32）
    "switch-handle": 16.9,      # 选中态手柄芯 23 px + 两侧各 1 px 抗锯齿（官方选中 24 / 未选 16）
    "row-pitch": 48.6,          # 开关行行距 72 px（下拉那一行 96 px = 64.8，更高）
    "card-width": 579.1,        # 2026-10-10 左右布局后重测：两张卡各 6 栏，左卡 x144..1002 = 858 px
    "card-gap": 8.1,            # 卡间 12 px = run_spacing 8（从前 12 + Card 4+4 = 20）
    "side-margin": 97.2,        # 窗口左缘 → 第一张卡：导轨 80 + 页面内边距 16 ≈ 96（左右布局后不再居中）
    "bar-height": 4.0,          # 页脚进度条竖切 6 px ⇒ 4.0 逻辑 = 官方 Height
    "bar-stop": 4.0,            # 停止点全宽 6 px（芯 4 px + 两侧各 1 px 抗锯齿）⇒ 官方 StopSize
    "bar-gap": 3.3,             # 活动段与停止点之间 5 px（再加 1 px 抗锯齿即 4）⇒ 官方 TrackActiveSpace
    "field-stroke": 1.33,       # 静息描边 2 px = 1 实 + 1 混 ⇒ 官方 OutlineWidth 1.0
    "field-focus-stroke": 2.0,  # 聚焦描边 3 px 纯 primary（DPR 1.5）⇒ 官方 FocusOutlineWidth 2.0
    # 结算表（2026-10-06 第三轮；m12800 表头底色照官方改回 `surface` 之后那条带子消失，
    # 表头高改由上下两条线量。当时那份 `history_dark` 基线 1898×1144、DPR 1.5；基线 2026-10-21 已退役）：
    # 表头顶边 y269 → 表头下边 y354 = 85 px = 56.67 逻辑；横线（`outline_variant` #45464f）
    # 共 11 条（y269 顶边 / y354 表头下边 / 每行一条 / y1089 底边），其中相邻间距有 8 个是
    # **恒定的 78 px**；左右两条竖线（x324 / x1853）就是整表外框。
    "hist-head-height": 56.0,
    "hist-row-pitch": 52.0,
}
# 两栏分界（`G.STACK_W = 992`）处一格的可用宽下限（实测 ≈161，取 160）。运行卡的瓦片是竖排的，
# 最宽一枚控件 = 数框 96（从前是「开关 52 + 空档 4 + 数框 96 = 152」，那枚「断连重试」瓦片
# 2026-10-10 用户 m12749 从多人页拆掉了），正是它让 992–1102 那段死区消失（m06279 之前的
# 清单行要在一格里并下 206 逻辑，窗口 1024 就溢出）。
# 2026-10-09（用户 m12311 问「多人演出左右两边的宽度有什么依据」）把这条重新核了一遍：
# **多人页那些瓦片的行比 160 更贴线** —— 5/12 + 7/12 在 992 处每枚只有 ≈151（`G.TILE_MIN_W`
# = 152 正好压在线上，靠吃掉 12 的列间距过活），换成 6/6 只剩 ≈127；m12749 拆掉那枚瓦片之后
# `G.TILE_MIN_W` 退成 96、两档都放得下 ⇒ 2026-10-10 用户 m13525 定「两栏等宽」，多人页与设置页
# 都改成 6/12 + 6/12（设置页原先是各 7 栏居中，栅格换行 ⇒ 其实是上下堆着）。所以多人页那一档
# 不按这个常数判，而在 `fletpanel.py` PART 10 里按**实拍的活值**（`G.MULTI_CHROME_W` /
# `G.TILE_MIN_W`）算。
HALF_CELL_MIN = 160.0
# 对比度：规范的正文角色要求 ≥ 4.5:1（on_X 压 X）。
CONTRAST_PAIRS = (
    ("primary", "on_primary"), ("secondary", "on_secondary"), ("tertiary", "on_tertiary"),
    ("error", "on_error"), ("surface", "on_surface"), ("surface", "on_surface_variant"),
    ("primary_container", "on_primary_container"),
    ("secondary_container", "on_secondary_container"),
    ("tertiary_container", "on_tertiary_container"),
    ("error_container", "on_error_container"),
    ("inverse_surface", "on_inverse_surface"),
)
CONTRAST_MIN = 4.5
GRID = 4.0                                          # M3 的 4dp 栅格


# ---------------------------------------------------------------------------
# 纯函数：比对逻辑与「谁提供值」分开，带牙才可能在同一进程里改坏再跑
# ---------------------------------------------------------------------------
def _px(v):
    """'3.5625rem' -> 57.0（1rem = 16px）；'0rem' -> 0.0；'-0.015625rem' -> -0.25。"""
    return round(float(str(v)[:-3]) * 16, 6)


def diff_roles(frozen, built):
    bad = []
    for which in ("light", "dark"):
        for role in built[which]:
            if frozen[which].get(role) != built[which][role]:
                bad.append(f"{which}.{role}: 表 {frozen[which].get(role)} vs 重算 {built[which][role]}")
    return bad


def diff_ext(frozen, built):
    bad = []
    for which in ("light", "dark"):
        for name, val in built[which].items():
            if frozen[which].get(name) != val:
                bad.append(f"{which}.{name}: 表 {frozen[which].get(name)} vs 重算 {val}")
        for name in frozen[which]:
            if name not in built[which]:
                bad.append(f"{which}.{name}: 表里有、重算没有")
    return bad


def diff_types(local, official):
    bad = []
    for role, (size, line, track, weight) in official.items():
        want = (_px(size), _px(line), WEIGHT_OF[weight], _px(track))
        got = tuple(local.get(role, ()))
        if len(got) != 4 or any(abs(float(a) - float(b)) > 1e-6 for a, b in zip(got, want)):
            bad.append(f"{role}: 面板 {got} vs 官方 {want}")
    for role in local:
        if role not in official:
            bad.append(f"{role}: 面板有、官方没有")
    return bad


def diff_map(local, official):
    """同键名逐格比（形状 / 高程 / 状态层 / 时长都用它）。"""
    bad = []
    for k, want in official.items():
        got = local.get(k, "<缺>")
        if not isinstance(got, (int, float)) or abs(float(got) - float(want)) > 1e-6:
            bad.append(f"{k}: 面板 {got} vs 官方 {want}")
    for k in local:
        if k not in official:
            bad.append(f"{k}: 面板有、官方没有")
    return bad


def diff_components(pairs):
    """pairs = [(说明, 面板值, 官方值)]。"""
    bad = []
    for label, got, want in pairs:
        if abs(float(got) - float(want)) > 1e-6:
            bad.append(f"{label}: 面板 {got} vs 官方 {want}")
    return bad


def _enum_members(cls):
    return list(getattr(cls, "__members__", {}).values()) or list(cls)


def _fields(cls):
    """flet 的控件都是 dataclass；量「有没有这个字段」就走它。"""
    try:
        return {f.name for f in dataclasses.fields(cls)}
    except TypeError:
        return set(getattr(cls, "__dataclass_fields__", {}))


# ---------------------------------------------------------------------------
# PART 1  颜色：46 个角色（重算 + 规范关系）
# ---------------------------------------------------------------------------
def part1():
    frozen = {"light": T.SCHEMES["light"], "dark": T.SCHEMES["dark"]}
    built = GEN.build()

    check("PART 1", "角色名与 flet.ColorScheme 的字段逐字相同",
          set(T.ROLES) == _fields(ft.ColorScheme),
          f"面板 {len(T.ROLES)} 个，ColorScheme {len(_fields(ft.ColorScheme))} 个"
          f"，差 {sorted(set(T.ROLES) ^ _fields(ft.ColorScheme))}")
    check("PART 1", "gen_m3_tokens 的角色表与 m3_theme 的同一套（顺序也一致）",
          tuple(GEN.ROLES) == tuple(T.ROLES))
    check("PART 1", "冻结表记着 seed / variant / contrast，且与生成器一致",
          T.TOKENS.get("seed") == GEN.SEED and T.TOKENS.get("variant") == GEN.VARIANT
          and float(T.TOKENS.get("contrast", -1)) == float(GEN.CONTRAST),
          f"{T.TOKENS.get('seed')} / {T.TOKENS.get('variant')} / {T.TOKENS.get('contrast')}")
    check("PART 1", "冻结表自带出处说明（_what / _how / _gen）",
          all(isinstance(T.TOKENS.get(k), str) and T.TOKENS.get(k) for k in ("_what", "_how", "_gen")))
    check("PART 1", "只有 on_inverse_surface 一个名字需要映射（参考实现的命名差）",
          GEN.MCU_NAME == {"on_inverse_surface": "inverse_on_surface"})
    check("PART 1", "46 × 2 套外观的色值都是 '#rrggbb' 小写",
          all(isinstance(v, str) and len(v) == 7 and v.startswith("#") and v == v.lower()
              for which in frozen for v in frozen[which].values()))
    check("PART 1", "两套外观不是同一套（至少 30 个角色不同）",
          sum(1 for r in T.ROLES if frozen["light"][r] != frozen["dark"][r]) >= 30)
    bad = diff_roles(frozen, built)
    check("PART 1", "46 × 2 格与参考实现重算一致", not bad, "; ".join(bad[:3]))
    ratios = []
    for which in ("light", "dark"):
        for base, on in CONTRAST_PAIRS:
            ratios.append((which, f"{base}/{on}",
                           mcu.get_contrast_ratio(frozen[which][base], frozen[which][on])))
    low = [f"{w}.{p}={r:.2f}" for w, p, r in ratios if r < CONTRAST_MIN]
    check("PART 1", f"正文对比度 ≥ {CONTRAST_MIN}:1（{len(ratios)} 对）", not low, "; ".join(low[:4]))
    check("PART 1", "极值也在合理区间（没有全黑/全白那种退化色板）",
          all(r < 21.0 for _, _, r in ratios) and min(r for _, _, r in ratios) > 1.5)


# ---------------------------------------------------------------------------
# PART 2  扩展色：6 组 × 5 色调 × 2 套外观
# ---------------------------------------------------------------------------
def part2():
    frozen = {"light": T.TOKENS["ext"]["light"], "dark": T.TOKENS["ext"]["dark"]}
    built = GEN.build_ext()
    check("PART 2", "6 组难度色与 EXT_NAMES 一一对应（success/warning/easy/normal/hard/expert）",
          len(T.EXT_NAMES) == 6
          and all(n in frozen[w] for w in ("light", "dark") for n in T.EXT_NAMES))
    want = {n: {n, "on_" + n, n + "_container", "on_" + n + "_container", n + "_container_dim"}
            for n in T.EXT_NAMES}
    bad = [f"{w}.{n}" for w in ("light", "dark") for n in T.EXT_NAMES
           if not want[n] <= set(frozen[w])]
    check("PART 2", "每组 5 个色调（含 _container_dim），两套外观同构", not bad, "; ".join(bad))
    bad = diff_ext(frozen, built)
    check("PART 2", "60 格与参考实现重算一致", not bad, "; ".join(bad[:3]))


# ---------------------------------------------------------------------------
# PART 3  字阶：15 档 × 4 格
# ---------------------------------------------------------------------------
def part3():
    bad = diff_types(T.TYPES, OFFICIAL_TYPES)
    check("PART 3", "15 档字阶（字号/行高/字距/字重）与官方 Web 导出一致", not bad,
          "; ".join(bad[:3]))
    check("PART 3", "TYPE_ORDER 就是 TYPES 的键序（视图层按它遍历）",
          tuple(T.TYPE_ORDER) == tuple(T.TYPES))
    fits = [r for r in T.TYPES if abs(T.TYPES[r][0] - round(T.TYPES[r][0])) > 1e-9]
    check("PART 3", "字号都是整数 px（rem × 16 的结果，没有半像素）", not fits, str(fits))
    div = {r: T.TYPES[r][3] for r in OFFICIAL_TYPE_DIVERGENCE}
    check("PART 3", "三处「Google 自家两份导出不一致」的 tracking 跟的是 Web 那份",
          all(abs(div[r] - _px(OFFICIAL_TYPES[r][2])) < 1e-6 for r in div)
          and all(abs(div[r] - OFFICIAL_TYPE_DIVERGENCE[r]) > 1e-6 for r in div),
          f"面板 {div}，androidx 那套是 {OFFICIAL_TYPE_DIVERGENCE}")
    check("PART 3", "'t' 那一档（区块标题）确实指向 titleMedium",
          T.FONT_ROLE.get("t") == "titleMedium" and set(T.FONT_ROLE.values()) <= set(T.TYPES))


# ---------------------------------------------------------------------------
# PART 4  形状 / 高程 / 状态层
# ---------------------------------------------------------------------------
def part4():
    bad = diff_map({k: v for k, v in T.SHAPE.items() if k != "full"}, OFFICIAL_SHAPE)
    check("PART 4", "形状 6 档与官方一致（none/extraSmall/small/medium/large/extraLarge）",
          not bad, "; ".join(bad[:3]))
    check("PART 4", "形状 full：面板 999 = 胶囊（官方 9999px，Flet 拿它当无穷大）",
          abs(T.SHAPE["full"] - 999) < 1e-9 and OFFICIAL_SHAPE_FULL == 9999.0,
          f"面板 {T.SHAPE['full']}，官方 {OFFICIAL_SHAPE_FULL}")
    check("PART 4", "形状归属表指向的都是存在的档位",
          all(v in T.SHAPE for v in T.SHAPE_ROLE.values()),
          str(sorted(set(T.SHAPE_ROLE.values()) - set(T.SHAPE))))
    check("PART 4", "字段→extraSmall、卡片→medium、按钮/胶囊→full、列表→none",
          (T.SHAPE_ROLE["field"], T.SHAPE_ROLE["card"], T.SHAPE_ROLE["button"],
           T.SHAPE_ROLE["list"]) == ("extraSmall", "medium", "full", "none"))
    check("PART 4", "高程 6 档与官方一致", not diff_map(T.ELEVATION, OFFICIAL_ELEVATION))
    check("PART 4", "状态层 4 条与 1 级 `_md-sys-state.scss` 一致（不跟 androidx 的 0.1）",
          not diff_map({k: T.STATE_OPACITY[k] for k in OFFICIAL_STATE}, OFFICIAL_STATE))
    check("PART 4", "另两条状态层（disabled / disabled_container）出处是 switch 的 opacity token",
          all(abs(T.STATE_OPACITY[k] - v[0]) < 1e-9 for k, v in OFFICIAL_STATE_EXTRA.items()),
          str({k: T.STATE_OPACITY.get(k) for k in OFFICIAL_STATE_EXTRA}))
    check("PART 4", "间距栅格 = 4dp 的整数倍；lg=16 就是官方的 leading-space，md=12 是**本项目定的**列表项上下空",
          all(abs(v % GRID) < 1e-9 for v in T.SPACE.values())
          and T.SPACE["lg"] == OFFICIAL_LIST["leading-space"]
          and T.SPACE["md"] == PROJECT_DECIDED["list-item-vertical-space"])


# ---------------------------------------------------------------------------
# PART 5  动效：16 档时长 + 7 条缓动 + 面板真正动的 5 处
# ---------------------------------------------------------------------------
def part5():
    bad = diff_map(T.MOTION_DURATION, OFFICIAL_DURATION)
    check("PART 5", "16 档时长与官方一致（含 extended 那 4 档，官方名是 extra-long）",
          not bad, "; ".join(bad[:3]))
    check("PART 5", "只有 extended1-4 四处命名与官方不同（extra-long1-4），其余同名",
          all(k in OFFICIAL_DURATION for k in T.MOTION_DURATION)
          and set(OFFICIAL_DURATION_NAME) == {"extended1", "extended2", "extended3", "extended4"})
    check("PART 5", "缓动的键就是官方 10 条里非 legacy 的那 7 条",
          set(T.MOTION_EASING) == set(OFFICIAL_EASING))
    check("PART 5", "emphasized 是逐点相等的那一条（easeInOutCubicEmphasized 就是 (0.2,0,0,1)）",
          T.MOTION_EASING["emphasized"] == ft.AnimationCurve.EASE_IN_OUT_CUBIC_EMPHASIZED)
    check("PART 5", "官方 legacy 那三条在 Flet 里没有对应曲线（所以不登记）",
          not any("LEGACY" in str(getattr(v, "name", v)).upper() for v in ft.AnimationCurve))
    check("PART 5", "官方这一版 emphasized 与 standard 是同一条曲线；面板 standard 走 Flutter 的 "
                    "easeInOut(0.4,0,0.2,1) —— 已知近似，记在 DEVIATIONS 里",
          OFFICIAL_EASING["standard"][1] == OFFICIAL_EASING["emphasized"][1]
          and T.MOTION_EASING["standard"] == ft.AnimationCurve.EASE_IN_OUT)
    bad = [f"{n}: {d}/{e}" for n, (d, e) in T.MOTION.items()
           if d not in T.MOTION_DURATION or e not in T.MOTION_EASING]
    check("PART 5", "面板动的 5 处都引用了官方档位（没有哪一处是自己编的数字）", not bad, str(bad))
    check("PART 5", "5 处装置的时长就是对应档位的时长",
          all(T.motion_ms(n) == OFFICIAL_DURATION[d] for n, (d, _) in T.MOTION.items()),
          str({n: T.motion_ms(n) for n in T.MOTION}))
    check("PART 5", "animation() 出来的 ft.Animation 带 duration 与 curve",
          all(isinstance(T.animation(n), ft.Animation) for n in T.MOTION))


# ---------------------------------------------------------------------------
# PART 6  组件几何：官方 token ↔ 面板常量
# ---------------------------------------------------------------------------
def component_pairs():
    return [
        ("「最近」每行高 RECENT_ROW_H ↔ list-item two-line", G.RECENT_ROW_H, OFFICIAL_LIST["two-line"]),
        ("「最近」封面 RECENT_ART ↔ list leading-image", G.RECENT_ART, OFFICIAL_LIST["leading-image"]),
        ("头像 AVATAR ↔ list leading-avatar-size", T.AVATAR, OFFICIAL_LIST["leading-avatar-size"]),
        ("大图标 ICON_LG ↔ list leading-icon-size", T.ICON_LG, OFFICIAL_LIST["leading-icon-size"]),
        ("行内空 T.SPACE['lg'] ↔ list leading-space", T.SPACE["lg"], OFFICIAL_LIST["leading-space"]),
        ("行内侧空 T.SPACE['lg'] ↔ list trailing-space", T.SPACE["lg"], OFFICIAL_LIST["trailing-space"]),
        ("行内上下空 T.SPACE['md'] ↔ 本项目定的列表项上留白",
         T.SPACE["md"], PROJECT_DECIDED["list-item-vertical-space"]),
        ("行内上下空 T.SPACE['md'] ↔ 本项目定的列表项下留白",
         T.SPACE["md"], PROJECT_DECIDED["list-item-vertical-space"]),
        ("按钮高 BTN_H ↔ filled-button container-height",
         G.BTN_H, OFFICIAL_FILLED_BUTTON["container-height"]),
        ("分段控件高 SEGMENT_H ↔ outlined-segmented-button container-height",
         T.SEGMENT_H, OFFICIAL_SEGMENT["container-height"]),
        ("卡片圆角 T.SHAPE['medium'] ↔ corner-medium", T.SHAPE["medium"], OFFICIAL_SHAPE["medium"]),
        ("字段圆角 T.SHAPE['extraSmall'] ↔ corner-extra-small",
         T.SHAPE["extraSmall"], OFFICIAL_SHAPE["extraSmall"]),
    ]


def part6():
    pairs = component_pairs()
    bad = diff_components(pairs)
    check("PART 6", f"面板常量与官方组件几何逐格对齐（{len(pairs)} 格）", not bad,
          "; ".join(bad[:3]))
    check("PART 6", "这些常量都落在 4dp 栅格上",
          all(abs(float(v) % GRID) < 1e-9 for _, v, _ in pairs),
          str([l for l, v, _ in pairs if abs(float(v) % GRID) > 1e-9]))
    # 「最近」那一行的几何是**一对**官方常数：两行列表项容器高 72 = 封面 56 + 上下各 8 内边距。
    # 2026-10-06 用户 m09165 报「封面是长方形」：行只留 64 而封面还是 56 ⇒ 被 Flutter 夹成
    # 56×48。这条把「封面 + 2×内边距 = 行高」钉成等式，光把两边的常数一起挪已经骗不过去了。
    check("PART 6", "「最近」一行 = 官方两行列表项（封面 56 + 上下 8 内边距 = 容器 72）",
          G.RECENT_ROW_H == OFFICIAL_LIST["two-line"]
          and G.RECENT_ART == OFFICIAL_LIST["leading-image"]
          and G.RECENT_ART + 2 * T.SPACE["sm"] == G.RECENT_ROW_H
          and G.RECENT_CHROME_H >= G.RECENT_ART and G.RECENT_POOL == 6
          # 2026-10-09 用户 m12311：多人页那张卡的上限单独一档（15）。两张卡同一个类，
          # 只差 `pool`，所以两个常数都得在（m14172 一度改成 10，同日 m14308 又改回 15）。
          and G.RECENT_POOL_MULTI == 15)
    check("PART 6", "运行卡最宽一枚瓦片（开关 52 + 空档 4 + 数框 96 = 152）装得进两栏分界处的一格",
          OFFICIAL_SWITCH["track-width"] + T.SPACE["xs"] + 96 <= HALF_CELL_MIN)
    check("PART 6", "两个 40 高的按钮族各取各的官方容器高（filled-button 与分段控件），"
                    "不是本项目定的触摸目标 48",
          G.BTN_H == OFFICIAL_FILLED_BUTTON["container-height"]
          and T.SEGMENT_H == OFFICIAL_SEGMENT["container-height"]
          and PROJECT_DECIDED["switch-touch-target"] != T.SEGMENT_H)


# ---------------------------------------------------------------------------
# PART 7  官方有、Flet 没有 —— 登记在案，且断言它**真的**没有（防止有人以为能用）
# 这里只剩 switch 的手柄几何：官方给手柄宽高，`ft.Switch` 一个字段都没有（52×32 由 Flutter 画）。
# 触摸目标 48 **不在这一列** —— 它只在 MWC 适配层（非 versioned）里，按依据顺序算本项目决定。
# ---------------------------------------------------------------------------
def part7():
    sw_fields = _fields(ft.Switch)
    check("PART 7", f"switch 几何 {len(OFFICIAL_SWITCH)} 条官方值登记在案（52×32 / 状态层 40 / 手柄四档）",
          OFFICIAL_SWITCH["track-width"] == 52.0 and OFFICIAL_SWITCH["track-height"] == 32.0
          and PROJECT_DECIDED["switch-touch-target"] == 48.0)
    check("PART 7", "ft.Switch 只有通用 width/height 与 track_outline_width，没有 "
                    "track-width/track-height/手柄几何（52×32 由 Flutter 画）",
          "track_outline_width" in sw_fields
          and not (sw_fields & {"track_width", "track_height", "handle_width", "handle_height",
                                "unselected_handle_width", "selected_handle_width"}),
          "Flet 的 track_outline_width=" + str(getattr(ft.Switch(), "track_outline_width", None))
          + f"（官方 {OFFICIAL_SWITCH['track-outline-width']}）")
    names = {getattr(v, "name", str(v)) for v in _enum_members(ft.AnimationCurve)}
    check("PART 7", f"官方 7 条非 legacy 缓动都能在 ft.AnimationCurve 里找到（本版枚举 {len(names)} 条）",
          len(names) >= 40
          and all(getattr(v, "name", "") in names for v in T.MOTION_EASING.values()),
          str(sorted(v.name for v in T.MOTION_EASING.values())))


# ---------------------------------------------------------------------------
# PART 8  自述：偏离必须写在 DEVIATIONS 里，出处必须写在文档里
# ---------------------------------------------------------------------------
def part8():
    check("PART 8", f"DEVIATIONS 是 {len(T.DEVIATIONS)} 条，每条都有理由（≥ 8 字）",
          len(T.DEVIATIONS) >= 7 and all(len(r) >= 8 for _, r in T.DEVIATIONS),
          f"{len(T.DEVIATIONS)} 条")
    check("PART 8", "缓动近似在 DEVIATIONS 里有条目（不假装逐点相等）",
          any("缓动" in d for d, _ in T.DEVIATIONS))
    theme_src = _read(os.path.join(TOOLS, "m3_theme.py"))
    check("PART 8", "m3_theme.py 顶栏记着官方出处（版本号 + 镜像前缀 + 组件级文件名）",
          "v0_192" in theme_src and "cdn.jsdelivr.net" in theme_src and "_md-comp-" in theme_src)
    check("PART 8", "m3_theme.py 指认本探针为「拿参考实现重算」的那一个",
          "probes/m3tokens.py" in theme_src or "probes\\m3tokens.py" in theme_src)
    agents = _read(os.path.join(ROOT, "AGENTS.md"))
    check("PART 8", "AGENTS.md 的权威顺序里有 material-web token 导出与版本号",
          "token" in agents and "v0_192" in agents)
    readme = _read(os.path.join(HERE, "README.md"))
    check("PART 8", "tools/probes/README.md 索引里有本探针",
          "m3tokens.py" in readme)
    refs: set[str] = set()
    for text in (theme_src, agents, readme):
        refs |= set(re.findall(r"probes[/\\]([A-Za-z0-9_]+\.py)", text))
    missing = sorted(r for r in refs if not os.path.exists(os.path.join(HERE, r)))
    check("PART 8", f"文档里点到的探针文件都真的存在（{len(refs)} 个）", not missing, str(missing))


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# PART 9  带牙：同一进程里把输入改坏，再跑同一个 diff 函数
# ---------------------------------------------------------------------------
def part9():
    built = GEN.build()
    frozen = {"light": dict(T.SCHEMES["light"]), "dark": dict(T.SCHEMES["dark"])}
    tainted = json.loads(json.dumps(frozen))
    tainted["light"]["primary"] = "#123456"
    check("PART 9", "改一格角色值 -> diff_roles 抓到 1 处",
          len(diff_roles(tainted, built)) == 1, str(diff_roles(tainted, built)[:1]))
    other_seed = GEN.build(seed="#ff0000")
    check("PART 9", "换种子重算 -> 抓到 ≥ 40 处（约一半角色会变）",
          len(diff_roles(frozen, other_seed)) >= 40, f"{len(diff_roles(frozen, other_seed))} 处")
    off = dict(OFFICIAL_TYPES)
    off["bodySmall"] = ("0.75rem", "1rem", "0.03rem", "regular")
    check("PART 9", "改一档字距 -> diff_types 抓到 1 处", len(diff_types(T.TYPES, off)) == 1)
    off = dict(OFFICIAL_DURATION)
    off["short1"] = 60
    check("PART 9", "改一档时长 -> diff_map 抓到 1 处",
          len(diff_map(T.MOTION_DURATION, off)) == 1)
    off = dict(OFFICIAL_SHAPE)
    off["medium"] = 10.0
    check("PART 9", "改一档形状 -> diff_map 抓到 1 处",
          len(diff_map({k: v for k, v in T.SHAPE.items() if k != "full"}, off)) == 1)
    pairs = list(component_pairs())
    # 按**标签**找那一格，不按序号：m06279 删掉第 0 格（`OPT_ROW_H`）之后，`pairs[2]` 已经从
    # 「封面图 ↔ leading-image」变成「头像 AVATAR ↔ leading-avatar-size」，而 T.AVATAR 本来就是
    # 40 —— 变异成了空操作，这条判据当场变假（判据不该依赖别处的顺序）。
    ci = next(k for k, p in enumerate(pairs) if "RECENT_ART" in p[0])
    pairs[ci] = (pairs[ci][0], pairs[ci][1], 40.0)       # 官方封面图改成 40
    check("PART 9", "官方封面图改成 40 -> 组件比对抓到 1 处", len(diff_components(pairs)) == 1)
    tainted = json.loads(json.dumps({"light": T.TOKENS["ext"]["light"], "dark": T.TOKENS["ext"]["dark"]}))
    tainted["dark"]["expert"] = "#000000"
    check("PART 9", "改一格扩展色 -> diff_ext 抓到 1 处",
          len(diff_ext(tainted, GEN.build_ext())) == 1)


# ---------------------------------------------------------------------------
# PART 10  设置页（两张卡）的 M3 口径：卡的成套、行的字色、开关四色、桌面密度、实测值
# ---------------------------------------------------------------------------
def part10():
    gui = _read(os.path.join(TOOLS, "flet_gui.py"))
    theme_src = _read(os.path.join(TOOLS, "m3_theme.py"))

    # ① 卡：M3 三种卡里 elevated 的三件套（容器色 + 高度 + 圆角）必须成套出现，
    #    只挑一半就不算任何一种卡（卡内边距已按官方 16 走，见 OFFICIAL_CARD）。
    check("PART 10", "设置页两张卡走 M3 的 elevated 卡：surface_container_low + level1 + 12 圆角",
          "variant=ft.CardVariant.ELEVATED" in gui
          and 'elevation=T.elevation("level1")' in gui
          and "bgcolor=tk.card" in gui and 'radius=T.radius("card")' in gui
          and T.SEMANTIC["card"] == "surface_container_low"
          and T.radius("card") == OFFICIAL_SHAPE["medium"] == 12.0
          and T.ELEVATION["level1"] == OFFICIAL_ELEVATION["level1"],
          "圆角 %s（官方 medium %s）"
          % (T.radius("card"), OFFICIAL_SHAPE["medium"]))
    check("PART 10", "卡片标题行是 16 号 titleMedium + leading 图标（官方 list leading-icon 24）",
          T.type_style(T.FONT_ROLE["t"]).size == 16
          and "ft.Icon(icon, size=T.ICON_LG, color=tk.accent)" in gui
          and T.ICON_LG == OFFICIAL_LIST["leading-icon-size"])

    # ② 设置行的标签：12 号 + on_surface_variant。M3 的列表项主文字是 16 号 + on_surface —— 知情偏离。
    check("PART 10", "设置行的标签是 bodySmall(12) + on_surface_variant（M3 列表项是 16 号 on_surface，"
                     "差异登记在 DEVIATIONS 里）",
          'txt(text, tk, "n", color=tk.text_dim)' in gui
          and T.type_style(T.FONT_ROLE["n"]).size == 12
          and T.type_style("bodyLarge").size == 16
          and T.SEMANTIC["text_dim"] == "on_surface_variant"
          and any("on_surface_variant" in d for d, _ in T.DEVIATIONS))

    # ③ 开关四色：M3 的角色名逐条点名。第 7 关查几何（52×32 由 Flutter 画），这里查色。
    fields = _fields(ft.Switch)
    check("PART 10", "开关四色按 M3 角色点名（选中手柄 on_primary、选中轨道 primary、未选中手柄 "
                     "outline、未选中轨道 surface_container_highest），且 ft.Switch 真有这四个字段",
          all(k in gui for k in ('"active_color": tk.on_accent',
                                 '"active_track_color": tk.accent',
                                 '"inactive_thumb_color": tk.outline',
                                 '"inactive_track_color": tk.field'))
          and {"active_color", "active_track_color",
               "inactive_thumb_color", "inactive_track_color"} <= fields
          and T.SEMANTIC["on_accent"] == "on_primary" and T.SEMANTIC["accent"] == "primary"
          and T.SEMANTIC["field"] == "surface_container_highest"
          and "outline" in T.ROLES and "on_primary" in T.ROLES,
          "只写 active_color 时轨道由 Flutter 推成 primary 的 50%（实测 #696f90），规范要不透明 primary")
    check("PART 10", "两颗开关助手都走 switch_colors()（不各写一份、不留写死的 active_color）",
          gui.count("**switch_colors(tk)") == 2
          and "def switch_colors(tk):" in gui
          and "active_color=tk.accent" not in inspect.getsource(G.toggle)
          and "active_color=tk.accent" not in inspect.getsource(G.switch))

    # ④ 桌面密度：官方 40 / 56 都是**标准档**的数。从前写 COMPACT（density × 4dp = 8dp，
    #    按钮画成 32、输入框画成 48），m08726 按官方改回 STANDARD；实拍 41.2 / 57.4 是官方值
    #    加上连通块把 1 px 描边反锯齿算进 bbox 的那 1.4。
    check("PART 10", "桌面密度取 STANDARD（官方 40 / 56 是标准档的数），实测按钮 41.2 / 输入框 57.4 "
                     "= 官方值 + 描边反锯齿",
          "visual_density=ft.VisualDensity.STANDARD" in theme_src
          and DENSITY_ADJUST == 0.0
          and abs(MEASURED_SETTINGS["button-height"] - DENSITY_ADJUST
                  - OFFICIAL_FILLED_BUTTON["container-height"]) <= 1.5
          and abs(MEASURED_SETTINGS["field-height"] - DENSITY_ADJUST
                  - OFFICIAL_TEXT_FIELD["container-height"]) <= 1.5,
          "官方 %s＋%s vs 实测 %s | 官方 %s＋%s vs 实测 %s"
          % (OFFICIAL_FILLED_BUTTON["container-height"], DENSITY_ADJUST,
             MEASURED_SETTINGS["button-height"], OFFICIAL_TEXT_FIELD["container-height"],
             DENSITY_ADJUST, MEASURED_SETTINGS["field-height"]))
    check("PART 10", "设置页实测：行距 ≥ 本项目定的触摸目标 48、开关轨道高 = 官方 32（±1）、"
                     "两卡各 6 栏左右并排（不靠居中来摆）",
          MEASURED_SETTINGS["row-pitch"] >= PROJECT_DECIDED["switch-touch-target"]
          and abs(MEASURED_SETTINGS["switch-height"] - OFFICIAL_SWITCH["track-height"]) <= 1.5
          and MEASURED_SETTINGS["side-margin"] > 0
          and MEASURED_SETTINGS["card-width"] > HALF_CELL_MIN
          and gui.count('col={"xs": 12, "md": 6}') >= 2
          and "alignment=ft.MainAxisAlignment.CENTER" not in gui,
          "行距 %.1f、轨道 %.1f、卡宽 %.1f、两侧留白 %.1f"
          % (MEASURED_SETTINGS["row-pitch"], MEASURED_SETTINGS["switch-height"],
             MEASURED_SETTINGS["card-width"], MEASURED_SETTINGS["side-margin"]))

    # ⑤ 下拉：Flet 有两只 —— `ft.Dropdown`（M3 档：DropdownOption + on_select + menu_style）与
    #    `ft.DropdownM2`（老 M2 那只：Option + on_change + item_height）。面板用的是前者。
    # ⑥ 手柄几何：官方两份导出（material-web 的 switch 表与 androidx SwitchTokens.kt）一致 ——
    #    选中手柄 24、未选中 16；实测选中态只有约 16.9（开关中心竖切，深色芯 23 px + 两侧各 1 px
    #    抗锯齿）⇒ 框架画的是 16 那一档。`ft.Switch` 没有手柄几何字段（第 7 关断言过），改不了，
    #    只能登记（`m3_theme.DEVIATIONS` 里「开关手柄尺寸跟框架走」那一条 —— 按名字指，不按序号）。
    check("PART 10", "开关手柄：官方选中 24 / 未选 16，实测选中态约 16.9（框架只画 16 那一档；"
                     "ft.Switch 没有手柄几何字段，登记在 DEVIATIONS）",
          OFFICIAL_SWITCH["selected-handle"] == 24.0
          and OFFICIAL_SWITCH["unselected-handle"] == 16.0
          and abs(MEASURED_SETTINGS["switch-handle"] - 16.9) <= 1.0
          and not (fields & {"handle_width", "handle_height", "handle_size",
                             "selected_handle_width", "selected_handle_height"})
          and any("手柄" in d for d, _ in T.DEVIATIONS),
          "官方选中 %.0f / 未选 %.0f，实测 %.1f"
          % (OFFICIAL_SWITCH["selected-handle"], OFFICIAL_SWITCH["unselected-handle"],
             MEASURED_SETTINGS["switch-handle"]))
    check("PART 10", "下拉用的是 Flet 的 M3 档 `ft.Dropdown`（M2 那只叫 `ft.DropdownM2`，没被用）",
          hasattr(ft, "Dropdown") and hasattr(ft, "DropdownM2")
          and "ft.DropdownM2" not in gui
          and "ft.DropdownOption(key=k, text=v)" in gui
          and "on_select=on_select" in gui
          and "border=input_border(tk)" in gui)

    # ⑦ 输入框描边两档：官方 `OutlineColor=Outline` / `OutlineWidth=1.0.dp` 与
    #    `FocusOutlineColor=Primary` / `FocusOutlineWidth=2.0.dp`。从前静息写的是 `tk.border`
    #    （= outline_variant，那是分界线角色）、聚焦只换色不换宽 —— 实拍两枚框的描边像素数
    #    完全一样（都 1032）⇒ 都只有 1dp。**`tk.border` 不能跟着改**：`hairline()` 用它，
    #    M3 的 `DividerTokens.Color` 正是 OutlineVariant。
    check("PART 10", "输入框描边：静息 outline 1dp / 聚焦 primary 2dp（官方 OutlinedTextField 两档；"
                     "分界线继续用 outline_variant）",
          "side=ft.BorderSide(1, tk.outline)" in gui
          and "side=ft.BorderSide(2, tk.accent)" in gui
          and "side=ft.BorderSide(1, tk.border)" not in gui
          and T.SEMANTIC["border"] == "outline_variant"
          and "ft.Divider(height=1, thickness=1, color=tk.border)" in gui
          and abs(MEASURED_SETTINGS["field-stroke"] - OFFICIAL_TEXT_FIELD["outline-width"]) <= 0.5
          and abs(MEASURED_SETTINGS["field-focus-stroke"]
                  - OFFICIAL_TEXT_FIELD["focus-outline-width"]) <= 0.5,
          "官方 %s/%s dp，实测 %s/%s"
          % (OFFICIAL_TEXT_FIELD["outline-width"], OFFICIAL_TEXT_FIELD["focus-outline-width"],
             MEASURED_SETTINGS["field-stroke"], MEASURED_SETTINGS["field-focus-stroke"]))

    # ⑧ 进度条：轨道 = SecondaryContainer（从前 `trough` 给的是 surface_container_highest，实拍
    #    轨道 `#34343a` / `#e3e1e9` 对不上官方 `#424659` / `#dee1f9`），活动段与停止点 = Primary；
    #    停止点 Flutter 自己画（M3 的确定值进度条默认就有），高/停止点/空档都 4dp。
    check("PART 10", "进度条：轨道 = secondary_container、活动段与停止点 = primary、"
                     "高/停止点/空档都是官方 4dp",
          T.SEMANTIC["trough"] == OFFICIAL_PROGRESS["track-role"]
          and T.SEMANTIC["accent"] == OFFICIAL_PROGRESS["active-role"]
          and "bgcolor=self.tk.trough" in gui
          and "linear_track_color=tk.trough" in theme_src
          and abs(MEASURED_SETTINGS["bar-height"] - OFFICIAL_PROGRESS["height"]) <= 0.5
          and abs(MEASURED_SETTINGS["bar-stop"] - OFFICIAL_PROGRESS["stop-size"]) <= 0.5
          and abs(MEASURED_SETTINGS["bar-gap"]
                  - OFFICIAL_PROGRESS["track-active-space"]) <= 0.8,
          "轨道 %s，高 %.1f / 停止点 %.1f / 空档 %.1f（官方全 4.0）"
          % (T.SEMANTIC["trough"], MEASURED_SETTINGS["bar-height"],
             MEASURED_SETTINGS["bar-stop"], MEASURED_SETTINGS["bar-gap"]))

    # ⑨ 搜索框尾部的清空按钮：官方 `TrailingIconSize 24`。从前取的是 `T.SPACE["lg"]`（= 16，
    #    那是列表内边距档，不是图标档）。
    check("PART 10", "搜索框尾部清空图标用 ICON_LG（= 官方 trailing-icon 24），不拿内边距档当图标尺寸",
          "icon_size=T.ICON_LG, visible=False" in gui
          and 'icon_size=T.SPACE["lg"]' not in gui
          and T.ICON_LG == OFFICIAL_TEXT_FIELD["trailing-icon-size"],
          "ICON_LG=%s 官方 %s" % (T.ICON_LG, OFFICIAL_TEXT_FIELD["trailing-icon-size"]))

    # ⑩ 卡片：规格表的 16 / ≤8。本地从前 `T.SPACE["md"]`(12) 内边距 + 栅格 12 + Card 自带 4+4，
    #    实拍卡间距 20；照 m08726 全部收到官方值（Card 的 margin 归零，间距交给外层 8）。
    check("PART 10", "卡片按官方规格表：内边距 16、卡间距 ≤8（Card 自带 4 margin 已归零）",
          'pad = padding if padding is not None else T.SPACE["lg"]' in gui
          and 'opts = {"margin": 0}' in gui
          and MEASURED_SETTINGS["card-gap"] <= OFFICIAL_CARD["gap"] + 1.0
          and gui.count('spacing=T.SPACE["sm"], run_spacing=T.SPACE["sm"]') >= 2,
          "卡间距实测 %.1f（官方上限 %.0f）" % (MEASURED_SETTINGS["card-gap"], OFFICIAL_CARD["gap"]))

    # ⑪ 输入框的字：官方 `OutlinedTextFieldTokens.InputFont = TypographyKeyTokens.BodyLarge`
    #    （源文件第 161-162 行）。这一档不是口味 —— Flet 画出来的容器高 = 文字行高 + 上下 16
    #    内边距，`bodyMedium`(20) 只到 52（实拍 53.3），`bodyLarge`(24) 才是 56。
    #    `dense=True,` 这一写法在视图层必须绝迹（它会把官方 56 压到 48）。
    check("PART 10", "输入框与下拉的字取官方 InputFont = BodyLarge（容器高 56 就是这一档撑出来的），"
                     "视图层不再出现 `dense=True`",
          gui.count('text_style=T.type_style("bodyLarge")') >= 3
          # 输入框/下拉那两条按函数源查（不能查 `bodyMedium` 是否存在：新写的 docstring 里就
          # 在讲它为什么不够；也不能查 `label_text_style=` —— 那里面含 `text_style=` 子串）
          and 'text_style=T.type_style("bodyLarge")' in inspect.getsource(G.num_field)
          and 'text_style=T.type_style("bodyLarge")' in inspect.getsource(G.dropdown)
          and "dense=True," not in gui and "dense=True," not in theme_src
          and T.type_style("bodyLarge").size == 16,
          "bodyLarge ×%d，dense 残留 %d"
          % (gui.count('text_style=T.type_style("bodyLarge")'), gui.count("dense=True,")))

    lt = T.theme("dark").list_tile_theme
    # ⑫ Chip / 列表行：Chip 内容内边距 8（`Chip.kt` ContentPadding）、容器高 32、图标 18；
    #    选曲列表行的 leading 图标取列表档 24（`ListTokens.ItemLeadingIconSize`，官方这一档就是 24），
    #    两行列表项 72 由框架画（视图层不许再挂 `dense` / 竖向内边距去压它）。
    check("PART 10", "Chip 内边距 8 / 容器高 32 / 图标 18，选曲列表行 leading 图标 24、两行项交给"
                     "框架（视图层与主题层都不许压），主题层字阶照官方",
          'padding=ft.Padding(T.SPACE["sm"], 0, T.SPACE["sm"], 0)' in gui
          and "ft.Icons.MUSIC_NOTE, size=T.ICON_LG" in gui
          and "min_vertical_padding" not in gui
          and 'horizontal_spacing=T.SPACE["lg"]' in gui
          # 主题层那一份从前把 72 压到约 57（m08726 只清了视图层）—— 这两条补上审计点名的洞。
          and "min_vertical_padding" not in theme_src
          and "dense=True," not in theme_src
          and 'horizontal_spacing=SPACE["lg"]),' in theme_src
          and lt.title_text_style.size == T.type_style("bodyLarge").size == 16
          and lt.subtitle_text_style.size == T.type_style("bodyMedium").size == 14
          and T.ICON_LG == OFFICIAL_LIST["leading-icon-size"]
          and T.ICON_SM == OFFICIAL_CHIP["icon-size"]
          and OFFICIAL_LIST["two-line"] == 72.0,
          "ICON_LG=%s（列表档 %s）、ICON_SM=%s（Chip 档 %s）、主题层两档字型 %s/%s"
          % (T.ICON_LG, OFFICIAL_LIST["leading-icon-size"], T.ICON_SM, OFFICIAL_CHIP["icon-size"],
             lt.title_text_style.size, lt.subtitle_text_style.size))

    # ⑬ 窗口尺寸：M3 只按宽度分 5 档（尺寸类），**不规定桌面窗口尺寸** —— 这两个数
    #    是用户点名的版式取舍：默认 1280×800（m09165）、下限 800×600（m09466）。写进判据，免得
    #    以后被「顺手改回 1180×780」。
    check("PART 10", "窗口默认 1280×800、下限 800×600（m09165／m09466 用户定的版式取舍），真入口从规范取",
          T.WINDOW_DEFAULT == (1280, 800) and T.WINDOW_MIN == (800, 600)
          and "page.window.width, page.window.height = T.WINDOW_DEFAULT" in gui
          and "page.window.min_width, page.window.min_height = T.WINDOW_MIN" in gui,
          "默认 %s、下限 %s" % (T.WINDOW_DEFAULT, T.WINDOW_MIN))

    # ⑯ 对话框：官方 `_md-comp-dialog.scss` 的标题 headline-small(24) / supporting text
    #    body-medium(14)，动作是**文字按钮**（action-label-text-color = primary、label-large）。
    #    主题层与视图层从前都把这两档压小（titleMedium 16 / bodySmall 12）、动作还是 filled；
    #    2026-10-06 按官方改回。两层都查：主题层取值、视图层真的用这两档与文字动作。
    dg = T.theme("dark").dialog_theme
    check("PART 10", "对话框标题 headlineSmall(24) / 正文 bodyMedium(14)、动作是文字按钮"
                     "（官方 _md-comp-dialog.scss）",
          OFFICIAL_DIALOG["title-font"] == "headlineSmall"
          and OFFICIAL_DIALOG["title-size"] == 24.0
          and OFFICIAL_DIALOG["supporting-font"] == "bodyMedium"
          and OFFICIAL_DIALOG["action-label-text-color"] == "primary"
          and dg.title_text_style.size == T.type_style("headlineSmall").size == 24
          and dg.content_text_style.size == T.type_style("bodyMedium").size == 14
          and 'type_style("headlineSmall", fam)' in theme_src
          and 'type_style("bodyMedium", fam)' in theme_src
          and 'txt_spec(title, tk, "headlineSmall"' in gui
          and 'txt_spec("快捷按键", tk, "headlineSmall"' in gui
          and 'txt_spec(body, tk, "bodyMedium"' in gui
          and 'txt_spec(what, tk, "bodyMedium"' in gui
          and 'button(tk, ok_label, _ok, kind="text")' in gui
          and 'page.pop_dialog(), kind="text")' in gui,
          "标题 %s / 正文 %s" % (dg.title_text_style.size, dg.content_text_style.size))

    # ⑰ 知情偏离的条目级判据：只有「非空 + 每条 ≥8 字」那颗计数牙是不够的 —— 整条被删掉时它照样
    #    绿。这里按关键词点住那几条（字号取向 / 列表行紧凑字型 / 触摸面）。2026-10-06 撤掉了
    #    「结算表选中行铺 secondary_container」那条（用户 m16213 让改回官方 surface_container_highest），
    #    所以条数从 8 降到 7，并顺手把「视图层真的用了官方那条 token」正向点住。
    #    2026-10-07 用户 m18525 定「导轨永远收起」⇒ +1 条成 8 条，关键词点住它。
    #    2026-10-07 用户 m19421 定「难度选择器完全按官方分段控件来」⇒ 撤掉「难度用四个 Container
    #    排 2×2」那条（视图层换成 `ft.SegmentedButton`），条数回到 7；那条正向证据改由
    #    `fletgui`（源码层）与 `fletpanel` 第 11 关（真窗口属性 + 像素）承担。
    dv = " ".join(a + " " + b for a, b in T.DEVIATIONS)
    check("PART 10", "DEVIATIONS 里那几条知情偏离都还在（字号取向 / 列表行紧凑字型 / 触摸面 / "
                     "导轨永远收起），且结算表选中行已照官方 token",
          len(T.DEVIATIONS) >= 7
          and all(len(b) >= 8 for _a, b in T.DEVIATIONS)
          and "titleLarge(22)" in dv and "紧凑" in dv and "触摸目标" in dv
          and "永远收起" in dv
          and "2×2" not in dv
          and "row-item-selected-container-color" not in dv
          and "bg = self.tk.surface_container_highest if hi else None" in gui,
          "%d 条：%s" % (len(T.DEVIATIONS), " / ".join(a for a, _b in T.DEVIATIONS)))

    # ⑱ 导航轨两档宽度：官方 `_NavigationRailDefaultsM3` 是 minWidth 80 / minExtendedWidth 256
    #    （material-web `_md-comp-navigation-rail.scss` 的 `container-width` 也是 80）。2026-10-06 从
    #    「展开 200」改回官方。2026-10-07 用户 m18525 定「永远收起」之后屏幕上只会出现 80 那一档，
    #    256 只剩主题层的令牌绑定 —— 这条只管「主题层绑的还是官方那两个数」，「视图层永不展开」
    #    由 `fletpanel` 第 10 关在 1560/760 两个宽度下钉。
    check("PART 10", "导航轨两档宽度在主题层取官方 80 / 256（视图层永不展开）",
          T.NAV_MIN_W == 80 and T.NAV_MIN_EXT_W == 256
          and "min_width=NAV_MIN_W" in theme_src
          and "min_extended_width=NAV_MIN_EXT_W" in theme_src,
          "minWidth=%s / minExtendedWidth=%s" % (T.NAV_MIN_W, T.NAV_MIN_EXT_W))

    # ⑭ filter chip 的 flat 三条（2026-10-06 实抓 `FilterChipTokens.kt` 与 Flutter
    #    `packages/flutter/lib/src/material/filter_chip.dart` 的 `_FilterChipDefaultsM3`）：
    #    未选中**不铺底**（官方 flat 未选中返回 `null`，token 里只有 `FlatSelectedContainerColor`）、
    #    未选中描 `outline_variant` 而**选中不描边**（除 `FlatUnselectedOutlineColor` 外没有第二条
    #    描边色）、内边距 8（`Chip.kt` 的 `ContentPadding`）。这两句颜色落在令牌层（视图层不许出现
    #    `ft.Colors`），所以查 `m3_theme` 的 `chip_side()` 与 `chip_theme`，不查控件。
    tk = T.tokens("dark")
    ct = T.theme("dark").chip_theme
    check("PART 10", "filter chip：未选中不铺底、选中不描边、内边距 8（官方 flat 三条）",
          ct.bgcolor == ft.Colors.TRANSPARENT
          and ct.padding.left == OFFICIAL_CHIP["content-padding"]
          and ct.padding.right == OFFICIAL_CHIP["content-padding"]
          and tk.chip_side(True).color == ft.Colors.TRANSPARENT
          and tk.chip_side(False).color == tk.outline_variant
          and tk.chip_side(True).color != tk.chip_side(False).color,
          "底=%s 内边距=%s 选中描边=%s 未选中描边=%s"
          % (ct.bgcolor, ct.padding.left, tk.chip_side(True).color, tk.chip_side(False).color))

    # ⑮ 数据表：官方 `_md-comp-data-table.scss` 的表头 56 / 行 52、表头字 title-small、格字
    #    body-medium、行与行之间一条 `row-item-outline`（1px outline-variant）、整表外框同一条。
    #    m12075 用户要「完全参照 M3 官方设计」⇒ 把上一轮那套桌面密度（表头 36 / 行 28 /
    #    labelMedium / bodySmall / 干脆不画分隔线）整体换掉。列宽只有「文字 + 8 内边距」这个关系是
    #    官方的（**官方没有列宽 token**），放大 1.2 倍是本项目定的换算，理由记在 `HIST_FONT_SCALE` 上。
    check("PART 10", "结算表照官方数据表：表头 56 / 行 52 / titleSmall / bodyMedium / 行间与外框都是 1px outline_variant",
          T.HIST_HEAD_H == OFFICIAL_DATA_TABLE["header-container-height"]
          and T.HIST_ROW_H == OFFICIAL_DATA_TABLE["row-item-container-height"]
          and T.HIST_HEAD_FONT == OFFICIAL_DATA_TABLE["header-headline"]
          and T.HIST_CELL_FONT == OFFICIAL_DATA_TABLE["row-item-label-text"]
          and T.type_style(T.HIST_HEAD_FONT).size == 14
          and T.type_style(T.HIST_CELL_FONT).size == 14
          and T.HIST_OUTLINE_W == OFFICIAL_DATA_TABLE["row-item-outline-width"]
          and T.HIST_OUTLINE_W == OFFICIAL_DATA_TABLE["outline-width"]
          and T.SEMANTIC["border"] == OFFICIAL_DATA_TABLE["row-item-outline-color"]
          # 那个角色名在 m3_theme 里只该出现一处（`SEMANTIC` 表里；正文注释里也写着它，所以这里只
          # 查带引号的键值那一处）
          and theme_src.count('"border": "outline_variant"') == 1
          # 视图层真把这五条挂到 `ft.DataTable` 上了（这几串在 flet_gui 里各只出现一次）
          and "heading_row_height=T.HIST_HEAD_H" in gui
          and "heading_text_style=T.type_style(T.HIST_HEAD_FONT)" in gui
          and "data_text_style=T.type_style(T.HIST_CELL_FONT)" in gui
          and "divider_thickness=T.HIST_OUTLINE_W" in gui
          and "horizontal_lines=ft.BorderSide(T.HIST_OUTLINE_W, self.tk.border)" in gui
          and "border=ft.Border(" in gui
          # 列宽换算得真按字号放大（70 → 84、170 → 204 是 `hist_width` 的两端；`HIST_WIDTHS` 是
          # `[CHIP_W] + 各列` 的列表，所以取「歌曲」那一格要拿 1 基列号）
          and T.hist_width(70) == 84 and T.hist_width(170) == 204
          and T.hist_width(170) > core.HIST_WIDTHS[core.HIST_COLS.index("song") + 1]
          and T.DBLCLICK_S == 0.5
          # 实拍也同意（history_dark.png：表头顶边到下边 85 px、行分隔线间距恒 78 px，DPR 1.5）
          and abs(MEASURED_SETTINGS["hist-head-height"]
                  - OFFICIAL_DATA_TABLE["header-container-height"]) <= 1.5
          and abs(MEASURED_SETTINGS["hist-row-pitch"]
                  - OFFICIAL_DATA_TABLE["row-item-container-height"]) <= 1.5,
          "表头 %s / 行 %s / %s+%s（各 %s）/ 线 %s / 歌曲列 %s→%s / 实拍 %s+%s"
          % (T.HIST_HEAD_H, T.HIST_ROW_H, T.HIST_HEAD_FONT, T.HIST_CELL_FONT,
             T.type_style(T.HIST_HEAD_FONT).size, T.HIST_OUTLINE_W,
             core.HIST_WIDTHS[core.HIST_COLS.index("song") + 1], T.hist_width(170),
             MEASURED_SETTINGS["hist-head-height"], MEASURED_SETTINGS["hist-row-pitch"]))

    # ⑯ 悬停态层（J）与表头底色（K）—— m12800 补的两条官方 token。两条都落在「一个平色」上：
    #    `DataRow.color` 一行吃不下半透明色，所以令牌层用 `blend()` 自己把「行底色 + 状态层」
    #    合成熟色（`Tokens.hover_fill`）。视图层再用 `T.HOVER_STATE` 这个开关把整条悬停态摘掉 ——
    #    窗口是在鼠标底下开的，指针只要压在表上那一行就会亮，截图会随鼠标位置变；拍照与探针
    #    路径在建面板**之前**关掉它，真面板照旧挂。
    dark = T.tokens("dark")
    light = T.tokens("light")
    check("PART 10", "结算表悬停态层 = on_surface @ 8%（HOVERED 一档 + DEFAULT 兜底，按官方两条 token）",
          T.STATE_OPACITY["hover"] == OFFICIAL_DATA_TABLE["row-item-hover-state-layer-opacity"]
          and T.SEMANTIC["text"] == OFFICIAL_DATA_TABLE["row-item-hover-state-layer-color"]
          and T.SEMANTIC["page"] == OFFICIAL_DATA_TABLE["header-container-color"]
          and T.HOVER_STATE is True
          # 视图层真把这三样挂上了（顺序也认：HOVERED 在前、DEFAULT 兜底）
          and "heading_row_color=self.tk.surface," in gui
          and "if T.HOVER_STATE:" in gui
          and "ft.ControlState.HOVERED: self.tk.hover_fill(bg or self.tk.surface)" in gui
          and "ft.ControlState.DEFAULT: bg or self.tk.surface" in gui
          # 合成算式：8 位四舍五入。黑盖白 8% = #141414 是纯算式；深浅两套各自的「页面底色 + 悬停」
          # 必须就是 `blend()` 的输出，而且不能等于底色本身（否则悬停看不出来）
          and T.blend("#000000", "#ffffff", 0.08) == "#141414"
          and dark.hover_fill(dark.surface) == T.blend(dark.surface, dark._r["on_surface"], 0.08)
          and light.hover_fill(light.surface) == T.blend(light.surface, light._r["on_surface"], 0.08)
          and dark.hover_fill(dark.surface) != dark.surface
          and light.hover_fill(light.surface) != light.surface,
          "状态层 %s / 官方 %s、深色悬停行 %s（底色 %s）、表头底 %s"
          % (T.STATE_OPACITY["hover"], OFFICIAL_DATA_TABLE["row-item-hover-state-layer-opacity"],
             dark.hover_fill(dark.surface), dark.surface, T.SEMANTIC["page"]))

    # ⑰ 换页 = M3 的 fade-through（`flutter/packages/animations/lib/src/fade_through_transition.dart`）：
    #    旧页先淡出（`short2` + `emphasized_accelerate` = 100 ms），新页再淡入、同时从 0.92 放大回 1
    #    （`short4` + `emphasized_decelerate` = 200 ms）。两拍合计 300 = `medium2`，与从前那一档的
    #    总时长相同；连点页签时靠 `_page_seq` 让在飞的那一次两拍都作废。
    #    2026-10-07（用户 m20852）：卡片进出场也拆成两档 —— 进场 `card` 用 `emphasized_decelerate`、
    #    退场 `card_out` 用 `emphasized_accelerate`（`short4` = 200 ms），照规范「Easing and duration」
    #    表里「进屏幕用 decelerate／离开屏幕用 accelerate」那对；所以 `MOTION` 是 **7 个档位、6 个装置**
    #    （换页那一对本来就是进出两档，卡片这一对是新拆的）。
    check("PART 10", "换页是 M3 fade-through：100 ms 淡出 + 200 ms 从 0.92 淡入（合计 medium2）",
          T.MOTION["page_out"] == ("short2", "emphasized_accelerate")
          and T.MOTION["page"] == ("short4", "emphasized_decelerate")
          and T.MOTION_DURATION[T.MOTION["page_out"][0]] == 100
          and T.MOTION_DURATION[T.MOTION["page"][0]] == 200
          and (T.MOTION_DURATION[T.MOTION["page_out"][0]]
               + T.MOTION_DURATION[T.MOTION["page"][0]]) == T.MOTION_DURATION["medium2"]
          and abs(T.PAGE_SCALE_IN - 0.92) < 1e-9
          and len(T.MOTION) == 7
          and T.MOTION["card"][1] == "emphasized_decelerate"
          and T.MOTION["card_out"][1] == "emphasized_accelerate"
          and T.MOTION_DURATION[T.MOTION["card_out"][0]] <= T.MOTION_DURATION[T.MOTION["card"][0]]
          and 'T.animation("page_out")' in gui
          and "self._body.scale = T.PAGE_SCALE_IN" in gui,
          "page_out %s + page %s = %s ms，起始缩放 %s，卡片进场/退场 %s / %s，共 %d 个档位"
          % (T.MOTION["page_out"], T.MOTION["page"],
             T.MOTION_DURATION[T.MOTION["page_out"][0]] + T.MOTION_DURATION[T.MOTION["page"][0]],
             T.PAGE_SCALE_IN, T.MOTION["card"], T.MOTION["card_out"], len(T.MOTION)))

    # ⑲ 组件主题的**值**（2026-10-06 用户 m16213 第 ⑤-3 条）：`fletgui.py` 第 11 关那条新判据只
    #    保证「值来自令牌或规范标度」，这一条把 17 张主题逐个对着**官方 token** 数一遍。两张官方
    #    导出（材料 web `tokens/versions/v0_192/_md-comp-*.scss`、androidx
    #    `compose/material3/…/tokens/*Tokens.kt`）在下面这些值上逐条相符；两家不一致的两处
    #    （chip 未选中描边色、focus/pressed 状态层不透明度）在对应位置写明跟的是哪一家。
    app = T.theme("dark").appbar_theme
    rail = T.theme("dark").navigation_rail_theme
    cardt = T.theme("dark").card_theme
    dlg = T.theme("dark").dialog_theme
    snack = T.theme("dark").snackbar_theme
    pmenu = T.theme("dark").popup_menu_theme
    dvd = T.theme("dark").divider_theme
    prog = T.theme("dark").progress_indicator_theme
    scr = T.theme("dark").scrollbar_theme
    tip = T.theme("dark").tooltip_theme
    iconb = T.theme("dark").icon_button_theme
    fbtn = T.theme("dark").filled_button_theme
    seg = T.theme("dark").segmented_button_theme
    check("PART 10", "组件主题的值照官方：顶栏 64/level0/titleLarge、导轨 80+256+"
                     "secondary_container、卡片 surface_container_low+level1+12、对话框 "
                     "surface_container_high+level3+28、零食条 inverse_surface+level3+4、菜单 "
                     "surface_container+level2+4+bodyLarge、分隔线 outline_variant+1、进度条 "
                     "primary+secondary_container+4+2、提示条 inverse_surface+4+bodySmall、"
                     "图标按钮 corner-full、按钮 corner-full+labelLarge、分段控件 40+胶囊"
                     "（`shape` 留空）+outline 描边+选中 secondary_container+不画对勾（用户 m20246）",
          app.toolbar_height == 64 and app.elevation == 0
          and app.bgcolor == tk.surface and app.title_text_style.size == 22
          and rail.min_width == 80 and rail.min_extended_width == 256
          and rail.indicator_color == tk.secondary_container and rail.group_alignment == -1.0
          and rail.selected_label_text_style.size == 12
          and cardt.color == tk.card and cardt.elevation == 1 and cardt.shape.radius == 12
          and dlg.bgcolor == tk.dialog and dlg.elevation == 6 and dlg.shape.radius == 28
          and dlg.title_text_style.size == 24 and dlg.content_text_style.size == 14
          and snack.bgcolor == tk.inverse_surface and snack.elevation == 6
          and snack.shape.radius == 4 and snack.content_text_style.size == 14
          and pmenu.color == tk.menu and pmenu.elevation == 3 and pmenu.shape.radius == 4
          # 菜单项的字官方是 body-large（androidx `ListTokens.ItemLabelTextFont`、材料 web
          # menu-item `label-text-font = body-large-font`）：2026-10-06 从 bodyMedium 改回官方。
          and pmenu.label_text_style.size == T.type_style("bodyLarge").size == 16
          and dvd.color == tk.outline_variant and dvd.thickness == 1
          and prog.color == tk.primary and prog.linear_track_color == tk.secondary_container
          and prog.linear_min_height == 4 and prog.border_radius == 2
          # 滚动条**不是 M3 组件**（两套官方导出里都没有）：8/4 跟的是 Flutter `scrollbar.dart`
          # 的 `_kScrollbarThickness = 8.0` / `_kScrollbarRadius = Radius.circular(8.0)`（画在 8dp
          # 宽的条上被夹成 4，与本项目的 `SCROLLBAR_W // 2` 等价）。
          and scr.thickness == T.SCROLLBAR_W == 8 and scr.radius == T.SCROLLBAR_R == 4
          and scr.thumb_color == tk.outline and scr.track_color == tk.page
          and tip.text_style.size == 12 and tip.decoration.bgcolor == tk.inverse_surface
          and tip.decoration.border_radius.top_left == 4
          and isinstance(iconb.style.shape, ft.CircleBorder)
          and isinstance(fbtn.style.shape, ft.StadiumBorder)
          and fbtn.style.text_style.size == T.type_style("labelLarge").size == 14
          # 分段控件（1 级没有这一份，按 3a 记）：整组的胶囊形状由 Flutter 的
          # `itemShape(index, count)` 现画 ⇒ `style.shape` **必须是 None**（给了就四段同形）；
          # 描边 1dp `outline` 两态都留着（官方 `activeBorderColor = inactiveBorderColor =
          # OutlineColor`）、未选中不铺底、选中 `secondary_container` + `on_secondary_container`。
          # 选中对勾**不给**（用户 m20246）：默认那个勾把选中段的文字右推 11.1 dp，长式标签
          # 「EXPERT Lv26」会被省略号截掉；官方对 4~5 段也说可缩短标签或只用图标。
          and seg.style.shape is None and seg.selected_icon is None
          and seg.style.icon_size == T.SEGMENT_ICON == 18
          and seg.style.bgcolor[ft.ControlState.DEFAULT] == ft.Colors.TRANSPARENT
          and seg.style.bgcolor[ft.ControlState.SELECTED] == tk.secondary_container
          and seg.style.color[ft.ControlState.DEFAULT] == tk.text
          and seg.style.color[ft.ControlState.SELECTED] == tk.on_secondary_container
          and seg.style.side[ft.ControlState.DEFAULT].width == T.SEGMENT_BORDER_W == 1
          and seg.style.side[ft.ControlState.DEFAULT].color == tk.outline
          and seg.style.side[ft.ControlState.SELECTED].color == tk.outline
          and seg.style.text_style.size == T.type_style("labelLarge").size == 14,
          "顶栏 %s/%s/%s、导轨 %s+%s、卡片 %s/%s/%s、对话框 %s/%s/%s、零食条 %s/%s/%s、"
          "菜单 %s/%s/%s/%s、线 %s/%s、进度 %s/%s/%s/%s、滚动条 %s/%s、提示 %s/%s/%s、"
          "分段 %s/%s/%s/%s"
          % (app.toolbar_height, app.elevation, app.title_text_style.size,
             rail.min_width, rail.min_extended_width,
             cardt.color, cardt.elevation, cardt.shape.radius,
             dlg.bgcolor, dlg.elevation, dlg.shape.radius,
             snack.bgcolor, snack.elevation, snack.shape.radius,
             pmenu.color, pmenu.elevation, pmenu.shape.radius, pmenu.label_text_style.size,
             dvd.color, dvd.thickness,
             prog.color, prog.linear_track_color, prog.linear_min_height, prog.border_radius,
             scr.thickness, scr.radius,
             tip.text_style.size, tip.decoration.bgcolor, tip.decoration.border_radius.top_left,
             seg.style.icon_size, seg.style.bgcolor[ft.ControlState.SELECTED],
             seg.style.side[ft.ControlState.DEFAULT].color, seg.selected_icon))

    # ⑳ 三个标度表也对着官方数一遍（高程 / 形状 / 状态层）：⑲ 只保证主题对象取到了它们，取错表里
    #    的某一格（例如把 level2 写成 4）在这里才会红。出处见 `m3_theme.py` 那三条注释。
    check("PART 10", "高程 0/1/3/6/8/12、形状 0/4/8/12/16/28、状态层 hover0.08 + focus/pressed0.12 "
                     "+ dragged0.16 + disabled0.38 + disabled_container0.12（两套官方导出逐条核过）",
          T.ELEVATION == {"level0": 0, "level1": 1, "level2": 3, "level3": 6,
                          "level4": 8, "level5": 12}
          and {k: v for k, v in T.SHAPE.items() if k != "full"} == {
              "none": 0, "extraSmall": 4, "small": 8, "medium": 12, "large": 16, "extraLarge": 28}
          and T.SHAPE["full"] > 0
          and T.STATE_OPACITY == {"hover": 0.08, "focus": 0.12, "pressed": 0.12, "dragged": 0.16,
                                  "disabled": 0.38, "disabled_container": 0.12},
          "高程 %s、形状 %s、状态层 %s"
          % (sorted(T.ELEVATION.values()), {k: v for k, v in T.SHAPE.items() if k != "full"},
             T.STATE_OPACITY))

    # ㉑㉒ 依据顺序（`AGENTS.md`「依据顺序」一节）落成的登记表 `docs/m3_sources.md`。这两条**不联网**，
    #    只钉「登记表覆盖了 `tools/gen_m3_sources.py` 里每一份 1 级文件、每份都带 64 位 sha256、
    #    三条链的前缀与 1 级文件头的版本戳都在」；真抓取与哈希由 `python tools/gen_m3_sources.py
    #    --write` 做（改登记表却不重生成，这里就红）。
    doc = _read(GS.DOC)
    web = list(GS.SOURCES_WEB)
    hex64 = re.compile(r"[0-9a-f]{64}")
    missing = [name for name, _tokens in web if name not in doc]
    nohash = [name for name, _tokens in web
              if not any(name in ln and hex64.search(ln) for ln in doc.splitlines())]
    check("PART 10", f"依据登记表覆盖 1 级全部 {len(web)} 份文件、且每份都带 64 位 sha256",
          bool(doc) and not missing and not nohash,
          f"缺 {missing}、无哈希 {nohash}")
    check("PART 10", "登记表里三条链的前缀、1 级文件头的五行版本戳与「只认 versions/ 那层」都在",
          GS.WEB_PREFIX in doc and GS.AND_PREFIX in doc and GS.FLU_PREFIX in doc
          and all(line in doc for line in GS.WEB_HEAD)
          and "versions/" in doc and "适配层" in doc)


# ---------------------------------------------------------------------------
def main():
    for fn in (part1, part2, part3, part4, part5, part6, part7, part8, part9, part10):
        fn()
    print()
    for part in sorted(COUNTS):
        print(f"  {part}: {COUNTS[part]} 条")
    if FAILS:
        print()
        for label in FAILS:
            print(f"  FAIL {label}")
        print(f"\n{len(FAILS)} 条 FAIL（共 {sum(COUNTS.values())} 条判据）")
        return 1
    print(f"\nALL PASS（{sum(COUNTS.values())} 条判据）")
    return 0


if __name__ == "__main__":
    t0 = time.time()
    rc = main()
    print(f"（{time.time() - t0:.1f}s）")
    sys.exit(rc)
