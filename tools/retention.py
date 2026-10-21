"""落盘预算 —— 把「research/ 能长到多大」写成一张表，检查与执行都从这张表来。

来路（2026-10-08）：项目长到 3.93 GB，靠一次手动删除压回 1.19 GB。手动删除不是机制 ——
同样的三条路会再长回来，而三条都已经看得见：

* 面板的 `auto_clean` 只碰 debug / stale / pycache（`panel_core.collect_junk`）。录像、归档、
  以及 `research/runs/<tag>.counters.avi`（一局 82–87 MB）一个都不在它的范围内；
* 面板只在**跑完一轮**时扫一次，所以不经过面板的实验没人管（HUD 看盘那次留下 1116 张、971 MB）；
* 没有任何地方说过「这个桶的上限是多少」—— 只有出事之后才有人量。

所以这个工具做三件事：**量**（`--check`，退出码 1 = 超了）、**按表执行**（`--go`）、
**把预算写成代码**（`BUDGETS`，每一条都带来路）。它能在面板之外跑，所以那些不经过面板的
实验 dump 也有人管；而它删的东西与面板删的是**同一套**判据（`collect_junk`），没有第二份规则。

只删「谁也打不开的东西」。不碰：被 git 跟踪的文件、`research/charts/`、`research/refsrc`、
`evidence/`、状态文件（`results*.jsonl` / `chain_cal.json` / `gui_state.json` /
`digit_templates.json` / `manifest.json` / `validated.json`）、文字日志（`*.out` 与
`*.detail.log`，`tools/backfill_log.py` 靠它补档）、以及 `FRESH_S` 秒之内新写的文件
（可能有一局正在跑）。**录像与归档只在显式 `--media` 下、且只在超过上限时按最老优先删** ——
「删老录像是判断，留给人按」这条规矩不变，这里只是把判断要用的数字摆出来。**调试截图桶
（frames 规则）与结算截图桶（count 规则）也是同一条纪律**：面板判据认得的垃圾 `--go` 直接删，
剩下那些「能打开、而且是某一局的证据」的帧只在 `--media` 且超上限时按保留集压（frames：留
`mp*` + 最近 `FRAME_KEEP_N` 张；result：留 `result_mp*` + 最近 `RESULT_KEEP_N` 张）。

三条**不需要人按**的动作（2026-10-19 加的，用户说「优化磁盘空间管理」）：

* `auto()` —— 面板每跑完一轮自动走的那条：垃圾照删 + 取证桶（frames/result）按保留集压到
  上限以内 + 顺带 `dedupe()`；**录像与归档不在自动范围内**（与 `--media` 差这一档）。
  它把一行账写进 `research/logs/retention.log`（时间、总占用、这次释放了多少），
  于是「树有没有长歪」在日志里就能看见，不用等下一次手动量。
* `dedupe()` —— 同一个字节串在 `research/` 里存了很多份（`research/recordings/mp2/cap`
  这类的抽帧语料，一张 1 MB 的页面重复 80 次）。把**重复的那几份换成硬链接**：内容一个字节
  不动、每个路径照旧能打开，只是盘上只存一份。只碰媒体扩展名（`.png/.jpg/…`）、
  至少 `DEDUPE_MIN` 大、而且**一天以前**的文件（新帧可能被同一 tag 重跑覆盖 —— 硬链接下
  「原地重写」会同时改掉两边，这是唯一真实的危险，所以用年龄挡住）。
* `--auto` —— 上面那条的命令行入口（面板之外也能跑：定时任务、手工）。

用法::

    .\\.venv\\Scripts\\python.exe tools\\retention.py            # 只看（超了退出 1）
    .\\.venv\\Scripts\\python.exe tools\\retention.py --go       # 按表清理 debug/stale/pycache
    .\\.venv\\Scripts\\python.exe tools\\retention.py --go --media   # 连录像也按上限压
    .\\.venv\\Scripts\\python.exe tools\\retention.py --auto     # 无人值守那条（不动录像）
    .\\.venv\\Scripts\\python.exe tools\\retention.py --dedupe   # 只把重复文件换成硬链接
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

import panel_core
import rlog

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 面板是 pythonw.exe（没有控制台），它调 `check()` 时 git 是个控制台程序 —— 不传这个就会在
# 屏幕上闪一个 CMD 窗口。与 `locate.CREATE_NO_WINDOW` 同一个东西，这里独立取一份免得绕依赖。
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MB = 1048576.0

# 十分钟之内写过的东西一律不碰：`--go` 可能在面板跑着一局的时候被叫起来，而刚落的取证帧
# 与刚写的 dets 是那一局的一部分，删掉就是把证据从正在进行的局底下抽走。
FRESH_S = 600.0

# 结算截图那一桶的保留规则（2026-10-09，用户 2026-10-08 对 `slim.py` 就是选的这一条）：
# 每局只落 result_ 一张（2026-10-11 起：FAST/SLOW 那一步降级为调试专用、只在内存里读），
# 其中 `result_mp*.png` 是多人链路的取证（那 22 局是交付物的
# 依据），一律留住；其余按时间留最近 RESULT_KEEP_N 张 —— 40 张 ≈ 最近 40 局。
# 它是证据不是垃圾，所以只在显式 `--media` 下、且只在超过上限时才动手 —— 与「录像与归档」
# 同一条纪律。
RESULT_KEEP_N = 40
RESULT_KEEP_PREFIX = "result_mp"

# 调试截图那一桶的保留规则（2026-10-09）：`--go` 照旧删面板判据认得的垃圾（不看上限，判据本身
# 就是「没人打得开」）；剩下的取证帧（走查放弃时落的 `nav_stuck_*`、被闸门弃掉的 `hudreject_*`、
# 手工存下来的实验帧……）是证据不是垃圾，所以只在显式 `--media` 且超过上限时，按「留 mp*
# （多人链路的取证，与结算截图同一条）+ 最近 FRAME_KEEP_N 张」压。10-08 那次 3.93 GB 里
# 971 MB 就是这一桶长出来的，而当时它一条规则都管不到 —— `--go` 只能删掉垃圾形状的那些，
# 剩下的 208 张（167.7 MB）把桶顶在 150 MB 之上没人能动。
FRAME_KEEP_N = 60
FRAME_KEEP_PREFIX = "mp"

# ---- 去重（2026-10-19）--------------------------------------------------------------
# 同一个字节串在 research/ 里存多份是很常见的：`research/recordings/mp2/cap` 那种整帧
# 抽帧语料，**同一张页面帧重复 80 次**（每份 1.0 MB）。2026-10-19 实测：100 组重复、
# 冗余 103.8 MB —— 与「删证据」无关，纯粹是同一个 inode 该有几个名字的问题。
DEDUPE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
DEDUPE_MIN = 64 * 1024          # 太小的不赚：一次硬链接的两个目录项也要几次元数据写
DEDUPE_AGE_S = 86400.0          # 一天以内的不碰：同一 tag 重跑会「原地重写」那张帧，
#                                 硬链接下两个名字共用一个 inode，重写会同时改掉两边
DEDUPE_EVERY_S = 6 * 3600.0     # `auto()` 里最多六小时做一次（一次要读几百 MB）
DEDUPE_STAMP = "retention.dedupe"

# `auto()` 的记账文件：每跑一次写一行，于是「树有没有长歪」在日志里就能看见。
LEDGER = os.path.join("logs", "retention.log")

# 文档里点名的取证文件（`AGENTS.md`/`docs/`/探针 docstring 里写着的 `research/…/x.png`）。
# 它们不是垃圾也不是「随便一张证据」—— 自动清理必须留住，否则文档就指向空气。
# 取**最后一段名字**（`research/archive/runs/split_t20.png` -> `split_t20.png`）：挡的时候按
# basename 比，跨目录同名极少，而且宁可多留一个也不删错。
REF_RE = re.compile(r"research/(?:[A-Za-z0-9_.+-]+/)*([A-Za-z0-9_.+-]+)")

# 每个桶一条：key 取自 `_bucket()`，cap 单位 MB，rule 决定 `--go` 能对它做什么。
#   junk    面板的 debug/stale 判据能删的桶 —— `--go` 删它们，不看上限（判据本身就是「没人打得开」）
#   frames  调试截图 —— 垃圾照 junk 删；剩下的取证帧是证据，只有 `--media` 且超过上限时按
#           「留 mp* + 最近 FRAME_KEEP_N 张」删（与 count 同一条纪律）
#   media   录像与归档 —— 只有 `--media` 且超过上限时，按最老优先删到上限以内
#   count   结算截图 —— 只有 `--media` 且超过上限时，按「留 mp* + 最近 N 局」删（证据，不是垃圾）
#   report  只量不删（谱面库与文字日志是必需/补档能力，超了要人来看，不是让工具动刀）
# 上限都留了余量（当前值写在 note 里），够跑一阵，又能在长歪的早期就报出来。
BUDGETS = (
    ("research", "research/ 全树", 1200, "report",
     "当前 616.7 MB / 8615 项（2026-10-20 目录收口后；收口只搬家不删，2029 个旧 .out 从根上"
     "进了 runs/）。这一条是总闸：超了先看哪个桶超了。"),
    ("frames", "调试截图", 150, "frames",
     "当前 76.8 MB / 108 张（取证帧按保留集压过几轮）。剩下的取证帧"
     "（`hudreject_kt*`、`mp*`、`nav_stuck_*`……）把桶顶在 150 MB 之上。2026-10-09 起这一桶"
     f"改由 frames 规则管：垃圾照删，取证帧只在 `--media` 下按「留 {FRAME_KEEP_PREFIX}* + 最近 "
     f"{FRAME_KEEP_N} 张」压。10-07 的 HUD 看盘留了 971 MB，就是这里长出来的。"),
    ("result", "结算截图", 80, "count",
     "当前每局一张 result_（2026-10-11 起不再落 split_）。2026-10-09 起按「留 result_mp* + 最近 "
     f"{RESULT_KEEP_N} 局」压（`--media` 才会动）：mp* 那批是多人链路的取证，其余按时间滚动。"),
    ("runs", "每轮数据", 260, "junk",
     "当前 89.0 MB / 5349 项：.detail.log、.out（2026-10-20 起根上的旧 .out 也在这里）与"
     " dets_/relock_ 投票语料。语料在 protected() 里点名保住，junk 规则不碰它们。"),
    ("runmedia", "每轮录像", 400, "media",
     "2026-10-09 加：`research/runs/*.counters.avi` 从前**哪个桶都管不到**。现在自成一桶、"
     "按最老优先删到上限。当前 0 KB —— 四条 cnt 实录与 g314/g316 都已删（HUD 阶梯的派生物 "
     "`*.stairs.json`/`*.counters.jsonl` 留在 runs/ 里，是回放用的替换记录）。"),
    ("recordings", "录像媒体", 400, "media",
     "当前 221.7 MB / 203 项（mp2/cap 抽帧语料 + mp1/seg_01.mp4）。"),
    ("archive", "归档", 200, "media",
     "当前 133.5 MB / 695 项（archive/media 86.2 起）。archive/media 被 "
     "freshfeed.py / spritebars.py 指着，删之前先看那两处。"),
    ("charts", "谱面与封面", 120, "report",
     "当前 40.9 MB / 821 项。谱面库、封面、钉子索引 —— 必需，超了是内容变多，不是垃圾变多。"),
    ("logs", "文字日志", 40, "report",
     "当前 5.5 MB / 954 项（logs/ 与 research/runs/*.out）。backfill_log.py 靠 <tag>.out 补档，"
     "永不自动删。"),
)


def _research():
    return rlog.RESEARCH


def _bucket(key):
    r = _research()
    if key == "runmedia":
        # runs/ 直接躺着的录像（--record-counters 的 <tag>.counters.avi、--record 的 mp4）：
        # 只量这些文件，不碰同目录的 dets_*.json / *.jsonl / *.detail.log。
        import glob
        out = []
        for pat in ("*.avi", "*.mp4"):
            out += sorted(glob.glob(os.path.join(rlog.RUNS, pat)))
        return out
    return {"research": r, "frames": rlog.FRAMES, "result": rlog.RESULT,
            "runs": rlog.RUNS, "charts": rlog.CHARTS,
            "recordings": os.path.join(r, "recordings"),
            "archive": os.path.join(r, "archive"),
            "logs": os.path.join(r, "logs")}[key]


def du(path):
    """(bytes, files) —— 目录递归求和；单个文件或一串文件也行；不存在就是 (0, 0)，绝不抛。"""
    if isinstance(path, (list, tuple)):
        total = n = 0
        for p in path:
            b, c = du(p)
            total += b
            n += c
        return total, n
    if not os.path.isdir(path):
        return (os.path.getsize(path), 1) if os.path.isfile(path) else (0, 0)
    total = n = 0
    for base, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(base, f))
                n += 1
            except OSError:
                pass
    return total, n


def tracked():
    """被 git 跟踪的相对路径（正斜杠）。git 不可用就返回 None —— 调用方据此**拒绝删除**。"""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                             timeout=60, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return {p for p in out.stdout.decode("utf-8", "replace").split("\0") if p}


def _rel(path):
    """相对 ROOT 的正斜杠路径。跨盘（探针把临时树放在 %TEMP%）时退回绝对路径 ——
    `os.path.relpath` 在 Windows 上跨盘会抛 ValueError，而「相对谁」在这里只用来比对名单。"""
    try:
        return os.path.relpath(path, ROOT).replace("\\", "/")
    except ValueError:
        return os.path.abspath(path).replace("\\", "/")


def referenced():
    """被**已跟踪的文件**点名的取证帧（`research/frames/x.png` / `research/result/y.png`）。

    这些名字出现在 `AGENTS.md`、`docs/`、探针的 docstring 里 —— 它们是给人回看的路标，
    自动删除会把文档指向空气。`git grep` 一次拿到（不读盘、只读索引里的内容），
    拿到多少都不会慢；git 不可用就当「一个都没被点名」。
    """
    try:
        out = subprocess.run(["git", "grep", "-o", "-I", "-E",
                              r"research/([A-Za-z0-9_.+-]+/)*[A-Za-z0-9_.+-]+"],
                             cwd=ROOT, capture_output=True, timeout=60,
                             creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return set()
    if out.returncode not in (0, 1):
        return set()
    names = set()
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        for m in REF_RE.finditer(line):
            names.add(m.group(1))
    return names


def protected(rel):
    """rel 是相对 ROOT 的正斜杠路径。被跟踪的文件由 `tracked()` 另外挡，这里挡结构性的。"""
    if rel.startswith(("research/charts/", "research/refsrc", "evidence/")):
        return True
    # 2026-10-19：这条 86 MB 的到期回放语料是 `tools/probes/freshfeed.py:53` 与
    # `tools/probes/spritebars.py:46` 的**输入**（477 张 jpg + meta.json，按 seq 点名读），
    # 而 archive 桶是 media 规则 —— 超过 200 MB 时它会「最老优先」把这些帧一张张删掉，
    # 两条探针随即变成「录音缺失」。整目录固定住；要腾空间应当由人决定。
    if rel.startswith("research/archive/media/our_survival_open_0930/"):
        return True
    base = os.path.basename(rel)
    if base in ("results.jsonl", "results_full.jsonl", "chain_cal.json", "gui_state.json",
                "digit_templates.json", "manifest.json", "validated.json"):
        return True
    # g314/g316 的计数器实录是 AGENTS.md 欠账 §1（判定物计数规则）的原始证据，用户明确要留。
    if base in ("g314.counters.avi", "g316.counters.avi"):
        return True
    # 文字日志是补档能力（backfill_log.py 读 <tag>.out），不是垃圾。
    if rel.endswith((".out", ".detail.log")):
        return True
    # 投票语料是三个回归与两条分析脚本的**输入**，不是「窗外的取证」：
    # tools/probes/votereplay.py（108 份 dump 的契约）、research/experiments/{objmap,detdiff,greatmap}.py 都要读 dets_<tag>.json / relock_<tag>.json。
    # collect_junk 的 stale 规则按编号判，正好会把这些老局判成垃圾（2026-10-09 实测：
    # 2759 个可删件里有 77 份 dets_ + 100 份 relock_）—— 面板的清理对话框仍按它的口径，
    # 但 retention 自己的 --go 不许碰它们。
    if base.startswith(("dets_", "relock_dets_", "relock_")):
        return True
    return False


def junk_paths():
    """`collect_junk()` 说「没人打得开」的那些路径（debug + stale + pycache）。

    只借它的判据，不借它的分类：面板那边的键是给对话框看的，这里的桶是按目录分的。
    """
    out = set()
    try:
        cats = panel_core.collect_junk()
    except Exception as exc:                                     # noqa: BLE001
        print(f"!! 读不到清理判据：{exc!r}")
        return out
    for c in cats:
        if c.get("key") in ("debug", "stale", "pycache"):
            out.update(c.get("files") or [])
    return out


def _deletable(paths, keep_tracked, now=None):
    """过滤成「可以删」的一组：(可删, 被跳过的原因计数)。"""
    now = time.time() if now is None else now
    ok, why = [], {"tracked": 0, "protected": 0, "fresh": 0, "missing": 0}
    for p in paths:
        if not os.path.exists(p):
            why["missing"] += 1
            continue
        rel = _rel(p)
        if keep_tracked is None:
            raise SystemExit("!! git 不可用：拒绝删除（没有跟踪名单就没法保证不碰跟踪文件）")
        if rel in keep_tracked:
            why["tracked"] += 1
            continue
        if protected(rel):
            why["protected"] += 1
            continue
        try:
            age = now - os.path.getmtime(p)
        except OSError:
            age = 0.0
        if age < FRESH_S:
            why["fresh"] += 1
            continue
        ok.append(p)
    return ok, why


def _size_of(p):
    return du(p)[0]


def _sha1(path):
    import hashlib
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.digest()


def dedupe(root=None, age_s=None, now=None, dry=False):
    """把 `research/` 里**字节完全相同**的媒体文件换成硬链接。

    内容一个字节不动、每个路径照旧打得开，只是盘上只存一份。只碰媒体扩展名、至少
    `DEDUPE_MIN` 大、而且一天以前的文件（新帧可能被同一 tag「原地重写」—— 硬链接下两个
    名字共用一个 inode，原地重写会同时改掉两边，这是这套做法唯一真实的危险，用年龄挡住）。
    返回 `{groups, dups, linked, freed, skipped, errors, dry, ok}`；git 不可用就 `ok=False`
    并且一个都不动（与删除同一条纪律：没有跟踪名单就不许改结构）。
    """
    root = root or _research()
    age_s = DEDUPE_AGE_S if age_s is None else age_s
    now = time.time() if now is None else now
    keep_tracked = tracked()
    out = {"groups": 0, "dups": 0, "linked": 0, "freed": 0, "skipped": 0, "errors": 0,
           "dry": bool(dry), "ok": keep_tracked is not None}
    if keep_tracked is None:
        return out
    by_size = {}
    for base, _dirs, names in os.walk(root):
        for fn in names:
            if os.path.splitext(fn)[1].lower() not in DEDUPE_EXT:
                continue
            p = os.path.join(base, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_size < DEDUPE_MIN or now - st.st_mtime < age_s:
                continue
            by_size.setdefault(st.st_size, []).append(p)
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_hash = {}
        for p in paths:
            try:
                by_hash.setdefault(_sha1(p), []).append(p)
            except OSError:
                continue
        for same in by_hash.values():
            if len(same) < 2:
                continue
            out["groups"] += 1
            try:
                same.sort(key=lambda p: os.stat(p).st_mtime)      # 最早的那份当主
                master = same[0]
                m_ino = os.stat(master).st_ino
            except OSError:
                continue
            for p in same[1:]:
                out["dups"] += 1
                rel = _rel(p)
                if rel in keep_tracked or protected(rel):
                    out["skipped"] += 1
                    continue
                try:
                    if os.stat(p).st_ino == m_ino:                 # 已经是硬链接了
                        out["skipped"] += 1
                        continue
                    if dry:
                        out["linked"] += 1
                        out["freed"] += size
                        continue
                    tmp = p + ".__link"
                    os.link(master, tmp)                           # 先把第二个名字挂上，
                    os.replace(tmp, p)                             # 再原子换掉旧的那份
                    out["linked"] += 1
                    out["freed"] += size
                except OSError:
                    out["errors"] += 1
    return out


def auto(as_json=False, dedupe_it=True):
    """无人值守那条：垃圾照删 + 取证桶（frames/result）按保留集压 + 顺带去重 + 记一行账。

    与 `go(media=True)` 只差一档：**录像/归档不在自动范围内**（删老录像是判断，留给人按）。
    去重六小时最多做一次（`DEDUPE_EVERY_S`，戳在 `research/retention.dedupe`）。
    返回 {deleted, freed, dedupe, total, over, line}；`over` 是自动清理之后仍然超上限的桶
    （剩下的都是 report/media 那一档，工具不自己动）。
    """
    ledger = {}
    go(media=True, skip=("media",), ledger=ledger)
    ded = {"groups": 0, "dups": 0, "linked": 0, "freed": 0, "skipped": 0, "errors": 0,
           "ok": True, "why": ""}
    if dedupe_it:
        stamp = os.path.join(_research(), DEDUPE_STAMP)
        try:
            due = (not os.path.exists(stamp)
                   or time.time() - os.path.getmtime(stamp) > DEDUPE_EVERY_S)
        except OSError:
            due = True
        if due:
            ded = dedupe()
            try:
                with open(stamp, "w", encoding="utf-8") as f:
                    f.write(f"{time.time():.0f}\n")
                os.utime(stamp, None)
            except OSError:
                pass
        else:
            ded["why"] = "六小时内已经做过"
    rows = check()
    total = rows[0]["size"] if rows else 0
    over = [r for r in rows if r["over"]]
    line = (f"{time.strftime('%Y-%m-%d %H:%M:%S')} auto  删 {ledger.get('deleted', 0)} 项 "
            f"{fmt(ledger.get('freed', 0))}  去重 {ded.get('linked', 0)} 个 "
            f"{fmt(ded.get('freed', 0))}  research/ {fmt(total)}"
            + (f"  超上限 {len(over)} 桶" if over else ""))
    try:
        lp = os.path.join(_research(), LEDGER)
        os.makedirs(os.path.dirname(lp), exist_ok=True)
        with open(lp, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    res = {"deleted": ledger.get("deleted", 0), "freed": ledger.get("freed", 0),
           "detail": ledger.get("detail") or [], "dedupe": ded, "total": total,
           "over": over, "line": line}
    if as_json:
        print(json.dumps({k: res[k] for k in ("deleted", "freed", "dedupe", "total", "line")}
                         | {"over": [r["key"] for r in over]}, ensure_ascii=False, indent=2))
    else:
        for label, what in res["detail"]:
            if what.startswith("删 0 项") or (what.startswith("跳过") and "删" not in what):
                continue
            print(f"  {label:<14}{what}")
        print(f"  {line}")
        if over:
            for r in over:
                print(f"  !! {r['label']} {fmt(r['size'])} / {fmt(r['cap'])} —— "
                      + ("只量不删" if r["rule"] == "report" else "录像与归档要人按 --media"))
    return res


def check():
    rows = []
    for key, label, cap_mb, rule, note in BUDGETS:
        path = _bucket(key)
        size, n = du(path)
        rows.append({"key": key, "label": label, "path": path, "size": size, "files": n,
                     "cap": int(cap_mb * MB), "rule": rule, "note": note,
                     "over": size > cap_mb * MB})
    return rows


def fmt(n):
    return f"{n / MB:.1f} MB" if n >= MB else f"{n / 1024:.0f} KB"


def _w(s):
    """显示宽度：中文按两格算，否则这张表在等宽字体里是歪的（第一版就是歪的）。"""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in str(s))


def _pad(s, width):
    return str(s) + " " * max(0, width - _w(s))


def show(rows, as_json=False):
    if as_json:
        print(json.dumps({"rows": [{k: r[k] for k in
                                    ("key", "label", "path", "size", "files", "cap", "rule",
                                     "over")} for r in rows]}, ensure_ascii=False, indent=2))
        return
    print(f"  {_pad('桶', 16)}{_pad('大小', 12)}{_pad('上限', 12)}{_pad('文件', 7)}判定")
    for r in rows:
        verdict = "!! 超了" if r["over"] else "ok"
        if r["rule"] == "report":
            verdict += "（只量不删）"
        print(f"  {_pad(r['label'], 16)}{_pad(fmt(r['size']), 12)}{_pad(fmt(r['cap']), 12)}"
              f"{_pad(r['files'], 7)}{verdict}")
    git = os.path.join(ROOT, ".git")
    if os.path.isdir(git):
        print(f"  {_pad('.git', 16)}{_pad(fmt(du(git)[0]), 12)}")
    print(f"  {_pad('项目根', 16)}{_pad(fmt(du(ROOT)[0]), 12)}")


def go(media=False, as_json=False, skip=(), ledger=None):
    rows = check()
    keep_tracked = tracked()
    if keep_tracked is None:
        raise SystemExit("!! git 不可用：拒绝删除")
    junk = junk_paths()
    pinned = referenced()          # 文档点名的取证帧：保留集里再加这一层
    deleted, freed = 0, 0
    detail = []
    # __pycache__ 不属于任何桶（它散在仓库各处），但面板的自动清理一直删它，这里跟上：
    # 删掉只会让下一次 import 慢一点，Python 自己会重建。
    pyc = [p for p in junk if os.path.basename(p) == "__pycache__"]
    keep_pyc, _why = _deletable(pyc, keep_tracked)
    for p in keep_pyc:
        import shutil
        shutil.rmtree(p, ignore_errors=True)
        deleted += 1
    if keep_pyc:
        detail.append(("脚本缓存", f"删 {len(keep_pyc)} 个 __pycache__"))
    junk = junk - set(pyc)
    for r in rows:
        path = r["path"]
        if r["rule"] in skip:
            # `auto()` 走的就是这一支：录像与归档不在无人值守的范围内 —— 删老录像是判断。
            detail.append((r["label"], "跳过（自动模式不动录像与归档）"))
            continue
        if r["rule"] == "junk":
            if not isinstance(path, str):
                continue
            want = [p for p in junk if os.path.abspath(p).startswith(os.path.abspath(path) + os.sep)]
            take, why = _deletable(want, keep_tracked)
            # 文档里点名的取证帧不进删除名单（`AGENTS.md` 写着 `research/frames/nav_stuck_options.png`
            # 这类名字时，它就不是「谁也打不开的东西」—— 那一条正是给人回看的路标）。
            take = [p for p in take if os.path.basename(p) not in pinned]
        elif r["rule"] == "frames":
            # 调试截图：垃圾照 junk 删（不看上限）；剩下的取证帧是证据，只在显式 --media 且超上限
            # 时按「留 mp* + 最近 FRAME_KEEP_N 张」压 —— 与结算截图同一条纪律。
            if not isinstance(path, str):
                continue
            want = [p for p in junk if os.path.abspath(p).startswith(os.path.abspath(path) + os.sep)]
            take, why = _deletable(want, keep_tracked)
            if media and r["over"]:
                files = [os.path.join(base, fn)
                         for base, _dirs, names in os.walk(path) for fn in names]
                rest = [p for p in files if p not in set(want)]
                rest.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
                          reverse=True)
                keep = {p for p in rest if os.path.basename(p).startswith(FRAME_KEEP_PREFIX)}
                keep |= {p for p in rest if os.path.basename(p) in pinned}
                keep |= set([p for p in rest if p not in keep][:FRAME_KEEP_N])
                take2, why2 = _deletable([p for p in rest if p not in keep], keep_tracked)
                take += take2
                for k, v in why2.items():
                    why[k] = why.get(k, 0) + v
            else:
                detail.append((r["label"], "垃圾照删；取证帧跳过（"
                               + ("没给 --media" if not media else "没超上限") + "）"))
        elif r["rule"] == "media":
            if not (media and r["over"]):
                detail.append((r["label"], "跳过（" + ("没给 --media" if not media else "没超上限") + "）"))
                continue
            if isinstance(path, str):
                files = []
                for base, _dirs, names in os.walk(path):
                    files += [os.path.join(base, fn) for fn in names]
            else:
                files = list(path)
            files.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
            take, why = _deletable(files, keep_tracked)
            take = [p for p in take if os.path.basename(p) not in pinned]   # 文档点名的留住
            cut, total = [], r["size"]
            for p in take:                       # 最老优先，删到上限以内就停
                if total <= r["cap"]:
                    break
                sz = _size_of(p)
                cut.append(p)
                total -= sz
            take = cut
        elif r["rule"] == "count":
            # 结算截图：留 mp*（多人链路取证）与最近 RESULT_KEEP_N 局，其余删。证据不是垃圾，
            # 所以与 media 同一条纪律 —— 只在显式 --media 且超上限时动手。
            if not (media and r["over"]):
                detail.append((r["label"], "跳过（" + ("没给 --media" if not media else "没超上限") + "）"))
                continue
            files = [os.path.join(base, fn)
                     for base, _dirs, names in os.walk(path) for fn in names]
            files.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
            keep = {p for p in files if os.path.basename(p).startswith(RESULT_KEEP_PREFIX)}
            keep |= {p for p in files if os.path.basename(p) in pinned}
            keep |= set([p for p in files if p not in keep][:RESULT_KEEP_N])
            take, why = _deletable([p for p in files if p not in keep], keep_tracked)
        else:
            if r["over"]:
                detail.append((r["label"], f"超了但只量不删（{fmt(r['size'])} / {fmt(r['cap'])}）"))
            continue
        n = f = 0
        for p in take:
            sz = _size_of(p)
            try:
                if os.path.isdir(p):
                    import shutil
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
            except OSError:
                continue
            n += 1
            f += sz
        deleted += n
        freed += f
        skipped = "、".join(f"{k} {v}" for k, v in why.items() if v)
        detail.append((r["label"], f"删 {n} 项 / {fmt(f)}" + (f"（跳过 {skipped}）" if skipped else "")))
    after = check()
    if ledger is not None:
        ledger.update({"deleted": deleted, "freed": freed, "detail": list(detail),
                       "rows": after})
    if as_json:
        print(json.dumps({"deleted": deleted, "freed": freed,
                          "detail": [{"bucket": a, "what": b} for a, b in detail],
                          "rows": [{k: r[k] for k in ("key", "label", "size", "cap", "files",
                                                      "over")} for r in after]},
                         ensure_ascii=False, indent=2))
    else:
        for label, what in detail:
            print(f"  {label:<14}{what}")
        print(f"  一共删除 {deleted} 项，释放 {fmt(freed)}")
        print()
        show(after)
    return 1 if any(r["over"] for r in after) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="落盘预算：量、按表清理、把上限写成代码")
    ap.add_argument("--check", action="store_true",
                    help="只量不删（这也是默认动作；写出来是为了让脚本与文档读得明白）")
    ap.add_argument("--go", action="store_true", help="按表清理（默认只看不动）")
    ap.add_argument("--media", action="store_true",
                    help="连录像/归档与取证帧（调试截图、结算截图）也按上限压"
                         "（最老优先 / 保留集；不给就只列出来）")
    ap.add_argument("--json", action="store_true", help="机器可读")
    ap.add_argument("--gc", action="store_true", help="顺带 git gc --auto")
    ap.add_argument("--auto", action="store_true",
                    help="无人值守那条：垃圾 + 取证桶按保留集压 + 顺带去重（不动录像与归档）")
    ap.add_argument("--dedupe", action="store_true",
                    help="只把 research/ 里字节相同的媒体文件换成硬链接（内容不动）")
    ap.add_argument("--dry-run", action="store_true", help="与 --dedupe 合用：只算不链")
    args = ap.parse_args(argv)

    if args.dedupe:
        d = dedupe(dry=args.dry_run)
        print(f"  去重：{d['groups']} 组 / 重复 {d['dups']} 份；"
              f"{'可' if args.dry_run else '已'}链 {d['linked']} 个，"
              f"释放 {fmt(d['freed'])}（跳过 {d['skipped']}、失败 {d['errors']}）")
        return 0 if d["ok"] else 1
    if args.auto:
        auto(as_json=args.json)
        rc = 0
    elif args.go:
        rc = go(media=args.media, as_json=args.json)
        if not args.json:
            d = dedupe()
            print(f"  去重：{d['groups']} 组 / 重复 {d['dups']} 份；已链 {d['linked']} 个，"
                  f"释放 {fmt(d['freed'])}（跳过 {d['skipped']}、失败 {d['errors']}）")
    else:
        rows = check()
        show(rows, as_json=args.json)
        rc = 1 if any(r["over"] for r in rows) else 0
    if args.gc:
        try:
            subprocess.run(["git", "gc", "--auto"], cwd=ROOT, timeout=600,
                           creationflags=CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
