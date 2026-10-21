"""Offline regression for the post-result walk's page recogniser (`calib.screen`).

The walk only taps buttons it can name, so a page it cannot name is a page it sits on until the
timeout: 羁绊奖励详情 (the scrollable variant the game opens over the result page after a 絆 rank
up) did exactly that twice -- start_live_stuck.png, then nav_stuck_other.png -- and both frames are
in the corpus below.

Part 0 checks the corpus itself: every frame under evidence/nav/ must still read as the page
MANIFEST.json recorded it for, and no frame may be there uninvited. Part 1 replays the rule set over
that corpus, once as the tree
ships it and once with `_bond_detail` switched off. PASS needs all three of: the two stuck frames
read "rewards" with the rule in, they read "other" with it out (the bug itself, reproduced), and
they are the only frames in the corpus whose verdict the rule changes -- a page recogniser that
reclassifies a third frame is how 首页's bottom bar got tapped once already.

Part 2 has the teeth for the rule's second gate. `_bond_detail` merges pale columns across <20 px
gaps where `_modal_close` merges across <60, which is what lets the pill out of the blurred
artwork -- but that same narrowing could hand the pill shape to 首页 (its bottom bar's run through
x=644 is 584 px wide and "safely wider" only at the old gap). The title gate is the guard, and no
首页 frame exists in the corpus, so the check is the counterfactual: paint the title box out of the
popup frame and the pill shape alone must no longer claim it; pin BOND_TITLE_MIN to 0 and the same
blinded frame must come back. That is the 首页 failure mode in a frame that exists.

Part 3 covers the second RANK UP layout (g169/g170 both died on it on 2026-10-01). The 玩家等级
splash paints the same pale-green title 120 px below the 羁绊 one, so `_level_rankup` claims it --
and it is asked only AFTER the modal tests, which is what keeps the result page's split view
(green histogram bars in that same band, plus the game's standard 252x60 pill 110 px lower)
reading "rewards". `rankup_ok` then returns the pill's own centre, because the historical
RANKUP_OK sits 100 px under it on blank scrim: naming the page without moving the tap would leave
the walk sitting on it all the same.

Part 4 is the 演出 load interstitial: the pale card puts a fully bright, fully inkless patch in
the top-right corner where 结算's rank badge lives, and the result test only asked whether that
box is bright -- so the load read as 结算 and the walk waited four watches on a page with nothing
to press. `_loading` claims it BEFORE the result test, so no real 结算 page has to be re-validated
against a tightened rule.

Part 6 is 首页, which had no frame in the corpus until 2026-10-01 -- and the first one we captured
broke the rule that was there. Its cue was the RANK plate top-left, a translucent plate over the
artwork, and a warm event banner moved its |R-B| to 25.5 against a gate of <25. 首页 then fell
through to 商店, whose test only counts orange pixels in two bands (that frame carries 7894 and
7304 against a gate of 5000), and 商店's only action is a tap at SHOP_HOME. The cue now reads
three opaque blue buttons and the 演出 word, and 首页 is asked before 商店. The part pins the
dependency set: paint the artwork out and keep only those four boxes, and 首页 must still read
首页 -- which is the whole point, since it is the artwork that changed.

Part 7 is the walk-back a finished round now takes: 结算 →下一步→ EXP 页 →再次演出 must stop the
moment it reads 乐曲选择. The scripted source holds one page up for ever, which is what a real
select page does for the second it takes to load -- so the counterfactual is blunt: without
`stop_at_select` the walk presses 确定 again and again, and the first of those is another LIVE.

Part 12 is the two rules the walk's own taps are held to, from the two rounds that broke them
(g347 00:47 and g446 15:25: the walk into a LIVE pressed 演出开始 on 乐队确认, the page then read
`band` 540+ more times until the walk gave up, and the walk *home* pressed 演出开始 again -- turning
"go home" into "start a song"). The walk-back may not press either button that starts a LIVE, and a
`live` frame is not "home"; the walk into a LIVE retries a 演出开始 the page ignored, but only
`START_RETRIES` times, and a page that turns into the field stops it at once.

Part 13 is what the random walk hands to the rest of the round. `--random` picks the song off the
screen, so the chart is only known once the LIVE is already running -- and on 2026-10-07 three
random rounds (g464/g465/g466) all died right there: the call site passed the pick's *loaded list*
to `chart_events`, which starts by opening the `.raw.json` next to the path it was given. The pick
now carries that path as well, and this part pins both halves of the contract: a path reads the
event table, a list reproduces the `AttributeError` that killed those three rounds.

Part 14 is `--song`: the other way a round can decide its chart on the select page. It walks the
list one row at a time because the list's own gestures are not a ruler (the same 200 px drag moves
+2 rows in 0.60 s and +24 in 0.30 s), reads the highlighted musicId back after every step, sets the
難度 pill, and gives up -- instead of spinning until the walk's timeout -- when the list stops
moving or starts drifting away. The part drives the real `run.pick_song` over a scripted list page
and pins the wiring too: `--song` registered, `on_select` dispatching to it, and the chart path
known for both `--random` and `--song`.

Parts 7 and 12 drive the real `calib.start_live`, which gives up by writing a frame into the
*working* dump (`research/frames`) -- and a scripted source that holds one page up for ever is
exactly the script that makes it give up: a full run on 2026-10-07 left three `nav_stuck_*.png`
there (23:49-23:50), invisible until now only because the panel's junk sweep deletes that name
pattern. Both parts now walk behind `_DumpGuard` and require the dump to have happened in scratch
while the working dump gained nothing.

Part 15 is the 多人 half of the same walk (2026-10-08). The user's own round -- screen-recorded by
`research/recordings/mp2`, 1947 frames at 2.88 fps -- put four pages between 乐队确认 and the field
that `screen` could not name, and every one of them was named something the walk then taps:
匹配中弹窗 and 准备页 both read "home" (the walk presses 首页's neon tile at 1090,600), the 抽曲动画 /
封面 / 五人加载 share one layout that read "options" and "shop" (演出 at 790,611, or the shop
header), and 排名页 read "result" -- the one accident that lands right, because its 下一步 is the
same (1080,660) the solo 结算 uses. Ten frames from that round are pinned in the corpus (PART 0
holds them) -- the tenth is the frame the 匹配中弹窗 dissolves into the 匹配页, which read `failed`
(a page whose walk action is 返回选曲, i.e. cancelling the match just found) until the lobby rule's
luma floor came down from 100 to 70; PART 15 pins that too; PART 15 holds the margins around them: fifteen neighbours that must not be reclassified,
a counterfactual for every gate (loosen it past the neighbour and the neighbour really does flip),
and the walk itself -- the three pre-match pages must be waited on without a single tap, 排名页 must
be tapped like 结算, and with that quiet set removed the 准备页 burns eight "unreadable screen" reads
and abandons the round.

2026-10-09: the 演出首页 grew the same white word in the box `_home`'s second leg reads, so 首页
claimed it -- and `screen()` asks 首页 before 演出首页, so the walk tapped 首页's 演出 tile on the
演出首页 and stacked three unreadable pages on top of itself (mp19's 03:14 and 03:43 rounds, both
lost).  `_home` now lets `_livehome` veto it.  PART 6 paints that box white on the fixture and
requires livehome anyway, and requires the same frame to read 首页 once the veto is taken back out.

Each part replays the whole corpus twice, so this file takes a few minutes.

Part 16 is the other half of a 多人 round: which chart it plays, and what the walk does between the
演出开始 tap and the field. The room draws the song -- only the 准备页's jacket says which one -- and
the 難度 pill row sits 30 px lower on the multi select page than on the solo one, so `read_difficulty`
now reads two bands (g486 died on the one it did not read) while the solo band keeps answering off its
own geometry alone. `read_prep` reads the drawn jacket: the mp2 round drew 100080 where the player had
picked 100056, and the mp1 round drew 100056 -- both are pinned. The tail is the second half: every
page of the field's own fade-in (other → rankup → result → options → one live frame → other) used to
be handed to its own branch, so 排名 up had its pill pressed and 4.11 s of `other` was eight unreadable
reads -- the whole round, if the walk missed that single live frame. The tail now watches every page,
and the counterfactual is the same page before the tail: 排名 up must still be pressed there. The
quiet pages also clear the repeat counter, because they wait for the game rather than watch one
verdict: without that, `other` read 3 times over 0.5 s was timed as "unchanged for 22 s" across the
34 s 匹配中弹窗 and handed back once. The walk's last stop, the 结算 EXP page, comes in two layouts
that `_exp_cards` tells apart -- 详情/下一步 and 主页/再次演出 -- and both are pressed at once: the
user settled on 2026-10-08 that in 多人 再次演出 also goes back to 乐曲選択 rather than re-queuing a
match, so the 10 s watch that layout used to get is gone and PART 16 requires it to be gone.

Part 19 is 消耗LB. The 加成火力 gate used to park the walk on 乐队确认页 and re-read every 20 s with
no upper bound (0 → 3 points can take an hour); the user's 2026-10-11 rule is to spend the readout
instead of waiting for it -- ≥N points sets 消耗LB to 3 档, anything less sets it to 0, and the LIVE
starts either way. The dialog that button opens also has to be named: it does not cover the LIVE
START, so `_blue(img, *SONG_GO)` claimed it and `screen()` called the page 乐曲選択 (measured live on
2026-10-11: `read_song_select` ok=False score 0.40) -- the walk would have pressed 決定 on one of its
four rows. `lb_popup` therefore sits BEFORE the select test, and the part drives the real walk over a
source that answers taps the way the game does: 3 档 and 0 档 in both directions, the gate switched
off, a dialog that will not close (the walk must stop short of pressing 演出开始), and the mutant
that takes the popup test back out.

Part 21 is the page the user found on 2026-10-20 (m51338): 结算分数页后面那一页（领奖/奖励）read as
乐曲選択, so the walk pressed 決定 on it, the read after the press said `select`, and the round
declared itself home on a page it had never left. The two families share colour, height and position
of the blue pill bottom-right -- only its WIDTH separates them: 決定 is 198..202 px, the 结算族
(下一步 / 再次演出 / 领奖 / 排名) is 245..250 px, measured on both rows the ink does not cross
(y632 / y687). `_go_pill_wide` therefore vetoes `select` and claims `exp` with the same one number,
and the part pins both directions: the pinned frame must read `exp`, the three 乐曲選択 frames must
still read `select`, a threshold pushed above 250 must fall back to the old (wrong) `select`, and one
pushed below 198 must stop eating the real 選択 page.
"""
import glob
import hashlib
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import calib                                                            # noqa: E402
import gameread                                                         # noqa: E402

STUCK = ("navgates_bond_detail_a.png", "navgates_bond_detail_b.png")
# The 玩家等级 RANK UP splash the post-result walk met on 2026-10-01 (g169/g170 both died on it):
# the same pale-green title as the 羁绊 splash, painted 120 px lower, and its OK pill 100 px
# HIGHER than the historical RANKUP_OK -- so recognising the page is only half the fix.
RANKUP = ("navgates_level_rankup_a.png", "navgates_level_rankup_b.png")
# Two captures of the 演出 load interstitial (NOW LOADING + a 集合! card over a full-bleed pale
# background), one mid-fade and one full: its pale corner answers the 结算 rank-letter test better
# than the badge does, which is why the walk sat there for four watches every round.
LOAD = ("navgates_load_a.png", "navgates_load_b.png")
# Two captures of the 结算 EXP page's second layout (详情 + 下一步): the 絆 rank-up interstitial
# that task #77 left open. Its 下一步 is the game's standard 252x60 pill at (1108, 660), under
# 确定's colour probe, so the page read as 乐曲选择 -- and 随机演奏 then waited for a jacket it
# cannot have. now_after_bond_close.png is the same page's 09-30 evidence frame.
EXPV = ("navgates_exp_detail_a.png", "navgates_exp_detail_b.png")
# The 结算 totals page the walk lands on one tap later: 主页 + 再次演出, no member cards. The old
# rule named it, so the union has to keep naming it.
EXP_HOME = "navgates_exp_home_a.png"
HOME_FRAME = "nav_home_a.png"
LIVE_FRAME = "nav_livehome_a.png"     # 演出首页: same resource bar, no 演出 tile       # 首页 under the 2026-10-01 warm banner: the frame that broke
                                    # the translucent-plate cue and read as 商店
# Copies of the two dumps the walks left behind (nav_stuck_other.png, start_live_stuck.png):
# those names get overwritten the next time a walk gives up somewhere else, and the fixture has to
# outlive the incident. The originals stay in the corpus, so both spellings are known pages here.
ALSO_SAME_PAGE = ("nav_stuck_other.png", "start_live_stuck.png")
# The four pages 多人 opens between 乐队确认 and the field, from the user's 2026-10-08 round: the
# 匹配中弹窗 (t 114.5-148.9, 34.9 s of nothing), the 准备页 (t 155.0-165.2), the 抽曲动画 / 抽中封面 /
# 五人加载 (one layout, t 150.1-152.4 + 152.8-154.6 + 167.95-170.61) and the 排名页 (t 299.9-602.7,
# 803 identical frames waiting for 下一步). PART 0 pins the frames; PART 15 pins the margins.
MP_VERDICTS = {
    "mp_matchpopup_a.png": "matchpopup", "mp_matchpopup_b.png": "matchpopup",
    "mp_prep_a.png": "prep", "mp_prep_b.png": "prep",
    "mp_matching_a.png": "matching", "mp_matching_b.png": "matching",
    "mp_matching_c.png": "matching", "mp_matching_d.png": "matching",
    "mp_rank_a.png": "rank", "mp_rank_b.png": "rank",
}
# The corpus frames closest to each new rule -- every one must keep the verdict it already has, and
# none may answer any of the four new predicates (a page that survives only because an earlier test
# grabbed it is not a margin). The tight ones are named:
MP_NEIGHBOURS = (
    ("navgates_pause_a.png", "pause"),    # pill.pale 0.805 against the popup gate 0.85
    ("nav_stuck_finish.png", "finish"),   # the 结算 splash: bl.pale 0.165, cyan 0.105
    ("nav_home_a.png", "home"),           # pbtn 0.206 / label 0.307 against 0.25 / 0.35
    ("nav_livehome_a.png", "livehome"),   # pbtn 0.214 against 0.05; bluesat 0.298 against 0.30
    ("navgates_load_a.png", "loading"),
    ("navgates_load_b.png", "loading"),
    ("nav_stuck_result.png", "loading"),
    ("nav_stuck_other.png", "other"),
    ("nav_stuck_band.png", "band"),
    ("nav_stuck_select.png", "select"),
    ("navgates_exp_home_a.png", "exp"),
    ("now_after_bond_close.png", "exp"),
    ("result_a43.png", "result"),         # mid.pale 0.764 against the rank gate 0.30
    ("result_a44.png", "result"),
    ("hud_great1.png", "live"),
)
ROOT = Path(__file__).resolve().parents[2]
NAV = ROOT / "evidence" / "nav"
# The round's *working* dump (research/frames) -- not the corpus. Parts 7 and 12 drive the real
# `calib.start_live` over a scripted frame source, and that function gives up by writing a frame
# through `rlog.subdir(FRAMES)`, which points here.
FRAMES_DIR = ROOT / "research" / "frames"


def _tree(d):
    """name -> size, for the 「the working dump did not move」 assertions."""
    try:
        return {p.name: p.stat().st_size for p in Path(d).iterdir()}
    except FileNotFoundError:
        return {}


class _DumpGuard:
    """Send `calib`'s give-up dumps to a scratch dir instead of the round's working dump.

    2026-10-07: a scripted source that holds one page up for ever is exactly what makes the walk
    give up -- and it gives up by writing `nav_stuck_<page>.png` into `research/frames`, the
    directory a real round is filling with HUD evidence. A full navgates run left three behind
    (nav_stuck_select/band/live.png, 23:49-23:50, while the newest round file was g470 at 22:40);
    they disappeared only because `panel_core`'s junk sweep deletes that exact name pattern, which
    is how the leak stayed invisible. A probe must not write into the working dump at all, so both
    walks run behind this, and the parts then require two things: the dump really happened (the
    scratch dir is not empty) and the working dump gained none of *our* dumps (another process's
    `nav_stuck_*` -- a round whose own walk gave up -- is not ours to answer for; see `leaked`).
    """

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="navgates_dump_")
        self.saved = None
        self.before = {}
        self.seen = []

    def __enter__(self):
        self.before = _tree(FRAMES_DIR)
        self.saved = calib.subdir
        calib.subdir = lambda _d: self.tmp
        return self

    def __exit__(self, *exc):
        calib.subdir = self.saved
        self.seen = sorted(os.listdir(self.tmp))
        return False

    def leaked(self):
        """Names the working dump gained that are **this probe's own** dumps.

        Deliberately not a whole-tree diff: a real round may be running beside the probe and
        writing its own hud_* frames, which is not this probe's business. Its *walks* are the same
        business though -- a round whose own walk gives up writes `nav_stuck_<page>.png` too, and
        on 2026-10-08 12:02 a panel round (pythonw, started 12:01:51) put
        nav_stuck_options.png/nav_stuck_other.png into research/frames while PART 12 was looking,
        which read as a leak of ours and turned the whole run red. So a name only counts as leaked
        when it is byte-identical to a dump this probe just wrote into scratch -- that is what
        "the guard let a dump through" actually means, and it leaves another process's files alone.
        """
        added = {n for n in _tree(FRAMES_DIR) if n not in self.before}
        ours = {}
        for n in os.listdir(self.tmp):
            with open(os.path.join(self.tmp, n), "rb") as f:
                ours[hashlib.sha1(f.read()).hexdigest()] = n
        out = []
        for n in sorted(added):
            if not n.startswith(("nav_stuck_", "start_live_stuck")):
                continue
            try:
                with open(os.path.join(FRAMES_DIR, n), "rb") as f:
                    h = hashlib.sha1(f.read()).hexdigest()
            except OSError:
                continue
            if h in ours:
                out.append(n)
        return out


def corpus():
    """The pinned whole-screen frames. research/ is no longer the corpus -- it is the working dump,
    and globbing it made every forensic frame both "this run's evidence" and "part of a regression",
    so nothing could ever be cleaned. tools/evidence.py builds this set and says why."""
    out = []
    for p in sorted(glob.glob(str(NAV / "*.png"))):
        try:
            im = Image.open(p)
        except Exception:
            continue
        if im.size == (1280, 720):
            out.append((Path(p), np.asarray(im.convert("RGB"))))
    return out


def part0():
    """The corpus itself: every pinned frame must still read as the page it was pinned for."""
    manifest = json.loads((NAV / "MANIFEST.json").read_text(encoding="utf-8"))["frames"]
    have = {p.name: calib.screen(img) for p, img in corpus()}
    lost = {n: (want, have.get(n)) for n, want in manifest.items() if have.get(n) != want}
    extra = sorted(set(have) - set(manifest))
    ok = not lost and not extra
    print(f"{len(manifest)} pinned frames, {len(set(manifest.values()))} page verdicts; "
          f"drifted: {lost or '无'}" + (f"; unmanifested: {extra}" if extra else ""))
    print("PART 0 " + ("PASS" if ok else "FAIL"))
    return ok


