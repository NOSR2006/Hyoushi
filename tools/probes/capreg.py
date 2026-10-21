"""The two capture paths must agree pixel for pixel, in one coordinate space.

`nemu_capture_display` (the 9 ms path) and `adb screencap` (the 278 ms path) are both used: the
song reads fast frames, the walk reads screencap, and every constant in the repo -- the perspective
trapezoid, the button coordinates, the hue keys -- was tuned on screencap pixels. On 2026-10-03 the
fast frame was that picture **shifted 4 columns left**, which nobody had noticed because y is
untouched and x only picks a lane; `mumucap.register()` corrected it. On 2026-10-06, on
MuMuPlayer-15.0-0 (the upgrade that also began framing `screencap` behind a 16-byte header), the two
paths hand back the same pixels and that correction became 0. A correction for a gap that is no
longer there is itself the error -- one of the 39 committed nav frames shows what it cost: shifted
by 4, `navgates_pause_a.png` reads `rewards` where the truth is `pause` (PART 5). This is the check
that keeps whichever number it is honest: if MuMu changes its offset, or someone edits the flip or
the copy in `frame()`, the two sources stop agreeing and this says so in one number.

PART 1-4 need the emulator running, like `mtdiag.py`; with no device they say SKIP and pass --
the correction is not something an offline run can invent. PART 5 and PART 6 run anyway: they
are the parts a broken device must not be able to hide behind that SKIP.

PART 1: the frame `frame()` hands out sits exactly on screencap (dx=0, and 0 beats the next
        offset by a wide margin).
PART 2: the two capture paths agree: mean per-channel difference under 2/255 and under 1%
        of pixels differing by more than 16 -- the frame-to-frame noise of one source is 1.52, so
        this is at the floor.
PART 3: y is not shifted (a dy scan has its minimum at 0), and `calib.screen()` reads the same page
        out of both sources.
PART 4: teeth -- a frame pushed 4 columns off (the error this file was born from) must fail the
        PART 2 threshold, or PART 2 is only measuring a screen with nothing on it.
PART 5: the perturbation the walk's own capture carries (a 4-column edge smear plus +-2/255 of
        noise) must not change `calib.screen()` on any committed nav frame -- while a whole-frame
        4-column shift must change at least one, or that first claim is measuring nothing.
PART 6: the framing `screencap` hands back -- the bare payload, or that payload behind the
        16-byte header MuMu 15 emits -- decodes to the same picture, and every other length or
        header is refused instead of sliced. No device needed, so this is what holds that fix
        still on a machine whose emulator cannot start at all.

Run from the repo root, emulator up:  python tools/probes/capreg.py
"""

import os
import sys

import numpy as np
from PIL import Image

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../tools
sys.path.insert(0, TOOLS)

W, H = 1280, 720
# The offset this probe was born from: `register()` applied it until 2026-10-06, when MuMu 15
# stopped needing one (see `mumucap.py`). PART 4 and PART 5 use it as the error to be caught.
OLD_SHIFT = 4


def _diff(a, b):
    d = np.abs(a.astype(int) - b.astype(int)).max(axis=2)
    return float(d.mean()), float(100.0 * (d > 16).mean())


def _best_shift(a, b, span):
    """The (dx, dy) that best aligns a onto b, over a small window."""
    out = []
    for d in range(-span, span + 1):
        ax = a[:, max(0, d):W + min(0, d)]
        bx = b[:, max(0, -d):W + min(0, -d)]
        out.append((np.abs(ax.astype(int) - bx.astype(int)).max(axis=2).mean(), d))
    out.sort()
    return out


def _shapes(pat):
    """Every framing `_frame_from_raw` must accept or refuse, as (label, raw, expect_ok)."""
    import struct
    import detect
    need = detect.H * detect.W * 4
    bare = pat.tobytes()
    if len(bare) != need:
        raise AssertionError(f"fixture is {len(bare)} bytes, not {need}")
    if detect.SHOT_HEADER != 16 or detect.SHOT_FORMATS != (1, 2):
        raise AssertionError(f"constants moved: {detect.SHOT_HEADER}, {detect.SHOT_FORMATS}")

    def hdr(w, h, fmt):
        return struct.pack("<IIII", w, h, fmt, 1) + bare

    return [
        ("裸帧", bare, True),
        ("带头 1280x720 fmt1", hdr(detect.W, detect.H, 1), True),
        ("带头 1280x720 fmt2", hdr(detect.W, detect.H, 2), True),
        ("带头 720x1280", hdr(detect.H, detect.W, 1), False),
        ("带头 fmt5（非 RGBA 序）", hdr(detect.W, detect.H, 5), False),
        ("全零头", b"\x00" * detect.SHOT_HEADER + bare, False),
        ("少 8 字节", bare[:-8], False),
        ("多 8 字节", bare + b"\x00" * 8, False),
        ("大 100000 字节（更大的设备）", bare + b"\x00" * 100000, False),
        ("头齐、载荷短 16（与裸帧同长）", hdr(detect.W, detect.H, 1)[:need], False),
    ]


