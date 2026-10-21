"""Read the game's 乐曲选择 screen: which song and which difficulty is selected right now.

No OCR anywhere -- uiautomator returns empty nodes on this Unity build (tested 2026-09-29), so
both answers come from pixels:

  - Song: the large jacket art in the right panel, drawn as a 300x300 square whose top-left is
    JACKET_BOX. Matching a 32x32 grey crop of it against the 85 jacket thumbnails downloaded
    from haneoka scores 0.94-0.99 for the selected song and <= 0.52 for every other one, so
    nearest neighbour plus a margin check is decisive. The descriptor is phase sensitive -- a
    +/-2 px offset still reads >=0.91, 4 px off drops to ~0.7, and a 304x303 box on the aligned
    corner reads 0.73 -- and the art's position relative to the frame drifts a few px with the
    capture state (measured 2026-09-29: the same select page read 0.96 in one run and 0.61-0.73
    in the next), so _match_jacket probes a small grid around JACKET_BOX instead of trusting
    one fixed crop.
  - Difficulty: the bar's four segments are equal quarters of one pill (pill x 741..1264, the
    four boundaries land on 871.75/1002.5/1133.25). The selected segment is the only saturated
    block in that row -- EXPERT measured as salmon (192,88,88) against a light-lavender
    (184,192,216) fill for the rest -- so colour only locates the block; its position names the
    difficulty.

Cost: 9.5 ms per read on the live select page (12 frames, mumucap, 2026-09-29); capture and the
difficulty read dominate, jacket probes cost 0.27 ms each and an aligned pane answers on the
first. The library is a 340 KB npz, 0.4 ms to load.
"""
from __future__ import annotations

import json
import os
import urllib.request

import numpy as np
from PIL import Image

from rlog import CHARTS, MANIFEST  # noqa: E402

JACKET_DIR = os.path.join(CHARTS, "jackets")
INDEX = os.path.join(CHARTS, "jackets.npz")
BASE = "https://haneoka.org"
UA = {"User-Agent": "Mozilla/5.0"}

JACKET_BOX = (738, 94)                 # top-left of the art square in the right panel, device px
JACKET_ART = 300                       # the pane draws the jacket at exactly this size, and the
                                       # haneoka thumbnails are the same art at the same scale:
                                       # an aligned crop reads 0.994
JACKET_SEARCH_R = 10                   # the art sits a few px from the calibration point in some
JACKET_SEARCH_STEP = 2                 # capture states, so _match_jacket sweeps this grid
JACKET_GOOD = 0.92                     # a probe this high is aligned enough; stop the sweep
DIFF_BAND = (527, 585)                 # rows of the difficulty pill
DIFF_X = (700, 1280)
# The pill is a fixed piece of layout: measured x 741..1265 (524 px) with the four segments as
# equal quarters of 131 px, verified because the selected EXPERT block came back 1133..1263,
# exactly the fourth quarter. Detecting the pill by brightness instead does not work -- the white
# song list to its left also passes a "light" test (up to 0.86 of the rows in a column) -- so the
# geometry is a constant and only the highlight is searched for.
PILL_X = (741, 1265)
DIFF_NAMES = ("easy", "normal", "hard", "expert")
FEAT = 32                              # jacket crops are compared at 32x32 grey
MIN_SCORE = 0.80                       # correct song measured 0.94, runner-up <= 0.52
MIN_GAP = 0.15
SAT_MIN = 60                           # max-min channel spread of the selected segment
DIFF_ROW_H = DIFF_BAND[1] - DIFF_BAND[0]
DIFF_SHIFT = 30                        # 多人 乐曲选择页 draws the same pill row 30 px lower
DIFF_BANDS = (DIFF_BAND[0], DIFF_BAND[0] + DIFF_SHIFT)
DIFF_ALIGN = 25.0                      # a highlight only counts on the quarter it names
PREP_JACKET_BOX = (856, 80)            # where the 準備页 draws the 抽签 drawn song's art
PREP_JACKET_GOOD = 0.90                # measured 0.993 for the drawn song, runner-up 0.410
PREP_JACKET_GAP = 0.20


def feat(crop) -> np.ndarray:
    """Zero-mean unit-norm 32x32 grey descriptor of a PIL image or an HxWx3 array."""
    if not isinstance(crop, Image.Image):
        crop = Image.fromarray(np.asarray(crop, dtype=np.uint8))
    a = np.asarray(crop.convert("L").resize((FEAT, FEAT), Image.LANCZOS), dtype=np.float32)
    a = a.ravel()
    a -= a.mean()
    n = float(np.linalg.norm(a))
    return a / (n or 1.0)


