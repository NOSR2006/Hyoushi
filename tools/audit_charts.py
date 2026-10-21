"""Rank every chart in the library by the failure classes we have already been bitten by.

Every check below is a class that cost a real MISS or a real crash before it had a rule; the point
of running them over all 340 charts is to turn "discover it by flying it" into "predict it from the
file", so the next chart we open is chosen by risk instead of by chance.

Measured basis (see the memory notes for each class):
  crossing   two long bars whose heads land close together AND whose trails swap sides -- the
             figure-8 apex shape that dropped 0058_03's tracking at 38.15 s. Kept here as a
             DISCRIMINATOR, not as a rule: replacing the shipped "any head overlap" trigger with
             "overlap that crosses" was tried and measured (42 spots under the shipped rule, 37
             under the crossing rule, but they only partly overlap -- 20 charts would gain shifts
             they never had, others would lose them). No live evidence picks between them, so the
             compiler keeps its shipped rule and this file just reports where the two disagree.
  narrow     size-4 (two-lane) bars exactly touching at their heads -- 0050_03 7.077 s and
             0034_03 154.619 s both MISSed there; 0110_03 73.200 s is the same shape, unflown.
  off_field  a compiled x outside the field edges. 0096_03's slide bar ran to x=1297 and killed two
             whole attempts before player.field_x clamped it; a clamp keeps the run alive but costs
             that bar, so these still need a measured geometry fix.
  late_vote the opening has no tap/flick for >1 s, so the *mid-song corrector* has no blob to
            vote on for that long -- informational only, the relock's sprite feed sees the bars and
             the run rides the t_field fallback clock, which wanders +-27 ms (唱's 8 ms margin).
  dock       a tap within 96 ms after a flick -- the L12 chain class that only effective offset 45
             (+55 nominal, docked -10) survives.

Every gap/pair arithmetic is imported from compile.py, so a pair this file flags is a pair the
shipped rule sees the same way.

Usage: python tools/audit_charts.py [--json research/reports/chart_audit.json]
"""
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compile import (HEAD_COINCIDE_MS as HEAD_WINDOW_MS, JUDGE_Y, NARROW_SIZE,  # noqa: E402
                     NARROW_TOUCH_PX as TOUCH_PX, _half_width_px as half_px, compile_chart, edge_x)
from rlog import (CHARTS, MANIFEST, RELEARN_INDEX,  # noqa: E402
                  fingerprint, flown, pin_state)
# The pin's own reader: "are these still the flown bytes, and were they flown under today's
# inputs?" is answered by the module that wrote the fingerprints, not by a second one here.
# fetch_charts does not import this file.
from fetch_charts import read_pins  # noqa: E402

# Song titles carry characters the GBK console cannot encode (100034's 🜁), and the report died
# mid-print on one; same guard as run.py.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

BLIND_OPEN_MS = 1000.0       # the mid-song corrector has no observation for this long
DOCK_MS = 96.0               # a tap this soon after a flick is inside its judgement window
FLICK_REACH_PX = 90          # player.py's swipe step: a flick nearer than this overscrolls out

LO, HI = edge_x(JUDGE_Y)


def head_gap(a, b):
    """Signed px between two bars' head hitboxes; negative means they overlap.

    Same arithmetic as compile._desync_overlapping_longs (rounded head x, not the float lane), so a
    pair this function calls overlapping is a pair the shipped rule shifts.
    """
    return abs(a["x"] - b["x"]) - half_px(a["size"]) - half_px(b["size"])


def trails_cross(a, b):
    """Do the two bars actually swap sides over their common time (a figure-8), not just overlap?"""
    ta = {q["t_ms"]: q["x"] for q in a.get("path", [])}
    tb = {q["t_ms"]: q["x"] for q in b.get("path", [])}
    signs = set()
    for t in sorted(set(ta) & set(tb)):
        d = ta[t] - tb[t]
        if abs(d) > 1:
            signs.add(d > 0)
    return len(signs) > 1


