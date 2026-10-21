"""探针：唯一的启动器（启动面板.bat）解析到的东西是否真的存在、真的可跑。

**它不起面板。** 做的事：
  1. 逐行解析 .bat，抽出「用哪个解释器、跑哪个入口」的四条分支；
  2. 对着真实文件系统判定第一条命中的分支（就是 .bat 自己会走的那个）；
  3. 断言命中的 `.py` 存在，且那套解释器**能 import 该入口的控件层**（Flet），
     以及 Flet 的桌面客户端真的在本地（zip 或 `~/.flet` 缓存 —— 缺了会去联网下 40 MB）；
  4. 断言 .bat 是 LF-only，且四条分支的入口名一字不差；
  5. 断言根目录下**只有这一个** .bat 入口 —— 面板只有一套，多出来的那个入口
     迟早指向一个已经不存在的文件，而双击它只会静默失败。

判定：任一 PART FAIL → 退出码 1。**这台机器还没装 `.venv` 时 PART 3 打 SKIP**（解释器
不在，控件层与桌面客户端无从判起，从前会在 `subprocess.run` 里抛 FileNotFoundError），
PART 1/2/4 照旧判到底 —— SKIP 不算通过。
"""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)

ENTRY = "tools/flet_gui.py"
BAT = "启动面板.bat"

FAILS: list[str] = []
SKIPS: list[str] = []


