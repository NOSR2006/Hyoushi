"""Read the OurNotes result page by pixel templates -- no OCR library.

The result page is the only acceptance instrument in this project, and it is
always on screen in the same 1280x720 layout, in the same few fonts. So the
reader does not OCR: it isolates the near-white glyphs inside fixed cell
windows, normalizes each glyph to a 24x28 bitmap and matches it against
templates cut from runs whose numbers are already known
(tools/build_templates.py writes research/digit_templates.json).

Two views of the same page exist and the reader auto-detects which one it is
looking at: the split view (FAST and SLOW columns, set by the toggling icon
the runs tap) and the plain totals view (one number per row). The split view
does not count hold ticks on its PERFECT line, so the totals view is the one
to trust for the perfect count; every other row agrees between the two, and
the acceptance metric (non-PERFECT = 0) is identical either way.
"""
import json
import os
import sys
from itertools import combinations

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rlog import RESEARCH  # noqa: E402

W, H = 1280, 720
ROWS = [("p", 376, 407), ("g", 415, 443), ("gd", 453, 481), ("b", 492, 520), ("m", 521, 559)]
ROWNAMES = [r[0] for r in ROWS]
FCOL = (850, 952)          # FAST column of the split view (also the unsplit number's x-range end)
SCOL = (956, 1043)         # SLOW column of the split view; must end before COMBO starts at 1044
SCORE = (950, 1250, 168, 232)
COMBO = (1150, 1246, 520, 558)
AP_BOX = (1045, 1250, 468, 525)
NR_BOX = (588, 700, 158, 232)

GLYPH_H, CANVAS_W = 28, 24
MIN_H, MAX_H, MAX_W = 16, 64, 26
MAX_W_SCORE = 44           # the score font is ~2.3x the judgement font
GLYPH_GAP = 0              # no merging: real digit gaps can be a single column
MIN_DIGIT_W = 6            # narrowest piece a wide-run split may cut; judge '1' is the floor
TEMPLATES = os.path.join(RESEARCH, "digit_templates.json")
CONFUSION_MAX = 95

_TPLCACHE = {}


def white_mask(im):
    r, g, b = im[..., 0], im[..., 1], im[..., 2]
    mn = np.minimum(np.minimum(r, g), b)
    mx = np.maximum(np.maximum(r, g), b)
    return (mn > 205) & ((mx - mn) < 30)


