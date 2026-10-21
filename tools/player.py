"""Play a compiled hit list into the emulator through the raw event4 touch channel.

Timing model: t0 is the instant the song audio starts. Every action fires at
hit.t_ms + offset - pre, so `offset` is the one number that has to be calibrated.
"""
import argparse
import contextlib
import ctypes
import gc
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compile import JUDGE_Y, edge_x  # noqa: E402
from detect import anchor_vote, frame_key, frames, note_blobs, sprite_blobs, vote_t0  # noqa: E402
from inject import to_raw  # noqa: E402
from mtouch import MTouch  # noqa: E402
from rlog import RUNS, subdir  # noqa: E402


# Every kind of note the compiler emits, and how much earlier than the shared clock each one is
# pressed. All zero is the recipe every flown result was played on, and the panel's 种类偏移
# starts there: the table exists so the tap-vs-flick conflict can be *measured* apart (a flick that
# is pressed late falls inside the next tap's credit window, while the chain wants presses later),
# not so it can be tuned from a hunch.
KINDS = ("tap", "long", "flick", "trace")
KIND_LEAD_MS = {k: 0.0 for k in KINDS}


def raise_timer_resolution():
    winmm = ctypes.windll.winmm
    winmm.timeBeginPeriod(1)


# An action that lands more than this many ms after its scheduled instant is worth naming in the
# log: the judgement window is ±50 ms, so a pause of this size already ate a fifth of the margin,
# and 12163 sampled 400-action windows (2026-10-19, `research/runs/*.out`) show 1.9% of them carrying a
# spike above 5 ms -- the tail that a MISS can be made of. The first STALL_LOG_MAX are named one by
# one (with the collector's own counters, so a GC pause is distinguishable from a starved host);
# after that only the tally grows, because a starved host does not need a line per action.
STALL_MS = 5.0
STALL_LOG_MAX = 20


@contextlib.contextmanager
def gc_guard(log=print):
    """Stop the garbage collector for the length of one song.

    The scheduler itself is not the problem -- `late` p50 over ~2000 rounds is 0.00 ms -- but its
    tail is, and Python's collector is the one pause we can take out of it. `freeze()` moves every
    object that is already alive into the permanent generation (it can never be freed, so it is
    never traversed again) and `disable()` stops the automatic collections for the song's two
    minutes; whatever cycle garbage the frame threads make in that window is a few MB and is
    collected as soon as the round is over. Wrapped around `play()` by run.py, so the enable runs
    even if the song raises.
    """
    gc.collect()
    gc.freeze()
    gc.disable()
    log("  gc: 曲中停止回收（freeze + disable），一曲结束即恢复")
    try:
        yield
    finally:
        gc.enable()


# The chart needs at most two fingers at once, but taps landing inside a hold's window on the
# other side need their own finger, and a note is never dropped for want of a slot.
SLOTS = 6
MIN_HOLD_MS = 300.0
# How long past its own tail a hold's finger stays down, in ms. 20 is the shipped value. The
# release is scheduled at tail + 20 in compiled chart time, and the link judges a press ~6 ms
# before the action it was scheduled for (a tap's action is planned at note - 20 while the clean
# rounds' `chain cal` reads -26 ms), so the finger is still down ~14 ms *after* the game judges
# the hold's last object -- #111's rule puts that object exactly on the tail. 45 would put it at
# +39, i.e. 11 ms from the ±50 GREAT wall, for no gain.
#
# The 2026-10-09 raise to 45 was undone the same night, because its premise was a measurement
# artifact: `research/experiments/objmap.py`'s ref_of() added `offset/1000` on top of a `t0` that
# already had the offset folded in (dets' `host = t0 + chart`, verified against the compiled
# action list), so a release that really lands 23 ms AFTER the object printed as 22 ms BEFORE it;
# `research/experiments/tailgap.py` had the same 45 ms baked into its `land` (-42 instead of -6),
# which is where the "81% of releases land before the last object" number came from. With the
# timebase fixed, no release lands before its last object at any margin >= 20.
# What actually decided it (2026-10-09 night, all on 0056_03 expert): 40 nominal rounds at 45
# lost 10/40 single notes (ktnom), tonight's margin-20 rounds lost 2/6 (kd55a/b/c + kd35a/b/c),
# and the 123-round g* baseline at 20 lost 13/123 -- the margin is not the lever; the single
# loss is a game-side coin flip on an `end_flick` tail (the input is byte-identical between an
# AP round and a losing one, `research/experiments/detdiff.py`). `--tail-margin` still overrides
# the constant for one round, which is how that A/B was run.
TAIL_MARGIN_MS = 20.0
# How much EARLIER the swipe of a 长条's tail flick is scheduled than the tail node's own ms. The
# game reads that one gesture late: the user measured ~20 ms SLOW on-device (2026-10-19) across
# charts, while a plain tap-lane flick whose laterals sit on `t + 2` / `t + 16` judges PERFECT --
# so the lateness is specific to a flick that comes off a hold's tail, not to the flick action
# itself (see build_actions' end_flick branch). The whole tail group moves, not just the release:
# the two 45 px laterals keep their 14 ms spacing (the frame-drop lesson), and the release stays
# `TAIL_MARGIN_MS` past the tail in the shifted clock, i.e. it still lands after the flick node.
# The move is geometrically free: 3748 `end_flick` longs in the library, their widened tail
# hitbox is 172..1032 px wide (median 430, one grid unit is 43 px) against a 90 px swipe, so the
# two lateral steps sit inside the tail's own hitbox and cannot break the hold. 0.0 is the
# pre-2026-10-19 behaviour, kept reachable through `--tail-flick-lead` for an on-device A/B.
# 20 was the first cut (compensating the whole reported 20 ms); the user asked for 10 on
# 2026-10-19 (m50302) -- half the correction, so the judgement still has ~10 ms of room on the
# early side for the jitter of the same measured gesture.
TAIL_FLICK_LEAD_MS = 10.0
# play() returns this when a `stop` callback ended the attempt early: the caller (run.py's
# --retry-on-break) owns what happens next -- pause, 重试, re-anchor -- and the player guarantees
# only that the fire loop stopped at an action boundary and every finger was lifted before
# returning.
ABORTED = 2
# Heads this close together are one event to the game, so they take a live correction as a unit.
CHORD_GROUP_MS = 40.0
# The field is centred on the screen, so the hand split is just which half of it a note is on.
FIELD_MID = sum(edge_x(JUDGE_Y)) / 2
# A hold too short for MIN_HOLD keeps its finger parked on the tail's x until the minimum press
# is over, and a trace whose head lands on that same x is then judged with two contacts on the
# lane: 0056_03's +70.889 s test has the trace 0.65 ms behind the tail and it is the only
# trace-on-a-parked-finger hand-off in the library (the 17 taps and one flick that do the same
# are all AP), while it breaks 1 run in 3 -- every single-note failure of the evening. The ghost
# is taken off the lane at tail + 30 ms, while the trace is judged, and returned before the
# release, which stays exactly where MIN_HOLD put it.
GHOST_CLEAR_MS = 30.0      # the finger holds the lane this long past its tail before stepping off
GHOST_RETURN_MS = 8.0      # ... and is back on it this long before the release
GHOST_CLEAR_PX = 70.0      # how far off the lane it steps (towards the field centre)
GHOST_NEAR_PX = 30.0       # a head this close to the tail x counts as the same lane

# How far the live corrector may move the remaining presses LATER, in ms. The earlier side keeps
# its -120 ms clamp; this side is bounded because a positive push is what the 626 object answers
# to (LiveCorrector has the split). run.py's --live-push-cap defaults here, the panel's 运行卡
# edits it and its 正推限制 switch turns it off.
LIVE_PUSH_MS = 10.0

# How many votes the winning bin must beat the runner-up by before an agreeing pair may move the
# clock. One is not enough, and g239's first pass is why: at chart +47.9 s six blobs voted -150 ms
# (5 vs 3), the pool carried them into the +50.9 s vote, and that one "agreed" at -152 ms with the
# runner-up family one vote behind -- 11 vs 10 -- which committed -45 ms and broke the run 0.3 s
# later. Two is not enough for a *big* move either: on 2026-10-07 g458 agreed on -163 ms with 12
# votes against a runner-up of 9 -- three votes, not one -- committed the full -45 ms step, and
# every one of the remaining 204 judged objects landed GREAT-FAST (638 PERFECT + 204 GREAT). The
# two aliases in the corpus (g454 -160 at 9/7, g458 -163 at 12/9) both asked for >= 100 ms; the
# useful corrections are g393 -7 at 8/0, g395 -2 at 5/1, g409 -12 at 9/5, g420 -23 at 8/4, g425 -6
# at 12/3, g436 -8 at 9/2, g438 -6 at 8/1, g449 -10 at 7/0, g452 -7 at 8/3 and +13 at 10/3 -- all
# <= 23 ms, and three of them (g392 +6, g393 0, g425 -6) do not clear their runner-up by 4 at all.
# So the margin is two-tiered rather than raised: see VOTE_MARGIN_BIG below.
VOTE_MARGIN = 2

# The margin a move *past* SMALL_MOVE_MS has to clear. Raising the flat margin to 4 instead was
# measured and rejected: it kills both aliases but also refuses g392/g393/g425's 0..6 ms steps and
# hands g460 a step of its own, because a refused pair changes the pool the next vote sees -- and a
# 6 ms correction sits inside the noise that decides a one-object round (g452 and g457 both lost a
# single object at this operating point). The bigger the claim, the stronger the evidence.
VOTE_MARGIN_BIG = 4

