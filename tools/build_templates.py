"""Cut digit templates for resultread.py out of result screenshots whose numbers are known.

Every entry below was read off the image by eye. run:  python tools/build_templates.py
Writes research/digit_templates.json (per digit: all sample bitmaps, matched by min distance).
"""
import json
import sys

sys.path.insert(0, "tools")
import numpy as np                                                    # noqa: E402
import rlog                                                           # noqa: E402
from resultread import ROWS, FCOL, SCOL, SCORE, COMBO, _glyph_boxes, glyph_bits, white_mask, _hex, _dist  # noqa: E402
from PIL import Image                                                 # noqa: E402

Z5 = {f"{n}_{s}": "0" for n, _, _ in ROWS for s in "fs"}

LABELS = {
    "research/archive/runs/split_t20.png": {**Z5, "p_f": "58", "p_s": "1052", "g_f": "8", "g_s": "44",
                               "gd_s": "1", "b_f": "23", "b_s": "5", "m_s": "2",
                               "combo": "483", "score": "3423416"},
    "research/archive/runs/split_t22.png": {**Z5, "p_f": "1153", "p_s": "23", "combo": "1777", "score": "4139558"},
    "research/archive/runs/split_a43.png": {**Z5, "p_f": "682", "p_s": "11", "combo": "960", "score": "3725297"},
    "research/archive/runs/split_a44.png": {**Z5, "p_f": "471", "p_s": "16", "combo": "768", "score": "4276596"},
    "research/archive/runs/result_t20.png": {"p_s": "1694", "g_s": "52", "gd_s": "1", "b_s": "28", "m_s": "2",
                                "combo": "483", "score": "3423416"},
    "research/archive/runs/result_t22.png": {"p_s": "1777", "combo": "1777", "score": "4139558"},
    "research/archive/runs/result_t23.png": {"p_s": "1777", "combo": "1777", "score": "4163524"},
    "research/archive/runs/result_t18.png": {"score": "4109791"},
    "research/archive/runs/split_t18.png": {"score": "4109791"},
    "research/archive/runs/result_t19.png": {"score": "3426660"},
    "research/archive/runs/split_t19.png": {"score": "3426660"},
    "research/archive/runs/result_t21.png": {"score": "4137781"},
    "research/archive/runs/split_t21.png": {"score": "4137781"},
}


def cell_window(cell):
    if cell == "score":
        return SCORE[2], SCORE[3], SCORE[0], SCORE[1], 44
    if cell == "combo":
        return COMBO[2], COMBO[3], COMBO[0], COMBO[1], 26
    name, side = cell.rsplit("_", 1)
    row = next(r for r in ROWS if r[0] == name)
    x0, x1 = FCOL if side == "f" else SCOL
    return row[1], row[2], x0, x1, 26


def main():
    families = {"judge": {}, "score": {}}
    # Both counters matter to the exit code. A `!!` line here is not cosmetic: it means the glyphs
    # found in the screenshot do not match the label read off it by eye, or a digit ended up with no
    # sample at all -- and the very next thing this file does is *overwrite* the template set that
    # every result-page read depends on. It used to print the `!!` and still `return 0`, so a
    # corrupted rebuild looked like a successful one to any caller that checks the status.
    problems = []
    for path, label_map in LABELS.items():
        im = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
        mask = white_mask(im)
        n_before = sum(len(v) for fam in families.values() for v in fam.values())
        for cell, want in label_map.items():
            y0, y1, x0, x1, mw = cell_window(cell)
            boxes = _glyph_boxes(mask, y0, y1, x0, x1, mw)
            if len(boxes) != len(want):
                print(f"!! {path} {cell}: {len(boxes)} glyphs found, label {want!r} has {len(want)}")
                problems.append(f"{path} {cell}: {len(boxes)} glyphs vs label {want!r}")
                continue
            fam = "score" if cell == "score" else "judge"
            for box, d in zip(boxes, want):
                families[fam].setdefault(d, []).append(_hex(glyph_bits(mask, box)))
        n_after = sum(len(v) for fam in families.values() for v in fam.values())
        print(f"[ok] {path}: +{n_after - n_before} samples")

    for fam, samples in families.items():
        counts = {d: len(v) for d, v in sorted(samples.items())}
        print(f"{fam}: samples per digit: {counts}")
        missing = [str(d) for d in range(10) if str(d) not in samples]
        if missing:
            print(f"!! {fam}: digits with no sample: {missing}")
            problems.append(f"{fam}: digits with no sample {missing}")

    out = {"families": {fam: {d: v for d, v in sorted(s.items())} for fam, s in families.items()},
           "meta": {"source": "known runs, cut by tools/build_templates.py",
                    "counts": {fam: {d: len(v) for d, v in s.items()} for fam, s in families.items()},
                    "glyph": [28, 24]}}
    # atomic, and in the file's own formatting: `resultread.load_templates` reads this on the first
    # read of every round, and a truncated template set is not a loud failure -- it silently
    # misreads digits. The separators are `json.dump`'s defaults and there is no trailing newline,
    # so rebuilding from unchanged inputs reproduces the committed file byte for byte (verified
    # with Get-FileHash; `rlog.write_json` would have added a newline and churned the file).
    rlog.atomic_write("research/digit_templates.json", json.dumps(out, ensure_ascii=False))
    print("wrote research/digit_templates.json")

    def bits(h):
        return np.unpackbits(np.frombuffer(bytes.fromhex(h), np.uint8)).astype(bool).reshape(28, 24)

    for fam, samples in families.items():
        worst_margin, worst_case = 999, None
        for d, hs in samples.items():
            for i, h in enumerate(hs):
                own = np.array([_dist(bits(h), bits(o)) for j, o in enumerate(hs) if j != i] or [0])
                wrong = min((min(_dist(bits(h), bits(o)) for o in ohs)
                             for od, ohs in samples.items() if od != d), default=999)
                margin = int(wrong - own.min())
                if margin < worst_margin:
                    worst_margin, worst_case = margin, (d, i, int(own.min()), wrong)
        print(f"{fam}: leave-one-out worst margin {worst_margin} {worst_case}"
              f"  (<0 means a sample would be misread)")
    if problems:
        print(f"!! {len(problems)} problem(s): " + "; ".join(problems[:5]))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
