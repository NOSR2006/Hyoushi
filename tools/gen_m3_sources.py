#!/usr/bin/env python
"""生成 `docs/m3_sources.md`：把「我们依据的官方源」抓一遍、算 sha256、落成一张可复算的表。

它不是判据（判据在 `tools/probes/m3tokens.py` 第 10 关，那条判据**不联网**，只钉
「登记表覆盖了下面清单里的每一份 1 级文件、每份都带 sha256、三条链前缀与版本戳都在」）。
这个脚本是**取证工具**，只在显式跑的时候才联网。

用法：

    python tools/gen_m3_sources.py --probe    # 只抓一遍并打印（不写文件），用来核对清单与 token 名
    python tools/gen_m3_sources.py --write    # 抓取 + 算 sha256 + 写 docs/m3_sources.md

下面的三张表是「我们真正引用了哪些官方文件、引了哪些 token」的唯一记录；依据顺序（0–5 级）
与裁决规则写在 `AGENTS.md` 的「依据顺序」一节。**改这里必须同时跑 `--write` 重生成登记表**，
否则 `tools/probes/m3tokens.py` 第 10 关会红。
"""
import argparse
import datetime
import hashlib
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "m3_sources.md")

# ---------------------------------------------------------------------------
# 0 级：生成器（能重算的绝不抄）
# ---------------------------------------------------------------------------
GEN_NAME = "material-color-utilities==0.2.6"
GEN_USE = "tools/gen_m3_tokens.py"
GEN_CHECK = "tools/probes/m3tokens.py PART 1-2"

# ---------------------------------------------------------------------------
# 1 级：数值权威 —— material-web 自动生成的设计系统导出（只认 versions/ 这层）
# ---------------------------------------------------------------------------
WEB_PREFIX = ("https://cdn.jsdelivr.net/gh/material-components/material-web@main"
              "/tokens/versions/v0_192/")
# 每份文件开头都逐字带这几行（`--write` 会核对，`m3tokens` 第 10 关也钉版本戳）
WEB_HEAD = ("Design system display name: Google Material 3",
            "Design system version: v0.192",
            'User-configured context group "Audience": "3P"',
            '"Platform": "Web"',
            '"Scheme": "Dynamic"')
