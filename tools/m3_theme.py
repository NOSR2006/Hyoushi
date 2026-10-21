"""Material 3 主题层（Flet 侧）。

这是视图层的**唯一**一处「什么颜色、多大字、多圆、多高」的出处。分三层，各自可以单独测：

  1. **颜色角色** —— 46 个规范角色 + 6 组扩展语义色，全部读 `tools/m3_tokens.json`（冻结表）。
     运行时**不 import material_color_utilities**：那张表是 `tools/gen_m3_tokens.py` 的产物，
     `tools/probes/m3tokens.py` 拿参考实现重算比对。种子 `#3e63dd`（旧 QSS 的强调色），
     方案 TONALSPOT + contrast 0.0 = Flutter `ColorScheme.fromSeed` 的默认档 = 规范基线。

  2. **规范标度** —— 字体阶梯（15 角色）/ 形状（7 档）/ 高程（6 级）/ 状态层（不透明度）/
     间距（4dp 栅格）/ 窗口尺寸类（5 档）。这里的每个数都抄自规范，不是「看着顺眼」挑的；
     `tools/probes/m3tokens.py` 逐条量着它们，免得下一版悄悄换成别的数。

  3. **装配** —— `theme(appearance, font_key)` 交出 `ft.Theme`，`apply(page, ...)` 落到页面上。

为什么要有 `SEMANTIC` 这层：视图层不该写 `role("surface_container_low")`。它说的是「这是卡片
底色」，由这张表决定落到哪个角色上 —— 规范改名、或者以后换一门设计语言，只动这张表。

**偏离规范的地方写在 `DEVIATIONS` 里**，一处一条，附理由。规范是给触摸屏写的，面板是桌面密集
控制台，两者在「行高」上必然打架；打架的地方要留痕，不能悄悄改一个数字了事。

**出处（2026-10-07 重订）**——完整清单（每一份文件的 URL、版本戳、我们引的每一条 token、sha256）
在 `docs/m3_sources.md`，由 `tools/gen_m3_sources.py --write` 抓取生成；**依据顺序与裁决规则在
`AGENTS.md`**（0 级生成器 → 1 级数值权威 → 2 级意图 → 3a androidx / 3b Flutter 旁证 → 4 级 Flet →
5 级本项目）。这里只留摘要：

- **颜色不是记忆**：`tools/gen_m3_tokens.py` 调 **Google 自己的** `material-color-utilities` 现算并
  冻结成 `tools/m3_tokens.json`；`tools/probes/m3tokens.py` PART 1–2 用同一个库重算、逐格比回来。
- **数值权威 = material-web 自动生成的设计系统导出**，且**只认 `versions/` 那一层**（文件头写着
  `Design system display name: Google Material 3` / `Design system version: v0.192`；镜像
  `https://cdn.jsdelivr.net/gh/material-components/material-web@main/tokens/versions/v0_192/`）：
  `_md-comp-list.scss` 的 `list-item-one-line-container-height 56px` / `two-line 72px` /
  `leading-image-* 56px` / `leading-avatar-size 40px`；`_md-comp-switch.scss` 的 `track-width 52px` /
  `track-height 32px` / `state-layer-size 40px`。**同一仓库 `tokens/` 下非 versioned 的文件是 MWC 的
  适配层**（`validate.values(... $new-tokens ...)` 会自己加 token、还会改 token 名），按依据顺序
  **不算依据** —— 从前引过的 `_md-comp-list-item.scss` 的 `top-space`/`bottom-space 12px` 与
  `_md-comp-switch.scss` 的 `touch-target-size 48px` 都出自那一层，已撤；面板那 12 与 48 是
  **本项目决定**（12 落在 4dp 栅格上、48 是触摸面下限），不是官方值。
- **1 级没定义、只有 androidx 给的**（算 3a 补位，用它的地方都要点明）：输入框容器高 56
  （`OutlinedTextFieldTokens.ContainerHeight`；1 级的 `_md-comp-outlined-text-field.scss` 整个文件
  都没有 56）。
- `m3.material.io` 是单页应用、抓不到正文，所以引的是 token 导出。官方内部也有小分歧：它自家
  `docs/components/list.md` 的表里 leading icon 写 18px、行文字体写 label-large，token 导出则是
  24px / body-large —— 面板把 18 当行内小图标用，是站得住的。
"""
import ctypes
import ctypes.wintypes as _wt
import json
import os
import sys

import flet as ft

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKENS_PATH = os.path.join(ROOT, "tools", "m3_tokens.json")


# ============================ 1. 颜色角色 ============================

def load_tokens(path=None):
    """读冻结表。**表不在或坏了就当场炸**，不退回一套内建默认值 —— 一个悄悄生效的备用色板
    会让「按规范生成的颜色」和「实际画出来的颜色」从此对不上，而且没有任何症状。"""
    with open(path or TOKENS_PATH, encoding="utf-8") as f:
        d = json.load(f)
    for key in ("roles", "light", "dark", "ext"):
        if key not in d:
            raise ValueError("m3_tokens.json 缺 %r 这一节" % key)
    return d


TOKENS = load_tokens()
ROLES = tuple(TOKENS["roles"])                              # 46 个规范角色
SCHEMES = {"light": TOKENS["light"], "dark": TOKENS["dark"]}
EXT = {"light": TOKENS["ext"]["light"], "dark": TOKENS["ext"]["dark"]}
EXT_NAMES = ("success", "warning", "easy", "normal", "hard", "expert")

APPEARANCE_CHOICES = ("跟随系统", "浅色", "深色")
APPEARANCE_KEYS = ("auto", "light", "dark")

# 面板的语义 -> M3 角色。左边是「这是干什么用的」，右边是规范里的名字。
SEMANTIC = {
    "page": "surface",
    "card": "surface_container_low",
    "card_high": "surface_container",
    "field": "surface_container_highest",
    "text": "on_surface",
    "text_dim": "on_surface_variant",
    "border": "outline_variant",
    "accent": "primary",
    "on_accent": "on_primary",
    "accent_container": "primary_container",
    "on_accent_container": "on_primary_container",
    "accent_dim": "primary_fixed_dim",
    "danger": "error",
    "on_danger": "on_error",
    "danger_container": "error_container",
    "on_danger_container": "on_error_container",
    "ok": "success",
    "on_ok": "on_success",
    "ok_container": "success_container",
    "on_ok_container": "on_success_container",
    "warn": "warning",
    "on_warn": "on_warning",
    "warn_container": "warning_container",
    "on_warn_container": "on_warning_container",
    # 规范里 tooltip 就是反色面（inverseSurface / onInverseSurface），与旧面板「深色下气泡反色」
    # 的结论同向，所以这一条不用自己发明。**snackbar 用的是同一对角色**（规范给这两个组件的
    # 容器色就是同一个），所以下面另起两个名字指同一对 —— 视图层写 `snack_bg` 比写 `tip_bg`
    # 读得懂，而 token 只有一份。
    "tip_bg": "inverse_surface",
    "tip_fg": "on_inverse_surface",
    "snack_bg": "inverse_surface",
    "snack_fg": "on_inverse_surface",
    # 对话框容器：规范给的是 `surface_container_high`（比卡片高一档，因为它是浮起来的）。
    # 从前这里用 `card_high`（= `surface_container`，与普通卡片同层）。
    "dialog": "surface_container_high",
    "menu": "surface_container",
    "menu_hover": "surface_container_high",
    # 进度条**轨道**：M3 给的是一档角色 —— androidx `LinearProgressIndicator` 的
    # `TrackColor = SecondaryContainer`（活动段 = Primary、停止点 = Primary）。从前这里写
    # `surface_container_highest`（那是早期 Flutter `backgroundColor` 的观感，不是 M3 角色），
    # 实拍轨道 `#34343a` / `#e3e1e9` 对不上官方 `#424659` / `#dee1f9`。
    "trough": "secondary_container",
    "grid": "outline_variant",
    # 结算表里「这一格是 0」与「这一格没读数（占位符 `—`）」共用的弱化字。**不能取 `outline`**
    # —— 那是描边角色（给分隔线与边框用的），拿它写字等于把边框色当文字色，M3 里弱化文字的
    # 角色是 `on_surface_variant`。两种格子的区别由字形承担（`0` vs `—`），不是再找一个更浅的
    # 文字色（2026-10-09 用户 m11595：占位符要与真数分明，但真 0 本来也该弱化）。
    "zero_dim": "on_surface_variant",
    "chip_ap": "primary",
    "chip_fc": "tertiary",
    "chip_np": "success",
    "chip_err": "error",
}

# 难度四色。次序与 `panel_core.DIFF_RANK` / `DIFF_LETTER` 一致（EASY/NORMAL/HARD/EXPERT）。
DIFF_KEYS = ("easy", "normal", "hard", "expert")
DIFF_LETTERS = ("e", "n", "h", "x")


def role(name, appearance="dark"):
    """一个规范角色在当前外观下的 `#rrggbb`。"""
    return SCHEMES[appearance][name]


def color_scheme(appearance="dark"):
    """46 个角色 -> `ft.ColorScheme`。**46 个全给**，一个都不留空：留空的那个由 Flutter 自己
    从种子里生成，于是「表里写的」和「画出来的」就不是同一份东西了。"""
    return ft.ColorScheme(**{r: SCHEMES[appearance][r] for r in ROLES})