def _jacket_url(path):
    return BASE + path if path.startswith("/") else path


def ensure_library(download=True, force=False, log=print) -> int:
    """Download any missing jackets, (re)build the index. Returns the number of songs indexed."""
    manifest = json.load(open(MANIFEST, encoding="utf-8"))
    os.makedirs(JACKET_DIR, exist_ok=True)
    ids, mats, missing = [], [], 0
    for s in manifest["songs"]:
        mid, path = s.get("musicId"), s.get("jacket") or ""
        dst = os.path.join(JACKET_DIR, f"{mid}.png")
        if force and os.path.exists(dst):
            os.remove(dst)
        if not os.path.exists(dst):
            if not download or not path:
                missing += 1
                continue
            req = urllib.request.Request(_jacket_url(path), headers=UA)
            try:
                open(dst, "wb").write(urllib.request.urlopen(req, timeout=30).read())
            except Exception as e:                                # noqa: BLE001
                log(f"jacket failed {mid}: {e!r}")
                missing += 1
                continue
        ids.append(mid)
        mats.append(feat(Image.open(dst)))
    if mats:
        np.savez_compressed(INDEX, ids=np.array(ids, dtype="<U12"),
                            feat=np.stack(mats).astype(np.float32))
    log(f"jacket library: {len(ids)} indexed"
        + (f", {missing} missing (recognition needs all 85)" if missing else ""))
    return len(ids)


_index_cache: tuple | None = None
_index_stamp: tuple | None = None


def _index_stamp_now():
    """(mtime_ns, size) of the npz, or None when it is not on disk yet."""
    try:
        st = os.stat(INDEX)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def load_index():
    """(ids, feat matrix) or (None, None) when the library has not been built yet.

    The cache is revalidated against the npz's (mtime, size) on **every** call: this module is
    imported into long-lived processes. The panel reads the 楽曲選択 page in-process, while
    `fetch_charts.py` rebuilds the library from a subprocess whenever a song is added -- a cache
    that is never revalidated leaves the new song's jacket unrecognisable for the whole life of
    that panel. Measured 2026-10-16 (user m28348): the frame that scores 0.9775 against the
    rebuilt 89-song index scores 0.3945 against the stale 88-song one, far under MIN_SCORE, so
    the read comes back "not the select screen" for a page that is exactly that.
    """
    global _index_cache, _index_stamp
    stamp = _index_stamp_now()
    if stamp is None:
        _index_cache, _index_stamp = None, None
        return None, None
    if _index_cache is None or stamp != _index_stamp:
        with np.load(INDEX) as z:
            _index_cache = ([str(x) for x in z["ids"]], z["feat"])
        _index_stamp = stamp
    return _index_cache


def chart_for(music_id, diff):
    """(song, difficulty entry) from the manifest for a game (musicId, difficulty name).

    What the game shows has to be turned into a local chart file for anything to be fired, and
    the two halves fail separately: the song may be absent from the library, or only that
    difficulty may be. Both are None when the manifest itself is missing.
    """
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            man = json.load(f)
    except OSError:
        return None, None
    song = next((s for s in man.get("songs", [])
                 if str(s.get("musicId")) == str(music_id)), None)
    if song is None:
        return None, None
    return song, next((d for d in song.get("difficulties", []) if d.get("name") == diff), None)


def _grab():
    """One frame from the emulator, or raise.

    `detect.grab` is whatever capture source the round has installed -- the renderer SDK under
    `--fastcap`, window capture under `--host`, screencap otherwise -- which is the same pixels
    `calib`'s walk and `songpick.read_current` read. This used to import `mumucap` directly, so a
    round without `--fastcap` could not read this page at all even though it was reading every
    other page fine.
    """
    import detect
    return detect.grab()


def _diff_run(band):
    """((x0, x1) in device x, width) of the widest saturated run in one pill-row band, or (None, 0)."""
    mx, mn = band.max(axis=2), band.min(axis=2)
    sat = (mx - mn) > SAT_MIN
    h = band.shape[0]

    start, runs = None, []
    col = sat.sum(axis=0) >= h * 0.5
    for i, v in enumerate(col):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(col)))
    merged = []                            # the level digits punch light holes in the fill
    for a, b in runs:
        if merged and a - merged[-1][1] <= 40:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    if not merged:
        return None, 0
    bx0, bx1 = max(merged, key=lambda r: r[1] - r[0])
    return (bx0 + DIFF_X[0], bx1 + DIFF_X[0]), bx1 - bx0