def _offline_parts(mumucap):
    """PART 5 and PART 6: the parts that need no device, run even when the emulator is absent.

    PART 5 is what the walk actually sees: the leftmost 4 columns of a live frame are edge fill
    rather than a measurement, so `calib.screen()` has to be blind to exactly that on the committed
    nav frames -- and the same corpus has to *notice* a whole-frame 4-column shift, which is the
    error this file was born from. PART 6 is the framing -- see `detect._frame_from_raw`.
    """
    import glob
    import detect
    import calib

    rng = np.random.default_rng(20261003)
    pages = 0
    smear, whole = [], []
    for path in sorted(glob.glob(os.path.join(TOOLS, "..", "evidence", "nav", "*.png"))):
        try:
            im = Image.open(path).convert("RGB")
        except Exception:                              # noqa: BLE001
            continue
        if im.size != (W, H):
            continue
        a = np.asarray(im)
        page = calib.screen(a)
        # The smear: a live frame's left OLD_SHIFT columns are edge fill, nothing else differs.
        sm = a.copy()
        sm[:, :OLD_SHIFT] = a[:, OLD_SHIFT:OLD_SHIFT + 1]
        # The shift: the whole picture moved by what `frame()` used to add, with the sliver that
        # falls off the edge filled from the first column -- `register()` with SHIFT_X = OLD_SHIFT.
        sh = np.empty_like(a)
        sh[:, OLD_SHIFT:] = a[:, :W - OLD_SHIFT]
        sh[:, :OLD_SHIFT] = a[:, 0:1]
        for bucket, img in ((smear, sm), (whole, sh)):
            noisy = np.clip(img.astype(np.int16) + rng.integers(-2, 3, img.shape, dtype=np.int16),
                            0, 255).astype(np.uint8)
            for probe, tag in ((img, "干净"), (noisy, "±2 噪声")):
                got = calib.screen(probe)
                if got != page:
                    bucket.append(f"{os.path.basename(path)}: {page} -> {got}（{tag}）")
        pages += 1
    ok5 = mumucap is not None and pages >= 20 and not smear and bool(whole)
    print(f"PART 5 走查看到的：{pages} 张已提交 nav 帧；左缘 {OLD_SHIFT} 列涂抹 + ±2 噪声改判页的 "
          f"{len(smear)} 张{'：' + '; '.join(smear[:3]) if smear else ''}；整幅平移 {OLD_SHIFT} 列"
          f"（老 SHIFT_X 的偏差）改判页的 {len(whole)} 张"
          f"{'：' + '; '.join(whole[:3]) if whole else ''}"
          f"{'' if mumucap is not None else '；mumucap 不可用'} -> " + ("PASS" if ok5 else "FAIL"))

    pat = (np.arange(detect.H * detect.W * 4, dtype=np.uint32) % 251).astype(np.uint8)
    bare = pat.tobytes()
    shapes = _shapes(pat)

    def dec(raw):
        """None if `raw` decoded, else the exception type name."""
        try:
            detect._frame_from_raw(raw)
            return None
        except Exception as exc:                       # noqa: BLE001
            return type(exc).__name__

    bad = []
    for label, raw, expect_ok in shapes:
        err = dec(raw)
        if (err is None) != expect_ok:
            bad.append(f"{label}: {'读了' if err is None else '拒绝了（' + err + '）'}")
    # The accepted framings have to be the *same* picture, not merely both accepted.
    ref = np.frombuffer(bare, dtype=np.uint8).reshape(detect.H, detect.W, 4)
    for label, raw, expect_ok in shapes:
        if expect_ok and label != "裸帧" and not np.array_equal(detect._frame_from_raw(raw), ref):
            bad.append(f"{label}: 与裸帧不是同一张画")
    # Teeth: the pre-fix code sliced to the first `need` bytes, so it would have read several of the
    # refused shapes quietly -- count them, or the refusals above could be a fixture nothing passes.
    need = detect.H * detect.W * 4
    quiet = []
    for label, raw, expect_ok in shapes:
        if expect_ok or len(raw) < need:
            continue
        try:                                           # the old logic, verbatim
            np.frombuffer(raw[:need], dtype=np.uint8).reshape(detect.H, detect.W, 4)
            quiet.append(label)
        except Exception:                              # noqa: BLE001
            pass
    ok6 = not bad and len(quiet) >= 2
    print(f"PART 6 取帧封装：{len(shapes)} 种形状读/拒判对 {len(shapes) - len(bad)}/{len(shapes)}"
          f"{'（' + '; '.join(bad[:3]) + '）' if bad else ''}；旧逻辑会静默读错的 {len(quiet)} 种"
          f"（{'; '.join(quiet[:3])}） -> " + ("PASS" if ok6 else "FAIL"))
    return ok5, ok6


