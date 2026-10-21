"""The regression evidence, kept out of research/.

research/ is the pipeline's working dump: gitignored, growing with every round, and impossible to
clean -- because two probes globbed it as their corpus, every forensic frame was simultaneously
"this run's evidence" and "part of a regression", so nothing was ever safely deletable.

evidence/ is the opposite: a fixed, committed set, small enough that a fresh clone can run the
regressions, and the rule that picks it lives in this file. Rebuild after a round that produced
new pages or new judgements:

    python tools/evidence.py build            # everything
    python tools/evidence.py build --only hud # one bucket
    python tools/evidence.py status           # what is here, and what research/ has that isn't

Five buckets:

  nav/     whole-screen frames, one or two per page verdict plus every frame a navgates part names
           outright. MANIFEST.json records the verdict each one must keep; that is the half of the
           page-recognition regression that proves an old page was not lost while a new one was
           added.
  hud/box/ the counter crop only (x 1148-1190, y 156-243) for every committed HUD event. hudgate
           reads nothing outside that box, so the crop carries the whole corpus at ~1/300th the
           bytes -- 469 MB of full frames became a couple of MB of digits.
  detect/  the frames spritebars measures sprite bars on, which do need the whole field.
  view/    the panel's own baselines -- every page, both palettes -- as photographed against a
           fixture corpus. Not built from research/ like the other three: the baselines live
           committed under evidence/view/ (flet_baselines/ 2026-10-21 退役) and `probes/fletviewcheck.py` only ever
           reads them, deliberately, because a baseline that absorbs an unintended change is worse than
           no baseline. Two kinds of file sit in this bucket and different code reads each: the
           eight `flet_*.png` are read by `probes/fletgui.py`, which *builds* their names (`VIEW` +
           name + ".png" over its `SHOTS` tuple) -- a filename grep finds no reference to any of
           them, which is how a 2026-10-06 audit came to count eight orphans that do not exist.
           The one file no code reads is `flet_real_history.png`: it is the real-device evidence
           for the g341 link (AP 759/759) quoted in `AGENTS.md`, kept as a record rather than as a
           fixture.
  pins/    the bytes each pinned result was flown on, zlib'd, plus INDEX.json. Not frames and not
           built by `build`: `fetch_charts.py --pin` writes it, because the point is that a flown
           geometry survives its disk. research/charts/ is gitignored, so until this existed the
           bytes behind an ALL PERFECT lived on one machine -- 0050_03 lost them to a rebuild and
           its result became a claim nobody can check.
"""
import argparse, collections, glob, json, os, re, shutil, sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calib                                                   # noqa: E402
import hudwatch                                                # noqa: E402
import rlog                                                    # noqa: E402

# Same guard as run.py / audit_charts.py: a console on the GBK codepage kills a Chinese line
# mid-print, and status() is all Chinese.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

RESEARCH = Path(rlog.RESEARCH)          # rlog owns where research/ lives; never re-derive it
FRAMES = Path(rlog.FRAMES)              # ... and the same for the bucket the stills live in
ROOT = RESEARCH.parent
EVIDENCE = Path(rlog.EVIDENCE)          # ... and where its committed counterpart lives
NAV = EVIDENCE / "nav"
HUD_BOX = EVIDENCE / "hud" / "box"
DETECT = EVIDENCE / "detect"
PINS = Path(rlog.PINS)
MANIFEST = NAV / "MANIFEST.json"

# The five counter rows and the right-aligned digit column -- everything hudwatch reads.
HUD_CROP = (min(y for _r, y0, y1 in hudwatch.ROWS for y in (y0, y1)),
            max(y for _r, y0, y1 in hudwatch.ROWS for y in (y0, y1)),
            hudwatch.X0, hudwatch.X1)
HUD_PAT = re.compile(r"hud_(.+?)_(great|good|bad|miss)(\d+)\.png")
PER_VERDICT = 2              # whole-screen frames kept per page verdict
MORE = {"live": 8}           # the field is where a menu cue gets falsely claimed: it fills the
                             # screen with bright blue, and 首页's cue reads blue discs


