"""The 多人 opening stamp (`calib.field_back_up`): t0 is the first frame of a *stable* field.

`calib.start_live` hands the walk the first frame that reads `live`, and run.py stamps t0 off that
frame (`field_seen`). In a 多人 room that is one frame too few. mp2's recording (0080_03 expert, note
1 at 3.28 s of the chart) reads live at 181.27 s, then band 0.006 -- the 等待其他玩家 scrim, `screen`
answering 'other' -- for 4.4 s, then live again at 186.05 s. A stamp taken off the 181.27 frame is
4.8 s early and the tight anchor window (`field_seen - 1.2 .. field_seen + 0.6`) lands on the scrim.
The four real rounds escaped on luck: mp5 stamped 12:46:23 and locked 12:46:27 at chart +3.386 s,
mp7 13:17:21/13:17:26 at +4.889 s, mp3 +7.042 s, mp4 +6.307 s -- the wait depends on how fast the
other four load, so it is a matter of time.

Three scripted walks drive the real `field_back_up` with the real detector (`_magenta_back` on real
frames out of evidence/nav -- one pinned live frame, one frame that is not a field):
  1. a field that stays up    -> the stamp is the FIRST frame of the run, not the one that confirmed it
  2. the mp2 shape            -> the lone early look is dropped, the stamp is the second run's first
  3. a field that never comes -> the walk gives up at its own limit and stamps the frame it has

The static half is the wiring: run.py must reach for the stamp only on `--multi`, and the
single-player stamp (`frames()[0]`) has to still be in the else -- that one is what every 单人 round
in the corpus was measured with. Both halves of that shape have their own counterfactual.
"""
import ast
import glob
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
NAV = ROOT / "evidence" / "nav"
RUN = ROOT / "tools" / "run.py"
sys.path.insert(0, str(ROOT / "tools"))
import calib                                                          # noqa: E402


def corpus():
    """The pinned whole-screen frames (same set navgates.py uses; research/ is the working dump)."""
    out = []
    for p in sorted(glob.glob(str(NAV / "*.png"))):
        im = Image.open(p)
        if im.size == (1280, 720):
            out.append((Path(p).name, np.asarray(im.convert("RGB"))))
    return out


class Script:
    """A frame source with its own clock: frames carry the chart timestamps, `now` rides the calls."""

    def __init__(self, seq, step=0.15):
        self.seq = list(seq)
        self.step = step
        self.i = 0
        self.now = 0.0
        self.calls = 0

    def frames(self):
        t, img = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        self.calls += 1
        self.now += self.step
        return t, img

    def perf_counter(self):
        return self.now

    def sleep(self, s):
        self.now += float(s)


def walk(script, limit=calib.FIELD_WAIT_MAX_S):
    """Run the real `field_back_up` over the script, with a clock that cannot stall the probe."""
    class Clock:
        perf_counter = staticmethod(script.perf_counter)
        sleep = staticmethod(script.sleep)

    said = []
    old = (calib.frames, calib.time)
    calib.frames, calib.time = script.frames, Clock
    try:
        stamp = calib.field_back_up(log=said.append, limit=limit)
    finally:
        calib.frames, calib.time = old
    return stamp, said, script


def part1():
    """The three walks. The frames are real; only the timestamps and the clock are scripted."""
    manifest = json.loads((NAV / "MANIFEST.json").read_text(encoding="utf-8"))["frames"]
    frames = corpus()
    field = next(im for n, im in frames if manifest.get(n) == "live")
    blank = next(im for _, im in frames if not calib._magenta_back(im))
    ok_premise = bool(calib._magenta_back(field)) and not calib._magenta_back(blank)

    # 1. a field that stays up: eight looks, 0.20 s apart
    up = [(100.00 + 0.20 * k, field) for k in range(8)]
    stamp1, said1, sc1 = walk(Script(up))
    ok_up = (stamp1 == 100.00 and sc1.calls >= 6
             and sum("画出来了" in s for s in said1) == 1
             and sum("那一下是虚的" in s for s in said1) == 0)

    # 2. the mp2 shape: one look at 181.27, 4.4 s of scrim, then a field from 186.05 on
    mp2 = ([(181.27, field)]
           + [(181.59 + 0.70 * k, blank) for k in range(6)]
           + [(186.05 + 0.20 * k, field) for k in range(7)])
    stamp2, said2, sc2 = walk(Script(mp2))
    ok_mp2 = (stamp2 == 186.05 and stamp2 != 181.27 and stamp2 != 187.25
              and sum("那一下是虚的" in s for s in said2) == 1
              and sum("画出来了" in s for s in said2) == 2)

    # 3. a field that never comes: the walk has to give up on its own limit, not spin
    never = [(200.00 + 0.20 * k, blank) for k in range(40)]
    stamp3, said3, sc3 = walk(Script(never), limit=3.0)
    ok_never = (any(s.startswith("  !!") for s in said3) and stamp3 in [t for t, _ in never]
                and sc3.calls < len(never))

    print(f"语料：LIVE 帧 {calib._magenta_back(field)}、非场地帧 {calib._magenta_back(blank)}"
          f"（要 True / False）= {ok_premise}")
    print(f"一直画着：章 = {stamp1:.2f}（要 100.00，不是确认那一帧），看了 {sc1.calls} 次 = {ok_up}")
    print(f"mp2 形状：章 = {stamp2:.2f}（要 186.05，不是 181.27 也不是 187.25）；"
          f"虚的那一下被丢掉一次 = {ok_mp2}")
    print(f"一直不画：章 = {stamp3:.2f}（要落在脚本里的某一帧上），看了 {sc3.calls} 次就放弃 = {ok_never}")
    return ok_premise and ok_up and ok_mp2 and ok_never


def calls(nodes):
    return [c for s in nodes for c in ast.walk(s) if isinstance(c, ast.Call)]


def wired(src):
    """run.py stamps t0 with `field_back_up` on `--multi`, and with `frames()[0]` everywhere else."""
    for n in ast.walk(ast.parse(src)):
        if not isinstance(n, ast.If):
            continue
        if "multi" not in {a.attr for a in ast.walk(n.test) if isinstance(a, ast.Attribute)}:
            continue
        got = {getattr(c.func, "id", "") for c in calls(n.body)}
        other = {getattr(c.func, "id", "") for c in calls(n.orelse)}
        if "field_back_up" in got and "frames" in other:
            return True
    return False


def part2():
    """The wiring, and its two counterfactuals: the wrong flag, and no single-player path left."""
    src = RUN.read_text(encoding="utf-8")
    ok_real = wired(src) and src.count("field_back_up(") == 1
    wrong = src.replace("if args.multi:\n            # 多人房间在开场前",
                        "if args.random:\n            # 多人房间在开场前", 1)
    gone = src.replace("        else:\n            field_seen = frames()[0]\n", "", 1)
    ok_mut = (wrong != src and gone != src
              and not wired(wrong) and not wired(gone))
    print(f"接线：只有 --multi 走开场章、单人仍取 frames()[0] = {ok_real}；"
          f"把条件换成 --random -> {not wired(wrong)}、删掉单人那半 -> {not wired(gone)}")
    return ok_real and ok_mut


def main():
    ok = part1() and part2()
    print("FIELDSTAMP " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