# Where "big" starts, in ms. The corpus's useful corrections are all <= 23 ms and its two aliases
# both wanted >= 100 ms, so the boundary only has to separate 6 ms from 160 ms; 15 leaves both
# measured populations untouched and is the smallest round number above the push cap the panel
# ships (LIVE_PUSH_MS = 10), so a panel round that wants its full cap is not treated as a big claim.
SMALL_MOVE_MS = 15.0

# The largest mid-song correction the corpus justifies, in ms. Every useful commit above is
# <= 23 ms; the two > 100 ms votes are the aliases VOTE_MARGIN now refuses. A pair that agrees,
# wins its margin and still wants more than this is refused *and logged* -- never silently kept,
# because "kept" and "the votes never agreed" read identically in the log, and the cost of being
# wrong is the rest of the round (both wrecked runs above stepped the full max_step, 45 ms).
# This is the second rail on purpose: an alias can win by a margin (that is what g458 looked like
# once the pool had grown), so the margin alone cannot be the whole story.
CORR_TRUST_MS = 50.0

# ...but the rail above must not jail the *opening* lock, which is the one error this class exists
# to fix. 2026-10-08, the first multi rounds: the anchor locked the clock some 155 ms early on
# 0056_03 (all 355 of the round's misses read SLOW, residual +74 ms) and some 45 ms early on
# 0094_03 (+44.5 ms); both fields then held a negative plateau -- 0056_03 at -155 ms for twelve
# consecutive votes from chart +33 s -- and every one of them was refused, so both rounds played
# out on a raw, never-corrected clock. Replaying those two runs' recorded probes offline
# (research/experiments/voteseq.py) reproduces the live refusal line verbatim.
#
# That policy is opt-in (`LiveCorrector(..., open_trust=True)`, which run.py asks for only on a
# 多人 round) and deliberately not the default: the corpus the rails were calibrated on is
# single-player, where the opening lock is good and every useful commit is <= 23 ms, so a 45 ms
# step there is the g454/g458 alias shape the rails exist to refuse -- tools/probes/votereplay.py
# pins exactly that and must stay green. A multi round is a different regime: its opening lock is
# measurably wrong in both rounds seen, and its votes come off a field carrying five players.
#
# The doubt has to be earned even there, because the rail is also what stops the staircase alias:
# 0056_03's *first* plateau sat at +154 ms -- its own known +316 ms echo -- so opening the rail on
# elapsed time alone would have committed the wrong side first. A run only becomes eligible once
# one of its own votes has already come back past the rail with nothing committed yet ("the lock
# this run started from is not trustworthy"); from then on the window stays open while the votes
# keep naming the same side the correction already took -- mp5 spent its one allowed step at chart
# +51 s and then watched a -133 ms plateau it could no longer act on -- and the small margin is
# enough: the plateaus that name the error are long (twelve votes) even when their peak-to-runner
# edge is thin, and waiting for the big margin is what pushed 0056_03's fix out to chart +75.9 s of
# a 101 s chart. g458 -- a clock that was fine, then a mid-song alias at -163 ms -- never
# qualifies, because its early votes all sit near zero. What bounds the window is max_corr (120 ms)
# and the side rule: a vote claiming more than SMALL_MOVE_MS back the other way is refused, first
# commit or not.


def _side(x):
    return -1 if x < FIELD_MID else 1


def field_x(x, y):
    """Clamp a compiled x to the field's own edges at row y.

    A slide bar's hidden waypoints leave the 0..24 lane grid (0096_03's long at 48.75 s runs
    through pos 19 size 16, centre 27), and lane_to_x then extrapolates past the right edge of
    the screen: g067 and g068 both died at chart +49.15 s when to_raw refused x=1297, and one
    waypoint took the whole attempt down with it. Nothing can be drawn outside the field, so the
    finger follows the bar as far as the field goes -- a clamp costs at most that bar.
    """
    lo, hi = edge_x(y)
    return min(max(x, lo), hi)


def build_actions(hits, judge_y, pre_ms, hold_ms, flick_dx, flick_dy=0, kind_lead=None):
    """Return a time-ordered action list: (t_ms, op, slot, x, y).

    A slot is a real finger, so it cannot be in two places at once: a hold owns its slot from
    head to tail (releasing early breaks it), and a note is handed to the free slot already on
    its own side of the field, which is what keeps the two-finger left/right shape of the chart
    instead of stacking everything onto one hand.

    `kind_lead` is {kind: ms} and moves a kind's **whole sequence** -- head, every step, tail --
    never the head alone. A long's press and its release are one finger's occupation: shifting
    only the head would slide the release across the next note while leaving the hold itself
    where it was. Empty or None is today's behaviour to the millisecond.

    The sign is 提前: a positive value presses that kind **earlier**, which is what the panel's
    boxes and the run's log line say they are setting.
    """
    notes = []
    kinds = []
    ghosts = []              # (index in `notes`, tail ms, tail x, release ms) of parked holds
    for h in hits:
        t = h["t_ms"]
        if h["kind"] == "long":
            start = t - pre_ms
            # Releasing at the exact tail ms risks a miss on the last frame, and a hold that is
            # shorter than the game's minimum contact is read as a tap. See TAIL_MARGIN_MS for
            # why the margin is larger than the +20 this used to be.
            end = max(h["end_ms"] + TAIL_MARGIN_MS, start + MIN_HOLD_MS)
            seq = [(start, "down", h["path"][0]["x"], judge_y)]
            seq += [(start + (p["t_ms"] - h["t_ms"]), "move", p["x"], judge_y)
                    for p in h["path"][1:]]
            ef = h.get("end_flick")
            if ef is None:
                seq.append((end, "up", h["path"][-1]["x"], judge_y))
                if end > h["end_ms"] + GHOST_CLEAR_MS:
                    ghosts.append((len(notes), h["end_ms"], h["path"][-1]["x"], end,
                                   h.get("time_shift_ms", 0.0)))
            else:
                # The hold ends in a flick and only a moving finger reads it, so once the trail
                # is done the tail gets the second half of the plain flick action: the swipe
                # sampled in two 45 px steps 14 ms apart and the release 28 ms after the tick,
                # exactly how every tap-lane flick is done. A single +90 jump is born and
                # re-positioned inside one frame whenever the frame time dips (the t07/t09
                # lesson), and the engine then sees a parked contact: the tail reads as a tap
                # and MISSes with a near-zero timing value (jp_0062's 43.067 s unit lost 3/3
                # runs that way while every timestamp was +2 ms).
                fx0 = h["path"][-1]["x"]
                fx = fx0 + flick_dx
                # The game reads this one gesture late (see TAIL_FLICK_LEAD_MS), so the tail
                # group -- both laterals and the release -- runs that much earlier than the tail
                # node's own ms. The trail point that would otherwise sit on top of the swipe is
                # dropped: the finger has to be at the tail x before the first 45 px step goes,
                # and a trail move landing after it would drag the contact back onto the bar in
                # the middle of the swipe.
                tail = ef["t_ms"] - TAIL_FLICK_LEAD_MS
                if TAIL_FLICK_LEAD_MS > 0.0:
                    seq = [a for a in seq if a[0] < tail]
                seq.append((tail + 2.0, "move", fx0 + flick_dx * 0.5, judge_y))
                seq.append((tail + 16.0, "move", fx, judge_y))
                seq.append((max(end - TAIL_FLICK_LEAD_MS, tail + 30.0,
                                start + MIN_HOLD_MS), "up", fx, judge_y))
            sh = h.get("time_shift_ms", 0.0)
            if sh:
                # The whole bar runs one input frame late so no event of it shares a millisecond
                # (hence a batch, hence a game frame) with the concurrent bar it crosses.
                seq = [(tm + sh, op, ax, ay) for tm, op, ax, ay in seq]
            notes.append((h["path"][0]["x"], seq))
            kinds.append("long")
        elif h["kind"] == "flick":
            # The game accepts a flick in any direction, so one fixed swipe vector is used. The
            # jump is sampled in two 45 px steps instead of one: the engine reads touch positions
            # once per delivered frame, and in the fever section's frame-time dips a single
            # down->far jump can be born and re-positioned inside one frame, where the delivery
            # shows a stationary contact at the far point and the swipe is invisible -- the flick
            # then reads as a tap and MISSes (t07/t09's failing units were timed +2 ms on the
            # judgement popup and still rejected). Two steps 14 ms apart keep a >=45 px
            # frame-to-frame delta for any frame up to ~35 ms, and the release still lands on
            # +30 so the 52.6 ms flick train at the section's tail keeps its 2.6 ms regroup.
            notes.append((h["x"], [
                (t - pre_ms, "down", h["x"], judge_y),
                (t + 2, "move", h["x"] + flick_dx * 0.5, judge_y - flick_dy),
                (t + 16, "move", h["x"] + flick_dx, judge_y - flick_dy),
                (t + 30, "up", h["x"] + flick_dx, judge_y - flick_dy),
            ]))
            kinds.append("flick")
        else:
            notes.append((h["x"], [
                (t - pre_ms, "down", h["x"], judge_y),
                (t - pre_ms + hold_ms, "up", h["x"], judge_y),
            ]))
            kinds.append(h["kind"])

    # The parked finger of a short hold steps off the lane while a trace's head takes it, and
    # comes back before its release -- see GHOST_CLEAR_MS. Only a trace triggers it: it is the
    # one kind the game judges as a slide, and the only place in the library where it lands on a
    # parked finger at all.
    for gi, tail_ms, tail_x, end, sh in ghosts:
        for j in range(gi + 1, min(gi + 4, len(notes))):
            if kinds[j] != "trace":
                continue
            head_ms = notes[j][1][0][0] + pre_ms      # the head's own time, not its press
            if head_ms > end:
                break
            if head_ms < tail_ms - 5.0 or abs(notes[j][0] - tail_x) > GHOST_NEAR_PX:
                continue
            seq = notes[gi][1]
            away = field_x(tail_x + (GHOST_CLEAR_PX if tail_x <= FIELD_MID else -GHOST_CLEAR_PX),
                           judge_y)
            back = min(end - GHOST_RETURN_MS, seq[-1][0] - GHOST_RETURN_MS)
            if back - (tail_ms + GHOST_CLEAR_MS) < 4.0:
                break                      # no room between the step-off and the release
            seq.insert(len(seq) - 1, (back + sh, "move", tail_x, judge_y))
            seq.insert(len(seq) - 2, (tail_ms + GHOST_CLEAR_MS + sh, "move", away, judge_y))
            break

    busy = [0.0] * SLOTS     # ms at which each finger next leaves the field
    last_x = [None] * SLOTS
    actions = []
    for (x, seq), kind in zip(notes, kinds):
        lead = (kind_lead or {}).get(kind, 0.0)
        if lead:
            seq = [(t - lead, op, ax, ay) for t, op, ax, ay in seq]
        need = seq[0][0]
        want_left = _side(x) < 0
        cand = [s for s in range(SLOTS) if busy[s] <= need]
        if cand:
            parked = [s for s in cand if last_x[s] is not None and _side(last_x[s]) == want_left]
            free = parked[0] if parked else cand[0]
        else:
            # Every finger is committed; steal the one that frees soonest rather than dropping
            # the note, and let the overlap show up in the report.
            free = min(range(SLOTS), key=lambda s: busy[s])
            print(f"  !! slot {free} overrun at {need:.0f} ms (busy until {busy[free]:.0f})")
        busy[free] = seq[-1][0]
        last_x[free] = x
        for tm, op, ax, ay in seq:
            actions.append((tm, op, free, ax, ay))
    actions.sort(key=lambda a: (a[0], a[1] == "down"))
    return actions, SLOTS


