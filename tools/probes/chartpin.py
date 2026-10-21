"""Offline regression for the 已验证谱面 pin: three guards that all have to hold.

Guard one -- `--force` cannot leave a flown chart playing bytes nobody has played. The sweep now
recompiles everything, including a pinned chart, and then compares against the bytes it found on
disk: different means the ones that were there go back and the compiler's new ones are parked in the
relearn queue. That is a claim about a code path which normally spends ten minutes on the network, so
it is tested here against a temp copy of the library with `get` stubbed out: nothing is downloaded,
the real research/charts/ is never touched, and every outcome that matters is read back off disk.

Four cases, because a guard that blocks everything would pass a one-case test:
  pinned            --force alone -> the bytes that were there are back, the candidate is parked,
                    and `--relearn` lists it
  pinned, named     --force --recompile <cid> -> the new bytes stay, and the run says so
  unpinned          --force -> rewritten, untouched by the pin
  archive           --pin writes the byte store, and every copy in it decompresses to exactly the
                    bytes the library is playing -- an archive you cannot restore from is a receipt

Guard two -- `--pin` cannot forget a chart. The pin is built from research/results.jsonl, which
keeps the newest 100 rounds, so a pin that only ever listed today's log rows would quietly stop
protecting a chart the moment its only round aged out of the file -- unprotecting exactly the
geometry the history no longer carries. `cumulative()` trims a copy of the log to 20 rounds and
checks the pin keeps every entry and every fingerprint.

Guard three -- the file's shape (`shapes()`). validated.json has had two: v1 said "this chart was
flown, on bytes with this sha", v2 carries the fingerprint the *round itself* recorded (compiled
bytes, raw chart, compiler, upstream revision) so a pin can be dated instead of assumed. The real
file is still v1, so the migration is read off it directly: fields carried across intact, everything
v1 never recorded left as None, and the current/drifted/unrecorded verdict required to change when
any one of those fingerprints changes -- a verdict that always answers "current" is the failure this
guard is for.

Usage: python tools/probes/chartpin.py       (exit 0 = PASS)
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import audit_charts as ac                                                    # noqa: E402
import fetch_charts as fc                                                    # noqa: E402
import rlog                                                                  # noqa: E402

REAL = "research/charts"
RESULTS = "research/results.jsonl"


def pick():
    """(a pinned chart the current compiler still moves, a chart nobody pinned).

    Chosen from the library every run because naming them rotted the day one was rebuilt: what the
    three cases need is a property the chart happens to have today, not a hard-coded id.
    """
    pins = fc.read_pins()
    loose = next(c for c in sorted(p.name[: -len(".hits.json")]
                                   for p in Path(rlog.CHARTS).glob("*.hits.json"))
                 if c not in pins)
    moved = next(c for c in sorted(pins)
                 if (ac.rebuild_delta(c) or {}).get("entries"))
    return moved, loose


PINNED, LOOSE = pick()


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def fake_get(url, timeout=30):
    """The three endpoints, answered from the two charts sitting in the temp library.

    A --force sweep re-downloads the raw chart too, so the chart URL has to return the real bytes:
    serve it junk and every case fails as a compile error instead of as a guard decision.
    """
    if "bands" in url:
        return b"{}"
    if "/charts/" in url:
        cid = url.rsplit("/", 1)[-1].removesuffix(".bytes")
        return open(f"{REAL}/{cid}.raw.json", "rb").read()
    songs = {}
    for i, cid in enumerate((PINNED, LOOSE), 1):
        book, dd = cid.split("_")
        songs[str(i)] = {
            "musicTitle": [cid], "bandName": ["probe"], "bandId": 1,
            "difficulty": [{"file": f"/charts/{book}_{dd}.bytes", "difficultyName": "EXPERT",
                            "displayLevel": 26, "noteCount": 1}],
        }
    return json.dumps(songs).encode()


def build_lib(tmp):
    for cid in (PINNED, LOOSE):
        for ext in (".raw.json", ".hits.json"):
            shutil.copyfile(f"{REAL}/{cid}{ext}", f"{tmp}/{cid}{ext}")
    rlog.write_json(f"{tmp}/validated.json", {"updated": "probe", "charts": {
        PINNED: {"np": 0, "tag": "probe",
                 "sha": sha(f"{tmp}/{PINNED}.hits.json")[:16]}}})
    # A sentinel: the unpinned chart's file is made obviously not-a-hit-list, so "it changed"
    # proves a write happened rather than that the compiler is deterministic.
    with open(f"{tmp}/{LOOSE}.hits.json", "w", encoding="utf-8") as f:
        f.write("[]")


def run(tmp, argv):
    out = io.StringIO()
    import gameread
    # CHARTS and MANIFEST are what the sweep opens; OUT_DIR only spells the paths it records.
    # Patching the wrong one of these is not a harmless test bug: the sweep then writes into the
    # real library, and 2026-09-30 lost a pinned chart's flown bytes that way. The last four are
    # the rollback store and the relearn queue -- both live outside research/charts/, and a probe
    # that wrote them would be a probe editing committed evidence.
    names = ("OUT_DIR", "CHARTS", "MANIFEST", "VALIDATED", "RESULTS", "HISTORY_FULL", "get",
             "PINS", "PINS_INDEX", "RELEARN", "RELEARN_INDEX")
    old = {n: getattr(fc, n) for n in names}
    fc.OUT_DIR, fc.CHARTS, fc.MANIFEST = tmp, tmp, f"{tmp}/manifest.json"
    fc.VALIDATED, fc.RESULTS, fc.get = f"{tmp}/validated.json", f"{tmp}/results.jsonl", fake_get
    fc.HISTORY_FULL = f"{tmp}/results.jsonl"
    fc.PINS, fc.PINS_INDEX = f"{tmp}/pins", f"{tmp}/pins/INDEX.json"
    fc.RELEARN, fc.RELEARN_INDEX = f"{tmp}/_relearn", f"{tmp}/_relearn.json"
    old_argv, sys.argv = sys.argv, argv
    # The sweep refreshes the jacket library at the end; that is network and unrelated here.
    keep_jackets = gameread.ensure_library
    gameread.ensure_library = lambda download=False: None
    try:
        with contextlib.redirect_stdout(out):
            fc.main()
    finally:
        for n, v in old.items():
            setattr(fc, n, v)
        gameread.ensure_library = keep_jackets
        sys.argv = old_argv
    return out.getvalue()


def _other_chart(seen):
    """A chart from the real library that the log does not name -- the synthetic row's subject."""
    import glob as _glob

    for p in sorted(_glob.glob(os.path.join(rlog.CHARTS, "*.hits.json"))):
        cid = os.path.basename(p)[: -len(".hits.json")]
        if cid and cid not in seen:
            return cid
    return None


