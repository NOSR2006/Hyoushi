"""落盘预算（`tools/retention.py`）：把「research/ 能长到多大」写成表，并在面板之外也能清。

来路（2026-10-08）：项目长到 3.93 GB，靠一次手动删除压回 1.19 GB。手动删除不是机制 ——
三条长回来的路都在代码里看得见，这个探针一条一条钉住：

* `research/runs/<tag>.counters.avi`（一局 82–87 MB）从前一条判据都不进：编号在前，
  `JUNK_TAGGED_RE` 的编号在后；扩展名也不在 `JUNK_DEBUG_RE` 认的 png/json/pid 里 ——
  于是项目里最大的单件产物在清理对话框里根本看不见；
* 名字带不上合法编号的 HUD dump（`hud_now_*` 之类）两条正则都不认：10-07 那次留下 1116 张、
  971 MB，在 `research/frames` 里躺了两天；
* 面板只在**跑完一轮**时扫一次，所以不经过面板的实验没人管；而且没有任何地方说过上限是多少。
* 反过来也有一刀：`collect_junk` 的 stale 规则按编号判，把**窗外的投票语料**（`runs/dets_<tag>.json`
  / `relock_*.json`）也算成垃圾 —— 而它们是 `votereplay` / `objmap` / `detdiff` / `greatmap` 的**输入**。2026-10-09 实测：2759 个可删件里有 77 份 `dets_` + 100 份 `relock_`，
  删掉就等于把三个回归的语料清空。`retention.protected` 现在按名字挡住这三种形状
  （面板的清理对话框仍按它自己的口径，那是用户手里的判断）。

PART 1 在临时树上跑真 `check()`/`go()`：四种归属（窗内 / 窗外 / 没编号 / 谁也不认）、录像不算
垃圾，以及三道保险（被跟踪的文件、十分钟内的新文件、文字日志与 charts）一个都不许被删。
PART 2 是表自己的自洽：键唯一、上限为正、规则合法、每个分桶的上限不超过总闸。
PART 3 是接线：`auto_clean` 必须把超预算的桶说出来，`collect_junk` 的媒体那一类必须看得见
`research/runs` 里的录像。
PART 4/5 是两条**保留集**规则（2026-10-09 新加）：结算截图（`count`：留 `result_mp*` + 最近
`RESULT_KEEP_N` 张）与调试截图（`frames`：垃圾照删，取证帧留 `mp*` + 最近 `FRAME_KEEP_N` 张），
都在临时树上把上限压到 0 让规则开火，各配一颗牙（把保留前缀换成谁也不认的 -> 那张取证必须被删）。
PART 6（2026-10-19，用户「优化磁盘空间管理」）量`dedupe()` 与 `auto()`：字节相同的媒体文件
换成硬链接（两个名字同一 inode、内容不动；太小/太新/被跟踪的三道拒绝各量一条；牙 = 年龄门槛
推到未来 ⇒ 刚写的那份也被链上），以及 `auto()` 那条无人值守的边界 —— **录像与归档不在自动
范围内**（`go(media=True)` 会删、`auto()` 一个都不许删），外加它往 `logs/retention.log` 记的
那一行账。

牙（模块属性或源码变异，红了才算数）：关掉时间保险 -> 刚写的文件被删；关掉结构保险 ->
文字日志被判可删；把语料豁免那一条摘掉 -> `dets_` 立刻被判可删；跟踪名单空掉 ->
被跟踪的文件被判可删；`JUNK_DEBUG_RE` 去掉 `hud_` -> 没编号的 HUD dump 不再算垃圾；
`RESULT_KEEP_PREFIX`/`FRAME_KEEP_PREFIX` 换成谁也不认的 -> 那两张取证被删；
面板的 `auto_clean` 拿掉 `retention.auto()` -> 接线判据变红；去重年龄门槛推到未来 ->
刚写的文件也被链上。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import panel_core as core                                             # noqa: E402
import retention                                                      # noqa: E402
import rlog                                                           # noqa: E402

OLD = time.time() - 3600.0          # 比 FRESH_S 老，才可能被删


def build(tmp):
    """一棵最小的 research/ 树：两个 tag（一个在窗内、一个在窗外）+ 一局计数器实录。"""
    r = os.path.join(tmp, "research")
    for d in ("frames", "runs", "result", "charts", "recordings", "archive", "logs"):
        os.makedirs(os.path.join(r, d), exist_ok=True)
    with open(os.path.join(r, "results.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"tag": "g900"}) + "\n")
    files = {
        "frames/hudreject_g900_keep.png": 1,      # 窗内 -> 留着
        "frames/hudreject_g800_stale.png": 1,     # 窗外 -> 删
        "frames/hud_now_1234.png": 1,             # 没有编号 -> 删（2026-10-08 新加的判据）
        "frames/keep_me.png": 1,                  # 谁也不认 -> 留着
        "frames/note.out": 1,                     # 文字日志 -> 绝不删
        "runs/g314.counters.avi": 4096,           # 录像 -> media，不是 junk
        "runs/dets_g800.json": 2,                 # 窗外编号的投票语料 -> 绝不删（2026-10-09 新加的判据）
    }
    for rel, n in files.items():
        p = os.path.join(r, rel)
        with open(p, "wb") as f:
            f.write(b"x" * n)
        os.utime(p, (OLD, OLD))
    return r


def run_go():
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = retention.go()
    return rc, buf.getvalue()


def part1():
    tmp = tempfile.mkdtemp(prefix="retention_probe_")
    try:
        r = build(tmp)
        rlog.retarget(r)
        # `panel_core.junk_protected` 用**它自己的** ROOT 算相对路径；临时树在 %TEMP%（C 盘）
        # 而仓库在 D 盘，跨盘 relpath 会抛 ValueError。把它也指到临时树上 —— 顺带让
        # `research/charts/` 这类结构豁免能在临时树上按行为验，而不是只调 protected()。
        # `panel_core.RESULTS` 是 import 时抄下来的那一份，`rlog.retarget` 改不到它 ——
        # 不补这一句，窗口表读的还是真账本，临时树里的 g900 会被判成「窗外」当场删掉。
        core_root, core.ROOT = core.ROOT, tmp
        core_results, core.RESULTS = core.RESULTS, os.path.join(r, "results.jsonl")
        rows = {x["key"]: x for x in retention.check()}
        size_ok = (rows["frames"]["files"] == 5 and rows["runs"]["size"] == 4098
                   and rows["charts"]["rule"] == "report")
        # 刚写下的两张：都是垃圾形状（没编号），但十分钟保险把它们挡住
        fresh = os.path.join(r, "frames", "hud_now_fresh.png")
        keep = os.path.join(r, "frames", "hud_now_keep.png")
        for p in (fresh, keep):
            with open(p, "wb") as f:
                f.write(b"x")
        rc, _out = run_go()
        after = {n for n in os.listdir(os.path.join(r, "frames"))}
        junk_ok = (after == {"hudreject_g900_keep.png", "keep_me.png", "note.out",
                             "hud_now_fresh.png", "hud_now_keep.png"}
                   and os.path.exists(os.path.join(r, "runs", "g314.counters.avi"))
                   and os.path.exists(os.path.join(r, "runs", "dets_g800.json")))
        # 录像必须是 media 那一类，不是 junk（删录像是判断，工具不许自己动）
        cats = {c["key"]: c for c in core.collect_junk()}
        avi = os.path.join(r, "runs", "g314.counters.avi")
        media_ok = (avi in (cats["media"]["files"] or [])
                    and avi not in (cats["debug"]["files"] or [])
                    and avi not in (cats["stale"]["files"] or []))
        # 三道保险是**单元**判据：junk 形状但受保护的路径不许进删除名单
        tracked_set = retention.tracked()
        shaped = keep                     # 垃圾形状、而且还在盘上（刚写的，被时间保险挡着）
        ok, why = retention._deletable([shaped], tracked_set)
        prot = retention.protected("research/frames/x.out") and \
            retention.protected("research/charts/0056_03.hits.json") and \
            not retention.protected("research/frames/x.png")
        # 投票语料（`dets_`/`relock_`/`relock_dets_`）是 votereplay/objmap/detdiff 的**输入**，
        # 而 `collect_junk` 的 stale 规则按编号判、正好会把这些老局判成垃圾 —— 2026-10-09 实测
        # 2759 个可删件里有 77 份 dets_ + 100 份 relock_。三种名字形状都要挡住。
        corpus = os.path.join(r, "runs", "dets_g800.json")
        corpus_ok = (retention.protected("research/runs/dets_g800.json")
                     and retention.protected("research/runs/relock_dets_g800.json")
                     and retention.protected("research/runs/relock_g800.json")
                     and not retention.protected("research/runs/hud_g800.png")
                     and retention._deletable([corpus], tracked_set)[0] == [])
        mine = str(ROOT / "tools" / "panel_core.py")      # 已提交、确实被跟踪
        _ok, why2 = retention._deletable([mine], tracked_set)
        # 牙：时间保险关掉 -> 刚写的那张也进名单；结构保险关掉 -> .out 进名单
        old_fresh, old_prot = retention.FRESH_S, retention.protected
        try:
            retention.FRESH_S = -1.0
            tooth_fresh = len(retention._deletable([fresh], tracked_set)[0]) == 1
            retention.protected = lambda rel: False
            tooth_prot = len(retention._deletable([shaped], tracked_set)[0]) == 1
        finally:
            retention.FRESH_S, retention.protected = old_fresh, old_prot
        # 牙：把语料那一条摘掉 -> 同一份 dets_ 立刻变成可删（真 `protected` 下它可删 0 项）
        try:
            retention.protected = (lambda rel: old_prot(rel)
                                   and not os.path.basename(rel).startswith(
                                       ("dets_", "relock_dets_", "relock_")))
            tooth_corpus = len(retention._deletable([corpus], tracked_set)[0]) == 1
        finally:
            retention.protected = old_prot
        # 跟踪名单空掉 -> 被跟踪的进名单。`now` 推到很远：`tools/panel_core.py` 刚被这一轮的
        # 改动写过，不推的话它会先被十分钟保险挡住，这颗牙就量不到跟踪那一层。
        far = time.time() + 4.0 * retention.FRESH_S
        tooth_tracked = (why2["tracked"] == 1
                         and len(retention._deletable([mine], set(), now=far)[0]) == 1)
        tooth_hud = False
        saved = core.JUNK_DEBUG_RE
        try:
            core.JUNK_DEBUG_RE = __import__("re").compile(
                r"^(?:now_|chang_|tmp_|calib_|judge_|hostcap|mumucap_|nav_stuck_|_)"
                r".*\.(?:png|json|pid)$")
            tooth_hud = avi not in (core.collect_junk()[0]["files"] or []) and \
                not any("hud_now_1234" in p for c in core.collect_junk()
                        for p in (c["files"] or []))
        finally:
            core.JUNK_DEBUG_RE = saved
        print(f"临时树：frames 5 个文件、runs 记 4098 B、charts 只量不删 = {size_ok}")
        print(f"清理后 frames 剩 {sorted(after)}（窗内的留、窗外的删、没编号的删、刚写的留）、"
              f"录像留着 = {junk_ok}；退出码 {rc}")
        print(f"录像归到媒体那一类（不是垃圾）= {media_ok}")
        print(f"保险：结构豁免 {prot}、投票语料豁免 {corpus_ok}、被跟踪的不删 "
              f"{why['tracked'] if 'tracked' in why else 0}"
              f"/{why2['tracked']}、junk 形状但受保护 -> 可删 {len(ok)} 项 = "
              f"{prot and why2['tracked'] == 1 and ok == []}")
        print(f"牙：时间保险关掉 -> 刚写的进名单 {tooth_fresh}、结构保险关掉 -> .out 进名单 "
              f"{tooth_prot}、语料豁免摘掉 -> dets_ 进名单 {tooth_corpus}、"
              f"跟踪名单空掉 -> 被跟踪的进名单 {tooth_tracked}、"
              f"JUNK_DEBUG_RE 去掉 hud_ -> 没编号的 HUD dump 不再算垃圾 {tooth_hud}")
        return (size_ok and junk_ok and media_ok and prot and corpus_ok
                and why2["tracked"] == 1 and ok == []
                and tooth_fresh and tooth_prot and tooth_corpus and tooth_tracked and tooth_hud)
    finally:
        core.ROOT = core_root
        rlog.retarget(str(ROOT / "research"))
        shutil.rmtree(tmp, ignore_errors=True)


def part2():
    """表自己的自洽：不依赖盘上现在多大（超预算不是这个探针该红的原因）。"""
    keys = [b[0] for b in retention.BUDGETS]
    caps = {b[0]: b[2] for b in retention.BUDGETS}
    total = caps.get("research")
    rules = {b[3] for b in retention.BUDGETS}
    ok_unique = len(keys) == len(set(keys))
    ok_pos = all(b[2] > 0 for b in retention.BUDGETS)
    ok_rule = rules <= {"junk", "frames", "media", "count", "report"}
    ok_fit = all(c <= total for k, c in caps.items() if k != "research")
    # 桶的路径要么是一个目录，要么是一串文件（`runmedia` 直接盯着 runs/ 里的录像文件）。
    ok_path = all((os.path.isdir(b) if isinstance(b, str) else all(os.path.exists(p) for p in b))
                  for b in (retention._bucket(k) for k in keys))
    print(f"表：{len(keys)} 个桶、键唯一 {ok_unique}、上限为正 {ok_pos}、规则合法 {ok_rule}"
          f"（{sorted(rules)}）、分桶都不超过总闸 {ok_fit}、路径都在 {ok_path}")
    return ok_unique and ok_pos and ok_rule and ok_fit and ok_path


def part3():
    """接线：面板每轮要把超预算的桶说出来；清理判据里要看得见 runs 的录像。

    2026-10-19（用户「优化磁盘空间管理」）起，面板的 `auto_clean` 不再自己写一份删除循环 ——
    它调 `retention.auto()`（同一套判据、同一张表、同样的三道保险），并且**超上限时它真的
    动手**（从前只报一句「超了，去跑 retention.py」）。这一关量的就是这条接线：
    `auto_clean` 里必须有 `retention.auto()`、必须按返回的 `over` 说话、而且不许再有一份
    自己的 `collect_junk()` 删除循环（两份判据就是两个真相）。
    """
    src = (ROOT / "tools" / "flet_gui.py").read_text(encoding="utf-8")
    core_src = (ROOT / "tools" / "panel_core.py").read_text(encoding="utf-8")
    body = src.split("def auto_clean(self):", 1)[-1].split("\n    async def ", 1)[0]
    ok_panel = ("res = retention.auto()" in body and 'res.get("over")' in body
                and "collect_junk()" not in body and "retention.fmt(" in body)
    mutant = body.replace("res = retention.auto()", "res = {}")
    ok_mut = mutant != body and "res = retention.auto()" not in mutant
    ok_core = ".avi" in core_src and "rlog.RUNS" in core_src
    print(f"面板：每轮调 retention.auto() 并按 over 说话 = {ok_panel}；牙（拿掉那次调用）"
          f"-> 接线判据变红 {ok_mut}；清理判据里看得见 runs 的录像 = {ok_core}")
    return ok_panel and ok_mut and ok_core


def part4():
    """结算截图那一桶的「留 result_mp* + 最近 RESULT_KEEP_N 张」规则（2026-10-09 新加）。

    真上限是 80 MB，临时树里造不出那么多，所以把上限临时压到 0 让规则开火；顺带用同一棵树
    量一颗牙：把 `RESULT_KEEP_PREFIX` 换成谁也不认的前缀，mp* 那张就必须进删除名单。
    """
    real_budgets, real_prefix = retention.BUDGETS, retention.RESULT_KEEP_PREFIX
    core_root = core.ROOT
    out = []
    try:
        for neuter in (False, True):
            tmp = tempfile.mkdtemp(prefix="retention_count_")
            r = os.path.join(tmp, "research")
            os.makedirs(os.path.join(r, "result"), exist_ok=True)
            with open(os.path.join(r, "results.jsonl"), "w", encoding="utf-8") as f:
                f.write(json.dumps({"tag": "g900"}) + "\n")
            # 45 张非 mp，mtime 依次变旧（g700 最新）；再加一张最老的 mp 取证。
            for i in range(45):
                p = os.path.join(r, "result", "result_g%03d.png" % (700 + i))
                with open(p, "wb") as f:
                    f.write(b"x" * 8)
                os.utime(p, (OLD - i * 60.0, OLD - i * 60.0))
            mp = os.path.join(r, "result", "result_mp9.png")
            with open(mp, "wb") as f:
                f.write(b"x" * 8)
            os.utime(mp, (OLD - 9999.0, OLD - 9999.0))
            rlog.retarget(r)
            core.ROOT = r
            core_results, core.RESULTS = core.RESULTS, os.path.join(r, "results.jsonl")
            retention.BUDGETS = tuple((k, l, (0 if k == "result" else cap), rule, note)
                                      for k, l, cap, rule, note in real_budgets)
            retention.RESULT_KEEP_PREFIX = "zzz" if neuter else real_prefix
            try:
                with redirect_stdout(io.StringIO()):
                    retention.go(media=True)
            finally:
                core.RESULTS = core_results
            out.append(set(os.listdir(os.path.join(r, "result"))))
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        retention.BUDGETS = real_budgets
        retention.RESULT_KEEP_PREFIX = real_prefix
        core.ROOT = core_root
        rlog.retarget(str(ROOT / "research"))
    shipped, squeezed = out[0], out[1]
    keep_mp = "result_mp9.png" in shipped
    keep_new = all(("result_g%03d.png" % (700 + i)) in shipped for i in range(retention.RESULT_KEEP_N))
    drop_old = not any(("result_g%03d.png" % (700 + i)) in shipped for i in range(40, 45))
    shipped_ok = keep_mp and keep_new and drop_old
    tooth_ok = "result_mp9.png" not in squeezed
    print(f"结算截图：mp 取证留着 {keep_mp}、最近 {retention.RESULT_KEEP_N} 张都留着 {keep_new}、"
          f"更老的五张删掉 {drop_old}（共留 {len(shipped)} 张）= {shipped_ok}")
    print(f"  牙：把 RESULT_KEEP_PREFIX 换成谁也不认的 -> mp 那张被删掉 = {tooth_ok}")
    return shipped_ok and tooth_ok


def part5():
    """调试截图那一桶的 frames 规则（2026-10-09 新加）。

    这一桶从前是 junk 规则：`--go` 只删面板判据认得的垃圾形状，而 226 张里有 208 张不是那个形状
    （`hudreject_kt*`、`mp*`、`nav_stuck_*`……），于是桶被顶在 150 MB 之上**没人能动**。
    现在垃圾照删，剩下的取证帧只在 `--media` 且超上限时按「留 mp* + 最近 FRAME_KEEP_N 张」压。

    真上限是 150 MB，临时树里造不出那么多，所以把上限临时压到 0 让规则开火；同一棵树上量两件事：
    不给 `--media` 时取证帧一张都不许动（纪律），给 `--media` 时保留集之外的全删；牙 = 把
    `FRAME_KEEP_PREFIX` 换成谁也不认的前缀，那张最老的 mp 取证就必须进删除名单。
    """
    real_budgets, real_prefix = retention.BUDGETS, retention.FRAME_KEEP_PREFIX
    core_root = core.ROOT
    out = []
    try:
        for media, neuter in ((False, False), (True, False), (True, True)):
            tmp = tempfile.mkdtemp(prefix="retention_frames_")
            r = os.path.join(tmp, "research")
            os.makedirs(os.path.join(r, "frames"), exist_ok=True)
            with open(os.path.join(r, "results.jsonl"), "w", encoding="utf-8") as f:
                f.write(json.dumps({"tag": "g900"}) + "\n")
            # 70 张非 mp，mtime 依次变旧（f000 最新）；再加一张最老的 mp 取证、一张窗外的垃圾、
            # 一张文字日志（protected）。
            for i in range(70):
                p = os.path.join(r, "frames", "frame_f%03d.png" % i)
                with open(p, "wb") as f:
                    f.write(b"x" * 8)
                os.utime(p, (OLD - i * 60.0, OLD - i * 60.0))
            for name, age in (("mp_take.png", 9999.0),
                              ("hudreject_g800_stale.png", 5000.0),
                              ("note.out", 5000.0)):
                p = os.path.join(r, "frames", name)
                with open(p, "wb") as f:
                    f.write(b"x" * 8)
                os.utime(p, (OLD - age, OLD - age))
            rlog.retarget(r)
            core.ROOT = r
            core_results, core.RESULTS = core.RESULTS, os.path.join(r, "results.jsonl")
            retention.BUDGETS = tuple((k, l, (0 if k == "frames" else cap), rule, note)
                                      for k, l, cap, rule, note in real_budgets)
            retention.FRAME_KEEP_PREFIX = "zzz" if neuter else real_prefix
            try:
                with redirect_stdout(io.StringIO()):
                    retention.go(media=media)
            finally:
                core.RESULTS = core_results
            out.append(set(os.listdir(os.path.join(r, "frames"))))
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        retention.BUDGETS = real_budgets
        retention.FRAME_KEEP_PREFIX = real_prefix
        core.ROOT = core_root
        rlog.retarget(str(ROOT / "research"))
    no_media, with_media, squeezed = out
    keep_mp = "mp_take.png" in with_media
    keep_new = all(("frame_f%03d.png" % i) in with_media for i in range(retention.FRAME_KEEP_N))
    drop_old = not any(("frame_f%03d.png" % i) in with_media
                       for i in range(retention.FRAME_KEEP_N, 70))
    drop_junk = "hudreject_g800_stale.png" not in with_media
    keep_log = "note.out" in with_media
    shipped_ok = keep_mp and keep_new and drop_old and drop_junk and keep_log
    idle_ok = ("frame_f000.png" in no_media and "frame_f069.png" in no_media
               and "mp_take.png" in no_media and "hudreject_g800_stale.png" not in no_media)
    tooth_ok = "mp_take.png" not in squeezed
    print(f"调试截图：mp 取证留着 {keep_mp}、最近 {retention.FRAME_KEEP_N} 张都留着 {keep_new}、"
          f"更老的 {70 - retention.FRAME_KEEP_N} 张删掉 {drop_old}、垃圾照删 {drop_junk}、"
          f"文字日志不碰 {keep_log}（共留 {len(with_media)} 张）= {shipped_ok}")
    print(f"  不给 --media：取证帧一张没动 {idle_ok}（只剩垃圾被删）")
    print(f"  牙：把 FRAME_KEEP_PREFIX 换成谁也不认的 -> mp 那张被删掉 {tooth_ok}")
    return shipped_ok and idle_ok and tooth_ok


def part6():
    """去重与无人值守那条（2026-10-19 新加，用户「优化磁盘空间管理」）。

    两件本事，各自量行为、各配一颗牙：

    * `dedupe()` —— 同一串字节在 research/ 里存多份（`recordings/mp2/cap` 那种抽帧语料，
      一张 1 MB 的页面重复 80 次，2026-10-19 实测 100 组 / 冗余 103.8 MB）。把重复的换硬链接：
      **两个名字同一个 inode**、内容一个字节不动、每个路径照旧读得出来。三道不肯动的理由各量
      一条：太小（< `DEDUPE_MIN`）、太新（< `DEDUPE_AGE_S`）、被跟踪/受保护。牙 = 把年龄门槛
      推到未来（`age_s = -1` 的等价物）⇒ 刚写的那对立刻被链上。
    * `auto()` —— 垃圾 + 取证桶按保留集压 + 去重（六小时一次），**录像与归档不在自动范围内**：
      把 recordings 的上限临时压到 0，同一棵树 `go(media=True)` 会删、`auto()` 一个都不许删。
      顺带量：它往 `research/logs/retention.log` 记了一行账。
    """
    real_budgets = retention.BUDGETS
    core_root = core.ROOT
    tmp = tempfile.mkdtemp(prefix="retention_dedupe_")
    try:
        r = os.path.join(tmp, "research")
        for d in ("frames", "runs", "result", "charts", "recordings", "archive", "logs"):
            os.makedirs(os.path.join(r, d), exist_ok=True)
        with open(os.path.join(r, "results.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"tag": "g900"}) + "\n")
        blob = b"Z" * (retention.DEDUPE_MIN + 4096)
        old = time.time() - retention.DEDUPE_AGE_S - 600.0    # 过年龄门槛才可能被链
        pair = []
        for name in ("a.png", "b.png"):
            p = os.path.join(r, "recordings", name)
            with open(p, "wb") as f:
                f.write(blob)
            os.utime(p, (old - 90, old - 90))
            pair.append(p)
        small = os.path.join(r, "recordings", "tiny.png")
        with open(small, "wb") as f:
            f.write(b"Q" * 1024)
        os.utime(small, (old - 90, old - 90))
        fresh = os.path.join(r, "frames", "fresh.png")
        with open(fresh, "wb") as f:
            f.write(blob)
        rlog.retarget(r)
        core.ROOT = r
        core_results, core.RESULTS = core.RESULTS, os.path.join(r, "results.jsonl")
        d = retention.dedupe()
        linked = (os.stat(pair[0]).st_ino == os.stat(pair[1]).st_ino)
        intact = open(pair[1], "rb").read() == blob
        counted = d["linked"] == 1 and d["freed"] >= retention.DEDUPE_MIN
        small_untouched = os.stat(small).st_ino != os.stat(pair[0]).st_ino
        fresh_untouched = os.stat(fresh).st_ino not in (os.stat(pair[0]).st_ino,)
        # 牙：年龄门槛推到未来 -> 刚写的那份也被链上（说明挡住它的正是年龄，不是别的）
        d2 = retention.dedupe(age_s=-1.0)
        tooth_age = d2["linked"] >= 1
        # auto() 不动录像：把 recordings 的上限压到 0，go(media=True) 会删，auto() 不会
        retention.BUDGETS = tuple((k, l, (0 if k == "recordings" else cap), rule, note)
                                  for k, l, cap, rule, note in real_budgets)
        rec = os.path.join(r, "recordings", "take.mp4")
        with open(rec, "wb") as f:
            f.write(b"M" * 9000)
        os.utime(rec, (OLD - 9000, OLD - 9000))
        with redirect_stdout(io.StringIO()):
            retention.go(media=True)
        go_took_it = not os.path.exists(rec)
        with open(rec, "wb") as f:
            f.write(b"M" * 9000)
        os.utime(rec, (OLD - 9000, OLD - 9000))
        with redirect_stdout(io.StringIO()):
            res = retention.auto()
        auto_kept = os.path.exists(rec)
        ledger = os.path.join(r, "logs", "retention.log")
        ledger_ok = os.path.exists(ledger) and "auto" in open(ledger, encoding="utf-8").read()
        ded6 = res.get("dedupe") or {}
        print(f"去重：两个名字同一 inode {linked}、内容照旧 {intact}、计数 {counted}、"
              f"太小没动 {small_untouched}、太新没动 {fresh_untouched}、"
              f"牙（年龄推到未来 -> 刚写的被链）{tooth_age}")
        print(f"auto：go(media) 会删录像 {go_took_it}、auto 不动录像 {auto_kept}、"
              f"记账行 {ledger_ok}（这次去重链了 {ded6.get('linked')} 个）")
        return (linked and intact and counted and small_untouched and fresh_untouched
                and tooth_age and go_took_it and auto_kept and ledger_ok)
    finally:
        retention.BUDGETS = real_budgets
        core.RESULTS = core_results
        core.ROOT = core_root
        rlog.retarget(str(ROOT / "research"))
        shutil.rmtree(tmp, ignore_errors=True)


def part7():
    """文档点名的取证帧 + 到期回放语料（2026-10-19）。

    * `referenced()` 从**已跟踪的文件**里捞出 `research/…` 名字（`AGENTS.md` 与探针 docstring
      里写着的路标），`go()` 拿它给 junk/frames/count/media 四条规则各加一层「这一个别删」。
      临时树里把 `referenced()` 换成两张帧名、把 frames 上限压到 0：按正常规则它们最老、
      第一个被删；有了这层就必须活着。牙 = 把 `referenced()` 换回空集 ⇒ 两张都没了。
    * `research/archive/media/our_survival_open_0930/` 是 `freshfeed.py` / `spritebars.py` 的输入，
      而 archive 桶是 media 规则（最老优先）—— 必须被 `protected()` 整目录挡住。
    """
    real_budgets, real_ref = retention.BUDGETS, retention.referenced
    core_root = core.ROOT
    pins = ("pinned_keep.png", "story_now.png")
    out = []
    try:
        for neuter in (False, True):
            tmp = tempfile.mkdtemp(prefix="retention_pin_")
            r = os.path.join(tmp, "research")
            for d in ("frames", "runs", "result", "charts", "recordings", "archive", "logs"):
                os.makedirs(os.path.join(r, d), exist_ok=True)
            with open(os.path.join(r, "results.jsonl"), "w", encoding="utf-8") as f:
                f.write(json.dumps({"tag": "g900"}) + "\n")
            for name in pins:
                p = os.path.join(r, "frames", name)
                with open(p, "wb") as f:
                    f.write(b"x" * 8)
                os.utime(p, (OLD - 99999.0, OLD - 99999.0))     # 最老：正常规则第一个删它
            for i in range(70):
                p = os.path.join(r, "frames", "frame_f%03d.png" % i)
                with open(p, "wb") as f:
                    f.write(b"x" * 8)
                os.utime(p, (OLD - i * 60.0, OLD - i * 60.0))
            rlog.retarget(r)
            core.ROOT = r
            core_results, core.RESULTS = core.RESULTS, os.path.join(r, "results.jsonl")
            retention.BUDGETS = tuple((k, l, (0 if k == "frames" else cap), rule, note)
                                      for k, l, cap, rule, note in real_budgets)
            retention.referenced = (lambda: set()) if neuter else (lambda: set(pins))
            try:
                with redirect_stdout(io.StringIO()):
                    retention.go(media=True)
            finally:
                core.RESULTS = core_results
            out.append(set(os.listdir(os.path.join(r, "frames"))))
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        retention.BUDGETS = real_budgets
        retention.referenced = real_ref
        core.ROOT = core_root
        rlog.retarget(str(ROOT / "research"))
    shipped, squeezed = out
    keep_ok = all(n in shipped for n in pins)
    drop_ok = sum(1 for n in shipped if n.startswith("frame_f")) <= retention.FRAME_KEEP_N
    tooth = not any(n in squeezed for n in pins)
    arch = retention.protected("research/archive/media/our_survival_open_0930/00001.jpg")
    arch_neo = not retention.protected("research/archive/media/other/00001.jpg")
    print(f"文档点名的帧：被点名的两张活着 {keep_ok}、其余照常压到 {retention.FRAME_KEEP_N} 张以内 "
          f"{drop_ok}；牙（点名单空掉）-> 两张被删 {tooth}")
    print(f"回放语料整目录受保护 {arch}（别的归档目录不受保护 {arch_neo}）")
    return keep_ok and drop_ok and tooth and arch and arch_neo


def part8():
    """不随仓库分发的那几份文档也参与点名（2026-10-22）。

    `AGENTS.md`、`docs/panel_spec.md`、`tools/probes/README.md` 已从 git 跟踪里移除，
    `referenced()` 因此改成「git grep + 直接读 `LOCAL_DOCS` 这几份盘上的文件」。
    临时树里把 `retention.ROOT` 指向一棵**不是 git 仓库**的目录（顺带证明 git 不可用时
    仍然读本地文档），只写一份 `AGENTS.md` 点名某张帧 ⇒ 必须被捞到。
    牙 = 把 `LOCAL_DOCS` 清空 ⇒ 捞不到。
    """
    real_root, real_docs = retention.ROOT, retention.LOCAL_DOCS
    tmp = tempfile.mkdtemp(prefix="retention_local_")
    name = "local_keep.png"
    try:
        os.makedirs(os.path.join(tmp, "research", "frames"), exist_ok=True)
        with open(os.path.join(tmp, "AGENTS.md"), "w", encoding="utf-8") as f:
            f.write("取证帧：`research/frames/%s`\n" % name)
        retention.ROOT = tmp
        keep_ok = name in retention.referenced()
        retention.LOCAL_DOCS = ()
        tooth = name not in retention.referenced()
    finally:
        retention.ROOT, retention.LOCAL_DOCS = real_root, real_docs
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"本地文档点名：AGENTS.md 里的帧被捞到 {keep_ok}；牙（LOCAL_DOCS 清空）-> 捞不到 {tooth}")
    return keep_ok and tooth


def main():
    ok = (part1() and part2() and part3() and part4() and part5() and part6() and part7()
          and part8())
    print("RETENTION " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
