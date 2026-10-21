# tools/ —— 程序模块

本目录包含项目的全部可执行代码。业务逻辑不依赖任何图形界面库：`panel_core.py` 为纯逻辑层，
`flet_gui.py` 为唯一视图层，命令行入口为 `run.py`。回归测试与反证用例
（内部称「牙」，即关闭对应守卫后必须失败的检验）位于 `probes/`，逐条口径见各文件的 docstring。

## 入口

| 模块 | 职责 |
|---|---|
| `run.py` | 单局全流程编排：导航进入 LIVE、开局锚定、编译与注入、曲中时间校正、结算读数、返回选曲页。命令行入口，支持 `--multi`、`--song`、`--random`、`--walk-home` 等参数 |
| `panel_core.py` | 界面业务层，不引用 tkinter、PySide6 或 flet。`RunOrchestrator` 负责以子进程启动 `run.py`、汇集日志、写入结算记录、清理与状态读写 |
| `flet_gui.py` | 唯一视图层（Flet / Material 3）。共五页：单人演出、多人演出、运行日志、结算记录、设置 |
| `verify.py` | 验收编排。默认执行 F 档（开工自检，5 项，约 13 秒）；`--tier C` 为发版流程。逐项调用真实入口，日志写入 `research/logs/verify_<时间戳>/` |

## 演奏链路

| 模块 | 职责 |
|---|---|
| `compile.py` | 将谱面 `<cid>.raw.json` 编译为毫秒级判定物列表。`JUDGE_Y = 570.0` 的唯一来源，其余模块仅引用 |
| `player.py` | 编译注入动作，执行注入循环（`gc_guard` 与迟发记账），并在曲中运行 `LiveCorrector` 时钟校正。`TAIL_MARGIN_MS`、`TAIL_FLICK_LEAD_MS`、`KIND_LEAD_MS` 均定义于此 |
| `calib.py` | 页面识别 `screen()`、页面导航（首页、演出首页、选曲、准备、LIVE、结算）、开局锚定、暂停与重试、LB 拨档、返回选曲 `leave_at_select` |
| `songpick.py` | `--song` 的选曲实现：逐格遍历列表，每格经 `gameread` 回读 musicId 与难度并核验 |
| `inject.py` | 原始 event4 多点注入（直接写入 `/dev/input/event4`），历史实现 |
| `mtouch.py` | 现役注入后端：minitouch。`send_bytes()` 为热路径的零分配字节帧 |

## 视觉读数

全部读屏功能均不使用光学字符识别，仅依据像素判据。

| 模块 | 职责 |
|---|---|
| `detect.py` | 读取 LIVE 场地：抓帧、掩码与连通域、透视梯形、`vote_t0` 与 `implied_votes` 时钟投票。判据常数不得修改 |
| `gameread.py` | 读取乐曲选择页与准备页：当前高亮的 musicId、难度（双带检测）、抽中曲封面（归一化互相关） |
| `hudwatch.py` | 曲中 HUD 计数器监视：六行与五行布局识别（JUST）、提交与拒绝的证据帧（有预算限制）、`tally()` |
| `hudread.py` | 对 `hudwatch` 保存的帧进行离线复核 |
| `resultread.py` | 结算页读数：像素模板与字形点阵（`digit_templates.json`），读取 PERFECT、GREAT、GOOD、BAD、MISS、score 与 combo |
| `picmap.py` | 无图像输入时的辅助读图工具：将 PNG 转为字符图并附图例（`--box`、`--cell`、`--geom`） |
| `build_templates.py` | 从数字已知的结算页截取字形模板，供 `resultread.py` 使用 |

## 抓帧

| 模块 | 职责 |
|---|---|
| `mumucap.py` | 现役抓帧后端：MuMu 渲染器 SDK（每帧 8.41 ms），为 `detect.capture` 的首选 |
| `hostcap.py` | 以 WGC 抓取 MuMu 窗口（中位 16.7 ms）。仅在指定 `--host` 时启用，与 `--fastcap` 同用时推迟至 SDK 失败之后 |
| `recorder.py` | 满帧率计数器录像（`--record-counters` 生成的 `.avi`），用于计数规则研究与回放 |

## 数据与网络

| 模块 | 职责 |
|---|---|
| `fetch_charts.py` | 自上游档案站点下载谱面，经 `compile.py` 编译后写入 `research/charts/` |
| `sources.py` | 游戏主表（含 `_fullComboCount`）与本地库的对账规则 |
| `check_upstream.py` | 检测上游对某谱面的改动（`--verify` 时下载至 `research/upstream/` 作为 STAGING） |
| `webfetch.py` | 上游文档的取页工具，供开发时使用，运行时不被引用 |

## 目录与治理

| 模块 | 职责 |
|---|---|
| `rlog.py` | `research/` 布局的唯一权威（各目录路径、两个日志通道、`retarget()`）。回归测试须先将此处重绑至夹具 |
| `locate.py` | 外部路径的唯一权威：adb、设备端点、minitouch、MuMu 安装目录与 SDK。可由 `HYOUSHI_*` 环境变量覆盖，旧 `BANG_*` 仍被识别 |
| `retention.py` | 落盘预算：九个目录的 `BUDGETS`、四道保护条件、`--check/--go/--media/--dedupe/--auto/--gc` |
| `watchdog.py` | 长时运行监视：`StallWatch`（静默达 600 秒且仍可恢复时触发）与 `recover()`（识别前台、重新启动、返回选曲页） |
| `memguard.py` | 开局前检查宿主可用内存：低于 6 GB 时回收后台缓存，低于 3 GB 时要求客户端回收堆，低于 1.5 GB 时重启客户端（多人模式不重启）。可用 `run.py --no-mem-guard` 关闭 |
| `evidence.py` | 将语料固定为 `evidence/` 夹具与 `MANIFEST.json`。回归测试的输入必须为稳定字节 |
| `audit_charts.py` | 按已发生过的失败类型对全库谱面评估风险，输出至 `research/reports/` |
| `backfill_log.py` | 自 `<tag>.out` 将漏记的对局补入 `results*.jsonl` |

## 视图基础设施

| 模块 | 职责 |
|---|---|
| `m3_theme.py` | Material 3 令牌层：46 个色彩角色、15 档字体、7 档形状、6 级高程、6 个状态层。有意偏离规范之处登记于 `DEVIATIONS` |
| `gen_m3_tokens.py` | 以 `material-color-utilities` 计算生成 `m3_tokens.json`。该依赖不得移除 |
| `gen_m3_sources.py` | 抓取 M3 规范的官方来源，生成 `docs/m3_sources.md`（该文件不随仓库分发） |

## 测试替身（产品侧不引用）

| 模块 | 职责 |
|---|---|
| `_fake_runner.py` | 命令行与 `run.py` 一致的假运行，供 `panelfly` 等回归测试在不接触设备的情况下驱动界面 |
| `_flet_smoke.py` | 离屏渲染：将五页渲染为 PNG，供界面版式检查与单页重拍使用 |

## 新增模块的约定

1. 先查阅 `probes/` 下同类用例，确认是否已有可复用的判据。
2. 涉及外部路径的，须经 `locate.py` 解析；涉及写盘的，须经 `rlog.py` 定位，并在
   `retention.BUDGETS` 中登记归属。
3. 模块出口若具有判据意义（守卫、提前量、容差），须同时提供一条可失败的回归检验；
   仅有数值输出而无检验的，不视为有效判据。
