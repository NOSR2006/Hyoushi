# tools/ —— 程序本体

一局的全部动作都从这里进出。**业务逻辑不 import 任何 GUI 库**：`panel_core.py` 是纯逻辑，
`flet_gui.py` 是唯一的视图层；CLI 入口是 `run.py`。回归与「牙」在 `probes/`，索引见
[`probes/README.md`](probes/README.md)。

## 入口

| 模块 | 是什么 |
|---|---|
| `run.py` | **一局的全部编排**：走查进 LIVE → 锚定 → 编译 + 注入 → 曲中修正 → 读结算 → 走回家。CLI 入口（`--multi` / `--song` / `--random` / `--walk-home` …） |
| `panel_core.py` | **面板业务层**（不 import tkinter/PySide6/flet）：`RunOrchestrator` 起子进程跑 `run.py`、攒日志、落账本、清理与状态读写 |
| `flet_gui.py` | **唯一的视图层**（Flet / Material 3）。五页：单人演出／多人演出／运行日志／结算记录／设置；细则在 [`docs/panel_spec.md`](../docs/panel_spec.md) |
| `verify.py` | 验收套件：默认 F（开工自检，5 步 13 s）、`--tier C` 发版那一趟；逐条跑真入口、日志落 `research/logs/verify_<时间戳>/` |

## 演奏链路

| 模块 | 是什么 |
|---|---|
| `compile.py` | 谱面 `<cid>.raw.json` → 毫秒级判定物列表（`JUDGE_Y = 570.0` 的**唯一定义**，`detect` 只是 import） |
| `player.py` | 编译成注入动作 + 火把循环（`gc_guard`、迟发记账）+ 中段修正 `LiveCorrector`；`TAIL_MARGIN_MS` / `TAIL_FLICK_LEAD_MS` / `KIND_LEAD_MS` 都在这里 |
| `calib.py` | 认页 `screen()`、走查（首页 ↔ 演出首页 ↔ 选曲 ↔ 准备 ↔ LIVE ↔ 结算）、开局锚定、暂停/重试、LB 拨档、回家 `leave_at_select` |
| `songpick.py` | `--song` 的选曲：列表一格一格走、每格回读 `gameread` 的 musicId/难度才算数 |
| `inject.py` | 原始 event4 多点注入（`/dev/input/event4` 直写，历史实现） |
| `mtouch.py` | **现役**注入：minitouch 后端；`send_bytes()` 是热路径的零分配字节帧 |

## 视觉（全部零 OCR）

| 模块 | 是什么 |
|---|---|
| `detect.py` | 读 LIVE 场地：抓帧、掩码/blob、透视梯形、`vote_t0` / `implied_votes` 时钟投票。**判据常数不许动** |
| `gameread.py` | 读游戏的 乐曲选择 页 / 准备页：当前高亮的 musicId、难度两带、抽中曲封面（NCC） |
| `hudwatch.py` | 曲中 HUD 计数器监视：六/五行布局识别（JUST）、提交与 reject 的证据帧（有预算）、`tally()` |
| `hudread.py` | 把 `hudwatch` 存下的帧再读一遍（离线复核） |
| `resultread.py` | 结算页读数：像素模板 + 字形点阵（`digit_templates.json`），读 P/G/GD/B/M、score、combo |
| `picmap.py` | 没有图像输入时的眼睛：PNG → 字符图 + 图例（`--box` / `--cell` / `--geom`） |
| `build_templates.py` | 从「数字已知」的结算页里切数字模板给 `resultread.py` |

## 捕获

| 模块 | 是什么 |
|---|---|
| `mumucap.py` | **现役**：MuMu 渲染器 SDK 抓帧（8.41 ms/帧），`detect.capture` 的第一选择 |
| `hostcap.py` | WGC 抓 MuMu 窗口（16.7 ms 中位），`--host` 才装；与 `--fastcap` 同用时推迟到 SDK 失败 |
| `recorder.py` | 满帧率读数录像（`--record-counters` 的 `.avi`；计数规则研究与回放用） |

## 数据与网络

| 模块 | 是什么 |
|---|---|
| `fetch_charts.py` | 从 Haneoka 档案下载全部谱面 → `compile.py` → `research/charts/` |
| `sources.py` | 游戏主表（`_fullComboCount` 等）与本地库的对账口径 |
| `check_upstream.py` | 上游是否改过某张谱（`--verify` 会下载到 `research/upstream/` 做 STAGING） |
| `webfetch.py` | 官网文档的取页小工具（agent 用；运行时不 import） |

## 目录与治理

| 模块 | 是什么 |
|---|---|
| `rlog.py` | **`research/` 的布局唯一权威**（各桶路径、两个日志通道、`retarget()`）；探针必须先把这里重绑到夹具 |
| `locate.py` | 外部路径唯一权威：adb / 设备号 / minitouch / MuMu 安装目录与 SDK（`HYOUSHI_*` 环境变量可覆盖，旧 `BANG_*` 仍认） |
| `retention.py` | 落盘预算：九个桶的 `BUDGETS`、四条保险、`--check/--go/--media/--dedupe/--auto/--gc` |
| `watchdog.py` | 夜间看门狗：`StallWatch`（静默 ≥600 s 且还救得起）+ `recover()`（认前台 → 重开 → 走回家） |
| `memguard.py` | 开工前看一眼宿主内存：可用 <6 GB 清缓存后台、<3 GB 让游戏回收堆、<1.5 GB 才重开（多人不重开）。`run.py --no-mem-guard` 关掉 |
| `evidence.py` | 把语料钉成 `evidence/` 夹具与 `MANIFEST.json`（**探针的输入，必须是稳定字节**） |
| `audit_charts.py` | 按「已经咬过我们的失败类型」给全库谱面排风险 → `research/reports/` |
| `backfill_log.py` | 从 `<tag>.out` 把漏记的局补进 `results*.jsonl` |

## 视图基础设施

| 模块 | 是什么 |
|---|---|
| `m3_theme.py` | Material 3 令牌层：46 色彩角色／15 字阶／7 形状／6 高程／6 状态层；`DEVIATIONS` 登记有意偏离 |
| `gen_m3_tokens.py` | 用 `material-color-utilities` 现算 `m3_tokens.json`（别卸这个依赖） |
| `gen_m3_sources.py` | 抓 M3 规范的官方来源生成 `docs/m3_sources.md` |

## 测试替身（产品侧不 import）

| 模块 | 是什么 |
|---|---|
| `_fake_runner.py` | 假的一局：命令行与 `run.py` 一致，给 `panelfly` 等探针跑面板而不碰设备 |
| `_flet_smoke.py` | 无头截图：把五页渲染成 PNG（像素基线与「只重拍变了的那页」都用它） |

## 加模块之前

- 先看 `probes/README.md` 有没有现成的判据可挂；新模块若带外部路径，走 `locate.py`；若写盘，
  走 `rlog.py` 并在 `retention.BUDGETS` 里给它归属。
- 新模块的出口如果有判据意义（守卫、提前量、容差），**必须配一条会红的探针**，否则它只是装饰。