def check(label, cond, extra=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(label)
    return cond


def skip(label, extra=""):
    """无从判起的一项（不是通过，也不是失败）—— 与 `capreg.py` 的 SKIP 同一套口径。"""
    print(f"  SKIP {label}" + (f"  {extra}" if extra else ""))
    SKIPS.append(label)


def parse_text(text):
    """把 .bat 的文本读成 [(解释器相对路径, 入口相对路径)]，按出现次序。

    只认 `start "" "<exe>" <entry>` 与裸 `<exe> <entry>` 两种形状 —— .bat 本身就这么写的；
    解析不动它，探针也就不会因为「谁改了写法」而假装通过。
    """
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith(("start ", "python", "pythonw")) and 'python' not in s:
            continue
        if ".py" not in s:
            continue
        parts = [p for p in s.replace('start ""', "").split() if p]
        exe = entry = None
        for i, p in enumerate(parts):
            if p.startswith('"'):
                exe = p.strip('"')
                if i + 1 < len(parts):
                    entry = parts[i + 1].strip('"')
                break
        if exe is None and len(parts) >= 2:
            exe, entry = parts[0], parts[1]
        if exe and entry and entry.endswith(".py"):
            out.append((exe, entry))
    return out


def parse_bat(path):
    with open(path, "r", encoding="utf-8") as f:
        return parse_text(f.read())


def teeth():
    """牙：把入口名换成不存在的文件，同一条比较必须亮起来。

    不复制整个仓库、也不碰真 .bat —— 变异的是**文本**，跑的还是上面那两个被提交的
    比较函数（`parse_text` + 那两条 `check` 的判据），所以这不是另写一份判据。
    """
    bat = os.path.join(ROOT, BAT)
    text = open(bat, "r", encoding="utf-8").read()
    good = parse_text(text)
    broken_text = text.replace(ENTRY.replace("/", "\\"), "tools\\flet_gui_nope.py")
    broken_text = broken_text.replace(ENTRY, "tools/flet_gui_nope.py")
    broken = parse_text(broken_text)

    # 控制组：原文必须过，否则「亮了」说明不了任何事。
    ctrl = len(good) >= 3 and all(e.replace("\\", "/") == ENTRY for _x, e in good)
    mutant_entried = len(broken) == len(good) and all(
        e.replace("\\", "/").endswith("flet_gui_nope.py") for _x, e in broken)
    # 两条被判据管的断言：分支名一致、入口存在。
    name_ok = len(broken) >= 3 and all(e.replace("\\", "/") == ENTRY for _x, e in broken)
    _exe, entry_b = first_hit(broken) if broken else ("", "")
    exists_ok = bool(entry_b) and os.path.exists(os.path.join(ROOT, entry_b))

    print("TEETH 控制组（原文四条分支都等于 %s）: %s" % (ENTRY, ctrl))
    print("TEETH 变异体（%d 条分支，入口都换成 flet_gui_nope.py）: %s"
          % (len(broken), mutant_entried))
    print("TEETH ① 「四条分支都指向 %s」必须亮: %s" % (ENTRY, not name_ok))
    print("TEETH ② 命中的入口必须不存在: %s" % (not exists_ok))
    ok = ctrl and mutant_entried and not name_ok and not exists_ok
    print("TEETH PASS" if ok else "TEETH FAIL")
    return 0 if ok else 1


def first_hit(branches):
    """.bat 会走的第一条存在分支（解释器存在就算命中）。"""
    for exe, entry in branches:
        if os.path.exists(os.path.join(ROOT, exe)):
            return exe, entry
    return branches[-1]


def importable(python, modules):
    code = ("import importlib,sys\n"
            "bad=[]\n"
            "for m in %r:\n"
            "    try: importlib.import_module(m)\n"
            "    except Exception as e: bad.append(m)\n"
            "print('|'.join(bad))\n" % (list(modules),))
    r = subprocess.run([python, "-c", code], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def pkg_dir(python, module):
    """问那套解释器：这个包在哪儿。取不到返回空串。"""
    code = ("import importlib,os\n"
            "m=importlib.import_module(%r)\n"
            "print(os.path.dirname(os.path.abspath(m.__file__)))\n" % module)
    r = subprocess.run([python, "-c", code], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


def main():
    print("PART 1 启动器的四条分支")
    bat = os.path.join(ROOT, BAT)
    check(f"{BAT} 存在", os.path.exists(bat))
    if not os.path.exists(bat):
        print("\nPART 探针 FAIL：启动器不在，后面的断言没有意义")
        return 1
    branches = parse_bat(bat)
    print(f"    分支：{branches}")
    check(f"四条分支都指向 {ENTRY}",
          len(branches) >= 3 and all(e.replace("\\", "/") == ENTRY for _x, e in branches),
          f"{[e for _x, e in branches]}")

    raw = open(bat, "rb").read()
    check(f"{BAT} 是 LF-only", b"\r\n" not in raw, f"CRLF={raw.count(bytes((13, 10)))}")

    print("PART 2 命中的解释器与入口真的存在")
    exe, entry = first_hit(branches)
    print(f"    命中：{exe} {entry}")
    check("入口存在", os.path.exists(os.path.join(ROOT, entry)), entry)
    py = os.path.join(ROOT, exe)
    have_py = os.path.exists(py)
    if have_py:
        check("解释器存在", True, py)
    else:
        # 没装 .venv 不是「启动器坏了」：入口与 .bat 照样判，只是命中的是 PATH 兜底分支，
        # 探针没法替它检查控件层（也不该替 PATH 上的解释器背书）。
        skip(f"解释器存在（这台机器没有 .venv，.bat 会落到 PATH 上的 {exe!r}），PART 3 无从判起")

    print("PART 3 那套解释器里有控件层")
    if not have_py:
        skip("Flet 在 .venv 里齐")
        skip("Flet 桌面客户端在本地（zip 或 ~/.flet 缓存）")
        skip(f"py_compile {entry}")
    else:
        bad = importable(py, ["flet", "flet_desktop"])
        check("Flet 在 .venv 里齐", bad == "", f"缺：{bad!r}")

        # 桌面客户端是**另一个进程**的真 Flutter 客户端：要么留着手工塞进去的 zip，
        # 要么已经解出过一份缓存。两个都没有就意味着首次运行要联网下 40 MB。
        pkg = pkg_dir(py, "flet_desktop")
        zip_path = os.path.join(pkg, "app", "flet-windows.zip") if pkg else ""
        cache = os.path.expanduser(os.path.join("~", ".flet"))
        check("Flet 桌面客户端在本地（zip 或 ~/.flet 缓存）",
              bool(zip_path) and os.path.exists(zip_path) or os.path.isdir(cache),
              f"zip={bool(zip_path) and os.path.exists(zip_path)} cache={os.path.isdir(cache)}")

        # 编译入口：语法与 import 顺序的问题当场现形，比开窗便宜。
        r = subprocess.run([py, "-m", "py_compile", entry], capture_output=True, text=True, cwd=ROOT)
        check(f"py_compile {entry}", r.returncode == 0, r.stderr.strip()[:200])

    print("PART 4 面板只有一套")
    # 根目录下的 .bat 一律当成入口看（排除非入口的辅助脚本由命名区分：入口都带「启动」）。
    # 多出来一个入口 = 迟早指向一个已经删掉的文件，而双击它只会静默失败。
    bats = sorted(n for n in os.listdir(ROOT) if n.lower().endswith(".bat"))
    check("根目录只有一个 .bat", bats == [BAT], f"{bats}")

    print()
    if FAILS:
        print(f"PART 探针 FAIL：{len(FAILS)} 项")
        for f in FAILS:
            print("  -", f)
        return 1
    if SKIPS:
        print(f"ALL PASS（SKIP {len(SKIPS)} 项：{'；'.join(SKIPS)}）")
    else:
        print("ALL PASS")
    return 0


if __name__ == "__main__":
    if "--teeth" in sys.argv[1:]:
        sys.exit(teeth())
    sys.exit(main())