def part1():
    frames = corpus()
    stuck = [img for p, img in frames if p.name in STUCK]
    off = calib._bond_detail
    try:
        now = {p: calib.screen(img) for p, img in frames}
        calib._bond_detail = lambda img: False
        was = {p: calib.screen(img) for p, img in frames}
    finally:
        calib._bond_detail = off
    changed = sorted(p.name for p in now if now[p] != was[p])
    strangers = [n for n in changed if n not in STUCK and n not in ALSO_SAME_PAGE]
    ok = (len(stuck) == 2
          and all(was[p] == "other" and now[p] == "rewards" for p in now if p.name in STUCK)
          and not strangers)
    print(f"frames: {len(frames)}; the popup reads "
          f"{[now[p] for p in now if p.name in STUCK]} with the rule, "
          f"{[was[p] for p in now if p.name in STUCK]} without it")
    print(f"verdicts the rule changes: {changed}"
          + (f" -- strangers: {strangers}" if strangers else ""))
    print("PART 1 " + ("PASS" if ok else f"FAIL: strangers={strangers}"))
    return ok


def part2():
    frame = next(img for p, img in corpus() if p.name == STUCK[0])
    blinded = frame.copy()
    blinded[18:50, 562:720] = 0
    lit = calib._bond_detail(frame)
    dark = calib._bond_detail(blinded)
    pinned = calib.BOND_TITLE_MIN
    try:
        # -1, not 0: the painted-out box reads exactly 0 white pixels and the gate is a strict >.
        calib.BOND_TITLE_MIN = -1
        dark_unguarded = calib._bond_detail(blinded)
    finally:
        calib.BOND_TITLE_MIN = pinned
    ok = lit and not dark and dark_unguarded
    print(f"the popup frame: claimed {lit}; with its title painted out: claimed {dark}; "
          f"title gate pinned off: claimed {dark_unguarded}")
    print("PART 2 " + ("PASS" if ok else "FAIL"))
    return ok


def part3():
    """The second RANK UP layout: the lower title band, and the tap point taken off its pill."""
    frames = corpus()
    have = {p.name for p, _ in frames} & set(RANKUP)
    if have != set(RANKUP):
        print(f"PART 3 FAIL: the corpus is missing {sorted(set(RANKUP) - have)}")
        return False
    lvl = calib._level_rankup
    try:
        now = {p: calib.screen(img) for p, img in frames}
        calib._level_rankup = lambda img: False          # the tree as it shipped before this rule
        was = {p: calib.screen(img) for p, img in frames}
    finally:
        calib._level_rankup = lvl
    changed = sorted(p.name for p in now if now[p] != was[p])
    # The two dumps the walk actually left are still in the corpus (the fixtures are copies of
    # them), and they are the same page -- PART 1 grants its originals the same way.
    strangers = [n for n in changed if n not in RANKUP and n not in ALSO_SAME_PAGE]
    img = next(im for p, im in frames if p.name == RANKUP[0])
    x, y = calib.rankup_ok(img)
    pill = calib._rankup_pill(img)
    # The historical point is not a near miss: it lands 100 px below the pill, on the scrim, which
    # is why recognising the page without moving the tap would still leave the walk sitting there.
    scrim = tuple(int(v) for v in img[calib.RANKUP_OK[1], calib.RANKUP_OK[0]])
    ok = (all(now[p] == "rankup" and was[p] == "other" for p in now if p.name in RANKUP)
          and not strangers
          and (x, y) == (int(pill[1]), int(pill[0]))
          and abs(y - calib.RANKUP_OK[1]) >= 60
          and max(scrim) < 60)
    print(f"the splash reads {[now[p] for p in now if p.name in RANKUP]} with the branch, "
          f"{[was[p] for p in now if p.name in RANKUP]} without it")
    print(f"verdicts the branch changes: {changed}"
          + (f" -- strangers: {strangers}" if strangers else ""))
    print(f"tap point from the pill: {x},{y}; the historical {calib.RANKUP_OK} lands on scrim "
          f"rgb{scrim} (100 px below the pill)")
    print("PART 3 " + ("PASS" if ok else "FAIL"))
    return ok


def part4():
    """The 演出 load interstitial, which wears 结算's top-right corner better than 结算 does."""
    frames = corpus()
    have = {p.name for p, _ in frames} & set(LOAD)
    if have != set(LOAD):
        print(f"PART 4 FAIL: the corpus is missing {sorted(set(LOAD) - have)}")
        return False
    ld = calib._loading
    try:
        now = {p: calib.screen(img) for p, img in frames}
        calib._loading = lambda img: False          # the tree as it shipped before this branch
        was = {p: calib.screen(img) for p, img in frames}
    finally:
        calib._loading = ld
    # `nav_stuck_result.png` is the same page in two directories (the live dump name and an
    # archived copy), so it is allowed to change alongside its fixtures.
    allowed = set(LOAD) | {"nav_stuck_result.png"}
    changed = sorted(str(p) for p in now if now[p] != was[p])
    strangers = [n for n in changed if Path(n).name not in allowed]
    ok = (all(now[p] == "loading" and was[p] == "result" for p in now if p.name in LOAD)
          and not strangers)
    print(f"the load reads {[now[p] for p in now if p.name in LOAD]} with the branch, "
          f"{[was[p] for p in now if p.name in LOAD]} without it (it wore the 结算 corner)")
    print(f"verdicts the branch changes: {len(changed)} frames"
          + (f" -- strangers: {strangers}" if strangers else ""))
    print("PART 4 " + ("PASS" if ok else "FAIL"))
    return ok


def part5():
    """The 详情/下一步 layout of the 结算 EXP page: the five cards name it, not the buttons."""
    frames = corpus()
    have = {p.name for p, _ in frames} & set(EXPV)
    if have != set(EXPV):
        print(f"PART 5 FAIL: the corpus is missing {sorted(set(EXPV) - have)}")
        return False

    def legacy(img):
        """The 主页-slot test this replaced -- it matched no pale 主页 on this layout."""
        r = img[646:674, 1030:1150].reshape(-1, 3).mean(0)
        l = img[646:674, 760:880].reshape(-1, 3).mean(0)
        if not (l[2] > 190 and l.min() > 150):
            return False
        orange = r[0] > 200 and r[1] > 120 and r[2] < 160 and r[0] - r[2] > 60
        blue = r[2] > 190 and r[2] - r[0] > 40
        return bool(orange or blue)

    shipped = calib._exp_page
    pill = calib._go_pill_wide
    try:
        now = {p: calib.screen(img) for p, img in frames}
        # 2026-10-20 之前那棵树：`_exp_page` 没有第三支，而 `select` 也还没有那颗宽药丸的否决
        # （`_go_pill_wide`）。两件一起摘掉，`was` 才是这一页真正撞上的那个旧判决（乐曲選択）。
        calib._exp_page, calib._go_pill_wide = legacy, (lambda _img: False)
        was = {p: calib.screen(img) for p, img in frames}
    finally:
        calib._exp_page, calib._go_pill_wide = shipped, pill
    # 多人那一局（mp2）的同一页两版也在语料里：`mp_exp_cards_a.png` 是 详情/下一步，旧规则读不出
    # 它（它就是「被这道改动改判的帧」之一），`mp_exp_totals_a.png` 是 主页/再次演出、两套规则都读 exp。
    allowed = set(EXPV) | {"now_after_bond_close.png",
                           "mp_exp_cards_a.png", "mp_exp_totals_a.png",
                           # 2026-10-20: 结算分数页后面那一页（PART 21）。它也是被这条改动改判的帧 ——
                           # 旧规则读 `select`，现在靠 `_exp_page` 的第三支（那颗宽药丸）认成 `exp`。
                           "navgates_after_result_a.png",
                           # 2026-10-20 深夜（PART 22）：活动主页那一族在 `options`/`exp` 之前就被
                           # `event` 认领了 —— 两棵树都不是它的判决，所以这两帧不是「被这条改动改判」。
                           # 它们是「演出那颗蓝 + 结算族那颗宽药丸」同时在的帧（全库只有这两帧）。
                           "navgates_event_home_a.png", "hud_g453_great39.png"}
    changed = sorted(str(p) for p in now if now[p] != was[p])
    strangers = [n for n in changed if Path(n).name not in allowed]
    img = next(im for p, im in frames if p.name == EXPV[0])
    blinded = img.copy()
    blinded[480:520] = 0                      # erase the five EXP bars, leave the buttons alone
    # 2026-10-20：`_exp_page` 现在还有第三支 —— 结算族那颗宽药丸（PART 21 的那一页）。它就在五条
    # 青条下面，所以「把青条涂掉、claim 必须跟着掉」这条牙要先把它摘掉，才问得出它本来问的那句话：
    # **五条青条自己撑不撑得住这个 claim**。
    try:
        calib._go_pill_wide = lambda _img: False
        cards_carry = calib._exp_page(img) and not calib._exp_page(blinded)
    finally:
        calib._go_pill_wide = pill
    # The totals page (pale 主页, no cards) is the other half of the union: it read "exp" under
    # the old rule and must keep doing so. Narrowing the test to the cards alone dropped it, and
    # it then wore 乐曲选择's identity exactly like the cards page did -- the pick's own guard is
    # what caught that, one round later, in 14 s instead of 150.
    home = next((im for p, im in frames if p.name == EXP_HOME), None)
    home_kept = home is not None and bool(calib._exp_page(home) and legacy(home))
    ok = (all(now[p] == "exp" and was[p] == "select" for p in now if p.name in EXPV)
          and not strangers and cards_carry and home_kept)
    print(f"the layout reads {[now[p] for p in now if p.name in EXPV]} with the cards test, "
          f"{[was[p] for p in now if p.name in EXPV]} with the old 主页 slot "
          f"(it wore 乐曲选择, and 随机演奏 waited on a jacket that is not there)")
    print(f"verdicts the change moves: {len(changed)} frames"
          + (f" -- strangers: {strangers}" if strangers else ""))
    print(f"the five bars carry the claim (buttons painted out still claim it: "
          f"{not cards_carry}); the totals page reads exp under both rules: {home_kept}")
    print("PART 5 " + ("PASS" if ok else "FAIL"))
    return ok


def part6():
    """首页 by its opaque chrome: a repainted banner must not be able to move the verdict."""
    frames = corpus()
    if HOME_FRAME not in {p.name for p, _ in frames}:
        print(f"PART 6 FAIL: the corpus is missing {HOME_FRAME}")
        return False

    def legacy_home(img):
        """The cue this replaced: the RANK plate at the top left, which is translucent."""
        b = img[17:73, 40:110].reshape(-1, 3).astype(int).mean(0)
        label = img[633:668, 1040:1120]
        return bool(b.min() > 130 and abs(b[0] - b[2]) < 25
                    and (label.min(2) > 170).mean() > 0.20)

    def cue_screen(test):
        """The shipped chain with only the 首页 cue swapped, so a frame that moves is a frame the
        *cue* decides -- not one a later slot happens to claim first. (2026-10-08: the old
        legacy-order replay also stopped at 商店 before 首页 could be asked, so 抽中封面
        mp_matching_b.png -- read "shop" then, read "matching" now by the 多人 rule -- showed up as
        a stranger of a change it has nothing to do with.)"""
        saved = calib._home
        calib._home = test
        try:
            return {p.name: calib.screen(im) for p, im in frames}
        finally:
            calib._home = saved

    now_verdicts = cue_screen(calib._home)
    with_old_cue = cue_screen(legacy_home)
    moved = {n: (with_old_cue[n], now_verdicts[n]) for n in now_verdicts
             if with_old_cue[n] != now_verdicts[n]}
    home_img = next(im for p, im in frames if p.name == HOME_FRAME)
    reproduced = moved.get(HOME_FRAME) == ("shop", "home")

    # The dependency set: the rule may read nothing but the three discs and the 演出 word, so a
    # background repaint -- which is what broke the plate -- cannot reach it. Paint the whole
    # frame flat and paste those four boxes back: still 首页. Then take one box away at a time:
    # each of the three discs must carry weight, or it is decoration and the rule is one button
    # deep.
    def painted(out=None):
        flat = np.full_like(home_img, 90)
        for y0, y1, x0, x1 in calib.HOME_DISCS:
            flat[y0:y1, x0:x1] = home_img[y0:y1, x0:x1]
        y0, y1, x0, x1 = calib.HOME_LABEL
        flat[y0:y1, x0:x1] = home_img[y0:y1, x0:x1]
        if out is not None:
            ys, ye, xs, xe = calib.HOME_DISCS[out]
            flat[ys:ye, xs:xe] = 90
        return flat

    survives = calib._home(painted()) and not legacy_home(painted())
    each_carries = all(not calib._home(painted(i)) for i in range(len(calib.HOME_DISCS)))
    strangers = sorted(name for name in moved if name != HOME_FRAME)

    # 演出首页 shares the resource bar, so it shares all three blue discs -- measured
    # 1.0 / 0.86 / 0.79 on the captured frame. What keeps the two pages apart is the second leg,
    # the 演出 word, and 首页 is asked FIRST. If that leg ever goes, livehome is claimed as 首页
    # and the walk taps LIVE_TILE where it means to tap 自由演出. So the pair must separate both
    # ways, and it must be the label leg that does it.
    live_img = next((im for p, im in frames if p.name == LIVE_FRAME), None)
    discs_only = lambda a: sum(1 for y0, y1, x0, x1 in calib.HOME_DISCS
                               if ((a[y0:y1, x0:x1, 2].astype(int)
                                    - a[y0:y1, x0:x1, 0].astype(int)) > 40).mean() > 0.55) == 3
    apart = (live_img is not None and calib.screen(live_img) == "livehome"
             and not calib._home(live_img) and not calib._livehome(home_img))
    label_carries = live_img is not None and discs_only(live_img.astype(int)) \
        and not calib._home(live_img)

    # 2026-10-09: the label leg is not enough on its own. The 演出首页 grew the same white word in
    # that box -- 0.431 / 0.555 on tonight's captured frames against 0.000 in this fixture -- and
    # 首页 is asked first, so the walk read the 演出首页 as 首页 and tapped LIVE_TILE there, stacking
    # three unreadable pages on top of itself (mp19's 03:14 and 03:43 rounds, both lost).  `_home`
    # now ends with `and not _livehome(img)`.  So paint that box white on the fixture: the page
    # must still read livehome, and with the veto taken back out the very same frame is 首页 --
    # which is what makes this a tooth and not a description.
    ly0, ly1, lx0, lx1 = calib.HOME_LABEL
    grown = live_img.copy()
    grown[ly0:ly1, lx0:lx1] = 255
    grew_label = (grown[ly0:ly1, lx0:lx1].min(2) > 170).mean()
    grown_ok = (grew_label > calib.HOME_LABEL_WHITE and discs_only(grown.astype(int))
                and calib.screen(grown) == "livehome")

    def no_veto(a):
        """`_home` before the veto: the three discs and the label box, nothing else."""
        b = a.astype(int)
        n = sum(1 for y0, y1, x0, x1 in calib.HOME_DISCS
                if ((b[y0:y1, x0:x1, 2] - b[y0:y1, x0:x1, 0]) > 40).mean() > calib.HOME_DISC_BLUE)
        y0, y1, x0, x1 = calib.HOME_LABEL
        return bool(n == len(calib.HOME_DISCS)
                    and (b[y0:y1, x0:x1].min(2) > 170).mean() > calib.HOME_LABEL_WHITE)

    saved_home = calib._home
    calib._home = no_veto
    try:
        veto_bites = calib.screen(grown) == "home"
    finally:
        calib._home = saved_home

    ok = (reproduced and survives and each_carries and not strangers
          and calib.screen(home_img) == "home" and apart and label_carries
          and grown_ok and veto_bites)
    print(f"the warm banner is the bug: 首页 read {moved.get(HOME_FRAME)} under the old cue "
          f"(商店's only action is a tap at {calib.SHOP_HOME})")
    print(f"verdicts the change moves: {len(moved)} frame(s)"
          + (f" -- strangers: {strangers}" if strangers else ""))
    print(f"artwork painted out, chrome kept: still 首页 ({survives}); "
          f"each of the three discs carries weight: {each_carries}")
    print(f"演出首页 shares all three discs, so the 演出 word is what separates them: "
          f"{label_carries}; and the pair reads apart: {apart}")
    print(f"演出首页 with that box painted white ({grew_label:.3f} > {calib.HOME_LABEL_WHITE}) still "
          f"reads livehome: {grown_ok}; without the `_livehome` veto the same frame is 首页: "
          f"{veto_bites}")
    print("PART 6 " + ("PASS" if ok else "FAIL"))
    return ok


def part7():
    """The walk-back: a finished round must stop at 乐曲选择, one tap short of another LIVE."""
    frames = {p.name: im for p, im in corpus()}
    need = ("result_a43.png", "navgates_exp_detail_a.png", "nav_stuck_select.png")
    missing = [n for n in need if n not in frames]
    if missing:
        print(f"PART 7 FAIL: the corpus is missing {missing}")
        return False
    script = [frames[n] for n in need]

    taps = []
    real_grab, real_tap = calib.grab, calib.tap
    guard = _DumpGuard()
    try:
        guard.__enter__()
        seq = list(script)

        def grab():
            return seq.pop(0) if seq else script[-1]

        def tap(x, y, *a, **k):
            taps.append((int(x), int(y)))

        calib.grab, calib.tap = grab, tap
        ok = calib.start_live(None, log=lambda *_: None, timeout=20.0, stop_at_select=True)
        back = list(taps)

        taps.clear()
        seq = list(script)
        again = calib.start_live(None, log=lambda *_: None, timeout=20.0)
        through = list(taps)
    finally:
        guard.__exit__()
        calib.grab, calib.tap = real_grab, real_tap

    next_step = (1080, 660)                       # 下一步 on 结算
    retry = tuple(int(v) for v in calib.EXP_RETRY)
    go = tuple(int(v) for v in calib.SONG_GO)     # 确定 on 乐曲选择: one LIVE, unasked for
    stops = ok and back == [next_step, retry]
    # Without the guard the walk keeps pressing 确定 on the select page -- the scripted source
    # holds that page up, which is exactly what a real one does for the second it takes to load.
    presses_on = (not again) and go in through
    # 这一趟「在选曲页停不下来」正是会让走页落盘 nav_stuck_select.png 的那种剧本：取证必须落在
    # scratch 里（`seen` 非空 = 真的写了），工作目录一个 nav_stuck_* 都不许多出来。
    dumped, leaked = guard.seen, guard.leaked()
    print(f"走回去 {back} -> 停在选曲页: {stops}; 不带 stop_at_select 则 {through}"
          f"（多出的一下就是又开一局）: {presses_on}")
    print(f"这两趟确实会落盘：scratch 里 {dumped}（要不为空）；research/frames 多出来的 "
          f"nav_stuck_* {leaked}（要 []）")
    print("PART 7 " + ("PASS" if (stops and presses_on and dumped and not leaked) else "FAIL"))
    return stops and presses_on and bool(dumped) and not leaked


