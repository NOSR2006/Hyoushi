"""Raw multi-touch injection into the MuMu virtual touchscreen (/dev/input/event4).

A single long-lived `adb shell cat > /dev/input/event4` process is kept open so taps can be
issued with host-side sub-millisecond scheduling instead of paying an adb fork per event.
"""

from __future__ import annotations

import struct
import subprocess
import sys
import time

from locate import ADB, CREATE_NO_WINDOW, DEVICE  # 路径集中探测（含环境变量）：见 tools/locate.py
EVENT_NODE = "/dev/input/event4"

# struct input_event on 64-bit Android: timeval(16) + type(2) + code(2) + value(4)
EVENT_FMT = "=qqHHi"
EVENT_SIZE = struct.calcsize(EVENT_FMT)

EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0x00
BTN_TOUCH = 0x140
ABS_MT_SLOT, ABS_MT_POSITION_X, ABS_MT_POSITION_Y = 0x2F, 0x35, 0x36
ABS_MT_TRACKING_ID, ABS_MT_PRESSURE = 0x39, 0x3A

# The node reports a 720x1280 (portrait) raw frame while the display is 1280x720 landscape.
RAW_W, RAW_H = 720, 1280
SCREEN_W, SCREEN_H = 1280, 720


class TouchInjector:
    def __init__(self, serial: str = DEVICE) -> None:
        self.serial = serial
        self._t0 = time.perf_counter()
        self.proc = None
        self.respawns = 0
        self.open()

    def open(self) -> None:
        """Start the writer and prove it can take events before returning.

        A bare poll() is not enough: the adb client sometimes survives the first 50 ms and dies
        a few hundred ms later, which used to look like a healthy injector until the very first
        note of a run hit EINVAL. So liveness is proven by writing a bare SYN_REPORT -- a no-op
        to the input layer, since no slot changed -- and requiring it to flush. Retries back off
        because a shell session the device just refused usually needs a moment, not a harder push.
        """
        bare_syn = struct.pack(EVENT_FMT, 0, 0, EV_SYN, SYN_REPORT, 0)
        last = None
        delay = 0.25
        for _ in range(8):
            proc = subprocess.Popen(
                [ADB, "-s", self.serial, "shell", f"cat > {EVENT_NODE}"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
            time.sleep(delay)
            delay = min(delay * 1.7, 1.5)
            if proc.poll() is None:
                try:
                    proc.stdin.write(bare_syn)
                    proc.stdin.flush()
                except OSError as exc:
                    last = f"write failed: {exc!r}"
                else:
                    if proc.poll() is None:
                        self.proc = proc
                        self.release_all()   # drop any contact a previous process left down
                        return
                    last = "died after the probe write"
            else:
                last = f"exited rc={proc.returncode}"
            try:
                proc.kill()
                proc.wait(timeout=2.0)
            except Exception:
                pass
        raise RuntimeError(f"injector writer will not stay up ({last})")

    def _reap(self) -> None:
        """Close and reap the current writer.

        Leaving it half-dead is what starves the next session: the point of the pipe is that one
        writer holds the node, so a zombie adb client makes every later open() fail.
        """
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except OSError:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except Exception:
            proc.kill()

    def probe(self) -> bool:
        """Confirm the writer is live and flushing, without touching any finger slot."""
        self._ensure()
        self._flush()
        return self.proc.poll() is None

    def _ensure(self) -> bool:
        """Respawn the writer if the device-side cat exited.

        It does exit on its own occasionally, and a silently dead pipe means every note of a
        run is dropped, so liveness is checked rather than assumed. Respawning costs a few
        hundred ms, which is why `respawns` is exposed: a mid-song respawn is a hole in the
        schedule, not a hiccup.
        """
        if self.proc is not None and self.proc.poll() is None:
            return True
        self.respawns += 1
        self._reap()
        self.open()
        return False

    def _send(self, type_: int, code: int, value: int) -> None:
        now = time.time()
        payload = struct.pack(EVENT_FMT, int(now), int((now % 1) * 1e6), type_, code, value)
        for _ in range(4):
            self._ensure()
            try:
                self.proc.stdin.write(payload)
                return
            except (OSError, ValueError):
                continue
        raise RuntimeError("injector writer will not accept events")

    def syn(self) -> None:
        self._send(EV_SYN, SYN_REPORT, 0)
        self._flush()

    def _flush(self) -> None:
        """Flush, respawning the writer if the reader went away.

        Must never raise into a running note schedule: a mid-burst exception drops every
        remaining note, whereas a respawn costs a few hundred ms and only loses the notes in
        that window.
        """
        for _ in range(4):
            try:
                self.proc.stdin.flush()
                return
            except (OSError, ValueError):
                self._ensure()
        raise RuntimeError("injector writer will not recover")

    def release_all(self, slots: int = 10) -> None:
        """Lift every finger slot.

        The device keeps multi-touch state across processes, so a run that died mid-song leaves
        phantom contacts that make the game ignore every later tap -- which looks exactly like
        injection having stopped working.
        """
        for slot in range(slots):
            self._send(EV_ABS, ABS_MT_SLOT, slot)
            self._send(EV_ABS, ABS_MT_TRACKING_ID, -1)
        self._send(EV_KEY, BTN_TOUCH, 0)
        self.syn()

    def touch_down(self, slot: int, x: int, y: int, tracking_id: int) -> None:
        self._send(EV_ABS, ABS_MT_SLOT, slot)
        self._send(EV_ABS, ABS_MT_TRACKING_ID, tracking_id)
        self._send(EV_ABS, ABS_MT_POSITION_X, x)
        self._send(EV_ABS, ABS_MT_POSITION_Y, y)
        if slot == 0:
            self._send(EV_KEY, BTN_TOUCH, 1)
        self.syn()

    def touch_up(self, slot: int) -> None:
        self._send(EV_ABS, ABS_MT_SLOT, slot)
        self._send(EV_ABS, ABS_MT_TRACKING_ID, -1)
        if slot == 0:
            self._send(EV_KEY, BTN_TOUCH, 0)
        self.syn()

    def touch_move(self, slot: int, x: int, y: int) -> None:
        self._send(EV_ABS, ABS_MT_SLOT, slot)
        self._send(EV_ABS, ABS_MT_POSITION_X, x)
        self._send(EV_ABS, ABS_MT_POSITION_Y, y)
        self.syn()

    def tap(self, x: int, y: int, hold_s: float = 0.03, slot: int = 0, tid: int = 1) -> None:
        self.touch_down(slot, x, y, tid)
        time.sleep(hold_s)
        self.touch_up(slot)

    def close(self) -> None:
        self._reap()


# Measured against the pointer_location crosshair on the launcher:
#   screen = (raw_y, RAW_W - raw_x)   with raw_x in [0,720], raw_y in [0,1280]
# i.e. the portrait "Xiaomi Touchscreen" is rotated 90 deg CCW into the 1280x720 display.
def to_raw(name: str, screen_x: float, screen_y: float) -> tuple[int, int]:
    """Invert the raw->screen mapping: given the desired screen point, find the raw axes to write."""
    rx = RAW_W - screen_y
    ry = screen_x
    if not (0 <= rx <= RAW_W and 0 <= ry <= RAW_H):
        raise RuntimeError(f"screen {(screen_x, screen_y)} maps outside raw axes")
    return int(round(rx)), int(round(ry))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    inj = TouchInjector()
    try:
        if mode == "selftest":
            print(f"EVENT_SIZE={EVENT_SIZE} (expect 24)")
            inj.tap(360, 640)
            print("sent one tap at raw (360,640)")
        else:
            name = mode
            rx, ry = to_raw(name, int(sys.argv[2]), int(sys.argv[3]))
            print(f"{name}: screen ({sys.argv[2]},{sys.argv[3]}) -> raw ({rx},{ry})")
            inj.tap(rx, ry)
    finally:
        inj.close()
