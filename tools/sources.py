"""Two sources for one library, and the manners each one is owed.

Haneoka (haneoka.org) is the only source with a *compilable* chart: it ingests the game's own
packages, decodes MusicScore into {meta, score:{events, notes}}, and publishes an immutable
release to R2 (its `.github/workflows/resource-pipeline.yml` is the whole story). Everything we
fly is those bytes -- the pin in validated.json is a sha of a Haneoka decode -- so no other
source may stand in for a chart.

MoeNotes (github.com/StarMoe-org/moenotes-masterdata) publishes the game's master tables per
region. It answers one question better than Haneoka does: *has anything moved?* Measured on the
2026-09-30 update (intl resource 1.0.0.201): their `hk-tw-mo` tables were pushed at 09:15:35Z,
while Haneoka's pipeline failed at 09:11Z and again at 09:31Z and only promoted at 11:13Z -- two
hours of "nothing new" from the source we used to ask. And 344 of their `_fullComboCount` values
agree with the `noteCount` our library already holds, 0 disagreements, so a difference between
them is a real revision rather than schema drift.

So: **MoeNotes decides whether to go look, Haneoka decides what we store.** Names, jacket URLs,
romaji and chart paths only exist on Haneoka anyway (`titleRomaji` is one of its locale slots),
and asking the archive for its 16 KB catalog is exactly what a quiet MoeNotes check spares it.

Both sides are then bounded by `research/charts/_sources/state.json`: at most one 4.8 MB tarball a
day (GitHub's CDN, not their origin), and one conditional catalog request whose 304 costs almost
nothing -- Haneoka answers `If-None-Match` with a real 304 (measured) and exposes
`X-Haneoka-Release-Id` for a body-free "did it move" check.

Nothing here writes into the library; `fetch_charts.py` stays the only thing that does.

Usage (from a shell, mostly for the probe):
    python tools/sources.py                # what would a refresh do right now?
    python tools/sources.py --moenotes     # parse their tables from the cache/tarball
"""

import json
import os
import sys
import tarfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rlog import CHARTS, MANIFEST, atomic_write, write_json  # noqa: E402

HANEOKA = "https://haneoka.org"
HANEOKA_CATALOG = f"{HANEOKA}/api/v1/servers/intl/songs"
# Their repo, not their site: one tarball carries all four regions' tables plus the version file.
MOENOTES_TARBALL = ("https://codeload.github.com/StarMoe-org/moenotes-masterdata"
                    "/tar.gz/refs/heads/main")
MOENOTES_REGION = "hk-tw-mo"          # the international server: 344 charts, our library exactly
# A name a human reads, not a bot: it is what lets the other side contact us if this ever is too
# much, which is the whole point of the etiquette rule it serves.
UA = {"User-Agent": "OurNotes-autoplay-panel/1.0 (+chart library refresh)",
      "Accept-Encoding": "gzip"}

SOURCES = os.path.join(CHARTS, "_sources")
STATE = os.path.join(SOURCES, "state.json")
TARBALL = os.path.join(SOURCES, "moenotes-masterdata.tar.gz")
DAY = 86400.0


def _read(url, headers=None, timeout=60):
    """GET with our UA and gzip accepted; returns (bytes, response headers)."""
    h = dict(UA)
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read(), dict(r.headers)


def _state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(st):
    os.makedirs(SOURCES, exist_ok=True)
    write_json(STATE, st)


def _fresh(path, max_age=DAY):
    return os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age


# ---------------------------------------------------------------- MoeNotes: the "did it move" side

def moenotes(force=False):
    """The game's own master tables, as {cid: {level, sortLevel, noteCount}} plus a version.

    One request for the whole repo (4.8 MB) and at most one a day: the version inside it
    (`current_version.json`) is compared first, so a day that changes nothing costs nothing.
    Raises on any trouble -- the caller decides whether that means "ask Haneoka instead".
    """
    st = _state()
    # The tarball's own mtime is the daily bound: a copy that is already here and already fresh
    # is not fetched again, whether it got here through this function or by hand.
    if not force and _fresh(TARBALL):
        return _moenotes_parse()
    blob, _ = _read(MOENOTES_TARBALL)
    os.makedirs(SOURCES, exist_ok=True)
    with open(TARBALL, "wb") as f:
        f.write(blob)
    out = _moenotes_parse()
    st["moenotes"] = {"tarball_at": time.time(), "version": out["version"],
                      "charts": len(out["charts"])}
    _save_state(st)
    return out


def _moenotes_table(tf, name):
    member = next((m for m in tf.getmembers()
                   if m.name.endswith(f"{MOENOTES_REGION}/{name}")), None)
    if member is None:
        raise RuntimeError(f"their tarball has no {MOENOTES_REGION}/{name}")
    d = json.loads(tf.extractfile(member).read().decode("utf-8"))
    # The service publishes either a bare array or a one-key wrapper; both are the same table.
    return d if isinstance(d, list) else next(iter(d.values()))


