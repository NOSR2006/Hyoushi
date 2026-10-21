"""Compile an OurNotes MusicScore JSON into a millisecond hit list in screen pixels.

Tick base: 480 ticks per beat. The field is a perspective trapezoid whose edges were
measured from a LIVE screenshot, so a lane's pixel x depends on the row it is read at.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rlog import write_json_file  # noqa: E402

TICKS_PER_BEAT = 480
LANES = 24

# Measured on research/g_8.png: left edge x = 608 - 0.845*y, right edge x = 676 + 0.845*y
EDGE_SLOPE = 0.845
EDGE_LEFT_AT_0 = 608.0
EDGE_RIGHT_AT_0 = 676.0
# Two magenta rows bound the hit interval (measured at y=542-543 and 597-598); the note is
# perfect at their centre, not at the early edge. Reading x at any other row would shift every
# lane because the field is a trapezoid. This is the one definition of the field for both sides of
# the harness: detect.py imports it, so the compiled times and the read landmark cannot drift apart.
JUDGE_Y = 570.0
# A trail bends at chart nodes, so sampling those nodes alone leaves the finger far off the
# trail for most of a hold. 20 ms is dense enough to stay inside a few pixels.
PATH_STEP_MS = 20.0


def edge_x(y):
    return EDGE_LEFT_AT_0 - EDGE_SLOPE * y, EDGE_RIGHT_AT_0 + EDGE_SLOPE * y


def lane_to_x(lane, y=JUDGE_Y):
    lo, hi = edge_x(y)
    return int(round(lo + (lane / LANES) * (hi - lo)))


def tick_to_ms(t, bpm_events):
    """Wall-clock ms of a chart tick, accumulating across every tempo change.

    Not `t * 60000 / (480 * <tempo in effect at t>)`: that scales the whole tick count by the
    tempo current at the far end, so a chart whose BPM changes lands every later note at the wrong
    time and the mapping turns backwards at the seam -- 愛は衝動 (0098_03) goes 90 -> 180 at tick
    19200, which put tick 19200 at 13333 ms while tick 19199 sat at 26665 ms. The two halves of
    the chart then interleave, so the compiled list carries a phantom press for every real note in
    the overlap and the whole second half runs 13.3 s early: the presses are punctual against our
    own clock, the notes the game is showing are somewhere else, and the run drowns in MISS at a
    fixed chart position. 56 of the 340 charts in the library change tempo.
    """
    ms = 0.0
    prev_t = 0
    bpm = bpm_events[0]["bpm"]
    for e in bpm_events:
        if e["t"] >= t:
            break
        ms += (e["t"] - prev_t) * 60000.0 / (TICKS_PER_BEAT * bpm)
        prev_t = e["t"]
        bpm = e["bpm"]
    return ms + (t - prev_t) * 60000.0 / (TICKS_PER_BEAT * bpm)


def _ease_u(u, ease):
    """The game's lateral curve between two hold nodes, the same one _auto_point resolves.

    A hold node's `ease` belongs to the segment that starts at it: `in` leaves the node slowly
    (u squared), `out` arrives at the next one slowly. Interpolating those segments linearly
    instead puts the finger a quarter of the segment away from the bar at its midpoint, which
    costs nothing on a short bend and breaks the hold on a wide one: the sweep that crosses the
    whole field (17 lanes) is off by 4.25 lanes = 183 px against a 129 px hitbox half-width, so
    the contact sits outside its own bar for half the segment and the tail reads MISS.
    """
    if ease == "in":
        return u * u
    if ease == "out":
        return u * (2.0 - u)
    return u


# A knot where the trail turns back on itself (the apex of a figure-8) is judged as its own node
# at its own tick, so the contact has to be on the apex exactly then. The 20 ms grid alone clips
# the apex off -- 真夜中遊園地's crossing never sampled closer than 12 px to its 986/298 apexes --
# and parking the finger exactly on the apex missed in every run since. The one thing every
# judgment that does clear has in common is a finger in motion (a parked contact is what makes
# SlideBeginFlick heads miss), so the tick now gets a moving pass: a left-right sweep of
# APEX_SWEEP_AMP_PX at APEX_SWEEP_HZ rides the apex, phase-locked so the sine is 0 -- the exact
# apex pixel -- at the tick, covering APEX_SWEEP_LEAD_MS before it to APEX_SWEEP_TAIL_MS after.
APEX_SWEEP_LEAD_MS = 40.0
APEX_SWEEP_TAIL_MS = 50.0
APEX_SWEEP_STEP_MS = 10.0
APEX_SWEEP_AMP_PX = 12.0
APEX_SWEEP_HZ = 6.0


def _trail_path(knots, judge_y):
    """Sample a hold's trail densely, then thin it to the points where the finger must move.

    A hold is judged continuously, so the contact has to sit on the trail the whole time rather
    than jumping between the few nodes the chart records. Consecutive samples that round to the
    same pixel are dropped so a straight hold costs one point, not fifty.
    """
    rev = [False] * len(knots)
    for i in range(1, len(knots) - 1):
        d0 = knots[i][1] - knots[i - 1][1]
        d1 = knots[i + 1][1] - knots[i][1]
        rev[i] = d0 * d1 < 0
    trail = []
    k = 0
    t = knots[0][0]
    while t <= knots[-1][0] + 1e-9:
        while k + 1 < len(knots) and knots[k + 1][0] <= t:
            k += 1
        nxt = k + 1
        # Inside a reversal's sweep window: ride the apex left-right, crossing it at the tick.
        if trail and nxt < len(knots) and rev[nxt] \
                and t >= knots[nxt][0] - APEX_SWEEP_LEAD_MS - PATH_STEP_MS:
            t_node = knots[nxt][0]
            x0 = lane_to_x(knots[nxt][1], judge_y)
            at = t_node - APEX_SWEEP_LEAD_MS
            while at <= t_node + APEX_SWEEP_TAIL_MS + 1e-9:
                # Phase-locked to the tick: the sine is 0 exactly at t_node, so the one sample
                # landing on the tick sits on the apex pixel while all others are moving.
                x = int(round(x0 + APEX_SWEEP_AMP_PX * math.sin(
                    2 * math.pi * APEX_SWEEP_HZ * (at - t_node) / 1000.0)))
                if trail[-1]["x"] != x:
                    trail.append({"t_ms": round(at, 3), "x": x})
                at += APEX_SWEEP_STEP_MS
            t = t_node + APEX_SWEEP_TAIL_MS + PATH_STEP_MS
            continue
        if k + 1 < len(knots):
            span = knots[k + 1][0] - knots[k][0]
            u = (t - knots[k][0]) / span if span > 0 else 1.0
            u = _ease_u(u, knots[k][2])
            lane = knots[k][1] + u * (knots[k + 1][1] - knots[k][1])
        else:
            lane = knots[-1][1]
        x = lane_to_x(lane, judge_y)
        if not trail or trail[-1]["x"] != x:
            trail.append({"t_ms": round(t, 3), "x": x})
        t += PATH_STEP_MS
    tail = {"t_ms": round(knots[-1][0], 3), "x": lane_to_x(knots[-1][1], judge_y)}
    if trail[-1]["t_ms"] == tail["t_ms"]:
        trail[-1] = tail
    else:
        trail.append(tail)
    return trail


# A SlideBeginFlick bar is read as a flick at its head, and the contact has to keep moving
# left-right while the bar is held -- a finger parked on the bar misses even though it is
# touching the right place. The jiggle rides the bar's own centreline, so the contact never
# leaves the bar: its amplitude is capped at half the narrowest node's width minus the finger's
# footprint, and it is faded in and out so the press and the release happen on the centreline.
WIGGLE_AMP_PX = 45.0
WIGGLE_HZ = 5.0
WIGGLE_RAMP_MS = 120.0


def _wiggle_path(knots, size, judge_y):
    """The centreline of a head-flick bar, plus the left-right jiggle the game wants on it.

    Unlike _trail_path this keeps every 20 ms sample even where the centreline stands still --
    that stillness is exactly what has to be broken up.
    """
    lo, hi = edge_x(judge_y)
    half_px = (size / 2.0) * (hi - lo) / LANES
    amp = max(0.0, min(WIGGLE_AMP_PX, half_px - 25.0))
    t0, t1 = knots[0][0], knots[-1][0]
    ramp = min(WIGGLE_RAMP_MS, (t1 - t0) * 0.3)
    # A tap-lane flick is down at t-20 and lateral at t+2, and those judge PERFECT, so the bar
    # head gets the same instant swipe: a sine fading in over 120 ms only crosses the game's
    # flick threshold around +65 ms and read "85ms GOOD" (a39 jp_1007). The jump IS the attack;
    # the wiggle is the same sine phase-locked to it, and only the tail still tapers.
    jump_t = t0 + 22.0
    pts = []
    k = 0
    t = t0
    while t <= t1 + 1e-9:
        while k + 1 < len(knots) and knots[k + 1][0] <= t:
            k += 1
        if k + 1 < len(knots):
            span = knots[k + 1][0] - knots[k][0]
            u = (t - knots[k][0]) / span if span > 0 else 1.0
            u = _ease_u(u, knots[k][2])
            lane = knots[k][1] + u * (knots[k + 1][1] - knots[k][1])
        else:
            lane = knots[-1][1]
        x = lane_to_x(lane, judge_y)
        env = 1.0
        if ramp > 0:
            env = min(1.0, (t1 - t) / ramp)
        if amp > 0 and t >= jump_t:
            x += amp * env * math.cos(2 * math.pi * WIGGLE_HZ * (t - jump_t) / 1000.0)
        pts.append({"t_ms": round(t, 3), "x": int(round(x))})
        t += PATH_STEP_MS
    if amp > 0 and len(pts) > 1 and jump_t < t1:
        # Lands as a real move at wall t+2 (build_actions shifts the path by t-20), off the
        # centreline the down touched, exactly like the plain flick's lateral.
        pts[1] = {"t_ms": round(jump_t, 3),
                  "x": int(round(lane_to_x(knots[0][1], judge_y) + amp))}
    tail = {"t_ms": round(t1, 3), "x": lane_to_x(knots[-1][1], judge_y)}
    if pts and pts[-1]["t_ms"] == tail["t_ms"]:
        pts[-1] = tail
    else:
        pts.append(tail)
    return pts


def _auto_point(nodes, i):
    """Centre and width of an `auto` node, resolved the way the game resolves it.

    Both edges are interpolated between the nearest numeric neighbours -- the left edge with
    the left node's ease, the right edge likewise -- and the centre is their midpoint. On
    焚音打's one such bar (head pos 9 size 6 -> tail 0x24) that centre is a constant 12, i.e.
    the finger just holds the field centre while the bar slides and widens around it; eases do
    move the centre in general, which is why the interpolation is done properly here.
    """
    left = i - 1
    while left >= 0 and not isinstance(nodes[left].get("pos"), (int, float)):
        left -= 1
    right = i + 1
    while right < len(nodes) and not isinstance(nodes[right].get("pos"), (int, float)):
        right += 1
    me = nodes[i]
    if left < 0 and right >= len(nodes):
        return 12.0, 12.0
    if left < 0:
        r = nodes[right]
        return r["pos"] + r["size"] / 2.0, r["size"]
    if right >= len(nodes):
        l = nodes[left]
        return l["pos"] + l["size"] / 2.0, l["size"]
    l, r = nodes[left], nodes[right]
    span = r["t"] - l["t"]
    p = 0.0 if span <= 0 else min(1.0, max(0.0, (me["t"] - l["t"]) / span))
    ease = l.get("ease", "linear")
    if ease == "in":
        p = p * p
    elif ease == "out":
        p = (2 - p) * p
    lane = l["pos"] + (r["pos"] - l["pos"]) * p
    l_right = l["pos"] + l["size"]
    r_right = r["pos"] + r["size"]
    right_edge = l_right + (r_right - l_right) * p
    return (lane + right_edge) / 2.0, right_edge - lane


def _node_centre(nodes, i):
    a = nodes[i]
    return _auto_point(nodes, i)[0] if isinstance(a["pos"], str) else a["pos"] + a["size"] / 2


def _node_size(nodes, i):
    a = nodes[i]
    return _auto_point(nodes, i)[1] if isinstance(a.get("pos"), str) else a["size"]


# Two longs whose heads land within one input frame on overlapping hitboxes cannot both bind
# cleanly: every event of the pair -- the two downs, and later every sample of a shared apex or
# crossing, since both trails run on the same millisecond grid -- shares one injection batch and
# one game frame, and one bar (always the left) loses its share: one MISS where the trails
# separate, then the hold reconnects because the finger never left its bar. Pushing the two
# trails apart in x changes nothing (both downs stay inside both spans); running the left bar a
# whole input frame late desynchronises every event of the pair instead. +16 ms of judgement is
# deep inside PERFECT +/-50, and a finger 16 ms behind its bar is at worst ~30 px off centre,
# inside any bar wide enough to overlap another head.
HEAD_COINCIDE_MS = 40.0
# One game input frame at 60 fps is 16.67 ms, so a shift of one frame's worth or less can still
# land both bars' events in the same frame for an unlucky phase; 20 ms is the smallest round
# value strictly above the period -- different frame guaranteed -- while +20 ms of judgement
# stays deep inside PERFECT +/-50 and the trail lag (<= ~3 px/ms of bar speed) stays inside the
# bar.
PAIR_DESYNC_MS = 20.0
# The two heads do not have to overlap to trip this, but almost all of them must not be touched:
# library-wide, 714 coincident-head pairs sit at 0-2 px of gap between their hitboxes (adjacent
# bars of the same width) and have always played clean, while 39 overlap. What separates the
# failures is the bar width, not the gap: the narrowest bars -- size 4, two lanes -- meeting
# edge-to-edge dropped the left head twice, 0050_03 at 7.077 s (three runs in a row) and 0034_03
# at 154.62 s (Symbol II's ending pair), and anima's three size-6 touching pairs in the very same
# runs never missed. So an edge-to-edge head joins the class only when both bars are that narrow:
# 3 pairs in the whole library, two known failures and their untested twin (0110_03 at 73.2 s).
NARROW_SIZE = 4
NARROW_TOUCH_PX = 2.0


def _half_width_px(size, judge_y=JUDGE_Y):
    lo, hi = edge_x(judge_y)
    return (size / 2.0) * (hi - lo) / LANES


def _desync_overlapping_longs(hits):
    """Give each bar of a coincident-head overlapping pair its own input frame.

    Bars are compared by head time and head hitbox; the left bar of a pair runs PAIR_DESYNC_MS
    late. Pairs are re-passed until no overlapping pair shares a shift, so a bundle of three
    mutually overlapping heads stacks to 0/16/32 rather than leaving two of them in sync.
    """
    longs = sorted((h for h in hits if h["kind"] == "long"), key=lambda h: h["t_ms"])
    for _ in longs:
        changed = False
        for i, a in enumerate(longs):
            for b in longs[i + 1:]:
                if b["t_ms"] - a["t_ms"] > HEAD_COINCIDE_MS:
                    break
                gap = (abs(a["x"] - b["x"])
                       - _half_width_px(a["size"]) - _half_width_px(b["size"]))
                narrow = (a["size"] <= NARROW_SIZE and b["size"] <= NARROW_SIZE
                          and gap <= NARROW_TOUCH_PX)
                if gap > 0.0 and not narrow:
                    continue
                left, right = (a, b) if a["x"] < b["x"] else (b, a)
                if left.get("time_shift_ms", 0.0) == right.get("time_shift_ms", 0.0):
                    left["time_shift_ms"] = left.get("time_shift_ms", 0.0) + PAIR_DESYNC_MS
                    changed = True
        if not changed:
            break


def compile_chart(path, judge_y=JUDGE_Y):
    score = json.load(open(path, encoding="utf-8"))["score"]
    bpm_events = score["events"]["bpm"]
    hits = []
    for note in score["notes"]:
        kind = note.get("type", "tap")
        if kind == "guide":
            # A guide whose nodes are *all* visible:false is decoration (Abracadabra). One that
            # renders nodes -- 焚音打's purple diamond rows -- is a trace: the player holds it and
            # follows it exactly like a long, just faster (the bar sweeps several lanes in a
            # couple of hundred ms), and every visible node is judged on the way.
            if all(a.get("visible") is False for a in note["node"]):
                continue
            kind = "long"
        if kind == "long":
            nodes = note["node"]
            knots = []
            for i, a in enumerate(nodes):
                kt = (tick_to_ms(a["t"], bpm_events), _node_centre(nodes, i),
                      a.get("ease"))
                # A long that ends in a flick carries a second tail node a fraction of a
                # millisecond later with the flick's wider hitbox, so its lane is not where the
                # trail goes; chasing it would snap the finger sideways on the last frame.
                if knots and kt[0] - knots[-1][0] < PATH_STEP_MS:
                    continue
                knots.append(kt)
            head_flick = nodes[0].get("type") == "flick"
            if head_flick:
                trail = _wiggle_path(knots, min(a["size"] for a in nodes), judge_y)
            else:
                trail = _trail_path(knots, judge_y)
            h = {
                "kind": "long",
                "t_ms": round(knots[0][0], 3),
                "end_ms": round(knots[-1][0], 3),
                "lane": knots[0][1],
                "size": nodes[0]["size"],
                "x": trail[0]["x"],
                "path": trail,
            }
            # A hold whose last node is wider than the one before it ends in a flick, and the
            # tail is only read from a real swipe there -- a finger sitting still inside that
            # wide hitbox still misses. For most of them the widened node is the +1-tick tail
            # dropped above; the big 10-second slides instead widen their own final node. A tail
            # node that is typed as a flick is one too, widened or not.
            if len(nodes) >= 2 and (_node_size(nodes, -1) > _node_size(nodes, -2)
                                    or nodes[-1].get("type") == "flick"):
                fl = nodes[-1]
                h["end_flick"] = {
                    "t_ms": round(tick_to_ms(fl["t"], bpm_events), 3),
                    "x": lane_to_x(_node_centre(nodes, len(nodes) - 1), judge_y),
                    "size": _node_size(nodes, len(nodes) - 1),
                }
            hits.append(h)
        else:
            h = {
                "kind": kind,
                "t_ms": round(tick_to_ms(note["t"], bpm_events), 3),
                "lane": note["pos"] + note["size"] / 2,
                "x": lane_to_x(note["pos"] + note["size"] / 2, judge_y),
                "size": note["size"],
            }
            if kind == "flick":
                h["dir"] = note.get("dir")
            hits.append(h)
    _desync_overlapping_longs(hits)
    hits.sort(key=lambda h: h["t_ms"])
    return hits


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "research/archive/data/mayoiuta_ex.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "research/archive/data/mayoiuta_ex.hits.json"
    hits = compile_chart(src)
    # Atomic: a .hits.json is not regenerated for free (it is gitignored and, once flown, is the
    # byte generation a pin names), so the file must never be visible half-written.
    write_json_file(out, hits)
    kinds = {}
    for h in hits:
        kinds[h["kind"]] = kinds.get(h["kind"], 0) + 1
    print(f"{len(hits)} hits {kinds} -> {out}")
    print(f"first {hits[0]['t_ms']} ms, last {hits[-1]['t_ms']} ms")
    for h in hits[:4]:
        print(" ", json.dumps(h, ensure_ascii=False))


if __name__ == "__main__":
    main()
