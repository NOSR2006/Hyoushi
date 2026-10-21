"""看图工具：这个会话没有图像输入，所以"看一眼"必须先变成数字。

    python tools/picmap.py <png> [更多 png...]                  # 26x18 的字符图 + 图例
    python tools/picmap.py --geom <png> ...                     # 固定探针点 + 前 6 色的包围盒
    python tools/picmap.py --box 1080,360,1300,560 --cell 6 <png>

字符图：`A`..`P` 是这张图里出现最多的 16 种颜色（图例给出十六进制与占比），落在同一格里的
其他颜色取最近的图例色、用小写写出来，`?` 表示离任何图例色都远。`--box x0,y0,x1,y1` 只看
一块（比例是相对整图的），`--cell` 是每格多少像素（默认按 26 列、18 行均分整图）。

输出全是 ASCII（控制台是 GBK，中文会炸）。像素统计一律 `Counter(im.tobytes())`，不用
`getdata()`（Pillow 12 起已弃用）。
"""

from __future__ import annotations

import os
import sys
from collections import Counter

from PIL import Image

LEGEND = "ABCDEFGHIJKLMNOP"
COLS = 26
PTS = (("rail(60,557)", 60, 557), ("gap(200,557)", 200, 557), ("body(400,300)", 400, 300),
       ("body(1000,600)", 1000, 600), ("top(900,40)", 900, 40), ("bottom(900,1090)", 900, 1090),
       ("right(1730,557)", 1730, 557))


def colours(im):
    raw = im.tobytes()
    return Counter(zip(raw[0::3], raw[1::3], raw[2::3]))


def hexs(c):
    return "#%02x%02x%02x" % c


def draw(path, im, box, cell):
    W, H = im.size
    x0, y0, x1, y1 = box
    sub = im.crop(box)
    sw, sh = sub.size
    cnt = colours(sub)
    top = [c for c, _ in cnt.most_common(len(LEGEND))]
    idx = {c: LEGEND[i] for i, c in enumerate(top)}
    print("== %s  %dx%d  box %d,%d,%d,%d  cell %dpx" % (path, W, H, x0, y0, x1, y1, cell))
    rows, cols = max(1, sh // cell), max(1, sw // cell)
    for r in range(rows):
        line = ""
        for col in range(cols):
            px = x0 + int(sw * (col + 0.5) / cols)
            py = y0 + int(sh * (r + 0.5) / rows)
            p = im.getpixel((px, py))
            if p in idx:
                line += idx[p]
                continue
            best, bd = "?", 1 << 30
            for q in top[:6]:
                d = sum((p[i] - q[i]) ** 2 for i in range(3))
                if d < bd:
                    bd, best = d, idx[q]
            line += best.lower()
        print("   " + line)
    total = sw * sh
    for i, c in enumerate(top[:8]):
        print("   %s %s %5.2f%%" % (LEGEND[i], hexs(c), cnt[c] * 100.0 / total))


def geom(path, im):
    W, H = im.size
    print("== %s  %dx%d" % (path, W, H))
    for name, x, y in PTS:
        if x < W and y < H:
            print("   %-18s %s" % (name, hexs(im.getpixel((x, y)))))
    cnt = colours(im)
    pos = {}
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            pos.setdefault(im.getpixel((x, y)), []).append((x, y))
    for c, n in cnt.most_common(6):          # 每 4 个像素里取 1 个，比例仍按全图算
        p = pos.get(c)
        if not p:
            continue
        xs = [q[0] for q in p]
        ys = [q[1] for q in p]
        print("   %s %6.2f%%  bbox x %d..%d  y %d..%d" % (
            hexs(c), n * 100.0 / (W * H), min(xs), max(xs), min(ys), max(ys)))


def main(argv):
    mode, box, cell, paths = "map", None, None, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--geom":
            mode = "geom"
        elif a == "--box":
            i += 1
            box = tuple(int(v) for v in argv[i].split(","))
        elif a == "--cell":
            i += 1
            cell = int(argv[i])
        else:
            paths.append(a)
        i += 1
    if not paths:
        print(__doc__)
        return 2
    for path in paths:
        if not os.path.exists(path):
            print("!! %s 不存在" % path)
            continue
        im = Image.open(path).convert("RGB")
        if mode == "geom":
            geom(path, im)
        else:
            draw(path, im, box or (0, 0) + im.size, cell or max(4, im.size[0] // COLS))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