def part8():
    """The field gate itself: every live frame reads live, no other page does, and the refusal waits.

    This gate is what the 暂停 tap of 断AP立即重试 is gated on, and it used to be one colour test:
    on the 14 live frames this corpus pins it fires on 7, and `screen` answers 'options' / 'story' /
    'preset' / 'livehome' for a field that is plainly up. g238 is the cost-- the abort stopped
    firing 1.2 s before, the frame still showed PERFECT 237 and the HP bar, and the restart gave up
    because the page reader did not believe it. The gate is two looks now, and the one that fails
    gets asked again rather than believed.
    """
    manifest = json.loads((NAV / "MANIFEST.json").read_text(encoding="utf-8"))["frames"]
    frames = corpus()
    live = [(p.name, im) for p, im in frames if manifest.get(p.name) == "live"]
    others = [(p.name, im) for p, im in frames if manifest.get(p.name) != "live"]
    missed = [calib.screen(im) for _, im in live]
    core_blind = [n for n, im in live if not calib._lines_core(im)]
    band_blind = [n for n, im in live if not calib._lines_band(im)]
    false = [n for n, im in others if calib._magenta_lines(im)]
    ok_gate = (len(live) >= 10 and all(v == "live" for v in missed)
               and len(core_blind) >= 5 and not false)

    field = next(im for _, im in live)
    not_field = next(im for n, im in others if n.startswith("result_"))
    real_grab = calib.grab
    try:
        seen = []
        seq = iter([not_field, not_field, field])

        def flaky():
            img = next(seq)
            seen.append(img)
            return img

        calib.grab = flaky
        recovered = calib.in_live(polls=5, wait=0.0)
        never = []
        calib.grab = lambda: (never.append(1) or not_field)
        refused = calib.in_live(polls=5, wait=0.0)
    finally:
        calib.grab = real_grab
    ok_poll = recovered and not refused and len(seen) == 3 and len(never) == 5

    print(f"{len(live)} 张 LIVE 帧全读 live: {all(v == 'live' for v in missed)}；"
          f"旧的单看一次会漏 {len(core_blind)} 张（换色带单独会漏 {len(band_blind)} 张）；"
          f"其余 {len(others)} 张非 LIVE 帧被误认成场的: {false or '没有'}")
    print(f"两次糊帧后第三次看清就敢按: {recovered}（看了 {len(seen)} 次）；"
          f"五次都不像场子就坚决不按: {not refused}（试了 {len(never)} 次）")
    print("PART 8 " + ("PASS" if ok_gate and ok_poll else "FAIL"))
    return ok_gate and ok_poll


def part9():
    """暂停面板问在弹窗判据之前 —— g296 与 g300 各因此白丢一局。

    `_dialog` 认暂停面板用的是三颗亮药丸（356/640/923），精确；但这一张暂停帧底下还多一条宽的浅色
    横条，`_modal_close` 把它当成奖励弹窗的 关闭 —— 于是旧顺序下 `screen()` 回 'rewards'，
    `restart_to_t0` 走进 "no pause panel to restart from"，断AP重试把这一局整局放弃（两局都 rc=1、
    不耗火，但那一次 GREAT 本来是可以重开救回来的）。语料里此前**一张暂停面板都没有**，所以这条
    顺序从来没人验过 —— 这也是它能活到今天的理由。
    """
    pause = next(im for p, im in corpus() if p.name == "navgates_pause_a.png")
    now = calib.screen(pause)
    collision = bool(calib._modal_close(pause))          # 旧顺序下把这一帧抢走的正是它
    bond = [(p.name, calib._dialog(im), calib.screen(im)) for p, im in corpus()
            if "bond_detail" in p.name]
    ok = (now == "pause" and collision and len(bond) == 2
          and all(d is None and s == "rewards" for _, d, s in bond))
    print(f"暂停面板：现在读 {now!r}（要 'pause'）；`_modal_close` 确实会抢它 = {collision}"
          f"（这就是旧顺序读成 'rewards' 的那个判据）")
    for n, d, s in bond:
        print(f"  {n}: _dialog={d} screen={s!r}")
    print("PART 9 " + ("PASS" if ok else "FAIL"))
    return ok


def part10():
    """选曲页在 EASY 选中时不许被读成 `preset` —— 这条判据把用户的歌单点乱过。

    `preset`（应用默认设置弹窗）的旧判据只有一条：`_blue(img, 770, 573)`（弹窗的 OK 是蓝的）。
    而**选曲页的难度药丸行**里，选中的 EASY 蓝药丸正好压在 (770,573) 上 —— 于是 2026-10-04 夜里
    一局把选曲页读成 preset，走页按 preset 分支去点“关闭”(510,573)，那个坐标在选曲页上是**歌单的
    一行**：二十来下把用户的选曲点乱，最后放弃（g315）。语料里那张 `navgates_select_easy.png`
    就是当时的画面。
    """
    frame = next(im for p, im in corpus() if p.name == "navgates_select_easy.png")
    now = calib.screen(frame)
    collision = bool(calib._blue(frame, 770, 573))       # 旧判据在这一帧上确实是 True
    pills = calib._pills(frame)                          # 而弹窗的两颗药丸并不存在
    # 牙：把「必须有那两颗药丸」这一条关掉，这一帧就该退回被抢走的旧答案。
    real = calib._pills_at
    try:
        calib._pills_at = lambda *a, **k: True            # 旧形状：只看蓝点
        teeth = calib.screen(frame)
    finally:
        calib._pills_at = real
    ok = now == "select" and collision and pills == [] and teeth == "preset"
    print(f"EASY 选中的选曲页：现在读 {now!r}（要 'select'）；旧判据 `_blue(770,573)` 会抢它 = "
          f"{collision}；这一帧的药丸 = {pills}（弹窗的 502/785 不在）")
    print(f"  把「必须有两颗药丸」关掉 -> {teeth!r}（旧形状必须是 'preset'，这一关才有牙）")
    print("PART 10 " + ("PASS" if ok else "FAIL"))
    return ok


def part11():
    """加成火力读数：一帧的水平位移、两位数、越界，以及读不出时按能打处理。

    `fire_power` 从前是**两个写死的 x 窗口**（1035..1070 / 1078..1112）。那套在实机帧上读得出
    `9/15`，但 `nav_stuck_band.png`（同一页、整串右移 4~5 px）读出来是 None —— 一帧的位移就够让
    门静默失效（读不出按能打处理，所以不卡住，只是门没了）。现在按帧找墨迹列 run、在斜杠处切开
    （`'/'` 是这里唯一「上部比下部更靠右」的字形，`1`/`7` 都反过来），于是位移免疫、两位数
    （右对齐、往斜杠左边长）也读得出。本部分只用语料里那一帧 ＋ 它自己的字形：离线、无窗口、无设备。
    """
    import resultread as rr

    band = next(im for p, im in corpus() if p.name == "nav_stuck_band.png")
    base = calib.fire_power(band)
    shifted = [calib.fire_power(np.roll(band, d, axis=1)) for d in (5, -5)]
    ok_shift = base == (0, 10) and shifted == [base, base]

    y0, y1 = calib.FIRE_Y
    one = band[y0:y1 + 2, 1086:1091].copy()        # this frame's cap is "10": its '1'
    zero = band[y0:y1 + 2, 1094:1104].copy()       # ...and its '0'
    bg = band[y0:y1 + 2, 1072:1073].copy()         # the chip's own dark fill, just left of the '/'

    def synth(glyphs):
        img = band.copy()
        img[y0:y1 + 2, 1044:1072] = np.repeat(bg, 28, axis=1)     # wipe this frame's current '0'
        for g, x in glyphs:
            img[y0:y1 + 2, x:x + g.shape[1]] = g
        return img

    ten = synth([(one, 1050), (zero, 1058)])       # 当前火力 "10", equal to the cap
    eleven = synth([(one, 1050), (one, 1058)])     # "11" > cap "10"
    blank = band.copy()
    blank[y0:y1 + 2, 1035:1126] = np.repeat(bg, 91, axis=1)
    two, over, gone = (calib.fire_power(i) for i in (ten, eleven, blank))
    ok_guard = two == (10, 10) and over is None and gone is None

    # 牙 1: what the two frozen windows read on this very frame -- why the reader changed. The
    # cap window still catches the shifted "10", but the current window cuts the shifted '0' in
    # half, so the frozen reader answered None (a gate that silently stops gating).
    mn = band.min(axis=2)
    m = (mn > calib.FIRE_MASK) & ((band.max(axis=2) - mn) < calib.FIRE_FLAT)
    tpl = rr.load_templates()
    c0, _ = rr.read_cell(m, y0, y1 + 1, 1035, 1070, tpl, min_h=calib.FIRE_MIN_H)
    c1, _ = rr.read_cell(m, y0, y1 + 1, 1078, 1112, tpl, min_h=calib.FIRE_MIN_H)
    old = (rr._num(c0), rr._num(c1))
    old_read = None if None in old else old
    # 牙 2: switch each new rule off once; the read has to collapse both times.
    lean, digs = calib.FIRE_SLASH_LEAN, calib.FIRE_DIGITS
    try:
        calib.FIRE_SLASH_LEAN = 99
        collapse_lean = calib.fire_power(band) is None
        calib.FIRE_DIGITS = (1, 3)
        collapse_digs = calib.fire_power(ten) is None
    finally:
        calib.FIRE_SLASH_LEAN, calib.FIRE_DIGITS = lean, digs

    ok = (ok_shift and ok_guard and old_read is None and collapse_lean and collapse_digs)
    print(f"语料帧读数 {base}（要 (0, 10)）；整帧平移 ±5 px 后: {shifted}（都要等于它）")
    print(f"两位数：读数 {two}（要 (10, 10)）；越界的 '11' -> {over}（要 None）；读数区抹空 -> "
          f"{gone}（要 None，读不出就按能打处理）")
    print(f"牙：旧的写死窗口在这一帧上按格读 {old} -> 整门 {old_read}（要 None：换个读法就是因为"
          f"它会在位移后静默失效）；斜杠规则关掉 -> 塌了 {collapse_lean}；两位数上限关掉 -> "
          f"塌了 {collapse_digs}")
    print("PART 11 " + ("PASS" if ok else "FAIL"))
    return ok
def part12():
    """走页的三条硬规矩：回家路上不许按「开打」，进 LIVE 那一路按不动要有界地补按，
    演出开始按出去之后的「只看不按」不许没有尽头。

    g347（00:47）与 g446（15:25）是同一个形状：进 LIVE 的走页在 乐队确认页 按下 演出开始 之后页面
    540+ 次读数不动（150 s 到点报 could not reach a LIVE），**回家那趟又按了一次 演出开始** ——
    把「回家」走成了「开打」，`tail` 之后只观望，45 s 后报「没能走回选曲页」。四份脚本：
    ① 回家遇到 乐队确认页 按左上角的返回箭头（`BAND_BACK`，用户 m02645）、页面换成 乐曲选择 才算
    到家，而**不按**演出开始；② 同一页不带 `stop_at_select` 时必须按 演出开始（证明①不是「谁都不
    按」），而且一下都不许按返回箭头；③ 页面卡在 乐队确认 会补按，但**有界**：`1 + START_RETRIES`
    次之后不再按；④ 按下之后页面转成现场，立刻返回、不再补按（补按不许打搅一局正常的开打）。

    ⑤⑥⑦ 是第三条（`TAIL_STUCK_S`，2026-10-08）：`tail` 的「只看不按」对 2~4 s 的载入是对的，
    对一个 **139 s** 的页面就是致命的。g471（2026-10-07 23:56）演出开始按下之后，游戏走的是
    故事解锁 → 商店 → 结算 流程，最后一个读作 `finish` 的页面被「只看不按」白等了 139 s，歌自己
    唱完才到点 —— 判据没错（同一晚 g472/g473 的现场都读得对），错在等待没有上限。⑤ 卡在
    `nav_stuck_finish.png`（g471 落盘的那一页）：连读 `TAIL_STUCK_S` 之后交回通用处理、按的是
    (640, 400)，而演出开始还是只按过那一次；⑥ 卡在 乐曲选择：它的通用处理会按「开一局」的按钮，
    分不清真页还是结算页误读（结算页的蓝色 下一步 就读成 `select`），所以只能认输、一下都不多按；
    ⑦ 一局正常开打里的慢页面（options 连读 20 次 ≈ 5 s，仍在 `TAIL_STUCK_S` 之内）不许被打断。
    """
    frames = {p.name: im for p, im in corpus()}
    need = ("nav_stuck_band.png", "nav_stuck_select.png", "hud_great1.png", "nav_stuck_finish.png",
            "nav_stuck_options.png")
    missing = [n for n in need if n not in frames]
    if missing:
        print(f"PART 12 FAIL: the corpus is missing {missing}")
        return False
    band, select, live, finish, options = (frames[n] for n in need)
    go = tuple(int(v) for v in calib.LIVE_START_BTN)

    real_grab, real_tap = calib.grab, calib.tap
    real_subdir = calib.subdir
    guard = _DumpGuard()
    try:
        guard.__enter__()

        def walk(script, stop, timeout):
            """Run the real walk over a scripted frame source; report (result, taps, log lines)."""
            seq = list(script)
            taps, said = [], []

            def grab():
                return seq.pop(0) if seq else script[-1]

            def tap(x, y, *a, **k):
                taps.append((int(x), int(y)))

            calib.grab, calib.tap = grab, tap
            out = calib.start_live(None, log=said.append, timeout=timeout,
                                   stop_at_select=stop)
            return out, taps, said

        # ① 回家：乐队确认页按左上角的返回箭头（BAND_BACK，用户 m02645），页面换成 乐曲选择 才算到家
        back_ok, back_taps, back_said = walk([band, select], True, 8.0)
        # ② 同一页进 LIVE：必须按，而且卡住时会补按 —— 有界
        fwd_ok, fwd_taps, fwd_said = walk([band], False, 12.0)
        # ③ 按下之后页面转成现场：立刻返回，一下都不多按
        live_ok, live_taps, live_said = walk([band, live], False, 8.0)
        # ④ 回家撞进 LIVE：不许报「已回家」
        stuck_ok, stuck_taps, stuck_said = walk([live], True, 4.0)
        # ⑤ g471 那一页：读作 finish、通用处理只是「点下一步」—— 逃生要把它交回通用处理
        esc_ok, esc_taps, esc_said = walk([band, finish], False, calib.TAIL_STUCK_S + 4.0)
        # ⑥ 卡在「通用处理会开一局」的页面：逃生只能认输，一下都不许多按
        give_ok, give_taps, give_said = walk([band, select], False, calib.TAIL_STUCK_S + 4.0)
        # ⑦ 一局正常开打里的慢页面：options 连读 20 次（约 5 s，够不着 TAIL_STUCK_S）
        slow_ok, slow_taps, slow_said = walk([band] + [options] * 20 + [live], False, 20.0)
    finally:
        guard.__exit__()
        calib.grab, calib.tap = real_grab, real_tap

    watched = any("按左上角的返回箭头" in t for t in back_said)
    goes = [t for t in fwd_taps if t == go]
    bounded = len(goes) == 1 + calib.START_RETRIES
    says_retry = sum(1 for t in fwd_said if "演出开始没反应" in t) == calib.START_RETRIES
    one_tap = live_taps == [go] and live_ok
    not_home = (stuck_ok is False and stuck_taps == []
                and any("回家路上撞进 LIVE" in t for t in stuck_said))
    # 这四趟里有三趟是「页面一动不动」的剧本，也就是说它们真的会落盘取证帧。它们必须落在
    # scratch 里（`dumped` 非空），工作目录一个 nav_stuck_* 都不许多。牙 = 守卫本身：把
    # `calib.subdir` 当模块属性解析一次，带守卫要落在 scratch、撤掉守卫要落回 research/frames；
    # 两条路径相同就说明这个守卫是装饰（2026-10-07 那三个漏出来的文件就是这么留下的）。
    dumped, leaked = guard.seen, guard.leaked()
    with _DumpGuard() as probe:
        guarded = Path(calib.subdir(calib.FRAMES))
        guard_path = probe.tmp
    calib.subdir = real_subdir
    unguarded = Path(calib.subdir(calib.FRAMES))
    guard_bites = guarded == Path(guard_path) and unguarded == FRAMES_DIR

    # ⑤ 逃生后按的是 finish 页的 (640, 400)，演出开始仍然只按过那一次；⑥ 会「开一局」的页面
    # 一下都不按、直接认输；⑦ 慢页面不许被逃生打断
    escaped = any("不再是载入，交回通用处理" in t for t in esc_said)
    esc_once = esc_taps.count((640, 400)) == 1 and esc_taps.count(go) == 1
    gave_up = any("只能按开一局的按钮" in t for t in give_said)
    quiet = not any(("交回通用处理" in t or "放弃等 LIVE" in t) for t in slow_said)

    ok = (back_ok and back_taps == [calib.BAND_BACK] and watched and bounded and says_retry
          and calib.BAND_BACK not in fwd_taps and one_tap
          and not_home and dumped and not leaked and guard_bites
          and esc_ok is False and escaped and esc_once
          and give_ok is False and gave_up and give_taps == [go]
          and slow_ok and slow_taps == [go] and quiet)
    print(f"回家遇到乐队确认页：按下 {back_taps}（要 {[calib.BAND_BACK]} —— 左上角的返回箭头），"
          f"仍停在选曲页 {back_ok}，日志认了那一按 {watched}")
    print(f"同一页进 LIVE：按下 {len(goes)} 次（要 1+{calib.START_RETRIES} 次，补按有界），"
          f"补按日志 {says_retry}，返回 {fwd_ok}（页面没动过，要走完超时）；"
          f"前进那趟没按返回箭头 {calib.BAND_BACK not in fwd_taps}")
    print(f"按下后转成现场：按下 {live_taps}（要正好一次），返回 {live_ok}")
    print(f"回家撞进 LIVE：返回 {stuck_ok}（要 False，不许报已回家），按下 {stuck_taps}（要 []），"
          f"日志认了这件事 {not_home}")
    print(f"四趟里会落盘的那些：scratch 里 {dumped}（要不为空）；research/frames 多出来的 "
          f"nav_stuck_* {leaked}（要 []）；守卫带上去 -> {guarded.name if guarded.is_dir() else guarded}"
          f"、撤下来 -> {unguarded}（要 {FRAMES_DIR}）: {guard_bites}")
    print(f"⑤ 卡在 finish（g471 那一页）：按下 {esc_taps}（要 [演出开始, (640,400)]），"
          f"日志认了逃生 {escaped}，返回 {esc_ok}（要 False，页面一直没动）")
    print(f"⑥ 卡在 乐曲选择：按下 {give_taps}（要只有那一次演出开始），日志认了「只能认输」"
          f"{gave_up}，返回 {give_ok}（要 False）")
    print(f"⑦ 慢页面（options 连读 20 次）不被打断：按下 {slow_taps}（要只有那一次演出开始），"
          f"返回 {slow_ok}（要 True），日志里没有逃生 {quiet}")
    print("PART 12 " + ("PASS" if ok else "FAIL"))
    return ok


