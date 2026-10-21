"""生成 Material 3 的 46 个颜色角色冻结表 -> tools/m3_tokens.json。

用 Google 的参考实现 material-color-utilities（`pip install material-color-utilities==0.2.6`）。
方案取 **TONALSPOT + contrast_level=0.0** —— 这正是 Flutter `ColorScheme.fromSeed` 的默认档，
也就是 M3 规范手册的基线（VIBRANT 那档是 Material You 的"多彩"变体，不是基线）。

面板运行时只读冻结表，不 import 这个包：`tools/m3_theme.py` 负责加载。
本脚本是那张表的出处，也是 `tools/probes/m3tokens.py` 重算比对的同一套逻辑。

用法：.venv\\Scripts\\python.exe tools\\gen_m3_tokens.py
"""
import json
import os
import sys

import material_color_utilities as mcu

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tools", "m3_tokens.json")

# 面板的身份色：沿用旧 QSS 的 ACCENT（Radix Indigo 9）。M3 只拿它当"种子"，
# 真正的角色值是种子经 HCT 色调板映射出来的，所以观感会变（这是规范要求的）。
SEED = "#3e63dd"
VARIANT = "TONALSPOT"
CONTRAST = 0.0

# 46 个角色，名字与 flet.ColorScheme 的字段逐字相同（顺序也照它的声明顺序）。
ROLES = (
    "primary", "on_primary", "primary_container", "on_primary_container",
    "secondary", "on_secondary", "secondary_container", "on_secondary_container",
    "tertiary", "on_tertiary", "tertiary_container", "on_tertiary_container",
    "error", "on_error", "error_container", "on_error_container",
    "surface", "on_surface", "on_surface_variant", "outline", "outline_variant",
    "shadow", "scrim", "inverse_surface", "on_inverse_surface", "inverse_primary",
    "surface_tint",
    "on_primary_fixed", "on_secondary_fixed", "on_tertiary_fixed",
    "on_primary_fixed_variant", "on_secondary_fixed_variant", "on_tertiary_fixed_variant",
    "primary_fixed", "secondary_fixed", "tertiary_fixed",
    "primary_fixed_dim", "secondary_fixed_dim", "tertiary_fixed_dim",
    "surface_bright", "surface_container", "surface_container_high",
    "surface_container_highest", "surface_container_low", "surface_container_lowest",
    "surface_dim",
)

# flet 的角色名 -> material-color-utilities 的属性名。只有这一个不一样：
# flet 写 on_inverse_surface，参考实现写 inverse_on_surface。其余 45 个逐字相同。
MCU_NAME = {"on_inverse_surface": "inverse_on_surface"}

# ---- 扩展角色（M3 规范里没有的语义色）----
#
# 规范只给了 error 一个"状态色"，面板要的"成功 / 警告"和难度四色都不在其中。做法不是随手挑
# hex，而是**用规范自己的规则扩展**：给一个色相 + 色度，按规范给 error 分配角色的那套色调来取
# 值（对照规范里的 error：浅色 E40/白字、容器 E90/E10；深色 E80/E20、容器 E30/E90）——
#
#   强调色   浅 T40   深 T80        on_强调色   浅 T100  深 T20
#   容器色   浅 T90   深 T30        on_容器色   浅 T10   深 T90
#
# 于是扩展色与 46 个角色出自同一台机器、同一条规则，明暗两套的关系也和规范一致（浅色的容器是
# 淡底深字，深色的容器是深底淡字）。色相取常用区间：成功=绿、警告=琥珀、难度四色=蓝/绿/琥珀/红。
# `hard` 与 `warning` 是**同一个琥珀**（同色相同色度），这不是抄漏 —— 旧面板里难度「困难」用的
# 就是那个琥珀，警告也是；写两遍是为了让两个角色各自独立可改。
EXT = {
    "success": (145.0, 48.0),
    "warning": (75.0, 60.0),
    "easy": (240.0, 40.0),
    "normal": (145.0, 40.0),
    "hard": (75.0, 60.0),
    "expert": (25.0, 60.0),
}
# 第五个数是「容器色的下一档」，给结算表的斑马线用（浅 T80、深 T20）。规范里没有这一档，
# 但它就是同一个色调板上的相邻色调，不是新颜色。
EXT_TONES = {"light": (40, 100, 90, 10, 80), "dark": (80, 20, 30, 90, 20)}


