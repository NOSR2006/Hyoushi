"""What number was the judgement we lost? Read it off the frame the watcher already saved.

The plan to give each note kind its own lead (task #109) needs one question answered first: are the
keys we lose sitting on the seams that hypothesis talks about -- a flick less than ~115 ms before
the next press, or a hold's tail landing under the next head -- or are they spread over the chart
the way notes are?

The first attempt at this tool timed the events: `hud: BAD #1 at host [a, b]` minus the round's
`fire t0=` gives a place in the chart. That turned out not to work, and the numbers say why: the
residual against the note grid has a standard deviation of 121 ms on an 80-160 ms grid, and a MISS
is only counted once the note has left the window, so its time is late by construction. Time cannot
name the object.

The ordinal can, and it is already in the pixels: every event saves a frame, and the frame shows the
five running counters (`hudread`, which reuses the result page's digit templates at a lower height
floor). Summed, they say "this was the Nth judged object" -- the same number that made 0056_03's 628
findable by hand in September, now read for every round whose frames are still on disk.

What this file then measures is the one thing standing between that ordinal and a note: the game
counts more judged objects than we press (843 vs 506 on 0056_03), and the rule for what a hold
contributes is #111. Per event this prints  ordinal − (actions we had fired by then), which is where
those extra objects actually are in time. That series is the fitting data; the seam table comes after
it, not before.

Run from the repo root:  python tools/probes/dropmap.py
"""
import bisect
import glob
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hudread                                               # noqa: E402
import rlog                                                  # noqa: E402
import resultread as rr                                      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

CHART_RE = re.compile(r"谱面 (\d{4}_\d{2})")
# Searched, not anchored: the detail log prefixes every line with a clock, so a `^ *fire` pattern
# matched nothing and the round's lead silently stayed None (measured: every event's chart time was
# then off by the ~45 ms the offset was supposed to correct).
FIRE_RE = re.compile(r"fire t0=([\d.]+) \(offset ([+-]?\d+) ms\)")
RELOCK_RE = re.compile(r"relock: locked t0 ([\d.]+)")
HUD_RE = re.compile(r"hud: (GREAT|GOOD|BAD|MISS) #(\d+) at host \[([\d.]+), ([\d.]+)\]"
                    r"(?: 第 (\d+) 个判定物)? -> (\S+)")
SEAM_MS = 115.0          # the credit window's bound is only known to lie in 96..115 (see run.py)


def chart_of(cid, _cache={}):
    """(heads, tails): every action's (t_ms, kind) sorted, and every hold's end_ms."""
    if cid not in _cache:
        try:
            hits = json.load(open(os.path.join(rlog.CHARTS, f"{cid}.hits.json"), encoding="utf-8"))
            _cache[cid] = (sorted((float(h["t_ms"]), h.get("kind", "?")) for h in hits),
                           sorted(float(h["end_ms"]) for h in hits if h.get("end_ms")))
        except (OSError, ValueError):
            _cache[cid] = None
    return _cache[cid]


def rounds():
    """[(tag, cid, t0, offset_ms, [(kind, host, frame)])] -- one entry per round that logged events."""
    out = []
    for path in sorted(glob.glob(os.path.join(rlog.RUNS, "*.detail.log"))):
        cid = t0 = off = None
        evs = []
        for line in open(path, encoding="utf-8", errors="replace"):
            if cid is None:
                m = CHART_RE.search(line)
                if m:
                    cid = m.group(1)
                continue
            r = RELOCK_RE.search(line)
            if r:
                t0 = float(r.group(1))
            f = FIRE_RE.search(line)
            if f:
                t0, off = float(f.group(1)), float(f.group(2))
            h = HUD_RE.search(line)
            if h and t0 is not None:
                evs.append((h.group(1), int(h.group(2)), float(h.group(4)), h.group(6),
                            int(h.group(5)) if h.group(5) else None))
        if cid and evs:
            out.append((os.path.basename(path).split(".")[0], cid, t0, off, evs))
    return out


def fired_by(heads, tau_ms):
    """How many actions were due at or before this chart time (a press is fired `offset` early)."""
    return bisect.bisect_right([h[0] for h in heads], tau_ms)


def seam_before(heads, tails, i):
    """(after a flick?, after a hold's tail?) within SEAM_MS of action i."""
    t = heads[i][0]
    flick = any(a[1] == "flick" and 0 < t - a[0] <= SEAM_MS for a in heads[max(0, i - 12):i])
    tail = bisect.bisect_left(tails, t) > bisect.bisect_right(tails, t - SEAM_MS)
    return flick, tail