# The notes whose presses can be lost to the lock are the ones due while the vote is still
# deciding, and on this chart that is the opening chord, the sliding long behind it and
# everything up to the tap/long pair at 7.58 s. The next note after that is a full second later,
# well past any plausible lock.
INTRO_MS = 8500.0


class _IntroShotgun:
    """Press the opening notes from the vote's own clock while the vote is still deciding.

    Its own thread, not the anchor loop: the anchor's cadence is a screencap, ~280 ms, which is
    half a PERFECT window, so a press scheduled from inside that loop could never land in one.
    The thread sleeps to each press time and fires; the anchor feeds it every vote, and the press
    plan only commits once two consecutive votes agree on one clock within 30 ms -- the same
    agreement the anchor itself accepts on.

    A tap is one down/up pair, a long is its whole compiled path (down at the head, a move per
    path point, up after the tail), so the intro's sliding longs are covered exactly the way the
    fire loop would play them. Abracadabra opens with a two-lane chord, and a chord needs two
    fingers at once -- one slot covering only the first note is what left its partner to be
    pressed 91 ms late by the fire loop (a37's GREAT). Presses that overlap in time therefore
    take separate slots.

    One alignment, not two: t03 scheduled the presses of the two leading alignments while the
    vote was undecided, and the second candidate sat 1.0 s away -- its presses ate the slots the
    real ones needed, notes 9/10 were fired at both clocks (the early pair collapsing onto a
    single starved slot) and the leading candidate's own presses starved behind them for 14
    misses. The plurality was the truth from the first vote of that run, twice in a row inside
    2 ms, so waiting for the pair-of-votes agreement costs nothing and the second candidate buys
    nothing but strays.

    Every target is scheduled at most once, and a press with no free slot is dropped and logged
    instead of handed a slot already in use. `busy_until` is written when a press is scheduled,
    not when it fires, so a slot's commitments are visible to the scheduler the moment they
    exist -- the t03 collision was two chord notes picked across two align() calls, the first
    one pending (not yet fired) and therefore invisible to the second call's slot check.

    Four slots, not three: a38 lost the intro's second note to four simultaneous presses -- the
    opening chord scheduled at both live alignments, 0.6 ms apart -- over three slots. The fourth
    press was handed a slot already in use at that instant, its touch_down overwrote the third
    one, and the overwritten note was never pressed; the fence had already counted both as
    covered (the fired list logs the schedule, not the hardware), so the fire loop never came
    back for it. They sit on ids 6..9, which the fire loop never builds actions on (ids 0..5 for
    the six play slots), so even the corner where a press outlives the join cannot collide with a
    fire-loop finger. Not 10..12: minitouch advertises ten contacts, and t04's opening chord --
    fenced as covered, so the fire loop never came back for it either -- crossed the band unhit
    because its presses went out on ids 11 and 10 and the daemon dropped them without a word.

    `stop()` does not cut the thread off: a down already on the glass has to be followed by its
    up (a sliding long can owe the glass a full second of moves), so the thread finishes the
    entries it has committed and exits when its queue drains. The overlap with the fire loop is
    safe because the touch ids are disjoint.
    """

    SLOTS = (9, 8, 7, 6)

    def __init__(self, inj, targets, pre_ms, hold_ms, judge_y, log, offset=0.0):
        self.inj = inj
        self.targets = targets          # (idx, [(t_ms, x), ...] from the head, up_ms)
        self.pre = pre_ms
        self.hold = hold_ms
        self.judge_y = judge_y
        self.log = log
        # Presses go out on the same clock the fire loop uses, offset correction included: the raw
        # vote t0 is early on the judged clock, and a29's only non-PERFECT was exactly a shotgun
        # press fired from the raw value -- note 1, GREAT FAST, while every corrected press in the
        # same run was PERFECT. A press that lands outside the window it was fired to claim is
        # worse than no shotgun at all.
        self.offset = offset
        self.lock = threading.Lock()
        self.pending = []               # sorted (host_t, op, idx, slot, x)
        self.fired = {}                 # idx -> [press host times fired]
        self.claimed = set()            # idx whose down has gone out
        self.down = {}                  # slot -> host time of the down still on the glass
        self.busy_until = {}            # slot -> host time the finger is off the glass
        self.scheduled = set()          # idx whose plan is committed (or was dropped)
        self.last_t0 = None             # the previous vote's leading alignment
        self.draining = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _pick_slot(self, p):
        """The first intro slot whose last commitment ends before `p`, or None (lock held)."""
        for s in self.SLOTS:
            if self.busy_until.get(s, 0.0) < p - 0.005:
                return s
        return None

    def align(self, t0, second_t0, peak, second):
        """Called by the anchor after every vote. Commits presses only once two consecutive votes
        have named the same clock within 30 ms; `second_t0` is deliberately not scheduled."""
        if t0 is None:
            return
        now = time.perf_counter()
        with self.lock:
            if self.draining.is_set():
                return
            confirmed = (self.last_t0 is not None and abs(t0 - self.last_t0) <= 0.030)
            self.last_t0 = t0
            if not confirmed:
                return
            base = t0 - self.offset / 1000.0
            for idx, pts, up_ms in self.targets:
                if idx in self.scheduled:
                    continue
                self.scheduled.add(idx)
                p = base + (pts[0][0] - self.pre) / 1000.0
                # A press due more than 30 ms ago is not worth firing: late inside the
                # PERFECT band it is a duplicate of nothing, late outside it is a BAD the
                # skip would not have had.
                if not now - 0.030 < p:
                    continue
                slot = self._pick_slot(p)
                if slot is None:
                    # Dropped, not double-booked: two downs on one id merge into something that
                    # is neither note, and the fence would still count both as covered.
                    self.log(f"  !! intro slot starvation: note {idx + 1} at {p:.3f} dropped")
                    continue
                self.busy_until[slot] = base + up_ms / 1000.0 + 0.01
                self.pending.append((p, "down", idx, slot, pts[0][1]))
                for tm, x in pts[1:]:
                    self.pending.append((base + (tm - self.pre) / 1000.0, "move", idx, slot, x))
                self.pending.append((base + up_ms / 1000.0, "up", idx, slot, pts[-1][1]))
            self.pending.sort()

    def _run(self):
        try:
            while True:
                now = time.perf_counter()
                due = []
                with self.lock:
                    while self.pending and self.pending[0][0] <= now + 0.030:
                        due.append(self.pending.pop(0))
                    for t, op, idx, slot, _ in due:
                        if op == "down" and idx not in self.claimed:
                            # Recorded at pop, not after the write: an align() racing the press
                            # must see this press as taken, or it schedules a second one.
                            self.claimed.add(idx)
                            self.fired.setdefault(idx, []).append(t)
                            self.down[slot] = t
                        elif op == "up":
                            self.down.pop(slot, None)
                    drained = not self.pending and self.draining.is_set()
                if due:
                    for t, op, idx, slot, x in due:
                        self._wait_until(t)
                        if op == "up":
                            self.inj.touch_up(slot)
                            continue
                        rx, ry = to_raw("MEASURED", field_x(x, self.judge_y), self.judge_y)
                        if op == "down":
                            self.inj.touch_down(slot, rx, ry, slot + 1)
                            # Logged before the wait for what follows: the note number pins any
                            # merge to a finger, and the batch's downs keep their timing.
                            self.log(f"  intro press: note {idx + 1:>3} slot {slot:>2} at {t:.3f}")
                        else:
                            self.inj.touch_move(slot, rx, ry)
                elif drained:
                    return
                else:
                    time.sleep(0.004)
        except Exception as e:                                  # noqa: BLE001
            self.log(f"  !! intro shotgun died: {e!r}")
        finally:
            # No shot finger may outlive the thread, whatever path it exits by.
            with self.lock:
                stuck = list(self.down)
                self.down.clear()
            for slot in stuck:
                self.inj.touch_up(slot)

    @staticmethod
    def _wait_until(t):
        while True:
            rem = t - time.perf_counter()
            if rem <= 0:
                return
            if rem > 0.003:
                time.sleep(rem - 0.002)

    def stop(self):
        """Stop taking new targets and return {idx: [press times]}.

        Committed entries still play out on the thread (a long's moves and up are owed to the
        glass); it exits on its own. Downs still sitting in the queue count too: they fire a
        moment later no matter what, and a fence that could not see them -- t04, whose stop()
        returned only the fired list -- counted their notes as uncovered and the fire loop
        double-pressed notes 3 through 12 behind the shotgun.
        """
        self.draining.set()
        with self.lock:
            out = {k: list(v) for k, v in self.fired.items()}
            for t, op, idx, _, _ in self.pending:
                if op == "down":
                    out.setdefault(idx, []).append(t)
            return out


