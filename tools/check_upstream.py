"""Check whether the Haneoka archive has revised any chart since we fetched it.

The pin (research/charts/validated.json) protects the bytes an ALL PERFECT was flown on, and it
assumes those bytes still describe what the game shows. If upstream revises a chart, that assumption
rots silently: our hit list fires at times the notes no longer occupy, and the failure looks exactly
like a geometry bug -- a MISS storm at a fixed chart position, with punctual presses.

Two signals, at two costs.

  catalog (default, one request): the songs endpoint carries each difficulty's file path,
    noteCount and displayLevel. A revision almost always moves at least one of them, and the same
    diff also lists songs that appeared since we last fetched -- new coverage for random mode.

  raw (--verify, one request per chart named by the catalog diff, or --all for the whole library):
    download the chart JSON and compare it byte-for-byte with the stored .raw.json. This is the
    answer to "did the geometry move", because noteCount can survive an edit.

Nothing here writes into research/charts/ except --verify's own downloads, which land in
research/upstream/ so a validated hits file can never be touched by a check.

Usage:
  python tools/check_upstream.py                    # catalog diff, one cached request
  python tools/check_upstream.py --verify           # + the charts the catalog flags
  python tools/check_upstream.py --pinned           # + every chart the pin protects (implies --verify)
  python tools/check_upstream.py --verify --all     # every chart in the library
"""
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_charts import BASE, get, loc, read_pins  # noqa: E402
from rlog import CHARTS, RESEARCH, read_json, write_json  # noqa: E402
import sources  # noqa: E402

# --verify downloads into its own directory so a check cannot touch a pinned hits file.
STAGING = os.path.join(RESEARCH, "upstream")
# 比对报告是给人看的产物，和 chart_audit.* 一起住在 research/reports/（atomic_write 会建目录）。
REPORT = os.path.join(RESEARCH, "reports", "upstream_check.json")


def catalog_index(raw):
    """musicTitle/file-keyed view of the live catalog: cid -> (file, noteCount, level, title).

    Accepts the bytes of a catalog response or the dict sources.haneoka() already parsed.
    """
    cat = json.loads(raw) if isinstance(raw, (bytes, str)) else raw
    out = {}
    for s in cat.values():
        title = loc(s.get("musicTitle"))
        for d in s.get("difficulty", []):
            rel = d.get("file") or ""
            if not rel:
                continue
            book, dd = rel.rsplit("/", 1)[-1].removesuffix(".bytes").split("_")
            out[f"{book}_{dd}"] = {"file": rel, "noteCount": d.get("noteCount"),
                                   "level": d.get("displayLevel"), "title": title}
    return out


def local_index():
    man = read_json(f"{CHARTS}/manifest.json")
    if man is None:
        raise SystemExit(f"no {CHARTS}/manifest.json - run tools/fetch_charts.py first")
    out = {}
    for s in man["songs"]:
        for d in s["difficulties"]:
            cid = f"{d['book']}_{d['dd']}"
            out[cid] = {"noteCount": d.get("noteCount"), "level": d.get("level"),
                        "title": s.get("title")}
    return out


def moenotes_index(charts, local):
    """The same cid -> index view, built from MoeNotes' master tables when the archive is silent.

    Their tables carry TextIDs instead of names, so a known song keeps the title from our manifest
    and a genuinely new one is only its cid.

    The level used to be `int(sortLevel)`: when this was written the archive's displayLevel was an
    integer and MoeNotes' `_musicScoreDisplayLevel` kept the half step (26.5), so flooring was what
    made the two comparable. On 2026-10-03 the archive started publishing the half step as well --
    53 of 348 charts are x.5, and our own manifest has them -- so flooring the fallback now makes it
    the odd one out (20 against everyone else's 20.5) and the panel's update check would report 53
    phantom changes. Keep the number as published; `srcfail` PART 5 holds the equality down in both
    directions. What this view cannot give is a download path, which is why it never satisfies
    --verify: only Haneoka has compilable bytes.
    """
    def level(v):
        s = v.get("sortLevel")
        return s if isinstance(s, (int, float)) else v.get("level")

    return {cid: {"file": None, "title": (local.get(cid) or {}).get("title") or cid,
                  "noteCount": v.get("noteCount"), "level": level(v)}
            for cid, v in charts.items()}


