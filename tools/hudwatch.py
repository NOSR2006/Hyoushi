"""Stamp every non-PERFECT judgement off the field HUD, live, while the run plays.

The result page totals the judgements but not their moments; a run that ends with eight BADs and a
handful of candidate flick notes cannot be repaired from the totals alone. The field HUD draws
PERFECT..MISS as live 4-digit counters (leading zeros drawn dim), and under the restart anchor all
five start at 0, so the frame a row's digits change is the frame that judgement landed on.

The rows are read by pixel diff, not OCR, and a diff alone is not evidence: the note-hit sparkles
drift across the counter column, and a sparkle that happens to sit still for one frame looks
exactly like a digit that just advanced. That was enough to cost a healthy run on 2026-09-30 -- the
log claimed GREAT 7 / GOOD 7 / BAD 5 / MISS 4 while the game's own counters read 0, and someone
reading the log believed it. So a candidate has to clear five gates.

Gate one is persistence: the new pixels must **hold still** for HOLD seconds. A digit stays put
between judgements, a sparkle keeps moving and gets dropped. The timestamp is still taken from the
frame where the change first appeared, so this costs precision nothing. It is not sufficient on its
own -- in a dense section an effect can park on a row for longer than HOLD.

Gate two is the counter itself. The thread remembers, per row, the digit box as it last saw it
settled; a tick is only reported if the box has actually changed since then. This is what kills the
remaining class: a sparkle that crosses the window registers as a change on the way in *and* on the
way out, and the frame it settles on is the clean one, so the diff against the previous frame fires
while the diff against the settled state is zero. Measured over the candidates this thread has ever
committed (research/hud_<tag>_<row><n>.png, each one a frame that passed gate one): replayed in
commit order, gate two keeps 27 of 393 and rejects 366, and the separation is wide - real carries
move 9-228 pixels of the box, rejected candidates move 0-1.

Gate two has a memory of its own to distrust, though: the settled snapshot is initialised from one
frame, and that frame is the HUD's slide-in right after 確定, which effects can be sitting on. A
baseline captured under an overlay makes every later *clean* frame look like a change. s03
(2026-09-30, anima EXPERT, bounded) committed a GREAT tick whose box was pixel-identical to the
all-zeros counter of an unrelated run, and twelve more states were absorbed by the re-baseline below
instead of being reported. So the run's true zero appearance is kept separately, as the per-pixel
minimum brightness ever seen in that box (gate three): a minimum cannot be raised by an overlay, and
under the restart anchor the counters genuinely start at 0000, so it converges on the all-zeros
pattern within a frame or two and stays there. A settle that still matches it reports nothing,
however far it sits from the remembered baseline. `tools/probes/hudgate.py` part 2b replays exactly
this opening - a first frame under an effect, the return to 0000, then a real carry - and without
this gate the run reports the opening as a judgement.

Gates two and three are both statements about *how much* of the box moved, and a bright enough
overlay satisfies any how-much. The corpus proved it: one of the 27 frames they keep is from g100,
迷路日々 EXPERT 1322/1322, a run whose result page counts nothing but PERFECT. Whatever lit that box
parked on the column for longer than HOLD, and it reached the dim leading-zero padding at its left
edge -- a counter judging nothing cannot.
Gate four is therefore about *where*: the read window is the right-aligned digit column, its leftmost
columns are padding no carry under four digits ever repaints, while a flash crossing the column
repaints from the edge in. Measured over the 27 frames gates two and three keep: the 26 real carries
start changing at column 16 at the earliest (median 26, out of 42), and g100 starts at column 1.
`CARRY_LEFT_MIN = 8` sits between the two with room on both sides. The known cost is a carry that
reaches the thousands digit (999 -> 1000) -- a count that high is a lost run, and the result page is
the authority on totals either way.

Gate five is gate two asked of the shape instead of the brightness, because the corpus grew frames
that beat every how-much: g109 (0056_03 EXPERT 843/843, result page ALL PERFECT) has a hit flash
parked on a GOOD counter that still reads 0, and so does g152's GREAT. They clear gate two with 1 px
of margin (9 px of the box moved more than SETTLE_DELTA), sit 132 px clear of the darkest state ever
seen, and start at column 24-26 of 42, so gate four is not their business either. Open the frame and
there is nothing to argue with: the drawn glyph is the same 0, only lit up. So binarise the box at
INK_LIT and XOR it against the shape the counter had last -- those frames move 0-2 pixels of ink,
while the nearest real carry in the corpus moves 14 (a 0 -> 1 retires the whole oval). Over the 465
frames the first four gates keep, exactly seven move less than `INK_MOVE_MIN = 8`, and all seven are
counters still showing the digit they showed before: g109's GOOD and GREAT and g152's GREAT (result
pages ALL PERFECT), t95-a1's false GOOD -- the one that cost a bounded attempt under 断AP立即重试 --
and three more whose boxes are read the same way in `tools/probes/hudgate.py`. The measured cost of
this gate is therefore 0 real events, and it is the shape-not-brightness rule the 2026-09-30 note
above has been reaching for since m01.

Three further rules keep the thread honest: a frame that moves three or more rows at once is a
screen effect (skill cut-in, fade) and is discarded wholesale; the read window is the digit column
only, so the row labels and the sparkle trail left of them cannot register at all; and PERFECT is
not counted, because it ticks on nearly every note, cannot be missed in any actionable way, and a
PERFECT row is the one most likely to be parked on by a sparkle during a dense section.

The row block is not always five rows. One kind of multi-player 激奏空間 (JUST, user m28650
2026-10-18) draws a sixth counter above PERFECT, and the block is anchored at its top: JUST 136 /
P 159 / G 182 / GD 205 / B 228 / M 251, one 23 px pitch apart. Read with the five-row windows that
layout hands every judgement to the row above it -- PERFECT ticks land in the GREAT window and
GREATs in GOOD -- so a perfectly healthy round commits a dump per judgement (g1684: 383 rejected
frames) and the committed ones disagree with the result page (that round's page reads BAD 1 /
MISS 0; the five-row read says MISS 1). The layout is decided per frame from the *sixth label band*
alone (`JUST_BAND`, x 1000..1145, ink on `min` across channels -- white glyphs light all three,
coloured glow only some, so `max` read three five-row frames of g1765 as 335 while `min` reads
15/42/47) and it holds for the whole round (g1684: 114 committed + 383 rejected frames, all six
rows). When it is seen every window shifts down by `JUST_SHIFT` and the whole baseline is reset, so
the crossing itself can never be mistaken for a tick. The result page has no JUST row -- it folds
into PERFECT -- so totals, AP verdicts and `--read-split` are unaffected; only this thread and
`hudread` need the shift. `tools/probes/hudgate.py` part 4 pins the detector, the geometry, the
reader's row set and the watcher's shift, with three teeth.

Evidence is bounded per round as well: `DUMP_MAX` frames / `DUMP_BYTES_MAX` bytes, then the watch
keeps counting and says once that it stopped writing. The 2026-10-18 JUST rounds taught that cap
(2343 frames / 2.0 GB in one night, 383 of them in a single round); `tools/probes/hudgate.py` part 5
pins the budget and both of its teeth.

It runs on its own daemon thread against MuMu's renderer SDK (~3 ms/frame, measured) rather than
through the fire loop's idle gaps, because the moments worth having sit in exactly the dense action
sections where the loop never idles. A second daemon thread owns everything a frame is worth *after*
the decision -- PNG encode and the ordinal read, 179 ms of it per event on this machine -- because
paying that inside the sampler is how a burst of judgements starves the thread that is supposed to
notice them (`tools/probes/framewriter.py` measures both sides of it).

What this thread produces is a *hint list*, not a verdict: an event means the game's own counter
moved at that moment, but the count runs low (judgements closer than HOLD read as one), and the
result page stays the only authority on totals. A tick here means "go look at this frame"; it never
means the run is lost.

One consumer is allowed to bet on a hint anyway: run.py's --retry-on-break (opt-in; the pure CLI
default is off) stops the attempt and 重试s it back to t=0 on the first committed event, with its
own per-round cap and a last attempt that always plays through. The caps, the fallbacks and the
choice to act all live there -- this thread keeps reporting hints.
"""

