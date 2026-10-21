"""Offline proof for the first-note anchor: time the chart's first note from a screenrecord.

Every anchor so far voted over the intro's whole blob population, and the intro's population is
the dirtiest part of the chart (long bars fragment into biased bodies, repeated sections build
1.5 s aliases, scenery spawns lanes that hold nothing), so each song ends up needing its own
babysitting. The reference harnesses instead time ONE start event and add a constant. This script
measures the two candidate events on recordings of the same song made in wildly different device
states (t02 clean, t04 host-clock experiment, t05 stalled timebase):

  * the chart's first note, watched in its own lane column, timed from EVERY sample by the same
    C map the vote uses -- if the per-sample crossings cluster, one tracked note carries the
    clock and the note's lane/time come from the chart, so there is nothing per-song to tune;
  * the playfield's fade-in, as a magenta-pixel ramp in the judge-line band.

If `first-note crossing - field onset` agrees across the three recordings, the start is game
locked and the next anchor can be built on it. The 230 ms live cadence is simulated from the
dense 60 fps samples to size the estimator's noise before it goes into the live path.
"""
import argparse
import json
import sys

import numpy as np

sys.path.insert(0, "tools")
from detect import C_FIELD, JUDGE_Y, VP_MOTION, lane_at, note_blobs  # noqa: E402

SJ = 1.0 / (JUDGE_Y - VP_MOTION)


def cross_at(t, y):
    """Judge-line crossing instant implied by a blob centre seen at (t, y)."""
    return t + C_FIELD * (1.0 / (y - VP_MOTION) - SJ)


def magenta(rgb):
    a = rgb.astype(int)
    m = (a[..., 0] > 150) & (a[..., 2] > 150) & (a[..., 1] < 110)
    return int(m[500:650, 250:1030].sum())


