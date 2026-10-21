"""Which statistic should turn the relock's votes into t0? Offline, over every recorded lock.

`detect.vote_t0` finds the histogram peak and then answers the **mean of every vote within +-50 ms
of that peak's centre**. The peak is chosen by count, so the neighbourhood mean is not a mode -- it
takes in votes from the alignments the histogram just rejected, and on a chart that repeats a
section those are not noise but a neighbouring family. The whole chart fires on that one number, and
1 px of landmark is 1.3 ms, so a statistic that drifts by 5 ms is 5 ms of the +/-50 ms PERFECT
window spent on nothing.

This replays the 86 recorded relocks (`research/runs/relock_dets_*.json`: the blobs the vote
actually ate, the notes, the window, the t0 that was fired) and scores candidate statistics on the
same votes. Nothing is decided here that a device decides better, but the number that matters is
available without one: **how far the answer moves when 30% of the blobs are dropped at random**.
That is the estimator's own variance, in ms, and it needs no ground truth -- the shipped mean is one
of the candidates and can lose.

Run from the repo root:  python tools/probes/voteab.py
"""
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rlog                                                    # noqa: E402
from detect import implied_votes  # noqa: E402

REPS = 60                    # jackknife draws per lock
DROP = 0.30                  # of the blobs each draw removes
BIN_S = 0.020


def _peak(vals, bin_s=BIN_S):
    """The winning bin's centre and its vote count, exactly as vote_t0 picks them."""
    if len(vals) < 3:
        return None, 0
    edges = np.arange(vals.min(), vals.max() + bin_s, bin_s)
    if len(edges) < 2:
        return float(vals.mean()), len(vals)      # one bin: that agreement is the answer
    counts, be = np.histogram(vals, bins=edges)
    k = int(np.argmax(counts))
    return float((be[k] + be[k + 1]) / 2.0), int(counts[k])


def _near(vals, centre, span):
    return vals[np.abs(vals - centre) <= span]


def mean_shipped(vals, bin_s=BIN_S):
    """What is in production: mean of votes within 2.5 bins (+-50 ms) of the peak centre."""
    c, n = _peak(vals, bin_s)
    return None if c is None else float(_near(vals, c, 2.5 * bin_s).mean())


def median_shipped(vals, bin_s=BIN_S):
    c, n = _peak(vals, bin_s)
    return None if c is None else float(np.median(_near(vals, c, 2.5 * bin_s)))


def _seek(vals, c, span, steps=4):
    """Mode-seeking: re-centre on the mean of what is near, a few times, with the +-50 ms radius."""
    for _ in range(steps):
        near = _near(vals, c, span)
        if not len(near):
            return c
        c = float(near.mean())
    return c


def seek50(vals, bin_s=BIN_S):
    c, n = _peak(vals, bin_s)
    return None if c is None else _seek(vals, c, 2.5 * bin_s)


def seek20(vals, bin_s=BIN_S):
    """Tighter radius (one bin), so neighbouring families are out rather than averaged in."""
    c, n = _peak(vals, bin_s)
    return None if c is None else _seek(vals, c, 1.0 * bin_s)


def fine_bin(vals, bin_s=BIN_S):
    """Find the peak in 5 ms bins instead of 20, then mean within +-10 ms of it."""
    c, n = _peak(vals, bin_s / 4.0)
    return None if c is None else float(_near(vals, c, 0.5 * bin_s).mean())


def trimmed(vals, bin_s=BIN_S):
    c, n = _peak(vals, bin_s)
    if c is None:
        return None
    near = _near(vals, c, 2.5 * bin_s)
    m = np.median(near)
    dev = np.abs(near - m)
    keep = near[dev <= np.quantile(dev, 0.75)]
    return float(keep.mean())


ESTS = (("mean+-50 (生产)", mean_shipped), ("median+-50", median_shipped),
        ("mode-seek+-50", seek50), ("mode-seek+-20", seek20),
        ("5ms 峰 + -10ms 均值", fine_bin), ("截尾+-50(25%)", trimmed))


def load():
    """(tag, dets, notes, lo, hi, t0_fired) for every dump that recorded its own feed."""
    out = []
    for f in sorted(glob.glob(os.path.join(rlog.RUNS, "relock_dets_*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        if d.get("dets") and d.get("notes") and d.get("t0") is not None:
            out.append((os.path.basename(f)[len("relock_dets_"):-len(".json")],
                        np.asarray(d["dets"], dtype=np.float64), d["notes"], d["lo"], d["hi"],
                        d["t0"]))
    return out


def jack(vals_fn, dets, notes, lo, hi, rng):
    """The estimator's spread under blob dropout: std over REPS draws, in ms."""
    keep_all = vals_fn(implied_votes(dets, notes, lo=lo, hi=hi))
    if keep_all is None:
        return None
    ans = []
    for _ in range(REPS):
        m = rng.random(len(dets)) >= DROP
        if m.sum() < 5:
            continue
        v = implied_votes(dets[m], notes, lo=lo, hi=hi)
        a = vals_fn(v)
        if a is not None:
            ans.append(a)
    if len(ans) < 8:
        return None
    return 1000.0 * float(np.std(ans))


def main():
    locks = load()
    if not locks:
        print("no relock dumps with a recorded feed")
        return 1
    rng = np.random.default_rng(20261002)
    votes, fired_gap = {}, {}
    for tag, dets, notes, lo, hi, t0 in locks:
        v = implied_votes(dets, notes, lo=lo, hi=hi)
        for name, fn in ESTS:
            a = fn(v)
            if a is not None:
                votes.setdefault(name, []).append(a)
                fired_gap.setdefault(name, []).append(1000.0 * (a - t0))
    print(f"{len(locks)} 个已录 relock 的票面重放（同一批票，只换统计量）")
    base = votes.get("mean+-50 (生产)", [])
    print(f"{'统计量':<22}{'与生产的差 med/max ms':>26}{'离当时实锁 med':>16}"
          f"{'抗抖动(票掉30%) med':>22}")
    for name, fn in ESTS:
        vs = votes.get(name, [])
        if not vs:
            continue
        d = np.abs(np.array(vs) - np.array(base)) * 1000.0
        gap = np.median(np.abs(fired_gap[name]))
        # stability is measured on a subset of locks (each jackknife draw is a full vote pass), so
        # the same 40 locks are used for every estimator and the comparison stays honest.
        stab = []
        for tag, dets, notes, lo, hi, t0 in locks[:40]:
            s = jack(fn, dets, notes, lo, hi, rng)
            if s is not None:
                stab.append(s)
        print(f"{name:<22}{np.median(d):>14.1f}/{d.max():>9.1f}{gap:>16.1f}"
              f"{(np.median(stab) if stab else float('nan')):>22.1f}")
    print("\n注：'离当时实锁' 只说明重放与当初那次投票的接近程度（当初是前缀票、这里是全量票），")
    print("    不是好坏；比的是各统计量在同一批票上的表现。抗抖动那列越小，t0 里随机项越少。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
