# Hyoushi — OurNotes 自动演奏

在 **MuMu 安卓模拟器**里替用户打音乐游戏 **OurNotes**：从社区谱面库下载并编译谱面 →
用游戏自己的判定线做视觉锚定、把时钟锁到谱面 t0 → 按编译好的时间用 minitouch 注入触摸 →
读结算页验收。目标是 **ALL PERFECT（AP）**：每个判定物都落在 ±50 ms 内。

- 面板：`启动面板.bat`（Flet / Material 3，仓库里唯一的面板）
- 命令行：`tools/run.py`（一局）、`tools/run.py --multi`（多人激奏演出）
- 回归与牙的索引：`tools/probes/README.md`；一次付清的全套：`tools/verify.py --tier C`
- 给接手 agent 的治理文件：`AGENTS.md`（事实与红线以它为准）

## 风险与边界（先读这一节）

- 这个工具**替用户操作他自己的账号**。游戏服务条款怎么看待自动化操作，风险落在**用户的账号**上，
  与本仓库无关 —— 自己判断要不要用。
- 它**绝不修改游戏资源、绝不花任何货币**；结算页的**达成奖励列表永不点**（唯一合法的是 `关闭`），
  商店的**购买永不点**。这些不是礼貌，是硬红线（`AGENTS.md`「硬规矩」）。
- 它只做一件事：按谱面时间注入触摸、把游戏走回乐曲選択页。它不刷分、不改数据、不碰存档。

## 支持矩阵（超出即不支持）

| 项 | 要求 |
|---|---|
| 系统 | Windows（抓帧走 MuMu 渲染器 SDK；`adb screencap` 是 278 ms 的兜底通道） |
| 模拟器 | MuMu（现役；adb 端点默认 `127.0.0.1:16384`） |
| 分辨率 | 模拟器固定 **1280×720**（分辨率或封装不对时会**拒绝读帧**，不会静默读错） |
| Python | **3.13**，用本仓库自己的 `.venv`（全局环境不算数） |

其他模拟器/分辨率/系统不在支持范围内 —— 判据会拒绝，而不是跑出难查的错。

分辨率不对时**改模拟器、不要改代码**：MuMu 里把分辨率设成 **1280×720**（`工具/设置 → 显示 → 分辨率`，
并确认没有开「自适应/高帧率缩放」之类的封装改写），然后重跑。判据按这个分辨率调过，代码里那几个
常数（`tools/detect.py` 的 `W`/`H`、`tools/compile.py:25` 的 `JUDGE_Y`、透视梯形与色相键）改了会把
别的判据一起弄坏 —— 报错信息也会指回这一节。

## 安装

```bat
:: 1) 克隆之后，在本仓库根目录建环境（解释器用 Python 3.13）
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

:: 2) 装 Flet 的桌面客户端（只有面板要它）
::    flet-desktop 的 Flutter 客户端不在 wheel 里，首次运行会去 GitHub 下 flet-windows.zip
::    （约 40 MB）。国内直连会超时，把 zip 放进
::    .venv\Lib\site-packages\flet_desktop\app\ 即可（或用 FLET_CLIENT_URL 指到镜像）。
::    细节见 docs/python_env.md。

:: 3) 自检路径（见下）
.venv\Scripts\python tools\locate.py
```

**路径**：`adb.exe`、minitouch、MuMu 的渲染器 DLL 都不在仓库里。默认值是本机历史路径
（`D:\MuMuPlayer\...`、`D:/Downloads/...`），换机器用环境变量指到自己的位置：

| 环境变量 | 是什么 |
|---|---|
| `HYOUSHI_ADB` | `adb.exe` 的完整路径 |
| `HYOUSHI_DEVICE` | adb 端点（默认 `127.0.0.1:16384`） |
| `HYOUSHI_MINITOUCH` | minitouch 可执行文件（EvATive7 版） |
| `HYOUSHI_MUMU_ROOT` | MuMu 安装根目录（派生渲染器 DLL 与 SDK 安装路径） |
| `HYOUSHI_MUMUCAP_DLL` / `HYOUSHI_MUMUCAP_INSTALL` | 单独覆盖上面两项派生的结果 |

