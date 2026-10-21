"""文档一致性核查（只读）：链接可达性、模块覆盖、常数与正文数字、字段名。

用法：PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe research/experiments/dockcheck.py
"""
import glob
import io
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TRACKED_DOCS = ["README.md", "DISCLAIMER.md", "research/README.md",
                "tools/README.md", "docs/python_env.md"]
LOCAL_DOCS = ["AGENTS.md", "docs/agents_manual.md", "docs/panel_spec.md",
              "docs/data_format.md", "docs/m3_sources.md",
              "tools/probes/README.md", "tools/bin/NOTICE.md"]
OPTIONAL = re.compile(r"^(research/|evidence/|%USERPROFILE%|C:|D:)")

# 已知豁免：每条都写明为什么它不该被算作断链。新增条目必须同样写明理由，
# 否则会变成「把判据调松」。键 = "<文档> :: <token>"。
ALLOW = {
    "docs/agents_manual.md :: flet/controls/base_control.py":
        "上游 Flet 源码路径，只作 get_api 依据的描述，本机不存",
    "docs/agents_manual.md :: probes/fletpanel.py":
        "探针名简写（省略 tools/ 前缀）",
    "docs/agents_manual.md :: probes/paneldata.py": "同上",
    "docs/agents_manual.md :: probes/panelfly.py": "同上",
    "docs/agents_manual.md :: tools/countrule.py":
        "已删（#111 判定物计数 2026-10-10 终止），文中是历史记述",
    "docs/agents_manual.md :: tools/gui.py":
        "已删（旧 PySide6 面板），文中是历史记述",
    "docs/panel_spec.md :: nav_lbpopup_a/b.png": "夹具名组写法（a/b 为同一组的两个变体）",
    "docs/python_env.md :: .mcp/flet-mcp/Scripts/python.exe":
        "%USERPROFILE% 下的宿主配置片段，正则从反斜杠后截断所致",
    "tools/probes/README.md :: nav_stuck_select/band/live.png": "夹具名组写法",
    "tools/probes/README.md :: tools/flet_gui_nope.py": "牙的假文件示例（故意不存在）",
    "tools/probes/README.md :: tools/gui.py": "已删的旧面板，文中是历史记述",
}


def read(rel):
    with io.open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def section(title):
    print("\n== %s ==" % title)


# ---------------- A. 链接与反引号路径 ----------------
def part_links():
    section("A 链接与路径")
    bad_links, miss_paths = [], []
    for rel in TRACKED_DOCS + [p for p in LOCAL_DOCS if os.path.exists(os.path.join(ROOT, p))]:
        text = read(rel)
        base = os.path.dirname(os.path.join(ROOT, rel))
        for m in re.finditer(r"\[[^\]]*\]\(([^)#][^)]*)\)", text):
            tgt = m.group(1).split("#")[0].strip()
            if not tgt or tgt.startswith(("http://", "https://", "mailto:")):
                continue
            if not os.path.exists(os.path.normpath(os.path.join(base, tgt))):
                bad_links.append("%s -> %s" % (rel, tgt))
        for m in re.finditer(r"`([A-Za-z0-9_./\\-]+\.(?:py|md|json|jsonl|bat|txt|png|zz|dll|exe))`", text):
            tok = m.group(1).replace("\\", "/")
            if OPTIONAL.match(tok) or tok.startswith("tools/") or "/" in tok:
                cand = os.path.join(ROOT, tok) if not tok.startswith("research/") else os.path.join(ROOT, tok)
                if os.path.exists(cand):
                    continue
                # 允许 docs/ 里相对自身的引用
                if os.path.exists(os.path.join(base, tok)):
                    continue
                miss_paths.append("%s :: %s" % (rel, tok))
    print("坏链接 %d：%s" % (len(bad_links), bad_links or "无"))
    uniq = sorted(set(miss_paths))
    exempt = [p for p in uniq if p in ALLOW]
    real = [p for p in uniq if p not in ALLOW and not OPTIONAL.match(p.split(" :: ")[1])]
    print("路径 token 缺失 %d（已知豁免 %d，非 research/evidence 的真缺 %d）"
          % (len(uniq), len(exempt), len(real)))
    for p in real:
        print("   ", p)
    return not bad_links and not real


