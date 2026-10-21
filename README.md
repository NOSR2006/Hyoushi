# Hyoushi

替你在 MuMu 模拟器里自动打 **OurNotes** 的小工具：认出当前是哪首曲子、把节拍对准、自动点击、打完
再把成绩读回来记进表格。目标是 **ALL PERFECT**（每一击都落在游戏判定的 ±50 ms 之内）。

- 跑在 **Windows** 上，配 **MuMu 模拟器**，模拟器分辨率固定 **1280×720**。
- 两种玩法：**单人演出**（你自己选曲）／**多人演出**（激奏演出，曲子由房间抽，和别的玩家同场）。
- 有图形界面（双击 `启动面板.bat`），也可以用命令行。

> 同人工具，与游戏官方、MuMu 官方均无关系，仓库里不含任何游戏文件、音乐、谱面数据。
> 用脚本玩在线游戏有账号风险（服务条款、封号），**后果自负** —— 动手前请读一遍
> [DISCLAIMER.md](DISCLAIMER.md)，其中载明了使用边界、风险与责任划分。

## 一、它做什么、不做什么

| 做 | 不做 |
|---|---|
| 读屏幕上的画面，认出当前页面、曲目与难度 | 不修改、不替换游戏程序与资源 |
| 按谱面时间表自动点击（走安卓的触摸注入） | 不碰游戏存档，不花一分货币，不领任何奖励 |
| 曲中实时校正时间偏差 | 不绕过付费，不规避检测，不含任何破解功能 |
| 打完读结算页，把成绩写进本地记录 | 不联网上传你的任何数据（没有遥测） |

## 二、开始之前

1. **Windows 10 / 11**，装了 **MuMu 模拟器**，模拟器里装好 OurNotes，能正常进游戏。
2. 模拟器设置里把分辨率固定为 **1280×720**（这是硬要求，别的尺寸程序会直接拒绝读画面）。
3. 电脑上装 **Python 3.13**（安装时勾选「Add python.exe to PATH」）。
4. **不用另外准备点击发生程序** —— `tools/bin/minitouch` 已经随仓库带了一份（第三方组件，
   Apache-2.0，来历见 `tools/bin/NOTICE.md`）。它会在开机时自动推到模拟器里，你什么都不用做。
   真丢了这个文件也不要紧：`locate.py` 会提示缺哪一项，模拟器里通常还留着上次推上去的那份，
   拉回来即可 —— `adb pull /data/local/tmp/minitouch_bang tools\bin\minitouch`
   （`adb.exe` 在 MuMu 安装目录里，例如 `D:\MuMuPlayer\nx_main\adb.exe`）。

## 三、安装（四步）

在仓库根目录打开命令提示符（或 PowerShell），依次执行：

```bat
:: 1) 建虚拟环境并装依赖
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

:: 2) 检查外部依赖找得到没有（这一步输出「启动校验：通过」再往下）
.venv\Scripts\python tools\locate.py

:: 3) 下载谱面并编译（首次几分钟；以后是增量的）
.venv\Scripts\python tools\fetch_charts.py

:: 4) 启动图形界面（也可以直接双击 启动面板.bat）
.venv\Scripts\python tools\flet_gui.py
```

`locate.py` 的预期输出长这样：

```
adb              D:\MuMuPlayer\nx_main\adb.exe  [default, 在]
device           127.0.0.1:16384  [default, 端点]
minitouch        D:\CodeX\Hyoushi\tools\bin\minitouch  [default:bundled, 在]
mumucap_dll      D:\MuMuPlayer\nx_main\sdk\external_renderer_ipc.dll  [default, 在]
mumucap_install  D:\MuMuPlayer  [default, 在]
启动校验：通过
```

出现「缺失」时用环境变量指过去（设置后要**重启面板**才生效）：

| 环境变量 | 指什么 |
|---|---|
| `HYOUSHI_MUMU_ROOT` | MuMu 安装目录（最省事，adb 与渲染器 DLL 都从它推） |
| `HYOUSHI_ADB` | `adb.exe` 的完整路径 |
| `HYOUSHI_DEVICE` | 设备端口，默认 `127.0.0.1:16384` |
| `HYOUSHI_MINITOUCH` | minitouch 可执行文件的完整路径 |

**第一次启动面板**会下载 Flet 桌面客户端（约 40 MB，从 GitHub 取）。网络不通时看
[docs/python_env.md](docs/python_env.md) 里的离线办法。

## 四、打一局

1. 先把游戏打开，**停在「楽曲選択」（乐曲选择）页**（停在这一页最省事：工具不必先到别处找路）。
2. 双击 `启动面板.bat`，左边选 **单人演出**（或 **多人演出**）。
3. 右边选参数，不懂就保持默认：连续演出轮数、断 AP 重试次数、火力门（消耗加成道具，默认开）。
4. 按 **F5**（或点「开始演奏」）。游戏会自己走页面、开打、打完、再走回楽曲選択页。
5. 中途停止用「本轮停止」；无响应时用「强制终止」。

面板一共五页，`Ctrl+1`～`Ctrl+5` 切换：**单人演出 / 多人演出 / 运行日志 / 结算记录 / 设置**。
曲中的实时读数（动作数、修正量、迟到、剩余时间）在运行卡下面那行四格里。一局打完想看细节，
到「结算记录」页选中那一行，点表头的「这一局」。

