"""Download every OurNotes chart from the Haneoka archive and compile it to a hit list.

The catalog is one gzip JSON keyed by musicId; each song carries its difficulties, whose
`file` is a plain-JSON chart (the site unpacks the game's .bytes). Incremental: charts whose
hits file already exists are skipped unless --force. Outputs under research/charts/:
  <book>_<dd>.raw.json    raw chart as downloaded (kept so a recompile needs no network)
  <book>_<dd>.hits.json   compiled hit list for the player
  manifest.json           catalog + local file map, read by the GUI
  validated.json          the pin list below

--force is the panel's 强制重下. Every geometry rule added since a chart was flown lands the moment
that chart is rebuilt, so a blanket --force would replace the bytes our ALL PERFECTs were actually
played on with bytes nobody has played. It no longer gets refused -- that veto was the answer this
tree had when there was nothing to go back to. --force recompiles everything and compares against the
bytes it *found*: a pinned chart whose geometry moved gets those bytes put back (held in memory, so
nothing is re-derived from a record), and the compiler's new ones wait in the relearn queue as a
question a live round answers, not a call this file gets to make. `--pin` is what makes the same
promise outlive this disk: it archives a compressed copy of the flown bytes in the committed evidence
tree, next to the regression frames.

  --pin                        write validated.json -- every chart with a graded round, its best
                               result, and what that round was fired on (its compiled bytes, its raw
                               chart, the compiler, the upstream revision; the last three measured by
                               run.py while the result page was still up) -- and refresh evidence/pins
  --recompile 0050_03 --force  keep the NEW bytes for this chart, because you are about to fly it
  --relearn                    what is still waiting: chart, pinned bytes, candidate bytes, and the
                               two commands that settle it
  --rebuild-raw <cid>[,<cid>...]
                               no network at all: recompile the named charts from the .raw.json
                               already on disk. For an unflown chart the stored hits are whatever
                               compiler version wrote them, so flying it tests old geometry; this
                               brings it up to this tree without downloading anything. A pinned
                               chart is refused -- there is no candidate question to ask about it,
                               its bytes are what a result was played on.
"""
import gzip
import json
import os
import sys
import time
import urllib.request
import zlib
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compile import compile_chart  # noqa: E402
from pypinyin import Style, pinyin  # noqa: E402
# RESULTS is deliberately re-exported: chartpin.py retargets fc.RESULTS (with VALIDATED and
# HISTORY_FULL) at a temp library, so removing it as "unused" breaks the pin regression.
from rlog import (CHARTS, MANIFEST, PIN_SCHEMA, PINS, PINS_INDEX, RELEARN,  # noqa: E402
                  HISTORY_FULL, RELEARN_INDEX, RESULTS, VALIDATED, flown_records, pin_state,
                  read_json, read_pins as read_pins_at, sha16, sha16_bytes, write_json,
                  atomic_write, write_json_file)

# The pin's summary lines are Chinese, and a console on the GBK codepage kills them mid-print
# (same guard as audit_charts.py / run.py).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

BASE = "https://haneoka.org"
CATALOG = f"{BASE}/api/v1/servers/intl/songs"
BANDS = f"{BASE}/api/v1/servers/intl/bands"
# Two spellings of the same directory, on purpose. manifest.json is tracked and records its chart
# files relative to the repo root (research/charts/xxx.hits.json), which the panel re-joins onto
# its own root; CHARTS above is anchored to this file and is what every open() here uses. Typing
# this command from another directory must not change which pin --force reads.
OUT_DIR = "research/charts"
UA = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"}


def chart_file(name):
    return os.path.join(CHARTS, name)


