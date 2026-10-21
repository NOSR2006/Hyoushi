"""Put every judgement of a run onto the chart timeline, from a device screenrecord of the LIVE.

The host-side recorder (rec.py) runs at 3.2 fps because it pays a screencap round trip per frame:
that is a +-310 ms quantiser on every popup it happens to catch, and it misses most of them. The
device's own `screenrecord` runs at the display rate and costs the host nothing, so one run pays
only the device CPU the encoder uses.

Two signals are read per frame:
  * the judgement popup at the field centre -- the word alone is a MISS, `<n>ms` over the word is
    anything else, matched against a known MISS frame rather than OCRed;
  * the MISS counter in the HUD, which is persistent, so a box diff localises the increment to a
    single frame independent of how long a popup stays on screen.

The chart time of a frame is its video stamp minus t0, and t0 is re-derived from the recorded blob
stream with the same vote the live anchor uses (thousands of blobs against the live anchor's
handful), so the frame timeline never depends on host clocks staying in step.
"""
import argparse
import json
import sys

import numpy as np

sys.path.insert(0, "tools")
from calib import _magenta_lines  # noqa: E402  (the same field test the menu walker uses)

WORD = (520, 422, 770, 490)        # the judgement word, full-frame
MS = (580, 368, 740, 418)          # the '<n>ms' line drawn above it
MISS_BOX = (1145, 220, 1210, 252)  # the MISS counter's digits in the in-song HUD


def white(arr, thr=210):
    return arr.min(2) > thr


def decode(path, tpl, blob_stride=1, log=print):
    """One streaming pass: per-frame popup metrics, the MISS-counter signature, and note blobs."""
    import cv2
    from detect import note_blobs

    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ntpl = int(tpl.sum())
    rows, sigs, dets = [], [], []
    i = -1
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        i += 1
        stamp = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        rgb = bgr[:, :, ::-1]
        field = _magenta_lines(rgb)
        ov = wpx = width = mspx = 0
        if field:
            w = white(rgb[WORD[1]:WORD[3], WORD[0]:WORD[2]])
            wpx = int(w.sum())
            if wpx:
                ov = int((w & tpl).sum()) / ntpl
                cols = np.flatnonzero(w.any(0))
                width = int(cols[-1] - cols[0]) if len(cols) else 0
            mspx = int((rgb[MS[1]:MS[3], MS[0]:MS[2]].max(2) > 165).sum())
            mb = rgb[MISS_BOX[1]:MISS_BOX[3], MISS_BOX[0]:MISS_BOX[2]].min(2) > 200
            sigs.append((i, np.packbits(mb).tobytes().hex()))
            if i % blob_stride == 0:
                for y, x in note_blobs(rgb):
                    dets.append((stamp, float(y), float(x)))
        rows.append([i, round(stamp, 4), int(field), round(ov, 3), wpx, width, mspx])
        if i % 300 == 0:
            log(f"  {i}/{n} frames decoded")
    log(f"  {i + 1} frames, {len(dets)} blobs, {len(sigs)} field frames")
    return rows, sigs, dets, ntpl


