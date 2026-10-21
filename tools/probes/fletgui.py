"""探针：Flet 面板（Material 3）—— 十一关。

这一关量「Flet 的观感是不是照着规范长的」。三条立足点：

  - **规范**（`tools/m3_tokens.json` / `tools/m3_theme.py`）是唯一的 token 出处，视图层
    `tools/flet_gui.py` 不许写死任何颜色、圆角、字号、高程、间距；
  - **对位**：56 个方法名冻在这一关的 `PARITY` 里（删名字当作弊），业务逻辑仍全在
    `tools/panel_core.py`（它既不 import tkinter 也不 import PySide6、更不 import flet）；
    **全仓不许再有任何 Qt** —— 谁把 `PySide6` / `qt_theme` 拉回来，第 6 关就亮。
  - **像素**：`evidence/view/flet_*.png` 是真截图，它们要同时满足「没有错误控件那片灰」和
    「该画出来的确实画出来了」。

十一个 PART：

  1. **换行的 `Row` 里不许有会撑开（`expand`）的孩子**。这一条是拿血换来的：Flutter 的
     `Wrap` 收到 `Expanded` 孩子会在布局期抛异常，整个内容区被错误控件盖成一片 `#C0C0C0`
     （量过：`#C0C0C0` @ α=0.943 在暗底 `#121318` 上正好是 `#b6b6b6`）。静态扫源码，不靠跑。
  2. 输入框走 `border=OutlineInputBorder(...)`，不用 `FormFieldControl` 已废弃的
     `border_color` / `focused_border_color` / `border_width` / `focused_border_width` /
     `border_radius`。
  3. 视图层不写死视觉值：没有十六进制色字面量、不用 `ft.Colors.*`、圆角/高程/字号不取裸数字，
     每一个间距实参都从 `T.SPACE` 取。
  4. 规范表自身自洽：15 档字体阶梯的数值、7 档形状、6 级高程、6 个状态层不透明度、4dp 栅格、
     46 个颜色角色、`on_*` 与底色的对比度 ≥ 4.5:1、偏离规范的地方逐条有理由。
  5. 截图里没有那片灰（`#C0C0C0` 系），而且该有的确实在（导航轨底色、结算表表头行、难度行带）。
  6. 架构红线：`panel_core` 三个框架都不 import；56 个方法名冻在 `PARITY` 里、一个不许少；
     视图层没有留下「施工中」的占位；**全仓无 Qt 残留** —— `tools/` 下没有任何 .py
     import `PySide6` / `shiboken` / `qt_theme` / `qt_motion` / `qt_history` / `_qt_smoke`，
     旧 Qt 源文件、探针、基线、`qt_*.png` 截图、`requirements.txt` 里的 PySide6 全部不在。
  7. 选曲列表的契约：分类下拉的选项由 `cat_map` 填、`reload_songs` 按标签过表、不许把下拉框
     的空串当 bandId 直递；页脚在建好之后补写谱面库概况；真入口按规范的尺寸开窗。这一关是
     **实测**换来的：`panel.songs` 曾经恒为 0，而像素比对看不见（基线少的也是同一块）。
  8. 交给 `ask()` / `_confirm_stop_round()` 的回调不许是协程。`ask()` 的回调是按钮那一按里
     **同步**调用的，把 `async def` 方法直接传进去只会造出一个从未被 await 的协程 —— 这正是
     `_on_window_event` 原来的样子：窗不关、子进程也不收（行为那半边由 `fletfly.py` 盯着）。
  9. **过渡动画那六处**走的是 `m3_theme` 的 `MOTION` / `MOTION_DURATION` / `MOTION_EASING`，时长与缓动
     都不许在视图层写死；关掉开关时六处直接落终态（`_motion()`：缺键、写坏都当开）。
     「卡片进出场」这一处分进出两档（`card` / `card_out`），所以 `MOTION` 有七个档位、六个装置。
  10. **采图工具自己的出口早闸**（`tools/_flet_smoke.py` 的 `audit()`）得认得坏图：真图放行，
     空白帧与 Flutter 异常灰必须被拦住 —— 一道永远放行的闸门等于没有闸门。
  11. **精致度那一轮加的东西不许静默退掉**：三个列表都有居中空态（而且真的随数据开关）、日志页
     有自动滚动 / 导出日志 / 清屏、键盘清单里的每一条 `_on_key` 都接得住、破坏性确认走 `error`
     容器色、选曲行与「最近」那几行拿封面当 leading（缺图退回乐队色块）、`toast()` 不再是死代码、
     `m3_theme.theme()` 里 17 张组件级主题齐全。这一关每条判据都自带一颗牙：把对应的守卫改坏、
     重新解析一遍，判据必须变假 —— 静态扫源码，同样不需要桌面会话。

**它不碰模拟器、不起 run.py、不写真实语料、不需要桌面会话**（只读源码、token 表与已有 PNG）。
判定：任一 PART FAIL → 退出码 1。

Run from the repo root:  python tools/probes/fletgui.py
"""

from __future__ import annotations

import ast
import io
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import flet as ft  # noqa: E402
import m3_theme as T  # noqa: E402
import panel_core as core  # noqa: E402  （只看常量：尾判滑键的出厂值只许有一处来源）
import player  # noqa: E402

SRC_PATH = os.path.join(TOOLS, "flet_gui.py")
SRC = io.open(SRC_PATH, encoding="utf-8").read()
TREE = ast.parse(SRC)
VIEW = os.path.join(ROOT, "evidence", "view")

FAILS: list[str] = []


def check(label, cond, extra=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(label)
    return cond


# ------------------------------------------------------------------ 小工具

def _ft_call(node, *names):
    """`ft.Row(...)` / `ft.TextField(...)` 这种。"""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in names
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "ft")


def _kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _truthy(node):
    return node is not None and not (isinstance(node, ast.Constant) and not node.value)


def _flat(node):
    """把 `btns + [x, y]` 这种拼出来的孩子列表摊平。"""
    if node is None:
        return []
    if isinstance(node, ast.List):
        return list(node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _flat(node.left) + _flat(node.right)
    return [node]


def _name_of(node):
    """`self.foo` -> "foo"；别的返回 None。"""
    if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "self"):
        return node.attr
    return None


def _walk_calls(*names):
    for node in ast.walk(TREE):
        if _ft_call(node, *names):
            yield node


def _where(node):
    return f"flet_gui.py:{node.lineno}"


# ------------------------------------------------------- PART 1  换行 + expand

def part1():
    print("PART 1  换行的 Row 里不许有 expand 的孩子（灰块那一刀）")
    expand_names = {}
    for node in ast.walk(TREE):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            tgt = node.targets[0] if isinstance(node, ast.Assign) else node.target
            nm = _name_of(tgt)
            if nm and isinstance(node.value, ast.Call) and _truthy(_kw(node.value, "expand")):
                expand_names[nm] = node.lineno

    n_expand = sum(1 for node in ast.walk(TREE)
                   if isinstance(node, ast.keyword) and node.arg == "expand"
                   and _truthy(node.value))
    bad, rows, wraps = [], 0, 0
    for node in _walk_calls("Row"):
        rows += 1
        if not _truthy(_kw(node, "wrap")):
            continue
        wraps += 1
        kids = _flat(node.args[0] if node.args else _kw(node, "controls"))
        for kid in kids:
            if isinstance(kid, ast.Call) and _truthy(_kw(kid, "expand")):
                bad.append(f"{_where(kid)} 换行的 Row 里有 expand=True 的孩子")
                continue
            nm = _name_of(kid)
            if nm and nm in expand_names:
                bad.append(f"{_where(kid)} 换行的 Row 里有 self.{nm}，"
                           f"它在 flet_gui.py:{expand_names[nm]} 用 expand=True 建出来")

    check("换行的 Row 里没有 expand 的孩子", not bad, "；".join(bad))
    # 正向：这两条规矩要真的在守东西 —— 一个 wrap 都没有的话，上面那条断言是空的。
    # 阈值从前写作「>= 6」（随手定的数），后来又改成「wrap 至少两处、落在两个不同的方法里」——
    # 那两版都是靠运行卡的几行凑数。m05361 用户点名运行卡必须是**三行定宽**（复选框裹进有界
    # 的 Container、数框贴右沿、右边不许留空），`_pair`/`_group` 里的 `wrap=True` 因此全拆了，
    # 全仓只剩设置页那一处兜底。于是两条闸改成：至少一处（不许量空气）+ **只**在设置页那一处
    # （运行卡再退回去靠换行兜底，这两条会红）。
    funcs = [(fn.lineno, fn.end_lineno or fn.lineno, fn.name)
             for fn in ast.walk(TREE)
             if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))]

    def _func_of(node):
        hit = [f for f in funcs if f[0] <= node.lineno <= f[1]]
        return min(hit, key=lambda f: f[1] - f[0])[2] if hit else "?"

    wrap_in = sorted({_func_of(node) for node in _walk_calls("Row")
                      if _truthy(_kw(node, "wrap"))})
    check(f"扫到 {rows} 个 ft.Row，其中 {wraps} 个是换行的", wraps >= 1, "期望 >= 1")
    check(f"换行的 Row 只在设置页兜底那一处 {wrap_in}", set(wrap_in) == {"_build_settings"},
          "运行卡第一/二/三行是定宽分格，不该再靠换行兜底")
    check(f"{n_expand} 处 expand=True（其中 {len(expand_names)} 个落在 self.* 上）",
          n_expand >= 10 and len(expand_names) >= 5)
    print("PART 1 " + ("PASS" if not bad else "FAIL"))
    return not bad


# ------------------------------------------------------------ PART 2  输入框

DEPRECATED_FIELDS = ("border_color", "focused_border_color", "border_width",
                     "focused_border_width", "border_radius")


def part2():
    print("PART 2  输入框走 border=OutlineInputBorder，不用已废弃的字段")
    bad, n = [], 0
    for node in _walk_calls("TextField", "Dropdown", "TextFormField"):
        n += 1
        got = {k.arg for k in node.keywords}
        for d in DEPRECATED_FIELDS:
            if d in got:
                bad.append(f"{_where(node)} 用了已废弃的 {d}=")
        if "border" not in got:
            bad.append(f"{_where(node)} 没给 border=")

    check(f"扫到 {n} 个输入控件，全部用 border=、没有废弃字段", not bad and n >= 3,
          "；".join(bad))
    # `input_border` 只此一处产出，且真的按状态分了两种边框。
    src = ast.get_source_segment(SRC, next(
        (fn for fn in TREE.body
         if isinstance(fn, ast.FunctionDef) and fn.name == "input_border"), None) or ast.Pass())
    check("input_border 按 ControlState 分状态给边框",
          bool(src) and "ControlState.DEFAULT" in src and "ControlState.FOCUSED" in src)
    print("PART 2 " + ("PASS" if not bad else "FAIL"))
    return not bad and n >= 3


# --------------------------------------------------- PART 3  不写死视觉值

SPACING_KW = ("spacing", "run_spacing", "padding", "content_padding", "label_padding",
              "column_spacing", "horizontal_margin", "vertical_margin",
              "horizontal_spacing", "min_vertical_padding", "item_padding")
VISUAL_KW = ("radius", "border_radius", "elevation", "font_size", "icon_size",
             "stroke_width", "shadow_color", "bar_height")


def _uses_t_space(node):
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Subscript) and isinstance(sub.value, ast.Attribute)
                and sub.value.attr in ("SPACE", "SPACE_X")):
            return True
    return False


def _ok_spacing(node):
    """间距实参要么直接写 `T.SPACE[...]`，要么是变量/变量的组合（如 `ft.Padding(pad,…)`）。

    裸数字一律不行：`padding=16` 不是从标度表来的，改一次标度就漏掉它。
    """
    if _uses_t_space(node):
        return True
    names = any(isinstance(s, (ast.Name, ast.Attribute)) for s in ast.walk(node))
    numbers = any(isinstance(s, ast.Constant) and isinstance(s.value, (int, float))
                  for s in ast.walk(node))
    return names and not numbers


def part3():
    print("PART 3  视图层不写死视觉值")
    bad = []

    # (a) 十六进制色字面量
    for node in ast.walk(TREE):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value.strip().lower()
            if v.startswith("#") and len(v) in (4, 7, 9) and all(
                    c in "0123456789abcdef" for c in v[1:]):
                bad.append(f"{_where(node)} 写死了颜色 {node.value}")
    # (b) ft.Colors.*
    for node in ast.walk(TREE):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "ft" and node.attr == "Colors"):
            bad.append(f"{_where(node)} 用了 ft.Colors")
    # (c) 圆角/高程/字号不取裸数字（`T.PROGRESS_H // 2` 这种「自己厚度的一半」放行）
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        for k in node.keywords:
            if k.arg in VISUAL_KW and isinstance(k.value, ast.Constant) \
                    and isinstance(k.value.value, (int, float)):
                bad.append(f"{_where(node)} {k.arg}={k.value.value} 是裸数字")

    # (d) 每个间距实参都从 T.SPACE 取
    gaps, literal_gaps = 0, []
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        for k in node.keywords:
            if k.arg in SPACING_KW:
                gaps += 1
                if not _ok_spacing(k.value):
                    literal_gaps.append(f"{_where(node)} {k.arg}= 不是从 T.SPACE 取的")

    check("没有十六进制色字面量、没有 ft.Colors", not any(
        "写死了颜色" in b or "ft.Colors" in b for b in bad),
        "；".join(b for b in bad if "写死了颜色" in b or "ft.Colors" in b))
    check("圆角/高程/字号没有裸数字", not any("是裸数字" in b for b in bad),
          "；".join(b for b in bad if "是裸数字" in b))
    check(f"{gaps} 个间距实参全部从 T.SPACE 取", not literal_gaps, "；".join(literal_gaps))
    ok = not bad and not literal_gaps
    print("PART 3 " + ("PASS" if ok else "FAIL"))
    return ok


# ------------------------------------------------------ PART 4  规范表自洽

SPEC_TYPES = {
    "displayLarge": (57, 64, 400, -0.25), "displayMedium": (45, 52, 400, 0.0),
    "displaySmall": (36, 44, 400, 0.0), "headlineLarge": (32, 40, 400, 0.0),
    "headlineMedium": (28, 36, 400, 0.0), "headlineSmall": (24, 32, 400, 0.0),
    "titleLarge": (22, 28, 400, 0.0), "titleMedium": (16, 24, 500, 0.15),
    "titleSmall": (14, 20, 500, 0.1), "bodyLarge": (16, 24, 400, 0.5),
    "bodyMedium": (14, 20, 400, 0.25), "bodySmall": (12, 16, 400, 0.4),
    "labelLarge": (14, 20, 500, 0.1), "labelMedium": (12, 16, 500, 0.5),
    "labelSmall": (11, 16, 500, 0.5),
}
SPEC_SHAPE = {"none": 0, "extraSmall": 4, "small": 8, "medium": 12, "large": 16,
              "extraLarge": 28, "full": 999}
SPEC_ELEV = {"level0": 0, "level1": 1, "level2": 3, "level3": 6, "level4": 8, "level5": 12}
SPEC_STATE = {"hover": 0.08, "focus": 0.12, "pressed": 0.12, "dragged": 0.16,
              "disabled": 0.38, "disabled_container": 0.12}
# M3 里每一对「文字/图标色 : 它所在的底色」。`surface_variant` 这个角色在 2024 版规范里已经
# 没有了（换成 `surface_container*` 一族），所以 `on_surface_variant` 是按容器配的。
ON_PAIRS = (
    ("primary", "on_primary"), ("primary_container", "on_primary_container"),
    ("secondary", "on_secondary"), ("secondary_container", "on_secondary_container"),
    ("tertiary", "on_tertiary"), ("tertiary_container", "on_tertiary_container"),
    ("error", "on_error"), ("error_container", "on_error_container"),
    ("surface", "on_surface"), ("surface_bright", "on_surface"), ("surface_dim", "on_surface"),
    ("surface_container_lowest", "on_surface"), ("surface_container_low", "on_surface"),
    ("surface_container", "on_surface"), ("surface_container_high", "on_surface"),
    ("surface_container_highest", "on_surface"),
    ("surface_container_low", "on_surface_variant"),
    ("surface_container", "on_surface_variant"),
    ("surface_container_high", "on_surface_variant"),
    ("inverse_surface", "on_inverse_surface"), ("inverse_surface", "inverse_primary"),
    ("primary_fixed", "on_primary_fixed"), ("primary_fixed_dim", "on_primary_fixed"),
    ("primary_fixed", "on_primary_fixed_variant"),
    ("secondary_fixed", "on_secondary_fixed"), ("secondary_fixed_dim", "on_secondary_fixed"),
    ("secondary_fixed", "on_secondary_fixed_variant"),
    ("tertiary_fixed", "on_tertiary_fixed"), ("tertiary_fixed_dim", "on_tertiary_fixed"),
    ("tertiary_fixed", "on_tertiary_fixed_variant"),
)


def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def contrast(a, b):
    def lum(h):
        h = h.lstrip("#")
        return 0.2126 * _lin(int(h[0:2], 16)) + 0.7152 * _lin(int(h[2:4], 16)) \
            + 0.0722 * _lin(int(h[4:6], 16))
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def part4():
    print("PART 4  规范表自身自洽")
    check("字体阶梯 15 档，数值与规范逐格相同", dict(T.TYPES) == SPEC_TYPES,
          f"{len(T.TYPES)} 档")
    check("形状 7 档", dict(T.SHAPE) == SPEC_SHAPE, str(T.SHAPE))
    check("高程 6 级", dict(T.ELEVATION) == SPEC_ELEV)
    check("状态层 6 个不透明度", dict(T.STATE_OPACITY) == SPEC_STATE)
    check("间距全在 4dp 栅格上",
          all(v % 4 == 0 for v in T.SPACE.values()) and T.SPACE["none"] == 0)
    check("形状归属指向真实档位",
          all(v in T.SHAPE for v in T.SHAPE_ROLE.values()) and len(T.SHAPE_ROLE) >= 10)

    roles = tuple(T.ROLES)
    check(f"颜色角色 {len(roles)} 个", len(roles) == 46, "规范 baseline + surface 扩展")
    check("角色名无重复", len(set(roles)) == len(roles))
    check("浅深两套色板的键完全相同",
          set(T.SCHEMES["light"]) == set(T.SCHEMES["dark"]) == set(roles))

    def bad_hex(v):
        return not (isinstance(v, str) and len(v) == 7 and v[0] == "#"
                    and all(c in "0123456789abcdefABCDEF" for c in v[1:]))

    check("每一格都是合法的 #rrggbb",
          not any(bad_hex(v) for s in ("light", "dark") for v in T.SCHEMES[s].values()))
    check("扩展色名与角色名不冲突",
          not (set(T.EXT["light"]) & set(roles)), f"扩展 {len(T.EXT['light'])} 个")

    # 语义名 -> 角色：每一个都要取得到，打错一个名字当场 AttributeError
    bad_sem = []
    for app in ("light", "dark"):
        tk = T.Tokens(app)
        for name in T.SEMANTIC:
            try:
                getattr(tk, name)
            except AttributeError:
                bad_sem.append(f"{app}.{name}")
    check(f"{len(T.SEMANTIC)} 个语义名都能取到", not bad_sem, "；".join(bad_sem))

    unknown = sorted({n for pair in ON_PAIRS for n in pair} - set(roles))
    check("对比度表里的角色名都真实存在", not unknown, "；".join(unknown))
    worst = []
    for app in ("light", "dark"):
        for bg, fg in ON_PAIRS:
            r = contrast(T.SCHEMES[app][bg], T.SCHEMES[app][fg])
            worst.append((r, f"{app} {fg} on {bg}"))
    worst.sort()
    check(f"{len(worst)} 对 on_/底色对比度都 >= 4.5:1", worst[0][0] >= 4.5 - 0.05,
          "；".join(f"{n} {r:.2f}" for r, n in worst[:3]))

    check("偏离规范的地方逐条写了理由",
          len(T.DEVIATIONS) >= 2 and all(len(d) == 2 and len(d[1]) > 20
                                         for d in T.DEVIATIONS),
          f"{len(T.DEVIATIONS)} 条")
    ok = not FAILS
    print("PART 4 " + ("PASS" if ok else "FAIL"))
    return ok


# ---------------------------------------------------------- PART 5  截图像素

SHOTS = ("flet_start", "flet_log", "flet_history", "flet_settings",
         "flet_light_start", "flet_light_log", "flet_light_history", "flet_light_settings")
# `#C0C0C0`（Flutter ErrorWidget 的底色）盖在暗底上得到 `#b6b6b6`、浅底上 `#c4c4c4`。
GREY_LO, GREY_HI = 0xA8, 0xD0


def _greyish(c):
    r, g, b = c
    return abs(r - g) <= 3 and abs(g - b) <= 3 and GREY_LO <= r <= GREY_HI