def pinyin_fields(title):
    """Search aids for a Chinese keyboard: full pinyin, joined, initials, and one variant per
    multi-reading character. Titles are Japanese, but a Chinese player reads the kanji the
    Chinese way on purpose -- 春日影 must answer to "chunriying", 六兆年 to "liuzhaonian".

    Kana are dropped from every search form. pypinyin passes them through untouched, and keeping
    them puts a gap inside the joined form -- 愛は衝動 came out "aiはchongdong", so a search for
    "aichongdong" found nothing. Latin tiles ("MyGO") survive: they are ASCII."""
    parts = []
    for rs in pinyin(title, style=Style.NORMAL, heteronym=True):
        opts = [r for r in rs if r and r.isascii()]
        if opts:
            parts.append(opts)
    main = [p[0] for p in parts]
    variants = set()
    for i, opts in enumerate(parts):
        for alt in opts[1:]:
            variants.add("".join(main[:i] + [alt] + main[i + 1:]))
    return {
        "py": " ".join(main),
        "pyJoin": "".join(main),
        "pyInitials": "".join(s[0] for s in main),
        "pyAlt": sorted(variants)[:8],
    }


def get(url, timeout=30, tries=3):
    """Fetch a URL, retrying only the failures that are worth retrying.

    A single TLS handshake timeout used to cost a chart. On 2026-10-04 過去を喰らう hard came back
    `<urlopen error _ssl.c:1015: The handshake operation timed out>` while the expert difficulty of
    the same song downloaded fine a second later, and the sweep moved on: the manifest still listed
    both difficulties, so the library looked complete, and the only way back was a second 联网更新
    the user had no reason to run. Retrying costs one request when nothing is wrong.

    An HTTP error is *not* retried: a 404 means the archive does not have those bytes, and asking
    three times does not change the answer.
    """
    last = None
    for k in range(max(1, tries)):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            if raw[:2] == b"\x1f\x8b" or r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw
        except urllib.error.HTTPError:
            raise                                   # the archive answered -- retrying is noise
        except Exception as e:                      # noqa: BLE001  timeout / reset / DNS / TLS
            last = e
            if k + 1 < tries:
                time.sleep(1.5 * (k + 1))
    raise last


def loc(x, i=0):
    """Some catalog fields are per-locale arrays; take the first non-null entry."""
    if isinstance(x, list):
        for v in x[i:]:
            if v:
                return v
        return ""
    return x or ""


def loc_exact(x, i):
    """Strict per-locale pick: "" instead of falling through to another locale."""
    if isinstance(x, list):
        return x[i] if 0 <= i < len(x) and x[i] else ""
    return (x or "") if i == 0 else ""


def hits_sha(cid):
    return sha16(chart_file(f"{cid}.hits.json"))


def read_pins():
    """The pin list in rlog's current shape, read from *this module's* VALIDATED.

    The delegation is so a caller that retargets the path -- the regression probe points it at a temp
    library -- still reads what it aimed at, rather than the real tree through rlog's own constant.
    """
    return read_pins_at(VALIDATED)


def writable(cid, pins, named):
    """May the sweep keep the bytes it just compiled for this chart?

    It may rewrite anything -- that half of the old rule is gone. What it may not do is *ship* a
    pinned chart's new geometry as if somebody had played it, so a changed chart gets its flown
    bytes put back and the candidate parked in the relearn queue. Naming a chart on the command
    line is how a human says they are about to fly it, and then the new bytes stay.
    """
    return cid not in pins or cid in named


def _pin_path(cid):
    return os.path.join(PINS, f"{cid}.hits.zz")


def _index(path, key):
    return (read_json(path) or {}).get(key) or {}


def list_queue():
    """--relearn: what the compiler wants to change that nobody has played yet, and how to answer it.

    The queue is the part of the pin that replaced the veto. A pinned chart whose bytes moved is not
    forbidden and not silently rebuilt -- it is an open question with both answers kept, and this is
    the command that says what is still open.
    """
    q = _index(RELEARN_INDEX, "queue")
    pins = read_pins()
    if not q:
        print(f"重学队列是空的：{RELEARN_INDEX}")
        return
    for cid, e in sorted(q.items()):
        b = (pins.get(cid) or {}).get("best") or {}
        print(f"  {cid}: 钉在 {e.get('flown')}（np={b.get('np')} @{b.get('tag')}），"
              f"候选 {e.get('candidate')}，登记于 {e.get('at')}")
        print(f"      候选文件 {os.path.join(RELEARN, f'{cid}.hits.json')}")
    print(f"共 {len(q)} 张。要试候选字节：run.py --hits 指到候选文件跑一局有界测试，"
          f"再 fetch_charts.py --pin —— 成绩更好钉子就挪到候选上，更差就留在原来那份。")


