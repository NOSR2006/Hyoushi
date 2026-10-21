"""Backfill rounds that were flown but never written to research/results.jsonl.

Runs started from a shell before run.py began recording its own round (ce90e9b) left a
research/runs/<tag>.out with a RESULT line and nothing in the log. That is not only a gap in the panel's
history page: research/charts/validated.json, the pin that stops --force from replacing flown
geometry, is built from the log, so an unrecorded ALL PERFECT is an unprotected one.

The chart is recovered from the log itself, not from memory. Two numbers have to agree: the count
the compiler fed the player ("N notes -> M actions") and the total the game judged
(perfect+great+good+bad+miss). Matching on one alone is ambiguous -- 唱 EXPERT and Mela! HARD both
compile to 340 hits -- but no two charts in the library share the pair, so an identified run names
its chart exactly. Anything ambiguous or unmatched is reported and left out; a guessed chart id
would pin the wrong geometry.

Usage:
  python tools/backfill_log.py             # show what would be added
  python tools/backfill_log.py --write     # append it, chronologically, through the capped writer
"""
import glob
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rlog import (CHARTS, HISTORY_CAP, HISTORY_FULL, RESEARCH, RESULTS, RUNS,  # noqa: E402
                  read_records, write_records)

# runs/ holds the current <tag>.out files (research/ 根的那 2029 个 2026-10-20 搬进去了);
# RESEARCH 还留在表里是为了仍能从旧树/手拖回去的文件补档。archive/logs holds the pre-rlog era, where the
# t-series and a-series runs (including the best config, T03) never recorded a round either.
LOGS = [RUNS, RESEARCH, os.path.join(RESEARCH, "archive", "logs"),
        os.path.join(RESEARCH, "archive", "runs")]
GLOBS = ("*.out", "*.log")

RESULT_RE = re.compile(r"^RESULT (\{.*\})$", re.M)
NOTES_RE = re.compile(r"^(\d+) notes -> ", re.M)


def library():
    """(hits count, game noteCount) -> (cid, title, difficulty) for every compiled chart."""
    man = json.load(open(f"{CHARTS}/manifest.json", encoding="utf-8"))
    out = {}
    dupes = 0
    for s in man["songs"]:
        for d in s["difficulties"]:
            cid = f"{d['book']}_{d['dd']}"
            p = f"{CHARTS}/{cid}.hits.json"
            if not os.path.exists(p):
                continue
            key = (len(json.load(open(p, encoding="utf-8"))), d.get("noteCount"))
            if key in out:
                dupes += 1
                key = (key[0], None)          # refuse to guess between two charts
                if key in out:
                    continue
            out[key] = (cid, s["title"], d["name"].lower())
    return out, dupes


def judge_total(res):
    """The five judged counts summed, or None when the RESULT line is incomplete.

    An old line can carry explicit nulls (`"perfect": null`, and g206.out has all five), and
    `res.get(k, 0)` handed the None straight back -- the sum then blew up with "unsupported
    operand type(s) for +: 'int' and 'NoneType'" on the archive corpus. Zero-filling would be the
    wrong repair though: a null is *missing data*, not a zero, and a fabricated total can match the
    wrong chart. This module exists to stop exactly that ("a guessed chart id would pin the wrong
    geometry"), so an incomplete line is reported as unidentifiable instead of being summed.
    """
    counts = [res.get(k) for k in ("perfect", "great", "good", "bad", "miss")]
    if any(c is None for c in counts):
        return None
    return sum(counts)


def recorded_tags():
    return {r["tag"] for r in read_records(RESULTS)}


def rows_from_logs():
    lib, dupes = library()
    if dupes:
        print(f"  (note: {dupes} note-count collisions in the library, those runs stay unidentified)")
    have = recorded_tags()
    out, skipped, seen = [], [], set()
    for d in LOGS:
        for pat in GLOBS:
            for path in sorted(glob.glob(os.path.join(d, pat))):
                tag = os.path.splitext(os.path.basename(path))[0]
                if tag in have or tag in seen:
                    continue          # one round per tag; research/ wins over the archive copy
                seen.add(tag)
                txt = open(path, encoding="utf-8", errors="replace").read()
                m, results = NOTES_RE.search(txt), RESULT_RE.findall(txt)
                if not results:
                    continue                      # no result page read: a crashed or bounded run
                res = json.loads(results[-1])     # a retry loop ends on the round the game kept
                judged = judge_total(res)
                if judged is None:
                    skipped.append((tag, "RESULT line has null judged counts"))
                    continue
                hit = lib.get((int(m.group(1)) if m else -1, judged))
                if hit is None:
                    skipped.append((tag, f"notes={m.group(1) if m else '?'} "
                                         f"judged={judged} matches no chart"))
                    continue
                cid, title, diff = hit
                row = {"ts": time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(path))),
                       "tag": tag, "song": title, "diff": diff, "chart": cid, "rc": 0,
                       "score": res.get("score"), "combo": res.get("combo"),
                       "perfect": res.get("perfect"), "great": res.get("great"),
                       "good": res.get("good"), "bad": res.get("bad"), "miss": res.get("miss"),
                       "non_perfect": res.get("non_perfect"),
                       "all_perfect": res.get("all_perfect"),
                       "full_combo": res.get("full_combo"),
                       "new_record": res.get("new_record"),
                       "views": ["totals", "split"] if "FAST/SLOW split" in txt else ["totals"],
                       "restored": True}
                out.append(row)
    return sorted(out, key=lambda r: r["ts"]), skipped


def main():
    rows, skipped = rows_from_logs()
    ap = [r for r in rows if r["non_perfect"] == 0]
    print(f"=== 可回填的局：{len(rows)} 轮，其中 ALL PERFECT {len(ap)} 轮 ===")
    for r in rows:
        print(f"  {r['ts']} {r['tag']:<6} {r['song'][:18]:<18} {r['diff']:<7} {r['chart']:<9} "
              f"np={r['non_perfect']}")
    if skipped:
        print("\n认不出曲子的（保持不写入，宁可漏一条记录也不要钉错一张谱）：")
        for tag, why in skipped:
            print(f"  {tag:<6} {why}")
    if "--write" not in sys.argv:
        print("\n（预览模式，未写入。加 --write 落盘）")
        return
    merged = sorted(read_records(RESULTS) + rows, key=lambda r: r["ts"])
    bad = [i for i in range(1, len(merged)) if merged[i]["ts"] < merged[i - 1]["ts"]]
    assert not bad, f"timestamps not monotonic after merge: {bad[:3]}"
    if len(merged) > HISTORY_CAP:
        print(f"\n注意：合并后 {len(merged)} 轮 > 上限 {HISTORY_CAP}，"
              f"最旧的 {len(merged) - HISTORY_CAP} 轮会被裁掉")
    write_records(RESULTS, merged)
    have = {r.get("tag") for r in read_records(HISTORY_FULL)}
    write_records(HISTORY_FULL, read_records(HISTORY_FULL) +
                  [r for r in rows if r.get("tag") not in have], cap=10 ** 9)
    print(f"\n写入 {RESULTS}：{len(rows)} 轮回填，共 {min(len(merged), HISTORY_CAP)} 轮")


if __name__ == "__main__":
    main()
