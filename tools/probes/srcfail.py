"""Offline regression for the two directory sources: who gets asked, when, and what a failure means.

`tools/sources.py` and the early return in `tools/check_upstream.py` make one promise to each side
and one to the user, and all four are about requests, not bytes:

  * a quiet day costs haneoka.org **nothing** -- MoeNotes' tables on GitHub say nothing moved;
  * their CDN sees at most one 4.8 MB tarball a day, judged by the copy already on disk;
  * past that day the archive gets a conditional request, and a 304 keeps the cached catalog;
  * when either source stops answering, the check degrades instead of dying -- and never pretends
    to have compared chart bytes, because only the archive has a path to download from.

None of that can be tested by going out: it is all about *not* going out. So every request in here
is a recorded fake, and the cache is a temp directory seeded with copies of the real tarball and
catalog -- the library under research/charts/ is read but never written, and the real _sources/
state and mtimes are left alone.

Usage: python tools/probes/srcfail.py       (exit 0 = PASS)
"""
import contextlib
import email.message
import io
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:                                    # the same guard run.py has: these paths print Chinese
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001 - a pipe that refuses is not a failure
    pass

import check_upstream as cu                                                     # noqa: E402
import sources                                                                  # noqa: E402

REAL_TARBALL = os.path.join(sources.SOURCES, "moenotes-masterdata.tar.gz")
REAL_CATALOG = os.path.join(sources.SOURCES, "haneoka-songs.json")
DEAD = sources.DAY * 2          # an mtime past the day bound: the cache has to go out again


class NoNet(Exception):
    """Raised by the fake reader when a part is supposed to make zero requests."""


def seed(tmp):
    """A copy of the real cache, so the probe parses real data without touching real state."""
    shutil.copyfile(REAL_TARBALL, os.path.join(tmp, "moenotes-masterdata.tar.gz"))
    shutil.copyfile(REAL_CATALOG, os.path.join(tmp, "haneoka-songs.json"))
    with open(os.path.join(tmp, "state.json"), "w", encoding="utf-8") as f:
        json.dump({"haneoka": {"etag": 'W/"seeded"', "release": "r-seeded"}}, f)


@contextlib.contextmanager
def sandbox(handler):
    """Point `sources` at the temp cache with `sources._read` replaced by a call-recording fake."""
    tmp = tempfile.mkdtemp(prefix="srcfail_")
    real = (sources.SOURCES, sources.STATE, sources.TARBALL, sources._read)
    calls = []
    seed(tmp)
    sources.SOURCES = tmp
    sources.STATE = os.path.join(tmp, "state.json")
    sources.TARBALL = os.path.join(tmp, "moenotes-masterdata.tar.gz")

    def fake(url, headers=None, timeout=60):
        calls.append((url, headers or {}))
        return handler(url, headers or {})

    sources._read = fake
    try:
        yield calls
    finally:
        (sources.SOURCES, sources.STATE, sources.TARBALL, sources._read) = real
        shutil.rmtree(tmp, ignore_errors=True)


def stale(path):
    os.utime(path, (time.time() - DEAD, time.time() - DEAD))


def fresh(path):
    now = time.time()
    os.utime(path, (now, now))


