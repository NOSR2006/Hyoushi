"""Regression: the minitouch echo must survive reconnects AND a saturated jlog.

t93/t94's restart cycles showed 14 daemon rebuilds in a row: every probe read "device is
silent" and rebuilt, while the restarts themselves worked. Two stacked host-side faults:

1. the pump thread re-read `self.sock` each iteration and died on the old socket's close
   in `reconnect()`, and reconnect never installed a new reader -- after ANY reconnect
   the channel had no reader at all (old code: pumps 2->0 across one reconnect);
2. `_echo()` waited on `len(self.jlog)` growing, but jlog is a deque(maxlen=4096) that a
   long attempt (~2400 actions = ~4800 command lines) saturates -- then the length never
   changes again and EVERY echo check reads "silent" forever, across reconnects and
   rebuilds (the deque survives both), while play-phase echo counters keep growing.

This probe drives a fresh MTouch (commit-only commands; nothing is touched on screen):

PART 1  open / reconnect: exactly one live pump per socket, the daemon answers a bare
        commit after both, and a reconnect costs no rebuild (respawns stays 0).
PART 2  saturation: shrink the deck to maxlen=4, push it full, and require the echo to
        keep answering -- with the len-based check the same state must read "silent".
PART 3  the adb endpoint itself: a restarted emulator leaves `emulator-5554` in `adb devices`
        but drops the TCP registration, so every `-s 127.0.0.1:16384` call answers "device
        ... not found" -- that is how g165/g166 died 5 s apart at 09:03 without ever reaching
        the game. `adb disconnect` recreates the state here: open() must heal it and go on
        firing, and with the heal switched off the same state must kill it the old way.

Needs the emulator's adb up (not the game). PART 3 disconnects and reconnects this host's adb
endpoint for a second or two, so run it while no round is in flight. Run from the repo root:
    python tools/probes/mtdiag.py     # exit 0 = PASS
"""

import os
import subprocess
import sys
import threading
import time
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mtouch  # noqa: E402


def pumps():
    return [t for t in threading.enumerate() if getattr(t, "_target", None) is not None
            and getattr(t._target, "__name__", "") == "_pump"]


def live_pumps():
    return sum(1 for t in pumps() if t.is_alive())


def raw_echo(inj, wait=0.6):
    """The daemon answers a bare commit (no repair logic, unlike MTouch.probe)."""
    n = inj.echoes
    inj.send(["c"])
    end = time.perf_counter() + wait
    while time.perf_counter() < end and inj.echoes == n:
        time.sleep(0.005)
    return inj.echoes > n


def len_echo(inj, wait=0.8):
    """The old, broken check: waits on len(self.jlog) -- teeth for PART 2."""
    n = len(inj.jlog)
    inj.send(["c"])
    end = time.perf_counter() + wait
    while time.perf_counter() < end and len(inj.jlog) == n:
        time.sleep(0.005)
    return len(inj.jlog) > n


def _adb(*args):
    return subprocess.run([mtouch.ADB, *args], capture_output=True, text=True,
                          creationflags=mtouch.CREATE_NO_WINDOW)


def main():
    inj = mtouch.MTouch(log=lambda s: print(f"  mt: {s}"))
    checks = []

    # PART 1 -- reader survives a reconnect, and a reconnect costs no rebuild.
    checks.append(("one live pump after open", live_pumps() == 1))
    checks.append(("echo after open", raw_echo(inj)))

    inj.reconnect()
    time.sleep(0.1)
    checks.append(("one live pump after reconnect", live_pumps() == 1))
    checks.append(("echo after reconnect", raw_echo(inj)))
    checks.append(("reconnect cost no rebuild", inj.respawns == 0))

    time.sleep(1.5)
    checks.append(("one live pump after 1.5s idle", live_pumps() == 1))
    checks.append(("echo after 1.5s idle", raw_echo(inj)))

    # PART 2 -- the deck is a maxlen deque; a full one must not blind the echo. Shrunk to 4
    # here so the saturation is seconds away instead of 4800 commands.
    inj.jlog = deque(inj.jlog, maxlen=4)
    for _ in range(8):
        inj.send(["c"])
    time.sleep(0.3)
    checks.append(("deck saturated", len(inj.jlog) == 4))
    checks.append(("echo on a saturated deck (echoes-based)", raw_echo(inj)))
    checks.append(("len-based check would read silent (teeth)", not len_echo(inj)))

    inj.close()

    # PART 3 -- the emulator-restart case, recreated by dropping this host's TCP registration.
    serial = mtouch.DEVICE
    _adb("disconnect", serial)
    if serial in _adb("devices").stdout:
        print("  endpoint heal: SKIP (disconnect 之后设备仍在列表里，造不出这个故障)")
    else:
        lines = []
        try:
            inj2 = mtouch.MTouch(serial=serial, log=lines.append)
            healed = any("重连" in s for s in lines) and raw_echo(inj2)
            inj2.close()
        except Exception as exc:                        # noqa: BLE001 -- the probe reports, no raise
            healed = False
            print(f"  !! 造故之后 open() 抛了：{type(exc).__name__}: {exc}")
        checks.append(("open() healed a dropped adb endpoint", healed))

        # Teeth: switch the heal off and the same state must kill open() the way it killed g165.
        _adb("disconnect", serial)
        real = mtouch.MTouch._connect
        mtouch.MTouch._connect = lambda self: False
        try:
            mtouch.MTouch(serial=serial, log=lambda s: None)
            checks.append(("no heal means the old death (teeth)", False))
        except RuntimeError:
            checks.append(("no heal means the old death (teeth)", True))
        finally:
            mtouch.MTouch._connect = real
        _adb("connect", serial)              # leave the endpoint registered, whatever happened

    for name, ok in checks:
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
    ok = all(c[1] for c in checks)
    print("MTDIAG " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
