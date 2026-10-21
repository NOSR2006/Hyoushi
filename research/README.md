# research/ —— 运行时数据与记录

本目录存放程序运行产生的数据，不属于程序本体。整个目录已被 `.gitignore` 排除，
仅 `experiments/` 下经 `git add -f` 明确纳入版本管理的证据脚本除外。删除任一子目录均不影响
程序运行；其价值在于事后查证某一局的实际运行情况。

本目录的维护规则有两条：

1. **根目录仅保留状态文件**（见下节所列六个）。新产生的文件一律写入对应子目录。2026-10-20 整理前，
   根目录曾累积 2041 个文件（其中 2029 个为 `*.out`），原因是某次实现将输出目录指向了此处。
2. **各子目录设有上限**（`tools/retention.py` 的 `BUDGETS`）。超出上限时，应先判断该批文件属于
   无效产物、证据还是数据量增长，再由 `retention.py` 处置。手动使用 `Remove-Item` 不属于既定机制。

## 根目录的六个状态文件

| 文件 | 写入方 | 内容 |
|---|---|---|
| `results.jsonl` | `panel_core`；`run.py`（设置 `OURNOTES_PANEL` 时） | 滚动保留最近 100 局的结算记录，供界面「结算记录」页读取 |
| `results_full.jsonl` | 同上 | 不裁剪的全量记录；`backfill_log.py` 向其补录历史对局 |
| `chain_cal.json` | `run.update_chain_cal` | 基于 40 条历史数据计算的跑间链路校准值（`corr`）；2026-10-11 起默认不再自动更新 |
| `gui_state.json` | `panel_core.save_state` | 界面状态：`next_index` 取号、`last_chart`、`defaults`、多人页与设置页开关 |
| `digit_templates.json` | `tools/build_templates.py` | 结算页数字的字形点阵模板，供 `resultread` 使用 |
| `retention.dedupe` | `retention.auto()` | 去重时间戳（六小时一次），不属于数据 |

本目录不再增加根级文件。新增子目录时，应同时登记至 `BUDGETS` 并说明写入方与保留规则；
仍处于试验阶段的产物，应置于 `experiments/` 或临时目录。

## 子目录

| 目录 | 写入方 | 内容 | 保留规则（`BUDGETS` 的 rule） |
|---|---|---|---|
| `charts/` | `tools/fetch_charts.py`、`research/experiments/` 中的下载脚本 | `<cid>.raw.json`（上游原始数据）、`<cid>.hits.json`（`compile.py` 编译结果）、`manifest.json`（曲目表）、`validated.json`、`covers/` | `report`（仅统计，不删除）：为程序运行所必需，`--relearn` 的排序亦依赖于此 |
| `runs/` | `tools/rlog.py`（每局 `.detail.log`）、`panel_core` 与 `run.py`（`<tag>.out`）、`run.py --dump-votes`（`dets_*.json`、`relock_*`） | 单局完整细节、分层日志、投票语料 | `junk`（仅删除界面判据认定的调试文件）；`dets_`、`relock_` 前缀在 `protected()` 中单独保护 |
| `reports/` | `tools/audit_charts.py`、`tools/check_upstream.py` | 工具报告（`chart_audit.{json,txt}`、`upstream_check.json`） | 由 `research` 总配额管理，不单设上限 |
| `logs/` | 界面「导出日志」、`tools/verify.py`（`verify_<时间戳>/`）、`retention.auto()`（`retention.log`）、`run.py` 与批次的 `.out` | 文本日志 | `report`（`backfill_log` 依赖 `<tag>.out` 补录，不作自动删除） |
| `frames/` | `hudwatch`（证据帧，受 `DUMP_MAX` 预算限制）、`calib`（`nav_stuck_*.png`）、一次性调试脚本 | 调试与取证截图 | `frames`：无效产物照常删除；取证帧仅在 `--media` 且超出上限时压缩，规则为保留 `mp*` 与最近 60 张 |
| `result/` | `run.py`（每局一张 `result_<tag>.png`） | 结算页截图 | `count`：保留 `result_mp*` 与最近 40 局 |
| `recordings/` | 手工采集的模拟器录像与抽帧（`mp1/`、`mp2/cap/`） | 多人链路的原始取证 | `media`（最旧优先）；名义大小按文件名统计，实际占用因硬链接去重而更低 |
| `recordings/rec_rec/` | 一次性脚本 | 字形模板的来源帧（模板已提取至 `digit_templates.json`） | 同上 |
| `archive/` | 手工归档（`media/`、`runs/`、`reports/`） | 到期回放语料、清理前保留的记录 | `media`；`archive/media/our_survival_open_0930/` 为 `freshfeed.py` 与 `spritebars.py` 的输入，由 `protected()` 整目录保护 |
| `experiments/` | 人工编写 | 一次性测量与取证脚本（77 个已纳入版本管理，其余仅保留在忽略区） | 不列入预算表，`retention` 不处理 |
| `upstream/` | `tools/check_upstream.py --verify` | 上游改谱检测的 STAGING（`<cid>.raw.json`） | 同上 |
| `refsrc/`、`refsrc_more/` | 人工保存 | 上游播放器的 JavaScript 参考（音符几何与判定模拟语义的来源） | 同上 |

## 查询与清理命令

```bash
.venv/Scripts/python.exe tools/retention.py --check      # 仅统计：九个目录、总配额、.git 与项目根
.venv/Scripts/python.exe tools/retention.py --go         # 删除 collect_junk 认定的无效产物（debug、stale、pycache）
.venv/Scripts/python.exe tools/retention.py --media      # 压缩录像与归档（最旧优先，删至上限以内）
.venv/Scripts/python.exe tools/retention.py --dedupe     # 将重复媒体替换为硬链接
.venv/Scripts/python.exe tools/retention.py --auto       # 界面每轮与 run.py 每局收尾执行的路径（不含 media）
.venv/Scripts/python.exe tools/retention.py --gc         # 执行 git pack（.git 不属于任何目录配额）
```

删除前设有四道保护条件，任一命中即不删除：已被 git 跟踪的文件；`research/charts/`、`research/refsrc*`
与 `evidence/` 下的内容；`FRESH_S`（600 秒）内新写入的文件；投票语料，以及文档与回归测试中明确引用的路径。`--auto` 还会将删除项数、去重数与 `research/` 当前体积写入 `research/logs/retention.log`。

## 2026-10-20 目录整理记录

`research/` 根目录的 2029 个 `*.out` 已迁入 `runs/`；`chart_audit.*` 与 `upstream_check.json` 已迁入
新建的 `reports/`；`observe_obs.json`、`pfg.txt`、`records_export.csv` 已归档至 `archive/reports/`；
根目录一个 0 字节的 `PATH` 文件已删除。相应地共有三处代码调整，已随该次整理一并落盘。该次整理仅迁移文件，未删除任何证据；当日的清理工作交由 `retention.py --go` 执行。