def build_ext():
    """返回 {"light": {角色: '#rrggbb'}, "dark": {...}}，角色名形如 success / on_success /
    success_container / on_success_container（难度四色同构）。"""
    out = {"light": {}, "dark": {}}
    for name, (hue, chroma) in EXT.items():
        pal = mcu.TonalPalette(hue, chroma)
        for which in ("light", "dark"):
            t_col, t_on, t_con, t_oncon, t_dim = EXT_TONES[which]
            out[which][name] = mcu.hex_from_argb(pal.get_argb(t_col))
            out[which]["on_" + name] = mcu.hex_from_argb(pal.get_argb(t_on))
            out[which][name + "_container"] = mcu.hex_from_argb(pal.get_argb(t_con))
            out[which]["on_" + name + "_container"] = mcu.hex_from_argb(pal.get_argb(t_oncon))
            out[which][name + "_container_dim"] = mcu.hex_from_argb(pal.get_argb(t_dim))
    return out


def build(seed=SEED, variant=VARIANT, contrast=CONTRAST):
    """返回 {"light": {...46...}, "dark": {...46...}}，值都是 '#rrggbb'。"""
    th = mcu.theme_from_color(seed, contrast_level=contrast,
                              variant=getattr(mcu.Variant, variant))
    out = {}
    for which in ("light", "dark"):
        s = getattr(th.schemes, which)
        # DynamicScheme 的角色属性直接就是 '#rrggbb' 字符串（不是 argb 整数）。
        vals = {r: getattr(s, MCU_NAME.get(r, r)) for r in ROLES}
        for r, v in vals.items():
            if not (isinstance(v, str) and len(v) == 7 and v.startswith("#")):
                raise SystemExit("角色 %s 不是 '#rrggbb'：%r" % (r, v))
        out[which] = vals
    return out


def main():
    schemes = build()
    ext = build_ext()
    # 与 flet.ColorScheme 的字段集合对齐 —— 少一个或多一个都说明规范面变了。
    try:
        import flet as ft
        fields = set(getattr(ft.ColorScheme, "__dataclass_fields__", {}))
        if fields:
            miss = sorted(fields - set(ROLES))
            extra = sorted(set(ROLES) - fields)
            print("flet.ColorScheme 字段 %d 个；ROLES %d 个" % (len(fields), len(ROLES)))
            if miss or extra:
                print("  对不齐！flet 独有 %s / 我独有 %s" % (miss, extra))
                return 1
            print("  逐字段对齐 OK")
    except ImportError:
        print("（没装 flet，跳过字段对齐检查）")

    data = {
        "_what": "M3 的 46 个颜色角色，由 Google 的 material-color-utilities 生成",
        "_how": "TONALSPOT + contrast_level=0.0（Flutter ColorScheme.fromSeed 的默认档）",
        "_gen": "tools/gen_m3_tokens.py",
        "seed": SEED,
        "variant": VARIANT,
        "contrast": CONTRAST,
        "roles": list(ROLES),
        "light": schemes["light"],
        "dark": schemes["dark"],
        "ext_spec": {"hues": {k: list(v) for k, v in EXT.items()},
                     "tones": {k: list(v) for k, v in EXT_TONES.items()},
                     "rule": "强调色 T40/T80、on_  T100/T20、容器 T90/T30、on_容器 T10/T90"},
        "ext": ext,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")

    print("\n写出 %s（%d 字节）" % (OUT, os.path.getsize(OUT)))
    for which in ("light", "dark"):
        s = schemes[which]
        print("\n--- %s" % which)
        for r in ("primary", "on_primary", "primary_container", "secondary", "tertiary",
                  "surface", "surface_container_low", "surface_container",
                  "surface_container_high", "surface_container_highest", "on_surface",
                  "on_surface_variant", "outline", "outline_variant", "error"):
            print("   %-24s %s" % (r, s[r]))
    for which in ("light", "dark"):
        e = ext[which]
        print("\n--- %s 扩展" % which)
        for name in EXT:
            print("   %-24s %s  (on_ %s / 容器 %s %s / on_容器 %s)"
                  % (name, e[name], e["on_" + name], e[name + "_container"],
                     e[name + "_container_dim"], e["on_" + name + "_container"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