def _moenotes_parse():
    with tarfile.open(TARBALL) as tf:
        music = _moenotes_table(tf, "MasterLiveMusic.json")
        score = _moenotes_table(tf, "MasterLiveMusicScore.json")
        ver = json.loads(next((tf.extractfile(m).read() for m in tf.getmembers()
                               if m.name.endswith("current_version.json")), b"{}"))
    region = (ver.get("regions") or {}).get(MOENOTES_REGION) or {}
    charts = {}
    for row in score:
        # "_musicScoreTextFileName": "0062/0062_03" -- the same book_dd our files are named by.
        tail = (row.get("_musicScoreTextFileName") or "").rsplit("/", 1)[-1]
        if "_" not in tail:
            continue
        cid = tail.removesuffix(".bytes") if tail.endswith(".bytes") else tail
        book, dd = cid.split("_", 1)
        charts[cid] = {"book": book, "dd": dd, "musicId": row.get("_musicId"),
                       "level": row.get("_musicScoreLevel"),
                       "sortLevel": row.get("_musicScoreDisplayLevel"),
                       "noteCount": row.get("_fullComboCount")}
    return {"source": "moenotes", "region": MOENOTES_REGION,
            "version": region.get("version") or "", "resource": region.get("resource_version") or "",
            "verified_at": region.get("verified_at") or "", "charts": charts}


# ------------------------------------------------------------------ Haneoka: what we actually store

def haneoka(force=False):
    """The archive's catalog, with a conditional request so a no-change check costs ~0 bytes.

    `force` is what --force keeps: a real refresh has to really go out. Otherwise the cached copy
    is reused inside DAY, and past that the stored ETag is offered back to them first.
    """
    st = _state()
    cached = os.path.join(SOURCES, "haneoka-songs.json")
    etag = (st.get("haneoka") or {}).get("etag")
    if not force and _fresh(cached):
        with open(cached, encoding="utf-8") as f:
            return {"source": "haneoka", "songs": json.load(f), "reused": "cache"}
    headers = {"If-None-Match": etag} if etag and not force else {}
    try:
        blob, hdr = _read(HANEOKA_CATALOG, headers)
    except urllib.error.HTTPError as e:
        if e.code != 304 or not os.path.exists(cached):
            raise
        # 304 carries no body: the headers are on the error, and the cached bytes are still current.
        with open(cached, encoding="utf-8") as f:
            songs = json.load(f)
        # They just told us this copy is up to date, so its mtime starts the day over again --
        # otherwise every later refresh that day would pay for another request.
        os.utime(cached, None)
        return {"source": "haneoka", "songs": songs, "reused": "304",
                "release": e.headers.get("X-Haneoka-Release-Id")}
    if blob[:2] == b"\x1f\x8b":
        import gzip
        blob = gzip.decompress(blob)
    songs = json.loads(blob)
    os.makedirs(SOURCES, exist_ok=True)
    # Atomic, and trusted-on-existence is what makes it matter: a truncated tarball keeps a fresh
    # mtime, so every later parse fails and the check silently degrades for a day.
    atomic_write(cached, blob, binary=True)
    st["haneoka"] = {"fetched_at": time.time(), "etag": hdr.get("ETag") or "",
                     "release": hdr.get("X-Haneoka-Release-Id") or "", "songs": len(songs)}
    _save_state(st)
    return {"source": "haneoka", "songs": songs, "reused": None,
            "release": hdr.get("X-Haneoka-Release-Id")}


# ------------------------------------------------------------------------- the decision both call

def _library_cids():
    """{cid: noteCount} from our own manifest -- what MoeNotes is compared against."""
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            man = json.load(f)
    except (OSError, ValueError):
        return {}
    return {f"{d['book']}_{d['dd']}": d.get("noteCount")
            for s in man.get("songs", []) for d in s.get("difficulties", [])}


def plan(preferred="moenotes", force=False):
    """What a library refresh should do, and the lines that say why.

    Returns {"look": bool, "source": str, "notes": [...], "moenotes": dict|None}. `look` is the
    answer to "should we ask Haneoka for its catalog and any new chart bytes at all"; the whole
    point of the MoeNotes side is that it is usually no.
    """
    notes, mn = [], None
    library = _library_cids()
    order = ["moenotes", "haneoka"] if preferred == "moenotes" else ["haneoka"]
    for name in order:
        if name != "moenotes":
            break
        try:
            mn = moenotes(force=force)
        except Exception as e:                                    # noqa: BLE001 - a mirror is a mirror
            notes.append(f"MoeNotes 目录源没拿到（{type(e).__name__}: {e}），改问 Haneoka")
            mn = None
            break
        new = sorted(c for c in mn["charts"] if c not in library)
        moved = sorted(c for c, v in mn["charts"].items()
                       if c in library and v.get("noteCount") != library[c])
        notes.append(f"MoeNotes {mn['region']} {mn['resource'] or mn['version']} "
                     f"({mn['verified_at'][:16].replace('T', ' ') if mn['verified_at'] else '?'}) "
                     f"{len(mn['charts'])} 张：库里缺 {len(new)}，判定物数变了 {len(moved)}")
        if new:
            notes.append("  新歌: " + " ".join(new[:12]) + (" …" if len(new) > 12 else ""))
        if moved:
            notes.append("  疑似改谱: " + " ".join(
                f"{c}({library[c]}→{mn['charts'][c]['noteCount']})" for c in moved[:8]))
        if not force and not new and not moved:
            return {"look": False, "source": "moenotes", "notes": notes, "moenotes": mn}
        break
    return {"look": True, "source": "haneoka" if mn is None else "moenotes→haneoka",
            "notes": notes, "moenotes": mn}


def main():
    if "--moenotes" in sys.argv:
        mn = moenotes(force="--force" in sys.argv)
        print(f"{mn['region']} {mn['resource']} version={mn['version']} "
              f"verified={mn['verified_at']} charts={len(mn['charts'])}")
        return 0
    p = plan(force="--force" in sys.argv)
    for line in p["notes"]:
        print(line)
    print(f"-> 该去 Haneoka 看吗: {'要' if p['look'] else '不用'}（{p['source']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