def _copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if not os.path.exists(dst) or os.path.getsize(src) != os.path.getsize(dst):
        shutil.copyfile(src, dst)
        return True
    return False


def build_nav():
    """Every frame a navgates part names, plus PER_VERDICT whole frames per page verdict.

    evidence/ is itself a source. The first build copies frames out of research/, and the cleanup
    that follows deletes those -- so a rebuild that read only research/ would quietly shrink the
    pinned corpus to whatever happens to be on disk this week. Not hypothetical: the first re-run
    after the research/ tidy-up dropped 26 of the 48 pinned frames, 首页 itself among them.
    """
    named = {os.path.basename(p): p for p in glob.glob(str(NAV / "*.png"))}
    for p in glob.glob(str(RESEARCH / "**" / "*.png"), recursive=True):
        n = os.path.basename(p)
        if re.match(r"^(navgates_|nav_|nav_stuck_|start_live_stuck|now_after_bond_close)", n):
            named.setdefault(n, p)
    # What the corpus already covers, counted before sampling: without this every build adds a
    # fresh round of samples on top of the ones it pinned last time, and the tree only grows.
    have = collections.defaultdict(list)
    for n, src in sorted(named.items()):
        im = np.asarray(Image.open(src).convert("RGB"))
        if im.shape[:2] == (720, 1280):
            have[calib.screen(im)].append(n)
    by_verdict = collections.defaultdict(list)
    for p in sorted(glob.glob(str(RESEARCH / "**" / "*.png"), recursive=True)):
        n = os.path.basename(p)
        if n in named or not n.startswith(("hud_", "result_", "split_", "now_", "chang_", "dets_")):
            continue
        try:
            im = np.asarray(Image.open(p).convert("RGB"))
        except Exception:                                       # noqa: BLE001 - unreadable png
            continue
        if im.shape[:2] != (720, 1280):
            continue
        verdict = calib.screen(im)
        room = MORE.get(verdict, PER_VERDICT) - len(have.get(verdict, [])) - len(by_verdict[verdict])
        if room > 0:
            by_verdict[verdict].append(p)
    manifest = {}
    for n, src in sorted(named.items()):
        dst = str(NAV / n)
        if os.path.abspath(src) != os.path.abspath(dst):
            _copy(src, dst)
        manifest[n] = calib.screen(np.asarray(Image.open(dst).convert("RGB")))
    for verdict, paths in sorted(by_verdict.items()):
        for p in paths:
            n = os.path.basename(p)
            _copy(p, str(NAV / n))
            manifest[n] = verdict
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump({"per_verdict": PER_VERDICT, "frames": manifest}, f, ensure_ascii=False, indent=1)
    return len(manifest), len(set(manifest.values()))


def build_hud():
    """Crop the corpus down to the digits: the box hudgate reads, and nothing else.

    Reads FRAMES, not RESEARCH: hudwatch writes its stills through `subdir(FRAMES)` (and parks an
    aborted attempt's as `hud_<tag>-a<k>_<row><n>.png`, which HUD_PAT takes unchanged), so the old
    `RESEARCH / "hud_*.png"` glob matched nothing -- a builder that found 0 inputs and reported
    success, while the 825 committed crops under evidence/hud/box could never be refreshed.
    """
    os.makedirs(HUD_BOX, exist_ok=True)
    n = 0
    for p in sorted(glob.glob(str(FRAMES / "hud_*.png"))):
        m = HUD_PAT.search(os.path.basename(p).replace("\\", "/"))
        if not m:
            continue
        y0, y1, x0, x1 = HUD_CROP
        im = np.asarray(Image.open(p).convert("RGB"))[y0:y1, x0:x1]
        dst = HUD_BOX / os.path.basename(p)
        Image.fromarray(im).save(dst)
        n += 1
    return n


def build_detect():
    """Re-copy the spritebars fixtures. Their producer is a forensic script, not a tool in this
    tree (`detect.py` cites them from the 0056_03 opening recording), so this reads FRAMES for the
    same reason build_hud does -- and a run that finds nothing is now a failure, not a printout:
    reporting "0 帧" next to a success exit code is how a builder silently stops working.
    """
    n = 0
    for p in sorted(glob.glob(str(FRAMES / "spritebars_*.png"))):
        _copy(p, str(DETECT / os.path.basename(p)))
        n += 1
    return n


