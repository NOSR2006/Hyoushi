"""Measure the perspective field geometry from a LIVE screenshot.

The judgment line is the bright magenta horizontal bar; its x-extent at its own
row is the pixel span the 24 lanes are distributed across.

Usage: python tools/probes/fieldcal.py <screenshot.png>
"""
import sys

import numpy as np
from PIL import Image

USAGE = "usage: python tools/probes/fieldcal.py <screenshot.png>"


def main():
    # 按需工具：它读一张指定的截图，没有默认对象可猜。裸跑时给一行用法，而不是
    # 一个 IndexError 堆栈（这份文件从前连用法行都没有）。
    if len(sys.argv) < 2:
        print(USAGE)
        return 2
    path = sys.argv[1]
    img = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    h, w, _ = img.shape
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    magenta = (r > 150) & (b > 150) & (g < 110) & ((r - g) > 60) & ((b - g) > 60)
    counts = magenta.sum(axis=1)

    print(f"image {w}x{h}")
    rows = [(y, int(counts[y])) for y in range(h) if counts[y] > w * 0.4]
    if not rows:
        print("no full-width magenta row found")
        return
    print("candidate judgment rows (y, magenta_px, x_min, x_max):")
    for y, c in rows:
        xs = np.flatnonzero(magenta[y])
        print(f"  y={y:4d} n={c:5d} x=[{xs.min()},{xs.max()}] span={xs.max()-xs.min()}")

    # lane guide lines: bright near-white pixels, per row, leftmost/rightmost
    white = (r > 200) & (g > 200) & (b > 200)
    print("\nfield edge trace (white diagonals):")
    for y in range(100, h - 5, 100):
        xs = np.flatnonzero(white[y])
        if xs.size:
            print(f"  y={y:4d} left={xs.min():5d} right={xs.max():5d} n={xs.size}")


if __name__ == "__main__":
    raise SystemExit(main())