`tools/locate.py` 会把这些打出来并告诉你缺什么、该设哪个变量；`tools/run.py` 与面板
**开跑前**就校验，缺 adb/minitouch 会当场拒绝（而不是三分钟后以「走页停住」的样子失败）。
渲染器 DLL 缺失**不拦**：`--fastcap` 装不上时自动落到窗口 / adb 抓帧。

**谱面库不在 git 里**（`research/charts/*.raw.json` / `*.hits.json` 是 gitignored 的大件）。
第一次用要自己拉：

```bat
.venv\Scripts\python tools\fetch_charts.py            :: 下载全目录并编译（增量，可 --force）
.venv\Scripts\python tools\fetch_charts.py --pin      :: 记录已验证谱面的钉子（可提交）
```

## 快速开始

游戏（B 站官服 OurNotes）开着、停在任意页面都行（面板自己走页；停在乐曲選択页最省事）。

**面板**：双击 `启动面板.bat`。左边「单人演出 / 多人演出」，右边配参数（连续演出轮数、
断 AP 重试、火力门……），F5 开始。面板与 CLI 共用 `research/gui_state.json` 里的状态。

**命令行**（照抄面板的参数）：

```bat
:: 单人：自己挑谱（--song <musicId>[:难度]），或 --random 让游戏随机抽
.venv\Scripts\python.exe tools\run.py --song 100056:expert ^
  --fastcap --offset 55 --live-push-cap 0 --watch-hud --retry-on-break 5 --tag gNNN

:: 多人（激奏演出）：房间自己抽曲，谱面在準備页上认出来
.venv\Scripts\python.exe tools\run.py --multi ^
  --fastcap --offset 55 --live-push-cap 0 --tag mpNNN
```

四条 CLI 规矩（每条都踩过，细节在 `AGENTS.md`「三分钟上手」）：取号要 fresh 读
`research/gui_state.json` 的 `next_index`；不要设 `OURNOTES_PANEL`；每局超时 ≥900 s；
开跑前只读地认谱（`--song` 是例外，它自己走到那一首）。

## 首次校准

- **`--offset`（名义 +55 ms）是这台机器的测量值**：链路（按下 → 判定）比谱面晚/早多少，
  每台机器不同。想量它就在命令行加 `--read-split`（调试开关）：结算页会多读一次 FAST/SLOW
  直方图，`tools/run.py` 把它折成 `research/chain_cal.json` 里的 `corr`（有效 offset = 名义 +
  corr，默认 corr 让 eff = 45 ms）。默认**不读**（少按一次、少等 2 s），所以 `corr` 平时不动。
  收敛要几局，别用一局的读数下结论。
- 标定脚本在 `tools/probes/`：`fieldcal.py`（场地/判定线几何）、`calibrate_map.py`（MuMu 窗口
  与设备的映射）、`retry_probe.py`（重开锚点）。首次上手建议按这个顺序各跑一遍。
- 每回合（含中途放弃）结束时工具会把游戏**走回乐曲選択页**；回家那趟不会按任何「开打」按钮。

## 目录