def sig_diff(a_hex, b_hex):
    a = np.unpackbits(np.frombuffer(bytes.fromhex(a_hex), dtype=np.uint8))
    b = np.unpackbits(np.frombuffer(bytes.fromhex(b_hex), dtype=np.uint8))
    return int(np.logical_xor(a, b).sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--hits", default="research/archive/data/mayoiuta_ex.hits.json")
    ap.add_argument("--t0-run", type=float, help="the firing t0 the run printed (host clock)")
    ap.add_argument("--field-host", type=float, help="'LIVE field at host ...' from the run log")
    ap.add_argument("--prev-tag", help="reuse the blob/rows pass of another tag instead of decoding")
    ap.add_argument("--miss-frame", default="research/recordings/rec_a17/judge_0135.png",
                    help="a host PNG that shows the MISS word (lossless, so a clean template)")
    ap.add_argument("--origin", default="250,340", help="where that PNG was cropped from")
    ap.add_argument("--ov", type=float, default=0.45, help="template overlap for a MISS word")
    ap.add_argument("--width-max", type=int, default=140)
    ap.add_argument("--counter-diff", type=int, default=25, help="bits changed = counter moved")
    ap.add_argument("--t0", type=float, help="skip the blob vote and use this video-clock t0")
    ap.add_argument("--no-blobs", action="store_true", help="scan popups only (fast)")
    ap.add_argument("--skip", type=int, default=0,
                    help="notes the run reported skipping, so the offline schedule matches it")
    args = ap.parse_args()

    log = print
    tag = args.tag
    cache = f"research/vidscan_{args.prev_tag or tag}.json"

    if args.prev_tag:
        d = json.load(open(cache, encoding="utf-8"))
        rows, sigs, dets, t0 = d["rows"], d["sigs"], d["dets"], d["t0"]
        if args.t0 is not None:
            t0 = args.t0
        log(f"loaded {len(rows)} frames, {len(dets)} blobs from {cache} (t0={t0:.3f})")
    else:
        from PIL import Image
        ox, oy = (int(v) for v in args.origin.split(","))
        png = np.asarray(Image.open(args.miss_frame).convert("RGB"))
        # WORD is a full-frame box; the PNG is a crop, so the box is translated into it.
        tpl = white(png[WORD[1] - oy:WORD[3] - oy, WORD[0] - ox:WORD[2] - ox])
        if tpl.shape != (WORD[3] - WORD[1], WORD[2] - WORD[0]):
            raise SystemExit(f"template box {WORD} does not fit {args.miss_frame} "
                             f"origin {args.origin}")
        log(f"MISS template: {int(tpl.sum())} px from {args.miss_frame}")
        rows, sigs, dets, _ = decode(args.video, tpl, log=log)
        t0 = None
        if not args.no_blobs:
            t0 = anchor(rows, dets, args, log)
        d = {"rows": rows, "sigs": sigs, "t0": t0,
             "dets": dets if len(dets) < 200000 else []}
        json.dump(d, open(cache, "w", encoding="utf-8"))
        log(f"pass -> {cache}")

    chart = json.load(open(args.hits, encoding="utf-8"))
    if t0 is None:
        log("no t0: pass --t0 or let the vote run; popup times are video-clock only")
        t0 = 0.0

    events(rows, sigs, dets, chart, t0, args, log, tag)


def anchor(rows, dets, args, log):
    from detect import C_FIELD, JUDGE_Y, VP_MOTION, vote_t0

    notes = [(h["t_ms"] / 1000.0, h["lane"])
             for h in json.load(open(args.hits, encoding="utf-8"))]
    est = None
    if args.t0_run is not None and args.field_host is not None:
        fv = next((r[1] for r in rows if r[2]), None)
        est = args.t0_run - args.field_host + fv
        log(f"field in video at {fv:.3f}s; host says t0 - field = {args.t0_run - args.field_host:+.3f}s"
            f" -> t0_video ~ {est:.3f}")
    lo = est - 15.0 if est is not None else None
    hi = est + 15.0 if est is not None else None
    t0, peak, second, _ = vote_t0(dets, notes, C_FIELD, VP_MOTION, JUDGE_Y, lo=lo, hi=hi)
    if t0 is None:
        log("blob vote found nothing")
        return None
    log(f"blob vote: t0={t0:.3f} peak={peak} second={second} from {len(dets)} blobs"
        + (f", delta vs host-link {t0 - est:+.3f}s" if est is not None else ""))
    return t0


def events(rows, sigs, dets, chart, t0, args, log, tag):
    # judgement popups: runs of frames whose word is the MISS shape
    pops = []
    prev = -9
    for r in rows:
        i, stamp, field, ov, wpx, width, mspx = r
        miss = bool(field) and ov >= args.ov and 0 < width <= args.width_max
        if miss and i - prev <= 3 and pops:
            pops[-1][1] = i
            pops[-1][3] = stamp
            pops[-1][4] += 1
        elif miss:
            pops.append([i, i, stamp, stamp, 1, ov])
        prev = i if miss else prev

    # MISS counter: a binarized-digit change between consecutive field frames
    counters = []
    for (i0, a), (i1, b) in zip(sigs, sigs[1:]):
        d = sig_diff(a, b)
        if d >= args.counter_diff:
            counters.append((i1, d))

    def ct(x):
        return x - t0

    stamp_of = {r[0]: r[1] for r in rows}
    log(f"\n=== judgement popups shaped like MISS: {len(pops)}")
    out = {"t0": t0, "miss_popups": [], "counter_moves": []}
    for i0, i1, ts, te, nf, ov in pops:
        c = ct(ts)
        rec = {"i0": i0, "i1": i1, "t": round(ts, 3), "t_end": round(te, 3),
               "chart": round(c, 3), "overlap": ov}
        out["miss_popups"].append(rec)
        log(f"  frame {i0:4d}-{i1:4d} video {ts:8.3f} chart {c:7.3f}s ({nf} frames, ov {ov:.2f})")
        for line in candidates(chart, c):
            log("      " + line)
        for line in actions_near(chart, c, args.skip):
            log("      " + line)

    log(f"\n=== MISS counter moved {len(counters)} times")
    for i, d in counters:
        c = ct(stamp_of[i])
        out["counter_moves"].append({"i": i, "video": round(stamp_of[i], 3),
                                     "chart": round(c, 3), "bits": d})
        log(f"  frame {i:4d} video {stamp_of[i]:8.3f} chart {c:7.3f}s (bits {d})")
        for line in candidates(chart, c):
            log("      " + line)
        for line in actions_near(chart, c, args.skip):
            log("      " + line)

    json.dump(out, open(f"research/vid_{tag}.json", "w", encoding="utf-8"))
    log(f"\n-> research/vid_{tag}.json")


def candidates(chart, c, win=0.55):
    lines = []
    for n in chart:
        t = n["t_ms"] / 1000.0
        if n["kind"] == "long":
            e = n["end_ms"] / 1000.0
            if e > c - win and t < c + win:
                tag = "head" if abs(t - c) < win else ("tail" if abs(e - c) < win else "span")
                lines.append(f"long {t:7.3f}->{e:7.3f} lane {n['lane']:4.1f} x {n['x']:4d} "
                             f"size {n['size']} ({tag})")
        elif abs(t - c) < win:
            lines.append(f"{n['kind']:5s} {t:7.3f} lane {n['lane']:4.1f} x {n['x']:4d} "
                         f"size {n['size']}")
    return lines


def actions_near(chart, c, skip=0, win=0.6):
    """Re-fire the schedule offline: what the harness itself did around chart time `c`.

    The run folds offset -55 into t0, so every action fires at its own ms + 55 in chart time.
    `skip` must match the run's "skipping the first N notes", because the slot picker carries
    state forward and a schedule rebuilt from the full chart parks its fingers on other slots.
    """
    from player import JUDGE_Y, build_actions

    acts, _ = build_actions(chart[skip:], JUDGE_Y, 20.0, 45.0, 90)
    out = []
    for tm, op, slot, x, y in acts:
        fc = (tm + 55.0) / 1000.0
        if abs(fc - c) < win:
            out.append(f"act {op:4s} slot {slot} x {x:4d} fires at {fc:7.3f}s")
    return out


if __name__ == "__main__":
    main()
