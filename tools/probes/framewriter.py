"""HUD 的「证据帧」与「判定物序号」不许站在采样线程上。

`HudWatch` 的采样线程决定一件事：游戏右上角那几个计数器跳了没有，以及因此 -- 断 AP 什么时候被发现。
它自己只有 ~10 ms 一帧，而两件"顺手"的事把它的节奏吃掉了两个数量级：每提交一个事件要 PNG 编码一张
1280×720（libpng 默认级 **89 ms**），再读一次判定物序号（`hudread.counters_arr` 把五个数字框对每个
数码、每个位移各比一遍，**90 ms**）。s303 一局产了 245 张这样的帧：**约 36 s** 的看盘线程时间全花在
画图上面，而那正是它最该盯着屏幕的一局。

这不是新病：#115 记的是 edge 闸门在一局里连弃 24 个真 GREAT、断 AP 晚 10 秒。当时归因给闸门，闸门
确实修了；这一条是同一形状的第二个因 -- **采样线程被证据编码饿住**。

所以编码与读数搬进了一个写手线程，PNG 顺手降到 level 1（89 → 35 ms，文件 0.64 → 1.00 MB，无损）。
日志行的顺序没有变：一个 FIFO 队列配一个读者，行仍按判定先后出，`dropmap` 就按这个顺序回放。

PART 1: 采样侧一次 `_commit`/`_reject` < 5 ms，并且 PIL 的 save 一次都不发生在采样线程上。
PART 2: level 1 无损在这里有意义 -- 写出来的帧逐位等于交进去的帧，序号读出来也一样。
PART 3: 行里点名的文件必须已经存在（把 save 拖慢来验），且行序 = 交件序。
PART 4: 牙齿：把老写法（编码 + 读数都在采样线程）当场量一遍，它必须比现在贵 20 倍以上，否则这个
        文件守着的数字不值一提。
PART 5: 写手没起/已死：不产幻影行（否则 dropmap 会按行去找不存在的帧），`undrawn` 记数。
PART 6: 快采的新鲜度记账（离线）：指纹必须远便宜于 9 ms 的捕获，且"同一张图"要能让计数一直长、
        "换了一张"要能归零。
PART 7: 看盘线程在停更时说话、在正常时闭嘴，且按节流出声（#115 的形状：静默被读成干净）。
PART 8: 中间那段接线：拿假的厂商调用驱动真的 `frame()`——它会一直返回合法尺寸、新时间戳的同一块
        缓冲，也就是"渲染器停了"本身。PART 6 与 PART 7 都碰不到这一层。
PART 9: 另一条真机快采入口（`run.py --host` 的 Windows.Graphics.Capture）在缺 `windows-capture`
        时必须**安静退回 adb 抓帧**（`detect.SOURCE` 留在原地），不许把一局打死。

Run from the repo root:  python tools/probes/framewriter.py
"""

import glob
import os
import queue
import shutil
import sys
import tempfile
import threading
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hudread                                 # noqa: E402
import hudwatch                                # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

BUDGET_MS = 5.0        # what one event may cost the thread that is watching the counters
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORPUS = os.path.join(ROOT, "research", "frames")


def a_frame():
    """A real committed HUD frame if the rolling window still has one; else a made-up picture.

    Real pixels matter for PART 2's ordinal -- a synthetic frame reads as nothing, which is still a
    fair equality test -- and the corpus is pruned, so this must not assume it is there.
    """
    black = np.zeros((720, 1280, 3), np.uint8)
    for p in sorted(glob.glob(os.path.join(CORPUS, "hud_*.png"))):
        try:
            im = np.asarray(Image.open(p).convert("RGB"))
        except (OSError, ValueError):
            continue
        if im.shape == black.shape:
            return im, os.path.basename(p)
    return black, "合成帧（全黑，语料已被滚动窗清掉）"


