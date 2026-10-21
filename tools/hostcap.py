"""Grab LIVE frames from the MuMu window on this desktop instead of over adb.

`screencap` costs ~274 ms and does not parallelise (the readback is serialised in the emulator), so
the anchor loop sees ~3.6 frames per second. That is what limits how early the song clock can be
locked: the first note is on screen for barely a second, and at 3.6 fps only ~4 samples of it exist
before it is due. Windows.Graphics.Capture on the emulator's own window delivers the same pixels on a 16.7 ms median callback interval
-- 60 fps at the source, measured -- keeps working when the window is covered, and needs no agent on
the device.

The catch is that WGC captures the whole emulator window, chrome included, while every constant in
`detect.py` is in device pixels. MuMu paints the device into a `nemuwin` child window and sizes that
plug to whatever room the window gives it, so on a small window it *scales* the device -- pixel-exact
reads need the plug to be exactly 1280x720. `find_surface()` locates the plug and grows the window
until it is, and `HostCapture` then lines the plug's offset up against a single `screencap` and
refuses to start if the two disagree, so the surface is located by measurement, never by guessing at
a title-bar height. That same comparison measures the colour map between the two paths -- MuMu
sometimes paints its own view a little darker than the device framebuffer is, and every threshold in
`detect.py` is absolute -- and undoes it with a lookup table.

Growing the emulator window until the plug is 1:1 changes the user's desktop, so `stop()` puts the
window back the way it found it. The columns MuMu's own side panel covers are replaced with the
device's own pixels from that same screencap, so the frames handed out are whole device frames;
those 40 columns are frozen at verification time, and they sit outside every read band `detect.py`
uses, so this is about frames that are whole, not about the judgement.
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

import cv2
import numpy as np

user32 = ctypes.windll.user32

# How many of the surface's columns the game is actually read from. MuMu paints its own side panel
# over the right edge of the `nemuwin` plug, and no read can reach it: every detector masks with
# `detect.field_mask()`, which is the trapezoid inset 12 px and clipped to the scanned rows
# (TOP_SCAN..BOTTOM_SCAN = 55..535). Measured on the committed 1280x720 frames that mask spans
# columns 168..1116 and holds 0 px beyond 1116 -- the rightmost note pixel was 1109, the rightmost
# sprite bar 1078 -- so 1240 leaves a 124 px margin. The wider trapezoid bound (1158 at JUDGE_Y=570)
# is why this is not simply "the widest band edge".
READ_W = 1240


def _windows():
    """Top-level windows as (hwnd, client_top_left, client_size, class, title)."""
    user32.SetProcessDPIAware()
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            r = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            p = wintypes.POINT(0, 0)
            user32.ClientToScreen(hwnd, ctypes.byref(p))
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            n = user32.GetWindowTextLengthW(hwnd)
            tit = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, tit, n + 1)
            out.append((hwnd, (p.x, p.y), (r.right, r.bottom), cls.value, tit.value))
        return True

    user32.EnumWindows(cb, 0)
    return out


def _class_of(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _rect(hwnd):
    """(left, top, width, height) in screen coordinates, chrome included."""
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def _client_size(hwnd):
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return r.right, r.bottom


def surfaces():
    """Every `nemuwin` plug on the desktop as (parent hwnd, plug rect)."""
    out = []
    for hwnd, _origin, _size, _cls, _title in _windows():
        for child in _children(hwnd):
            if _class_of(child) == "nemuwin":
                out.append((hwnd, _rect(child)))
    return out


def _color_fit(px, ref):
    """Least-squares per-channel (slope, offset) taking a host frame to the device's own pixels.

    Two moments and a covariance per channel -- `a` is cov(x, y) / var(x) and `b` is mean(y) -
    a * mean(x) -- so there is no matrix work over 2.7 M pixels.
    """
    x = px.astype(np.float64)
    y = ref.astype(np.float64)
    out = []
    for c in range(3):
        xc, yc = x[:, :, c].ravel(), y[:, :, c].ravel()
        vx = xc.var()
        if vx <= 0.0:                   # a flat channel carries no slope information at all
            out.append((1.0, 0.0))
            continue
        a = ((xc * yc).mean() - xc.mean() * yc.mean()) / vx
        out.append((float(a), float(yc.mean() - a * xc.mean())))
    return tuple(out)


def _color_lut(fits, max_off=0.03, max_shift=8.0):
    """A 256-entry table undoing `fits`, or None when the two paths already agree.

    The guards are what make this safe to apply to every frame: a map that is not near identity is
    left unapplied, and `_verify` then judges the capture on its own terms; a map that is wilder than
    any display difference (the fit latched onto a different screen) is refused here so that a broken
    capture can never be papered over by a lookup table.
    """
    if not all(0.5 <= a <= 1.5 and abs(b) <= 60.0 for a, b in fits):
        return None
    if all(abs(a - 1.0) <= max_off and abs(b) <= max_shift for a, b in fits):
        return None
    vals = np.arange(256, dtype=np.float64)
    return np.rint(np.stack([np.clip(a * vals + b, 0, 255) for a, b in fits], axis=1)).astype(
        np.uint8).reshape(1, 256, 3)


def find_surface(w=1280, h=720, fit=True, log=print, undo=None):
    """Locate the device surface: (window to capture, x, y of the surface in its client area).

    `nemuwin` is the Qt plug MuMu paints the device framebuffer into, and it is the only thing on
    this desktop that knows where the surface is -- the window around it is chrome. MuMu keeps the
    plug at the device aspect ratio but fits it to the room it is given, so anything but an exact
    w x h plug means the device is being scaled and a pixel-exact read is impossible. `fit` grows the
    window by the shortfall, which only changes how the emulator displays, never the device itself
    (MuMu 15 here: 1277x762 client -> 1247x701 plug -> 1310x781 client -> 1280x720 plug).

    Growing the window is a change to the user's desktop, so the original rect is appended to `undo`
    (a caller-owned list) before the first resize and `HostCapture.stop()` puts it back. A window
    that is already 1:1 is never touched, so `undo` stays empty and stopping changes nothing.
    """
    for _attempt in range(4):
        for hwnd, (l, t, cw, ch) in surfaces():
            if (cw, ch) == (w, h):
                p = wintypes.POINT(l, t)
                user32.ScreenToClient(hwnd, ctypes.byref(p))
                return hwnd, p.x, p.y
        if not fit:
            return None
        plugs = surfaces()
        if not plugs:
            return None
        hwnd, (_l, _t, cw, ch) = plugs[0]
        ox, oy, ow, oh = _rect(hwnd)
        gw, gh = _client_size(hwnd)
        bx, by = ow - gw, oh - gh           # the chrome WGC leaves out of the client area
        nw, nh = gw + (w - cw) + 2, gh + (h - ch) + 2
        if undo is not None and not undo:
            undo.append((hwnd, ox, oy, ow, oh))         # for `stop()` to put back
        nx = max(0, min(ox, user32.GetSystemMetrics(0) - (nw + bx)))
        ny = max(0, min(oy, user32.GetSystemMetrics(1) - (nh + by)))
        log(f"host capture: the emulator paints the device into a {cw}x{ch} plug, so this window is "
            f"scaling it; resizing to a {nw}x{nh} client area for a 1:1 {w}x{h} surface")
        user32.SetWindowPos(hwnd, 0, nx, ny, nw + bx, nh + by, 0x0004 | 0x0010)  # NOZORDER|NOACTIVATE
        time.sleep(0.5)
    return None


def _children(hwnd):
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(child, _):
        out.append(child)
        return True

    user32.EnumChildWindows(hwnd, cb, 0)
    return out


class HostCapture:
    """The newest emulator frame, in device coordinates, stamped with when it was composed.

    `Frame.timespan` is the capture system's own monotonic clock in microseconds and, like
    `time.perf_counter`, it is QueryPerformanceCounter on Windows, so the two line up on a single
    affine map. Stamping by that instead of by arrival matters more than it looks: a14 locked the
    clock through a 30/60 fps hiccup, arrival times said the song started ~150 ms later than it
    did, and every press after that was 150 ms slow.
    """

    def __init__(self, log=print, verify=True):
        import windows_capture

        self._undo = []         # window rects `find_surface` had to move, restored in `stop()`
        self._log = log
        loc = find_surface(log=log, undo=self._undo)
        if loc is None:
            raise RuntimeError("no MuMu window with a 1280x720 `nemuwin` surface is open")
        hwnd, cx, cy = loc
        self.sx, self.sy = cx, cy
        self._lut = None        # colour map to the device, once `_verify` has measured one
        self._fill = None       # device pixels for the columns the emulator's own panel covers
        self.n = 0
        self._lock = threading.Lock()
        self._raw = None
        self._map = None
        self._last_span = None
        self.stalls = 0
        self.worst = 0.0

        cap = windows_capture.WindowsCapture(window_hwnd=hwnd, cursor_capture=False)
        outer = self

        @cap.event
        def on_frame_arrived(frame, ctrl):
            # The buffer is a view on a mapping this Frame owns, so holding the reference is safe;
            # copying 2.7 MB per frame in the capture thread would cap us well below 30 fps.
            #
            # Gaps have to be counted HERE, between deliveries. Counting them between polls, as a
            # first version did, just measures how busy the firing loop was and reported 76 s of
            # "lost capture" on a run that had only polled sparsely.
            span = frame.timespan
            if outer._last_span is not None:
                gap = (span - outer._last_span) / 1e7
                if gap > 0.08:
                    outer.stalls += 1
                    outer.worst = max(outer.worst, gap)
            outer._last_span = span
            with outer._lock:
                outer._raw = (time.perf_counter(), span, frame)
                outer.n += 1

        @cap.event
        def on_closed():
            pass

        self._ctl = cap.start_free_threaded()
        # WGC returns the client area plus the border DWM draws around it, so the plug's client
        # offset falls short of the surface position in the capture frame by that border. Measure it
        # off the first frame instead of assuming a title bar height.
        fh, fw = self._probe_frame().frame_buffer.shape[:2]
        cw, ch = _client_size(hwnd)
        self.sx, self.sy = cx + max(0, (fw - cw) // 2), cy + max(0, (fh - ch) // 2)
        log(f"host capture: hwnd={hwnd} frame {fw}x{fh} client {cw}x{ch} surface at "
            f"({self.sx},{self.sy})")
        if verify:
            self._verify(log)

    def _probe_frame(self, timeout=2.0):
        """The newest raw frame, nothing sliced -- the surface offset is not known yet."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            with self._lock:
                raw = self._raw
            if raw is not None:
                return raw[2]
            time.sleep(0.005)
        raise RuntimeError("the emulator window delivered no frames")

    def _verify(self, log, radius=6, limit=0.20):
        """Line the frame up with a screencap, and refuse to run if the two disagree.

        The border arithmetic above is a guess about how this Windows build composes a window into a
        capture frame; a screencap is ground truth. `limit` is deliberately loose -- the emulator
        keeps animating between the two grabs, so a few percent of the read columns legitimately
        differ -- while still catching the case that matters, a frame that is not this device at all.
        """
        from detect import capture

        # Same channel convention as `grab()`: WGC hands back BGRA, a screencap is RGBA, and a
        # comparison across the two orders differs on every pixel that is not grey.
        img = np.ascontiguousarray(self._probe_frame().frame_buffer[:, :, :3][:, :, ::-1])
        shot = capture()
        if shot.shape[:2] != (720, 1280):
            raise RuntimeError(f"screencap came back {shot.shape[1]}x{shot.shape[0]}, not 1280x720")
        adb = np.ascontiguousarray(shot[:, :, :3])
        x0, y0 = self.sx, self.sy
        xlo, ylo = max(0, x0 - radius), max(0, y0 - radius)
        xhi, yhi = min(img.shape[1] - 1280, x0 + radius), min(img.shape[0] - 720, y0 + radius)
        if xhi < xlo or yhi < ylo:
            raise RuntimeError(f"the capture frame is {img.shape[1]}x{img.shape[0]}, too small for a "
                               f"1280x720 surface at ({x0},{y0})")
        res = cv2.matchTemplate(img[ylo : yhi + 720, xlo : xhi + 1280], adb, cv2.TM_SQDIFF)
        _mn, _mx, loc, _pt = cv2.minMaxLoc(res)
        mx, my = xlo + loc[0], ylo + loc[1]
        px = img[my : my + 720, mx : mx + 1280]
        # MuMu sometimes paints its whole view a little darker than the device framebuffer actually
        # is -- its side panel is not the only overlay it owns -- and every threshold in `detect.py`
        # is absolute, so measure the colour map between the two and undo it. Fitted, not guessed:
        # `_color_lut` only hands back a table for a map that is close to identity.
        fits = _color_fit(px, adb)
        lut = _color_lut(fits)
        if lut is not None:
            self._lut = lut
            px = cv2.LUT(px, lut)
        d = cv2.absdiff(px, adb).max(2)
        # MuMu paints its own side panel over the right edge of the surface, so only the columns the
        # game is read from have to agree; whatever the panel covers is reported, not counted.
        bad = float((d[:, :READ_W] > 16).mean())
        if bad > limit:
            raise RuntimeError(f"host frames do not match the device ({bad * 100:.1f}% of the read "
                               f"columns differ, colour map "
                               + ", ".join(f"{nm} x{a:.3f}{b:+.1f}"
                                           for nm, (a, b) in zip("RGB", fits))
                               + ") -- staying on screencap")
        if (mx, my) != (x0, y0):
            log(f"  host capture: the screencap puts the surface at ({mx},{my}), the window border "
                f"arithmetic guessed ({x0},{y0})")
        self.sx, self.sy = mx, my
        if lut is not None:
            log("  host capture: host frames read "
                + ", ".join(f"{nm} x{a:.3f}{b:+.1f}" for nm, (a, b) in zip("RGB", fits))
                + " against the device, and a lookup table undoes it")
        panel = int((d[:, READ_W:] > 16).sum())
        if panel:
            # Keep the device's own pixels for the columns MuMu paints over and paste them into
            # every frame `grab()` hands out. No read can reach those columns -- every detector masks
            # with `field_mask()`, whose right bound is column 1116 on the scanned rows -- so this is
            # not about the judgement, it is about frames that are WHOLE: saved evidence, a human
            # opening research/hostcap.png, any read added later. Measured over the 39 committed
            # 1280x720 device frames: covering columns 1240-1279 changes no read output at all
            # (a note-coloured patch inside the mask does change it, so that comparison is live).
            # The trade is one-way and worth naming: those 40 columns are frozen at the moment of
            # verification instead of showing the emulator's panel. A window with no panel over the
            # surface pastes nothing, so clean windows keep live pixels everywhere.
            self._fill = np.ascontiguousarray(adb[:, READ_W:])
            log(f"  host capture: {panel} px under the emulator's own side panel are covered in "
                f"host frames (columns {READ_W}-1279); the device's own pixels for those columns "
                f"are pasted into every frame from here on")
        log(f"  host capture: lined up against a screencap -- {(d == 0).mean() * 100:.2f}% identical, "
            f"{bad * 100:.3f}% of the read columns differ")

    def _time(self, arrival, span):
        if self._map is None:
            # Anchor the capture clock to perf_counter with one frame and trust the offset from
            # then on. Both are 100 ns ticks of the same hardware counter; measured over 603 frames
            # the two rates differ by 19 ppm, which is 1.7 ms across the whole song. Calibrating
            # the rate would spend the first second of the intro to save nothing, and a fit started
            # later would stamp the intro on one clock and the rest on another.
            self._map = (arrival, span)
            return arrival
        a, s0 = self._map
        return a + (span - s0) / 1e7

    def grab(self, timeout=0.25):
        """(frame time, RGB device frame), waiting for a frame that is not the last one handed out."""
        deadline = time.perf_counter() + timeout
        last = None
        while time.perf_counter() < deadline:
            with self._lock:
                last = self._raw
            if last is not None and last[0] > getattr(self, "_seen", 0.0):
                break
            time.sleep(0.002)
        if last is None:
            raise RuntimeError("no frames from the emulator window")
        arrival, span, frame = last
        self._seen = arrival
        t = self._time(arrival, span)
        buf = frame.frame_buffer[self.sy : self.sy + 720, self.sx : self.sx + 1280, :3]
        rgb = np.ascontiguousarray(buf[:, :, ::-1])
        if self._lut is not None:
            rgb = cv2.LUT(rgb, self._lut)
        if self._fill is not None:
            rgb[:, READ_W:] = self._fill     # the columns the emulator's panel covers, frozen
        return t, rgb

    def stop(self):
        """Stop capturing, then put the emulator window back the way `find_surface` found it.

        Only a window that had to be resized is touched, so a run that starts on an already-1:1
        window leaves the desktop exactly as it was. A process that is killed skips this and can
        leave the window grown; it is only a window size, and the next run adopts whatever it finds.
        """
        try:
            self._ctl.stop()
        except Exception:
            pass
        for hwnd, ox, oy, ow, oh in self._undo:
            user32.SetWindowPos(hwnd, 0, ox, oy, ow, oh, 0x0004 | 0x0010)   # NOZORDER|NOACTIVATE
            self._log(f"host capture: the emulator window is back at {ow}x{oh} where it started")
        self._undo.clear()


