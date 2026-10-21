"""探针用的假演奏器：长相与 tools/run.py 的标准输出契约一致，但不碰模拟器、不碰语料。

它存在的唯一理由是让「面板起进程 → 逐行读标准输出 → 收结果 → 写 results.jsonl」这条链路
能在**没有模拟器**的情况下被真跑一遍（见 `tools/probes/panelfly.py`）。这条链路是换界面
框架时唯一被重写的东西，而它坏掉的样子是「面板看起来一切正常，结果永远不动」—— 所以它
必须有一条会失败的回归，而不是一段只打印数字的脚本。

它只做三件事：

  1. 把收到的 argv / cwd / 两个环境变量写成 JSON，供探针核对**面板到底发出了什么命令**
     （`OURNOTES_PANEL=1` 决定 results.jsonl 的写手是谁，漏了它面板跑的一局会被记两次）；
  2. 按 run.py 的契约往标准输出吐机器行与普通行：
     `#STATUS# phase=..;progress=..`（只推状态，不进日志）、`#ATSELECT#`（演出间隔的锚点）、
     `RESULT {json}`（一局的结算）、以及会被 NATIVE_NOISE 丢掉的原生库横幅；
  3. 场景 `stuck` 下**活着不动**，只往心跳文件追加字节。探针靠「心跳有没有继续长」判断
     面板在异常路径上到底有没有把子进程杀掉 —— 这是唯一不依赖 tasklist/psutil 的判据。

环境变量（都由探针设，生产路径不会出现；前缀 2026-10-20 从 `BANG_` 改成 `HYOUSHI_`，
旧写法仍在认，见 `_flag()`）：

    HYOUSHI_FAKE_DIR       写 argv.json / heartbeat 的目录（必填，否则只打印就退出）
    HYOUSHI_FAKE_SCENARIO  ok（默认）| stuck | fail | noresult
    HYOUSHI_FAKE_STEPS     #STATUS# 进度行的条数，默认 3
    HYOUSHI_FAKE_TAG       覆盖 RESULT 里的 tag（默认取 --tag）

它**故意**不 import 项目里的任何模块：一个会 import detect/mumucap 的假演奏器，就不再是
「不碰模拟器」的证明了。
"""

from __future__ import annotations

import json
import os
import sys
import time

# 与 run.py 同款：pythonw 起的面板没有控制台，编码不对时一行中文就能把子进程打死。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                                 # noqa: BLE001
    pass


def _out(line):
    print(line, flush=True)


def _split_argv(argv):
    """把面板给的命令行拆成 (位置参数, 选项字典)。

    只认 `--k v` 与 `--k=v` 两种形状 —— 面板两种都不用，它只发 `--k v`，而 run.py 的
    argparse 也只要求这一种。未知选项照样记下来：探针要能发现「面板多发了什么」。
    """
    pos, opts = [], {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            if "=" in a:
                k, _, v = a.partition("=")
                opts[k] = v
            elif i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opts[a] = argv[i + 1]
                i += 1
            else:
                opts[a] = True
        else:
            pos.append(a)
        i += 1
    return pos, opts


def _flag(name):
    """环境变量的一行读法：`HYOUSHI_<name>` 优先，旧的 `BANG_<name>` 回落。

    这里不 import `locate.env` 是刻意的（见文件头）：这个假演奏器不碰项目里的任何模块。
    """
    for prefix in ("HYOUSHI_", "BANG_"):
        got = os.environ.get(prefix + name)
        if got:
            return got
    return ""


def main():
    argv = sys.argv[1:]
    pos, opts = _split_argv(argv)
    d = _flag("FAKE_DIR")
    scenario = _flag("FAKE_SCENARIO") or "ok"
    tag = _flag("FAKE_TAG") or str(opts.get("--tag") or "fake000")
    try:
        steps = max(1, int(_flag("FAKE_STEPS") or 3))
    except ValueError:
        steps = 3

    if d:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "argv.json"), "w", encoding="utf-8") as f:
            json.dump({"argv": argv, "positional": pos, "opts": opts,
                       "cwd": os.getcwd(), "pid": os.getpid(),
                       "ournotes_panel": os.environ.get("OURNOTES_PANEL"),
                       "pythonioencoding": os.environ.get("PYTHONIOENCODING"),
                       "scenario": scenario, "tag": tag}, f, ensure_ascii=False, indent=1)

    def beat():
        """心跳：一行字节。stuck 场景下这就是「子进程还活着」的唯一证据。"""
        if not d:
            return
        with open(os.path.join(d, "heartbeat"), "ab") as f:
            f.write(b".")
            f.flush()

    if scenario == "stuck":
        # 故意不发任何东西：面板若在异常路径上忘了杀子进程，这里就会一直活着。
        beat()
        try:
            while True:
                time.sleep(0.1)
                beat()
        except KeyboardInterrupt:
            pass
        return 0

    # ---- 正常契约 ----
    # 这一行以 product 开头，属于 mumucap 原生库直接写到 fd 1 的横幅，面板必须丢掉它。
    _out("product nemu_connect 0x1")
    _out("connect not same day")
    _out("12:00:01 导航：乐曲选择页")
    _out("12:00:02 链路校准：corr -10.0 ms")
    # `!!` 是演奏器的严重度标记：面板要把它判成错误行，并把这个标记剥掉。
    _out("12:00:03 !! 断键，第 12 条")
    for i in range(steps):
        _out(f"#STATUS# phase=正在演奏 {i + 1}/{steps};progress={(i + 1) / steps:.2f}")
        beat()
        time.sleep(0.01)
    # 回到选曲页：面板拿它当演出间隔的锚点，它本身不进日志。
    _out("#ATSELECT#")
    _out("12:00:09 ALL PERFECT 假谱 EXPERT " + tag)
    _out("12:00:10 结果已写入 research/results.jsonl")

    if scenario in ("noresult", "fail"):
        # 一局没有 RESULT 行（结算页读不到，或者演奏被中断）：面板必须收下退出码并把它记成
        # 异常局，而不是崩掉、也不是把上一轮的记录又写一遍。
        return 3 if scenario == "fail" else 0

    rec = {
        "ts": "01-01 12:00", "tag": tag, "song": "假谱", "diff": "EXPERT",
        "chart": (pos[0].split(os.sep)[-1].replace(".hits.json", "") if pos else "0000_00"),
        "rc": 0, "all_perfect": True, "full_combo": True,
        "perfect": 174, "great": 0, "good": 0, "bad": 0, "miss": 0,
        "non_perfect": 0, "combo": 174, "score": 4140060, "aborts": 0,
        "cfg": {"offset": 55.0, "eff": 45.0}, "asof": "flight",
    }
    _out("RESULT " + json.dumps(rec, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