class LiveCorrector:
    """Re-anchor the fire clock mid-song from the falling notes, and keep it re-anchored.

    The opening anchor cannot always be trusted: 唱 opens with long bars the blob mask cannot
    see, so its relock window is empty by construction and every run plays on the
    t_field+0.045 fallback, which wandered +-27 ms across g009-g013 (+3 / -27 / +12 / +12 / +7).
    With the chain the way it is (presses judged ~-42 ms at offset 55), the clock error decides
    the run: a +12 draw floods it GREAT-FAST (g011's 289) while a -27 draw walks toward the
    other wall. The error is constant for the whole run, so one solid vote fixes everything
    after it -- the probe thread feeds every blob it captures, the corrector histogram-votes
    them against the chart (vote_t0, the instrument the opening relock uses, band centred on
    the current belief), and once two consecutive votes agree within 15 ms the correction goes
    live: every press not yet fired is shifted, so a 唱-class chart plays its first notes on
    the fallback and the remaining hundreds on a voted clock.

    Safety rails, one per way a lone vote can be wrong: two consecutive votes must agree (a
    sparse field ties the truth with a long note's tail family), and the second of them has to
    beat its runner-up by VOTE_MARGIN before the pair may move anything -- or by VOTE_MARGIN_BIG
    when the move it asks for is past SMALL_MOVE_MS, since the two aliases in the corpus wanted
    160 ms and a 6 ms correction is worth a GREAT-sized nudge at most; the correction it agrees
    on must lie within CORR_TRUST_MS of the nominal clock, because a 157 ms-spaced staircase can
    alias a whole window onto the neighbouring step -- that pair agrees with itself, wins its
    margin, and is still 160 ms wrong; the band keeps the chart's +-0.316 echo out; the correction
    is clamped (down to -120 ms, up to less -- see below); and re-commits inside a 6 ms deadband
    are skipped, because churn around the truth is how a working clock gets destroyed.

    One commit also moves the clock by at most max_step. The clamp alone was not enough: on
    2026-09-30 g118 took a single aliased pair of votes in a 157 ms-spaced section and stepped
    the remaining half of the song -120 ms in one go -- 110 MISS, the only |>=60 ms| commit in
    the corpus's 98. A genuinely large error still converges, because each new commit is voted
    against the moved belief and a real error keeps agreeing; what the step size buys is that a
    wrong vote costs a GREAT-sized nudge instead of a note's worth of time. 2026-10-07's g458 was
    that shape one rail short: a -163 ms window at 12 votes to 9 committed the full -45 ms step,
    and the remaining 204 judged objects all landed GREAT-FAST -- which is why the pair's margin
    was raised and the trusted-drift rail added above, rather than the step size lowered.

    On a 多人 round (open_trust=True) the trusted-drift rail is also open, and the window it opens
    is wider than one commit. The live 多人 rounds of 2026-10-08 all locked a clock tens to 155 ms
    out, and mp5 showed what one max_step buys: the -45 ms landed at chart +51 s of a 111 s chart,
    the clock then sat 88 ms from the plateau every later vote still named (-133 ms), and the window
    had shut behind it. So once earned the window stays open, and what bounds it is the side: a vote
    claiming more than SMALL_MOVE_MS against the direction the correction already took is mp4's
    +139 ms plateau (whose result page read SLOW), not a drift, and is refused -- the direction is
    the one thing the result page can confirm. A pair may also step over one noisy vote, because
    those plateaus are thin-edged (mp5: edges of 1-2) and a lone draw between two plateau votes used
    to reset the run. Nothing here reaches a single-player run: open_trust is False there, and the
    clamp at max_corr bounds the whole window however many plateaus it sees.

    The upward clamp is 10 ms, and it is the one number in this class that came from a single
    object. 0056_03's 628th judged object is a trace at chart +70.890 s whose x is the x the long
    before it ended on 0.65 ms earlier -- the only trace-on-a-parked-finger hand-off in the
    library. Cutting the window's 87 runs of that chart by the correction in force at that
    object: 17 runs at <= 0 ms broke it 0 times, 60 runs at > 0 ms broke it 13 (22%, Fisher
    p=0.028), every break BAD or MISS on the FAST side, and the breaks start at +8 ms rather
    than at any threshold. The cut the corpus supports on its own is therefore the sign; 10 ms
    is a deliberate sliver of the other side, kept so a genuinely late chart is still nudged,
    and the panel's 设置 page owns the number (0 reproduces the sign cut, 120 removes the
    bound). The ghost-clear special case for the same object is still in place (GHOST_CLEAR_MS)
    and had already taken the rate from 33% to 7%; what survived it is all on the positive side.

    The cost is bounded and one-sided: a chart whose votes want a later clock now runs up to 10 ms
    short of them (0056_03's p90 vote is +18 ms, 0062_03's +26), and the result page's histogram
    still measures the residual, which chain cal still moves the next round's offset for.
    """

    def __init__(self, notes, ref, log, band=0.28, max_corr=0.12, deadband=0.006,
                 max_dets=600, max_step=0.045, max_corr_up=None, open_trust=False):
        self.notes = notes
        self.ref = ref
        self.log = log
        self.band = band
        self.max_corr = max_corr
        self.max_step = max_step
        self.deadband = deadband
        self.max_dets = max_dets
        # None means the vote asks for the same ceiling both ways.
        self.max_corr_up = max_corr if max_corr_up is None else max_corr_up
        # 多人 rounds ask for this (see the note above CORR_TRUST_MS); every other caller, and the
        # corpus the rails were calibrated on, leaves it off.
        self.open_trust = open_trust
        self.dets = []
        self.corr = 0.0
        self.committed = 0
        # Corrections the trusted-drift rail refused, and what they wanted (ms). Counted apart from
        # the deadband/ceiling "kept" path on purpose: a refusal is the corrector saying the field
        # pointed somewhere impossible, and run.py reports the count at the end of the round.
        self.refused = 0
        self.refused_ms = []
        # Set once one of this run's own votes comes back past CORR_TRUST_MS while nothing has been
        # committed yet: the opening lock is suspect, so the rail may be opened for the pair that
        # finally agrees (see CORR_OPEN_TRUST). Never set after a commit -- that is g458's shape.
        self._open_doubt = False
        self._n_voted = 0
        self._agree = None
        # The vote before that one. Only the opening window reads it (see feed): one noisy draw
        # between two agreeing votes must not throw the plateau away.
        self._agree2 = None
        # The newest vote against the run's own clock, seconds (+ = the notes are later than we
        # press, so our presses land SLOW). Reported even when it does not commit: a run killed
        # mid-song never reaches the end-of-fire residual, and that number is the only thing that
        # tells "the clock drifted" apart from "the presses never arrived".
        self.last_vote = None
        # Every accepted vote of the attempt, in order. The live path only needs the newest one,
        # but run.py's retry loop needs the population: an attempt that died because the corrector
        # wanted to move and the push cap refused leaves its whole argument here (s291: eight
        # aborts on 0066_02, every attempt's votes reading +17..+26 ms).
        self.votes = []

    def feed(self, t, blobs):
        """Take one frame's blobs; vote, and commit once two votes in a row agree."""
        if not blobs:
            return
        self.dets.extend((t, y, x) for y, x in blobs)
        if len(self.dets) > self.max_dets:
            self.dets = self.dets[-self.max_dets:]
        if len(self.dets) - self._n_voted < 6:
            return
        self._n_voted = len(self.dets)
        v, peak, runner, _ = vote_t0(self.dets, self.notes,
                                     lo=self.ref + self.corr - self.band,
                                     hi=self.ref + self.corr + self.band)
        if v is None or peak < 4 or peak <= runner:
            return
        self.last_vote = v - self.ref
        self.votes.append(self.last_vote)
        raw = v - self.ref
        target = min(raw, self.max_corr_up) if raw > 0 else max(raw, -self.max_corr)
        # A vote past the rail with nothing committed yet is the opening lock saying it is wrong
        # (see CORR_OPEN_TRUST). Remember it; the pair that finally agrees may then act on it.
        if abs(target) * 1000.0 > CORR_TRUST_MS and not self.committed:
            self._open_doubt = True
        # The window does not shut at the first commit. A 多人 lock 155 ms out needs more than one
        # max_step to reach the plateau the votes keep naming -- mp5 took its -45 ms at chart +51 s
        # of a 111 s chart and then sat there while every later vote still read -133 ms -- so once
        # earned the window stays open, and what bounds it is the *side*: the correction already
        # taken points one way, and a vote claiming more than SMALL_MOVE_MS the other way is mp4's
        # +139 ms plateau (whose result page read SLOW), not a drift. The target is clamped to
        # max_corr (120 ms), so however many plateaus the window sees it walks at most that far.
        opened = self.open_trust and self._open_doubt
        # The side rule is part of the 多人 window, so it is scoped to `open_trust` and nowhere else:
        # on a single-player round the push cap is the *sanctioned* way to spend a vote back (a +40 ms
        # pair with a +10 ms cap must commit +10 -- pushcap PART 1), and a rule that overrode the cap
        # would be a second, hidden cap. In 多人 the later plateaus are aliases of the lock we already
        # corrected (mp4's +139 ms against a -45 ms correction, on a page that read SLOW), so there the
        # side is the bound and the cap is not.
        opposing = (self.open_trust and self.committed > 0
                    and (raw > 0.0) != (self.corr > 0.0)
                    and abs(raw) * 1000.0 > SMALL_MOVE_MS)
        # How big a claim this pair is making decides how much evidence it needs (see VOTE_MARGIN).
        # While the opening lock is doubted the pair is allowed the small margin too: the run is
        # demonstrably playing on a wrong clock, and the plateaus that name the error are long
        # (0056_03 held -155 ms for twelve votes) even when their peak-to-runner edge is thin --
        # waiting for the big margin there is what pushed the fix out to chart +75.9 s of a 101 s
        # chart. Off a doubted opening this can only move the clock toward the rail's own cap.
        need = (VOTE_MARGIN if (abs(target) * 1000.0 <= SMALL_MOVE_MS or opened)
                else VOTE_MARGIN_BIG)
        # ... and while it is doubted the pair may also step over a single noisy vote. The 多人
        # field is thin (mp5's plateau votes ran edges of 1-2 against peaks of 11-18) and a lone
        # +28 ms draw between two -130 ms plateau votes reset the run every time -- that, not the
        # margin, is what kept mp5's fix out to chart +51 s. Pairing against either of the last two
        # is still two votes agreeing within 15 ms, and the margin, the rail, the side rule and the
        # clamp are all untouched; the extra slot only exists while `opened`, i.e. only on a run
        # whose opening lock is already known to be wrong.
        paired = (self._agree is not None and abs(v - self._agree) <= 0.015) or \
                 (opened and self._agree2 is not None and abs(v - self._agree2) <= 0.015)
        if paired and peak - runner >= need:
            if abs(target) * 1000.0 > CORR_TRUST_MS and not opened:
                # The staircase alias VOTE_MARGIN does not always catch: the window agrees with
                # itself and wins by a margin while pointing past any drift the corpus ever showed
                # (g458: 12 votes to 9 at -163 ms, on a section whose taps are 157 ms apart).
                self.refused += 1
                self.refused_ms.append(target * 1000.0)
                self.log(f"  live re-anchor: two votes agree on {raw * 1000:+.0f} ms, but "
                         f"{target * 1000:+.0f} ms is past the trusted drift "
                         f"({CORR_TRUST_MS:.0f} ms) -> refused "
                         f"({peak} votes from {len(self.dets)} blobs)")
            elif opposing:
                # Only reachable in 多人 with a correction already in place: it went this clock's way
                # (all three 多人 rounds' result pages read SLOW) and this vote wants to spend it back.
                # Keep the correction and say so.
                self.refused += 1
                self.refused_ms.append(target * 1000.0)
                self.log(f"  live re-anchor: vote reads {raw * 1000:+.0f} ms against the "
                         f"{self.corr * 1000:+.0f} ms the opening window already took -> kept "
                         f"({peak} votes from {len(self.dets)} blobs)")
            elif abs(target - self.corr) < self.deadband:
                # Two different reasons land here and they read differently: a vote inside the
                # deadband of where the clock already is is the vote agreeing with us, while a vote
                # past the ceiling is the panel's 正推上限 doing its job. At 0 ms every late-looking
                # field takes the second path, and calling that "deadband" sends a reader hunting for
                # votes that never agree.
                why = (f"正推上限 +{self.max_corr_up * 1000:.0f} ms 已封"
                       if raw > self.max_corr_up else "inside deadband")
                self.log(f"  live re-anchor: voted {v - self.ref:+.3f}s "
                         f"({peak} votes from {len(self.dets)} blobs) - {why}, kept")
            else:
                if raw > self.max_corr_up:
                    self.log(f"  live re-anchor: vote wanted {raw * 1000:+.0f} ms of push, "
                             f"capped at +{self.max_corr_up * 1000:.0f} ms")
                if abs(target) * 1000.0 > CORR_TRUST_MS:
                    # Only reachable with the rail opened: say so, so the log never shows a big
                    # correction appearing without the reason it was allowed through.
                    self.log(f"  live re-anchor: opening lock was already doubted -> taking "
                             f"{target * 1000:+.0f} ms past the trusted drift "
                             f"({CORR_TRUST_MS:.0f} ms) "
                             f"({peak} votes from {len(self.dets)} blobs)")
                self.corr += max(-self.max_step, min(self.max_step, target - self.corr))
                self.committed += 1
                self.log(f"  live re-anchor: two votes agree -> correction "
                         f"{self.corr * 1000:+.0f} ms on the remaining presses "
                         f"({peak} votes from {len(self.dets)} blobs)")
            self.dets = []
            self._n_voted = 0
            self._agree = None
            self._agree2 = None
        else:
            self._agree2 = self._agree
            self._agree = v


