"""Two channels for one run: what the panel shows live, and what forensics needs later.

The pipeline grew its log line by line over a hundred runs, so by now a single Symbol II round
prints 150 lines of which ~40 are worth watching (which page the walk is on, whether the clock
locked, how the firing loop is doing, what the result was) and the rest is per-sample detail that
only matters when a run misbehaves. This module splits them without touching the call sites:
every existing ``log("...")`` keeps working, and the line itself decides where it goes.

The default is stdout, on purpose. A line nobody classified still shows up -- hiding an unknown
line is how a new failure mode becomes invisible, and the whole reason this exists is that a
misleading log line cost a healthy run on 2026-09-30.

Two rendering tables drive it:

``QUIET``   patterns whose detail belongs in ``research/<tag>.detail.log`` only,
``RENDER``  patterns rewritten from the builder's terse English into the Chinese status line the
            panel shows, so the field names (``p50``, ``ms``, ``corr``) stay greppable while the
            prose reads in the same language as the rest of the panel.

Lines that start with ``!!`` are warnings and never quiet, whatever else they match.

``#STATUS#`` lines are the machine channel to the panel (``tools/flet_gui.py``): it drives the phase label and the
progress bar from them instead of scraping English prose, so rewording a status line can no
longer break the panel. They carry no timestamp prefix, and neither does ``RESULT``, which the
panel parses for the record row -- the two machine lines stay at column 0 forever.

The module also owns the other log: ``append_record`` is the single writer of
``research/results.jsonl``, the round history both the panel and a shell round append to, kept to
the newest ``HISTORY_CAP`` rounds, and ``flown`` is the one question anyone else ever asks of it.

And it owns the *shape* of the two things a round leaves behind: ``fingerprint`` is what the fired
bytes were built from (recorded with the result, so a claim can be dated), and ``pin_entry`` /
``pin_state`` are ``validated.json``'s current shape and its "is this still about today's inputs"
verdict. Readers get those instead of indexing the file themselves -- the pin has had two shapes
already, and a shape each reader guesses on its own is a shape nobody can change.

Where those files live is decided here, once. Every path below is anchored to this file's own
directory, never to the working directory: a pin read as ``research/charts/validated.json`` resolves
to nothing at all when the command is typed from elsewhere, and "nothing at all" is exactly what
``--force`` needs in order to sweep the flown geometry it was supposed to protect.
"""

import hashlib
import json
import os
import re
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH = os.path.join(ROOT, "research")
# Three buckets, so the working dump stops being one heap of a few thousand loose files:
#   runs/    per-round text and machine data -- <tag>.out, <tag>.detail.log, dets_, relock_
#   frames/  every debug or forensic still that is not a result page -- hud_, hudreject_, now_, ...
#   result/  what the panel shows: result_, failed_  (no split_ since 2026-10-11: the FAST/SLOW
#            read is debug-only and stays in memory)
# The small live-state files (results.jsonl, chain_cal.json, gui_state.json, digit_templates.json)
# stay at the top: they are tracked, they are few, and moving them would move the pin's evidence too.
RUNS = os.path.join(RESEARCH, "runs")
FRAMES = os.path.join(RESEARCH, "frames")
RESULT = os.path.join(RESEARCH, "result")
DETAIL_DIR = RUNS
CHARTS = os.path.join(RESEARCH, "charts")


def subdir(path):
    """A bucket under research/, created the first time something writes into it."""
    os.makedirs(path, exist_ok=True)
    return path

MANIFEST = os.path.join(CHARTS, "manifest.json")
VALIDATED = os.path.join(CHARTS, "validated.json")
RESULTS = os.path.join(RESEARCH, "results.jsonl")
# The same rows, never trimmed. results.jsonl is capped at HISTORY_CAP because the panel shows it,
# and a display window was being used as the record: 186 rounds' RESULT lines are still readable out
# of research/runs/, and the pin had to carry a `carried` special case to remember what the window
# forgot. This file is the answer to "what has this chart ever done"; the window stays the panel's.
HISTORY_FULL = os.path.join(RESEARCH, "results_full.jsonl")
CHAIN_CAL = os.path.join(RESEARCH, "chain_cal.json")