def sha(b):
    return hashlib.sha256(b).hexdigest()[:16]


def main():
    args = sys.argv
    verify = "--verify" in args
    everything = "--all" in args
    pinned = "--pinned" in args
    preferred = next((a.split("=", 1)[1] for a in args if a.startswith("--source=")), "moenotes")
    # The panel's 目录首选源 decides who gets asked: MoeNotes publishes the game's own master tables
    # to GitHub and moved ~2 h before the archive did on 2026-09-30, so when their tables match our
    # manifest there is nothing the archive could report -- and the quiet answer costs haneoka.org
    # no request at all. --source=haneoka (or an explicit --verify/--all/--pinned) always asks it.
    p = None
    if not (verify or everything or pinned):
        p = sources.plan(preferred=preferred)
        for line in p["notes"]:
            print(line, flush=True)
        if not p["look"]:
            print("  未向 archive 请求：第二源说目录没动"
                  "（--verify / --all / --pinned 会强制问它）", flush=True)
            write_json(REPORT, {"new": [], "gone": [], "fields_changed": {},
                                "byte_moved": [], "byte_unchanged": [], "failed": [],
                                "asked_archive": False, "evidence": p["notes"],
                                "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")})
            print(f"\n写入 {REPORT}")
            return
    local = local_index()
    # The archive's own conditional request: a cached copy inside the day is reused without going
    # out at all, and past that the stored ETag is offered back first -- a 304 costs it a header.
    # The chart bytes below always go out fresh, so a stale catalog can only make this name one
    # chart fewer to check, never hide a move that a download would have found.
    # And if the archive does not answer at all, the second source still knows what the game's own
    # tables say: the directory comparison survives, only the byte-by-byte check below is refused.
    evidence, from_archive = [], True
    try:
        h = sources.haneoka()
        live = catalog_index(h["songs"])
        evidence.append(f"archive 目录 {h.get('release') or '?'}"
                        f"（{'复用 ' + h['reused'] if h.get('reused') else '新拉'}，{len(live)} 张）")
    except Exception as e:                                    # noqa: BLE001 - a mirror is a mirror
        from_archive = False
        print(f"!! archive 没答话（{type(e).__name__}: {e}），改用 MoeNotes 的 master 表比目录")
        try:
            mn = (p or {}).get("moenotes") or sources.moenotes()
        except Exception as e2:                               # noqa: BLE001
            raise SystemExit(f"两个目录源都没答话：archive: {e} / MoeNotes: {e2}")
        live = moenotes_index(mn["charts"], local)
        evidence.append(f"MoeNotes {mn['region']} {mn['resource'] or mn['version']}"
                        f"（archive 不可达时的降级目录，{len(live)} 张）")
    print(f"live catalog: {len(live)} charts | local manifest: {len(local)} charts")

    new = sorted(set(live) - set(local))
    gone = sorted(set(local) - set(live))
    changed = {}
    for cid in sorted(set(live) & set(local)):
        # The manifest never stores the archive path, only book/dd, so a path change is invisible
        # here -- and harmless, since a revision that renames the file also lands in new/gone.
        fields = [k for k in ("noteCount", "level")
                  if live[cid].get(k) != local[cid].get(k)]
        if fields:
            changed[cid] = {k: [local[cid].get(k), live[cid].get(k)] for k in fields}

    print(f"\n=== 曲目目录 ===\n  新增 {len(new)} 张 / 下架 {len(gone)} 张 / 字段变动 {len(changed)} 张")
    for cid in new[:40]:
        lv = live[cid]
        print(f"  + {cid} {lv['title'][:22]:<22} Lv{lv['level']} {lv['noteCount']} notes")
    if len(new) > 40:
        print(f"  ... 其余 {len(new) - 40} 张见 {REPORT}")
    for cid, f in list(changed.items())[:20]:
        print(f"  ~ {cid} {live[cid]['title'][:22]:<22} "
              + " ".join(f"{k}: {a}->{b}" for k, (a, b) in f.items()))
    for cid in gone[:20]:
        print(f"  - {cid} 目录里没有了")

    # --pinned adds the charts whose flown geometry this check is really protecting; naming them
    # without --verify would be a check that downloads nothing, so it implies the byte comparison.
    if pinned:
        verify = True
    suspect = set(live) if everything else set(changed) | set(new)
    if pinned:
        suspect |= set(read_pins()) & set(live)
    suspect = sorted(suspect)
    if verify and suspect and not from_archive:
        # The bytes only exist on the archive, and the fallback tables have no path to offer. Naming
        # it is the useful half of a degraded check; downloading a guessed path is not.
        print(f"\n跳过逐张比对：archive 没答话，而 MoeNotes 的表里没有下载路径，"
              f"{len(suspect)} 张等它回来再比")
        suspect = []
    byte_moved, unchanged, failed = [], 0, []
    if verify and suspect:
        os.makedirs(STAGING, exist_ok=True)
        print(f"\n=== 逐张比对原始谱字节（{len(suspect)} 张，下载到 {STAGING}）===")
        for i, cid in enumerate(suspect, 1):
            rel = live[cid]["file"]
            url = f"{BASE}{rel if rel.startswith('/') else '/' + rel}"
            stored = f"{CHARTS}/{cid}.raw.json"
            try:
                blob = get(url)
                json.loads(blob)                      # a 200 that is not JSON is not a chart
            except Exception as e:                    # noqa: BLE001 - one bad fetch is a report line
                failed.append((cid, repr(e)))
                continue
            open(f"{STAGING}/{cid}.raw.json", "wb").write(blob)
            if not os.path.exists(stored):
                byte_moved.append((cid, "本地没有 raw"))
            elif sha(blob) != sha(open(stored, "rb").read()):
                byte_moved.append((cid, "字节不同"))
            else:
                unchanged += 1
            time.sleep(0.15)              # same courtesy as the downloader's sweep
            if i % 25 == 0:
                print(f"  [{i}/{len(suspect)}] {unchanged} 未变, {len(byte_moved)} 变, "
                      f"{len(failed)} 取不到", flush=True)
        print(f"  结果：{unchanged} 张与存盘一致，{len(byte_moved)} 张字节变了，{len(failed)} 张取不到")
        for cid, why in byte_moved:
            print(f"  !! {cid} {live[cid]['title'][:22]:<22} {why}")
        for cid, why in failed[:10]:
            print(f"  ?? {cid} {why}")

    report = {"new": new, "gone": gone, "fields_changed": changed,
              "byte_moved": [c for c, _ in byte_moved], "byte_unchanged": unchanged,
              "failed": [c for c, _ in failed], "asked_archive": from_archive,
              "evidence": evidence, "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    write_json(REPORT, report)
    print(f"\n写入 {REPORT}")
    if new:
        titles = sorted({live[c]["title"] for c in new})
        print(f"  新曲 {len(set(c.split('_')[0] for c in new))} 首：{'、'.join(titles[:8])}"
              + (" …" if len(titles) > 8 else ""))
    if byte_moved:
        print("  这些谱的几何已经不在了：重编译它=拿新谱换掉飞过的那份，必须重飞一次有界测试；"
              "钉子（validated.json）里的那些尤其要先 --pin 更新指纹再动。")


if __name__ == "__main__":
    main()
