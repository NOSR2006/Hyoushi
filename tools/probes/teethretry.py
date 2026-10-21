"""`fletpanel --teeth` 的「变异体少写了判据」不许读成牙自己的错。

2026-10-06 的全拆（29/29）里 `clamp`/`reset`/`trim` 三颗报「变异体只写了 183/191 条判据」，
单独重放每一颗都全绿 —— 全套连拆时 Flutter 客户端偶发半路没了，与那颗牙无关。这条回归把
判据钉在那次修上：**少写一次就再放一次，以第二次为准**，但真会半路死的变异体是确定性的，
连着两次少写仍然必须 FAIL（否则「拆了守卫还全绿」会被重放悄悄放过）。

假 `_once` 脚本化返回，不起窗口、不碰语料、不碰提交的字节（`tools/flet_gui.py` 只被读）。

PART 1: 少写一次 → 重放一次 → 以第二次为准，整颗牙绿，且输出里点明重放过。
PART 2: 连着两次少写 → FAIL，报「只写了 N/M」而不是「一条都没亮」。
PART 3: 写满了就不重放（`_once` 恰好调两次：控制组 + 这颗牙）；退出码非 0 也不重放。
PART 4: 重放之后亮错了关 → 仍走「期望只点亮 …」那条 FAIL（装饰判据不被重放掩盖）。

Run from the repo root:  python tools/probes/teethretry.py
"""

import importlib.util
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError, OSError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = os.path.join(HERE, "fletpanel.py")

# 控制组真正写出来的 11 关条数（204 条）。这里按关铺开，判据的关归属才与真跑一致。
COUNT = {"PART 1": 45, "PART 2": 3, "PART 3": 2, "PART 4": 6, "PART 5": 9, "PART 6": 21,
         "PART 7": 5, "PART 8": 20, "PART 9": 2, "PART 10": 36, "PART 11": 55}


def _rows(fail_part=None, only=None):
    """一份假判据：`fail_part` 那一关全红；`only` 给定就只写那么多条（子进程半路没了）。"""
    out = []
    for part, n in COUNT.items():
        for i in range(n):
            if only is not None and len(out) >= only:
                return out
            out.append({"part": part, "label": f"{part}#{i}", "ok": part != fail_part,
                        "extra": ""})
    return out


def _payload(rows, rc=0):
    return ({"res": rows, "guard": True, "iso": True, "state_written": True, "rc": rc},
            "（假子进程日志）")


def _the_teeth(script, names=("clamp",), monkeypatch=True):
    """把脚本化的 `_once` 塞给真 `_teeth`，返回 (rc, 输出, 调用次数)。"""
    spec = importlib.util.spec_from_file_location("fletpanel_uut", PROBE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fletpanel_uut"] = mod
    spec.loader.exec_module(mod)
    calls = []

    def fake_once(d=None):                       # noqa: ARG001
        calls.append(d)
        return script[min(len(calls) - 1, len(script) - 1)]

    if monkeypatch:
        mod._once = fake_once
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        rc = mod._teeth(list(names))
    finally:
        sys.stdout = old
    return rc, buf.getvalue(), len(calls)


def part1():
    """少写一次：重放，第二次写满了、只点亮 PART 6 ⇒ 绿，且输出里点明重放。"""
    rc, text, calls = _the_teeth([_payload(_rows()), _payload(_rows(only=150)),
                                 _payload(_rows(fail_part="PART 6"))])
    replayed = "重放一次" in text
    green = rc == 0 and "只点亮 PART 6" in text and "TEETH PASS" in text
    print(f"PART 1 少写一次 → 重放以第二次为准=绿：{green}；说了重放={replayed}"
          f"；_once 调用 {calls} 次（期望 3） -> "
          f"{'PASS' if green and replayed and calls == 3 else 'FAIL'}")
    return green and replayed and calls == 3


def part2():
    """连着两次少写 ⇒ FAIL，且理由必须是「只写了 N/M」。"""
    rc, text, calls = _the_teeth([_payload(_rows()), _payload(_rows(only=150)),
                                 _payload(_rows(only=150))])
    said = "只写了 150/204 条判据" in text
    failed = rc == 1 and "TEETH FAIL" in text
    guessed = "期望只点亮" in text               # 老误判那条路（装饰判据）不许走
    print(f"PART 2 连着两次少写 → FAIL：{failed}；理由是「只写了 N/M」={said}"
          f"；没走「装饰判据」那条路={not guessed}；_once {calls} 次（期望 3） -> "
          f"{'PASS' if failed and said and not guessed and calls == 3 else 'FAIL'}")
    return failed and said and not guessed and calls == 3


def part3():
    """写满了不重放；退出码非 0 也不重放（两条都只看调用次数）。"""
    rc_a, _, calls_a = _the_teeth([_payload(_rows()), _payload(_rows(fail_part="PART 6"))])
    rc_b, text_b, calls_b = _the_teeth([_payload(_rows()),
                                       _payload(_rows(fail_part="PART 6"), rc=1)])
    print(f"PART 3 写满不重放：_once {calls_a} 次（期望 2）、rc={rc_a}；"
          f"退出码非 0 不重放：_once {calls_b} 次（期望 2）、rc={rc_b}、"
          f"报了退出码={'退出码' in text_b} -> "
          f"{'PASS' if calls_a == 2 and rc_a == 0 and calls_b == 2 and rc_b == 1 and '退出码' in text_b else 'FAIL'}")
    return calls_a == 2 and rc_a == 0 and calls_b == 2 and rc_b == 1 and "退出码" in text_b


def part4():
    """重放之后亮错了关：仍按「期望只点亮 …」FAIL，装饰判据不被重放掩盖。"""
    rc, text, calls = _the_teeth([_payload(_rows()), _payload(_rows(only=150)),
                                 _payload(_rows(fail_part="PART 3"))])
    caught = "期望只点亮 PART 6" in text and rc == 1
    print(f"PART 4 重放后亮错关 → 仍 FAIL：{caught}；_once {calls} 次（期望 3） -> "
          f"{'PASS' if caught and calls == 3 else 'FAIL'}")
    return caught and calls == 3


def main():
    if not os.path.exists(PROBE):
        print(f"找不到 {PROBE}")
        return 1
    print("teethretry  牙自己「少写了判据」时的重放规矩（假 _once，离线、不起窗口）\n")
    parts = [part1(), part2(), part3(), part4()]
    print("\nteethretry " + ("PASS" if all(parts) else "FAIL"))
    return 0 if all(parts) else 1


if __name__ == "__main__":
    sys.exit(main())