class TempFrames:
    """Point hudwatch's writer at a directory we own, so the probe leaves no evidence behind."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="framewriter_")

    def __enter__(self):
        self._real = hudwatch.subdir
        hudwatch.subdir = lambda *a, **k: self.dir
        return self.dir

    def __exit__(self, *exc):
        hudwatch.subdir = self._real
        shutil.rmtree(self.dir, ignore_errors=True)


def watch(lines, tag="probe"):
    """A HudWatch with only its writer thread running: no capture, no device, no live."""
    w = hudwatch.HudWatch(log=lines.append, tag=tag)
    w._q = queue.Queue()
    w._writer = threading.Thread(target=w._writer_loop, daemon=True)
    w._writer.start()
    return w


def part1(img):
    """Cost to the sampler, and proof that PNG encoding does not happen on its thread."""
    saved_on = []
    real_save = Image.Image.save
    main = threading.current_thread().name

    def spy(self, fp, *a, **k):
        saved_on.append(threading.current_thread().name)
        return real_save(self, fp, *a, **k)

    lines = []
    Image.Image.save = spy
    try:
        with TempFrames():
            w = watch(lines, "p1")
            t0 = time.perf_counter()
            for i in range(12):
                w._commit(1.0 + i, 1.01 + i, "GREAT", img)
                w._reject("edge", i, 2.0 + i, 2.01 + i, "GOOD", img)
            per = (time.perf_counter() - t0) / 24 * 1000
            w.stop()
    finally:
        Image.Image.save = real_save
    on_sampler = sum(1 for n in saved_on if n == main)
    ok = per < BUDGET_MS and on_sampler == 0 and len(saved_on) == 24
    print(f"PART 1 采样线程每事件 {per * 1000:.0f} µs（预算 {BUDGET_MS} ms）；24 个事件里编码发生了 "
          f"{len(saved_on)} 次、其中在采样线程上 {on_sampler} 次 -> {'PASS' if ok else 'FAIL'}")
    return ok


def part2(img, src):
    """What the writer puts on disk decodes back to the same pixels and reads back the same."""
    lines = []
    same = got = want = None
    size = 0.0
    with TempFrames() as d:
        w = watch(lines, "p2")
        w._commit(1.0, 1.01, "GREAT", img)
        w.stop()
        path = lines[0].split(" -> ")[-1] if lines else None
        if path and os.path.exists(path):
            back = np.asarray(Image.open(path).convert("RGB"))
            same = np.array_equal(back, img)
            want = hudread.ordinal(hudread.counters_arr(img))
            got = hudread.ordinal(hudread.counters_arr(back))
            size = os.path.getsize(path) / 1e6
    ok = bool(same) and want == got
    print(f"PART 2 用{src}：写出 {size:.2f} MB，逐位相同={same}；序号 原件={want} 副本={got} -> "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def part3(img):
    """A line may only name a file that already exists, and lines keep their hand-off order."""
    real_save = Image.Image.save

    def slow(self, fp, *a, **k):
        time.sleep(0.06)                   # a writer that cannot keep up must not get to speak first
        return real_save(self, fp, *a, **k)

    lines = []
    missing = []

    def on_line(s):
        lines.append(s)
        if not os.path.exists(s.split(" -> ")[-1]):
            missing.append(s)

    Image.Image.save = slow
    try:
        with TempFrames():
            w = watch(lines, "p3")
            w.log = on_line
            for i in range(6):
                w._commit(1.0 * i, 1.0 * i + 0.01, "GREAT", img)
            w.stop()
    finally:
        Image.Image.save = real_save
    n = [int(l.split("great")[-1].split(".")[0]) for l in lines]
    ok = not missing and len(lines) == 6 and n == sorted(n)
    print(f"PART 3 save 被拖到 60 ms：6 条行里先点名后落盘的 {len(missing)} 条；"
          f"行序 {n} -> {'PASS' if ok else 'FAIL'}")
    return ok


def part4(img):
    """Teeth: the old shape, measured here rather than asserted, and it has to stay expensive."""
    with tempfile.TemporaryDirectory() as d:
        t0 = time.perf_counter()
        for i in range(6):
            Image.fromarray(img).save(os.path.join(d, f"x{i}.png"))    # 默认级
            hudread.ordinal(hudread.counters_arr(img))                  # 序号也在这条线程上
        inline = (time.perf_counter() - t0) / 6 * 1000
    lines = []
    with TempFrames():
        w = watch(lines, "p4")
        t0 = time.perf_counter()
        for i in range(6):
            w._commit(1.0 * i, 1.0 * i + 0.01, "GREAT", img)
        now = (time.perf_counter() - t0) / 6 * 1000
        w.stop()
    ratio = inline / max(now, 0.001)
    ok = inline > 100.0 and now < BUDGET_MS
    print(f"PART 4 同样 6 个事件：老写法（编码+读数都在采样线程）{inline:.0f} ms/事件，现在 "
          f"{now * 1000:.0f} µs/事件，差 {ratio:.0f} 倍（判据：老 >100 ms 且新 <{BUDGET_MS} ms）-> "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def part5(img):
    """No writer: the frame is not written, and -- the part that matters -- no line is spoken."""
    lines = []
    w = hudwatch.HudWatch(log=lines.append, tag="p5")
    with TempFrames():
        w._commit(1.0, 1.01, "MISS", img)          # never started
        w.stop()                                   # started nothing, and must not now invent one
        w._commit(2.0, 2.01, "MISS", img)          # after stop(): the writer is gone
    ok = not lines and w.undrawn == 2 and w.n["MISS"] == 2
    print(f"PART 5 没有写手：日志行 {len(lines)} 条（必须 0，否则 dropmap 会去找不存在的帧）、"
          f"undrawn={w.undrawn}、事件照记 {w.tally()} -> {'PASS' if ok else 'FAIL'}")
    return ok


def part6():
    """The capture's own liveness bookkeeping, without a device.

    `_note_fresh` is what `stalled_s()` is read out of, and `_fingerprint` must stay far cheaper than
    the 9 ms capture it watches -- a watchdog that slows the thing it watches is worse than none.
    """
    import mumucap
    saved = dict(mumucap._stall)
    try:
        a = np.zeros((720, 1280, 3), np.uint8)
        b = a.copy()
        b[296, 592] = 255                                   # a pixel the stride does sample
        c = a.copy()
        c[300, 600] = 255                                   # one it does not
        mumucap._stall.update({"fp": None, "changed": None})
        t0 = time.perf_counter()
        for _ in range(400):
            mumucap._fingerprint(a)
        per = (time.perf_counter() - t0) / 400 * 1000
        first = mumucap._note_fresh(a)
        same = mumucap._note_fresh(a)
        grown = mumucap.stalled_s()
        time.sleep(0.05)
        after = mumucap.stalled_s()
        mumucap._note_fresh(b)
        reset = mumucap.stalled_s()
        time.sleep(0.05)
        mumucap._note_fresh(c)
        blind = mumucap.stalled_s() > reset
        # Same picture twice: the count keeps growing rather than restarting. A change where the
        # sample reaches: back to zero. A change sitting between sampled pixels: not movement -- the
        # price of a 0.8% fingerprint, and why the line it feeds says 暂停**或**停更 rather than
        # declaring the capture broken. During a LIVE it cannot matter: notes scroll the whole way
        # down between frames, so a real frame always moves sampled pixels.
        grows = same == first and after > grown and reset < 0.02 and blind
    finally:
        mumucap._stall.update(saved)
    ok = per < 1.0 and grows
    print(f"PART 6 指纹 {per:.3f} ms/帧（捕获本身 9 ms，判据 <1）；同一帧计数在长 {after > grown}、"
          f"格点上的变化归零 {reset < 0.02}、单像素盲点仍在长 {blind} -> "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def part7(img):
    """What the watcher says when the capture stops delivering: one line, and none when it's fresh."""
    import mumucap
    box = {"stalled": 0.0}

    class Fake:
        @staticmethod
        def frame():
            return time.perf_counter(), img

        @staticmethod
        def stalled_s():
            return box["stalled"]

    sys.modules["mumucap"] = Fake()          # hudwatch imports it by name, inside its loop
    lines = []
    said = []
    try:
        hudwatch.STALL_LOG_S, hudwatch.STALL_SAY_S = 0.2, 0.4
        with TempFrames():
            for stall in (5.0, 0.0):
                box["stalled"] = stall
                lines = []
                w = hudwatch.HudWatch(log=lines.append, tag="p7")
                w._q = queue.Queue()
                w._writer = threading.Thread(target=w._writer_loop, daemon=True)
                w._writer.start()
                th = threading.Thread(target=w._run, args=(0.0,), daemon=True)
                th.start()
                time.sleep(1.0)
                w._stop.set()
                th.join(2.0)
                w.stop()
                said.append(sum(1 for l in lines if "没给过新帧" in l))
    finally:
        sys.modules["mumucap"] = mumucap
        hudwatch.STALL_LOG_S, hudwatch.STALL_SAY_S = 2.0, 10.0
    ok = said[0] >= 2 and said[1] == 0
    print(f"PART 7 停更 5 s 的看盘在 1 s 里说了 {said[0]} 次（按 0.4 s 节流，判据 >=2），"
          f"帧一直在更新的看盘说了 {said[1]} 次（必须 0）-> {'PASS' if ok else 'FAIL'}")
    return ok


