"""The counter recorder: full-rate pixels, off the sampling thread, read back by the real reader.

#111 (how many judged objects one long note contributes) has its reader, its regression and its
framework -- what it never had is a round's worth of counters at the capture's own cadence. This
probe holds down the thing that produces it, because everything it can get wrong is silent:

  * doing I/O (or the 93.6 ms/frame reader) on the sampling thread would cost a *round's* accuracy
    to produce a diagnostic -- the queue must absorb it and `offer()` must stay microseconds;
  * a lossy codec corrupts exactly the pixels being counted (mp4v: max channel delta 63, 2028
    pixels over threshold in the box, measured) -- the file must be bit-exact;
  * a stalled writer must drop and say so, not grow without bound.

PART 1 `offer()` on the sampling thread; PART 2 the file round-trips bit-exactly with its
timestamps; PART 3 the *pinned reader* reads the recording (a real crop with a known answer);
PART 4 the bound and its counterfactual (unbounded = no drops); PART 5 the writer keeps up with a
9 ms capture; PART 6 the flag refuses to start a round without 看盘与快采.

No device, no emulator, no round: real counter crops from `evidence/hud/counters/`, a temp dir, and
one subprocess for the flag.

Run from the repo root:  python tools/probes/counterrec.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time

import numpy as np
from PIL import Image

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
CROPS = os.path.join(ROOT, "evidence", "hud", "counters")


def _crops():
    """Two real crops with pinned answers, as (rgb array, expected counters)."""
    man = json.load(open(os.path.join(CROPS, "MANIFEST.json"), encoding="utf-8"))
    out = []
    for name in sorted(man)[:2]:
        img = np.asarray(Image.open(os.path.join(CROPS, name)).convert("RGB"))
        out.append((img, man[name]["counters"], man[name]["offset"]))
    if len(out) < 2:
        raise SystemExit("need two pinned counter crops in evidence/hud/counters/")
    return out


def _frame(crop, offset):
    """A 720p frame with the crop pasted where it belongs."""
    full = np.zeros((720, 1280, 3), np.uint8)
    ox, oy = offset
    full[oy:oy + crop.shape[0], ox:ox + crop.shape[1]] = crop
    return full


def main():
    import cv2
    import recorder
    from recorder import CountersRecorder

    (crop_a, want_a, off_a), (crop_b, want_b, off_b) = _crops()
    frame_a, frame_b = _frame(crop_a, off_a), _frame(crop_b, off_b)
    tmp = tempfile.mkdtemp(prefix="counterrec-")
    bad = []

    # PART 1 -- the sampling side pays microseconds and touches no file. The burst here outruns
    # the writer on purpose (2000 offers back to back is ~25x a round's rate): what it proves is
    # that the caller never waits -- the drops it causes are PART 4's subject.
    path = os.path.join(tmp, "a.counters.avi")
    rec_a = CountersRecorder(path).start()
    t0 = time.perf_counter()
    for i in range(2000):
        rec_a.offer(float(i) * 0.009, frame_a)
    per = (time.perf_counter() - t0) / 2000 * 1000
    ok1 = per < 0.05
    print(f"offer() 每次 {per:.3f} ms（判据 <0.05，采样线程只入队）；"
          f"这一串把队列灌满了（丢弃 {rec_a.dropped}，那是 PART 4 的事）")
    if not ok1:
        bad.append(f"offer() 太贵：{per:.3f} ms/帧")
    rec_a.close()

    # PART 2 -- the file is the stream, bit for bit, with its own stamps. Sized inside the queue
    # on purpose: this part is about fidelity, and a burst that outruns the writer is PART 4's
    # subject (a real round offers ~110 frames a second against a writer that does ~1700).
    rec = CountersRecorder(os.path.join(tmp, "r.counters.avi")).start()
    stamps = [round(i * 0.009, 4) for i in range(300)]
    for t in stamps:
        rec.offer(t, frame_a)
    rec.close()
    path = rec.path
    cap = cv2.VideoCapture(path)
    n, exact = 0, True
    x0, y0, x1, y1 = recorder.BOX
    want = frame_a[y0:y1, x0:x1]
    while True:
        ok, got = cap.read()
        if not ok:
            break
        if not np.array_equal(got, want):
            exact = False
        n += 1
    cap.release()
    idx = [json.loads(l) for l in open(os.path.join(tmp, "r.counters.jsonl"), encoding="utf-8")]
    ok2 = n == 300 and exact and len(idx) == 300 and [d["t"] for d in idx] == stamps
    print(f"录像回读：{n} 帧（逐位相等={exact}）索引 {len(idx)} 行，"
          f"时间戳{'一致' if [d['t'] for d in idx] == stamps else '不一致'}；"
          f"{os.path.getsize(path) / 1e6:.1f} MB")
    if not ok2:
        bad.append(f"录像回读对不上：{n} 帧 exact={exact} 索引 {len(idx)} 行")

    # PART 3 -- the recorder's geometry is the reader's geometry: read a recorded frame with the
    # pinned reader and get the pinned answer (this is the whole point of the file).
    import hudread
    back = cv2.VideoCapture(path)
    back.set(cv2.CAP_PROP_POS_FRAMES, 0)
    ok, got = back.read()
    back.release()
    canvas = np.zeros((720, 1280, 3), np.uint8)
    x0, y0, x1, y1 = recorder.BOX
    canvas[y0:y1, x0:x1] = got
    read = hudread.counters_arr(canvas)
    ok3 = read == want_a
    print(f"读数器读录像里的那一帧：{read}（钉住的答案 {want_a}）")
    if not ok3:
        bad.append(f"读数器读不回录像：{read} != {want_a}")

    # PART 4 -- bounded, and the drops are counted. The case is a writer that is not draining
    # (here: one that was never started), and the counterfactual is the unbounded queue this
    # design's first draft would have had -- same burst, nothing dropped, nothing said.
    slow = CountersRecorder(os.path.join(tmp, "b.counters.avi"), queue_max=32)
    for i in range(200):
        slow.offer(float(i), frame_b)
    ok4 = slow.dropped > 0 and slow._q.qsize() <= 32
    print(f"写手不排空时 offer 200 次：入队 {slow._q.qsize()}（上限 32）丢弃 {slow.dropped}")
    if not ok4:
        bad.append(f"队列没有界：qsize={slow._q.qsize()} dropped={slow.dropped}")
    free = CountersRecorder(os.path.join(tmp, "c.counters.avi"), queue_max=10 ** 6)
    for i in range(200):
        free.offer(float(i), frame_b)
    teeth = free.dropped == 0 and free._q.qsize() == 200
    print(f"反事实（不设界）：丢弃 {free.dropped}，入队 {free._q.qsize()} -> 这一关看得见差别={teeth}")
    if not teeth:
        bad.append("反事实没被看见：不设界时也发生了丢弃")

    # PART 5 -- the writer keeps up with the capture (0.73 ms/frame measured for the crop; a 9 ms
    # cadence is the budget). Fed as fast as the sampling thread would, with a live writer.
    rec3 = CountersRecorder(os.path.join(tmp, "d.counters.avi")).start()
    t0 = time.perf_counter()
    for i in range(600):
        rec3.offer(float(i) * 0.009, frame_a if i % 2 else frame_b)
    rec3.close()
    per_write = (time.perf_counter() - t0) / 600 * 1000
    ok5 = per_write < 4.0 and rec3.dropped == 0
    print(f"连灌 600 帧（含写盘）：{per_write:.3f} ms/帧，丢弃 {rec3.dropped}（判据 <4 ms、0 丢）")
    if not ok5:
        bad.append(f"写手跟不上：{per_write:.3f} ms/帧 丢弃 {rec3.dropped}")

    # PART 6 -- the flag refuses to start a round without its partners.
    r = subprocess.run([sys.executable, os.path.join(TOOLS, "run.py"),
                        os.path.join(tmp, "nonexistent.hits.json"), "--record-counters"],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    said = "--record-counters 需要 --watch-hud 与 --fastcap" in (r.stdout or "")
    ok6 = r.returncode == 1 and said
    print(f"只给 --record-counters：rc={r.returncode}，拒绝了={'是' if said else '否'}")
    if not ok6:
        bad.append(f"缺配套参数时没有拒绝：rc={r.returncode}")

    for b in bad:
        print("   " + b)
    print("counterrec " + ("PASS" if not bad else "FAIL"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
