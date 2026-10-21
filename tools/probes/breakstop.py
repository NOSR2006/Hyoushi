"""Pin the --retry-on-break stop contract: no device, no live, no frames.

The fire loop is what every night's runs ride on, and the abort branch inside it is only
reachable live (a real HUD commit, on a real song) -- so this probe replays it offline against a
fake injector. It requires all three of: a `stop` callback that turns truthy mid-fire ends the
loop at an action boundary (not at the end), every finger that went down is lifted before play
returns, and the caller gets ABORTED with the hint in the parked dump. PART 1 also runs the
shipped call with the guard switched off (`stop=None`): the same hits must fire through and
return 0, or the abort branch is "always on" and the probe has no teeth.

PART 2 is the trigger itself: BreakHint must fire on the first committed event, stay stable
across the polls the fire loop makes while it decides to stop, and report nothing on an empty
event list.

PART 3 is the born-late guard: with `late_fail` armed, a lock that finds the first presses
already past (t92's restart-with-a-dead-channel case) must abort at once with row LATE and
close to nothing fired, while the same lock without the guard must still play through -- and a
healthy lock with the guard armed must fire exactly like an unguarded one.

PART 5 is the same thread's freshness gate: a capture that hands back the same buffer is not a
second sample of the world, so the probe thread refuses it where the frames come in -- said out
loud once, and refused again while it lasts. What that buys is measured in `freshfeed.py`: the
detector does not run over frozen pixels at the renderer's cadence, the corrector's histogram does
not collect duplicate votes, and the replay corpus keeps one frame per moment rather than two.

A `StillWatch` stands in for run.py's host-capture Watch so the probe never touches the
emulator: with `watch` supplied, play's own probe thread is not started and the idle-gap calls
go nowhere. PART 4 runs the other branch on purpose -- `watch=None`, with `player.frames` and
`player.note_blobs` swapped -- because that thread is the only thing that sees the field during a
normal run, and what it saw used to be dropped on the floor.

Run from the repo root:  python tools/probes/breakstop.py
"""

import json
import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import player  # noqa: E402
import run  # noqa: E402


class FakeInj:
    def __init__(self):
        self.cmds = 0
        self.echoes = 0
        self.respawns = 0
        self.downs = []
        self.ups = []

    def probe(self):
        return True

    def touch_down(self, slot, x, y, i=None):
        self.downs.append(slot)
        self.cmds += 1
        self.echoes += 1

    def touch_move(self, slot, x, y):
        self.cmds += 1
        self.echoes += 1

    def touch_up(self, slot):
        self.ups.append(slot)
        self.cmds += 1
        self.echoes += 1

    def clock_offset_ms(self):
        return 0


class StillWatch:
    def __init__(self):
        self.dets = []

    def __call__(self, budget):
        pass


HITS = [{"t_ms": t, "x": x, "kind": "tap", "lane": i}
        for i, (t, x) in enumerate([(500, 400), (700, 500), (900, 600),
                                    (1200, 700), (1500, 800), (1900, 900)])]


def _fire(inj, stop, t0_delta=0.3, late_fail=False):
    dump = os.path.join(tempfile.gettempdir(), "breakstop_dump.json")
    t0 = time.perf_counter() + t0_delta
    rc = player.play(HITS, inj, print, t0_fixed=t0, offset=0.0, watch=StillWatch(),
                     dump=dump, stop=stop, late_fail=late_fail)
    out = json.load(open(dump, encoding="utf-8"))
    os.remove(dump)
    return rc, out