# The digit column plus a margin, and the origin it was cut from: hudread reads fixed screen
# geometry, so the crop is pasted back onto a black frame at this offset rather than teaching the
# reader a second set of coordinates.
HUD_COUNT_BOX = (1100, 118, 1210, 252)
HUD_COUNT_DIR = EVIDENCE / "hud" / "counters"
HUD_COUNT_MANIFEST = HUD_COUNT_DIR / "MANIFEST.json"


def build_hudcount(limit=10):
    """Pin a handful of event frames with the counter values they must keep reading as.

    `hudread` is a new judgement (it decodes the in-song HUD counters, which nothing did before), so
    it gets the same treatment as the page recogniser: evidence first, then the rule. Only frames
    where all five rows read *and* the moved row agrees with the count the log claims are pinned --
    those are the ones where two independent instruments agree on the truth.
    """
    import hudread
    import resultread as rr
    os.makedirs(HUD_COUNT_DIR, exist_ok=True)
    tpl = rr.load_templates()
    manifest = {}
    for p in sorted(glob.glob(str(RESEARCH / "frames" / "hud_*.png")))[:400]:
        if len(manifest) >= limit:
            break
        c = hudread.counters(p, tpl)
        if any(v is None for v in c.values()):
            continue
        m = re.match(r"hud_(.+?)_(great|good|bad|miss)(\d+)\.png", os.path.basename(p))
        if not m or c[m.group(2).upper()] < int(m.group(3)):
            continue
        im = Image.open(p).convert("RGB")
        x0, y0, x1, y1 = HUD_COUNT_BOX
        name = os.path.basename(p)
        im.crop((x0, y0, x1, y1)).save(HUD_COUNT_DIR / name)
        manifest[name] = {"offset": [x0, y0], "counters": c,
                          "ordinal": hudread.ordinal(c)}
    with open(HUD_COUNT_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    return len(manifest)


BUILDERS = {"nav": build_nav, "hud": build_hud, "detect": build_detect,
            "hudcount": build_hudcount}


def size(p):
    return sum(os.path.getsize(os.path.join(r, f)) for r, _d, fs in os.walk(p) for f in fs)


def status():
    for name, d in (("nav", NAV), ("hud/box", HUD_BOX), ("detect", DETECT)):
        cnt = len(glob.glob(str(d / "**" / "*.png"), recursive=True)) if d.exists() else 0
        print(f"{name:9s} {cnt:5d} 帧  {size(d)/1048576:7.1f} MB")
    zz = len(glob.glob(str(PINS / "*.zz"))) if PINS.exists() else 0
    print(f"{'pins':9s} {zz:5d} 份飞过的谱面字节  {size(PINS)/1048576:7.1f} MB"
          "   （fetch_charts.py --pin 写的，不在 build 里）")
    print(f"合计      {sum(len(glob.glob(str(d / '**' / '*.png'), recursive=True))
                          for d in (NAV, HUD_BOX, DETECT)):5d} 帧  "
          f"{sum(size(d) for d in (NAV, HUD_BOX, DETECT, PINS) if d.exists())/1048576:7.1f} MB")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("build", "status"))
    ap.add_argument("--only", default="nav,hud,detect")
    a = ap.parse_args()
    if a.cmd == "status":
        status()
        return 0
    empty = []
    for name in a.only.split(","):
        got = BUILDERS[name]()
        if name == "nav":
            print(f"nav: {got[0]} 帧，覆盖 {got[1]} 种页面判据")
        else:
            print(f"{name}: {got} 帧")
        if (got[0] if name == "nav" else got) == 0:
            # A builder whose inputs are gone must not exit 0: `hud` and `detect` both globbed a
            # directory nothing writes to and reported success for months, which is why the 825
            # committed crops under evidence/hud/box could not be refreshed and nobody noticed.
            empty.append(name)
    if empty:
        print(f"!! {'/'.join(empty)} 一个输入都没找到——源帧不在 {FRAMES}，"
              f"这份语料现在无法重建（不是「已经是最新」）")
        status()
        return 1
    status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