def scan(hits):
    """Return (flags, detail) for one compiled chart."""
    flags, det = set(), {}
    if not hits:
        return {"empty"}, det
    ts = [h["t_ms"] for h in hits]
    if any(b < a for a, b in zip(ts, ts[1:])):
        flags.add("backwards")                     # the multi-tempo mapping bug class
    longs = [h for h in hits if h["kind"] == "long"]
    cross, narrow, par, wtouch = [], [], [], 0
    for i, a in enumerate(longs):
        for b in longs[i + 1:]:
            if abs(a["t_ms"] - b["t_ms"]) > HEAD_WINDOW_MS:
                continue
            gap = head_gap(a, b)
            both_narrow = (a["size"] <= NARROW_SIZE and b["size"] <= NARROW_SIZE)
            if gap < 0 and trails_cross(a, b):
                cross.append(round(a["t_ms"] / 1000, 2))
            elif gap < 0:
                par.append((round(a["t_ms"] / 1000, 2), round(gap, 1)))
            elif gap <= TOUCH_PX and both_narrow:
                narrow.append(round(a["t_ms"] / 1000, 2))
            elif gap <= TOUCH_PX:
                wtouch += 1
    if cross:
        flags.add("crossing")
    if narrow:
        flags.add("narrow")
    if par:
        flags.add("overlap_parallel")
    off = []
    for h in hits:
        xs = [h["x"]] + [q["x"] for q in h.get("path", [])]
        for x in xs:
            if x < LO or x > HI:
                off.append((round(h["t_ms"] / 1000, 2), round(x)))
                break
    if off:
        flags.add("off_field")
    # This started as "blind_open -- the opening has no tap/flick for >1 s, so the relock vote has
    # no blob to vote on", and that premise died on 2026-10-02: the relock's feed is sprite_blobs,
    # which finds long and trace bars too (detect.sprite_blobs), so a chart that opens on bars is
    # not blind to it at all -- 0030_02 rode 23.1 s of exactly that to an ALL PERFECT with its
    # first mid-song vote at +6 ms. Nor is *silence* a risk: presses only happen when notes exist,
    # and the library's first note is at 1.5-10.7 s, all inside the relock's deadline. What is
    # left is a fact about an instrument, not a hazard: how long the mid-song corrector has no
    # observation. It stays as `late_vote`, out of HARD, and the detail says who covers it.
    vis = [h for h in hits if h["kind"] in ("tap", "flick")]
    if vis:
        late = min(h["t_ms"] for h in vis) - min(ts)
        if late > BLIND_OPEN_MS:
            flags.add("late_vote")
        taps = sorted(h["t_ms"] for h in vis if h["kind"] == "tap")
        dock = sum(1 for f in vis if f["kind"] == "flick"
                   and any(0 <= t - f["t_ms"] <= DOCK_MS for t in taps))
        if dock:
            flags.add("dock")
        det["dock"] = dock
        det["late_ms"] = round(late)
    # a flick whose 90 px swipe leaves the field cannot be drawn -- the clamp eats it
    edge_f = [round(f["t_ms"] / 1000, 2) for f in vis if f["kind"] == "flick"
              and (f["x"] - LO < FLICK_REACH_PX or HI - f["x"] < FLICK_REACH_PX)]
    if edge_f:
        flags.add("flick_at_edge")
    det["crossing"], det["narrow"], det["off"] = cross, narrow, off
    det["parallel_overlap"], det["wide_touch"] = par, wtouch
    det["parallel"] = len(par)
    det["flick_edge"] = edge_f
    det["first"] = round(min(ts) / 1000, 1)
    return flags, det


def rebuild_delta(cid):
    """How far the stored file sits from what the compiler in this tree would write today.

    This is the number that answers "do we recompile the library?": the stored geometry is what the
    AP runs were actually flown on, and every geometry rule added since (ease interpolation, apex
    sweep, head desync) lands the moment a chart is rebuilt. A chart with a delta is a chart whose
    validated behaviour would be replaced by unflown bytes, so it only gets rebuilt together with a
    fresh bounded test.
    """
    raw = os.path.join(CHARTS, f"{cid}.raw.json")
    if not os.path.exists(raw):
        return None
    new = compile_chart(raw)
    old = json.load(open(os.path.join(CHARTS, f"{cid}.hits.json"), encoding="utf-8"))
    if len(new) != len(old):
        return {"entries": -1, "shift_only": False, "rebuild_shifts": []}
    diff = [i for i, (a, b) in enumerate(zip(new, old)) if a != b]
    shift_only = all(set(new[i]) ^ set(old[i]) == {"time_shift_ms"} for i in diff)
    shifts = [round(h["t_ms"] / 1000, 2) for h in new if h.get("time_shift_ms")]
    return {"entries": len(diff), "shift_only": shift_only, "rebuild_shifts": shifts}


