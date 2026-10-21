"""Burst-capture live frames, running the note detector inline so the loop stays at capture rate.

Writes bands.json (one entry per frame, with the host timestamp of the capture start) and keeps a
PNG every --keep frames for eyeballing.
"""
import argparse
import json
import os
import sys
import time

from PIL import Image

sys.path.insert(0, "tools")
from detect import capture, field_mask, note_mask, bands, widest_run  # noqa: E402
from inject import TouchInjector, to_raw  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--keep", type=int, default=5, help="save every Nth frame as PNG")
    ap.add_argument("--tap", default="", help="screen point fired right before recording starts")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    inside = field_mask()
    manifest = []
    tap_t = None
    inj = TouchInjector() if args.tap else None
    t_end = time.perf_counter() + args.seconds
    k = 0
    while True:
        t = time.perf_counter()
        if t >= t_end:
            break
        if inj is not None:
            sx, sy = (int(v) for v in args.tap.split(","))
            inj.tap(*to_raw("MEASURED", sx, sy), hold_s=0.08)
            tap_t = time.perf_counter()
            print(f"tapped ({sx},{sy}) at {tap_t:.3f}", flush=True)
            inj.close()
            inj = None
        img = capture()
        m = note_mask(img).astype(bool) & inside
        bs = [(a, b) + widest_run(m, a, b) for a, b in bands(m)]
        manifest.append({"i": k, "t": t, "tap": tap_t,
                         "bands": [list(x) for x in bs if x[3] - x[2] > 40]})
        tap_t = None
        if k % args.keep == 0:
            Image.fromarray(img[..., :3]).save(f"{args.outdir}/f{k:03d}.png")
        k += 1
    with open(f"{args.outdir}/bands.json", "w") as f:
        json.dump(manifest, f)
    ts = [m["t"] for m in manifest]
    print(f"{len(ts)} frames in {ts[-1]-ts[0]:.1f}s, mean gap "
          f"{(ts[-1]-ts[0])/max(1,len(ts)-1)*1000:.0f} ms")


if __name__ == "__main__":
    main()