def part1():
    """stop mid-fire vs no stop at all, same hits, same fake channel."""
    started = time.perf_counter()

    def stop():
        # truthy one action into the run (t0 sits 0.3 s after _fire's entry, first press at t0
        # +0.48): the abort has to land mid-list, with fingers down and actions still planned
        if time.perf_counter() > started + 0.9:
            return {"row": "MISS", "lo": time.perf_counter(), "hi": time.perf_counter() + 0.003}
        return None

    stopped = FakeInj()
    rc_s, out_s = _fire(stopped, stop)
    full = FakeInj()
    rc_f, out_f = _fire(full, None)
    ok = (rc_s == player.ABORTED
          and 0 < len(out_s["fired"]) < len(out_f["fired"])
          and out_s.get("aborted", {}).get("row") == "MISS"
          and set(stopped.downs) and set(stopped.downs) <= set(stopped.ups)
          and rc_f == 0 and "aborted" not in out_f)
    print(f"stopped: rc={rc_s} fired={len(out_s['fired'])}/{len(out_f['fired'])} "
          f"downs={sorted(set(stopped.downs))} ups={sorted(set(stopped.ups))} "
          f"aborted={out_s.get('aborted', {}).get('row')}; unguarded: rc={rc_f} "
          f"fired={len(out_f['fired'])}")
    print("PART 1 " + ("PASS" if ok else "FAIL"))
    return ok


def part2():
    """one committed event ends the trigger; an empty list reports nothing."""
    class FakeHud:
        def __init__(self):
            self.events = []

    hud = FakeHud()
    hint = run.BreakHint(hud)
    ok = hint() is None
    hud.events.append((1.0, 1.003, "MISS"))
    hud.events.append((2.0, 2.003, "GREAT"))
    first, again = hint(), hint()
    ok = ok and first == again == {"row": "MISS", "lo": 1.0, "hi": 1.003}
    print(f"first={first} again={again}")
    print("PART 2 " + ("PASS" if ok else "FAIL"))
    return ok


def part3():
    """late_fail on vs off vs armed-but-not-late, same born-late lock."""
    # t0 0.65 s in the past puts note 1's press (at t0 + 0.48) 0.17 s behind the fence, so it
    # is lost; notes 2-6 (from +0.03) are kept. The guard must abort immediately (row LATE),
    # with at most a press or two of overdue kept actions out; off, the same lock plays through.
    late = FakeInj()
    rc_l, out_l = _fire(late, None, t0_delta=-0.65, late_fail=True)
    old = FakeInj()
    rc_o, out_o = _fire(old, None, t0_delta=-0.65)
    # ... and armed on a healthy lock must be a no-op: nothing is lost, so the fence never swaps
    # the stop in and the run fires exactly like an unguarded one.
    ok_inj = FakeInj()
    rc_k, out_k = _fire(ok_inj, None, t0_delta=0.3, late_fail=True)
    ok = (rc_l == player.ABORTED
          and out_l.get("aborted", {}).get("row") == "LATE"
          and len(out_l["fired"]) <= 2 < len(out_o["fired"])
          and set(late.downs) <= set(late.ups)
          and rc_o == 0 and "aborted" not in out_o
          # The healthy lock keeps every note, the born-late one lost note 1, so ">=" (not ==):
          # the point is the guard did not eat a note it had no business eating.
          and rc_k == 0 and "aborted" not in out_k
          and len(out_k["fired"]) > len(out_o["fired"]))
    print(f"born-late guarded: rc={rc_l} fired={len(out_l['fired'])} "
          f"aborted={out_l.get('aborted', {}).get('row')}; unguarded: rc={rc_o} "
          f"fired={len(out_o['fired'])}; healthy guarded: rc={rc_k} fired={len(out_k['fired'])}")
    print("PART 3 " + ("PASS" if ok else "FAIL"))
    return ok


# The probe thread captures its first frame 0.8 s in and then every 1.5 s, so a chart that ends
# at 1.9 s only ever yields one frame. One note past 3 s buys a second and third.
LONG_HITS = HITS + [{"t_ms": 3600, "x": 900, "kind": "tap", "lane": 6}]


