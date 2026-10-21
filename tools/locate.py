"""Where adb, minitouch and MuMu's renderer SDK live -- one place instead of eight.

Why this exists: this tool grew up on one machine, so five modules hard-coded
``D:\\MuMuPlayer\\nx_main\\adb.exe`` (detect / inject / mtouch / panel_core / probes.calibrate_map),
mumucap hard-coded the renderer SDK's DLL and its install root, and mtouch hard-coded the EvATive7
minitouch binary under a Downloads folder. That is the single biggest reason nobody else can run
this, and it is the whole of "发行前要补的" 第 1 条 on the path half.

Nothing here is a new capability. Every value keeps the historical literal as its default, so this
machine (no environment set) behaves byte-identically; the environment is the escape hatch:

    HYOUSHI_ADB               adb.exe
    HYOUSHI_DEVICE            the adb endpoint (host:port -- not a file)
    HYOUSHI_MINITOUCH         the minitouch binary that gets pushed to the device
    HYOUSHI_MUMU_ROOT         MuMu's install root (the two below derive from it)
    HYOUSHI_MUMUCAP_DLL       external_renderer_ipc.dll
    HYOUSHI_MUMUCAP_INSTALL   the path mumucap.install() is handed

2026-10-20 the project was renamed Bang -> Hyoushi, so the prefix is `HYOUSHI_`; the old `BANG_`
spelling of every name is still honoured (as a fallback -- see `_env`), because the user's own
shell/scripts and the probe corpus were written with it.

`report()` says what each value is and where it came from, `check()` turns that into a startup
verdict that names the environment variable instead of letting adb fail three minutes into a round,
and `python tools/locate.py` prints both. `tools/probes/paths.py` pins the defaults, the override
and the refusal. `tools/probes/endpointheal.py` pins the other thing this module owns: `endpoint_gone`
and `reconnect`, the repair for an adb TCP registration the host forgot (see `reconnect` below).
"""

from __future__ import annotations

import os
import subprocess

# spawned from a console-less parent (pythonw) every console child -- adb -- otherwise gets a
# console window of its own; the flag suppresses the window, not the process.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# adb is not consistent about its output code page: the Chinese socket error behind a refused
# `adb connect` arrives as bytes the GBK locale cannot decode, and subprocess's own reader thread
# then dies with a UnicodeDecodeError that leaves stdout/stderr as None -- which reads as "the
# repair printed nothing", and at the banner read as "the daemon never talked". Decode adb as
# utf-8 and replace whatever still will not decode.
TEXT = {"text": True, "encoding": "utf-8", "errors": "replace"}

# The historical literals. Defaults, not laws -- see the module docstring.
ADB_DEFAULT = r"D:\MuMuPlayer\nx_main\adb.exe"
DEVICE_DEFAULT = "127.0.0.1:16384"
# 2026-10-20：那个 Downloads 目录被清掉了（一套能跑的工具不该依赖一个跟它无关的下载目录）。设备上
# 一直留着当初推上去的那一份（/data/local/tmp/minitouch_bang），`adb pull` 拉回来放进 tools/bin/
# （gitignored，28 KB，EvATive7 的 x86_64 构建，握手实测过）—— 从此默认值优先是随包这一份，历史
# 字面量只作为「随包那份被删了」的退路；环境变量仍然最高优先。
MINITOUCH_LEGACY = (r"D:/Downloads/autodori_v1.2.4_Windows_X64/assets/minitouch_EvATive7"
                    r"/x86_64/minitouch")
MINITOUCH_BUNDLED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "minitouch")
MINITOUCH_DEFAULT = MINITOUCH_BUNDLED if os.path.exists(MINITOUCH_BUNDLED) else MINITOUCH_LEGACY
MUMU_ROOT_DEFAULT = r"D:\MuMuPlayer"


ENV_PREFIX = "HYOUSHI_"          # current spelling (project renamed 2026-10-20)
ENV_PREFIX_LEGACY = "BANG_"      # the old spelling -- still honoured, never advertised