def play(hits, inj, log, vote=None, field_seen=None, offset=0.0, pre=20.0, hold=45.0,
         judge_y=JUDGE_Y, flick_dx=90, flick_dy=0, anchor=True, anchor_deadline=90.0,
         delay=5.0, min_votes=7, shotgun=True, watch=None, dump=None, t0_fixed=None, stop=None,
         late_fail=False, push_cap=LIVE_PUSH_MS, kind_lead=None, vote_sink=None, events=None,
         open_trust=False, status=None):
    """Anchor if asked, then fire `hits` through an injector the caller owns.

    The injector is never opened or closed here: run.py walks the menus with the same one it
    plays the song with, and handing over a live socket instead of spawning a second process is
    what buys back the ~3 s of interpreter start, imports and minitouch launch that the anchor
    would otherwise spend before its first frame.

    `vote` is the chart the anchor matches against -- the whole song even when `hits` is a
    truncated trial burst, because a vote that can only name the first twelve notes will happily
    identify the frame as note 300 and fire everything 30 seconds early.

    `field_seen` is the host time the caller saw the LIVE field appear. The audio starts a second
    or so after that, which bounds the search: the chart has repeated sections, and an alignment
    onto the wrong repeat is a real contender for the vote's plurality.

    `shotgun` adds the intro rescue: the opening taps are pressed at both leading alignments by a
    helper thread while the vote is still deciding, because on this chart it provably cannot
    decide before they are due (see _IntroShotgun). Turn it off to measure the raw vote.

    `stop`, when given, is polled inside the fire loop's idle wait, and the first truthy return
    (a dict naming the judgement that ended the attempt) drops the remaining actions, lifts every
    finger and returns ABORTED. It exists for run.py's --retry-on-break; armed, the wait's single
    sleep is capped at 100 ms so a long idle section cannot delay the check by seconds, and
    unarmed the loop keeps its original shape and timing exactly.

    `late_fail`, armed by the same switch, turns a fence that found the first presses already
    past (a restart born late: the song was running while the lock was still being voted) into an
    immediate ABORTED instead of a play-through -- the intro notes were auto-missed before the
    first press could go out and firing the rest of the song would only burn it. The stop it
    installs fires at the first target still ahead, so only kept-but-already-due presses go out.

    `push_cap` bounds how far the live corrector may move the remaining presses later, in ms;
    LiveCorrector says why that side is capped tighter than the other. 120 makes it symmetric.

    `status`, when given, is called with the same numbers the every-400-actions log line prints
    (`progress`, `actions`, `corr`, `late`, `left`) so the panel can show them on its 「本局」
    strip without parsing prose -- the log line is for the record, this is for the display, and
    a panel that reads the display must not have to regex a Chinese sentence to get it.
    """
    notes = [(h["t_ms"] / 1000.0, h["lane"]) for h in (vote or hits)]
    t0 = None
    fired = {}
    if t0_fixed is not None:
        # The restart anchor: the caller pressed 确定 on the 重试 confirmation and clocked it, so
        # t0 is one calibrated constant away -- no vote, no shotgun, nothing waits on the intro.
        # The fence further down still runs: it says whether a press is already overdue at this t0.
        t0 = t0_fixed
        now = time.perf_counter()
        log(f"restart anchor: t0={t0:.3f} given, note 1 due in {t0 + notes[0][0] - now:+.3f}s")
        if not inj.probe():
            log(f"  !! channel had to be re-established before the run ({inj.respawns} respawns)")
    elif anchor:
        shot = None
        if shotgun:
            targets = []
            for i, h in enumerate(hits):
                if h["t_ms"] > INTRO_MS:
                    continue
                # The same per-kind lead the fire loop applies, or the intro would be pressed on a
                # different clock from the rest of the song.
                lead = (kind_lead or {}).get(h["kind"], 0.0)
                if h["kind"] == "tap":
                    targets.append((i, [(h["t_ms"] - lead, h["x"])],
                                    h["t_ms"] - lead - pre + hold))
                elif h["kind"] == "long":
                    # The whole path: the fire loop is not the only thing that can slide a long,
                    # and the opening longs are exactly the ones the lock can arrive too late for.
                    targets.append((i, [(p["t_ms"] - lead, p["x"]) for p in h["path"]],
                                    max(h["end_ms"] + TAIL_MARGIN_MS - lead,
                                        h["t_ms"] - lead - pre + MIN_HOLD_MS)))
            if targets:
                shot = _IntroShotgun(inj, targets, pre, hold, judge_y, log, offset)
                shot.start()

        def vote(seconds, lo, hi, tag, **kw):
            mv = kw.pop("min_votes", min_votes)
            log(f"anchoring: voting {len(notes)} chart notes against the field"
                + (f" in [{lo:.1f}, {hi:.1f}]" if lo is not None else "")
                + (f" ({tag})" if tag else ""))
            return anchor_vote(frames, notes, seconds=seconds, min_votes=mv,
                               judge_y=judge_y, lo=lo, hi=hi, log=log,
                               on_vote=shot.align if shot else None,
                               # The sprite feed, not the tap mask. Until 2026-10-07 this loop
                               # asked for `note_blobs`, and that feed can only see notes a tap blob
                               # covers -- so a chart whose opening is long/trace notes votes on
                               # nothing at all for seconds. 0056_03 opens with eight of them
                               # (first note long at 2.356 s, no tap before it): replayed through
                               # the shipped detector over our_survival_open_0930 the tap feed cast
                               # its first vote at chart +5.51 s and locked at +6.30 s, 3.2 s after
                               # the first press was due -- exactly the opening g291-g295 lost, and
                               # the reason they only came back through a restart. The same frames
                               # on `sprite_blobs` vote at +1.12 s and lock at +1.65 s, -10.5 ms,
                               # 0.64 s *before* that press. sprite_blobs is note_blobs plus the
                               # judged sprites the tap blob does not cover, so no tap evidence is
                               # dropped; the relock has voted this way since it was written (99
                               # recorded locks, every one of them inside its own window).
                               # freshfeed.py PART 6 pins this and the tap feed as its control.
                               blobber=sprite_blobs, **kw)

        def stop_shot():
            nonlocal fired
            fired = shot.stop()
            n = sum(len(v) for v in fired.values())
            if n:
                log(f"  intro shotgun: {n} presses on {len(fired)} notes "
                    f"while the vote was deciding")

        try:
            if field_seen is not None:
                # The audio starts about the moment the field is painted -- on 焚音打's own
                # recording the field is up 0.17 s before t0 -- and host detection can only be
                # late, so t0 lives in a window barely wider than the detection lag. That matters
                # more than it sounds: with a +-6 s window the early votes sat on section aliases
                # 2.5 s and 5 s away (t02: three votes in a row, peak 17:15 and 21:20, both
                # wrong) and the first true answer only arrived with the 66th blob, chart +4.2 s,
                # four intro notes gone. Squeezed to this window the same eleven blobs vote 7:0,
                # err +0.02 s -- and the vote floor can drop with it: the tight window is what
                # makes a five-blob vote trustworthy. A run where the field is painted unusually
                # late (or detection unusually early) finds nothing in here and falls through to
                # the wide fallback below, exactly as before. min_dets is three, not five: the
                # shotgun only hears votes this loop has already answered, and its confirming
                # pair has to land by chart +2.53 to schedule the opening chord due at +2.56 --
                # five blobs pushed the first answer past +3.7 on the screencap clock, which is
                # where t03's opening three notes went. Acceptance below still demands the
                # five-vote peak; the floor only says when the histogram is worth a first look.
                # 2026-10-07: -2.0 was still too wide. 0056_03 carries a self-similar alignment
                # 1.88 s before the truth -- g453 locked at field-1.813 and g454 at -1.830, both
                # with the first four notes already gone (386 and 373 MISS) -- and its three votes
                # agree to 16 ms, so peak>=5 and peak>=second+1 both cleared at chart +1.6/+1.7 s,
                # before the true alignment had the 18-19 blobs it needs (it appears at +1.9 s;
                # the two runs that locked correctly, g452 and g455, sat at field+0.066/+0.145 with
                # 43-44 blobs). Chart 0 cannot precede the moment the LIVE is entered, so the lower
                # bound only has to clear the field stamp's own lag, and -1.2 is set by both ends:
                # a stamp 0.73 s *after* t0 still has to fall inside (the archive's own +0.332 s
                # stamp plus the probe's worst 0.4 s sweep) while the 1.88 s alias has to stay out
                # with room to spare. margin goes 1 -> 3 with it: both aliases won by 2, the two
                # true locks by 6 (g452, 23:17) and 3 (g455, 28:25), and a narrower window shrinks
                # the runner-up anyway.
                t0, dets = vote(12.0, field_seen - 1.2, field_seen + 0.6, "tight",
                                stable=2, margin=3, min_votes=5, min_dets=3)
                if t0 is None:
                    t0, d2 = vote(max(anchor_deadline - 12.0, 10.0), field_seen - 5.0,
                                  field_seen + 30.0, "wide fallback")
                    dets.extend(d2)
            else:
                t0, dets = vote(anchor_deadline, None, None, "")
        finally:
            # Only the failure path stops the thread here. On success it has to stay alive until
            # the lock probe has come back: this chart's vote locks at +6.7-6.8 s, past the presses
            # already scheduled for the next intro tap, and the probe's ~300 ms round trip is
            # exactly the window those presses are still due in. Killing the thread at the vote
            # return is what lost one note in a31 and a32 ("1 lost, 1 rescued") and nothing in
            # a29/a30, whose locks came 100-200 ms earlier.
            if shot is not None and t0 is None:
                stop_shot()
        if dump is not None:
            # The raw blobs of the vote that actually locked: without them a run that locks on a
            # different clock than its recording says is undiagnosable (t03 voted on a histogram
            # whose shape only the blobs themselves can explain).
            json.dump({"dets": dets, "notes": notes, "field_seen": field_seen, "t0": t0},
                      open(dump, "w", encoding="utf-8"))
            log(f"vote blobs -> {dump}")
        if t0 is None:
            # Without the raw blobs a failed vote is unrepeatable: the same 30 s of frames have to
            # be re-recorded to see which alignment won and why it was rejected.
            json.dump({"dets": dets, "notes": notes},
                      open(f"{subdir(RUNS)}/anchor_dets.json", "w", encoding="utf-8"))
            log(f"anchor failed after {len(dets)} blobs, dets -> {RUNS}/anchor_dets.json")
            return 1
        if watch is not None:
            watch.dets.extend(dets)          # the intro is the part a drift curve needs most
        now = time.perf_counter()
        log(f"locked at chart {(now - t0):+.3f}s from {len(dets)} blobs, "
            f"{(now - t0) - notes[0][0]:+.3f}s after note 1")
        if not inj.probe():
            log(f"  !! channel had to be re-established after the anchor "
                f"({inj.respawns} respawns)")
        # The fence below counts the shotgun's presses as coverage, so the thread only dies after
        # the one step that could still race a press it has scheduled.
        if shot is not None:
            stop_shot()
    if t0 is not None:
        t0 -= offset / 1000.0
        # Printed absolute so a capture in another process can be lined up against the song: the
        # chart time of any frame is its perf_counter stamp minus this number.
        log(f"fire t0={t0:.3f} (offset {offset:+.0f} ms)")
        # The fence is on the press, not on the note: a note is judged when its press lands, and
        # the press is scheduled `pre` ms early, so a lock that lands 40 ms before note 1 still
        # leaves its press target in the future -- a27 skipped note 1 with that target 18 ms away,
        # and a per-note fence on the note time threw it away. A note whose press is already past
        # is only truly lost if the shotgun did not cover it (a fired press within wobble distance
        # of where the note's press belongs at the locked t0); everything else keeps its slot --
        # the fire loop presses overdue targets on the spot, so the worst a kept note costs is a
        # late-but-kept judgement where the skip it replaces was a MISS.
        now = time.perf_counter()
        keep, covered, lost, wobble = [], 0, [], 0.0
        for i, h in enumerate(hits):
            press = t0 + (h["t_ms"] - pre) / 1000.0
            fs = fired.get(i, ())
            d = min((abs(f - press) for f in fs), default=None)
            if d is not None and d <= 0.12:
                covered += 1
                wobble = max(wobble, d)
            elif press > now - 0.08:
                keep.append(i)
            else:
                lost.append(i + 1)
        if not keep:
            log("the vote landed on the end of the song - nothing left to fire")
            return 1
        if lost and late_fail:
            # A restart born late (t92: the minitouch rebuild ate the [確定 -> note 1] budget on
            # two attempts) can never be FC/AP, so with --retry-on-break armed the fence turns
            # into an immediate ABORTED instead of three wasted minutes. Swapping `stop` for a
            # closure keeps the exit on the fire loop's existing abort path: the first target
            # still ahead polls the stop and breaks before it fires, and only the kept-but-
            # already-due targets (a press or two in a born-dead restart) go out on the spot.
            late_fail_hit = {"row": "LATE", "lo": now, "hi": now}
            log(f"  !! {len(lost)} note(s) already past at this lock "
                f"(note {lost[0]} first) - 出生即废（重开晚到），不发剩余动作直接重试")
            def _late():
                return late_fail_hit
            stop = _late
        elif lost:
            log(f"  !! {len(lost)} note(s) lost before the lock could press them {lost}"
                + (f", {covered} rescued by the shotgun" if covered else "")
                + ", this run cannot be FC")
        elif covered:
            # The wobble is the distance from the shotgun press to where the locked t0 puts it:
            # it should read a couple of ms, which is what says the press is on the same clock as
            # the fire loop rather than the raw vote value (a29: 56 ms, its only GREAT).
            log(f"  the shotgun had already pressed the first {covered} notes of the intro"
                + (f", worst {wobble * 1000:.0f} ms off the locked press" if wobble else ""))
        late = [i for i in keep if t0 + (hits[i]["t_ms"] - pre) / 1000.0 < now]
        if late:
            log(f"  !! {len(late)} note(s) already due at the lock (note {late[0] + 1} first), "
                f"pressed on the spot, this run cannot be AP")
        hits = [hits[i] for i in keep]
    else:
        # Same convention: t0 is the host time of chart t = -offset, so a positive offset fires early.
        t0 = time.perf_counter() + delay - offset / 1000.0
        log(f"t0 in {delay:.1f}s (fire at hit.t - {offset} ms, - {pre} ms press)")

    actions, nslots = build_actions(hits, judge_y, pre, hold, flick_dx, flick_dy, kind_lead)
    if any(v for v in (kind_lead or {}).values()):
        # Said out loud because it changes where every press of that kind sits, and a run that was
        # played with a lead has to be readable as such later.
        log("  种类偏移: " + " ".join(f"{k}{v:+g}ms" for k, v in sorted((kind_lead or {}).items())
                                    if v) + "（整段一起移：头、每一步、尾）")
    log(f"{len(hits)} notes -> {len(actions)} actions on {nslots} slots")
    over = [a for a in actions if a[3] != field_x(a[3], a[4])]
    if over:
        log(f"  !! {len(over)} 个路径点越出场界（x 最大 {max(a[3] for a in over):.0f}），"
            f"已夹到场上边缘：曲内 +{min(a[0] for a in over) / 1000:.1f}s 起")
    # Mid-song drift probes, on their own thread so the press clock stays owned by the loop: a31
    # and a32 both turned everything after ~40% of the song into BAD/MISS SLOW while the host
    # schedule held 0.5 ms, and only frames taken during play can say whether the notes moved
    # with the stall or only the presses did. The halves are voted again offline once the song
    # is over, and every frame now also feeds the live corrector -- the probes stopped being
    # diagnostics the moment the clock they measure could still be fixed mid-song.
    probes = []
    probe_stop = threading.Event()
    ref = t0 + offset / 1000.0
    live = LiveCorrector(notes, ref, log, max_corr_up=push_cap / 1000.0,
                         open_trust=open_trust)

    def _probe_loop():
        wait = 0.8            # early and often: the first commit is worth the most
        last_key = None
        dupes = 0
        while not probe_stop.wait(wait):
            try:
                t, img = frames()
            except Exception:                                # noqa: BLE001
                return
            key = frame_key(img)
            if key == last_key:
                # The same buffer, handed back again. `note_blobs` would run over it again (11.9 ms
                # of a 9 ms budget at the renderer's cadence), `live.dets` would grow junk that every
                # vote re-histograms, and the offline replay corpus in `probes` would carry the same
                # instant twice as often as it carries the next one. Refuse it here, where a frame
                # costs something, rather than downstream where it has to be noticed as a tie.
                dupes += 1
                if dupes == 1:
                    log("  !! drift probe: 捕获交回的是上一帧，未喂给修正器（连续重复开始）")
                wait = min(wait, 0.2)        # ask again promptly; a stall should not cost a whole cycle
                continue
            if dupes:
                log(f"  drift probe: 重复帧 {dupes} 张未计，采样恢复")
                dupes = 0
            last_key = key
            blobs = note_blobs(img)
            probes.append((t, blobs))
            live.feed(t, blobs)
            log(f"  drift probe at chart +{t - ref:.1f}s, {len(blobs)} blobs")
            wait = 8.0 if live.committed else 1.5

    if watch is None:
        threading.Thread(target=_probe_loop, daemon=True).start()
    # The chart's own event table, on the wall clock: skill points, fever windows, tempo changes.
    # Read by run.py from the raw chart and handed over as (chart_ms, text); logged the moment the
    # judgement clock reaches them, so the log lines up with the breaks and the effect bursts
    # instead of being reconstructed afterwards. Never a gate -- a missing table just means no
    # lines.
    ev_stop = threading.Event()
    if events:
        def _event_loop():
            for ms, text in events:
                if ev_stop.wait(max(0.0, t0 + ms / 1000.0 - time.perf_counter())):
                    return
                log(f"  {text} @chart +{ms / 1000.0:.1f}s")
        threading.Thread(target=_event_loop, daemon=True).start()
    late = []
    stalls = []                   # (index, chart_ms, ms late) over STALL_MS -- see the summary
    fired = 0
    aborted = None
    fired_log = []
    # 面板「预计还剩」的参照点：末一个动作的曲内时刻。拿曲长算会差一截 —— 截断试发
    # （`--min-fire`）的那些动作本来就不在末尾。
    tm_last = actions[-1][0] if actions else 0.0
    slot_corr = [None] * nslots
    grp_tm, grp_corr = None, 0.0
    last_cmd, last_echo = inj.cmds, inj.echoes
    for tm, op, slot, x, y in actions:
        # `offset` is already folded into t0, so applying it here too would cancel it out and
        # make the flag a no-op, which is exactly what an entire calibration sweep missed.
        # The live correction rides on top, latched per gesture: a commit landing between a
        # flick's two 45 px steps would stretch or crush their 14 ms spacing, and the spacing
        # is the shape.
        if op == "down":
            # ... and one more time across heads: compile.py puts PAIR_DESYNC_MS between two bars
            # whose coincident heads would otherwise share an input frame (0050_03's side-by-side
            # pair at 7.077 s, 真夜中遊園地's crossing apex), and a commit landing inside that gap
            # cancels the desync -- g064's -20 ms arrived between the two downs, pulled the second
            # back onto the first's frame, and the left bar came back "0ms MISS" as if nothing had
            # been fixed. Members of a group therefore inherit the correction the group started on.
            if grp_tm is not None and 0 < tm - grp_tm <= CHORD_GROUP_MS:
                slot_corr[slot] = grp_corr
            else:
                slot_corr[slot] = grp_corr = live.corr
            grp_tm = tm
        target = t0 + tm / 1000.0 + (slot_corr[slot] if slot_corr[slot] is not None
                                     else live.corr)
        while True:
            rem = target - time.perf_counter()
            if rem <= 0:
                break
            if stop is not None:
                # --retry-on-break's poll. Checked before the sleep below, which is capped at
                # 100 ms only while stop is armed, so a long idle section cannot delay the check
                # by seconds; unarmed the loop keeps its single-sleep shape exactly.
                aborted = stop()
                if aborted is not None:
                    break
            if watch is not None and rem > 0.09:
                # Idle time between actions is free, and 2739 actions over 88 s leaves most of the
                # song unobserved. Using it to keep recording blobs is what makes a drift curve
                # measurable without a second pass, and without a thread that can preempt a press.
                watch(rem - 0.05)
                continue
            if rem > 0.003:
                time.sleep(min(rem - 0.002, 0.1) if stop is not None else rem - 0.002)
        if aborted is not None:
            break
        t_now = time.perf_counter()
        dt_ms = (t_now - target) * 1000.0
        late.append(dt_ms)
        if dt_ms > STALL_MS:
            # Named while it happens, not only in the summary: 强制终止 is a TerminateProcess, so a
            # round killed for its MISS flood never reaches the end of this function. `gc.get_count()`
            # is (gen0, gen1, gen2) since the last collection -- a big gen2 number next to a spike is
            # the collector's signature, whereas a spike with the counters flat is the host starving
            # us (another probe on the machine, the emulator hitching, the OS scheduler).
            stalls.append((fired, tm, dt_ms))
            if len(stalls) <= STALL_LOG_MAX:
                log(f"  !! 迟发 {dt_ms:+.1f} ms @action {fired} chart +{tm / 1000.0:.1f}s  "
                    f"gc {gc.get_count()}")
        rx, ry = to_raw("MEASURED", field_x(x, y), y)
        if op == "down":
            inj.touch_down(slot, rx, ry, slot + 1)
        elif op == "move":
            inj.touch_move(slot, rx, ry)
        else:
            inj.touch_up(slot)
        if op == "up":
            slot_corr[slot] = None
        fired += 1
        if fired % 400 == 0:
            # Every 400 actions, on the log rather than only at the end: the panel's 强制终止 is a
            # TerminateProcess, so nothing after the loop survives a bounded test, and a run that
            # is being killed for its MISS flood has to have already said whether the presses went
            # out on time and whether the field still agrees with the clock.
            #
            # `cmd`/`echo` are deltas over the window, not levels: sendall only proves the bytes
            # reached the TCP buffer, so the pair that matters is how many lines the host wrote
            # against how many the device echoed back in the same span. Equal rates mean the queue
            # is draining; echo falling behind is a fixed t0 cannot hold, and every note past the
            # backlog misses while the scheduler still reports 0.00 ms.
            w = sorted(late[-400:])
            nv = "     none" if live.last_vote is None else f"{live.last_vote * 1000:+6.0f}"
            dev = inj.clock_offset_ms()
            dv = "  none" if dev is None else f"{dev:+7.0f}"
            log(f"  fire {fired}/{len(actions)} @chart {t_now - t0:+5.1f}s  "
                f"late p50 {w[len(w) // 2]:+5.1f} max {w[-1]:+6.1f} ms  "
                f"stalls {len(stalls)}  "
                f"vote {nv} ms corr {live.corr * 1000:+4.0f} ms  "
                f"cmd +{inj.cmds - last_cmd} echo +{inj.echoes - last_echo} dev {dv} ms  "
                f"respawns {inj.respawns}")
            last_cmd, last_echo = inj.cmds, inj.echoes
            if status is not None:
                # 面板「本局」读数带：与上面那行日志是同一批数字，但走机器通道（`#STATUS#`）——
                # 界面不该靠正则化一句中文来取数。`left` 是曲内还剩多少**秒**。
                status(progress=f"{fired / len(actions):.3f}",
                       actions=f"{fired}/{len(actions)}",
                       corr=f"{live.corr * 1000:+.0f}",
                       late=f"{w[len(w) // 2]:+.1f}",
                       left=f"{max(0.0, (tm_last - tm) / 1000.0):.0f}")
        # target/actual in host seconds, for joining against hud-watch judgement stamps: when a
        # flick comes back BAD, the question is which touch the game credited, and the answer is
        # a subtraction, not a reconstruction.
        fired_log.append((round(target, 3), round(t_now, 3), op, slot, x, y))
    # Report before the cleanup can also fail: a run that died at action 800 of 2737 looks
    # exactly like a run with bad timing unless the count is printed.
    probe_stop.set()
    ev_stop.set()
    log(f"fired {fired}/{len(actions)} actions, {inj.respawns} injector respawns")
    if status is not None:
        # 收尾那一下：进度轨要走满（没走满的只有被中止的那些，进度就停在那儿 —— 那正是实情）。
        status(progress=f"{fired / len(actions):.3f}" if actions else "1.000",
               actions=f"{fired}/{len(actions)}", left="0")
    if vote_sink is not None:
        # The attempt's own votes, back to whoever is deciding whether to restart it. A retry
        # that only replays the clock cannot fix a systematic offset, and the votes are the only
        # place that offset is written down.
        vote_sink["votes"] = list(live.votes)
    if aborted is not None:
        # The attempt is dead where it stands: run.py pauses the live, 重试s it back to t=0 and
        # fires again, so nobody reads this attempt's counters -- the log line naming the
        # judgement (with its chart time) plus the parked dump are the abort's whole evidence.
        if aborted.get("row") == "LATE":
            log(f"  !! 出生即废 @host {aborted['lo']:.3f} = chart +{aborted['lo'] - t0:.1f}s "
                f"，停发剩余 {len(actions) - fired} 个动作，松手离场")
        else:
            log(f"  !! 断键（{aborted['row']}）@host {aborted['lo']:.3f} = chart "
                f"+{aborted['lo'] - t0:.1f}s，停发剩余 {len(actions) - fired} 个动作，松手离场")
    if dump is not None:
        out = {"t0": t0, "offset": offset, "fired": fired_log,
               "notes": [(h["t_ms"] / 1000.0, h["lane"]) for h in hits]}
        # Which rail set this round ran under. A 多人 round is replayed by votereplay under both
        # halves of its contract, and until 2026-10-08 the only way to tell one apart was a list of
        # tags inside the probe -- so every new 多人 round made that probe fail until it was edited.
        # The dump now says so itself; the tag list stays as the fallback for the older dumps.
        out["open_trust"] = bool(open_trust)
        if aborted is not None:
            # The parked dump is the abort's evidence: the fired log up to the stop plus the
            # judgement that ended it, which is what says whether the hint can be trusted.
            out["aborted"] = aborted
        if watch is not None:
            out["dets"] = watch.dets
        elif probes:
            # The probe thread's own frames. Until now they were only ever reduced to the two
            # half-song votes printed below and then dropped, which is why 86 recent dumps carry
            # 270k fired actions and not one blob: no offline re-vote of a finished run was
            # possible. Stamped frames, rounded to a tenth of a pixel -- the vote's own tolerance
            # is 2.5 lanes, so this loses nothing it could see.
            out["probes"] = [[round(t, 3), [[round(y, 1), round(x, 1)] for y, x in blobs]]
                             for t, blobs in probes]
        json.dump(out, open(dump, "w", encoding="utf-8"))
        log(f"  {len(fired_log)} fired actions"
            + (f" and {len(watch.dets)} blobs" if watch is not None else
               f" and {len(probes)} probe frames" if probes else "")
            + f" -> {dump}")
    if aborted is None and len(probes) >= 4:
        half = len(probes) // 2
        log(f"  drift probes: {len(probes)} frames during play, voted against the effective "
            f"clock (+ is notes late, presses land SLOW)")
        for name, part in (("first", probes[:half]), ("second", probes[half:])):
            dets = [(t, y, x) for t, blobs in part for y, x in blobs]
            if not dets:
                log(f"    {name} half: no blobs")
                continue
            # +-0.28 s keeps the chart's repeated-section aliases (the intro family sits at
            # +-0.316 s) out of the band: an alias vote would read as a 316 ms stall. The band
            # rides the live correction, because what a corrected run still wants to know is
            # its residual -- a probe voted against the raw ref would just report the
            # correction back.
            v, peak = vote_t0(dets, notes, lo=ref + live.corr - 0.28,
                              hi=ref + live.corr + 0.28)[:2]
            if v is None:
                log(f"    {name} half: no alignment from {len(dets)} blobs")
            else:
                log(f"    {name} half: notes {v - ref - live.corr:+.3f}s vs the effective clock "
                    f"({peak} votes from {len(dets)} blobs)")
        if live.committed or live.refused:
            log(f"  live re-anchor: {live.committed} correction(s) applied, "
                f"final {live.corr * 1000:+.0f} ms"
                + (f", {live.refused} refused as aliases" if live.refused else ""))
    # Every finger this loop pressed has to come off the glass before it returns, whatever path it
    # returns by. The lift used to be a bare loop after the fire loop, so an exception from the
    # injector (`MTouch.send` raises "minitouch socket will not accept commands" once its three
    # repairs are spent, and `to_raw` raises on an out-of-bounds point) skipped it entirely and left
    # a contact down for the rest of the round and the walk after it -- the device keeps MT state
    # across processes, and the next round then enters a LIVE with a phantom finger. Each lift is
    # individually guarded, because the failure mode being handled is "the channel is already
    # broken": letting the first exception escape the `finally` would skip the remaining slots.
    try:
        for s in range(nslots):
            try:
                inj.touch_up(s)
            except Exception as e:                              # noqa: BLE001
                log(f"  !! 松手失败 slot {s}：{e!r}")
        try:
            inj.release_all()                                   # the daemon's own blanket reset
        except Exception as e:                                  # noqa: BLE001
            log(f"  !! release_all 失败：{e!r}")
    except Exception as e:                                      # noqa: BLE001
        log(f"  !! 收尾松手出错：{e!r}")
    if late:
        late.sort()
        n = len(late)
        log(f"schedule error: min {late[0]:.2f} p50 {late[n // 2]:.2f} "
            f"p99 {late[int(n * 0.99)]:.2f} max {late[-1]:.2f} ms")
    if stalls:
        worst = max(stalls, key=lambda s: s[2])
        log(f"迟发 > {STALL_MS:.0f} ms 的动作 {len(stalls)} 个，最坏 {worst[2]:+.1f} ms "
            f"@action {worst[0]} chart +{worst[1] / 1000.0:.1f}s"
            + ("（只有前 %d 个逐条记过）" % STALL_LOG_MAX if len(stalls) > STALL_LOG_MAX else ""))
    return ABORTED if aborted is not None else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hits")
    ap.add_argument("--offset", type=float, default=0.0, help="ms added to every hit")
    ap.add_argument("--pre", type=float, default=20.0, help="press this many ms before the note")
    ap.add_argument("--hold", type=float, default=45.0)
    ap.add_argument("--judge-y", type=float, default=JUDGE_Y)
    ap.add_argument("--flick-dx", type=int, default=90)
    ap.add_argument("--flick-dy", type=int, default=0)
    ap.add_argument("--delay", type=float, default=5.0, help="seconds from start to t0")
    ap.add_argument("--anchor", action="store_true", help="derive t0 by voting every note in view")
    ap.add_argument("--anchor-deadline", type=float, default=45.0, help="seconds to give the anchor")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    all_hits = json.load(open(args.hits, encoding="utf-8"))
    hits = all_hits[: args.limit] if args.limit else all_hits
    if args.dry:
        actions, nslots = build_actions(hits, args.judge_y, args.pre, args.hold,
                                         args.flick_dx, args.flick_dy)
        print(f"{len(hits)} notes -> {len(actions)} actions on {nslots} slots")
        for a in actions[:12]:
            print("  ", a)
        return

    raise_timer_resolution()

    def log(m):
        print(m, flush=True)

    # Opened before anchoring, not after: the anchor can take tens of seconds and a writer
    # created in the last half-second before note one would still be starting up.
    inj = MTouch()
    try:
        sys.exit(play(hits, inj, log, vote=all_hits, offset=args.offset, pre=args.pre,
                      hold=args.hold,
                      judge_y=args.judge_y, flick_dx=args.flick_dx, flick_dy=args.flick_dy,
                      anchor=args.anchor, anchor_deadline=args.anchor_deadline,
                      delay=args.delay))
    finally:
        inj.close()


if __name__ == "__main__":
    main()