def part4():
    """play()'s own probe frames reach the dump; the host-capture path still writes `dets`.

    Until 2026-10-02 the probe thread's frames were reduced to two half-song log lines and
    dropped, which is why the 86 recent dumps carry 270k fired actions and not one blob: no
    finished run could be re-voted offline. This pins both halves of the new contract -- the
    frames are in the file, and only one source's frames are, whichever path ran.
    """
    frames_old, blobs_old = player.frames, player.note_blobs
    entered = time.perf_counter()
    # Distinct pictures, because `play`'s probe thread now refuses a frame that is the last frame
    # again (PART 5): a stub that hands back one object would be filtered as a frozen capture.
    seq = iter(range(1, 400))
    player.frames = lambda timeout=0.25: (time.perf_counter(),
                                          np.full((720, 1280, 3), next(seq), np.uint8))
    player.note_blobs = lambda img: [(300.04, 620.06), (420.5, 500.0)]
    dump = os.path.join(tempfile.gettempdir(), "breakstop_probes.json")
    try:
        player.play(LONG_HITS, FakeInj(), lambda *a: None, t0_fixed=time.perf_counter() + 0.3,
                    offset=0.0, watch=None, dump=dump)
        out = json.load(open(dump, encoding="utf-8"))
    finally:
        player.frames, player.note_blobs = frames_old, blobs_old
        os.remove(dump)
    pr = out.get("probes") or []
    flat = [v for f in pr for bl in f[1] for v in bl]
    ok = (len(pr) >= 2 and "dets" not in out
          and all(len(f) == 2 and f[0] >= entered for f in pr)
          # Rounded to a tenth of a pixel on the way out (300.04 in the feed, 300.0 in the file),
          # and every blob of the frame kept whole.
          and all(b == round(b, 1) for b in flat)
          and sum(len(f[1]) for f in pr) == 2 * len(pr))
    print(f"probes in dump: {len(pr)} frames / {sum(len(f[1]) for f in pr)} blobs, "
          f"dets written: {'dets' in out}")
    print("PART 4 " + ("PASS" if ok else "FAIL"))
    return ok


def part5():
    """A frozen capture is not a second sample: the probe thread must refuse it out loud.

    `LiveCorrector` commits when two consecutive samples agree about the clock, and the dump this
    thread writes is re-voted offline -- both count *samples*, so the same buffer handed back twice
    does not merely add nothing, it adds the previous one again. The renderer can do this (a valid
    frame, a fresh stamp, old pixels), and so can a page that is simply not animating.
    """
    def run_once(key):
        frames_old, blobs_old, k_old = player.frames, player.note_blobs, player.frame_key
        same = np.full((720, 1280, 3), 7, np.uint8)
        player.frames = lambda timeout=0.25: (time.perf_counter(), same)
        player.note_blobs = lambda img: [(300.04, 620.06), (420.5, 500.0)]
        player.frame_key = key
        lines = []
        dump = os.path.join(tempfile.gettempdir(), "breakstop_frozen.json")
        try:
            player.play(LONG_HITS, FakeInj(), lines.append,
                        t0_fixed=time.perf_counter() + 0.3, offset=0.0, watch=None, dump=dump)
            out = json.load(open(dump, encoding="utf-8")) if os.path.exists(dump) else {}
        finally:
            player.frames, player.note_blobs, player.frame_key = frames_old, blobs_old, k_old
            if os.path.exists(dump):
                os.remove(dump)
        return out.get("probes") or [], "\n".join(lines)

    n = [0]
    guarded, glog = run_once(lambda img: 0)                      # every frame reads as the last
    open_, olog = run_once(lambda img: n.__setitem__(0, n[0] + 1) or n[0])   # always new
    # The first sample is always let through (there is nothing to compare it to), so the whole
    # difference is in what comes after: one accepted frame against the three the same script
    # collects when the frames are genuinely new, and the refusal is said out loud once.
    ok = (len(guarded) == 1 and glog.count("上一帧") == 1 and len(open_) >= 2
          and "上一帧" not in olog)
    print(f"同一张图一直交回来：收下 {len(guarded)} 帧（第一帧总要）、说了一次重复 "
          f"{glog.count('上一帧')}；把新鲜度判据换成'每帧都新'的同一剧本：收下 {len(open_)} 帧 -> "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if (part1() and part2() and part3() and part4() and part5()) else 1)