class Tokens:
    """一个外观的全部颜色，属性式取。

    取值的次序是「语义名 -> 规范角色 -> 扩展色」，所以 `t.card` 与 `t.surface_container_low`
    都能用；打错一个名字当场 AttributeError，而不是画出一块黑（沿用旧 `Palette` 的取舍）。
    """

    def __init__(self, appearance):
        self.appearance = appearance
        self._r = SCHEMES[appearance]
        self._e = EXT[appearance]

    def __getattr__(self, name):
        # 与旧 `Palette` 同一条防线：`__getattr__` 只在常规查找失败时被调用，而 `self._r` 是在
        # `__init__` 里设的 —— 它一旦缺失（`__new__` 造对象、`__init__` 半途抛错），
        # `self._r` 会再触发一次 `__getattr__("_r")`，无限递归报 RecursionError。
        if name.startswith("_"):
            raise AttributeError(name)
        key = SEMANTIC.get(name, name)
        if key in self._r:
            return self._r[key]
        if key in self._e:
            return self._e[key]
        raise AttributeError(name)

    # 难度四色：0..3 或字母 e/n/h/x 都能取
    def diff(self, i):
        return self._e[DIFF_KEYS[i % len(DIFF_KEYS)]]

    def diff_container(self, i):
        return self._e[DIFF_KEYS[i % len(DIFF_KEYS)] + "_container"]

    def diff_on_container(self, i):
        return self._e["on_" + DIFF_KEYS[i % len(DIFF_KEYS)] + "_container"]

    def diff_letter(self, letter):
        """按 `e/n/h/x` 取难度的**强调色** —— 给字用的，不铺底。

        结算表从前把整行铺成难度的容器色（`X_container` ↔ `X_container_dim` 走斑马线，用户
        看到的就是满屏红/蓝/绿的横条），这条路径已被用户要求去掉（原话：「把这些列表项背景色
        去了吧」）。去掉底色之后难度只剩「难度」这一格的字色，选中与「刚结算」改用官方数据表的
        `row-item-selected-container-color = surface_container_highest`（2026-10-06 起；
        从前是本项目自己拿 `secondary_container` 顶的，那条偏离已从 `DEVIATIONS` 撤掉）——
        于是 `hist_bg`/`hist_sel`/`hist_sel_ink` 三个 helper 一起删掉了，这里是取代它们的那一个。
        """
        if letter not in DIFF_LETTERS:
            return self._r["on_surface_variant"]
        return self._e[DIFF_KEYS[DIFF_LETTERS.index(letter)]]

    # 状态层：规范说交互态是「在控件本色上盖一层 on_ 色，透明度按状态取」
    def state(self, color, kind="hover"):
        return ft.Colors.with_opacity(STATE_OPACITY[kind], color)

    def hover_fill(self, base):
        """一行底色 `base` 在**悬停**下的那个平色（规范：盖一层 `on_surface` @ 8%）。

        官方数据表只有 hover 这一档状态层：`row-item-unselected-hover-state-layer-color =
        on-surface`、`row-item-selected-hover-state-layer-color = on-surface`，两条的 opacity 都是
        `md-sys-state.hover-state-layer-opacity`（= 本项目 `STATE_OPACITY["hover"]` 那 0.08）；
        没有 pressed/focus 的行状态层。行底色可能是 `surface`（未选中）或
        `surface_container_highest`（选中 / 刚结算，官方 `row-item-selected-container-color`），
        所以合成得按底色现算 —— 两个色都由调用方给。
        """
        return blend(base, self._r["on_surface"], STATE_OPACITY["hover"])

    def disabled(self, color):
        return ft.Colors.with_opacity(STATE_OPACITY["disabled"], color)

    def chip_side(self, on):
        """filter chip 的描边：未选中 `outline_variant` 1dp、选中**透明**。

        官方 `_FilterChipDefaultsM3.side`（`ft.Chip` 在 Flutter 侧就是 `FilterChip`）在 flat
        变体下：未选中给 `outlineVariant`，选中给 `Colors.transparent` —— `FilterChipTokens.kt`
        里也只有 `FlatUnselectedOutlineColor` 一条，没有「选中态描边」。`ft.Chip.border_side` 只吃
        **一个** `BorderSide`（不是按状态分档的值），所以建的时候与 `paint_chip` 刷的时候必须说同
        一句话，统一走这里；选中给「透明 1dp」而不是 `None`，是为了描边占位不变、只有颜色隐掉，
        布局不动。这句话留在令牌层，是因为视图层不许出现 `ft.Colors`。
        """
        return ft.BorderSide(1, ft.Colors.TRANSPARENT if on else self.outline_variant)


# ============================ 2. 规范标度 ============================

# 字体阶梯：15 个角色，值 = (字号 px, 行高 px, 字重, 字距 px)。**抄自规范手册**。
TYPES = {
    "displayLarge": (57, 64, 400, -0.25),
    "displayMedium": (45, 52, 400, 0.0),
    "displaySmall": (36, 44, 400, 0.0),
    "headlineLarge": (32, 40, 400, 0.0),
    "headlineMedium": (28, 36, 400, 0.0),
    "headlineSmall": (24, 32, 400, 0.0),
    "titleLarge": (22, 28, 400, 0.0),
    "titleMedium": (16, 24, 500, 0.15),
    "titleSmall": (14, 20, 500, 0.1),
    "bodyLarge": (16, 24, 400, 0.5),
    "bodyMedium": (14, 20, 400, 0.25),
    "bodySmall": (12, 16, 400, 0.4),
    "labelLarge": (14, 20, 500, 0.1),
    "labelMedium": (12, 16, 500, 0.5),
    "labelSmall": (11, 16, 500, 0.5),
}
TYPE_ORDER = tuple(TYPES)

# 旧面板那四档字号 -> 规范角色。视图层搬迁时按这张桥走，于是「原来的 9pt 正文」在规范里
# 就是 bodySmall(12/16)。`t` 原来是 12pt 的区块标题，规范里对应 titleMedium(16/24)。
FONT_ROLE = {"s": "labelSmall", "n": "bodySmall", "b": "labelLarge", "t": "titleMedium"}

# 形状：规范给 7 档（full 是胶囊，不写 999 而写它自己的名字）。
# 出处（两套官方导出逐条相符）：material-web `tokens/versions/v0_192/_md-sys-shape.scss` 的
# `corner-none 0 / corner-extra-small 4 / corner-small 8 / corner-medium 12 / corner-large 16 /
# corner-extra-large 28 / corner-full 9999`；androidx `ShapeTokens.kt` 同值（`CornerFull =
# CircleShape`、`CornerNone = RectangleShape`）。这里的 `full` 收成 999 是
# Flet 的圆角哨兵（大于任何一边的半径即全圆），不是规范数。
SHAPE = {"none": 0, "extraSmall": 4, "small": 8, "medium": 12, "large": 16,
         "extraLarge": 28, "full": 999}

# 各组件的形状归属（规范手册里逐个组件写明的）。视图层说「这是个卡片」，不说 12。
# 已逐文件核过的：app bar `container-shape = corner-none`、elevated card `corner-medium`、
# dialog `corner-extra-large`、chip `corner-small`（androidx `FilterChipTokens.ContainerShape`）、
# menu `corner-extra-small`、plain tooltip / snackbar `corner-extra-small`、icon button
# `state-layer-shape = corner-full`（androidx `SmallIconButtonTokens.ContainerShapeRound`，本表
# 归在 `button` 那一档）、导航轨指示条同为 full（androidx
# `NavigationRailBaselineItemTokens.ActiveIndicatorShape`）。`field`(4) / `list`(不裁) /
# `sheet`(16) 三条是按手册组件页归纳的，不入判据。
SHAPE_ROLE = {
    "button": "full", "card": "medium", "dialog": "extraLarge", "field": "extraSmall",
    "chip": "small", "menu": "extraSmall", "tooltip": "extraSmall", "snackbar": "extraSmall",
    "nav_indicator": "full", "list": "none", "sheet": "large",
}

# 高程：6 级（规范按 dp 给）。Flet 里只有一部分控件收 `elevation`。
# 出处：material-web `_md-sys-elevation.scss` 与 androidx `ElevationTokens.kt` 逐条相同
# （level0 0 / level1 1 / level2 3 / level3 6 / level4 8 / level5 12）。`theme()` 里用到四处，
# 都是官方组件表点名的同一档：app bar `level0`、elevated card `level1`、menu `level2`、
# dialog 与 snackbar `level3`。
ELEVATION = {"level0": 0, "level1": 1, "level2": 3, "level3": 6, "level4": 8, "level5": 12}

# 输入框（outlined text field / 下拉）的容器高：`OutlinedTextFieldTokens.ContainerHeight
# = 56.0`，规格表逐字写 `Container height 56dp`。注意 Flet 的 `height` **只改布局槽位**，
# 真正画出来的盒子高 = 文字行高 + 上下各 16 内边距，所以让盒子落到官方 56 的是字取
# `InputFont = BodyLarge`（行高 24：24 + 32 = 56；实拍 57.4 是 1.35 的描边反锯齿）；字若
# 换回 `bodyMedium`（行高 20）就只有 52（实拍 53.3）。这里显式钉 56，是让布局槽位与画出来
# 的盒子对齐。`dense` 是 Flutter 收内边距的开关，会把 56 压到 48（M2 的旧档），一律不写。
FIELD_H = 56

