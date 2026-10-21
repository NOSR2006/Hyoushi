"""探针：面板口径的冻结表 + 「读的字段必须是存在的字段」。

换视图最容易悄悄改掉的是**口径**。口径改了不报错、不写日志、不崩，只是列表顺序不同、搜索查不
到东西、结算行少一格 —— 用户只会觉得「怎么跟以前不一样」，而没有任何东西会红。当初换渲染器时
两个面板各实现一遍，于是有一个探针拿同一份输入各跑一次、要求逐位相同；现在只剩一个面板，那个
做法没有第二个实现可比了，于是这一关改成**冻结表**：把当前口径逐位写死，改动必须显式改表。

这一关当初抓到的两类真实缺陷（都是修完才写成断言的），现在就冻在这里：

  1. `panel_core.song_sort_key` 读 `s.get("roma")`，而清单里的字段叫 `titleRomaji` —— 87 首
     里 `roma` 命中 0。读错字段不报错，只会静默退回中文标题：「罗马音序」实际按中文码位排。
     `filtered_songs` 的搜索键表里同样有死字段 `roma`/`titleZh`，而且四个拼音字段全缺 ——
     搜索框查不到罗马音（"mayoiuta"）和拼音（"liu zhao nian" / "lzny"）。PART 4 守着这一类。
  2. 排序键曾经根本不是同一套：三种模式在 87 首里分别差 28/78/85 处。PART 3 守着顺序。
  3. `panel_core.JUNK_TAGGED_RE` 把 parked 取证的 `-a{k}` 后缀**放进了捕获组**，于是
     `dets_g417-a1.json` 的编号读成 `g417-a1`、而滚动窗表里只有 `g417` ⇒ 每一份 parked 取证
     都被判成「窗外取证」，被面板的每轮自动清理当场 `os.remove`。PART 6 守着这个判定。
  4. `panel_core.next_tag` 在计数器指向已占用的号时**直接跳到「从 1 向上」**，于是返回 g001 ——
     低段并没有占满（`results_full.jsonl` 只从 g142 起，更早的取证早就不在盘上），面板会从
     g001 一路发下去。PART 7 守着「先往上续号」这个顺序。

**它不碰模拟器、不起 run.py、不写任何东西**（只读真实语料；`hist_*` 的输入是内存里的记录；
PART 6 的目录夹具建在系统临时目录里，建完就删）。

判定：任一 PART FAIL → 退出码 1。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)

FAILS: list[str] = []


def check(label, cond, extra=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"  {extra}" if extra else ""))
    if not cond:
        FAILS.append(label)
    return cond


# ---------------------------------------------------------------------------
# 读过的键都要记下来 —— 「你读的字段必须是存在的字段」
# ---------------------------------------------------------------------------
READS: set[str] = set()


class Watched(dict):
    """A dict that remembers which keys were read.

    这就是本探针的核心手法：不去正则扫源码（那只能看出「写了哪个字符串」），而是让数据自己
    记账 —— 谁读了什么键，键在不在，一目了然。`panel_core` 读 `roma` 之所以能活到今天，就是
    因为 `dict.get` 对不存在的键只会安静地返回 None。
    """

    def get(self, key, default=None):
        READS.add(key)
        return super().get(key, default)

    def __getitem__(self, key):
        READS.add(key)
        return super().__getitem__(key)

    def __contains__(self, key):
        READS.add(key)
        return super().__contains__(key)


def watch(obj):
    """Recursively wrap dicts/lists so every field read inside gets recorded."""
    if isinstance(obj, dict):
        return Watched({k: watch(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [watch(v) for v in obj]
    return obj


def scan_fields(manifest, touch):
    """Run `touch(song)` on every song; return {field: [songs that read it while absent]}.

    `touch` receives a `Watched` song, so anything it reads lands in READS. A field that is read
    and is not in that song's own key set (nor in any of its difficulties') is the defect: the
    caller asked for something this manifest never promised.
    """
    bad: dict[str, list] = {}
    for s in manifest.get("songs", []):
        allowed = set(s.keys())
        for d in (s.get("difficulties") or []):
            allowed |= set(d.keys())
        sw = watch(s)
        READS.clear()
        touch(sw)
        for k in sorted(READS - allowed):
            bad.setdefault(k, []).append(s.get("title"))
    return bad


RECORDS = [
    # 全完美
    {"tag": "p1", "ts": "01-01 00:00", "song": "甲", "diff": "EXPERT", "rc": 0,
     "all_perfect": 1, "full_combo": 1, "non_perfect": 0, "perfect": 100,
     "great": 0, "good": 0, "bad": 0, "miss": 0},
    # 全连但有 GREAT
    {"tag": "p2", "ts": "01-01 00:01", "song": "乙", "diff": "HARD", "rc": 0,
     "all_perfect": 0, "full_combo": 1, "non_perfect": 3, "perfect": 97,
     "great": 3, "good": 0, "bad": 0, "miss": 0},
    # 漏键
    {"tag": "p3", "ts": "01-01 00:02", "song": "丙", "diff": "NORMAL", "rc": 0,
     "all_perfect": 0, "full_combo": 0, "non_perfect": 5, "perfect": 90,
     "great": 2, "good": 1, "bad": 0, "miss": 2},
    # 异常局：结果页没读出来
    {"tag": "p4", "ts": "01-01 00:03", "song": "丁", "diff": "EASY", "rc": 1},
    # 全零
    {"tag": "p5", "ts": "01-01 00:04", "song": "戊", "diff": "EXPERT", "rc": 0,
     "all_perfect": 0, "full_combo": 0, "non_perfect": 0, "perfect": 0,
     "great": 0, "good": 0, "bad": 0, "miss": 0},
    # 只带 tag 与 ts（旧记录的形状）
    {"tag": "p6", "ts": "01-01 00:05"},
    # 数字是字符串
    {"tag": "p7", "ts": "01-01 00:06", "song": "己", "diff": "EXPERT", "rc": 0,
     "all_perfect": 0, "full_combo": 0, "non_perfect": "2", "perfect": "98",
     "great": "2", "good": "0", "bad": "0", "miss": "0"},
    # 带重开次数
    {"tag": "p8", "ts": "01-01 00:07", "song": "庚", "diff": "EXPERT", "rc": 0,
     "aborts": 2, "all_perfect": 1, "full_combo": 1, "non_perfect": 0,
     "perfect": 50, "great": 0, "good": 0, "bad": 0, "miss": 0},
]

# 冻结表：纯函数。每格是 (输入, 期望输出)，None 期望 = 「抛异常」，异常类型写在边上。
GOLDEN_PURE = [
    ("chart_id", [({"hits": "research/charts/0056_03.hits.json"}, "0056_03"),
                  ({"hits": "research/charts/0001_00.hits.json"}, "0001_00"),
                  ({"hits": ""}, ""), ({}, ""), ({"hits": None}, "")]),
    ("fmt_size", [(0, "0 KB"), (1, "0 KB"), (512, "0 KB"), (1023, "1 KB"), (1024, "1 KB"),
                  (1536, "2 KB"), (1048576, "1.0 MB"), (1073741824, "1024.0 MB")]),
    ("lv", [({"level": 3, "sortLevel": 3.5}, "3.5"), ({"level": 7}, "7"),
            ({"sortLevel": 9.5}, "9.5"), ({"level": 7, "displayLevel": 6}, "7"),
            ({"level": None}, "?")]),
]

# 冻结表：结算行。tag -> (badge, 六个数, cells 摘要, 排序列的 13 个键)
# `cells` 摘要 2026-10-09 重钉过三次：用户 m11451「结算记录里数数别留空」把数字列从留空改成
# 印占位符，用户 m11595「占位符与正常数的差距还是太小了」又把占位符从 `0` 改成 `core.HIST_BLANK`
# （`—`）—— `0` 是一个读数（真的零），和「没量到」长得一样；用户 m11846「仅完成未FC与AP的记录
# 状态标为成功，现在的破折号有歧义」又把判定列那个 `—` 改成 `成功`（同一个 `—` 在数字列里读作
# 「没量到」，两件事不能共用一个字形）。摘要由 `research/experiments/rowgolden.py` 打出来
# （它把八条夹具的 `hist_cells` 逐个打印）。
GOLDEN_ROWS = {
    "p1": ("AP", (100, 0, 0, 0, 0, 0), "cf0ebf4e307c916e",
           ("01-01 00:00", "甲", 3, 0, None, 0, 100, 0, 0, 0, 0, None, None)),
    "p2": ("FC", (97, 3, 0, 0, 0, 3), "d83d53a304764a78",
           ("01-01 00:01", "乙", 2, 1, None, 3, 97, 3, 0, 0, 0, None, None)),
    "p3": ("成功", (90, 2, 1, 0, 2, 5), "612f68d5183b6a94",
           ("01-01 00:02", "丙", 1, 2, None, 5, 90, 2, 1, 0, 2, None, None)),
    "p4": ("中断", (None, None, None, None, None, None), "ac57862cda8e2a75",
           ("01-01 00:03", "丁", 0, 4, None, None, None, None, None, None, None, None, None)),
    "p5": ("成功", (0, 0, 0, 0, 0, 0), "ce64afa06f600c5b",
           ("01-01 00:04", "戊", 3, 3, None, 0, 0, 0, 0, 0, 0, None, None)),
    "p6": ("读取失败", (None, None, None, None, None, None), "9bdd81a12f09732d",
           ("01-01 00:05", "", -1, 4, None, None, None, None, None, None, None, None, None)),
    "p7": ("成功", (98, 2, 0, 0, 0, 2), "43a4aec884f04750",
           ("01-01 00:06", "己", 3, 2, None, 2, 98, 2, 0, 0, 0, None, None)),
    "p8": ("AP", (50, 0, 0, 0, 0, 0), "81117fd2bbebaa44",
           ("01-01 00:07", "庚", 3, 0, 2, 0, 50, 0, 0, 0, 0, None, None)),
}

# 冻结表：四种排序下的 musicId 顺序（全序列摘要 + 前 8 个，够定位也够读）。
# 2026-10-09 重钉过一次：`tools/fetch_charts.py` 从 haneoka 目录补进 Odd Dice（`0111_00..03`）
# ⇒ 库 87 → 88 首，四种排序的全序列摘要全变（前 8 个只有「未AP优先」变）。这是**数据真的变了**，
# 不是回归：重钉用的算法就是下面 `part3` 那一份（`research/experiments/pdgolden.py` 打出来）。
GOLDEN_ORDER = {
    # 2026-10-21 重拍：曲库 87 → 90 首（上游 2026-10-18 加了 3 首，`research/charts/manifest.json`
    # 的 mtime 就是那一天）。改的只有四条全序列的哈希 + `未AP优先` 的头 —— 新曲子没打过，按定义
    # 排在最前面，其余三种排序的头一个字没动。这不是代码回归：排序键一个字节都没改。
    "乐队优先": ("50a73c738e7ff6e6",
                 ["100001", "100002", "100003", "100004", "100005", "100006", "100007",
                  "100008"]),
    "罗马音序": ("76f556711e6c70b5",
                 ["100041", "100107", "100031", "100043", "100026", "100053", "100038",
                  "100019"]),
    "难度升序": ("6864346034a85a02",
                 ["100007", "100019", "100035", "100092", "100072", "100087", "100028",
                  "100057"]),
    "未AP优先": ("3e4a614460a440f7",
                 ["100002", "100112", "100037", "100041", "100113", "100110", "100111",
                  "100106"]),
}

NUM_KEYS = ("perfect", "great", "good", "bad", "miss", "non_perfect")


def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def part1(core):
    print("PART 1 纯函数的冻结表")
    for name, table in GOLDEN_PURE:
        fn = getattr(core, name)
        for item, want in table:
            try:
                got = fn(item)
                ok = got == want
            except Exception as e:                                  # noqa: BLE001
                got, ok = f"{type(e).__name__}", False
            check(f"{name}({item!r}) == {want!r}", ok, f"got={got!r}")
    # 数据之外的输入：`level` 键在、值是 None。把字符串 "None" 印在难度列上不值得保住。
    check("level 为 None 时印 '?'，不印 'None'",
          core.lv({"level": None}) == "?" and "None" not in core.lv({"level": None}))
    return True


def part2(core):
    print("PART 2 结算行的冻结表")
    seen = set()
    for rec in RECORDS:
        tag = rec["tag"]
        seen.add(tag)
        want = GOLDEN_ROWS.get(tag)
        if want is None:
            check(f"{tag} 在冻结表里", False, "夹具多了一条，冻结表没跟上")
            continue
        w_badge, w_nums, w_cells, w_value = want
        got_nums = tuple(core.hist_num(rec, k) for k in NUM_KEYS)
        check(f"{tag} badge == {w_badge!r}", core.hist_badge(rec) == w_badge,
              f"got={core.hist_badge(rec)!r}")
        check(f"{tag} 六个数 == {w_nums}", got_nums == w_nums, f"got={got_nums}")
        got_cells = digest(core.hist_cells(rec))
        check(f"{tag} 十四个格子 == {w_cells}", got_cells == w_cells,
              f"got={got_cells} cells={core.hist_cells(rec)!r}")
        got_value = tuple(core.hist_value(rec, c) for c in core.HIST_COLS)
        check(f"{tag} 排序列键 == 冻结表", got_value == w_value, f"got={got_value!r}")
    missing = set(GOLDEN_ROWS) - seen
    check("冻结表里没有夹具之外的 tag", not missing, f"{sorted(missing)}")
    # 数字列**一个空格子都不留**（2026-10-09 用户 m11451：「结算记录里数数别留空，无读数就用
    # 占位符」）。列 5..13 = 重开/漏键/P/G/GD/B/M/连击/分数；时间、歌名、难度、判定四列不是数数
    # （它们本来就有字：AP / FC / 成功 / 中断 / 读取失败）。
    holes = [(r["tag"], c) for r in RECORDS for c, v in enumerate(core.hist_cells(r))
             if c >= 5 and v in ("", None)]
    check("数字列一个空格子都没有（没读数印占位符）", not holes, f"{holes[:4]}")
    # 判定列**不借占位符**（2026-10-09 用户 m11846：「仅完成未FC与AP的记录状态标为成功，现在的
    # 破折号有歧义」）：打完了、既没 AP 也没 FC 的那些（p3 漏键 / p5 全零 / p7 数字是字符串）
    # 写「成功」。同一个 `—` 在数字列里读作「没量到」—— 两件事不能共用一个字形。
    def badge_of(tag):
        return core.hist_badge(next(r for r in RECORDS if r["tag"] == tag))
    check("打完了但没 AP/FC 的判定列写「成功」，不写破折号",
          [badge_of(t) for t in ("p3", "p5", "p7")] == ["成功"] * 3
          and badge_of("p1") == "AP" and badge_of("p2") == "FC"
          and badge_of("p4") == "中断" and badge_of("p6") == "读取失败"
          and "—" not in [core.hist_cells(r)[4] for r in RECORDS],
          f"p3={badge_of('p3')!r} p5={badge_of('p5')!r} p7={badge_of('p7')!r}")
    # 带牙：把判定列那个破折号放回去，上面那条判据必须当场变红。
    def old_badge(rec):
        if rec.get("rc"):
            return "中断"
        if rec.get("all_perfect"):
            return "AP"
        if rec.get("full_combo"):
            return "FC"
        return "读取失败" if rec.get("error") or rec.get("non_perfect") is None else "—"
    tooth_badge = [r["tag"] for r in RECORDS if old_badge(r) == "—"]
    check("带牙：旧的「判定列写破折号」写法在同一份夹具上必须露出来", len(tooth_badge) >= 2,
          f"露出 {len(tooth_badge)} 条：{tooth_badge}")
    # 占位符必须**与真数分明**（2026-10-09 用户 m11595：「占位符与正常数的差距还是太小了」）：
    # 没读数恰好印 `core.HIST_BLANK`（`—`），**不是 `0`** —— `0` 是一个读数（真的是零）。
    # p4/p6 六个数全缺（中断 / 读取失败）⇒ 那九列必须一个 `0` 都没有；p5 六个数全是真 0 ⇒
    # 那九列必须一个 `—` 都没有（连击/分数仍缺，所以是「九列里的前七个」）。
    def nums_of(tag):
        rec = next(r for r in RECORDS if r["tag"] == tag)
        return core.hist_cells(rec)[5:14]
    check("没读数印的是占位符而不是 0（p4/p6 九列无 '0'）",
          all(v == core.HIST_BLANK for v in nums_of("p4") + nums_of("p6"))
          and "0" not in nums_of("p4") + nums_of("p6"),
          f"p4={nums_of('p4')} p6={nums_of('p6')}")
    check("真 0 印的是 0 而不是占位符（p5 六个数全 0）",
          nums_of("p5")[:7] == [core.HIST_BLANK, 0, 0, 0, 0, 0, 0]
          and nums_of("p5")[7:] == [core.HIST_BLANK, core.HIST_BLANK],
          f"p5={nums_of('p5')}")
    # 带牙：把旧写法（没读数就留空）放回来，同一份夹具必须当场露空格 —— 否则上面那条在量空气。
    def old_cells(rec):
        npf = core.hist_num(rec, "non_perfect")
        retries = core.hist_num(rec, "aborts")
        score = core.hist_num(rec, "score")
        return ["", rec.get("ts", ""), rec.get("song", ""), (rec.get("diff") or "").upper(),
                core.hist_badge(rec), "" if not retries else retries,
                "" if npf is None else npf, rec.get("perfect", ""), rec.get("great", ""),
                rec.get("good", ""), rec.get("bad", ""), rec.get("miss", ""),
                rec.get("combo", ""), f"{score:,}" if score is not None else ""]
    tooth = [(r["tag"], c) for r in RECORDS for c, v in enumerate(old_cells(r))
             if c >= 5 and v in ("", None)]
    check("带牙：旧的「没读数留空」写法在同一份夹具上当场露空格", len(tooth) >= 5,
          f"空格 {len(tooth)} 个：{tooth[:4]}")
    # 缺数据的行**两个方向都排最后**（2026-10-09 用户 m11595：「从大到小排序时为什么总是这些
    # 占位符排在最前面」）。次序只由 `core.hist_order` 定：有读数的一堆先排，缺数的一堆原样接在
    # 后面 —— 从前是 `key=(v is None, v)` 加 `reverse=desc`，哨兵跟着一起翻，降序时缺数行全在最前。
    def order_ok(desc):
        rows = core.hist_order(list(RECORDS), "M", desc)
        vals = [core.hist_value(r, "M") for r in rows]
        have = [v for v in vals if v is not None]
        return (vals[:len(have)] == sorted(have, reverse=bool(desc))
                and all(v is None for v in vals[len(have):])
                and len(vals) == len(RECORDS))
    check("漏键升序：有读数的在前（小→大）、缺读数的都在后", order_ok(False))
    check("漏键降序：有读数的在前（大→小）、缺读数的仍在后", order_ok(True))
    # 带牙：旧的「哨兵元组 + reverse=」写法在同一份夹具上，降序必须把缺数行翻到最前 ——
    # 否则上面两条在量空气。
    def old_order(rows, col, desc):
        def key(r):
            v = core.hist_value(r, col)
            return (v is None, v if v is not None else "")
        return sorted(rows, key=key, reverse=bool(desc))
    bad_head = core.hist_value(old_order(list(RECORDS), "M", True)[0], "M")
    good_head = core.hist_value(core.hist_order(list(RECORDS), "M", True)[0], "M")
    check("带牙：旧的「哨兵 + reverse」写法降序时缺数行排到最前", bad_head is None,
          f"旧写法降序首行 miss={bad_head!r}")
    check("带牙：同一个降序在新写法下首行是有读数的", good_head is not None,
          f"新写法降序首行 miss={good_head!r}")
    return True


def part3(core, manifest, band_rank, ap):
    print("PART 3 四种排序的冻结表")
    songs = manifest.get("songs") or []
    for mode in core.SORT_MODES:
        ids = [s["musicId"] for s in
               sorted(songs, key=lambda s: core.song_sort_key(mode, s, band_rank, ap))]
        want_digest, want_head = GOLDEN_ORDER.get(mode, (None, None))
        if want_digest is None:
            check(f"{mode} 在冻结表里", False, "排序模式多了一个，冻结表没跟上")
            continue
        got = digest(ids)
        check(f"{mode} 全序列 == {want_digest}", got == want_digest,
              f"got={got} 共 {len(ids)} 首，前 8 个 {ids[:8]}")
        check(f"{mode} 前 8 个 == 冻结表", ids[:8] == want_head, f"got={ids[:8]}")
    check("排序模式集合与冻结表一致",
          set(core.SORT_MODES) == set(GOLDEN_ORDER), f"{core.SORT_MODES}")
    return True


def part4(core, manifest):
    """本关核心：读的字段必须是存在的字段。"""
    print("PART 4 读的字段必须是清单里存在的字段")
    songs = manifest.get("songs") or []
    check("读到真实清单", len(songs) > 50, f"{len(songs)} 首")

    all_d = [(s.get("title"), d) for s in songs for d in (s.get("difficulties") or [])]
    check("真实清单每个难度都读得出难度数字",
          all(core.lv(d) and core.lv(d) != "?" for _t, d in all_d),
          f"{len(all_d)} 个")

    _cm, _nids, band_rank = core.categories(manifest)
    ap = core.ap_ids()

    def touch_all(s):
        for mode in core.SORT_MODES:
            core.song_sort_key(mode, s, band_rank, ap)
        core.song_hay(s)
        core.song_name(s)
        core.song_ap(s, ap)

    bad = scan_fields(manifest, touch_all)
    check("谱面库函数只读存在的字段", not bad,
          "" if not bad else "; ".join(f"{k}（{len(v)} 首，如 {v[0]}）" for k, v in bad.items()))

    # 带牙：同一个 watcher 必须能抓到一次坏读，否则上面那条「全过」什么也没证明。
    teeth = scan_fields(manifest, lambda s: (s.get("roma"), s.get("titleZh")))
    check("带牙：watcher 抓得到不存在的字段", set(teeth) == {"roma", "titleZh"},
          f"{sorted(teeth)} × {len(teeth.get('roma') or [])} 首")
    check("带牙：不存在的字段确实不在清单里",
          not any(k in songs[0] for k in ("roma", "titleZh")),
          f"清单字段 {sorted(songs[0])}")
    return True, band_rank, ap


def part5(core, manifest, band_rank, ap):
    """判据从数据里长出来，不写死歌名 —— 换谱面库之后这关照样有效。"""
    print("PART 5 搜索框找得到的东西")
    songs = manifest.get("songs") or []
    _cm, nids, _br = core.categories(manifest)

    def first_with(field):
        for s in songs:
            if str(s.get(field) or "").strip():
                return s
        return None

    probes = []
    for label, field, take in (("罗马音", "titleRomaji", lambda v: str(v).split()[0]),
                               ("拼音全拼", "py", lambda v: str(v)),
                               ("拼音首字母", "pyInitials", lambda v: str(v)),
                               ("乐队中文名", "bandZh", lambda v: str(v)),
                               ("中文标题", "title", lambda v: str(v))):
        s = first_with(field)
        if s:
            probes.append((label, take(s[field]).strip().lower(), s))

    for label, q, target in probes:
        rows = core.filtered_songs(manifest, q, None, nids, band_rank, ap,
                                   core.SORT_DEFAULT, False)
        found = target in rows
        check(f"按{label}搜得到 {target.get('title')!r}", found,
              f"q={q!r} 命中 {len(rows)} 首" + ("" if found else "  ← 该歌不在结果里"))
    return True


def part6(core):
    r"""parked 取证（`-a{k}` 后缀）必须跟它的 tag 一起活到滚出滚动窗为止。

    2026-10-07 实测的缺陷：`JUNK_TAGGED_RE` 把 `(?:-a\d+)?` 放进了**捕获组**，于是
    `dets_g417-a1.json` 的编号读成 `g417-a1`，而 `collect_junk` 的窗口表 `{r["tag"]}` 里
    只有 `g417` ⇒ 每一份 parked 取证都被判成「窗外取证」；`tools/flet_gui.py` 的每轮自动
    清理对这一类一律 `os.remove`。后果：`results_full.jsonl` 里 25 局 `aborts>0`、
    `runs/*.detail.log` 里 66 行「本轮中止的取证已改名」，而 `research/` 全树 4666 个文件里
    一个 `-a1` 都不剩（只有 `evidence/hud/box/` 下 27 个躲过了扫描）。`tools/run.py` 的
    `_park_attempt` 本身是对的 —— 用真函数造文件实测五个都改名成功，删它们的是这条判定。

    这一关把判定冻住：名字里的编号必须剥掉后缀；再拿 `collect_junk` 走一遍临时目录，
    窗内 tag 的 parked 文件不许出现在 stale 桶里，窗外 tag 的照旧进去。
    """
    print("PART 6 parked 取证（-a{k}）的窗口判定")
    import rlog

    want = {"dets_g417-a1.json": "g417",
            "relock_dets_g417-a2.json": "g417",
            "relock_g31-a1.json": "g31",
            "hud_t95-a1_good1.png": "t95",
            "hudreject_g417-a1_zero_good1.png": "g417"}
    got = {}
    for n in want:
        m = core.JUNK_TAGGED_RE.match(n)
        got[n] = m.group(1) if m else None
    check("parked 名字的编号要剥掉 -a{k} 后缀", got == want, f"got={got}")

    tags = {str(r.get("tag")) for r in rlog.read_records(core.RESULTS)}
    check("真实滚动窗里的编号从不带 -a 后缀",
          bool(tags) and not any("-a" in t for t in tags), f"{len(tags)} 个编号")

    tmp = tempfile.mkdtemp(prefix="bang_junk_")
    saved = (rlog.FRAMES, rlog.RUNS, rlog.RESULT, rlog.RESEARCH, core.ROOT,
             rlog.read_records, core.JUNK_TAGGED_RE)
    try:
        put = {"frames": ["hud_g417-a1_great1.png", "hud_zz999-a1_great1.png",
                          "hudreject_g417-a2_zero_good1.png"],
               "runs": ["dets_g417-a1.json", "relock_zz999.json"],
               "result": ["result_g417-a1.json"],
               "research": ["split_g417-a2.json"]}
        for sub, names in put.items():
            os.makedirs(os.path.join(tmp, sub), exist_ok=True)
            for n in names:
                with open(os.path.join(tmp, sub, n), "wb"):
                    pass
        rlog.FRAMES = os.path.join(tmp, "frames")
        rlog.RUNS = os.path.join(tmp, "runs")
        rlog.RESULT = os.path.join(tmp, "result")
        rlog.RESEARCH = os.path.join(tmp, "research")
        core.ROOT = tmp
        rlog.read_records = lambda _p: [{"tag": "g417"}]

        def stale_names():
            return {os.path.basename(p) for c in core.collect_junk()
                    if c["key"] == "stale" for p in c["files"]}

        stale = stale_names()
        check("窗内 tag 的 parked 文件不进「窗外取证」桶",
              not any("g417" in n for n in stale), f"stale={sorted(stale)}")
        check("窗外 tag 的取证照旧进「窗外取证」桶",
              {"hud_zz999-a1_great1.png", "relock_zz999.json"} <= stale,
              f"stale={sorted(stale)}")

        # 带牙：后缀塞回捕获组，窗内的 parked 文件必须当场掉进「窗外」桶 —— 这正是删证据的旧形状。
        core.JUNK_TAGGED_RE = re.compile(
            r"^(?:hud|hudreject|result|split|failed|dets|relock_dets|relock)_"
            r"([a-z]+\d+(?:-a\d+)?)[_.]")
        try:
            tooth = stale_names()
        finally:
            core.JUNK_TAGGED_RE = saved[6]
        check("带牙：后缀塞回捕获组后窗内 parked 掉进「窗外」桶",
              {"dets_g417-a1.json", "hud_g417-a1_great1.png"} <= tooth,
              f"tooth stale={sorted(tooth)}")
    finally:
        (rlog.FRAMES, rlog.RUNS, rlog.RESULT, rlog.RESEARCH, core.ROOT,
         rlog.read_records, core.JUNK_TAGGED_RE) = saved
        shutil.rmtree(tmp, ignore_errors=True)
    return True


def part7(core):
    r"""计数器指向已占用的号时，下一个号是它**上面**的第一个空号，不是从 g001 重来。

    2026-10-07 实测：`next_index` 停在 452、而 g452…g460 已被手写命令行用掉（`tag_taken` 认的是
    盘上证据，不是 `results.jsonl` 那个滚动窗），旧写法直接走「从 1 向上」的兜底分支，返回
    **g001**。低段并不是占满的：`results_full.jsonl` 只从 g142 起（更早的轮次记在别的格式里），
    它们的取证也早已不在盘上 ⇒ g001/g002 在这套判定下是自由的，面板会从这里一路发下去，
    而正确的下一个号是 g461。

    这一关用临时夹具把三件事冻住：续号优先、兜底仍在（往上一直占满才回到 1）、取号之后计数器 +1。
    """
    print("PART 7 取号：续号优先、从 1 兜底")
    import rlog

    tmp = tempfile.mkdtemp(prefix="bang_tag_")
    saved = (rlog.RESULTS, rlog.HISTORY_FULL, rlog.RUNS, rlog.FRAMES, rlog.RESULT,
             core.STATE, core.tag_taken)
    try:
        for sub in ("runs", "frames", "result"):
            os.makedirs(os.path.join(tmp, sub), exist_ok=True)
        results = os.path.join(tmp, "results.jsonl")
        with open(results, "w", encoding="utf-8") as fh:
            for t in ("g100", "g101", "g102"):
                fh.write(json.dumps({"tag": t}) + "\n")
        rlog.RESULTS = results
        rlog.HISTORY_FULL = results
        rlog.RUNS = os.path.join(tmp, "runs")
        rlog.FRAMES = os.path.join(tmp, "frames")
        rlog.RESULT = os.path.join(tmp, "result")
        core.STATE = os.path.join(tmp, "gui_state.json")     # save_state 写到这里，别碰真的

        st = {"next_index": 101}
        got = core.next_tag(st)
        check("计数器指着已占用的号时，下一个号是它上面的第一个空号",
              got == "g103", f"got={got}")
        check("取号之后计数器推进到下一格", st.get("next_index") == 104,
              f"{st.get('next_index')}")

        # 兜底那一路：往上一直占满（这里用「g100 及以上全占」模拟），才回到从 1 向上。
        core.tag_taken = lambda t: int(t[1:]) >= 100
        st2 = {"next_index": 101}
        got2 = core.next_tag(st2)
        check("往上一直占满时仍从 1 兜底", got2 == "g001", f"got={got2}")
        core.tag_taken = saved[6]

        # 带牙：把「从 1 向上」放回第一位（旧写法），同一个状态必须当场发低号。
        def old_next_tag(state):
            i = int(state.get("next_index", 1))
            if core.tag_taken(f"g{i:03d}"):
                i = next((n for n in range(1, core.TAG_SCAN_END)
                          if not core.tag_taken(f"g{n:03d}")), core.TAG_SCAN_END)
            state["next_index"] = i + 1
            return f"g{i:03d}"

        st3 = {"next_index": 101}
        tooth = old_next_tag(st3)
        check("带牙：把「从 1 向上」放回第一位，同一个状态发的是低号", tooth == "g001",
              f"tooth got={tooth}")
    finally:
        (rlog.RESULTS, rlog.HISTORY_FULL, rlog.RUNS, rlog.FRAMES, rlog.RESULT,
         core.STATE, core.tag_taken) = saved
        shutil.rmtree(tmp, ignore_errors=True)
    return True


def part8(core):
    r"""结算记录页的「来源」筛选（单人 / 多人）：两枚 chip 各自独立，模型层只认那一个戳。

    2026-10-10 用户 m13266：「记录界面加个单人多人的筛选」。两枚 chip 走的是官方 filter chip 的
    多选语义 —— 都亮 = 两半都列，都不亮 = 什么都不列（由表上已有的空态接住）。口径必须与两张
    「最近演出」卡**同一个**（`core.hist_mode`），否则同一局在卡上有、在表上却被筛掉。
    """
    print("PART 8 结算记录的来源筛选（单人 / 多人）")
    import flet_gui

    def rec(tag, multi, ts, perfect=False):
        npf = 0 if perfect else 3
        return {"tag": tag, "ts": ts, "song": "歌" + tag, "multi": multi, "rc": 0,
                "all_perfect": perfect, "full_combo": perfect, "judged": 100,
                "non_perfect": npf, "perfect": 100 - npf, "great": npf, "good": 0,
                "bad": 0, "miss": npf, "combo": 90, "score": 1000000}

    recs = {"s1": rec("s1", False, "2026-10-10 01:00:00", True),
            "s2": rec("s2", False, "2026-10-10 01:02:00"),
            "m1": rec("m1", True, "2026-10-10 01:01:00", True),
            "m2": rec("m2", True, "2026-10-10 01:03:00"),
            "m3": rec("m3", True, "2026-10-10 01:04:00")}
    m = flet_gui.HistModel()
    m.set_records(recs)
    check("默认两枚来源都亮着（两半都列）",
          m.sources == {"solo", "multi"} and len(m.tags) == 5,
          f"{sorted(m.sources)} {len(m.tags)} 行")

    m.set_source("multi", False)
    check("熄掉「多人」：表上一条多人局都不剩",
          set(m.tags) == {"s1", "s2"}, f"{m.tags}")
    check("熄掉「多人」：条数统计仍是全局的（侧边栏徽标与 chip 上的数不许跟着筛）",
          m.counts()["all"] == 5, f"{m.counts()}")

    m.set_source("solo", False)
    check("两枚都不亮：一条都不列（空态接住）",
          m.tags == [] and m.tally() == (0, 0), f"{m.tags} {m.tally()}")

    m.set_source("solo", True)
    check("只点亮「单人」：只剩单人那两条", set(m.tags) == {"s1", "s2"}, f"{m.tags}")
    m.set_source("solo", False)
    m.set_source("multi", True)
    check("只点亮「多人」：只剩多人那三条", set(m.tags) == {"m1", "m2", "m3"}, f"{m.tags}")
    check("来源筛选与判定筛选叠加（多人 + 漏键）",
          (m.set_filter("np"), set(m.tags) == {"m2", "m3"})[-1], f"{m.tags}")
    check("两张「最近演出」卡不看来源筛选（只按 mode 取自己那一半）",
          m.recent_tags(9, "multi") == ["m3", "m2", "m1"] and m.recent_tags(9, "solo") == ["s2", "s1"],
          f"multi={m.recent_tags(9, 'multi')} solo={m.recent_tags(9, 'solo')}")
    check("不认识的键不许改状态",
          (m.set_source("band", False), m.sources == {"multi"})[-1], f"{sorted(m.sources)}")

    # 带牙：旧写法（只看判定、不看来源）在同一份夹具上必须把多人局留在表上 ——
    # 否则上面那几条「熄掉之后就不剩」在量空气。
    def old_tags(model):
        kept = [r for r in model.recs.values() if core.hist_kept_for(r, model.filter)]
        return [r.get("tag", "?") for r in core.hist_order(kept, model.sort_col, model.sort_desc)]

    m.set_source("solo", True)
    m.set_source("multi", False)
    tooth = old_tags(m)
    check("带牙：旧写法（不看来源）在同一份夹具上会把多人局留在表上",
          any(core.hist_mode(recs[t]) == "multi" for t in tooth), f"tooth={tooth}")
    return True


def part9(core):
    r"""策略数字：设置页写的键 = 编排读的键。

    2026-10-10 用户 m14586 要用 CLI 跑「正推限制 0」，逐行核对时发现面板与它自己说的不是
    同一个数：设置页那个数字框写 `defaults["push_cap_ms"]`，`refresh_policy` 与开跑确认框
    念的也是它，而 `RunOrchestrator.push_ms()` 读的却是 `push_ms` —— 那个键全仓只有它一处
    读、面板从来不写，于是框里填 0 也永远返回 `PUSH_ON_MS`(10)，面板实际发的是
    `--live-push-cap 10`。这一关把「同一个数」钉在取数函数上，并带一颗牙。
    """
    print("PART 9 策略数字：面板写的键 = 编排读的键")
    defaults = {"push_cap": 1, "push_cap_ms": 0.0, "retry_cap": 3.0, "gap_min": 0.0,
                "fire_gate": 1, "runs": 1}
    o = core.RunOrchestrator({"defaults": dict(defaults)})
    check("正推上限读的是设置页那个框（0 就是 0）", o.push_ms() == 0.0, f"{o.push_ms()}")
    check("框里填 25 就是 25",
          core.RunOrchestrator({"defaults": {**defaults, "push_cap_ms": 25.0}}).push_ms() == 25.0)
    check("空 state 才落到 PUSH_ON_MS 兜底",
          core.RunOrchestrator({"defaults": {}}).push_ms() == float(core.PUSH_ON_MS))
    check("旧键名 push_ms 还认（历史状态文件）",
          core.RunOrchestrator({"defaults": {"push_ms": 7.0}}).push_ms() == 7.0)
    check("同一个 state 的另外四个取数函数各读各的键",
          (o.retry_cap(), o.gap_min(), o.fire_gate(), o.rounds()) == (3, 0.0, True, 1),
          f"{o.retry_cap()} {o.gap_min()} {o.fire_gate()} {o.rounds()}")

    gui_src = open(os.path.join(TOOLS, "flet_gui.py"), encoding="utf-8").read()
    core_src = open(os.path.join(TOOLS, "panel_core.py"), encoding="utf-8").read()
    body = core_src.split("def push_ms(self):", 1)[-1].split("def retry_cap", 1)[0]
    check("设置页写的是 push_cap_ms", '"push_cap_ms"' in gui_src)
    check("编排读的也是 push_cap_ms（新键在前、旧键只兜底）",
          '"push_cap_ms"' in body and body.index('"push_cap_ms"') < body.index('"push_ms"'))

    # 带牙：把旧写法放回来，同一份 state 必须当场返回 10 —— 否则上面第一条在量空气。
    def old_push_ms(self):
        d = self.defaults()
        try:
            return float(d.get("push_ms", core.PUSH_ON_MS))
        except (TypeError, ValueError):
            return core.PUSH_ON_MS

    got = old_push_ms(o)
    check("带牙：旧写法（读 push_ms）在同一份 state 上返回 10 而不是框里的 0",
          got == float(core.PUSH_ON_MS) and got != 0.0, f"tooth={got}")
    return True


def part10(core):
    r"""种类偏移（2026-10-10 用户 m15291 从「演奏提前量」改名）：状态里那个 dict 怎么被读成
    一份完整的表。

    2026-10-05 面板上那四个框被删过，2026-10-10 用户 m15057「把四种都放出来」让它们回到
    设置页。这一关盯 `RunOrchestrator.kind_lead()` 的三条性质：**缺的键按出厂表补**（不是
    当成 0 之外的什么东西）、**认不出的键名与读不出的值一律丢掉**（`run.py` 的
    `parse_kind_lead` 遇到不认识的种类名会拒绝整局，那不该由状态文件里一行旧数据触发）、
    以及 `--kind-lead` 的实参**只列非零的**（全零时一个字节都不多发 ⇒ 命令行与从前逐字相同）。
    """
    print("PART 10 种类偏移：状态 dict -> 完整表 -> --kind-lead 实参")
    zeros = dict.fromkeys(core.KIND_LEAD_MS, 0.0)
    check("空 state 读出来就是出厂表（全零）",
          core.RunOrchestrator({"defaults": {}}).kind_lead() == zeros)
    got = core.RunOrchestrator({"defaults": {"kind_lead": {"tap": -30, "flick": 5}}}).kind_lead()
    check("只写了两个键，另外两个按出厂补 0",
          got == {**zeros, "tap": -30.0, "flick": 5.0}, f"{got}")
    check("认不出的种类名直接丢（不许让它走到 run.py 的 --kind-lead）",
          core.RunOrchestrator({"defaults": {"kind_lead": {"banana": 9}}}).kind_lead() == zeros)
    check("读不出的值也丢（abc 不会变成异常）",
          core.RunOrchestrator({"defaults": {"kind_lead": {"tap": "abc"}}}).kind_lead() == zeros)
    check("kind_lead 根本不是 dict 也不炸",
          core.RunOrchestrator({"defaults": {"kind_lead": 7}}).kind_lead() == zeros)
    check("全零时 --kind-lead 的实参是空串（一个字都不多发）",
          core.kind_lead_arg(zeros) == "", repr(core.kind_lead_arg(zeros)))
    check("有值时按 种类=毫秒 拼、只列非零的、顺序照 KIND_LEAD_MS",
          core.kind_lead_arg({**zeros, "tap": -30.0, "flick": 5.0}) == "tap=-30,flick=5",
          repr(core.kind_lead_arg({**zeros, "tap": -30.0, "flick": 5.0})))
    check("日志表头那一串与实参同源（只是写法不同）",
          core.kind_lead_text({**zeros, "tap": -30.0, "flick": 5.0}) == "tap-30 flick+5",
          repr(core.kind_lead_text({**zeros, "tap": -30.0, "flick": 5.0})))

    # 尾判滑键（用户 m52916「能否将尾滑偏移加入设置」）：它是**另一格**，不是一个种类 ——
    # 状态键 `tail_flick_lead`（不在 `kind_lead` 那个 dict 里），缺省 = 出厂值
    # `core.TAIL_FLICK_LEAD_DEFAULT`，且那份必须与 `player.TAIL_FLICK_LEAD_MS` 同源
    # （面板显示 10、实机按别的数打，就是这一关要拦的漂移）。
    import player                                            # noqa: PLC0415
    print("PART 10b 尾判滑键：独立的那个数框 -> defaults['tail_flick_lead']")
    dflt = core.TAIL_FLICK_LEAD_DEFAULT
    check("出厂值只有一处来源：core 那份与 player.TAIL_FLICK_LEAD_MS 相同",
          abs(dflt - player.TAIL_FLICK_LEAD_MS) < 1e-9, f"{dflt} vs {player.TAIL_FLICK_LEAD_MS}")
    check("没写这一项时读出来就是出厂值",
          core.RunOrchestrator({"defaults": {}}).tail_flick_lead() == dflt)
    check("写 0 读出来就是 0（0 = 关掉这段提前量，不是「没设」）",
          core.RunOrchestrator({"defaults": {"tail_flick_lead": 0}}).tail_flick_lead() == 0.0)
    check("读不出的值回落出厂值（abc 不会变成异常）",
          core.RunOrchestrator({"defaults": {"tail_flick_lead": "abc"}}).tail_flick_lead() == dflt)
    check("它不参与 --kind-lead 的实参（那一格不是第五个种类）",
          core.kind_lead_arg(zeros) == "" and
          core.kind_lead_text(zeros) == "全零", repr(core.kind_lead_arg(zeros)))
    check("日志表头：出厂值那一档不占地方，改了才写一行",
          core.tail_lead_text(dflt) == "" and core.tail_lead_text(None) == ""
          and core.tail_lead_text(0.0).strip() == "尾判滑键 0 ms"
          and core.tail_lead_text(25.0).strip() == "尾判滑键 25 ms",
          repr((core.tail_lead_text(dflt), core.tail_lead_text(0.0),
                core.tail_lead_text(25.0))))

    # 带牙：把四个键都写进实参（含 0）—— 全零时也会追加一条 `--kind-lead 0,0,0,0`，
    # 「全零时一个字节都不多发」当场变假。
    def old_arg(table):
        return ",".join(f"{k}={float(v):g}" for k, v in (table or {}).items())

    tooth = old_arg(zeros)
    check("带牙：四个键全写进实参的话，全零时也会多出一条 --kind-lead",
          tooth == "tap=0,long=0,flick=0,trace=0" and tooth != "", f"tooth={tooth!r}")
    return True


def part11(core):
    r"""「这一局」诊断卡（`panel_core.round_diag`）：把一局的 `.out` 压成几行读数。

    它是一条**读日志的出口**，风险全在「读错了还看不出」：行换了写法、取成第一条而不是最后
    一条、把告警丢了 —— 卡片照样显示，只是显示的是别的东西，而没有任何东西会红。这一关用一
    份合成日志把三条约定钉住：

      1. **取最后一条** `fire`（收尾那条遥测才算数）；
      2. 「投递」里的**最坏迟发取最大值**（不是第一条、也不是最后一行）；
      3. 锚定那一行只写在 `detail.log` 里 —— 要能跨文件取到，取不到也不能炸。

    另外两条边界：没选中（空 tag）、日志已被落盘预算清掉（文件不存在）都必须是 `ok=False`
    + 一句人话，**不许抛异常**（老记录本来就可能没有日志）。夹具建在系统临时目录里、建完就删，
    不碰真实语料，也只读不写真实路径。
    """
    print("PART 11 诊断卡：合成日志 -> 几行读数")
    tmp = tempfile.mkdtemp(prefix="hyoushi_diag_")
    keep = core.rlog.RUNS
    core.rlog.RUNS = tmp
    try:
        log = "\n".join([
            "10:00:00 谱面 0056_03 これはぼくたちの生存のあらすじ EXPERT Lv27.0，共 843 音符",
            "10:00:00 链路校准：文件里 -10 ms（2026-10-11 02:52:12）→ 有效偏移 +45 ms（名义 +55）",
            "10:00:01 开打：t0=131064.013，偏移 +45 ms",
            "10:00:05 实时修正 -6 ms（7 票 / 19 blob）",
            "10:00:09 实时修正：本局共 3 次，末值 -45 ms",
            "10:00:10 fire 400/3157 @chart +10.4s  late p50  +0.0 max   +1.0 ms  stalls 1",
            "10:00:20 本局事件表：技能 5 处（4.9/14.8 s）、fever 3 段",
            "10:00:21 !! 迟发 +1.2 ms @action 315 chart +8.9s  gc (10150, 0, 0)",
            "10:00:22 hud: GOOD at host [131089.303, 131089.313] 被zero闸门弃掉 -> x.png",
            "10:00:30 !! 迟发 +9.2 ms @action 600 chart +18.9s  gc (10150, 0, 0)",
            "10:00:40 fire 3157/3157 @chart +101.1s  late p50  +0.0 max   +0.4 ms  stalls 0",
            "10:00:41 ALL PERFECT，判定 843/843，combo 843，score 5883017，"
            "GREAT 0 GOOD 0 BAD 0 MISS 0",
        ]) + "\n"
        with open(os.path.join(tmp, "gd999.out"), "w", encoding="utf-8") as f:
            f.write(log)
        with open(os.path.join(tmp, "gd999.detail.log"), "w", encoding="utf-8") as f:
            f.write("fire t0=131064.013 (offset +45 ms)\n"
                    "live locked at chart +1.857s from 23 blobs, -0.499s after note 1\n")

        rec = {"perfect": 840, "great": 3, "good": 0, "bad": 0, "miss": 0}
        d = core.round_diag("gd999", rec)
        rows = dict(d["rows"])
        check("合成日志读得出来（ok=True、tag 带回来）",
              d["ok"] and d["tag"] == "gd999", str(d.get("why")))
        check("谱面/结果/链路/开打/锚定/修正/投递/事件/判定/告警/文件 都在",
              set(rows) >= {"谱面", "结果", "链路", "开打", "锚定", "修正", "投递", "事件",
                            "判定", "告警", "文件"}, ",".join(rows))
        check("谱面行里那串就是日志的第一行",
              rows.get("谱面", "").startswith("0056_03 ") and "843 音符" in rows.get("谱面", ""),
              rows.get("谱面", ""))
        check("投递取的是**最后**一条 fire（3157/3157，不是 400/3157）",
              rows.get("投递", "").startswith("fire 3157/3157"), rows.get("投递", ""))
        check("修正取的是「本局共」那句（末值 -45 ms），不是中间那次 -6 ms",
              "本局共 3 次" in rows.get("修正", "") and "-45" in rows.get("修正", ""),
              rows.get("修正", ""))
        check("锚定从 detail.log 里跨文件取到了",
              "locked at chart +1.857s" in rows.get("锚定", ""), rows.get("锚定", ""))
        check("告警里的迟发**取最大的那条**（+9.2，不是 +1.2）",
              "迟发 2 条" in rows.get("告警", "") and "+9.2" in rows.get("告警", ""),
              rows.get("告警", ""))
        check("告警里点出被 zero 闸门弃掉的次数",
              "1 次" in rows.get("告警", ""), rows.get("告警", ""))
        check("判定分布按 rec 算百分比（840/843 = 99.64%）",
              "99.64%" in rows.get("判定", "") and "共 843 个判定" in rows.get("判定", ""),
              rows.get("判定", ""))
        check("文件那一行给的是真路径",
              rows.get("文件", "").endswith("gd999.out"), rows.get("文件", ""))

        empty = core.round_diag("")
        check("没选中任何一局：ok=False，不炸", not empty["ok"] and bool(empty["why"]),
              repr(empty["why"]))
        gone = core.round_diag("gd998")
        check("日志已被清掉：ok=False，why 里点出文件名",
              not gone["ok"] and "gd998" in gone["why"], repr(gone["why"]))

        # 牙：下面这两条要是被改成「随便取一条」，上面那两条判据就必须会红
        with open(os.path.join(tmp, "gd998.out"), "w", encoding="utf-8") as f:
            f.write("10:00:00 !! 迟发 +1.2 ms @action 1\n")
        tooth = dict(core.round_diag("gd998")["rows"])
        check("牙 只有一条迟发时，告警里就是它自己（证明最大值是算出来的）",
              "迟发 1 条" in tooth.get("告警", ""), str(tooth))
        with open(os.path.join(tmp, "gd998.out"), "w", encoding="utf-8") as f:
            f.write("x\n")
        bare = core.round_diag("gd998")
        check("牙 一条能认的行都没有时仍返回 ok=True（空卡也不算异常）",
              bare["ok"] and len(bare["rows"]) <= 3, str(bare["rows"]))
    finally:
        core.rlog.RUNS = keep
        shutil.rmtree(tmp, ignore_errors=True)
    return True


def main():
    import panel_core as core

    manifest = core.read_json(core.MANIFEST, {})
    part1(core)
    part2(core)
    _ok, band_rank, ap = part4(core, manifest)
    part3(core, manifest, band_rank, ap)
    part5(core, manifest, band_rank, ap)
    part6(core)
    part7(core)
    part8(core)
    part9(core)
    part10(core)
    part11(core)

    print()
    if FAILS:
        print(f"PART 探针 FAIL：{len(FAILS)} 项")
        for f in FAILS:
            print("  -", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    import time
    t0 = time.time()
    rc = main()
    print(f"（{time.time() - t0:.1f}s）")
    sys.exit(rc)