def retarget(research):
    """Point every path this module derives at another research/ tree -- for fixtures and probes.

    One function on purpose: `DETAIL_DIR` is derived from `RUNS` *at import*, so a harness that
    reassigned the four obvious names still had `RunLog` write its round logs into the user's
    `research/runs/` -- which is exactly what the recoverwalk probe did on 2026-10-03, minutes after
    the same class of bug (a cached path surviving a retarget) had been fixed in `gui`. Whoever
    moves the corpus moves all of it.
    """
    global RESEARCH, RUNS, FRAMES, RESULT, DETAIL_DIR, CHARTS, MANIFEST, VALIDATED, RESULTS
    global HISTORY_FULL, CHAIN_CAL
    RESEARCH = research
    RUNS = os.path.join(research, "runs")
    FRAMES = os.path.join(research, "frames")
    RESULT = os.path.join(research, "result")
    DETAIL_DIR = RUNS
    CHARTS = os.path.join(research, "charts")
    MANIFEST = os.path.join(CHARTS, "manifest.json")
    VALIDATED = os.path.join(CHARTS, "validated.json")
    RESULTS = os.path.join(research, "results.jsonl")
    HISTORY_FULL = os.path.join(research, "results_full.jsonl")
    CHAIN_CAL = os.path.join(research, "chain_cal.json")

# evidence/ is the committed half of this tree's memory (see tools/evidence.py): it survives a fresh
# clone, research/ does not. The pin's byte snapshots live there for the same reason the regression
# frames do -- a flown geometry that exists on one disk is a result that can be silently invalidated.
EVIDENCE = os.path.join(ROOT, "evidence")
PINS = os.path.join(EVIDENCE, "pins")
PINS_INDEX = os.path.join(PINS, "INDEX.json")
# The relearn queue's candidate bytes: compiled, never flown, and deliberately *not* committed --
# they are one `--force` away from being regenerable, unlike the flown bytes above.
RELEARN = os.path.join(CHARTS, "_relearn")
RELEARN_INDEX = os.path.join(CHARTS, "_relearn.json")

# Verbose by design: the per-sample chatter of the anchor vote, the capture banners, the fired
# action dumps. Each of these was worth reading on the run that introduced it.
QUIET = [
    r"^  minitouch: ",
    r"^fast capture: ",
    r"^  relock: (judgement lines back|voting the field|no lock|only )",
    r"^  \d+ blobs at \+\d+\.\d+s: ",
    r"^relock blobs -> ",
    r"^restart anchor: \S+ [\d.]+ \+ ",
    r"^  重试 确定 pressed at host ",
    r"^restart anchor: t0=[\d.]+ given, ",
    r"^  drift probe at chart ",
    r"^  live re-anchor: voted [+-]\d\.\d+s .*(deadband|已封)",
    r"^  hud watch: \d+ rows changed at once ",
    r"^  fired \d+ press",
    r"^  intro (press|shotgun): ",
    r"^  \d+ fired actions -> ",
    r"^  vote blobs -> ",
    r"^  drift probes: \d+ frames during play",
    r"^    (first|second) half: ",
    r"^  screen: \S+ \(x\d+\)$",
    r"^  screen: loading$",
    r"^  unreadable screen \(\d/8\)$",
    r"^  anchor attempt \d+ failed, restarting$",
    # mumucap's native library prints its connection banner on stdout at process exit, in the
    # middle of whoever is reading the log. Nothing else writes these three.
    r"^(product|nemu_connect|connect not same day)",
]