# 线性进度指示器：规范给的轨道高是 4dp（面板页脚那根进度条用它，不写 6 这种随手值）。
PROGRESS_H = 4
# 它的圆角是**胶囊**（规范里这条轨道就是 `StadiumBorder`，两端半圆）—— 半径恒等于条高的一半。
# 2 不在 SHAPE 那七档上：那是 SHAPE 表的适用范围问题（那七档是给卡片/对话框这种块状组件
# 用的），不是这里该凑一个 4。视图层从前写 `T.PROGRESS_H // 2` 自己做算术，现在算术收在
# 这里 —— 探针要能说「这个半径来自规范的那条定义」，而不是「某个看着顺眼的数字」。
PROGRESS_R = PROGRESS_H // 2

# 结算表的两条行高。官方的数据表令牌（material-web `tokens/versions/v0_192/
# _md-comp-data-table.scss`）给的是表头 56（`header-container-height`）、行 52
# （`row-item-container-height`）。从前这里取的是 4dp 栅格上的 36 / 28（「桌面密度」，还记在
# `DEVIATIONS` 里）；用户 m12075 那轮定了「完全参照 M3 官方设计」，就照抄成官方的 56 / 52 ——
# 一屏从三十来行降到十来行，是「贴合官方」的代价，不是遗漏（「显示条数」那档下拉还在，按它截行）。
HIST_HEAD_H = 56
HIST_ROW_H = 52

# 结算表的列宽预算。用户 m12075：「表单宽度应与窗口宽度保持同步，目前在小窗口下表单超出宽度
# 显示」—— 这张表从前是 13 个定宽列（`core.HIST_WIDTHS` 合计 749）+ 12 的列间距，自然宽 **1176**：
# 默认 1280×800 窗的内容区只有 1032 ⇒ 右边「分数」整列被裁在视口外；800 宽那档更只剩 673。
# 现在列集与列宽都按窗口宽现算（`Panel._hist_layout`）。
#
# `HIST_ARROW_W` = Flutter `DataTable` 给**每个可排序列**预留的那一格排序箭头。实测反推：拿 1280
# 窗实拍的 11 个相邻表头左沿之差，减去「列宽 + 列距 12」，11 个残差均值 **18.0**、最大偏 2.7 逻辑
# px（第 0 列是色条、没有 `on_sort`，不多这一格）。按 18 摆下整张表，13 列表头左沿全部对得上实拍
# （`时间` 244 / `歌曲` 344 / `难度` 544 / … / `分数` 1275，最大偏 3.3）。预留归预留：`sort_column_index`
# 不设就一个箭头都不画，那 18 px 从前一直白占着（观感上的另一个洞，一起补了）。
HIST_ARROW_W = 18
# 必留的五列，以及宽裕时按这个顺序加进去的列（加不下的不画；要丢就先丢排在后面的）。余量全给
# 「歌曲」列 —— 13 列里只有它该长，也只有它会被省略号截。
HIST_FIT_ALWAYS = ("time", "song", "diff", "badge", "score")
HIST_FIT_ORDER = ("np", "P", "combo", "reopen", "G", "GD", "B", "M")

# 结算表的字。官方同一份令牌给 `header-headline = title-small`(14)、`row-item-label-text =
# body-medium`(14)；从前表头与格子都走 labelSmall(11)，这一轮抬到官方那两档。两档都不在面板自己的
# 四档 `FONT_ROLE` 里，所以按规范里的**角色名**直接取（`txt()` 认得角色名，见它的 docstring）。
HIST_HEAD_FONT = "titleSmall"
HIST_CELL_FONT = "bodyMedium"
# 列宽跟着字号走。`panel_core.HIST_WIDTHS` 是按 9pt 量出来的「文字宽 + 8 留白」；字号抬到 14 后文字
# 本该同比放大 14/11 = 1.27，但最窄那档窗口（800 窗 ⇒ 客户端 785.33 ⇒ 可用宽 673.33）只给必留的
# 五列留得下 1.2 倍。9pt 那个量法本来就留了 20% 余量（11pt 渲染到今没出现过省略号），1.2 之后每列
# 仍有 6 dp 以上余量，所以取 1.2、向上凑 4dp 栅格 —— 再宽就丢列（`HIST_FIT_*`），不改这个数。
HIST_PAD_W = 8
HIST_FONT_SCALE = 1.2
HIST_WIDTH_STEP = 4