def read_difficulty(img):
    """('expert'|..., detail) or (None, why).

    Two bands, because the 多人 乐曲选择页 draws the same four pills DIFF_SHIFT px lower: on the
    frame g486 died on the single-player band found the song art's own saturated block at
    851..952 (named "normal") while the band 30 px down found 1133..1264, exactly the EXPERT
    quarter the player had selected. A block only counts when it sits on the quarter it names
    (DIFF_ALIGN), which is what keeps the 乐队确认 banner, the 準備页 frame and a cover's own art
    from answering with a difficulty nobody picked. A block in the first band is answered off its
    own geometry alone -- that is the row this function has always read, so every single-player
    read is unchanged by construction.
    """
    arr = np.asarray(img, dtype=np.int16)
    if arr.ndim != 3 or arr.shape[2] < 3:
        return None, "frame is not RGB"
    seg = (PILL_X[1] - PILL_X[0]) / 4.0
    legacy, why = None, "no highlighted difficulty segment"
    for k, top in enumerate(DIFF_BANDS):
        band = arr[top:top + DIFF_ROW_H, DIFF_X[0]:DIFF_X[1]]
        if band.shape[0] != DIFF_ROW_H:
            continue
        run, best = _diff_run(band)
        if run is None:
            continue
        bx0, bx1 = run
        if best < seg * 0.5:
            why = "no highlighted difficulty segment"
            continue
        if best > seg * 1.3:
            why = "highlight spans several segments"
            continue
        idx = int(((bx0 + bx1) / 2.0 - PILL_X[0]) / seg)
        if not 0 <= idx <= 3:
            why = f"highlight outside the pill (idx {idx})"
            continue
        detail = {"block": (int(bx0), int(bx1)), "row": top}
        if k == 0:
            # Only the single-player band answers off its own geometry: it is the row this
            # function has always read, so its verdict stands whatever it lands on. A block in
            # the lower band counts only when it sits on the quarter it names -- otherwise the
            # 乐队确认 banner, a story page and a LIVE HUD frame all come back with a difficulty
            # nobody selected (measured: 1210 frames on this machine).
            legacy = (DIFF_NAMES[idx], detail)
        if abs((bx0 + bx1) / 2.0 - (PILL_X[0] + seg * (idx + 0.5))) <= DIFF_ALIGN:
            return DIFF_NAMES[idx], detail
    return legacy if legacy is not None else (None, why)


_JACKET_OFFS: list | None = None


def _jacket_offsets():
    """The probe grid around JACKET_BOX, nearest first so an aligned art answers on the first try."""
    global _JACKET_OFFS
    if _JACKET_OFFS is None:
        offs = [(dx, dy)
                for dx in range(-JACKET_SEARCH_R, JACKET_SEARCH_R + 1, JACKET_SEARCH_STEP)
                for dy in range(-JACKET_SEARCH_R, JACKET_SEARCH_R + 1, JACKET_SEARCH_STEP)]
        offs.sort(key=lambda o: o[0] * o[0] + o[1] * o[1])
        _JACKET_OFFS = offs
    return _JACKET_OFFS


def _match_jacket(arr, mat, box=None):
    """Best (index, score, runner-up score, top-left) for the pane jacket in one frame.

    A single fixed crop stopped being enough on 2026-09-29: the same select page that read 0.96
    in one run read 0.61-0.73 in the next, because the art sits a few px off the calibration
    point in some capture states and the 32x32 descriptor loses >0.2 ncc per 2 px of phase slip.
    Probes stop early on an aligned hit (0.94-0.99); text or a score page never reaches even the
    0.80 gate at any position, so a low best here is a real "not the select screen".
    """
    x0, y0 = box or JACKET_BOX        # 準備页 draws the drawn song at PREP_JACKET_BOX
    best = None
    for dx, dy in _jacket_offsets():
        x, y = x0 + dx, y0 + dy
        s = mat @ feat(arr[y:y + JACKET_ART, x:x + JACKET_ART])
        o = np.argsort(-s)
        top, second = float(s[o[0]]), float(s[o[1]])
        if best is None or top > best[1]:
            best = (int(o[0]), top, second, (x, y))
        if top >= JACKET_GOOD:
            break
    return best