# (文件名, 我们引用的 token 名)  —— token 名必须真的出现在文件里，`--probe` 会逐个核
SOURCES_WEB = (
    ("_md-comp-list.scss", ("list-item-one-line-container-height",
                            "list-item-two-line-container-height",
                            "list-item-three-line-container-height",
                            "list-item-leading-image-width",
                            "list-item-leading-avatar-size",
                            "list-item-leading-icon-size",
                            "list-item-leading-space",
                            "list-item-trailing-space",
                            "list-item-label-text-font",
                            "list-item-supporting-text-font")),
    # 注意：官方**只**给 track 52×32 与状态层 40；`touch-target-size 48px` 只在 MWC 适配层里，
    # 按依据顺序第 1 级不算依据（面板的 48 触摸面是「本项目决定」，不是官方值）。
    ("_md-comp-switch.scss", ("track-width", "track-height", "state-layer-size")),
    ("_md-comp-filled-button.scss", ("container-height", "container-shape",
                                     "label-text-font", "with-icon-icon-size",
                                     "disabled-container-opacity",
                                     "disabled-label-text-opacity")),
    ("_md-comp-outlined-button.scss", ("container-height", "container-shape",
                                       "label-text-font")),
    # 官方导出**没有** `container-height`（全文件没有 56）：输入框容器高 56 只有 androidx 给
    # （`OutlinedTextFieldTokens.ContainerHeight`）⇒ 那一条算 3a 补位，不算 1 级值。
    ("_md-comp-outlined-text-field.scss", ("input-text-font", "input-text-size",
                                           "input-text-line-height", "outline-width",
                                           "focus-outline-width", "leading-icon-size",
                                           "trailing-icon-size")),
    ("_md-comp-dialog.scss", ("container-color", "container-elevation", "container-shape",
                              "headline-font", "headline-size", "supporting-text-font",
                              "supporting-text-size", "action-label-text-color",
                              "action-label-text-font")),
    ("_md-comp-data-table.scss", ("header-container-height", "row-item-container-height",
                                  "header-headline-font", "row-item-label-text-font",
                                  "row-item-outline-width", "row-item-outline-color",
                                  "outline-width", "outline-color",
                                  "header-container-color",
                                  "row-item-selected-container-color",
                                  "row-item-unselected-hover-state-layer-color",
                                  "row-item-unselected-hover-state-layer-opacity",
                                  "row-item-selected-hover-state-layer-color",
                                  "row-item-selected-hover-state-layer-opacity")),
    ("_md-comp-navigation-rail.scss", ("container-width",)),
    ("_md-comp-top-app-bar-small.scss", ("container-height", "container-color",
                                         "container-elevation", "headline-font")),
    ("_md-comp-divider.scss", ("color", "thickness")),
    ("_md-comp-plain-tooltip.scss", ("container-color", "container-shape",
                                     "supporting-text-font")),
    ("_md-comp-filled-icon-button.scss", ("container-shape", "icon-size",
                                          "disabled-icon-opacity",
                                          "disabled-container-opacity")),
    ("_md-comp-menu.scss", ("container-color", "container-elevation", "container-shape")),
    ("_md-comp-snackbar.scss", ("container-color", "container-elevation", "container-shape",
                                "supporting-text-font", "action-label-text-font")),
    ("_md-comp-elevated-card.scss", ("container-color", "container-elevation",
                                     "container-shape")),
    ("_md-comp-assist-chip.scss", ("container-height", "container-shape",
                                   "label-text-font", "with-icon-icon-size")),
    ("_md-sys-shape.scss", ("corner-extra-small", "corner-small", "corner-medium",
                            "corner-large", "corner-extra-large", "corner-full")),
    ("_md-sys-elevation.scss", ("level0", "level1", "level2", "level3", "level4",
                                "level5")),
    ("_md-sys-state.scss", ("hover-state-layer-opacity", "focus-state-layer-opacity",
                            "pressed-state-layer-opacity", "dragged-state-layer-opacity")),
    ("_md-sys-typescale.scss", ("body-large-size", "body-medium-size", "label-large-size",
                                "title-large-size", "headline-small-size")),
)

# ---------------------------------------------------------------------------
# 3a 级：androidx（旁证；分支型来源，哈希只代表抓取当日）
# ---------------------------------------------------------------------------
AND_PREFIX = ("https://raw.githubusercontent.com/androidx/androidx/androidx-main"
              "/compose/material3/material3/src/commonMain/kotlin/androidx/compose/material3/")
SOURCES_AND = (
    ("tokens/StateTokens.kt", "状态层**分歧记录**：它写 focus/pressed 各 0.1，与 1 级 0.12 不符 ⇒ 不采"),
    ("tokens/SwitchTokens.kt", "开关四色与手柄几何"),
    ("tokens/OutlinedTextFieldTokens.kt", "输入框 56 / 描边 1 / 聚焦 2 / 图标 24"),
    ("tokens/TypeScaleTokens.kt", "15 档字阶（tracking 三处与 Web 导出不同）"),
    ("tokens/AssistChipTokens.kt", "chip 32 / 图标 18"),
    ("tokens/FilterChipTokens.kt", "flat 三条：未选中描边 outline_variant、选中 0、选中底 secondary_container"),
    ("Chip.kt", "chip 内边距 8 / 横向间距 8"),
    ("tokens/ProgressIndicatorTokens.kt", "轨道 secondary_container / 活动段 primary / 全 4.0"),
    ("tokens/LinearProgressIndicatorTokens.kt", "线性进度条 4.0"),
    ("tokens/ShapeTokens.kt", "4/8/12/16/28/full"),
    ("tokens/ElevationTokens.kt", "0/1/3/6/8/12"),
    ("tokens/AppBarSmallTokens.kt", "顶栏 64"),
    ("tokens/ListTokens.kt", "列表 56/72/88 与 leading 图标 24"),
    ("Menu.kt", "菜单项 48 与 ItemLabelTextFont = BodyLarge"),
    ("tokens/ElevatedCardTokens.kt", "elevated 卡三件套"),
    ("tokens/SnackbarTokens.kt", "snackbar 三件套"),
    ("tokens/PlainTooltipTokens.kt", "tooltip 三件套"),
    ("tokens/DividerTokens.kt", "分隔线 outline_variant / 1dp"),
    ("Button.kt", "按钮 40 / corner-full / label-large"),
)

