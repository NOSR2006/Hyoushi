"""MuMu's own screencap: the renderer SDK instead of `adb exec-out screencap`.

`screencap` is a 216-248 ms round trip, which caps the whole harness at 3.6 fps and is the reason
the anchor cannot finish before note 1 (a note is on screen for 1.54 s before it hits, so the vote
needs fast frames, not a better vote). MuMu ships external_renderer_ipc.dll, the same capture path
MaaFramework reaches via screencap_methods=64 + extras.mumu, and its maafw log on this machine
shows consecutive captures 8-16 ms apart. This module drives that DLL directly.

The DLL is MuMu's own vendored component; talking to it is the same kind of move as talking to
their adb or their minitouch build -- no third-party bot code runs here.

Call `install()` once, then `frame()` returns (t, RGB uint8 (720,1280,3)). The frame is the
renderer's latest composited buffer, so it is stamped at the moment of the call like screencap:
the call costs ~10 ms, and ten milliseconds of stamp jitter that averages out over a hundred
blobs is exactly what a vote can eat and a single-sample landmark cannot.
"""

import ctypes
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from locate import DLL_PATH, INSTALL_PATH  # noqa: E402  路径集中探测：见 tools/locate.py

W, H = 1280, 720
BUFSIZE = W * H * 4

_dll = None
_handle = None
_display = None
_conv = None
# The DLL's capture is a synchronous vendor call and `_conv` is a module-global buffer, so two
# threads reading concurrently are not a race but a silent frame swap: thread B overwrites thread
# A's pixels while A is still in the DLL, and A's stamp then names B's frame. HudWatch and the
# relock vote are the first callers that can overlap.
_lock = threading.Lock()
# This is the one place an emulator's capture offset is corrected for, and here it is 0. It was 4:
# on 2026-10-03 nemu_capture_display handed back the same picture as `screencap` 4 columns to the
# left (its column j was screencap's column j+4), the best x offset measured -4 three times on a
# still screen, and after correcting it the two sources agreed to a mean of 0.58-1.04 per channel
# with 0.07% of pixels differing by more than 16 -- closer than the fast source agreed with *itself*
# two frames in a row (1.52). MuMu 15 (MuMuPlayer-15.0-0, the same upgrade that began framing
# `screencap` behind a 16-byte header) closed that gap: measured 2026-10-06 on a still screen, the
# DLL frame is byte-identical to screencap at dx=0 (best-shift difference 0.000, against 3.250 once
# the old 4 is applied to it), so two sources that were 15.7 apart are now 0.00 apart and the 4 was
# itself the error.
#
# Nothing in a run would ever have caught that: y is not shifted (a dy scan puts the minimum exactly
# at 0), so the timing axis was right, and x only picks a lane -- 4 px is 0.16 of a lane against a
# 2.5-lane tolerance. `tools/probes/capreg.py` PART 1/2 caught it the first time it had a device to
# look at, which is what that probe is for.
SHIFT_X = 0


def register(img):
    """Move a fast-source frame into the coordinate space every constant here is tuned in.

    A no-op at the current SHIFT_X = 0, kept as the single seam for an emulator that starts handing
    frames back off by a few columns again. When the shift was 4, the columns screencap had and the
    fast source did not were the leftmost sliver of the screen, which no check reads (the field's
    left edge is near x=340 and every button is tens of px wide), so they were edge-filled rather
    than guessed at. `tools/probes/capreg.py` PART 1/2 fail if this ever stops matching `screencap`.
    """
    if SHIFT_X == 0:
        # 恒等那一档别再白拷一遍：`frame()` 交进来的已经是它自己那份私有拷贝
        # （`_conv[::-1, :, :3].copy()`），所以直接把引用交出去是安全的 —— 没有第二个调用方，
        # `tools/probes/capreg.py` 用的是它自己那份平移（只把 `register()` 写在注释里）。
        # 实测（2026-10-06）：这一份多余的 2.7 MB 拷贝值 **0.504 ms/帧**，而一次 `frame()` 一共
        # 8.41 ms（60 帧帧间中位 8.13 ms）⇒ 白扔 6%。
        return img
    out = np.empty_like(img)
    out[:, SHIFT_X:] = img[:, :W - SHIFT_X]
    out[:, :SHIFT_X] = img[:, 0:1]
    return out


# The renderer hands back "whatever is composited right now", so a stalled pipeline looks exactly
# like a paused game: a valid frame, a fresh stamp, and pixels that are a second old.
_stall = {"fp": None, "changed": None}


def _fingerprint(img):
    """A cheap 'did the screen move' number: 0.8% of the pixels, one sum.

    A hash of the whole frame would cost more than the 9 ms call it measures. Every 8th row and
    16th column still covers both lanes and the HUD counters, and anything that moved at all moved
    some of them -- between two frames of a live the notes scroll, so a real frame is never identical
    to its predecessor. This is a liveness check, not a comparison: what it must never become is the
    thing that slows the capture down.
    """
    return int(img[::8, ::16, 0].sum())