def read_song_select(frame=None):
    """Identify the game's current 乐曲选择 selection.

    {'ok': True, 'musicId': ..., 'diff': 'expert', 'score': .94, 'gap': .44, 'pos': [x, y], ...}
    {'ok': False, 'why': '...'} -- not on the song-select screen, or the library is missing.
    """
    ids, mat = load_index()
    if ids is None:
        return {"ok": False, "why": "封面库未建立（设置页「资源」卡点「联网更新」，或跑 "
                                    "tools/gameread.py）"}
    try:
        arr = np.asarray(_grab() if frame is None else frame)
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "why": f"取帧失败（模拟器在运行吗）：{e!r}"}
    idx, best, second, pos = _match_jacket(arr, mat)
    if best < MIN_SCORE or best - second < MIN_GAP:
        return {"ok": False, "why": "画面上没有可识别的选曲封面（游戏在乐曲选择页吗）",
                "score": best, "gap": best - second, "pos": list(pos)}
    diff, detail = read_difficulty(arr)
    if diff is None:
        return {"ok": False, "why": f"认出歌曲 {ids[idx]}，但读不到难度：{detail}",
                "musicId": ids[idx], "pos": list(pos)}
    return {"ok": True, "musicId": ids[idx], "diff": diff,
            "score": best, "gap": best - second, "pos": list(pos), "detail": detail}


def read_band(frame=None):
    """The 難度 pill row alone: {'ok': True, 'diff', 'row', 'block'} / {'ok': False, 'why'}.

    `read_song_select` refuses to say anything about the pills until the jacket library is built
    and a cover has matched, and the 多人 walk needs neither half: the room draws the song, and
    all the walk wants off this page is which band the lit pill sits in -- the single-player page
    starts at DIFF_BAND[0] (row 527), the 多人 one DIFF_SHIFT px lower (row 557) -- plus the
    difficulty name. Reading the band alone also survives a page whose cover is scrolled out of
    its box, and since `_grab` goes through `detect.grab` it works on a round with no `--fastcap`:
    that was the one way the walk could not tell the two pages apart and went on to press 決定 on
    a page it had not identified (2026-10-08, user m04278).
    """
    try:
        arr = np.asarray(_grab() if frame is None else frame)
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "why": f"取帧失败（模拟器在运行吗）：{e!r}"}
    diff, detail = read_difficulty(arr)
    if diff is None:
        return {"ok": False, "why": detail}
    return {"ok": True, "diff": diff, "row": detail.get("row"), "block": detail.get("block")}


def read_prep(frame=None):
    """Identify the song the 多人 room drew, off the 準備页.

    {'ok': True, 'musicId': ..., 'score': .99, 'gap': .58, 'pos': [x, y]}
    {'ok': False, 'why': '...'}

    The 準備页 is the only page that shows the drawn song, and it is the *room's* draw, not our
    own nomination: in the mp2 recording the 乐曲选择 page read 100056 at 0.995 (what the player
    had picked) while this page read 100080 at 0.993, and that round's result page counted 650
    judged notes -- exactly 100080's EXPERT noteCount, against 843 for 100056's. So the chart a
    多人 round plays is decided here, after the draw, and never before it.
    """
    ids, mat = load_index()
    if ids is None:
        return {"ok": False, "why": "封面库未建立（设置页「资源」卡点「联网更新」，或跑 "
                                    "tools/gameread.py）"}
    try:
        arr = np.asarray(_grab() if frame is None else frame)
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "why": f"取帧失败（模拟器在运行吗）：{e!r}"}
    idx, best, second, pos = _match_jacket(arr, mat, PREP_JACKET_BOX)
    if best < PREP_JACKET_GOOD or best - second < PREP_JACKET_GAP:
        return {"ok": False, "why": f"准备页上读不出抽中的是哪首（{PREP_JACKET_BOX} 那一块不像封面）",
                "score": best, "gap": best - second, "pos": list(pos)}
    return {"ok": True, "musicId": ids[idx], "score": best, "gap": best - second,
            "pos": list(pos)}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="read + verify the game's song-select selection")
    ap.add_argument("--build", action="store_true", help="download jackets / rebuild the index")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--frames", type=int, default=5, help="repeat the read N times")
    a = ap.parse_args()
    if a.build:
        ensure_library(force=a.force)
    for i in range(a.frames):
        r = read_song_select()
        print(json.dumps(r, ensure_ascii=False))