import os
import queue
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rlog import FRAMES, subdir  # noqa: E402

X0, X1 = 1148, 1190        # the right-aligned digit column; the labels sit left of this
ROWS = [("GREAT", 156, 174), ("GOOD", 179, 197), ("BAD", 202, 220), ("MISS", 225, 243)]
# A 激奏空間 can add a sixth judgement row: JUST, above PERFECT. The block is top-anchored at 136,
# so the sixth row pushes PERFECT..MISS down one 23 px pitch and each window above then reads the
# row *above* its own -- PERFECT read as GREAT, GREAT as GOOD, ... and MISS falling off the bottom
# entirely. That is user m28650's "Just 认成 P、P 认成 G", and it is what filled research/frames
# with hudreject_* dumps (g1684 alone: 383 of them, all rejected by gates two to five).
#
# The layout is per-round, not per-激奏区間: measured over g1684, all 114 committed frames and all
# 383 rejected ones are six-row, while the five-row control round g1765 never lights the sixth
# label band. It is detected from the *labels* -- drawn whether a counter moved or not, where a
# digit-band test would be blind at the start of a song (dim leading zeros) -- at x 1000..1145,
# y 250..266: lit for six rows (245 ink px at >150) and never for five (0..47, the combo text
# above). 100 sits between the two.
JUST_SHIFT = 23             # one row pitch: every window moves down this far in a six-row layout
JUST_BAND = (250, 266)      # the sixth row label's band; nothing is drawn here in a five-row layout
JUST_BAND_X = (1000, 1145)  # the labels' column (the counters themselves live at X0..X1)
JUST_BAND_INK = 100         # ink pixels that mean the sixth label is really there