def main():
    as_json = None
    if "--json" in sys.argv:
        as_json = sys.argv[sys.argv.index("--json") + 1]
    man = json.load(open(MANIFEST, encoding="utf-8"))
    names = {}
    for s in man["songs"]:
        for d in s["difficulties"]:
            names[f"{d['book']}_{d['dd']}"] = (s["title"], d["name"].upper(), d.get("level", "?"))
    # Coverage is the pin's question, not the log's. results.jsonl holds the newest 100 rounds, so a
    # chart whose only ALL PERFECT aged out of it reads here as "never flown" while the panel's 谱面库
    # page -- which reads the pin -- shows it as flown and protected. Take the better of the two, and
    # say nothing about which: the report asks "what has this chart's best been", not "when".
    flew = dict(flown())     # the untrimmed history, not the panel's 100-row window
    for cid, e in read_pins().items():
        np_, tag = e["best"].get("np"), e["best"].get("tag") or ""
        if np_ is not None and (cid not in flew or np_ < flew[cid][0]):
            flew[cid] = (np_, tag)

    rows = []
    for p in sorted(glob.glob(os.path.join(CHARTS, "*.hits.json"))):
        cid = os.path.basename(p)[: -len(".hits.json")]
        hits = json.load(open(p, encoding="utf-8"))
        flags, det = scan(hits)
        title, diff, lv = names.get(cid, (cid, "", "?"))
        best = flew.get(cid)
        rows.append({"id": cid, "song": title, "diff": diff, "lv": lv, "notes": len(hits),
                     "flags": sorted(flags), "best_np": best[0] if best else None,
                     "best_tag": best[1] if best else "", "rebuild": rebuild_delta(cid),
                     **det})

    HARD = ("backwards", "crossing", "narrow", "off_field")
    total = len(rows)
    print(f"=== 谱面静态审计 · {total} 张 ===")
    for k, label in (("backwards", "时间映射倒退（多变速类，已修）"),
                     ("crossing", "长条头部重叠+路径交叉（0058 顶点形状）"),
                     ("narrow", f"窄条（size≤{NARROW_SIZE}）头部相切（0050/0034 类）"),
                     ("overlap_parallel", "头部重叠但路径不交叉（同类触发，无失效证据）"),
                     ("off_field", "编译坐标越出场界（安全网会夹，代价=那一条）"),
                     ("late_vote", f"首个 tap/flick 晚于开盘 >{BLIND_OPEN_MS / 1000:.0f}s"
                                   "（中段修正无观测；开局钟由重锁 sprite 条兜住，实测 23.1s 无碍）"),
                     ("flick_at_edge", "flick 距边 <90px（手势会滑出场）"),
                     ("dock", f"flick→tap <{DOCK_MS:.0f}ms 接力（靠 eff45 的 dock）")):
        hit = [r for r in rows if k in r["flags"]]
        spots = {"crossing": "crossing", "narrow": "narrow", "off_field": "off",
                 "overlap_parallel": "parallel_overlap"}.get(k)
        pairs = sum(len(r.get(spots) or []) for r in hit) if spots else 0
        extra = f"（{pairs} 处）" if pairs else ""
        print(f"  {label:<42} {len(hit):>3} 张{extra}")
    print(f"  {'头部 0–2px 近距相切的宽条（规则不动，飞的局里也没坏过）':<42} "
          f"{sum(r['wide_touch'] for r in rows):>3} 对 / "
          f"{sum(1 for r in rows if r['wide_touch']):>3} 张")

    flown_n = sum(1 for r in rows if r["best_np"] is not None)
    ap_n = sum(1 for r in rows if r["best_np"] == 0)
    print(f"\n飞过：{flown_n}/{total} 张，其中 AP {ap_n} 张。"
          f"未飞过 {total - flown_n} 张 —— 下面的队列按硬风险排序，没有规则命中的排在后面。")

    drift = [r for r in rows if r["rebuild"] and r["rebuild"]["entries"]]
    only_shift = [r for r in drift if r["rebuild"]["shift_only"]]
    ap_drift = [r for r in drift if r["best_np"] == 0]
    print("\n=== 现存谱面 vs 本树编译器重建 ===")
    print(f"  有差异：{len(drift)}/{total} 张"
          f"（其中只差 time_shift_ms 的 {len(only_shift)} 张；几何本身也变了 {len(drift) - len(only_shift)} 张）")
    print(f"  已经 AP 过、但重建后会换掉字节：{len(ap_drift)} 张 —— "
          f"{'、'.join(r['id'] for r in ap_drift[:12])}{' …' if len(ap_drift) > 12 else ''}")
    print("  结论：重建=用未飞过的字节替换验证过的几何，所以单张重编译必须配一次有界测试。")

    # The pin's own tripwire, now in two parts. The v1 half: it stored the fingerprint of the bytes
    # a result was flown on, so a pinned chart whose file has since been rewritten is the promise
    # breaking. The new half is wider than the file: the raw chart, the compiler and the upstream
    # revision are each fingerprinted with the round, so a pin can say whether the *inputs* it was
    # set under are still the inputs on this disk. Neither is a verdict about the music -- "drifted"
    # means the result no longer predicts today's bytes, i.e. a relearn round would answer it.
    off, gens = [], Counter()
    pins = read_pins()
    for cid, e in sorted(pins.items()):
        at = e["at"]
        now = fingerprint(cid)
        gens[pin_state(cid, e, now)] += 1
        was = at.get("hits")
        if now["hits"] is not None and now["hits"] != was:
            off.append((cid, e["best"].get("np"), e["best"].get("tag"), was, now["hits"]))
    print(f"  钉子按输入分代：同代 {gens['current']} / 输入已变 {gens['drifted']} / "
          f"记不出输入 {gens['unrecorded']}（共 {len(pins)} 张）")
    # The queue is the same finding from the other side: charts where this tree's compiler produces
    # bytes no result was flown on. Not a backlog to feel bad about -- each one is one bounded round
    # from an answer.
    try:
        queue = (json.load(open(RELEARN_INDEX, encoding="utf-8")) or {}).get("queue") or {}
    except (OSError, ValueError):
        queue = {}
    print(f"  重学队列：{len(queue)} 张等新字节被飞一次"
          f"{'（fetch_charts.py --relearn 看清单）' if queue else ''}")
    print(f"  钉子对不上（飞过的那份字节已经不在了）：{len(off)} 张"
          + (" —— " + "、".join(f"{c}/np{np_}@{t}" for c, np_, t, _, _ in off[:8]) if off else ""))
    for c, np_, t, was, now in off:
        print(f"     {c}: 钉在 {was}，现在 {now}，"
              f"这一张的成绩 ({'AP' if not np_ else f'{np_} 漏'}@{t}) 已经无法在当前字节上复现，"
              f"重飞一次有界测试后才能再 --pin")

    # Which charts the head-desync rule fires on TODAY, straight from the compiler in this tree --
    # the stored files only show what the flown geometry did (or failed to do) under its own rules.
    will = [r for r in rows if r["rebuild"] and r["rebuild"].get("rebuild_shifts")]
    flown_will = [r for r in will if r["best_np"] is not None]
    print("\n=== 用本树规则重建后会被错帧的长条对（重编译带来的扰动）===")
    print(f"  {len(will)} 张 / {sum(len(r['rebuild']['rebuild_shifts']) for r in will)} 处，"
          f"其中 {len(flown_will)} 张已经飞过。")
    for r in sorted(will, key=lambda x: (x["best_np"] is not None, -len(x["rebuild"]["rebuild_shifts"]))):
        st = "未飞" if r["best_np"] is None else (f"AP({r['best_tag']})" if not r["best_np"]
                                                 else f"{r['best_np']}漏({r['best_tag']})")
        print(f"  {r['id']:<9} {r['song'][:20]:<20} {r['diff']:<7} {st:<12} "
              f"+{','.join(str(s) for s in r['rebuild']['rebuild_shifts'])} s")
    print("  对照实验（做过、没有采纳）：把「头部重叠就错帧」换成「路径交叉才错帧」，全库 42 处变 37 处，"
          "但两个集合只部分重合 —— 20 张谱会多出从未有过的错帧，另一些会丢掉保护。没有实机证据选边，"
          "所以 compile.py 保持已验证的规则，交叉判别只留在这里当线索。")

    def hard_count(r):
        return len(set(r["flags"]) & set(HARD))

    queue = sorted(rows, key=lambda r: (-hard_count(r), r["best_np"] is not None, -r["notes"]))
    print("\n=== 硬风险队列（前 25）===")
    print(f"{'谱':<9} {'难度':<7} {'Lv':<3} {'音符':>5}  {'最好结果':<9} 风险            明细")
    for r in queue[:25]:
        hs = [f for f in r["flags"] if f in HARD]
        if not hs:
            continue
        best = "未飞" if r["best_np"] is None else (f"AP({r['best_tag']})"
                                                   if not r["best_np"] else f"{r['best_np']}漏({r['best_tag']})")
        detail = []
        if r.get("crossing"):
            detail.append("交叉@" + ",".join(str(x) for x in r["crossing"][:3]))
        if r.get("narrow"):
            detail.append("相切@" + ",".join(str(x) for x in r["narrow"][:3]))
        if r.get("off"):
            detail.append(f"越界{len(r['off'])}点@" + ",".join(str(x[0]) for x in r["off"][:2]))
        if "blind_open" in r["flags"]:
            detail.append(f"修正盲区{r.get('late_ms', 0) / 1000:.1f}s")
        print(f"{r['id']:<9} {r['diff']:<7} {r['lv']:<3} {r['notes']:>5}  {best:<9} "
              f"{'+'.join(hs):<14} " + " ".join(detail))
    print("\n=== 已验证名单里带硬风险的（不要再动它们的几何）===")
    for r in rows:
        if r["best_np"] == 0 and set(r["flags"]) & set(HARD):
            print(f"  {r['id']} {r['song']} {r['diff']}: {'+'.join(f for f in r['flags'] if f in HARD)}")
    if as_json:
        os.makedirs(os.path.dirname(os.path.abspath(as_json)), exist_ok=True)
        with open(as_json, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        print(f"\n写入 {as_json}（{len(rows)} 条）")


if __name__ == "__main__":
    main()