**打完再开打**：不用你管。工具每局结束（包括中途放弃的）都会把游戏走回楽曲選択页；
一局 AP 了是否继续、间隔多久，都由面板设置决定。

## 五、想调手感

同一台机器上「游戏判定」和「程序发出点击」之间有一个固定延迟，默认按 **+55 ms** 提前量发出
（这个数是这台机器量出来的，别人机器可能不同）。第一局若满屏 GREAT/GOOD，说明提前量与本机不匹配。

- 设置页的「种类偏移」可以按音符种类微调提前量（白键 / 滑键 / 长条 / 引导 / 尾判滑键），
  单位毫秒；默认值即出厂值，**不确定时保持不动**。
- 链路校准：加 `--read-split` 跑几局，程序会从结算页的 FAST/SLOW 分布里自己修正那个延迟；
  默认关闭，因为它需要多局才收敛。

## 六、常见问题

| 现象 | 怎么办 |
|---|---|
| 提示「找不到本工具要用的程序」 | `locate.py` 看是哪一项缺失，按上表设环境变量；minitouch 见「开始之前」第 4 条 |
| 提示「设备没连上」/ `device not found` | 模拟器没开，或 MuMu 换过端口：先 `adb connect 127.0.0.1:16384` |
| 提示分辨率或画面格式不对 | 模拟器设置改 **1280×720**；**不要去改代码里的判据常数** |
| 一直读不出页面、在同一页反复动作 | 把游戏停在「楽曲選択」页再开；游戏刚启动时前几个页面会卡几秒，正常 |
| 满屏 GREAT，一个 PERFECT 都没有 | 提前量不对（见上节），或机器卡顿（关闭占用 CPU 的其他程序） |
| 多人局一直匹配不到人 | 房间内没有其他玩家。工具等待 2 分钟会取消重排，一局最多重试两次 |
| 面板打不开 / 白屏 | 第一次要下载 Flet 客户端，网络问题见 docs/python_env.md；仍不行看 `research/logs/` 下的面板日志 |
| 谱面列表是空的 | 没跑 `tools/fetch_charts.py`，或上游暂时不可达 |

## 七、命令行（可选）

面板能做的事命令行都能做，适合后台批量运行或脚本化：

```bat
:: 指定曲目单局（100056 = 曲目 id，难度 easy/normal/hard/expert 任选）
.venv\Scripts\python.exe tools\run.py --song 100056:expert ^
  --fastcap --offset 55 --live-push-cap 0 --watch-hud --tag g901

:: 让游戏自己随机选曲
.venv\Scripts\python.exe tools\run.py --random --fastcap --offset 55 --live-push-cap 0 --tag g902

:: 多人演出（曲子由房间抽，难度默认 expert，可加 --diff hard）
.venv\Scripts\python.exe tools\run.py --multi --fastcap --offset 55 --live-push-cap 0 --tag mp901
```

几个要注意的点：

- `--tag` 是这一局的编号，会和面板共用计数器（`research/gui_state.json` 的 `next_index`）。
  重复的编号会被拒绝。
- 一局最长可能跑五分钟以上，若用 `timeout` 限制时长请给足 **900 秒**。
- 从命令行跑不要设 `OURNOTES_PANEL` 环境变量，否则结算记录会写到另一处。

## 八、目录里都有什么

| 位置 | 内容 |
|---|---|
| `启动面板.bat` | 双击启动图形界面 |
| `tools/` | 全部程序代码（入口 `run.py`，界面 `flet_gui.py`，模块分工见 `tools/README.md`） |
| `docs/` | 仅 `python_env.md`（Python 环境与 Flet 客户端约定）；其余内部与上游文档留在本机、不随仓库分发 |
| `research/` | 运行数据：结算记录、校准数据、谱面、日志（不随仓库分发，跑起来会自己生成） |
| `tools/bin/` | 随包的 `minitouch` 可执行文件与它的第三方声明 |
| `tools/probes/` | 回归测试与标定脚本（开发者用，不影响使用） |

仓库只放「能跑起来的那部分」。`evidence/`（画面夹具）、`research/` 的产物、谱面数据、以及开发
过程的内部记录都不在仓库里 —— 谱面用 `tools/fetch_charts.py` 自己下载，其余需要时自己采集。

## 九、许可与免责

- 代码以 **GNU AGPL-3.0** 授权，全文见 [`LICENSE`](LICENSE)。可以自由使用、修改、再分发
  （含商用），但分发修改版或把它做成网络服务时，须以同一许可公开对应源码。
- 使用边界与风险（非许可条款，是作者的请求）：**多人模式是和真人同场**，别在别人不知情时开；
  拿去做付费代练、刷分服务这类事，许可证允许，但作者不认可也不提供任何支持。
- 因使用本工具导致的账号处罚、数据损失等后果，由使用者自行承担。完整条款见
  [`DISCLAIMER.md`](DISCLAIMER.md)。
- 第三方组件：`tools/bin/minitouch` 来自 openstf/minitouch（Apache-2.0），许可全文与来历说明
  见 `tools/bin/NOTICE.md` 与 `tools/bin/LICENSE-APACHE-2.0.txt`。该组件不在 AGPL 覆盖范围内。

问题与建议走本仓库的 issue；涉及权利主张的通知，按 `DISCLAIMER.md` 第六条办理。
