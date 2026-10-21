"""Offline regression for the fire path's own hygiene: the two things that keep a 3000-action
song on time, plus the accounting that says when it was not.

Built 2026-10-19 (user m51116) out of a measurement rather than a hunch: over 12163 sampled
"400 actions" windows (~2000 rounds) `late p50` is 0.00 ms everywhere, but 1.9% of the windows
carry a `max` above 5 ms and the worst is 996.6 ms (`g340`) -- 45 ms of judgement slack gone in
one stall. Two of those three fixes are guards that a future refactor can silently undo, so they
are pinned here; the third is only accounting.

PART 1  `player.gc_guard`: `gc.collect()` -> `gc.freeze()` -> `gc.disable()` in that order, with
        `gc.enable()` in a `finally` -- the enable has to run even when the song raises, or a
        crashed round leaves the collector off for the rest of the process.
PART 2  `run.py` wraps its `play()` call in that guard (a guard nobody enters is decoration).
PART 3  the stall accounting: `STALL_MS == 5.0`, the hot loop compares `dt_ms` against it, the
        per-action line carries the chart time and `gc.get_count()`, and the summary reports the
        worst one -- that log line is how a stall gets told apart from "the host was busy".
PART 4  `mtouch.send_bytes`: the three touch primitives build their frame as bytes and hand it
        over in one call, while `send()` stays behind as the control arm. The control is judged
        by bytes, not by presence -- both arms are sent the same event and must produce the
        same payload.

Teeth (each must turn exactly one judgment false): `gc.disable()` -> `pass`; unwrapping the
`with player.gc_guard(...)` in run.py; `> STALL_MS` -> `> 1e9`; one primitive back on `send()`.

Usage: python tools/probes/firepath.py [--teeth]    (exit 0 = PASS)
"""
import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

import mtouch  # noqa: E402
import player  # noqa: E402

RUN = os.path.join(TOOLS, "run.py")


def _src(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def gc_order(text):
    """The three calls in order, and the enable inside a finally."""
    for name in ("gc.collect()", "gc.freeze()", "gc.disable()"):
        if name not in text:
            return False
    order = [text.index(n) for n in ("gc.collect()", "gc.freeze()", "gc.disable()")]
    if order != sorted(order):
        return False
    tail = text[text.index("gc.disable()"):]
    return "finally:" in tail and "gc.enable()" in tail


def wraps_play(text):
    """`with player.gc_guard(...)` must open a block around the `play(` call."""
    i = text.find("with player.gc_guard(")
    if i < 0:
        return False
    j = text.find("play(", i)
    if j < 0:
        return False
    line_start = text.rfind("\n", 0, j) + 1
    indent_open = len(text[line_start:]) - len(text[line_start:].lstrip())
    with_line = text[text.rfind("\n", 0, i) + 1:i]
    indent_with = len(with_line) - len(with_line.lstrip())
    # the play() call has to sit deeper than the `with` that guards it
    return indent_open > indent_with and text[j:j + 5] == "play("


def stall_accounting(text):
    body = text[text.index("for tm, op, slot, x, y in actions:"):]
    return ("STALL_MS = 5.0" in text
            and "if dt_ms > STALL_MS:" in body
            and "!! 迟发" in body
            and "gc.get_count()" in body
            and "迟发 > " in text)


def bytes_path(mt_src, touch_src):
    """All three primitives on the byte transport, and `send()` still there as the control."""
    if "def send_bytes(" not in mt_src or "def send(" not in mt_src:
        return False
    for name in ("touch_down", "touch_move", "touch_up"):
        i = touch_src.find("def " + name + "(")
        if i < 0:
            return False
        nxt = touch_src.find("\n    def ", i + 1)
        chunk = touch_src[i:nxt if nxt > 0 else len(touch_src)]
        if "self.send_bytes(" not in chunk:
            return False
        if 'b"d ' not in chunk and 'b"m ' not in chunk and 'b"u ' not in chunk:
            return False
    return True


class _Sink:
    """Both arms of the transport, recording what each was handed."""

    def __init__(self):
        self.frames = []
        self.lines = []

    def send_bytes(self, payload, nlines=1):
        self.frames.append(bytes(payload))

    def send(self, lines):
        self.lines.append("\n".join(lines).encode("ascii") + b"\n")


def same_bytes():
    """The hot path and the control arm must hand the transport the same bytes."""
    m = object.__new__(mtouch.MTouch)
    sink = _Sink()
    m.send_bytes = sink.send_bytes
    m.send = sink.send
    m.touch_down(1, 300, 400)
    m.touch_move(1, 301, 402)
    m.touch_up(1)
    sink.send(["d 1 300 400 %d" % mtouch.PRESSURE, "c"])
    sink.send(["m 1 301 402 %d" % mtouch.PRESSURE, "c"])
    sink.send(["u 1", "c"])
    return sink.frames == sink.lines and len(sink.frames) == 3


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    teeth = "--teeth" in argv
    player_src = inspect.getsource(player)
    run_src = _src(RUN)
    mt_src = inspect.getsource(mtouch)
    touch_src = mt_src

    checks = [
        ("gc_guard 三步顺序 + finally 里 enable", gc_order(player_src)),
        ("run.py 用 gc_guard 包住 play()", wraps_play(run_src)),
        ("迟发登记（STALL_MS=5 / !! 迟发 / gc.get_count / 汇总）", stall_accounting(player_src)),
        ("三条触摸原语走 send_bytes，send() 留作对照", bytes_path(mt_src, touch_src)),
        ("send_bytes 与 send 发同样的字节", same_bytes()),
    ]
    ok = True
    for label, good in checks:
        print(("  ok   " if good else "  FAIL ") + label)
        ok = ok and bool(good)

    if teeth:
        bare = player_src.replace("    gc.disable()\n", "    pass\n", 1)
        flat = run_src.replace("            with player.gc_guard(log=log):\n", "")
        flat = "\n".join(ln[4:] if ln.startswith("                ") else ln
                         for ln in flat.splitlines())
        loud = player_src.replace("if dt_ms > STALL_MS:", "if dt_ms > 1e9:", 1)
        slow = touch_src.replace('self.send_bytes(b"u %d\\nc\\n" % slot, 2)',
                                 'self.send([f"u {slot}", "c"])', 1)
        bites = [
            ("牙 gc.disable -> pass", not gc_order(bare), bare != player_src),
            ("牙 拆掉 with gc_guard", not wraps_play(flat), flat != run_src),
            ("牙 迟发门推到 1e9", not stall_accounting(loud), loud != player_src),
            ("牙 touch_up 退回 send()", not bytes_path(mt_src, slow), slow != touch_src),
        ]
        for label, bit, changed in bites:
            print(("  ok   " if (bit and changed) else "  FAIL ") + label)
            ok = ok and bool(bit) and bool(changed)

    print("FIREPATH " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