def just_layout(img):
    """True when the HUD is drawing six rows (a JUST 激奏空間 round), so every window sits 23 px low.

    `min` across the channels, not `max`: the labels are white text, and a coloured effect over the
    band (a skill cut-in glow) lights only some channels -- with `max` three five-row frames of
    g1765 read 335 ink and were taken for six-row, with `min` they read 15..47.
    """
    arr = np.asarray(img)
    band = arr[JUST_BAND[0]:JUST_BAND[1], JUST_BAND_X[0]:JUST_BAND_X[1]]
    return int(np.count_nonzero(band.min(axis=2) > 150)) >= JUST_BAND_INK


DELTA = 60          # intensity step that counts as ink appearing/vanishing
MIN_PX = 8          # changed digit pixels needed for a tick
MIN_INK = 40        # bright pixels a read must still hold: the digits, not an overlay covering them
HOLD = 0.12         # seconds the new digits must hold still before the tick is believed
SETTLE_DELTA = 50   # gate two: intensity step against the last settled state
SETTLE_MIN_PX = 8   # ...and pixels of the box that must differ, else the counter never moved
ZERO_MIN_PX = 8     # gate three: pixels of separation needed from the darkest state ever seen
# Gate four: a judgement repaints digits, an effect repaints the window. The read window is
# right-aligned 4-digit counters, so its leftmost columns are dim leading-zero padding that no
# carry under four digits ever touches -- measured over the 27 frames gates two and three keep:
# the 26 real carries start changing at column 16 at the earliest (median 26, out of 42), the one
# false one (g100, an ALL PERFECT run) starts at column 1. 8 sits between the edge and the nearest
# real event with room on both sides.
CARRY_LEFT_MIN = 8
# ... but the baseline is only ever *lowered* by frames that look like a counter, and a restart
# reseeds it wholesale. Two ways it went wrong, both measured: a screen darker than the counter
# (a pause scrim, an overlay) teaches the darkest-ever box a level below every real frame, after
# which gate four eats every carry for the rest of the round -- s260's sixth attempt lost 24 real
# GREAT carries in a row that way (the counters read 3 -> 44 while the watcher reported nothing,
# and the abort fired only on the GOOD that ended the burst, 10 s late). And a bright pollution
# (a sparkle as the first frame) needs the ordinary min update to be *corrected* by the next dark
# frame, so the update cannot simply refuse dark frames -- refusing them is what the 2b script of
# hudgate catches. A restart is the one moment the counters are known to be back at zero, so it is
# the one moment the darkest-ever box can be thrown away and re-learned from scratch: run.py calls
# reseed() after every successful 重试.
# Gate five asks the same question as gate two -- what did the counter say just now -- of the
# *shape* rather than the brightness. Gates two to four all measure how much moved, and the corpus
# produced the frame that beats any how-much: g109 (0056_03 EXPERT 843/843, ALL PERFECT) parked a
# hit flash on a counter that still read 0, brightening 9-12 px of the digit past SETTLE_DELTA,
# 132 px clear of the darkest state, starting at column 26 of 42. Look at the frame and there is
# nothing to argue with -- the glyph is the same 0, only lit up. Binarising the box at INK_LIT and
# XORing it against the last settled shape says so in one number: those frames move 0-2 pixels of
# ink, while the 458 survivors that are carries move at least 14 (a 0 -> 1 retires the whole oval).
# INK_MOVE_MIN = 8 sits in that gap, and the measured cost over the whole corpus is 0 real events.
INK_LIT = 200
INK_MOVE_MIN = 8
REBASE = 1.0        # seconds of stillness after which whatever is displayed is simply the truth
# libpng's own default (6) costs 89 ms for a 1280x720 frame of this content, level 1 costs 35 ms and
# writes 1.0 MB against 0.64 MB. The frames are replayed by `probes/hudgate.py` and read back by
# `hudread`, both of which decode rather than re-encode, so a lossless-but-cheaper level changes
# what they see by nothing at all: the probe asserts the pixels come back identical.
FRAME_PNG_LEVEL = 1
# A frozen capture and a screen nobody is judging look the same from here: no row moved. Only one of
# them is evidence, and #115's whole cost was a silent stretch of readings being read as a clean
# stretch of play. `mumucap.stalled_s()` separates them -- a live page repaints every frame because
# notes scroll, so identical pixels for 2 s mean either a paused scrim or a frozen buffer, and the
# line names both without claiming either. 2 s is well past a 暂停→重试 tap; one line per 10 s keeps a
# genuinely quiet stretch from filling the log.
STALL_LOG_S = 2.0
STALL_SAY_S = 10.0
# How many consecutive `mumucap.frame()` exceptions the sampler tolerates before it stops. One is
# not evidence that the capture path is gone -- MuMu's DLL has thrown a single access violation
# mid-round (g067) -- and `return` on the first one silently removed the watcher, and with it the
# --retry-on-break trigger, for the rest of that attempt.
CAP_FAILS_MAX = 20
# How much evidence one round may write. CAP_FAILS_MAX above bounds the *capture* failing; this
# bounds the *gates* disagreeing with themselves, which used to be unbounded: the 2026-10-18 JUST
# rounds (user m28650) wrote 2343 frames / 2.0 GB, one round alone (g1684) 383 of them, because a
# mis-read layout made every single judgement look like a rejected candidate. The layout bug is
# fixed; the *cost* of the next such bug is this budget's job, not the next cleanup's. Past the cap
# the watch keeps counting and keeps saying so, and only stops writing. 60 frames is ~47 MB at
# level 1 (a 1280x720 frame of this content is 0.79 MB) and far more than a real round needs -- a
# healthy AP round commits 0, a round with real misses commits a handful.
DUMP_MAX = 60
DUMP_BYTES_MAX = 48 * 1024 * 1024