def part5():
    print("PART 5  截图里没有那片灰，而且该有的确实在")
    try:
        from PIL import Image
    except ImportError:
        check("Pillow 可用", False)
        print("PART 5 FAIL")
        return False

    missing = [s for s in SHOTS if not os.path.exists(os.path.join(VIEW, s + ".png"))]
    if not check(f"八张截图都在（{len(SHOTS)} 张）", not missing, "；".join(missing)):
        print("PART 5 FAIL")
        return False

    ok = True
    for name in SHOTS:
        app = "light" if "_light_" in name else "dark"
        tk = T.Tokens(app)
        im = Image.open(os.path.join(VIEW, name + ".png")).convert("RGB")
        w, h = im.size
        raw = im.tobytes()  # `getdata()` 在 Pillow 14 会被删，`tobytes()` 更快也更稳
        cnt = Counter(zip(raw[0::3], raw[1::3], raw[2::3]))
        total = w * h
        grey = max((n for c, n in cnt.items() if _greyish(c)), default=0)
        flat = {f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}": n for c, n in cnt.items()}
        # 数的是「**一片**灰有多大」，不是灰像素的总和：结算表去掉难度底色之后，那些灰字
        # 在页面上留下上千 px 的孤立反锯齿像素（单色最多 33 px），按总和判会被文字骗。
        check(f"{name}: {w}x{h}，单色最大灰块 {grey} px（{100.0 * grey / total:.3f}%）",
              grey <= total * 0.001 and w >= 1200 and h >= 800)
        # 正向：页面底（`surface` —— 顶栏、导航轨、页脚用的是**同一个**角色，规范如此）与卡片
        # （`surface_container_low`）都在。从前这里量的是导航轨底色 `tk.card`；导航轨改成
        # `surface` 之后那条判据就退化成「量页面底」了 —— 换成这两条更直白，也不假装在量导轨。
        # **结算记录页例外**：它是整页的 DataTable，不是 `card()`（`_build_history` 返回裸
        # Container），那一页没有 `tk.card` 像素；它的正向判据在下面那三条里。
        surf = flat.get(tk.surface, 0)
        check(f"{name}: 页面底 {tk.surface} 占 {100.0 * surf / total:.1f}%", surf > total * 0.05)
        if not name.endswith("history"):
            card = flat.get(tk.card, 0)
            check(f"{name}: 卡片 {tk.card} 占 {100.0 * card / total:.1f}%",
                  card > total * 0.005)
        if name.endswith("history"):
            # 结算表真的画出来了：**1 px 的行间线与四边外框**（`outline_variant`）+ 行首竖条 +
            # 难度是**字色**（`tk.diff_letter`）。难度不再铺底色 —— 用户点掉的就是那一片红
            # （见 `flet_gui._hist_row`）。
            # 表头那一带**不能**再当正向证据：m12800 起表头底色就是官方 `header-container-color
            # = surface`，与页面底同色（从前抬一档 `surface_container_high`，抬出来的那条判据在
            # 改回官方值之后会红 —— 这正是 `fletviewcheck` 的 `DELTA=24` 量不到的那一类改动，
            # 见 `tools/probes/README.md`）。改成量那几条 1 px 线：11 条横线各约 1500 px、左右两条
            # 竖线各约 735 px，合计约 0.8%，阈值取 0.5%。
            lines = flat.get(tk.border, 0)
            chip = sum(flat.get(getattr(tk, k), 0)
                       for k in ("chip_ap", "chip_fc", "chip_np", "chip_err"))
            ink = sum(flat.get(tk.diff_letter(L), 0) for L in T.DIFF_LETTERS)
            check(f"{name}: 行间线与外框 {tk.border} 占 "
                  f"{100.0 * lines / total:.2f}%，行首竖条四色合计 {100.0 * chip / total:.2f}%，"
                  f"难度字色合计 {100.0 * ink / total:.2f}%",
                  lines > total * 0.005 and chip > total * 0.001 and ink > total * 0.001)
            # 反向：行底色**不再**是难度的容器色（从前 expert 那两档合计占 48.7%）
            bands = sum(flat.get(getattr(tk, k + s), 0)
                        for k in T.DIFF_KEYS for s in ("_container", "_container_dim"))
            check(f"{name}: 难度容器色（含 _dim）合计 {100.0 * bands / total:.3f}%",
                  bands <= total * 0.001)
        ok = ok and not FAILS
    print("PART 5 " + ("PASS" if not FAILS else "FAIL"))
    return not FAILS


# ---------------------------------------------------- PART 6  架构红线与对位

# 2026-10-10：`sel_song` / `sel_diff` 两个名字从名单里去掉 —— 它们是 `Panel` 上**从未被调用过**
# 的公开方法（全仓只有定义与这份名单），随「清死代码」一起删了 ⇒ 名单长度 58 → 56。
PARITY = (
    "_after_check", "_appearance_label", "_build_header", "_build_history",
    "_build_last_run", "_build_log", "_build_pick", "_build_run",
    "_build_settings", "_build_start", "_confirm_stop_round",
    "_build_run_card", "_follow_target", "_hist_row", "_notify_result", "_on_hist_select",
    "_open_dir", "_open_run_row", "_refresh_ap_marks", "_refresh_font_hint", "_render_diffs",
    "_save_appearance",
    "_save_autoclean", "_save_defaults", "_save_follow", "_save_font", "_save_motion",
    "_set_phase", "_sync_last_cards", "_sync_rail", "_toggle_desc", "_verify_target",
    "_write_line", "auto_clean",
    "cleanup_junk", "clear_log", "export_history", "force_kill", "load_history",
    "load_manifest", "on_song_select", "open_shot", "refresh_cfg_info", "refresh_data",
    "refresh_last_run", "refresh_policy", "refresh_start_state", "reload_songs",
    "restart_panel", "select_diff", "selected_chart_id", "set_hist_filter", "set_log_filter",
    "show_tab", "start_run", "update_tally",
)
PLACEHOLDERS = ("施工中", "TODO", "FIXME", "NotImplementedError", "pass  # 待")


def _methods(path, cls):
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return {f.name for f in node.body
                    if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return set()


def _imports(path):
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


def part6():
    print("PART 6  架构红线（全仓无 Qt）与功能对位")
    core_imp = _imports(os.path.join(TOOLS, "panel_core.py"))
    check("panel_core 不 import 任何 UI 框架",
          not (core_imp & {"tkinter", "customtkinter", "tksheet", "PySide6", "flet"}),
          repr(sorted(core_imp & {"tkinter", "customtkinter", "tksheet", "PySide6", "flet"})))
    fl_imp = _imports(SRC_PATH)
    check("flet_gui 不 import tkinter/PySide6",
          not (fl_imp & {"tkinter", "customtkinter", "tksheet", "PySide6"}))
    check("flet_gui 只用 panel_core 拿业务逻辑",
          "panel_core" in fl_imp and "m3_theme" in fl_imp)

    fl = _methods(SRC_PATH, "Panel")
    miss_fl = sorted(set(PARITY) - fl)
    check(f"{len(PARITY)} 个方法名 Flet 面板里都在（名单冻在这一关里，删名字当作弊）",
          not miss_fl and len(PARITY) == 56,
          f"缺 {miss_fl}；名单长度 {len(PARITY)}")

    # 全仓不许再有任何 Qt。查的是**会真的把 Qt 拉起来**的东西：
    #   ① `tools/` 下所有 .py（含探针自己）的 import —— `qt_theme` / `qt_motion` 这些名字
    #      之所以能直接 import，是因为 `panel_core` 把 `tools/` 插进了 `sys.path`；
    #   ② 旧 Qt 源文件与探针**不许还在**（被 import 到一半才发现少一层保护）；
    #   ③ `requirements.txt` 里不许还钉着 PySide6 —— 那会让新机器装上一整套 Qt。
    # 文档里提「Qt」不算残留（那是历史说明），把 Qt 拉起来才算。
    QT_MODULES = {"PySide6", "shiboken6", "shiboken", "qt_theme", "qt_motion",
                  "qt_history", "_qt_smoke"}
    dirty = []
    for base, _dirs, files in os.walk(TOOLS):
        if os.path.basename(base) == "__pycache__":
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(base, fn)
            try:
                got = _imports(p) & QT_MODULES
            except SyntaxError as ex:
                dirty.append(f"{os.path.relpath(p, ROOT)} 解析不了：{ex}")
                continue
            if got:
                dirty.append(f"{os.path.relpath(p, ROOT)} import {sorted(got)}")
    check("tools/ 下一个 .py 都不 import Qt 系模块", not dirty, "；".join(dirty))

    GONE = ["tools/gui.py", "tools/qt_theme.py", "tools/qt_history.py", "tools/qt_motion.py",
            "tools/_qt_smoke.py", "tools/probes/qtstyle.py", "tools/probes/qtviewcheck.py",
            "tools/probes/qtfont.py", "tools/probes/qtmotion.py", "tools/probes/panelqt.py",
            "tools/probes/palette.py", "evidence/view/qt_baselines",
            "evidence/view/font_aa_compare.png"]
    left = [p for p in GONE if os.path.exists(os.path.join(ROOT, p.replace("/", os.sep)))]
    check("旧 Qt 的源文件 / 探针 / 基线都不在了", not left, "；".join(left))
    shots = sorted(fn for fn in os.listdir(VIEW)
                   if fn.startswith("qt_") and fn.endswith(".png")) if os.path.isdir(VIEW) else []
    check("evidence/view 里没有 qt_*.png 的截图", not shots, "；".join(shots[:6]))
    req = io.open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read().lower()
    check("requirements.txt 里没有 PySide6", "pyside" not in req and "shiboken" not in req)

    hits = [p for p in PLACEHOLDERS if p in SRC]
    check("视图层没有留下占位标记", not hits, "；".join(hits))
    ok = not FAILS
    print("PART 6 " + ("PASS" if ok else "FAIL"))
    return ok


def _func_src(src, name, cls=None):
    """取某个函数（或某个类里的某个方法）的源码片段。找不到返回 None。

    `AsyncFunctionDef` 也算 —— PART 9 要取的那四个动画函数**全是 async**，
    只看 `FunctionDef` 会让那一关在量空气（这一条是被 PART 9 自己抓出来的）。
    """
    tree = ast.parse(src)
    kinds = (ast.FunctionDef, ast.AsyncFunctionDef)
    if cls:
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == cls:
                for f in node.body:
                    if isinstance(f, kinds) and f.name == name:
                        return ast.get_source_segment(src, f)
        return None
    for node in tree.body:
        if isinstance(node, kinds) and node.name == name:
            return ast.get_source_segment(src, node)
    return None


def part7():
    """选曲列表的契约。这一关是**实测**换来的：真语料下 `panel.songs` 曾经恒为 0。

    三件事凑成那个 bug：① `cat_box` 的选项从来没被 `cat_map` 填过（它一直只有占位的
    `("", "全部")`）；② `reload_songs` 把下拉框的值直接递给 `filtered_songs`；③
    `filtered_songs` 把 `cat is not None` 读作「bandId 必须等于它」，而下拉框的初值是空串
    （bandId 是 int）→ 一首都不剩。三条各自看着都合理，合起来是「面板第一帧起曲目列表就是
    空的」。六张截图基线也全都把空列表拍了进去 —— **像素比对发现不了「少了一整块」**。
    """
    print("PART 7  选曲列表的契约（分类下拉 → cat_map → filtered_songs）")
    reload_src = _func_src(SRC, "reload_songs", "Panel") or ""
    fill_src = _func_src(SRC, "_fill_cats", "Panel") or ""
    build_src = _func_src(SRC, "build", "Panel") or ""
    main_src = _func_src(SRC, "main") or ""

    check("分类下拉的选项由 cat_map 填", "cat_box.options =" in fill_src)
    check("build() 调了 _fill_cats()", "_fill_cats()" in build_src)
    check("重读数据重填分类并按 bandId 接回选择", _p_cat_refresh(TREE))
    check("reload_songs 按标签过 cat_map",
          "cat_map.get(" in reload_src,
          "" if "cat_map.get(" in reload_src else "没找到 cat_map.get(")
    check('不把空串当 bandId 直递（`cat_box.value or ""`）',
          'cat_box.value or ""' not in reload_src)
    check("build() 在页脚建好之后补写谱面库概况",
          "_set_status(self._lib_status)" in build_src)
    check("main() 用规范的窗口尺寸开窗",
          "page.window.width" in main_src and "T.WINDOW_DEFAULT" in main_src)

    import panel_core as core
    man = {"bands": [{"bandId": 1, "name": "B1"}],
           "songs": [{"musicId": i, "bandId": 1, "titleRomaji": f"S{i}", "title": f"曲{i}",
                      "difficulties": [{"chartId": f"00{i:02d}_01", "difficulty": "easy"}]}
                     for i in (1, 2, 3)]}
    all_songs = core.filtered_songs(man, "", None, set(), {}, set(), core.SORT_DEFAULT, False)
    empty = core.filtered_songs(man, "", "", set(), {}, set(), core.SORT_DEFAULT, False)
    check("cat=None 是「全部」（3 首都出来）", len(all_songs) == 3, f"{len(all_songs)} 首")
    check('cat="" 一首都不剩 —— 上面那条禁令就是它', len(empty) == 0, f"{len(empty)} 首")

    ok = not FAILS
    print("PART 7 " + ("PASS" if ok else "FAIL"))
    return ok


def part8():
    """交给 `ask()` 的回调必须是**同步**的。

    这一关是 `fletfly.py` 抓出来的真 bug 的静态那一半：`_on_window_event` 原来把协程方法
    `self._shutdown` 直接交给 `ask()`，而 `ask()` 的回调是按钮那一按里同步调用的 ——
    结果只造出一个**从未被 await 的协程**：窗不关、子进程也不收，正好是「关掉面板等于把一局
    留在后台继续往游戏里注触摸」那件事。行为那半边由 `fletfly.py` 的心跳判据盯着；这里把
    **同一类错误在别的调用点上**提前挡住（行为只走关窗那一条路）。
    """
    print("PART 8  交给 ask() 的回调不许是协程")
    tree = ast.parse(SRC)
    async_methods = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Panel":
            async_methods = {f.name for f in node.body if isinstance(f, ast.AsyncFunctionDef)}
    bad, n_ask = [], 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = (fn.attr if isinstance(fn, ast.Attribute)
                else fn.id if isinstance(fn, ast.Name) else None)
        if name not in ("ask", "_confirm_stop_round"):
            continue
        n_ask += 1
        # ask(page, tk, title, body, on_ok) → 下标 4；_confirm_stop_round(title, body, on_ok) → 2
        idx = 4 if name == "ask" else 2
        if len(node.args) > idx:
            a = node.args[idx]
            if (isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name)
                    and a.value.id == "self" and a.attr in async_methods):
                bad.append(f"{name}(..., self.{a.attr}) @ 第 {a.lineno} 行")
    check("没有被同步调用的协程回调", not bad, "；".join(bad))
    check("真的找到了 Panel 的 async 方法（否则上面在量空气）", len(async_methods) >= 2,
          f"{len(async_methods)} 个")
    check("真的扫到了回调式调用点（否则上面在量空气）", n_ask >= 8, f"{n_ask} 处")
    ok = not FAILS
    print("PART 8 " + ("PASS" if ok else "FAIL"))
    return ok


