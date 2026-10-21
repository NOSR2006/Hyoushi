# research/ —— 运行时语料与记录

这是**跑出来的东西**，不是程序。整个目录在 `.gitignore` 里（只有 `experiments/` 下 77 个被
`git add -f` 钉住的证据脚本例外）。删掉任何一桶都不会让程序坏掉，丢的是「那一局当时到底
发生了什么」的证据 —— 所以这个目录的价值全在**能不能回头查**，规则也只有两条：

1. **根上只放状态文件**（下节那六个）。新产生的文件一律进桶，别再往根上写 —— 2026-10-20
   收口前根上攒了 2041 个文件（2029 个 `*.out`），就是因为有人把输出目录指成了这里。
2. **每个桶有上限**（`tools/retention.py` 的 `BUDGETS`）。超了先问「这是垃圾、证据、还是内容
   变多了」，再让 `retention.py` 动刀；手动 `Remove-Item` 不是机制。

## 根上的六个状态文件（唯一允许留在根上的东西）

| 文件 | 谁写 | 是什么 |
|---|---|---|
| `results.jsonl` | `panel_core` / `run.py`（设了 `OURNOTES_PANEL` 才写） | 滚动 100 局结算，面板「结算记录」页读它 |
| `results_full.jsonl` | 同上 | 永不裁剪的全量账本；`backfill_log.py` 会往里补历史局 |
| `chain_cal.json` | `run.update_chain_cal` | 跑间链路校准（`corr`，40 条历史）；2026-10-11 起默认不动 |
| `gui_state.json` | `panel_core.save_state` | 面板状态：`next_index` 取号、`last_chart`、`defaults`、多人页与设置页的开关 |
| `digit_templates.json` | `tools/build_templates.py` | 结算页数字的字形点阵模板（`resultread` 用） |
| `retention.dedupe` | `retention.auto()` | 去重的时间戳（六小时一次），不是数据 |

**不要在这里再加名字**：新桶要么进 `BUDGETS` 并写清写入方与保留规则，要么就还在实验期、
进 `experiments/` 或临时目录。

## 各桶

| 目录 | 写入方 | 里面是什么 | 保留规则（`BUDGETS` 的 rule） |
|---|---|---|---|
| `charts/` | `tools/fetch_charts.py`（+ `research/experiments/` 的下载脚本） | `<cid>.raw.json`（上游原样）+ `<cid>.hits.json`（`compile.py` 编译结果）+ `manifest.json`（曲目表）+ `validated.json` + `covers/` | `report`（只量不删）：**程序运行必需**，`--relearn` 的排序也靠它 |
| `runs/` | `tools/rlog.py`（每局 `.detail.log`）、`panel_core` / `run.py`（`<tag>.out`）、`run.py --dump-votes`（`dets_*.json`、`relock_*`）、`countrule` 时代的 `cnt50*.stairs.json` | 一局的全量细节、给人看的分层日志、投票语料 | `junk`（只删面板判据认的调试件）；`dets_`/`relock_` 在 `protected()` 里点名保住 |
| `reports/` | `tools/audit_charts.py`、`tools/check_upstream.py` | 给人看的工具报告（`chart_audit.{json,txt}`、`upstream_check.json`） | 归 `research` 总闸管，没有自己的上限 |
| `logs/` | 面板「导出日志」、`tools/verify.py`（`verify_<时间戳>/`）、`retention.auto()`（`retention.log`）、`run.py`/批次的 `.out` | 文字日志 | `report`（`backfill_log` 靠 `<tag>.out` 补档，永不自动删） |
| `frames/` | `hudwatch`（证据帧，有 `DUMP_MAX` 预算）、`calib`（`nav_stuck_*.png`）、一次性调试脚本 | 调试与取证截图 | `frames`：垃圾照删；取证帧只在 `--media` 且超上限时按「留 `mp*` + 最近 60 张」压 |
| `result/` | `run.py` 每局一张 `result_<tag>.png` | 结算页截图 | `count`：留 `result_mp*` + 最近 40 局 |
| `recordings/` | 手工抓的模拟器录像与抽帧（`mp1/`、`mp2/cap/`） | 多人链路的原始取证 | `media`（最老优先）；注意名义大小按文件名计、实际占盘因硬链接去重更低 |
| `recordings/rec_rec/` 一类模板挖掘语料 | 一次性脚本 | 数字模板的来源帧（模板已抽进 `digit_templates.json`） | 同上 |
| `archive/` | 手工归档（`media/`、`runs/`、`reports/`） | 到期回放语料、被清桶前抢救下来的记录 | `media`；`archive/media/our_survival_open_0930/` 被 `freshfeed.py`/`spritebars.py` 指着，`protected()` 整目录挡住 |
| `experiments/` | 人 | 一次性量测/取证脚本（77 个已入 git，其余纯探索的留在忽略区） | 不进预算表，`retention` 不碰 |
| `upstream/` | `tools/check_upstream.py --verify` | 上游改谱检测的 STAGING（`<cid>.raw.json`） | 同上 |
| `refsrc/`、`refsrc_more/` | 人（手工存的） | 上游播放器的 JS 参考（音符几何、判定模拟器的语义来源） | 同上 |

## 查/清命令

```bash
.venv/Scripts/python.exe tools/retention.py --check      # 只量：九个桶 + 总闸 + .git + 项目根
.venv/Scripts/python.exe tools/retention.py --go         # 删 collect_junk 认的垃圾（debug/stale/pycache）
.venv/Scripts/python.exe tools/retention.py --media      # 再压录像与归档（最老优先，删到上限以内）
.venv/Scripts/python.exe tools/retention.py --dedupe     # 把重复的媒体换成硬链接
.venv/Scripts/python.exe tools/retention.py --auto       # 面板每轮 / run.py 每局收尾走的那一条（不含 media）
.venv/Scripts/python.exe tools/retention.py --gc         # git pack（.git 不属于任何桶）
```

四道保险，任何一条命中就不删：被 git 跟踪的文件、`research/charts/` + `research/refsrc*` +
`evidence/`、`FRESH_S`（600 s）内新写的、投票语料与 `AGENTS.md`/探针里点名过的路径。
`--auto` 还会把「删了几项、去重几个、`research/` 现多大」写进 `research/logs/retention.log`。

## 2026-10-20 收口记

`research/` 根上的 2029 个 `*.out` 搬进 `runs/`，`chart_audit.*`/`upstream_check.json` 搬进
新建的 `reports/`，`observe_obs.json`/`pfg.txt`/`records_export.csv` 归档进
`archive/reports/`，根上一个 0 字节的 `PATH` 删掉。代码随之改的三处见 `AGENTS.md`
的「目录收口」一段。收口只搬家、没有删任何证据；当天的清理交给 `retention.py --go`。