def onset_of(ramp, sustain=6, frac=0.25):
    """First sustained rise of the ramp, interpolated between the two straddling frames."""
    t = np.array([r[0] for r in ramp], float)
    v = np.array([r[1] for r in ramp], float)
    if len(v) < sustain + 2:
        return None, 0.0, 0.0
    base = float(np.median(v[: max(8, len(v) // 10)]))
    peak = float(np.percentile(v, 92))
    if peak < base + 30:
        return None, base, peak
    thr = base + frac * (peak - base)
    n = len(v)
    for i in range(1, n - sustain):
        if v[i] > thr and (v[i:i + sustain] > thr).all() and v[i - 1] <= thr:
            f = (thr - v[i - 1]) / max(v[i] - v[i - 1], 1e-9)
            return float(t[i - 1] + f * (t[i] - t[i - 1])), base, peak
    return None, base, peak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--hits", default="research/archive/data/tanebi_ex.hits.json")
    ap.add_argument("--win", default="0,80", help="decode window in video seconds")
    ap.add_argument("--lane-tol", type=float, default=1.2)
    ap.add_argument("--t0-run", type=float, help="run's fire t0 (host clock), for the walk-lag line")
    ap.add_argument("--field-host", type=float, help="run's 'LIVE field at host', same")
    ap.add_argument("--save", help="prefix to dump ramp/samples as .npz")
    args = ap.parse_args()

    import cv2

    notes = json.load(open(args.hits, encoding="utf-8"))
    n0 = notes[0]
    x0, tms = float(n0["x"]), n0["t_ms"] / 1000.0
    lane0 = lane_at(x0, JUDGE_Y)
    print(f"[{args.tag}] first note: t={tms:.3f}s kind={n0['kind']} x={x0:.0f} lane={lane0:.2f}")

    w0, w1 = (float(v) for v in args.win.split(","))
    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.set(cv2.CAP_PROP_POS_MSEC, w0 * 1000.0)
    ramp, lane_samples, all_blobs = [], [], []
    i = 0
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if t < w0:
            continue
        if t > w1:
            break
        i += 1
        rgb = bgr[:, :, ::-1]
        ramp.append((t, magenta(rgb)))
        for y, x in note_blobs(rgb):
            all_blobs.append((t, float(y), float(x)))
            if abs(lane_at(x, y) - lane0) <= args.lane_tol:
                lane_samples.append((t, float(y), float(x)))
    cap.release()
    print(f"[{args.tag}] {i} frames decoded ({w0:.0f}..{w1:.0f}s, fps~{fps:.1f}), "
          f"{len(lane_samples)} samples in the first note's lane, {len(all_blobs)} blobs total")

    onset, base, peak = onset_of(ramp)
    if onset is None:
        print(f"[{args.tag}] field onset: NOT FOUND (baseline {base:.0f}, peak {peak:.0f})")
    else:
        near = [(t, v) for t, v in ramp if onset - 0.5 <= t <= onset + 0.8]
        shape = " ".join(f"{v:.0f}" for _, v in near[:: max(1, len(near) // 40)])
        print(f"[{args.tag}] field onset {onset:.3f}s (baseline {base:.0f} -> peak {peak:.0f}); "
              f"ramp around: {shape}")

    if not lane_samples:
        return
    cs = np.array([cross_at(t, y) for t, y, x in lane_samples])
    order = np.argsort(cs)
    cs_sorted = cs[order]
    # earliest dense cluster = the first note; later objects in the same lane cross ~seconds later
    first = cs_sorted[cs_sorted < cs_sorted[0] + 0.9]
    sel = np.flatnonzero(np.isin(cs, first))
    st = sorted((lane_samples[j] for j in sel), key=lambda s: s[0])
    cross_med = float(np.median(first))
    mad = float(np.median(np.abs(first - cross_med)) * 1000.0)
    t0_video = cross_med - tms
    y0, y1 = st[0][1], st[-1][1]
    print(f"[{args.tag}] first-note cluster: n={len(first)} y {y0:.0f}..{y1:.0f} "
          f"t {st[0][0]:.3f}..{st[-1][0]:.3f}")
    print(f"[{args.tag}] per-sample crossings: " +
          " ".join(f"{c - cross_med:+.3f}" for c in sorted(first)[:14]))
    print(f"[{args.tag}] crossing {cross_med:.3f}s (MAD {mad:.1f}ms) -> t0_video {t0_video:.3f}s")

    # the whole intro blob population fed to the old vote, framed like the live tight window,
    # to see how far the vote's answer sits from the tracked note
    from detect import vote_t0
    first_t = st[0][0]
    dets = [(t, y, x) for t, y, x in all_blobs if first_t - 1.0 <= t <= first_t + 8.5]
    v_t0, v_peak, v_second, _ = vote_t0(dets, [(n["t_ms"] / 1000.0, n["lane"]) for n in notes],
                                        lo=t0_video - 2.0, hi=t0_video + 2.0)
    if v_t0 is not None:
        print(f"[{args.tag}] vote over intro blobs: t0={v_t0:.3f}s "
              f"(dt vs first note {v_t0 - t0_video:+.3f}s, peak {v_peak}, second {v_second})")

    if onset is not None:
        print(f"[{args.tag}] INTERVAL onset -> crossing: {cross_med - onset:.3f}s")

    if args.t0_run is not None and args.field_host is not None and onset is not None:
        est = args.t0_run - args.field_host + onset
        print(f"[{args.tag}] walk lag: host t0_video-link {est:.3f}s vs tracked {t0_video:.3f}s "
              f"(walk saw the field {t0_video - est:+.3f}s after the recorded onset)")

    # live cadence: ~230 ms capture with jitter, 2..5 samples -> median crossing estimate
    rng = np.random.default_rng(7)
    arr = np.array(st)
    dense = cross_med
    if len(arr) >= 4:
        parts = []
        for k in (2, 3, 4, 5):
            errs = []
            for _ in range(400):
                phase = rng.uniform(0.0, 0.23)
                jit = rng.uniform(0.0, 0.08)
                picked, tt = [], arr[0][0] + phase
                while len(picked) < k and tt < arr[-1][0] + 0.4:
                    j = int(np.argmin(np.abs(arr[:, 0] - tt)))
                    if abs(arr[j][0] - tt) <= 0.14 and (not picked or arr[j][0] > picked[-1][0]):
                        picked.append(arr[j])
                    tt += 0.23 + rng.uniform(0.0, jit)
                if len(picked) >= k:
                    est = np.median([cross_at(p[0], p[1]) for p in picked])
                    errs.append(abs(est - dense) * 1000.0)
            if errs:
                parts.append(f"k={k}: p50 {np.percentile(errs, 50):.0f}ms "
                             f"p90 {np.percentile(errs, 90):.0f}ms")
        print(f"[{args.tag}] live-cadence sim (|err| vs dense): " + "; ".join(parts))

    if args.save:
        np.savez(args.save, ramp=np.array(ramp), samples=arr)
        print(f"[{args.tag}] -> {args.save}.npz")


if __name__ == "__main__":
    main()
