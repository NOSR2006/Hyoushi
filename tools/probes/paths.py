"""Regression: the eight hard-coded paths live in one place now, and a round refuses without them.

Why this probe exists: the tool grew up on one machine, so adb was hard-coded in five modules,
MuMu's renderer DLL and install root in a sixth, and the minitouch binary in a seventh place --
that is the whole of "发行前要补的" 第 1 条 on the path half. `tools/locate.py` holds them once with
an environment override each, and both entry points validate before a round starts instead of
failing three minutes in as "the walk stalled".

PART 1  the defaults are the historical literals, byte for byte (checked in a child with every
        locate env variable stripped -- both the current `HYOUSHI_*` spelling and the legacy
        `BANG_*` one -- which is the "this machine behaves exactly as before" claim), and
        the six consumers re-export them from locate. The scan that says "no other file carries the
        literal" is itself scanned: a copy of mtouch.py with the literal put back must be flagged.
PART 2  the environment wins: HYOUSHI_ADB / HYOUSHI_MINITOUCH / HYOUSHI_DEVICE move the values,
        HYOUSHI_MUMU_ROOT derives the SDK pair, and HYOUSHI_MUMUCAP_DLL can move the DLL alone.
        `missing()` and `check()` follow. 2026-10-20 (the Bang -> Hyoushi rename): the legacy
        `BANG_` spelling still answers (`env:legacy`) and loses to `HYOUSHI_` when both are set.
        Teeth: `_env` mutated to ignore the environment, the legacy prefix dropped from the
        lookup table, a drifted default, and a mutant whose bundled binary lives elsewhere.
PART 3  the validation is wired into both entry points and runs *before* the flag guards, so a
        hand-written `--retry-anchor` without `--fastcap` still gets its own refusal while a missing
        adb wins over it (both directions run for real, and neither touches the emulator).
        `panel_core.start()` refuses offline with a log line and spawns nothing. Teeth: the check
        line deleted, and the check line moved below the guard.

Run from the repo root:  python tools/probes/paths.py     # exit 0 = PASS
Needs no emulator, no game, no network: everything here is files, environment and two processes.

This probe is called paths.py and not locate.py on purpose (2026-10-09): it inserts `tools/probes`
ahead of `tools` on sys.path, so a probe named locate.py would shadow the module under test and
`import locate` inside detect.py would resolve to the probe -- which is exactly the ImportError this
file was first run into. Any probe named after a tools/ module has the same trap.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
PROBES = TOOLS / "probes"
sys.path.insert(0, str(TOOLS))
# Deliberately *not* putting tools/probes first: a probe sharing a name with a tools/ module would
# then shadow it for every consumer (see the note at the top of this file).

import locate  # noqa: E402

# The historical literals, frozen here on purpose: this is the "nothing moved" expectation, so it
# is written out rather than derived from the module under test.
FROZEN = {
    "ADB_DEFAULT": r"D:\MuMuPlayer\nx_main\adb.exe",
    "DEVICE_DEFAULT": "127.0.0.1:16384",
    # 2026-10-20：默认值不再是一个字面量，而是「随包那份（tools/bin/minitouch）优先，没有才退回这个
    # 历史字面量」。冻结的仍是那个字面量 —— 它必须逐字不动，只是不再是第一顺位。
    "MINITOUCH_LEGACY": r"D:/Downloads/autodori_v1.2.4_Windows_X64/assets/minitouch_EvATive7/x86_64/minitouch",
    "MUMU_ROOT_DEFAULT": r"D:\MuMuPlayer",
    "DLL_PATH": r"D:\MuMuPlayer\nx_main\sdk\external_renderer_ipc.dll",
    "INSTALL_PATH": r"D:\MuMuPlayer",
}
LITERALS = (FROZEN["ADB_DEFAULT"], FROZEN["MINITOUCH_LEGACY"], FROZEN["DLL_PATH"])
# The two files allowed to carry the literals: the module that owns them and this probe (which
# freezes them). One name each -- this probe is paths.py precisely so it cannot shadow locate.py.
ALLOWED = {"locate.py", "paths.py"}
SITE_FILES = ("detect.py", "inject.py", "mtouch.py", "mumucap.py", "panel_core.py",
              "probes/calibrate_map.py")
SITES = {
    "detect": {"ADB": "ADB", "DEVICE": "DEVICE"},
    "inject": {"ADB": "ADB", "DEVICE": "DEVICE"},
    "mtouch": {"ADB": "ADB", "DEVICE": "DEVICE", "LOCAL_BINARY": "MINITOUCH"},
    "mumucap": {"DLL_PATH": "DLL_PATH", "INSTALL_PATH": "INSTALL_PATH"},
    "panel_core": {"ADB": "ADB", "DEVICE": "DEVICE"},
}
BANG_VARS = ("BANG_ADB", "BANG_DEVICE", "BANG_MINITOUCH", "BANG_MUMU_ROOT",
             "BANG_MUMUCAP_DLL", "BANG_MUMUCAP_INSTALL")
# 2026-10-20 项目改名 Bang -> Hyoushi，前缀改 `HYOUSHI_`，旧写法作为回落保留。这一份是**两套都清**，
# 因为「默认值逐字相同」那条判据要求环境里一个都不剩。
ENV_VARS = BANG_VARS + tuple(n.replace("BANG_", "HYOUSHI_", 1) for n in BANG_VARS)

CHILD = r'''
import json
import locate
print("@@@" + json.dumps({
    "const": {k: getattr(locate, k) for k in
              ("ADB_DEFAULT", "DEVICE_DEFAULT", "MINITOUCH_DEFAULT", "MINITOUCH_LEGACY",
               "MINITOUCH_BUNDLED", "MUMU_ROOT_DEFAULT",
               "DLL_PATH", "INSTALL_PATH", "ADB", "DEVICE", "MINITOUCH", "MUMU_ROOT")},
    "source": {k: getattr(locate, k) for k in
               ("ADB_SOURCE", "DEVICE_SOURCE", "MINITOUCH_SOURCE", "DLL_SOURCE",
                "INSTALL_SOURCE")},
    "missing": locate.missing(),
    "check": locate.check(log=lambda s: None),
}, ensure_ascii=False))
'''

PANEL_CHILD = r'''
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["HYOUSHI_PROBE_ROOT"], "tools"))
import panel_core
core = panel_core.RunOrchestrator({"defaults": {}})
ok = core.start(None, "房间抽曲", "expert", 1, False)
lines = []
while not core.q.empty():
    lines.append(str(core.q.get()))
print("@@" + json.dumps({"ok": ok, "busy": core.busy(), "lines": lines}, ensure_ascii=False))
'''


def child_env(extra=None, path=TOOLS):
    """A child environment with every locate env variable removed, then `extra` applied."""
    env = os.environ.copy()
    for name in ENV_VARS:
        env.pop(name, None)
    env["PYTHONPATH"] = str(path)
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra or {})
    return env


def run_child(extra=None, path=TOOLS, script=CHILD, timeout=120):
    p = subprocess.run([sys.executable, "-c", script], cwd=str(ROOT), env=child_env(extra, path),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout)
    tag = "@@@" if script is CHILD else "@@"
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith(tag)), None)
    if line is None:
        raise RuntimeError(f"child printed no verdict (rc={p.returncode})\n{p.stdout}\n{p.stderr}")
    return json.loads(line[len(tag):])


def mutant(replacements):
    """A copy of tools/locate.py with `replacements` applied, in its own directory.

    2026-10-20: the copy carries a `bin/minitouch` too, so a mutant still looks like *this* machine
    (the bundled binary is the default now). Without it every mutant would report minitouch missing
    and the teeth below would be measuring the temp directory instead of the change.
    """
    d = Path(tempfile.mkdtemp(prefix="locate_mut_"))
    src = (TOOLS / "locate.py").read_text(encoding="utf-8")
    for old, new in replacements:
        if old not in src:
            raise RuntimeError(f"mutant anchor not found: {old!r}")
        src = src.replace(old, new, 1)
    (d / "locate.py").write_text(src, encoding="utf-8")
    (d / "bin").mkdir()
    real = TOOLS / "bin" / "minitouch"
    (d / "bin" / "minitouch").write_bytes(real.read_bytes() if real.exists() else b"")
    return d


def literals_in(paths):
    """[(file, literal)] for every scanned file that still carries a hard-coded path."""
    hits = []
    for p in paths:
        if Path(p).name in ALLOWED:
            continue
        txt = Path(p).read_text(encoding="utf-8", errors="replace")
        for lit in LITERALS:
            if lit in txt:
                try:
                    rel = str(Path(p).relative_to(ROOT))
                except ValueError:               # the tooth scans a copy outside the repo
                    rel = str(p)
                hits.append((rel, lit))
    return hits


def missing_with(seq, name):
    """`seq` plus `name`, in the order locate reports them."""
    order = list(locate.SETTINGS)
    return sorted(set(seq) | {name}, key=order.index)


def wired_run(src):
    """run.py validates before the flag guards (the guards' own order is kept)."""
    check = src.find('locate.check(("adb", "minitouch")')
    anchor_guard = src.find("--retry-anchor 需要 --fastcap")
    last_guard = src.find("--random 与 --song 都在乐曲选择页决定谱面")
    return (-1 < check < anchor_guard < last_guard)


def wired_panel(src):
    """panel_core.start() validates inside start(), before it clears the stop flag."""
    a = src.find("    def start(self, chart_id")
    b = src.find("    def stop_graceful(self)")
    if a == -1 or b == -1 or b < a:
        return False
    body = src[a:b]
    check = body.find('locate.check(("adb", "minitouch")')
    return -1 < check < body.find("self.stop_flag.clear()")


def run_cli(extra):
    p = subprocess.run([sys.executable, str(TOOLS / "run.py"), "--tag", "locate_probe",
                        "--retry-anchor"], cwd=str(ROOT), env=child_env(extra),
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=180)
    return p.stdout + p.stderr


def part1(base):
    frozen_ok = all(base["const"][k] == v for k, v in FROZEN.items())
    # 2026-10-20：随包那份（tools/bin/minitouch）在，默认就必须指着它；不在就必须退回历史字面量。
    has_bundled = (TOOLS / "bin" / "minitouch").exists()
    want = base["const"]["MINITOUCH_BUNDLED"] if has_bundled else base["const"]["MINITOUCH_LEGACY"]
    bundled_ok = (base["const"]["MINITOUCH_BUNDLED"] == str(TOOLS / "bin" / "minitouch")
                  and base["const"]["MINITOUCH_DEFAULT"] == want
                  and base["const"]["MINITOUCH"] == want)
    # The invariant, not the machine: check() is exactly "nothing in NEEDED is missing" (the SDK is
    # deliberately not in NEEDED, so a machine without MuMu still starts a round -- see part 2).
    needed_missing = [n for n in base["missing"] if n in locate.NEEDED]
    default_ok = base["check"] == (not needed_missing)

    import importlib
    site_ok = True
    for name, attrs in SITES.items():
        mod = importlib.import_module(name)
        for attr, target in attrs.items():
            if getattr(mod, attr, None) != getattr(locate, target, None):
                site_ok = False
                print(f"   {name}.{attr} = {getattr(mod, attr, None)!r} != locate.{target}")
    calib = importlib.import_module("calibrate_map")
    for attr in ("ADB", "DEVICE"):
        if getattr(calib, attr, None) != getattr(locate, attr):
            site_ok = False
            print(f"   calibrate_map.{attr} = {getattr(calib, attr, None)!r} != locate.{attr}")

    hits = literals_in(sorted(TOOLS.rglob("*.py")))
    scan_ok = not hits
    for where, lit in hits:
        print(f"   还带着写死的路径：{where} -> {lit}")

    wired_ok = all("locate" in (TOOLS / f).read_text(encoding="utf-8")
                   and "from locate import" in (TOOLS / f).read_text(encoding="utf-8")
                   for f in SITE_FILES)

    # 牙：把字面量放回 mtouch.py 的一份副本里，扫描必须看见它、接线判据必须变红。
    # 2026-10-16: the import is parenthesized and multi-line now (locate grew four names), so the
    # whole statement is dropped by pattern rather than one exact line -- a tooth that quietly
    # stops matching is a tooth that stopped biting.
    mut = Path(tempfile.mkdtemp(prefix="locate_site_")) / "mtouch.py"
    txt = (TOOLS / "mtouch.py").read_text(encoding="utf-8")
    txt, hits = re.subn(r"from locate import [^\n]*?(?:\([^)]*\))?\n",
                        lambda m: f'ADB = r"{FROZEN["ADB_DEFAULT"]}"\n', txt, count=1)
    mut.write_text(txt, encoding="utf-8")
    tooth_ok = (hits == 1 and bool(literals_in([mut]))
                and "from locate import" not in mut.read_text(encoding="utf-8"))

    print(f"PART 1  默认值逐字相同 {frozen_ok}、随包那份优先 {bundled_ok}（本机 {has_bundled}）、"
          f"校验就是「NEEDED 里没缺东西」{default_ok}（本机缺失 {base['missing'] or '无'}）、"
          f"六个站点都从 locate 取值 {site_ok}、没有别的文件带写死路径 {scan_ok}、"
          f"六个文件都接了 locate {wired_ok}、牙（副本里的字面量被看见）{tooth_ok}")
    return (frozen_ok and bundled_ok and default_ok and site_ok and scan_ok and wired_ok
            and tooth_ok)


def part2(base):
    moved = run_child({"HYOUSHI_ADB": r"C:\nope\adb.exe", "HYOUSHI_MINITOUCH": r"C:\nope\minitouch",
                       "HYOUSHI_DEVICE": "127.0.0.1:9999", "HYOUSHI_MUMU_ROOT": r"D:\OtherMuMu"})
    c, s = moved["const"], moved["source"]
    moved_ok = (
        c["ADB"] == r"C:\nope\adb.exe" and s["ADB_SOURCE"] == "env"
        and c["DEVICE"] == "127.0.0.1:9999" and s["DEVICE_SOURCE"] == "env"
        and c["MINITOUCH"] == r"C:\nope\minitouch" and s["MINITOUCH_SOURCE"] == "env"
        and c["DLL_PATH"] == r"D:\OtherMuMu\nx_main\sdk\external_renderer_ipc.dll"
        and s["DLL_SOURCE"] == "env:MUMU_ROOT"
        and c["INSTALL_PATH"] == r"D:\OtherMuMu" and s["INSTALL_SOURCE"] == "env:MUMU_ROOT"
        and moved["missing"] == ["adb", "minitouch", "mumucap_dll", "mumucap_install"]
        and moved["check"] is False)

    alone = run_child({"HYOUSHI_MUMUCAP_DLL": r"C:\nope\ipc.dll"})
    alone_ok = (alone["const"]["DLL_PATH"] == r"C:\nope\ipc.dll"
                and alone["source"]["DLL_SOURCE"] == "env"
                and alone["const"]["INSTALL_PATH"] == FROZEN["INSTALL_PATH"]
                and alone["source"]["INSTALL_SOURCE"] == "default"
                and alone["missing"] == missing_with(base["missing"], "mumucap_dll")
                # the SDK is not in NEEDED: losing the DLL changes the verdict by nothing
                and alone["check"] == base["check"])

    # 2026-10-20：前缀改名的两半都要钉住 —— ① 旧的 `BANG_` 仍然生效（用户的旧脚本与旧手柄还在用
    # 这个名字），② 两套同时在场时 `HYOUSHI_` 赢（否则「改名」等于没改，只是多了一个同义词）。
    old_only = run_child({"BANG_ADB": r"C:\nope\adb.exe", "BANG_DEVICE": "127.0.0.1:7777"})
    legacy_ok = (old_only["const"]["ADB"] == r"C:\nope\adb.exe"
                 and old_only["source"]["ADB_SOURCE"] == "env:legacy"
                 and old_only["const"]["DEVICE"] == "127.0.0.1:7777"
                 and old_only["source"]["DEVICE_SOURCE"] == "env:legacy")
    both = run_child({"HYOUSHI_ADB": r"C:\new\adb.exe", "BANG_ADB": r"C:\old\adb.exe"})
    wins_ok = (both["const"]["ADB"] == r"C:\new\adb.exe"
               and both["source"]["ADB_SOURCE"] == "env")

    # 牙：把 _env 改成永远读默认值，同一份环境必须被忽略。
    deaf = mutant([("got = os.environ.get(prefix + name)", "got = None")])
    blind = run_child({"HYOUSHI_ADB": r"C:\nope\adb.exe", "HYOUSHI_MINITOUCH": r"C:\nope\minitouch"},
                      path=deaf)
    tooth_ok = (blind["const"]["ADB"] == FROZEN["ADB_DEFAULT"]
                and blind["source"]["ADB_SOURCE"] == "default"
                and blind["missing"] == [])

    # 牙：把旧前缀从查找表里去掉，`BANG_` 那条回落判据必须变红（证明 `legacy_ok` 测的是回落本身，
    # 而不是「环境变量读法碰巧还能用」）。
    no_legacy = mutant([('(ENV_PREFIX, "env"), (ENV_PREFIX_LEGACY, "env:legacy")',
                         '(ENV_PREFIX, "env"),')])
    deaf_old = run_child({"BANG_ADB": r"C:\nope\adb.exe"}, path=no_legacy)
    legacy_bites = (deaf_old["const"]["ADB"] == FROZEN["ADB_DEFAULT"]
                    and deaf_old["source"]["ADB_SOURCE"] == "default")

    # 牙：默认值本身被改动，PART 1 的那条冻结判据必须变红。
    wrong = mutant([(r'"/x86_64/minitouch")', r'"/x86_64/minitouch_x")')])
    drifted = run_child(path=wrong)
    frozen_bites = drifted["const"]["MINITOUCH_LEGACY"] != FROZEN["MINITOUCH_LEGACY"]

    # 牙：「随包那份」必须看着模块自己所在的目录，不能写死项目路径。把 locate.py 与一份假的
    # bin/minitouch 拷到临时目录，默认值就必须指到那份假的。
    own = Path(tempfile.mkdtemp(prefix="locate_bundled_"))
    (own / "bin").mkdir()
    (own / "bin" / "minitouch").write_bytes(b"")
    (own / "locate.py").write_text((TOOLS / "locate.py").read_text(encoding="utf-8"),
                                   encoding="utf-8")
    moved_default = run_child(path=own)
    bundled_bites = moved_default["const"]["MINITOUCH_DEFAULT"] == str(own / "bin" / "minitouch")

    print(f"PART 2  环境变量优先 {moved_ok}、单独指 DLL {alone_ok}、"
          f"旧前缀 BANG_ 仍生效 {legacy_ok}、两套同时在场 HYOUSHI_ 赢 {wins_ok}、"
          f"牙（忽略环境就读默认值）{tooth_ok}、牙（拆掉回落后旧前缀失效）{legacy_bites}、"
          f"牙（默认值改动会被 PART 1 看见）{frozen_bites}、"
          f"牙（随包那份按模块目录找）{bundled_bites}")
    return (moved_ok and alone_ok and legacy_ok and wins_ok and tooth_ok and legacy_bites
            and frozen_bites and bundled_bites)


def part3():
    run_src = (TOOLS / "run.py").read_text(encoding="utf-8")
    pc_src = (TOOLS / "panel_core.py").read_text(encoding="utf-8")
    wired_ok = wired_run(run_src) and wired_panel(pc_src)

    # 牙：删掉那一段校验、以及把它挪到 flag 守卫之后，接线判据都必须变红。
    check_line = '    if not locate.check(("adb", "minitouch"), log=print):\n        return 1\n'
    cut = run_src.replace(check_line, "")
    moved = run_src.replace(check_line, "") + "\n" + check_line
    teeth_ok = (not wired_run(cut)) and (not wired_run(moved)) and (cut != run_src)

    pc_check = ('            if not locate.check(("adb", "minitouch"),\n'
                '                                log=lambda s: self.q.put(("log_err", s))):\n'
                '                return False\n')
    pc_cut = pc_src.replace(pc_check, "")
    pc_moved = pc_src.replace(pc_check, "")
    pc_moved = pc_moved.replace("            self.stop_flag.clear()\n",
                                "            self.stop_flag.clear()\n" + pc_check, 1)
    panel_teeth = (not wired_panel(pc_cut)) and (not wired_panel(pc_moved)) and (pc_cut != pc_src)

    # 真跑两个方向：缺 adb 时是 locate 的话先出声；工具都在时是 flag 守卫先出声。
    block = "找不到本工具要用的程序"
    guard = "--retry-anchor 需要 --fastcap"
    bad = run_cli({"HYOUSHI_ADB": r"C:\nope\adb.exe"})
    # 牙：minitouch 缺失时，拒绝里必须给那条真能救回来的退路（2026-10-20 宿主那份被删、
    # 设备里那份还在，就是靠它恢复的）。指一个不存在的 HYOUSHI_MINITOUCH 即可复现。
    hint = run_cli({"HYOUSHI_MINITOUCH": r"C:\nope\minitouch"})
    hint_ok = ("adb pull /data/local/tmp/minitouch_bang tools/bin/minitouch" in hint
               and "adb pull" not in bad)
    # The clean direction only exists on a machine that has the tools: with adb present the same
    # command must reach the flag guard instead, which is the ordering proof. Without them the
    # locate block is the correct answer twice, so only the refusal half is judged.
    clean = not locate.missing(("adb", "minitouch"))
    good = run_cli({}) if clean else ""
    order_ok = (block in bad and guard not in bad
                and (not clean or (guard in good and block not in good)))

    # 面板：缺 adb 时 start() 必须拒绝、往队列写一行错误、而且一个子进程都不许起。
    tmp = Path(tempfile.mkdtemp(prefix="locate_panel_"))
    marker = tmp / "spawned.txt"
    runner = tmp / "fake_runner.py"
    runner.write_text(f"open(r'{marker}', 'w').write('x')\n", encoding="utf-8")
    pan = run_child({"HYOUSHI_ADB": r"C:\nope\adb.exe", "HYOUSHI_PROBE_ROOT": str(ROOT),
                     "OURNOTES_STATE": str(tmp / "gui_state.json"),
                     "OURNOTES_RUNNER": str(runner)}, script=PANEL_CHILD)
    panel_ok = (pan["ok"] is False and pan["busy"] is False and not marker.exists()
                and any(block in ln for ln in pan["lines"]))

    print(f"PART 3  两个入口都接线且在守卫之前 {wired_ok}、"
          f"牙（删掉/挪到守卫之后）{teeth_ok}、牙（面板那条删掉/挪走）{panel_teeth}、"
          f"真跑两个方向的出声顺序 {order_ok}、面板拒绝且不起子进程 {panel_ok}、"
          f"牙（minitouch 缺失时给出 adb pull 退路）{hint_ok}")
    return wired_ok and teeth_ok and panel_teeth and order_ok and panel_ok and hint_ok


def main():
    base = run_child()                      # BANG_* stripped: the historical machine
    ok = part1(base)
    ok = part2(base) and ok
    ok = part3() and ok
    print("PATHS PASS" if ok else "PATHS FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