def snapshot_write(pins):
    """Keep a committed, compressed copy of the bytes each pinned result was flown on.

    research/charts/ is gitignored, so until now the flown geometry existed on exactly one disk and
    0050_03 showed what that costs: a rebuild replaced its bytes, nothing could bring them back, and
    the recorded result became a claim nobody can check. A snapshot is what lets --force answer
    "these changed, here is the old one back" instead of answering "no".

    Only bytes still on disk can be saved, and only when they are the ones the pin names -- an entry
    whose file has already been rewritten has nothing left to snapshot, and the audit's tripwire
    keeps saying so every run. Already-stored entries are left alone, so the committed tree grows
    when a chart's flown bytes really change and not every time somebody types --pin.
    """
    idx = _index(PINS_INDEX, "pins")
    added = kept = lost = 0
    for cid, e in sorted(pins.items()):
        want, have = e["at"].get("hits"), hits_sha(cid)
        if not want or have != want:
            lost += 1
            continue
        if idx.get(cid, {}).get("hits") == want and os.path.exists(_pin_path(cid)):
            kept += 1
            continue
        raw = open(chart_file(f"{cid}.hits.json"), "rb").read()
        blob = zlib.compress(raw, 9)
        os.makedirs(PINS, exist_ok=True)
        atomic_write(_pin_path(cid), blob, binary=True)
        idx[cid] = {"hits": want, "bytes": len(raw), "zbytes": len(blob),
                    "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        added += 1
    if added:
        write_json(PINS_INDEX, {"updated": time.strftime("%Y-%m-%d %H:%M:%S"), "pins": idx})
    return added, kept, lost


def put_back(cid, blob, want):
    """Write `blob` back over the library's copy of a chart, verified against the sha it claims.

    The bytes the sweep is protecting are the ones it just overwrote, so they are held in memory and
    put back here -- never re-derived from the pin. That distinction matters: a chart flown on new
    bytes and not yet re-pinned would otherwise be rolled back under its own result, because the pin
    still names the older generation. `snapshot_write` is the same promise made durable for the next
    disk, not the mechanism of this one.

    Returns whether the library now holds those bytes.
    """
    if sha16_bytes(blob) != want:
        return False
    dst = chart_file(f"{cid}.hits.json")
    try:
        atomic_write(dst, blob, binary=True)
    except OSError as e:
        # Reported rather than raised: the caller's whole job is to say whether flown bytes were
        # replaced by unflown ones, and an OSError escaping here would be filed as a generic
        # per-chart FAILED line -- swallowing the one warning that names this data loss.
        print(f"  !! 放回 {cid} 的旧字节失败：{e!r}", flush=True)
        return False
    return sha16(dst) == want


def queue_candidate(cid, flown, candidate):
    """Park the bytes the compiler now produces, and why the sweep is not shipping them.

    The candidate is a question for a live round: the only answer that means anything is whether this
    chart can still be ALL PERFECT on it. Keeping it beside the library instead of in it is what
    makes the queue a relearn rather than a ban -- and it is why --force no longer needs to refuse,
    because nothing is thrown away on the way back to the flown geometry.

    Has to be called with the candidate still on disk: the restore that follows overwrites it.
    Returns whether the queue now holds those bytes.
    """
    src = chart_file(f"{cid}.hits.json")
    if not os.path.exists(src):
        return False
    blob = open(src, "rb").read()
    if sha16_bytes(blob) != candidate:
        return False                   # the file moved again mid-sweep: park nothing this time
    os.makedirs(RELEARN, exist_ok=True)
    q = _index(RELEARN_INDEX, "queue")
    dst = os.path.join(RELEARN, f"{cid}.hits.json")
    if sha16(dst) != candidate:
        tmp = f"{dst}.tmp"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, dst)
    q[cid] = {"flown": flown, "candidate": candidate, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "why": "编译器想要不同的字节，飞过的成绩不在上面"}
    write_json(RELEARN_INDEX, {"updated": time.strftime("%Y-%m-%d %H:%M:%S"), "queue": q})
    return sha16(dst) == candidate


