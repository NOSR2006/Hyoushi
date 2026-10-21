#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Regression: a dropped adb endpoint heals on the *frame* path too, not just the touch path.

Why this probe exists (2026-10-16, user m27658 「普通的开始演奏按钮不会重连模拟器」): the repair for a
forgotten adb TCP registration lived only in `MTouch._adb`, so the taps healed and the frames did
not. `detect.capture()` -- which backs every screencap read, including the panel's pre-flight
「读画面」 before the ordinary 开始演奏 -- raised `CalledProcessError` instead, the panel said
「没有画面」 and the button did nothing, while 开始演出 (no screen read, run.py's own MTouch heals)
worked. One `adb connect` was the whole difference.

PART 1  behaviour, no device: `detect.capture()` with `subprocess` swapped for a scripted stand-in.
        (a) screencap says "device ... not found" -> connect -> the retry returns a frame:
            exactly three commands, in that order, and a 720x1280x4 array comes back.
        (b) a failure that is *not* the endpoint ("error: closed") -> no connect, adb's own
            CalledProcessError, one command -- the gate matters, or every bad frame reconnects.
        (c) the connect itself fails -> two commands, then adb's own error (no repair loop).
PART 2  the judgement and the repair are one thing now: `mtouch._endpoint_gone` answers exactly
        what `locate.endpoint_gone` answers, `locate.reconnect` prints the three historical lines
        (`probes/mtdiag.py` PART 3 reads the middle one), a USB serial is refused with no call, and
        `adb connect` exists at exactly one site in the tree.
PART 3  teeth (`--teeth`): with `detect.endpoint_gone` forced False, with `detect.reconnect`
        forced False, with the heal taken out of detect.py's source, and with the mtouch
        delegation removed, the same expectations must go red.

Run from the repo root:  python tools/probes/endpointheal.py          # exit 0 = PASS
                         python tools/probes/endpointheal.py --teeth  # every tooth must be red
Needs no emulator, no game, no network: the adb client is never started.
"""

import argparse
import contextlib
import io
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import numpy as np  # noqa: E402

import detect  # noqa: E402
import locate  # noqa: E402
import mtouch  # noqa: E402

SERIAL = "127.0.0.1:16384"
NEED = 720 * 1280 * 4
FRAME = b"\0" * NEED
GONE = b"error: device '127.0.0.1:16384' not found\n"
CLOSED = b"error: closed\n"
CONNECTED = "connected to 127.0.0.1:16384\n"
CONNECT_FAIL = "cannot connect to 127.0.0.1:16384: Connection refused\n"
# The historical line, frozen: `probes/mtdiag.py` PART 3 looks for "重连" in it, and the operators
# read it in the round logs.
LOG_HEALED = "  adb 端点掉线，已重连 127.0.0.1:16384"


class FakeSub:
    """The `subprocess` module as one module under test sees it.

    `run` is scripted and every command is recorded; the exception classes are the *real* ones, so
    `raise subprocess.CalledProcessError` still raises what the callers catch. Patched onto
    `detect.subprocess` / `locate.subprocess` -- never onto the real module, which the rest of this
    process still needs.
    """

    CalledProcessError = subprocess.CalledProcessError
    TimeoutExpired = subprocess.TimeoutExpired
    PIPE = subprocess.PIPE

    def __init__(self, script):
        self.script = script
        self.calls = []

    def run(self, cmd, **kw):
        self.calls.append(list(cmd))
        return self.script(list(cmd), kw)


@contextlib.contextmanager
def swapped(fake, *mods):
    """`mod.subprocess = fake` for each module, restored on the way out."""
    old = [(m, m.subprocess) for m in mods]
    for m, _prev in old:
        m.subprocess = fake
    try:
        yield fake
    finally:
        for m, prev in old:
            m.subprocess = prev


def screencap_script(fail_with=GONE, heal=CONNECTED, fail_times=1):
    """screencap fails `fail_times` times with `fail_with`; `adb connect` answers `heal`."""
    state = {"n": 0}

    def script(cmd, kw):
        if "connect" in cmd:
            return subprocess.CompletedProcess(cmd, 0 if heal == CONNECTED else 1,
                                               stdout=heal, stderr="")
        state["n"] += 1
        if state["n"] <= fail_times:
            return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=fail_with)
        return subprocess.CompletedProcess(cmd, 0, stdout=FRAME, stderr=b"")
    return script


def scenario(fake=None, mod=None, mods=(detect, locate)):
    """`capture()` once against the fake adb. Returns (result or the exception, the commands)."""
    fake = fake or FakeSub(screencap_script())
    mod = mod or detect
    with swapped(fake, *mods):
        try:
            res = mod.capture(SERIAL)
        except Exception as exc:            # noqa: BLE001 - this probe reads the type, not the text
            res = exc
    return res, fake.calls


def _kinds(calls):
    """The command list reduced to what each call was: "screencap" or "connect"."""
    return ["connect" if "connect" in c else "screencap" for c in calls]


def part1():
    res, calls = scenario()
    healed = (isinstance(res, np.ndarray) and res.shape == (720, 1280, 4)
              and _kinds(calls) == ["screencap", "connect", "screencap"])

    res2, calls2 = scenario(FakeSub(screencap_script(fail_with=CLOSED)))
    gated = (isinstance(res2, subprocess.CalledProcessError) and _kinds(calls2) == ["screencap"])

    res3, calls3 = scenario(FakeSub(screencap_script(heal=CONNECT_FAIL)))
    honest = (isinstance(res3, subprocess.CalledProcessError)
              and _kinds(calls3) == ["screencap", "connect"])

    print(f"PART 1  端点掉了自愈（{_kinds(calls)}）{healed}、"
          f"不是端点的错就不连（{_kinds(calls2)}）{gated}、"
          f"连不上就报 adb 原话（{_kinds(calls3)}）{honest}")
    return healed and gated and honest


def _wiring(src_lo, src_mt, src_dt):
    """The static half: one judgement, one repair, one `adb connect` site."""
    return ("def endpoint_gone(" in src_lo and "def reconnect(" in src_lo
            and 'reconnect(self.serial, log=self.log)' in src_mt
            and '"connect", self.serial' not in src_mt
            and "endpoint_gone(" in src_dt and "reconnect(serial)" in src_dt)


def _src(name):
    return io.open(TOOLS / name, encoding="utf-8").read()


def part2():
    shim = (mtouch._endpoint_gone("device offline") is True
            and mtouch._endpoint_gone("error: closed") is False)

    lines = []
    fake = FakeSub(lambda cmd, kw: subprocess.CompletedProcess(cmd, 0, stdout=CONNECTED, stderr=""))
    with swapped(fake, locate):
        ok1 = locate.reconnect(SERIAL, log=lines.append)

    lines2 = []
    fake2 = FakeSub(lambda cmd, kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr=CONNECT_FAIL))
    with swapped(fake2, locate):
        ok2 = locate.reconnect(SERIAL, log=lines2.append)

    lines3 = []
    fake3 = FakeSub(lambda cmd, kw: subprocess.CompletedProcess(cmd, 0, stdout=CONNECTED, stderr=""))
    with swapped(fake3, locate):
        ok3 = locate.reconnect("emulator-5554", log=lines3.append)

    logs = (ok1 is True and lines == [LOG_HEALED]
            and ok2 is False and lines2 and lines2[0].startswith("  !! adb 重连 127.0.0.1:16384 失败：")
            and ok3 is False and not fake3.calls and not lines3)

    wired = _wiring(_src("locate.py"), _src("mtouch.py"), _src("detect.py"))
    print(f"PART 2  mtouch 与 locate 同判 {shim}、三条日志原文 {logs}（USB 端点不连 {ok3 is False}）、"
          f"adb connect 只有一处 {wired}")
    return shim and logs and wired


def tooth_judgement_off():
    """Force the gate False: the heal must not happen, and the caller must see the raw failure."""
    old = detect.endpoint_gone
    detect.endpoint_gone = lambda text: False
    try:
        res, calls = scenario()
    finally:
        detect.endpoint_gone = old
    return isinstance(res, subprocess.CalledProcessError) and _kinds(calls) == ["screencap"]


def tooth_heal_off():
    """Force the repair False (the heal deleted): same failure, no third command."""
    old = detect.reconnect
    detect.reconnect = lambda serial=None, log=print: False
    try:
        res, calls = scenario()
    finally:
        detect.reconnect = old
    return isinstance(res, subprocess.CalledProcessError) and _kinds(calls) == ["screencap"]


def tooth_mutant_detect():
    """The heal taken out of detect.py's source, loaded as its own module."""
    src = _src("detect.py")
    bad = src.replace("            and reconnect(serial)):", "            and False):")
    if bad == src:
        return False
    mod = types.ModuleType("detect_mutant")
    mod.__file__ = str(TOOLS / "detect.py")
    exec(compile(bad, mod.__file__, "exec"), mod.__dict__)   # noqa: S102 - a mutated copy, on purpose
    res, calls = scenario(mod=mod, mods=(mod, locate))
    return isinstance(res, subprocess.CalledProcessError) and _kinds(calls) == ["screencap"]


def tooth_mutant_mtouch():
    """The mtouch delegation removed: the static pin must go red."""
    src = _src("mtouch.py")
    bad = src.replace("        return reconnect(self.serial, log=self.log)", "        return False")
    return bad != src and not _wiring(_src("locate.py"), bad, _src("detect.py"))


TEETH = (
    ("门被掰成 False", tooth_judgement_off),
    ("修复被删掉", tooth_heal_off),
    ("detect 源码里的修复抠掉", tooth_mutant_detect),
    ("mtouch 的委托抠掉", tooth_mutant_mtouch),
)


def main():
    ap = argparse.ArgumentParser(description="adb 端点自愈的回归（帧路径 + 触摸路径）")
    ap.add_argument("--teeth", action="store_true", help="只跑牙：每颗都必须变红")
    args = ap.parse_args()

    if args.teeth:
        bad = []
        for name, fn in TEETH:
            try:
                red = bool(fn())
            except Exception as exc:        # noqa: BLE001 - a tooth that blows up is not red
                red = False
                print(f"  !! 牙 {name} 自己抛了 {exc!r}")
            print(f"  牙 {name}: {'红（对）' if red else '没红（错）'}")
            if not red:
                bad.append(name)
        print("ENDPOINTHEAL TEETH PASS" if not bad else f"ENDPOINTHEAL TEETH FAIL {bad}")
        return 0 if not bad else 1

    ok = part1()
    ok = part2() and ok
    print("ENDPOINTHEAL PASS" if ok else "ENDPOINTHEAL FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
