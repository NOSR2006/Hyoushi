"""Map hud-watch judgements back to chart notes and to the actions that were in flight.

`--watch-hud` leaves lines like "hud: BAD #3 at host [565437.123, 565437.131]" in the run log.
This reads them, converts host time to chart time via the run's own t0 line, and prints for every
event: the notes due in that neighbourhood (a BAD is a touch 100-120 ms off a note, so the note
sits just after or before the touch), and the actions whose fire time lands in the same
neighbourhood, with the slot and x they used. That triple -- note, action, slot -- is what tells
a timing failure apart from a wrong-slot or wrong-position swipe.

Actions come from research/dets_<tag>.json (the run's own fired log: target and actual host time
per action) when that file exists, so the offsets are measured, not reconstructed; logs from the
pre-2026-09 layout under research/archive/logs/ find their dets in research/archive/runs/.
Without it, build_actions is re-run to place them on the chart clock.

Usage: python tools/probes/hudmap.py research/archive/logs/t08.log research/archive/data/tanebi_ex.hits.json
"""
import json
import os
import re
import sys

sys.path.insert(0, "tools")
from player import build_actions  # noqa: E402

HUD = re.compile(r"hud: (\w+) #(\d+) at host \[([\d.]+), ([\d.]+)\]")
# After the relock the "-> t0" on the restart line is only the press+delta prior; the clock the
# run actually fired on is printed on the following "given" line, so prefer that one.
T0_GIVEN = re.compile(r"restart anchor: t0=([\d.]+) given")
T0 = re.compile(r"restart anchor: .*-> t0 ([\d.]+)")


def main(log_path, hits_path, pad=0.16):
    log = open(log_path, encoding="utf-8", errors="replace").read()
    m = T0_GIVEN.search(log) or T0.search(log)
    t0 = float(m.group(1))
    events = [(r, int(n), float(a), float(b)) for r, n, a, b in HUD.findall(log)]
    print(f"t0 {t0:.3f}, {len(events)} hud events")

    hits = json.load(open(hits_path, encoding="utf-8"))
    notes = sorted(((h["t_ms"] / 1000.0, h) for h in hits), key=lambda kv: kv[0])

    tag = os.path.basename(log_path).rsplit(".", 1)[0]
    dets_path = os.path.join(os.path.dirname(log_path), f"dets_{tag}.json")
    if not os.path.exists(dets_path):
        dets_path = os.path.join("research", "archive", "runs", f"dets_{tag}.json")
    fires = None
    if os.path.exists(dets_path):
        d = json.load(open(dets_path, encoding="utf-8"))
        fires = d.get("fired")
        print(f"fired log: {len(fires) if fires else 0} actions from {dets_path}")
    if not fires:
        actions, _ = build_actions(hits, 570.0, 20.0, 45.0, 90)
        fires = [(round(t0 + a[0] / 1000.0, 3), round(t0 + a[0] / 1000.0, 3),
                  a[1], a[2], a[3], a[4]) for a in sorted(actions)]
        print("fired log missing - actions placed on the chart clock instead")

    for row, n, a, b in events:
        mid = (a + b) / 2
        lo, hi = mid - pad, mid + pad
        print(f"\n{row} #{n}  host [{a:.3f}, {b:.3f}]  chart +{(mid - t0) * 1000:.0f} ms")
        for t, h in notes:
            if lo - t0 <= t <= hi - t0:
                kind = h["kind"]
                extra = ""
                if kind == "flick":
                    extra = f" dir={h.get('dir')}"
                elif kind == "long":
                    extra = f" end={h['end_ms'] / 1000:.3f}"
                print(f"    note  d{(t - (mid - t0)) * 1000:+7.1f} ms  {kind:5s} "
                      f"lane {h['lane']:4.1f} x {h['x']:4d}{extra}")
        for tg, ac, op, slot, x, y in fires:
            if lo <= ac <= hi:
                print(f"    act   d{(ac - mid) * 1000:+7.1f} ms  {op:4s} slot {slot} "
                      f"x {x:6.1f} y {y:.0f}  (skew {(ac - tg) * 1000:+.1f} ms)")


if __name__ == "__main__":
    # 按需工具：两个位置参数都是它没法猜的语料路径（用法写在模块 docstring 里）。
    # 裸跑给这行字，别把一个 IndexError 堆栈当用法说明。
    if len(sys.argv) < 3:
        print("usage: python tools/probes/hudmap.py <run.log> <chart.hits.json>")
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2])