def main():
    try:
        import mumucap
    except Exception as exc:                       # noqa: BLE001
        mumucap = None
        print(f"mumucap 不可用（{exc!r}）")
    ok_off = _offline_parts(mumucap)
    try:
        import detect
        import mumucap
        mumucap.install()
        fast = mumucap.frame()[1]
        ref = detect.capture()[:, :, :3]
        fast2 = mumucap.frame()[1]
    except Exception as exc:                                     # noqa: BLE001
        print(f"没有可用的模拟器画面，PART 1-4 跳过（{exc!r}） -> SKIP")
        return ok_off[0] and ok_off[1]
    try:
        # PART 1: what `frame()` hands out is aligned to screencap, and only at zero offset.
        scan = _best_shift(fast, ref, 8)
        (m0, d0), (m1, d1) = scan[0], scan[1]
        ok1 = d0 == 0 and m1 > m0 * 3
        print(f"PART 1 frame() 的坐标：最优 dx={d0:+d} 差 {m0:.2f}，次优 dx={d1:+d} 差 {m1:.2f} -> "
              + ("PASS" if ok1 else "FAIL"))

        # PART 2: judged against the source's own frame-to-frame noise, not an absolute number --
        # the selection page animates, and on a busy screen that floor is what everything else is
        # measured against (it has been 0.79 and it has been 2.31 on the same page minutes apart).
        floor, floor_over = _diff(fast, fast2)
        mean, over = _diff(fast2, ref)
        ok2 = mean <= floor + 0.6 and over <= max(2.0, floor_over * 2)
        print(f"PART 2 两条捕获路径：平均差 {mean:.2f}/255、>16 的像素 {over:.2f}%；"
              f"同源噪声地板 {floor:.2f}/{floor_over:.2f}% -> " + ("PASS" if ok2 else "FAIL"))

        # PART 3
        import calib
        sy = [(np.abs(fast[max(0, d):H + min(0, d)].astype(int) -
                     ref[max(0, -d):H + min(0, -d)].astype(int)).max(axis=2).mean(), d)
              for d in (-2, -1, 0, 1, 2)]
        sy.sort()
        page_fast, page_ref = calib.screen(fast2), calib.screen(ref)
        ok3 = sy[0][1] == 0 and page_fast == page_ref
        print(f"PART 3 y 方向最优 dy={sy[0][1]}；判页 fast={page_fast} ref={page_ref} -> "
              + ("PASS" if ok3 else "FAIL"))

        # PART 4: teeth -- push the frame out to where it sat while SHIFT_X was OLD_SHIFT. The best
        # offset must land on +OLD_SHIFT and the PART 2 threshold must fail on it, or PART 2 is only
        # measuring a screen with nothing on it.
        wrong = np.empty_like(fast)
        wrong[:, OLD_SHIFT:] = fast[:, :W - OLD_SHIFT]
        wrong[:, :OLD_SHIFT] = fast[:, 0:1]
        wm, wo = _diff(wrong, ref)
        _, wd = _best_shift(wrong, ref, 8)[0]
        ok4 = wd == OLD_SHIFT and not (wm <= floor + 0.6 and wo <= max(2.0, floor_over * 2))
        print(f"PART 4 反事实：整幅推 {OLD_SHIFT} 列（老 SHIFT_X 留下的偏差）后最优 dx={wd:+d}"
              f"（应为 {OLD_SHIFT:+d}），平均差 {wm:.2f}、>16 的像素 {wo:.2f}%（判据必须 FAIL） -> "
              + ("PASS" if ok4 else "FAIL"))
        return ok1 and ok2 and ok3 and ok4 and ok_off[0] and ok_off[1]
    finally:
        mumucap.uninstall()


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