def cumulative():
    """--pin must not lose a chart whose only round trimmed out of the 100-row log."""
    tmp = tempfile.mkdtemp(prefix="pinlife_")
    shutil.copyfile(RESULTS, f"{tmp}/results.jsonl")
    # The corpus can degenerate to a single chart -- 2026-10-19 the user left 乐曲识别 running and
    # the whole 100-row window became 0058_03 x100, at which point "the moment one chart falls out
    # of the window" no longer exists and this test could only fail. That failure is the log's
    # shape, not the code's, so give the log a second (real) chart to carry: the synthetic row is
    # the oldest, so trimming to the newest row drops it exactly like an aged-out round.
    rows = rlog.read_records(f"{tmp}/results.jsonl")
    seen = {r.get("chart") for r in rows if r.get("chart")}
    if len(seen) < 2 and rows:
        other = _other_chart(seen)
        if other:
            row = dict(rows[0])
            row.update({"chart": other, "tag": "probe", "rc": 0, "non_perfect": 0,
                        "at": {"hits": fc.hits_sha(other)}})
            rlog.write_records(f"{tmp}/results.jsonl", [row] + rows, cap=10 ** 9)
    # CHARTS stays the real library: pin_current only ever reads it, and real fingerprints are the
    # half of the promise worth testing. VALIDATED, the log, the byte store and the queue go to the
    # temp dir -- pin_current now *writes* the store, and that is committed evidence.
    names = ("VALIDATED", "RESULTS", "HISTORY_FULL", "PINS", "PINS_INDEX", "RELEARN",
             "RELEARN_INDEX")
    old = {n: getattr(fc, n) for n in names}
    fc.VALIDATED, fc.RESULTS = f"{tmp}/validated.json", f"{tmp}/results.jsonl"
    fc.HISTORY_FULL = f"{tmp}/results.jsonl"      # the pin reads the history, not the window
    fc.PINS, fc.PINS_INDEX = f"{tmp}/pins", f"{tmp}/pins/INDEX.json"
    fc.RELEARN, fc.RELEARN_INDEX = f"{tmp}/_relearn", f"{tmp}/_relearn.json"
    try:
        # pin_current's own summary lines are the tested behaviour, not probe output.
        with contextlib.redirect_stdout(io.StringIO()):
            full = fc.pin_current()
            keep = rlog.read_records(f"{tmp}/results.jsonl")
            # 裁到「至少掉一张**已钉住的**谱」的那个窗口。2026-10-19 第二次踩同一个坑：
            # 原先这里问的是「日志里出现过的每一种谱」（`charts`），而 `pin_current` 只钉**飞过**
            # 的那些（`flown()`：那一局真按现在的字节打过）—— 语料里可能有一条不属于这一类的
            # 记录（当日那 100 行里就混着一条 0056_03），于是「覆盖全部 `charts` 的最小窗口」比
            # 「覆盖全部 `full` 的最小窗口」更宽：裁完那 6 行里两张已钉住的谱都还在，没有东西可
            # 携带，`set(again) > flew` 只能红。要证明的是「钉住的那张不会因为它的那一局被裁掉
            # 而丢」，所以窗口按 `full` 算。
            n = 1
            while n < len(keep) and not (set(full) - {r.get("chart") for r in keep[-n:]
                                                      if r.get("chart")}):
                n += 1
            cut = max(1, n - 1)
            rlog.write_records(f"{tmp}/results.jsonl", keep[-cut:], cap=cut)
            again = fc.pin_current()
            flew = set(rlog.flown(fc.RESULTS))
        gone = sorted(set(full) - set(again))
        changed = [c for c in again if c not in flew
                   and again[c]["at"].get("hits") != full[c]["at"].get("hits")]
        # The same promise made durable: --pin archives a compressed copy of the flown bytes, and an
        # archive that does not decompress to what the library is playing is not an archive.
        arch, mismatched = 0, []
        for cid in sorted(again):
            zz, lib = (os.path.join(tmp, "pins", f"{cid}.hits.zz"),
                       os.path.join(rlog.CHARTS, f"{cid}.hits.json"))
            if os.path.exists(zz):
                arch += 1
                if zlib.decompress(open(zz, "rb").read()) != open(lib, "rb").read():
                    mismatched.append(cid)
        # Everything whose flown bytes are still on disk must be archived; 0050_03 is the one entry
        # whose are not, and it is deliberately left out rather than faked.
        archivable = [c for c, e in again.items() if fc.hits_sha(c) == e["at"].get("hits")]
        print(f"log trimmed to the newest {cut} of {len(keep)} rows ({len(flew)} charts) "
              f"-> pin {len(full)} -> {len(again)}; "
              f"{len(set(again) - flew)} carried, dropped={gone}, sha_changed={changed}")
        print(f"byte store written by --pin: {arch}/{len(archivable)} 可存, "
              f"与库内字节不一致={mismatched}")
        return (not gone and set(again) > flew and not changed
                and arch == len(archivable) and not mismatched)
    finally:
        for n, v in old.items():
            setattr(fc, n, v)
        shutil.rmtree(tmp, ignore_errors=True)