def _env(name, default):
    """(value, source) for one setting: the environment wins over the literal.

    Two names are tried, current spelling first: `HYOUSHI_<name>` then `BANG_<name>`. `source` says
    which one answered (`env` / `env:legacy` / `default`) so `report()` can be honest about it --
    a value that only arrived because of a name from the previous release is worth a word.
    """
    for prefix, tag in ((ENV_PREFIX, "env"), (ENV_PREFIX_LEGACY, "env:legacy")):
        got = os.environ.get(prefix + name)
        if got and got.strip():
            return got.strip(), tag
    return default, "default"


def env(name, default=""):
    """Value of a non-path switch (`HYOUSHI_<name>`, legacy `BANG_<name>`), or `default`.

    Lives here so that every env spelling the project reads has one owner; `_fake_runner.py` keeps
    its own two-line copy on purpose (it must not import anything from this package).
    """
    for prefix in (ENV_PREFIX, ENV_PREFIX_LEGACY):
        got = os.environ.get(prefix + name)
        if got is not None and got != "":
            return got
    return default


ADB, ADB_SOURCE = _env("ADB", ADB_DEFAULT)
DEVICE, DEVICE_SOURCE = _env("DEVICE", DEVICE_DEFAULT)
MINITOUCH, MINITOUCH_SOURCE = _env("MINITOUCH", MINITOUCH_DEFAULT)
if MINITOUCH_SOURCE == "default" and MINITOUCH_DEFAULT == MINITOUCH_BUNDLED:
    MINITOUCH_SOURCE = "default:bundled"
MUMU_ROOT, MUMU_ROOT_SOURCE = _env("MUMU_ROOT", MUMU_ROOT_DEFAULT)
# The SDK ships inside the install root, so MUMU_ROOT alone covers a moved install; the two
# specific names are for the case where only one of them moved.
DLL_PATH, DLL_SOURCE = _env("MUMUCAP_DLL",
                            os.path.join(MUMU_ROOT, "nx_main", "sdk",
                                         "external_renderer_ipc.dll"))
INSTALL_PATH, INSTALL_SOURCE = _env("MUMUCAP_INSTALL", MUMU_ROOT)
if DLL_SOURCE == "default" and MUMU_ROOT_SOURCE != "default":
    DLL_SOURCE = f"{MUMU_ROOT_SOURCE}:MUMU_ROOT"
if INSTALL_SOURCE == "default" and MUMU_ROOT_SOURCE != "default":
    INSTALL_SOURCE = f"{MUMU_ROOT_SOURCE}:MUMU_ROOT"

# name -> (value, source, kind). "endpoint" is not a path and can never be missing.
SETTINGS = {
    "adb": (ADB, ADB_SOURCE, "file"),
    "device": (DEVICE, DEVICE_SOURCE, "endpoint"),
    "minitouch": (MINITOUCH, MINITOUCH_SOURCE, "file"),
    "mumucap_dll": (DLL_PATH, DLL_SOURCE, "file"),
    "mumucap_install": (INSTALL_PATH, INSTALL_SOURCE, "dir"),
}
ENV_NAMES = {
    "adb": ENV_PREFIX + "ADB",
    "device": ENV_PREFIX + "DEVICE",
    "minitouch": ENV_PREFIX + "MINITOUCH",
    "mumucap_dll": ENV_PREFIX + "MUMUCAP_DLL",
    "mumucap_install": ENV_PREFIX + "MUMUCAP_INSTALL",
}
# What a round cannot start without. The SDK is deliberately absent from this set: `--fastcap`
# falls back to window/adb capture by design (see run.py's --host help), so a missing DLL is a
# note, not a refusal.
NEEDED = ("adb", "minitouch")


def report():
    """One row per setting: name, value, source, kind, exists (None when it is not a path)."""
    out = []
    for name, (value, source, kind) in SETTINGS.items():
        exists = None if kind == "endpoint" else os.path.exists(value)
        out.append({"name": name, "value": value, "source": source, "kind": kind,
                    "exists": exists})
    return out


def missing(names=None):
    """Names whose path is not on disk (endpoints are never listed)."""
    return [r["name"] for r in report()
            if r["kind"] != "endpoint" and not r["exists"]
            and (names is None or r["name"] in names)]


