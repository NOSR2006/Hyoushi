"""One offset trial: anchor the clock, fire the first N notes, pause, screenshot the score.

A full LIVE is 85 s, which makes sweeping `--offset` one run at a time far too slow. Firing only
the first dozen notes and reading LIVE SCORE before the rest of the song matters turns each trial
into ~20 s, and 重试 restarts for free, so the whole sweep costs no extra stamina.
"""
import argparse

import numpy as np
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from detect import JUDGE_Y, _components, anchor_vote, frames, grab, sprite_blobs  # noqa: E402
from player import build_actions, raise_timer_resolution  # noqa: E402
from inject import to_raw  # noqa: E402
from mtouch import MTouch  # noqa: E402
from rlog import FRAMES, subdir  # noqa: E402

PAUSE_BTN = (1247, 38)
RETRY_BTN = (640, 578)      # 重试, the middle pill of the pause panel (measured y 552..606)
RETRY_OK = (790, 573)       # 重试 on the "start this LIVE over?" confirmation
SCORE_BOX = (25, 108, 185, 146)
# The judgement word (PERFECT / GREAT / GOOD / BAD / MISS) is drawn centred around (640, 445) and
# persists well over a frame, so one capture right after a burst shows what the notes did.
JUDGE_BOX = (486, 398, 794, 492)
SONG_GO = (1155, 638)       # 演出开始 on the song-select page
# 右下角那颗蓝药丸有两种**宽度**，这是 乐曲选择 与结算族唯一的几何差别（两族同高 y631..688、
# 都盖住 (1155,638)）：
#   乐曲选择的 決定   x1063..1264 / x1067..1268  ⇒ 198..202 px（三张钉住的 select 帧都一样）
#   结算族的 下一步 / 再次演出 / 领奖  x950..1230 ⇒ 245..250 px（result / rank / exp 两版 / 今天这页）
# 2026-10-20 用户 m51338 报的就是宽的那种：「模拟器里游戏当前这一画面被程序判断为乐曲选择页，但
# 实际上是结算界面分数页后的奖励页」—— 回家那趟读到 select 就 `#ATSELECT#`，游戏停在那一页上。
# 量 y632 与 y687 两行（药丸上下边缘，文字的墨从 y≈636 起，所以这两行是纯色），取宽的那个以容忍
# 上下 1~2 px 的排版偏移；两行都读不到就当窄 —— 宁可把结算族漏成 select（老行为），也不要反过来。
GO_PILL_ROWS = (632, 687)
GO_PILL_NARROW = 220        # 决定于 198..202，结算族 245..250 ⇒ 门放在中间那道缝里
RANDOM_BTN = (960, 660)     # 随机选曲 on the song-select page, same pill row as 确定. The one
#                             control here that minitouch cannot press -- drive it with adb_tap
PERFORM = (790, 611)        # 演出 on 演出前选项设置
# The two dialog pill rows, in x. Measured off real frames -- see `_dialog`.
PAUSE_PILLS = (356, 640, 923)   # 暂停面板: 终止 / 重试 / 继续
PRESET_PILLS = (502, 785)       # 两按钮弹窗（应用默认设置 关闭/OK、确认更换…）
BACK_TO_SELECT = (924, 611)  # 返回选曲 on the 演出失败 page
# 乐队确认页左上角的返回箭头：回 乐曲选择。用户 m02645（2026-10-08 14:11）说「乐队确认页左上角
# 的箭头按钮返回乐曲选择页啊，单人模式不也这样吗」—— 他说的对，实测同一格：多人页上点 (40,36)
# 1.4 s 后 screen 读作 select、read_song_select 的难度带 row 557（多人那一带），单人页是同一个
# 控件。**只有走回家的那趟按它**（`stop_at_select`）：前进的那趟这一页要按的是 自由対戦 /
# 演出开始，按了返回就等于把「开打」走成「回家」。有界 —— 按不动就回到「只观望」的老行为。
BAND_BACK = (40, 36)
BAND_BACK_TRIES = 2
# 单人选曲页左上角是**同一格**的返回箭头（2026-10-08 实测：从 演出首页 按 自由演出 进单人选曲页，
# 读出来是 row 527；在那页上按 (40,36) → 1.2 s 后 screen 读作 livehome）。但这一页上它要按**久**
# 一点：`tap` 默认 0.12 s 的接触它不认（页面一动不动、row 还是 527），0.30 s 才动。用户 m04029
# 的假设正是「误入单人选曲页就点左上角返回按钮回演出首页重新选多人模式」。
SELECT_BACK = BAND_BACK
SELECT_BACK_HOLD = 0.30
SELECT_BACK_TRIES = 2
SELECT_BACK_SETTLE = 1.4
# 乐队确认页的红 LEADER 横幅在 (640,120)±(70,16) 那一格里恒占 **0.300..0.310**（全语料 234 张
# band 帧：最小 0.300、p5 0.300、中位 0.306、最大 0.310）。门原来是 0.15，2026-10-08 15:35 的
# mp11 上撞了：**多人演出失败**那一局，排名页与结算页上同一条仪表条由绿 (`#5bc18b`) 变红
# (`#ff3737`) + 品红 (`#ff3db3`)，那一格读到 **0.158** ⇒ band 门抢在 `_mp_rank` 之前把排名页
# 读成 band ⇒ `wait_result` 等不到 result、走查死等到超时。失败局是这次才出现的新场景（mp2 /
# mp9 / mp10 都是成功局，绿条只有 0.024）。所以门提到 **0.22**：失败局 0.158 留 0.062 余量、
# 真横幅 0.300 留 0.078。方向是安全的 —— band 门漏报只会让走查读成 `other` 干等，误报才会锁死。
BAND_RED = 0.22
LIVE_START_BTN = (1155, 655)  # LIVE START on 乐队确认
# 演出开始 按下去之后页面若还停在 乐队确认，那一按就是被吃掉的：g347（00:47）与 g446（15:25）
# 两局都在这一页出现后 ~1 s 内按下，之后 540+ 次读数全是 band，150 s 到点放弃，回家那趟又按
# 了一次。补按是**有界**的，而且只在页面**连续**读成 band 时才补 —— 红 LEADER 横幅还在场，
# 说明确实是这一页，不是载入中的误读：实测一局正常的按下之后只会再多读出一两次 band 就转
# loading（g456 20:25:09 按下、20:25:10 仍是 band、20:25:10 就是 loading）。
START_RETRIES = 3             # 补按上限（加上第一次，一局最多 4 次 演出开始）
START_SETTLE = 8              # 连续 8 次读数仍是 band 才补（0.25 s 一次，约 2 s）
# `tail`（演出开始按出去之后）只观望、不按键：载入中的页面被误读成什么，通用处理就会去按那一页，
# 而重复按 演出开始 正是 a14 那 35 连按事故。但载入是短的 —— g473/g474/g475 三局从按下到进现场
# 只用 4~10 s，那一段里同一个 verdict 最长只连读 1.4 s（g473 的 options）；反过来 g471 那个读作
# finish 的页面连读了 139 s，把整局耗光（游戏自己把歌演完了）。所以 tail 只认这么长的「无进展」：
TAIL_STUCK_S = 12.0
# 这些页面的通用处理会按「开一局」的按钮（确定 / 演出 / 自由演出 / 演出开始）。tail 期间它们无
# 进展时不能交回通用处理 —— 分不清是真页还是结算页误读（结算页的蓝色 下一步 就会读成 `select`，
# 见 on_select 的 "wait"），按错就是开一局没人认过的谱，所以只能认输。
TAIL_LIVE_STARTERS = ("select", "options", "livehome", "band")
# tail **之前**的通用走查也要有同一个逃生，而且更要有：那边每一轮都在按那一页的按钮，所以
# 「同一个 verdict 连读很久」只可能是那一下按不动。2026-10-09 03:15 的 mp19 就是这个形状 ——
# 游戏在 首页→演出首页 的过场里冻住（画面逐像素静止、`input keyevent 4` 也纹丝不动），走查把
# 那一帧读成 `result` 之后在 (1080,660) 上按了 280 次，通用处理里却**只有**读不出来的页面计数
# （unknown/8），于是整局空转到 600 s 的 deadline 才报「没能走到 LIVE」，一帧证据都没留下。
# 60 s 是给「按一下、页面自己在播过场视频」留的余量（过场 4~10 s），正常走查没有任何一页会在
# 通用处理里停这么久。
WALK_STUCK_S = 60.0
# 例外只有乐曲选择页：在 `select` 上「按不动」是正常的 —— on_select 正在翻列表找谱（可能几十
# 秒），而且它自己返回 "wait" 时会把连读计数清掉，所以这一页不进上面的逃生。
WALK_STUCK_KEEP = ("select",)
HOME_LIVE_WAIT_S = 240.0      # 走回家撞进 LIVE 时最多等它唱完这么久（一首歌约 2 分钟）
FREE_LIVE = (875, 300)        # 自由演出 card on 演出首页; every other tile there is locked
LIVE_TILE = (1090, 600)       # the neon 演出 tile in the bottom-right of 首页
# ---- 多人模式开打前的四页（2026-10-08 真机录像实测，钉在 evidence/nav/mp_*.png）----
# 录像在 research/recordings/mp2（1947 帧，2.88 fps，03:22:58 起）；逐页时间轴与按钮实测记在
# tools/probes/navgates.py 的 PART 15/16 里（那是这套判据唯一被钉住的地方，别处不用再找）。
# 判据用的区域全部按那一局的真机帧量出来（x0, x1, y0, y1）：
MP_PILL_BOX = (500, 765, 543, 602)      # 判定线那一带：匹配中弹窗的药丸 / 暂停面板的宽条
MP_PBTN_BOX = (1014, 1265, 606, 691)    # 右下角大按钮：准备页的 准备（252x86，中心 1139,644）
MP_LABEL_BOX = (1040, 1120, 633, 668)   # 那个按钮上的字
MP_MID_BOX = (675, 830, 647, 698)       # 底部中间：单人结算页 下一步 的一带
MP_TOPR_BOX = (1180, 1240, 59, 91)      # 右上角：排名页自己的名次/分数
MP_BL_BOX = (14, 152, 628, 679)         # 左下角：首页/单人结算 的返回药丸；准备页上这一格是
#                                         发表情包（用户 2026-10-08）—— 只用来认页，永远不按
# 匹配中弹窗（用户 03:25:52–03:26:27 停在匹配中）：整页压暗 + 底部一条宽药丸。
MP_POPUP_LUM = 80.0
MP_POPUP_PILL = 0.85
# 准备页（五人状态 + 抽中封面 + 难度 + 右下 准备）：右下按钮与它的字都亮，整页蓝紫。
MP_PREP_PBTN = 0.25
MP_PREP_LABEL = 0.35
MP_PREP_BLUESAT = 0.5
# 右下那个按钮现在是彩色的 准备 还是灰色的 取消（用户 2026-10-08：按一下玩家就进准备状态、
# 按钮立刻从彩色的 准备 变成灰色的 取消）—— 彩色 = 还没准备（可以按），灰色 = 已经准备
# （再按就是取消准备，绝不能按）。量的是这一格里带色相的像素占比（通道极差 > PREP_BTN_SPREAD）：
# mp2/mp1 的 36 张准备页帧全在 0.66..0.91（按钮自己的呼吸两个相位都高：暗相 0.905、亮相
# 0.661），而同一格里那些灰色的页面（被 _mp_prep 误认成准备页的五人加载卡 mp_prep_b.png、
# f00483、f00484，框内均值 rgb (197,201,224)）只有 0.004..0.038 —— 0.5 这一刀两边都很宽。
# 见 research/experiments/prepsat.py。
PREP_BTN_SPREAD = 40
PREP_BTN_COLOUR = 0.5
# 匹配页 / 五人加载页：抽曲动画、封面展示、五人加载进度画的是同一套版面（特征互相重叠，
# 见 _mp_matching），所以只能给一个 verdict；这几道门把它与 商店（橙）/ 演出前选项 /
# 结算 splash（nav_stuck_finish：lbl 0.064、mid 0.096、bl 0.165）分开。
# 下限 70（2026-10-08 从 100 降下来）：匹配弹窗散开、匹配页淡入的那一帧（mp_matching_d.png，
# luma 75.1）在 100 的门外读成 `failed` —— 走页对 `failed` 的动作是按 返回选曲（924,611），
# 正好把刚匹配上的一局取消掉。70 的门外那一帧被收进来，而 匹配中弹窗（54.8..61.5）与
# 暂停面板（43.3）仍在门外；4197 张真帧重扫，多出来的是 22 张 live 帧（先被 _magenta_lines
# 抢走，screen 不变）与两张同类过渡帧，evidence/nav 仍是零命中。
MP_LOBBY_LUM = (70.0, 170.0)
MP_LOBBY_PBTN = 0.05
MP_LOBBY_LABEL = 0.03
MP_LOBBY_MID = 0.03
MP_LOBBY_BL = 0.15
MP_LOBBY_CYAN = 0.06
MP_LOBBY_BLUESAT = 0.30
# 排名页（五人名次 + 分数，等 下一步）：底部中间没有 下一步、左下角没有返回药丸。
MP_RANK_MID = 0.30
MP_RANK_TOPR_LUM = 120.0
MP_RANK_PILL = 0.20
MP_RANK_PBTN = 0.15
MP_RANK_BL = 0.06
# 这几页和载入一样：页面自己在走，没有一个「往前走」的按钮该按（准备页那个按钮按两下
# 就是取消准备，所以只在它还是彩色的时候按一下，见 start_live 的 prep 分支）。
MP_QUIET_PAGES = ("matchpopup", "prep", "matching")
# 多人链路（用户 2026-10-08 的录像 + 口述）：演出首页 → 右方 激奏演出 → 乐曲选择（与单人同一页）
# → 确定 → 乐队确认（右下按钮文案变 自由对战，位置与单人 演出开始 同一个键）→ 匹配中弹窗 →
# 抽曲/封面/五人加载（都读 matching）→ 准备页（右下 准备：按一次进准备状态，再按一次取消准备）
# → 全游戏载入 → 现场。歌照打，曲终先出 排名页（rank）再进单人结算流程。
# 演出首页右方那张 激奏演出 瓦片：真机实测它的可点区在右下（2026-10-08 05:3x，游戏停在演出首页）——
# 点 (1150,270) 与 (1130,345) 都毫无反应，点 (1140,500) 立刻进 乐曲选择。瓦片本身的紫色亮块实测
# x1021..1264 y458..567，那两行文字在 y480..520 / x1090..1190，所以取它的中心。
MULTI_LIVE_TILE = (1140, 505)
MULTI_PREP_BTN = (1139, 644)      # 准备页右下 准备（实测按钮 x1014..1265 / y606..691）
MULTI_PREP_TRIES = 2              # 最多按两下：第二下只在按钮**还是彩色**时允许（见下面的 prep 分支）
MULTI_PREP_SETTLE = 1.2           # 按下之后至少等这么久，再看那一下有没有把按钮变成灰色的 取消
MULTI_WALK_TIMEOUT_S = 600.0      # 匹配 + 等另外四个人准备 + 载入，比单人的 150 s 长
# 匹配中弹窗在 mp2 上停了 34.9 s（帧一动不动，没有任何「往前走」的按钮），房间配不到人时它可以
# 永远停在那里：mp8 在那一页上停了 15 分钟，走查零按键等到自己的 deadline，整局判掉，回家也没
# 走成。那个静态药丸是**取消这次匹配**（2026-10-08 实测：点它的中心 1.5 s 后回到 乐队确认页），
# 所以等够 MULTI_MATCH_WAIT_S 就取消一次，让走查回去再按一次 自由対戦（`band` 分支会按，受
# START_RETRIES 限制），最多取消 MULTI_MATCH_TRIES 次。deadline 因此抬到 600 s。
MULTI_MATCH_WAIT_S = 120.0        # 一页匹配中弹窗等这么久还没动就取消它（mp2 实测正常是 34.9 s）
MULTI_MATCH_TRIES = 2             # 最多取消几次（之后交给走查的 deadline，不再动那一页）
MP_PILL_CENTRE = ((MP_PILL_BOX[0] + MP_PILL_BOX[1]) // 2,
                  (MP_PILL_BOX[2] + MP_PILL_BOX[3]) // 2)   # (632, 572)：匹配中弹窗那个药丸
# 单人局读到「匹配中弹窗」：单人**没有**匹配这回事（匹配只在激奏演出里），所以那个 verdict 只
# 可能是「盖在结算页上的弹窗」被 `_mp_matchpopup` 抢走。用户 m10037（2026-10-09）报的故事解锁
# 弹窗就是它：整页压暗 + 底部一颗居中的亮药丸，而它的 关闭 正是那颗药丸（= STORY_CLOSE）。
# 整库 476 张全尺寸帧的普查（research/experiments/mphits.py，2026-10-09）—— 最终 verdict 是
# matchpopup 的只有 15 张：11 张是多人匹配弹窗（mean 61.8..65.1、`_story_close` True、亮组恰好
# 一颗 (514,252)）与 3 张这一页（mean 50.67、`_story_close` False、亮组三颗），**没有第三种页面**。
# 而 `_story_close` 对它是 False（底部那一带今天有三组亮列，判据要求恰好一组），所以「把
# `_story_close` 挪到 `_mp_matchpopup` 前面」修不了它 —— 它必须由模式（单人/多人）认出来。
# g508（16:46:33）就卡在这里：matchpopup 在 MP_QUIET_PAGES 里，走查只看不按，45 s 后报
# 「没能走回选曲页」，游戏留在弹窗上（g209 2026-10-01 与 g488 2026-10-08 那两局读到的是 story，
# 所以走查按了 关闭 就走了 —— 「以前可以」是这个原因）。
SOLO_MODAL_TRIES = 2              # 单人局在这一页上最多按几下那颗药丸（第二下是没落地时的补按）
SOLO_MODAL_SETTLE = 1.2           # 按下之后至少等这么久，再看这一页有没有走
# 加成火力 on 乐队确认: the bright `cur/cap` readout above the white pill in the top-right corner.
# White ink on a dark chip, so `min(RGB) > 190` plus a flat channel spread picks the glyphs.
# The glyphs are found per frame instead of through frozen x-windows: the whole readout slides
# 4..5 px between frames (the saved 乐队确认 frame under evidence/nav sits 4 px right of the live
# one, and the old frozen windows read it as nothing at all), and a two-digit current grows
# leftward -- a right-aligned second digit lands around x1046, i.e. inside FIRE_BAND_X and clear
# of the `/` at x1071. FIRE_BAND_X is also clear of the chip's own white left edge (x1007..1008)
# and of the white block right of the readout (x1136+), so only the readout's ink is in it.
# One read of the whole line is not possible: the `/` is classified as a `7` at distance 103..110,
# past `resultread.CONFUSION_MAX` (95), so the line comes back `7?15` and `_num` refuses it.
# Instead the band is split at the slash -- the one run that leans right at the top -- and each
# half goes to the shipped `judge` reader. No new templates, no OCR.
FIRE_Y = (24, 46)             # the readout's line; its glyph ink measures y27..43
FIRE_BAND_X = (1035, 1125)    # where the ink runs are looked for; the readout itself is x1058..1103
FIRE_MASK = 190               # min(RGB) above this is ink
FIRE_FLAT = 60                # (max-min) below this is white text, not a colour chip
FIRE_MIN_H = 12               # glyph height floor: the digits measure 16..17
FIRE_SLASH_W = 10             # the '/' measures 6 px; digits run 6..10, so this only drops noise
FIRE_SLASH_LEAN = 2           # px the run's top third must sit right of its bottom third
FIRE_MAX_W = 12               # widest single glyph; a wider run gets cut and verified by read_cell
FIRE_DIGITS = (2, 3)          # digits allowed either side of the slash: (current, cap)
# 消耗LB（加成火力档位）弹窗 —— 乐队确认页 LIVE START 左边那枚按钮打开的四档选择器（用户 m26442）。
# 真机实测 2026-10-11（1280×720，MuMu）：
#   按钮 (922, 660)；弹窗四行（自上而下 3/2/1/0 档）中心 y = 124 / 180 / 236 / 292，行横跨
#   x 303..951；OK 按钮 x 516..768 / y 629..688 → 中心 (642, 658)。
# 四行都是圆角条：未选中铺深蓝 (56,63,116)、选中的那一行铺青色 (~(56,100,108))，两者的差别不在
# 亮度上而在通道关系上 —— `b - r` 判是不是行条（深蓝 51 / 青 44 / 弹窗底 26），`g - b` 判选中
# （青 -8 / 深蓝 -47）。整个弹窗由三个特征一起认：四行都在 + 恰好一行是青的 + OK 那颗亮蓝按钮
# 就在 (642,658)。**必须抢在 `select` 之前问**：实测弹窗开着时 `_blue(*SONG_GO)` 会把它读成
# 乐曲選択页（弹窗没有盖住乐队确认页右侧的 LIVE START），走查于是会去按 決定。
# 这扇门从前是「读数不足就停在确认页每 20 秒重读、不设上限」（加成火力约每 20 分钟回复 1 点，
# 从 0 攒到 3 是一小时量级）—— 用户 m26442 要的正是别再等：按读数把档位拨过去，然后照常开打。
LB_BTN = (922, 660)            # 乐队确认页的 消耗LB
LB_OK = (642, 658)             # 弹窗底部的 OK
LB_ROW_X = 627                 # 四行共同的点击 x（行横跨 303..951）
LB_ROW_Y = {3: 124, 2: 180, 1: 236, 0: 292}
LB_ROW_BANDS = ((104, 144), (160, 200), (216, 256), (272, 312))
LB_ROW_LEVELS = (3, 2, 1, 0)   # LB_ROW_BANDS 自上而下的档位
LB_ROW_XBAND = (340, 900)      # 判色用的横带（避开行两端的圆角与图标）
LB_ROW_BLUE = 35               # b - r 高于这个才算「行条」：深蓝 51 / 青 44 / 弹窗底 26
LB_ROW_TEAL = -25              # g - b 高于这个 = 选中的那一行：青 -8 / 深蓝 -47
LB_OK_BOX = (520, 630, 764, 686)   # OK 按钮的框；判它自己的亮蓝（实测 0.974，非弹窗帧最高 0.656）
LB_OK_BLUE = 0.60
LB_LEVEL_HIGH = 3              # 火力够时用的档位：消耗 3 点，奖励 ×15
LB_LEVEL_LOW = 0               # 火力不够时用的档位：消耗 0 点，奖励 ×1（不烧火）
LB_SETTLE_S = 0.9              # 按一下之后等画面
LB_TRIES = 2                   # 开弹窗 / 换档 / 关弹窗各自的重试上限
# 首页's three opaque blue round buttons: the two 「+」 pills on the resource bar and the 「≡」
# menu disc top-right. They are chrome with solid fills, so event artwork behind them cannot tint
# them -- unlike the translucent RANK plate the old cue read (see `_home`).
HOME_DISCS = ((36, 62, 500, 534), (36, 62, 1132, 1166), (20, 64, 1208, 1256))
HOME_DISC_BLUE = 0.55         # blue fraction inside a disc box: 0.76 / 0.73 / 0.79 on 首页
HOME_LABEL = (633, 668, 1040, 1120)   # the white 演出 word on the bottom-right neon tile
HOME_LABEL_WHITE = 0.20       # its own share of near-white pixels, measured 0.285
MODAL_CLOSE = (640, 655)      # 关闭 on a full-screen modal -- the only thing here worth tapping
# 到达 乐曲選択 之后，游戏还可能自己把 达成奖励列表 盖上来（2026-10-19 用户：连续演奏打完最后一局，
# 游戏停在「显示奖励的那一页」）。走查原本读到 `select` 就 return，那之后再盖上的弹窗就没人关 ——
# 下一局会把它当 rewards 关掉，可最后一批就停在那儿。所以到达之后再看几眼，只认 `_reward` 与
# `_bond_detail`（这一页上唯一合法的是底部那枚浅色 关闭，任何奖励格子都不碰）。
REWARD_OVER_SELECT_TRIES = 3    # 再看几眼
REWARD_OVER_SELECT_SETTLE = 1.0  # 每眼之间隔多久（秒）
# _bond_detail's two gates, as constants so tools/probes/navgates.py can pin them off and show
# what each one is holding back.
BOND_MERGE_PX = 20            # pale columns chain at 60 px behind the modals, but the blurred
                              # artwork behind 羁绊奖励详情 reaches the pill that way (605 px run)
BOND_TITLE_MIN = 1600         # white pixels in the title box: 1862 on the popup, 1413 the most
                              # any other committed frame reaches (the 结算 page's own header)
STORY_CLOSE = (644, 571)      # 关闭 on the 故事解锁 modal, which sits a row higher than MODAL_CLOSE
EXP_RETRY = (1104, 655)       # 再次演出 on the post-result 结算 page: re-selects this song
PURCHASE_CANCEL = (497, 664)  # 取消 on a 确认购买 dialog: the only tap on it that spends nothing
SHOP_HOME = (166, 41)         # the house icon in the 商店 header: the way out of the store
RANKUP_OK = (642, 652)        # OK on the 羁绊/玩家等级 RANK UP splash -- where a modal's 关闭 sits
SPLIT_TOGGLE = (1216, 398)    # the ⇄ beside the judgement rows: splits each one into FAST / SLOW


def _orange_px(a):
    return (a[:, :, 0] > 195) & (a[:, :, 0] - a[:, :, 2] > 65) & (a[:, :, 0] - a[:, :, 1] > 40) \
        & (a[:, :, 1] > 120)


def _purchase(img):
    """A 确认购买 dialog: 取消 on the left, an orange 购买 on the right, in the bottom row.

    Nothing on this page may ever be tapped except 取消. It is reached from the store, whose
    tiles open it, so it is the one screen where a mis-aimed tap costs real money.
    """
    right = img[640:690, 660:905].reshape(-1, 3).astype(int).mean(0)
    left = img[640:690, 375:620].reshape(-1, 3).astype(int).mean(0)
    return bool(right[0] > 220 and right[0] - right[2] > 70 and left.min() > 190)


def _shop(img):
    """The 商店, which is a wall of 购买 pills: two rows of 246x36 orange, four to a row.

    Its tiles lead to 确认购买, and its tab column leads to more tiles, so the walk leaves the
    moment it sees one. 5k orange pixels in one of the two pill rows is a threshold the largest
    non-store orange mass in the corpus (再次演出 on 结算, ~2.6k) sits well under.
    """
    a = img.astype(int)
    o = _orange_px(a)
    return int(o[335:378].sum()) > 5000 or int(o[662:704].sum()) > 5000


def _mean(img, x, y, w=30, h=12):
    return img[y - h:y + h, x - w:x + w].reshape(-1, 3).astype(int).mean(0)


def _livehome(img):
    """演出首页, by its two side-by-side stage cards.

    Turning off 演出前选项设置 put this page between the main menu and song select, and every
    other tile on it (激奏舞台, 课程演出, the bottom one) is padlocked, so 自由演出 is the only
    way forward. Neither card colour is distinctive alone -- half the corpus has one of them --
    but blue on the left next to purple on the right only ever occurs here.
    """
    f, s = _mean(img, 900, 300), _mean(img, 1113, 300)
    return (f[2] > 100 and f[2] - f[0] > 40 and f[2] - f[1] > 25
            and s[0] > s[1] and s[2] > s[1] and (s[0] + s[2]) / 2 - s[1] > 20)


def _lines_core(a):
    """The old single look: a row that is majority *strict* magenta anywhere on the field."""
    a = a.astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = (r > 150) & (b > 150) & (g < 110)
    return bool((m[:, 250:1030].mean(1) > 0.5).any())


def _lines_band(a):
    """The judgement-line band by hue rather than by colour, at the two rows the lines live on."""
    s = a[535:605, 250:1030].astype(int)
    r, g, b = s[..., 0], s[..., 1], s[..., 2]
    m = (r > 120) & (b > 120) & (b - g > 25) & (r - g > 10)
    return bool((m.mean(1) > 0.90).any())


def _magenta_lines(a):
    """True where the two judgment lines are on screen -- by either of two looks at them.

    The pause overlay dims everything behind it, so a paused field fails both, which is why the
    pause panel is found by its own pills in `_dialog` instead. What this still gates is the 暂停
    tap itself: 1247,38 is 达成奖励列表 on the result page and a claimable tile elsewhere, so it is
    only tapped while the field proves itself up.

    One look was not enough. The strict core colour alone (what this used to be) fires on 120 of
    the 188 frames the HUD watcher committed *inside a LIVE*: a skill glow or a hit flash washes
    half of a line and that row drops under half magenta. `screen` then answers 'options' /
    'story' / 'rewards' for a field that is plainly up, the pause tap is refused, and
    断AP立即重试 -- which enters through this gate -- has lost every one of its twelve attempts
    (g238's four saved frames all read 'other'). The band hue test, the one `_magenta_back` was
    written for, fires on 176 of those 188 and on 0 of the 30 non-live frames in `evidence/nav`;
    the union on 178 and still 0. The ten frames neither catches are the ones a full-screen effect
    owns, which is why `in_live` samples the question instead of asking it once.
    """
    return _lines_core(a) or _lines_band(a)


def _magenta_back(img):
    """Is the field painted? The band look, on its own -- this one is a timing instrument.

    Rows 535..605 hold the two judgement lines (542..598) and the x range is the field's own
    width there, so this answers "field is up" without letting any other page's magenta -- 首页
    tiles, song-select art -- vote. The hue-only predicate (r,b>120 with b-g>25, r-g>10) measured
    >=0.968 on every one of the 25 field frames checked then and 0.00 on result pages, and across
    research/archive/media/retry_probe1.mp4 it reads 1.00 the frame the restarted field is painted
    -- two frames after 0.02 under the black fade. Threshold 0.90: live frames keep 0.068 of margin,
    and the only transition frames that ever crossed it (0.88, as the pause scrim fades in) belong
    to the pause OPEN, before any 確定.

    Used to stamp `[field back up]` after a 重试 restart: the lines vanish under the pause scrim
    and are the first thing back when the restarted field is drawn. It stays the band alone, and
    not `_magenta_lines`' union, because that stamp is a latency measurement -- a second way to
    answer would be a second way to be early.
    """
    return _lines_band(img)


def in_live(polls=5, wait=0.12):
    """True only when the two magenta judgment lines are on screen.

    Every other screen has a button at the top-right corner, and 1247,38 is 达成奖励列表 on the
    result page, so the pause tap has to be gated on positively seeing the playfield.

    Sampled, because the gate is a colour test on a screen that is on fire: a full-screen effect
    washes the lines out for a frame or two (`_magenta_lines` still misses 10 of 188 live frames),
    and the next grab is usually clean. The refusal is what costs a round, so it gets the benefit
    of the doubt for `polls` grabs and never taps on a guess.
    """
    for k in range(polls):
        if _magenta_lines(grab()):
            return True
        if k + 1 < polls:
            time.sleep(wait)
    return False


# 多人开场盖章：判定线要连续画着这么久才算「真的回来了」（见 `field_back_up`）。
FIELD_STABLE_S = 1.0
FIELD_POLL_S = 0.15
FIELD_WAIT_MAX_S = 40.0


def field_back_up(log=print, stable=FIELD_STABLE_S, poll=FIELD_POLL_S, limit=FIELD_WAIT_MAX_S):
    """Stamp the moment the field is *really* up: the first frame of a run of painted ones.

    `start_live` returns on the first frame that reads 'live' and its caller stamps t0 off that
    frame. In a 多人 room one frame is not enough. mp2's recording (0080_03 expert, note 1 at
    3.28 s) shows the judgement lines painted at 181.27 s, then covered by the 等待其他玩家 scrim for
    4.4 s -- band 0.006, `screen` answering 'other' -- and painted again at 186.05 s, with the notes
    only starting to fall 2.7 s after that. A walk that samples the 181.27 frame stamps t0 4.8 s
    early and the tight anchor window (`field_seen - 1.2 .. field_seen + 0.6`) lands on the scrim.

    The four real rounds got away with it: their stamps sit at chart 0 (mp5 stamped 12:46:23 and
    locked 12:46:27 at chart +3.386 s, mp7 13:17:21/13:17:26 at +4.889 s, mp3 +7.042 s, mp4
    +6.307 s). How long the room waits depends on how fast the other four load, so it is a matter of
    time, not of luck.

    Same instrument as the 重试 stamp -- `_magenta_back`, the band alone -- because that one is a
    latency measurement and a second way to answer would be a second way to be early. What comes
    back is the first frame of the stable run, not the frame that confirmed it, so the anchor window
    still holds the moment the lines came back.
    """
    t_first = None
    end = time.perf_counter() + limit
    while True:
        t, img = frames()
        if _magenta_back(img):
            if t_first is None:
                t_first = t
                log(f"  开场：判定线画出来了，等它连着画满 {stable:.1f} s 再盖章")
            elif t - t_first >= stable:
                log(f"  开场：判定线连着画了 {t - t_first:.2f} s 没断 -> t0 盖在这一段的第一帧")
                return t_first
        elif t_first is not None:
            log(f"  开场：判定线又没了（只画了 {t - t_first:.2f} s）—— 那一下是虚的，重新等")
            t_first = None
        if time.perf_counter() > end:
            log(f"  !! 开场：等了 {limit:.0f} s 也没等到判定线连着画满 {stable:.1f} s —— 就按这一帧盖章")
            return t
        time.sleep(poll)


def pause_if_live(inj, log=print):
    """Tap the top-right pause corner if a LIVE is up (fires; it does not confirm).

    **Only the solo LIVE has that corner.** 2026-10-10 用户 m13106：多人（激奏演出）房间里
    匹配完毕那一刻唯一的提前退出是关掉游戏进程，LIVE 界面上没有暂停按钮 —— 所以 `--multi`
    的调用方一律不许走到这里（`run.py` 的 `_to_t0` 与 no-pick 两条路都已按 `args.multi` 分流）。
    """
    if not in_live():
        log("  not in a LIVE (no judgment lines) - refusing to tap the top-right corner")
        return False
    tap(*PAUSE_BTN, i=inj)
    time.sleep(1.5)
    return True


def _blue(img, x, y):
    p = img[y - 12:y + 12, x - 30:x + 30].reshape(-1, 3).mean(0)
    return p[2] > 170 and p[2] - p[0] > 60


def _go_pill_wide(img):
    """右下角那颗蓝药丸是不是结算族那颗宽的（乐曲选择的 決定 是窄的）。

    两族的颜色、高度、位置全都一样 —— 只有宽度分得开（见 `GO_PILL_ROWS` 上方的量测）：決定
    198..202 px，下一步/再次演出/领奖 245..250 px。判据只看那一行的蓝色连续段，所以它既不依赖
    文字（y632/y687 在墨的上下两侧），也不依赖任何版面元素。

    读不到蓝（淡入、淡出、被弹窗盖住）时返回 False：调用方 `screen()` 里 `select` 要的是
    `_blue(*SONG_GO) and not _go_pill_wide()`，而这个函数只用来**否决** select 与**认领** exp，
    所以失败方向必须是「不算宽」—— 漏认只会退回 2026-10-19 之前的老行为，误认则可能把真正的
    乐曲选择页叫成 exp，让走查在那一页上按 (1104,655)（= 选曲页的 決定 左边一截）。
    """
    x = 1140                       # 两族药丸都盖住这一列
    widest = 0
    for y in GO_PILL_ROWS:
        row = img[y].astype(np.int16)
        m = (row[:, 2] > 170) & (row[:, 2] - row[:, 0] > 60)
        if not m[x]:
            continue
        x0 = x
        while x0 > 0 and m[x0 - 1]:
            x0 -= 1
        x1 = x
        while x1 < len(m) - 1 and m[x1 + 1]:
            x1 += 1
        widest = max(widest, x1 - x0 + 1)
    return widest > GO_PILL_NARROW


def _frac(img, pred, x, y, w, h):
    p = img[y - h:y + h, x - w:x + w].reshape(-1, 3).astype(int)
    return float(pred(p).mean())


def _red(a):
    return (a[:, 0] > 150) & (a[:, 1] < 80) & (a[:, 2] < 80)


def _white(a):
    return a.min(1) > 150


def _ink(a):
    return a.mean(1) < 120


def _loading(img):
    """The 演出 load's interstitial: a full-bleed pale card with a NOW LOADING bar.

    It wears the same top-right corner the 结算 rank badge sits in, and the result test only asks
    whether that box is bright -- a pale background answers that better than a badge does (white
    1.00 / ink 0.00 on both dumps of this page, against white 0.16..0.32 with ink 0.21..0.49 on
    all 349 real result and split frames in the corpus). The badge's dark letter is the
    difference, and the walk used to spend four taps' worth of waiting on the load because of it.
    """
    return (_frac(img, _white, 1180, 75, 60, 16) > 0.9
            and _frac(img, _ink, 1180, 75, 60, 16) < 0.02)


def _finish(img):
    """The LIVE FINISH rank splash, by its huge pale-blue title.

    It is a full-screen page with no controls on it, so a tap anywhere advances -- but only
    after positively seeing it, because tapping blind on an unknown page is how a state machine
    wanders into 达成奖励. "Bright area up here" was enough to claim this page until a run tapped
    its way from the store's pink card art into a 确认购买 dialog through it; the title's own
    colour is what tells the splash from artwork, and the splash is 0.33 of the band against at
    most 0.13 for anything else in the frame corpus.
    """
    a = img[100:210, 310:975].astype(int)
    return float(((a.min(2) > 165) & (a[:, :, 2] >= a[:, :, 0])).mean()) > 0.22


def _home(img):
    """The main menu, which is where a 演出失败 or a finished LIVE eventually drops back to.

    Three opaque blue round buttons (the resource bar's two 「+」 and the top-right 「≡」) plus the
    white 演出 word on the bottom-right tile. The cue before this one read the translucent RANK
    plate at the top left, and a plate is only as stable as the artwork behind it: the 2026-10-01
    home screen (a sunset chain-link fence) warmed its |R-B| to 25.5 against a gate of <25, so
    首页 stopped reading as 首页 -- and because `_shop` only counts orange pixels in two bands and
    that frame carries 7894 and 7304 against a gate of 5000, it read as 商店, a page whose only
    action is a tap at SHOP_HOME. Chrome cannot be repainted by an event; artwork can.

    Measured over every full-size frame on disk (1874): 首页 hits 3/3 discs at 0.76 / 0.73 / 0.79,
    and exactly one other frame hits 3/3 -- a 乐队确认 frame, which the band test claims first.
    Two of three is not enough: at that level 42 frames would flip, 26 of them live-field frames.

    2026-10-09: the 演出首页 grew the same white word in that bottom-right box (0.431 tonight
    against 0.000 in the 2026-10-08 05:3x fixture), so 首页 started claiming the 演出首页 -- and
    `screen()` asks `_home` (line 844) before `_livehome` (line 879), so the walk pressed 首页's
    演出 tile (LIVE_TILE) on the 演出首页 and fell into a page it cannot read (mp19, 03:43 and
    03:14, both rounds lost).  Every other cue is shared with the 演出首页 (discs 1.00/0.86/0.79,
    the two mode cards at y300), so the split has to come from `_livehome`.  `homescan.py` walks
    the 3233 full-size frames on disk with both versions of this function: 17 frames move, every
    one of them `home` -> `livehome`, and all 17 are 演出首页 frames captured tonight -- the
    2026-10-08 fixtures, the mp2 recording, every 结算 and research frame are untouched, and the
    real 首页 never claims both.  (The 177 frames where `_livehome` fires are that page plus
    live-field frames that `_home` already rejected.)
    """
    a = img.astype(int)
    discs = sum(1 for y0, y1, x0, x1 in HOME_DISCS
                if ((a[y0:y1, x0:x1, 2] - a[y0:y1, x0:x1, 0]) > 40).mean() > HOME_DISC_BLUE)
    y0, y1, x0, x1 = HOME_LABEL
    return (discs == len(HOME_DISCS)
            and (a[y0:y1, x0:x1].min(2) > 170).mean() > HOME_LABEL_WHITE
            and not _livehome(img))


def _reward(img):
    """The 达成奖励列表 modal, which the game opens by itself over the result page.

    It is a hazard, not just a nuisance: every tile in it claims an item, so the walk has to see
    it and leave by 关闭 alone. The EXPERT tab of its COMBO row is the only bright orange thing at
    that height, and the 关闭 pill below it is bright and neutral on every page that has one.
    """
    tab = img[348:372, 1035:1145].reshape(-1, 3)
    close = img[637:673, 600:680].reshape(-1, 3)
    return ((tab[:, 0] > 170).mean() > 0.5 and tab[:, 0].mean() - tab[:, 2].mean() > 60
            and close.min(1).mean() > 140)


def _modal_close(img):
    """Any full-screen modal whose only exit is the bottom-centre 关闭 pill.

    羁绊奖励详情 appears in the same post-result walk as 达成奖励列表 and strands the walk the
    same way, and 关闭 sits at the same spot on both. The pill is 250 px of pale across the middle
    with the dark word 关闭 split into it, so it is measured as one run of that width rather than
    as "something bright near the centre" -- which is what the home page's bottom bar answers to,
    and tapping its 关闭 coordinate on 首页 lands on the 商店 tile 20 px away.
    """
    col = (img[645:670, :].min(2) > 110).mean(0) > 0.5
    groups, start = [], None
    for x in range(len(col)):
        if col[x] and start is None:
            start = x
        elif not col[x] and start is not None:
            groups.append((start, x - start))
            start = None
    if start is not None:
        groups.append((start, len(col) - start))
    merged = []
    for s, w in groups:
        if merged and s - (merged[-1][0] + merged[-1][1]) < 60:
            merged[-1] = (merged[-1][0], s + w - merged[-1][0])
        else:
            merged.append((s, w))
    # 羁绊奖励详情 and 结算宽 both draw things left of the pill that merge into it, so the range
    # has to take a merged run of ~406 -- and the filter is what keeps 首页 out, whose longest run
    # through x=644 is its 招募 label at 73 px. The other runs through x=644 in the corpus are the
    # purchase dialog's (536), 乐曲详情 (532) and 首页's bottom bar (584+), all safely wider.
    return any(s <= 644 <= s + w and 180 <= w <= 420 for s, w in merged)


def _bond_detail(img):
    """羁绊奖励详情, the scrollable variant, which floats over a *blurred* still of the song art.

    Its 关闭 is the same pale pill the other modals use, but the artwork behind the panel is
    bright enough to chain into the pill's run at the 60 px gap `_modal_close` merges across: the
    first frame of this page measured one 605 px run through x=644, the width cap refused it, and
    two walks then sat on the page until they gave up (start_live_stuck.png, then
    nav_stuck_other.png, 2026-09-30). Merging only across <20 px gaps keeps the artwork out and
    leaves the pill's own run at 293 px -- the 关闭 ink inside it is what splits the pale columns,
    at 2 px.

    Narrowing the merge is what makes the second gate necessary: 首页's bottom bar, whose run
    through x=644 is 584 px and "safely wider" at the old gap, could break into a 180..420 px
    piece here. The title settles it -- 1862 white pixels in the top-centre box, where the 结算
    page's own white header tops out at 1413 across all 695 committed frames.
    """
    col = (img[645:670, :].min(2) > 110).mean(0) > 0.5
    groups, start = [], None
    for x in range(len(col)):
        if col[x] and start is None:
            start = x
        elif not col[x] and start is not None:
            groups.append((start, x - start))
            start = None
    if start is not None:
        groups.append((start, len(col) - start))
    merged = []
    for s, w in groups:
        if merged and s - (merged[-1][0] + merged[-1][1]) < BOND_MERGE_PX:
            merged[-1] = (merged[-1][0], s + w - merged[-1][0])
        else:
            merged.append((s, w))
    if not any(s <= 644 <= s + w and 180 <= w <= 420 for s, w in merged):
        return False
    title = img[18:50, 562:720].reshape(-1, 3)
    return int((title.min(1) > 175).sum()) > BOND_TITLE_MIN


def _story_close(img):
    """The 故事解锁 modal, which the game opens by itself when a LIVE unlocks a 羁绊故事.

    達成奖励列表 and 羁绊奖励详情 both put their 关闭 in the [637:673] band, but this modal's pill
    sits a row higher, so it slipped past and stranded the walk on an unreadable screen. Telling it
    from the other thing with a bright button at this height -- the 暂停 panel -- needs shape, not
    brightness: the pause panel draws three buttons across the band and this modal draws one wide
    pill, so exactly one contiguous bright group is the modal and nothing else in the corpus is.
    The story card in the middle of this modal is never tapped, only this pill.
    """
    col = (img[552:596, :].min(2) > 110).mean(0) > 0.5
    groups, start = [], None
    for x in range(len(col)):
        if col[x] and start is None:
            start = x
        elif not col[x] and start is not None:
            if x - start > 15:
                groups.append(x - start)
            start = None
    if start is not None:
        groups.append(len(col) - start)
    return len(groups) == 1 and groups[0] >= 180


def _exp_cards(img):
    """The five member cards' EXP bars: five wide cyan runs on one 248 px pitch.

    This is what the 结算 EXP page *is*, and it is identical in both layouts the game ships -- the
    one with 主页/再次演出 and the one with 详情/下一步 (measured: bars at x 45-251, 293-499,
    541-747, 789-995, 1037-1243 in all four frames of the two layouts; no other frame in the
    corpus paints more than three).
    """
    b = img[480:520]
    m = (b[:, :, 1] > 200) & (b[:, :, 2] > 200) & (b[:, :, 0] < 140)
    xs = np.flatnonzero(m.any(axis=0))
    if xs.size == 0:
        return False
    segs = np.split(xs, np.flatnonzero(np.diff(xs) > 12) + 1)
    return int(sum(1 for s in segs if s.size >= 40)) == 5


def _exp_page(img):
    """The post-result pages that wear 乐曲选择's blue pill: the EXP cards page and the totals page.

    Both are interposed by a 絆 rank-up and both put a pale-blue pill exactly under 确定's colour
    probe at (1155, 638), so a walk that cannot name them calls them 乐曲选择 -- and 随机演奏 then
    waits for a jacket the page does not have. Two features claim them, and neither alone covers
    both: the five member cards' EXP bars (`_exp_cards`, both layouts of that page), or the pale
    主页 button beside the pill (the totals page, which has no cards). The pill itself is required
    either way, because it is what `EXP_RETRY` presses -- 再次演出 on the totals page, 下一步 on
    the cards page, and both land back on 乐曲选择 through a LIVE BOOST tip any tap dismisses.

    A third layout joined them on 2026-10-20 (user m51338: the 奖励 page the game shows after the
    score page, which the walk called 乐曲选择 and stranded on): it has neither cards nor a 主页
    button, but its pill is the **wide** one, which `_go_pill_wide` names on its own -- 決定 on
    乐曲选择 is ~200 px and every pill of this family is ~250 px. That anchor is also what lets
    `screen` refuse to call this page `select`, so the walk presses 下一步 here instead of
    declaring itself home.

    Orange on the older build, pale blue on every current frame. Only meaningful after the result
    test claims 结算: its pale 达成奖励 button sits in the very same box.
    """
    r = img[646:674, 1030:1150].reshape(-1, 3).mean(0)
    orange = r[0] > 200 and r[1] > 120 and r[2] < 160 and r[0] - r[2] > 60
    blue = r[2] > 190 and r[2] - r[0] > 40
    if not (orange or blue):
        return False
    l = img[646:674, 760:880].reshape(-1, 3).mean(0)
    return _exp_cards(img) or bool(l[2] > 190 and l.min() > 150) or _go_pill_wide(img)


RANKUP_TITLE_TOP = (120, 170)     # 羁绊 UP's pale-green title
RANKUP_TITLE_LOW = (240, 290)     # 玩家等级 UP's, same text 120 px lower
RANKUP_GREEN_MIN = 2500
RANKUP_PILL = (200, 300, 40, 80)  # the OK pill's (w min, w max, h min, h max); measured 252 x 60


def _rankup_title(img, band):
    """The splash's pale-green title, counted in one of its two known bands."""
    y0, y1 = band
    a = img[y0:y1, 530:760]
    g = (a[:, :, 1] > 150) & (a[:, :, 1] - a[:, :, 0] > 20) & (a[:, :, 1] - a[:, :, 2] > 10)
    return int(g.sum()) > RANKUP_GREEN_MIN


def _rankup_pill(img):
    """The splash's OK pill as (cy, cx), or None.

    Blue at that height is not rare -- the live field glows with it -- so the shape is what
    separates them: a blob 200..300 px wide and 40..80 tall, near the centre column of the lower
    half. The live field's band is one unbroken run hundreds of px wide.
    """
    b = (img[:, :, 2] > 190) & (img[:, :, 2].astype(int) - img[:, :, 0].astype(int) > 40)
    reg = np.zeros_like(b)
    reg[460:700, 380:900] = b[460:700, 380:900]
    wlo, whi, hlo, hhi = RANKUP_PILL
    best = None
    for cy, cx, _npx, w, h in _components(reg):
        if abs(cx - 643) > 60 or not (wlo <= w <= whi and hlo <= h <= hhi):
            continue
        if best is None or abs(cy - 570) < abs(best[0] - 570):
            best = (cy, cx)
    return best


def _rankup(img):
    """The 羁绊 RANK UP splash, which the game drops between the rewards and the 结算.

    Its OK sits where every modal's 关闭 sits, but the pill cannot be found the way those are:
    the splash is drawn over two full-height character illustrations, so the bright band through
    the middle is one unbroken run and every width test fails. The pale-green RANK UP title is
    the way in -- it is 4000 green pixels inside a 230x50 window, and the nearest other page in
    the corpus (a song-select frame whose difficulty chip clips the window edge) reaches 1700.

    The 玩家等级 splash paints the same title 120 px lower and is handled by `_level_rankup`,
    later in `screen` -- after the modal tests, which is what keeps the result page's split view
    (green histogram bars in that same band, and the game's standard 252x60 pill 110 px lower)
    reading "rewards".
    """
    return _rankup_title(img, RANKUP_TITLE_TOP)


def _level_rankup(img):
    """The 玩家等级 RANK UP splash: the same title one layout down, plus its own OK pill.

    The lower band is where the live field's notes sit, so the title alone is not enough --
    measured on the two dumps the walk left on 2026-10-01 (2816 / 2811 green px) against the
    201 frames in the corpus that clear the count: only a splash carries a bounded 252x60
    pale-blue pill under it.
    """
    return _rankup_title(img, RANKUP_TITLE_LOW) and _rankup_pill(img) is not None


def rankup_ok(img):
    """Where to tap the splash's OK.

    羁绊 UP keeps the historical point: its frame did not survive in the corpus (the walk's dump
    name gets overwritten by the next stuck page), and that tap is what has been working in the
    field. 玩家等级 UP paints the same pill 100 px higher, so when the title sits in the lower
    band the point comes off the pill itself -- measured (643, 550), where RANKUP_OK would have
    tapped blank scrim.
    """
    if _rankup_title(img, RANKUP_TITLE_TOP):
        return RANKUP_OK
    cy, cx = _rankup_pill(img)
    return int(cx), int(cy)


def _box_pale(a, box):
    """Fraction of a (x0, x1, y0, y1) box that is pale (min(RGB) > 150) -- the mp_* regions."""
    x0, x1, y0, y1 = box
    return float((a[y0:y1, x0:x1].min(2) > 150).mean())


def _box_lum(a, box):
    """Weighted luma mean inside a box: 排名页's own 名次/分数 readout sits in the top-right."""
    x0, x1, y0, y1 = box
    s = a[y0:y1, x0:x1].astype(np.float32)
    return float((0.299 * s[..., 0] + 0.587 * s[..., 1] + 0.114 * s[..., 2]).mean())


def _prep_btn_colour(a):
    """准备页右下那个按钮现在是彩色的 准备 还是灰色的 取消（用户 2026-10-08）。

    按一下玩家就进准备状态，按钮**立刻**从彩色的 准备 变成灰色的 取消：彩色 = 还没准备
    （可以按），灰色 = 已经准备（再按就是取消准备，绝不能按）。量的是 MP_PBTN_BOX 里带色相
    的像素占比（通道极差 > PREP_BTN_SPREAD）；两边的实测值与余量见 PREP_BTN_COLOUR 的注释。
    """
    x0, x1, y0, y1 = MP_PBTN_BOX
    box = np.asarray(a, dtype=np.int16)[y0:y1, x0:x1]
    return float(((box.max(2) - box.min(2)) > PREP_BTN_SPREAD).mean())


def _mp_luma(a):
    """Weighted luma mean of a frame -- the number every MP_* threshold was measured with."""
    a = a.astype(np.float32)
    return float((0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]).mean())