def hist_width(w):
    """把 `panel_core.HIST_WIDTHS` 的 9pt 列宽抬到官方字号那一档（留白不跟着放大，向上凑 4 的倍数）。

    「字号变了列宽跟着变」这条换算只有一个出处：视图层 `Panel._hist_layout` 只调这一个函数，
    探针也就只钉这一处（`fletpanel.py` 第 1 关拿 `_hist_w` 与实拍对）。
    """
    text = max(0.0, float(w) - HIST_PAD_W) * HIST_FONT_SCALE
    want = text + HIST_PAD_W
    n = int(want)
    if n < want:
        n += 1
    return -(-n // HIST_WIDTH_STEP) * HIST_WIDTH_STEP


# 官方外框与行分隔线的宽度：`outline-width = 1px`、`row-item-outline-width = 1px`（同一份令牌里
# `row-item-outline-color = outline-variant` 正是本项目的 `tk.border`）。外框那 1 px 落在数据表
# 自己的 `horizontal_margin`(8) 里，所以列宽预算（`Panel._hist_demand`）不用加它。
HIST_OUTLINE_W = 1
# 双击的判定窗口。M3 规范不管指针双击（那是平台约定），取 Windows 默认的 500 ms —— 写在这里是
# 为了让「双击结算行 = 打开这一局的截图」这条交互有一个探针钉得住的出处。
DBLCLICK_S = 0.5

# 导航轨（M3 navigation rail）：两档宽度都取官方默认（Flutter `_NavigationRailDefaultsM3` 的
# minWidth = 80、minExtendedWidth = 256；material-web `_md-comp-navigation-rail.scss` 里
# `container-width` 也是 80 —— 两家一致）。
# 2026-10-06 从 200 改回官方（那两个数从前是视图层里的裸数字 88 / 200）。
# 2026-10-07 用户 m18525 定「导轨永远收起」：视图层不再 `extended`，屏幕上只会出现 80 那一档；
# 256 仍绑在主题层（令牌绑定，不是活配置），理由与判据见 `DEVIATIONS` 最后一条。
NAV_MIN_W = 80
NAV_MIN_EXT_W = 256

# 图标尺寸：规范给三档（24 是标准、20 用在密集处、18 给行内小图标），本项目只用 18 / 24 两档 ——
# 20 那一档一处落点都没有（2026-10-10 清死代码时删掉 `ICON_MD`）。视图层从前写 16 / 20 这种随手值
# —— `tools/probes/fletgui.py` 第 3 关把 `icon_size=` 算作「必须来自 token」的实参。
ICON_SM = 18
ICON_LG = 24

# 空态那个大图标（规范没有这一档：空态不是标准组件，取 4dp 栅格上的一档）、列表行首的头像位
# （M3 list 的 leading 就是 40dp）、页脚那盏状态灯。
EMPTY_ICON = 40
AVATAR = 40
DOT = 8

# 空态图标底下那枚圆盘的直径。M3 同样没有这一档（空态不是组件）：一个线框图标浮在卡片上既没有
# 重量、也与页面上别处的「有色容器」不是一个语汇，所以给它一枚 `secondary_container` 的底，
# 图标色跟着换成官方配对的 `on_secondary_container`（同 chip 选中态）。64 = 40 的图标 + 两侧各 12。
EMPTY_BADGE = 64

# 日志控制台里时间戳那一栏的宽。8 位等宽数字（bodySmall / Cascadia Mono）实测墨迹 57.6dp，行上
# 还带一个尾随空格（7.2dp）⇒ 64.8dp；给 68 才不会把最后一位挤掉（见 `Panel._log_line`）。
LOG_TS_W = 68

# 桌面滚动条：粗 8、两端圆。**M3 没有滚动条组件**（material-web 的组件 token 里没有它、
# androidx 也没有 ScrollbarTokens）—— 这两个数跟的是 Flutter 的 Material 默认：
# `packages/flutter/lib/src/material/scrollbar.dart` 的 `_kScrollbarThickness = 8.0`、
# `_kScrollbarRadius = Radius.circular(8.0)`（画在 8dp 宽的条上会被夹成 4，与这里的
# `SCROLLBAR_W // 2` 视觉等价）、`_kScrollbarThicknessWithTrack = 12.0`、
# `_kScrollbarMargin = 2.0`、`_kScrollbarMinLength = 48.0`。别写成「M3 规范规定 8dp」。
# 拇指**什么时候露面**不在这里定：视图层一律走 `flet_gui.scroll_when_needed()`
# （`ft.Scrollbar(thumb_visibility=False)`）。2026-10-10 用户 m14308 报过「滚动条怎么常显的，
# 太丑了」—— 根因是 `ScrollMode.ADAPTIVE` 在 Flet 里映射成
# `thumb_visibility=page.web or not page.platform.is_mobile()`，桌面恒 True。
SCROLLBAR_W = 8
SCROLLBAR_R = SCROLLBAR_W // 2

# M3 顶部应用栏（top app bar）高 64dp：material-web `_md-comp-top-app-bar-small.scss` 的
# `container-height = 64px`，androidx `AppBarSmallTokens.ContainerHeight = 64.0dp`。同一对官方表
# 还点明 `container-color = surface`、`container-elevation = level0`、`headline-font = title-large`
# （androidx 放在 `AppBarTokens.kt`：`ContainerColor = Surface`、`ContainerElevation = Level0`、
# `TitleColor = OnSurface`）。面板从前是自制 `ft.Container` 当栏 —— 高度随内容走，于是它比任何
# 一张卡片都矮却顶着标题的位置。
APPBAR_H = 64

# M3 分段控件（segmented button）的三个几何值。1 级（material-web `tokens/versions/v0_192/`）
# **没有**分段控件的组件 token（`_md-comp-segmented-button*.scss` 两份都 404）⇒ 这条按 3a 记：
# androidx `tokens/OutlinedSegmentedButtonTokens.kt`（文件头 `// VERSION: v0_162`）的
# `ContainerHeight = 40.0.dp`、`IconSize = 18.0.dp`、`OutlineWidth = 1.0.dp`；
# 形状 `CornerFull`（整组一个胶囊：Flutter 的 `SegmentedButton` 按 `itemShape(index, count)`
# 把首尾两段画成半圆、中间段画成直角 ⇒ 样式里**不给 `shape`**，给了就四段同形）、
# `OutlineColor = Outline`、`SelectedContainerColor = SecondaryContainer`、
# `SelectedLabelTextColor = OnSecondaryContainer`、`UnselectedLabelTextColor = OnSurface`、
# `LabelTextFont = LabelLarge`；`SegmentedButton.kt:548-572` 的默认配色里**选中段也留着 1dp
# `outline` 描边**、未选中段 `Color.Transparent` 不铺底。视图层见 `flet_gui.py::diff_seg`。
SEGMENT_H = 40
SEGMENT_ICON = 18
SEGMENT_BORDER_W = 1

# 最小命中目标（**可点**区域，不是可视高）。出处是 **2 级** m3.material.io 的
# 「Touch and pointer target sizes」那一节，逐字：「For most platforms, consider making touch
# targets at least 48 x 48dp. A touch target this size results in a physical size of about 9mm,
# regardless of screen size. The recommended target size for touchscreen elements is 7-10mm.」
# 以及「Pointer targets are similar to touch targets, but are implemented by motion-tracking
# pointer devices such as a mouse or a stylus. Consider making pointer targets minimums 44 x 44dp.」
# —— 两条都是 consider（建议）：触屏 48、鼠标/笔 44。1 级与 3a 的 token 表里**没有**这一条
# （48 只出现在 MWC 适配层，按依据顺序不算依据）⇒ 数听 2 级，取更严的 **48**（也盖住鼠标那档）。
#
# 面板里可视高 40 的真按钮（动作区四个 + 难度分段控件）按这一档补：官方那 8 个逻辑像素的余量
# 本来由框架的 `MaterialTapTargetSize` 补 —— `button_style_button.dart:578-589` 的 `padded`
# 档把按钮包进 `_InputPadding(minSize: kMinInteractiveDimension=48)`、`shrinkWrap` 档给
# `Size.zero`，而 `theme_data.dart:400-409` 只在 android/fuchsia/iOS 选 `padded`、
# linux/macOS/windows 选 `shrinkWrap` ⇒ 面板跑在 Windows，那 8 个像素不存在（`ft.Theme` 也没有
# `materialTapTargetSize` 可写，Flet 整包 grep `tap_target` 零命中）。所以**自己补**：可视仍是
# 40，上下各垫一条 `(HIT_MIN - 40) / 2 = 4` 逻辑高的**隐形**可点带（`flet_gui.hit48`）。
# 用户 m20246 当初定：只补条目点名的那两处（动作区四按钮 + 难度分段控件），chip / 图标按钮 /
# 开关先只记着、不动。**2026-10-09 用户 m11996 的 M3 审查之后这句已作废**：全库不再有裸着放的
# chip / 图标按钮 / 开关 —— chip 两排筛选（运行日志 + 结算表）用 `hit_pad(b, pad_x=0,
# pad_y=HIT_PAD_CHIP)`（可视 32、上下各 8）、五颗 `ft.IconButton`（帮助 / 排序方向 / 回顶 /
# 两个清空）与全部开关（多人三枚 + 单人六枚 + 设置页四枚 + 运行日志那枚，`hit_switch`）都套了。
# 视图层逐处核对过（判据在 `tools/probes/fletgui.py`，`tools/probes/fletpanel.py` 控制组盯着）。
#
# 实测（2026-10-07，合成真鼠标点击；脚本 `%TEMP%\bang_hitband_test.py` 是一次性的、不入库 ——
# 它会动真实鼠标，所以只把结论留在这里）：动作区那一格可点 **72 物理 px ≈ 49.7 dp**
# （4 + 40 + 4 整条都吃点击），同一颗按钮裸着放只有 **60 px ≈ 41.4 dp**（就是它自己的 40）
# ⇒ 两条隐形带净增 8 dp 可点区；难度那条壳的可点跨度 **60→130 物理 px ≈ 48.4 dp**，
# 上带逐格命中且下标正确。
# 已知限制：`ft.SegmentedButton` 自己的命中区只有约 30 dp（40 dp 盒子里底部约 5 dp 不吃点击；
# 不套带时也一样 ⇒ 是 Flutter 自己的行为，不是这两条带造成的）。
HIT_MIN = 48

# 状态层：规范按状态给不透明度（不是 0.5 这种随手值）。
# 出处（按依据顺序，用户 m19222 定）：四条都跟 **1 级** material-web `_md-sys-state.scss`
# 的 `hover/focus/pressed/dragged-state-layer-opacity`（0.08 / 0.12 / 0.12 / 0.16）；
# `disabled 0.38` 与 `disabled_container 0.12` 出自 1 级 `_md-comp-filled-icon-button.scss`
# 的 `disabled-icon-opacity` / `disabled-container-opacity`。
# **分歧记录**：3a 的 androidx `StateTokens.kt` 写 focus/pressed 各 0.1 —— 与 1 级不符，
# 按依据顺序不采（面板不渲染 focus/pressed，这两个值只影响注释口径）。
STATE_OPACITY = {"hover": 0.08, "focus": 0.12, "pressed": 0.12, "dragged": 0.16,
                 "disabled": 0.38, "disabled_container": 0.12}

# 悬停态层的「画不画」开关。面板里唯一的悬停态是结算表的行（`DataRow.color` 的 HOVERED 那格）：
# 窗口是在鼠标底下开的，指针只要正好压在表上那一行就会亮起来 ⇒ **截图会随鼠标位置变**
# （tooltip 那次 534×38 的反色方块是同一条机理，`_flet_smoke.strip_tooltips` 已按同一个理由摘掉
# 整棵控件树的 tooltip）。拍照与探针两条路径在建面板**之前**把它置 False，基线里就一行悬停都没有；
# 真面板照旧挂悬停态。视图层只读它，不改它。
HOVER_STATE = True


def blend(base, top, alpha):
    """把 `alpha` 不透明的 `top` 压到 `base` 上，返回 `#rrggbb`（两个入参都是 `#rrggbb`）。

    为什么要有这一条：`DataRow.color` 一行只吃**一个**平色，而规范说的悬停是「在行底色上盖一层
    `on_` 色」—— 客户端不会替我们合（`T.state()` 给的是半透明色，那是给 Flutter 自己会叠状态层的
    控件用的）。取整按四舍五入到 8 位；与 Flutter `Color.alphaBlend`（`ft.Colors.with_opacity` 那条
    路）在 8 位土上最多差 1，颜色角色就那么几个、每一处都写在探针的断言里。
    """
    a = max(0.0, min(1.0, float(alpha)))
    out = []
    for i in (1, 3, 5):
        b = int(base[i:i + 2], 16)
        t = int(top[i:i + 2], 16)
        out.append(int(round(b * (1.0 - a) + t * a)))
    return "#%02x%02x%02x" % tuple(out)

# 间距：规范只规定「4dp 栅格」，没给命名阶梯 —— 所以这张表是**我们的**梯子，但它站在栅格上，
# 而且名字而不是序号（`SPACE["md"]` 说的是「中等间隔」，`SPACE[3]` 不是）。
SPACE = {"none": 0, "xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}

# 动效：规范给两套令牌 —— 时长（short/medium/long/extended 各 4 档，毫秒）与缓动（emphasized/
# standard 各三档 + linear）。整张表都抄下来，理由和 46 个颜色角色一样：探针要能说「我们动的
# 那一处就是规范的这一档」，而不是「某个看着顺眼的数字」。面板真正用到几档见 `MOTION`。
MOTION_DURATION = {
    "short1": 50, "short2": 100, "short3": 150, "short4": 200,
    "medium1": 250, "medium2": 300, "medium3": 350, "medium4": 400,
    "long1": 450, "long2": 500, "long3": 550, "long4": 600,
    "extended1": 700, "extended2": 800, "extended3": 900, "extended4": 1000,
}

# 规范给的是 cubic-bezier。Flet 只暴露 Flutter 的**命名**曲线，逐点相等的只有 emphasized
# （`Curves.easeInOutCubicEmphasized` 就是 (0.2, 0, 0, 1)）—— 其余档取枚举里最接近的一条，
# 这条近似记在 `DEVIATIONS` 里，不假装逐点相等。
MOTION_EASING = {
    "emphasized": ft.AnimationCurve.EASE_IN_OUT_CUBIC_EMPHASIZED,
    "emphasized_decelerate": ft.AnimationCurve.EASE_OUT_CUBIC,
    "emphasized_accelerate": ft.AnimationCurve.EASE_IN_CUBIC,
    "standard": ft.AnimationCurve.EASE_IN_OUT,
    "standard_decelerate": ft.AnimationCurve.EASE_OUT,
    "standard_accelerate": ft.AnimationCurve.EASE_IN,
    "linear": ft.AnimationCurve.LINEAR,
}

# 面板真正动起来的六处，各自取规范的哪一档。这六处就是「过渡动画」开关管的全部东西：
# `tools/probes/fletgui.py` 的 PART 9 量规格（档位名、时长、缓动都对得上规范），
# `tools/probes/fletpanel.py` 第 1 关量它在真控件树上的行为（换页三拍 + 淡表三条路径）。
# `page` 与 `page_out` 是**同一次换页的两拍**（M3 的 fade-through：旧页先淡出、新页再淡入并放大，
# 见 `PAGE_SCALE_IN`）—— 两拍合计 100 + 200 = 300 = `medium2`，与从前那一档的总时长相同。
#
# 进场／退场按规范那**一对**缓动取：进场的用 decelerate、退场的用 accelerate
# （m3.material.io「Easing and duration」那张表逐行是：emphasized 500 ms「begin and end on screen」、
# emphasized decelerate 400 ms「enter the screen」、emphasized accelerate 200 ms「exit the screen」）。
# 所以「卡片进出场」这一处分两档：进场 `card`（250 ms decelerate）、退场 `card_out`
# （200 ms = `short4` accelerate）—— 从前两条退场借的是进场那一档，淡出是「慢慢停下」而不是
# 「加速离开」，与规范那一对是反的。
MOTION = {
    "page_out": ("short2", "emphasized_accelerate"),   # 100 ms：换页第一拍，旧页淡出（30%）
    "page": ("short4", "emphasized_decelerate"),       # 200 ms：换页第二拍，新页淡入并放大（70%）
    "progress": ("short4", "emphasized_decelerate"),   # 200 ms：进度跳变变连续
    "phase": ("short3", "standard_decelerate"),        # 150 ms：状态行那句话变了
    "flash": ("extended1", "linear"),                  # 700 ms：新结算行强调（长度照旧版没变）
    "card": ("medium1", "emphasized_decelerate"),       # 250 ms：摘要卡与空态出现时淡入
    "card_out": ("short4", "emphasized_accelerate"),    # 200 ms：摘要卡与「最近」卡退场（加速离开）
}

# M3 的 fade-through（`flutter/packages/animations/lib/src/fade_through_transition.dart`，
# Google 自家实现）给新页的起始缩放。官方原话：「the outgoing page fades out, then the incoming page
# fades in and scale up… Scale is only applied to incoming elements to emphasize new content over old.」
# 具体是 `_scaleIn` 前 30%（6/20）恒 0.92、之后 0.92 → 1.0；`_inCurve = Cubic(0.0, 0.0, 0.2, 1.0)`
# （= emphasized decelerate）、`_outCurve = Cubic(0.4, 0.0, 1.0, 1.0)`（= emphasized accelerate）——
# 正是 `MOTION` 里那两拍的缓动。缩放**只给新页**，旧页只淡出。
PAGE_SCALE_IN = 0.92

# 进度条是 0..1。小于 3% 的跳变不值得动画：一局里进度事件很密，每条都插一段动画会让指针
# 永远追不上真实值，看起来反而是「卡」。
MOTION_MIN_PROGRESS = 0.03


def motion_ms(name):
    """`MOTION` 里那一处的时长（毫秒）—— 规范令牌的取值，不是一个数字。"""
    return MOTION_DURATION[MOTION[name][0]]


def motion_curve(name):
    return MOTION_EASING[MOTION[name][1]]


def animation(name):
    """给 Flet 的隐式动画用（`animate_opacity=T.animation("page")` 这样）。"""
    return ft.Animation(duration=motion_ms(name), curve=motion_curve(name))

# 窗口尺寸类：规范按窗口宽度分 5 档（compact 0-599 / medium 600-839 / expanded 840-1199 /
# large 1200-1599 / extraLarge 1600-）。这里**只留说明、没有代码**：视图层对窗口宽做的唯一一次
# 分档是 `flet_gui.STACK_W`(992) 那一刀（`_apply_window_class`），2026-10-10 清死代码时把那张
# 表与它唯一的消费者 `window_class()` 一起删了。将来真要做窄窗版式，照上面这五档重建。

# 面板的最小窗口：用户 m09466 定 800x600。800 宽仍在 `STACK_W`(992) 以下 ⇒ 这是最窄那一档的
# 「叠成一栏」版式，该档下「最近」卡整张不显示（页高 600 - 37.33 = 562.67 ⇒ room 为负）；
# 结算表按 `HIST_FIT_*` 丢掉排在后面的几列（内容区只有 673，见那两行的注释）。规范不规定桌面
# 窗口尺寸，与 `WINDOW_DEFAULT` 一样纯粹是版式取舍。
WINDOW_MIN = (800, 600)
# 默认窗 **1280x800**（用户 m09165 点名 16:9，复选时定的高）。页高 = 800 - 37.33 = 762.67，右栏摊得下
# 运行卡（自然高 448）、「最近」卡的标题头（64）**和一行记录**（`_sync_last_cards` 的
# room = 762.67 - 128 - 448 - 8 - 64 = 114.67 ⇒ fit 1）。要两行得把窗口拉到 830 以上（页高 792.67）；
# 矮到 720 那档就一行都放不下（room 34.67 ⇒ 整张卡不显示）。规范不规定桌面窗口尺寸，这里纯粹是页高预算。
WINDOW_DEFAULT = (1280, 800)

# 偏离规范的地方，一处一条。探针会断言这张表非空且每条都有理由 —— 有痕迹才叫「知情偏离」。
DEVIATIONS = (
    ("正文取阶梯下端（两处例外照官方）", "规范的 bodySmall(12)/labelSmall(11) 就是为小屏信息密度"
                                         "准备的，面板正文与列表行内文字都落在 11–16 之间。只有"
                                         "两个位置越过这条线，且都是官方给那两处的档：顶部应用栏"
                                         "标题 titleLarge(22)、对话框标题 headlineSmall(24)；对"
                                         "话框正文 bodyMedium(14) 与两行列表项 bodyLarge(16) 也"
                                         "照官方。"),
    ("缓动取 Flet 枚举里最接近的一条", "规范给的是 cubic-bezier，Flet 只把 Flutter 的**命名**曲线"
                                       "暴露出来，逐点相等的只有 emphasized（easeInOutCubicEmphasized"
                                       " 就是 (0.2,0,0,1)）。其余档在枚举里挑最近的一条；时长一律是"
                                       "规范令牌，一处没有编数字。"),
    ("难度分段控件不画选中对勾（两家参考实现的默认都画）",
     "官方 guidelines 的 Behavior 段逐字：「When using both icons and label text in segmented "
     "buttons, the icon label is replaced by the checkmark icon when the segment is selected.」"
     "—— 那条勾的规则前提是**段里同时有图标和文字**；面板四段是纯文字，规范正文没规定要画勾。"
     "androidx `SegmentedButton(showSelectedIcon = true)` 与 Flutter 的默认都会画，选中段的内容"
     "于是变成「18 的勾 + 8 的间距 + 文字」再整体居中，实测那会把选中段的文字从段中心右推 "
     "**11.1 dp**（`start_dark.png`，DPR 1.4814：选中段文字墨迹中心 118 px、段中心 101.5 px）。"
     "用户 m20246 定撤掉：`flet_gui.diff_seg` 给 `show_selected_icon=False`，文字在选中/未选中时"
     "位置恒定（段上标签也照用户 m20246 放回长式「EXPERT Lv26」—— 撤掉勾之后 112.7 dp 的段内"
     "可用宽装得下）。"),
    ("设置行与运行行的标签是 12 号 on_surface_variant",
     "M3 的列表项把主文字排成 bodyLarge(16) + on_surface；面板的行是密集表单里的「标签 …… 控件」，"
     "标签取 bodySmall(12) + on_surface_variant（弱化一档），与 48 的触摸目标、约 49 的行距一起"
     "把一屏撑满。设置页两张卡、运行卡三行瓦片都是这个行式；粗体/字色都还在 `T.FONT_ROLE` 里，"
     "探针第 3、4 关对着官方字阶与角色表。"),
    ("开关手柄尺寸跟框架走（选中实测约 17，官方选中 24 / 未选 16）",
     "material-web 的 switch 表与 androidx `SwitchTokens.kt` 两份官方导出一致：选中手柄 24、"
     "未选中 16。实测选中态的芯只有 23 px ≈ 16.9 逻辑（量法：开关中心竖切，深色芯 23 px + 两侧"
     "各 1 px 抗锯齿）⇒ Flutter 画的是 16 那一档。`ft.Switch` 没有手柄几何字段（探针第 7 关"
     "断言过），改不了，只能登记；四色倒是能改，已按官方的角色拼法写进 `switch_colors()`。"),
    ("选曲列表行的行内文字取紧凑那两档（12/11），行高完全交给框架",
     "官方两行列表项高 72（`ListTokens`），主文字 bodyLarge(16) + supporting text bodyMedium(14)。"
     "面板一屏要尽量多放歌，行内文字取 bodySmall(12) + labelSmall(11)（同上面「正文取阶梯下端」）；"
     "**行高一行不压**：视图层与主题层都不许再挂框架的密集档或额外的竖向内边距 —— m08726 清了视图层，"
     "主题层那份到 2026-10-06 才清掉（它此前一直把 72 压到约 57）。"),
    ("导航轨永远收起（官方给宽窗的是展开成 256 的「扩展轨」）",
     "官方 token 的 `container-width` 就是 80（material-web `_md-comp-navigation-rail.scss` 与 "
     "Flutter `_NavigationRailDefaultsM3.minWidth` 一致），"
     "Flutter 另给宽窗一个 `extended` 形态（`minExtendedWidth = 256`）。面板在 ≥1200 逻辑宽"
     "（用户窗口实测 1265.33）会命中那一档，但展开轨每行只有 56×32 的胶囊加两个字、右边近 170"
     "逻辑全是空白，内容区还白少 176 逻辑。用户 m18525 定「永远收起」：`extended` 恒 False、"
     "`label_type` 恒 ALL（标签压在图标下），`_hist_avail` 因此只减 `NAV_MIN_W`(80)。判据在 "
     "`fletpanel` 第 10 关（1560 与 760 两个宽度下都必须是收起轨）。"),
    ("运行日志的错误行铺 error 12%（状态层浓度）当静态底色",
     "M3 的静态错误容器角色是 error_container 配 on_error_container；深色下那一档是一整片深红，"
     "铺满控制台宽度会把日志区压死。这里借的是状态层那 12%（`state(danger, \"disabled_container\")`），"
     "文字直接用 error，灰度下也分得出。M3 没有「控制台」这个组件，整页的语汇（surface 凹面、"
     "等宽行、68 的时间戳栏、居中的空态圆盘）都是本项目决定，逐条写在 docs/panel_spec.md 的"
     "「运行日志页」那节里。"),
    ("关键词框只有 placeholder、没有 M3 输入框解剖里的 label",
     "M3 的 filled/outlined 输入框把 label 当常驻件，placeholder 只在聚焦前露一次。运行日志与选曲卡"
     "的搜索框都排在工具栏里、宽度按行分配，挂上常驻 label 会再占一行或把 56 的盒子撑高，所以两处"
     "都只用 hint（色角色 on_surface_variant，主题层 `hint_color` 钉过）。M3 另有 Search bar 组件"
     "（corner-full、surface_container_high、无描边），这里保留 outlined 描边是为了键盘焦点可见"
     "（面板红线：焦点不许消失），也是「就地过滤列表」而不是打开搜索视图。"),
)


def _weight(w):
    return ft.FontWeight.W_400 if w == 400 else ft.FontWeight.W_500


def _snake(name):
    """'displayLarge' -> 'display_large'（`ft.TextTheme` 的字段是蛇形）。"""
    out = []
    for ch in name:
        if ch.isupper():
            out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out)


def type_style(name, family=None, color=None):
    """字体阶梯里的一档 -> `ft.TextStyle`。`height` 在 Flutter 里是**行高/字号的倍数**。

    `family` 缺省时**不写** `font_family`：让这一格跟着 `ft.Theme.font_family` 走。这不是省事 ——
    写死了家族名的 `TextStyle` 会在设置页换字体时原地不动（它已经不再看主题了），
    于是「切到澎湃」只对换完之后新建的控件生效。只有等宽那种**故意不跟着换**的地方
    （日志列对齐）才显式传家族名。

    `color` 是可选的第三项：日志那种「同一档字型、每行不同色」的地方，从前是拿 `TYPES[name][0]`
    自己拼一个 `ft.TextStyle`，于是 `height` / `letter_spacing` / `weight` 全丢了（行高与字距
    都不是规范那一档了）。给颜色走参数，字型仍然整档取。
    """
    size, line, weight, spacing = TYPES[name]
    st = ft.TextStyle(size=size, height=round(line / size, 4), weight=_weight(weight),
                      letter_spacing=spacing)
    if family:
        st.font_family = family
    if color:
        st.color = color
    return st


def text_theme(family=None):
    """15 个角色一次给全，-> `ft.TextTheme`。"""
    fam = family or font_family()
    return ft.TextTheme(**{_snake(k): type_style(k, fam) for k in TYPE_ORDER})


def radius(name="medium"):
    """形状档 -> 半径。传组件名（`radius("card")`）或档名（`radius("medium")`）都认。"""
    return SHAPE[SHAPE_ROLE.get(name, name)]


def border_radius(name="medium"):
    return ft.BorderRadius(radius(name), radius(name), radius(name), radius(name))


def elevation(name="level1"):
    return ELEVATION[name]


# ============================ 3. 字体 ============================

# 与旧面板同名同链。每档给一条**家族链**而不是一个名字，两个理由都还在：
#   1. Windows 把同一族的每个字重注册成各自独立的家族名（「中等」要单独写一个名字）；
#   2. 选中的字体未必装在这台机器上 —— 链里第一个真装了的胜出，一个都没装就退回最后一格，
#      设置页会明说「未安装 X，回退到 Y」。静默换一个字体比看得见的回退更糟。
FONTS = {
    "harmony": {
        "label": "鸿蒙",
        "family": "HarmonyOS Sans SC",
        "medium": "HarmonyOS Sans SC Medium",
        "chain": ("HarmonyOS Sans SC", "Microsoft YaHei UI", "Segoe UI"),
        "chain_medium": ("HarmonyOS Sans SC Medium", "HarmonyOS Sans SC",
                         "Microsoft YaHei UI", "Segoe UI"),
    },
    "misans": {
        "label": "澎湃",
        "family": "MiSans",
        "medium": "MiSans Medium",
        "chain": ("MiSans", "MiSans VF", "MiSans SC", "HarmonyOS Sans SC",
                  "Microsoft YaHei UI", "Segoe UI"),
        "chain_medium": ("MiSans Medium", "MiSans", "HarmonyOS Sans SC Medium",
                         "HarmonyOS Sans SC", "Microsoft YaHei UI", "Segoe UI"),
    },
}
FONT_DEFAULT = "harmony"
FONT_KEYS = tuple(FONTS)                                        # ("harmony", "misans")
FONT_CHOICES = tuple(FONTS[k]["label"] for k in FONT_KEYS)      # ("鸿蒙", "澎湃")
FONT_MONO = "Cascadia Mono"                                     # 等宽不跟着换：日志列对齐靠它

_FAMILY = {}

# ---- GDI 枚举字体家族 ----
#
# Flet 侧没有 QFontDatabase 了，但「未安装 X，回退到 Y」这句结论要保住。走 GDI 的
# EnumFontFamiliesExW：它给的是**真正的家族名**。不走注册表，因为注册表给的是**文件名** ——
# 实测那台机器上是 `MiSans Medium (TrueType)`、`Microsoft YaHei & Microsoft YaHei UI
# (TrueType)`、`Cascadia Mono Regular (TrueType)`，要自己拆 `&`、剥 `Regular/Bold/...` 后缀，
# 全靠猜；而 GDI 直接给 `MiSans`、`MiSans Medium`、`Microsoft YaHei UI`、`Cascadia Mono`。

if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    class _LOGFONTW(ctypes.Structure):
        _fields_ = [
            ("lfHeight", _wt.LONG), ("lfWidth", _wt.LONG),
            ("lfEscapement", _wt.LONG), ("lfOrientation", _wt.LONG),
            ("lfWeight", _wt.LONG),
            ("lfItalic", ctypes.c_ubyte), ("lfUnderline", ctypes.c_ubyte),
            ("lfStrikeOut", ctypes.c_ubyte), ("lfCharSet", ctypes.c_ubyte),
            ("lfOutPrecision", ctypes.c_ubyte), ("lfClipPrecision", ctypes.c_ubyte),
            ("lfQuality", ctypes.c_ubyte), ("lfPitchAndFamily", ctypes.c_ubyte),
            ("lfFaceName", ctypes.c_wchar * 32),
        ]

    _ENUMPROCFONTEXW = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.POINTER(_LOGFONTW), ctypes.c_void_p, _wt.DWORD, _wt.LPARAM)
    _gdi32.EnumFontFamiliesExW.argtypes = [
        _wt.HDC, ctypes.POINTER(_LOGFONTW), _ENUMPROCFONTEXW, _wt.LPARAM, _wt.DWORD]
    _gdi32.EnumFontFamiliesExW.restype = ctypes.c_int
    _DEFAULT_CHARSET = 1

    def installed_families():
        """这台机器上装了的家族名集合。**问不出来返回 None**（≠ 没装）。"""
        hdc = _user32.GetDC(None)
        if not hdc:
            return None
        seen = set()

        def _cb(lpelf, _lptm, _fonttype, _lparam):
            seen.add(lpelf.contents.lfFaceName)
            return 1

        cb = _ENUMPROCFONTEXW(_cb)
        lf = _LOGFONTW()
        lf.lfCharSet = _DEFAULT_CHARSET
        try:
            _gdi32.EnumFontFamiliesExW(hdc, ctypes.byref(lf), cb, 0, 0)
        finally:
            _user32.ReleaseDC(None, hdc)
        return seen or None
