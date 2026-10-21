"""Pull the frames around a chart time out of a screenrecord, for looking at with eyes.

`vidscan` measures; this one is for when the measurement disagrees with what the result page says
and the only way forward is to see the popup, the notes and the HUD counters at the same instant.
"""
import argparse
import json
import sys

sys.path.insert(0, "tools")

HUD = (1040, 100, 1280, 380)
POP = (450, 330, 830, 560)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--t0", type=float, help="default: the t0 vidscan stored")
    ap.add_argument("--at", required=True, help="comma-separated chart seconds")
    ap.add_argument("--pad", type=float, default=0.0, help="also grab t-pad and t+pad")
    ap.add_argument("--full", action="store_true", help="save the whole frame, not just crops")
    args = ap.parse_args()

    import cv2
    from PIL import Image

    idx = json.load(open(f"research/vidscan_{args.tag}.json", encoding="utf-8"))
    t0 = args.t0 if args.t0 is not None else idx["t0"]
    cap = cv2.VideoCapture(f"research/{args.tag}.mp4")
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"video {n} frames, t0 {t0:.3f}")

    times = []
    for v in args.at.split(","):
        t = float(v)
        for dt in ({0.0} if not args.pad else {-args.pad, 0.0, args.pad}):
            times.append(round(t + dt, 3))
    times.sort()

    i, frame, pts = 0, None, None
    for want in times:
        target = (want + t0) * 1000.0
        while i < n and (pts is None or pts < target):
            ok, bgr = cap.read()
            if not ok:
                break
            i += 1
            pts = cap.get(cv2.CAP_PROP_POS_MSEC)
            frame = bgr
        if frame is None:
            print(f"{want:8.3f}s: past the end")
            continue
        rgb = frame[:, :, ::-1]
        name = f"research/vf_{args.tag}_{want:07.3f}"
        Image.fromarray(rgb).crop(HUD).resize((480, 560), Image.LANCZOS).save(f"{name}_hud.png")
        Image.fromarray(rgb).crop(POP).resize((760, 460), Image.LANCZOS).save(f"{name}_pop.png")
        if args.full:
            Image.fromarray(rgb).save(f"{name}_full.png")
        print(f"{want:8.3f}s -> frame {i} pts {pts:.1f} {name}_hud.png / _pop.png")


if __name__ == "__main__":
    main()