def _mp_feats(a):
    """The two frame-wide numbers the lobby test needs: cyan ink and the blue-violet cast.

    多人 匹配页/五人加载页 画在蓝紫色舞台上：真机帧上 bluesat 0.32..0.81 同时 cyan
    0.06..0.17。商店 是橙的，演出前选项 是整片淡卡片，唯一长得像的是 结算 splash
    （nav_stuck_finish：bluesat 0.512 但 cyan 只有 0.105、底部中间 mid 0.096、左下角
    返回药丸 bl 0.165）。
    """
    a = a.astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    cyan = float(((g > 150) & (b > 150) & (r < 130)).mean())
    bluesat = float(((b > r + 30) & (b > g + 20) & (b > 90)).mean())
    return cyan, bluesat


def _mp_matchpopup(img):
    """多人 匹配中弹窗（排到人之前那一页）：整页压暗，底部一条宽药丸。

    用户 2026-10-08 的录像（research/recordings/mp2）里这一页停在 t 114.5–148.9（34.9 s
    一动不动），`screen` 当时把它读成 story：`_story_close` 要的「底部恰好一条宽 ≥180 px
    的亮组」正是这个弹窗自己的药丸。两道门都按真机帧量：这一页 luma 54.8..61.5（整页压暗），
    而 首页 152.8、单人结算 83.9、结算 splash 124.5 都在 80 以上；pill.pale 0.867..0.919
    把它与 暂停面板（navgates_pause_a：pill 0.805，但 luma 只有 43.3 —— 单看 pill 就会把
    暂停读成弹窗）分开。4197 张真帧（evidence/** 900 + research/frames + mp1 + mp2）扫下来
    111 命中：mp2 弹窗 93、mp1 弹窗 15、research/frames 3 —— 两张 live 的帧先被 `_magenta_lines`
    抢走，第三张 hud_g454_great63 是现场的一帧特效帧（辉光正好不在、y460-690 里还有 57 行白线）：
    改判前它读 story、走页会往场地正中按 (644,571)，现在读 matchpopup、走页只是安静等。
    evidence/nav 当时那 41 张零命中（新钉的 9 张 mp_* 正例除外）。
    """
    if img.mean() >= MP_POPUP_LUM + 25:
        return False        # 便宜的粗筛（img.mean 比加权 luma 高，见 _mp_luma）
    if _mp_luma(img) >= MP_POPUP_LUM:
        return False
    return _box_pale(img, MP_PILL_BOX) > MP_POPUP_PILL