else:
    def installed_families():
        return None


def resolve_font(want=None):
    """'harmony' 或 'misans'。状态文件的 `font` 说了算，读不到/不认识就用默认档。"""
    if want is None:
        try:
            with open(state_path(), encoding="utf-8") as f:
                want = json.load(f).get("font")
        except (OSError, ValueError):
            want = None
    return want if want in FONTS else FONT_DEFAULT


def font_spec(key=None):
    return FONTS[resolve_font(key)]


def pick_family(chain, available=None):
    """家族链里第一个真的装了的；一个都没装（或问不出来）就用链首。"""
    if available is None:
        available = installed_families()
    if not available:
        return chain[0]
    for fam in chain:
        if fam in available:
            return fam
    return chain[-1]


def font_status(key=None):
    """设置页那行小字要的结论：想要哪个家族、实际会画成哪个、是不是回退了。"""
    spec = font_spec(key)
    available = installed_families()
    fam = pick_family(spec["chain"], available)
    return {"key": resolve_font(key), "label": spec["label"], "want": spec["family"],
            "family": fam, "missing": fam != spec["family"],
            "probed": available is not None}


def font_hint(key=None):
    """上面那份结论的一句话版本（空字符串 = 问不出来，说不出结论）。"""
    st = font_status(key)
    if not st["probed"]:
        return ""
    if st["missing"]:
        return "未安装 %s，回退到 %s" % (st["want"], st["family"])
    return "已装：%s" % st["family"]