def part13():
    """随机选曲交出去的是「路径」：`--random` 那一路把谱面事件表喂给 `chart_events`。

    2026-10-07：`--random` 连打三局（g464/g465/g466）全在**开打之后**崩在调用点 —— 它把
    `pick_random` 已经 `json.load` 好的 list 当路径传给了 `chart_events`，而后者第一件事就是
    `hits_path.replace(".hits.json", ".raw.json")` ⇒
    `AttributeError: 'list' object has no attribute 'replace'`。三局全丢，且异常抛在 LIVE 已经
    开打之后：`finally` 里的回家走查撞进那局没人按的 LIVE，45 s 后报「没能走回选曲页，游戏停在
    原处」。四份脚本：① 猴补屏幕与按键跑**真的** `pick_random`，要求交出的 dict 带 `path`
    （存在的 `.hits.json`）与 `hits`（list）；② 同一份 dict 喂 `chart_events`：`path` 要读出
    **非空**事件表；③ 反事实 —— 把 `hits`（list）喂进去必须原样复现那条 `AttributeError`
    （修前的形状）；④ 源码钉：`tools/run.py` 里每个 `chart_events(...)` 的实参都不许是
    `hit_pick["hits"]` 这种「已加载的 list」，且这条钉对把旧写法放回去的变异源码必须变红。
    """
    import ast
    import run

    def is_pick_hits(node):
        """`hit_pick["hits"]`，或者把它包在 `if args.random else ...` 里的那种写法。"""
        if isinstance(node, ast.IfExp):
            return is_pick_hits(node.body) or is_pick_hits(node.orelse)
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                and node.value.id == "hit_pick"):
            k = node.slice
            return isinstance(k, ast.Constant) and k.value == "hits"
        return False

    def offenders(src):
        """每个把已加载的 hits（list）当路径的 `chart_events(...)` 实参。"""
        bad = []
        for node in ast.walk(ast.parse(src)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "chart_events"):
                continue
            bad += [ast.unparse(a) for a in node.args if is_pick_hits(a)]
        return bad

    # ① 脚本化的屏幕：页面先显示一首、随机选曲之后落到另一首，两首都是库里真有的谱。
    seen = []
    real_read, real_tap = run._select_read, run.adb_tap
    try:
        def read(budget=5.0, step=0.35, differs=None):
            seen.append(differs)
            return {"musicId": 100054 if len(seen) == 1 else 100056,
                    "diff": "expert", "score": 0.99, "gap": 0.53}

        run._select_read = read
        run.adb_tap = lambda *a, **k: None
        pick = run.pick_random(log=lambda *a: None, state={})
    finally:
        run._select_read, run.adb_tap = real_read, real_tap

    path = pick.get("path") if isinstance(pick, dict) else None
    hits = pick.get("hits") if isinstance(pick, dict) else None
    path_ok = (isinstance(path, str) and path.endswith(".hits.json")
               and (ROOT / path).exists()
               and isinstance(hits, list) and len(hits) > 0)

    # ② 同一份 dict 交给发货的调用点要喂的东西：路径。
    ev, summ = run.chart_events(path) if path_ok else ([], "")
    reads_ok = len(ev) > 0 and "技能" in summ

    # ③ 反事实：修前传的就是这个 list。
    raised = ""
    try:
        run.chart_events(hits)
    except AttributeError as e:
        raised = str(e)
    list_dies = raised == "'list' object has no attribute 'replace'"

    # ④ 源码钉 + 牙：把旧写法放回去，同一条检查必须点出它。
    src = (ROOT / "tools" / "run.py").read_text(encoding="utf-8")
    old = "        events, ev_summary = chart_events(hits_path)"
    new = ('        events, ev_summary = chart_events('
           'hit_pick["hits"] if args.random else args.hits)')
    mutant = src.replace(old, new)
    bad = offenders(src)
    tooth = mutant != src and len(offenders(mutant)) == 1

    ok = path_ok and reads_ok and list_dies and bad == [] and tooth
    print(f"随机选曲交出的 dict：path {path!r}（是存在的 .hits.json {path_ok}）、"
          f"hits 是 {type(hits).__name__}（{len(hits) if isinstance(hits, list) else 0} 条）")
    print(f"同一份 dict 喂 chart_events：path 读出 {len(ev)} 条事件（{summ[:24]!r}）")
    print(f"反事实：把 hits（list）喂进去 → {raised or '没报错'}（要那条 AttributeError）")
    print(f"源码钉：run.py 里把已加载的 list 当路径的调用点 {bad}（要 []）；"
          f"把旧写法放回去 → {offenders(mutant)}（要正好一条）")
    print("PART 13 " + ("PASS" if ok else "FAIL"))
    return ok


def part14():
    """`--song` 也是「拖一格 + 回读」的闭环：起点、方向、放弃条件与接线都钉住。

    2026-10-07 落地 `tools/songpick.py`（真机 100056 → 100053 三步 7 s）。列表的手势是**概率**的：
    同一个 200 px 拖动 0.60 s 时 +2、0.30 s 时 +24（甩动惯性），起点落在选中行的封面带（y
    303..410）时完全不动，向下拖 560→700 只有 4/6 次动一格 —— 所以循环只做两件事：拖一格、回读
    `gameread.read_song_select()` 说的真话。六份脚本（全部离线，屏幕与手指都脚本化）：① 接线九条
    （argparse 注册 `--song` 与 `--diff`、`on_select` 分派到 `pick_song`、`pick_mode` 认三种选曲
    方式、谱面路径 `hits_path` 两个分支都认、`on_prep` 挂到了 `start_live`、默认难度
    `MULTI_DIFF_DEFAULT` 是 `expert`、误入单人选曲页时按 `SELECT_BACK` 回演出首页、多人这一页
    读的是 `gameread.read_band` 而不是 `read_song_select`），五颗牙各自把其中一条改坏时必须变红；
    ② 快乐路径走 4 格 + 点难度 + 稳定回读，交出的 dict 与
    `pick_random` 同形；③ 被吃掉的一拖会重试、仍然到达；④ 一直拖不动到 `STALL_RETRIES` 次就放弃；
    ⑤ 每次都被推到更远处，连续 `DRIFT_LIMIT` 步没能靠近就放弃；⑥ 难度点不上时也放弃（并在放弃
    前留下取证帧 —— 这里落在临时目录，不碰 research/）。`parse_song` 的写法单独一条。
    """
    import ast
    import tempfile

    import gameread
    import run
    import songpick

    # ---------- ⑦ parse_song：两种写法 + 坏难度 ----------
    plain = run.parse_song("100054")
    with_diff = run.parse_song(" 100054:HARD ")
    raised = ""
    try:
        run.parse_song("100054:banana")
    except SystemExit as exc:
        raised = str(exc)
    except Exception as exc:                                     # noqa: BLE001 - report whatever came
        raised = repr(exc)
    spec_ok = (plain == ("100054", None) and with_diff == ("100054", "hard")
               and "banana" in raised)

    # ---------- ① 接线（源码钉 + 牙） ----------
    def wired(src):
        """接线都在：`--song` 注册、`on_select` 认 `pick_song`、`pick_mode` 认三种选曲方式、
        谱面路径按 `pick_mode` 走（2026-10-08 的多人局把最后一条从 `args.random or args.song`
        改成了 `pick_mode`：多人局也是「走查里自己决定谱面」）、`--diff` 注册且 `MULTI_DIFF_DEFAULT`
        就是用户裁定的 `expert`、`on_prep` 真的挂到了 `start_live` 上（抽中的曲子靠它回到
        run.py —— 那条回调没接上时整局都会走到现场却没谱面）、以及误入**单人选曲页**时按
        `SELECT_BACK` 回演出首页重新进房间（用户 m04029）。"""
        tree = ast.parse(src)
        flag = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "add_argument"
                   and any(isinstance(a, ast.Constant) and a.value == "--song" for a in n.args)
                   for n in ast.walk(tree))
        diff_flag = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "add_argument"
                        and any(isinstance(a, ast.Constant) and a.value == "--diff" for a in n.args)
                        for n in ast.walk(tree))
        dispatch = any(isinstance(n, ast.FunctionDef) and n.name == "on_select"
                       and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                               and c.func.id == "pick_song" for c in ast.walk(n))
                       for n in ast.walk(tree))
        prep = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "start_live"
                   and any(k.arg == "on_prep"
                           and any(isinstance(v, ast.Name) and v.id == "on_prep"
                                   for v in ast.walk(k.value))
                           for k in n.keywords)
                   for n in ast.walk(tree))
        default = any(isinstance(n, ast.Assign) and len(n.targets) == 1
                      and isinstance(n.targets[0], ast.Name)
                      and n.targets[0].id == "MULTI_DIFF_DEFAULT"
                      and isinstance(n.value, ast.Constant) and n.value.value == "expert"
                      for n in ast.walk(tree))
        # 单人选曲页的出路（用户 m04029「误入单人选曲页应该点左上角的返回按钮回到演出首页重新
        # 选择多人模式」）：`on_select_multi` 在那一版页面上按 `SELECT_BACK`（左上角返回箭头，hold
        # 用 `SELECT_BACK_HOLD` —— 0.12 s 的默认接触那一页不认）并把 "wait" 交回走查，让走查自己
        # 重读页面，绝不按 決定。少了这一按，误入单人页时整局就只剩「不开始」。
        solo_back = False
        for n in ast.walk(tree):
            if isinstance(n, ast.FunctionDef) and n.name == "on_select_multi":
                solo_back = any(
                    any(isinstance(a, ast.Starred) and isinstance(a.value, ast.Name)
                        and a.value.id == "SELECT_BACK" for a in c.args)
                    for c in ast.walk(n)
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                    and c.func.id == "tap")

        # 多人这一页只欠一条难度带：`on_select_multi` 读的是 `gameread.read_band`（只走
        # `read_difficulty`，不要求封面库建好、也不要求封面对上），不是 `read_song_select`。
        # 少了这条，封面被卷出框（或封面库没建）时这一页读不出来，走查就会在**没认出的页面**
        # 上按 決定 —— 2026-10-08 16:03 那一局单人演奏正是这么来的（用户 m04278 要求补掉）。
        band_read, song_read = False, False
        for n in ast.walk(tree):
            if isinstance(n, ast.FunctionDef) and n.name == "on_select_multi":
                for c in ast.walk(n):
                    if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                            and isinstance(c.func.value, ast.Name) and c.func.value.id == "gameread"):
                        band_read = band_read or c.func.attr == "read_band"
                        song_read = song_read or c.func.attr == "read_song_select"

        def used(name, kind):
            """`name = <表达式>` 那条赋值里用到的属性名（kind="attr"）或名字（kind="id"）。"""
            for n in ast.walk(tree):
                if (isinstance(n, ast.Assign) and len(n.targets) == 1
                        and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name):
                    got = set()
                    for a in ast.walk(n.value):
                        if kind == "attr" and isinstance(a, ast.Attribute):
                            got.add(a.attr)
                        elif kind == "id" and isinstance(a, ast.Name):
                            got.add(a.id)
                    return got
            return set()

        mode = used("pick_mode", "attr")
        names = used("hits_path", "id")
        attrs = used("hits_path", "attr")
        # 记录里那一局的名字：`--multi` 也要进这个分支（2026-10-08 之前只有 --random/--song，
        # 于是七条多人记录全是空歌名空难度，用户 m04278 问起来的那个）。必须带 `if ...:` 前缀 ——
        # 光看 `args.random or args.song or args.multi` 会被同形的 `pick_mode = ...` 那行蒙混过去。
        multi_name = "if args.random or args.song or args.multi:" in src
        return (flag and diff_flag and dispatch and prep and default and solo_back
                and band_read and not song_read and multi_name
                and {"random", "song", "multi"} <= mode
                and "pick_mode" in names and "hits" in attrs)

    src = (ROOT / "tools" / "run.py").read_text(encoding="utf-8")
    pin = wired(src)
    mutant = src.replace('hits_path = hit_pick["path"] if pick_mode else args.hits',
                         'hits_path = hit_pick["path"] if args.random else args.hits')
    tooth = mutant != src and not wired(mutant)
    mutant2 = src.replace("on_prep=on_prep if args.multi else None", "on_prep=None")
    tooth2 = mutant2 != src and not wired(mutant2)
    mutant3 = src.replace('MULTI_DIFF_DEFAULT = "expert"', 'MULTI_DIFF_DEFAULT = "easy"')
    tooth3 = mutant3 != src and not wired(mutant3)
    mutant4 = src.replace("tap(*SELECT_BACK, i=inj, hold=SELECT_BACK_HOLD)",
                          "tap(*(0, 0), i=inj, hold=SELECT_BACK_HOLD)")
    tooth4 = mutant4 != src and not wired(mutant4)
    mutant5 = src.replace("got = gameread.read_band()", "got = gameread.read_song_select()")
    tooth5 = mutant5 != src and not wired(mutant5)
    mutant6 = src.replace("if args.random or args.song or args.multi:",
                          "if args.random or args.song:")
    tooth6 = mutant6 != src and not wired(mutant6)

    # ---------- ⑧ 记录：多人那一局（没有位置参数 hits）也要写出歌名与难度 ----------
    # 2026-10-08 用户 m04278 问「为什么所有多人模式记录都没有歌名和难度的数值」：`record_cli` 从前
    # 只按位置参数 `args.hits` 查表，而多人局的谱面是准备页上读出来的，于是 cid 空、歌名难度也空。
    import argparse
    import run as runmod
    keep_results = runmod.RESULTS
    tmpd = tempfile.mkdtemp(prefix="navgates_rec_")
    try:
        runmod.RESULTS = os.path.join(tmpd, "results.jsonl")
        runmod.record_cli(argparse.Namespace(hits=None, tag="mpZ"),
                          {"chart": "0058_03", "song": "真夜中遊園地", "diff": "expert",
                           "multi": True}, lambda *_a: None)
        with open(runmod.RESULTS, encoding="utf-8") as f:
            rec_line = json.loads(f.read().strip())
    finally:
        runmod.RESULTS = keep_results
    rec_ok = (rec_line.get("song") == "真夜中遊園地" and rec_line.get("diff") == "expert"
              and rec_line.get("chart") == "0058_03")

    # ---------- ②③④⑤⑥ 循环 ----------
    class List:
        """脚本化的选曲页：`mode` 决定它怎么回应一次拖动，手指落点解码回屏幕坐标。"""

        def __init__(self, mid, diff, mode="normal"):
            self.mid, self.diff, self.mode = mid, diff, mode
            self.drags = self.taps = self.swallowed = 0
            self._pts = []

        def idx(self):
            return songpick.ORDER.index(self.mid)

        @staticmethod
        def _screen(p):
            return p[1], int(round(720 - p[0]))        # to_raw 的逆向：raw=(720-y, x)

        def touch_down(self, slot, x, y, tracking_id=0):
            self._pts = [(x, y)]

        def touch_move(self, slot, x, y):
            self._pts.append((x, y))

        def touch_up(self, slot):
            pts = self._pts or [(0, 0)]
            x1, y1 = self._screen(pts[-1])
            if len(pts) > 1:
                y0 = self._screen(pts[0])[1]
                if y1 == y0:
                    return
                self.drags += 1
                if self.mode == "never" or (self.mode == "swallow1" and not self.swallowed):
                    self.swallowed += 1
                    return
                step = 1 if y1 < y0 else -1          # 屏幕向上 = 列表上一条
                if self.mode == "away":
                    step = 1                          # 不管往哪拖都背离目标走
                i = min(max(self.idx() + step, 0), len(songpick.ORDER) - 1)
                self.mid = songpick.ORDER[i]
            else:
                self.taps += 1
                if self.mode == "notap":
                    return
                if 741 <= x1 <= 1265 and 527 <= y1 <= 585:
                    self.diff = min(songpick.DIFF_PILLS,
                                    key=lambda k: abs(songpick.DIFF_PILLS[k] - x1))

    start = "100056"
    i0 = songpick.ORDER.index(start)
    tgt = songpick.ORDER[i0 - 4]
    start_diff = next(d for d in ("hard", "normal", "easy", "expert")
                      if gameread.chart_for(start, d)[1] is not None)
    want = next((d for d in ("hard", "normal", "easy", "expert")
                 if d != start_diff and gameread.chart_for(tgt, d)[1] is not None), None)
    dd = gameread.chart_for(tgt, want)[1] if want else None
    want_cid = f"{dd['book']}_{dd['dd']}" if dd else "?"

    tmp = tempfile.mkdtemp(prefix="navgates_songpick_")
    keep = [(run, "grab", run.grab), (run, "subdir", run.subdir),
            (run, "_select_read", run._select_read),
            (songpick, "read_current", songpick.read_current)]
    keep_sleep = (songpick.SETTLE_S, songpick.HOLD_S)
    songpick.SETTLE_S = songpick.HOLD_S = 0.0
    run.grab = lambda: np.zeros((720, 1280, 3), np.uint8)
    run.subdir = lambda _d: tmp
    try:
        def play(world, spec):
            said = []

            def read(frame=None):
                return world.mid, world.diff, 0.99

            def sel(budget=5.0, step=0.35, differs=None):
                return {"musicId": world.mid, "diff": world.diff, "score": 0.99, "gap": 0.5}

            songpick.read_current, run._select_read = read, sel
            return run.pick_song(spec, log=said.append, inj=world, state={}), said

        happy = play(List(start, start_diff), f"{tgt}:{want}")
        stole = play(List(start, start_diff, "swallow1"), f"{tgt}:{want}")
        never = play(List(start, start_diff, "never"), f"{tgt}:{want}")
        drift = play(List(start, start_diff, "away"), f"{tgt}:{want}")
        notap = play(List(start, start_diff, "notap"), f"{tgt}:{want}")
    finally:
        for mod, name, val in keep:
            setattr(mod, name, val)
        songpick.SETTLE_S, songpick.HOLD_S = keep_sleep

    pick, said = happy
    happy_ok = (isinstance(pick, dict) and pick["musicId"] == tgt
                and pick["diff"] == want and pick["cid"] == f"{dd['book']}_{dd['dd']}"
                and isinstance(pick["hits"], list) and len(pick["hits"]) > 0
                and str(pick["path"]).endswith(".hits.json") and (ROOT / pick["path"]).exists()
                and pick.get("hits") is not pick.get("path")
                and any("到达" in s for s in said))
    stole_pick, stole_said = stole
    stole_ok = (isinstance(stole_pick, dict) and stole_pick["musicId"] == tgt
                and any("没动" in s for s in stole_said))
    never_pick, never_said = never
    never_ok = (never_pick is None and any("拖不动" in s for s in never_said)
                and (Path(tmp) / "song_not_reached.png").exists())
    drift_pick, drift_said = drift
    drift_ok = (drift_pick is None and any("没能靠近" in s for s in drift_said))
    notap_pick, notap_said = notap
    notap_ok = (notap_pick is None and any("难度没点到" in s for s in notap_said))

    ok = (spec_ok and pin and tooth and tooth2 and tooth3 and tooth4 and tooth5 and tooth6
          and rec_ok and happy_ok and stole_ok and never_ok and drift_ok and notap_ok)
    print(f"parse_song：{plain} / {with_diff}（要 ('100054', None) / ('100054', 'hard')），"
          f"坏难度 → {raised[:44]!r}")
    print(f"接线：--song 注册 + --diff 注册 + on_select 分派 + pick_mode 三种选曲 + hits_path 两条分支 + "
          f"on_prep 挂上 start_live + 默认难度 expert + 单人页按 SELECT_BACK 回演出首页 + "
          f"多人这一页读 read_band（不是 read_song_select）+ 记录里 --multi 也带名字 = {pin}"
          f"（要 True）；"
          f"把谱面路径改回只认 --random → {wired(mutant)}（要 False）；"
          f"把 on_prep 摘掉 → {wired(mutant2)}（要 False）；"
          f"把默认难度改成 easy → {wired(mutant3)}（要 False）；"
          f"把单人页那一按换成别的坐标 → {wired(mutant4)}（要 False）；"
          f"把这一页的读数改回 read_song_select → {wired(mutant5)}（要 False）；"
          f"把记录的名字只留给 --random/--song → {wired(mutant6)}（要 False）")
    print(f"记录：多人那一局（没有位置参数 hits）写出的歌名 {rec_line.get('song')!r}、难度 "
          f"{rec_line.get('diff')!r}、谱面 {rec_line.get('chart')!r}（要 真夜中遊園地/expert/0058_03）"
          f"= {rec_ok}")
    print(f"快乐路径 {start}→{tgt}（{want}）：走 {len([s for s in said if '选曲 ' in s])} 步，"
          f"交出 {pick.get('cid') if isinstance(pick, dict) else pick}（要 {want_cid}），"
          f"{len(pick['hits']) if isinstance(pick, dict) else 0} 音符，path 是真文件 "
          f"{(ROOT / pick['path']).exists() if isinstance(pick, dict) else False} = {happy_ok}")
    print(f"被吃掉的一拖：重试日志 "
          f"{sum(1 for s in stole_said if '没动' in s)} 条，仍到达 {stole_ok}")
    print(f"拖不动：放弃 {never_pick is None}（要 True），日志认了这件事 "
          f"{any('拖不动' in s for s in never_said)}，取证帧已落盘 "
          f"{(Path(tmp) / 'song_not_reached.png').exists()}")
    print(f"越走越远：连续 {songpick.DRIFT_LIMIT} 步没靠近就放弃 "
          f"{drift_pick is None}（要 True）= {drift_ok}")
    print(f"难度点不上：放弃 {notap_pick is None}（要 True）= {notap_ok}；取证留 {tmp}")
    print("PART 14 " + ("PASS" if ok else "FAIL"))
    return ok