# The pages calib.py's walk recognises, in the words the panel uses for them.
NAV = {"pause": "游戏已暂停", "confirm": "确认重试", "live": "已进入 LIVE",
       "livehome": "LIVE 主页", "select": "乐曲选择页", "band": "乐队确认页",
       "result": "结算页", "exp": "演出结果页", "loading": "加载中",
       "rewards": "达成奖励列表", "story": "故事解锁", "purchase": "购买确认",
       "shop": "商店", "rankup": "排名上升", "options": "选项页", "finish": "曲终",
       "home": "主页", "other": "未识别页面", "failed": "演出失败"}


def _nav():
    return lambda m: f"导航：{NAV.get(m.group(1), m.group(1))}"


# (compiled pattern, renderer). The renderer gets the match and returns the Chinese line, or None
# to fall through to printing the original.
RENDER = [
    (re.compile(r"^chain cal: (-?\d+) ms on file \(([^)]*)\) - effective offset (\d+) ms "
                r"\(nominal \+(\d+)\)"),
     lambda m: f"链路校准：文件里 {m.group(1)} ms（{m.group(2)}）→ 有效偏移 +{m.group(3)} ms"
               f"（名义 +{m.group(4)}）"),
    (re.compile(r"^  screen: (\w+)"), _nav()),
    (re.compile(r"^  four (?:watches|taps) with no change on (\w+) -> (.*)"),
     lambda m: f"导航：{NAV.get(m.group(1), m.group(1))}连续四次读不到变化 → {m.group(2)}"),
    (re.compile(r"^LIVE field at host ([\d.]+)"),
     lambda m: f"已进入 LIVE（字段 {m.group(1)}）"),
    (re.compile(r"^  relock: locked t0 ([\d.]+) = 確定 \+ ([\d.]+)s "
                r"\(([+-]\d+) ms vs press\+delta\), (\d+) blobs"),
     lambda m: f"锚定：重锁成功 t0={m.group(1)}（確定 +{m.group(2)}s，"
               f"比 press+delta {m.group(3)} ms，{m.group(4)} 票）"),
    (re.compile(r"^  relock did not lock \(attempt (\d+)/(\d+)\)"),
     lambda m: f"锚定 {m.group(1)}/{m.group(2)}：重锁未达成 → 重新开始这一局"),
    (re.compile(r"^  relock never locked - playing on the field stamp instead: "
                r"t0 = t_field \+ (\d\.\d+) = ([\d.]+)"),
     lambda m: f"锚定：三轮都没锁上 → 退回字段戳 t0={m.group(2)}（t_field+{m.group(1)}s）"),
    (re.compile(r"^fire t0=([\d.]+) \(offset ([+-]\d+) ms\)"),
     lambda m: f"开打：t0={m.group(1)}，偏移 {m.group(2)} ms"),
    (re.compile(r"^(\d+) notes -> (\d+) actions on (\d+) slots"),
     lambda m: f"谱面：{m.group(1)} 音符 → {m.group(2)} 动作 / {m.group(3)} 指位"),
    (re.compile(r"^  live re-anchor: two votes agree -> correction ([+-]\d+) ms "
                r"on the remaining presses \((\d+) votes from (\d+) blobs\)"),
     lambda m: f"实时修正 {m.group(1)} ms（{m.group(2)} 票 / {m.group(3)} blob）"),
    (re.compile(r"^  live re-anchor: two votes agree on ([+-]\d+) ms, but ([+-]\d+) ms is past "
                r"the trusted drift \((\d+) ms\) -> refused \((\d+) votes from (\d+) blobs\)"),
     lambda m: f"实时修正：两票都指向 {m.group(1)} ms，但 {m.group(2)} ms 超出可信漂移 "
               f"±{m.group(3)} ms —— 不采（{m.group(4)} 票 / {m.group(5)} blob）"),
    (re.compile(r"^  live re-anchor: vote wanted ([+-]\d+) ms of push, capped at \+(\d+) ms"),
     lambda m: f"实时修正：正推 {m.group(1)} ms 已限到 +{m.group(2)} ms"),
    (re.compile(r"^  hud: (\w+) #(\d+) at host \[([\d.]+), ([\d.]+)\]( 第 (\d+) 个判定物)? -> (.*)"),
     lambda m: (f"HUD 计数器变化 {m.group(1)} 第 {m.group(2)} 次 @host {m.group(3)}"
                + (f"，全局第 {m.group(6)} 个判定物" if m.group(6) else "")
                + f" → {m.group(7)}")),
    (re.compile(r"^  fire (\d+)/(\d+) @chart ([+-][\d.]+)s\s+late p50\s+([+-][\d.]+) "
                r"max\s+([+-][\d.]+) ms\s+vote\s+([+-]\d+) ms corr\s+([+-]\d+) ms\s+"
                r"cmd \+(\d+) echo \+(\d+) dev\s+\+(\d+) ms\s+respawns (\d+)"),
     lambda m: (f"演奏 {m.group(1)}/{m.group(2)} @曲内 {m.group(3)}s"
                f"，迟到 p50 {m.group(4)} max {m.group(5)} ms"
                f"，漂移 {m.group(6)} ms 修正 {m.group(7)} ms"
                f"，回显 {m.group(9)}/{m.group(8)} 断连 {m.group(11)}")),
    (re.compile(r"^fired (\d+)/(\d+) actions, (\d+) injector respawns"),
     lambda m: f"注入完成 {m.group(1)}/{m.group(2)}（通道断连 {m.group(3)} 次）"),
    (re.compile(r"^  live re-anchor: (\d+) correction\(s\) applied, final ([+-]\d+) ms"
                r"(?:, (\d+) refused as aliases)?"),
     lambda m: f"实时修正：本局共 {m.group(1)} 次，末值 {m.group(2)} ms"
               + (f"，另有 {m.group(3)} 次越界不采" if m.group(3) else "")),
    (re.compile(r"^schedule error: min ([\d.]+) p50 ([\d.]+) p99 ([\d.]+) max ([\d.]+) ms"),
     lambda m: f"调度误差：min {m.group(1)} p50 {m.group(2)} p99 {m.group(3)} max {m.group(4)} ms"),
    (re.compile(r"^  hud tally: (.*) - (.*)$"),
     lambda m: f"HUD 计数器（总数仍以结果页为准）：{m.group(1)}（{m.group(2)}）"),
    (re.compile(r"^  result page -> (.*)"), lambda m: f"结算页 → {m.group(1)}"),
    (re.compile(r"^  FAST/SLOW split -> (.*)"), lambda m: f"FAST/SLOW 分布 → {m.group(1)}"),
    (re.compile(r"^  tapping through the LIVE FINISH splash"),
     lambda m: "曲终：穿过 LIVE FINISH"),
    (re.compile(r"^  closing the (.*) the game opened over the result"),
     lambda m: f"关闭盖在结算页上的：{m.group(1)}"),
    (re.compile(r"^chain cal: judged (-?\d+) ms -> correction (-?\d+) -> (-?\d+) ms "
                r"\(tag \S+; next run fires at \+(\d+) on the nominal \+(\d+)\)"),
     lambda m: f"链路校准回写：判读 {m.group(1)} ms → 修正 {m.group(3)} ms"
               f"（下一跑有效 +{m.group(4)}，名义 +{m.group(5)}）"),
    (re.compile(r"^random pick: (.*)"), lambda m: f"随机选曲：{m.group(1)}"),
    (re.compile(r"^t0 in ([\d.]+)s"), lambda m: f"倒计时 {m.group(1)} 秒后开打"),
]