def part9():
    """动效：规范令牌 + 六处都受那个开关管 + 时长一律来自令牌。

    这一关是**行为**那一半（`fletfly.py` 量管道）之外的另一半：动画是客户端 Flutter 里的东西，
    Python 侧既看不见中间帧、也没有能采样的属性，所以这里量的是**规格**这一层 —— 而这正是
    「严格按规范」这句话唯一能被钉住的地方。

    四件事：
    ① 16 档时长令牌逐格等于规范（探针自带一份独立抄写的表，不是从代码里读回来的）；
    ② 7 档缓动都在，且逐点相等的那一档确实是 `EASE_IN_OUT_CUBIC_EMPHASIZED`（其余是近似，
       已经记在 `DEVIATIONS` 里）；六个装置的档位名都取得到；
    ③ `MOTION` 的七个档位恰好就是 page_out / page / progress / phase / flash / card / card_out
       （名单冻在这一关里；以前是拿 Qt 那份 `DUR` 对名字，Qt 删掉后改成字面量）。
       这七个档位覆盖六个装置（「卡片进出场」分进出两档：进场 `card` 用 decelerate、
       退场 `card_out` 用 accelerate，照规范「Easing and duration」那张表的成对规定），
       少一个就有一处动效被漏掉；
    ④ 六处现场（`show_tab` / `_set_progress` / `_set_phase` / `_hist_upsert` / `_apply_window_class` /
       `_set_hint`）都真的过 `self._motion()`，而且面板里每一个 `asyncio.sleep(...)` 的时长都从 `T.motion_ms` 取
       （不许再出现 `1.4` 这种数字 —— 这一条正是把 `_flash_tick` 从「一秒多」改成
       「extended1 = 700 ms」时立的）。

    **牙**：把任一时长令牌改一格、把 `_set_phase` 里的 `self._motion()` 去掉、或把某处
    `asyncio.sleep(T.motion_ms(...))` 换回字面量，都各有一条会 FAIL。
    """
    print("PART 9  动效（规范令牌 + 开关 + 无字面量时长）")
    # ① 规范逐格抄在这里，不从 m3_theme 读回来 —— 否则探针只是在照镜子
    spec = {"short": (50, 100, 150, 200), "medium": (250, 300, 350, 400),
            "long": (450, 500, 550, 600), "extended": (700, 800, 900, 1000)}
    bad = []
    for fam, vals in spec.items():
        for k, want in enumerate(vals, start=1):
            got = T.MOTION_DURATION.get(f"{fam}{k}")
            if got != want:
                bad.append(f"{fam}{k}: {got} != {want}")
    check("16 档时长令牌逐格等于规范", not bad, "；".join(bad))
    check("时长阶梯单调（short < medium < long < extended）",
          all(spec[a][-1] < spec[b][0] for a, b in (("short", "medium"), ("medium", "long"),
                                                    ("long", "extended"))))

    # ② 缓动
    want_ease = {"emphasized": ft.AnimationCurve.EASE_IN_OUT_CUBIC_EMPHASIZED,
                 "emphasized_decelerate": ft.AnimationCurve.EASE_OUT_CUBIC,
                 "emphasized_accelerate": ft.AnimationCurve.EASE_IN_CUBIC,
                 "standard": ft.AnimationCurve.EASE_IN_OUT,
                 "standard_decelerate": ft.AnimationCurve.EASE_OUT,
                 "standard_accelerate": ft.AnimationCurve.EASE_IN,
                 "linear": ft.AnimationCurve.LINEAR}
    check("7 档缓动令牌都在，而且那一档逐点相等的就是 emphasized",
          T.MOTION_EASING == want_ease,
          "；".join(f"{k}: {getattr(T.MOTION_EASING.get(k), 'name', T.MOTION_EASING.get(k))} "
                    f"!= {v.name}" for k, v in want_ease.items() if T.MOTION_EASING.get(k) != v))
    bad = [n for n, (d, e) in T.MOTION.items()
           if d not in T.MOTION_DURATION or e not in T.MOTION_EASING]
    check("六个装置的档位名都取得到", not bad, "；".join(bad))
    check("缓动的近似已经写进 DEVIATIONS（知情偏离）",
          any("缓动" in t for t, _ in T.DEVIATIONS))

    # ③ 七个档位名冻在这里（不从 m3_theme 读回来）：名字被改动就说明有一处漏掉了，
    #    而「六个装置各自动哪一处」是面板与规范之间唯一的一份契约 —— 其中「卡片进出场」这一处
    #    分进出两档（`card` / `card_out`），所以档位比装置多一个。
    check("MOTION 的七个档位恰好就是 page_out / page / progress / phase / flash / card / card_out",
          set(T.MOTION) == {"page_out", "page", "progress", "phase", "flash", "card", "card_out"},
          f"实测 {sorted(T.MOTION)}")
    # 进场用 decelerate、退场用 accelerate —— 规范「Easing and duration」那张表的成对规定
    # （emphasized decelerate 400 ms「enter the screen」／emphasized accelerate 200 ms「exit the screen」）。
    # 退场还**不许比进场慢**：离开比进来还拖沓就是把那一对用反了。
    check("进场的 decelerate 与退场的 accelerate 成对，且退场不比进场慢",
          T.MOTION["card"][1] == "emphasized_decelerate"
          and T.MOTION["card_out"][1] == "emphasized_accelerate"
          and T.MOTION_DURATION[T.MOTION["card_out"][0]]
          <= T.MOTION_DURATION[T.MOTION["card"][0]],
          f"{T.MOTION['card']} / {T.MOTION['card_out']}")
    # 换页那一对（官方 fade-through 的 30/70 分界）：旧页淡出 + 新页淡入合计必须还是 300 ms
    # （medium2 = 从前那一档的总时长），而且「先出后进」的档位不能反 —— 反了就是新页先亮起来。
    check("换页两拍 = 100 + 200 = 300 ms（与从前那一档同长），而且是先出后进",
          T.MOTION_DURATION[T.MOTION["page_out"][0]]
          + T.MOTION_DURATION[T.MOTION["page"][0]] == 300
          and T.MOTION_DURATION[T.MOTION["page_out"][0]] < T.MOTION_DURATION[T.MOTION["page"][0]]
          and T.MOTION["page_out"][1] == "emphasized_accelerate"
          and T.MOTION["page"][1] == "emphasized_decelerate",
          f"{T.MOTION['page_out']} + {T.MOTION['page']}")
    check("新页起始缩放 PAGE_SCALE_IN = 0.92（官方 fade-through 的 _scaleIn）",
          0.0 < T.PAGE_SCALE_IN < 1.0 and abs(T.PAGE_SCALE_IN - 0.92) < 1e-9,
          repr(T.PAGE_SCALE_IN))

    # ④ 现场
    sites = ("show_tab", "_set_progress", "_set_phase", "_hist_upsert",
             "_apply_window_class", "_set_hint")
    missing = [n for n in sites if "_motion()" not in (_func_src(SRC, n, "Panel") or "")]
    check("六处现场都过 self._motion()", not missing, "；".join(f"{n} 没这道闸" for n in missing))
    # 九处动画函数里所有 asyncio.sleep 的时长都从令牌取（不许再出现 `1.4` 这种数字 ——
    # 这一条正是把 `_flash_tick` 从「一秒多」改成「extended1 = 700 ms」时立的）。
    # **只管这九个函数**：`restart_panel.bye()` 里那个 `sleep(0.3)` 是「让新面板先起来再关自己」
    # 的进程交接延时，与动效无关，不该被这条规则连坐。
    anim_fns = ("_fade_page", "_fade_in", "_fade_reflow", "_fade_box_back", "_fade_out_card",
                "_fade_out_row", "_tween_progress", "_fade_phase", "_flash_tick")
    lit = []
    for name in anim_fns:
        seg = _func_src(SRC, name, "Panel")
        if seg is None:
            lit.append(f"{name} 找不到")
            continue
        for node in ast.walk(ast.parse(seg)):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if (isinstance(fn, ast.Attribute) and fn.attr == "sleep"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                lit.append(f"{name} 里 sleep({node.args[0].value!r})")
    check("九个动画函数里没有写死时长的 sleep（一律走 T.motion_ms）", not lit, "；".join(lit))
    check("真的扫到了这九个函数（否则上面在量空气）",
          all(_func_src(SRC, n, "Panel") for n in anim_fns))
    # `_motion()` 的默认口径：缺键 / 写坏都当开
    try:
        import types as _t  # noqa: PLC0415
        import flet_gui as G  # noqa: PLC0415
        probe = G.Panel
        got = [probe._motion(_t.SimpleNamespace(state=s)) for s in
               ({}, {"motion": 1}, {"motion": 0}, {"motion": "x"}, {"motion": None})]
        check("_motion() 的口径：缺键 / 写坏都当开，只有明确写 0 才是关",
              got == [True, True, False, True, True], f"实测 {got}")
    except Exception as ex:                                     # noqa: BLE001
        check("能 import flet_gui 并直接问 _motion()", False, f"{type(ex).__name__}: {ex}")
    ok = not FAILS
    print("PART 9 " + ("PASS" if ok else "FAIL"))
    return ok


# ------------------------------------------- PART 10  采图工具自己的闸门

def part10():
    print("PART 10  `_flet_smoke.audit()` 认得出坏图（给出口早闸装牙）")
    try:
        import _flet_smoke as SMOKE
        from PIL import Image
    except ImportError as ex:                                    # noqa: BLE001
        check("Pillow 与 `_flet_smoke` 都能 import", False, f"{type(ex).__name__}: {ex}")
        print("PART 10 FAIL")
        return False

    def shot(name):
        with io.open(os.path.join(VIEW, name + ".png"), "rb") as fh:
            return fh.read()

    missing = [s for s in SHOTS if not os.path.exists(os.path.join(VIEW, s + ".png"))]
    if not check(f"八张截图都在（{len(SHOTS)} 张）", not missing, "；".join(missing)):
        print("PART 10 FAIL")
        return False

    # ① 真图必须全部放行 —— 卡在真图上的闸门是坏闸门
    verdicts = {s: SMOKE.audit(shot(s)) for s in SHOTS}
    check("八张真图全部放行", not any(verdicts.values()),
          "；".join(f"{k}: {v}" for k, v in verdicts.items() if v))

    src = Image.open(os.path.join(VIEW, "flet_history.png")).convert("RGB")
    w, h = src.size
    x0, y0, x1, y1 = SMOKE.BODY_BOX

    # ② 早闸必须严于 PART 5 那个 0.1%，否则两处判据会各说各话
    p5 = w * h * 0.001
    check(f"灰预算 {SMOKE.ERROR_GREY_BUDGET} px 严于 PART 5 的 0.1%（{p5:.0f} px）",
          SMOKE.ERROR_GREY_BUDGET < p5)
    check(f"内容区 {SMOKE.BODY_BOX} 落在 {w}x{h} 里面", 0 < x0 < x1 <= w and 0 < y0 < y1 <= h)

    # ③ 空白帧（整块内容区一个颜色）必须被拦住
    blank = src.copy()
    blank.paste(Image.new("RGB", (x1 - x0, y1 - y0), (0x12, 0x13, 0x18)), (x0, y0))
    buf = io.BytesIO()
    blank.save(buf, "PNG")
    msg = SMOKE.audit(buf.getvalue())
    check("整块内容区涂成底色（空白页的样子）→ 拦住", bool(msg) and "内容区" in (msg or ""),
          f"判词：{msg}")

    # ④ Flutter 的 ErrorWidget 异常灰必须被拦住（α=0.943 的 #C0C0C0 就是量出来的那层）
    a = 0.943
    grey = Image.new("RGB", (w, h), (0xC0, 0xC0, 0xC0))
    over = Image.blend(src, grey, a)
    buf = io.BytesIO()
    over.save(buf, "PNG")
    msg = SMOKE.audit(buf.getvalue())
    check("整块界面被异常灰顶掉 → 拦住", bool(msg) and "异常灰" in (msg or ""), f"判词：{msg}")

    # ⑤ 合成一片**孤立**的反锯齿灰字 → 必须放行。这一条是给 2026-10-05 那次假阳性立的规矩：
    # 去掉结算表的难度底色之后，历史页的灰字留下 1628 px 孤立反锯齿像素（单档最多 33 px），
    # 按「近似灰像素的总和」判会拦下一张好图；按「一片灰有多大」判就不会。
    aa = src.copy()
    px = aa.load()
    for k in range(60):                                   # 60 档色阶，摊在那一带亮度里
        shade = 0xA8 + k
        for j in range(40):                               # 每档只有 40 px，连不成片
            px[(320 + (k * 17 + j * 347) % 1400, 90 + (k * 23 + j * 41) % 940)] = (shade, shade, shade)
    buf = io.BytesIO()
    aa.save(buf, "PNG")
    msg = SMOKE.audit(buf.getvalue())
    check("2400 px 孤立的反锯齿灰字（60 档色阶各 40 px）→ 放行", msg is None, f"判词：{msg}")

    # ⑥ 采图工具本身的静态契约：孪生帧守卫还在，等待时间没被调回 0.7
    sm = io.open(os.path.join(TOOLS, "_flet_smoke.py"), encoding="utf-8").read()
    check(f"孪生帧守卫还在（SETTLE = {SMOKE.SETTLE}s，0.8s 会拍到空页）",
          SMOKE.SETTLE >= 1.0 and "逐字节相同" in sm and "SHOOT-FAIL" in sm,
          f"SETTLE={SMOKE.SETTLE}")

    # ⑦ 采图工具的 `--appearance both`（2026-10-05 加的，分档验证里「只重拍变了的那一页」靠它
    # 一趟拍完两套）：换外观必须**重建面板** —— 颜色是建控件的时候就从 token 取走的，只改
    # `theme_mode` 只会让 Flutter 自己那层主题变、已经建好的控件还挂着旧色；而「上一张图」
    # 要**跨外观**传下去，否则「浅色那张与暗色那张逐字节相同」这种失败抓不到（同一个外观内部
    # 比对本来就抓不到「外观根本没切过去」）。
    def both_ready(text):
        return ('"both"' in text and "def shoot_pass(" in text
                and "page.clean()" in text and "跨外观" in text)

    check("采图工具能一个进程拍两套主题（both + 重建面板 + 跨外观比对）",
          both_ready(sm), "缺 `--appearance both`、重建面板那一步、或跨外观的孪生帧比对")
    check("上一条不是装饰（把 both 抹掉，同一个谓词必须变假）",
          not both_ready(sm.replace('"both"', '"no"')),
          "谓词对坏源码也是真的 —— 这条判据是装饰")

    ok = not FAILS
    print("PART 10 " + ("PASS" if ok else "FAIL"))
    return ok

# --------------------------------------------------- PART 11  精致度那一轮

THEME_PATH = os.path.join(TOOLS, "m3_theme.py")
THEME_SRC = io.open(THEME_PATH, encoding="utf-8").read()
THEME_TREE = ast.parse(THEME_SRC)

# 组件级主题：只数 Flet 1.0.3 里**存在**的那些（`FilledTonalButtonTheme` / `MenuTheme` /
# `InputDecorationTheme` 在 1.0.3 里没有，照 Flutter 的名字写会 AttributeError）。
THEME_KW = ("appbar_theme", "navigation_rail_theme", "card_theme", "dialog_theme",
            "snackbar_theme", "chip_theme", "list_tile_theme", "popup_menu_theme",
            "divider_theme", "progress_indicator_theme", "scrollbar_theme", "tooltip_theme",
            "icon_button_theme", "filled_button_theme", "outlined_button_theme",
            "text_button_theme",
            "segmented_button_theme")

# 主题层里**允许**出现的裸数字。其余一切（颜色角色、字阶、形状半径、高程、间距、密度）都必须
# 从令牌属性（`tk.*`）或规范标度（`ELEVATION` / `SHAPE_ROLE` / `SPACE` / `PROGRESS_H` …）里取。
# 每一项都写着出处；想往主题层塞一个新数字，就得先在这里把它的规范出处写出来 —— 抄不到出处的，
# 登记到 `m3_theme.DEVIATIONS` 去。字符串同理：必须是规范标度里真有的名字（`radius("cardd")`
# 这种手滑会在这一条上变假）。
THEME_LITERALS = {
    0: "0dp：chip 内边距的上下分量（官方 chip 的 content-padding 只给左右各 8）",
    1: "1dp：divider 厚度（`_md-comp-divider.scss` 的 `height = 1px`）"
       "、chip 描边宽度（chip `outline-width = 1dp`）",
    -1.0: "Flutter `NavigationRail.groupAlignment` 的默认值（不是规范数，是框架默认）",
    True: "`use_material3 = True` 是开关，不是尺寸",
}
THEME_NAMES = (set(T.SHAPE_ROLE) | set(T.SHAPE) | set(T.TYPES) | set(T.ELEVATION)
               | set(T.SPACE) | set(T.STATE_OPACITY))


def _dotted(node):
    # `tk.danger` -> "tk.danger"
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _func(tree, name):
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == name:
            return fn
    return None


def _p_empties(tree):
    # 三张空态都真的建出来了，而且 empty_state 是「居中的图标 + 字」，不是贴左上角的一行灰字。
    made = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "empty_state"):
            made |= {_name_of(t) for t in node.targets if _name_of(t)}
    if not {"song_empty", "hist_empty", "log_empty"} <= made:
        return False
    fn = _func(tree, "empty_state")
    if fn is None:
        return False
    icon = any(_ft_call(n, "Icon") for n in ast.walk(fn))
    # 「居中」这件事要认**外面那个** Container（`alignment=CENTER` + `expand=True` 是它的签名）：
    # 只数 `.Alignment.CENTER` 出现过的写法，会被空态图标那枚圆盘的居中顺手满足（A3 之后它自己
    # 也有一个 CENTER），于是这颗牙咬不动了。
    center = any(isinstance(n, ast.Call) and _dotted(n.func) == "ft.Container"
                 and _dotted(_kw(n, "alignment")) == "ft.Alignment.CENTER"
                 and getattr(_kw(n, "expand"), "value", False) is True
                 for n in ast.walk(fn))
    return icon and center


def _p_empty_toggle(tree):
    # 空态不是画上去就没管：结算与日志都得在「有数据 / 没数据」之间真的切 visible。
    # 两种写法都算：直接写 `self.X.visible = not empty`，或者走统一入口
    # `self._toggle_empty(self.X, empty)`（带淡入的那一版，m05361 起三处空态都换成了它）。
    want = {("_render_history", "hist_box"), ("_render_history", "hist_empty"),
            ("_refresh_log_info", "log_view"), ("_refresh_log_info", "log_empty")}
    got = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and len(n.targets) == 1:
                t = n.targets[0]
                if (isinstance(t, ast.Attribute) and t.attr == "visible"
                        and isinstance(t.value, ast.Attribute)
                        and isinstance(t.value.value, ast.Name)
                        and t.value.value.id == "self"):
                    got.add((fn.name, t.value.attr))
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "_toggle_empty" and n.args):
                a0 = n.args[0]
                if (isinstance(a0, ast.Attribute) and isinstance(a0.value, ast.Name)
                        and a0.value.id == "self"):
                    got.add((fn.name, a0.attr))
    return want <= got


def _p_log_tools(tree):
    # 自动滚动开关、它真去改 log_view.auto_scroll、导出走 save_log。
    ctl = bind = False
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1:
            if _name_of(n.targets[0]) == "log_autoscroll":
                ctl = True
            t = n.targets[0]
            if (isinstance(t, ast.Attribute) and t.attr == "auto_scroll"
                    and isinstance(t.value, ast.Attribute) and t.value.attr == "log_view"):
                bind = True
    fn = _func(tree, "_build_log")
    export = fn is not None and any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "save_log"
        for n in ast.walk(fn))
    return ctl and bind and export


def _shortcut_decl(tree):
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Tuple)
                and any(isinstance(t, ast.Name) and t.id == "SHORTCUTS" for t in n.targets)):
            out = []
            for el in n.value.elts:
                if isinstance(el, ast.Tuple) and el.elts \
                        and isinstance(el.elts[0], ast.Constant):
                    out.append(el.elts[0].value)
            return out
    return []


# 清单上写的是给人看的箭头字形，`_on_key` 认的是 Flutter 的 `keyLabel` 拼写
# （见 `tools/flet_gui.py` 的 `KEY_UP` 上面那段）。
_SHORTCUT_GLYPH = {"\u2191": "Arrow Up", "\u2193": "Arrow Down",
                   "\u2190": "Arrow Left", "\u2192": "Arrow Right"}


def _shortcut_need(decl):
    # 把清单里那行人话拆成 `_on_key` 里真会命中的键。
    need = set()
    for d in decl:
        if "+" in d:
            need |= {p.strip() for p in d.split("+", 1)[1].split("/")}
        elif d == "Esc":
            need |= {"Escape", "Esc"}
        else:
            need.add(d)
    return {_SHORTCUT_GLYPH.get(x, x) for x in need}


def _membership_names(fn):
    """`_on_key` 里 `key in NAME` 这种比较右边的模块级名字（`KEY_UP` 那三个）。"""
    return {c.comparators[0].id for c in ast.walk(fn)
            if isinstance(c, ast.Compare) and len(c.comparators) == 1
            and isinstance(c.comparators[0], ast.Name)
            and any(isinstance(op, ast.In) for op in c.ops)}


def _module_strs(tree, names):
    """模块级 `NAME = ("…", …)` 里的字符串字面量。"""
    out = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id in names
                and isinstance(n.value, (ast.Tuple, ast.List))):
            out |= {e.value for e in n.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return out


def _p_shortcuts(tree):
    # 弹窗念的就是真管用的那几个：清单拆出来的键，`_on_key` 得全接得住。
    # 「接得住」= 函数体里的字符串字面量 **加上** 它 `key in NAME` 比较到的那些模块级元组
    # 里的字面量 —— 方向键与回车走 `KEY_UP`/`KEY_DOWN`/`KEY_ENTER`（一个键收几种拼写），
    # 只数函数体字面量会把它们误判成「没人接」。
    decl = _shortcut_decl(tree)
    if not decl:
        return False
    fn = _func(tree, "_on_key")
    if fn is None:
        return False
    handled = {n.value for n in ast.walk(fn)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    handled |= _module_strs(tree, _membership_names(fn))
    need = _shortcut_need(decl)
    return bool(need) and need <= handled


def _p_danger(tree):
    # 破坏性确认按钮是**文字档 + error 字色**（对话框的动作就是文字按钮；铺底/描边会把它抬成
    # outlined），且确认框的调用点真的带 danger=True。
    styled = False
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Attribute)
                and n.targets[0].attr == "style"
                and isinstance(n.targets[0].value, ast.Name)
                and n.targets[0].value.id == "confirm"
                and isinstance(n.value, ast.Call) and _ft_call(n.value, "ButtonStyle")
                and _kw(n.value, "bgcolor") is None
                and "tk.danger" in ast.unparse(n.value)):
            styled = True
    sites = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Call)
                for k in n.keywords if k.arg == "danger" and _truthy(k.value))
    return styled and sites >= 3


def _p_cat_refresh(tree):
    """重读数据之后分类下拉框必须重填，并按 bandId 把选中项接回来（用户 m28348）。

    选项的 key 是**带计数的标签**（"Ave Mujica（24）"），清单一变标签就跟着变。`refresh_data`
    从前只 `load_manifest()` + `reload_songs()`，下拉框里剩的还是旧标签 ⇒ 下一句
    `cat_map.get(旧标签)` 拿到 None ⇒ 筛选静默退回「全部」—— 用户看到的就是
    「Mujica 筛选不起作用」（面板活过了一次联网更新）。所以三件事一起查：选项重填、
    认 `keep` 参数、并且在**换表之前**把选中项译成 bandId。
    """
    fill = _func(tree, "_fill_cats")
    ref = _func(tree, "refresh_data")
    if fill is None or ref is None:
        return False
    fsrc = ast.unparse(fill)
    rsrc = ast.unparse(ref)
    keep_at = rsrc.find("keep = self.cat_map.get(")
    load_at = rsrc.find("self.load_manifest()")
    return ("cat_box.options =" in fsrc
            and "v == keep" in fsrc
            and "_fill_cats(keep=" in rsrc
            and 0 <= keep_at < load_at)


def _p_jackets(tree):
    # 选曲行 leading 走 song_leading；封面路径有缓存（os.path.exists）；摘要卡的封面槽
    # `c["art"]` 由 `_set_card_art` 换（m05361 起两张卡的封面都走它），`refresh_last_run`
    # 负责把「记录里的歌名」过清单换成 `jacket_src(...)` 再交进去。
    lead = any(isinstance(k, ast.keyword) and k.arg == "leading"
               and isinstance(k.value, ast.Call) and isinstance(k.value.func, ast.Name)
               and k.value.func.id == "song_leading"
               for n in ast.walk(tree) if isinstance(n, ast.Call) for k in n.keywords)
    js = _func(tree, "jacket_src")
    cached = js is not None and any(_dotted(n) == "os.path.exists" for n in ast.walk(js))
    # 缓存只许记「有」（用户 m28348）：从前是 `_JACKETS[key] = p if os.path.exists(p) else None`，
    # 于是「这一帧还没下下来」的那首歌会把 None 钉死在缓存里，新歌永远只显示兜底图标。
    jsrc = ast.unparse(js) if js is not None else ""
    nocache = "_JACKETS[key] = p" in jsrc and "p if os.path.exists(p) else None" not in jsrc
    rr = _func(tree, "refresh_last_run")
    setter = _func(tree, "_set_card_art")

    def _art_slot(t):
        # `self.last_art.content` 或摘要卡那本字典的 `c["art"].content`（改两张卡之后是后者）。
        if not isinstance(t, ast.Attribute) or t.attr != "content":
            return False
        v = t.value
        if isinstance(v, ast.Attribute):
            return v.attr == "art"
        return (isinstance(v, ast.Subscript) and isinstance(v.slice, ast.Constant)
                and v.slice.value == "art")

    # 槽里真的写过 `jacket_art(...)`（在 `_set_card_art` 里 —— 三个入口共用它）。
    art = setter is not None and any(
        isinstance(n, ast.Assign) and len(n.targets) == 1
        and _art_slot(n.targets[0])
        and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "jacket_art"
        for n in ast.walk(setter))
    # 刷新那条路上真的去清单里查封面：`refresh_last_run` 把 `jacket_src(song_music_id(...))`
    # 交给 `_set_card_art`。否则空记录那一支的 `_set_card_art(c, None)` 一个人就能点亮判据。
    src = rr is not None and any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_set_card_art"
        and any(isinstance(a, ast.Call) and isinstance(a.func, ast.Name)
                and a.func.id == "jacket_src" for a in n.args)
        for n in ast.walk(rr))
    return lead and cached and art and src and nocache


def _p_toast(tree):
    # `toast()` 从前是死代码（全仓只有定义处）。现在它得在几个真会出事的地方说话。
    callers = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "toast"
                for n in ast.walk(fn)):
            callers.add(fn.name)
    return {"save_log", "export_history", "cleanup_junk", "_save_appearance"} <= callers


def _p_themes(tree):
    # 组件级主题：连 Flet 自己建的控件（下拉菜单、滚动条、工具提示、对话框按钮）都落在 token 上。
    kw = set()
    for n in ast.walk(tree):
        if _ft_call(n, "Theme"):
            kw |= {k.arg for k in n.keywords if k.arg}
    return set(THEME_KW) <= kw


def _p_theme_values(tree):
    """主题层的**值**：`_p_themes` 只数「17 张主题都在」（键存在），这一条数它们身上写的是什么。

    规则两条，都对着 `m3_theme` 的规范标度：
      ① 数字/真假常量只许是 `THEME_LITERALS` 里登记过的（divider 厚度与 chip 描边的 1dp、chip
         内边距的 0、Flutter `groupAlignment` 默认 -1.0、`use_material3=True`）；
      ② 字符串只许是规范标度里真有的名字 —— 形状档/组件名（`SHAPE` / `SHAPE_ROLE`）、字阶
         （`TYPES`）、高程档（`ELEVATION`）、间距档（`SPACE`）、状态名（`STATE_OPACITY`）。
    于是主题层手写一个 `#141218`、或者把 `radius("card")` 手滑成 `radius("cardd")`，都会当场变假；
    反过来，任何新加的手挑值都必须先拿到规范出处、登记进 `THEME_LITERALS`，才有地方落脚。
    """
    call = None
    for n in ast.walk(tree):
        if _ft_call(n, "Theme"):
            call = n
            break
    if call is None:
        return False
    nums, strs = set(), set()
    for n in ast.walk(call):
        if isinstance(n, ast.Constant):
            v = n.value
            if isinstance(v, bool) or isinstance(v, (int, float)):
                nums.add(v)
            elif isinstance(v, str):
                strs.add(v)
        elif (isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub)
              and isinstance(n.operand, ast.Constant)
              and isinstance(n.operand.value, (int, float))):
            nums.add(-n.operand.value)     # `-1.0` 在 AST 里是 `UnaryOp(USub, Constant(1.0))`
    if not nums <= set(THEME_LITERALS):
        return False
    return strs <= THEME_NAMES