def untouched():
    """Everything outside the temp dir this test could dirty: the library and the pin, and the two
    new stores -- the committed byte library and the relearn queue. Any change here means the probe
    leaked into the bytes a result was flown on, or wrote evidence it only came to read."""
    out = {}
    for p in (f"{REAL}/validated.json", f"{REAL}/manifest.json",
              f"{REAL}/{PINNED}.hits.json", f"{REAL}/{LOOSE}.hits.json",
              fc.PINS_INDEX, fc.RELEARN_INDEX, os.path.join(fc.RELEARN, f"{PINNED}.hits.json")):
        out[p] = sha(p) if os.path.exists(p) else None
    return out


def _cut(entry, k):
    """A copy of a pin entry with one fingerprint field replaced by something else."""
    e = json.loads(json.dumps(entry))
    e["at"][k] = "0123456789abcdef"
    return e


def shapes():
    """The pin has had two shapes, and a reader must not have to guess which one it got.

    ``validated.json`` on disk is still v1 -- nothing has been re-pinned since the fingerprint
    landed -- so this reads the real file, read-only, and asks the two questions the migration has
    to answer: are the three v1 fields carried across intact, and is everything v1 never recorded
    left as None? An entry that filled in today's raw chart would be the exact lie the fingerprint
    exists to prevent: it would read as "flown on these inputs" forever.

    Then the verdict, against a fabricated v2 entry holding this library's real fingerprints, with
    one field broken at a time. A verdict that answers 'current' whatever the bytes do is no
    verdict, and that is the failure mode worth a tripwire here.
    """
    v1 = rlog.pin_entry({"np": 3, "tag": "g001", "sha": "deadbeef"})
    moved = (v1["best"] == {"np": 3, "tag": "g001", "score": None, "ts": None}
             and v1["at"] == {"hits": "deadbeef", "raw": None, "build": None, "rev": None,
                              "cfg": None, "asof": None})
    pins = fc.read_pins()
    tidied = bool(pins) and all(set(e) == {"best", "at"} for e in pins.values())
    first = sorted(pins)[0]
    unrec = rlog.pin_state(first, pins[first]) == "unrecorded"

    now = rlog.fingerprint(first)
    good = {"best": {"np": 0},
            "at": {"hits": now["hits"], "raw": now["raw"], "build": now["build"],
                   "rev": now["rev"], "cfg": None, "asof": "flight"}}
    cur = rlog.pin_state(first, good, now) == "current"
    teeth = all(rlog.pin_state(first, _cut(good, k), now) == "drifted"
                for k in ("hits", "raw", "build"))
    late_rev = rlog.pin_state(first, _cut(good, "rev"), now) == "drifted"
    no_rev = rlog.pin_state(first, {**good, "at": {**good["at"], "rev": None}}, now) == "current"
    # The lie this shape exists to stop: a fingerprint the *pin* measured (asof None) can hold
    # today's bytes exactly and still say nothing about what the recorded round was played on.
    minted = rlog.pin_state(first, {**good, "at": {**good["at"], "asof": None}}, now)

    print(f"v1 -> v2: fields kept={moved}, whole file tidied={tidied} "
          f"({len(pins)} entries), migrated entry reads unrecorded={unrec}")
    print(f"verdict: today's bytes=current({cur}), each field broken=drifted({teeth}), "
          f"revision moved=drifted({late_rev}), revision never recorded=current({no_rev}), "
          f"pin-minted bytes={minted!r}")
    ok = moved and tidied and unrec and cur and teeth and late_rev and no_rev
    ok = ok and minted == "unrecorded"
    print("SHAPES " + ("PASS" if ok else "FAIL"))
    return ok


