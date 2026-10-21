"""Did the game stall when it judged? A render that never happened shows up as the same blobs.

Screenrecord samples the display at a fixed rate, so when the game renders slower than that the
newest frame is presented again and the note blobs sit at the same pixels for two or more samples.
Reading the stalls off the recorded blob stream is the cheapest way to test "the miss was a
stutter" against "the miss was the note's own handling".
"""
import argparse
import json



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--tol", type=float, default=0.75, help="blob move below this = same render")
    ap.add_argument("--gap", type=float, default=0.08, help="sample gap above this breaks a run")
    ap.add_argument("--min-run", type=int, default=2, help="repeats in a row = one stall")
    args = ap.parse_args()

    d = json.load(open(f"research/vidscan_{args.tag}.json", encoding="utf-8"))
    t0 = d["t0"]
    by = {}
    for t, y, x in d["dets"]:
        by.setdefault(round(t, 4), []).append((y, x))
    times = sorted(by)

    runs, cur = [], None
    for t1, t2 in zip(times, times[1:]):
        if t2 - t1 > args.gap:
            cur = None
            continue
        a, b = sorted(by[t1]), sorted(by[t2])
        same = (len(a) == len(b) and len(a) > 0
                and max(abs(p[0] - q[0]) for p, q in zip(a, b)) < args.tol
                and max(abs(p[1] - q[1]) for p, q in zip(a, b)) < args.tol)
        if same:
            if cur is None:
                cur = [t1, t2, 2]
                runs.append(cur)
            else:
                cur[1] = t2
                cur[2] += 1
        else:
            cur = None

    print(f"{len(runs)} stalls (runs of >= {args.min_run} identical samples, {args.tol} px tol)")
    tot = 0.0
    for t1, t2, n in runs:
        dur = (t2 - t1) * 1000
        tot += dur
        if dur >= 80:
            print(f"  chart {t1 - t0:7.3f}..{t2 - t0:7.3f}s  {n} samples  {dur:5.0f} ms")

    misses = json.load(open(f"research/vid_{args.tag}.json", encoding="utf-8"))
    print("\nnear each MISS-counter move:")
    for m in misses["counter_moves"]:
        c = m["chart"]
        near = [(t1, t2, n) for t1, t2, n in runs if t1 - t0 - 0.8 < c < t2 - t0 + 0.4]
        s = ", ".join(f"{t1 - t0 - c:+.2f}s/{((t2 - t1) * 1000):.0f}ms" for t1, t2, _ in near)
        print(f"  chart {c:7.3f}s: {s or 'no stall within -0.8..+0.4s'}")


if __name__ == "__main__":
    main()