def _calls(fn, dotted):
    """`fn` 里有没有一处调用 `dotted`（名字按 `_dotted` 那套点号写）。"""
    return any(isinstance(n, ast.Call) and _dotted(n.func) == dotted for n in ast.walk(fn))


def _p_feedback(tree):
    # 审查报告 A1 / A2 / A7：视图层不许「按下去什么都不说」。
    #   ① 忙的时候 F5 与「开始演奏」走 `start_run` 的 busy 分支 —— 那句 snackbar 收在
    #      `_busy_notice()` 里（单人页与多人页共用，用户 m02832 的多人页也是同一个忙法），
    #      所以两个方法都得喊它、它自己得真说话；
    #   ② 「本轮停止」走 `stop_run`：先 `stop_graceful`，再把状态行与 snackbar 说出来；
    #   ③ 「强制终止」在确认回调里同样要说话，并把四个按钮的启用态刷一遍。
    run = _func(tree, "start_run")
    multi = _func(tree, "start_multi_run")
    busy = _func(tree, "_busy_notice")
    stop = _func(tree, "stop_run")
    kill = _func(tree, "force_kill")
    if run is None or multi is None or busy is None or stop is None or kill is None:
        return False
    return (_calls(busy, "toast")
            and _calls(run, "self._busy_notice")
            and _calls(multi, "self._busy_notice")
            and _calls(stop, "self.core.stop_graceful")
            and _calls(stop, "self._set_phase")
            and _calls(stop, "toast")
            and _calls(kill, "self._set_phase")
            and _calls(kill, "toast")
            and _calls(kill, "self.refresh_start_state"))


def _p_phase_colors(tree):
    # 审查报告 A3 / A4：整屏只有页脚那一行说「现在在干什么」，所以颜色必须按状态分开 ——
    # 从前「等待下一轮 …」与「倒计时 …」都落到最后的 `else`，和「演奏中」同色。
    fn = _func(tree, "_set_phase")
    if fn is None:
        return False
    body = ast.unparse(fn)
    return all(s in body for s in ("ALL", "tk.ok", "失败", "错误", "异常", "tk.danger",
                                   "空闲", "已停止", "更新", "等待", "tk.text_dim",
                                   "倒计时", "tk.warn", "tk.accent"))


def _p_footer_src(tree):
    # 审查报告 P1-③：页脚那句谱面库概况只有一个出处 —— `_set_status`。`load_manifest()`（含
    # `refresh_data()` 走过来那条路）重算完必须自己回写一次，否则 Ctrl+R 之后页脚一直念旧数。
    fn = _func(tree, "load_manifest")
    return fn is not None and _calls(fn, "self._set_status")


def _p_update(tree):
    # 用户 m06894：设置页的「资源更新」整组不见了（Tk 版就有，面板全面转 PySide6 时被删）。
    # 这一条只钉视图层那一链：按钮 → `start_update()` → `core.update_charts()`；core 那半边
    # （两个工具名 / 两条事件名 / busy 守卫）在 `fletpanel.py` 第 10 关钉，这个探针看不到它。
    bs = _func(tree, "_build_settings")
    su = _func(tree, "start_update")
    ru = _func(tree, "_run_update")
    if bs is None or su is None or ru is None:
        return False
    src = ast.unparse(bs)
    ru_src = ast.unparse(ru)
    return ("self.update_btn" in src and "self.force_chk" in src
            and "self.res_hint" in src
            and "self.source_box" in src and "self.verify_chk" in src
            and _calls(bs, "self.start_update")
            and _calls(bs, "self._refresh_res_hint")
            and "self._save_source" in src
            and not _calls(su, "ask") and _calls(su, "self._run_update")
            and "self.force_chk.value" in ru_src and "self.verify_chk.value" in ru_src
            and "preferred_source" in ru_src
            and _calls(ru, "self.core.update_charts"))


def _p_update_tail(tree):
    # 用户 m07179：`charts_done` 是更新链路的终点，收尾必须 `refresh_start_state()` —— 更新期间
    # 那四个起点按钮是按「忙」那一版重排的，不收尾「开始演奏」会一直是灰的。同一函数里
    # `("done", None)` 那支本来就调一次，所以要求至少两处。
    fn = _func(tree, "_on_message")
    if fn is None:
        return False
    body = ast.unparse(fn)
    if "charts_done" not in body:
        return False
    # 只看 `charts_done` 那一支（到下一个分支为止）：`update_abort` 那支也调一次，所以数
    # 全文出现次数分不出是谁调的 —— 而需要钉住的正是「终点这一支自己收尾」。
    seg = body.split("charts_done", 1)[1].split("update_abort", 1)[0]
    return "self.refresh_start_state()" in seg


def _p_askflow(tree):
    # 用户 m07356 的 P1-①/②：更新改成「先比对完、拿着目录现状再问」，所以
    #   ① `ask()` 得能收一个取消回调（core 那条 worker 正等这一按）与滚长正文；
    #   ② `start_update()` 自己不再弹框 —— 问话搬去了 `_after_check()`（上游的答案在那里）；
    #   ③ `_after_check()` 里那个 `ask` 带 `on_cancel=`，两条路都要把答案递给 core；
    #   ④ 首选目录是**落盘**的（与两枚不落盘的开关同处一张卡，只有它长期有效）。
    ask = _func(tree, "ask")
    su = _func(tree, "start_update")
    ac = _func(tree, "_after_check")
    so = _func(tree, "_save_source")
    if ask is None or su is None or ac is None or so is None:
        return False
    args = {a.arg for a in list(ask.args.args) + list(ask.args.kwonlyargs)}
    if not {"on_cancel", "scrollable"} <= args:
        return False
    return ("scrollable=scrollable" in ast.unparse(ask)
            and not _calls(su, "ask") and _calls(su, "self._run_update")
            and _calls(ac, "ask") and "on_cancel=" in ast.unparse(ac)
            and _calls(ac, "self.core.answer_update")
            and _calls(so, "core.save_state"))


def _p_switch_state(tree):
    # 两枚开关**都不落盘**（`toggle(tk, 0, ...)`：每次开面板都从关着开始）—— 一次 `--force`
    # 会把全部谱面重新下载并重编译，一次 `--verify` 是一张一个请求，都不该跟着开机生效。
    # 同一张卡上只有首选目录读状态、并且真的写回（`_save_source`）。
    bs = _func(tree, "_build_settings")
    so = _func(tree, "_save_source")
    if bs is None or so is None:
        return False
    src = ast.unparse(bs)
    return ("self.force_chk = toggle(self.tk, 0, None" in src
            and "self.verify_chk = toggle(self.tk, 0, None" in src
            and "core.preferred_source(self.state)" in src
            and "preferred_source" in ast.unparse(so))


def _p_recent_motion(tree):
    # 用户 m09421：「最近演出」卡拉窗/缩窗时要知道自己是「进出场」，不许同帧硬切。出现走整卡
    # `_fade_in`；消失先淡出 `MOTION["card_out"]`（退场那一档：accelerate、200 ms）、**淡完**再
    # `visible=False`（`_fade_out_card`）；卡在台上而只是行数变少时走 `_fade_out_row`。两条退场
    # 都要能被作废：`rc.seq` 防「淡出还没播完又要显示」，`rc.hiding`／`r["out"]` 防同一次
    # 退场排两遍。顺序（sleep 在 visible=False 之前）也要钉 —— 反了就等于同帧硬切，动画白写。
    # 2026-10-09（用户 m10950）两张卡之后这些字段从 `self._recent_*` 变成 `RecentCard` 上的
    # `rc.seq`／`rc.hiding`，而且 `_sync_last_cards` 里那一大段包在 `for rc in (...)` 里 ——
    # 所以这里同时钉住「两张卡都走同一套逻辑」。
    # 注意：两条退场是 `async def` —— Python 3.13 的 AST 里它们是 `AsyncFunctionDef`、不是
    # `FunctionDef`，所以**不能借 `_func()`**（那个只认同步函数，拿 async 方法会返回 None，
    # 判据会变成一条永远为假的装饰）。另：`ast.unparse` 会给 BoolOp 里的 `not X` **加括号**
    # （`… and (not rc.hiding)`），所以锚点只取 `not rc.hiding` 这一段。
    def find(name):
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name:
                return fn
        return None

    sync = find("_sync_last_cards")
    out = find("_fade_out_card")
    row = find("_fade_out_row")
    if sync is None or out is None or row is None:
        return False
    s = ast.unparse(sync)
    o = ast.unparse(out)
    r = ast.unparse(row)
    sleep = "await asyncio.sleep(T.motion_ms('card_out') / 1000.0)"
    return ("for rc in (self.recent, self.m_recent):" in s
            and "self.page.run_task(self._fade_in, card_)" in s
            and "self.page.run_task(self._fade_in, box)" in s
            and "self.page.run_task(self._fade_out_card, rc, rc.seq)" in s
            and "self.page.run_task(self._fade_out_row, r, r['seq'])" in s
            and "rc.seq += 1" in s
            and "rc.hiding = True" in s
            and "not rc.hiding" in s
            and "was_hiding" in s
            and sleep in o
            and o.index("await asyncio.sleep") < o.index("card_.visible = False")
            and sleep in r
            and r.index("await asyncio.sleep") < r.index("box.visible = False")
            and "T.animation('card_out')" in o and "T.animation('card_out')" in r
            and "self._motion()" in o and "self._motion()" in r)


def _p_recent_modes(tree):
    # 用户 m10950：「最近」改名「最近演出」；单人页那张只列单人局，多人页**左侧**换成同一张卡、
    # 只列多人局。五件事一起钉：
    #   ① `RecentCard` 这个家什存在，标题写死「最近演出」；
    #   ② `Panel` 持有两张实例，`mode` 分别是 solo / multi；
    #   ③ `_build_start` 那张是 solo、`_build_multi` 左栏那张是 multi（**换掉的正是旧说明卡**）；
    #   ④ 行按 mode 建（`_build_run_card(i, mode)`），点行也带 mode 跳（`_open_run_row(i, m)`）；
    #   ⑤ 取数真的按那一半过滤（`recent_tags` 里 `core.hist_mode_ok`、`refresh_last_run` 里
    #      `rc.mode`、`_sync_last_cards` 数条数时也只数那一半）。
    def find(name):
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name:
                return fn
        return None

    rc_cls = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "RecentCard":
            rc_cls = node
    start, multi = find("_build_start"), find("_build_multi")
    last, refresh = find("_build_last_run"), find("refresh_last_run")
    card_fn, open_fn = find("_build_run_card"), find("_open_run_row")
    model = find("recent_tags")
    if None in (rc_cls, start, multi, last, refresh, card_fn, open_fn, model):
        return False
    init = ast.unparse(rc_cls)
    if "self.title = '最近演出'" not in init or "self.mode = mode" not in init:
        return False
    if "self.recent = RecentCard('solo')" not in ast.unparse(tree):
        return False
    if "self.m_recent = RecentCard('multi')" not in ast.unparse(tree):
        return False
    # 旧说明卡必须真的没了（它的名字连一次都不许再出现）—— 不然「换成同一张卡」可能只是加了
    # 一张、说明卡还在下面躺着。
    if find("_build_multi_note") is not None:
        return False
    if "self._build_last_run('multi')" not in ast.unparse(multi):
        return False
    if "self._build_last_run('solo')" not in ast.unparse(start):
        return False
    if "self._build_run_card(i, mode)" not in ast.unparse(last):
        return False
    if "self._open_run_row(i, m)" not in ast.unparse(card_fn):
        return False
    if "core.hist_mode_ok(r, mode)" not in ast.unparse(model):
        return False
    sync = find("_sync_last_cards")
    if sync is None:
        return False
    return ("self.hist.recent_tags(len(rc.rows), rc.mode)" in ast.unparse(refresh)
            and "for rc in (self.recent, self.m_recent):" in ast.unparse(refresh)
            and "core.hist_mode_ok(r, rc.mode)" in ast.unparse(sync))


def _p_recent_pool(tree):
    # 用户 m12311：「多人演出的最近面板条目上限调整为15」（2026-10-10 用户 m14172 曾改成 10，
    # 同日用户 m14308「还是改回15吧」又改回来 —— 那张卡撑满之后条数只决定列表多长，
    # 不决定看得见几条）。两张卡同一套逻辑，但**上限分档**：单人页 6、多人页 15。
    # 三件事一起钉：
    #   ① 两个常数都在，值就是 6 / 15；
    #   ② `RecentCard` 按 `mode` 挑上限（`self.pool = RECENT_POOL if mode == "solo" else …`）；
    #   ③ 建行、算余量、算条数三处**都读 `rc.pool`** —— 任何一处退回 `RECENT_POOL`，多人页
    #      就又只剩 6 行（这条卡住的是「上限改了但某一路没跟上」，光看常数看不出来）。
    src = ast.unparse(tree)
    if "RECENT_POOL = 6" not in src or "RECENT_POOL_MULTI = 15" not in src:
        return False
    rc_cls = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "RecentCard":
            rc_cls = node
    if rc_cls is None:
        return False
    if ("self.pool = RECENT_POOL if mode == 'solo' else RECENT_POOL_MULTI"
            not in ast.unparse(rc_cls)):
        return False

    def find(name):
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name:
                return fn
        return None

    last, room, sync = find("_build_last_run"), find("_recent_room"), find("_sync_last_cards")
    if None in (last, room, sync):
        return False
    return ("for i in range(rc.pool)" in ast.unparse(last)
            and "rc.pool * RECENT_ROW_H" in ast.unparse(room)
            and "min(fit, have, rc.pool)" in ast.unparse(sync))


def _p_recent_fill(tree):
    # 用户 m13783（2026-10-10）：「为什么默认高度下多人的最近底部会缺一块，想办法解决一下」。
    # 那一栏的高度是**右栏的运行卡**定的（它本来就 `box={"expand": True}` 撑满，实测 643.2
    # 逻辑），左卡从前是自然高（7 行 = 572.4）⇒ 卡底空出 70.8 逻辑，就是用户看到的那一块。
    # 修法照单人页「选曲」卡那套：卡撑满那一栏、里面那层也撑、列表自己滚，撑满多出来的高度
    # 全给条目。七件事一起钉，缺任何一件都退回老样子：
    #   ① `RecentCard` 按 mode 判 `fill`（只有多人页那张独占一栏）；
    #   ② `_build_last_run` 读 `rc.fill`；
    #   ③ 列表 `tight=not fill` + `expand=fill`（`tight` 与 `expand` 打架，选曲列表踩过）；
    #   ④ 列表 `scroll` 只在撑满那张上开（不滚就是「卡撑满了、行还是从顶上排」），
    #      且一律走 `scroll_when_needed()`（`ScrollMode.ADAPTIVE` 在桌面上拇指恒显，
    #      用户 m14308 报过）；
    #   ⑤ 卡自己 `box={"expand": True}` **并且**里面那层 Container 也 `expand`（`card()` 的
    #      `**kw` 给的是里面那层）—— 只撑外面那层，内容还是从顶上排、卡底留白；
    #   ⑥ 撑满那张**有多少放多少**（`rc.pool` 封顶、列表滚得到），单人页那张照旧按余量放；
    #   ⑦ 叠栏时那三层 expand 都得撤（页一滚竖方向就没有紧约束，带着 expand 会红屏）。
    def find(name):
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name:
                return fn
        return None

    rc_cls = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "RecentCard":
            rc_cls = node
    last, sync, win = find("_build_last_run"), find("_sync_last_cards"), find("_apply_window_class")
    if None in (rc_cls, last, sync, win):
        return False
    if "self.fill = mode == 'multi'" not in ast.unparse(rc_cls):
        return False
    body = ast.unparse(last)
    if "fill = rc.fill" not in body:
        return False
    if "tight=not fill, expand=fill" not in body:
        return False
    if "scroll=scroll_when_needed() if fill else None" not in body:
        return False
    if "box={'expand': True} if fill else None" not in body:
        return False
    if "**{'expand': True} if fill else {}" not in body:
        return False
    if "min(have, rc.pool)) if rc.fill else" not in ast.unparse(sync):
        return False
    return ("self.m_recent.card, getattr(self.m_recent.card, 'content', None), "
            "self.m_recent.body" in ast.unparse(win))


def _p_settings_grid(tree):
    # 用户 m15291（2026-10-10）：「优化设置界面的美观度，横平竖直贴边对齐」。这一页的三条硬
    # 规矩各钉一处 —— ① 上面两张卡**等高**；② 下面「种类偏移」卡的四枚框**铺满各自那一格**；
    # ③ 行距与列距**同档**（都是 `SPACE["sm"]`）。两条踩过的坑也一起钉：
    #   ④ 等高**不走** `vertical_alignment=STRETCH` —— 那一页的外层 Column 是可滚的
    #      （`scroll=ScrollMode.AUTO`）⇒ 主轴无界，ResponsiveRow 一拉伸整页就渲染不出来
    #      （实拍 `research/frames/set_now.png` 只剩 96.73% 的页面底色，两张卡一个像素都没画），
    #      所以改成两张卡各钉同一个**实测**高度 `SET_CARD_H`；
    #   ⑤ 叠栏时必须把那个高度撤掉（窄窗里文字会换行，钉死高度会把内容挤出卡片）。
    def find(name):
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name:
                return fn
        return None

    settings, win = find("_build_settings"), find("_apply_window_class")
    if None in (settings, win):
        return False
    gui = ast.unparse(tree)
    if "SET_CARD_H = 380" not in gui:          # 实测常量（`cardspan.py` 逐行数卡片色量的）
        return False
    body = ast.unparse(settings)
    if body.count("box={'height': SET_CARD_H}") != 2:
        return False
    if "vertical_alignment=ft.CrossAxisAlignment.STRETCH" in body:
        return False
    # 那四枚**种类偏移**框的调用要整行对上：只判 `width=None` 不够 —— 卡里现在还有第二枚
    # `width=None` 的数框（尾判滑键），于是「把四枚退回 96」那颗牙会被那句话挡住。
    if ("sp = num_field(self.tk, int(kd.get(k, 0.0) or 0.0), self._save_kind_lead, "
            "suffix=' ms', decimals=0, width=None)") not in body:
        return False
    if "sp.expand = True" not in body:
        return False
    if "spacing=T.SPACE['sm']" not in body:
        return False
    # 卡名与卡面上那句**静态**说明（2026-10-21 用户 m53176「种类偏移+点明」）：名字从
    # 「分类偏移」改成「种类偏移」之后，还得在卡面上自己说清它按**音符种类**调、与选曲页
    # 那个「分类」下拉（乐队分类筛选）无关 —— 撞字的地方不能只靠改名解决。
    if "title='种类偏移'" not in body:
        return False
    if "self.kind_note = txt(" not in body or "「分类」筛选" not in body or "无关" not in body:
        return False
    return "c.height = None if stacked else SET_CARD_H" in ast.unparse(win)


def _p_tail_lead(tree):
    """尾判滑键那一格（用户 m52916「能否将尾滑偏移加入设置」）。

    钉五件事，缺一处就等于那格是摆设：
      ① 那格**存在且接线**（`self.tail_lead_spin = num_field(…, self._save_tail_lead, …)`）并
         真的被排进卡里（它是同一行五格里的最后一格：`opt_line(*[…], tail_tile)`）；
      ② 它写的是**另一个键** `defaults["tail_flick_lead"]` —— 不能塞进 `kind_lead` 那个 dict：
         它不是一个种类，而是一种手势位置（长条尾巴上挂着的 flick），而 `run.py` 的
         `parse_kind_lead` 遇到不认识的名字会拒绝整局；
      ③ 夹取档位 `NUM_RANGE["tail_lead"] == (0.0, 60.0)` —— 只往早的方向（负数会把那记滑键
         推到尾巴之后，那不是微调）；
      ④ 出厂值只有一处来源：视图里读 `core.TAIL_FLICK_LEAD_DEFAULT`，而 `core` 那份与
         `player.TAIL_FLICK_LEAD_MS` 必须一致（两边漂移 = 面板显示 10、实机按别的数打）；
      ⑤ 那张卡的正文**只有三段**（一句支持文本 `self.kind_note` + 一条 `opt_line` + 一句提示）
         —— 用户 m53338 要求设置页不出现滚动：这一页的余量按行算（并掉一整行瓦片换来的 68 逻辑，
         支持文本又吃回去一档行高 + 8）；谁再往里排一行（哪怕只是把尾滑格挪回单独一行，那正好
         是一行 68），整页又会开始滚。支持文本**必须是第一个孩子**（M3 卡片解剖：标题 + 支持
         文本上下叠；塞到标题行右边不是规范版式，2026-10-21 用户 m53608 就是这么指出来的）。
    """
    def find(name):
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name:
                return fn
        return None

    settings, save = find("_build_settings"), find("_save_tail_lead")
    if None in (settings, save):
        return False
    body = ast.unparse(settings)
    if "self.tail_lead_spin = num_field(" not in body:
        return False
    if "self._save_tail_lead" not in body:
        return False
    if "opt_line(tail_tile)" not in body and ", tail_tile)" not in body:
        return False
    if "core.TAIL_FLICK_LEAD_DEFAULT" not in body:
        return False
    # ⑤ 那张卡的正文只有三段：一句**支持文本**（`self.kind_note`，M3 的「标题 + 支持文本上下叠」
    #    就靠它，见 2026-10-21 用户 m53608）+ 一条 `opt_line`（五格）+ 一句提示。
    # 按 AST 认那个 `card(…, title='种类偏移')`，数它正文 `ft.Column` 的孩子 —— 谁多加一行就红。
    # **支持文本必须是第一个孩子**（塞到标题行右边就不是 M3 的卡片解剖了，那正是 m53608 那一问）。
    kind_card = None
    for call in ast.walk(settings):
        if not isinstance(call, ast.Call):
            continue
        if not any(k.arg == "title" and isinstance(k.value, ast.Constant)
                   and k.value.value == "种类偏移" for k in call.keywords):
            continue
        # `card(self.tk, ft.Column([...]), title=…, icon=…, note=…)`：正文是**第二个位置实参**
        # （第一个是 `self.tk`）—— 这里按形状认那个 `ft.Column` 调用，不按下标写死。
        for a in call.args:
            if (isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute)
                    and a.func.attr == "Column"):
                kind_card = a
    if not isinstance(kind_card, ast.Call):
        return False
    if not isinstance(kind_card.func, ast.Attribute) or kind_card.func.attr != "Column":
        return False
    kids = kind_card.args[0] if kind_card.args else None
    if not isinstance(kids, ast.List) or len(kids.elts) != 3:
        return False
    # 第一段是支持文本：属性首、`self.kind_note`；第二段是那一行五格。
    first = kids.elts[1]
    if not (isinstance(first, ast.Call) and isinstance(first.func, ast.Name)
            and first.func.id == "opt_line"):
        return False
    note = kids.elts[0]
    if not (isinstance(note, ast.Attribute) and note.attr == "kind_note"
            and isinstance(note.value, ast.Name) and note.value.id == "self"):
        return False
    sv = ast.unparse(save)
    if "d['tail_flick_lead'] = self._clamp_field('tail_lead'" not in sv:
        return False
    if "d['kind_lead']" in sv or "setdefault('kind_lead'" in sv:
        return False
    gui = ast.unparse(tree)
    if "'tail_lead': (0.0, 60.0)" not in gui:
        return False
    return abs(core.TAIL_FLICK_LEAD_DEFAULT - player.TAIL_FLICK_LEAD_MS) < 1e-9