def part15():
    """多人开打前的四页：匹配中弹窗 / 准备页 / 匹配页与五人加载页 / 排名页（2026-10-08 真机录像）。

    用户 2026-10-08 自己打的那一局（research/recordings/mp2，1947 帧、2.88 fps）里这四页 screen
    都认不出来，而走页按着它读出来的名字按键：匹配中弹窗 与 准备页 都读成 home（按首页底部的
    霓虹块 LIVE_TILE 1090,600）、抽曲动画/抽中封面/五人加载 读成 options 与 shop（按 演出 790,611
    或页头的房子）、排名页读成 result（按 (1080,660) —— 恰好是它自己的 下一步，所以只有这一页
    不改也行）。九张新语料按 PART 0 的口径钉进 evidence/nav，这里补的是它们周围的边界：

    ① 十张正例必须读对；② 语料里最像它们的十五张一张都不许改判、也不许答上任何一个新判据；
    ③ 每道门都要有反事实：把门放宽到刚越过邻居，邻居就必须真的翻过去 —— 不然这条规则只是
    「今天恰好没撞上」；④ 走页：MP_QUIET_PAGES 三页只等不按（走到 乐曲选择 时一次都没按过），
    rank 与 result 一样按 (1080,660)；把这套静候撤掉，准备页就会连着 8 次 unreadable screen
    把这一局放弃。

    ③ 报的是每页要几道门同时放宽才会被抢走：结算 splash 两道（luma 80、pill 0.85）、首页三道
    （pbtn、label、bluesat）、单人结算两道（mid 0.30、bl 0.06）、演出首页六道（最近的一道是
    bluesat 0.298 对 0.30，靠 pbtn 0.214 对 0.05 才守住）。这些数字都在这里的打印里。
    """
    frames = {p.name: im for p, im in corpus()}
    need = tuple(MP_VERDICTS) + tuple(n for n, _ in MP_NEIGHBOURS)
    missing = [n for n in need if n not in frames]
    if missing:
        print(f"PART 15 FAIL: the corpus is missing {missing}")
        return False

    pos = [(n, calib.screen(frames[n]), want) for n, want in MP_VERDICTS.items()]
    pos_ok = all(got == want for _, got, want in pos)
    neigh = [(n, calib.screen(frames[n]), want) for n, want in MP_NEIGHBOURS]
    neigh_ok = all(got == want for _, got, want in neigh)
    pred_ok = True
    for n, _, _ in neigh:
        a = frames[n]
        if calib._mp_matchpopup(a) or calib._mp_prep(a) or calib._mp_matching(a) or calib._mp_rank(a):
            pred_ok = False

    def flip(name, value, fn):
        """Run fn with one module-level gate moved -- the counterfactual every gate needs."""
        saved = getattr(calib, name)
        setattr(calib, name, value)
        try:
            return fn()
        finally:
            setattr(calib, name, saved)

    splash, home = frames["nav_stuck_finish.png"], frames["nav_home_a.png"]
    pause, livehome = frames["navgates_pause_a.png"], frames["nav_livehome_a.png"]
    solo = frames["result_a43.png"]

    # 匹配中弹窗：g471 那一页（结算 splash）要 luma 与 pill 两道门同时放宽才会被读成弹窗；
    # 暂停面板的宽药丸 0.805 只在 pill 门放宽到 0.80 时进来（screen 仍读 pause，因为 pause 问得更早）
    pop_ok = (not calib._mp_matchpopup(splash)
              and not flip("MP_POPUP_LUM", 200.0, lambda: calib._mp_matchpopup(splash))
              and flip("MP_POPUP_LUM", 200.0,
                       lambda: flip("MP_POPUP_PILL", 0.40, lambda: calib._mp_matchpopup(splash))))
    pause_ok = (not calib._mp_matchpopup(pause)
                and flip("MP_POPUP_PILL", 0.80, lambda: calib._mp_matchpopup(pause)))
    # 准备页：首页的头两道门（pbtn 0.206 对 0.25、label 0.307 对 0.35）都只差一点，第三道
    # bluesat（0.071 对 0.5）才是那道真正的墙。（label 这道门 2026-10-08 已经从 `_mp_prep` 挪到
    # 「按不按」那一步，下面 `spin_ok` 钉新的分工；这里的反事实仍然成立，只是它现在只靠 pbtn +
    # bluesat 两道门。）
    prep_ok = (calib.screen(home) == "home"
               and flip("MP_PREP_PBTN", 0.20,
                        lambda: flip("MP_PREP_LABEL", 0.30, lambda: calib.screen(home))) == "home"
               and flip("MP_PREP_PBTN", 0.20, lambda: flip("MP_PREP_LABEL", 0.30,
                        lambda: flip("MP_PREP_BLUESAT", 0.05,
                                     lambda: calib.screen(home)))) == "prep")
    # 匹配页：结算 splash 的 mid 0.096 / bl 0.165 都被门挡住（要 mid 0.15 才越过去）
    match_ok = (calib.screen(splash) == "finish"
                and flip("MP_LOBBY_BL", 0.20, lambda: flip("MP_LOBBY_LABEL", 0.10,
                         lambda: calib.screen(splash))) == "finish"
                and flip("MP_LOBBY_BL", 0.20, lambda: flip("MP_LOBBY_LABEL", 0.10,
                         lambda: flip("MP_LOBBY_MID", 0.15, lambda: calib.screen(splash)))) == "matching")
    # 排名页：单人结算被 mid 0.764 挡住，就算把 mid 门放到 0.80，还有左下角 bl 0.000 那一道
    rank_ok = (calib.screen(solo) == "result"
               and flip("MP_RANK_MID", 0.80, lambda: calib.screen(solo)) == "result"
               and flip("MP_RANK_MID", 0.80, lambda: flip("MP_RANK_BL", -0.01,
                        lambda: calib.screen(solo))) == "rank")
    # 演出首页：把按钮门放宽到 0.30（越过它的 0.214）还是 livehome —— 后面还有五道门
    livehome_ok = (calib.screen(livehome) == "livehome"
                   and flip("MP_LOBBY_PBTN", 0.30, lambda: calib.screen(livehome)) == "livehome")
    # 匹配页的 luma 下限（2026-10-08 从 100 降到 70）：弹窗散开、匹配页淡入的那一帧在 100 的
    # 门外读 failed，而走页对 failed 的动作是按 返回选曲（924,611）—— 正好把刚匹配上的一局取消
    trans = frames["mp_matching_d.png"]
    floor_ok = (calib.screen(trans) == "matching"
                and flip("MP_LOBBY_LUM", (100.0, 170.0), lambda: calib.screen(trans)) == "failed")
    # band 门 0.15 → 0.22（2026-10-08 15:35 的 mp11）：多人演出**失败**那一局的排名/结算页上，同一条
    # 仪表条由绿 (#5bc18b) 变红 (#ff3737) + 品红 (#ff3db3)，band 那一格读到 **0.158** ⇒ 旧门把它读成
    # band、`wait_result` 等不到 result、走查死等到超时（`evidence/nav/mp_rank_red.png` 就是那一帧）。
    # 真 LEADER 横幅恒 **0.300..0.310**（全语料 234 张 band 帧）。把门钉在两个总体之间：门必须严格
    # 落在那一帧的读数和真横幅之间，而且门一降到读数之下，同一帧就必须被读成 band（那次死锁本身）。
    red_gauge = frames["mp_rank_red.png"]
    red_frac = calib._frac(red_gauge, calib._red, 640, 120, 70, 16)
    band_ok = (calib.screen(red_gauge) == "rank"
               and abs(red_frac - 0.158) < 0.01
               and red_frac < calib.BAND_RED < 0.300
               and flip("BAND_RED", red_frac - 0.01, lambda: calib.screen(red_gauge)) == "band")
    # 准备页的 label 门 2026-10-08 从 `_mp_prep` 挪到「按不按」那一步：转圈态（蓝底 + 白圈、没有字）
    # 过的了 pbtn(0.301)/bluesat(0.669)，从前被 label 门(0.011)踢出去、`screen` 落到
    # `_blue(*PERFORM)` 读成 options（走查在那页上按 (790,611)）。现在它读 prep、但一下都不按。
    spin = frames["mp_prep_spin.png"]

    def _uses(fn, name):
        """`fn` 的**代码**里用没用这个名字 —— 走 AST，所以 docstring 里提到它不算。"""
        import ast as _ast
        import textwrap
        tree2 = _ast.parse(textwrap.dedent(inspect.getsource(fn)))
        return any(isinstance(n, _ast.Name) and n.id == name for n in _ast.walk(tree2))

    spin_ok = (calib.screen(spin) == "prep"
               and calib._box_pale(spin, calib.MP_LABEL_BOX) <= calib.MP_PREP_LABEL
               and not _uses(calib._mp_prep, "MP_PREP_LABEL")
               and _uses(calib.start_live, "MP_PREP_LABEL"))

    real_grab, real_tap = calib.grab, calib.tap
    guard = _DumpGuard()
    with guard:
        def walk(script, stop, timeout, quiet=None):
            """The real walk over a scripted frame source: (returned, taps, log)."""
            seq = list(script)
            taps, said = [], []

            def grab():
                return seq.pop(0) if seq else script[-1]

            def tap(x, y, *a, **k):
                taps.append((int(x), int(y)))

            saved_q = calib.MP_QUIET_PAGES
            calib.grab, calib.tap = grab, tap
            if quiet is not None:
                calib.MP_QUIET_PAGES = quiet
            try:
                out = calib.start_live(None, log=said.append, timeout=timeout,
                                       stop_at_select=stop)
            finally:
                calib.grab, calib.tap = real_grab, real_tap
                calib.MP_QUIET_PAGES = saved_q
            return out, taps, said

        sel = frames["nav_stuck_select.png"]
        quiet_prep = walk([frames["mp_prep_a.png"], sel], True, 6.0)
        quiet_match = walk([frames["mp_matching_a.png"], sel], True, 6.0)
        quiet_pop = walk([frames["mp_matchpopup_a.png"], sel], True, 6.0)
        rank_walk = walk([frames["mp_rank_a.png"], frames["hud_great1.png"]], False, 6.0)
        give_up = walk([frames["mp_prep_a.png"]], True, 40.0, quiet=())
        dumped = sorted(os.listdir(guard.tmp))

    quiet_ok = (all(out and not taps for out, taps, _ in (quiet_prep, quiet_match, quiet_pop))
                and rank_walk[0] and rank_walk[1] == [(1080, 660)])
    giveup_ok = (not give_up[0] and not give_up[1]
                 and sum(1 for s in give_up[2] if s.startswith("  unreadable screen")) == 8
                 and "nav_stuck_prep.png" in dumped and "start_live_stuck.png" in dumped)

    ok = (pos_ok and neigh_ok and pred_ok and pop_ok and pause_ok and prep_ok and match_ok
          and rank_ok and livehome_ok and floor_ok and band_ok and spin_ok and quiet_ok
          and giveup_ok and not guard.leaked())
    for n, got, want in pos:
        print(f"  {n}: {got}（要 {want}）{'ok' if got == want else 'WRONG'}")
    print(f"语料里最像它们的 {len(neigh)} 张：全部保持原判 {neigh_ok}，且没有一张答上新判据 {pred_ok}"
          f"（暂停 {neigh[0][1]} / splash {neigh[1][1]} / 首页 {neigh[2][1]} / 演出首页 {neigh[3][1]}"
          f" / 单人结算 {neigh[12][1]}）")
    print(f"反事实：结算 splash 两道门才被读成弹窗 {pop_ok}；暂停面板的宽药丸越门即中 {pause_ok}；"
          f"首页三道门 {prep_ok}；splash 读成匹配页要 mid 0.15 {match_ok}；"
          f"单人结算两道门 {rank_ok}；演出首页按钮门放宽仍是 livehome {livehome_ok}；"
          f"匹配页 luma 下限 100 时那帧过渡帧读 failed {floor_ok}；"
          f"band 门 {calib.BAND_RED} 落在失败局 {red_frac:.3f} 与真横幅 0.300 之间 {band_ok}"
          f"（门降到读数之下就变 band）；准备页转圈态读 prep 且 label 门只在按那一步 {spin_ok}")
    print(f"走页：三页静候零按键 "
          f"{[(o, t) for o, t, _ in (quiet_prep, quiet_match, quiet_pop)]}，"
          f"rank 按 {rank_walk[1]}（要 [(1080, 660)]）；撤掉静候后 准备页 8 次 unreadable 后放弃 "
          f"{give_up[0] is False}，落盘 {dumped}，工作 dump 没被碰 {not guard.leaked()}")
    print("PART 15 " + ("PASS" if ok else "FAIL"))
    return ok