def _note_fresh(img):
    """Say whether these pixels are new; call with `_lock` held. Returns the last change's stamp."""
    fp = _fingerprint(img)
    if fp != _stall["fp"]:
        _stall["fp"] = fp
        _stall["changed"] = time.perf_counter()
    return _stall["changed"]


def stalled_s():
    """Seconds since the renderer last handed back different pixels; 0.0 until two frames exist.

    The point is not the number but the possibility of asking. `frames()`' contract is "the stamp is
    when those pixels reached us", and a frozen buffer satisfies it while the pixels are seconds old
    -- so a rule that reads "nothing moved" as "nothing happened" is being lied to. hostcap has had
    this watchdog since the day it was written (`hostcap.py` says so and takes the other source
    meanwhile); the renderer SDK, which the walks, the relock vote and the HUD watch now all run on,
    did not. `tools/probes/freshfeed.py` measures what that costs each sampling loop, and
    `tools/probes/framewriter.py` PART 6/7 pins this bookkeeping and the line it feeds.
    """
    with _lock:
        return 0.0 if _stall["changed"] is None else time.perf_counter() - _stall["changed"]


def _load():
    global _dll
    if _dll is not None:
        return _dll
    dll = ctypes.CDLL(DLL_PATH)
    dll.nemu_connect.restype = ctypes.c_int
    dll.nemu_connect.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
    dll.nemu_disconnect.restype = None
    dll.nemu_disconnect.argtypes = [ctypes.c_int]
    dll.nemu_capture_display.restype = ctypes.c_int
    dll.nemu_capture_display.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_int,
                                         ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                         ctypes.POINTER(ctypes.c_ubyte)]
    if hasattr(dll, "nemu_get_display_id"):
        dll.nemu_get_display_id.restype = ctypes.c_int
        dll.nemu_get_display_id.argtypes = [ctypes.c_int, ctypes.c_uint]
    _dll = dll
    return dll


def install(index=0, path=INSTALL_PATH):
    global _handle, _display, _conv
    if _handle is not None:
        return _handle
    dll = _load()
    h = dll.nemu_connect(path, index)
    if h < 0:
        raise RuntimeError(f"nemu_connect({path!r}, {index}) -> {h}")
    _handle = h
    if hasattr(dll, "nemu_get_display_id"):
        _display = dll.nemu_get_display_id(h, 0)
        if _display < 0:
            _display = 0
    else:
        _display = 0
    _conv = np.empty((H, W, 4), dtype=np.uint8)
    return _handle


def uninstall():
    global _handle, _display, _conv
    if _handle is not None:
        _load().nemu_disconnect(_handle)
    _handle, _display, _conv = None, None, None
    # A fresh handle starts a fresh clock: the next frame has to be allowed to be "new" even when it
    # happens to fingerprint like the last one on the old display.
    _stall["fp"] = _stall["changed"] = None


def frame():
    """(perf_counter stamp at call start, RGB frame)."""
    if _handle is None:
        install()
    with _lock:
        t = time.perf_counter()
        buf = _conv.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte))
        w = ctypes.c_int(0)
        h = ctypes.c_int(0)
        rc = _load().nemu_capture_display(_handle, _display, BUFSIZE, ctypes.byref(w),
                                          ctypes.byref(h), buf)
        if rc != 0 or w.value != W or h.value != H:
            raise RuntimeError(f"nemu_capture_display rc={rc} {w.value}x{h.value}")
        # The renderer hands the frame back bottom-up but in the same channel order as screencap,
        # so only the row axis is flipped. The extra [..., ::-1] that used to be here mirrored R
        # and B: measured on one still screen, |fast - screencap| was 14.4 with a channel flip
        # against 4.9 without, and the channel means matched exactly (fast R 61.4 = ref B 61.4).
        # Every hue-keyed check in the walk then read a warm-mirrored page -- blue buttons as
        # orange ones -- and the a26 run walked into the wrong tiles before its live even started.
        # The copy is what makes the lock brief: callers hold pixels that no later capture can
        # scribble on, and the stamp stays honest because it is taken before the DLL does anything.
        img = register(_conv[::-1, :, :3].copy())
        _note_fresh(img)
    return t, img


def source(timeout=0.25):
    """Drop-in for detect.frames' SOURCE contract: (stamp, RGB)."""
    return frame()


if __name__ == "__main__":
    from PIL import Image

    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from detect import capture

    install()
    t0 = time.perf_counter()
    ts = []
    for i in range(60):
        t, img = frame()
        ts.append(t)
    dt = np.diff(ts)
    print(f"60 frames in {time.perf_counter() - t0:.2f}s: "
          f"median {np.median(dt)*1000:.1f} ms, max {dt.max()*1000:.1f} ms")
    Image.fromarray(img).save("research/mumucap_fast.png")

    ref = capture()[:, :, :3]
    Image.fromarray(ref).save("research/mumucap_ref.png")
    diff = np.abs(img.astype(int) - ref.astype(int)).mean()
    print(f"mean |fast - screencap| = {diff:.1f} (same scene: single-digit)")
    uninstall()