def _p_multi_no_retry(tree):
    # 用户 m12749：「你确定断连重试对多人模式有用？为什么要放到多人模式的界面里」—— 答案是没用
    # （`--retry-on-break` 的机制是「暂停 LIVE → 重试 → 确定」把同一首从头再打，房间局要么走不通、
    # 要么把这一轮作废），所以多人页那枚瓦片拆掉了。四处一起钉，缺一处就等于没拆干净：
    #   ① 多人运行卡里不许再出现那两个控件名与那四个字；
    #   ② `_multi_widgets()` 的名单里也不许有（否则忙时会去 getattr 一个不存在的控件）；
    #   ③ `_save_multi` 不许再写那两个状态键（它们从此只归单人页）；
    #   ④ `start_multi_run()` 递给 `core.start()` 的第 7 个位置参数必须是 False（retry_break）。
    # 反过来单人页必须**还留着**那枚瓦片 —— 否则「多人页拆干净了」与「整个功能都被删了」
    # 在这条判据下分不出来（量空气）。
    def find(name):
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name:
                return fn
        return None

    def code_of(fn):
        # 比的是「真写进去的语句」，不是整段 unparse —— 文档串也是 AST 里的一节，而
        # `_save_multi` 的文档串**正该**讲清这两个键为什么不再写（第一版就是被它弄红的）。
        stmts = list(fn.body)
        if (stmts and isinstance(stmts[0], ast.Expr)
                and isinstance(stmts[0].value, ast.Constant)
                and isinstance(stmts[0].value.value, str)):
            stmts = stmts[1:]
        return "\n".join(ast.unparse(s) for s in stmts)

    mrun, save, start, widgets, solo = (find("_build_multi_run"), find("_save_multi"),
                                        find("start_multi_run"), find("_multi_widgets"),
                                        find("_build_run"))
    if None in (mrun, save, start, widgets, solo):
        return False
    if any(w in code_of(mrun) for w in ("m_break_chk", "m_retry_spin", "断连重试")):
        return False
    if any(w in code_of(widgets) for w in ("m_break_chk", "m_retry_spin")):
        return False
    if any(w in code_of(save) for w in ("retry_on_break", "retry_cap")):
        return False
    calls = [n for n in ast.walk(start)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "start"]
    if len(calls) != 1 or len(calls[0].args) < 7:
        return False
    arg = calls[0].args[6]
    if not (isinstance(arg, ast.Constant) and arg.value is False):
        return False
    solo_src = ast.unparse(solo)
    return "断连重试" in solo_src and "self.break_chk" in solo_src


def _p_log_search(tree):
    # 用户 m09617「全面审查并改进日志界面」翻出来的头一条：一页最多 2000 行，翻找只能靠关键词框。
    #   ① `_build_log` 真建了 `ft.TextField`（SEARCH 前缀图标 + 接 `_on_log_search`）；
    #   ② 关键词是 `_log_pass` 的**头一条**判定 —— 排在页签后面就等于「只搜当前页签」；
    #   ③ 换页签 / 改词 / 清词三条入口走同一个 `_reload_log_view`（一处重画），而它自己既铺行
    #      也报数（重画完计数行还停在上一拍，就是又一次「算好了没推出去」）。
    build = _func(tree, "_build_log")
    passed = _func(tree, "_log_pass")
    reload_fn = _func(tree, "_reload_log_view")
    if build is None or passed is None or reload_fn is None:
        return False
    fields = [n for n in ast.walk(build)
              if isinstance(n, ast.Call) and _dotted(n.func) == "ft.TextField"]
    if not any(_dotted(_kw(c, "prefix_icon")) == "ft.Icons.SEARCH"
               and _dotted(_kw(c, "on_change")) == "self._on_log_search" for c in fields):
        return False
    # 注意：`body[0]` 是 docstring（`Expr`），不是守卫 —— 直接取会拿到那句文档，判据永远为假。
    first = [s for s in passed.body
             if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    head = ast.unparse(first[0]) if first else ""
    if "self.log_query" not in head or "self.log_filter" in head:
        return False
    sites = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Call)
                and _dotted(n.func) == "self._reload_log_view")
    return (sites >= 3 and _calls(reload_fn, "self._log_line")
            and _calls(reload_fn, "self._refresh_log_info"))


def _p_log_scroll(tree):
    # 内容溢出一屏时 Flutter **一条滚动条都不画**（实测 `%TEMP%\bang_probe2_many_default.png` 右边缘
    # 26 列零个非白像素），所以这条轨必须自己点名滚动条。**不能点名 `ScrollMode.ADAPTIVE`**：
    # Flet 把它映射成 `thumb_visibility=page.web or not page.platform.is_mobile()` ⇒ 桌面恒 True
    # （拇指永远挂在边上，用户 m14308 报过「太丑」）⇒ 一律走 `scroll_when_needed()`（见那条判据）。
    # 而 `auto_scroll` 的默认补间是 1 s ease —— 追不上 `PUMP_MS`=120 ms 一次的追加（每次都被
    # 下一行打断），改成 0 才是瞬时到底。
    # 开关还不许说谎：用户往上滚时框架本来就暂停钉住，`on_scroll` 要把真实状态说给开关听。
    # **但只许掰开关、不许去翻 `auto_scroll`**（用户 m27254：用户从底部上滑解除自动滚动，整屏
    # 照样被拉回顶部 —— 翻它换掉的是客户端的元素树形状 ⇒ 子树重建、位置丢掉）。那一侧的暂停/
    # 恢复 Flet 自己会做（`ScrollableControl.auto_scroll` docstring：滚离末尾时暂停、滚回来自己
    # 恢复）；只有「回到底部」那一侧重新武装，且只在它真的是关着的时候翻（已是 True 的赋值是
    # 空操作，不重建、不跳）。
    ctor = None
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and _dotted(n.func) == "ft.ListView"
                and _dotted(_kw(n, "on_scroll")) == "self._on_log_scroll"):
            ctor = n
            break
    if ctor is None:
        return False
    scr = _kw(ctor, "scroll")
    if not (isinstance(scr, ast.Call) and _dotted(scr.func) == "scroll_when_needed"):
        return False
    anim = _kw(ctor, "auto_scroll_animation")
    if not (isinstance(anim, ast.Constant) and anim.value == 0):
        return False
    fn = _func(tree, "_on_log_scroll")
    if fn is None:
        return False
    s = ast.unparse(fn)
    # 开关要照实说（`ctl.value = at_bottom` + 推出去），但**一个字节都不许写 `auto_scroll`**
    # （用户 m27254：用户从底部上滑解除自动滚动，整屏照样被拉回顶部 —— 写它换掉的是客户端的
    # 元素树形状 ⇒ 子树重建、位置丢掉）。而且只在**用户要跟**的时候掰开关
    # （`if self.log_view.auto_scroll and …`）：用户自己关掉过就是他的设置，滚回底部也不许掰回来。
    return ("at_bottom" in s and "max_scroll_extent" in s
            and "ctl.value = at_bottom" in s
            and "if self.log_view.auto_scroll and" in s
            and "self.log_view.auto_scroll =" not in s
            and "_push_ctl" in s)


def _p_scroll_thumb(tree):
    # 用户 m14308：「这个滚动条怎么常显的，太丑了」。根因是 Flet 把 `ScrollMode.ADAPTIVE` 映射成
    # `ft.Scrollbar(thumb_visibility=page.web or not page.platform.is_mobile())` —— 面板跑的是
    # Windows 桌面（既不是 web 也不是手机）⇒ 那一项恒为 True，8dp 的拇指永远挂在边上
    # （2026-10-10 实拍 `research/frames/scroll_old_1280.png`：左卡 x964..975、y188..641 一条
    # 454px 高的 `#767680`；改完 `scroll_new_1280.png` 同位置一条都没有）。
    # 规矩：**全模块不许再出现 `ScrollMode.ADAPTIVE`**，一律走 `scroll_when_needed()`
    # （`ft.Scrollbar(thumb_visibility=False)` ⇒ Flutter `RawScrollbar` 的默认：滚动时淡入、
    # 停手约 600ms 淡出、悬停也出现），厚度/颜色/圆角仍由主题层 `scrollbar_theme` 一处说了算。
    fn = _func(tree, "scroll_when_needed")
    if fn is None:
        return False
    body = ast.unparse(fn)
    if "ft.Scrollbar(thumb_visibility=False)" not in body:
        return False
    # 只认真的用了那个枚举（`ft.ScrollMode.ADAPTIVE` 这串字在 `scroll_when_needed` 的
    # docstring 里作为「别再这么写」出现过，`ast.unparse` 会把 docstring 也算进来 ⇒ 不能搜字串）。
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr == "ADAPTIVE"
                and _dotted(node.value) == "ft.ScrollMode"):
            return False
    # 两个用到滚动条的地方都得走它：日志那条列表（建在 `Panel.__init__` 里 —— 注意
    # `_func` 取的是全树第一个 `__init__`，那是 `RecentCard` 的，所以要按类找）与
    # 多人页撑满那张「最近演出」卡的列表。
    panel_cls = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Panel":
            panel_cls = node
    init = None
    if panel_cls is not None:
        for node in ast.walk(panel_cls):
            if isinstance(node, ast.FunctionDef) and node.name == "__init__":
                init = node
                break
    last = _func(tree, "_build_last_run")
    for host in (init, last):
        if host is None or "scroll_when_needed()" not in ast.unparse(host):
            return False
    return True


def _fn(tree, name):
    # `_func` 只认 `ast.FunctionDef`，而日志那几件（`_pin_back` / `_log_to_top`）是 `async def`
    # （`ast.AsyncFunctionDef`）⇒ 这里两种都收。
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def _assigned(tree, name):
    # 模块级常量的赋值值节点（`TABS = (...)` / `SHORTCUTS = (...)`）。
    # 注意 `_name_of` 只认 `self.foo` 那种目标，这里的目标是裸 `ast.Name`。
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and any(
                _dotted(t) in (name, "self." + name) for t in n.targets):
            return n.value
    return None


def _p_log_name(tree):
    # 页名是「运行日志」（用户 m10393）：页签、卡片标题、快捷键清单**三处一起**改，一处留旧名就算假。
    tabs = _assigned(tree, "TABS")
    if not isinstance(tabs, ast.Tuple):
        return False
    names = []
    for el in tabs.elts:
        if not (isinstance(el, ast.Tuple) and el.elts and isinstance(el.elts[0], ast.Constant)):
            return False
        names.append(el.elts[0].value)
    if names != [u"单人演出", u"多人演出", u"运行日志", u"结算记录", u"设置"]:
        return False
    shortcuts = _assigned(tree, "SHORTCUTS")
    if shortcuts is None or u"运行日志" not in ast.unparse(shortcuts):
        return False
    fn = _func(tree, "_build_log")
    return fn is not None and "title='运行日志'" in ast.unparse(fn)


def _p_log_pin(tree):
    # 翻「自动滚动」不许带走视图、打开必须落到底（用户 m10610）；「回顶」是独立一颗 M3 图标按钮。
    #
    # 为什么这条得钉住：`auto_scroll` 在客户端换掉的是滚动控件的**元素树形状**
    # （`scrollable_control.dart` 的 `build()` 只在它为真时把列表包进一层 `NotificationListener`）
    # ⇒ 子树重建、位置丢掉 ⇒ 关掉那一刻整屏跳回顶部（真面板实测 mean 6.86、7 万个像素变了）。
    # 所以 `_auto` 翻完必须把位置交给 `_pin_back` 复位：关掉回 `px`（翻之前记的），打开落到底
    # （`offset=-1` = 从末尾算 1 px）。复位那一拍 `_log_pin` 立闸门，事件只记位置不掰开关。
    auto, pin = _fn(tree, "_auto"), _fn(tree, "_pin_back")
    top, sc = _fn(tree, "_log_to_top"), _fn(tree, "_on_log_scroll")
    if None in (auto, pin, top, sc):
        return False
    a, p, t, s = (ast.unparse(x) for x in (auto, pin, top, sc))
    # ① 同步那一半（补边带直接调它，协程在那里不会被 await）+ 异步那一半交给 run_task
    if "self.log_view.auto_scroll = on" not in a or "run_task(_pin_back, on, px)" not in a:
        return False
    # ② 关掉回原位、打开落到底，且闸门两头都在
    # （注意 `ast.unparse` 会把源码里那对括号吃掉：`(-1.0 if on else px)` → `-1.0 if on else px`）
    if "-1.0 if on else px" not in p:
        return False
    if "self._log_pin = True" not in p or "self._log_pin = False" not in p:
        return False
    # ③ 回顶：绝对位置 0、瞬时（框架默认 1 s 补间），位置账当场记 0
    if "scroll_to(offset=0, duration=0)" not in t or "self._log_pixels = 0.0" not in t:
        return False
    # ④ 位置账记在闸门之前（复位自己发的串也必须入账）+ 闸门本身
    if "self._log_pixels = pixels" not in s or "if self._log_pin:" not in s:
        return False
    # ⑤ 用户自己滚离底部时**一个字节都不许写 `auto_scroll`**（用户 m27254：从底部上滑解除
    #    自动滚动，整屏照样被拉回顶部 —— 写它换掉的是客户端的元素树形状，见上面那条）。这一侧
    #    的暂停与恢复 Flet 1.0.3 自己会做（`ScrollableControl.auto_scroll` docstring：滚离末尾
    #    时暂停、滚回来自己恢复），开关只把这件事说出来；而且只在**用户要跟**的时候说
    #    （`if self.log_view.auto_scroll and …`）—— 用户自己关掉过就是他的设置，不许被掰回来。
    if "self.log_view.auto_scroll =" in s:
        return False
    if "if self.log_view.auto_scroll and" not in s:
        return False
    # ⑥ 那颗按钮本身照 M3：图标按钮、24 图标、`on_surface_variant` 色，48 可点区由 hit_pad 补
    btn = None
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and _dotted(n.func) == "ft.IconButton"
                and _dotted(_kw(n, "on_click")) == "self._log_to_top"):
            btn = n
            break
    if btn is None:
        return False
    if (_dotted(_kw(btn, "icon")) != "ft.Icons.VERTICAL_ALIGN_TOP"
            or _dotted(_kw(btn, "icon_size")) != "T.ICON_LG"
            or _dotted(_kw(btn, "icon_color")) != "self.tk.text_dim"):
        return False
    build = _func(tree, "_build_log")
    return build is not None and "hit_pad(self.log_top_btn)" in ast.unparse(build)


def _p_log_err_tint(tree):
    # 严重度不能只靠颜色：红/绿型色觉障碍下 `danger` 与 `ok` 两档的亮度几乎一样，只换字色分不出来。
    # 错误行铺一层 `danger` 的 `disabled_container`（12%，面积线索）—— 透明度不许写字面量。
    # 从前这层底挂在 `ft.Text` 自己那个盒子上，只有文字那么宽（实测 41 %），看着像「选中了这段字」；
    # 现在挂在包住整行的 `ft.Container` 上（`ListView` 的孩子是松约束、`expand` 无效 ⇒ 靠 `ft.Row`
    # 的 `mainAxisSize` 默认 max 铺满）。判据钉的就是「底在 Container 上」，不是荧光笔式的。
    # 注意：`ast.unparse` 把字符串字面量写成**单引号**（`'log_err'`），比对时别写成双引号。
    fn = _func(tree, "_log_line")
    if fn is None:
        return False
    s = ast.unparse(fn)
    return ("if kind == 'log_err'" in s
            and "band = self.tk.state(self.tk.danger, 'disabled_container')" in s
            and "return ft.Container(content=row, bgcolor=band)" in s)


def _p_log_hdr_flat(tree):
    # **只有错误行铺底**。分段行（`log_hdr`：「面板已启动」「第 N 轮」「随机选曲：」）曾经也铺
    # 一格 `tk.field`（`surface_container_highest`）当小节头，用户 m11974 报「蓝字 Log 那行会带
    # 灰色背景」。分段已经由 `accent` 字色承担，不再加底 —— 这条判据盯的就是「`_log_line` 里
    # 不许再出现 `log_hdr` 那一路底色」。`ast.unparse` 会把注释丢掉，所以注释里提到 `log_hdr`
    # 不会让判据变假（这也是这颗牙能咬动的前提）。
    fn = _func(tree, "_log_line")
    if fn is None:
        return False
    s = ast.unparse(fn)
    return ("if kind == 'log_err'" in s
            and "log_hdr" not in s
            and "return ft.Container(content=row, bgcolor=band)" in s)


def _p_log_columns(tree):
    # 一行两栏（B4）。时间戳独立一栏：固定宽 `T.LOG_TS_W`、不折行；正文栏吃余量、自己折行 ——
    # 折行的续行因此有悬挂缩进（从前两段是同一个 `ft.Text` 的 span，续行回卷到行首、骑在时间戳
    # 底下）。两栏由**一个** `ft.SelectionArea` 包住：两段各自 `selectable` 会各开一个选区、
    # 拖选被截断，复制出来只剩半行。
    fn = _func(tree, "_log_line")
    if fn is None:
        return False
    texts = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and _dotted(n.func) == "ft.Text"]
    gut = any(_dotted(_kw(c, "width")) == "T.LOG_TS_W"
              and getattr(_kw(c, "no_wrap"), "value", None) is True for c in texts)
    msg = any(getattr(_kw(c, "expand"), "value", None) is True
              and getattr(_kw(c, "no_wrap"), "value", None) is False for c in texts)
    sel = None
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and _dotted(n.func) == "ft.SelectionArea":
            sel = _kw(n, "content")
    row_ok = (isinstance(sel, ast.Call) and _dotted(sel.func) == "ft.Row"
              and sel.args and isinstance(sel.args[0], ast.List) and len(sel.args[0].elts) == 2)
    return gut and msg and row_ok


def _p_log_pane(tree):
    # 控制台是一块「下沉一档」的凹面（C）：卡片是 `surface_container_low`，再往下一档就是基面
    # `surface` —— 一屏字铺基面才读得出一块「屏」。圆角取 `card`（官方 `CornerMedium` = 12dp）；
    # `clip_behavior` 必须给：整行带是方的，不裁会顶出面板的圆角。工具行与这块凹面之间一条
    # `hairline`（官方 `DividerTokens.Color = OutlineVariant`，厚 1dp）—— 从前工具栏直接贴着
    # 第一行日志，两边都是一行字，分不出哪块是哪块。
    build = _func(tree, "_build_log")
    if build is None:
        return False
    pane = False
    for n in ast.walk(build):
        br = _kw(n, "border_radius") if isinstance(n, ast.Call) else None
        if (isinstance(n, ast.Call) and _dotted(n.func) == "ft.Container"
                and _dotted(_kw(n, "bgcolor")) == "self.tk.surface"
                and _dotted(_kw(n, "clip_behavior")) == "ft.ClipBehavior.ANTI_ALIAS"
                and isinstance(br, ast.Call) and _dotted(br.func) == "T.radius"):
            pane = True
    return pane and _calls(build, "hairline")


def _p_log_rhythm(tree):
    # 行距（D+A2）。两千行挤成一堵墙（从前节距 20dp）⇒ 一节 24dp：正文盒 16 + `ListView.spacing`
    # 取 4dp 栅格上最小的一档，列表上下再各留 8。这一条只看**列表自己**那两处，不看别处的 padding。
    ctor = None
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and _dotted(n.func) == "ft.ListView"
                and _dotted(_kw(n, "on_scroll")) == "self._on_log_scroll"):
            ctor = n
            break
    if ctor is None:
        return False
    pad = _kw(ctor, "padding")
    if not (isinstance(pad, ast.Call) and _dotted(pad.func) == "ft.Padding"):
        return False
    return (ast.unparse(_kw(ctor, "spacing")) == "T.SPACE['xs']"
            and ast.unparse(pad).count("T.SPACE['sm']") == 2)