# ---------------------------------------------------------------------------
# 3b 级：Flutter（只在 M3 没定义的地方用；必须标注「这是 Flutter 的选择」）
# ---------------------------------------------------------------------------
FLU_PREFIX = "https://cdn.jsdelivr.net/gh/"
SOURCES_FLU = (
    ("flutter/flutter@master", "packages/flutter/lib/src/material/scrollbar.dart",
     "M3 没有滚动条组件：粗 8 / 半径 8（画在 8dp 上夹成 4）"),
    ("flutter/flutter@master", "packages/flutter/lib/src/material/navigation_rail.dart",
     "收起 80 / 展开 256（`_NavigationRailDefaultsM3`）"),
    ("flutter/flutter@master", "packages/flutter/lib/src/material/data_table.dart",
     "排序箭头格 18"),
    ("flutter/flutter@master", "packages/flutter/lib/src/material/filter_chip.dart",
     "flat 未选中不铺底、选中描边透明"),
    # `animations` 包**不在** flutter/flutter 里，在 flutter/packages —— 这条曾经引错仓库（404 过），别改回去
    ("flutter/packages@main",
     "packages/animations/lib/src/fade_through_transition.dart",
     "换页 `_scaleIn` 0.92 与两拍曲线（`_inCurve` Cubic(0,0,0.2,1) / `_outCurve` Cubic(0.4,0,1,1)）"),
)


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (bang-m3-sources)"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read()


def fetch(url, github=False):
    """抓一份。github=True 时先走 ghproxy 镜像（本机直连 raw.githubusercontent 取不到）。"""
    tries = ["https://ghproxy.net/" + url, url] if github else [url]
    last = None
    for u in tries:
        try:
            return _fetch(u)
        except Exception as exc:  # noqa: BLE001 - 逐个镜像试
            last = exc
    raise RuntimeError(f"{url}: {last}")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _version_stamp(text):
    m = re.search(r"//\s*VERSION:\s*(\S+)", text)
    return m.group(1) if m else ""


def probe(verbose=True):
    """抓一遍，返回 (rows_web, rows_and, rows_flu, problems)。"""
    rows_web, rows_and, rows_flu, problems = [], [], [], []

    for name, tokens in SOURCES_WEB:
        try:
            data = fetch(WEB_PREFIX + name)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"1 级 {name}: {exc}")
            if verbose:
                print(f"  MISS 1 级 {name}")
            continue
        text = data.decode("utf-8", "replace")
        missing = [t for t in tokens if t not in text]
        if missing:
            problems.append(f"1 级 {name}: token 名对不上 {missing}")
        head_ok = all(h in text for h in WEB_HEAD)
        if not head_ok:
            problems.append(f"1 级 {name}: 文件头不是 v0.192 导出")
        rows_web.append((name, len(data), sha256(data), tokens, missing))
        if verbose:
            flag = "OK  " if not missing else "TOK?"
            print(f"  {flag} 1 级 {name:<38} {len(data):>7} B  {sha256(data)[:8]}"
                  f"{'' if not missing else '  缺 ' + ','.join(missing)}")

    for path, note in SOURCES_AND:
        try:
            data = fetch(AND_PREFIX + path, github=True)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"3a {path}: {exc}")
            if verbose:
                print(f"  MISS 3a {path}")
            continue
        stamp = _version_stamp(data.decode("utf-8", "replace"))
        rows_and.append((path, len(data), sha256(data), stamp, note))
        if verbose:
            print(f"  OK   3a {path:<38} {len(data):>7} B  {sha256(data)[:8]}  {stamp}")

    for repo, path, note in SOURCES_FLU:
        try:
            data = fetch(FLU_PREFIX + repo + "/" + path)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"3b {repo}/{path}: {exc}")
            if verbose:
                print(f"  MISS 3b {repo}/{path}")
            continue
        rows_flu.append((f"{repo}/{path}", len(data), sha256(data), note))
        if verbose:
            print(f"  OK   3b {repo}/{path:<58} {len(data):>7} B  {sha256(data)[:8]}")

    return rows_web, rows_and, rows_flu, problems