def _mp_prep(img):
    """多人 准备页（五人准备状态 + 抽中封面 + 难度 + 右下 准备）。

    用户 2026-10-08 的录像里它停在 t 155.0–165.2（10.1 s），`screen` 当时把它读成 home ——
    走页就会去按首页底部的霓虹块（LIVE_TILE 1090,600），而真正的按钮是右下的 准备
    （1139,644，252x86）。三道门按真机帧量：这个按钮框的 pale 占比 0.303..0.961（按钮点亮的
    变样帧更高），按钮上的字 0.562..0.997，整页蓝紫 bluesat 0.538..0.647；而 首页 nav_home_a
    同一对框只有 0.206 / 0.307、整页 bluesat 只有 0.071 —— 头两道门差得不算远，第三道门把它
    远远挡在外面。4197 张真帧扫下来 35 命中（mp2 的 30 张准备页 + 4 张变样 + mp1 的 1 张
    准备页），别处零命中。

    **按钮上的字这道门 2026-10-08 撤了**（原 `_box_pale(img, MP_LABEL_BOX) <= MP_PREP_LABEL`）：
    准备页还有一个「蓝底 + 白色转圈、没有字」的过渡态（右下按钮正在转圈，`#ffffff` 占那一格
    10.47%、`_box_pale(MP_LABEL_BOX)` 只有 0.011），它过的了 pbtn(0.300) 与 bluesat(0.675) 两道
    门，却因为读不到字被踢出去 ⇒ `screen` 落到 `_blue(*PERFORM)` 读成 options ⇒ 走查在那页上按
    (790,611)（`research/frames/nav_stuck_options.png`，mp12/mp14/mp15 三跑都出现过）。全语料 3325
    帧里「pbtn+bluesat 过、label 不过」的**只有 2 帧**（另一张是 mp2 的 f00521_0180.88_options.png），
    两帧都是同一页在加载，所以撤掉这道门零附带损害。**但按不按**另有一道门：只有在字读得出来
    （`MP_LABEL_BOX` 的 pale 过 `MP_PREP_LABEL`）时才按 —— 转圈态永远不按。见
    research/experiments/prepspin.py。
    """
    if _box_pale(img, MP_PBTN_BOX) <= MP_PREP_PBTN:
        return False
    return _mp_feats(img)[1] > MP_PREP_BLUESAT