def _p_empty_badge(tree):
    # 空态的图标坐在一枚 64dp 的 `secondary_container` 圆上（A3）：单个线框图标浮在卡片上没有重量，
    # 也与页面上别处的「有色容器」（chip、进度轨、导航指示条）不是一个语汇；图标色换成官方配对的
    # `on_secondary_container`。M3 没有「空态」组件，这个圆盘是本项目决定（`T.EMPTY_BADGE`）。
    fn = _func(tree, "empty_state")
    if fn is None:
        return False
    for n in ast.walk(fn):
        if not (isinstance(n, ast.Call) and _dotted(n.func) == "ft.Container"):
            continue
        if (_dotted(_kw(n, "width")) == "T.EMPTY_BADGE"
                and _dotted(_kw(n, "height")) == "T.EMPTY_BADGE"
                and _dotted(_kw(n, "shape")) == "ft.BoxShape.CIRCLE"
                and _dotted(_kw(n, "bgcolor")) == "tk.secondary_container"):
            ic = _kw(n, "content")
            return (isinstance(ic, ast.Call) and _dotted(ic.func) == "ft.Icon"
                    and _dotted(_kw(ic, "color")) == "tk.on_secondary_container")
    return False


def _p_empty_roles(tree):
    # 空态两行字各就各位（2026-10-09 M3 审查）：主句是这一段的主内容 ⇒ **不给 `color`**（`txt` 的
    # 默认色就是 `on_surface`）；提示句是支撑文字 ⇒ `on_surface_variant`（`tk.text_dim`）。两行都取
    # `bodySmall`（角色 `"n"`）—— 提示句从前写 `"s"`，那是 `labelSmall`，字阶里给标签（按钮、页签、
    # chip）用的一档，拿来排一整句话是把标签当正文；主句从前也铺 `text_dim`，于是整张空态里一个
    # `on_surface` 都没有、主次分不出来。四张空态（选曲、结算、运行日志两张）共用这一个函数。
    fn = _func(tree, "empty_state")
    if fn is None:
        return False
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and _dotted(n.func) == "txt"]
    if len(calls) < 2:
        return False

    def role(c):
        return getattr(c.args[2], "value", None) if len(c.args) > 2 else None

    main = [c for c in calls if role(c) == "n" and _kw(c, "color") is None]
    hint = [c for c in calls if role(c) == "n"
            and _dotted(_kw(c, "color")) == "tk.text_dim"]
    return (bool(main) and bool(hint)
            and not any(role(c) == "s" for c in calls))


def _p_log_push(tree):
    # 「算好了没推出去」是真毛病，不是假想：改了兄弟控件的属性而**不调它的 `.update()`**，客户端
    # 照旧画旧值（`%TEMP%\bang_probe2_sib_{stale,push}.png` 两张字节不同）。日志页有三处不归
    # `log_view` 管 —— 计数行、空态（藏的那一路）、以及首帧那一放 —— 三处都得自己推。
    info = _func(tree, "_refresh_log_info")
    tgl = _func(tree, "_toggle_empty")
    build = _func(tree, "_build_log")
    if info is None or tgl is None or build is None:
        return False
    return (_calls(info, "self._push_ctl") and _calls(tgl, "self._push_ctl")
            and "self._refresh_log_info()" in ast.unparse(build))


def _p_log_two_empty(tree):
    # 两种空不一样：「库里真没行」与「库里 412 行、只是被筛没了」不该说同一句话
    # （`没有日志` / `没有匹配`），而且由 `_refresh_log_info` 一处定夺、两张空态互斥。
    made = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "empty_state"):
            made |= {_name_of(t) for t in node.targets if _name_of(t)}
    info = _func(tree, "_refresh_log_info")
    if "log_none" not in made or info is None:
        return False
    s = ast.unparse(info)
    return "no_match" in s and s.count("self._toggle_empty") >= 2


def _p_log_clear_toast(tree):
    # 「按下去必须当场说话」：清屏是破坏性的（内存里那份没了、导出也救不回来），一声不吭等于按了
    # 没反应。0 行与 N 行两种话都要说；`toast` 走 `inverse_surface`，正是 AGENTS.md 那句
    # 「导出与清理的结果由它说」。
    fn = _func(tree, "clear_log")
    if fn is None:
        return False
    return _calls(fn, "toast") and _calls(fn, "self._refresh_log_info")


def _p_chip_view(tree):
    # 用户 m11265「点了的确会切换但选中效果不变」查下去，视图层自己的口径也要跟官方对齐：
    #   ① 选中**不描边**、未选中才描 `outline_variant`（`_FilterChipDefaultsM3.side`：flat 且选中
    #      ⇒ `Colors.transparent`）。`ft.Chip.border_side` 只吃**一个** `BorderSide`，所以「建的
    #      时候」与「刷的时候」必须调同一个 `tk.chip_side()` —— 各写各的，就会建出来是选中样、
    #      一刷又描上；
    #   ② 未选中不铺底，底由 `chip_theme.bgcolor` 给（视图层不许出现 `ft.Colors` ⇒ 控件上不写
    #      `bgcolor=`）；
    #   ③ `paint_chip` 是唯一改状态的地方，三件（selected / 标签色 / 描边）一起刷，别只刷一半。
    btn = _func(tree, "chip_button")
    paint = _func(tree, "paint_chip")
    if btn is None or paint is None:
        return False
    chip = None
    for n in ast.walk(btn):
        if isinstance(n, ast.Call) and _dotted(n.func) == "ft.Chip":
            chip = n
            break
    if chip is None or _kw(chip, "bgcolor") is not None:
        return False
    bs = _kw(chip, "border_side")
    if not (isinstance(bs, ast.Call) and _dotted(bs.func) == "tk.chip_side"):
        return False
    s = ast.unparse(paint)
    return ("chip.selected = bool(on)" in s and "chip.label.color = " in s
            and "chip.border_side = tk.chip_side(on)" in s)


def _p_chip_theme(tree):
    # 令牌层替 chip 说的两句话：未选中**不铺底**（官方 `_FilterChipDefaultsM3.color` 在 flat
    # 未选中时返回 `null`；`FilterChipTokens.kt` 里只有 `FlatSelectedContainerColor`），
    # 内边距 **8**（`Chip.kt` 的 `ContentPadding = 8.dp`，规格表 chip 也是 8 —— 从前写 12）。
    # 描边那句必须留在这一层：视图层不许出现 `ft.Colors`，而「透明」只能从 `ft.Colors` 来。
    ct = None
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and _dotted(n.func) == "ft.ChipTheme":
            ct = n
            break
    if ct is None or _dotted(_kw(ct, "bgcolor")) != "ft.Colors.TRANSPARENT":
        return False
    if "SPACE['sm']" not in ast.unparse(_kw(ct, "padding")):
        return False
    fn = _func(tree, "chip_side")
    if fn is None:
        return False
    s = ast.unparse(fn)
    return "ft.Colors.TRANSPARENT" in s and "outline_variant" in s


def _p_chip_gap(tree):
    # 一排 chip 的间距：官方 chip set 是 8（material-web `chips/internal/_chip-set.scss` 的
    # `:host { flex-wrap: wrap; gap: 8px }`）。锚点是「元素里有 `btns` 的那几个 `ft.Row`」——
    # 日志页与结算页各一排，两排都得是 8（从前都是 4）。
    rows = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and _dotted(n.func) == "ft.Row" and n.args
                and "btns" in ast.unparse(n.args[0])):
            rows.append(n)
    return len(rows) >= 2 and all(
        ast.unparse(_kw(r, "spacing")) == "T.SPACE['sm']" for r in rows)


def _p_chip_push(tree):
    # 用户报的那一条的真身：点筛选 chip，行换了、选中视觉不动 —— `paint_chip` 只改了控件属性，
    # 没有任何人给 chip 调 `.update()`（`_reload_log_view` 只推列表、`_refresh_log_info` 只推计数
    # 行）。改状态的函数必须把改过的控件一起推出去，一枚不留。
    fn = _func(tree, "set_log_filter")
    if fn is None:
        return False
    s = ast.unparse(fn)
    return "paint_chip" in s and "log_btns" in s and "_push_ctl" in s


def _p_hist_fit(tree):
    # 用户 m12075：「表单宽度应与窗口宽度保持同步，目前在小窗口下表单超出宽度显示」。结算表是 13 个
    # 定宽列（`core.HIST_WIDTHS` 合计 749）+ 12 的列间距 + 每个可排序列 18 的箭头格 ⇒ 自然宽 1155，
    # 而 1280 窗的内容区只有 1032（800 窗只有 673）—— 右边「分数」整列被裁在视口外。
    # 这一条钉「预算」本身：可用宽**只有一个出处**（`_hist_avail`，导轨恒为收起的 80 宽），
    # 占宽**只有一个出处**（`_hist_demand`，含 `T.HIST_ARROW_W`），挑列按 `T.HIST_FIT_ALWAYS`
    # 先占位、`T.HIST_FIT_ORDER` 依次加。
    lay = _func(tree, "_hist_layout")
    dem = _func(tree, "_hist_demand")
    if lay is None or dem is None or _func(tree, "_hist_avail") is None:
        return False
    if not (_calls(lay, "self._hist_avail") and _calls(lay, "self._hist_demand")):
        return False
    s = ast.unparse(lay)
    if not ("T.HIST_FIT_ALWAYS" in s and "T.HIST_FIT_ORDER" in s and "core.HIST_HEADS" in s):
        return False
    avail = ast.unparse(_func(tree, "_hist_avail"))
    # 箭头那一格必须真加进「每列的占宽」里 —— 按 AST 认那个加法，不按字符串认：`_hist_demand` 的
    # docstring 里也写着 `T.HIST_ARROW_W`，用文本判会让「忘了算箭头格」那颗牙咬不动（踩过）。
    arrow_in_sum = any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add)
                       and _dotted(n.right) == "T.HIST_ARROW_W" for n in ast.walk(dem))
    # 2026-10-07：导轨永远收起（用户 m18525）之后，可用宽只许减 `T.NAV_MIN_W` —— 所以这里
    # 反过来要求「`T.NAV_MIN_EXT_W` 不许再出现在预算里」（从前是按窗口尺寸类二选一）。
    return ("T.NAV_MIN_W" in avail and "T.NAV_MIN_EXT_W" not in avail and arrow_in_sum)


def _p_hist_sync(tree):
    # 表要跟着窗口走，就得在 resize 那条路上重挑列（`_apply_window_class` 每次 resize 都喊一声
    # `_sync_hist_cols`），而且**只有指纹变了**才重建、重画：每个 resize 事件都重排一次的话，拖窗口
    # 时客户端会一帧一帧地重算上百行格子（`_apply_window_class` 里「只在换挡那一下动版面」是同一个
    # 教训）。表头也必须由预算造 —— 列宽变了不重建 `columns`，表头会与行对不上。
    sync = _func(tree, "_sync_hist_cols")
    win = _func(tree, "_apply_window_class")
    build = _func(tree, "_build_history")
    if sync is None or win is None or build is None or _func(tree, "_build_hist_cols") is None:
        return False
    if not (_calls(win, "self._sync_hist_cols") and _calls(sync, "self._render_history")):
        return False
    s = ast.unparse(sync)
    if not ("hist_table.columns" in s and "_hist_sig" in s):
        return False
    # 「只按指纹重建」的守卫本体：这一档的指纹**真的被记下来**了（否则每来一个 resize 事件都重排）。
    if not any(isinstance(n, ast.Assign) and len(n.targets) == 1
               and _dotted(n.targets[0]) == "self._hist_sig" for n in ast.walk(sync)):
        return False
    for n in ast.walk(build):
        if (isinstance(n, ast.Call) and _dotted(n.func) == "ft.DataTable"
                and "self._build_hist_cols" in ast.unparse(_kw(n, "columns"))):
            return True
    return False


def _p_hist_arrow(tree):
    # 排序箭头：Flutter 只在 `sort_column_index` 指到某一列时才画那一列的箭头 —— 而列宽里那 18 px
    # （`T.HIST_ARROW_W`）是它先占下的，从前 `sort_column_index` 从头到尾没设过 ⇒ 一个箭头都不画，
    # 那 18 px 白占着。行那边也要按预算的列集/列宽画（`_hist_row` 只画这一档选中的列，格子宽取
    # 预算里那一份，而颜色/对齐仍按 `core.HIST_COLS` 的 1 基列号算）。
    render = _func(tree, "_render_history")
    row = _func(tree, "_hist_row")
    if render is None or row is None:
        return False
    arrow = any(isinstance(n, ast.Assign) and len(n.targets) == 1
                and _dotted(n.targets[0]) == "self.hist_table.sort_column_index"
                for n in ast.walk(render))
    if not (arrow and "sort_ascending" in ast.unparse(render)):
        return False
    s = ast.unparse(row)
    return "self._hist_cols" in s and "self._hist_w[" in s and "core.HIST_COLS.index" in s


def _p_hist_style(tree):
    # C/H/I（m12075「完全参照 M3 官方设计」）：结算表整体换成官方数据表那一套 —— 表头 56 / 行 52
    # （`T.HIST_HEAD_H`/`T.HIST_ROW_H`，官方 `_md-comp-data-table.scss` 的 header-container-height /
    # row-item-container-height）、表头字 titleSmall、格字 bodyMedium（`T.HIST_HEAD_FONT` /
    # `T.HIST_CELL_FONT`）、行与行之间一条 1px outline-variant（`divider_thickness` +
    # `horizontal_lines`）、整表外框同一条（`border` 四条边）。上一轮那套是表头 36 / 行 28 /
    # labelMedium / bodySmall / 干脆不画分隔线（`divider_thickness=0`）。
    build = _func(tree, "_build_history")
    row = _func(tree, "_hist_row")
    if build is None or row is None:
        return False
    if "T.HIST_CELL_FONT" not in ast.unparse(row):
        return False
    for n in ast.walk(build):
        if not (isinstance(n, ast.Call) and _dotted(n.func) == "ft.DataTable"):
            continue
        if _dotted(_kw(n, "heading_row_height")) != "T.HIST_HEAD_H":
            continue
        if _dotted(_kw(n, "data_row_min_height")) != "T.HIST_ROW_H":
            continue
        if _dotted(_kw(n, "data_row_max_height")) != "T.HIST_ROW_H":
            continue
        if _dotted(_kw(n, "divider_thickness")) != "T.HIST_OUTLINE_W":
            continue
        lines = _kw(n, "horizontal_lines")
        if not (isinstance(lines, ast.Call) and _dotted(lines.func) == "ft.BorderSide"
                and _dotted(lines.args[0]) == "T.HIST_OUTLINE_W"):
            continue
        head = _kw(n, "heading_text_style")
        cell = _kw(n, "data_text_style")
        if not (isinstance(head, ast.Call) and _dotted(head.func) == "T.type_style"
                and _dotted(head.args[0]) == "T.HIST_HEAD_FONT"):
            continue
        if not (isinstance(cell, ast.Call) and _dotted(cell.func) == "T.type_style"
                and _dotted(cell.args[0]) == "T.HIST_CELL_FONT"):
            continue
        border = _kw(n, "border")
        if not (isinstance(border, ast.Call) and _dotted(border.func) == "ft.Border"):
            continue
        sides = [k.value for k in border.keywords]
        return (len(sides) == 4 and all(
            isinstance(s, ast.Call) and _dotted(s.func) == "ft.BorderSide"
            and _dotted(s.args[0]) == "T.HIST_OUTLINE_W" for s in sides))
    return False


def _p_hist_cols(tree):
    # D：数值列右对齐 —— 官方数据表里表头与数值共用一条对齐轴，Flutter 的 `DataColumn.numeric`
    # 既管格的右对齐也管表头的对齐，所以视图层要同时给 `numeric=True` 与
    # `heading_row_alignment=END`。1 基列号必须先换算：`core.HIST_RIGHT`/`HIST_CENTER` 存的是
    # 1 基列号，而这里的 `c` 是列名（照抄 `_hist_row` 的写法，列被丢掉时编号不该跟着挪）。
    fn = _func(tree, "_build_hist_cols")
    if fn is None:
        return False
    s = ast.unparse(fn)
    if not ("n = core.HIST_COLS.index(c) + 1" in s and "right = n in core.HIST_RIGHT" in s):
        return False
    for n in ast.walk(fn):
        if not (isinstance(n, ast.Call) and _dotted(n.func) == "ft.DataColumn"):
            continue
        if _dotted(_kw(n, "numeric")) != "right":
            continue
        hra = _kw(n, "heading_row_alignment")
        if not (isinstance(hra, ast.IfExp) and _dotted(hra.body) == "ft.MainAxisAlignment.END"):
            continue
        return "T.HIST_HEAD_FONT" in s and "on_sort=" in s and "tooltip=" in s
    return False


def _p_hist_sortinfo(tree):
    # F：「表按什么排的」常显。`_render_history` 只在排序列**还在表上**时才画箭头 ⇒ 排序键被这一档
    # 窗口挤掉时表头那行没落点，所以这一句是 `update_tally` 里无条件拼上去的（挤掉时再补
    # 「该列未显示」）。
    fn = _func(tree, "update_tally")
    if fn is None:
        return False
    s = ast.unparse(fn)
    if not ("该列未显示" in s and "self.hist.sort_desc" in s):
        return False
    return any(isinstance(n, ast.AugAssign) and _dotted(n.target) == "info"
               and "core.HIST_HEADS[self.hist.sort_col]" in ast.unparse(n.value)
               for n in ast.walk(fn))


def _p_hist_dblclick(tree):
    # L：双击一行打开这一局的 HUD 截图。Flet 的 `DataRow` 只有 `on_select_change`（`datatable.py`
    # 里没有 `on_double_tap`）⇒ 只能自己按时间判：同一行两次点击间隔 ≤ `T.DBLCLICK_S` 算双击，
    # 第二下**保留**选中态（用户要的是「双击 = 打开」，不是「打开并取消选中」）。
    fn = _func(tree, "_on_hist_select")
    init = _func(tree, "_build_history")
    if fn is None or init is None:
        return False
    dbl = any(isinstance(n, ast.Compare) and any(
        isinstance(cmp, ast.Attribute) and _dotted(cmp) == "T.DBLCLICK_S"
        for cmp in n.comparators) for n in ast.walk(fn))
    opens = any(isinstance(n, ast.Call) and _dotted(n.func) == "self.open_shot"
                for n in ast.walk(fn))
    s = ast.unparse(fn)
    return (dbl and opens and "time.monotonic()" in s and "self.hist_row_tag = tag" in s
            and "self._hist_click_tag" in s and "_hist_click_tag" in ast.unparse(init))


def _p_hist_hover(tree):
    # J：行悬停态层。官方数据表**只有 hover 这一档**行状态层（`row-item-unselected-hover-state-layer-color`
    # 与 `row-item-selected-hover-state-layer-color` 都是 `on-surface`、opacity 都是 8%），而
    # `DataRow.color` 只吃平色 ⇒ 底色与状态层得先在令牌层合成熟色（`self.tk.hover_fill`），再把
    # `HOVERED`／`DEFAULT` 两格写成 `ControlStateValue` 交给 `DataRow(color=…)`。
    # 只按文本认是不够的：`T.HOVER_STATE` 与 `hover_fill` 在 docstring 里也写着（那条老教训）⇒
    # 必须按 AST 认「那个字面量字典的键」「`if` 的测试里真有 `T.HOVER_STATE`」「合成的色真交给了
    # `DataRow` 的 `color`」。缺 `DEFAULT` 那一格就没接住未声明的状态（选中态是随机来的）。
    fn = _func(tree, "_hist_row")
    if fn is None:
        return False
    keys = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                d = _dotted(k)
                if d.startswith("ft.ControlState."):
                    keys.add(d.rsplit(".", 1)[1])
    guard = any(isinstance(n, ast.If) and "T.HOVER_STATE" in ast.unparse(n.test)
                for n in ast.walk(fn))
    fills = any(isinstance(n, ast.Call) and _dotted(n.func) == "self.tk.hover_fill"
                for n in ast.walk(fn))
    var, row = None, None
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Dict) and len(n.targets) == 1:
            var = _dotted(n.targets[0]) or var
        elif isinstance(n, ast.Call) and _dotted(n.func) == "ft.DataRow":
            row = n
    used = row is not None and var is not None and _dotted(_kw(row, "color")) == var
    return ({"HOVERED", "DEFAULT"} <= keys) and guard and fills and used


def _p_hist_head_surface(tree):
    # K：表头底色就是官方 `header-container-color`（= `surface`，与页面同色），不再是本项目
    # 自己抬一档的 `surface_container_high`（那条已从 `DEVIATIONS` 撤掉）。
    fn = _func(tree, "_build_history")
    if fn is None:
        return False
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and _dotted(n.func) == "ft.DataTable":
            return _dotted(_kw(n, "heading_row_color")) == "self.tk.surface"
    return False


