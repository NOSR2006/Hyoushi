"""A round that gives up must still put the game back on 乐曲選択.

Two consecutive failures stop the panel's queue, so a failure that *leaves* the game somewhere odd
does not cost one round -- it costs the night. That is not hypothetical: g274 abandoned a LIVE with
the game sitting on 达成奖励列表, and g275 then died reading that same page ("连续四次读不到变化")
without playing a note. The walk that fixes it already existed; it just only ran on the happy path
(`if not args.stay_on_result:` at the end of the round), and every early exit -- no LIVE found, a
restart that could not be walked out of, a re-lock that never locked -- returned past it.

PART 1: an abandoned round still walks home: the recorder sees the entry walk (stop_at_select=False)
        and then a second walk with `stop_at_select=True`. Same script, `--stay-on-result` must
        leave it at one call.
PART 2: the tooth -- the same script with `run.WALK_HOME_ON_ANY_EXIT` turned off must show only
        the entry walk, because that is the bug this probe exists for. (The first version loaded
        HEAD's run.py from git instead; committing the fix turned that counterfactual into a copy
        of the fix, so the guarantee is a named constant the probe can switch off.)
PART 3: the walk is what carries the machine line the panel's 演出间隔 counts from: `#ATSELECT#`
        appears in the round log when the walk reports success, and does not when it fails.
PART 4: the fire gate's wiring -- `--min-fire N` has to reach `start_live`, and the walk home must
        *not* carry it (that trip has no band-confirm page to wait on). The stand-in for
        `start_live` is what caught this going unwired: it did not sign `min_fire` at all, so the
        probe died with a TypeError the moment run.py started passing the flag. Default 0 = the
        command line from before the gate existed, byte for byte.
PART 5: the same lesson one keyword later, for the 多人 chain: the walk home has to be handed
        `multi` (both walks, in fact), because on the 多人 结算 page that button may re-queue a
        match instead of going home -- `calib`'s `exp` branch watches that layout. The stand-in
        signs `multi`/`on_prep`/`grabber` for the same reason PART 4 signs `min_fire`.
PART 6: the 房间 LIVE has no pause button (2026-10-10, the user's own account: once the match is
        made the only way out is killing the game, otherwise the round has to be played to the 结算
        page). Both places that used to 重试/暂停 a live are solo-only now -- the no-pick path (a
        LIVE reached with no chart) and `_to_t0`'s opening anchor, which used to spend two taps on
        the top-right corner at the start of *every* 多人 round. The drive below reaches a LIVE
        with no chart on purpose, the one path that can still touch that corner: a 多人 round must
        send nothing, and the same round without `--multi` must still 重试 + 暂停, byte for byte.
        The tooth compiles run.py with the `args.multi` fork replaced by `if False:` -- the same
        多人 drive then has to call `restart_to_t0` again.

No device, no emulator, no frames: `MTouch` and `start_live` are replaced, and every path run.py
writes is pointed at a temp fixture (the chart pair is copied, the originals are only read).

Run from the repo root:  python tools/probes/recoverwalk.py
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)


class _NoSleep:
    """`time` with `sleep()` neutered.

    The give-up path polls the page for up to three minutes (`for _ in range(60): time.sleep(3)`),
    and PART 6 drives it three times; the poll itself is stubbed out, so waiting for it is pointless.
    """

    def __getattr__(self, name):
        return getattr(time, name)

    @staticmethod
    def sleep(_seconds):
        pass


def _fixture(root):
    """A research/ tree with one real chart pair and nothing else run.py needs a device for."""
    for d in ("charts", "runs", "frames", "result"):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    src = os.path.join(ROOT, "research", "charts")
    pair = None
    for f in sorted(os.listdir(src)):
        if f.endswith(".hits.json") and os.path.exists(os.path.join(src, f.replace(".hits", ".raw"))):
            pair = f
            break
    if pair is None:
        raise SystemExit("no compiled chart pair in research/charts -- nothing to drive run.py with")
    cid = pair.replace(".hits.json", "")
    for ext in (".hits.json", ".raw.json"):
        shutil.copyfile(os.path.join(src, cid + ext), os.path.join(root, "charts", cid + ext))
    open(os.path.join(root, "results.jsonl"), "w", encoding="utf-8").close()
    json.dump({"corr_ms": 0.0, "updated": "fixture", "history": []},
              open(os.path.join(root, "chain_cal.json"), "w", encoding="utf-8"))
    return os.path.join("research", "charts", cid + ".hits.json")


def _load(name, path):
    """Import a module from an explicit path, so two copies of run.py can stand side by side."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_src(name, src, path):
    """Import run.py from *source text* while keeping `__file__` at the real path.

    PART 6's tooth compiles a mutated run.py. Writing the mutant to a temp directory would move
    `__file__` (and therefore the `tools` directory run.py puts on `sys.path`) into that directory;
    compiling in place keeps every path run.py computes identical to the shipped file.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = path
    sys.modules[name] = mod
    exec(compile(src, path, "exec"), mod.__dict__)
    return mod


def _drive(source, fixture, hits_rel, tag, extra=(), walk=True, fires=None, multis=None,
           reach_live=False, restarts=None, pauses=None, src=None, modname=None):
    """Run one round: device and walk replaced. `walk=False` is the pre-fix shape. Returns (rc, calls).

    `fires` (a list, optional) collects the `min_fire` each `start_live` call was handed.
    `multis` (a list, optional) collects the `multi` flag each call was handed -- the walk home of a
    多人 round has to be handed it too, or it walks home with the solo tap policy.
    `reach_live=True` makes the stand-in report a LIVE (with no chart), which is the one path that
    can still reach the pause corner; `restarts`/`pauses` (lists, optional) collect every call to
    `restart_to_t0`/`pause_if_live`. `src` (optional) is run.py's text with edits, compiled at
    `source`'s path -- that is how the PART 6 tooth switches the guard off without touching the repo.
    """
    import rlog
    # One call, because a cached path surviving a retarget is how this probe first wrote its round
    # logs into the user's own research/runs/ (`rlog.retarget` moves every path for that reason).
    rlog.retarget(fixture)

    name = modname or ("run_probe_" + os.path.basename(source))
    mod = _load_src(name, src, source) if src is not None else _load(name, source)
    calls = []
    seen_fire = []
    seen_multi = []
    seen_restart = []
    seen_pause = []

    class FakeInj:
        respawns = 0

        def __init__(self, log=None):
            pass

        def probe(self):
            pass

        def close(self):
            pass

    # The stand-in has to sign every keyword `run.py` hands `start_live` -- `min_fire` (2026-10-06)
    # and `multi`/`on_prep` (the 多人 chain) each cost a probe failure by not being signed here.
    def fake_start(inj, log=print, timeout=150.0, on_select=None, stop_at_select=False,
                   min_fire=0, grabber=None, multi=False, on_prep=None):
        calls.append(bool(stop_at_select))
        seen_fire.append(int(min_fire))
        seen_multi.append(bool(multi))
        return reach_live               # False: nothing on this machine can reach a LIVE

    # The two functions that reach for the pause corner need a device, so they are stand-ins here as
    # well -- and both record, because PART 6 is about who is allowed to call them.
    def fake_restart(inj, log=print, rounds=8):
        seen_restart.append(True)
        return None                     # a restart that does not go through: the give-up shape

    def fake_pause(inj, log=print):
        seen_pause.append(True)

    mod.MTouch = FakeInj
    mod.start_live = fake_start
    mod.restart_to_t0 = fake_restart
    mod.pause_if_live = fake_pause
    mod.page = lambda: "result"         # the give-up path polls the page; no frames on this machine
    mod.time = _NoSleep()               # ... and that poll waits 3 s a turn
    mod.WALK_HOME_ON_ANY_EXIT = walk
    argv = [hits_rel] + list(extra) + ["--tag", tag]
    old = sys.argv
    sys.argv = ["run.py"] + argv
    try:
        rc = mod.main()
    finally:
        sys.argv = old
    if fires is not None:
        fires.extend(seen_fire)
    if multis is not None:
        multis.extend(seen_multi)
    if restarts is not None:
        restarts.extend(seen_restart)
    if pauses is not None:
        pauses.extend(seen_pause)
    return rc, calls


def main():
    fixture = tempfile.mkdtemp(prefix="recoverwalk-")
    hits_rel = _fixture(fixture)
    here = os.path.join(TOOLS, "run.py")
    bad = []

    # PART 1 -- the guard on: the give-up path walks home.
    rc, calls = _drive(here, fixture, hits_rel, "rwnew")
    print(f"新版：rc={rc} 走动调用 {calls}（False=进 LIVE 的走查，True=走回选曲页）")
    ok1 = rc == 1 and calls == [False, True]
    if not ok1:
        bad.append(f"放弃的局没有走回选曲页：调用序列 {calls}")

    # ... and the flag still means what it says.
    rc2, calls2 = _drive(here, fixture, hits_rel, "rwstay", extra=["--stay-on-result"])
    print(f"新版 + --stay-on-result：rc={rc2} 走动调用 {calls2}")
    ok2 = rc2 == 1 and calls2 == [False]
    if not ok2:
        bad.append(f"--stay-on-result 仍然走了：{calls2}")

    # PART 2 -- the tooth: with the guarantee switched off, the abandoned round does not walk
    # home at all (the shape that left g274's game on 达成奖励列表).
    rc3, calls3 = _drive(here, fixture, hits_rel, "rwold", walk=False)
    print(f"守护关掉（WALK_HOME_ON_ANY_EXIT=False）：rc={rc3} 走动调用 {calls3}")
    tooth = rc3 == 1 and calls3 == [False]
    if not tooth:
        bad.append(f"关掉守卫竟然还走回选曲页（{calls3}）-- 这一关看不见要修的东西")
    print("PART 1 " + ("PASS" if ok1 and ok2 else "FAIL") +
          "   PART 2 " + ("PASS" if tooth else "FAIL"))

    # PART 3 -- the machine line the panel counts 演出间隔 from.
    f1 = os.path.join(fixture, "runs", "rwnew.detail.log")
    f2 = os.path.join(fixture, "runs", "rwold.detail.log")
    log1 = open(f1, encoding="utf-8", errors="replace").read() if os.path.exists(f1) else ""
    log3 = open(f2, encoding="utf-8", errors="replace").read() if os.path.exists(f2) else ""
    # The walk failed in both (the stub says no), so the honest assertion is about the *attempt*:
    # the new log names the failure to get home, the old one never tried.
    tried = "没能走回选曲页" in log1
    never = "没能走回选曲页" not in log3
    print(f"开着守卫时日志里有走回家的尝试（失败也写一行）：{tried}；关掉之后一句都没有：{never}")
    if not tried or not never:
        bad.append("日志对不上：开守卫时 finally 应该尝试过（并写一行），关掉应一句都没有")
    print("PART 3 " + ("PASS" if tried and never else "FAIL"))

    # PART 4 -- 火力门的接线（用户 m13786；语义 2026-10-11 由 m26442 改成「拨档」）：`--min-fire`
    # 只是命令行上的一个数，真正要走到 `start_live` 里才有用（从前那道闸没接，探针的替身也签不出
    # `min_fire`，于是这一关自己先 TypeError —— 这一关是那次漏接的牙）。默认 0 = 门关着、命令行一个
    # 字不变；给了 3 就是 3；而**走回选曲页那一次调用必须不带门**（那一趟没有乐队确认页可以拨档）。
    fires = []
    rc4, calls4 = _drive(here, fixture, hits_rel, "rwfire", extra=["--min-fire", "3"],
                         fires=fires)
    print(f"新版 + --min-fire 3：rc={rc4} 进 LIVE 那次拿到 {fires[:1]}、走回家那次拿到 {fires[1:]}"
          f"（默认 0 = 门关着；走回家那趟不许带门）")
    ok4 = fires == [3, 0] and calls4 == [False, True]
    if not ok4:
        bad.append(f"火力门没接到 start_live：每次调用拿到的 min_fire = {fires}")
    print("PART 4 " + ("PASS" if ok4 else "FAIL"))

    # PART 5 -- 多人局的家要用多人的走法回（用户 m00001 的多人链路）。`leave_at_select` 只有拿到
    # `multi` 才会在结算页上观望而不是按「再次演出」；多人结算页那一按可能把一局没人打的匹配排起来。
    # 两次走动都要拿到 `--multi` 说的那个值：带上就是 True，不带就是 False。
    multis = []
    rc5, calls5 = _drive(here, fixture, hits_rel, "rwmulti", extra=["--multi"], multis=multis)
    solo = []
    rc5b, _calls5b = _drive(here, fixture, hits_rel, "rwsolo", multis=solo)
    print(f"新版 + --multi：rc={rc5} 两次走动拿到的 multi = {multis}（都要 True）；"
          f"不带 --multi 的同一局 = {solo}（都要 False）")
    ok5 = rc5 == 1 and calls5 == [False, True] and multis == [True, True] and solo == [False, False]
    if not ok5:
        bad.append(f"multi 没走到 start_live：带 --multi {multis}、不带 {solo}")
    print("PART 5 " + ("PASS" if ok5 else "FAIL"))

    # PART 6 -- 房间里没有暂停按钮（2026-10-10 用户 m13106：匹配完毕那一刻唯一的提前退出是关掉
    # 游戏进程）。从前两条路都会去按右上角那个角：no-pick 那条（走到 LIVE 却没有谱面）与
    # `_to_t0` 的开局锚。这里把「走到 LIVE 却没有谱面」那一趟真的驱动一遍 —— 它是唯一还能碰到
    # 暂停角的路径 —— 多人局必须一个字节都不发，同一趟单人局必须照旧重试 + 暂停。
    # 那条路只在「谱面要由走查决定」时才存在（`pick_mode`），所以单人那一半用 `--song`：走查是
    # 替身，谱面永远不会被选出来，于是它同样落到 no-pick。
    def _log_of(tag):
        f = os.path.join(fixture, "runs", tag + ".detail.log")
        return open(f, encoding="utf-8", errors="replace").read() if os.path.exists(f) else ""

    r6, p6 = [], []
    rc6, calls6 = _drive(here, fixture, hits_rel, "rwmulti_nopause", extra=["--multi"],
                         reach_live=True, restarts=r6, pauses=p6)
    quiet = "多人局没有暂停按钮：不重开、不按暂停" in _log_of("rwmulti_nopause")
    ok6 = rc6 == 1 and calls6 == [False, True] and not r6 and not p6 and quiet
    print(f"多人：走到 LIVE 却没有谱面 -- rc={rc6}、重试 {len(r6)} 次、暂停 {len(p6)} 次（都要 0）、"
          f"日志有那一句 {quiet}、还是走回了选曲页 {calls6 == [False, True]} = {ok6}")
    if not ok6:
        bad.append(f"多人局去按了暂停角：重试 {r6}、暂停 {p6}（走动 {calls6}）")

    r7, p7 = [], []
    rc7, _c7 = _drive(here, fixture, hits_rel, "rwsolo_pauses", extra=["--song", "100056:expert"],
                      reach_live=True, restarts=r7, pauses=p7)
    loud = "连重试都走不通，只能把它暂停后放弃" in _log_of("rwsolo_pauses")
    ok7 = rc7 == 1 and len(r7) == 1 and len(p7) == 1 and loud
    print(f"单人（同一趟、谱面同样没选出来）：rc={rc7}、重试 {len(r7)} 次、暂停 {len(p7)} 次（都要 1）、"
          f"日志有那一句 {loud} = {ok7}")
    if not ok7:
        bad.append(f"单人那半没按暂停角：重试 {r7}、暂停 {p7} -- 这一关在量空气")

    # 牙：把 no-pick 那条的 `if args.multi:` 拆成 `if False:`（房间里也去重试），同一份判据必须变红。
    src6 = open(here, encoding="utf-8").read()
    fork = ("                if args.multi:\n"
            "                    # 房间里的 LIVE 没有暂停按钮（2026-10-10 用户 m13106）：")
    if src6.count(fork) != 1:
        bad.append("找不到 no-pick 那条的多人分流 -- 牙的锚点过期了")
        tooth6 = False
    else:
        r8, p8 = [], []
        rc8, _c8 = _drive(here, fixture, hits_rel, "rwtooth_nopause", extra=["--multi"],
                          reach_live=True, restarts=r8, pauses=p8,
                          src=src6.replace(fork, fork.replace("if args.multi:", "if False:")),
                          modname="run_probe_nopause_tooth")
        tooth6 = rc8 == 1 and len(r8) == 1 and len(p8) == 1
        print(f"牙：把多人分流拆掉之后，同一趟又去重试 {len(r8)} 次、暂停 {len(p8)} 次（都要 1）"
              f"= {tooth6}")
        if not tooth6:
            bad.append("拆掉多人分流竟然还是不发 -- 这一关看不见要修的东西")

    # 开局那条路（`_to_t0`）在这里驱动不了（要先有谱面与场地），所以静态钉住它：多人时直接落到
    # 开场投票、一个字节都不发；单人那一半的重试必须还在（否则就是两头都拆了）。
    anchor = ('            if args.multi:\n'
              '                if replay:\n'
              '                    log("  多人局没有暂停按钮，中途重开走不出去 —— 本局放弃，停止注入让它自己跑完")\n'
              '                    return None\n'
              '                log("  多人局：房间里的 LIVE 没有暂停按钮，不做重开，直接走开场投票")\n'
              '                return None, False\n')
    solo_line = "                t_ok = restart_to_t0(inj, log=log)\n"

    def _to_t0_quiet(text):
        return text.count(anchor) == 1 and text.count(solo_line) >= 1

    ok8 = _to_t0_quiet(src6)
    tooth8 = not _to_t0_quiet(src6.replace(anchor, ""))
    print(f"开局锚：多人直接落到开场投票、单人那半还在 {ok8}；"
          f"牙：把那段摘掉之后同一份判据变红 {tooth8} = {ok8 and tooth8}")
    if not (ok8 and tooth8):
        bad.append("_to_t0 的多人分流没钉住（或钉了个空）")
    print("PART 6 " + ("PASS" if ok6 and ok7 and tooth6 and ok8 and tooth8 else "FAIL"))

    for b in bad:
        print("   " + b)
    print("recoverwalk " + ("PASS" if not bad else "FAIL"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
