"""Regression: no function reads a name it cannot see (the g647/g648 `NameError: name 'args'`).

Why this probe exists: 2026-10-11 the结算页 FAST/SLOW read was moved behind a new `--read-split`
flag, and the branch that used it was written *inside* `wait_result()` as `if args.read_split:` --
but `args` only exists inside `main()`. `py_compile` cannot see it (a name lookup is a runtime
event, not a syntax error) and `tools/run.py --help` never enters that function, so two real rounds
(g647 03:41, g648 03:43) played perfectly and then died at the result page: the score was read,
`result_g648.png` was written, and the round's record was never recorded. This probe is the static
check that would have caught it, and it costs no emulator.

The check is `symtable` (stdlib, no new dependency): for every function scope, a *referenced* name
that is neither local nor free, is never assigned in that scope, and is absent from both the
module's own top-level names and builtins is a name the function cannot resolve. That is exactly
pyflakes' undefined-name rule, minus the parts that need a full type/import graph.

PART 1  the whole tree is clean: every tools/*.py and tools/probes/*.py (the probes are the files
        that would crash a 40-minute batch, so they are scanned too), and no file uses `import *`
        -- which is what makes the module-level name set complete.
PART 2  the tooth: the exact g647/g648 shape -- a mutant of the *real* run.py with `read_split`
        removed from the signature and `args.read_split` put back -- must be reported, naming `args`
        in `wait_result()`. A second synthetic shape (a module-level function reading a name that
        only exists inside another function) must be reported too.
PART 3  the false-positive guards, because a scanner that cries wolf gets switched off: a nested
        closure reading its enclosing function's local must NOT be reported (`run.py`'s own
        `on_select`/`on_prep` closures read `main()`'s `args` and are legal), a function reading a
        module-level global must NOT be reported, and `global x` + assignment must NOT be reported.

Run from the repo root:  python tools/probes/scopes.py     # exit 0 = PASS
"""

import ast
import builtins
import os
import symtable
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
BUILTINS = set(dir(builtins))
ok_all = True


def _report(tag, ok, detail=""):
    global ok_all
    ok_all = ok_all and ok
    print(f"  {'ok  ' if ok else 'FAIL'} {tag}{(' -- ' + detail) if detail else ''}")
    return ok


def first_load_line(tree, scope_name, name):
    """symtable.Symbol has no line number in 3.13 -- find a pointer with ast for the report."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == scope_name:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id == name and isinstance(sub.ctx, ast.Load):
                    return sub.lineno
    return 0


def undefined_names(src, filename="<src>"):
    """[(scope, name, line)] for every name a function reads but cannot resolve."""
    tree = ast.parse(src, filename)
    top = symtable.symtable(src, filename, "exec")
    module_names = {s.get_name() for s in top.get_symbols()}
    bad = []

    def walk(table):
        if table.get_type() != "module":
            for s in table.get_symbols():
                n = s.get_name()
                if (s.is_referenced() and not s.is_assigned() and not s.is_free()
                        and not s.is_local() and n not in module_names and n not in BUILTINS):
                    bad.append((table.get_name(), n, first_load_line(tree, table.get_name(), n)))
        for c in table.get_children():
            walk(c)

    walk(top)
    return bad


def scan_file(path):
    with open(path, encoding="utf-8") as f:
        return undefined_names(f.read(), str(path))


# ---------------------------------------------------------------- PART 1
print("PART 1 全树干净")
files = sorted(list(TOOLS.glob("*.py")) + list(TOOLS.glob("probes/*.py")))
stars = []
hits = []
for p in files:
    src = p.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src, str(p))):
        # 看语法树，不看文本：这个探针自己的 docstring 里就写着 `import *` 这四个字
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            stars.append(p.name)
    for scope, name, line in undefined_names(src, str(p)):
        hits.append(f"{p.name}:{line}: {scope}() -> {name}")
_report(f"扫了 {len(files)} 个文件（tools/ + tools/probes/）", not hits, "; ".join(hits[:6]))
_report("没有 `import *`（否则模块级名字集就不完整）", not stars, ", ".join(stars))
if not _report("tools/run.py 在里面", any(p.name == "run.py" for p in files)):
    pass


# ---------------------------------------------------------------- PART 2
print("PART 2 牙：抓得到 g647/g648 那一刀")
real = (TOOLS / "run.py").read_text(encoding="utf-8")
old_sig = ("def wait_result(tag, inj, timeout=150.0, log=print, extra=None, multi=False, "
           "read_split=False):")
new_sig = "def wait_result(tag, inj, timeout=150.0, log=print, extra=None, multi=False):"
mutant = real.replace(old_sig, new_sig).replace("            if read_split:",
                                                "            if args.read_split:")
_report("变异真的生效了（签名去掉参数 + 装回 args.read_split）",
        mutant != real and "if args.read_split:" in mutant)
mut_hits = [h for h in undefined_names(mutant, "run_mutated.py") if h[1] == "args"]
_report("真 run.py 的变异体被抓到，且点名的就是 wait_result() 里的 args",
        len(mut_hits) == 1 and mut_hits[0][0] == "wait_result",
        str(mut_hits))
_report("变异体里没有别的误报", len(undefined_names(mutant, "run_mutated.py")) == 1)

synthetic = (
    "def helper(n):\n"
    "    return n + secret\n"          # only exists inside main()
    "def main():\n"
    "    secret = 41\n"
    "    return helper(1)\n"
)
syn = undefined_names(synthetic)
_report("合成例：模块级函数读另一个函数的局部量，被抓到",
        len(syn) == 1 and syn[0][1] == "secret", str(syn))


# ---------------------------------------------------------------- PART 3
print("PART 3 反例：合法的作用域不许报")
closure = (
    "def main():\n"
    "    args = object()\n"
    "    def on_select():\n"
    "        return args.hits\n"
    "    return on_select\n"
)
_report("闭包读外层函数的局部量（run.py 的 on_select/on_prep 就是这样）", not undefined_names(closure))

glob = "SETTING = 3\ndef use():\n    return SETTING + 1\n"
_report("函数读模块级全局", not undefined_names(glob))

globassign = "TOTAL = 0\ndef bump():\n    global TOTAL\n    TOTAL += 1\n    return TOTAL\n"
_report("global 声明 + 赋值", not undefined_names(globassign))

builtin_use = "def use():\n    return len(sorted([3, 1]))\n"
_report("内建函数", not undefined_names(builtin_use))

nested_def = (
    "def outer():\n"
    "    def inner():\n"
    "        return len([])\n"
    "    return inner\n"
)
_report("嵌套函数定义", not undefined_names(nested_def))

# 真树也要顺带确认它抓的是「当前这份源码」而不是缓存的什么：改一个字符就要变红
tmp = Path(tempfile.gettempdir()) / "scopes_probe_mutant.py"
tmp.write_text(mutant, encoding="utf-8", newline="\n")
_report("从磁盘上重新读回来的变异体一样被抓到（走的是真文件路径）",
        [h[1] for h in scan_file(str(tmp))] == ["args"])
try:
    os.remove(tmp)
except OSError:
    pass

print("\n" + ("SCOPES PASS" if ok_all else "SCOPES FAIL"))
sys.exit(0 if ok_all else 1)
