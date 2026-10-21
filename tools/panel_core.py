"""面板的业务层：不 import 任何 GUI 框架（tkinter / PySide6 / flet 都不）。

这个模块的存在理由只有一个 —— **换掉界面框架时，不该把业务逻辑也重写一遍**。
`tools/flet_gui.py`（唯一的视图层）从这里取走全部事实：

    * 配置：state 文件的读/写、运行策略、排序与筛选口径、表格列定义、配色 token；
    * 数据：谱面库、歌曲筛选/排序、结算记录、已 AP 的谱面编号；
    * 管道：`RunOrchestrator` —— 起 `run.py`、解析它的标准输出、发事件；
    * 工具：tag 取号、垃圾文件盘点。

视图唯一允许自己决定的东西是「怎么画」和「用户点了什么」。任何在这里写下的判断，
换界面时不会跟着变；这也是为什么 AGENTS.md 的红线（不许点奖励列表、不许花货币…）
在这条链路上只有一份实现 —— 它们全在 `run.py` / `detect.py` 里，面板只是发命令。

事件的形状（`RunOrchestrator` 往队列里放的就是这些，视图负责翻译成自己的画法）：

    ("log", text) ("log_err"|"log_ok"|"log_hdr"|"log_dim", text)
    ("phase", str) ("progress", float)
    ("result", {"record": dict, "tag": str})
    ("upstream", payload) ("charts_done", rc) ("done", None)
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import rlog  # noqa: E402

# pythonw 启动的面板没有控制台；不挂这个标志，面板发出的每一次 adb 调用都会弹一个黑框。
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

import locate  # noqa: E402  -- 路径集中探测与启动校验（见 tools/locate.py）
from locate import ADB, DEVICE  # noqa: E402
import watchdog  # noqa: E402  -- 夜间看门狗：卡死判定与救场（见 tools/watchdog.py）
OFFSET = 55.0
# 面板出厂时的两个策略数字：run.py 的 --live-push-cap 默认值，与 --retry-on-break 的每轮上限。
# 设置页可以改，改完记进 gui_state.json，所以这两个是首跑值而不是定律。PUSH_OFF_MS 是
# "不限制"在一个只收数字的字段里的诚实写法。
PUSH_ON_MS, PUSH_OFF_MS, RETRY_CAP = 10.0, 120.0, 3
# 多人局（`run.py --multi`）的正推上限**恒为 0**，面板不给这一条开关：房间抽到哪首只在
# 準備 页上认出来，开局没有「我选的那首的第一个音符」可以依赖，而 `--live-push-cap 0` 正是
# 2026-10-08 那两局 ALL PERFECT（mp9/mp10）用的配方（见 AGENTS.md 的多人段）。
MULTI_PUSH_CAP_MS = 0.0
# **种类偏移**：每类键的偏移量（ms，正数 = 更早），出厂值全是 0 —— 每个被钉住的成绩都是这套
# 参数打出来的。2026-10-05 起面板不能改它，2026-10-10 用户 m15057 把四个框放回设置页；
# 同一天用户 m15291 把它改名「分类偏移」，2026-10-21 用户 m53176 再改成「种类偏移」
# （旧名与选曲页那个「分类」下拉撞名；`--kind-lead` 这个参数名与状态键一个字没改）。
# 表还是同一张：player.KIND_LEAD_MS 是同一份，probes/pushcap.py 会因为两边漂移而失败。
KIND_LEAD_MS = {"tap": 0.0, "long": 0.0, "flick": 0.0, "trace": 0.0}

# **尾判滑键**：长条末尾那一记滑键比尾巴自己的毫秒早多少（ms）。与上面那张表**不同**：
# 它不是一类键，而是一种手势位置 —— 「长条尾巴上挂着 flick」这一种（`player.build_actions`
# 的 `end_flick` 分支），与「长条 long」那一格叠加。默认值与 `player.TAIL_FLICK_LEAD_MS`
# 同一份（探针 `probes/panelfly.py` 会因为两边漂移而失败）。
# 存的是**绝对值**而不是与出厂值的差：状态文件里读到 10 就是「早 10 ms」，读到 0 就是关掉。
TAIL_FLICK_LEAD_DEFAULT = 10.0


def kind_lead_text(kind_lead):
    """`{"tap": -30.0, …}` -> `"tap-30"`：只列非零的，按 `KIND_LEAD_MS` 的顺序。

    日志表头与 `--kind-lead` 的实参共用这一份写法 —— 表头说的与真发出去的必须是同一串
    （`push_ms` 那个键名 bug 就是「说的」与「发的」分家）。
    """
    return " ".join(f"{k}{float(v):+g}" for k, v in (kind_lead or {}).items()
                    if float(v or 0.0)) or "全零"


def kind_lead_arg(kind_lead):
    """`{"tap": -30.0, …}` -> `"tap=-30"`（`run.py --kind-lead` 的写法，只列非零的）。

    全零时返回空串：那时命令行与从前**逐字相同**，探针里比对 argv 的判据不受影响。
    """
    return ",".join(f"{k}={float(v):g}" for k, v in (kind_lead or {}).items()
                    if float(v or 0.0))


def tail_lead_text(tail_lead):
    """`10.0` / `None` -> `""`，`0.0` -> `" 尾判滑键 0 ms"`：只在与出厂值不同时才进表头。

    与 `kind_lead_text` 同一个理由 —— 表头说的必须与真发出去的是同一串。出厂值那一档
    命令行里根本没有 `--tail-flick-lead`，表头也就不该多出一个「默认值」来占地方。
    """
    if tail_lead is None:
        return ""
    try:
        v = float(tail_lead)
    except (TypeError, ValueError):
        return ""
    if abs(v - TAIL_FLICK_LEAD_DEFAULT) < 1e-9:
        return ""
    return f" 尾判滑键 {v:g} ms"

MANIFEST = rlog.MANIFEST
VALIDATED = rlog.VALIDATED
UPSTREAM_REPORT = os.path.join(rlog.RESEARCH, "reports", "upstream_check.json")
# 「强制重下」的确认框排在**比对之后**（原 Tk 版 `_after_check()` 就是这个顺序）：core 比对完
# 把目录现状交给面板，然后停在这里等那一按。超时只是防御（面板被关掉、用户一直不理），
# 「本轮停止」与「强制终止」都会立刻解除等待。
DECIDE_WAIT = 600.0
# `fetch_charts.py` 逐首打的进度行头（`[12/87] …`）；按它推进度条。
PROGRESS_RE = re.compile(r"^\[(\d+)\s*/\s*(\d+)\]")
RESULTS = rlog.RESULTS
# 状态文件的位置可以重定向。**只为一个用途**：让面板能在没有模拟器、也不许碰用户实时状态
# 的情况下被真跑一遍（冒烟截图、探针）。生产路径永远是 research/gui_state.json。
STATE = os.environ.get("OURNOTES_STATE") or os.path.join(rlog.RESEARCH, "gui_state.json")
# 一轮的 `<tag>.out` 写在哪。**生产路径是 research/runs/** —— 和 `<tag>.detail.log`、`dets_*.json`
# 同一个桶（2026-10-20 之前写的是 research/ 根，那 2029 个旧 `*.out` 就是那么攒出来的，那次
# 一并搬进 runs/）。**唯一的重定向用途**：让「起进程 → 读标准输出 → 收结果」这条链路能在不往
# 用户语料里丢文件的前提下被真跑一遍（见 tools/probes/panelfly.py）。
RUN_OUT_DIR = rlog.RUNS
# `_save_state` 的串行化：run worker 与 UI 线程都会重写这个文件，而它们 dump 的是同一个 dict。
# 只在写的那几毫秒持锁 —— 代价是一点 JSON，换来的是不会出现半截文件（读者拿到 {} 会把
# next_index 悄悄重置成 1，然后覆盖已经在盘上有证据的编号）。
STATE_LOCK = threading.Lock()
# `next_tag` 在计数器被清零时会向上扫多远。语料是 230 多局、编号形如 g%03d，真实空隙只有几十宽；
# 这个上界是为了**终止**，而不是为了找得远。
TAG_SCAN_END = 10000
# 一局的产物散落在 research/ 下；2026-09 重组之前的局在 research/archive/runs/。两处都要找。
RUN_DIRS = (rlog.RESULT, rlog.RUNS, rlog.RESEARCH, os.path.join(rlog.RESEARCH, "archive", "runs"))

SORT_DEFAULT = "乐队优先"
SORT_MODES = (SORT_DEFAULT, "罗马音序", "难度升序", "未AP优先")

# 「清理垃圾」只认这几类；谱面库、结算记录、面板状态、标定文件从不入列 ——
# 判据是一个问题：面板还打不打得开它。文件名里的编号掉出 results.jsonl 的滚动窗（最近 100 局）
# 之后点不到、排不了、审计也不读，那些帧和机器数据就是死重。文字日志例外 —— 三百多个才 2 MB，
# 而 tools/backfill_log.py 靠 <tag>.out 把漏写的记录补回来，删它等于把补档能力一起删掉。
# `-a{k}` 后缀必须留在**捕获组外**：它标的是「这是第 k 次重开的取证」，编号仍旧是同一个 tag。
# 2026-10-07 实测：后缀在组里时 `dets_g417-a1.json` 的 group(1) 变成 `g417-a1`，而窗口表里只有
# `g417` ⇒ 每一份 parked 取证都被判成「窗外」，被面板的每轮自动清理当场删掉。证据：results_full.jsonl
# 里 25 局 aborts>0、runs/*.detail.log 里 66 行「本轮中止的取证已改名」，而 research/ 全树 4666 个文件
# 里一个 `-a1` 都不剩（只有 evidence/hud/box/ 下 27 个躲过扫描）。tools/run.py:_park_attempt 本身是对的
# （用真函数造文件实测五个都改名成功）—— 删它们的是这里。
JUNK_TAGGED_RE = re.compile(
    r"^(?:hud|hudreject|result|split|failed|dets|relock_dets|relock)_"
    r"([a-z]+\d+)(?:-a\d+)?[_.]")
# 落到这一条的是**没有**合法编号的调试截图。`hud_`/`hudreject_` 2026-10-08 补进来：HUD 看盘那次
# 的 1116 张、971 MB 里有一批名字带不上合法编号（`hud_now_*` 之类），于是两条正则都不认，
# 在 research/frames 里躺了两天。带合法编号的 `hud_<tag>_` 走上面那条（窗内留、窗外删），
# 不会因为这里多两个前缀而改变归属。已提交的那半在 evidence/hud/，由 JUNK_PROTECTED_REL 挡住。
JUNK_DEBUG_RE = re.compile(
    r"^(?:hud_|hudreject_|now_|chang_|tmp_|calib_|judge_|hostcap|mumucap_|nav_stuck_|_)"
    r".*\.(?:png|json|pid)$")
JUNK_PROTECTED_REL = ("research/charts/", "research/refsrc")
JUNK_PROTECTED_NAME = ("results.jsonl", "gui_state.json", "chain_cal.json",
                       "digit_templates.json")

# run.py 的摘要走 rlog，噪声不会出现在那里；这三行是 mumucap 的原生库直接写到进程标准输出的，
# 只能在面板这一侧拦。
NATIVE_NOISE = re.compile(r"^(?:product|nemu_connect|connect not same day)")

APPEARANCE_CHOICES = ("跟随系统", "浅色", "深色")
APPEARANCE_KEYS = ("auto", "light", "dark")     # gui_state.json 存的就是这个次序

# 上游两个目录源（`tools/check_upstream.py --source=`）。两边分工不同，不是一个备份另一个：
# MoeNotes 的 master 表回答「要不要看」，Haneoka 的目录回答「库里该有什么」—— 只有后者手里
# 有能编译的字节，所以逐张核对字节时无论如何都要问它。首选只决定先问谁。
SOURCE_KEYS = ("moenotes", "haneoka")
SOURCE_CHOICES = ("MoeNotes", "Haneoka")


def preferred_source(state, fallback="moenotes"):
    """首选目录。`gui_state.json` 里的值不是这两个键之一（或根本没这个键）就回退。

    读的时候一律兜底：Tk 时代就写在这个键上，值域变过，而一个坏值不该让面板起不来。
    """
    key = (state or {}).get("preferred_source")
    return key if key in SOURCE_KEYS else fallback

CHIP_W = 8
DIFF_LETTER = {"EASY": "e", "NORMAL": "n", "HARD": "h", "EXPERT": "x"}
DIFF_RANK = {"EASY": 0, "NORMAL": 1, "HARD": 2, "EXPERT": 3}

HIST_FILTERS = (("all", "全部"), ("ap", "AP"), ("fc", "FC"), ("np", "漏键"), ("err", "异常"))
HIST_FILTER_TIPS = {
    "all": "显示全部结算记录。",
    "ap": "只看 ALL PERFECT：漏键数为 0 的局。",
    "fc": "只看全连而未 ALL PERFECT：有 GREAT、没有 BAD／MISS 的局。",
    "np": "只看有漏键的局：漏键数大于 0。",
    "err": "只看异常的局：演奏被中断，或结算页没有读到。",
}
# 结算记录的**来源**筛选（2026-10-10 用户 m13266「记录界面加个单人多人的筛选」）：两枚可同时
# 点亮的 chip（filter chip 的官方用法就是多选细化），两个都亮 = 两半都列。判据只看
# `hist_mode()` 那个戳，所以这里三个词与单人页／多人页那两张「最近演出」卡用的是同一口径。
HIST_SOURCES = (("solo", "单人"), ("multi", "多人"))
HIST_SOURCE_TIPS = {
    "solo": "列单人演出的局（与「多人」可以同时点亮；两个都不点亮就什么都不列）。",
    "multi": "列多人（激奏演出）的局（与「单人」可以同时点亮）。",
}
# 列宽实测于本机 9pt 雅黑：每列给 max(表头, 最宽数据) + 8 px 单元格留白，剩下的全给歌曲列 ——
# 它是唯一「越长越好」的列。
HIST_COLS = ("time", "song", "diff", "badge", "reopen", "np", "P", "G", "GD", "B", "M",
             "combo", "score")
HIST_HEADS = {"time": ("时间", 70, "center"), "song": ("歌曲", 170, "w"),
              "diff": ("难度", 48, "center"), "badge": ("判定", 41, "center"),
              "np": ("漏键", 38, "e"), "P": ("PERFECT", 60, "e"), "G": ("GREAT", 48, "e"),
              "GD": ("GOOD", 46, "e"), "B": ("BAD", 38, "e"), "M": ("MISS", 40, "e"),
              "combo": ("连击", 38, "e"), "score": ("分数", 70, "e"),
              "reopen": ("重开", 34, "e")}
# 第 0 列是结果竖条，没有表头也没有文字，所以数据列整体右移一格。
HIST_TITLES = [" "] + [HIST_HEADS[c][0] for c in HIST_COLS]
HIST_WIDTHS = [CHIP_W] + [HIST_HEADS[c][1] for c in HIST_COLS]
HIST_RIGHT = [i + 1 for i, c in enumerate(HIST_COLS) if HIST_HEADS[c][2] == "e"]
HIST_CENTER = [i + 1 for i, c in enumerate(HIST_COLS) if HIST_HEADS[c][2] == "center"]
# 结算表的**显示条数**：Flet 的 `DataTable` 每个格子都是一个控件，几百行时客户端会明显卡
# （用户原话：「记录列表做成可设置显示数，一下展示三百条太卡了」）。所以表上只画前 N 行，
# N 存在 `gui_state.json` 的 `hist_limit` 里，0 = 全部、缺键/写坏都退回默认 50。
# **上限只影响画多少行**：筛选（chips 上的计数）、「导出 CSV」与页脚统计都仍按全部记录算 ——
# 导出的那条路读的是 `HistModel.tags`（全量筛出行），跟这个上限没关系。
# 档位 2026-10-10（用户 m13481「记录默认显示条数改为50，并同步调整数量的档位细化，目前已有
# 超500条记录」）：账本 552 行 ⇒ 小档补 25（小窗口/只想扫一眼）、大档补 300/500（接近语料规模），
# 中间仍是倍档。默认从 100 降到 50：一屏看得完、翻页也不至于太碎。
HIST_LIMITS = (25, 50, 100, 200, 300, 500, 0)      # 下拉里的预设档位，末档 0 = 全部
HIST_LIMIT_DEFAULT = 50
HIST_LIMIT_MAX = 1000
HIST_LIMIT_KEY = "hist_limit"


def hist_limit_label(n):
    """"全部" / "100 条" —— 0 单独说成「全部」，别让人看见「0 条」。"""
    return "全部" if not n else f"{n} 条"


def clamp_hist_limit(raw):
    """读状态文件里的 `hist_limit`：手改成的字面量认不出来就回默认，**绝不抛**。

    与 `clamp_num` 同一套口径：合法范围内原样保留（手写的 300 也认，下拉会把当前值补进去），
    只把「负数 / 非数字 / 离谱大」挡回去。
    """
    try:
        n = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return HIST_LIMIT_DEFAULT
    if n < 0:
        return HIST_LIMIT_DEFAULT
    return min(n, HIST_LIMIT_MAX)


def hist_limit(state):
    return clamp_hist_limit((state or {}).get(HIST_LIMIT_KEY, HIST_LIMIT_DEFAULT))


NUM_COL = {"P": "perfect", "G": "great", "GD": "good", "B": "bad", "M": "miss",
           "np": "non_perfect", "combo": "combo", "score": "score", "reopen": "aborts"}

#: 数字列「这一格没有读数」印什么（2026-10-09 用户 m11451 要求不留空，m11595 要求与真数分明）。
#: 破折号而不是 `0`：`0` 是一个**读数**（真的是零），破折号才读得成「没量到」。全项目只有这一处。
HIST_BLANK = "—"

LOG_FILTERS = (("all", "全部"), ("err", "错误"), ("run", "本轮"))
LOG_FILTER_TIPS = {
    "all": "显示全部日志行。颜色就是分级，一眼要看的只有红和绿：\n"
           "红：要行动的 —— 断键、断AP 重开、面板内部错误。\n"
           "绿：结论 —— ALL PERFECT、重锁成功、注入完成、HUD 与结果页对平。\n"
           "蓝：一轮的抬头 —— 随机选曲、链路校准。\n"
           "白：过程里要知道的 —— 开打、谱面、进入 LIVE、曲终。\n"
           "灰：可以不看 —— 导航一站、HUD 每个候选、发射心跳、指向文件的一行、"
           "以及任何不带中文的第三方原文。",
    "err": "只看标红的行：断键、出生即废、面板内部错误 —— 演奏器自己标 !! 的那些。",
    "run": "只看本轮开始后的行：上一次点「开始」之后的日志。",
}
# 存储留最近 LOG_KEEP 行，这样一局打到一半改筛选还能看到东西；视图只是当前筛选的滚动窗口。
LOG_KEEP, LOG_WINDOW = 4000, 2000

# 演出间隔从「游戏回到乐曲选择页」那一刻起算（run.py 走到选曲页时发一条 #ATSELECT#），
# 所以设 5 分就是 5 分后开下一局，收尾那几秒不再额外往上加。0 = 不等待。
GAP_FLOOR_S = 2.0
GAP_MAX_MIN = 120

# 连续演出的轮数上限。**这是 AGENTS.md 里那个数**（「连续演出上限 100 轮，≈13 小时，够一夜
# 无人值守」），面板的输入框按它设范围 —— 写在这里而不是界面里，是为了让探针能把两处对起来：
# 曾经界面写 50、文档写 100，两边都不报错，只是用户按文档设 80 会被静默夹到 50。
RUNS_MAX = 100

# 加成火力门的门槛：开打前读一次火力，≥ FIRE_MIN 就把 消耗LB 拨 3 档、不足就拨 0 档，然后照常
# 开打 —— 不再停在乐队确认页等它回复（用户 m13786 立项「打一次歌最多会消耗3点以获得额外道具
# 奖励」，2026-10-11 用户 m26442 把「等够」改成「拨档」）。**两个出处必须一起改**：这里是面板与
# CLI 共用的那个数（`_spawn_run` 把它交给 `run.py --min-fire`），游戏侧的读数与拨档逻辑在
# `tools/calib.py`（`fire_power` / `set_live_boost` / `start_live(min_fire=…)`），那里不认识这个
# 常数、只认传进去的值。
FIRE_MIN = 3

# 日志分级。一局会出几百行，只有少数是「看一眼就要行动」的，所以颜色给结论、弱化给过程：
# 严重度靠演奏器自己的 `!!` 标记，其余按行首形状判。措辞是 rlog 的 RENDER 表定的，
# 面板与演奏器共用一份说法，所以认形状就够。
LOG_LEVELS = (
    ("log_hdr", re.compile(r"^(随机选曲：|链路校准：)")),
    ("log_ok", re.compile(r"^(ALL PERFECT|锚定：重锁成功|注入完成 \d+/\d+（通道断连 0 次）"
                          r"|HUD 计数器（总数仍以结果页为准）：GREAT 0 GOOD 0 BAD 0 MISS 0)")),
    ("log_dim", re.compile(r"^(导航：|HUD 计数器变化|调度误差：|\s*(fire|hud|screen|random roll)\b)"
                           r"|结果已写入|取证已改名|(→|->) [A-Za-z]:[\\/]")),
    # 纯 ASCII 的一律是 adb / minitouch / 校准器的原文，不是面板写的话。
    ("log_dim", re.compile(r"^[^一-鿿]*$")),
)
# 演奏器给每一行盖时间戳；戳吃一个空格，行自己的缩进留在后面，所以判形状前先剥掉这 10 个字符。
LOG_TS = re.compile(r"^\d\d:\d\d:\d\d ")


def gap_wait(gap_min, since_anchor):
    """轮间该坐多久（秒），given 距离回到选曲页已经过了 `since_anchor` 秒。

    两个边界都要能不问显示器直接测：不短于收尾那一拍，也不超过间隔本身 ——
    锚点比间隔还旧就立刻开下一局，而不是再等一整个间隔。
    """
    if gap_min <= 0:
        return GAP_FLOOR_S
    return max(GAP_FLOOR_S, gap_min * 60.0 - since_anchor)


# ---------------- 小工具（两种视图共用，语义只能有一份） ----------------

def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                             # noqa: BLE001
        return default if default is not None else {}


def read_json_str(s):
    try:
        return json.loads(s)
    except Exception:                                             # noqa: BLE001
        return None


def listdir(d):
    try:
        return os.listdir(d)
    except OSError:
        return []


def path_size(p):
    try:
        if os.path.isdir(p):
            return sum(os.path.getsize(os.path.join(b, f))
                       for b, _d, fs in os.walk(p) for f in fs)
        return os.path.getsize(p)
    except OSError:
        return 0


def fmt_size(n):
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{n / 1024:.0f} KB"


def chart_id(d):
    """'research/charts/0056_03.hits.json' -> '0056_03'，与结果记录、钉子同一套编号。"""
    return os.path.basename(str(d.get("hits") or "")).split(".")[0]


def lv(d):
    """难度数字，按游戏写的那个显示。

    归档的 `displayLevel` 被抹成整数，而它的 `sortLevel` 留着游戏里显示的半步 ——
    唱 EXPERT 在那边是 Lv23.5、这里是 Lv23。只有显示与排序读它；`level` 仍是审计与钉子看的值，
    所以一个在字段出现之前写的 manifest 只会显示它一直在显示的那个整数。
    """
    s = d.get("sortLevel")
    if isinstance(s, (int, float)) and s:
        return f"{s:g}"
    return str(d.get("level") or d.get("displayLevel") or "?")


def logged_tags(path):
    """`results*.jsonl` 里有行的每一个 tag。坏行跳过而不是抛出：这是一次撞号检查，
    一行损坏的记录不能让面板连一个安全编号都取不出来。"""
    out = set()
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                try:
                    t = json.loads(ln).get("tag")
                except (ValueError, TypeError):
                    continue
                if t:
                    out.add(t)
    except OSError:
        pass
    return out


def tag_taken(tag):
    """这一轮是不是已经有主了？叫 `_taken` 而不是 `_unused`，因为在这里证明一个编号是自由的
    是不可能的：它自由当且仅当盘上没有任何东西记得它，而这个函数的职责是**拒绝**那些记得的。

    问两个问题，因为产物的文件名形状不统一。**记过账**是指 `results*.jsonl` 里有它的行 ——
    那才是记录，history 覆盖每一轮写过的。**有实物**是指工作目录里有以它命名的文件：
    `hud_<tag>_`、`hudreject_<tag>_`、`result_<tag>.png`、`failed_<tag>.png`、
    `dets_<tag>.json` 以及 `<tag>.out`/`<tag>.detail.log` 都把它当一个完整 token 带着，
    下面两个测试找的就是这个。早期版本只认 `_<tag>_`，所以径直走过了 `dets_g005.json`
    和 `failed_g005.png`。
    """
    if tag in logged_tags(rlog.RESULTS) or tag in logged_tags(rlog.HISTORY_FULL):
        return True
    try:
        for e in os.scandir(rlog.RUNS):
            if e.name.startswith(tag + "."):
                return True
    except OSError:
        pass
    for d in (rlog.RUNS, rlog.FRAMES, rlog.RESULT):
        try:
            for e in os.scandir(d):
                if f"_{tag}_" in e.name or f"_{tag}." in e.name or f"_{tag}-" in e.name:
                    return True
        except OSError:
            pass
    return False


def next_tag(state):
    """一个没有任何一轮用过的编号，取到之后立刻持久化。

    只读 `next_index` 再相信它是不够的：它住在一个可能丢的文件里，而 run.py 自己的闸门只扫
    `results.jsonl` —— 滚动 100 行，而记录有 230 多轮，每一轮还在盘上留一套
    `dets_/relock_/hud_/result_`。一个已经滚出那个窗口的编号会被 run.py 接受，然后
    **覆盖掉更早一轮的取证**，这就是那次「重复铸号」事故。所以计数器只是一个起点提示，
    答案是盘上的证据还没占用的那一个。

    两种形状，因为计数器会朝两个方向错。通常它跑在一切前面（每轮结束时推进过），下面的分支
    一次都不跑。它要是被清零了 —— 丢一次 gui_state.json 就是这种情况 —— 序列会从 g001 重新
    开始，撞进一个已经占满的区间，这时有用的搜索是**从 1 向上**：空隙最宽也就是飞过的轮数，
    所以扫描由 `TAG_SCAN_END` 限界，而不是由一百万限界。有界在这里是硬要求：
    在占满的区间上写一个无界的 `while` 永不终止，而这段代码跑在 UI 线程上。

    **顺序是 2026-10-07 改的：先往上续号，再从 1 兜底。** 起因是一次实测 —— 计数器停在 452
    而 g452…g460 已被手写命令行用掉，旧写法直接跳到「从 1 向上」，返回 **g001**：低段并**不是**
    占满的，`results_full.jsonl` 只从 g142 起（更早的轮次记在别的格式里），它们的取证也早已不在
    盘上，所以 g001/g002 在这套判定下是「自由」的，面板会从这里一路发 g001、g002、g003…，
    而正确的下一个号是 g461。`tools/probes/paneldata.py` PART 7 钉着这个顺序。
    """
    idx = int(state.get("next_index", 1))
    if tag_taken(f"g{idx:03d}"):
        nxt = next((n for n in range(idx + 1, TAG_SCAN_END) if not tag_taken(f"g{n:03d}")),
                   None)
        if nxt is None:                     # 往上一直占满（计数器被清零撞进满区间）才从 1 兜底
            nxt = next((n for n in range(1, TAG_SCAN_END) if not tag_taken(f"g{n:03d}")),
                       TAG_SCAN_END)
        idx = nxt
    state["next_index"] = idx + 1
    save_state(state)
    return f"g{idx:03d}"


def save_state(state):
    with STATE_LOCK:
        try:
            rlog.write_json(STATE, state)
        except Exception:                                         # noqa: BLE001
            pass


def junk_protected(p):
    rel = os.path.relpath(p, ROOT).replace("\\", "/")
    return rel.startswith(JUNK_PROTECTED_REL) or os.path.basename(rel) in JUNK_PROTECTED_NAME


def collect_junk(state=None):
    """每次点击都从头重扫。四类，每类 {key,label,files,size,on} —— `files` 只装面板任何功能
    都打不开的路径（见 JUNK_* 过滤；charts / results.jsonl / state / 标定文件是被结构排除的，
    不是被挑掉的）。

    重产物的判据是滚动窗，不是年龄：一个已经滑出 results.jsonl 的编号点不到，它的帧和机器数据
    就谁也不服务。文字日志按设计豁免 —— 见 JUNK_TAGGED_RE 上的说明。
    """
    tags = {r.get("tag") for r in rlog.read_records(RESULTS)}
    debug, stale = [], []
    for d in (rlog.FRAMES, rlog.RUNS, rlog.RESULT, rlog.RESEARCH):
        for n in listdir(d):
            p = os.path.join(d, n)
            if not os.path.isfile(p):
                continue
            m = JUNK_TAGGED_RE.match(n)
            if m:
                if m.group(1) not in tags:
                    stale.append(p)
            elif JUNK_DEBUG_RE.match(n):
                debug.append(p)
    media = []
    for d in (os.path.join(rlog.RESEARCH, "recordings"),
              os.path.join(rlog.RESEARCH, "archive", "media"),
              os.path.join(rlog.RESEARCH, "archive", "screens")):
        for base, _dirs, files in os.walk(d):
            media += [os.path.join(base, fn) for fn in files]
    # 2026-10-08：`--record-counters` 的实录（`research/runs/<tag>.counters.avi`，一局 82–87 MB）
    # 从前一条判据都不进 —— 名字是「编号在前」，JUNK_TAGGED_RE 的编号在后；扩展名也不是
    # JUNK_DEBUG_RE 认的 png/json/pid。于是项目里最大的单件产物在清理对话框里根本看不见。
    # 它进**录像媒体**这一类（默认不勾选）：删它是判断，但判断至少要看得见数字。
    for fn in listdir(rlog.RUNS):
        if os.path.splitext(fn)[1].lower() in (".avi", ".mp4"):
            media.append(os.path.join(rlog.RUNS, fn))
    caches = []
    for base, dirs, _files in os.walk(ROOT):
        # .git 不是缓存；.venv 是别人的包树 —— 它的 __pycache__ 是别人 20 MB 的构建产物，
        # 清掉只会让下一次 import 更慢。这一类说的是本仓库自己的代码。
        dirs[:] = [d for d in dirs if d not in (".git", ".venv")]
        if "__pycache__" in dirs:
            caches.append(os.path.join(base, "__pycache__"))
            dirs.remove("__pycache__")
    cats = [
        {"key": "debug", "on": True, "label": "调试截图", "files": debug,
         "tip": "标定、抓帧自检与临时文件。删除不影响任何成绩记录。"},
        {"key": "stale", "on": True, "label": "窗外取证", "files": stale,
         "tip": "文件名里的编号已经掉出结算记录的滚动窗（最近 100 局），面板打不开它。\n"
                "删除后不可恢复；文字日志 <编号>.out 不属于这一类，永远保留。"},
        {"key": "media", "on": False, "label": "录像媒体", "files": media,
         "tip": "录像与归档媒体。删除后不可恢复，默认不勾选。"},
        {"key": "pycache", "on": True, "label": "脚本缓存", "files": caches,
         "tip": "__pycache__ 目录。删除后 Python 会自动重建。"},
    ]
    for c in cats:
        c["files"] = [p for p in c["files"] if not junk_protected(p)]
        c["size"] = sum(path_size(p) for p in c["files"])
    return cats


def child_line(text):
    """演奏器 stdout 的一行 -> (事件种类, 文本)，种类决定颜色。

    `!!` 是演奏器的严重度标记：它决定颜色，然后被剥掉，所以到达日志的只有话。两件事曾经破坏过
    它。判据曾拿**原始行**去测，而原始行以时间戳开头，于是它从不触发，一个丢键就以普通墨水到达、
    还粘着一个字面的 `!!`；而且用的是 `startswith`，断键那些行本来就漏掉，因为它们是引发它的那
    一轮的缩进子行。两处现在都看得过去了。时间戳与缩进留在文本里 —— 前者说这是什么时候，
    后者说这一行属于谁。
    """
    msg = LOG_TS.sub("", text, count=1)
    body = msg.lstrip()
    if body.startswith("!!"):
        return ("log_err", text[:len(text) - len(body)] + body[2:].strip())
    for kind, pat in LOG_LEVELS:
        if pat.search(msg):
            return (kind, text)
    return ("log", text)


# ---------------- 结算记录：纯函数，视图只负责摆放 ----------------

def hist_num(rec, key):
    try:
        return int(rec.get(key))
    except (TypeError, ValueError):
        return None


DIAG_READ_MAX = 400_000


def _diag_body(line):
    """去掉行首的 `HH:MM:SS ` —— 日志每行都带时间戳，诊断卡不关心它。"""
    return line[9:] if len(line) > 9 and line[2] == ":" and line[5] == ":" else line


def round_diag(tag, rec=None):
    """一局的「诊断卡」：把 `<tag>.out`（外加 `<tag>.detail.log` 的一行）压成几行读数。

    为什么要它：结算表只答「这一局是什么结果」，不答「为什么」。要答后半句，现在只有一条
    路 —— 去运行日志页翻那一局的几百行。这里的几行是**同一批数字的摘要**，没有任何新测量：
    谱面 / 链路校准 / 开打 / 锚定 / 曲中修正 / 最后一次投递遥测 / 事件表 / 判定分布 / 告警。

    为什么在读日志的地方做：这些数的**唯一**来源就是那两行日志（`run.py` 与 `player.play` 打的），
    界面不该为了显示它们再存一份状态，否则两边一旦不同步，"面板说 +5 ms、日志说 -45 ms" 这种
    事就会发生（`#STATUS#` 那条通道对读数带用的也是同一个原则：发什么显示什么）。

    返回 `{"ok", "why", "tag", "path", "rows": [(标签, 值), …]}`；读不到文件就是 `ok=False`，
    不抛异常 —— 老记录（`retention` 清过的、`results_full` 里来自别处的）本来就可能没有日志。
    """
    tag = str(tag or "").strip()
    if not tag:
        return {"ok": False, "why": "还没有选中任何一局", "tag": "", "path": "", "rows": []}
    path = os.path.join(rlog.RUNS, tag + ".out")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(DIAG_READ_MAX)
    except OSError as exc:
        return {"ok": False, "tag": tag, "path": path, "rows": [],
                "why": f"读不到 {tag}.out（{exc.strerror or exc}）—— 可能已被落盘预算清掉"}

    head = cal = opened = corr = fire = events = result = ""
    late_n, late_worst, rejects, corr_n = 0, 0.0, 0, 0
    for raw in text.splitlines():
        t = _diag_body(raw).strip()
        if not t:
            continue
        if not head and t.startswith("谱面 "):
            head = t[3:]
        elif "链路校准：" in t:
            cal = t.split("链路校准：", 1)[1]
        elif t.startswith("开打："):
            opened = t[3:]
        elif "实时修正：本局共" in t:
            corr = t
        elif t.startswith("实时修正"):
            corr_n += 1
        elif t.startswith("fire "):
            fire = t                                    # 只留最后一次：它是收尾时的遥测
        elif "本局事件表：" in t:
            events = t.split("本局事件表：", 1)[1]
        elif "combo " in t and ("MISS" in t or "ALL PERFECT" in t):
            result = t
        m = re.search(r"迟发 \+([\d.]+) ms", t)
        if m:
            late_n += 1
            late_worst = max(late_worst, float(m.group(1)))
        if "被zero闸门弃掉" in t:
            rejects += 1

    rows = []
    if head:
        rows.append(("谱面", head))
    if result:
        rows.append(("结果", result))
    if not cal:
        rows.append(("链路", "日志里没有「链路校准」那一行（老版本或半路作废的一局）"))
    else:
        rows.append(("链路", cal))
    if opened:
        rows.append(("开打", opened))
    # 锚定只写在 `detail.log` 里（`.out` 是给人看的那一份，不含每帧读数）。
    anchor = ""
    try:
        with open(os.path.join(rlog.RUNS, tag + ".detail.log"), "r",
                  encoding="utf-8", errors="replace") as f:
            for raw in f:
                if "locked at chart" in raw:
                    anchor = raw.strip()
                    break
    except OSError:
        pass
    if anchor:
        rows.append(("锚定", anchor))
    rows.append(("修正", corr or (f"曲中修正 {corr_n} 次（末值没写进日志）" if corr_n
                               else "曲中修正：一次都没有（时钟一直没被推翻）")))
    if fire:
        rows.append(("投递", fire))
    if events:
        rows.append(("事件", events))
    if rec:
        cnt = {k: hist_num(rec, k) or 0 for k in ("perfect", "great", "good", "bad", "miss")}
        total = sum(cnt.values())
        if total:
            rows.append(("判定", f"P {cnt['perfect']}（{100.0 * cnt['perfect'] / total:.2f}%）"
                                 f"／G {cnt['great']}／GD {cnt['good']}／B {cnt['bad']}"
                                 f"／M {cnt['miss']}   共 {total} 个判定"))
    if late_n or rejects:
        bits = []
        if late_n:
            bits.append(f"迟发 {late_n} 条（最坏 +{late_worst:.1f} ms）")
        if rejects:
            bits.append(f"判定行被 zero 闸门弃掉 {rejects} 次")
        rows.append(("告警", "、".join(bits) + "　── 队列没排完时后面每个音都会晚"))
    rows.append(("文件", path))
    return {"ok": True, "why": "", "tag": tag, "path": path, "rows": rows}


def hist_badge(rec):
    """判定列那两个字/四个字。**「打完了、既没 AP 也没 FC」写「成功」，不写破折号**
    （2026-10-09 用户 m11846：「仅完成未FC与AP的记录状态标为成功，现在的破折号有歧义」）。

    破折号有歧义是因为数字列现在拿它当「这一格没有读数」的占位符（`HIST_BLANK`）——
    同一个 `—` 在判定列里读作「打完了但没 AP/FC」、在数字列里读作「没量到」，两件事。
    判定列本来就是**有字**的列（`AP` / `FC` / `成功` / `中断` / `读取失败`），不该去借占位符。
    """
    if rec.get("rc"):
        return "中断"
    if rec.get("all_perfect"):
        return "AP"
    if rec.get("full_combo"):
        return "FC"
    return "读取失败" if rec.get("error") or rec.get("non_perfect") is None else "成功"


def hist_kind(rec):
    """行首竖条说什么。异常 = 这一次尝试从没产出可用的判定数据：进程被中断，或结算页读不出来。"""
    npf = hist_num(rec, "non_perfect")
    if rec.get("rc") or npf is None:
        return "err"
    if rec.get("all_perfect"):
        return "ap"
    if rec.get("full_combo"):
        return "fc"
    return "np" if npf else "none"


def hist_kept_for(rec, f):
    if f == "all":
        return True
    if f == "ap":
        return bool(rec.get("all_perfect"))
    if f == "fc":
        return bool(rec.get("full_combo")) and not rec.get("all_perfect")
    if f == "err":
        return hist_kind(rec) == "err"
    return bool(hist_num(rec, "non_perfect"))


def hist_mode(rec):
    """这一局是单人还是多人 —— `"solo"` / `"multi"`。

    `multi` 是 `run.py` 在 `--multi` 下盖的戳（`fly_extra`，2026-10-08 用户 m04278 那次补的）；
    面板自己起的那一轮由 `record_round` 补上（半路作废、没有 RESULT 行的那些否则会没有戳）。
    没有戳的一律算单人：位置参数 `hits` 与 `--random` 都是单人局。
    """
    return "multi" if rec.get("multi") else "solo"


def hist_mode_ok(rec, mode):
    """这一条记录属不属于 `mode` 那一半（`None` / `"all"` = 两半都要）。

    2026-10-09 用户 m10950：单人页与多人页各挂一张「最近演出」，各只列自己那一半。
    """
    return mode in (None, "", "all") or hist_mode(rec) == mode


def hist_cells(rec):
    """表格的一行：先竖条列（永远没有文字），再数据列。

    数字列**一个空格子都不留**（2026-10-09 用户 m11451：「结算记录里数数别留空，无读数就用
    占位符，比如写个0之类的」）：没有读数就印 `HIST_BLANK`（破折号）。判定列与时间/歌名/难度
    照旧 —— 那几列本来就有字（`AP` / `FC` / `成功` / `中断` / `读取失败`）。

    占位符**必须与真数分得开**（2026-10-09 用户 m11595：「这些占位符与正常数的差距还是太小了，
    不够分明」）。第一版印的是 `0`，那是错的：`0` 是一个读数（真的零），和「没量到」长得一模一样。
    现在三种状态三个样子：**没读数** = `—`、**真 0** = 压暗的 `0`、**真数** = 正常字色 —— 视图层
    把 `hist_num(...) in (None, 0)` 的格子压暗（`HistModel.is_muted`），字形与字色各承担一半。

    排序口径一个字没动（`hist_value` 缺数仍是 `None`），次序由 `hist_order` 定：缺数的行
    **两个方向都排在最后**。
    """
    def num(key):
        v = hist_num(rec, key)
        return HIST_BLANK if v is None else v

    score = hist_num(rec, "score")
    return ["", rec.get("ts", ""), rec.get("song", ""), (rec.get("diff") or "").upper(),
            hist_badge(rec), num("aborts"), num("non_perfect"),
            num("perfect"), num("great"), num("good"), num("bad"), num("miss"), num("combo"),
            f"{score:,}" if score is not None else HIST_BLANK]


def hist_value(rec, col):
    """一列一个排序键。文本列按 str、其余按 int —— 从不混用。这一列没有数字的记录键为 None，
    那把它排到所有有数字的行**之后**（两个方向都如此）：缺数据不是最好成绩，
    也不是把它藏到每个次序末尾的理由。"""
    if col == "time":
        return rec.get("ts", "")
    if col == "song":
        return rec.get("song", "")
    if col == "diff":
        return DIFF_RANK.get((rec.get("diff") or "").upper(), -1)
    if col == "badge":
        return {"ap": 0, "fc": 1, "np": 2, "none": 3, "err": 4}[hist_kind(rec)]
    return hist_num(rec, NUM_COL[col])


def hist_order(rows, col, desc):
    """按 `hist_value(rec, col)` 排 `rows`，**缺数据的行两个方向都排在最后**。

    这一条必须由这里保证，不能交给 `sorted(key=..., reverse=...)`：拿「是不是 None」当元组第一位
    再把整个 key 交给 `reverse=True`，**缺数据那一行会被翻到最前面**（哨兵跟着一起翻）——
    2026-10-09 用户 m11595 报的「从大到小排序时占位符总是排在最前面」就是这个。所以先把有值的
    与缺数的分成两堆：有值那堆按方向排，缺数那堆原样接在后面。

    `reverse=` 的花招在混类型列上还会抛 `TypeError`（文本列里混进一个数字），那一档退回按
    `str` 排，仍是确定的次序 —— 一列脏数据不该让整个页面白屏。
    """
    have = [r for r in rows if hist_value(r, col) is not None]
    miss = [r for r in rows if hist_value(r, col) is None]
    try:
        have.sort(key=lambda r: hist_value(r, col), reverse=bool(desc))
    except TypeError:
        have.sort(key=lambda r: str(hist_value(r, col)), reverse=bool(desc))
    return have + miss


def ap_ids():
    """已 AP 的谱面编号：钉子里 best np == 0 的那些。

    读 validated.json 而不是 results.jsonl —— 后者只有滚动 100 局，早期的 AP 会被挤出去
    （实测窗内只剩 9 张），钉子才是累计口径（60+ 张）。
    """
    try:
        v = rlog.read_json(VALIDATED) or {}
        return {c for c, e in (v.get("charts") or {}).items()
                if rlog.pin_entry(e)["best"].get("np") == 0}
    except Exception:                                             # noqa: BLE001
        return set()


def song_ap(s, ap):
    diffs = s.get("difficulties") or []
    return sum(1 for d in diffs if chart_id(d) in ap), len(diffs)


# ---------------- 谱面库：读 manifest，出「筛选后的歌曲顺序」 ----------------

def library_summary(manifest):
    """谱面库页顶上的五个数字。没读到谱面库时返回 None（页面上换成「暂无谱面库」）。"""
    songs = manifest.get("songs", [])
    if not songs:
        return None
    pins = rlog.read_pins()
    gens = {"current": 0, "drifted": 0, "unrecorded": 0}
    for cid, e in pins.items():
        gens[rlog.pin_state(cid, e)] += 1
    queued = len((read_json(rlog.RELEARN_INDEX, {}) or {}).get("queue") or {})
    return {
        "songs": f"{len(songs)} 首",
        "charts": f"{sum(len(s['difficulties']) for s in songs)} 张",
        "pins": f"{len(pins)} 张：同代 {gens['current']}／已变 {gens['drifted']}／"
                f"未记 {gens['unrecorded']}",
        "relearn": f"{queued} 张",
        "fetched": str(manifest.get("fetched_at", "?")),
    }


def categories(manifest):
    """(cat_map, native_ids, band_rank)：下拉框的 {标签: bandId} 与两个查表。"""
    songs = manifest.get("songs", [])
    bands = manifest.get("bands") or []
    cat_map = {"全部": None}
    native_ids = {b.get("bandId") for b in bands}
    band_rank = {b.get("bandId"): i for i, b in enumerate(bands)}
    if bands:
        for b in bands:
            count = sum(1 for s in songs if s.get("bandId") == b.get("bandId"))
            if count:
                cat_map[f"{b.get('name') or b.get('bandId')}（{count}）"] = b.get("bandId")
        rest = sum(1 for s in songs if s.get("bandId") not in native_ids)
        if rest:
            cat_map[f"其他（{rest}）"] = "other"
    else:
        seen = {}
        for s in songs:
            seen.setdefault(s.get("bandId"), s.get("bandZh") or s.get("band") or "?")
        for band_id, name in sorted(seen.items(),
                                    key=lambda kv: ((0, kv[0]) if isinstance(kv[0], int)
                                                    else (1, 0))):
            count = sum(1 for s in songs if s.get("bandId") == band_id)
            cat_map[f"{name}（{count}）"] = band_id
    return cat_map, native_ids, band_rank


def song_name(s):
    """排序与搜索用的歌名。**字段名以清单为准**：`titleRomaji`，不是 `roma`。

    清单里没有 `roma` 也没有 `titleZh`（实测 87 首，两个字段 0 命中）。这两个名字来自
    nnnotes 那边的格式，本仓的 fetch_charts.py 写的是 `titleRomaji`/`title`。读错字段不会
    报错，只会静默退回中文标题 —— 「罗马音序」变成「按中文码位序」，搜索框查不到罗马音和
    拼音。这一处曾经真的写错过，`probes/paneldata.py` PART 5 就是钉它的。

    这一份只服务**排序与搜索**（罗马音序要按拉丁转写排）；界面上写哪几个字走
    `song_label()` —— 合成一个函数的话，改排序口径就会顺手改掉界面语言。
    """
    return str(s.get("titleRomaji") or s.get("title") or "")


def song_label(s):
    """列表里**给人看**的歌名：原文标题（日文/中文）优先，没有才退回罗马音。

    与 `song_name()` 分工不同，有意分开：那一份按罗马音排、按罗马音搜，这一份决定界面上
    写什么字。清单里 87 首的 `title` 都是原文（迷星叫 / 壱雫空 / 影色舞…），游戏里显示
    的也是它；列表从前显示的是 `song_name()`，于是整列都是 Mayoiuta / Hitoshizuku 这种
    拉丁转写，看着像「全是英文名」。`probes/fletpanel.py` 第 11 关钉这两件事不许再合流。
    """
    return str(s.get("title") or s.get("titleRomaji") or "")


def song_romaji(s):
    """副标题里的拉丁转写。清单里不少歌只有汉字名（`titleRomaji` 与 `title` 同值），
    这种返回空串，免得同一行写两遍同样几个字。"""
    ro = str(s.get("titleRomaji") or "")
    return "" if ro == song_label(s) else ro


def song_all_ap(s, ap):
    """这首歌的每一档都 AP 了吗？列表徽标、「已 AP 几首」计数与「未AP优先」排序共用它。"""
    done, total = song_ap(s, ap)
    return bool(total) and done == total


# 搜索框能看见的字段。改这里之前先看 `probes/paneldata.py` PART 7 —— 它从清单里挑真实存在
# 的字段去搜，要求搜得到，所以少一个键就会亮。
SONG_HAY_KEYS = ("title", "titleRomaji", "band", "bandZh",
                 "py", "pyJoin", "pyInitials")


def song_hay(s):
    """一首歌的可搜文本。拼音四件套是「输入 liu zhao nian / lzny 都能找到」的原因。"""
    parts = [str(s.get(k) or "") for k in SONG_HAY_KEYS]
    parts.append(" ".join(s.get("pyAlt") or []))
    parts.append(str(s.get("musicId") or ""))
    return " ".join(parts).lower()


def song_sort_key(mode, s, band_rank, ap):
    """歌曲列的一种排序 —— 全仓唯一一份实现。

    这不是「随手写的排序」，而是从当初那套 Tk 面板逐位抄过来的口径，抄的时候才发现两边
    已经悄悄不一致了（难度升序一边取 expert 那一档的 sortLevel、一边取所有档的最大值；
    乐队优先一边组内按 musicId、一边按歌名；未AP优先一边多一层「已 AP 数从少到多」）。
    排序是最容易悄悄改掉的东西：改了不报错、不写日志，只是列表顺序不同，用户只会觉得
    「怎么跟以前不一样」。`probes/paneldata.py` PART 6 钉这件事。

    四个模式各自的口径：
      - 乐队优先：`(bk, mid)`，bk = (乐队在清单里的次序, bandId)，非清单内的乐队排最后。
      - 罗马音序：`(罗马音小写, bk, mid)`。
      - 难度升序：**expert 那一档**的 sortLevel（不是所有档的最大值）。
      - 未AP优先：全 AP 的沉底，其余**按已 AP 数从少到多**（-total + done），再按乐队、编号。
    """
    bi = s.get("bandId")
    bk = (band_rank.get(bi, len(band_rank)), bi if isinstance(bi, int) else 99)
    try:
        mid = int(s.get("musicId"))
    except (TypeError, ValueError):
        mid = 0
    if mode == "罗马音序":
        return (song_name(s).lower(), bk, mid)
    diffs = s.get("difficulties") or []
    if mode == "难度升序":
        d = next((x for x in diffs if x.get("name") == "expert"), None) or {}
        return (d.get("sortLevel") or d.get("level") or 0, bk, mid)
    if mode == "未AP优先":
        done, total = song_ap(s, ap)
        return (0 if song_all_ap(s, ap) else 1, -total + done, bk, mid)
    return (bk, mid)


def filtered_songs(manifest, query, cat, native_ids, band_rank, ap, mode, desc):
    """搜索 + 分类 + 排序之后，歌曲列表里该显示的那些。"""
    q = (query or "").strip().lower()
    rows = []
    for s in manifest.get("songs", []):
        if cat == "other":
            if s.get("bandId") in native_ids:
                continue
        elif cat is not None and s.get("bandId") != cat:
            continue
        if q:
            hay = song_hay(s)
            if q not in hay:
                continue
        rows.append(s)
    rows.sort(key=lambda s: song_sort_key(mode, s, band_rank, ap), reverse=bool(desc))
    return rows


def read_history_records():
    """结算记录页的数据源：tag -> record。新记录覆盖同 tag 的旧记录。"""
    out = {}
    for rec in rlog.read_records(rlog.HISTORY_FULL) or []:
        t = rec.get("tag")
        if t:
            out[t] = rec
    return out


# ---------------- 运行管道：起 run.py、读它的 stdout、发事件 ----------------

class RunOrchestrator:
    """跑一局（或连续 n 局）的那条链路，与界面框架无关。

    视图要做的事情只有两件：把用户的选择交给 `start()`，然后每 ~120 ms 把 `q` 排空、
    按事件种类更新自己的画面。停止是 `stop_graceful()`（本轮结束就不再开始下一轮）与
    `force_kill()`（立刻杀掉 run.py）—— 这两个的差别是有意义的：前者不毁掉正在飞的这一局。
    """

    def __init__(self, state):
        self.state = state
        self.q: queue.Queue = queue.Queue()
        self.proc: subprocess.Popen | None = None
        self.worker: threading.Thread | None = None
        self.stop_flag = threading.Event()
        # 更新链路里「面板对确认框的那一按」：`update_charts(force=True)` 比对完停在这里等，
        # 由视图线程 `answer_update()` 放行（普通更新不看它）。
        self.decide: dict = {}
        self.decide_ev = threading.Event()
        self.serial: threading.Lock = threading.Lock()
        # 本轮 run.py 说它回到乐曲选择页的时刻；演出间隔从这里起算，每轮清零 ——
        # 一个从没走回选曲页的轮次不能借上一轮的锚点等待。
        self.at_select: float | None = None
        # 夜间看门狗（用户 m28899 的第 ③ 条）：一批局里「多久没新输出算卡死」与救场额度。
        # `_stalled` 由 `_spawn_run` 的监控线程置位，`_run_loop` 在那一轮收尾时救场。
        self.watch = watchdog.StallWatch()
        self._stalled = False

    def busy(self):
        return (self.worker is not None and self.worker.is_alive()) or self.proc is not None

    # ---- 策略：从 state 里读出这一刻的运行参数（设置页改了立刻生效） ----

    def defaults(self):
        return (self.state.get("defaults") or {})

    def push_ms(self):
        """正推上限（ms）。键是 `push_cap_ms` —— 设置页那个数字框、`refresh_policy` 与开跑
        确认框念的都是它。

        从前这里读的是 `push_ms`，而那个键**全仓只有这一处读**、面板从来不写它：框里填 0
        也永远返回 `PUSH_ON_MS`(10)，于是面板实际发的是 `--live-push-cap 10`，与框里、
        与确认框里写的 0 不是一回事（2026-10-10 用户 m14586 要用 CLI 跑 cap 0 时逐行核出来
        的）。旧键名留着当兜底，空值不算数。
        """
        d = self.defaults()
        for key in ("push_cap_ms", "push_ms"):
            v = d.get(key)
            if v is None:
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return PUSH_ON_MS

    def retry_cap(self):
        d = self.defaults()
        try:
            return int(d.get("retry_cap", RETRY_CAP))
        except (TypeError, ValueError):
            return RETRY_CAP

    def gap_min(self):
        """演出间隔的分钟数。上界也夹在这里：输入框那条路已经夹过（`flet_gui.clamp_num`），
        但状态文件是可以手改的 —— 写个 999 进去就是 999 分钟的等待，这一层不能只兜非负。"""
        d = self.defaults()
        try:
            return min(float(GAP_MAX_MIN), max(0.0, float(d.get("gap_min", 0.0))))
        except (TypeError, ValueError):
            return 0.0

    def fire_gate(self):
        """开打前是否要求火力 ≥ `FIRE_MIN`（开关，存在 defaults 里，与别的开关同一处）。"""
        return bool(int(self.defaults().get("fire_gate", 0) or 0))

    def rounds(self):
        d = self.defaults()
        try:
            return max(1, int(d.get("runs", 1)))
        except (TypeError, ValueError):
            return 1

    def kind_lead(self):
        """**种类偏移**：每类键的偏移量（ms，**正数 = 更早**）。状态键是 `kind_lead`，一个
        dict，缺的按 `KIND_LEAD_MS` 补。

        面板上那四个框 2026-10-05 被删过（读数没法在面板里验），2026-10-10 用户 m15057
        「把四种都放出来」让它们回到设置页；同一天用户 m15291 把它改名「分类偏移」，
        2026-10-21 用户 m53176 再改成「种类偏移」（旧名与选曲页那个「分类」下拉撞名）。
        **认不出的键名直接丢**：`run.py` 的 `parse_kind_lead` 遇到不认识的种类名会拒绝整局，
        那不该由状态文件里一行旧数据触发。
        """
        raw = self.defaults().get("kind_lead")
        out = dict(KIND_LEAD_MS)
        if isinstance(raw, dict):
            for k in KIND_LEAD_MS:
                v = raw.get(k)
                if v is None:
                    continue
                try:
                    out[k] = float(v)
                except (TypeError, ValueError):
                    continue
        return out

    def tail_flick_lead(self):
        """**尾判滑键**：长条尾巴上那一记滑键提前多少毫秒（正数 = 更早）。

        状态键是 `tail_flick_lead`（**不是** `kind_lead` 里的第五个键 —— 它不是一个种类，
        而是「长条尾巴上挂着 flick」这一种**手势位置**，与 `long` 那一格叠加；`run.py` 的
        `parse_kind_lead` 也会把不认识的名字整局拒掉）。缺省 = 出厂值
        `TAIL_FLICK_LEAD_DEFAULT`（与 `player.TAIL_FLICK_LEAD_MS` 同一份）。
        """
        try:
            return float(self.defaults().get("tail_flick_lead", TAIL_FLICK_LEAD_DEFAULT))
        except (TypeError, ValueError):
            return TAIL_FLICK_LEAD_DEFAULT

    # ---- 起跑 ----

    def start(self, chart_id, song, diff, n, stop_ap, random_mode=False, retry_break=False,
              push_cap=True, multi=None):
        """把一条跑局链路拉到后台线程。调用者负责先确认自己不在忙。

        `multi` 非空 = 这一局是**激奏演出**（`run.py --multi`），它的值就是难度名：房间自己
        抽曲，所以 `chart_id` 与那个 hits 文件都不参与（面板不选曲），难度按这里的名字发
        `--diff`。单人局保持默认 `None`，命令行与从前逐字相同。
        """
        with self.serial:
            if self.busy():
                return False
            # 与 CLI 同一条启动校验（`run.py` 的 main 里那一段）：面板起的子进程也是同一个
            # run.py，但把话说在前面比让它三分钟后以「走页停住」失败要好。路径集中在
            # `tools/locate.py`，缺什么就写哪一行错误进日志页。
            if not locate.check(("adb", "minitouch"),
                                log=lambda s: self.q.put(("log_err", s))):
                return False
            self.stop_flag.clear()
            self.worker = threading.Thread(
                target=self._run_loop,
                args=(chart_id, song, diff, n, stop_ap, random_mode, retry_break, push_cap,
                      self.retry_cap(), self.push_ms(), self.gap_min(), self.fire_gate(), multi,
                      self.kind_lead(), self.tail_flick_lead()),
                daemon=True)
            self.worker.start()
            return True

    def stop_graceful(self):
        self.stop_flag.set()
        self.q.put(("log_dim", "已请求停止，本轮结束后不再开始下一轮"))

    def force_kill(self):
        self.stop_flag.set()
        p = self.proc
        if p is not None and p.poll() is None:
            self.q.put(("log_err", "强制终止当前演奏，游戏内本局将失败，下一轮会重新进入 LIVE"))
            p.kill()
        self.kill_stray_minitouch()

    # ---- 资源更新（联网比对上游 + 补下载谱面） ----
    #
    # 这一段从前长在 Tk 版的设置页里（`update_charts()` + `_stream()`），面板全面转 PySide6 时
    # 整组被删掉了，只剩视图层那两个处理器（`upstream` / `charts_done`）没人喂事件 ——
    # 用户报「设置里的资源更新不见了」（m06894）。两个工具本身一直都在。

    def update_charts(self, force=False, verify=False, source=None):
        """联网更新谱面库：先比对上游目录，再补下载缺失或缺封面的谱面。

        `force=True` 对应面板上的「强制重下」（`fetch_charts.py --force`）；`verify=True` 是
        「逐张核对」（`check_upstream.py --verify`：把目录点名的那几张真下下来按 sha 比一次 ——
        noteCount 可以活过改谱，**纯几何改动只有这一步看得见**）；`source` 是首选目录
        （`--source=moenotes|haneoka`）。整条链路跑在 `self.worker` 上，所以**更新期间面板起不了
        局** —— `fetch_charts` 会重写 `research/charts/`，一边重写一边飞会读到半份谱面。
        返回 False = 已经有活在跑。
        """
        with self.serial:
            if self.busy():
                return False
            self.stop_flag.clear()
            self.decide = {}
            self.decide_ev.clear()
            self.worker = threading.Thread(
                target=self._update_loop, args=(bool(force), bool(verify), source), daemon=True)
            self.worker.start()
            return True

    def answer_update(self, ok, force=None):
        """面板对确认框的那一按：`update_charts(force=True)` 在比对之后停在这里等它。

        只有开了「强制重下」才会问（它会把全部谱面重新下载并重编译）。超时、`stop_flag`
        或 `force_kill()` 都会把这次更新收掉，不会把面板卡在忙态。
        """
        self.decide = {"ok": bool(ok)}
        if force is not None:
            self.decide["force"] = bool(force)
        self.decide_ev.set()

    @staticmethod
    def _mtime(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0.0

    @staticmethod
    def _pinned_ids():
        """钉子保护着的谱面号；读不出来就是空集（面板照实说，不假装保护了谁）。"""
        try:
            return set((read_json(VALIDATED, {}) or {}).get("charts", {}) or {})
        except Exception:                                        # noqa: BLE001
            return set()

    def _update_loop(self, force, verify=False, source=None):
        """比对 → （开着「强制重下」就先问面板）→ 下载。

        **只有这一趟真写过报告才算证据**：报告文件跨趟留存，失败的一趟读它等于把上一次的目录
        差异端上来（原 Tk 版用 mtime 前后比较守住这件事）。比对那一步之后用户按了停止就不再
        下载（只读那一步不白跑）。
        """
        before = self._mtime(UPSTREAM_REPORT)
        cmd = [os.path.join(ROOT, "tools", "check_upstream.py")]
        if source:
            cmd.append("--source=" + str(source))
        if verify:
            cmd.append("--verify")
        rc = self._stream_tool(cmd, "上游比对", timeout=120)
        fresh = rc == 0 and self._mtime(UPSTREAM_REPORT) > before
        rep = (read_json(UPSTREAM_REPORT, {}) or {}) if fresh else {}
        self.q.put(("upstream", {"rc": rc, "report": rep, "fresh": fresh,
                                 "validated": self._pinned_ids(), "force": bool(force)}))
        if force:
            # 重下要把全部谱面重新下载并重编译（含飞过的），代价太大：把目录现状摆给用户看了再
            # 决定。每 0.25 秒看一眼 stop_flag，所以「本轮停止」「强制终止」在这里立刻生效。
            deadline = time.time() + DECIDE_WAIT
            while not self.decide_ev.wait(0.25):
                if self.stop_flag.is_set() or time.time() > deadline:
                    break
        if self.stop_flag.is_set():
            self.q.put(("log_dim", "更新已停止，没有开始下载"))
            self.q.put(("done", None))
            return
        if force:
            if not (self.decide_ev.is_set() and self.decide.get("ok")):
                self.q.put(("update_abort", None))
                return
            if "force" in self.decide:
                force = bool(self.decide["force"])
        cmd = [os.path.join(ROOT, "tools", "fetch_charts.py")] + (["--force"] if force else [])
        rc = self._stream_tool(cmd, "更新谱面", timeout=1800)
        if self.stop_flag.is_set():
            self.q.put(("log_dim", "更新已停止"))
            self.q.put(("done", None))
            return
        self.q.put(("charts_done", rc))

    def _stream_tool(self, cmd, phase, timeout=900):
        """跑一个同级工具，输出逐行进面板日志；返回退出码（负数是启动失败或超时）。

        `cmd` 可以是脚本路径（`str`）、`[脚本路径, 选项…]` 或现成的 argv —— 头一个元素是 `.py`
        就补上本机解释器（不补就是 Windows 的 193，见下面那段注释）。与 `_spawn_run` 同一套写法
        （`self.proc` 因此也被 `force_kill()` 认，能中途终止）。

        读输出**另起一条线程**：从前是在这里直接 `for line in self.proc.stdout` 读，于是
        `wait(timeout)` 要等读到 EOF 才轮到 —— 卡在网络上的那一趟永远走不到超时那一步
        （用户 m07356 那一轮点名过这件事）。进度条也在这里喂：`fetch_charts.py` 逐首打
        `[i/N]`，按行头认出来就推一条 `("progress", i/N)`。
        """
        # `cmd` 的三种形状都要能起来：脚本路径（`str`）、`[脚本路径, 选项…]`、现成的 argv。
        # **Windows 的 CreateProcess 不按文件关联执行 `.py`**：把脚本路径直接当程序名交给它，
        # 报的是 `OSError(8, '%1 不是有效的 Win32 应用程序。', None, 193, None)`（193 =
        # ERROR_BAD_EXE_FORMAT）。`_update_loop` 那两趟传的正是 `[脚本路径, …]` 这种形状，而这里
        # 从前只在 `isinstance(cmd, str)` 时补解释器 ⇒ 面板上「联网更新」自 2026-10-06（`ace8e77a`
        # 全面转 Flet 那一笔）起两趟都起不来，用户 m09816 报的「更新功能损坏了」就是这一条。
        # 回归：`tools/probes/panelfly.py` PART 7（拿假 Popen 记下两次调用真收到的 argv）。
        if isinstance(cmd, str):
            cmd = [cmd]
        cmd = [str(x) for x in cmd]
        if cmd and cmd[0].lower().endswith(".py"):
            cmd = [sys.executable, *cmd]
        self.q.put(("phase", phase))
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=ROOT, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                bufsize=1, creationflags=CREATE_NO_WINDOW,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        except Exception as e:                                   # noqa: BLE001
            self.q.put(("log_err", f"{phase}起不来：{e!r}"))
            self.proc = None
            return -1
        child = self.proc
        reader = threading.Thread(target=self._pump_child, args=(child,), daemon=True)
        reader.start()
        rc = -1
        try:
            rc = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            child.kill()
            self.q.put(("log_err", f"{phase}超过 {timeout:g} 秒没结束，已终止"))
            try:
                child.wait(timeout=10)
            except Exception:                                    # noqa: BLE001
                pass
        except Exception as e:                                   # noqa: BLE001
            self.q.put(("log_err", f"{phase}出错：{e!r}"))
        finally:
            reader.join(timeout=5)
            if self.proc is child:
                self.proc = None
        return rc

    def _pump_child(self, child):
        """把子进程的输出逐行搬进面板日志（跑在自己那条线程上）。

        子进程被杀时读到 EOF 自然收工；`stop_flag` 一置起来就把它收了 —— 与从前同一个行为，
        只是不再挡着 `wait(timeout)` 那一步。
        """
        try:
            for line in child.stdout:
                text = line.rstrip()
                m = PROGRESS_RE.match(text)
                if m:
                    try:
                        done, total = int(m.group(1)), max(1, int(m.group(2)))
                        self.q.put(("progress", min(1.0, done / total)))
                    except Exception:                            # noqa: BLE001
                        pass
                self.q.put(child_line(text))
                if self.stop_flag.is_set():
                    child.kill()
                    break
        except Exception:                                        # noqa: BLE001
            pass

    @staticmethod
    def kill_stray_minitouch():
        """设备上残留的 minitouch 进程，按 PID 精确杀。

        注意这里**不**清杀 python/pythonw —— 用户的面板可能就在里面跑（AGENTS.md 的红线）。
        minitouch 是设备侧的行，与主机进程无关。
        """
        try:
            out = subprocess.run([ADB, "-s", DEVICE, "shell", "ps -A"], capture_output=True,
                                 text=True, timeout=15, creationflags=CREATE_NO_WINDOW).stdout
        except Exception:                                         # noqa: BLE001
            return
        for ln in out.splitlines():
            if "minitouch" in ln:
                parts = ln.split()
                if len(parts) > 1:
                    subprocess.run([ADB, "-s", DEVICE, "shell", f"kill {parts[1]}"],
                                   capture_output=True, timeout=15, creationflags=CREATE_NO_WINDOW)

    # ---- 内部 ----

    def _run_loop(self, chart_id, song, diff, n, stop_ap, random_mode, retry_break, push_cap,
                  retry_cap, push_ms, gap_min, fire_gate, multi=None, kind_lead=None,
                  tail_lead=None):
        multi = str(multi or "") or None
        # 多人局**没有**「断AP立即重试」（用户 m12749）：那条能力是「暂停 LIVE → 重试 → 确定」
        # 把同一首从头再打，房间局重开要么走不通、要么把这一轮直接作废（run.py 的 `_to_t0`
        # 走不出去就 return 1）。调用方本来就不该在 multi 下发它；这里再兜一次，顺便让下面
        # 那行表头说的与真发出去的一致。
        if multi:
            retry_break = False
        self.state["last_chart"] = chart_id or ""
        hits = (None if (random_mode or multi)
                else os.path.join(rlog.CHARTS, f"{chart_id}.hits.json"))
        # 随机的一轮在 run 回来之前没有名字，所以退回值是「随机」；真标题在 RESULT 行里回来，
        # 由 `record_round` 覆盖。多人局同理 —— 房间抽到哪一首只有 準備 页上才知道，那之前
        # 记的是「房间抽曲」。
        if multi:
            base_song, base_diff = "房间抽曲", multi
        elif random_mode:
            base_song, base_diff = "随机", ""
        else:
            base_song, base_diff = song, diff
        failures = 0
        # 每批一份新的看门狗额度（用户 m28899 的第 ③ 条）。
        self.watch = watchdog.StallWatch()
        self._stalled = False
        for i in range(1, n + 1):
            if self.stop_flag.is_set():
                self.q.put(("log_dim", "已停止，未开始下一轮"))
                break
            self.at_select = None
            tag = next_tag(self.state)
            label = ("多人演出" if multi else "随机选曲" if random_mode else f"{song} {diff.upper()}")
            self.q.put(("phase", f"[{i}/{n}] {label} {tag}"))
            self.q.put(("log_hdr", f"第 {i}/{n} 轮 编号 {tag} "
                                   + ("房间自己抽曲（面板每轮随机提名一首）"
                                      if (multi and random_mode)
                                      else "房间自己抽曲（面板不选曲）" if multi
                                      else "每轮由游戏随机选曲" if random_mode else hits)
                                   + (f" 断AP立即重试 {retry_cap} 次" if retry_break else "")
                                   + (f" 正推限制 +{push_ms:.0f} ms"
                                      if (push_cap and not multi) else "")
                                   + (f" 种类偏移 {kind_lead_text(kind_lead)}"
                                      if any(kind_lead or {}) else "")
                                   + tail_lead_text(tail_lead)))
            rc, rec = self._spawn_run(hits, tag, random_mode, retry_break, push_cap,
                                      retry_cap, push_ms, fire_gate, multi, kind_lead,
                                      tail_lead)
            ok = rc == 0 and isinstance(rec, dict) and "error" not in rec
            self.state["last_ok"] = ok
            save_state(self.state)
            self.q.put(("result", {"record": self.record_round(tag, base_song, base_diff,
                                                               rec, rc, multi=bool(multi)),
                                   "tag": tag}))
            if self._stalled:
                # 看门狗终止了这一局（用户 m28899 的第 ③ 条）：游戏大概率冻在某个页面或加载上，
                # 收掉子进程只是第一步 —— 重开游戏、再走回 楽曲選択，下一轮才起得来。额度每批
                # `MAX_RECOVER` 次、两次之间至少 `RECOVER_GAP_S`；用完了就只报、不再动游戏。
                self._stalled = False
                seq = self.watch.claim(time.monotonic())
                if seq:
                    self.q.put(("log_err", f"看门狗：第 {seq}/{self.watch.max_recover} 次救场"
                                           f" —— 重开游戏，再走回乐曲選択"))
                    got = watchdog.recover(log=lambda s: self.q.put(("log_dim", s)))
                    self.q.put(("log_ok" if got else "log_err",
                                "看门狗：游戏已重开并回到乐曲選択" if got
                                else "看门狗：救场没走完 —— 下一轮可能起不来"))
                else:
                    self.q.put(("log_err", "看门狗：这一批的救场额度用完了，不再重开游戏"))
            if ok and rec.get("all_perfect"):
                name = rec.get("song") or song or "?"
                dname = (rec.get("diff") or diff or "").upper()
                self.q.put(("phase", f"ALL PERFECT {name} {dname} {tag}"))
                if stop_ap:
                    self.q.put(("log_ok", "ALL PERFECT，连续演出结束"))
                    break
                self.q.put(("log_ok", "ALL PERFECT，未勾选停止，继续下一轮"))
            elif not ok:
                failures += 1
                self.q.put(("log_err", f"第 {i} 轮失败，退出码 {rc}"))
                if failures >= 2:
                    self.q.put(("phase", "连续两次失败，已停止"))
                    self.q.put(("log_err", "请检查模拟器与游戏状态后重新开始"))
                    break
            else:
                failures = 0
            if i < n and not self._wait_before_next(gap_min):
                # 「停止」在等待里被按下：收尾就到这里，不再开下一局（也不再报一次）。
                break
        self.q.put(("done", None))

    def _wait_before_next(self, gap_min):
        """轮与轮之间坐多久。锚点是「回到乐曲选择页」，不是「上一轮结束」。

        `False` 表示「停止」被按下 —— 调用方不许再开下一局。

        这里**只问一次** `gap_wait`，然后把它数完。第一版把 `gap_wait` 放进了循环里反复问，
        而下限（收尾那一拍，2 秒）是**下限**不是倒计时：`left` 一旦落到下限上，下一轮再问
        还是同一个下限，`left <= 0` 就永远不成立 —— 只要间隔非零，面板就永远停在
        「等待下一轮 0:02」上，下一局永远不会开始（间隔越短越容易撞上）。而间隔为 0 时，
        第一版的守卫 `if gap_min <= 0: return` 又让收尾那一拍整个消失（Tk 版一直等着它）。
        两个错同源：把「还要等多久」当成一个可以反复问的量，其实它是从这一刻起算的定值。
        """
        anchor = self.at_select if self.at_select is not None else time.monotonic()
        want = gap_wait(gap_min, time.monotonic() - anchor)
        if want > GAP_FLOOR_S:
            self.q.put(("log_dim", f"演出间隔 {gap_min:g} 分钟（从回到乐曲选择页起算）"))
            left = want
            while left > 0:
                self.q.put(("phase", f"等待下一轮 {int(left) // 60}:{int(left) % 60:02d}"))
                if self.stop_flag.wait(min(1.0, left)):
                    self.q.put(("log_dim", "已停止，未开始下一轮"))
                    return False
                left -= 1.0
            return True
        return not self.stop_flag.wait(want)

    def _spawn_run(self, hits, tag, random_mode, retry_break, push_cap, retry_cap, push_ms,
                   fire_gate=False, multi=None, kind_lead=None, tail_lead=None):
        # 演奏器的路径可以被环境变量换掉：整条「起进程 → 解析标准输出 → 收结果」的链路
        # 因此能在没有模拟器的情况下被真测一遍（替身见 tools/_fake_runner.py，探针见
        # tools/probes/panelfly.py）。生产路径就是 tools/run.py。
        runner = os.environ.get("OURNOTES_RUNNER") or os.path.join(ROOT, "tools", "run.py")
        cmd = [sys.executable, runner]
        if multi:
            # 激奏演出：面板不选曲 —— 房间自己抽，位置参数那个 hits 文件用不上（`run.py`
            # 在 `--multi` 下也不收它）。难度按面板选的那个发 `--diff`；房间的难度与它不同时，
            # `run.py` 会在 乐曲选择 页上改过来（改不成则按页面上的那个打完并说明）。
            cmd += ["--multi", "--diff", str(multi)]
            if random_mode:
                # 多人页那颗「随机乐曲」（2026-10-16 用户 m27959 顶掉了原来的「LB监测」）：
                # 谱面是房间从五个人的提名里抽的，面板能做的只是**随机提名一首** ——
                # `run.py` 在 楽曲選択 页按 `--random` 挑一首当提名（`on_select_multi`），
                # 打哪首仍由房间抽。不发这一条时提名页面上停着的那一首。
                cmd += ["--random"]
        else:
            cmd += ["--random"] if random_mode else [hits]
        # `--host` 与 `--fastcap` 一起发，是**兜底**而不是第二选择：`run.py` 同时收到两者时先试
        # MuMu 的渲染器 SDK，只有 SDK 装不上（DLL 被 MuMu 更新换掉、句柄被另一个实例占住）才去装
        # 窗口抓帧（Windows.Graphics.Capture，16.7 ms/帧 ≈ 60 fps）。装窗口那一步会把模拟器窗口调
        # 到客户区 1312×782，所以它**推迟**到 SDK 失败那一刻 —— SDK 正常的那一局它一个字节都不动。
        # 值这一条的理由：SDK 挂了而没带 `--host` 时，整局只能吃 `screencap` 的 257 ms（3.9 fps），
        # 锚点基本锁不准；带上它那一局还有 60 fps 可走。契约由 `tools/probes/panelfly.py` 第 1 关钉。
        cmd += ["--fastcap", "--host", "--retry-anchor", "--offset", str(OFFSET),
                "--live-push-cap", str(MULTI_PUSH_CAP_MS if multi
                                       else (push_ms if push_cap else PUSH_OFF_MS)),
                "--watch-hud", "--tag", tag]
        if retry_break and not multi:
            # 多人局不发这一条（用户 m12749）：房间局不能把同一首从头再打一遍，而这条能力的
            # 失败路径是「整轮作废」。`_run_loop` 已经先把它按 False 收口，这里再挡一次 ——
            # 契约由 `tools/probes/panelfly.py` 第 1 关钉（multi 下必须没有这一条）。
            cmd += ["--retry-on-break", str(retry_cap)]
        if fire_gate:
            # 火力不足就在乐队确认页等（`calib.start_live` 那一侧不设等待上限）—— 关闭时这条
            # 参数根本不出现，命令行与从前逐字相同，探针里比对 argv 的那些判据不受影响。
            cmd += ["--min-fire", str(FIRE_MIN)]
        lead = kind_lead_arg(kind_lead)
        if lead:
            # 种类偏移（用户 m15057 把四个框放回设置页，m15291 改名）。**只列非零的**：全零时这条
            # 参数根本不出现，命令行与从前逐字相同。`run.py` 的 `parse_kind_lead` 会从出厂表开始
            # 覆盖，所以少写几个键 = 那几个键仍是 0，不是「没设」。
            cmd += ["--kind-lead", lead]
        if tail_lead is not None and abs(float(tail_lead) - TAIL_FLICK_LEAD_DEFAULT) > 1e-9:
            # 尾判滑键（用户 m52916「能否将尾滑偏移加入设置」）：与出厂值相同时这条参数**不出现**，
            # 命令行与从前逐字相同（`probes/panelfly.py` 第 1 关拿它钉 argv）。0 是有意义的一档
            # ——「关掉这一段提前量」，所以判的是「与出厂值不同」而不是「非零」。
            cmd += ["--tail-flick-lead", f"{float(tail_lead):g}"]
        # OURNOTES_PANEL 告诉 run.py：results.jsonl 的写手是面板。没有它，面板跑的一局会被
        # 记两次（run.py 从 shell 飞的时候自己记账）。
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "OURNOTES_PANEL": "1"}
        out_path = os.path.join(RUN_OUT_DIR, f"{tag}.out")
        rec = None
        # 看门狗（用户 m28899 的第 ③ 条）：一局正常时每几秒就有一行（走页 verdict、HUD、
        # 投票）；静默超过 `watchdog.STALL_S` 就收掉子进程。`pc5504` 静默 14 分钟、`mp8`
        # 在匹配弹窗上坐了 15 分钟 —— 从前这里只有一个「读到 EOF 为止」的循环，卡住的一局
        # 会把整批钉在那里。收掉之后由 `_run_loop` 决定救不救（额度在那边）。
        self._stalled = False
        self.watch.note(time.monotonic())
        stop_mon = threading.Event()

        def _stall_monitor(child):
            while not stop_mon.wait(5.0):
                if child.poll() is not None:
                    return
                if self.watch.due(time.monotonic()):
                    self._stalled = True
                    self.q.put(("log_err", f"看门狗：{int(self.watch.stall_s)} 秒没有新输出"
                                           f" —— 终止这一局"))
                    try:
                        child.kill()
                    except Exception:                            # noqa: BLE001
                        pass
                    return

        try:
            self.proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                         errors="replace", bufsize=1, creationflags=CREATE_NO_WINDOW,
                                         env=env)
            threading.Thread(target=_stall_monitor, args=(self.proc,), daemon=True).start()
            with open(out_path, "w", encoding="utf-8") as out:
                for line in self.proc.stdout:
                    line = line.rstrip()
                    self.watch.note(time.monotonic())
                    if line == "#ATSELECT#":
                        # 本轮已经走回乐曲选择页 —— 演出间隔的基点。认这条机器行而不认
                        # 「导航：乐曲选择页」那句话：同一个页面在日志里有两种写法，其中一种是
                        # 「连续四次读不到变化」，拿它当到达就把卡住当成了成功。
                        self.at_select = time.monotonic()
                        continue
                    if line.startswith("#STATUS#"):
                        # 机器通道：它只推动状态标签与进度条，不是日志的一行。
                        self._scan_status(line)
                        continue
                    if NATIVE_NOISE.match(line):
                        # mumucap 的原生库在 run 的进程退出时，把连接横幅直接写到 fd 1，
                        # 就夹在日志中间。
                        continue
                    out.write(line + "\n")
                    out.flush()
                    self.q.put(child_line(line))
                    if line.startswith("RESULT "):
                        rec = read_json_str(line[7:])
            rc = self.proc.wait()
        except Exception as e:                                    # noqa: BLE001
            self.q.put(("log_err", f"启动 run.py 失败：{e!r}"))
            if self._reap_child():
                # 这一条线索是给「面板看起来正常、游戏却留在 LIVE」那个形状留的：子进程已经
                # 弹过一部分键了，收掉它意味着这一局作废，不收掉意味着它带着一个没人读的管道
                # 活着 —— 几十 KB 之后永久阻塞在 print 上，而面板已经把唯一的句柄丢掉了。
                self.q.put(("log_err", "已收掉这一轮的子进程，游戏内本局作废"))
            rc = -1
        finally:
            stop_mon.set()
            self.proc = None
        return rc, rec

    def _reap_child(self):
        """收掉当前子进程，返回「确实收掉了一个还活着的」。

        异常路径**必须**走这里。原来只在 `finally` 里把 `self.proc` 置空，于是 `open(out_path)`
        一失败（磁盘满、杀软锁住、目录被别的东西占了）就留下一个活着、没人读管道的 run.py：
        它继续在游戏里弹键，面板却再也够不着它，`force_kill()` 拿到的已经是 `None`。
        """
        p = self.proc
        if p is None:
            return False
        alive = p.poll() is None
        if alive:
            try:
                p.kill()
            except Exception:                                     # noqa: BLE001
                pass
        try:
            p.wait(timeout=5)
        except Exception:                                         # noqa: BLE001
            pass
        try:
            if p.stdout is not None:
                p.stdout.close()
        except Exception:                                         # noqa: BLE001
            pass
        return alive

    def _scan_status(self, line):
        """`#STATUS#` 的拆包：`phase` / `progress` 各自走一条老事件，其余键汇总成一条。

        `phase`/`progress` 是面板一直认的那两个（探针按名字钉着），所以保持原样；`player.play`
        另外发的 `actions`/`corr`/`late`/`left` 是「本局」读数带的四个数，界面只需要它们的最新值，
        一条 `("status", {...})` 就够 —— 面板不必去正则化那句中文日志。未知键也照收：这条通道
        的规矩是「发什么显示什么」，多一个键只是多一格读数，不会让哪条判据变错。
        """
        extra = {}
        for token in line[len("#STATUS#"):].strip().split(";"):
            key, _, value = token.partition("=")
            if key == "phase" and value:
                self.q.put(("phase", value))
            elif key == "progress" and value:
                try:
                    self.q.put(("progress", min(1.0, float(value))))
                except ValueError:
                    pass
            elif key and value:
                extra[key] = value
        if extra:
            self.q.put(("status", extra))

    def record_round(self, tag, song, diff, rec, rc, multi=False):
        """把一轮写进 results.jsonl，返回真正落盘的记录（视图拿它渲染表格）。

        `multi` = 这一轮是激奏演出。戳由这里补一次：`run.py` 只在走完 準備 页、拿到 RESULT 行
        时才带 `multi`（`fly_extra`），而半路作废的那一轮 `rec` 是 `None` —— 没有这一笔，它会
        落到单人页那张「最近演出」上（2026-10-09 用户 m10950 要求两页各只列自己那一半）。
        """
        out = {"ts": time.strftime("%m-%d %H:%M"), "tag": tag, "song": song, "diff": diff,
               "rc": rc, "chart": self.state.get("last_chart")}
        if multi:
            out["multi"] = True
        if isinstance(rec, dict):
            out.update(rec)
        rlog.append_record(RESULTS, out)
        return out