def part8():
    """The wiring, on a fake DLL: a renderer that stops writing must be the thing we detect.

    PART 6 tests the bookkeeping and PART 7 the line it feeds; this is the one in between that
    neither reaches -- `frame()` has to *call* the bookkeeping on the buffer the vendor call filled.
    A stubbed `nemu_capture_display` that writes nothing is a stalled renderer, and the only way to
    see it is the one this probe exists to defend.
    """
    import ctypes

    import mumucap
    saved = (mumucap._handle, mumucap._display, mumucap._conv, dict(mumucap._stall), mumucap._load)
    buf = np.empty((mumucap.H, mumucap.W, 4), np.uint8)      # what install() allocates
    state = {"writes": True, "v": 0}

    class FakeDll:
        def nemu_capture_display(self, h, d, size, w, hh, out):
            if state["writes"]:
                state["v"] = (state["v"] + 1) % 250
                ctypes.memset(out, state["v"], size)
            w._obj.value = mumucap.W
            hh._obj.value = mumucap.H
            return 0

    try:
        mumucap._handle, mumucap._display, mumucap._conv = 1, 0, buf
        mumucap._stall.update({"fp": None, "changed": None})
        mumucap._load = lambda: FakeDll()
        moved = [mumucap.frame() for _ in range(4)]
        flowing = max(mumucap.stalled_s() for _ in range(3))
        state["writes"] = False                       # the renderer goes quiet; the call still succeeds
        for _ in range(20):
            mumucap.frame()
        frozen = mumucap.stalled_s()
        shape = all(t > 0 and im.shape == (720, 1280, 3) for t, im in moved)
    finally:
        (mumucap._handle, mumucap._display, mumucap._conv,
         mumucap._stall["fp"], mumucap._stall["changed"],
         mumucap._load) = saved[0], saved[1], saved[2], saved[3]["fp"], saved[3]["changed"], saved[4]
    ok = shape and flowing < 0.05 and frozen > 0.05
    print(f"PART 8 假的厂商调用：帧形对了={shape}；它一直在写 -> stalled_s {flowing * 1000:.1f} ms，"
          f"它开始原样交回同一块缓冲 -> {frozen * 1000:.1f} ms（判据：前者贴 0、后者离开 0）-> "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def part9():
    """`run.py --host` 的快采入口缺依赖时，必须安静退回 adb 抓帧。

    `hostcap.install()` 抓不到 WGC 时返回 None、把 `detect.SOURCE` 留在原地（`None` = 走
    `detect.capture()`），`run.py` 里每个 `hc` 的用法都带 `is not None` 守卫 —— 三件事缺一条，
    `--host` 就会把一局打死，或者悄悄冻在一张旧帧上而日志一片安静。

    2026-10-06 起本机装了 windows-capture 2.0.1（`requirements.txt`），所以这里把
    `sys.modules["windows_capture"]` 毒成 None 来走一遍那条路：形状与真缺一模一样。
    """
    import detect
    import hostcap
    lines = []
    src0 = detect.SOURCE
    saved = sys.modules.get("windows_capture", _ABSENT)
    try:
        sys.modules["windows_capture"] = None       # import 它会失败
        hc = hostcap.install(log=lines.append)
    finally:
        if saved is _ABSENT:
            sys.modules.pop("windows_capture", None)
        else:
            sys.modules["windows_capture"] = saved
    quiet = hc is None and detect.SOURCE is src0
    said = bool(lines) and "screencap" in lines[0]
    print(f"PART 9 --host 缺 windows-capture：安静退回 adb={quiet}；日志说清楚了={said}"
          f"（{lines[0] if lines else '一句没说'}）-> {'PASS' if quiet and said else 'FAIL'}")
    return quiet and said


def part10():
    """`--host` 的两条硬要求：颜色要接回设备像素，盲区要盖住判读边（纯函数，离线）。

    MuMu 有时把自己整幅视图压暗约 10 级 —— WGC 抓得到、screencap 抓不到 —— 而 `detect.py` 的阈值
    全是绝对值，所以 `hostcap` 拿一张对齐的 screencap 量出 `device ~ a*host + b`，用 256 项表补回
    去。这里用合成帧驱动真函数：恒等不建表、压暗要建表且补完逐像素接近设备（**方向**对了才可能，
    反着装表会把帧压得更暗）、另一块屏幕那种离谱映射不许建表拿来掩盖。另一半是 `READ_W`：它必须
    盖住 `detect` 最宽的判读边，否则 MuMu 自己的侧栏会进判读。
    """
    import cv2
    import numpy as np

    import compile as G
    import hostcap

    yy, xx = np.mgrid[0:720, 0:1280]
    dev = np.clip(np.stack([(xx * 0.19 + yy * 0.07) % 200 + 20,
                            (xx * 0.05 + yy * 0.23) % 180 + 30,
                            (xx * 0.11 - yy * 0.13) % 160 + 40], axis=2), 0, 255).astype(np.uint8)

    same = hostcap._color_lut(hostcap._color_fit(dev, dev)) is None
    dim = np.rint(np.clip(dev.astype(np.float64) * 0.92 - 11, 0, 255)).astype(np.uint8)
    fits = hostcap._color_fit(dim, dev)
    lut = hostcap._color_lut(fits)
    slope = all(abs(a - 1 / 0.92) < 0.01 for a, b in fits)
    if lut is None:
        err = float("inf")
    else:
        err = float(np.abs(cv2.LUT(dim, lut).astype(np.int16) - dev.astype(np.int16)).mean())
    wild = hostcap._color_lut(
        hostcap._color_fit(np.clip(dev.astype(np.float64) * 0.3, 0, 255).astype(np.uint8),
                           dev)) is None
    widest = G.EDGE_RIGHT_AT_0 + G.EDGE_SLOPE * G.JUDGE_Y
    covered = widest < hostcap.READ_W
    # The bound that actually binds is the mask every detector ANDs with: `field_mask()` is clipped
    # to the scanned rows, so its right edge is 1116, not the trapezoid's 1157.7 at JUDGE_Y. Pin both
    # -- widen the scan or the trapezoid and this number moves, which is the warning that READ_W has
    # to move with it.
    import detect

    cols = np.nonzero(detect.field_mask().any(axis=0))[0]
    real_widest = int(cols.max())
    real_covered = real_widest < hostcap.READ_W
    ok = same and lut is not None and slope and err < 1.2 and wild and covered and real_covered
    print(f"PART 10 --host 的颜色自检与盲区：恒等不建表={same}；压暗建表={lut is not None}"
          f"（斜率对={slope}，补完平均差 {err:.2f} 级，判据 <1.2）；离谱映射被拒={wild}；"
          f"READ_W={hostcap.READ_W} 盖住梯形最宽边 {widest:.1f}={covered}、"
          f"也盖住 field_mask 的真实右界 {real_widest}={real_covered} -> "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def part11():
    """`--host` 什么时候装：单独给时开局就装，和 `--fastcap` 一起给时**推迟**到 SDK 失败那一刻。

    钉的是一次真实的误报：`hostcap.install()` 会把模拟器窗口调到客户区 1312×782（那是让设备面
    1:1 的必要动作），所以「优先 SDK、SDK 挂了再走窗口抓帧」这种用法在 SDK 正常的那一局不该去动
    用户的窗口。三件事按源码文本认：开局的 guard 带 `not args.fastcap`；`hostcap.install(log=log)`
    恰好两次（开局那次 + SDK 失败那一支）；失败分支两条日志各自点名**当前真正在用的源** —— 旧文案
    一律说「回落到 screencap」，在 `--host` 已经装好时是错的。牙：把那半句 guard 摘掉，判据必须
    变假（它正是这次改动之前的样子）。
    """
    import io as _io

    src = _io.open(os.path.join(ROOT, "tools", "run.py"), encoding="utf-8").read()

    def holds(text):
        return (text.count("if args.host and not args.fastcap:") == 1
                and text.count("hostcap.install(log=log)") == 2
                and "nonlocal hc" in text
                and "本局改用 --host 的窗口抓帧" in text
                and "整局回落到 screencap" in text)

    good = holds(src)
    tooth = holds(src.replace("if args.host and not args.fastcap:", "if args.host:"))
    ok = good and not tooth
    print(f"PART 11 --host 的安装时机：开局 guard 带 `not args.fastcap`={good}；"
          f"牙（摘掉那半句后判据必须变假）={not tooth} -> {'PASS' if ok else 'FAIL'}")
    return ok


def part12():
    """`--host` 动过的两处帧外状态：用户的窗口（必须还原）、侧栏那 40 列（必须补齐）。

    两件都**离线**验，不用开窗口：给 `find_surface` 一套假的桌面（`surfaces`/`_rect`/
    `_client_size`/`user32`），给 `HostCapture` 一个假的 `_ctl` 与一帧假 buffer，直接调真代码。

    钉的三件事：
      1. 插件已经是 1280x720 的窗口**一次都不许动**（这是「不打扰用户」的前提）；
      2. 插件被缩过时按缺额调窗口，并把**原始矩形**记进 `undo` —— 只记一次（同一个 `undo`
         列表复用、循环重试都不许重复追加），`undo=None` 时照样能适配；
      3. `stop()` 按记录的矩形还原窗口、第二次调用不再动；`grab()` 把 `_fill` 贴回
         `[:, READ_W:]`，`_fill=None` 时一个像素都不改（这是牙：判据必须能变假）。
    """
    import threading

    import numpy as np

    import hostcap

    lines: list[str] = []

    class FakeUser32:
        """只记 SetWindowPos 的调用；ScreenToClient 把插件位置定在客户区 (3,25)。"""

        def __init__(self):
            self.calls = []

        def ScreenToClient(self, hwnd, ref):
            ref._obj.x, ref._obj.y = 3, 25

        def GetSystemMetrics(self, i):
            return 3840 if i == 0 else 2160      # 够大，别让 nx/ny 被屏幕边缘夹掉

        def SetWindowPos(self, hwnd, after, x, y, w, h, flags):
            self.calls.append((hwnd, x, y, w, h, flags))

    fake = FakeUser32()
    saved = (hostcap.user32, hostcap.surfaces, hostcap._rect, hostcap._client_size)
    # 插件尺寸是这块假桌面的状态：MuMu 实测行为是「窗口够大之后插件就正好 1:1」
    # （客户区 1312x782 时插件 1280x720），所以 SetWindowPos 之后把状态翻过去。
    state = {"plug": (1247, 701)}
    hostcap.user32 = fake
    hostcap._rect = lambda _hwnd: (1277, 0, 1287, 767)
    hostcap._client_size = lambda _hwnd: (1277, 762)
    hostcap.surfaces = lambda: [(111, (3, 25) + state["plug"])]
    try:
        def resize_to_1x1(hwnd, after, x, y, w, h, flags):
            fake.calls.append((hwnd, x, y, w, h, flags))
            state["plug"] = (1280, 720)

        fake.SetWindowPos = resize_to_1x1

        # (1) 已经 1:1 的窗口：不动
        state["plug"] = (1280, 720)
        undo: list = []
        loc = hostcap.find_surface(log=lambda _m: None, undo=undo)
        untouched = loc == (111, 3, 25) and fake.calls == [] and undo == []

        # (2) 插件 1247x701：按缺额调到客户区 1312x783，原矩形记一次
        state["plug"] = (1247, 701)
        loc2 = hostcap.find_surface(log=lambda _m: None, undo=undo)
        want_call = (111, 1277, 0, 1312 + 10, 783 + 5, 0x14)
        fitted = (loc2 == (111, 3, 25) and fake.calls == [want_call]
                  and undo == [(111, 1277, 0, 1287, 767)])

        # 同一个 undo 再来一遍：还是要调窗口，但**不许**再记一条原矩形
        state["plug"] = (1247, 701)
        hostcap.find_surface(log=lambda _m: None, undo=undo)
        once = len(undo) == 1 and len(fake.calls) == 2

        # 不传 undo：照样适配，只是没人记账
        state["plug"] = (1247, 701)
        loc4 = hostcap.find_surface(log=lambda _m: None)
        optional = loc4 == (111, 3, 25) and len(fake.calls) == 3

        # (3) stop() 还原窗口；第二次是空操作
        fake.calls.clear()
        stopped: list = []

        class Ctl:
            def stop(self):
                stopped.append(1)

        class Cap:
            pass

        cap = Cap()
        cap._ctl, cap._log = Ctl(), lines.append
        cap._undo = [(111, 1277, 0, 1287, 767)]
        hostcap.HostCapture.stop(cap)
        restore = (fake.calls == [(111, 1277, 0, 1287, 767, 0x14)] and cap._undo == []
                   and stopped == [1])
        hostcap.HostCapture.stop(cap)
        idle = len(fake.calls) == 1

        # (4) grab() 把侧栏那 40 列贴成设备像素；_fill=None 时不许改像素
        buf = np.zeros((720, 1280, 4), np.uint8)
        buf[:, :, 0], buf[:, :, 1], buf[:, :, 2], buf[:, :, 3] = 10, 20, 30, 255

        class Frame:
            frame_buffer = buf
            timespan = 12345

        class Grab:
            pass

        g = Grab()
        g._lock, g.sx, g.sy, g._map, g._lut = threading.Lock(), 0, 0, (0.0, 12345), None
        g._time = lambda arrival, span: hostcap.HostCapture._time(g, arrival, span)
        g._raw = (1.0, 12345, Frame())
        g._fill = np.full((720, 40, 3), 7, np.uint8)
        _t, filled_img = hostcap.HostCapture.grab(g, timeout=0.05)
        rgb = np.array([30, 20, 10], np.uint8)
        filled = bool((filled_img[:, 1240:] == 7).all() and (filled_img[:, :1240] == rgb).all())
        g._fill = None
        _t, plain_img = hostcap.HostCapture.grab(g, timeout=0.05)
        plain = bool((plain_img == rgb).all())
    finally:
        (hostcap.user32, hostcap.surfaces, hostcap._rect, hostcap._client_size) = saved

    ok = all((untouched, fitted, once, optional, restore, idle, filled, plain))
    print(f"PART 12 --host 的窗口记账与侧栏补齐：插件 1:1 时不动窗口={untouched}；"
          f"按缺额适配并记下原矩形={fitted}；同一个 undo 只记一次={once}；"
          f"不传 undo 也能适配={optional}；stop() 还原={restore}；第二次 stop() 空操作={idle}；"
          f"侧栏 40 列贴上设备像素={filled}；_fill=None 时逐像素不动={plain} -> "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


_ABSENT = object()


def main():
    img, src = a_frame()
    print(f"证据帧 {img.shape} 来自 {src}；PNG level={hudwatch.FRAME_PNG_LEVEL}\n")
    parts = [part1(img), part2(img, src), part3(img), part4(img), part5(img), part6(), part7(img),
             part8(), part9(), part10(), part11(), part12()]
    print("\nframewriter " + ("PASS" if all(parts) else "FAIL"))
    return 0 if all(parts) else 1


if __name__ == "__main__":
    sys.exit(main())
