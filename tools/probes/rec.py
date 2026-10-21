"""Record what the LIVE actually shows, in a process of its own, while a run plays the chart.

Why a separate process: the firing loop holds a press to sub-millisecond accuracy, and any work
in that interpreter -- even in a thread, because numpy and PIL hold the GIL -- shows up as a late
action. This recorder never talks to the player, has no shared state, and stamps every frame with
its own clock, so the two are correlated offline through the run's t0.

What it records, and why each region:

  judge_<i>.png  x 250..1030, y 340..560 -- the game draws the judgement word of the note it just
                 resolved at the centre of the field (calib.py reads the same words out of
                 486,398..794,492). A MISS therefore leaves a picture of itself, which is the
                 only way to put a miss on the chart timeline without reading the live counters.
  hud_<i>.png    x 1040..1280, y 100..380 -- the in-song judgement counters and combo, a second
                 and independent way to see a miss land. The counters sit below the top strip,
                 which is the health bar and the pause button.
  full_<i>.jpg   the whole frame every 12th capture, for anything the two crops were not aimed at.

Frame rate is whatever `screencap` gives (~4/s), which is why the crops must keep the word on
screen for longer than a frame to be seen at all; that is measured offline, and it is the number
that says whether this instrument is usable at all.

`--fast` swaps screencap for MuMu's renderer (mumucap, ~150/s measured while a run is playing
too) and changes the plan to match the rate:

  every frame    the five judgement counters (PERFECT..MISS, x 1060..1280 y 125..250): the crop
                 is diffed against the previous one and saved as hit_<k>.png only when it
                 changes. A MISS therefore leaves an image of the counter with its new value and
                 a timestamp a frame (~7 ms) wide -- for a counter that moves a few dozen times
                 over a song that is minimal disk for a very sharp clock.
  every 30th     the judgement word crop as jp_<k>.jpg (~10/s): the word lives ~0.5 s on screen,
                 so this pins which lane missed even at 3 ms steps.
  every 600th    the whole frame as full_<k>.jpg (~0.5/s), for context.

The counters crop starts below the health bar and stops above the combo number, so the only
things in it are the five counters themselves.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, "tools")
import numpy as np  # noqa: E402
from detect import capture, note_blobs  # noqa: E402

JUDGE_CROP = (250, 340, 1030, 560)   # x0, y0, x1, y1
HUD_CROP = (1040, 100, 1280, 380)
COUNTER_CROP = (1060, 125, 1280, 250)   # the five counters, nothing else
FULL_EVERY = 12
CHANGE_PIXELS = 8        # counter digits are white on dark; any real change moves hundreds
CHANGE_MARGIN = 8


def record_fast(args):
    """The mumucap path: counters every frame, judgement word ~25/s, full frames ~2.5/s."""
    from PIL import Image

    import mumucap
    mumucap.install()

    out = f"research/recordings/rec_{args.tag}"
    os.makedirs(out, exist_ok=True)
    x0, y0, x1, y1 = COUNTER_CROP
    jx0, jy0, jx1, jy1 = JUDGE_CROP
    times, hits, jud, full = [], [], [], []
    prev = None
    i = k = j = f = 0
    t_end = time.perf_counter() + args.seconds
    while time.perf_counter() < t_end:
        try:
            t, img = mumucap.frame()
        except Exception as exc:
            print(f"  capture failed: {exc!r}", flush=True)
            time.sleep(0.05)
            continue
        times.append(round(t, 4))
        # mumucap.frame() hands back a slice of one reused buffer, so without the copy `prev`
        # aliases `cur` and every diff is zero -- this is why a38 recorded 0 counter changes.
        cur = img[y0:y1, x0:x1].copy()
        if prev is not None:
            d = np.abs(cur.astype(np.int16) - prev.astype(np.int16))
            if int(np.count_nonzero(np.any(d > CHANGE_MARGIN, axis=2))) > CHANGE_PIXELS:
                name = f"hit_{k:03d}.png"
                Image.fromarray(cur).save(f"{out}/{name}")
                hits.append([round(t, 4), name])
                k += 1
        prev = cur
        if i % args.judge_every == 0:
            name = f"jp_{j:04d}.jpg"
            Image.fromarray(img[jy0:jy1, jx0:jx1]).save(f"{out}/{name}", quality=75)
            jud.append([round(t, 4), name])
            j += 1
        if i % args.full_every == 0:
            name = f"full_{f:04d}.jpg"
            Image.fromarray(img).save(f"{out}/{name}", quality=80)
            full.append([round(t, 4), name])
            f += 1
        i += 1
        if i % 500 == 0:
            print(f"  {i} frames, {k} counter changes", flush=True)

    json.dump({"counter_crop": list(COUNTER_CROP), "judge_crop": list(JUDGE_CROP),
               "judge_every": args.judge_every, "full_every": args.full_every,
               "times": times, "hits": hits, "judge": jud, "full": full},
              open(f"research/recordings/rec_{args.tag}.json", "w", encoding="utf-8"))
    print(f"{i} frames, {k} counter changes, {j} judgement crops -> {out}/, "
          f"index research/recordings/rec_{args.tag}.json", flush=True)
    mumucap.uninstall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=200.0)
    ap.add_argument("--tag", default="rec")
    ap.add_argument("--no-blobs", action="store_true",
                    help="skip the numpy pass; only the pictures are kept")
    ap.add_argument("--fast", action="store_true",
                    help="mumucap source (~150 fps) with the counters/judge/full plan")
    ap.add_argument("--judge-every", type=int, default=30)
    ap.add_argument("--full-every", type=int, default=600)
    args = ap.parse_args()

    if args.fast:
        record_fast(args)
        return

    from PIL import Image

    out = f"research/recordings/rec_{args.tag}"
    os.makedirs(out, exist_ok=True)
    frames, blobs = [], []
    i = 0
    t_end = time.perf_counter() + args.seconds
    while time.perf_counter() < t_end:
        t_call = time.perf_counter()
        try:
            img = capture()[:, :, :3]
        except Exception as exc:
            print(f"  capture failed: {exc!r}", flush=True)
            time.sleep(0.05)
            continue
        t_ret = time.perf_counter()
        x0, y0, x1, y1 = JUDGE_CROP
        Image.fromarray(img[y0:y1, x0:x1]).save(f"{out}/judge_{i:04d}.png")
        x0, y0, x1, y1 = HUD_CROP
        Image.fromarray(img[y0:y1, x0:x1]).save(f"{out}/hud_{i:04d}.png")
        if i % FULL_EVERY == 0:
            Image.fromarray(img).save(f"{out}/full_{i:04d}.jpg", quality=88)
        if not args.no_blobs:
            for y, x in note_blobs(img):
                blobs.append([i, round(y, 1), round(x, 1)])
        frames.append([round(t_call, 4), round(t_ret, 4)])
        i += 1
        if i % 40 == 0:
            print(f"  {i} frames, {t_ret - t_call:.3f}s capture", flush=True)

    json.dump({"crop": JUDGE_CROP, "hud_crop": HUD_CROP, "full_every": FULL_EVERY,
               "frames": frames, "blobs": blobs},
              open(f"research/recordings/rec_{args.tag}.json", "w", encoding="utf-8"))
    print(f"{i} frames -> {out}/, index research/recordings/rec_{args.tag}.json", flush=True)


if __name__ == "__main__":
    main()