def part16():
    """多人这一局打哪张谱，以及「演出开始之后只看不按」（2026-10-08）。

    激奏演出的曲子是房间抽签抽的，只有 准备页 上那张封面知道抽中了谁 —— 这一页读不出来，这一局
    就没有谱面可打（`--song/--random` 在多人里只是「我推荐的那首」，位置参数给的 hits 用不上）。
    这里钉三件事：

    ① `gameread.read_prep` 读的是**抽中的那一首**，不是玩家自己点的那一首。mp2 那一局玩家选的是
       100056（选曲页封面 0.995），抽中的是 100080（准备页 ncc 0.993、次高差 0.58）；mp1 那一局
       抽中的才是 100056（0.992）—— 两张封面都读得出来，所以这不是「谁在中间」。不是准备页的帧
       一律不许答（选曲页 / 排名页 / 结算 splash 上都没有那张封面）。
    ② 难度带在多人页上比单人页低 30 px（单人药丸行 y527..585、多人 y557..615，四格 x 不变），
       而**只有单人那一带**能凭自身几何作答：g486 那一局就死在多人页上读不出难度，因为旧代码只扫
       单人那一带。两带的读数各自钉在语料里，行数不是整 58 行的帧一律拒答（旧代码在截断的带上
       读出过垃圾 —— 那些帧是 HUD 弹窗，不是选曲页）。同一页的取帧也有个坑：`read_song_select` 在
       frame=None 时要走**本轮装上的**抓帧源（`detect.grab`），从前写死成 mumucap，于是没有
       `--fastcap` 的局在这一页上永远读不出难度（而它读别的页都好好的）；现在按默认 expert 打也能开局。
       ②c 又补了一条：多人这一页只欠**一条难度带**，所以 `run.py` 读的是 `gameread.read_band`
       （只走 `read_difficulty`），不是 `read_song_select`（后者要先建封面库、还要封面对上）。
       判据把封面库藏起来跑一遍：`read_band` 在单人与多人两版页面上都照答，同一帧
       `read_song_select` 就答不出了。从前少了这条，封面认不出时这一页读不出难度，走查便在
       **没认出的页面**上按 決定 —— 2026-10-08 16:03 那一局单人演奏就是这么来的（用户 m03977）。
    ③ 尾段：演出开始那一按出去之后，场地载入期间的**每一页**都只观望、不按任何键。mp2 的现场淡入
       依次被读成 other(0.86 s) / rankup(0.43 s) / result(1.13 s) / options(1.12 s) / live(1 帧) /
       other(4.11 s)，其中 rankup 会按自己的药丸中心、other 会累计 unreadable 计数（八次就放弃整局，
       而 4.11 s 正好是八次读数）。反事实：同一页出现在尾段之前就必须按下去 —— 所以这不是「这一页
       不用按」，是「尾段不按」。安静页还要把重复计数一起清掉：它等的是游戏自己走完，不是「同一个
       verdict 连读」（重放 mp2 时 `other` 只连读 3 次、真的只过了 0.5 s，却因为中间隔着 34 s 的
       匹配中弹窗被算成「连读 22 s」，白交回一次通用处理）。
    ④ 回家路上最后一页（结算 EXP 页）：多人有两版，`_exp_cards` 分得开 —— 详情/下一步（五张成员卡）
       与主页/再次演出（没有卡）。**两版都是第一眼就按 `EXP_RETRY`**：mp2 录像两版都只挂了约 2 s、
       游戏自己走到了 乐曲选择，证不出「再次演出」在多人里的语义，用户 2026-10-08 给了答案 —— 它也是
       回乐曲選択，不会再排一局。所以那道「先等 `EXP_WAIT_S` 再按」的观望被删掉了，这里同时钉住它
       不存在（`hasattr(calib, "EXP_WAIT_S")` 必须是 False）：一页真的在等按键时，干等只会让每一趟
       走页都超时，而它已经不是那种页了。
    ⑤ 准备页右下那一按只在按钮**还是彩色**时才按：按一下玩家就进准备状态、按钮立刻从彩色的
       准备 变成灰色的 取消，再按一下就是取消准备（用户 2026-10-08）。旧代码在按钮 pale 没涨时
       补按（最多 3 次），但那一格的 pale 本来就是按钮自己的呼吸 —— mp2 的 36 张准备页帧在 0.303
       与 0.744 之间来回跳、周期约 1.4 s（量在 `research/experiments/preppale.py`），
       `pale <= prep_pale + 0.05` 分不出「按中」和「正好跳到暗相」。这里两趟都连读 6 帧：彩色的
       那趟（`mp_prep_a.png`，带色相 0.905）按满 `MULTI_PREP_TRIES` 下（脚本帧不会变灰，所以
       有界补按会走满），灰色那趟（`mp_prep_b.png`，0.038）一下都不许有、只许打一行「灰色的
       取消」；并静态钉住 `start_live` 里只有一处 `MULTI_PREP_BTN` 的 tap（复制一份就是被删掉的
       补按，必须变红）。
    ⑥ 匹配中弹窗不能无限等：那一页在 mp2 上停了 34.9 s、帧一动不动，没有任何「往前走」的按钮，
        只有那个静态药丸是**取消这次匹配**（2026-10-08 实测：点它的中心 1.5 s 后回到 乐队确认页）。
        房间配不到人时它会永远停在那里 —— mp8 停了 15 分钟，旧代码零按键等到 deadline，整局判掉、
        回家也没走成。所以等够 `MULTI_MATCH_WAIT_S` 就取消一次、让走查回去再按一次 自由対戦，最多
        `MULTI_MATCH_TRIES` 次。这里三趟：短等（6 帧 ≈ 2.4 虚拟秒）一下都不许按；等过门按一次
        `MP_PILL_CENTRE`；一直不变时封顶在两次并打一行「不再取消」。
    ⑦ 走回家的那趟停在 乐队确认页：左上角的返回箭头就是回 乐曲选择（用户 m02645「乐队确认页左上角
        的箭头按钮返回乐曲选择页啊，单人模式不也这样吗」；2026-10-08 实测点 (40,36) 1.4 s 后 screen
        读作 select、`read_song_select` 的难度带 row 557 = 多人那一带）。从前这一页只能干等 12 s 再
        交回通用处理（而通用处理按的是「开一局」的按钮，所以只能认输）—— 上一局停在 乐队确认 就再也
        回不了家。现在有界地按 `BAND_BACK`：两趟都是「按 `BAND_BACK_TRIES` 下、页面不动就只抱怨一次
        然后观望」，并静态钉住源码里只有走回家的那一支按它（`tap(*BAND_BACK` 只出现一次）——前进那趟
        这一页要按的是 演出开始 / 自由対戦，按了返回就是把「开打」走成「回家」。
    """
    frames = {p.name: im for p, im in corpus()}
    need = ("mp_prep_a.png", "mp_prep_b.png", "mp_prep_c.png", "mp_select_a.png",
            "mp_exp_cards_a.png", "mp_exp_totals_a.png",
            "navgates_select_easy.png", "nav_stuck_select.png", "nav_stuck_other.png",
            "nav_stuck_rankup.png", "nav_stuck_options.png", "nav_livehome_a.png",
            "nav_stuck_band.png", "result_a43.png", "hud_great1.png")
    missing = [n for n in need if n not in frames]
    if missing:
        print(f"PART 16 FAIL: the corpus is missing {missing}")
        return False

    # ① 抽签：读的是抽中的那一首
    want_draw = {"mp_prep_a.png": "100080", "mp_prep_b.png": "100080", "mp_prep_c.png": "100056"}
    draws = [(n, gameread.read_prep(frames[n])) for n in want_draw]
    draw_ok = all(g.get("ok") and g.get("musicId") == want_draw[n]
                  and g.get("score", 0.0) >= gameread.PREP_JACKET_GOOD
                  and g.get("gap", 0.0) >= gameread.PREP_JACKET_GAP for n, g in draws)
    false_prep = [n for n in ("navgates_select_easy.png", "mp_rank_a.png", "nav_stuck_other.png")
                  if gameread.read_prep(frames[n]).get("ok")]

    # ② 两条难度带：单人那一带照旧，多人那一带 30 px 低
    def diff_of(name):
        d, det = gameread.read_difficulty(frames[name])
        det = det or {}
        return d, det.get("row"), tuple(int(x) for x in det.get("block", ()))

    solo_d, solo_row, _ = diff_of("navgates_select_easy.png")
    solo2_d, solo2_row, _ = diff_of("nav_stuck_select.png")
    multi_d, multi_row, multi_blk = diff_of("mp_select_a.png")
    cut_d = gameread.read_difficulty(frames["navgates_select_easy.png"][:540])[0]
    diff_ok = ((solo_d, solo_row) == ("easy", gameread.DIFF_BAND[0])
               and (solo2_d, solo2_row) == ("expert", gameread.DIFF_BAND[0])
               and (multi_d, multi_row) == ("expert", gameread.DIFF_BANDS[1])
               and len(multi_blk) == 2 and 1130 <= multi_blk[0] and multi_blk[1] <= 1268
               and cut_d is None)

    # ②b 取帧：`read_band` / `read_song_select` 那条 frame=None 的路要走**本轮装上的**抓帧源
    # （`detect.grab`，与 `calib` 的走查、`songpick.read_current` 同一个），不能写死 mumucap ——
    # 写死的话没有 `--fastcap` 的局在这页上永远读不出难度，而它读别的页都好好的（2026-10-08
    # 改掉的那条；多人这一页现在走 `read_band`，它只欠一条难度带）。
    import detect
    keep_grab = detect.grab
    try:
        detect.grab = lambda: "sentinel-frame"
        grab_ok = gameread._grab() == "sentinel-frame"
    finally:
        detect.grab = keep_grab

    # ②c 多人这一页只欠一条难度带：把封面库藏起来，`read_band` 照样答（同一帧上
    # `read_song_select` 就答不出了）。这条正是 2026-10-08 那个洞的判据 —— 从前这一页用
    # `read_song_select`，封面认不出（被卷出框、或库没建）时读不到难度，走查便在**没认出的
    # 页面**上按 決定，于是误开了一局单人演奏（用户 m03977/m04278）。
    keep_idx = gameread.load_index
    try:
        gameread.load_index = lambda: (None, None)
        band_solo = gameread.read_band(frames["navgates_select_easy.png"])
        band_multi = gameread.read_band(frames["mp_select_a.png"])
        song_none = gameread.read_song_select(frames["mp_select_a.png"])
    finally:
        gameread.load_index = keep_idx
    bandread_ok = (band_solo.get("ok") and band_solo.get("diff") == "easy"
                   and band_solo.get("row") == gameread.DIFF_BAND[0]
                   and band_multi.get("ok") and band_multi.get("diff") == "expert"
                   and band_multi.get("row") == gameread.DIFF_BANDS[1]
                   and not song_none.get("ok"))

    # ③ 尾段：载入期的每一页只观望
    real_grab, real_tap, real_time = calib.grab, calib.tap, calib.time
    guard = _DumpGuard()
    with guard:
        class Clock:
            """A virtual clock. The quiet pages sleep 0.15 s per read and the tail's escape is
            timed at TAIL_STUCK_S, so a wall-clock run of a 准备页-length wait would take minutes."""

            def __init__(self):
                self.t = 0.0

            def sleep(self, dt):
                self.t += float(dt)

            def perf_counter(self):
                return self.t

            def time(self):
                return self.t

        def walk(script, timeout=8.0, multi=True, quiet=None, clock=None, stop=False):
            """The real walk over a scripted frame source: (returned, taps, log)."""
            seq = list(script)
            taps, said = [], []

            def grab():
                return seq.pop(0) if seq else script[-1]

            def tap(x, y, *a, **k):
                taps.append((int(x), int(y)))

            saved_q = calib.MP_QUIET_PAGES
            calib.grab, calib.tap = grab, tap
            if clock is not None:
                calib.time = clock
            if quiet is not None:
                calib.MP_QUIET_PAGES = quiet
            try:
                out = calib.start_live(None, log=said.append, timeout=timeout, multi=multi,
                                       stop_at_select=stop)
            finally:
                calib.grab, calib.tap, calib.time = real_grab, real_tap, real_time
                calib.MP_QUIET_PAGES = saved_q
            return out, taps, said

        livehome, sel, band = frames["nav_livehome_a.png"], frames["nav_stuck_select.png"], \
            frames["nav_stuck_band.png"]
        # mp2 的淡入顺序，原样摆进来
        fade = walk([livehome, sel, band, frames["nav_stuck_other.png"],
                     frames["nav_stuck_rankup.png"], frames["result_a43.png"],
                     frames["nav_stuck_options.png"], frames["nav_stuck_other.png"],
                     frames["hud_great1.png"]])
        # 反事实：同一页出现在尾段之前（这里没有 livehome 的瓦片键，从 select 起步也一样）
        before = walk([livehome, sel, frames["nav_stuck_rankup.png"], band,
                       frames["hud_great1.png"]])
        # 安静页之后的 other 不许被算成「连读」：一个虚拟时钟把匹配中弹窗拉长到 12 s 以上
        clock = Clock()
        long_quiet = walk([livehome, sel, band] + [frames["mp_matching_a.png"]] * 90
                          + [frames["nav_stuck_other.png"], frames["hud_great1.png"]],
                          timeout=20.0, clock=clock)
        # 反事实：安静页不是安静页（MP_QUIET_PAGES 清空）时，同一个脚本确实会交回一次
        clock2 = Clock()
        no_quiet = walk([livehome, sel, band] + [frames["mp_matching_a.png"]] * 90
                        + [frames["nav_stuck_other.png"], frames["hud_great1.png"]],
                        timeout=20.0, quiet=(), clock=clock2)
        # ④ 结算 EXP 页两版：多人、单人都是第一眼就按 `EXP_RETRY`。
        # 多人的 timeout 有 300 s 下限，所以这几趟都用虚拟时钟，并且用一张 LIVE 帧收尾
        # （走查进了现场就只等不按，不会再有别的键）。
        cards, totals, field = (frames["mp_exp_cards_a.png"], frames["mp_exp_totals_a.png"],
                                frames["hud_great1.png"])
        press_cards = walk([cards, field], stop=True, clock=Clock())
        press_totals = walk([totals, field], stop=True, clock=Clock())
        press_solo = walk([totals, field], multi=False, stop=True, clock=Clock())
        # ⑤ 准备页那一按：只在按钮**还是彩色**（= 还没准备）时才按（用户 2026-10-08：按一下
        # 玩家就进准备状态、按钮立刻从彩色的 准备 变成灰色的 取消，再按一下就是取消准备）。
        # 旧代码在按钮 pale 没涨时补按（最多 3 次），可那一格的 pale 本来就是按钮自己的呼吸：
        # mp2 的 36 张准备页帧实测在 0.303（暗相）与 0.744（亮相）之间来回跳、周期约 1.4 s
        # （research/experiments/preppale.py），判据分不出「按中」和「正好跳到暗相」——补按
        # 就是替玩家取消准备。这里两趟都连读 6 帧：彩色那趟（mp_prep_a）的脚本帧不会因为按了
        # 就变灰，所以有界补按会走满（两下）；灰色那趟（mp_prep_b，实测带色相 0.038）一下都
        # 不许有，只许打一行「灰色的 取消」。
        class FastClock(Clock):
            """多人走查的 timeout 有 300 s 下限（`MULTI_WALK_TIMEOUT_S`），这几趟只数按键，
            不必把 300 虚拟秒一帧一帧走完。"""

            def sleep(self, dt):
                self.t += 20.0 * float(dt)

        prep_walk = walk([frames["mp_prep_a.png"]] * 6 + [field], timeout=12.0, clock=FastClock())
        grey_walk = walk([frames["mp_prep_b.png"]] * 6 + [field], timeout=12.0, clock=FastClock())
        spin_walk = walk([frames["mp_prep_spin.png"]] * 6 + [field], timeout=12.0, clock=FastClock())
        # ⑥ 匹配中弹窗等太久：那个静态药丸是**取消这次匹配**（2026-10-08 实测：点它的中心 1.5 s
        # 后回到 乐队确认页），所以等够 MULTI_MATCH_WAIT_S 就取消一次、让走查回去再按一次 自由対戦
        # —— 但取消次数有上限。mp8 就是停在这一页上 15 分钟（房间配不到人），旧代码零按键等到
        # deadline、整局判掉、回家也没走成。虚拟时钟把这一页拉过那道门。
        quick = Clock()
        pop_quick = walk([frames["mp_matchpopup_a.png"]] * 6 + [field], timeout=12.0, clock=quick)
        slow = Clock()
        pop_slow = walk([frames["mp_matchpopup_a.png"]] * 320 + [field], timeout=200.0, clock=slow)
        slow2 = Clock()
        pop_bound = walk([frames["mp_matchpopup_a.png"]] * 1400 + [field], timeout=900.0,
                         clock=slow2)
        # ⑦ 走回家的路上停在 乐队确认页：左上角那个返回箭头就是回 乐曲选择（用户 m02645「乐队确认页
        # 左上角的箭头按钮返回乐曲选择页啊，单人模式不也这样吗」；2026-10-08 实测点 (40,36) 1.4 s 后
        # screen 读作 select、read_song_select 的难度带 row 557）。有界地按它：脚本帧一直是 band 时
        # 按 BAND_BACK_TRIES 下、只抱怨一次，然后回到老行为（只观望）；前进的那趟一下都不许按
        # —— 那一趟这一页要按的是 自由対戦 / 演出开始，按了返回就是把「开打」走成「回家」。
        back_walk = walk([band, band, sel], stop=True, timeout=900.0, clock=FastClock())
        back_stuck = walk([band] * 8 + [sel], stop=True, timeout=900.0, clock=FastClock())
        dumped = sorted(os.listdir(guard.tmp))

    tap_tile = calib.MULTI_LIVE_TILE
    tap_go = calib.SONG_GO
    tap_start = calib.LIVE_START_BTN
    fade_ok = (fade[0] is True and fade[1] == [tap_tile, tap_go, tap_start])
    # 反事实：rankup 在尾段之前按的是它自己的药丸中心
    rank_tap = tuple(int(v) for v in calib.rankup_ok(frames["nav_stuck_rankup.png"]))
    before_ok = (before[0] is True
                 and before[1] == [tap_tile, tap_go, rank_tap, tap_start])
    quiet_ok = (long_quiet[0] is True
                and long_quiet[1] == [tap_tile, tap_go, tap_start]
                and not [s for s in long_quiet[2] if "连读" in s])
    noquiet_ok = bool([s for s in no_quiet[2] if "连读" in s])
    exp_ok = (press_cards[1] == [calib.EXP_RETRY]
              and press_totals[1] == [calib.EXP_RETRY]
              and press_solo[1] == [calib.EXP_RETRY]
              and not hasattr(calib, "EXP_WAIT_S")
              and not [s for s in press_totals[2] if "先不按" in s])
    # ⑤ 的静态那一半：整个 `start_live` 里只有一处 `MULTI_PREP_BTN` 的 tap，把那一按复制一份
    # （就是被删掉的补按）必须让这条变红。
    prep_src = inspect.getsource(calib.start_live)
    prep_one_site = prep_src.count("tap(*MULTI_PREP_BTN") == 1
    prep_mutant = prep_src.replace(
        "tap(*MULTI_PREP_BTN, i=inj, hold=0.16)",
        "tap(*MULTI_PREP_BTN, i=inj, hold=0.16)\n"
        "                    tap(*MULTI_PREP_BTN, i=inj, hold=0.16)")
    prep_colour = calib._prep_btn_colour(frames["mp_prep_a.png"])
    prep_grey_colour = calib._prep_btn_colour(frames["mp_prep_b.png"])
    prep_once_ok = (prep_walk[1] == [calib.MULTI_PREP_BTN] * calib.MULTI_PREP_TRIES
                    and len([s for s in prep_walk[2] if "按 准备（按钮是彩色的" in s]) == 1
                    and len([s for s in prep_walk[2] if "补按" in s]) == 1
                    and grey_walk[1] == []
                    and len([s for s in grey_walk[2] if "灰色的 取消" in s]) == 1
                    and spin_walk[1] == []
                    and len([s for s in spin_walk[2] if "还在转圈" in s]) == 1
                    and prep_colour >= calib.PREP_BTN_COLOUR > prep_grey_colour
                    and prep_one_site
                    and prep_mutant.count("tap(*MULTI_PREP_BTN") != 1
                    and not [s for s in prep_walk[2] + grey_walk[2] if "按钮亮层没变" in s])
    # ⑥ 匹配页：短等（6 帧 ≈ 2.4 虚拟秒）一下都不许按；等过门就按药丸取消一次；取消次数封顶。
    pop_once_ok = (pop_quick[1] == []
                   and pop_slow[0] is True
                   and pop_slow[1] == [calib.MP_PILL_CENTRE]
                   and len([s for s in pop_slow[2] if "取消这次匹配" in s]) == 1
                   and pop_bound[0] is True
                   and pop_bound[1] == [calib.MP_PILL_CENTRE] * calib.MULTI_MATCH_TRIES
                   and len([s for s in pop_bound[2] if "不再取消" in s]) == 1)
    # ⑦ 返回箭头的静态那一半：整个 `start_live` 里只有走回家的那一支按它（前进那趟按的是
    # 演出开始 / 自由対戦），所以源码里 `tap(*BAND_BACK` 只许出现一次。
    back_once_site = inspect.getsource(calib.start_live).count("tap(*BAND_BACK") == 1
    back_ok = (back_walk[0] is True
               and back_walk[1] == [calib.BAND_BACK] * calib.BAND_BACK_TRIES
               and back_stuck[0] is True
               and back_stuck[1] == [calib.BAND_BACK] * calib.BAND_BACK_TRIES
               and len([s for s in back_stuck[2] if "返回箭头按了没动" in s]) == 1
               and calib.BAND_BACK not in fade[1]
               and back_once_site)

    ok = (draw_ok and not false_prep and diff_ok and grab_ok and bandread_ok and fade_ok
          and before_ok and quiet_ok and noquiet_ok and exp_ok and prep_once_ok and pop_once_ok
          and back_ok and not guard.leaked())
    print(f"抽签：{[(n, g.get('musicId'), round(g.get('score', 0), 3)) for n, g in draws]}"
          f"（要 {want_draw}）；不是准备页却答上来的 {false_prep or '无'}")
    print(f"难度带：单人 {solo_d}/{solo_row}（要 easy/{gameread.DIFF_BAND[0]}）、"
          f"另一张单人页 {solo2_d}/{solo2_row}、多人 {multi_d}/{multi_row} {multi_blk}"
          f"（要 expert/{gameread.DIFF_BANDS[1]}）；截断到 540 行 {cut_d}（要 None）；"
          f"取帧走 detect.grab {grab_ok}（要 True）")
    print(f"只欠一条难度带：封面库藏起来之后 read_band 单人 {band_solo.get('diff')}/"
          f"{band_solo.get('row')}、多人 {band_multi.get('diff')}/{band_multi.get('row')}，"
          f"同一帧 read_song_select 答不出 {not song_none.get('ok')}（要 True）= {bandread_ok}")
    print(f"尾段：淡入顺序零按键 {fade[1]}（要 {[tap_tile, tap_go, tap_start]}），走到 LIVE {fade[0]}；"
          f"同一页在尾段之前按 {before[1][2]}（要 {rank_tap}）")
    print(f"安静页：90 次匹配中弹窗（虚拟时钟 {round(clock.t, 1)} s）之后 other 不交回 "
          f"{quiet_ok}；把安静页撤掉同一个脚本确实交回一次 {noquiet_ok}")
    print(f"结算页：多人 详情/下一步 版第一眼就按 {press_cards[1]}（要 [{calib.EXP_RETRY}]）；"
          f"主页/再次演出 版也第一眼就按 {press_totals[1]}（要 [{calib.EXP_RETRY}]，用户 2026-10-08 "
          f"确认它也是回选曲页，所以那条 10 s 观望必须不在：{not hasattr(calib, 'EXP_WAIT_S')}）；"
          f"单人同一版照按 {press_solo[1]}（要 [{calib.EXP_RETRY}]）= {exp_ok}")
    print(f"准备页：彩色按钮（带色相 {prep_colour:.3f}）连读 6 帧按 {prep_walk[1]}"
          f"（要 {[calib.MULTI_PREP_BTN] * calib.MULTI_PREP_TRIES}：按一下就是准备状态，脚本帧"
          f"不会变灰，所以有界补按走满）；灰色按钮（{prep_grey_colour:.3f}）按 {grey_walk[1]}"
          f"（要 []，灰的 取消 再按就是取消准备）；转圈态（读不到字）按 {spin_walk[1]}"
          f"（要 []，按钮还没出来，一下都不按）；`start_live` 里只有一处 MULTI_PREP_BTN 的 tap "
          f"{prep_one_site}（复制一份就变红 {prep_mutant.count('tap(*MULTI_PREP_BTN') != 1}）= "
          f"{prep_once_ok}")
    print(f"匹配页：短等 {len(pop_quick[2])} 帧按 {pop_quick[1]}（要 []）；等过 {calib.MULTI_MATCH_WAIT_S:.0f}"
          f" s 按 {pop_slow[1]}（要 [{calib.MP_PILL_CENTRE}] = 取消这次匹配）；一直不变时封顶在 "
          f"{pop_bound[1]}（要 {[calib.MP_PILL_CENTRE] * calib.MULTI_MATCH_TRIES}）= {pop_once_ok}")
    print(f"乐队确认页（走回家的那趟）：按返回箭头 {back_walk[1]}（要 "
          f"{[calib.BAND_BACK] * calib.BAND_BACK_TRIES}）；页面一直不动时封顶在 {back_stuck[1]} 并只"
          f"抱怨一次（要 {[calib.BAND_BACK] * calib.BAND_BACK_TRIES}）= {back_ok}；前进那趟按的是 "
          f"{fade[1]}（不含 {calib.BAND_BACK}，源码里只有一处 tap(*BAND_BACK) = {back_once_site}）")
    print(f"落盘 {dumped}，工作 dump 没被碰 {not guard.leaked()}")
    print("PART 16 " + ("PASS" if ok else "FAIL"))
    return ok


