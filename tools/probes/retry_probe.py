"""Measure the 暂停→重试 restart as a clock: record three retry cycles, tap nothing else.

The user's observation: after 暂停 → 重试 (confirm), the song starts again from a fixed point --
possibly exactly chart t=0. If [the confirmation closes] -> [the first note crosses the judgement
band] is the same interval on every retry, this is a better anchor than anything the intro's
pixel soup can vote up: t0 = the tap we sent (host clock, ~1 ms) + one constant, known seconds
before the first note is due, and identical for every song, because the pause panel is the same
UI everywhere and the constant is the game's own restart latency.

The script drives the UI and records; it never presses notes. Exactly three kinds of tap go out,
each gated on calib's positive identification: the pause button (only while the field's magenta
lines prove a LIVE is running), the middle pill of the pause panel, and 重试 on the confirmation.
Anything unrecognised stops the probe instead of guessing, and the LIVE is left paused at the end.
"""
import argparse
import subprocess
import sys
import time

sys.path.insert(0, "tools")
from calib import PAUSE_BTN, RETRY_BTN, RETRY_OK, in_live, screen, start_live, tap, which_dialog  # noqa: E402
from detect import ADB, DEVICE, grab  # noqa: E402
from mtouch import MTouch  # noqa: E402
from player import raise_timer_resolution  # noqa: E402


def _adb(*args):
    return subprocess.run([ADB, "-s", DEVICE, *args], capture_output=True, text=True)


def _start_recorder(dev_path, seconds, bit_rate):
    return subprocess.Popen(
        [ADB, "-s", DEVICE, "shell", "screenrecord",
         "--time-limit", str(seconds), "--bit-rate", str(bit_rate), dev_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _stop_recorder(proc, log):
    out = _adb("shell", "pidof", "screenrecord")
    pids = out.stdout.split()
    if pids:
        log(f"  rec: SIGINT to {pids}")
        _adb("shell", "kill", "-2", *pids)
    else:
        log("  rec: pidof empty, waiting out the time limit")
    proc.wait(timeout=30)


def _pause_panel(inj, log, tries=3):
    """Put the pause panel on screen, or give up without tapping anything uncertain."""
    for k in range(tries):
        d = which_dialog()
        if d == "pause":
            return True
        if d == "confirm":
            log("  already at the 重试 confirmation")
            return True
        if not in_live():
            log(f"  field not running and no dialog (saw {d!r}) - stopping")
            return False
        log(f"  tapping 暂停 (try {k + 1})")
        tap(*PAUSE_BTN, i=inj)
        time.sleep(1.6)
    return which_dialog() in ("pause", "confirm")


def _confirm(inj, log, tries=3):
    """Reach the 重试 confirmation (tapping the panel's middle pill if needed), not past it."""
    for k in range(tries):
        d = which_dialog()
        if d == "confirm":
            return True
        if d == "pause":
            log(f"  tapping 重试 on the panel (try {k + 1})")
            tap(*RETRY_BTN, i=inj)
            time.sleep(1.2)
            continue
        log(f"  expected the 重试 confirmation, seeing {d!r} - stopping")
        return False
    return which_dialog() == "confirm"


def _wait_live(log, timeout=30.0):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        if in_live():
            return True
        time.sleep(0.5)
    log("  field did not come back within the wait")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--gap", type=float, default=20.0, help="seconds of song between retries")
    ap.add_argument("--tag", default="retry_probe")
    args = ap.parse_args()

    def log(m):
        print(f"+{time.perf_counter() - t_start:7.2f}s {m}", flush=True)

    raise_timer_resolution()
    t_start = time.perf_counter()
    log(f"current screen: {screen(grab())!r} (walk will start from here)")
    inj = MTouch()
    dev_path = f"/sdcard/{args.tag}.mp4"
    out_path = f"research/{args.tag}.mp4"
    proc = None
    try:
        _adb("shell", "rm", "-f", dev_path)
        if not start_live(inj, log=log):
            log("could not reach a LIVE")
            return 1
        log("LIVE field is up")
        proc = _start_recorder(dev_path, 180, 6000000)
        log("recorder started")
        time.sleep(1.0)
        for i in range(1, args.samples + 1):
            if not _pause_panel(inj, log):
                return 2
            if not _confirm(inj, log):
                return 3
            log(f"sample {i}: confirmed the restart (tapping 重试 OK now)")
            tap(*RETRY_OK, i=inj)
            time.sleep(args.gap)
            if i < args.samples:
                _wait_live(log)
        if not _pause_panel(inj, log):
            return 4
        log("LIVE left paused")
        return 0
    finally:
        if proc is not None:
            _stop_recorder(proc, log)
            out = _adb("pull", dev_path, out_path)
            log(f"  rec: pull rc={out.returncode} {out.stdout.strip()} {out.stderr.strip()}")
            _adb("shell", "rm", "-f", dev_path)
        inj.close()
        log("done")


if __name__ == "__main__":
    sys.exit(main())