def install(log=print):
    """Point detect.py's frame source at the emulator window, falling back to adb if it stops.

    The fallback matters because WGC only delivers while the window is rendering: minimise MuMu or
    close it and the callbacks stop, and a run that silently freezes on a stale frame is worse than
    one that drops to 3.6 fps.
    """
    import detect

    try:
        hc = HostCapture(log=log)
    except Exception as e:
        log(f"host capture unavailable ({type(e).__name__}: {e}) -- staying on adb screencap "
            f"(~3.6 fps; installing `windows-capture` turns on the WGC path)")
        return None
    fails = [0]

    def source(timeout=0.25):
        try:
            return hc.grab(timeout)
        except RuntimeError:
            fails[0] += 1
            if fails[0] in (1, 50):
                log(f"  host capture stalled {fails[0]}x, using screencap meanwhile")
            t = time.perf_counter()
            return t, detect.capture()[:, :, :3]

    detect.SOURCE = source
    return hc


def align(log=print):
    """Start a capture and report where it measured the surface (the once-a-run self-check)."""
    hc = HostCapture(log=log)
    log(f"surface {hc.sx},{hc.sy}")
    hc.stop()
    return hc.sx, hc.sy


if __name__ == "__main__":
    import sys

    from PIL import Image

    hc = HostCapture()
    time.sleep(0.5)
    t0 = time.perf_counter()
    k = 0
    fps = []
    while time.perf_counter() - t0 < 3.0:
        t, img = hc.grab()
        k += 1
        fps.append(t)
    d = np.diff(fps)
    print(f"{k} grabs in {fps[-1] - fps[0]:.2f}s -> {k / (fps[-1] - fps[0]):.1f} fps, "
          f"interval med {np.median(d) * 1e3:.1f} ms p90 {np.percentile(d, 90) * 1e3:.1f} ms")
    Image.fromarray(img).save("research/hostcap.png")
    hc.stop()
    sys.exit(0)