def ties():
    """A tie for the best round goes to the newest one -- an AP pin is not frozen at its first.

    Two rounds with the same count used to keep the *older*, and since 0 is the floor that meant an
    ALL PERFECT pin could never move onto a round that measured its own inputs: the one thing the
    v2 pin exists to carry. 2026-10-02 it left four pins sitting on pre-fingerprint rounds while
    newer measured ones were already in the log, and it would have left every future AP frozen the
    same way. Three rows tell the two rules apart -- 1, then 0, then 0+指纹 -- and the assertion
    names the third: first-wins picks the second, newest-wins the third.
    """
    tmp = tempfile.mkdtemp(prefix="pintie_")
    cid = sorted(fc.read_pins())[0]                       # a real chart, so nothing has to be faked
    rows = [
        {"ts": "01-01 00:00", "tag": "t_old", "rc": 0, "chart": cid, "non_perfect": 1},
        {"ts": "01-02 00:00", "tag": "t_mid", "rc": 0, "chart": cid, "non_perfect": 0},
        {"ts": "01-03 00:00", "tag": "t_new", "rc": 0, "chart": cid, "non_perfect": 0,
         "at": {"hits": "a" * 16, "raw": "b" * 16, "build": "c" * 16, "rev": None,
                "cfg": {"eff": 45.0}}},
    ]
    names = ("VALIDATED", "RESULTS", "HISTORY_FULL", "PINS", "PINS_INDEX", "RELEARN",
             "RELEARN_INDEX")
    old = {n: getattr(fc, n) for n in names}
    fc.VALIDATED = f"{tmp}/validated.json"
    fc.HISTORY_FULL = fc.RESULTS = f"{tmp}/results.jsonl"
    fc.PINS, fc.PINS_INDEX = f"{tmp}/pins", f"{tmp}/pins/INDEX.json"
    fc.RELEARN, fc.RELEARN_INDEX = f"{tmp}/_relearn", f"{tmp}/_relearn.json"
    try:
        rlog.write_records(fc.HISTORY_FULL, rows, cap=100)
        with contextlib.redirect_stdout(io.StringIO()):
            fc.pin_current()
        e = fc.read_pins()[cid]
    finally:
        for n, v in old.items():
            setattr(fc, n, v)
        shutil.rmtree(tmp, ignore_errors=True)
    ok = (e["best"]["tag"] == "t_new" and e["best"]["np"] == 0
          and e["at"].get("asof") == "flight" and e["at"].get("hits") == "a" * 16)
    print(f"三行日志（np1 → np0 → np0+指纹）钉到的是 {e['best']['tag']}（np={e['best']['np']}，"
          f"asof={e['at'].get('asof')}）—— 取最新一局: {ok}")
    return ok