def _p_page_fade(tree):
    # 换页 = 官方 fade-through：旧页淡出（`page_out` = short2 = 100 ms）→ 换内容、缩放**不带动画**
    # 落到 `PAGE_SCALE_IN`（0.92）→ 新页淡入（`page` = short4 = 200 ms）同时把缩放抬回 1。
    # 两处 `seq != self._page_seq`：连点页签时在飞的那一次两拍都要能作废（`show_tab` 里 `+1`）。
    # `_fade_page` 是 **async def**（Python 3.13 里是 `AsyncFunctionDef`）⇒ 得自己认两种函数定义，
    # 借 `_func()` 只会拿到 None、判据变成永远为假的装饰（这条坑踩过一次）。
    fade = next((n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == "_fade_page"), None)
    show = _func(tree, "show_tab")
    # `_func(tree, "__init__")` 会抓到文件里**第一个** `__init__`（`HistModel` 那些都排在前面），
    # 得先认 `class Panel` 再取它自己的 `__init__`。
    cls = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "Panel"), None)
    init = next((n for n in (cls.body if cls else [])
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == "__init__"), None)
    if fade is None or show is None or init is None:
        return False
    if not isinstance(fade, ast.AsyncFunctionDef):
        return False
    anims = {_dotted(n.func) + ":" + ast.unparse(n.args[0])
             for n in ast.walk(fade)
             if isinstance(n, ast.Call) and _dotted(n.func) == "T.animation" and n.args}
    scales = {ast.unparse(n.value) for n in ast.walk(fade)
              if isinstance(n, ast.Assign) and _dotted(n.targets[0]) == "self._body.scale"}
    guards = sum(1 for n in ast.walk(fade)
                 if isinstance(n, ast.Compare) and "self._page_seq" in ast.unparse(n))
    def writes(node, name):
        # `self.X = …`（Assign）与 `self.X += 1`（AugAssign）都算「写过这一处」—— 连点页签那个
        # 作废计数器正是 `+=`，只认 Assign 会把这条判据变成永远为假（差点又踩一次）。
        if isinstance(node, ast.Assign):
            return any(_dotted(t) == name for t in node.targets)
        if isinstance(node, ast.AugAssign):
            return _dotted(node.target) == name
        return False

    return ("T.animation:'page_out'" in anims and "T.animation:'page'" in anims
            and "T.PAGE_SCALE_IN" in scales and "1.0" in scales
            and guards >= 2
            and any(writes(n, "self._page_seq") for n in ast.walk(show))
            and any(writes(n, "self._page_seq") for n in ast.walk(init))
            and "self._fade_page" in ast.unparse(show)
            and any(writes(n, "self._body.animate_scale") for n in ast.walk(fade)))


def _p_log_fade(tree):
    # 日志页点筛选 chip 时整列行被换掉 ⇒ 也走那套两拍淡出淡入；**敲关键词那一路不许淡**
    # （每敲一个字都闪一下就没法打字了）。打字与 chip 共用 `_reload_log_view`，所以淡只能挂在
    # `set_log_filter` 上、不能挂在 `_reload_log_view` 里 —— 这条判据就是钉这个分工的。
    def calls(node, name):
        return any(isinstance(n, ast.Call) and _dotted(n.func) == name
                   for n in ast.walk(node))

    pick = _func(tree, "set_log_filter")
    reload_ = _func(tree, "_reload_log_view")
    search = _func(tree, "_on_log_search")
    if pick is None or reload_ is None or search is None:
        return False
    return (calls(pick, "self._fade_box")
            and not calls(reload_, "self._fade_box")
            and not calls(search, "self._fade_box"))


def _tile_labels(tree):
    u"""`_build_run` 里 `_tile(图标, "标签", 控件…)` 的第二个实参 —— 用户看得见的那几个名字。"""
    fn = _func(tree, "_build_run")
    if fn is None:
        return set()
    out = set()
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_tile"
                and len(n.args) > 1 and isinstance(n.args[1], ast.Constant)
                and isinstance(n.args[1].value, str)):
            out.add(n.args[1].value)
    return out


def _p_run_mode_labels(tree):
    # m14282：运行卡三枚瓦片改名（连续→连续演出 / 跟随游戏→曲目跟随 / 随机演奏→随机曲目）。
    # 2026-10-08 用户 m03411 又把四枚改名（火力等待→LB监测 / AP 停止→AP终止 /
    # 限制正推→正推限制 / 重开上限→断连重试）；2026-10-16 用户 m27959 把「曲目跟随」改成
    # 「乐曲识别」、「随机曲目」改成「随机乐曲」—— 半截名（「连续」「正推」「重试」）与
    # 对不上的旧名（「跟随游戏」「随机演奏」「连续演奏」「火力等待」「AP 停止」
    # 「限制正推」「重开上限」，以及这一轮退休的「曲目跟随」「随机曲目」）一个都不许再当标签；
    # 带空格的「AP 终止」也一起挡掉（用户 m03740：拉丁字母与汉字之间不空格）。
    labels = _tile_labels(tree)
    want = {"连续演出", "演出间隔", "乐曲识别", "随机乐曲",
            "LB监测", "AP终止", "正推限制", "断连重试"}
    return labels == want and not ({"连续", "跟随游戏", "随机演奏", "正推", "重试",
                                    "连续演奏", "火力等待", "AP 停止", "AP 终止",
                                    "限制正推", "重开上限", "曲目跟随", "随机曲目"} & labels)


def _p_modes_exclusive(tree):
    # m14282：两颗模式开关互斥、收口在一处 —— 「乐曲识别」那颗的 on_change 是 `_save_follow`
    # （喊 "follow"），「随机乐曲」那颗走 `_save_defaults`（喊 "random"），谁刚开谁胜出。
    def shouts(fname, keep):
        fn = _func(tree, fname)
        if fn is None:
            return False
        return any(isinstance(n, ast.Call) and _dotted(n.func) == "self._exclusive_modes"
                   and n.args and isinstance(n.args[0], ast.Constant)
                   and n.args[0].value == keep
                   for n in ast.walk(fn))

    return shouts("_save_follow", "follow") and shouts("_save_defaults", "random")


def _p_mode_defaults(tree):
    # m14282：旧存档里两颗都开着（`follow_game` 默认 1）时按「随机」收口 —— `follow_on` 只在
    # `rnd_on` 为 0 时取存档值，否则面板亮着「乐曲识别」、跑起来却是随机选曲，又回到静默不一致。
    fn = _func(tree, "_build_run")
    if fn is None:
        return False
    names = {tg.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
             for tg in n.targets if isinstance(tg, ast.Name)}
    ternary = any(isinstance(n, ast.IfExp) and isinstance(n.test, ast.Name)
                  and n.test.id == "rnd_on" for n in ast.walk(fn))
    used = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "toggle" and len(n.args) > 1
               and isinstance(n.args[1], ast.Name) and n.args[1].id == "follow_on"
               for n in ast.walk(fn))
    return {"rnd_on", "follow_on"} <= names and ternary and used


def _p_dialog(tree):
    # 对话框照官方 `_md-comp-dialog.scss`：标题 headline-small(24)、supporting text
    # body-medium(14)（主题层与视图层两层都要），动作是**文字按钮**（不是 filled 的容器色）。
    # 一律按 AST 查：查模块级 `SRC` 的写法翻不了假，那颗牙就成了装饰（第一版就是这么错的）。
    def _spec(node, fname, idx):
        # `type_style("headlineSmall", fam)` 的档名在第 0 个实参，`txt_spec(v, tk, "…")` 在第 2 个
        return (isinstance(node, ast.Call) and _dotted(node.func) == fname
                and len(node.args) > idx and isinstance(node.args[idx], ast.Constant)
                and isinstance(node.args[idx].value, str) and node.args[idx].value)

    theme_specs = set()
    titles, bodies = set(), set()
    # 主题层那一份在 `THEME_TREE` 里（这条判据挂在 gui 那一侧，两棵树都要走）
    for n in ast.walk(THEME_TREE):
        if _ft_call(n, "DialogTheme"):
            theme_specs = {_spec(_kw(n, "title_text_style"), "type_style", 0),
                           _spec(_kw(n, "content_text_style"), "type_style", 0)}
    sites, dialogs = 0, 0
    for n in ast.walk(tree):
        if _ft_call(n, "AlertDialog"):
            dialogs += 1
            titles.add(_spec(_kw(n, "title"), "txt_spec", 2))
            cont = _kw(n, "content")
            bodies.add(_spec(_kw(cont, "content") if isinstance(cont, ast.Call) else None,
                             "txt_spec", 2))
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "confirm"
                and isinstance(n.value, ast.Call) and _dotted(n.value.func) == "button"
                and isinstance(_kw(n.value, "kind"), ast.Constant)
                and _kw(n.value, "kind").value == "text"):
            sites += 1
    dg = T.theme("dark").dialog_theme
    return (theme_specs == {"headlineSmall", "bodyMedium"}
            and dialogs == 2 and titles == {"headlineSmall"} and len(titles) == 1
            and {b for b in bodies if b} == {"bodyMedium"}
            and sites == 1
            and dg.title_text_style.size == T.type_style("headlineSmall").size == 24
            and dg.content_text_style.size == T.type_style("bodyMedium").size == 14)


def _p_list_theme(tree):
    # 主题层的 `ListTileTheme`：官方两行项 72 由框架自己算，字阶 body-large(16) /
    # body-medium(14)、行首间距 leading-space 16（`_md-comp-list.scss`）。
    lt = T.theme("dark").list_tile_theme
    for n in ast.walk(tree):
        if _ft_call(n, "ListTileTheme"):
            names = {k.arg for k in n.keywords if k.arg}
            sub = _kw(n, "horizontal_spacing")
            return ("dense" not in names and "min_vertical_padding" not in names
                    and isinstance(sub, ast.Subscript) and _dotted(sub.value) == "SPACE"
                    and isinstance(sub.slice, ast.Constant) and sub.slice.value == "lg"
                    and lt.title_text_style.size == T.type_style("bodyLarge").size == 16
                    and lt.subtitle_text_style.size == T.type_style("bodyMedium").size == 14)
    return False


ITEMS11 = (
    (u"运行卡八枚瓦片用新名（连续演出 / 乐曲识别 / 随机乐曲 / LB监测 / AP终止 / 正推限制 / 断连重试），半截名与旧名一个不留",
     _p_run_mode_labels, "gui"),
    (u"「乐曲识别」与「随机乐曲」互斥收口在一处（跟随喊 follow、随机喊 random）",
     _p_modes_exclusive, "gui"),
    (u"旧存档里两颗都开着时按「随机」收口（面板显示的与真实跑法一致）",
     _p_mode_defaults, "gui"),
    ("三张列表都有居中空态", _p_empties, "gui"),
    ("空态真的跟着数据开关", _p_empty_toggle, "gui"),
    ("日志页有自动滚动 / 导出日志 / 清屏", _p_log_tools, "gui"),
    ("键盘清单里每一条 `_on_key` 都接得住", _p_shortcuts, "gui"),
    ("破坏性确认按钮是文字档 + error 字色、无容器色（且 >=3 处带 danger）", _p_danger, "gui"),
    ("选曲行与「最近」那几行拿封面当 leading（缺图有兜底）", _p_jackets, "gui"),
    ("`toast()` 不再是死代码", _p_toast, "gui"),
    ("忙时、本轮停止、强制终止都在视图层当场说话", _p_feedback, "gui"),
    ("页脚的谱面库概况由 `_set_status` 一处写（`load_manifest` 重算后回写）", _p_footer_src, "gui"),
    ("阶段行按状态分色（全 AP / 出事 / 待命 / 即将开打 / 进行态）", _p_phase_colors, "gui"),
    ("设置页「资源」卡的更新链接得住（按钮 → start_update → core）", _p_update, "gui"),
    ("更新收尾把起点按钮刷回空闲（`charts_done` 也调 `refresh_start_state`）", _p_update_tail, "gui"),
    ("「强制重下」先比对后问：`ask` 收得起取消回调，问话在 `_after_check`", _p_askflow, "gui"),
    ("首选目录是唯一落盘的那一件（两枚开关都不落盘）", _p_switch_state, "gui"),
    ("「最近演出」卡进出场都是淡的（整卡 fade_in / fade_out_card，退场靠 rc.seq 作废）",
     _p_recent_motion, "gui"),
    ("两张「最近演出」卡各只列自己那一半（单人页 solo / 多人页左侧 multi，旧说明卡已删）",
     _p_recent_modes, "gui"),
    ("「最近演出」的条数上限分档（单人页 6、多人页 15，三处都读这张卡自己的 pool）",
     _p_recent_pool, "gui"),
    ("多人页那张「最近演出」卡撑满左栏、列表自己滚（卡底与右栏运行卡齐平）",
     _p_recent_fill, "gui"),
    ("设置页横平竖直：两张卡等高（实测常量，不用会炸页的 STRETCH）+ 四枚框铺满各自那一格"
     " + 行距列距同档", _p_settings_grid, "gui"),
    ("尾判滑键那格在设置页、写进 defaults['tail_flick_lead']、夹 0..60，且出厂值与 player 同源",
     _p_tail_lead, "gui"),
    ("多人页没有「断连重试」（房间局不能中途重开；单人页那枚照旧）",
     _p_multi_no_retry, "gui"),
    ("日志页有关键词框，且先搜词后分页签", _p_log_search, "gui"),
    ("日志滚到底是自报的：滚动条按需露面 + 瞬时钉住 + 开关镜像真实状态",
     _p_log_scroll, "gui"),
    ("滚动条只在滚动/悬停时露面（全模块不许再出现 ScrollMode.ADAPTIVE）",
     _p_scroll_thumb, "gui"),
    ("页名是「运行日志」（页签 / 卡片标题 / 快捷键清单三处一起）", _p_log_name, "gui"),
    ("翻「自动滚动」不带走视图、打开落到底；回顶是独立一颗 M3 图标按钮",
     _p_log_pin, "gui"),
    ("错误行不只靠颜色（铺 danger 的 disabled_container，且是整行带）", _p_log_err_tint, "gui"),
    ("只有错误行铺底（分段行只靠 accent 字色，不铺灰底）", _p_log_hdr_flat, "gui"),
    ("日志一行两栏：时间戳固定宽不折行 + 正文吃余量，整行一个选区", _p_log_columns, "gui"),
    ("控制台是下沉一档的凹面 + 工具行下一条分界线", _p_log_pane, "gui"),
    ("日志行距落在 4dp 栅格上（spacing 4 + 上下各 8）", _p_log_rhythm, "gui"),
    ("空态图标坐在 64dp 的 secondary_container 圆底上", _p_empty_badge, "gui"),
    ("空态两行字各就各位（主句 on_surface 的 bodySmall、提示句 on_surface_variant 的 bodySmall，"
     "没有 labelSmall 排句子）", _p_empty_roles, "gui"),
    ("计数行 / 空态 / 首帧都自己推给客户端（不靠泵）", _p_log_push, "gui"),
    ("两种空分开：没有日志 vs 没有匹配", _p_log_two_empty, "gui"),
    ("清屏当场说话（toast 说清了几行）", _p_log_clear_toast, "gui"),
    ("chip 照官方画：选中不描边、未选中不铺底，统一走 `tk.chip_side()`", _p_chip_view, "gui"),
    ("chip 的两句规范数留在令牌层（透明底 + 内边距 8）", _p_chip_theme, "theme"),
    ("两排 chip 的间距都是 8（官方 chip set）", _p_chip_gap, "gui"),
    ("点筛选当场把 chip 推出去（点了选中态就变）", _p_chip_push, "gui"),
    ("结算表列宽按窗口现算（可用宽/占宽各只有一个出处）", _p_hist_fit, "gui"),
    ("窗口 resize 重挑列，但只按指纹重建（表头也由预算造）", _p_hist_sync, "gui"),
    ("排序箭头真指到排序列（行按预算的列集/列宽画）", _p_hist_arrow, "gui"),
    ("结算表照官方数据表：表头 56 / 行 52 / titleSmall+bodyMedium / 1px 行间线+外框",
     _p_hist_style, "gui"),
    ("数值列表头也右对齐（1 基列号先换算；numeric + heading END）", _p_hist_cols, "gui"),
    ("「按什么排的」常显（排序键被挤掉时说该列未显示）", _p_hist_sortinfo, "gui"),
    ("双击一行打开这一局的截图（自己按时间判，第二下保留选中）", _p_hist_dblclick, "gui"),
    ("行悬停态层 = 行底色 + on_surface @ 8%（HOVERED 与 DEFAULT 两格都在）", _p_hist_hover, "gui"),
    ("表头底色 = 官方 header-container-color（surface，不再抬一档）",
     _p_hist_head_surface, "gui"),
    ("换页是 fade-through：先淡出、新页从不带动画的 0.92 淡回来，两拍各自能作废",
     _p_page_fade, "gui"),
    ("日志页点筛选 chip 也淡（打字那一路共用 `_reload_log_view`，不淡）", _p_log_fade, "gui"),
    ("17 张组件级主题都在", _p_themes, "theme"),
    ("17 张主题的值都落在令牌 / 规范标度上（手挑值只有登记过的那几个常量）",
     _p_theme_values, "theme"),
    ("对话框照官方：标题 headlineSmall(24) / 正文 bodyMedium(14) / 动作是文字按钮",
     _p_dialog, "gui"),
    ("选曲列表的主题层：无密集档、无额外竖向内边距、字阶与行首间距照官方",
     _p_list_theme, "theme"),
)