# ---------------- B. 模块覆盖 ----------------
def part_modules():
    section("B 模块覆盖（tools/README.md vs tools/*.py）")
    readme = read("tools/README.md")
    mods = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOT, "tools", "*.py")))
    missing = [m for m in mods if ("`%s.py`" % m) not in readme and ("`%s`" % m) not in readme]
    listed = sorted(set(re.findall(r"`([a-z0-9_]+)\.py`", readme)))
    ghost = [m for m in listed if not os.path.exists(os.path.join(ROOT, "tools", m + ".py"))]
    print("tools/*.py 共 %d 个；README 未提及 %d：%s" % (len(mods), len(missing), missing or "无"))
    print("README 提及但不存在的模块 %d：%s" % (len(ghost), ghost or "无"))
    probes = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOT, "tools", "probes", "*.py")))
    idx = read("tools/probes/README.md")
    pmiss = [p for p in probes if p not in idx]
    print("探针 %d 个；索引未收录 %d：%s" % (len(probes), len(pmiss), pmiss or "无"))
    return not missing and not ghost and not pmiss


# ---------------- C. 常数与正文数字 ----------------
def part_numbers():
    section("C 常数与正文数字")
    src = {}
    for rel in ("tools/panel_core.py", "tools/player.py", "tools/calib.py",
                "tools/watchdog.py", "tools/memguard.py", "tools/run.py",
                "tools/flet_gui.py"):
        src[rel] = read(rel)

    def const(rel, name):
        m = re.search(r"^%s\s*=\s*([^\n#]+)" % re.escape(name), src[rel], re.M)
        return m.group(1).strip() if m else None

    checks = [
        ("RUNS_MAX", const("tools/panel_core.py", "RUNS_MAX"), "100"),
        ("STACK_W", const("tools/flet_gui.py", "STACK_W"), "992"),
        ("FIRE_MIN", const("tools/panel_core.py", "FIRE_MIN"), "3"),
        ("TAIL_FLICK_LEAD_MS", const("tools/player.py", "TAIL_FLICK_LEAD_MS"), "10.0"),
        ("STALL_S", const("tools/watchdog.py", "STALL_S"), "600"),
        ("MAX_RECOVER", const("tools/watchdog.py", "MAX_RECOVER"), "3"),
        ("FREEZE_REPRESS_S", const("tools/calib.py", "FREEZE_REPRESS_S"), "20"),
        ("TITLE_DEADLINE", const("tools/calib.py", "TITLE_DEADLINE"), "600"),
        ("MULTI_MATCH_WAIT_S", const("tools/calib.py", "MULTI_MATCH_WAIT_S"), "120"),
        ("START_RETRIES", const("tools/calib.py", "START_RETRIES"), "3"),
        ("SELECT_BACK", const("tools/calib.py", "SELECT_BACK"), None),
    ]
    ok = True
    for name, got, want in checks:
        flag = "  "
        if want is not None and got is None:
            flag, ok = "!!", False          # 找不到这个常量本身就算失败，不能静默 None
        elif want is not None and want not in got:
            flag, ok = "!!", False
        print("%s%-20s 代码=%s" % (flag, name, got))
    # README 与 AGENTS 的关键数字是否与之相符
    md = read("README.md")
    agents = read("AGENTS.md")
    pairs = [("README 900 秒", "900" in md), ("README +55 ms", "+55 ms" in md),
             ("README 2 分钟", "2 分钟" in md), ("AGENTS RUNS_MAX 100", "RUNS_MAX" in agents and "100" in agents),
             ("AGENTS 关闭 (640,655)", "(640,655)" in agents)]
    for label, good in pairs:
        if not good:
            flag, ok = "!!", False
        else:
            flag = "  "
        print("%s%s" % (flag, label))
    return ok


# ---------------- D. data_format 字段与代码 ----------------
def part_fields():
    section("D data_format.md 字段名 vs 代码")
    doc = read("docs/data_format.md")
    missing = []
    for field in ("meta", "score", "events", "bpm", "notes", "pos", "size", "type",
                  "node", "visible", "ease", "dir", "kind", "t_ms", "lane", "x",
                  "end_ms", "end_flick", "path", "musicId", "noteCount", "bandId"):
        if field not in doc:
            missing.append(field)
    print("文档缺字段名 %d：%s" % (len(missing), missing or "无"))
    code = read("tools/compile.py") + read("tools/fetch_charts.py") + read("tools/gameread.py")
    ghosts = [f for f in ("end_flick", "time_shift_ms", "node", "visible") if f not in code]
    print("代码中查不到的字段 %d：%s" % (len(ghosts), ghosts or "无"))
    return not missing and not ghosts


if __name__ == "__main__":
    results = [part_links(), part_modules(), part_numbers(), part_fields()]  # 不短路，四段全跑
    ok = all(results)
    print("\nDOCKCHECK %s" % ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)