def never_worse():
    """A worse log row may not overwrite a better pin.

    0062_03 (唱) had ALL PERFECT ×3 recorded and its pin read np=20 @s09 once those rows aged out
    of the 100-round log; 0053_03 the same. The stored entry -- tag, count, and the fingerprint of
    the bytes that round flew on -- is the only thing left that remembers, so `pin_current` now
    keeps it whenever the log only offers something worse. This probe hands it exactly that: a
    pin on file at np=0, a log whose best for the chart is np=7.
    """
    tmp = tempfile.mkdtemp(prefix="pinworse_")
    cid = sorted(fc.read_pins())[0]                       # a real chart, so nothing has to be faked
    rlog.write_json(f"{tmp}/validated.json", {"schema": 2, "updated": "probe", "charts": {cid: {
        "best": {"np": 0, "tag": "t_ap", "score": 9, "ts": "01-01 00:00"},
        "at": {"hits": "d" * 16, "raw": None, "build": None, "rev": None, "cfg": None,
               "asof": None}}}})
    names = ("VALIDATED", "RESULTS", "HISTORY_FULL", "PINS", "PINS_INDEX", "RELEARN",
             "RELEARN_INDEX")
    old = {n: getattr(fc, n) for n in names}
    fc.VALIDATED = f"{tmp}/validated.json"
    fc.HISTORY_FULL = fc.RESULTS = f"{tmp}/results.jsonl"
    fc.PINS, fc.PINS_INDEX = f"{tmp}/pins", f"{tmp}/pins/INDEX.json"
    fc.RELEARN, fc.RELEARN_INDEX = f"{tmp}/_relearn", f"{tmp}/_relearn.json"
    try:
        rlog.write_records(fc.HISTORY_FULL, [
            {"ts": "01-09 00:00", "tag": "t_worse", "rc": 0, "chart": cid, "non_perfect": 7}],
            cap=100)
        with contextlib.redirect_stdout(io.StringIO()):
            fc.pin_current()
        e = fc.read_pins()[cid]
    finally:
        for n, v in old.items():
            setattr(fc, n, v)
        shutil.rmtree(tmp, ignore_errors=True)
    ok = (e["best"]["tag"] == "t_ap" and e["best"]["np"] == 0
          and e["at"].get("hits") == "d" * 16)
    print(f"日志里只剩 np=7 的一局，钉子保住的是 {e['best']['tag']}（np={e['best']['np']}，"
          f"字节指纹 {str(e['at'].get('hits'))[:8]}…）—— 不许变差: {ok}")
    return ok