# 每条判据自带一颗牙：把对应的守卫改坏、重新解析一遍，这条判据必须变假。
TEETH11 = (
    ("瓦片退回旧名", _p_run_mode_labels, "gui",
     '_line(_tile(ft.Icons.SYNC, "连续演出", self.n_field),',
     '_line(_tile(ft.Icons.SYNC, "连续", self.n_field),'),
    ("互斥：跟随那侧不喊了", _p_modes_exclusive, "gui",
     'self._exclusive_modes("follow")', 'self._exclusive_modes_off("follow")'),
    ("互斥：随机那侧不喊了", _p_modes_exclusive, "gui",
     'self._exclusive_modes("random")', 'self._exclusive_modes_off("random")'),
    ("旧存档不再收口", _p_mode_defaults, "gui",
     '0 if rnd_on else int(self.state.get("follow_game", 1))',
     'int(self.state.get("follow_game", 1))'),
    ("空态", _p_empties, "gui", "alignment=ft.Alignment.CENTER, expand=True,",
     "alignment=ft.Alignment.TOP_LEFT, expand=True,"),
    ("空态开关", _p_empty_toggle, "gui", "        self.hist_box.visible = not empty\n", ""),
    ("空态提示句退回标签字阶", _p_empty_roles, "gui",
     'txt(hint, tk, "n", color=tk.text_dim, text_align=ft.TextAlign.CENTER)',
     'txt(hint, tk, "s", color=tk.text_dim, text_align=ft.TextAlign.CENTER)'),
    ("空态主句又铺灰（主次分不出来）", _p_empty_roles, "gui",
     'txt(text, tk, "n", text_align=ft.TextAlign.CENTER)',
     'txt(text, tk, "n", color=tk.text_dim, text_align=ft.TextAlign.CENTER)'),
    # 这颗牙原来咬的是 `self.log_view.auto_scroll = bool(e.control.value)`；加了 `_on_log_scroll`
    # 之后源码里还有第二处给 `auto_scroll` 赋值（日志开关镜像真实钉住状态），那颗牙就咬不动了
    # （拆掉仍是真）。改咬开关自己的绑定 —— 它才是 `_p_log_tools` 里 `log_autoscroll` 那一支的守卫。
    ("日志工具", _p_log_tools, "gui",
     '        self.log_autoscroll = switch(self.tk, "自动滚动", True, _auto,',
     '        self.log_autoscroll_x = switch(self.tk, "自动滚动", True, _auto,'),
    ("清单少一条实现", _p_shortcuts, "gui",
     'elif ctrl and key == "F":', 'elif ctrl and key == "G":'),
    ("清单多一条没人接", _p_shortcuts, "gui",
     '("F5", "开始演奏 / 开始演出"),', '("F8", "开始演奏 / 开始演出"),'),
    ("危险按钮", _p_danger, "gui",
     '        confirm.style = ft.ButtonStyle(\n            color={ft.ControlState.DEFAULT: tk.danger,',
     '        confirm.style = ft.ButtonStyle(\n            color={ft.ControlState.DEFAULT: tk.accent,'),
    ("封面", _p_jackets, "gui", "leading=song_leading(self.tk, s,",
     "leading=band_avatar(self.tk, s,"),
    # 用户 m28348 的两颗牙：① 重读数据之后不按 bandId 接回选择（下拉框里剩旧标签 ⇒ 筛选
    # 静默退回「全部」）；② 封面缓存把「没有」也记下来（新歌永远只显示兜底图标）。
    ("重读数据不接回分类选择", _p_cat_refresh, "gui",
     '        keep = self.cat_map.get(self.cat_box.value) if hasattr(self, "cat_box") else None\n',
     "        keep = None\n"),
    ("封面把「没有」也缓存", _p_jackets, "gui",
     "    if os.path.exists(p):\n        _JACKETS[key] = p\n        return p\n    return None\n",
     "    _JACKETS[key] = p if os.path.exists(p) else None\n    return _JACKETS[key]\n"),
    ("摘要卡封面", _p_jackets, "gui",
     "self._set_card_art(c, jacket_src(song_music_id(self.manifest, song)))",
     "self._set_card_art(c, None)"),
    ("忙时说话", _p_feedback, "gui", '        toast(self.page, self.tk, "已在演奏")',
     "        pass"),
    ("停轮说话", _p_feedback, "gui", '        self.core.stop_graceful()',
     "        pass"),
    ("阶段配色", _p_phase_colors, "gui",
     '        elif text.startswith("倒计时"):\n            color = self.tk.warn',
     '        elif text.startswith("倒计时"):\n            color = self.tk.accent'),
    ("页脚回写", _p_footer_src, "gui",
     "# 还不存在，`_set_status` 自己会跳过，随后由 `main()` 里那次补上 —— 一处写、两条路都对。\n"
     "        self._set_status(self._lib_status)",
     "pass"),
    ("资源更新链", _p_update, "gui",
     '            self.tk, "联网更新", lambda _e: self.start_update(), kind="tonal",',
     '            self.tk, "联网更新", lambda _e: None, kind="tonal",'),
    ("ask 收不起回调", _p_askflow, "gui",
     'def ask(page, tk, title, body, on_ok, ok_label="确定", danger=False, on_cancel=None,\n'
     '        scrollable=False):',
     'def ask(page, tk, title, body, on_ok, ok_label="确定", danger=False):'),
    ("问话不再带取消回调", _p_askflow, "gui",
     '                on_cancel=lambda: self.core.answer_update(False))',
     '                )'),
    ("起链路那一按", _p_askflow, "gui",
     '        self._run_update()\n', '        pass\n'),
    ("开关落盘", _p_switch_state, "gui",
     '        self.force_chk = toggle(\n            self.tk, 0, None,',
     '        self.force_chk = toggle(\n            self.tk, int(self.state.get("force", 0)),'
     ' None,'),
    ("更新收尾", _p_update_tail, "gui",
     '        elif kind == "charts_done":\n            self.refresh_data()\n'
     '            self.refresh_start_state()\n',
     '        elif kind == "charts_done":\n            self.refresh_data()\n'),
    ("toast 调用点", _p_toast, "gui", 'toast(self.page, self.tk, f"清理完成',
     '_nope(self.page, self.tk, f"清理完成'),
    ("组件级主题", _p_themes, "theme", "divider_theme=ft.DividerTheme(",
     "_xx_theme=ft.DividerTheme("),
    ("主题层塞裸色值", _p_theme_values, "theme",
     'bgcolor=tk.surface, color=tk.text, elevation=ELEVATION["level0"],',
     'bgcolor="#141218", color=tk.text, elevation=ELEVATION["level0"],'),
    ("主题层写错形状名", _p_theme_values, "theme",
     'radius=radius("card")', 'radius=radius("cardd")'),
    ("最近卡进场", _p_recent_motion, "gui",
     "self.page.run_task(self._fade_in, card_)", "pass"),
    ("最近卡退场", _p_recent_motion, "gui",
     "self.page.run_task(self._fade_out_card, rc, rc.seq)",
     "card_.visible = False"),
    ("最近卡只同步一张", _p_recent_motion, "gui",
     "for rc in (self.recent, self.m_recent):\n            rows = rc.rows",
     "for rc in (self.recent,):\n            rows = rc.rows"),
    ("最近卡退场闸门挂回 self 上的旧字段", _p_recent_motion, "gui",
     "rc.hiding = True", "self._recent_hiding = True"),
    ("多人页左栏退回说明卡", _p_recent_modes, "gui",
     'self._multi_left = ft.Column([self._build_last_run("multi")], spacing=T.SPACE["md"],',
     'self._multi_left = ft.Column([self._build_multi_note()], spacing=T.SPACE["md"],'),
    ("单人页那张卡不按 mode 建行", _p_recent_modes, "gui",
     "self._build_run_card(i, mode)", "self._build_run_card(i, \"solo\")"),
    ("最近演出卡退回旧名", _p_recent_modes, "gui",
     'self.title = "最近演出"', 'self.title = "最近"'),
    ("取数不按那一半过滤", _p_recent_modes, "gui",
     "rows = [r for r in self.recs.values() if core.hist_mode_ok(r, mode)]",
     "rows = [r for r in self.recs.values()]"),
    ("多人页那张卡也刷单人局", _p_recent_modes, "gui",
     "self.hist.recent_tags(len(rc.rows), rc.mode)", "self.hist.recent_tags(len(rc.rows))"),
    ("多人页上限退回 6", _p_recent_pool, "gui",
     "RECENT_POOL_MULTI = 15", "RECENT_POOL_MULTI = 6"),
    ("建行不读这张卡的上限", _p_recent_pool, "gui",
     "for i in range(rc.pool)", "for i in range(RECENT_POOL)"),
    ("算条数不读这张卡的上限", _p_recent_pool, "gui",
     "min(fit, have, rc.pool)", "min(fit, have, RECENT_POOL)"),
    ("卡不按 mode 挑上限", _p_recent_pool, "gui",
     'self.pool = RECENT_POOL if mode == "solo" else RECENT_POOL_MULTI',
     "self.pool = RECENT_POOL"),
    ("多人页那张卡又不撑满那一栏（用户 m13783 看到的那一块）", _p_recent_fill, "gui",
     'box={"expand": True} if fill else None,', "box=None,"),
    ("卡撑了但里面那层 Container 不撑（内容还是从顶上排）", _p_recent_fill, "gui",
     '**({"expand": True} if fill else {}))', "**{})"),
    ("撑满之后列表不滚（行从顶上排、卡底留白）", _p_recent_fill, "gui",
     "scroll=scroll_when_needed() if fill else None,", "scroll=None,"),
    ("撑满那张也按余量放（后面那些记录滚不到）", _p_recent_fill, "gui",
     "show = max(0, min(have, rc.pool)) if rc.fill else max(0, min(fit, have, rc.pool))",
     "show = max(0, min(fit, have, rc.pool))"),
    ("叠栏时不撤那三层 expand（页一滚就红屏）", _p_recent_fill, "gui",
     'self.m_recent.card, getattr(self.m_recent.card, "content", None),\n'
     "                        self.m_recent.body):", "):"),
    ("设置页那两张卡不等高（等高常量被改小）", _p_settings_grid, "gui",
     "SET_CARD_H = 380", "SET_CARD_H = 300"),
    ("设置页左卡不钉高度（退回自然高、下沿又一高一低）", _p_settings_grid, "gui",
     'title="面板", icon=ft.Icons.SETTINGS,\n            box={"height": SET_CARD_H})',
     'title="面板", icon=ft.Icons.SETTINGS,\n            box={"expand": True})'),
    ("设置页两张卡又走 STRETCH（那一页整页渲染不出来）", _p_settings_grid, "gui",
     '            ft.Container(content=self.res_card, col={"xs": 12, "md": 6}),\n'
     '        ], spacing=T.SPACE["sm"], run_spacing=T.SPACE["sm"],\n'
     "            vertical_alignment=ft.CrossAxisAlignment.START)",
     '            ft.Container(content=self.res_card, col={"xs": 12, "md": 6}),\n'
     '        ], spacing=T.SPACE["sm"], run_spacing=T.SPACE["sm"],\n'
     "            vertical_alignment=ft.CrossAxisAlignment.STRETCH)"),
    ("种类偏移那四枚框退回写死的 96（右端贴不到卡内沿）", _p_settings_grid, "gui",
     'sp = num_field(self.tk, int(kd.get(k, 0.0) or 0.0), self._save_kind_lead,\n'
     '                           suffix=" ms", decimals=0, width=None)',
     'sp = num_field(self.tk, int(kd.get(k, 0.0) or 0.0), self._save_kind_lead,\n'
     '                           suffix=" ms", decimals=0, width=96)'),
    ("尾滑那格写了却没排进卡（控件是个摆设）", _p_tail_lead, "gui",
     "], tail_tile),", "]),"),
    ("种类偏移卡名退回「分类偏移」（又与选曲页的分类下拉撞字）", _p_settings_grid, "gui",
     "title=\"种类偏移\", icon=ft.Icons.TUNE)", "title=\"分类偏移\", icon=ft.Icons.TUNE)"),
    ("卡面那句「与分类筛选无关」被抹掉（撞字没人说清）", _p_settings_grid, "gui",
     "按音符种类调提前量 —— 与选曲页那个「分类」筛选（乐队分类）无关。",
     "按音符种类调提前量。"),
    ("尾滑写进了 kind_lead 那个 dict（run.py 会把整局拒掉）", _p_tail_lead, "gui",
     'd["tail_flick_lead"] = self._clamp_field("tail_lead", sp, float,',
     'd.setdefault("kind_lead", {})["tail_flick"] = self._clamp_field("tail_lead", sp, float,'),
    ("尾滑的档位放开到负数（那记滑键被推到尾巴之后）", _p_tail_lead, "gui",
     '"tail_lead": (0.0, 60.0),', '"tail_lead": (-60.0, 60.0),'),
    ("叠栏时不撤那个高度（窄窗内容被挤出卡片）", _p_settings_grid, "gui",
     "c.height = None if stacked else SET_CARD_H", "c.height = SET_CARD_H"),
    ("多人页又把「断连重试」放回去", _p_multi_no_retry, "gui",
     '            opt_line(opt_tile(self.tk, ft.Icons.CHECK_CIRCLE, "AP终止",\n'
     '                              hit_switch(self.m_stop_ap)),\n',
     '            opt_line(opt_tile(self.tk, ft.Icons.CHECK_CIRCLE, "AP终止",\n'
     '                              hit_switch(self.m_stop_ap)),\n'
     '                     opt_tile(self.tk, ft.Icons.RESTART_ALT, "断连重试",\n'
     '                              hit_switch(self.m_stop_ap)),\n'),
    ("多人页又开始写 retry_on_break", _p_multi_no_retry, "gui",
     '        d["stop_on_ap"] = 1 if self.m_stop_ap.value else 0\n',
     '        d["stop_on_ap"] = 1 if self.m_stop_ap.value else 0\n'
     '        d["retry_on_break"] = 0\n'),
    ("多人局又把 retry_break 传成 True", _p_multi_no_retry, "gui",
     '            ok = self.core.start(None, "房间抽曲", diff, n, stop_ap, rnd, False, False,\n',
     '            ok = self.core.start(None, "房间抽曲", diff, n, stop_ap, rnd, True, False,\n'),
    ("日志关键词框", _p_log_search, "gui", "on_change=self._on_log_search",
     "on_change=None"),
    ("关键词不先于页签", _p_log_search, "gui",
     "        if self.log_query and self.log_query.lower() not in text.lower():\n"
     "            return False",
     "        if False:\n            return False"),
    ("日志滚动条", _p_log_scroll, "gui", "scroll=scroll_when_needed(),", "scroll=None,"),
    ("滚动条拇指又变常显（thumb_visibility 翻回 True）", _p_scroll_thumb, "gui",
     "ft.Scrollbar(thumb_visibility=False)", "ft.Scrollbar(thumb_visibility=True)"),
    ("滚动条退回桌面恒显的 ScrollMode.ADAPTIVE", _p_scroll_thumb, "gui",
     "scroll=scroll_when_needed(),", "scroll=ft.ScrollMode.ADAPTIVE,"),
    ("日志瞬时到底", _p_log_scroll, "gui", "auto_scroll_animation=0,",
     "auto_scroll_animation=True,"),
    ("页签退回旧名", _p_log_name, "gui",
     '("运行日志", ft.Icons.ARTICLE_OUTLINED, ft.Icons.ARTICLE)',
     '("日志", ft.Icons.ARTICLE_OUTLINED, ft.Icons.ARTICLE)'),
    ("卡片标题退回旧名", _p_log_name, "gui",
     'title="运行日志", icon=ft.Icons.ARTICLE_OUTLINED,',
     'title="日志", icon=ft.Icons.ARTICLE_OUTLINED,'),
    ("翻开关不接位置", _p_log_pin, "gui",
     "self.page.run_task(_pin_back, on, px)", "pass"),
    ("复位不落到底", _p_log_pin, "gui",
     "await self.log_view.scroll_to(offset=(-1.0 if on else px), duration=0)",
     "await self.log_view.scroll_to(offset=px, duration=0)"),
    ("复位那一拍掰开关", _p_log_pin, "gui",
     "        if self._log_pin:\n", "        if False:\n"),
    ("位置账不记了", _p_log_pin, "gui",
     "        self._log_pixels = pixels\n", "        pass\n"),
    # 用户 m27254：用户自己滚离底部时又去翻 `auto_scroll`（换掉客户端元素树形状 ⇒ 整屏跳回
    # 顶部）。旧的 `self.log_view.auto_scroll = at_bottom` 就是那一手，把它放回去必须被咬住。
    ("滚离底部又翻钉住", _p_log_pin, "gui",
     "        if self.log_view.auto_scroll and bool(ctl.value) != at_bottom:\n",
     "        if bool(ctl.value) != at_bottom:\n"
     "            self.log_view.auto_scroll = at_bottom\n"),
    ("回顶不是瞬时", _p_log_pin, "gui",
     "await self.log_view.scroll_to(offset=0, duration=0)",
     "await self.log_view.scroll_to(offset=0, duration=1)"),
    ("回顶按钮换图标", _p_log_pin, "gui",
     "icon=ft.Icons.VERTICAL_ALIGN_TOP, icon_size=T.ICON_LG,",
     "icon=ft.Icons.VERTICAL_ALIGN_BOTTOM, icon_size=T.ICON_LG,"),
    ("错误行底色", _p_log_err_tint, "gui",
     'band = self.tk.state(self.tk.danger, "disabled_container")',
     'band = None'),
    ("分段行不铺底", _p_log_hdr_flat, "gui",
     '        if kind == "log_err":',
     '        if kind in ("log_err", "log_hdr"):'),
    ("时间戳独立栏", _p_log_columns, "gui", "width=T.LOG_TS_W, no_wrap=True,",
     "width=None, no_wrap=True,"),
    ("整行一个选区", _p_log_columns, "gui",
     'row = ft.SelectionArea(content=ft.Row([gut, msg], spacing=T.SPACE["xs"],',
     'row = ft.Container(content=ft.Row([gut, msg], spacing=T.SPACE["xs"],'),
    ("控制台凹面", _p_log_pane, "gui",
     'bgcolor=self.tk.surface, border_radius=T.radius("card"),',
     'bgcolor=None, border_radius=T.radius("card"),'),
    ("控制台分界线", _p_log_pane, "gui",
     "body = ft.Column([head, hairline(self.tk), self.log_pane],",
     "body = ft.Column([head, self.log_pane],"),
    ("日志行距", _p_log_rhythm, "gui",
     'self.log_view = ft.ListView(expand=True, spacing=T.SPACE["xs"], auto_scroll=True,',
     'self.log_view = ft.ListView(expand=True, spacing=T.SPACE["sm"], auto_scroll=True,'),
    ("日志列表内边距", _p_log_rhythm, "gui",
     'padding=ft.Padding(0, T.SPACE["sm"], 0, T.SPACE["sm"]))',
     'padding=ft.Padding(0, 0, 0, 0))'),
    ("空态圆底", _p_empty_badge, "gui",
     "width=T.EMPTY_BADGE, height=T.EMPTY_BADGE, shape=ft.BoxShape.CIRCLE,",
     "width=T.EMPTY_ICON, height=T.EMPTY_ICON, shape=ft.BoxShape.CIRCLE,"),
    ("空态图标配色", _p_empty_badge, "gui",
     "content=ft.Icon(icon, size=T.EMPTY_ICON, color=tk.on_secondary_container)",
     "content=ft.Icon(icon, size=T.EMPTY_ICON, color=tk.outline)"),
    ("计数行自己推", _p_log_push, "gui", "self._push_ctl(self.log_info)", "pass"),
    ("两种空互斥", _p_log_two_empty, "gui",
     'self._toggle_empty(getattr(self, "log_none", None), no_match)', "pass"),
    ("清屏说话", _p_log_clear_toast, "gui",
     '            toast(self.page, self.tk, f"已清空 {n} 行日志" if n else "日志当前为空")',
     "            pass"),
    ("chip 选中不描边", _p_chip_view, "gui", "border_side=tk.chip_side(selected),",
     "border_side=ft.BorderSide(1, tk.outline_variant),"),
    ("chip 重刷描边", _p_chip_view, "gui", "chip.border_side = tk.chip_side(on)",
     "chip.border_side = None"),
    ("chip 不铺底", _p_chip_theme, "theme",
     "bgcolor=ft.Colors.TRANSPARENT, selected_color=tk.secondary_container,",
     "bgcolor=tk.surface, selected_color=tk.secondary_container,"),
    ("chip 透明描边", _p_chip_theme, "theme",
     "return ft.BorderSide(1, ft.Colors.TRANSPARENT if on else self.outline_variant)",
     "return ft.BorderSide(1, self.outline_variant)"),
    ("chip 间距 8", _p_chip_gap, "gui",
     '            ft.Row(btns + [self.log_search, self.log_info],\n'
     '                   spacing=T.SPACE["sm"],',
     '            ft.Row(btns + [self.log_search, self.log_info],\n'
     '                   spacing=T.SPACE["xs"],'),
    ("chip 选中要推出去", _p_chip_push, "gui", "        self._push_ctl(*self.log_btns.values())",
     "        pass"),
    ("结算表可用宽不问出处", _p_hist_fit, "gui", "        avail = self._hist_avail(w)",
     "        avail = w"),
    ("结算表忘了算箭头格", _p_hist_fit, "gui",
     "        cells = core.CHIP_W + sum(widths[c] + T.HIST_ARROW_W for c in cols)",
     "        cells = core.CHIP_W + sum(widths[c] for c in cols)"),
    ("resize 不重挑列", _p_hist_sync, "gui", "        self._sync_hist_cols(width)",
     "        pass"),
    ("列预算不留指纹", _p_hist_sync, "gui", "        self._hist_sig = sig\n", ""),
    ("排序箭头不再指向", _p_hist_arrow, "gui",
     "        self.hist_table.sort_ascending = not self.hist.sort_desc\n", ""),
    ("行不按预算的列宽画", _p_hist_arrow, "gui",
     "                width=self._hist_w[name], alignment=align)))",
     "                width=core.HIST_WIDTHS[c], alignment=align)))"),
    ("结算表退回桌面密度", _p_hist_style, "gui",
     "            heading_row_height=T.HIST_HEAD_H,\n",
     "            heading_row_height=36,\n"),
    ("表头字退回 labelMedium", _p_hist_style, "gui",
     "            heading_text_style=T.type_style(T.HIST_HEAD_FONT),\n",
     '            heading_text_style=T.type_style("labelMedium"),\n'),
    ("行间线不画", _p_hist_style, "gui",
     "            divider_thickness=T.HIST_OUTLINE_W,\n",
     "            divider_thickness=0,\n"),
    ("数值列不右对齐", _p_hist_cols, "gui",
     "                numeric=right,\n", "                numeric=False,\n"),
    ("数值列忘了换算 1 基列号", _p_hist_cols, "gui",
     "            n = core.HIST_COLS.index(c) + 1\n",
     "            n = 1\n"),
    ("不报按什么排的", _p_hist_sortinfo, "gui",
     '            info += (f"；按「{core.HIST_HEADS[self.hist.sort_col][0]}」"\n'
     '                     f"{\'降序\' if self.hist.sort_desc else \'升序\'}")\n',
     "            pass\n"),
    ("双击不判间隔", _p_hist_dblclick, "gui",
     '               and now - getattr(self, "_hist_click_at", 0.0) <= T.DBLCLICK_S)',
     '               and now - getattr(self, "_hist_click_at", 0.0) <= 0)'),
    ("双击的时间戳不留档", _p_hist_dblclick, "gui",
     "        self._hist_click_tag = None\n", ""),
    ("悬停态层被关掉", _p_hist_hover, "gui", "if T.HOVER_STATE:", "if False:"),
    ("悬停少 DEFAULT 那一格", _p_hist_hover, "gui",
     "ft.ControlState.DEFAULT: bg or self.tk.surface",
     "ft.ControlState.FOCUSED: bg or self.tk.surface"),
    ("表头底色抬一档", _p_hist_head_surface, "gui", "heading_row_color=self.tk.surface,",
     "heading_row_color=self.tk.surface_container_high,"),
    ("新页不从 0.92 起", _p_page_fade, "gui", "self._body.scale = T.PAGE_SCALE_IN",
     "self._body.scale = 1.0"),
    ("换页不记 seq", _p_page_fade, "gui", "self._page_seq += 1", "pass"),
    ("日志筛选的淡被摘掉", _p_log_fade, "gui",
     'self._fade_box(getattr(self, "log_view", None))', "pass"),
    ("对话框标题退回旧档", _p_dialog, "gui",
     'title=txt_spec(title, tk, "headlineSmall", color=tk.text),',
     'title=txt_spec(title, tk, "titleMedium", color=tk.text),'),
    ("对话框动作退回 filled", _p_dialog, "gui",
     'confirm = button(tk, ok_label, _ok, kind="text")',
     'confirm = button(tk, ok_label, _ok, kind="filled")'),
    ("主题层又挂回密集档", _p_list_theme, "theme",
     '            horizontal_spacing=SPACE["lg"]),',
     '            dense=True, horizontal_spacing=SPACE["lg"]),'),
)


def part11():
    print("PART 11  精致度那一轮（空态 / 封面 / 快捷键 / 危险按钮 / 组件级主题）")
    box = {"gui": (SRC, TREE), "theme": (THEME_SRC, THEME_TREE)}
    ok = True
    for label, pred, which in ITEMS11:
        ok = check(label, bool(pred(box[which][1]))) and ok
    for label, pred, which, old, new in TEETH11:
        src = box[which][0]
        if src.count(old) != 1:
            ok = check(f"牙 {label}：锚点唯一", False,
                       f"{src.count(old)} 处 `{old.strip()[:40]}`") and ok
            continue
        try:
            mt = ast.parse(src.replace(old, new))
        except SyntaxError as e:
            ok = check(f"牙 {label}：改坏之后必须变假", False, f"改完不再是合法 python：{e}") and ok
            continue
        flipped = not pred(mt)
        ok = check(f"牙 {label}：把守卫拆掉这条判据必须变假", flipped,
                   "" if flipped else "拆了还是真的 —— 这条判据是装饰") and ok
    print("PART 11 " + ("PASS" if ok else "FAIL"))
    return ok



if __name__ == "__main__":
    import time
    t0 = time.time()
    oks = [(fn.__name__, fn()) for fn in (part1, part2, part3, part4, part5, part6, part7, part8,
                                          part9, part10, part11)]
    print()
    failed = [n for n, ok in oks if not ok]
    if failed or FAILS:
        print(f"PART 探针 FAIL：{len(set(failed)) + len(set(FAILS))} 项")
        for n in failed:
            print("  -", n)
        for f in dict.fromkeys(FAILS):
            print("  -", f)
        sys.exit(1)
    print(f"ALL PASS（{time.time() - t0:.1f}s）")