def _mp_matching(img):
    """多人 匹配页 / 五人加载页：抽曲动画、封面展示、五人加载进度画的是同一套版面。

    用户 2026-10-08 的录像里这三段是 t 150.1–152.4（抽曲动画）、152.8–154.6（抽中封面）、
    167.95–170.61（五人加载），`screen` 当时把它们读成 options / failed / shop —— 走页会按
    演出（790,611）或 返回选曲（924,611），在多人里都是按错页面。它们分不开：抽曲动画与五人
    加载的区域统计几乎一样（pbtn 0.019..0.026、label 0、mid 0），所以只能给一个 verdict。
    几道门全部按真机帧量（对照是同一批真帧里最像它的邻居）：右下角没有 pale 大按钮
    （这里 0.019..0.026；准备页 0.303）、按钮上没有字（0；准备页 0.562）、底部中间没有 下一步
    （0；单人结算 0.764）、左下角没有返回药丸（0.000..0.005；结算 splash 0.165）、整页 luma
    102.0..142.4、cyan 0.062..0.166、bluesat 0.32..0.81。4197 张真帧扫下来 23 命中
    （mp2 的 options 11 / failed 8 / shop 3 / rewards 1），覆盖匹配窗口那 23 帧里的 22 帧
    —— 第 23 帧（mp_matching_d.png，弹窗散开、匹配页淡入的那一帧）整页太暗（lum 59.2），
    cyan 只有 0.010，本来就不该被这组门收：它在 4197 张里与别的暗帧一样落进 other，
    走页对 other 只是数一次 unreadable screen，不按键。
    evidence/nav 当时那 41 张零命中（新钉的 4 张 mp_matching 正例除外）。
    """
    if _box_pale(img, MP_PBTN_BOX) >= MP_LOBBY_PBTN:
        return False
    if _box_pale(img, MP_LABEL_BOX) >= MP_LOBBY_LABEL:
        return False
    if _box_pale(img, MP_MID_BOX) >= MP_LOBBY_MID:
        return False
    if _box_pale(img, MP_BL_BOX) >= MP_LOBBY_BL:
        return False
    lum = _mp_luma(img)
    cyan, bluesat = _mp_feats(img)
    return (MP_LOBBY_LUM[0] < lum < MP_LOBBY_LUM[1] and cyan > MP_LOBBY_CYAN
            and bluesat > MP_LOBBY_BLUESAT)


def _mp_rank(img):
    """多人 排名页（五个人的名次与分数，等 下一步）：单人结算页的兄弟，版面不同。

    用户 2026-10-08 03:27:58 打完之后它就出来了，一直停到 03:33:01 用户按 下一步
    （t 299.9–602.7，803 帧完全静止），`screen` 当时把它读成 result —— 走页按的 (1080,660)
    正好落在它的 下一步 上（实测 x1012..1265 / y631..691），所以走页不用改，这个 verdict
    只是把话说准。与单人结算页分开的三处（都在真机帧上量）：底部中间没有 下一步（这里
    mid.pale 0.090，单人结算 result_a43/a44 是 0.764）、左下角有返回药丸（0.122，单人结算
    0.000）、右上角有自己的名次/分数（topR.luma 132.1，而 nav_stuck_finish 41.8）。
    4197 张真帧扫下来 800 命中，全部落在 mp2 里 screen=result 的帧上（排名页那 803 帧与它的
    近邻），evidence/nav 当时那 41 张零命中（result_a43/a44 被 mid.pale 0.764 与 bl.pale 0.000
    挡在外面）。
    """
    if _box_pale(img, MP_MID_BOX) >= MP_RANK_MID:
        return False
    if _box_lum(img, MP_TOPR_BOX) <= MP_RANK_TOPR_LUM:
        return False
    if _box_pale(img, MP_PILL_BOX) >= MP_RANK_PILL:
        return False
    if _box_pale(img, MP_PBTN_BOX) >= MP_RANK_PBTN:
        return False
    return _box_pale(img, MP_BL_BOX) > MP_RANK_BL


def screen(img):
    """Which menu we are on.

    Button colour alone cannot tell these pages apart: 下一步, 确定 and LIVE START are all blue
    in roughly the same corner, and the LIVE START gradient reads as magenta on the options page
    too. So each page is claimed by a layout feature only it has -- the red LEADER banner, the
    rank letter on the score breakdown, the modal's 演出 button -- and the order matters, with
    the live field checked first because nothing else is on screen then.
    """
    if _magenta_lines(img):
        return "live"
    if _purchase(img):
        return "purchase"    # 确认购买: nothing here is worth tapping except 取消
    if _frac(img, _red, 640, 120, 70, 16) > BAND_RED:
        return "band"        # 乐队确认, by its LEADER banner
    if _mp_prep(img):
        return "prep"        # 多人 准备页：问在 首页 之前（它现在被读成 home，走页会按错）
    if _home(img):
        # 首页, asked before 商店: the store test counts orange pixels in two bands, and a warm
        # full-screen event banner on 首页 saturates it (7894 against a gate of 5000).
        return "home"
    if _mp_matching(img):
        # 多人 匹配页 / 五人加载页，问在 商店 之前：抽中封面那一屏的橙色被 `_shop` 的橙像素
        # 计数误读成 商店（mp2 的三张封面帧现在读 shop），走页就会去按页头的房子图标。
        return "matching"
    if _shop(img):
        return "shop"        # 商店: leave by the header's house icon, never a 购买 pill
    if _blue(img, *PERFORM) and _go_pill_wide(img):
        # 活动主页（挑战演出活动）: 挑戦演出 与 演出 两颗蓝按钮并排，右边那颗正是结算族的
        # **宽**药丸。它不是任何一条流程认得的页面 —— 2026-10-20 23:5x 它被判成 options，
        # 走查会去按 (790,611)，也就是「演出」；判成 exp 则按 (1104,655)，还是「演出」。
        # 从这一页开局等于拿活动去开一局没人排过曲的 LIVE，所以这里只给它一个名字，让走查
        # **什么都不按**、直接放弃（见下面 event 分支）。两颗蓝同时成立在语料里只有这一帧。
        return "event"
    if _blue(img, *PERFORM):
        return "options"     # 演出前选项设置
    d = _dialog(img)
    if d == "confirm":
        return "confirm"     # 重试 confirmation, before the 'preset' it shares its pill row with
    if _blue(img, 770, 573) and _pills_at(img, *PRESET_PILLS):
        # 应用默认设置: OK is blue, 关闭 to its left is grey -- but blue alone is not enough. The
        # song-select page's *selected difficulty pill* sits at (770,573) too, so on 2026-10-04 a
        # chart parked on EASY was read as this dialog and the walk tapped 关闭's coordinates
        # (510,573), which on the select page is a row of the song list: twenty taps that shuffled
        # the user's selection before the round gave up. The two pills are the dialog's own
        # geometry -- the same 502/785 pair `_dialog` already measured for the two-button dialogs.
        return "preset"
    if _loading(img):
        return "loading"     # 演出 load interstitial: pale card, no badge -- asked before result
    if _mp_rank(img):
        return "rank"        # 多人 排名页：与 结算 共用走页的 下一步，只是版面不同
    if _frac(img, _white, 1180, 75, 60, 16) > 0.12:
        return "result"      # 结算, by its rank letter
    if _exp_page(img):
        return "exp"         # 结算 EXP page, whose blue 再次演出 sits in 确定's own corner
    if lb_popup(img):
        # 消耗LB 的四档弹窗（盖在乐队确认页上）。**必须问在 `select` 之前**：弹窗没盖住乐队
        # 确认页右下角的 LIVE START，`_blue(*SONG_GO)` 照样命中，2026-10-11 真机实测这一页被
        # 读成乐曲選択页 —— 走查于是会去按 決定（在弹窗上就是一行档位）。上面那些判据（红横幅、
        # 首页、匹配页、商店、加载…）在这张弹窗上都不成立，所以插在这里既能盖住 select，又不会
        # 抢走别的页面。
        return "lbpopup"
    if _blue(img, *SONG_GO) and not _go_pill_wide(img):
        return "select"      # 乐曲选择（**窄**的決定；结算族那颗宽的由上面的 exp 认领）
    if _blue(img, 924, 611):
        return "failed"
    if _livehome(img):
        return "livehome"    # 演出首页, checked last since 演出失败 overlays it
    if _finish(img):
        return "finish"      # LIVE FINISH rank splash, which sits between the song and 结算
    if _rankup(img):
        return "rankup"      # 羁绊 RANK UP, between the reward modals and 结算
    if d == "pause":
        # Asked before the modal tests, because a paused LIVE can wear a fourth pale pill: this
        # frame (g296/g300 both died on it) has a wide pale bar under the 终止/重试/继续 row, which
        # `_modal_close` reads as the 关闭 of a reward modal -- so the pause panel was classified
        # 'rewards', `restart_to_t0` fell into its "no pause panel to restart from" branch, and
        # every 断AP重试 that lands on this variant abandons its round for nothing. The dialog test
        # is the exact one (three bright pills at 356/640/923 on the pill row), and it collides
        # with nothing in the corpus: of the 37 pinned frames, none but this one answers 'pause',
        # and the two 羁绊奖励详情 frames answer None.
        return "pause"       # the dimmed field reads as nothing else, but the 3 pills are exact
    if _reward(img) or _modal_close(img) or _bond_detail(img):
        return "rewards"     # 达成奖励列表 / 羁绊奖励详情, opened by the game over the result page
    if _level_rankup(img):
        return "rankup"      # 玩家等级 RANK UP: the same splash one layout lower, asked only after
                             # the modal tests so the split view keeps reading "rewards"
    if _mp_matchpopup(img):
        return "matchpopup"  # 多人 匹配中弹窗：`_story_close` 会把它读成 故事解锁
    if _story_close(img):
        return "story"       # 故事解锁, same post-result walk, 关闭 a row higher
    return "other"