def index_reload():
    """封面索引必须跟着 npz 一起更新 —— 库在读者活着的时候被重建过一次（用户 m28348）。

    `fetch_charts.py` 每轮扫完都会刷新封面库，而 Flet 面板是**长寿命进程**、在进程内读
    楽曲選択 页。2026-10-16 用户就在面板活着的时候更新了库：面板缓存里那份 88 首的老矩阵
    把新歌封面读成 0.3945，远低于 `MIN_SCORE` 0.80 ⇒ 一个正正好是选曲页的画面答回
    「不是选曲页」。`load_index` 现在每次调用都对账 npz 的 (mtime_ns, size)。
    """
    import inspect
    import textwrap
    import numpy as np
    import gameread
    tmp = tempfile.mkdtemp(prefix="indexreload_")
    idx = f"{tmp}/jackets.npz"
    feat = gameread.FEAT * gameread.FEAT
    keep = (gameread.INDEX, gameread._index_cache, gameread._index_stamp)
    try:
        def write(ids):
            np.savez_compressed(idx, ids=np.array(ids, dtype="<U12"),
                                feat=np.zeros((len(ids), feat), dtype=np.float32))

        gameread.INDEX, gameread._index_cache, gameread._index_stamp = idx, None, None
        write(["1", "2"])
        first = list(gameread.load_index()[0])
        write(["1", "2", "100113"])
        second = list(gameread.load_index()[0])

        # 牙：把 stamp 那一句抠掉，同样两次读会答出同一份老矩阵（这正是面板当时的样子）。
        mutant = textwrap.dedent(inspect.getsource(gameread.load_index)).replace(
            "if _index_cache is None or stamp != _index_stamp:", "if _index_cache is None:")
        ns = dict(gameread.__dict__)
        exec(mutant, ns)                                    # noqa: S102 - probe-side mutant
        write(["1", "2"])
        ns["_index_cache"], ns["_index_stamp"] = None, None
        m1 = list(ns["load_index"]()[0])
        write(["1", "2", "100113"])
        m2 = list(ns["load_index"]()[0])
    finally:
        gameread.INDEX, gameread._index_cache, gameread._index_stamp = keep
        shutil.rmtree(tmp, ignore_errors=True)
    fresh = first == ["1", "2"] and second == ["1", "2", "100113"]
    stale = m1 == ["1", "2"] and m2 == ["1", "2"]
    print(f"库重建后重读：{first} → {second}（要 3 首）={fresh}；"
          f"牙（抠掉 stamp 那一句）：{m1} → {m2}（要停在 2 首）={stale}")
    return fresh and stale


def main():
    base = untouched()
    tmp = tempfile.mkdtemp(prefix="chartpin_")
    try:
        build_lib(tmp)
        before = sha(f"{tmp}/{PINNED}.hits.json")

        a = run(tmp, ["fetch_charts.py", "--force"])
        held = sha(f"{tmp}/{PINNED}.hits.json") == before
        moved = json.load(open(f"{tmp}/{LOOSE}.hits.json", encoding="utf-8")) != []
        said = "原样放回" in a
        # The two halves of the new answer: the bytes that were there came back, and the compiler's
        # opinion was kept rather than thrown away.
        cand = os.path.join(tmp, "_relearn", f"{PINNED}.hits.json")
        parked = os.path.exists(cand) and sha(cand) != before
        shown = "共 1 张" in run(tmp, ["fetch_charts.py", "--relearn"])

        b = run(tmp, ["fetch_charts.py", "--force", "--recompile", PINNED])
        escaped = sha(f"{tmp}/{PINNED}.hits.json") != before
        warned = "点名重编" in b

        print(f"--force alone:        pinned bytes back={held}  candidate parked={parked}  "
              f"reported={said}  --relearn lists it={shown}")
        print(f"--force --recompile:  pinned rewritten={escaped}  accepted warned={warned}")
        print(f"                      unpinned rewritten={moved}")
        lived = cumulative()
        print(f"--pin survives a trimmed log, and archives every restorable chart: {lived}")
        tied = ties()
        kept_best = never_worse()
        shaped = shapes()
        reloaded = index_reload()
        still = untouched()
        leaked = [k for k, v in base.items() if still[k] != v]
        print(f"real library touched by the probe: {leaked or 'nothing'}")
        ok = (held and moved and said and escaped and warned and lived and shaped and tied
              and kept_best and parked and shown and reloaded and not leaked)
        print("CHARTPIN " + ("PASS" if ok else "FAIL"))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