def apply_font(key=None):
    """选定一档、解析出真正要画的家族名，返回 `(正文, 中等, 是否回退)`。"""
    spec = font_spec(key)
    available = installed_families()
    fam = pick_family(spec["chain"], available)
    fam_b = pick_family(spec["chain_medium"], available)
    _FAMILY["n"], _FAMILY["b"] = fam, fam_b
    return fam, fam_b, fam != spec["family"]


def font_family(medium=False):
    """当前真正要画的家族名（`apply_font` 解析过就用它，否则用默认档声明的那个）。"""
    slot = "b" if medium else "n"
    return _FAMILY.get(slot) or FONTS[FONT_DEFAULT]["medium" if medium else "family"]


def state_path():
    """状态文件路径。**每次问一遍业务层**，不在这里存第二份（当年旧 Qt 面板的 `qt_theme` 踩过这个坑）。"""
    import panel_core
    return panel_core.STATE


def resolve_appearance(want=None):
    """'light' 或 'dark'。状态文件的 `appearance` 说了算；跟随系统时问 Windows。

    读法与旧面板逐字一致（只有明确写了 light/dark 才采用，否则交给 darkdetect，读不到按浅色），
    所以同一个 `gui_state.json` 在两套视图下选中的是同一套颜色。
    """
    if want is None:
        try:
            with open(state_path(), encoding="utf-8") as f:
                want = json.load(f).get("appearance")
        except (OSError, ValueError):
            want = None
    if want in ("light", "dark"):
        return want
    try:
        import darkdetect
        return "dark" if darkdetect.theme() == "Dark" else "light"
    except Exception:                                             # noqa: BLE001
        return "light"