QUIET_C = [re.compile(p) for p in QUIET]

# What the panel's status label should read after a line like this. Kept separate from RENDER so a
# status line can be reworded without touching what the panel shows.
PHASES = [
    (re.compile(r"^  screen: (\w+)"), lambda m: NAV.get(m.group(1), f"导航：{m.group(1)}")),
    (re.compile(r"^  relock did not lock"), lambda m: "锚定中（重锁未达成）"),
    (re.compile(r"^  relock: locked t0|^fire t0="), lambda m: "时钟已锁定，即将开打"),
    (re.compile(r"^  fire \d+/\d+ @chart"), lambda m: "演奏中"),
    (re.compile(r"^fired \d+/\d+ actions"), lambda m: "演奏结束，等待结算"),
    (re.compile(r"^  result page -> "), lambda m: "结算页，读取判定"),
    (re.compile(r"^random pick: (.*)"), lambda m: f"随机选曲：{m.group(1)}"),
    (re.compile(r"^t0 in ([\d.]+)s"), lambda m: f"倒计时 {m.group(1)} 秒后开打"),
]

DRIFT = re.compile(r"^  drift probe at chart \+([\d.]+)s")

# Both writers of the result log go through append_record, so the cap is one number in one place.
HISTORY_CAP = 100


def atomic_write(path, data, binary=False):
    """Replace `path` with `data` in one step: unique temp in the same directory, then os.replace.

    Every writer of a file that cannot be regenerated should come through here. The failure this
    closes is not exotic: `json.dump(x, open(path, "w"))` truncates the destination first, so a
    power cut, a 强制终止 or an exception inside the dump leaves a half-written file, and the next
    reader treats "exists" as "valid" -- `fetch_charts` skipped any chart whose `.hits.json` was
    present, and `gui_state`'s reader returns `{}` for an unparseable file, which resets the tag
    counter. Two details are load-bearing and were both measured:

    * The temp name is unique (`tempfile.mkstemp`), not `f"{path}.tmp"`. A fixed name makes two
      concurrent writers share one buffer -- they interleave into the same file and both replace
      with a mixture -- and on Windows `os.replace` onto the *other* writer's live temp raises.
    * If a reader holds the destination open, Windows refuses the rename with
      `PermissionError [WinError 5]` (measured on this machine). That refusal is *persistent* while
      the handle lives, so a retry only rides out a reader that closes on its own; the readers here
      (`read_records`, `read_json`, the user opening the file) are exactly that. A caller that must
      not lose data anyway is the log's job, not this helper's -- see `append_record`.
    """
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb" if binary else "w",
                       **({} if binary else {"encoding": "utf-8", "newline": "\n"})) as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())        # the bytes are on the platter before anything replaces
        last = None
        for k in range(6):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as e:    # a reader (or AV) is holding the destination
                last = e
                time.sleep(0.05 * (k + 1))
        raise last
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_records(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f.read().splitlines() if ln.strip()]
    except FileNotFoundError:
        return []


