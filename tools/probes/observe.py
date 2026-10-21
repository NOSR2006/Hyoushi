"""Sit out a LIVE and record every note blob with its host timestamp, tapping nothing.

Why: t0 currently comes from extrapolating a three-sample track of a single note, and two runs of
the same chart put it 100+ ms apart -- which is the whole difference between a7's 417 misses and
a8's 512. This measures the same quantity with roughly a thousand detections instead of three, so
the clock relationship (bias, and whether it drifts at all) can be fit offline in one shot.

Nothing is tapped. A LIVE reaches FINISH with zero input and MISS only costs HP, so an observation
run is free.

Both timestamps are kept per frame: `adb exec-out screencap` blocks for ~220 ms, and whether the
returned pixels are from the moment the call started or the moment it returned is a 220 ms question
-- about four judgement windows -- that labelling alone cannot answer.
"""
import argparse
import json
import sys
import time

sys.path.insert(0, "tools")
import numpy as np  # noqa: E402

from calib import start_live  # noqa: E402
from detect import bands, capture, field_mask, note_mask, widest_run  # noqa: E402
from mtouch import MTouch  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=100.0)
    ap.add_argument("--tag", default="obs")
    args = ap.parse_args()

    inj = MTouch()
    if not start_live(inj):
        inj.close()
        print("could not reach a LIVE")
        return 1
    inj.close()          # deliberately: this run must not touch the screen at all

    frames = []
    detections = []
    t_end = time.perf_counter() + args.seconds
    while time.perf_counter() < t_end:
        t_call = time.perf_counter()
        try:
            raw = capture()
        except Exception as exc:
            print(f"  capture failed: {exc!r}", flush=True)
            continue
        t_ret = time.perf_counter()
        img = raw[:, :, :3]
        m = note_mask(img) & field_mask()
        rows = bands(m)
        frames.append({"t_call": t_call, "t_ret": t_ret, "n_bands": len(rows)})
        for y0, y1 in rows:
            x0, x1 = widest_run(m, y0, y1)
            if x1 - x0 + 1 < 20:
                continue
            detections.append({"t_call": t_call, "t_ret": t_ret,
                               "y0": y0, "y1": y1, "x0": x0, "x1": x1})
        if len(frames) % 50 == 0:
            print(f"  {len(frames)} frames, {len(detections)} blobs, "
                  f"capture {t_ret - t_call:.3f}s", flush=True)

    path = f"research/observe_{args.tag}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"frames": frames, "detections": detections}, fh)
    lat = np.array([f["t_ret"] - f["t_call"] for f in frames])
    print(f"{len(frames)} frames, {len(detections)} blobs -> {path}")
    print(f"capture duration: p50 {np.median(lat) * 1000:.0f} ms "
          f"min {lat.min() * 1000:.0f} max {lat.max() * 1000:.0f}")


if __name__ == "__main__":
    main()
