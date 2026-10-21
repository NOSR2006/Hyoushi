"""Replay a failed anchor offline from the blobs it recorded.

Re-running a LIVE to test a vote parameter costs a minute of the song and a page walk; the dump
player.py writes on failure has every blob the vote saw, so the parameters can be swept here
instead. `python tools/probes/votediag.py [dump.json]` prints the strongest alignments and when each
one first became the winner, which is what a lock criterion has to be tuned against. With no argument
it reads `research/anchor_dets.json`, the dump `player.py` writes when a lock fails: no failed run,
no dump, and then this says so in one line instead of raising (it is an on-demand tool -- nothing to
guess at when the file is missing).
"""
import json
import os
import sys

import numpy as np

sys.path.insert(0, "tools")
from detect import C_FIELD, VP_MOTION, JUDGE_Y, lane_at  # noqa: E402


def votes(dets, notes, c_sec=C_FIELD, vp=VP_MOTION, judge_y=JUDGE_Y, lane_tol=2.5):
    """Every (implied t0, blob index) pair, i.e. the raw material of the histogram."""
    sj = 1.0 / (judge_y - vp)
    out = []
    for i, (t, y, x) in enumerate(dets):
        cross = t + c_sec * (1.0 / (y - vp) - sj)
        lane = lane_at(x, y)
        for nt, nlane in notes:
            if abs(nlane - lane) <= lane_tol:
                out.append((cross - nt, i))
    return out


def peaks(vs, bin_s=0.020, top=8):
    vals = np.array([v for v, _ in vs])
    edges = np.arange(vals.min(), vals.max() + bin_s, bin_s)
    counts, be = np.histogram(vals, bins=edges)
    order = np.argsort(counts)[::-1]
    out = []
    for k in order[:top]:
        near = [v for v, i in vs if abs(v - (be[k] + be[k + 1]) / 2.0) <= 2.5 * bin_s]
        if not near:
            continue
        # Which blobs back this peak: an alias is usually carried by a handful of blobs voted
        # many ways, while the truth is one vote from each of many blobs.
        blobs = {i for v, i in vs if abs(v - (be[k] + be[k + 1]) / 2.0) <= 2.5 * bin_s}
        out.append((float(np.mean(near)), int(counts[k]), len(blobs)))
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "research/anchor_dets.json"
    if not os.path.exists(path):
        print("usage: python tools/probes/votediag.py [failed-anchor-dump.json]")
        print(f"{path} 不存在：这份 dump 由 player.py 在锁谱失败时写出，没有失败的局就没有它。")
        return 2
    d = json.load(open(path, encoding="utf-8"))
    dets = [(t, y, x) for t, y, x in d["dets"]]
    notes = [(nt, nl) for nt, nl in d["notes"]]
    t0_ref = dets[0][0]
    print(f"{len(dets)} blobs over {dets[-1][0] - t0_ref:.1f}s, {len(notes)} chart notes")
    vs = votes(dets, notes)
    print(f"{len(vs)} raw votes, range {min(v for v, _ in vs) - t0_ref:+.1f} .. "
          f"{max(v for v, _ in vs) - t0_ref:+.1f} s relative to the first blob")
    print("peak t0 (rel. first blob)   votes  distinct blobs")
    for t0, n, nb in peaks(vs):
        print(f"  {t0 - t0_ref:+9.3f}s  {t0:14.3f}  {n:5d}  {nb:5d}")

    # When each candidate first reached a given vote count -- the answer to "could we have locked
    # earlier, and on which candidate".
    print("\ncumulative winner over time (20 bins of blobs):")
    for k in range(1, 21):
        sub = dets[:max(1, len(dets) * k // 20)]
        pv = peaks(votes(sub, notes), top=1)
        if pv:
            t0, n, nb = pv[0]
            print(f"  {len(sub):4d} blobs at +{sub[-1][0] - t0_ref:5.1f}s: "
                  f"t0={t0 - t0_ref:+8.3f}s votes={n:4d} blobs={nb:4d}")


if __name__ == "__main__":
    raise SystemExit(main())