| 位置 | 是什么 |
|---|---|
| `tools/run.py` | 一局的全部编排（CLI 入口） |
| `tools/player.py` | 编译动作 + 火把循环 + 中段修正 |
| `tools/calib.py` | 走页认页、暂停→重试锚点、重锁 |
| `tools/detect.py` | 掩码 / blob / 投票（判定线几何的唯一定义在 `tools/compile.py`） |
| `tools/flet_gui.py` / `tools/panel_core.py` | 面板视图层 / 业务逻辑（后者不 import GUI） |
| `tools/locate.py` | 外部路径与环境变量（见上） |
| `tools/retention.py` | 落盘预算：`--check` / `--go` / `--media` / `--dedupe` / `--auto` / `--gc` |
| `tools/verify.py` | 验收编排（默认 F = 开工自检 5 步 13 s；`--tier C` = 发版那一趟 ~11 min） |
| `tools/` | 36 个模块的分工与「加模块之前」的规矩见 `tools/README.md`；52 条回归见 `tools/probes/README.md` |
| `research/` | 工作区：结算记录、链路校准、谱面、帧、录像（**全部 gitignored**，跑起来自己长出来）；每个桶的写入方与保留规则见 `research/README.md` |
| `evidence/` | 回归夹具：钉住的帧、谱面钉子（**不入库**，见下） |
| `docs/` | 面板细则（`panel_spec.md`）、上游格式副本、Python 环境约定 |

仓库里**只放能跑起来的那部分**：`tools/`（程序本体与回归）、`docs/`、`README.md` / `AGENTS.md`、
`requirements.txt`、`启动面板.bat`。下面两类是**本机自备件**，不在仓库里：

- `evidence/` 的夹具帧、`research/` 的一切产物：前者是游戏画面（版权归原方），后者是本机的
  录像、帧、日志与实机记录，体积大且只对这台机器有意义。要跑探针就自己跑一局把帧拍下来，
  按 `tools/probes/README.md` 的口径钉住。
- `research/charts/` 的谱面：`tools/fetch_charts.py` 从上游拉（见「快速开始」）。

## 验证

**默认不跑探针。** 时间预算默认给开发：写完、`py_compile` 过、能起来就进下一步。只有四种情况才跑测试
（细则见 `AGENTS.md` 的「改动怎么验：带牙 + 按需」）：改了判据／守卫／牙本身、改了某个模块的核心行为
（检测阈值、时钟与偏移、注入、走查分支、结算读数）、你要求验、发版前。

```bat
:: 开工自检（编译 + 作用域 + 外部路径 + 窗口钉子 + 谱面钉子，约 13 s；不带参数就是 F 档）
.venv\Scripts\python.exe tools\verify.py

:: 单条回归（看最后一行 PASS/FAIL）
.venv\Scripts\python.exe tools\probes\hudgate.py

:: 只拆一条牙（B 档的常态：改判据就只拆那一条）
.venv\Scripts\python.exe tools\probes\fletpanel.py --teeth tailplace

:: 全套探针（36 条，清单见 tools/probes/README.md；只在发版或怀疑大面积回归时跑）
for %p in (hudgate framewriter freshfeed chartpin navgates spritebars breakstop pushcap tailmargin ^
           paths endpointheal scopes chaincal hudcount logclass roundgap maskfast capreg srcfail recoverwalk counterrec ^
           mtdiag teethretry panelfly launchers paneldata m3tokens fieldstamp retention votereplay watchdog firepath ^
           fletgui fletpanel fletfont fletfly) do @.venv\Scripts\python.exe tools\probes\%p.py
```

- 绝大多数探针**零设备零联网**，本机直接跑。`capreg` / `mtdiag` 需要模拟器 adb 在线。
- `fletfly` / `fletpanel` / `fletfont` 要开真 Flutter 窗口，**必须在真实桌面上跑**（Flet 桌面客户端没有离屏模式）；`fletviewcheck` 的十二面像素基线 2026-10-21 退役（它从 10-09 起一直红着、从没拦过东西）。
- 每条修复都配一个**会 FAIL 的回归**（把守卫关掉重放必须看见差别），不是只打印数字的脚本 —— 这条纪律没有放松。

## 许可证

**保留所有权利（All rights reserved）。** 这是作者的私人工具，**没有**授予任何使用、复制、修改或
分发的许可 —— 仓库可见不等于可以拿去用；想用请先联系作者取得书面许可。

- 仓库里**不含**游戏本体、游戏资源或上游谱面数据（`research/charts/` 是 gitignored 的本地下载结果），
  那些内容的权利属于各自的版权方。
- `requirements.txt` 里的第三方依赖各自适用其原始许可证。