def ok(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  -- {detail}" if detail else ""))
    return bool(cond)


# --------------------------------------------------------------------------------------------- parts

def part1():
    """The quiet day: MoeNotes matches the library, so the archive is never contacted at all."""

    def die(url, headers):
        raise NoNet(f"a request went out to {url[:60]}")

    with sandbox(die) as calls:
        fresh(sources.TARBALL)
        # Make the archive's cache look past its day: if anything about the early return were
        # lazy, this is where it would quietly go out and buy a catalog nobody needed.
        stale(os.path.join(sources.SOURCES, "haneoka-songs.json"))
        p = sources.plan(preferred="moenotes")
        quiet = (ok("第二源答话，archive 一次都没被问", not calls and not p["look"],
                    f"look={p['look']} 请求数={len(calls)}")
                 and ok("报告说清了为什么", "缺 0" in " ".join(p["notes"]), p["notes"][0]))
        # Teeth: hide one chart from the library and the same path has to want to go look.
        real_cids = sources._library_cids
        hidden = sorted(real_cids())[0]
        sources._library_cids = lambda: {k: v for k, v in real_cids().items() if k != hidden}
        try:
            wanted = sources.plan(preferred="moenotes")
            teeth = ok(f"把 {hidden} 藏出库里 -> 它得说“要去看”，但仍然不出门",
                       wanted["look"] and not calls
                       and hidden in " ".join(wanted["notes"]),
                       " | ".join(wanted["notes"]))
        finally:
            sources._library_cids = real_cids
        return quiet and teeth


def part2():
    """One tarball a day, judged by the copy on disk -- and `force` still overrules it."""
    blob = open(REAL_TARBALL, "rb").read()

    def serve(url, headers):
        return blob, {"ETag": 'W/"tarball"'}

    with sandbox(serve) as calls:
        stale(sources.TARBALL)
        n1 = len(calls)
        sources.moenotes()
        n2 = len(calls)
        sources.moenotes()
        n3 = len(calls)
        bound = ok("过期的副本下去一次，日内第二次不出门", n1 == 0 and n2 == 1 and n3 == 1,
                   f"{n1}->{n2}->{n3}")
        sources.moenotes(force=True)
        teeth = ok("force 仍然真的去（上限是文件的 mtime，不是内存里的字典）", len(calls) == 2,
                   f"calls={len(calls)}")
        fresh(sources.TARBALL)                     # a copy that got here by hand is equally usable
        n4 = len(calls)
        sources.moenotes()
        return bound and teeth and ok("手工放好的副本不会被再下一遍", len(calls) == n4)


def part3():
    """首选源挂了：降级去问 archive，并把降级说给用户听。"""

    def down(url, headers):
        if url.startswith(sources.HANEOKA):
            return json.load(open(REAL_CATALOG, encoding="utf-8")), {}
        raise urllib.error.URLError("github unreachable")

    with sandbox(down) as calls:
        # The copy on disk has to look past its day, or nothing would go out and there would be no
        # failure to fall over on: a stale local mirror is deliberately not trusted as "no change",
        # because that is the two-hour blind spot the second source exists to remove.
        stale(sources.TARBALL)
        stale(os.path.join(sources.SOURCES, "haneoka-songs.json"))
        p = sources.plan(preferred="moenotes")
        fell = (ok("首选没答话 -> 改问 archive", p["look"] and p["source"] == "haneoka",
                   f"look={p['look']} source={p['source']}")
                and ok("降级是写出来的，不是偷偷的", "没拿到" in " ".join(p["notes"]), p["notes"][0])
                and ok("过期的第二源副本不会被当成“没变化”", not p["moenotes"],
                       f"moenotes={p['moenotes']}"))
        # Teeth: the panel's other setting must not touch GitHub at all (count from here on --
        # the first plan above already paid for its own failed attempt).
        n = len(calls)
        only = sources.plan(preferred="haneoka")
        return fell and ok("首选=archive 时不碰第二源",
                           only["look"] and only["source"] == "haneoka" and len(calls) == n,
                           f"新请求={len(calls) - n}")


def run_check(argv, handler_state):
    """Drive check_upstream.main() with the archive dead: capture what it prints and reports."""
    report = os.path.join(sources.SOURCES, "report.json")
    cu.REPORT = report
    buf = io.StringIO()
    argv_real = sys.argv
    sys.argv = argv
    try:
        with contextlib.redirect_stdout(buf):
            cu.main()
    finally:
        sys.argv = argv_real
    handler_state["report"] = json.load(open(report, encoding="utf-8"))
    handler_state["text"] = buf.getvalue()
    return handler_state


def part4():
    """archive 挂了：目录照样比完，字节比对明确拒绝，一个下载都不发。"""
    real_haneoka, real_get = sources.haneoka, cu.get
    downloads = []

    def dead(*a, **k):
        raise urllib.error.URLError("haneoka.org refused")

    def no_get(url, *a, **k):
        downloads.append(url)
        raise AssertionError(f"--verify tried to download {url}")

    def handler(url, headers):
        raise NoNet(f"part 4 must be offline, {url[:60]}")

    sources.haneoka, cu.get = dead, no_get
    state = {}
    try:
        with sandbox(handler) as calls:
            fresh(sources.TARBALL)
            run_check(["check_upstream.py", "--source=haneoka"], state)
            rep, text = state["report"], state["text"]
            # The count is read off the catalog, not written down: upstream added four songs on
            # 2026-10-03 (344 -> 348) and a literal here turned that into a red probe.
            live_n = len(cu.catalog_index(json.load(open(REAL_CATALOG, encoding="utf-8"))))
            kept = (ok(f"目录照样比完：{live_n} 张、无差",
                       rep["new"] == [] and rep["gone"] == [] and rep["fields_changed"] == {}
                       and f"{live_n} charts" in text,
                       f"new={len(rep['new'])} gone={len(rep['gone'])} 字段={len(rep['fields_changed'])}"
                       f"（目录 {live_n} 张）")
                    and ok("报告承认这次没问过 archive", rep["asked_archive"] is False,
                           " | ".join(rep["evidence"])))
            # Teeth: doctor the second source so one chart looks revised. Without the from_archive
            # guard the byte loop would reach for a download path the master tables do not have.
            real_moenotes = sources.moenotes

            def doctored(force=False):
                mn = real_moenotes(force=force)
                cid = sorted(mn["charts"])[0]
                mn["charts"][cid] = dict(mn["charts"][cid],
                                         noteCount=(mn["charts"][cid]["noteCount"] or 0) + 1)
                return mn

            sources.moenotes = doctored
            try:
                run_check(["check_upstream.py", "--source=haneoka", "--verify"], state)
            finally:
                sources.moenotes = real_moenotes
            rep2 = state["report"]
            teeth = (ok("改动确实被点名（守卫不是靠空清单蒙过去的）",
                        len(rep2["fields_changed"]) == 1, str(rep2["fields_changed"]))
                     and ok("但它拒绝下载：没有路径就没有字节比对",
                            not downloads and rep2["failed"] == []
                            and "跳过逐张比对" in state["text"],
                            f"下载尝试={len(downloads)}"))
            return kept and teeth
    finally:
        sources.haneoka, cu.get = real_haneoka, real_get


def part5():
    """The claim `moenotes_index` rests on: their level is our level, half step and all.

    It was the other way round until 2026-10-03: the archive published integers and MoeNotes kept
    the .5, so the fallback floored to match. The archive started publishing x.5 that day (53 of
    348, and our own manifest has them), which turned the flooring into the odd one out -- 20
    against everyone's 20.5, and the panel's update check would call all 53 "changed".
    """

    def die(url, headers):
        raise NoNet(f"part 5 must be offline, {url[:60]}")

    with sandbox(die):
        mn = sources.moenotes()
        live = cu.catalog_index(json.load(open(REAL_CATALOG, encoding="utf-8")))
        fb = cu.moenotes_index(mn["charts"], cu.local_index())
        lv = [c for c in live if c in fb and fb[c]["level"] != live[c]["level"]]
        nc = [c for c in live if c in fb and fb[c]["noteCount"] != live[c]["noteCount"]]
        agree = set(fb) == set(live) and not lv and not nc
        # Teeth, in the direction that now matters: floor the fallback again and the agreement must
        # break on exactly the charts whose level carries a half step.
        def floored(cid):
            v = mn["charts"].get(cid) or {}
            s = v.get("sortLevel")
            return int(s) if isinstance(s, (int, float)) else v.get("level")

        halves = [c for c in live if c in mn["charts"] and floored(c) != live[c]["level"]]
        return (ok("两张目录的 cid、等级、判定物数全等", agree,
                   f"{len(live)} vs {len(fb)} 张，等级差 {len(lv)}，判定物差 {len(nc)}")
                and ok("半级必须原样保留（floor 回去就要出错）", len(halves) > 0,
                       f"floor 之后会有 {len(halves)} 张对不上"))


def part6():
    """The conditional request: a 304 keeps the cached catalog and restarts its day; a 5xx does not."""
    catalog = open(REAL_CATALOG, "rb").read()
    cached = json.loads(catalog)

    def not_modified(url, headers):
        assert headers.get("If-None-Match") == 'W/"seeded"', f"no ETag offered: {headers}"
        hdr = email.message.Message()
        hdr["X-Haneoka-Release-Id"] = "r-still-the-same"
        raise urllib.error.HTTPError(url, 304, "Not Modified", hdr, None)

    with sandbox(not_modified) as calls:
        cat = os.path.join(sources.SOURCES, "haneoka-songs.json")
        stale(cat)
        r = sources.haneoka()
        kept = (ok("304 用回缓存目录", r["reused"] == "304" and r["songs"] == cached,
                    f"reused={r['reused']}"))
        kept &= ok("问的方式是带 ETag 的条件请求",
                   len(calls) == 1 and calls[0][1].get("If-None-Match") == 'W/"seeded"')
        kept &= ok("304 之后缓存的“今天”重新开始", os.path.getmtime(cat) > time.time() - 60)
        before = len(calls)
        again = sources.haneoka()
        kept &= ok("所以一次日内不会为同一份目录问第二遍",
                   len(calls) == before and again["reused"] == "cache")

    def service_unavailable(url, headers):
        raise urllib.error.HTTPError(url, 503, "Service Unavailable", email.message.Message(), None)

    with sandbox(service_unavailable) as calls:
        stale(os.path.join(sources.SOURCES, "haneoka-songs.json"))
        try:
            sources.haneoka()
            five = ok("5xx 不会被当成 304 悄悄复用", False, "it returned normally")
        except urllib.error.HTTPError as e:
            five = ok("5xx 照实抛给调用方（然后由 part 4 的路径降级）", e.code == 503)
    return kept and five


def part7():
    """`fetch_charts.get` retries what is worth retrying, and only that.

    2026-10-04: 過去を喰らう hard came back `<urlopen error _ssl.c:1015: The handshake operation
    timed out>` while the same song's expert downloaded fine seconds later -- and with one try the
    chart was simply missing. The manifest still listed it (it mirrors the catalog), so the library
    looked complete, and the only way back was a second 联网更新 nobody had a reason to run. The
    contract now: transient failures are retried with a growing wait, the whole thing is bounded,
    and an HTTP error is the archive answering -- asked once, raised as-is.
    """
    import urllib.error
    import fetch_charts as fc

    class Resp:
        headers = {}

        def __init__(self, blob):
            self._blob = blob

        def read(self):
            return self._blob

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    tries, sleeps = [], []
    real_open, real_sleep = fc.urllib.request.urlopen, fc.time.sleep
    try:
        fc.time.sleep = lambda s: sleeps.append(s)

        def flaky(url, timeout=None):
            tries.append(url)
            if len(tries) < 3:
                raise urllib.error.URLError("_ssl.c:1015: The handshake operation timed out")
            return Resp(b'{"ok": 1}')

        fc.urllib.request.urlopen = flaky
        got = fc.get("https://example.invalid/chart")
        recovered = ok("两次超时之后第三次拿到", got == b'{"ok": 1}' and len(tries) == 3,
                       f"尝试 {len(tries)} 次，等待 {sleeps}")

        tries.clear()
        sleeps.clear()

        def dead(url, timeout=None):
            tries.append(url)
            raise urllib.error.URLError("handshake timed out")

        fc.urllib.request.urlopen = dead
        raised = False
        try:
            fc.get("https://example.invalid/chart")
        except urllib.error.URLError:
            raised = True
        bounded = ok("一直失败就按次数收手", raised and len(tries) == 3,
                     f"尝试 {len(tries)} 次，等待 {sleeps}")

        # Tooth: the single-try behaviour this replaced loses exactly that chart.
        tries.clear()
        fc.urllib.request.urlopen = flaky
        lost = False
        try:
            fc.get("https://example.invalid/chart", tries=1)
        except urllib.error.URLError:
            lost = True
        tooth = ok("只试一次就会丢（这就是要修的形状）", lost and len(tries) == 1,
                   f"尝试 {len(tries)} 次")

        tries.clear()

        def not_found(url, timeout=None):
            tries.append(url)
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

        fc.urllib.request.urlopen = not_found
        how = None
        try:
            fc.get("https://example.invalid/gone")
        except urllib.error.HTTPError as e:
            how = e.code
        once = ok("404 只问一次就抛（存档答了就是答了）", how == 404 and len(tries) == 1,
                  f"尝试 {len(tries)} 次，code {how}")
    finally:
        fc.urllib.request.urlopen, fc.time.sleep = real_open, real_sleep
    return recovered and bounded and tooth and once


def main():
    if not (os.path.exists(REAL_TARBALL) and os.path.exists(REAL_CATALOG)):
        print("srcfail SKIP: 需要真缓存 research/charts/_sources/ "
              "（先跑一次 python tools/sources.py --moenotes）")
        return 0
    parts = [("1 安静的一天：archive 一次都不被问", part1),
             ("2 tarball 的一日上限，force 仍然出门", part2),
             ("3 首选源挂了 -> 降级问 archive", part3),
             ("4 archive 挂了 -> 目录仍比、字节比对拒绝装样子", part4),
             ("5 降级目录与 archive 目录本来就相等", part5),
             ("6 条件请求：304 复用缓存并重启这一天", part6),
             ("7 下载重试：瞬时的会重试、有界的收手、404 只问一次", part7)]
    failed = []
    for name, fn in parts:
        print(f"\n--- PART {name} ---")
        try:
            if not fn():
                failed.append(name)
        except Exception as e:                                    # noqa: BLE001 - a crash is a FAIL
            print(f"  FAIL {name} -- {type(e).__name__}: {e}")
            failed.append(name)
    print("\n" + ("srcfail PASS: 两个源的礼貌与降级都按承诺" if not failed
                  else f"srcfail FAIL: {len(failed)} part(s) -- " + "; ".join(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