def _table(rows, first, kind):
    if kind == "web":
        out = [f"| {first} | 字节 | sha256 | 我们引用的 token |", "|---|---|---|---|"]
        for name, size, digest, tokens, _missing in rows:
            used = "、".join(f"`{t}`" for t in tokens) or "（只引文件头/版本戳）"
            out.append(f"| `{name}` | {size} | `{digest}` | {used} |")
    elif kind == "and":
        out = [f"| {first} | 字节 | sha256 | VERSION | 用途 |", "|---|---|---|---|---|"]
        for name, size, digest, stamp, note in rows:
            out.append(f"| `{name}` | {size} | `{digest}` | {stamp or '（无戳）'} | {note} |")
    else:
        out = [f"| {first} | 字节 | sha256 | 用途 |", "|---|---|---|---|"]
        for name, size, digest, note in rows:
            out.append(f"| `{name}` | {size} | `{digest}` | {note} |")
    return out


def write(rows_web, rows_and, rows_flu):
    today = datetime.date.today().isoformat()
    lines = [
        "# M3 依据来源登记表",
        "",
        f"> 由 `tools/gen_m3_sources.py --write` 生成（**抓取当日：{today}**，sha256 对 HTTP 响应体的",
        "> 原始字节计算）。`tools/probes/m3tokens.py` 第 10 关**不联网**地钉住这份表：清单里的每一份",
        "> 1 级文件都在表里、每份都带 64 位 sha256、三条链的前缀与 `Design system version: v0.192`",
        "> 都在。依据顺序与裁决规则见 `AGENTS.md` 的「依据顺序」一节。",
        "",
        "**镜像**：material-web 与 Flutter 走 jsDelivr（`cdn.jsdelivr.net/gh/...`），androidx 走",
        "`ghproxy.net` 代理的 `raw.githubusercontent.com`（本机直连取不到）。androidx 与 Flutter 是",
        "**分支型**来源，哈希只代表抓取当日；material-web 那份带版本戳 `v0.192`，是唯一可长期钉住的。",
        "",
        "## 0 级｜生成器（能重算的绝不抄）",
        "",
        f"- `{GEN_NAME}` —— 颜色不是抄来的，是 `{GEN_USE}` 现算的（种子 `#3e63dd`、TONALSPOT、",
        "  contrast 0.0，即 Flutter `ColorScheme.fromSeed` 的默认档 = 规范基线），冻结成",
        "  `tools/m3_tokens.json`。",
        f"- 复算：`{GEN_CHECK}` 用**同一个库**把 46 个角色 × 两套外观重算一遍、逐格比回来。",
        "",
        "## 1 级｜数值权威：material-web 自动生成的设计系统导出",
        "",
        f"- 前缀 `{WEB_PREFIX}`",
        "- 每份文件开头逐字：`!!! THIS FILE WAS AUTOMATICALLY GENERATED !!!`、`!!! DO NOT MODIFY IT",
        "  BY HAND !!!`，以及",
        *[f"  - `{h}`" for h in WEB_HEAD],
        "- **只认这一层**。同一仓库 `tokens/` 下**非 versioned** 的文件是 Material Web Components 的",
        "  适配层（`validate.values(... $new-tokens ...)` 会自己加 token、改 token 名），**不算依据**；",
        "  `tokens/v0_192/*.scss` 那批 130 B 存根只是 `@forward` 转发。",
        "",
        *_table(rows_web, "文件", "web"),
        "",
        "## 2 级｜意图权威",
        "",
        "- `https://m3.material.io/` —— 讲的是**为什么**（组件语义、用法、无障碍），不是数值。它是单页",
        "  应用，正文抓不到；唯一实抓成功的是 cards 规格表（`OFFICIAL_CARD` 的 16/8）。**抓不到就记",
        "  「未取证」，不许凭印象补数**。数值上与 1 级冲突时听 1 级，并在 `DEVIATIONS` 登记。",
        "",
        "## 3 级｜旁证与平台补位",
        "",
        "### 3a androidx Compose Material3（**旁证**；取它的值必须与 1 级相符，对不上就不采）",
        "",
        f"- 前缀 `{AND_PREFIX}`（`Chip.kt`/`Menu.kt`/`Button.kt` 在 `material3/` 根目录，不在 `tokens/`）",
        "- 有些文件带 `// VERSION:` 戳（见下表），没有戳的只能按分支记。**androidx 含 Material 3",
        "  Expressive 的增量**（本项目只走最纯正的 M3，一律不采）。",
        "- **1 级没定义、只有它给的**算「3a 补位」（注释里要点明是哪一条）：输入框容器高 56",
        "  （`OutlinedTextFieldTokens.ContainerHeight` —— 1 级的 `_md-comp-outlined-text-field.scss`",
        "  整个文件都没有 56）、开关四色与手柄几何（1 级只给 `track-width` 52 / `track-height` 32 /",
        "  `state-layer-size` 40）。",
        "- **与 1 级不符的一律不采**，只作分歧记录留在表里：`StateTokens.kt` 写 focus/pressed 各 0.1，",
        "  1 级 `_md-sys-state.scss` 写 0.12 ⇒ 跟 1 级（用户 m19222 定）。",
        "",
        *_table(rows_and, "文件", "and"),
        "",
        "### 3b Flutter（只在 M3 **没有定义**的地方用）",
        "",
        "- `https://cdn.jsdelivr.net/gh/flutter/flutter@master/`（material 组件）与",
        "  `https://cdn.jsdelivr.net/gh/flutter/packages@main/`（`animations` 包 —— 它**不在**",
        "  `flutter/flutter` 里，第一版引错了仓库、404 过一次）。",
        "- 用它的每一处都必须在注释里写明「这是 Flutter 的选择，不是 M3 的规定」。",
        "",
        *_table(rows_flu, "文件", "flu"),
        "",
        "## 4 级｜落地层",
        "",
        "- Flet 1.0.3（`https://flet.dev/docs/`）+ **Flet MCP**（`get_api`/`list_controls`/`get_enum`/",
        "  `search_enum_members`/`enum_has_member`/`find_icon`）—— 只决定「Flet 能怎么表达」，",
        "  不决定「M3 要求什么」。",
        "",
        "## 5 级｜本项目自身",
        "",
        "- `tools/m3_theme.py`（令牌与组件主题）、`tools/m3_tokens.json`、`AGENTS.md`、`DEVIATIONS`",
        "  —— 这是**结果**不是来源：与高级别冲突时改代码，不改来源。",
        "",
    ]
    with open(DOC, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return DOC


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--probe", action="store_true", help="只抓一遍并打印（不写文件）")
    g.add_argument("--write", action="store_true", help="抓取 + 算 sha256 + 写 docs/m3_sources.md")
    args = ap.parse_args()

    rows_web, rows_and, rows_flu, problems = probe()
    print(f"1 级 {len(rows_web)}/{len(SOURCES_WEB)}、3a {len(rows_and)}/{len(SOURCES_AND)}、"
          f"3b {len(rows_flu)}/{len(SOURCES_FLU)}")
    for p in problems:
        print("PROBLEM " + p)

    if args.write:
        if problems:
            print(f"有 {len(problems)} 个问题，**不写文件**（先把清单改对）")
            return 1
        path = write(rows_web, rows_and, rows_flu)
        print(f"written {os.path.relpath(path, ROOT)} ({os.path.getsize(path)} B)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