def write_records(path, recs, cap=HISTORY_CAP):
    """Rewrite the whole log, keeping only the newest `cap` rounds.

    A rewrite rather than an append because the cap drops from the front. Through `atomic_write`,
    so a crash mid-write cannot leave the log half-written and two writers cannot share a temp.
    """
    atomic_write(path, "\n".join(json.dumps(r, ensure_ascii=False) for r in recs[-cap:]) + "\n")


def append_record(path, rec, cap=HISTORY_CAP):
    """Append one round to research/results.jsonl, and to the untrimmed history.

    Read-modify-write is not atomic against a second writer, but there are only two (the panel and
    a shell round), and the panel sets OURNOTES_PANEL so the child it spawns never writes at all.
    The history is a plain append: nothing ever rewrites it, so the worst a crash can do there is
    lose the round that was in flight.

    A round is *recorded*, not best-effort: a finished LIVE is minutes of the user's account and it
    cannot be re-derived, so losing its row to a rename the OS refused is the wrong trade. When the
    atomic rewrite cannot land (something is holding `path` open), fall back to a plain append:
    an append does not need to replace anything, so it succeeds where the rename did not, at the
    cost of the row count briefly exceeding `cap`. The window is a display convenience and the cap
    is re-applied on the next successful rewrite.
    """
    try:
        write_records(path, read_records(path) + [rec], cap)
    except OSError as e:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"!! results: 整体重写没成功（{e!r}），改为直接追加一行；"
              f"这一行不会丢，但滚动上限要等下一次成功重写才收回", flush=True)
    if path == RESULTS:
        seed_full()          # so the window's existing rows are not lost to the first append
        with open(HISTORY_FULL, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def seed_full():
    """Start the untrimmed history from whatever the window still holds, once, if it is not there.

    Deliberately not a backfill from `research/runs/*.out` -- `backfill_log.py` does that with a
    chart identification it trusts, and running it is a visible decision rather than a side effect
    of importing this file.
    """
    if not os.path.exists(HISTORY_FULL):
        write_records(HISTORY_FULL, read_records(RESULTS), cap=10 ** 9)
    return HISTORY_FULL


def flown(path=None):
    """chart id -> best graded outcome recorded for it: (non_perfect, tag).

    This is the question the pin and the audit both ask, and it is asked of the result log, so it
    lives with the log's reader rather than with one of its reports. A row with ``rc`` set never
    finished, so it is not an outcome; neither is one whose judgement counts could not be read.
    """
    return {c: (r["non_perfect"], r.get("tag", "")) for c, r in flown_records(path).items()}


def flown_records(path=None):
    """chart id -> the whole best record, for callers that need more of a round than its count.

    ``flown`` is the tuple, and the pin needs the round's own fingerprint and score, so the record
    is what is actually kept here. The choice rule is fewest non-PERFECT, and **the newest round
    wins a tie** -- the log is chronological, so the last row that is at least as good is the one
    kept. A tie used to keep the *oldest*, which quietly froze every ALL PERFECT pin at its first
    round: 0 is the floor, ``<`` never replaces it, so re-flying an AP chart could never put a
    round that measured its own inputs into the pin. That is the one thing the v2 pin exists to
    carry (2026-10-02: four pins were sitting on pre-fingerprint rounds with newer measured ones
    already in the log). Defaults to the untrimmed history; pass ``RESULTS`` for the panel window.
    """
    out = {}
    for r in read_records(path or HISTORY_FULL):
        c = r.get("chart")
        if not c or r.get("rc") or r.get("non_perfect") is None:
            continue
        cur = out.get(c)
        if cur is None or r["non_perfect"] <= cur["non_perfect"]:
            out[c] = r
    return out


# ---------------- the pin's shape, and what a result was flown on ----------------

SOURCES = os.path.join(CHARTS, "_sources", "state.json")
COMPILER = os.path.join(ROOT, "tools", "compile.py")


def sha16_bytes(data):
    """Fingerprint of bytes that are already in memory, in the same 16 hex digits as ``sha16``.

    One definition of "the fingerprint of these bytes", because a restore has to prove the copy it
    is writing back is the generation the pin named, and a second hasher would be a second opinion.
    """
    return hashlib.sha256(data).hexdigest()[:16]


def sha16(path):
    """Fingerprint of a file's bytes, or None when the file is not there.

    16 hex digits is what validated.json has always stored. The question is "did these bytes
    change", asked against a few hundred files by nobody in a hurry -- not a contest.
    """
    try:
        with open(path, "rb") as f:
            return sha16_bytes(f.read())
    except OSError:
        return None


def source_rev():
    """The revision the fetcher's own caches say they are at: {haneoka, moenotes}, missing -> None.

    Tolerant by design, unlike ``read_json``: this is metadata about a round that just finished, and
    an unreadable revision file must not be the reason a result page goes unrecorded. Unknown is
    written as None, which ``pin_state`` reads as "cannot tell" -- never as "unchanged".
    """
    try:
        st = read_json(SOURCES) or {}
    except (OSError, ValueError, TypeError):
        return {}
    return {k: (st.get(k) or {}).get("release") or (st.get(k) or {}).get("version")
            for k in ("haneoka", "moenotes")}


def fingerprint(cid, hits_path=None):
    """What the bytes this round fires are built from: the chart, its raw input, the compiler, the
    upstream revision.

    Recorded *alongside the result* (run.py puts it in the record), so a pin can state which inputs
    a result was flown on instead of asserting today's and hoping nothing moved in between. A None
    field means that input was not there to be measured -- not that it was the same.
    """
    rev = source_rev()
    return {"hits": sha16(hits_path or os.path.join(CHARTS, f"{cid}.hits.json")),
            "raw": sha16(os.path.join(CHARTS, f"{cid}.raw.json")),
            "build": sha16(COMPILER),
            "rev": rev.get("haneoka")}


PIN_SCHEMA = 2


def pin_entry(e):
    """One ``validated.json`` record in the current shape: ``{"best": {...}, "at": {...}}``.

    The v1 shape was ``{np, tag, sha}``. Migrating on read rather than with a one-shot script is
    the honest option here because the pin is *cumulative*: an entry whose chart is never re-flown
    would otherwise keep the old shape forever, and every reader would carry two branches. Nothing
    is invented on the way through -- a field v1 never carried stays None, which is what "we do not
    know" reads as downstream.
    """
    if not isinstance(e, dict):
        return {"best": {}, "at": {}}
    if "best" in e or "at" in e:
        return {"best": dict(e.get("best") or {}), "at": dict(e.get("at") or {})}
    return {"best": {"np": e.get("np"), "tag": e.get("tag"),
                     "score": e.get("score"), "ts": e.get("ts")},
            "at": {"hits": e.get("sha"), "raw": None, "build": None, "rev": None,
                   "cfg": None, "asof": None}}


def pin_state(cid, e, now=None):
    """Is this pin's claim still about the inputs on disk: 'current', 'drifted' or 'unrecorded'?

    'drifted' is not an error and not a veto. It says the recorded result no longer predicts the
    bytes here now, which means a relearn round is the thing that would answer it -- the shape the
    user asked for on 2026-10-02 (a pin is a measurement with a date on it, not a forbidden change).

    Only a fingerprint the round itself recorded can answer the question, so ``at.asof`` has to say
    ``"flight"``. A pin written from an older round has no measurement of that round's inputs, and
    minting one from today's disk would let the audit report "same generation as today" about bytes
    the result was never played on -- the exact lie this whole field exists to avoid. Such entries
    are 'unrecorded', whatever their bytes happen to look like.

    The strategy numbers in ``at.cfg`` are deliberately *not* part of the verdict: the correction
    moves by design, almost every round, so folding it in would mark the whole library stale once
    a day and the word would stop meaning anything. It stays in the record as context -- the score
    says which recipe the round was played on, which is the thing to compare when a relearn happens.
    """
    at = pin_entry(e)["at"]
    if at.get("asof") != "flight":
        return "unrecorded"
    if not at.get("hits") or not at.get("raw") or not at.get("build"):
        return "unrecorded"
    now = now or fingerprint(cid)
    if any(now.get(k) != at.get(k) for k in ("hits", "raw", "build")):
        return "drifted"
    if at.get("rev") and now.get("rev") != at.get("rev"):
        return "drifted"
    return "current"


def read_pins(path=None):
    """The pin list, every entry in the current shape, or {} when it has never been written.

    A file that exists but does not parse is allowed to raise: treating a corrupt pin as "nothing
    is protected" is the one failure mode this guard must not have.

    Lives here rather than in fetch_charts, which used to own it, because readers are not only the
    sweep: the panel shows what the pin says about the library and `audit_charts`/`check_upstream`
    ask the same question, and a v1 record has to migrate in exactly one place.
    """
    return {cid: pin_entry(e) for cid, e in
            ((read_json(path or VALIDATED) or {}).get("charts") or {}).items()}


def read_json(path):
    """Read a small research/ state file (manifest.json, validated.json, a report).

    A missing file is None -- the caller decides whether that means "never fetched" or "start
    empty". A file that exists but does not parse raises: for the pin, guessing "no pins" off a
    half-written file would hand --force an unguarded sweep.
    """
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    """Write one of those files atomically, so a crash mid-write cannot corrupt it."""
    atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def write_json_file(path, obj, indent=None):
    """`atomic_write` for the JSON blobs that are not small research state: indent=None is compact.

    `write_json` above is the pretty one the research/*.json files have always used; this exists so
    the chart compilers do not have to re-implement (or forget) the temp+replace themselves.
    """
    atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=indent) + "\n")