def check(need=NEEDED, log=print):
    """Startup verdict: True = everything in `need` is on disk.

    Refuses rather than warns, because the failure it prevents is silent by distance: a missing
    adb or minitouch shows up as "the walk stalled" a few minutes into a round, not as an error
    where it happened.
    """
    rows = [r for r in report() if r["name"] in need]
    bad = [r for r in rows if r["kind"] != "endpoint" and not r["exists"]]
    if not bad:
        return True
    log("!! 找不到本工具要用的程序，本局不开始（换机器只需给环境变量，见 tools/locate.py）：")
    for r in bad:
        log(f"   {r['name']} 现在指向 {r['value']}（来路 {r['source']}）"
            f" —— 用 {ENV_NAMES[r['name']]} 指到别处")
    log("   另外几个开关：HYOUSHI_DEVICE / HYOUSHI_MUMU_ROOT / HYOUSHI_MUMUCAP_DLL / "
        "HYOUSHI_MUMUCAP_INSTALL（旧的 BANG_ 前缀仍然认，只是不再宣传）")
    if any(r["name"] == "minitouch" for r in bad):
        # 2026-10-20 就是这么救回来的：宿主上那份被删了，设备里那份还在（mtouch 只在缺失时才 push，
        # 所以旧副本会一直留着）。把这条路写进拒绝里，下次不必再靠人想起它。
        log("   minitouch 的退路：设备上通常还留着当初推上去的那一份 —— "
            "adb pull /data/local/tmp/minitouch_bang tools/bin/minitouch")
    return False


def endpoint_gone(text):
    """Whether adb is describing a missing transport rather than a command that failed.

    A restarted emulator leaves ``emulator-5554`` in ``adb devices`` but drops the TCP
    registration, so every ``-s 127.0.0.1:16384`` call answers "device ... not found" -- which is
    how g165/g166 died 5 s apart without ever touching the game. A shell command that prints
    "not found" itself has no "device" in that line, and "no devices" / "device offline" are the
    server's other two ways of saying the same thing.

    Moved here from mtouch on 2026-10-16, unchanged: the *frame* reads need the same judgement the
    taps have had, and a second copy of these three substrings is how they drift apart.
    """
    t = (text or "").lower()
    return ("device" in t and "not found" in t) or "no devices" in t or "device offline" in t


def reconnect(serial=None, log=print):
    """Re-register a dropped TCP endpoint. True when adb says it connected.

    Client-side bookkeeping only: nothing on the device is touched, the emulator was never down,
    the host just forgot the registration -- and an endpoint that is still registered answers
    "already connected". Only meaningful for a host:port endpoint, so a USB serial (no ":") is
    refused without a word: there is nothing to re-register.

    The three log lines are the historical ones from ``MTouch._connect`` (2026-10-05); the probe
    `tools/probes/mtdiag.py` PART 3 reads them, so they are contract, not prose.
    """
    serial = serial or DEVICE
    if ":" not in serial:
        return False
    try:
        r = subprocess.run([ADB, "connect", serial], capture_output=True, timeout=15,
                           creationflags=CREATE_NO_WINDOW, **TEXT)
    except (subprocess.TimeoutExpired, OSError) as exc:
        log(f"  !! adb 重连 {serial} 没跑完：{exc}")
        return False
    out = f"{r.stdout or ''}{r.stderr or ''}".lower()
    if "connected" in out:                      # "connected to X" / "already connected to X"
        log(f"  adb 端点掉线，已重连 {serial}")
        return True
    # Nothing is listening: the emulator is off, and the caller's own check will now raise with
    # adb's original words -- the honest error for that case.
    log(f"  !! adb 重连 {serial} 失败：{(r.stdout or r.stderr).strip()}")
    return False


def lines():
    """The table `python tools/locate.py` prints (and logs quote)."""
    out = []
    for r in report():
        if r["kind"] == "endpoint":
            state = "端点"
        else:
            state = "在" if r["exists"] else "!! 不在"
        out.append(f"{r['name']:<16} {r['value']}  [{r['source']}, {state}]")
    return out


def main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="打印本工具依赖的路径、来路与启动校验结果")
    ap.add_argument("--json", action="store_true", help="给脚本读的结构化版本")
    args = ap.parse_args(argv)
    if args.json:
        print(json.dumps(report(), ensure_ascii=False, indent=2))
        return 0 if not missing() else 1
    for line in lines():
        print(line)
    ok = check(log=print)
    print("启动校验：" + ("通过" if ok else "不过 —— 见上面那几行"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