def _fire_runs(mask, y0, y1, x0, x1):
    """Ink runs across the fire band -> [(x_left, x_right, top_cx, bot_cx, height), ...].

    The two centroids are what separate the readout's two halves: a `/` is the only glyph here
    whose top third sits right of its bottom third, `1` and `7` lean the other way.
    """
    band = mask[y0:y1 + 1, x0:x1 + 1]
    cols = band.any(axis=0)
    out, i, n = [], 0, len(cols)
    while i < n:
        if not cols[i]:
            i += 1
            continue
        s = i
        while i < n and cols[i]:
            i += 1
        sub = band[:, s:i]
        rows = np.nonzero(sub.any(axis=1))[0]
        top, bot = int(rows[0]), int(rows[-1])
        third = max(1, (bot - top + 1) // 3)

        def _cx(blk):
            xs = np.nonzero(blk.any(axis=0))[0]
            return float(xs.mean()) if len(xs) else float(s)

        out.append((x0 + s, x0 + i - 1, _cx(sub[top:top + third]),
                    _cx(sub[bot - third + 1:bot + 1]), bot - top + 1))
    return out


def fire_power(img, templates=None):
    """加成火力 `(cur, cap)` off 乐队确认's top-right readout, or None if it did not read cleanly.

    Zero OCR, same machinery as the result page and the HUD, except the glyph positions come from
    the frame: the readout slides a few px between frames and a two-digit current grows leftward,
    so the band is split at the slash every time rather than at frozen x. None is the right answer
    when it is ambiguous -- the caller then plays, which is what the game did before this gate.
    `templates`, if given, spares the per-poll reload. One call costs about 30 ms, and since 用户
    m26442 the gate reads it once per arrival at 乐队确认 (there is no polling loop any more).
    """
    from resultread import _num, load_templates, read_cell

    a = np.asarray(img)
    y0, y1 = FIRE_Y
    bx0, bx1 = FIRE_BAND_X
    # The mask is built on the band alone -- 0.07 ms against 29 ms for the same three reductions
    # over the whole 1280x720 frame, and these are the frame's own values, so the reading is
    # unchanged. Everything below is therefore in band-relative coordinates.
    sub = a[y0:y1 + 1, bx0:bx1 + 1]
    mn = sub.min(axis=2)
    mask = (mn > FIRE_MASK) & ((sub.max(axis=2) - mn) < FIRE_FLAT)
    by1 = y1 - y0
    runs = [r for r in _fire_runs(mask, 0, by1, 0, bx1 - bx0)
            if r[4] >= FIRE_MIN_H]
    slash = next((i for i, r in enumerate(runs)
                  if r[1] - r[0] + 1 <= FIRE_SLASH_W and r[2] - r[3] >= FIRE_SLASH_LEAN), None)
    if slash is None:
        return None
    left, right = runs[:slash], runs[slash + 1:]
    if not (1 <= len(left) <= FIRE_DIGITS[0] and 1 <= len(right) <= FIRE_DIGITS[1]):
        return None
    tpl = load_templates() if templates is None else templates
    cur, _d1 = read_cell(mask, 0, by1 + 1, left[0][0], left[-1][1] + 1, tpl,
                         max_w=FIRE_MAX_W, min_h=FIRE_MIN_H)
    cap, _d2 = read_cell(mask, 0, by1 + 1, right[0][0], right[-1][1] + 1, tpl,
                         max_w=FIRE_MAX_W, min_h=FIRE_MIN_H)
    cur_n, cap_n = _num(cur), _num(cap)
    if cur_n is None or cap_n is None or cur_n > cap_n:
        return None
    return (cur_n, cap_n)


def lb_ok(img):
    """消耗LB 弹窗底部那颗 OK 的「亮蓝占比」—— 认弹窗的第三道门（实测 0.974，非弹窗帧最高 0.656）。

    单独用它分不干净（`mp_prep_spin.png` 也有 0.656），所以 `lb_popup` 是三个特征一起看。
    """
    a = np.asarray(img).astype(np.int16)
    x0, y0, x1, y1 = LB_OK_BOX
    sub = a[y0:y1 + 1, x0:x1 + 1]
    lum = sub.mean(axis=2)
    return float(((lum > 110) & (sub[:, :, 2] > sub[:, :, 0] + 40)).mean())


def lb_state(img):
    """`(行条数, 选中档)` —— 四行里有多少行是「行条」，以及哪一档铺着青色（读不出就是 None）。

    四行都是圆角条：未选中铺深蓝 (56,63,116)、选中的那一行铺青 (~(56,100,108))。差别不在亮度
    而在通道关系上，所以用 `b - r` 判「是不是行条」、用 `g - b` 判选中（青 -8 / 深蓝 -47）。
    只认「行条」会假阳性 10 张（乐曲選択页的列表行也是蓝的），只认「有一行是青的」也不够
    （`nav_stuck_finish.png` 就是），所以两个都要。
    """
    a = np.asarray(img).astype(np.int16)
    x0, x1 = LB_ROW_XBAND
    bars, selected = 0, None
    for (y0, y1), lvl in zip(LB_ROW_BANDS, LB_ROW_LEVELS):
        sub = a[y0:y1 + 1, x0:x1 + 1]
        if float((sub[:, :, 2] - sub[:, :, 0]).mean()) > LB_ROW_BLUE:
            bars += 1
            if selected is None and float((sub[:, :, 1] - sub[:, :, 2]).mean()) > LB_ROW_TEAL:
                selected = lvl
    return bars, selected


def lb_popup(img):
    """这一帧是不是 消耗LB 的四档弹窗：四条行带都在 + 恰好一行是青的 + OK 那颗亮蓝按钮在。

    三个特征缺一不可：`evidence/nav` 63 张夹具里，只看「四条行带」会假阳性 10 张（乐曲選択页、
    匹配中、準備页…），加上「有一行是青的」还剩 1 张（`nav_stuck_finish.png`），三个一起才 0 张。
    真弹窗帧 `lb_ok` 0.974、`real_now.png`（乐队确认页）0.14。

    必须在 `screen()` 里**抢在 `select` 之前**问：弹窗没盖住乐队确认页右侧的 LIVE START，
    `_blue(*SONG_GO)` 照样命中，于是这一页会被读成乐曲選択页、走查会去按 決定（真机实测）。
    """
    bars, selected = lb_state(img)
    return bars >= len(LB_ROW_BANDS) and selected is not None and lb_ok(img) > LB_OK_BLUE


def set_live_boost(level, i, log=print, grabber=None):
    """把本次 Live 的加成火力档位设成 `level`（`LB_LEVEL_HIGH` 或 `LB_LEVEL_LOW`），成功 True。

    乐队确认页点 消耗LB → 等弹窗 → 选中档不对就点那一行并**验证真的换了**（上限 `LB_TRIES`）→
    点 OK → 验证弹窗真的关了。任一步验不过都照按一次 OK 收场：**绝不能把一个开着的弹窗留给
    走查**（`screen()` 会把它读成乐曲選択页，走查就会去按 決定）。`grabber` 不给就用 `grab`。
    """
    read = grab if grabber is None else grabber
    tap(*LB_BTN, i=i)
    time.sleep(LB_SETTLE_S)
    img = read()
    if not lb_popup(img):
        log(f"!! 消耗LB 弹窗没开（点了 {LB_BTN}）—— 档位保持原样，按现状开打")
        return False
    got = None
    for _ in range(LB_TRIES):
        _bars, got = lb_state(img)
        if got == level:
            break
        log(f"  消耗LB：现在 {got} 档，点 {level} 档（y={LB_ROW_Y[level]}）")
        tap(LB_ROW_X, LB_ROW_Y[level], i=i)
        time.sleep(LB_SETTLE_S)
        img = read()
    if got != level:
        log(f"!! 消耗LB：点了 {level} 档，读数却是 {got} 档 —— 按 OK 收场，档位随游戏自己")
    tap(*LB_OK, i=i)
    time.sleep(LB_SETTLE_S)
    img = read()
    if lb_popup(img):
        log("!! 消耗LB 弹窗没关掉 —— 再按一次 OK")
        tap(*LB_OK, i=i)
        time.sleep(LB_SETTLE_S)
        img = read()
    closed = not lb_popup(img)
    if closed:
        log(f"  消耗LB：{level} 档已设好，弹窗已关")
    else:
        log("!! 消耗LB 弹窗关不掉 —— 走查会把它读成乐曲選択页")
    return closed and got == level


def solo_modal(s, multi):
    """单人局读到「匹配中弹窗」时，那一页的真身是「盖在结算页上的弹窗」（故事解锁）。

    匹配只在激奏演出里有，所以 `multi=False` 的走查不可能真的站在匹配弹窗上。用户 m10037
    （2026-10-09）报的故事解锁弹窗正是这一页：`_mp_matchpopup` 的两道门（mean < 105、
    `_mp_luma` < 80、MP_PILL_BOX 的 pale > 0.85）它全过，而 `_story_close` 对它又是 False
    （底部那一带今天有三组亮列，判据要求恰好一组），于是它落在 `matchpopup` 上 —— 那一页在
    `MP_QUIET_PAGES` 里，走查只看不按，g508 因此 45 s 后「没能走回选曲页」，游戏留在弹窗上。

    整库普查（`research/experiments/mphits.py`）：最终 verdict 是 matchpopup 的只有 15 张 ——
    11 张多人匹配弹窗 + 3 张这一页，没有第三种页面。所以这条规则不是猜的。

    这一页只有一个合法按键：那颗居中的亮药丸，也就是 故事解锁 的 关闭（`STORY_CLOSE`）。多人的
    匹配弹窗在同一个位置（`MP_PILL_CENTRE`）是「取消这次匹配」，但那条路只在 `multi=True` 时走，
    这里不会碰到它。单独抽成函数是为了让 `tools/probes/navgates.py` 的 PART 18 能把它换掉、
    证明这颗牙是真的（拆掉它，同一个脚本必须走不完）。
    """
    return s == "matchpopup" and not multi


def start_live(inj, log=print, timeout=150.0, on_select=None, stop_at_select=False,
               min_fire=0, grabber=None, multi=False, on_prep=None):
    """Walk from anywhere to a running LIVE, tapping only buttons this function has seen.

    达成奖励 is never clicked: it claims items, which is out of bounds.

    `stop_at_select` turns the same walk around: it ends at 乐曲选择 instead of pressing into
    another LIVE, which is how a finished round hands the game back ready to pick a song. On that
    trip the two buttons that *start* a LIVE (演出开始 on 乐队确认, 演出 on 演出前选项设置) are not
    pressed at all, and a `live` frame is not success: a walk that pressed its way into a field
    would otherwise report "home" while a song runs with nobody firing at it (g446). 乐队确认 on
    that trip is passed through with its top-left back arrow (`BAND_BACK`, user m02645) rather than
    waited on -- a round abandoned on that page would otherwise never get home.

    `on_select`, if given, runs before 确定 goes out -- the last moment a chart can still be
    changed. Random mode hangs its 随机选曲 press there and reads the game's pick back off the
    page. Returning False stops the walk instead of starting a LIVE, because a pick that could
    not be read leaves nothing to play. Returning "wait" means the frame only looked like the
    select page (the 结算 page is blue where 确定 sits too, and the user watched a pick start on
    it mid-animation): nothing is tapped, the frame is re-read, and the callback gets another
    chance -- or the walk moves on if the page changes under it.

    `min_fire`, when positive, is the 加成火力 gate on 乐队确认, and since 用户 m26442 (2026-10-11) it
    **picks the 消耗LB tier instead of waiting**: a LIVE spends up to 3 points for the extra item
    reward, and the readout sits on that page. A clean reading at or above `min_fire` sets tier
    `LB_LEVEL_HIGH` (3), one below it sets tier `LB_LEVEL_LOW` (0), and the walk starts either way --
    no sleep, no upper bound, nothing to strand. An unreadable readout is played through *without
    touching 消耗LB* ("有任何不确定也可以打，损失不大"), so a classifier that breaks on some future
    frame can neither hang a round nor burn fire it could not count. Tier 3 needs a reading of at
    least `max(min_fire, LB_LEVEL_HIGH)`, because the dialog's own red note says an unmet cost spends
    everything held. `grabber` overrides the frame source, which is how a probe drives this with a
    frozen frame instead of an emulator.

    Once the start tap is out the walk only *watches* (see `tail` below), but not for ever: a page
    that keeps reading the same verdict for `TAIL_STUCK_S` is not a load (g471 sat on one such page
    for 139 s while the song played itself out), so the walk hands it back to its normal handling --
    unless that handling would press a button that starts a LIVE (`TAIL_LIVE_STARTERS`: 确定 on the
    song-select page, 演出, 自由演出, 演出开始), in which case the walk gives up instead of pressing
    one blind, because a 结算 page's blue 下一步 reads as `select` too.

    `multi` is the 多人 chain (see MULTI_LIVE_TILE): the 演出首页 tile it presses is 激奏演出
    instead of 自由演出, the 乐队确认 button it presses is 自由对战 (same coordinate), and the 准备页
    gets its 准备 pressed -- the one button in this walk whose *second* press undoes the first, so it
    is only re-pressed while the button's own bright layer says the press never landed. The deadline
    is pushed out to MULTI_WALK_TIMEOUT_S: 匹配 and the other four players' 准备 are not ours to
    hurry. The one exception is the 匹配中弹窗: its static pill is 取消 (measured 2026-10-08: the page
    is back on 乐队确认 1.5 s later), so a popup that has sat for MULTI_MATCH_WAIT_S is cancelled and
    the walk re-presses 自由対戦 -- up to MULTI_MATCH_TRIES times, because a room with nobody in it
    never resolves (mp8 sat on that page for 15 minutes). 多人不消耗物资, and nothing on the way is a
    购买 or a 达成奖励 button.

    `on_prep` is the other half of that flow. 多人 draws the song *after* the walk leaves 乐曲选择
    (匹配 → 抽曲动画 → 准备页), so the chart cannot be named when 确定 goes out -- the 准备页 is the
    only page that shows the draw. The callback is handed what `gameread.read_prep` read there (the
    drawn song's jacket sits at PREP_JACKET_BOX) and runs once, on the first 准备页 frame that reads a
    song at all: the page is up for about ten seconds and its first frames can still be mid-animation,
    so a read that fails is not an answer and the page is re-read on the next pass. What the callback
    does with it -- load the chart, remember the difficulty -- is the caller's business; the walk
    only goes on pressing 准备.
    """
    from PIL import Image

    if multi:
        timeout = max(timeout, MULTI_WALK_TIMEOUT_S)
    end = time.perf_counter() + timeout
    unknown = 0
    press_at = {}           # 页 -> (上一次按下去时那一帧的指纹, 那一刻)

    def _once(page_name, limit=FREEZE_REPRESS_S):
        """这一页在**当前这一帧**上还没按过（或者已经等了 `limit` 秒）才允许按。

        冷启动之后头一次进某个页面会**定格几秒**（用户 m54800：缓存被清掉了），这一帧上
        补按不会让页面动，只会在解冻后落到**下一页**上 —— 准备 那一下尤其糟：第二下就是
        取消准备，整局就按死在准备页上。判据是「同一帧」而不是「同一页」，所以页面一动
        （按钮呼吸、动画、真的翻页）就立刻恢复正常节奏。
        """
        key = frame_key(img)
        prev = press_at.get(page_name)
        now = time.perf_counter()
        if prev is not None and prev[0] == key and now - prev[1] < limit:
            return False
        press_at[page_name] = (key, now)
        return True

    prep_taps, prep_t0 = 0, 0.0   # 准备页那一按：按一次就是准备状态，再按是取消，所以最多两下
    prep_grey = False       # 已经看见按钮变成灰色的 取消（= 玩家在准备状态上），之后一下都不按
    prep_spin = False       # 已经看见按钮在转圈（读不到字 = 这一页还在加载），只抱怨一次、不按
    prep_read, prep_failed = None, False            # 抽中的曲子（read_prep 读到的第一份成功答案）
    mp_t0, mp_cancels, mp_stopped = None, 0, False  # 匹配中弹窗：这一页等了多久 / 取消过几次
    solo_t0, solo_taps, solo_stopped = None, 0, False   # 单人局读到「匹配弹窗」时的 关闭 预算
    back_taps = 0           # 回家那趟在乐队确认页按了几次返回箭头（离开那一页就清零）
    lb_taps = 0             # 撞见 消耗LB 弹窗时按了几次 OK（`set_live_boost` 本该把它关掉）
    tail = False            # True once the LIVE-START tap has gone out
    starts = 0              # how many 演出开始 taps have gone out (the retry is bounded)
    home_live = None        # when the walk-home first read a running LIVE (see the `live` branch)
    rep_s, rep, rep_t0 = None, 0, None   # rep_t0 = when this run of identical verdicts started
    read = grab if grabber is None else grabber
    while time.perf_counter() < end:
        img = read()
        s = screen(img)
        if s != "band":
            back_taps = 0       # 这一页的返回箭头计数只在连续停在 band 时累加
        if s != "lbpopup":
            lb_taps = 0         # 弹窗的 OK 计数同理，只在连续停在 消耗LB 弹窗上时累加
        nap = 1.6
        if s in MP_QUIET_PAGES or s == "loading" or (s == "other" and img.mean() < 24):
            # 演出 commits to a fade through black before the field loads, and the load itself
            # paints a full-bleed pale card. Tapping into either is harmless but reading the fade
            # as an unknown page quits a run that was going fine, and reading the card as 结算
            # spent four watches' worth of naps on a page with nothing to press.
            # 多人开打前的三页（MP_QUIET_PAGES：匹配中弹窗 35 s / 准备页 10 s / 匹配页与五人
            # 加载页）同理：页面自己在走，没有一个「往前走」的按钮是这里该按的 —— 准备页那个
            # 按钮只在它还是**彩色**的 准备 时按一下（灰的 取消 再按就是取消准备，见下面的 prep
            # 分支），弹窗与加载页只能等。它们落到下面的 else 里 8 次（约 12.8 s）就被当成卡死、
            # 整局判掉，所以在载入这里一起等。
            log(f"  screen: {s if s in MP_QUIET_PAGES else 'loading'}")
            unknown = 0
            # 这一页在等游戏自己走完（匹配中弹窗 35 s、准备页 10 s、加载页），不是「同一个
            # verdict 连读」——把重复计数一起清掉。不清的话尾段的逃生会拿一段安静页**之前**
            # 的时间来算：重放 mp2 时 `other` 只连读 3 次（真的只过了 0.5 s），却因为中间隔着
            # 34 s 的匹配中弹窗而被算成「连读 22 s」，白交回一次通用处理。
            rep_s, rep, rep_t0 = None, 0, None
            if s == "prep" and multi and not stop_at_select:
                if prep_read is None:
                    # 这一局打哪张谱，只有准备页上看得出来：抽中的曲子封面在 PREP_JACKET_BOX。
                    # 页面前几帧可能还在抽曲动画里，所以只认第一份读出来的成功答案（读不出来的帧
                    # 不算答案，下一轮再读）；读到就交给 on_prep，由调用方去装谱面。
                    import gameread
                    got = gameread.read_prep(img)
                    if got.get("ok"):
                        prep_read = got
                        diff, det = gameread.read_difficulty(img)
                        log(f"  准备页：抽中 {got['musicId']}（ncc {got['score']:.3f}，"
                            f"次高差 {got['gap']:.3f}）")
                        log(f"  准备页：难度带读出 {diff}（{det}）—— 只是诊断，本局难度按乐曲选择页")
                        if on_prep is not None:
                            on_prep(got)
                    elif not prep_failed:
                        prep_failed = True
                        log(f"  准备页：还没读出抽中的曲子（{got.get('why')}）—— 继续等")
                # 准备页右下那个按钮（MULTI_PREP_BTN）：按一下玩家就进准备状态，按钮**立刻变成
                # 灰色的 取消** —— 再按一下就是取消准备（用户 2026-10-08 确认）。所以只有按钮还是
                # **彩色**（= 还没准备）时才按，灰了就只等另外四个人（等待由走查的 deadline 兜底）。
                # 补按也只在这个前提下、且过了 MULTI_PREP_SETTLE 才允许：从前它按按钮 pale 没涨
                # 就补按（最多 3 次），可那一格的 pale 本来就是按钮自己的呼吸（mp2 的 36 张准备页帧
                # 实测在 0.303（暗相）与 0.744（亮相）之间来回跳、周期约 1.4 s），判据
                # `pale <= prep_pale + 0.05` 分不出「按中」和「正好跳到暗相」—— 补按就是替玩家
                # 取消准备，把这一局按死在准备页上。见 research/experiments/preppale.py。
                sat = _prep_btn_colour(img)
                # 按钮上读不出字（`_box_pale(MP_LABEL_BOX)` 不过门）说明它还在转圈 —— 页面还在
                # 加载，那一下按下去没有意义（`_mp_prep` 已经不再因为读不到字就否认这一页）。
                labelled = _box_pale(img, MP_LABEL_BOX) > MP_PREP_LABEL
                now = time.perf_counter()
                if not labelled:
                    if not prep_spin:
                        prep_spin = True
                        log(f"  准备页：按钮还在转圈（读不到字，带色相 {sat:.2f}）—— 不按，等它出来")
                elif sat < PREP_BTN_COLOUR:
                    if not prep_grey:
                        prep_grey = True
                        log(f"  准备页：按钮是灰色的 取消（带色相 {sat:.2f}）—— 已经在准备状态，不按")
                elif (prep_taps < MULTI_PREP_TRIES
                      and (prep_taps == 0 or now - prep_t0 >= MULTI_PREP_SETTLE)
                      and _once("准备")):
                    prep_taps += 1
                    prep_t0 = now
                    if prep_taps == 1:
                        log(f"  准备页：按 准备（按钮是彩色的 {sat:.2f}）")
                    else:
                        log(f"  准备页：按了 {prep_taps - 1} 次按钮还是彩色的（{sat:.2f}）—— 那一下没落地，补按")
                    tap(*MULTI_PREP_BTN, i=inj, hold=0.16)
            if solo_modal(s, multi):
                # 单人局读到匹配弹窗 —— 单人没有匹配，这一页是盖在结算页上的弹窗（故事解锁，
                # 用户 m10037）。它的 关闭 就是那颗居中的亮药丸（STORY_CLOSE），别的什么都不按。
                # 有界：先等 SOLO_MODAL_SETTLE 再按（挡掉淡入里的误读），最多 SOLO_MODAL_TRIES 下，
                # 之后安静等 deadline；离开这一页就把预算清掉（下面那个 else）。
                if solo_t0 is None:
                    solo_t0 = time.perf_counter()
                    path = f"{subdir(FRAMES)}/nav_stuck_matchpopup_solo.png"
                    Image.fromarray(img).save(path)
                    log(f"  单人局读到匹配弹窗（单人没有匹配）—— 这一页是盖在结算页上的弹窗，"
                        f"按它的 关闭；存 {path}")
                elif time.perf_counter() - solo_t0 >= SOLO_MODAL_SETTLE:
                    solo_t0 = None
                    if solo_taps < SOLO_MODAL_TRIES:
                        solo_taps += 1
                        log(f"  弹窗：按 关闭（第 {solo_taps}/{SOLO_MODAL_TRIES} 次）")
                        tap(*STORY_CLOSE, i=inj, hold=0.16)
                    elif not solo_stopped:
                        solo_stopped = True
                        log(f"  弹窗：按过 {SOLO_MODAL_TRIES} 次还没走 —— 不再按，交给 deadline")
            elif s == "matchpopup" and multi:
                # 匹配中弹窗：房间配不到人时它就一直停在这里（mp8 停了 15 分钟），帧一动不动、也没
                # 有一个「往前走」的按钮 —— 只有那个静态药丸是取消这次匹配（2026-10-08 实测：点它
                # 1.5 s 后回到 乐队确认页）。所以只能按时间判：等够 MULTI_MATCH_WAIT_S 就取消一次，
                # 走查接着会在 `band` 分支再按一次 自由対戦（受 START_RETRIES 限制），最多取消
                # MULTI_MATCH_TRIES 次；用完就不再动那一页，交给 deadline。
                if mp_t0 is None:
                    mp_t0 = time.perf_counter()
                elif time.perf_counter() - mp_t0 >= MULTI_MATCH_WAIT_S:
                    mp_t0 = None
                    if mp_cancels < MULTI_MATCH_TRIES:
                        mp_cancels += 1
                        log(f"  匹配页：等了 {MULTI_MATCH_WAIT_S:.0f} s 还没配到人 —— 按药丸取消这次"
                            f"匹配，回去再按一次 自由対戦（第 {mp_cancels}/{MULTI_MATCH_TRIES} 次）")
                        tap(*MP_PILL_CENTRE, i=inj, hold=0.16)
                    elif not mp_stopped:
                        mp_stopped = True
                        log(f"  匹配页：已经取消过 {MULTI_MATCH_TRIES} 次，不再取消，等 deadline")
            else:
                mp_t0 = None   # 离开那一页（prep/matching/载入）就把计时清掉
                solo_t0, solo_taps, solo_stopped = None, 0, False
            # Under `tail` the fade matters: the field is painted within a second or two of the
            # start tap, and every 0.4 s slept through it is a 0.4 s later vote. The loading
            # branch is the one page that is definitely not a button, so it is safe to rush.
            time.sleep(0.15 if tail else 0.4)
            continue
        # A tap that changes nothing has to be visible in the log. The frame source used to cost
        # 300 ms, which paced this loop by itself; at 30 fps the same 1.6 s of nap is a dozen
        # identical taps, and a14 spent eleven seconds tapping 开始Live on a page that had
        # already moved on underneath it.
        rep = rep + 1 if s == rep_s else 1
        rep_s = s
        if rep == 1:
            rep_t0 = time.perf_counter()   # tail's escape times this run; every reset writes rep=0
        log(f"  screen: {s}" + (f" (x{rep})" if rep > 1 else ""))
        if rep == 4:
            # Under `tail` nothing is tapped, so the same count of frames is the same evidence
            # with a different name -- rnd4's live fade read as "result" eight times in a row
            # and the note about "four taps" sent the wrong reader looking for a stray button.
            path = f"{subdir(FRAMES)}/nav_stuck_{s}.png"
            Image.fromarray(img).save(path)
            log(f"  four {'watches' if tail else 'taps'} with no change on {s} -> {path}")
        if s == "live":
            if not stop_at_select:
                return True
            # 走回家撞进 LIVE（按钮按错、或上一局没退干净停在歌里）：这里**不能**报「已回家」——
            # `leave_at_select` 会打 `#ATSELECT#`，面板据此认为本局收尾完毕，而游戏正在打歌、
            # 没人在发键，下一局的开场就被这一局吃掉。没有人在打，歌自己会唱完并出结算页，
            # 所以只等（上限 HOME_LIVE_WAIT_S），不再按任何按钮，等到了接着走回家。
            if home_live is None:
                home_live = time.perf_counter()
                log("  回家路上撞进 LIVE —— 没人在发键，等它自己唱完再走（不再按按钮）")
            if time.perf_counter() - home_live > HOME_LIVE_WAIT_S:
                log(f"  回家路上撞进 LIVE，等了 {HOME_LIVE_WAIT_S:.0f} s 还没结束 —— 放弃回家")
                return False
            time.sleep(1.0)
            continue
        if s == "select" and stop_at_select:
            # The walk-back: 乐曲选择 is the destination here, not a page to press. Tapping 确定
            # on it would start another LIVE, which is exactly what a finished round must not do.
            #
            # 到达之后再多看几眼：达成奖励列表 会在这一页上自己弹出来（2026-10-19 用户：「连续演奏
            # 打完最后一局会停在显示奖励的那一页」）。走到这儿立刻 return 的话，弹窗再没人关 ——
            # 下一局开工时才会把它当 rewards 关掉，最后一批就停在那儿。判据只用 `_reward` 与
            # `_bond_detail`（达成奖励列表 / 羁绊奖励详情），它们在这一页上只对那个弹窗成立；`_modal_close`
            # 不许用，它对 准备页 / 消耗LB弹窗 / 暂停面板 都为真，只有 `screen()` 里排在它们后面才安全。
            for _ in range(REWARD_OVER_SELECT_TRIES):
                time.sleep(REWARD_OVER_SELECT_SETTLE)
                again = read()
                if not (_reward(again) or _bond_detail(again)):
                    break
                log("  选曲页上又盖上了 达成奖励列表 —— 按 关闭（不领奖）")
                tap(*MODAL_CLOSE, i=inj)
            return True
        if tail:
            # The LIVE is loading. Whatever the load is misread as, the walk would tap that page
            # to advance it, and re-tapping the start button into the load is what fired 35
            # 开始Live presses into a14's without ever starting the song. Once the start tap is
            # out the field needs no more buttons, so the tail only watches -- quickly, because
            # the field was missed for 2.2 s after the fade in t04 (one 1.6 s nap too many) and
            # the opening chord is due at chart +2.56.
            #
            # Every page, not a whitelist. The whitelist was the set of misreads seen so far, and
            # it was never complete: replaying mp2's 激奏演出 against the real walk (mpreplay.py,
            # 2026-10-08) put the field's own fade-in through other (0.86 s) -> rankup -> result
            # -> options -> live (a single frame) -> other (4.11 s) -> live, and two of those
            # names were not on the list. `rankup` fell through to its own branch and tapped the
            # RANK UP pill's centre (642,652) into the field; `other` fell through to the
            # unreadable counter, and 4.1 s of it is eight reads, so a walk that missed that one
            # live frame gave up the whole round ("stuck on an unreadable screen") with the field
            # already on screen. Watching everything costs nothing -- the hand-back below still
            # releases a page that will not change, and TAIL_LIVE_STARTERS still refuses to press
            # a button that opens a LIVE.
            hand_back = False   # 逃生把这一页交回通用处理时置位（下面的 sleep/continue 就不走）
            if (s == "select" and multi and prep_read is None and rep >= 3
                    and mp_cancels < MULTI_MATCH_TRIES):
                # 匹配散了（mp24/mp27，2026-10-09 04:29 与 04:37）：房间里没凑满人时游戏**自己**
                # 把匹配中弹窗收掉（32 s，没到 MULTI_MATCH_WAIT_S 的 120 s，所以上面那个取消药丸
                # 一次都没机会按），掉回 演出失敗 / 多人选曲页。原来走到这里就被下面
                # TAIL_LIVE_STARTERS 那条判死（「只能按开一局的按钮，分不清真假，不再等」），一局
                # 就这么丢了 —— 本批八局里两局。但**多人这一页上的 确定 不开一局**：它去 乐队确认，
                # 再按 自由対戦 才是开匹配，所以这一页可以交回通用处理（按 确定 → 乐队确认 → 上面
                # 的 band 分支再按一次 自由対戦，重来一次匹配）。两重有界：rep >= 3（连续三个
                # verdict 都是 select ≈0.75 s，挡掉载入淡入里的误读），以及与弹窗取消共用
                # MULTI_MATCH_TRIES 这份预算（一局最多回头两次）。prep_read is None 保证只在
                # **还没抽到曲子**时走这条路 —— 抽到了就说明这一局已经在准备页上了，那时回到
                # 选曲页是真出事，仍然认输。
                mp_cancels += 1
                log(f"  匹配散了，回到选曲页 —— 交回通用处理再按一次 确定/自由対戦"
                    f"（第 {mp_cancels}/{MULTI_MATCH_TRIES} 次）")
                rep_s, rep, rep_t0 = None, 0, None
                hand_back = True
            elif (s == "band" and not stop_at_select and starts <= START_RETRIES
                    and rep >= START_SETTLE):
                # 那一按被吃掉了（见 START_RETRIES 处的两局）：页面还停在 乐队确认、红 LEADER
                # 横幅在场，可以再按一次。有界 —— `starts` 记着已经按了几次，每补一次 `rep`
                # 清零，于是补按之间至少隔 START_SETTLE 次读数（约 2 s），不会变成 a14 那 35 下。
                starts += 1
                log(f"  演出开始没反应（第 {starts} 次按）")
                tap(*LIVE_START_BTN, i=inj, hold=0.16)
                rep_s, rep = "band", 0
            elif rep_t0 is not None and time.perf_counter() - rep_t0 >= TAIL_STUCK_S:
                # 无进展逃生（g471，2026-10-07 23:56）：载入是短的，同一个 verdict 连读
                # TAIL_STUCK_S 的页面一定在等人按。那一局演出开始按出去之后，游戏走的是
                # 故事解锁 → 商店 → 结算 流程，最后一个读作 finish 的页面被这里的「只看不按」
                # 挂了 139 s，歌都自己唱完了才到点（放弃后游戏立刻出 rankup/rewards/home）。
                # 交回通用处理 —— 但下面几页的通用处理按的是「开一局」的按钮，分不清真页还是
                # 结算页误读，那几页只能认输，一下都不多按。
                stuck = time.perf_counter() - rep_t0
                if s in TAIL_LIVE_STARTERS:
                    log(f"  {s} 连读 {rep} 次 / {stuck:.0f} s 没变 —— 这一页只能按开一局的"
                        f"按钮，分不清真假，不再等：放弃等 LIVE")
                    return False
                log(f"  {s} 连读 {rep} 次 / {stuck:.0f} s 没变 —— 不再是载入，交回通用处理")
                rep_s, rep, rep_t0 = None, 0, None
                hand_back = True
                nap = 0.3       # 交回通用处理按下的那一键，可能就把页面推进场了
            if not hand_back:
                time.sleep(0.25)
                continue
        if (rep_t0 is not None and s not in WALK_STUCK_KEEP
                and time.perf_counter() - rep_t0 >= WALK_STUCK_S):
            # 通用处理的每一页都有一个「往前走」的按钮，而且每一轮都在按它（result/rank 按
            # (1080,660)、home 按演出、livehome 按激流演出/自由演出…）。同一个 verdict 连读
            # WALK_STUCK_S 秒还是它，就是那一下按不动 —— 要么游戏冻住了（mp19 03:15：帧逐像素
            # 不变、BACK 也不动），要么这一页被读错了、真正的那一页没有按钮在这里。两种情况下
            # 再按下去都只是重复，所以有界地放弃，并把那一帧留下来当证据。
            stuck = time.perf_counter() - rep_t0
            path = f"{subdir(FRAMES)}/walk_stuck_{s}.png"
            Image.fromarray(img).save(path)
            log(f"  {s} 连读 {rep} 次 / {stuck:.0f} s 没变 —— 这一页按不动（不是安静页，"
                f"通用处理每轮都在按它），放弃这一局；存 {path}")
            return False
        if s in ("result", "rank"):
            # 多人 排名页的 下一步 就落在这个坐标上（实测按钮 x1012..1265 / y631..691），与单人
            # 结算页同一个键，所以两页共用一条走法；尾段（tail）里它也跟 result 一样只看不按。
            # 排名页会一直等这一按：mp2 录像里那 803 帧静止是用户自己没点（他 2026-10-08 说的），
            # 不是页面会自己走 —— 所以这一按是必须的，别把它挪进安静页。
            tap(1080, 660, i=inj)          # 下一步
        elif s == "select":
            if on_select is not None:
                r = on_select()
                if r == "wait":
                    # Not a page to act on: 确定 stays unpressed, because the frame may be a
                    # 结算 page whose blue 下一步 classified as this one, and there is no chart
                    # under the page to start. The callback's own confirm loop paces the ruse
                    # out, so the only cost of a wait is a slower walk.
                    rep_s, rep = None, 0
                    time.sleep(0.5)
                    continue
                on_select = None
                if not r:
                    return False
            if _once("决定"):
                tap(*SONG_GO, i=inj)       # 确定
        elif s == "preset":
            tap(510, 573, i=inj)           # 关闭, so no display preset is applied
        elif s == "band":
            if stop_at_select:
                # 走回家的路上，乐队确认页只是路过（或者上一局没退干净停在这里）——**不许**按
                # 演出开始：那会把「回家」走成「开打」，然后 `tail` 只观望、游戏又没进 LIVE，
                # 一路空转到超时（g446 的第二半就是这一下：15:27:54 又按了一次）。
                # 但这里也不该死等：左上角那个返回箭头就是回 乐曲选择（用户 m02645，见 BAND_BACK）。
                # 有界地按它（BAND_BACK_TRIES 次），按不动就回到老行为 —— 只观望，把这一页交给
                # 上面的 TAIL_STUCK_S 逃生。
                if back_taps < BAND_BACK_TRIES:
                    back_taps += 1
                    log(f"  回家路上停在乐队确认页 —— 按左上角的返回箭头（第 {back_taps} 次）")
                    tap(*BAND_BACK, i=inj)
                elif back_taps == BAND_BACK_TRIES:
                    back_taps += 1   # 只抱怨一次，之后每一轮都安静观望
                    log("  回家路上停在乐队确认页 —— 返回箭头按了没动，只观望，不按演出开始")
                time.sleep(0.25)
                continue
            # 加成火力 gate (用户 m13786 / m26442): a LIVE spends up to 3 points for the extra item
            # reward, the readout is on this page, and 消耗LB 就在 LIVE START 左边 —— 所以这里不再
            # 「等够再打」，而是**按读数把档位拨到该去的那一档**（用户 m26442）：读数 ≥ 门槛就拨
            # 3 档、不到就拨 0 档，然后照常开打。Three deliberate choices live in these few lines:
            #   * only a **clean** reading picks a tier. A frame that does not read (a transition, a
            #     popup over the readout) is played through **without touching 消耗LB** -- "有任何不确定
            #     也可以打，损失不大" -- so a classifier that breaks on some future frame can never
            #     strand a round forever, nor silently burn fire it could not count.
            #   * 3 档只在**读得出够 3 点**时才拨：弹窗自己的红字写着「如果持有数量未达到设置的消耗
            #     数量，将消耗持有的全部数量」—— 1~2 点火上 3 档就是把它们全烧掉，而那正是用户要
            #     「小于 3 切 0 档」的用意（`max(min_fire, LB_LEVEL_HIGH)`）。用户 m27090 把这句钉死：
            #     **门槛就是 3 —— 3 点及以上拨 3 档，1~2 点一律拨 0 档**，`min_fire` 填 1/2 也按 3 算。
            #   * 拨完档重新抓一帧确认还站在乐队确认页，不是就交回主循环：`set_live_boost` 自己
            #     保证弹窗关掉了，但页面万一变了，这一下 LIVE START 就按在了别处。
            if min_fire > 0:
                got = fire_power(img)
                if got is None:
                    log("  火力读数不可用，按能打处理 —— 不动 消耗LB，直接开打")
                else:
                    want = (LB_LEVEL_HIGH if got[0] >= max(min_fire, LB_LEVEL_HIGH)
                            else LB_LEVEL_LOW)
                    log(f"  火力 {got[0]}/{got[1]}（门槛 {min_fire}）—— 消耗LB 拨 {want} 档")
                    set_live_boost(want, inj, log=log, grabber=read)
                    img = read()
                    s = screen(img)
                    if s != "band":
                        log(f"  拨完 消耗LB 之后读到的是 {s} —— 这一帧不按，交回主循环")
                        rep_s, rep = None, 0
                        continue
            starts += 1
            log(f"  {'自由对战' if multi else '演出开始'}按下（第 {starts} 次）")
            tap(*LIVE_START_BTN, i=inj, hold=0.16)
            # The song's audio starts about a second after the field appears, and the page stays
            # recognisably 难度选择 through the fade, so this nap is the gap that tells a tap that
            # worked from one that did not. Shortening it to chase field_seen made a14 fire 35
            # 开始Live taps into a load; the `tail` flag is the other half of that lesson -- the
            # walk stops tapping entirely once this one goes out and only watches for the field.
            # But how fast it watches is now the whole margin: the field went missed for 2.2 s
            # after the fade in t04, one 1.6 s nap too many, and the opening chord is due at
            # chart +2.56. Watching at 0.3 s hands the anchor about 1.5 s of that back.
            tail = True
            nap = 0.3
        elif s == "lbpopup":
            # 消耗LB 弹窗不该停在这里（`set_live_boost` 一定把它关掉才回来），但它一旦开着，
            # `screen()` 就会把这一页读成 `select`、走查会去按 決定（真机实测：2026-10-11 弹窗
            # 没盖住右下角的 LIVE START）。所以留一条**有界**的收场：按 OK 关掉它，最多 LB_TRIES
            # 次，之后只观望 —— 绝不去碰那四行档位（那是用户在游戏里自己选的东西）。
            if lb_taps < LB_TRIES:
                lb_taps += 1
                log(f"  撞见 消耗LB 弹窗（第 {lb_taps}/{LB_TRIES} 次）—— 按 OK 关掉")
                tap(*LB_OK, i=inj)
            elif lb_taps == LB_TRIES:
                lb_taps += 1   # 只抱怨一次，之后每一轮都安静观望
                log("  消耗LB 弹窗还在 —— 只观望，不再按")
            time.sleep(0.25)
            continue
        elif s == "options":
            if stop_at_select:
                # 演出 (演出前选项设置) 也是「开一局」的按钮，回家路上一样不许按。
                log("  回家路上停在演出前选择页 —— 只观望，不按演出")
                time.sleep(0.25)
                continue
            tap(*PERFORM, i=inj, hold=0.16)
        elif s == "failed":
            tap(*BACK_TO_SELECT, i=inj)
        elif s == "livehome":
            # 多人入口是右方 激奏演出（MULTI_LIVE_TILE），单人（含走回家的那趟）是左方 自由演出。
            if multi and not stop_at_select:
                log("  演出首页：按右方 激奏演出（多人入口）")
                tap(*MULTI_LIVE_TILE, i=inj)
            else:
                tap(*FREE_LIVE, i=inj)
        elif s == "home":
            tap(*LIVE_TILE, i=inj)         # 演出, the neon tile at the bottom right of 首页
        elif s == "rewards":
            tap(*MODAL_CLOSE, i=inj)       # 关闭 only; no reward tile is ever tapped
        elif s == "story":
            tap(*STORY_CLOSE, i=inj)       # 关闭 only; the story card itself is never tapped
        elif s == "exp":
            # 再次演出: back to 乐曲选择 (through a LIVE BOOST tip any tap dismisses), the same
            # song left selected -- measured 2026-09-29, and in solo that is the way home.
            #
            # 多人 paints two layouts of this page: 详情/下一步, which the five member cards carry
            # (`_exp_cards`), and 主页/再次演出, which carries no cards. Both are the same button at
            # the same point, and the user settled the one thing the mp2 recording could not
            # (2026-10-08): in 多人 再次演出 also goes back to 乐曲選択, it does not re-queue a match.
            # So this presses either layout at once -- no watch, no wait.
            tap(*EXP_RETRY, i=inj)
        elif s == "purchase":
            tap(*PURCHASE_CANCEL, i=inj)   # 取消 only; 购买 is never tapped
        elif s == "shop":
            tap(*SHOP_HOME, i=inj)         # the house icon; no 购买 pill and no tab is tapped
        elif s == "rankup":
            tap(*rankup_ok(img), i=inj)    # OK, wherever this layout paints its pill
        elif s == "pause":
            tap(*RETRY_BTN, i=inj)         # 重试: a fresh LIVE, never a mid-song resume
        elif s == "confirm":
            tap(*RETRY_OK, i=inj)          # 重试 on the confirmation; 取消 is left alone
        elif s == "finish":
            tap(640, 400, i=inj)         # the rank splash has no buttons; any tap advances
        elif s == "event":
            # 活动主页（挑战演出活动）。它两颗蓝按钮里的「挑戦演出」要花 10 CP，而这里的每一条
            # 自动流程都没有「从活动开局」这一说 —— 一按就是替玩家开一局没人排过曲的 LIVE。
            # 所以只报一次名、留一帧，然后放弃：比按对了更重要的，是在不认识的地方不动手。
            Image.fromarray(img).save(f"{subdir(FRAMES)}/start_live_event.png")
            log("  停在活动主页（挑战演出活动）：不是任何流程的入口，一个按钮都不按 -> "
                "research/frames/start_live_event.png")
            return False
        else:
            # A page can be unreadable for the few hundred ms of its own transition, so one bad
            # frame is not evidence; only a sustained run of them means we are actually stuck.
            unknown += 1
            log(f"  unreadable screen ({unknown}/8)")
            if unknown >= 8:
                Image.fromarray(img).save(f"{subdir(FRAMES)}/start_live_stuck.png")
                log("  stuck on an unreadable screen -> research/start_live_stuck.png")
                return False
        time.sleep(nap)
    return False


def page():
    """Where we actually are. Kept as the menu-level half of `screen`, plus the pause dialogs.

    A live field has three bright bars across it that are indistinguishable from a three-button
    dialog, so `which_dialog` only gets a vote once the field is confirmed.
    """
    img = grab()
    s = screen(img)
    if s != "live":
        return s
    d = which_dialog()
    return d if d in ("pause", "confirm") else "live"


def wait_in_live(inj, log=print, timeout=150.0):
    """Drive the state machine until the LIVE is running."""
    return start_live(inj, log=log, timeout=timeout)


def tap(x, y, i, hold=0.12):
    """UI taps need >=0.1 s of contact; a 0.05 s tap is drawn but ignored by the game."""
    rx, ry = to_raw("MEASURED", x, y)
    i.touch_down(0, rx, ry, 1)
    i.syn()
    time.sleep(hold)
    i.touch_up(0)
    i.syn()


# 冷启动的那一页「TAP TO START」：点哪儿都行，但要按满 ~0.12 s（用户 m54615：
# 上一版走查在这一页按的是结算页那颗靠右下的键，位置太靠边，也没等它从开屏动画里出来，
# 最后是用户自己点进去的）。这一页在 `screen()` 里读成 `result`（白字带长得像结算页），
# 所以这里单独一条判据，**只给重开游戏之后用**（`clear_title`），不动那 22 种 verdict。
TITLE_MEAN = (120.0, 200.0)      # 整页亮度：标题页 169，真结算页 87，加载页 >200
TITLE_BAND = (440, 700)          # TAP TO START 那条白带的 y 范围
TITLE_WHITE = 500                # 那一带里某一行至少这么多近白像素
TITLE_TAP = (640, 360)           # 点正中（用户 m54615：点任意位置都行）
TITLE_READY = ("home", "livehome", "select")   # 冷启动该落到的页面
TITLE_TRIES = 20   # 登录页 CG 会让判据在亮帧上反复命中、开屏段偶尔也亮一条窄白带（110 s 采样
                  # 里 2 次）—— 那些都是点空，所以预算给宽一点；真正的上限是 TITLE_DEADLINE
TITLE_WAIT = 1.4
TITLE_DEADLINE = 600.0   # 2026-10-22 实测一次冷启动从 force-stop 到点进登录页花了 178 s
                         # （比 10-21 那次 59 s 慢三倍，模拟器跑了一整天之后更慢）—— 200 s 只剩
                         # 22 s 余量，太险；这一档只在重开时用，等久了没有任何代价
# 冷启动之后第一次进某个页面会定格几秒（安卓把缓存清了，用户 m54800 口述）：同一帧上不补按，
# 落地后也要等画面对齐再交回去 —— 都是「等」，不是「换判据」。
TITLE_FREEZE_STEP = 4      # 帧指纹按 4x4 抽样，只用来判「两帧是不是同一幅」
FREEZE_REPRESS_S = 20.0    # 同一帧上按住等多久才允许补按（冷启动卡顿时补按会落到下一页）
TITLE_SETTLE = 4.0         # 落地后最多等这么久让画面不再变
TITLE_SETTLE_POLL = 0.5   # 实测冷启动到能点 ~52 s、点完再 ~7 s；200 s 是 3 倍余量


def title_screen(img):
    """「TAP TO START」标题页：整页偏亮 + 中下部一条**不满宽**的白带。

    白带右端是标题 logo 那块（不白），所以「x 从 0 起、宽度不到 1150」是关键 —— 加载页
    与厂商 logo 都是整幅白/满宽（宽 1280），结算页那条白带只有二十来像素高、行内近白
    像素不到 500。本地 185 张帧（夹具 + research/frames）普查下来只命中这一页。

    登录页的背景是**动态 CG**（用户 m54750），亮度在 37..214 之间来回跑，所以这一页只会在
    「亮起来的那几帧」命中 —— 调用方必须反复轮询（`clear_title` 每 `TITLE_WAIT` 秒一次），
    不能指望一次性命中；反过来，CG 开屏段偶尔也会亮出一条窄白带（110 s 采样里 2 次），
    在那里按一下没有副作用（点空），预算 `TITLE_TRIES` 兜着。
    """
    a = img[:, :, :3].astype(int)
    m = float(a.mean())
    if not (TITLE_MEAN[0] <= m <= TITLE_MEAN[1]):
        return False
    mx, mn = a.max(2), a.min(2)
    white = (a.mean(2) > 205) & (mx - mn < 30)
    rows = white.sum(1)[TITLE_BAND[0]:TITLE_BAND[1] + 1]
    if not len(rows) or rows.max() <= TITLE_WHITE:
        return False
    y = TITLE_BAND[0] + int(rows.argmax())
    xs = np.where(white[y])[0]
    return bool(len(xs) and xs[0] < 60 and (xs[-1] - xs[0]) < 1150)


def frame_key(img, step=TITLE_FREEZE_STEP):
    """粗指纹：按 `step` 抽样后的字节。只用来判「两帧是不是同一幅」，不当判据用。"""
    return hashlib.blake2b(np.asarray(img)[::step, ::step].tobytes(), digest_size=8).digest()


def _title_settle(log=print, limit=TITLE_SETTLE, poll=TITLE_SETTLE_POLL):
    """等画面不再变（冷启动后刚进去的那一页会定格几秒）。True = 对齐了。"""
    t0 = time.time()
    prev = frame_key(grab())
    while time.time() - t0 < limit:
        time.sleep(poll)
        cur = frame_key(grab())
        if cur == prev:
            return True
        prev = cur
    log(f"  标题页：落地后画面还在变（{limit:.0f} s 没对齐）—— 照常往下走")
    return False


def clear_title(log=print, tries=TITLE_TRIES, wait=TITLE_WAIT, injector=None,
                deadline=TITLE_DEADLINE):
    """重开游戏之后把 TAP TO START 点掉；返回「现在站在一个能用的页面上」。

    冷启动的真实顺序（2026-10-22 用户 m54750 口述 + 本机实测，时间轴见下）：**白屏**
    （安卓冷启动，时快时慢；`screen()` 读 `loading`，整页白、宽 1280）→ **发行商 / 开发商 /
    代理商 logo**（约 1 s 一个，多是白底满宽，读成 shop/result/rank/live 都有）→ **温馨提示**
    （深底）→ **约 1 s 黑屏** → **登录页（背景是动态动画 CG，亮度一直在变）**，等 `TAP TO
    START` 露出来才点得进去 → 能用的一页（`TITLE_READY`）。

    实测一次（tag 无关，`research/experiments/titleprod.py`）：0.9 s 读 loading、16.3 s
    result、31.5 s live、47.0 s band、**52.1 s 才命中标题并点正中第 1 下**、59.1 s 落到
    select —— 所以「等」必须按落点判，不能按时间判。

    两条由此定下的规矩：既不能「看到不是标题就走」（那会在动画里就往回走，正是上一版按到
    屏幕边上的原因），也不能「连续两次读数一样就算过」（动画里 `other` 能连着读两次）。
    判据只认落点：见到标题就点，落到 `home`/`livehome`/`select` 才算过，其余一律继续等。

    两件事要耐心（2026-10-22 用户 m54800）：① 重开之后头一次进某个页面（比如乐曲选择）
    会**定格几秒**，缓存被清掉了；所以同一帧上不补按（补按会落到解冻后的下一页上），
    落地后还要等画面不再变（`_title_settle`）才交回去。② 不手动换曲的话，重开之后
    乐曲选择**还停在上一首**上 —— 所以「用户把游戏停在选曲页 = 用画面停着的那首」这条
    规矩在重开之后同样成立，不需要重新选曲。
    """
    own = injector is None
    inj = injector or MTouch(log=lambda *_: None)
    t0 = time.time()
    taps = 0
    said = 0.0
    last_key = None      # 上一次按下去时那一帧的指纹
    try:
        while time.time() - t0 < deadline:
            img = grab()
            if title_screen(img):
                key = frame_key(img)
                if key == last_key:
                    # 同一帧上不补按：冷启动卡在那里时按下去，等解冻就落到下一页了
                    if time.time() - said >= 5.0:
                        said = time.time()
                        log("  标题页：画面定格（冷启动），这一帧上不再补按，等它动")
                    time.sleep(wait)
                    continue
                if taps >= tries:
                    log(f"  !! 标题页点了 {taps} 下还没进去 —— 交回走查")
                    return False
                taps += 1
                last_key = key
                log(f"  标题页 TAP TO START：点正中 {TITLE_TAP}（第 {taps} 下，按住 0.15 s）")
                tap(TITLE_TAP[0], TITLE_TAP[1], inj, hold=0.15)
                time.sleep(wait)
                continue
            s = screen(img)
            if s in TITLE_READY:
                log(f"  标题页：过了（现在是 {s}）" + (f"，点了 {taps} 下" if taps else ""))
                _title_settle(log)
                return True
            if time.time() - said >= 15.0:
                said = time.time()
                log(f"  标题页：还在开屏/加载（读到 {s}），继续等")
            time.sleep(wait)
        log(f"  !! 等了 {deadline:.0f} s 还没站到能用的页面上 —— 交回走查")
        return False
    finally:
        if own:
            try:
                inj.close()
            except Exception:                                    # noqa: BLE001
                pass


def anchor(log, notes, judge_y=JUDGE_Y, timeout=40.0, field_seen=None):
    """The manual calibration sweep's two-stage vote -- not the run path's clock.

    The unbounded vote needs ~70 blobs before the true alignment outvotes the intro's aliases
    and then three agreeing answers to lock -- by which time note 1 is long gone, and every
    trial of the first sweep ended in 'already passed'. Bounded to the window the audio could
    have begun in, the correct start is the plurality from the first dozen blobs, and two
    agreeing answers are the lock.

    It deliberately does NOT share player.play()'s numbers any more, and this docstring used to
    claim it did: the windows here are [field-6, field+2] then [field-5, field+30] (wider to the
    left, because the sweep walks in from a pause panel and has no fresh field stamp), and the
    feed is anchor_vote's default tap mask, where the run path's opening vote passes sprite_blobs
    since 2026-10-07. Only calib.trial() calls this, and trial() is only reachable from this
    file's __main__, so nothing in the run path reads it -- but a sweep that measures the offset
    on a feed which locks seconds later than the shipped one is a different instrument, so the
    divergence is stated here rather than papered over.
    """
    if field_seen is None:
        t0, _ = anchor_vote(frames, notes, seconds=timeout, judge_y=judge_y, log=log)
        return t0
    t0, _ = anchor_vote(frames, notes, seconds=12.0, min_votes=5, judge_y=judge_y,
                        lo=field_seen - 6.0, hi=field_seen + 2.0, stable=2, margin=1, log=log)
    if t0 is None:
        t0, _ = anchor_vote(frames, notes, seconds=max(timeout - 12.0, 10.0), judge_y=judge_y,
                            lo=field_seen - 5.0, hi=field_seen + 30.0, log=log)
    return t0


def _pills(img):
    """Centres of the bright ~250-px pills on the judgment-line row, left to right.

    One detector for every dialog: the pause panel's three (356/640/923), the two-button dialogs'
    pair (502/785), and 应用默认设置's own pair. The row is the one the judgment lines occupy, and
    the width window is what keeps the song list's album art and the select page's difficulty pills
    out of it -- those are not 180..320 px wide at this row, and they are not this bright.
    """
    a = img.astype(int)
    col = (a[555:600, :].sum(2) > 430).mean(axis=0) > 0.5
    runs, start = [], None
    for x in range(len(col)):
        if col[x] and start is None:
            start = x
        elif not col[x] and start is not None:
            runs.append((start, x - 1))
            start = None
    if start is not None:
        runs.append((start, len(col) - 1))
    return [(s + e) / 2.0 for s, e in runs if 180 <= e - s + 1 <= 320]


def _pills_at(img, *centres):
    """True when the pills on that row are exactly these centres (within 6 px)."""
    found = _pills(img)
    return len(found) == len(centres) and all(abs(p - c) <= 6 for p, c in zip(found, centres))


def _dialog(img):
    """The pause panel or the 重试 confirmation, or None.

    A paused LIVE cannot be told from a menu by its background -- the scrim dims the judgment
    lines below every magenta threshold, so screen() reads the whole page as 'other' -- and that
    is what stranded every multi-trial run: the field was there, the walk just could not see it.
    The dialog is identified by its own geometry instead, bright ~250-px pills on the row the
    judgment lines occupy. Three at 356/640/923 is the pause panel. Two at 502/785 is a
    two-button dialog, and only the 重试 confirmation is claimed here, by its 2-character title:
    应用默认设置 (关闭/OK) and the deck's 确认更换 (不保存并返回/保存并返回) wear the same two
    pills, and both are left to the earlier blue-OK check that taps their LEFT pill -- answering
    them at the 重试 coordinates would adopt a display preset or save a deck.
    """
    if _pills_at(img, *PAUSE_PILLS):
        return "pause"
    if _pills_at(img, *PRESET_PILLS):
        t = img[115:155, 200:1080]
        cols = np.flatnonzero((t.min(2) > 170).any(0))
        if len(cols) and cols.max() - cols.min() + 1 <= 80:
            return "confirm"
    return None


def which_dialog():
    """The dialog a paused LIVE is showing, from a fresh frame.

    'unknown' on a running field is the answer that matters: a clean field's judgement band has
    no 250-px pills at these exact centres, so nothing here fires on pixels that are not a dialog.
    """
    return _dialog(grab()) or "unknown"


def ensure_restarted(inj, log=print):
    """Get the LIVE back to t=0 via the free 重试, from any screen."""
    for _ in range(5):
        p = page()
        if p == "pause":
            tap(*RETRY_BTN, i=inj)
            time.sleep(1.0)
        elif p == "confirm":
            tap(*RETRY_OK, i=inj)
            return True
        elif p == "live":
            pause_if_live(inj, log)
        else:
            return wait_in_live(inj, log)
    return page() == "confirm"


def restart_to_t0(inj, log=print, rounds=8):
    """Pause the running LIVE and 重试 it back to t=0, returning the host time of the 确定 press.

    This is the restart anchor: three retries inside one LIVE (research/archive/media/retry_probe1.mp4) put
    note 1's crossing at [last confirm frame]+2.721/+2.703/+2.713 s and [field back up]+2.571/
    +2.579/+2.579 s -- a fixed song position with ~10 ms of spread, wherever the song was paused.
    The caller turns the returned time into t0 = T + delta and then needs no intro pixels at all.

    Only three gated taps ever go out: the top-right pause corner (only while the field is sampled
    up), the 重试 pill of the pause panel, and 确定 on its confirmation. 取消 is never touched.

    **Solo only.** 2026-10-10 用户 m13106：多人的房间 LIVE 右上角没有暂停按钮（匹配完毕后要
    提前退出只能关掉游戏进程），所以这条重开在房间里按不到 —— `run.py` 的 `_to_t0` 在
    `args.multi` 时直接落到开场投票，一个字节都不发（`mp13` 那一次「第 2 次暂停之后才出来」
    是 2026-10-08 的旧观察，已被用户的口述取代）。

    The pause corner gets at most two taps. `pause_if_live` sleeps and returns True whatever the
    screen did afterwards -- it fires, it does not confirm -- and g291/g292/g293 each read `live`
    once, took that as "nothing to restart from", and fell back to the intro vote an already-running
    LIVE cannot win: the lock landed at chart +6 s with ten notes past, and every one of those three
    rounds spent its first attempt on the 出生即废 fence. A second tap after the panel is *still*
    not up is a re-press this function has to earn by looking first, which is what the loop does.
    """
    if in_live() and not pause_if_live(inj, log):
        return None
    taps = 1
    for _ in range(rounds):
        p = page()
        if p == "pause":
            tap(*RETRY_BTN, i=inj)          # 重试
            if taps > 1:
                # Worth a line only when the first tap did not take: that is the case that used to
                # be read as "nothing to restart from" and cost the round its first attempt.
                log(f"  暂停面板在第 {taps} 次暂停之后才出来")
            time.sleep(0.8)
        elif p == "confirm":
            t = time.perf_counter()
            tap(*RETRY_OK, i=inj)           # 确定
            log(f"  重试 确定 pressed at host {t:.3f}")
            return t
        elif p == "live":
            if taps >= 2:
                log("  LIVE is up with no dialog - nothing to restart from")
                return None
            taps += 1
            log(f"  按过暂停，画面却还是 LIVE -- 暂停面板没等到，补按一次（第 {taps - 1}/1 次）")
            if not pause_if_live(inj, log):
                return None
        else:
            log(f"  no pause panel to restart from (on {p!r})")
            return None
        time.sleep(0.4)
    log("  the 重试 confirmation never appeared")
    return None


# Seconds from the restarted field (magenta judgement lines visible again after 確定) to chart t0.
# Measured: the votes that locked g006/g007 landed at t_field+0.0464 and t_field+0.0455, and the
# probe video's three restarts read the same gap as 0.045-0.054. Used both as the vote window's
# centre offset and as the fallback play clock when no vote can lock at all (see run.py).
FIELD_TO_AUDIO = 0.045


def relock(notes, t_ok, delta=0.25, offset=-55.0, pre=20.0, log=print, timeout=1.5, dump=None):
    """Re-derive t0 from the falling notes after a 重试 restart, around the restarted field.

    The restart anchor's press+delta clock wanders run to run by up to 60 ms -- the game's own
    input-sampling and audio-buffer latency, which no press timestamp can see. Drift probes
    (locked note lateness) across t06-t11 read +32/+27, -4/+4, +8/+27, -12/-10, +19/+18,
    +51/+47 ms, and t12's read +114/+129: tonight's chain is drifting upward, and at +114 the
    presses ride into the GREAT-FAST zone for a 580-GREAT run. The vote done from actual pixels
    has no such error term -- it is how every AP run locked. So the restart supplies the frame
    (song restarts at a fixed position, seconds before note 1); the clock comes from the notes.

    The vote's histogram window centres on `t_field` + one calibrated constant, +-0.22 s wide;
    the window comment below has the reasoning. `prior` = t_ok + delta remains as the fallback
    centre and as the number the log compares the lock against.

    Also stamps `t_field`: the first frame after the press whose band shows the magenta lines
    again, i.e. the restarted field is painted. That is the landmark proposal from the 2026-09-29
    session ("点击重试后检测品红色判定线的出现作为锚点"), and tonight's numbers promoted it from
    a diagnostic to the window's anchor: it read +0.316 s on t12 against a probe constant of
    +0.325, ~10 ms in agreement, while the press->audio chain wandered 100 ms across the same
    two runs.

    The feed is every judged sprite's bright bar (detect.sprite_blobs), not the tap mask: 唱 opens
    with two long notes at 3.64 s and 0056_03 with long x4 + trace x7, and note_blobs -- one flat
    pale blue -- saw 0 of them in all 16 recorded 0056_03 relocks, so this vote ran on an empty
    window and every one of those runs played the t_field fallback. On the 2026-09-30 0056_03
    opening recording the strips implied the right crossings to -8..-25 ms on the same y-shaped
    curve the tap blobs live on.

    Returns (t0 or None, t_field or None). None for t0 means "keep press+delta": the vote must
    fail safe and never move the clock on a bad frame.
    """
    prior = t_ok + delta
    t_field = None
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        t, img = frames()
        if _magenta_back(img):
            t_field = t
            break
    if t_field is not None:
        log(f"  relock: judgement lines back {t_field - t_ok:+.3f}s after 確定 "
            f"(prior t0 {prior:.3f})")
    else:
        log(f"  relock: no judgement lines within {timeout:.1f}s of 確定 - field lagging?")
    first = min(n[0] for n in notes)
    # The fire loop's first press is due at t0 + (first - pre) on the judgement clock and rides
    # the offset lead (-55 ms -> +0.055 s), so with `prior` as t0 it lands at prior+2.56 for
    # 焚音打. The vote is only allowed to run until 0.40 s before that: a vote still thinking
    # when note 1 needs the clock hands back press+delta, never a late lock.
    deadline = prior + first - pre / 1000.0 - offset / 1000.0 - 0.40
    left = deadline - time.perf_counter()
    if left < 0.35:
        log(f"  relock: only {left:.2f}s before the first press is due - not voting")
        return None, t_field
    # The window centres on the field stamp when we have it, not on press+delta: the stamp is
    # taken after the reset pipeline has already run, so what is left to wander is only the
    # field->audio gap -- read at 0.054 s on t12 and 0.045-0.051 s across the probe video's
    # three restarts -- instead of the whole press->audio chain, which read +51 ms on t11 and
    # +114/+129 ms on t12's probes and is drifting upward tonight. A degraded pipeline moves
    # the field paint and the audio together, so t_field+0.045 tracks the drifts that broke
    # press+delta; if the lines never came back, press+delta is all we have. +-0.22 stays clear
    # of the opening feed's one rival family -- a long note's tail votes land ~0.30 s after its
    # head -- by ~0.09 s.
    centre = t_field + FIELD_TO_AUDIO if t_field is not None else prior
    lo, hi = centre - 0.22, centre + 0.22
    log(f"  relock: voting the field in [{lo:.3f}, {hi:.3f}], deadline {deadline:.3f}")
    # min_dets/min_votes are for a feed that is one chord: the opening note plus its partner,
    # one or two blobs per 40 ms sample. t12's vote was silent because it needed twenty of
    # those before it would look; the consecutive-agreement acceptance is what keeps a small
    # count honest, not the count itself. Five samples, not eight: at the opening feed's
    # ~4.5 blobs/s the eighth sample arrived at +1.8 s on t15 and exactly one answer fitted
    # before the deadline, so stable=2 was unreachable and the run kept a clock 95 ms stale.
    # And min_votes=5 with five samples means every blob on screen must match one note -- on
    # t16's three attempts the first vote peaked 4/4/3 and was rejected, while the accepted
    # second vote agreed with it to 7-10 ms: the gate, not the data, was the failure. Four of
    # five is a 4-blob alignment claim in a +-0.22 s window whose rival (a long note's tail)
    # ties by design, and the consecutive-agreement chain is what keeps it honest.
    t0, dets = anchor_vote(frames, notes, seconds=left, lo=lo, hi=hi, min_votes=4,
                           min_dets=5, stable=2, tol_s=0.030, margin=1, log=log,
                           blobber=sprite_blobs)
    if dump is not None:
        # The blobs the vote actually ate, so a failed window is diagnosable offline: t12 lost
        # its lock with no vote line printed at all, which says either the feed never reached
        # min_dets or nothing in the window matched -- and only the raw dets can tell which.
        json.dump({"t_ok": t_ok, "t_field": t_field, "prior": prior, "lo": lo, "hi": hi,
                   "deadline": deadline, "t0": t0, "dets": dets, "notes": notes},
                  open(dump, "w", encoding="utf-8"))
        log(f"relock blobs -> {dump}")
    if t0 is None:
        log("  relock: no lock - keeping press+delta")
        return None, t_field
    log(f"  relock: locked t0 {t0:.3f} = 確定 + {t0 - t_ok:.3f}s "
        f"({1000.0 * (t0 - prior):+.0f} ms vs press+delta), {len(dets)} blobs")
    return t0, t_field


def fire(inj, hits, args, t0, log):
    """Run the scheduled actions, returning how late each one actually fired (ms)."""
    late = []
    respawn0 = inj.respawns
    actions = build_actions(hits, args.judge_y, args.pre, args.hold, 90)[0]
    for tm, op, slot, x, y in actions:
        target = t0 + tm / 1000.0
        while True:
            rem = target - time.perf_counter()
            if rem <= 0:
                break
            if rem > 0.003:
                time.sleep(rem - 0.002)
        late.append((time.perf_counter() - target) * 1000.0)
        rx, ry = to_raw("MEASURED", x, y)
        if op == "down":
            inj.touch_down(slot, rx, ry, slot + 1)
        elif op == "move":
            inj.touch_move(slot, rx, ry)
        else:
            inj.touch_up(slot)
    for s in range(8):
        inj.touch_up(s)
    late.sort()
    if late:
        log(f"  fired {len(actions)} actions, schedule error "
            f"min {late[0]:+.1f} / p50 {late[len(late)//2]:+.1f} / max {late[-1]:+.1f} ms")
    if inj.respawns != respawn0:
        # A respawn costs ~200 ms, which is a hole in the schedule, not a hiccup.
        log(f"  !! injector pipe respawned {inj.respawns - respawn0}x mid-burst "
            f"(p50/p90 are meaningless for this trial)")
    return late


def trial(inj, hits, notes, args, offset, log):
    """Restart the LIVE, anchor, fire the first len(hits) notes at `offset`, pause, read score."""
    from PIL import Image

    for attempt in range(3):
        if not ensure_restarted(inj, log):
            log("  could not reach the retry confirmation")
            return None
        # Open the burst on a provably fresh channel: contacts lifted and echoed back by the
        # device, so a stale socket or a finger still down from the last trial cannot hole
        # note 1. The song's silent intro is the only cheap place to pay for it.
        inj.reset()
        inj.respawns = 0
        # Stamp the first sighting of the fresh field, exactly as run.py does: the tight vote
        # window is built around it and without it the anchor is the slow unbounded one.
        field_seen = None
        end = time.perf_counter() + 20.0
        while time.perf_counter() < end:
            t, img = frames()
            if screen(img) == "live":
                field_seen = t
                break
            time.sleep(0.2)
        t0 = anchor(log, notes, judge_y=args.judge_y, timeout=args.anchor_timeout,
                    field_seen=field_seen)
        if t0 is not None:
            break
        log(f"  anchor attempt {attempt + 1} failed, restarting")
        pause_if_live(inj, log)
    else:
        log("  ANCHOR FAILED 3x")
        return None

    vote = t0
    # Same convention as player.py: a positive offset fires earlier.
    t0 -= offset / 1000.0
    first = t0 + notes[0][0]
    log(f"  vote={vote:.3f} t0={t0:.3f} note 1 at {first:.3f} "
        f"slack={first - time.perf_counter():+.2f}s")
    if first < time.perf_counter():
        log("  anchor resolved after note 1 had already passed, skipping this trial")
        return None
    fire(inj, hits, args, t0, log)

    time.sleep(args.settle)
    # Read the score BEFORE pausing: the 暂停 overlay dims and blurs everything behind it,
    # including the LIVE SCORE counter, so a post-pause crop is unreadable.
    img = grab()
    tag = f"{int(offset):+04d}".replace("+", "p").replace("-", "m")
    Image.fromarray(img).save(f"{subdir(FRAMES)}/calib_{tag}_full.png")
    Image.fromarray(img).crop(SCORE_BOX).resize((720, 172), Image.NEAREST).save(args.out)
    Image.fromarray(img).crop(JUDGE_BOX).resize((616, 188), Image.LANCZOS).save(
        f"{subdir(FRAMES)}/judge_{tag}.png")
    tap(*PAUSE_BTN, i=inj)
    time.sleep(1.4)
    log(f"  score crop -> {args.out}")
    return t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hits")
    ap.add_argument("--offsets", default="0", help="comma-separated ms values to try")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--pre", type=float, default=20.0)
    ap.add_argument("--hold", type=float, default=45.0)
    ap.add_argument("--judge-y", type=float, default=JUDGE_Y)
    ap.add_argument("--settle", type=float, default=0.30)
    ap.add_argument("--anchor-timeout", type=float, default=30.0)
    ap.add_argument("--fastcap", action="store_true",
                    help="MuMu's renderer SDK for every frame, the same source a --fastcap run "
                         "plays on. The offset it needs is not the one screencap needs: the "
                         "anchor's t0 absorbs the capture path's lag, and screencap lags by the "
                         "~55 ms the old offset was cancelling")
    ap.add_argument("--out", default="research/calib_score.png")
    args = ap.parse_args()

    all_hits = json.load(open(args.hits, encoding="utf-8"))
    hits = all_hits[: args.limit]
    # The vote has to be able to name every note on screen, not just the ones this trial fires,
    # or a --limit burst anchors on the wrong note.
    notes = [(h["t_ms"] / 1000.0, h["lane"]) for h in all_hits]
    offsets = [float(v) for v in str(args.offsets).split(",")]
    print(f"{len(hits)} notes x {len(offsets)} offsets: {offsets}", flush=True)

    raise_timer_resolution()
    if args.fastcap:
        import detect
        import mumucap

        mumucap.install()
        detect.SOURCE = mumucap.source
    inj = MTouch()
    def log(m):
        print(m, flush=True)
    try:
        if not wait_in_live(inj, log):
            log("cannot reach a running LIVE")
            raise SystemExit(1)
        for k, off in enumerate(offsets):
            args.out = f"{subdir(FRAMES)}/calib_{int(off):+04d}.png".replace("+", "p").replace("-", "m")
            print(f"--- trial {k + 1}/{len(offsets)} offset {off:+.0f} ms", flush=True)
            trial(inj, hits, notes, args, off, log)
    finally:
        inj.close()
        if args.fastcap:
            import mumucap

            mumucap.uninstall()


if __name__ == "__main__":
    main()