class HudWatch:
    """Call start(); when the song is over call stop() and read n/events.

    events are (t_lo, t_hi, row): the counter changed somewhere inside that frame interval and the
    new value then held. The interval is one capture cadence wide (single-digit ms), so t_lo is
    already tight enough to name the note being judged.
    """

    def __init__(self, log=print, tag="run", sink=None):
        self.log = log
        self.tag = tag
        # Called on this thread for every frame that comes off the capture, before any gate looks
        # at it: the recorder behind it must be non-blocking (see tools/recorder.py).
        self.sink = sink
        self.n = {r: 0 for r, _, _ in ROWS}
        self.events = []
        self.dropped = 0
        self.unverified = 0
        self.unzeroed = 0
        self.wholebox = 0
        self.unmoved = 0
        self.rebased = 0
        self.reseeded = 0
        self.error = None
        self.undrawn = 0            # evidence frames the writer never got to
        self.stalled = 0            # times the watch said "no new frames" during this live
        self.dumped = 0             # evidence frames this round has spent from DUMP_MAX
        self.dump_bytes = 0         # bytes those frames took, summed by the writer thread
        self.dump_over = 0          # evidence frames the budget turned away
        self._dump_said = False
        self._last_stall = 0.0
        self._stop = threading.Event()
        self._reseed = threading.Event()
        self._thread = None
        self._writer = None
        self._q = queue.Queue()     # (path, pixels, what to say afterwards) still to be handled

    def _draw(self, path, img, line, ordinal=False):
        """Hand an evidence frame to the writer thread: encode, read, then say the line.

        Both halves of what a committed frame is worth used to happen *inside the sampling loop*:
        libpng's default level costs 89 ms for a frame of this size, and the ordinal read costs 90
        more (`hudread.counters_arr` classifies five boxes against every digit at every shift). A
        round that produced 245 candidate frames s303's way spent ~36 s of its own watcher on
        pictures -- the one thread whose cadence decides when 断AP is noticed, starving exactly
        during the burst that is the finding. That is the s260 shape (24 real carries lost, the abort
        10 s late) with a second cause attached to it.

        The queue itself has no bound, because a bound *there* would drop evidence without anyone
        being able to say so; what is bounded is what reaches it -- `_dump_room` caps one round at
        DUMP_MAX frames / DUMP_BYTES_MAX bytes and says so once, on the line that would have named
        the frame (2026-10-18: the JUST layout bug wrote 2343 frames / 2.0 GB in one night). Within
        that budget the only way this counts anything is a writer that died or was never started,
        which is the case where the frames would not have been written before either.
        """
        if self._writer is None or not self._writer.is_alive():
            self.undrawn += 1
            return
        self._q.put((path, img, line, ordinal))

    def _writer_loop(self):
        from PIL import Image

        from hudread import counters_arr, ordinal

        while True:
            item = self._q.get()
            if item is None:
                return
            path, img, line, want = item
            o = None
            if want:
                # A read that fails says nothing rather than something wrong -- `line` renders the
                # sentence without the 第 N 个判定物 clause.
                try:
                    o = ordinal(counters_arr(img))
                except Exception:                                   # noqa: BLE001
                    o = None
            try:
                Image.fromarray(img).save(path, compress_level=FRAME_PNG_LEVEL)
            except OSError as e:                      # noqa: BLE001 - evidence, not the live
                self.undrawn += 1
                self.log(f"  hud watch: 证据帧写盘失败 {os.path.basename(path)}（{e}）")
                continue
            # Summed here, on the thread that did the encode: the sampling thread only reads it,
            # so a byte total that lags by whatever is still queued is fine -- DUMP_MAX bounds the
            # count and this bounds the size.
            try:
                self.dump_bytes += os.path.getsize(path)
            except OSError:
                pass
            # Said after the write, because every path this thread prints has to exist: `dropmap`
            # goes looking for the frame named on the line.
            self.log(line(o))

    def reseed(self):
        """Ask the watcher to forget its darkest-ever box; call it after a 重试 restarts the live.

        The counters are back at zero then, so the next frames are the zeros pattern itself, and a
        baseline taught by anything else (a pause scrim dims the box by half) would sit below every
        real frame -- gate four then rejects carries as if they were overlays. Thread-safe on
        purpose: run.py calls this while the watch thread is in its loop.
        """
        self._reseed.set()

    def start(self, delay=0.0):
        # A fresh queue per attempt: whatever an earlier attempt's writer was still chewing on when
        # its stop() timed out belongs to a live that has ended -- including the sentinel that
        # retires a writer, which a shared queue would hand to this attempt's thread.
        # A fresh dump budget goes with it: the first frame of this attempt cannot be paid for by
        # the previous one's leftovers.
        self.dumped, self.dump_bytes, self.dump_over, self._dump_said = 0, 0, 0, False
        self._q = queue.Queue()
        self._writer = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer.start()
        self._thread = threading.Thread(target=self._run, args=(delay,), daemon=True)
        self._thread.start()

    def stop(self, timeout=2.0, drain=6.0):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        # The sampling thread has now made its last hand-off, so what is left in the queue is bounded
        # -- one round's worth of judgements. 6 s is 245 frames at level 1 plus their ordinal reads.
        if self._writer is not None:
            self._q.put(None)
            self._writer.join(drain)
            self._writer = None

    def _dump_room(self):
        """May one more evidence frame be written this round? Says so once when the answer turns no.

        Called from the sampling thread by both the commit and the reject path, before anything is
        handed to the writer. The count is the authoritative half -- `dump_bytes` is summed by the
        writer thread after the encode, so it lags by whatever is still queued -- and either cap
        stops the *writing*, not the counting: `n`, `events` and the tally keep going, because the
        round's judgement history is worth more than its pictures.
        """
        if self.dumped >= DUMP_MAX or self.dump_bytes >= DUMP_BYTES_MAX:
            if not self._dump_said:
                self._dump_said = True
                self.log(f"  hud watch: 证据帧预算用尽（{DUMP_MAX} 张 / "
                         f"{DUMP_BYTES_MAX / (1024 * 1024):.0f} MB）—— 后续只记数不落盘")
            self.dump_over += 1
            return False
        self.dumped += 1
        return True

    def tally(self):
        return (" ".join(f"{r} {self.n[r]}" for r, _, _ in ROWS)
                + (f"  证据帧未写 {self.undrawn}" if self.undrawn else "")
                + (f"  证据帧省下 {self.dump_over} 张" if self.dump_over else "")
                + (f"  快采停更 {self.stalled} 次" if self.stalled else ""))

    def _commit(self, lo, hi, row, img):
        self.n[row] += 1
        n = self.n[row]
        self.events.append((lo, hi, row))
        if not self._dump_room():
            # The judgement still happened and is still in `n`/`events`; only the picture is gone.
            # Said here, on this thread, because there is no file for the writer to name.
            self.log(f"  hud: {row} #{n} at host [{lo:.3f}, {hi:.3f}]（证据帧预算用尽，未落盘）")
            return
        # Tagged, because the untagged name made every run overwrite the previous one's evidence.
        path = f"{subdir(FRAMES)}/hud_{self.tag}_{row.lower()}{n}.png"
        # The ordinal, in the line and not only in the png: the rolling window prunes frames, and by
        # the time a seam question is worth asking most of this round's evidence is gone (measured on
        # the corpus: 366 of 519 logged events no longer have their frame). One pass over the frame
        # already in hand buys that number forever -- and the queue is FIFO with one reader, so the
        # lines still arrive in judgement order, which is what `dropmap` replays them by.
        self._draw(path, img,
                   lambda o: f"  hud: {row} #{n} at host [{lo:.3f}, {hi:.3f}]"
                             + (f" 第 {o} 个判定物" if o else "") + f" -> {path}",
                   ordinal=True)

    def _reject(self, kind, count, lo, hi, row, img):
        """Keep the frames the gates throw away, or the next cost analysis has nothing to label.

        Deliberately not named like a committed frame: `hud_<tag>_<row><n>.png` is the corpus the
        offline probe replays, and a reject has no result-page label yet. No ordinal either -- the
        whole point of these frames is that no counter moved, and reading one costs 90 ms.
        """
        if not self._dump_room():
            self.log(f"  hud: {row} at host [{lo:.3f}, {hi:.3f}] 被{kind}闸门弃掉"
                     f"（证据帧预算用尽，未落盘）")
            return
        path = f"{subdir(FRAMES)}/hudreject_{self.tag}_{kind}_{row.lower()}{count}.png"
        self._draw(path, img,
                   lambda o: f"  hud: {row} at host [{lo:.3f}, {hi:.3f}] 被{kind}闸门弃掉 -> {path}")

    def _settle(self, lo, hi, row, img, c, settled, zero):
        """Gates two to five: the digits themselves, not the frame-to-frame diff, decide."""
        was = settled[row].copy()
        d = int(np.count_nonzero(np.abs(c - settled[row]) > SETTLE_DELTA))
        settled[row] = c.copy()
        if d < SETTLE_MIN_PX:
            # Whatever crossed the window has gone and the counter reads exactly what it read
            # before: nothing was judged. This is the sparkle that exits through the column.
            self.unverified += 1
            return
        away = np.abs(c - zero) > SETTLE_DELTA
        if int(np.count_nonzero(away)) < ZERO_MIN_PX:
            # It reads the all-zeros pattern after all, so the difference above is the baseline
            # being wrong, not the counter having moved.
            self.unzeroed += 1
            self._reject("zero", self.unzeroed, lo, hi, row, img)
            return
        cols = np.flatnonzero(away.any(axis=0))
        if cols.size and int(cols[0]) < CARRY_LEFT_MIN:
            # The repaint reaches the dim-zero padding at the left edge of the window. A count that
            # small cannot have carried that far; an overlay bright enough to light the padding can,
            # and does (g100, an ALL PERFECT run whose GREAT counter had not moved).
            self.wholebox += 1
            self._reject("edge", self.wholebox, lo, hi, row, img)
            return
        ink = int(np.count_nonzero((c > INK_LIT) ^ (was > INK_LIT)))
        if ink < INK_MOVE_MIN:
            # The same digit is still drawn, only brighter. Whatever crossed the column parked there
            # for longer than HOLD; no judgement happened, because a judgement changes which glyph
            # is up -- it cannot leave the ink exactly where it was.
            self.unmoved += 1
            self._reject("shape", self.unmoved, lo, hi, row, img)
            return
        self._commit(lo, hi, row, img)

    def _run(self, delay):
        try:
            import mumucap

            if delay:
                time.sleep(delay)
            prev = {}
            settled = {}
            zero = {}
            still = {}
            cand = {}
            last_t = None
            cap_fails = 0
            shift = None
            while not self._stop.is_set():
                if self._reseed.is_set():
                    # A 重试 put the counters back at zero: the darkest-ever box describes the
                    # screen the previous attempt was played on, and measuring this attempt's
                    # carries against it is how gate four ate s260's 24 in a row. Drop it and let
                    # the next frames teach it again -- they are the zeros pattern by construction.
                    zero.clear()
                    self._reseed.clear()
                    self.reseeded += 1
                try:
                    t, img = mumucap.frame()
                    frozen = mumucap.stalled_s()
                except Exception as e:                             # noqa: BLE001
                    # One transient fault ends the watcher for the whole attempt with the old
                    # `return` -- g067's detail log has a single "access violation reading
                    # 0x37D50000" inside MuMu's DLL, and the round then had no live judge at all
                    # (with --retry-on-break armed, the abort mechanism was simply gone). The SDK
                    # is an external component that run.py's own use_fast_capture already treats as
                    # something that may fail; tolerate a short burst of failures before giving up.
                    cap_fails += 1
                    self.error = f"{e}"
                    if cap_fails >= CAP_FAILS_MAX:
                        self.log(f"  hud watch: capture failed {cap_fails} times ({e}) - stopping")
                        return
                    if cap_fails == 1:
                        self.log(f"  hud watch: capture failed ({e}) - retrying")
                    time.sleep(0.02)
                    continue
                cap_fails = 0            # a delivered frame means the channel came back
                if frozen > STALL_LOG_S and time.perf_counter() - self._last_stall > STALL_SAY_S:
                    # Worth a line because its absence is the whole of #115: a frozen buffer still
                    # carries a fresh stamp, so the counters genuinely cannot have moved as far as
                    # this thread can tell, and a silent stretch of log reads as a clean stretch of
                    # play. It says which of the two it was. It changes nothing -- the run's authority
                    # is the result page, and aborting a live because a *reader* stalled is the
                    # mistake #115's lesson says not to make twice.
                    self._last_stall = time.perf_counter()
                    self.stalled += 1
                    self.log(f"  hud watch: 快采已 {frozen:.1f}s 没给过新帧 -- 暂停、或这一路停更；"
                             f"这段没有读数")
                if self.sink is not None:
                    # Fed before the gates and before the fade branch: the recording is the raw
                    # stream of one round, not the watcher's opinion of it. Wrapped because a
                    # diagnostic must never be able to stop the watch.
                    try:
                        self.sink(t, img)
                    except Exception as e:                          # noqa: BLE001
                        self.sink, self.error = None, f"recorder: {e!r}"
                if img.mean() > 140:
                    # A fade/whiteout is not a screen: the counters are not readable through it,
                    # and the frame after it must re-baseline rather than diff against white. The
                    # settled state survives, because a fade judges nothing and re-reading it from
                    # one post-fade frame is how a polluted baseline gets in.
                    prev.clear()
                    still.clear()
                    cand.clear()
                    last_t = None
                    continue
                just = JUST_SHIFT if just_layout(img) else 0
                if just != shift:
                    # The geometry moved under us: a JUST round started, or the first frames were
                    # too dark to read the labels. Nothing measured against the old geometry means
                    # anything -- a shifted window holds different pixels, so every baseline
                    # (including the darkest-ever box, which was a different window) is re-learned
                    # from here. Clearing `prev` also keeps the change from looking like four rows
                    # moving at once and being quashed as a screen effect.
                    if shift is not None:
                        self.log("  hud watch: 判定行布局变为 "
                                 + ("6 行（JUST）" if just else "5 行") + " - 重新起算")
                        prev.clear()
                        settled.clear()
                        zero.clear()
                        still.clear()
                        cand.clear()
                    shift = just
                moved = set()
                cur = {}
                for row, y0, y1 in ROWS:
                    c = np.ascontiguousarray(img[y0 + shift:y1 + shift, X0:X1]).astype(np.int16)
                    cb = c.max(axis=2)
                    cur[row] = cb
                    if row not in zero:
                        zero[row] = cb.copy()
                    else:
                        np.minimum(zero[row], cb, out=zero[row])
                    p = prev.get(row)
                    prev[row] = c
                    if row not in settled:
                        settled[row] = cb.copy()
                    if p is None or last_t is None:
                        continue
                    m = (np.abs(c - p) > DELTA) & ((c > 170) | (p > 170))
                    if np.count_nonzero(m) >= MIN_PX and np.count_nonzero(c > 170) >= MIN_INK:
                        moved.add(row)
                quashed = set()
                if len(moved) >= 3:
                    # Judgements never tick three rows inside one frame. Drop every pending
                    # candidate: whatever this was, it moved more than the counters.
                    self.log(f"  hud watch: {len(moved)} rows changed at once "
                             f"({sorted(moved)}) - screen effect, ignored")
                    self.dropped += len(cand)
                    cand.clear()
                    # ...and do not let this same frame seed new ones. Seeding them here is what
                    # turned the round-start repaint into four "#1" judgements: the four boxes are
                    # drawn at once, the line above says the frame is ignored, and then each of the
                    # four rows got a candidate anyway and committed HOLD later. g468 is the proof
                    # they are false -- its tally read MISS 1 while its result page read MISS 0 /
                    # ALL PERFECT -- and with --retry-on-break the first of them aborts the round
                    # 0.03 s in, which a co-op round cannot retry. The rows come back only through
                    # REBASE: a second of stillness hands the new picture to the baseline, so a
                    # judgement after the repaint is still reported.
                    quashed = set(moved)
                for row, _, _ in ROWS:
                    if row in quashed:
                        still[row] = None
                        continue
                    if row in moved:
                        # A row that moves again has not settled: the candidate restarts, and the
                        # one it replaces is dropped -- two judgements inside HOLD read as one,
                        # which is the price of not reporting sparkles.
                        if row in cand:
                            self.dropped += 1
                        cand[row] = (last_t, t)
                        still[row] = None
                        continue
                    if still.get(row) is None:
                        still[row] = t
                    elif t - still[row] >= REBASE:
                        # A second without a twitch means the box is showing the live count, even
                        # if the candidate that would have reported it was discarded above. Without
                        # this the baseline goes stale on a screen effect and every later sparkle
                        # exits onto a real difference.
                        if int(np.count_nonzero(np.abs(cur[row] - settled[row]) > SETTLE_DELTA)) \
                                >= SETTLE_MIN_PX:
                            settled[row] = cur[row].copy()
                            self.rebased += 1
                    if row in cand:
                        lo, hi = cand[row]
                        if t - hi >= HOLD:
                            del cand[row]
                            self._settle(lo, hi, row, img, cur[row], settled, zero[row])
                last_t = t
        except Exception as e:                                     # noqa: BLE001
            self.error = f"{e}"
            self.log(f"  hud watch unavailable ({e})")