def part17():
    """匹配散了要回头（2026-10-09 04:42 的修复，`tools/calib.py:1217`）。

    房间里没凑满人时游戏**自己**把匹配中弹窗收掉（mp24 04:29 与 mp27 04:37：32 s，没到
    `MULTI_MATCH_WAIT_S` 的 120 s，所以那个取消药丸一次都没机会按），掉回 多人选曲页。修复前
    走到这里就被 `TAIL_LIVE_STARTERS` 判死（「只能按开一局的按钮，分不清真假，不再等」）——
    mp23–mp30 那八局里两局就是这么丢的；修复后交回通用处理：按 確定 → 乐队确认页 → 尾段的
    band 分支再按一次 自由対戦，重来一次匹配。两重有界：`rep >= 3`（连续三个 verdict 都是
    select ≈0.75 s，挡掉载入淡入里的误读）与与弹窗取消共用的 `MULTI_MATCH_TRIES` 预算
    （一局最多回头两次）；`prep_read is None` 保证只在**还没抽到曲子**时才走这条路。

    这里三趟（都用虚拟时钟，多人走查的 timeout 有 600 s 下限）：

    ① 匹配散了那一趟必须回头并把这一局走完：日志里有「匹配散了」（1..`MULTI_MATCH_TRIES`
       次 —— 脚本帧不会因为按了就翻页，那 6 帧 select 会把预算走满）、按键里 確定 恰好是
       回头次数 + 1（第一次进乐队确认页、之后每回头一次再进一次）、自由対戦 两次
       （第一次 + 尾段补按）。
    ② 牙：把 `MULTI_MATCH_TRIES` 掐成 0（= 修复前那条路）后，同一个脚本必须**放弃**这一局
       （走查返回 False、打「只能按开一局的按钮」、不许有「匹配散了」）。
    ③ 静态钉住这条路在源码里：三处判据与那一行日志都在。
    """
    frames = {p.name: im for p, im in corpus()}
    need = ("nav_livehome_a.png", "mp_select_a.png", "nav_stuck_band.png",
            "mp_matchpopup_a.png", "mp_prep_a.png", "hud_great1.png")
    missing = [n for n in need if n not in frames]
    if missing:
        print(f"PART 17 FAIL: the corpus is missing {missing}")
        return False

    real_grab, real_tap, real_time = calib.grab, calib.tap, calib.time
    guard = _DumpGuard()
    with guard:
        class Clock:
            """A virtual clock: the multi walk's timeout has a 600 s floor and the tail's escape
            is timed at TAIL_STUCK_S, so a wall-clock run of this tape would take minutes."""

            def __init__(self):
                self.t = 0.0

            def sleep(self, dt):
                self.t += float(dt)

            def perf_counter(self):
                return self.t

            def time(self):
                return self.t

        def walk(script, timeout=20.0):
            """The real walk over a scripted frame source: (returned, taps, log)."""
            seq = list(script)
            taps, said = [], []

            def grab():
                return seq.pop(0) if seq else script[-1]

            def tap(x, y, *a, **k):
                taps.append((int(x), int(y)))

            calib.grab, calib.tap, calib.time = grab, tap, Clock()
            try:
                out = calib.start_live(None, log=said.append, timeout=timeout, multi=True)
            finally:
                calib.grab, calib.tap, calib.time = real_grab, real_tap, real_time
            return out, taps, said

        livehome, sel, band = (frames["nav_livehome_a.png"], frames["mp_select_a.png"],
                               frames["nav_stuck_band.png"])
        popup, prep, field = (frames["mp_matchpopup_a.png"], frames["mp_prep_a.png"],
                              frames["hud_great1.png"])
        # 演出首页 -> 多人选曲页 -> 乐队确认（自由対戦，进尾段）-> 匹配中弹窗 6 帧（不够
        # MULTI_MATCH_WAIT_S，所以取消药丸一次都不按）-> 游戏自己收掉弹窗、掉回选曲页 6 帧
        # （够 rep>=3）-> 乐队确认 10 帧（够尾段补按的 START_SETTLE=8）-> 再匹配 6 帧 ->
        # 准备页 4 帧 -> 现场。
        tape = ([livehome, sel, band] + [popup] * 6 + [sel] * 6 + [band] * 10
                + [popup] * 6 + [prep] * 4 + [field])
        got, taps, said = walk(tape)
        dissolves = [line for line in said if "匹配散了" in line]
        starts = [t for t in taps if t == calib.LIVE_START_BTN]
        goes = [t for t in taps if t == calib.SONG_GO]
        # 脚本帧不会因为按了就翻页（PART 16 的准备页也是这个道理），所以那 6 帧 select 会把
        # 回头预算走满：每回头一次就多一次 確定，多一次 自由対戦 —— 回头次数本身受
        # `MULTI_MATCH_TRIES` 管着，这三条一起钉住「有界 + 每次都真的回去再按一次」。
        fixed_ok = bool(got and 1 <= len(dissolves) <= calib.MULTI_MATCH_TRIES
                        and len(goes) == len(dissolves) + 1 and len(starts) == 2)

        # 牙：回头预算掐成 0 之后，同一个脚本必须判死（修复前那条路）
        saved_tries = calib.MULTI_MATCH_TRIES
        try:
            calib.MULTI_MATCH_TRIES = 0
            broke, _, said_b = walk([livehome, sel, band] + [popup] * 6 + [sel] * 60
                                    + [band] * 10 + [field])
        finally:
            calib.MULTI_MATCH_TRIES = saved_tries
        gave_up = [line for line in said_b if "只能按开一局的按钮" in line]
        tooth_ok = bool((not broke) and gave_up
                        and not [line for line in said_b if "匹配散了" in line])

        # ③ 静态钉住这条路
        src = (ROOT / "tools" / "calib.py").read_text(encoding="utf-8")
        sites = ("and mp_cancels < MULTI_MATCH_TRIES", "hand_back = True", "rep >= 3",
                 "匹配散了，回到选曲页")
        wired = all(s in src for s in sites)
        dumped = sorted(os.listdir(guard.tmp))

    ok = fixed_ok and tooth_ok and wired
    print(f"匹配散了那一趟：走完这一局 {got}、日志「匹配散了」{len(dissolves)} 次"
          f"（1..{calib.MULTI_MATCH_TRIES}）、確定 {len(goes)} 次（要回头次数 + 1 = "
          f"{len(dissolves) + 1}）、自由対戦 {len(starts)} 次（要 2）= {fixed_ok}")
    print(f"牙：把 MULTI_MATCH_TRIES 掐成 0 后同一个脚本判死 {not broke}、"
          f"打「只能按开一局的按钮」{len(gave_up)} 次、没有「匹配散了」"
          f"{not [line for line in said_b if '匹配散了' in line]} = {tooth_ok}")
    print(f"源码三处判据与那一行日志都在 = {wired}")
    print(f"落盘 {dumped}，工作 dump 没被碰 {not guard.leaked()}")
    print("PART 17 " + ("PASS" if ok else "FAIL"))
    return ok


def part18():
    """单人局读到「匹配中弹窗」= 盖在结算页上的弹窗（2026-10-09 用户 m10037 的修复）。

    用户报「游戏当前的故事解锁弹窗为什么识别不出来了，我记得以前可以的」。读数：那一页
    （research/frames/story_now.png）mean 50.67、`_mp_luma` 46.88、MP_PILL_BOX 的 pale 0.921
    ⇒ `_mp_matchpopup` 的两道门全过；而 `_story_close` 对它 False（底部 y552:596 今天有三组亮列，
    判据要求恰好一组）⇒ `screen()` 判它 matchpopup。matchpopup 在 `MP_QUIET_PAGES` 里，走查只看
    不按，g508（16:46:33 → 16:47:10）45 s 后报「没能走回选曲页」，游戏留在弹窗上。以前能过
    （g209 2026-10-01 23:53:45、g488 2026-10-08 11:58）是因为那时它被判成 story。

    修法 = `tools/calib.py` 的 `solo_modal(s, multi)`：单人局**没有**匹配（匹配只在激奏演出里），
    所以这一页只能是盖在结算页上的弹窗，按它的 关闭（STORY_CLOSE）—— 有界（SOLO_MODAL_TRIES 下、
    间隔 SOLO_MODAL_SETTLE），并把那一帧存成 nav_stuck_matchpopup_solo.png。`run.py` 的
    wait_result 里同一条规则（它也会盖在结算页上，g488 的「等结算 16s：上一页 'story'」）。

    这里用**会随按键翻页**的帧源（脚本帧不会因为按了就翻页，见 PART 17）：按过键之后才给乐曲
    选择页，所以「有没有按那一下」直接决定这一趟走不走得完。四趟：

    ① 单人走回家的那趟：必须按恰好那颗药丸（STORY_CLOSE）、走到 select 返回 True。
    ② 牙：把 `solo_modal` 换成「永远不是」后，同一个帧源必须走不完（那一页留在 matchpopup，
       走查只看不按）—— 证明这条规则是载荷。
    ③ 牙：`SOLO_MODAL_TRIES = 0`（不许按）也必须走不完，且日志里有「不再按」。
    ④ 多人不受影响：同一个帧源 `multi=True` 时按的是 MP_PILL_CENTRE（取消匹配）、不是
       STORY_CLOSE，日志里没有「单人局读到匹配弹窗」。
    ⑤ 静态钉住两个入口与那几处判据。
    """
    frames = {p.name: im for p, im in corpus()}
    need = ("mp_matchpopup_a.png", "navgates_select_easy.png")
    missing = [n for n in need if n not in frames]
    if missing:
        print(f"PART 18 FAIL: the corpus is missing {missing}")
        return False

    real_grab, real_tap, real_time = calib.grab, calib.tap, calib.time
    guard = _DumpGuard()
    with guard:
        class Clock:
            """A virtual clock: the walk's deadline is wall-clock and the multi walk has a 600 s
            floor, so a real-time run of these tapes would take minutes (same as PART 17)."""

            def __init__(self):
                self.t = 0.0

            def sleep(self, dt):
                self.t += float(dt)

            def perf_counter(self):
                return self.t

            def time(self):
                return self.t

        popup, sel = frames["mp_matchpopup_a.png"], frames["navgates_select_easy.png"]

        def walk(timeout=20.0, multi=False):
            """The real walk over a source that turns the page over once a key has gone out."""
            taps, said = [], []

            def grab():
                return sel if taps else popup

            def tap(x, y, *a, **k):
                taps.append((int(x), int(y)))

            calib.grab, calib.tap, calib.time = grab, tap, Clock()
            try:
                out = calib.start_live(None, log=said.append, timeout=timeout,
                                       stop_at_select=True, multi=multi)
            finally:
                calib.grab, calib.tap, calib.time = real_grab, real_tap, real_time
            return out, taps, said

        got, taps, said = walk()
        solo_ok = bool(got and taps == [calib.STORY_CLOSE]
                       and [s for s in said if "单人局读到匹配弹窗" in s]
                       and [s for s in said if "按 关闭（第 1/" in s])

        # ② 牙：把这条规则拆掉（= 修复前那条路）
        saved_rule = calib.solo_modal
        try:
            calib.solo_modal = lambda s, multi: False
            broke, taps_b, said_b = walk()
        finally:
            calib.solo_modal = saved_rule
        tooth_rule = bool((not broke) and not taps_b
                          and not [s for s in said_b if "单人局读到匹配弹窗" in s])

        # ③ 牙：预算掐成 0（那一页还在，一下都不许按）
        saved_tries = calib.SOLO_MODAL_TRIES
        try:
            calib.SOLO_MODAL_TRIES = 0
            broke2, taps2, said2 = walk()
        finally:
            calib.SOLO_MODAL_TRIES = saved_tries
        tooth_tries = bool((not broke2) and not taps2
                           and [s for s in said2 if "不再按" in s])

        # ④ 多人那一趟还是走「取消匹配」那条路（这一页在多人里就是匹配弹窗）
        saved_wait = calib.MULTI_MATCH_WAIT_S
        try:
            calib.MULTI_MATCH_WAIT_S = 1.0
            got_m, taps_m, said_m = walk(timeout=60.0, multi=True)
        finally:
            calib.MULTI_MATCH_WAIT_S = saved_wait
        multi_ok = bool(got_m and taps_m == [calib.MP_PILL_CENTRE]
                        and not [s for s in said_m if "单人局读到匹配弹窗" in s])

        # ⑤ 静态钉住两个入口
        src = (ROOT / "tools" / "calib.py").read_text(encoding="utf-8")
        runsrc = (ROOT / "tools" / "run.py").read_text(encoding="utf-8")
        sites = ("def solo_modal(s, multi):", "if solo_modal(s, multi):",
                 "SOLO_MODAL_TRIES = 2", "SOLO_MODAL_SETTLE = 1.2",
                 "nav_stuck_matchpopup_solo.png", "tap(*STORY_CLOSE, i=inj, hold=0.16)")
        wired = all(s in src for s in sites)
        runsites = ('if s == "matchpopup" and not multi:', "multi=args.multi")
        wired_run = all(s in runsrc for s in runsites)
        dumped = sorted(os.listdir(guard.tmp))
        dumped_ok = "nav_stuck_matchpopup_solo.png" in dumped

    ok = solo_ok and tooth_rule and tooth_tries and multi_ok and wired and wired_run and dumped_ok
    print(f"单人走回家撞上那一页：走完这一趟 {got}、按键 {taps}（要 [{list(calib.STORY_CLOSE)}]）"
          f"、日志有「单人局读到匹配弹窗」{bool([s for s in said if '单人局读到匹配弹窗' in s])} "
          f"= {solo_ok}")
    print(f"牙：拆掉 solo_modal 后同一帧源走不完 {not broke}、一个键都没按 {not taps_b} = {tooth_rule}")
    print(f"牙：SOLO_MODAL_TRIES=0 后走不完 {not broke2}、没按键 {not taps2}、"
          f"打「不再按」{bool([s for s in said2 if '不再按' in s])} = {tooth_tries}")
    print(f"多人不受影响：走完 {got_m}、按键 {taps_m}（要 [{list(calib.MP_PILL_CENTRE)}]）、"
          f"没有走单人那条路 {not [s for s in said_m if '单人局读到匹配弹窗' in s]} = {multi_ok}")
    print(f"源码接线：calib {wired}、run.py {wired_run}；落盘 {dumped}（要含那一张）"
          f"= {dumped_ok}，工作 dump 没被碰 {not guard.leaked()}")
    print("PART 18 " + ("PASS" if ok else "FAIL"))
    return ok