# ============================ 4. 装配 ============================

def theme(appearance="dark", font_key=None):
    """一套完整的 `ft.Theme`：颜色角色 + 字体阶梯 + 密度 + 规范里那几个散落的颜色钩子。"""
    tk = Tokens(appearance)
    fam = font_family() if font_key is None else apply_font(font_key)[0]
    btn = ft.ButtonStyle(shape=ft.StadiumBorder(), text_style=type_style("labelLarge", fam))
    return ft.Theme(
        use_material3=True,
        color_scheme=color_scheme(appearance),
        text_theme=text_theme(fam),
        font_family=fam,
        # **STANDARD，不收**：M3 的容器高就是在这一档下给的 —— 常见按钮 40、outlined 输入框 56
        # （androidx `FilledTonalButtonTokens.ContainerHeight = 40.0`、
        # `OutlinedTextFieldTokens.ContainerHeight = 56.0`；规格表也逐条写着 40dp / 56dp）。
        # 从前挂的是 Flutter 桌面的 COMPACT，每个容器的基准高要减 2 × 4dp（实拍按钮 32.4、
        # 输入框 48.6），照用户 m08726「严格按照官方的设计参数来编写代码」改回标准档。
        # 字号阶梯本来就不受密度影响，这一条只动控件内边距。
        visual_density=ft.VisualDensity.STANDARD,
        scaffold_bgcolor=tk.page,
        canvas_color=tk.page,
        card_bgcolor=tk.card,
        divider_color=tk.border,
        hint_color=tk.text_dim,
        secondary_header_color=tk.text_dim,
        unselected_control_color=tk.text_dim,
        disabled_color=tk.disabled(tk.text),
        splash_color=tk.state(tk.text, "pressed"),
        highlight_color=tk.state(tk.text, "pressed"),
        hover_color=tk.state(tk.text, "hover"),
        focus_color=tk.state(tk.text, "focus"),
        # 组件级主题。规范里每个组件都有一张「容器色 / 形状 / 字型」的表；能交给主题的交给主题，
        # 于是**连 Flet 自己建的控件**（下拉菜单、滚动条、工具提示、对话框里那几个按钮）也落在
        # 同一套 token 上，不必在视图层逐处手写。视图层里显式写的那几处仍然显式写 —— 它们带状态。
        #
        # 每一张的出处（材料 web 取 `tokens/versions/v0_192/_md-comp-*.scss`，androidx 取
        # `compose/material3/material3/src/commonMain/kotlin/androidx/compose/material3/tokens/*Tokens.kt`，
        # 两套在下面这些值上逐条相符）：
        #   app bar   container-height 64 / surface / level0 / title-large
        #   rail      指示条 = secondary-container + corner-full、两档 label-medium
        #             （宽 80/256 跟 Flutter `_NavigationRailDefaultsM3`，见 NAV_MIN_W 的注释）
        #   card      surface-container-low / level1 / corner-medium
        #   dialog    surface-container-high / level3 / corner-extra-large / headline-small +
        #             body-medium，动作是 label-large 的**文字按钮**
        #   snackbar  inverse-surface / level3 / corner-extra-small / body-medium +
        #             inverse-on-surface（动作色官方是 inverse-primary，Flet 侧自己取）
        #   chip      容器高 32 / corner-small / label-large / 描边 1dp（见 `chip_side`）
        #   list      两行项 72、主文字 body-large、支撑行 body-medium、行首间距 16
        #   menu      surface-container / level2 / corner-extra-small，项的**字**是 body-large
        #             （androidx `ListTokens.ItemLabelTextFont`；项高 48 是 `Menu.kt` 里的常量，
        #             不是 token）
        #   divider   outline-variant / 1dp
        #   progress  4dp 高 + 轨道 secondary-container + 两端胶囊
        #   tooltip   inverse-surface / corner-extra-small / body-small + inverse-on-surface
        #   icon      corner-full（40×40 由 Flutter 画）；button corner-full + label-large
        #   segmented 整组 corner-full（首尾半圆 + 中间直角，Flutter 按段序号现算）、描边 1dp
        #             `outline`（选中段也留）、段高 40、图标 18、选中段
        #             `secondary-container` + `on-secondary-container`、未选中不铺底 + `on-surface`
        #             —— 1 级没有分段控件，这条是 3a（见 SEGMENT_H 的注释）
        appbar_theme=ft.AppBarTheme(
            bgcolor=tk.surface, color=tk.text, elevation=ELEVATION["level0"],
            toolbar_height=APPBAR_H, title_text_style=type_style("titleLarge", fam)),
        # 官方 `NavigationRailColorTokens.ItemActiveIndicator = SecondaryContainer`、
        # `…BaselineItemTokens.ActiveIndicatorShape = CornerFull`、两档 `LabelTextFont = LabelMedium`。
        navigation_rail_theme=ft.NavigationRailTheme(
            bgcolor=tk.surface, indicator_color=tk.secondary_container,
            indicator_shape=ft.RoundedRectangleBorder(radius=radius("nav_indicator")),
            selected_label_text_style=type_style("labelMedium", fam),
            unselected_label_text_style=type_style("labelMedium", fam),
            min_width=NAV_MIN_W, min_extended_width=NAV_MIN_EXT_W, group_alignment=-1.0),
        # 官方 elevated card（`ElevatedCardTokens.kt`）：surface-container-low / level1 / corner-medium。
        card_theme=ft.CardTheme(color=tk.card, elevation=ELEVATION["level1"],
                                shape=ft.RoundedRectangleBorder(radius=radius("card"))),
        dialog_theme=ft.DialogTheme(
            bgcolor=tk.dialog, elevation=ELEVATION["level3"],
            shape=ft.RoundedRectangleBorder(radius=radius("dialog")),
            # 官方 `_md-comp-dialog.scss`：标题 headline-small(24)、supporting text
            # body-medium(14)。视图层从前把这两档压成 titleMedium(16)/bodySmall(12)，
            # 2026-10-06 按官方改回（视图层同样走这两档，见 `flet_gui` 的 `txt_spec`）。
            title_text_style=type_style("headlineSmall", fam),
            content_text_style=type_style("bodyMedium", fam)),
        # 官方 `SnackbarTokens.kt`：inverse-surface / level3 / corner-extra-small / body-medium +
        # inverse-on-surface（动作字色官方是 inverse-primary + label-large，Flet 侧自己取）。
        snackbar_theme=ft.SnackBarTheme(
            bgcolor=tk.snack_bg, elevation=ELEVATION["level3"],
            shape=ft.RoundedRectangleBorder(radius=radius("snackbar")),
            content_text_style=type_style("bodyMedium", fam, tk.snack_fg)),
        chip_theme=ft.ChipTheme(
            # 未选中的 filter chip **不铺底**：官方 `_FilterChipDefaultsM3.color` 在 flat 变体、
            # 未选中时返回 `null`（`FilterChipTokens.kt` 里也只有 `FlatSelectedContainerColor`，
            # 没有任何未选中容器色）。从前写 `surface`，比它所在的卡片还暗一档 —— 一排 chip 看着
            # 像在卡上挖了几个洞（实拍 `log_dark.png`：卡片 `#1a1b21`、未选中 chip 内里 `#121318`）。
            bgcolor=ft.Colors.TRANSPARENT, selected_color=tk.secondary_container,
            check_color=tk.on_secondary_container,
            label_text_style=type_style("labelLarge", fam),
            shape=ft.RoundedRectangleBorder(radius=radius("chip")),
            # 描边 1dp：androidx `FilterChipTokens.FlatUnselectedOutlineColor = OutlineVariant`
            # （材料 web A 层给的是 `outline` —— 两家官方不一致，本项目跟 androidx/Flutter 这一套）。
            border_side=ft.BorderSide(1, tk.outline_variant),
            # 内边距 8：chip 的左右内边距在两套官方里都不是 token（androidx `Chip.kt` 按有无图标算，
            # 横向元素间距 `HorizontalElementsPadding = 8.dp`；材料 web B 层的 `leading-space 16`
            # 是含图标槽的另一套口径）。
            padding=ft.Padding(SPACE["sm"], 0, SPACE["sm"], 0)),
        list_tile_theme=ft.ListTileTheme(
            selected_tile_color=tk.secondary_container, icon_color=tk.text_dim,
            # 官方 `_md-comp-list.scss`：两行项 72 由框架自己算，行主文字 body-large(16) +
            # supporting text body-medium(14)、行首间距 leading-space 16。主题层从前挂着框架的
            # 密集档 + 4dp 竖向内边距把 72 压到约 57 —— m08726 只清了视图层，这一份到 2026-10-06
            # 才清掉（视图层那一行仍按 DEVIATIONS 里「正文取阶梯下端」取紧凑字型）。
            text_color=tk.text, title_text_style=type_style("bodyLarge", fam),
            subtitle_text_style=type_style("bodyMedium", fam),
            horizontal_spacing=SPACE["lg"]),
        popup_menu_theme=ft.PopupMenuTheme(
            color=tk.menu, elevation=ELEVATION["level2"],
            shape=ft.RoundedRectangleBorder(radius=radius("menu")),
            # 菜单项的字官方是 body-large（androidx `ListTokens.ItemLabelTextFont`、材料 web
            # menu-item `label-text-font = body-large-font`）—— 2026-10-06 从本项目手挑的
            # bodyMedium 改回官方。
            label_text_style=type_style("bodyLarge", fam)),
        # 官方 `DividerTokens.kt` / `_md-comp-divider.scss`：`color = outline-variant`、
        # `thickness = 1px`（那两份导出里没有 height，thickness 是唯一几何）。
        divider_theme=ft.DividerTheme(color=tk.border, thickness=1),
        # 官方 `ProgressIndicatorTokens.kt`：活动段与停止点 = primary、**轨道 = secondary-container**
        # （`tk.trough` 就是它，见 SEMANTIC）、`TrackShape = corner-full` ⇒ 半径 = 条高的一半；
        # 几何四条（height / track-thickness / stop-size / track-active-space）全是 4.0dp。
        progress_indicator_theme=ft.ProgressIndicatorTheme(
            color=tk.accent, linear_track_color=tk.trough,
            linear_min_height=PROGRESS_H, border_radius=PROGRESS_R),
        scrollbar_theme=ft.ScrollbarTheme(
            thickness=SCROLLBAR_W, radius=SCROLLBAR_R, thumb_color=tk.outline,
            track_color=tk.page),
        # 官方 plain tooltip（`PlainTooltipTokens.kt` / `_md-comp-plain-tooltip.scss`）：
        # `container-color = inverse-surface`、`corner-extra-small`、supporting text = body-small +
        # inverse-on-surface（容器高与内边距在那两份导出里都不是 token）。
        tooltip_theme=ft.TooltipTheme(
            text_style=type_style("bodySmall", fam, tk.tip_fg),
            decoration=ft.BoxDecoration(bgcolor=tk.tip_bg,
                                        border_radius=border_radius("tooltip"))),
        # icon button：官方 `SmallIconButtonTokens.ContainerShapeRound = corner-full`（40×40 的
        # 容器由 Flutter 按 24 图标 + 两侧各 8 算出来）。
        icon_button_theme=ft.IconButtonTheme(style=ft.ButtonStyle(shape=ft.CircleBorder())),
        # 三种按钮共用一份 `btn`（`StadiumBorder` = corner-full + label-large）：官方
        # `ButtonSmallTokens` / `BaselineButtonTokens` 的容器高 40、形状 corner-full、标签字
        # label-large、左右内边距 filled/outlined 24（带图标那一侧 16）、text 12 —— 高度与内边距
        # 由 Flutter 的按钮自己画，这里只钉形状与字阶（`btn` 在 `theme()` 顶部）。
        filled_button_theme=ft.FilledButtonTheme(style=btn),
        outlined_button_theme=ft.OutlinedButtonTheme(style=btn),
        text_button_theme=ft.TextButtonTheme(style=btn),
        # 分段控件：官方那套配色与几何**全交给控件自己画**，这里只钉值 —— 形状（整组一个胶囊，
        # 首尾半圆 + 中间直角）、描边 1dp `outline`（选中段也留着）、段高 40、图标 18、字阶
        # label-large、选中段 `secondary_container` + `on_secondary_container`、未选中不铺底 +
        # `on_surface`。**选中对勾不给**（`selected_icon` 留空 + 视图层 `show_selected_icon=False`）：
        # 官方那条勾的规则前提是「段里同时有图标和文字」，面板四段是纯文字，画了反而把文字右推
        # 11.1 dp —— 理由与实测见 DEVIATIONS 里那条「不画选中对勾」。
        # **不给 `shape`**：`style.shape` 是整组的外框，一给就四段同形；分段形状的来源是 Flutter
        # 的 `itemShape(index, count)`。出处见 SEGMENT_H 的注释。
        segmented_button_theme=ft.SegmentedButtonTheme(
            style=ft.ButtonStyle(
                bgcolor={ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
                         ft.ControlState.SELECTED: tk.secondary_container},
                color={ft.ControlState.DEFAULT: tk.text,
                       ft.ControlState.SELECTED: tk.on_secondary_container},
                icon_color={ft.ControlState.DEFAULT: tk.text,
                            ft.ControlState.SELECTED: tk.on_secondary_container},
                icon_size=SEGMENT_ICON,
                side={ft.ControlState.DEFAULT: ft.BorderSide(SEGMENT_BORDER_W, tk.outline),
                      ft.ControlState.SELECTED: ft.BorderSide(SEGMENT_BORDER_W, tk.outline)},
                text_style=type_style("labelLarge", fam))),
    )


def apply(page, appearance=None, font_key=None):
    """把主题落到页面上，返回真正生效的外观（'light'/'dark'）。

    `theme_mode` 与两套 `ft.Theme` 一起给：跟随系统时由 Flutter 自己按 `ThemeMode.SYSTEM`
    在亮暗之间切，面板不必自己去听系统事件。
    """
    want = appearance
    if want is None:
        want = resolve_appearance()
    apply_font(font_key)
    page.theme = theme("light")
    page.dark_theme = theme("dark")
    page.theme_mode = {"light": ft.ThemeMode.LIGHT, "dark": ft.ThemeMode.DARK}.get(
        want, ft.ThemeMode.SYSTEM)
    return want


def tokens(appearance=None):
    return Tokens(appearance or resolve_appearance())