def stamp(msg):
    """`HH:MM:SS ` + the line, with the line's own indent dropped: one column, one gap, always.

    The runner indents a sub-line by two spaces to say "this belongs to the one above", and that
    depth landed *after* the clock -- so the text started at two different columns and the log read
    as ragged (asked twice on 2026-10-03: 多空两格, then 还是多空一格，我要的是对齐). The hierarchy is
    carried by colour now (the panel's dim level is exactly those process lines), so the indent is
    spent on nothing but a ragged left edge. It stays in the strings themselves: rlog's own filters
    and the detail file's callers still see `  fire ...`, only the column is normalised here.
    """
    return f"{time.strftime('%H:%M:%S')} {msg.lstrip()}"


class RunLog:
    def __init__(self, tag="run", quiet=False):
        self.tag = tag
        self.quiet = quiet
        self.song_len = None
        self._detail_path = os.path.join(DETAIL_DIR, f"{tag}.detail.log")
        self._detail = None
        self._nav = None
        self._phase = None

    # -- channels ---------------------------------------------------------------

    def detail(self, msg):
        """Write to the detail file only. Safe to call before the first summary line."""
        self._open().write(stamp(msg) + "\n")

    def __call__(self, msg):
        msg = str(msg)
        if msg.startswith("#") or msg.startswith("RESULT "):
            # Machine lines: verbatim, at column 0, no stamp -- the panel parses them.
            print(msg, flush=True)
            self.detail(msg)
            return
        status = []
        d = DRIFT.match(msg)
        if d and self.song_len:
            # The probe fires every couple of seconds through the song, which makes it the natural
            # thing to hang the progress bar on -- and it is a quiet line, so take the number here
            # before the line is filed away.
            status.append(("progress", round(min(1.0, float(d.group(1)) / self.song_len), 3)))
        quiet = any(p.match(msg) for p in QUIET_C) and "!!" not in msg
        if not quiet:
            line = msg
            for pat, render in RENDER:
                m = pat.match(msg)
                if m:
                    # The walk prints one line per page it reads; a stall on the same page is not
                    # worth a line each time, so repeats collapse until the page actually changes.
                    if msg.startswith("  screen: "):
                        s = m.group(1)
                        if s == self._nav:
                            self.detail(msg)
                            return
                        self._nav = s
                    line = render(m) or line
                    break
            print(stamp(line), flush=True)
            for pat, phase in PHASES:
                m = pat.match(msg)
                if m:
                    p = phase(m)
                    if p and p != self._phase:
                        self._phase = p
                        status.append(("phase", p))
                    break
        if not self.quiet:
            self.detail(msg)
        for k, v in status:
            self.status(**{k: v})

    def status(self, phase=None, progress=None, **extra):
        """The machine channel to the panel. Absent fields mean 'unchanged'.

        Fields are ; separated because a phase string is Chinese prose and can contain spaces
        (已进入 LIVE); the panel splits on ; and takes each token up to its first =.

        `phase` and `progress` are the two the panel has always known; anything else is passed
        through as ``key=value`` and lands on the panel's 「本局」readings strip (`corr`,
        `late`, `actions`, `left` from `player.play`). Values must stay free of ``;`` and ``=``
        — they are formatted numbers and short tokens, not prose.
        """
        if phase is None and progress is None and not extra:
            return
        parts = [f"{k}={v}" for k, v in (("phase", phase), ("progress", progress))
                 if v is not None]
        parts += [f"{k}={v}" for k, v in extra.items() if v is not None]
        self.__call__("#STATUS# " + ";".join(parts))

    def _open(self):
        if self._detail is None:
            os.makedirs(DETAIL_DIR, exist_ok=True)
            self._detail = open(self._detail_path, "w", encoding="utf-8", buffering=1)
        return self._detail

    def close(self):
        if self._detail is not None:
            self._detail.close()
            self._detail = None