def part19():
    """消耗LB（LIVE BOOST）：火力门从「等它回复」改成「拨档然后照常开打」（2026-10-11，用户 m26442）。

    旧的门是：乐队确认页右上角的火力读数 < N 就不点 演出开始，停在这一页每 20 秒重读一次、不设
    等待上限（加成火力约 20 分钟回 1 点，从 0 攒到 3 点可能要一小时）。用户 m26442 要的是**按读数
    花掉它**：≥N 就把 消耗LB 拨到 3 档、不足就拨到 0 档，然后照常开打，不再等。

    这一页还有个真 bug 挡在路上：**弹窗开着时 `screen()` 把它读成 `select`** —— 弹窗没盖住右下角的
    LIVE START，`screen()` 末尾那条 `_blue(img, *SONG_GO)` 照样命中（2026-10-11 真机实测：
    `gameread.read_song_select` ok=False score 0.40、`read_difficulty` 读出 normal row 557），于是
    走查会去按 決定 —— 在弹窗上那一下按的就是一行档位。所以 `lb_popup` 的判据插在 `select` 之前。

    判据必须三条一起（单条都不够，量在 `research/experiments/lbprobe.py`，63 张夹具）：
    ① `LB_ROW_BANDS` 四条带都是「行条」（`b - r > LB_ROW_BLUE`）—— 只靠这条有 **10 张**假阳性
       （`mp_matching_a`/`mp_prep_spin`/`mp_select_a`/`nav_stuck_band` 等，页面底部本来就有条）；
    ② 恰好一行是青的（`g - b > LB_ROW_TEAL`，就是被选中的那一档）—— 加这条只剩 `nav_stuck_finish`；
    ③ OK 框 (520,630,764,686) 里亮蓝占比 > `LB_OK_BLUE` —— 真弹窗 0.974、非弹窗最高 0.656、乐队
       确认页 0.14；加这条 **0 假阳性**。
    """
    frames = {p.name: im for p, im in corpus()}
    need = ("nav_lbpopup_a.png", "nav_lbpopup_b.png", "nav_band_fire12.png",
            "nav_stuck_band.png", "nav_stuck_select.png", "nav_livehome_a.png",
            "hud_great1.png")
    missing = [n for n in need if n not in frames]
    if missing:
        print(f"PART 19 FAIL: the corpus is missing {missing}")
        return False

    pop_a, pop_b = frames["nav_lbpopup_a.png"], frames["nav_lbpopup_b.png"]
    band12, band0 = frames["nav_band_fire12.png"], frames["nav_stuck_band.png"]
    live = frames["hud_great1.png"]

    # ① 判据：两张真弹窗（3 档选中 / 0 档选中）都读 `lbpopup` 且选中档读对；两张乐队确认页都不是
    #    弹窗。乐队确认页的火力读数一张够、一张不够，所以拨档两个方向各有一张真帧。
    reads = []
    for name, im, want in (("nav_lbpopup_a.png", pop_a, 3), ("nav_lbpopup_b.png", pop_b, 0)):
        bars, selected = calib.lb_state(im)
        reads.append((name, calib.screen(im) == "lbpopup", bars, selected, want,
                      round(float(calib.lb_ok(im)), 3)))
    judge = all(s and bars >= len(calib.LB_ROW_BANDS) and selected == want
                for _n, s, bars, selected, want, _o in reads)
    fire12, fire0 = calib.fire_power(band12), calib.fire_power(band0)
    judge_band = bool(not calib.lb_popup(band12) and not calib.lb_popup(band0)
                      and fire12 is not None and fire12[0] >= calib.LB_LEVEL_HIGH
                      and fire0 is not None and fire0[0] < calib.LB_LEVEL_HIGH)

    # ② 走查：帧源按游戏的方式回应点按（消耗LB 开弹窗、点行换档、OK 关掉、演出开始离开这一页）
    real_grab, real_tap, real_time = calib.grab, calib.tap, calib.time
    guard = _DumpGuard()
    with guard:
        class Clock:
            def __init__(self):
                self.t = 0.0

            def sleep(self, dt):
                self.t += float(dt)

            def perf_counter(self):
                return self.t

            def time(self):
                return self.t

        class Source:
            """游戏那一侧：`LB_BTN` 开弹窗（开在 `tier` 档）、点行换档、OK 关掉（`stuck` 时关不掉）、
            演出开始之后这一页就离开（返回一张 LIVE 帧，好让走查正常收场）。"""

            def __init__(self, band, tier, stuck=False):
                self.band, self.tier, self.stuck = band, tier, stuck
                self.open, self.started, self.taps = False, False, []

            def grab(self):
                if self.open:
                    return pop_a if self.tier == calib.LB_LEVEL_HIGH else pop_b
                return live if self.started else self.band

            def tap(self, x, y, *a, **k):
                x, y = int(x), int(y)
                self.taps.append((x, y))
                if (x, y) == calib.LB_BTN:
                    self.open = True
                elif self.open and x == calib.LB_ROW_X:
                    for lvl, yy in calib.LB_ROW_Y.items():
                        if abs(y - yy) <= 6:
                            self.tier = lvl
                elif self.open and (x, y) == calib.LB_OK:
                    if not self.stuck:
                        self.open = False
                elif (x, y) == calib.LIVE_START_BTN:
                    self.started = True

        def walk(src, min_fire, timeout=12.0):
            said = []
            calib.grab, calib.tap, calib.time = src.grab, src.tap, Clock()
            try:
                out = calib.start_live(None, log=said.append, timeout=timeout, min_fire=min_fire)
            finally:
                calib.grab, calib.tap, calib.time = real_grab, real_tap, real_time
            return out, src.taps, said

        # 够门槛（12/15）→ 拨 3 档。弹窗开在 0 档，所以要先点 3 档那一行。
        hi = Source(band12, tier=calib.LB_LEVEL_LOW)
        got_hi, taps_hi, said_hi = walk(hi, min_fire=calib.LB_LEVEL_HIGH)
        hi_ok = bool(got_hi and hi.tier == calib.LB_LEVEL_HIGH
                     and taps_hi == [calib.LB_BTN,
                                     (calib.LB_ROW_X, calib.LB_ROW_Y[calib.LB_LEVEL_HIGH]),
                                     calib.LB_OK, calib.LIVE_START_BTN]
                     and [s for s in said_hi if "拨 3 档" in s])
        # 不足门槛（0/10）→ 拨 0 档。弹窗开在 3 档。
        lo = Source(band0, tier=calib.LB_LEVEL_HIGH)
        got_lo, taps_lo, said_lo = walk(lo, min_fire=calib.LB_LEVEL_HIGH)
        lo_ok = bool(got_lo and lo.tier == calib.LB_LEVEL_LOW
                     and taps_lo == [calib.LB_BTN,
                                     (calib.LB_ROW_X, calib.LB_ROW_Y[calib.LB_LEVEL_LOW]),
                                     calib.LB_OK, calib.LIVE_START_BTN]
                     and [s for s in said_lo if "拨 0 档" in s])
        # 门关着（min_fire=0）→ 一个 LB 键都不许按，档位保持原样。
        off = Source(band0, tier=calib.LB_LEVEL_HIGH)
        got_off, taps_off, said_off = walk(off, min_fire=0)
        off_ok = bool(got_off and taps_off == [calib.LIVE_START_BTN]
                      and off.tier == calib.LB_LEVEL_HIGH and not off.open)
        # 弹窗关不掉：照按 OK 收场，然后走查有界收场 —— 绝不盲目按 演出开始。
        stuck = Source(band12, tier=calib.LB_LEVEL_HIGH, stuck=True)
        got_stuck, taps_stuck, said_stuck = walk(stuck, min_fire=calib.LB_LEVEL_HIGH)
        stuck_ok = bool((not got_stuck) and calib.LB_BTN in taps_stuck
                        and calib.LIVE_START_BTN not in taps_stuck
                        and taps_stuck.count(calib.LB_OK) >= calib.LB_TRIES + 1
                        and [s for s in said_stuck if "拨完 消耗LB 之后读到的是" in s]
                        and [s for s in said_stuck if "还在" in s])

        # ③ 牙：把 `screen()` 里的弹窗判据抠掉，真机那个 bug 必须原样回来 —— 3 档那一帧读成
        #    `select`（`_blue(*SONG_GO)` 照样命中 LIVE START，走查就会去按 決定）；0 档那一帧
        #    落到更后面的 `rewards`（弹窗的 OK 药丸）。两帧都必须不再是 `lbpopup`。
        #
        #    2026-10-20 起 `select` 还多了一道 `_go_pill_wide` 的否决（PART 21 那页），而这一页
        #    的药丸也是宽的 ⇒ 今天抠掉弹窗判据，它落到 `rewards` 而不是 `select`。所以这里放两棵树：
        #    `old`（连宽药丸的否决一起摘掉 = 当年的原貌）必须读成 `select`，证明那个 bug 真存在；
        #    `mutant`（只抠弹窗判据 = 今天的树）必须既不是 `lbpopup` 也不是 `select`，证明第二道
        #    防线独立地挡住了它。
        src_screen = inspect.getsource(calib.screen)
        one_site = src_screen.count("if lb_popup(img):") == 1
        # 只找 `_blue(img, *SONG_GO)`，不带尾部 —— 2026-10-20 起 `select` 那一行还带着
        # `and not _go_pill_wide(img)`，钉死整行会让这条接线判据跟着文案一起红。
        before_select = (src_screen.find("if lb_popup(img):")
                         < src_screen.find("_blue(img, *SONG_GO)"))
        ns = dict(vars(calib))
        ns_old = dict(vars(calib))
        ns_old["_go_pill_wide"] = lambda _img: False
        try:
            body = src_screen.replace("if lb_popup(img):", "if False:")
            exec(compile(body, "<navgates-mutant>", "exec"), ns)
            exec(compile(body, "<navgates-mutant-old>", "exec"), ns_old)
            mutant, old_tree = ns["screen"], ns_old["screen"]
        except Exception as exc:                    # pragma: no cover
            print(f"PART 19 FAIL: the mutant did not compile: {exc}")
            return False
        tooth = bool(one_site and before_select
                     and old_tree(pop_a) == "select"
                     and old_tree(pop_b) not in ("lbpopup",)
                     and mutant(pop_a) not in ("select", "lbpopup")
                     and mutant(pop_b) not in ("lbpopup",)
                     and calib.screen(pop_a) == "lbpopup")
        # ④ 静态钉：门槛用的是 `max(min_fire, LB_LEVEL_HIGH)`（1~2 点不许上 3 档，弹窗自己的红字
        #    写着「如果持有数量未达到设置的消耗数量，将消耗持有的全部数量」），且这一门不再等待。
        live_src = inspect.getsource(calib.start_live)
        wired = bool("max(min_fire, LB_LEVEL_HIGH)" in live_src
                     and live_src.count("set_live_boost(") == 1
                     and "LB_LEVEL_LOW" in live_src
                     and "fire_power(img)" in live_src)
        calib_src = (ROOT / "tools" / "calib.py").read_text(encoding="utf-8")
        run_src = (ROOT / "tools" / "run.py").read_text(encoding="utf-8")
        gone = bool(not hasattr(calib, "FIRE_POLL_S")
                    and "FIRE_POLL_S" not in calib_src and "FIRE_POLL_S" not in run_src)
        dumped = sorted(os.listdir(guard.tmp))
        # 关不掉的弹窗就是「四帧没动」那一页，走查照例把它 dump 成 `nav_stuck_lbpopup.png`（落进
        # `_DumpGuard` 的 scratch 里，不进 research/frames）。
        dumped_ok = "nav_stuck_lbpopup.png" in dumped

    ok = bool(judge and judge_band and hi_ok and lo_ok and off_ok and stuck_ok
              and tooth and wired and gone and dumped_ok)
    for name, s, bars, selected, want, ok_px in reads:
        print(f"判据 {name}：{s}（要 True）、行条 {bars}、选中 {selected}（要 {want}）、"
              f"OK 亮蓝 {ok_px}")
    print(f"乐队确认页不是弹窗 {not calib.lb_popup(band12) and not calib.lb_popup(band0)}、"
          f"火力读数 {fire12}（要 ≥{calib.LB_LEVEL_HIGH}）与 {fire0}"
          f"（要 <{calib.LB_LEVEL_HIGH}）= {judge_band}")
    print(f"够门槛 → 拨 3 档：走完 {got_hi}、档位 {hi.tier}、按键 {taps_hi} = {hi_ok}")
    print(f"不足门槛 → 拨 0 档：走完 {got_lo}、档位 {lo.tier}、按键 {taps_lo} = {lo_ok}")
    print(f"门关着 → 一下都不按：走完 {got_off}、按键 {taps_off}、档位 {off.tier} = {off_ok}")
    print(f"弹窗关不掉：走不完 {not got_stuck}、没按演出开始 "
          f"{calib.LIVE_START_BTN not in taps_stuck}、按键 {taps_stuck} = {stuck_ok}")
    print(f"牙：判据唯一 {one_site}、在 select 之前 {before_select}、抠掉之后读成 "
          f"{mutant(pop_a)!r}/{mutant(pop_b)!r}（当年的树 {old_tree(pop_a)!r}，要 select；今天不许"
          f"再是 select/lbpopup）= {tooth}")
    print(f"源码接线：门槛取 max {wired}、FIRE_POLL_S 已删干净 {gone}；"
          f"工作 dump 没被碰 {not guard.leaked()}（落盘 {dumped}）= {dumped_ok}")
    print(f"小结：判据 {judge}、乐队页 {judge_band}、3 档 {hi_ok}、0 档 {lo_ok}、"
          f"门关 {off_ok}、关不掉 {stuck_ok}、牙 {tooth}、接线 {wired}、删干净 {gone}、"
          f"没落盘 {dumped_ok}")
    print("PART 19 " + ("PASS" if ok else "FAIL"))
    return ok


def part20():
    """到达 乐曲選択 之后，达成奖励列表 会自己盖上来 —— 走查得多看一眼才收工（用户 2026-10-19）。

    「连续演奏打完最后一局，游戏停在显示奖励的那一页」：`start_live(stop_at_select=True)` 读到
    `select` 就 `return True`，此后游戏自己把 达成奖励列表 弹到选曲页上，再没有人关它 —— 下一局
    开工时才会把它当 `rewards` 关掉，可最后一批就停在那儿（用户是手动返回才回来的）。

    ① 到位之后 `_reward` 说「弹窗在这」→ 按一次 `MODAL_CLOSE`（关闭），然后照常返回 True；
    ② 没有弹窗 → 一个键都不按。补看**不许**变成「在选曲页上乱点」：这一页上的蓝色按钮就是 決定，
       按下去就换歌、甚至直接开一局；
    ③ 牙：把 `REWARD_OVER_SELECT_TRIES` 掐成 0，同一个剧本必须一个键都不按（补看真的在起作用）；
    ④ 静态：补看只认 `_reward` / `_bond_detail`，**不许**把 `_modal_close` 也挪进来 —— 它对
       准备页 / 消耗LB弹窗 / 暂停面板都为真（`evidence/nav/mp_prep_a.png`、`nav_lbpopup_a/b.png`、
       `navgates_pause_a.png` 实测），在 `screen()` 里只有排在那些页面后面才安全。
    """
    frames = {p.name: im for p, im in corpus()}
    sel = frames["nav_stuck_select.png"]
    sel_modal = sel.copy()          # 同一张选曲页画布：判据靠**身份**认它，不靠像素
    real_grab, real_tap, real_time = calib.grab, calib.tap, calib.time
    real_reward, real_bond = calib._reward, calib._bond_detail
    close = tuple(calib.MODAL_CLOSE)

    class Clock:
        def __init__(self):
            self.t = 0.0

        def sleep(self, dt):
            self.t += float(dt)

        def perf_counter(self):
            return self.t

        def time(self):
            return self.t

    def walk(with_modal, tries=None):
        """到达选曲页之后，补看第一眼抓到的就是那张「盖着弹窗」的画布。"""
        taps, said = [], []
        seq = [sel, sel_modal, sel, sel, sel, sel, sel, sel] if with_modal else [sel] * 8

        def grab():
            return seq.pop(0) if seq else sel

        def tap(x, y, *a, **k):
            taps.append((int(x), int(y)))

        def reward(img):
            return img is sel_modal

        calib.grab, calib.tap, calib.time = grab, tap, Clock()
        calib._reward, calib._bond_detail = reward, (lambda _img: False)
        saved = calib.REWARD_OVER_SELECT_TRIES
        if tries is not None:
            calib.REWARD_OVER_SELECT_TRIES = tries
        try:
            out = calib.start_live(None, log=said.append, timeout=20.0, stop_at_select=True)
        finally:
            calib.grab, calib.tap, calib.time = real_grab, real_tap, real_time
            calib._reward, calib._bond_detail = real_reward, real_bond
            calib.REWARD_OVER_SELECT_TRIES = saved
        return out, taps, said

    got, taps, said = walk(True)
    one = bool(got) and taps == [close] and any("达成奖励列表" in s for s in said)
    got0, taps0, _ = walk(False)
    none = bool(got0) and taps0 == []
    got_m, taps_m, _ = walk(True, tries=0)
    tooth = bool(got_m) and taps_m == []
    src = inspect.getsource(calib.start_live)
    static = bool("REWARD_OVER_SELECT_TRIES" in src and "_reward(again)" in src
                  and "_bond_detail(again)" in src and "_modal_close(again)" not in src)
    print(f"到位后盖着 达成奖励列表 → 走完 {got}、按键 {taps}（要 [{close}]）= {one}")
    print(f"到位后没有弹窗 → 走完 {got0}、一个键都没按 {taps0 == []} = {none}")
    print(f"牙：补看掐成 0 次 → 同一个剧本按键 {taps_m}（要空）= {tooth}")
    print(f"源码：补看只认 _reward/_bond_detail（不碰 _modal_close）= {static}")
    print("PART 20 " + ("PASS" if (one and none and tooth and static) else "FAIL"))
    return bool(one and none and tooth and static)


def part21():
    """结算分数页之后那几页（2026-10-20 用户 m51338）：右下角那颗蓝药丸只有宽度分得开两族。"""
    frames = {p.name: img for p, img in corpus()}
    sel = ("mp_select_a.png", "nav_stuck_select.png", "navgates_select_easy.png")
    new = "navgates_after_result_a.png"
    missing = [n for n in sel + (new,) if n not in frames]
    if missing:
        print(f"语料缺帧：{missing}")
        print("PART 21 FAIL")
        return False

    def widest(img):
        """那一行蓝色连续段的宽度。y632/y687 是药丸上下边缘，文字的墨从 y≈636 起。"""
        x, best = 1140, 0
        for y in calib.GO_PILL_ROWS:
            row = img[y].astype(np.int16)
            m = (row[:, 2] > 170) & (row[:, 2] - row[:, 0] > 60)
            if not m[x]:
                continue
            a = x
            while a > 0 and m[a - 1]:
                a -= 1
            b = x
            while b < len(m) - 1 and m[b + 1]:
                b += 1
            best = max(best, b - a + 1)
        return best

    narrow = {n: widest(frames[n]) for n in sel}
    wide = widest(frames[new])
    cols = calib.GO_PILL_ROWS == (632, 687) and 202 < calib.GO_PILL_NARROW < 245
    read_new, read_sel = calib.screen(frames[new]), {n: calib.screen(frames[n]) for n in sel}
    kept = bool(cols and read_new == "exp" and all(v == "select" for v in read_sel.values()))
    shape = all(198 <= w <= 202 for w in narrow.values()) and 245 <= wide <= 250

    saved = calib.GO_PILL_NARROW
    try:
        calib.GO_PILL_NARROW = 400                     # 高于结算族那颗
        fell_back = calib.screen(frames[new])
        calib.GO_PILL_NARROW = 150                     # 低于 決定
        eaten = [calib.screen(frames[n]) for n in sel]
    finally:
        calib.GO_PILL_NARROW = saved
    low = fell_back == "select"                       # 门太松 ⇒ 退回老行为（奖励页又成 select）
    high = all(v != "select" for v in eaten)          # 门太紧 ⇒ 真选曲页被 exp 吃掉

    src = inspect.getsource(calib.screen)
    lines = src.splitlines()
    idx = [i for i, ln in enumerate(lines) if 'return "select"' in ln]
    guard = bool(len(idx) == 1
                 and any("_go_pill_wide(img)" in ln for ln in lines[max(0, idx[0] - 3):idx[0] + 1]))
    exp_uses = any("_go_pill_wide(img)" in ln for ln in inspect.getsource(calib._exp_page).splitlines())
    blind = not calib._go_pill_wide(np.zeros((720, 1280, 3), dtype=np.uint8))
    static = bool(guard and exp_uses and blind)

    print(f"药丸宽度：乐曲选择 {narrow}（要 198..202）、新钉的奖励页 {wide}（要 245..250）= {shape}")
    print(f"判决：奖励页 {read_new}（要 exp）、三张乐曲选择 {read_sel}（要全 select）= {kept}")
    print(f"牙：门推到 400 → 奖励页读 {fell_back}（要 select）= {low}；压到 150 → 选曲页 {eaten}"
          f"（要全不是 select）= {high}")
    print(f"源码：select 那一行带 _go_pill_wide、_exp_page 也用它、读不到蓝时返回 False = {static}")
    ok = bool(shape and kept and low and high and static)
    print("PART 21 " + ("PASS" if ok else "FAIL"))
    return ok


def part22():
    """活动主页（2026-10-20 用户 m51939 那一帧）：两颗蓝按钮的页面，一个按钮都不许按。"""
    frames = {p.name: img for p, img in corpus()}
    ev = "navgates_event_home_a.png"
    keep = {"nav_stuck_options.png": "options", "navgates_after_result_a.png": "exp",
            "mp_exp_totals_a.png": "exp", "mp_rank_a.png": "rank",
            "mp_select_a.png": "select"}
    missing = [n for n in (ev,) + tuple(keep) if n not in frames]
    if missing:
        print(f"语料缺帧：{missing}")
        print("PART 22 FAIL")
        return False

    img = frames[ev]
    got = calib.screen(img)
    same = {n: calib.screen(frames[n]) for n in keep}
    # 它凭什么被认出来：演出那颗蓝（PERFORM）与结算族那颗宽药丸同时在。
    marks = bool(calib._blue(img, *calib.PERFORM) and calib._go_pill_wide(img))
    kept = bool(got == "event" and same == keep and marks)

    # 牙 ①：把宽药丸那把尺子关掉（门就此失效）⇒ 这一页必须重新变成会按的那个判决。
    saved = calib._go_pill_wide
    try:
        calib._go_pill_wide = lambda a: False
        off = calib.screen(img)
    finally:
        calib._go_pill_wide = saved
    tooth_gate = off != "event" and calib.screen(img) == "event"

    # 牙 ②：走查那一支必须「零按键」。把 event 分支的正文抠出来，里面不许出现 tap。
    body, inside = [], False
    for ln in inspect.getsource(calib.start_live).splitlines():
        if ln.strip().startswith('elif s == "event":'):
            inside = True
            continue
        if inside:
            if ln.strip().startswith(("elif ", "else:")) or (ln and not ln.startswith(" " * 8)):
                break
            body.append(ln)
    no_tap = bool(body) and not any("tap(" in ln for ln in body) and any(
        "return False" in ln for ln in body)

    # 牙 ③：这一支真的挂在这个判决上 —— 把 event 改名成 other，走查必须回到「8 次读不出」的旧路。
    src = inspect.getsource(calib.screen)
    line = [ln for ln in src.splitlines() if 'return "event"' in ln]
    wired = bool(len(line) == 1)

    print(f"判决：活动主页 {got}（要 event）、其余 {same}（要 {keep}）、两颗蓝同时在 = {marks} = {kept}")
    print(f"牙：关掉宽药丸那把尺子 → 这一页读 {off}（要不再是 event）= {tooth_gate}")
    print(f"牙：event 分支正文 {len(body)} 行、零 tap、含 return False = {no_tap}")
    print(f"源码：screen 里只有一处 return \"event\" = {wired}")
    ok = bool(kept and tooth_gate and no_tap and wired)
    print("PART 22 " + ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    print(f"constants: BOND_MERGE_PX={calib.BOND_MERGE_PX} BOND_TITLE_MIN={calib.BOND_TITLE_MIN} "
          f"RANKUP_PILL={calib.RANKUP_PILL} RANKUP_TITLE_LOW={calib.RANKUP_TITLE_LOW}")
    sys.exit(0 if (part0() and part1() and part2() and part3() and part4() and part5()
                   and part6() and part7() and part8() and part9() and part10()
                   and part11() and part12() and part13() and part14() and part15()
                   and part16() and part17() and part18() and part19()
                   and part20() and part21() and part22()) else 1)