def _wide_run_pieces(mask, y0, y1, x0, s, e, cols, max_w, templates, family):
    """Cut one ink run wider than max_w into digit-sized pieces, relative to x0.

    Touching digits are real: on g022's 结算 frame (2026-09-29) 874's 7 and 4 merge
    into a single 27 px run, and the width filter used to drop the run whole, so
    PERFECT read as "8". The cuts go at ink-profile valleys, cheapest arrangement first,
    and every candidate is checked against the templates, so a cut through the middle of
    a glyph cannot win over the true digit boundary.
    """
    w = e - s
    kmin = max(2, -(-w // max_w))                 # fewest pieces that can fit under max_w
    ktop = min(w // MIN_DIGIT_W, kmin + 2)
    cands = [c for c in range(s + MIN_DIGIT_W, e - MIN_DIGIT_W + 1)
             if cols[c] <= cols[c - 1] and cols[c] <= cols[c + 1]]
    cands.sort(key=lambda c: cols[c - 1] + cols[c])
    arrs = []
    for k in range(kmin, ktop + 1):
        for cut in combinations(cands, k - 1):
            bounds = (s,) + cut + (e,)
            if all(MIN_DIGIT_W <= b - a <= max_w for a, b in zip(bounds, bounds[1:])):
                arrs.append(cut)
    if not arrs:                                  # no valley at all: the run is fused solid
        k = kmin
        arrs = [tuple(int(s + round(w * i / k)) for i in range(1, k))]
    arrs.sort(key=lambda cut: sum(cols[c - 1] + cols[c] for c in cut))

    def pieces_of(cut):
        bounds = (s,) + cut + (e,)
        out = []
        for a, b in zip(bounds, bounds[1:]):
            rows = np.nonzero(mask[y0:y1, a + x0:b + x0].sum(axis=1))[0]
            if not len(rows):
                return None
            ytop, ybot = int(rows[0]), int(rows[-1])
            if not MIN_H <= ybot - ytop + 1 <= MAX_H:
                return None
            out.append((a, b, ytop, ybot))
        return out

    for cut in arrs[:5]:
        pieces = pieces_of(cut)
        if pieces is None:
            continue
        if templates is not None:
            dists = [classify(glyph_bits(mask, (a + x0, b + x0, ytop + y0, ybot + y0)),
                              templates[family])[1] for a, b, ytop, ybot in pieces]
            if any(d > CONFUSION_MAX for d in dists):
                continue
        return pieces
    # Nothing verified: hand the cheapest cut back and let read_cell mark bad pieces '?'.
    return pieces_of(arrs[0]) or []


def _glyph_boxes(mask, y0, y1, x0, x1, max_w=MAX_W, templates=None, family="judge",
                 min_h=MIN_H, max_h=MAX_H):
    """Ink runs inside the cell, cut to digit boxes.

    `min_h` / `max_h` are parameters because the same template family reads two different sizes in
    this game: the result page's judgement digits are ~31 px tall, the in-song HUD counters are
    ~14. The classifier normalizes each glyph onto the 24x28 canvas before matching, so the only
    thing the height bounds are doing is rejecting noise and descenders -- which is why the HUD can
    ask for a lower floor rather than need a second reader.
    """
    sub = mask[y0:y1, x0:x1]
    cols = sub.sum(axis=0)
    runs = []
    inb = False
    for i, v in enumerate(cols):
        if v and not inb:
            inb, s = True, i
        elif not v and inb:
            inb, e = False, i
            runs.append([s, e])
    if inb:
        runs.append([s, len(cols)])
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] <= GLYPH_GAP:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    boxes = []
    for s, e in merged:
        if e - s > max_w and templates is not None:
            for a, b, ytop, ybot in _wide_run_pieces(mask, y0, y1, x0, s, e, cols, max_w,
                                                     templates, family):
                boxes.append((a + x0, b + x0, ytop + y0, ybot + y0))
            continue
        rows = np.nonzero(sub[:, s:e].sum(axis=1))[0]
        if not len(rows):
            continue
        ytop, ybot = int(rows[0]), int(rows[-1])
        h, w = ybot - ytop + 1, e - s
        if min_h <= h <= max_h and w <= max_w:
            boxes.append((s + x0, e + x0, ytop + y0, ybot + y0))
    return boxes


def glyph_bits(mask, box):
    x0, x1, y0, y1 = box
    g = (mask[y0:y1 + 1, x0:x1].astype(np.uint8)) * 255
    img = Image.fromarray(g)
    w, h = img.size
    nw = max(2, round(w * GLYPH_H / h))
    a = np.asarray(img.resize((nw, GLYPH_H), Image.BILINEAR)) > 127
    canvas = np.zeros((GLYPH_H, CANVAS_W), bool)
    if nw <= CANVAS_W:
        xo = (CANVAS_W - nw) // 2
        canvas[:, xo:xo + nw] = a
    else:
        canvas = a[:, :CANVAS_W]
    return canvas


def _hex(canvas):
    return np.packbits(canvas).tobytes().hex()


def _unhex(s):
    return np.unpackbits(np.frombuffer(bytes.fromhex(s), np.uint8)).astype(bool).reshape(GLYPH_H, CANVAS_W)


def load_templates(path=TEMPLATES):
    if path not in _TPLCACHE:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        _TPLCACHE[path] = {fam: {d: [_unhex(h) for h in hs] for d, hs in digits.items()}
                           for fam, digits in raw["families"].items()}
    return _TPLCACHE[path]


def _dist(a, b):
    """Hamming distance with +-1 px slack: a glyph cut one column over is the same glyph."""
    best = 1 << 30
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            d = int((a ^ np.roll(np.roll(b, dy, axis=0), dx, axis=1)).sum())
            if d < best:
                best = d
    return best


def classify(canvas, samples):
    best, bestd, second = None, 1e9, 1e9
    for d, hs in samples.items():
        dist = min(_dist(canvas, s) for s in hs)
        if dist < bestd:
            best, second, bestd = d, bestd, dist
        elif dist < second:
            second = dist
    return best, bestd, second


def read_cell(mask, y0, y1, x0, x1, templates, family="judge", max_w=MAX_W,
              min_h=MIN_H, max_h=MAX_H):
    boxes = _glyph_boxes(mask, y0, y1, x0, x1, max_w, templates=templates, family=family,
                         min_h=min_h, max_h=max_h)
    if not boxes:
        return "", []
    out, det = [], []
    for b in boxes:
        d, dist, second = classify(glyph_bits(mask, b), templates[family])
        if dist > CONFUSION_MAX:
            out.append("?")
        else:
            out.append(d)
        det.append({"box": b, "d": d, "dist": dist, "margin": second - dist})
    return "".join(out), det


def _num(s):
    if s == "":
        return None
    if "?" in s:
        return None
    return int(s)


def _sum_duo(cell):
    f, s = cell
    if f is None or s is None:
        return None
    return f + s


def read_image(path, templates=None):
    return read_array(np.asarray(Image.open(path).convert("RGB")), path, templates)


def read_array(im, path=None, templates=None):
    """Read one result-page frame the caller already holds -- no file involved.

    `path` is a label for the record only (run.py reads the totals capture off the frame it just
    saved and the FAST/SLOW split straight out of the grab, so a debug read never writes a PNG).
    """
    templates = templates or load_templates()
    im = np.asarray(im).astype(np.int16)
    if im.shape[:2] != (H, W):
        raise ValueError(f"{path or '<frame>'}: expected {W}x{H}, got {im.shape[1]}x{im.shape[0]}")
    mask = white_mask(im)
    cells, det = {}, {}
    for name, y0, y1 in ROWS:
        for side, (x0, x1) in (("f", FCOL), ("s", SCOL)):
            cells[f"{name}_{side}"], det[f"{name}_{side}"] = read_cell(
                mask, y0, y1, x0, x1, templates)
    cells["combo"], det["combo"] = read_cell(mask, *COMBO[2:], *COMBO[:2], templates)
    cells["score"], det["score"] = read_cell(mask, *SCORE[2:], *SCORE[:2], templates,
                                             family="score", max_w=MAX_W_SCORE)

    split = all(cells[f"{n}_f"] for n, _, _ in ROWS)
    rows = {}
    for name, _, _ in ROWS:
        f, s = _num(cells[f"{name}_f"]), _num(cells[f"{name}_s"])
        rows[name] = (f, s)

    counts = {}
    if split:
        for name in ROWNAMES:
            counts[name] = rows[name]
        non_perfect = _sum_duo(rows["g"]) if None not in (rows["g"][0], rows["g"][1]) else None
        for k in ("gd", "b", "m"):
            v = _sum_duo(rows[k])
            non_perfect = None if (non_perfect is None or v is None) else non_perfect + v
    else:
        for name in ROWNAMES:
            counts[name] = rows[name][1] if rows[name][1] is not None else rows[name][0]
        vals = [counts[k] for k in ("g", "gd", "b", "m")]
        non_perfect = None if None in vals else sum(vals)

    cyan = pink = nr_pink = 0
    y0, y1, x0, x1 = AP_BOX[2], AP_BOX[3], AP_BOX[0], AP_BOX[1]
    box = im[y0:y1, x0:x1]
    r, g, b = box[..., 0], box[..., 1], box[..., 2]
    cyan = int(((b > 170) & (g > 170) & (r < 150)).sum())
    pink = int(((r > 170) & (b > 150) & (g < 150)).sum())
    box = im[NR_BOX[2]:NR_BOX[3], NR_BOX[0]:NR_BOX[1]]
    r, g, b = box[..., 0], box[..., 1], box[..., 2]
    nr_pink = int(((r > 170) & (b > 140) & (g < 160)).sum())

    rec = {
        "file": path, "view": "split" if split else "totals",
        "score": _num(cells["score"]), "combo": _num(cells["combo"]),
        "perfect": _sum_duo(rows["p"]) if split else _num(cells["p_s"]),
        "great": counts.get("g"), "good": counts.get("gd"),
        "bad": counts.get("b"), "miss": counts.get("m"),
        "non_perfect": non_perfect,
        "all_perfect": cyan > 30,
        # ALL PERFECT contains full combo and the badge box draws only one of the two, so the
        # pink-only test reported full_combo False on every AP run (s02: combo 1162 of 1162,
        # miss 0, flagged not full-combo).
        "full_combo": (cyan > 30 or pink > 200),
        "new_record": nr_pink > 500,
        "cells": cells,
    }
    if split:
        rec["split_note"] = "split view: PERFECT line excludes hold ticks"
        # The raw FAST/SLOW pairs of the split page, verbatim: run.py's chain calibration reads
        # the histogram's lean as the run's mean judgement delta (-50 ms = all FAST, 0 = all SLOW).
        rec["rows"] = rows
    with_unk = [k for k, v in cells.items() if "?" in v]
    if with_unk:
        rec["warn"] = f"unreadable glyph in {','.join(with_unk)}"
    rec["_det"] = det
    return rec


def read_pair(result_png, split_png=None, templates=None):
    """Read both captures of one run off the disk (CLI / offline inspection)."""
    templates = templates or load_templates()

    def one(p):
        if not p:
            return None
        try:
            return read_image(p, templates)
        except Exception as e:                                    # noqa: BLE001
            return {"file": p, "error": str(e)}

    return merge(one(result_png), one(split_png))


def merge(totals, split=None):
    """Merge the two views of one run. The totals view wins the counts; split view
    only fills gaps."""
    recs = [r for r in (totals, split) if r]
    good = [r for r in recs if "error" not in r]
    if not good:
        return {"error": "no readable capture", "files": recs}
    totals = next((r for r in good if r["view"] == "totals"), None)
    split = next((r for r in good if r["view"] == "split"), None)
    main = totals or split
    out = {k: main[k] for k in ("score", "combo", "perfect", "great", "good", "bad", "miss",
                                "non_perfect", "all_perfect", "full_combo", "new_record")}
    out["views"] = [r["view"] for r in good]
    # `warn` has to survive the merge. `read_image` sets it per glyph (`unreadable glyph in ...`),
    # and the old whitelist above dropped it -- only the two views-disagree branches below could
    # ever set it. A round whose digits were misread then landed in results_full.jsonl looking
    # exactly like a clean one, which is the one thing a warning must not do.
    if main.get("warn"):
        out["warn"] = main["warn"]
    if split and split.get("warn") and split.get("warn") != out.get("warn"):
        out["warn"] = ((out["warn"] + "; ") if out.get("warn") else "") + split["warn"]
    # ... and a read that produced *no* number at all is not a result. Every judged-object count
    # None means the crop was of a blank or unrecognisable page: `flown_records` skips such a row
    # (so a flown round silently vanishes from the pin/audit history) and `update_chain_cal`'s
    # flooded-run guard reads `non_perfect or 0`, i.e. 0, letting a round nobody could read steer
    # the chain calibration. Measured over results_full.jsonl: 31 rows have every count None, and
    # 30 of them carry rc=1 already -- g206 is the lone rc=0 one, i.e. the one that was filed as a
    # successful round with no judgement data at all. This check is what moves it to the other 30.
    if all(out.get(k) is None for k in ("perfect", "great", "good", "bad", "miss", "score")):
        out["error"] = "no numbers on the page (blank or unrecognised result view)"
        # ... and a page with no numbers carries no badges either. The three flags above are colour
        # tests on the badge boxes (`cyan > 30` is ALL PERFECT) and the 多人 rank page is cyan enough
        # to light them all up: mp7's 13:19:19 frame was that rank page fading in, read as 结算, and
        # the row filed for it said all_perfect/full_combo/new_record true with every count None
        # (2026-10-08). A round nobody could read must not be recorded as a perfect one.
        for k in ("all_perfect", "full_combo", "new_record"):
            out[k] = False
    if split and split.get("rows"):
        out["split"] = split["rows"]
    if totals and split and totals["non_perfect"] != split["non_perfect"]:
        out["non_perfect"] = max(v for v in (totals["non_perfect"], split["non_perfect"])
                                 if v is not None)
        out["warn"] = (f"views disagree: totals {totals['non_perfect']} "
                       f"vs split {split['non_perfect']} -- kept the worse")
    elif split and not totals:
        out["warn"] = "split view only: hold-tick faults would not show here"
        if split.get("warn"):
            out["warn"] += f"; {split['warn']}"
    if totals and split and split.get("rows"):
        # Hold ticks are counted on the totals PERFECT line and never in the split, so
        # totals PERFECT can only be larger. Smaller means a read dropped digits -- the
        # exact shape of g022's "874 -> 8", which without this check would have been
        # filed as a clean ALL PERFECT.
        sp = split["rows"].get("p")
        if totals.get("perfect") is not None and sp and None not in sp:
            if totals["perfect"] < sp[0] + sp[1]:
                out["warn"] = ((out["warn"] + "; ") if out.get("warn") else "") + (
                    f"totals PERFECT {totals['perfect']} < split FAST+SLOW "
                    f"{sp[0]}+{sp[1]} -- one of the two reads is wrong")
    return out


def _pair_for(path):
    import os
    d, b = os.path.split(path)
    for pre, other in (("result_", "split_"), ("split_", "result_")):
        if b.startswith(pre):
            cand = os.path.join(d, other + b[len(pre):])
            return cand if os.path.exists(cand) else None
    return None


def main():
    import argparse
    ap = argparse.ArgumentParser(description="read OurNotes result screenshots")
    ap.add_argument("png", nargs="+")
    ap.add_argument("--debug", action="store_true", help="per-glyph distances")
    args = ap.parse_args()
    for p in args.png:
        rec = read_pair(p, _pair_for(p))
        print(json.dumps(rec, ensure_ascii=False))
        if args.debug:
            for cell, d in read_image(p)["_det"].items():
                print("  ", cell, [(g["d"], g["dist"], g["margin"]) for g in d])
    return 0


if __name__ == "__main__":
    sys.exit(main())