def queue_prune(pins):
    """Drop queue entries the pin has already absorbed -- the candidate got flown, won, and is now
    what the pin names. Called from --pin, so a relearn leaves the queue the moment it has an answer
    either way: a better result moves the pin onto the candidate, and a worse one leaves the pin on
    the old bytes while --pin keeps rewriting the entry from the round's own fingerprint."""
    q = _index(RELEARN_INDEX, "queue")
    if not q:
        return 0
    won = [c for c, e in q.items()
           if (pins.get(c) or {}).get("at", {}).get("hits") == e.get("candidate")
           or hits_sha(c) == e.get("candidate")]
    for c in won:
        q.pop(c)
        if os.path.exists(os.path.join(RELEARN, f"{c}.hits.json")):
            os.remove(os.path.join(RELEARN, f"{c}.hits.json"))
    if won:
        write_json(RELEARN_INDEX, {"updated": time.strftime("%Y-%m-%d %H:%M:%S"), "queue": q})
    return len(won)



def pin_current():
    """Record, for every chart flown to a result page, its best result and the inputs that round
    was played on.

    The second half is why this file exists in its current shape. The v1 pin stored one sha and left
    a reader unable to tell "this result still predicts today's bytes" from "the game, the raw chart
    or the compiler has moved since, and nobody has flown this chart since" -- so the only action
    either state supported was refusing to recompile. With the round's own fingerprint (
    `fingerprint`, taken by run.py while the result page was still up) a pin becomes a dated
    measurement: `rlog.pin_state` says current / drifted / unrecorded, and drifted means "queue a
    relearn", not "hands off".

    Cumulative on purpose. results.jsonl keeps the newest 100 rounds (rlog.HISTORY_CAP), so a pin
    rebuilt from today's log alone would quietly drop the charts whose only record aged out --
    forgetting exactly the results the log no longer carries. A pinned entry is only ever lost by
    deleting this file.

    Nothing is inferred that could be read: a record carrying no `at` (flown before the round
    measured its own inputs) keeps the byte claim the earlier pin made and gets `asof: None`, which
    `pin_state` reads as "cannot tell". Minting today's fingerprint in its place would let the audit
    report "same generation as today" about bytes that result was never played on.
    """
    old = read_pins()
    best = flown_records(HISTORY_FULL)
    os.makedirs(CHARTS, exist_ok=True)
    out = dict(old)
    dated = silent = carried_worse = 0
    for cid, r in sorted(best.items()):
        # A pin never gets worse. The log keeps the newest 100 rounds, so a chart whose better
        # round rolled off it would otherwise be rebuilt from a worse one -- and that happened:
        # 0062_03 (唱) had ALL PERFECT ×3 recorded, and after its rows aged out the pin read
        # np=20 @s09; 0053_03 the same. The stored entry -- tag, count, and the fingerprint of
        # the bytes that round flew on -- is the only thing left that remembers, so a worse log
        # row may not overwrite it. (Better or equal still writes, which is how a relearn lands.)
        was = (old.get(cid) or {}).get("best") or {}
        was_np = was.get("np")
        if was_np is not None and (r["non_perfect"] is None or was_np < r["non_perfect"]):
            out[cid] = {"best": dict(was), "at": dict((old.get(cid) or {}).get("at") or {})}
            carried_worse += 1
            continue
        at = dict(r.get("at") or {})
        if at:
            at["asof"] = "flight"
            dated += 1
        else:
            # This round never measured its own inputs -- it predates the field. Keep whatever byte
            # claim the earlier pin made (so the audit's tripwire survives the rewrite), or fall back
            # on today's file for a chart nobody has pinned, leave the rest None, and let pin_state
            # call it what it is: unrecorded, not current.
            prior = old.get(cid, {}).get("at") or {}
            at = {"hits": prior.get("hits") or hits_sha(cid), "raw": prior.get("raw"),
                  "build": prior.get("build"), "rev": prior.get("rev"), "asof": None}
            silent += 1
        at["cfg"] = r.get("cfg") or (old.get(cid, {}).get("at") or {}).get("cfg")
        out[cid] = {"best": {"np": r["non_perfect"], "tag": r.get("tag", ""),
                             "score": r.get("score"), "ts": r.get("ts")}, "at": at}
    drifted = [c for c, v in out.items()
               if c in old and c in best and old[c]["at"].get("hits") != v["at"].get("hits")]
    carried = [c for c in out if c not in best]
    gone = [c for c, v in out.items() if v["at"].get("asof") == "flight"
            and hits_sha(c) != v["at"].get("hits")]
    write_json(VALIDATED, {"schema": PIN_SCHEMA, "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                           "charts": out})
    gens = Counter(pin_state(c, e) for c, e in out.items())
    print(f"pinned {len(out)} flown charts -> {VALIDATED}"
          + (f"（{len(carried)} 条来自更早的钉子，日志里已经裁掉）" if carried else "")
          + (f"；{carried_worse} 条日志里只剩更差的局，钉子按「不许变差」保住原成绩"
             if carried_worse else ""))
    print(f"  按输入分代：与今天的输入同代 {gens['current']} 张、输入已变 {gens['drifted']} 张、"
          f"记不出输入 {gens['unrecorded']} 张"
          + (f"（本局自带指纹 {dated} 张；{silent} 张那一局没测过自己的输入，只能说「说不清」）"
             if silent else ""))
    if drifted:
        print(f"  (!! 自上次钉以来这些谱的编译字节变了: {' '.join(drifted[:10])})")
    if gone:
        print(f"  (!! 这几张的飞行当时用的是别的字节，现在盘上已经不是那一份了: {' '.join(gone[:10])})")
    won = queue_prune(out)
    added, kept, nowrite = snapshot_write(out)
    print(f"  字节库 evidence/pins：{kept} 张已在库"
          + (f"、本次新存 {added} 张" if added else "")
          + (f"、{nowrite} 张存不了（飞过的字节已不在盘上）" if nowrite else "")
          + (f"；重学队列 {won} 张已有答案，出队" if won else ""))
    return out


def rebuild_from_raw(cids):
    """--rebuild-raw: bring named charts up to this tree's compiler, without the archive."""
    pins = read_pins()
    changed = 0
    for cid in cids:
        raw = chart_file(f"{cid}.raw.json")
        if cid in pins:
            b = pins[cid]["best"]
            print(f"  !! {cid} 在钉子里（np={b.get('np')} @{b.get('tag')}），不重编")
            continue
        if not os.path.exists(raw):
            print(f"  !! {cid} 没有 {raw}，这一步不联网，跳过")
            continue
        before = hits_sha(cid)
        hits = compile_chart(raw)
        json.dump(hits, open(chart_file(f"{cid}.hits.json"), "w", encoding="utf-8"),
                  ensure_ascii=False)
        after = hits_sha(cid)
        changed += before != after
        print(f"  {cid}: {len(hits)} 个动作 -> {cid}.hits.json "
              + ("字节已变" if before != after else "字节不变"))
    print(f"重编译 {len(cids)} 张，其中 {changed} 张字节变了")


def main():
    if "--pin" in sys.argv:
        pin_current()
        return
    if "--relearn" in sys.argv:
        list_queue()
        return
    if "--rebuild-raw" in sys.argv:
        rebuild_from_raw([c for c in
                          sys.argv[sys.argv.index("--rebuild-raw") + 1].split(",") if c])
        return
    force = "--force" in sys.argv
    recompile = {sys.argv[i + 1] for i, a in enumerate(sys.argv[:-1]) if a == "--recompile"}
    pins = read_pins()
    restored, accepted, lost = [], [], []
    os.makedirs(CHARTS, exist_ok=True)
    print("fetching catalog ...", flush=True)
    catalog = json.loads(get(CATALOG))
    songs = sorted(catalog.items(), key=lambda kv: kv[0])
    print(f"{len(songs)} songs in the intl catalog", flush=True)

    print("fetching band list ...", flush=True)
    try:
        bl = json.loads(get(BANDS))
        bands = [{"bandId": b["bandId"],
                  "name": loc_exact(b.get("bandName"), 3) or loc(b.get("bandName"))}
                 for b in bl.values()]
        bands.sort(key=lambda b: b["bandId"])
        print(f"{len(bands)} native bands: " + ", ".join(b["name"] for b in bands), flush=True)
    except Exception as e:  # noqa: BLE001 - the panel can still group by each song's bandId
        bands = []
        print(f"band list failed ({e}), continuing without it", flush=True)

    manifest = {"server": "intl", "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "bands": bands, "songs": []}
    done = failed = skipped = 0
    fail_ids = []
    for si, (music_id, s) in enumerate(songs, 1):
        entry = {
            "musicId": music_id,
            "title": loc(s.get("musicTitle")),
            "titleRomaji": loc(s.get("musicTitle"), 1),
            "band": loc(s.get("bandName")),
            "bandId": s.get("bandId"),
            "bandZh": loc_exact(s.get("bandName"), 3),
            "jacket": s.get("jacketThumbUrl") or s.get("jacketUrl") or "",
            "difficulties": [],
        }
        entry.update(pinyin_fields(entry["title"]))
        for diff in sorted(s.get("difficulty", []), key=lambda d: d.get("difficulty", 0)):
            rel = diff.get("file") or ""
            if not rel:
                continue
            book, dd = rel.rsplit("/", 1)[-1].removesuffix(".bytes").split("_")
            cid = f"{book}_{dd}"
            raw_path = chart_file(f"{cid}.raw.json")
            hits_path = chart_file(f"{cid}.hits.json")
            d = {
                "name": diff.get("difficultyName"),
                "level": diff.get("displayLevel"),
                # The archive publishes two levels: displayLevel is rounded down to an integer,
                # sortLevel keeps the half step the game's own list shows (唱 EXPERT is 23.5).
                # `level` stays what everything else reads, so this is display-only.
                "sortLevel": diff.get("sortLevel"),
                "noteCount": diff.get("noteCount"),
                "book": book,
                "dd": dd,
                "raw": f"{OUT_DIR}/{cid}.raw.json",
                "hits": f"{OUT_DIR}/{cid}.hits.json",
            }
            entry["difficulties"].append(d)
            if os.path.exists(hits_path) and not force:
                skipped += 1
                continue
            was = pins.get(cid)
            # Hold on to what is on disk for a pinned chart before compiling over it: the bytes this
            # sweep is not allowed to lose are exactly the ones it is about to overwrite.
            keep = (open(hits_path, "rb").read()
                    if was and force and os.path.exists(hits_path) else None)
            pre = sha16_bytes(keep) if keep else None
            try:
                fetched = False
                if not os.path.exists(raw_path) or force:
                    blob = get(BASE + rel)
                    json.loads(blob)
                    # Atomic, so a kill mid-write cannot leave a truncated raw. Nothing downstream
                    # validates one: `compile_chart` reads it, and the *raw's existence* is what
                    # stops the next sweep from downloading it again.
                    atomic_write(raw_path, blob, binary=True)
                    fetched = True
                    time.sleep(0.15)
                try:
                    hits = compile_chart(raw_path)
                except Exception:
                    # A 200 that is valid JSON but not a chart would otherwise be permanent: the
                    # raw is on disk, so line 493/the `os.path.exists(raw_path)` test above skip it
                    # forever and every later sweep replays the same failure. Drop what this sweep
                    # fetched and the next one re-downloads; a raw we did NOT fetch is left alone
                    # (it is the user's only copy of that chart).
                    if fetched:
                        try:
                            os.unlink(raw_path)
                        except OSError:
                            pass
                        print(f"  !! {cid} 下载到的 raw 不是谱面（{loc(s.get('musicTitle'))} "
                              f"{d['name']}），已删除，下次联网更新会重下", flush=True)
                    raise
                write_json_file(hits_path, hits)
                done += 1
                print(f"[{si}/{len(songs)}] {loc(s.get('musicTitle'))} {d['name']} "
                      f"Lv{d['level']} {len(hits)} notes", flush=True)
                after = hits_sha(cid)
                if was and pre and after != pre:
                    # The compiler moved a chart somebody has actually played. Whether that is an
                    # improvement is a question for a live round, not for this sweep, so the old
                    # bytes go back and the new ones wait in the queue.
                    b = was["best"]
                    if writable(cid, pins, recompile):
                        accepted.append((cid, b.get("np"), b.get("tag"), after))
                    elif queue_candidate(cid, pre, after) and put_back(cid, keep, pre):
                        restored.append((cid, b.get("np"), b.get("tag"), after))
                    else:
                        lost.append((cid, b.get("np"), b.get("tag"), after))
            except Exception as e:  # noqa: BLE001 - one bad chart must not kill the sweep
                failed += 1
                fail_ids.append(f"{cid}({d['name']})")
                print(f"[{si}/{len(songs)}] FAILED {loc(s.get('musicTitle'))} {d['name']}: {e}",
                      flush=True)
        manifest["songs"].append(entry)

    if restored:
        print(f"!! --force 重编了 {len(restored)} 张已飞过的谱，本树编译器想要的字节与盘上的不同："
              "盘上那一份已原样放回，新的一份进了重学队列 " + RELEARN_INDEX + "：" +
              " ".join(f"{c}/np{np_}@{t}" for c, np_, t, _ in restored[:12]) +
              (f" 等，共 {len(restored)}" if len(restored) > 12 else ""))
        print("   要试新字节就点名：--recompile <cid> --force，飞一次有界测试，成绩更好再 --pin 换钉子。")
    if accepted:
        print(f"!! {len(accepted)} 张点名重编的已飞过谱，现在盘上是没飞过的字节"
              "（下一局请针对它们跑有界测试，再 --pin 决定钉子要不要移动）: " +
              " ".join(f"{c}/np{np_}@{t}" for c, np_, t, _ in accepted[:12]))
    if lost:
        print(f"!! {len(lost)} 张既没存进重学队列、也没放回原处（磁盘写入没成功），"
              "现在盘上是没飞过的字节，得重飞一次才能定钉子：" +
              " ".join(f"{c}/np{np_}@{t}" for c, np_, t, _ in lost[:12]))
    if force and not pins:
        print(f"!! 没有 {VALIDATED}：--force 此刻重编的已飞过谱没有任何记录，也无从判断哪一份是"
              f"成绩的来源。先跑 python tools/fetch_charts.py --pin")

    write_json(MANIFEST, manifest)
    if fail_ids:
        # Named at the end as well as in the FAILED lines above: the panel streams this whole text
        # into its log, and "1 failed" somewhere in three hundred lines is how a chart stays missing
        # for a week. The exit code is 1 for the same reason -- the panel's phase reads it.
        print(f"!! {len(fail_ids)} 张没有下来：{' '.join(fail_ids[:12])}"
              + (" 等" if len(fail_ids) > 12 else "")
              + " —— 网络或上游的问题，重跑一次「联网更新」通常就好；这几张现在本地没有谱面，"
                "在游戏里选中它们会核对失败。", flush=True)
    print(f"done: {done} compiled, {skipped} cached, {failed} failed -> {MANIFEST}", flush=True)

    # The song-select recogniser matches against these jackets (tools/gameread.py), so the one
    # button that refreshes the library must refresh them too. Incremental: existing files are
    # kept, only the missing ones are fetched.
    try:
        import gameread
        gameread.ensure_library(download=True)
    except Exception as e:  # noqa: BLE001 - the panel still works without recognition
        print(f"jacket library failed: {e!r}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