def main():
    tpl = rr.load_templates()
    rows, src, disagree, checkable, recon, lost = [], Counter(), 0, 0, 0, 0
    for tag, cid, t0, off, evs in rounds():
        lib = chart_of(cid)
        if not lib:
            continue
        heads, tails = lib
        n_log = {"GREAT": 0, "GOOD": 0, "BAD": 0, "MISS": 0}
        for kind, n, host, frame, line_ord in evs:
            n_log[kind] = max(n_log[kind], n)      # the watcher's own tally, replayed in order
            if line_ord is not None:
                o = line_ord                       # read live, in the line itself
                src["行里自带（当时就写的）"] += 1
            else:
                p = frame if os.path.exists(frame) else os.path.join(rlog.ROOT, frame)
                if not os.path.exists(p):
                    p = os.path.join(rlog.FRAMES, os.path.basename(frame))
                c = hudread.counters(p, tpl) if os.path.exists(p) else {}
                if not c:
                    lost += 1
                    continue
                if all(v is not None for v in c.values()):
                    o = sum(c.values())
                    src["帧：五格全读"] += 1
                elif c.get("PERFECT") is not None:
                    # Not used. The tempting reconstruction -- PERFECT from the frame plus the four
                    # non-PERFECT rows from the log's own tally -- was tried and measured: on the
                    # events where it could be cross-checked, the tally disagreed with what the
                    # pixels said 17 times out of 19. The watcher counts *ticks it sampled*, and two
                    # judgements inside one capture interval read as one. So the ordinal is only
                    # ever what the frame says; this branch just reports the disagreement.
                    recon += 1
                    for r, v in c.items():
                        if r != "PERFECT" and v is not None:
                            checkable += 1
                            disagree += v != n_log[r]
                    src["帧：只有 PERFECT（重建已否决，见下）"] += 1
                    continue
                else:
                    src["帧：读不出 PERFECT，放弃"] += 1
                    continue
            tau = 1000.0 * (host - t0) + (off or 0)
            a = fired_by(heads, tau)
            i = max(0, min(a, len(heads)) - 1)
            f, tl = seam_before(heads, tails, i)
            rows.append((tag, cid, kind, o, a, o - a, tau, heads[i][1], f, tl, {}))
    n = len(rows)
    print(f"事件 {n} 个有精确序号；帧已没了的 {lost}")
    for k, v in src.most_common():
        print(f"   {k:<34} {v:>4}")
    print(f"   重建路径的交叉核对：{recon} 个事件、{checkable} 行可比，其中日志的 #n 与帧上真实计数"
          f"不符 {disagree} 处 —— 监视器数的是「它采样到的跳变」，两个判定落在同一采样间隔里就读成一次，"
          f"所以序号只能从像素读，不能从日志推")
    if not rows:
        print("一个序号都没读到 -- 停在这里")
        return 1

    gaps = [r[5] for r in rows]
    print(f"序号 - 我们已发的动作数：中位 {statistics.median(gaps):+.0f}，"
          f"范围 {min(gaps):+d}..{max(gaps):+d}（这就是「一个 hold 贡献几个判定物」要解释的量）")
    print("\n每局按谱面时间排开的 gap 序列（前 8 局，看它怎么长出来的）")
    per = defaultdict(list)
    for r in sorted(rows, key=lambda e: (e[0], e[6])):
        per[(r[0], r[1])].append(r)
    for (tag, cid), rs in list(per.items())[:8]:
        lib = chart_of(cid)
        print(f"  {tag} {cid}: " + "  ".join(f"+{r[6] / 1000:.1f}s#{r[3]}({r[5]:+d})" for r in rs[:9]))

    print("\n掉键落在哪种音符上（按序号读出来的那一格，对照全谱构成）")
    obs = Counter(r[7] for r in rows)
    kinds_all, dock_all, tail_all = Counter(), 0, 0
    for cid in sorted({r[1] for r in rows}):
        heads, tails = chart_of(cid)
        for i in range(len(heads)):
            kinds_all[heads[i][1]] += 1
            f, tl = seam_before(heads, tails, i)
            dock_all += f
            tail_all += tl
    n = len(rows)
    total = sum(kinds_all.values())
    for kind in sorted(kinds_all, key=lambda k: -kinds_all[k]):
        share = kinds_all[kind] / total
        print(f"  {kind:<6} 掉 {obs.get(kind, 0):>4} ({100 * obs.get(kind, 0) / n:4.1f}%)   "
              f"谱面占 {100 * share:4.1f}%   倍数 {((obs.get(kind, 0) / n) / share):4.2f}x")
    fl = sum(1 for r in rows if r[8])
    tl = sum(1 for r in rows if r[9])
    print(f"\n接缝（{SEAM_MS:.0f} ms 内）：紧跟 flick {fl}/{n} = {100 * fl / n:.1f}%   vs 基线 "
          f"{100 * dock_all / total:.1f}%   提升 {(fl / n) / (dock_all / total) if dock_all else 0:.2f}x")
    print(f"                    紧跟长条/轨迹尾 {tl}/{n} = {100 * tl / n:.1f}%   vs 基线 "
          f"{100 * tail_all / total:.1f}%   "
          f"提升 {(tl / n) / (tail_all / total) if tail_all else 0:.2f}x")
    print("  （基线几乎为零的那些，说明读到的语料里就没有这种接缝 -- 该去飞有接缝的谱，不是这里）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
