# Python 环境约定

**用一个 Python 3.13（64 位）建的 `.venv`**，仓库自带的那份就是（`.venv/`，已 gitignore）。
建法：

```bat
cd /d <你的项目目录>
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

下面这些版本号、体积和路径是作者开发机上量到的（Windows 11 + Python 3.13.11 + MuMu 模拟器），
换机器按自己那份读，**别照抄路径**：外部程序的默认位置都在 `tools/locate.py` 里，
用 `HYOUSHI_*` 环境变量指到你自己的那份即可（见根 README 的「支持矩阵」）。

## 本仓库

- 依赖清单：`requirements.txt`（numpy 2.4.1 / opencv-python 5.0.0.93 / windows-capture 2.0.1 /
  pillow 12.1.0 / pypinyin 0.55.0 / darkdetect 0.8.0 / material-color-utilities 0.2.6 / flet 1.0.3 /
  flet-desktop 1.0.3，版本钉死）。`opencv` 那条 2026-10-06 从 `-headless` 换成带 GUI 的版本：
  `windows-capture` 的元数据要求 `opencv-python`，而两个包共用同一批 `cv2` 文件，同时装会互相删。
  `windows-capture` 只给 `run.py --host` 用：`tools/hostcap.py` 按类名找 MuMu 的 `nemuwin` 插件、
  把窗口调到插件正好 1280x720 再按偏移切片（实测 60.0 fps，screencap 那条 3.6 fps），与一张
  screencap 对齐自检（含把 MuMu 偶尔的整幅压暗补回去的颜色表）之后才启用，任何一步对不上
  就安静退回 adb。**代价：它会把模拟器窗口调成客户区 1312x782**（否则 MuMu 把设备面缩放，
  像素就不等于设备像素了）—— 局末 `stop()` 会把它放回原处（记下原矩形，实测客户区
  1277x762 → 1312x782 → 停抓后回到原矩形），所以这是「一局里临时改一下」而不是永久改。
  另外 MuMu 的侧栏会盖住表面右端 40 列（1240-1279），那 40 列在 host 帧里被补成设备像素
  （冻结在自检那一刻）；`detect.py` 的判读一律进不了那些列（掩码右界 1116）。`tkinter` 随解释器自带，但**本仓库已经不用它了** —— 面板从
  customtkinter/tksheet 转到过 PySide6，2026-10-05 又整体转到 Flet：Qt 那套连文件带探针带基线一起
  删干净了，`requirements.txt` 里也不再钉 `PySide6`（原先约 350 MB 的 wheel 只有旧面板要）。
  `coloraide` 也一起删了：它原先是给探针算 WCAG 对比度的，但全库零 import（2026-10-06 查）。
  - **Flet** 是 `tools/flet_gui.py`（现役面板）的视图层，Python 侧 4 MB。它的桌面客户端
    **不在 wheel 里**：首次运行会去 `https://github.com/flet-dev/flet/releases/download/...`
    下 `flet-windows.zip`（约 40 MB，解到 `%USERPROFILE%\.flet\client\`）。国内直连 github.com
    会超时，本机是把 zip 直接放进 `.venv\Lib\site-packages\flet_desktop\app\` 绕过的（该路径是
    `flet_desktop.get_package_bin_dir()` 的第一查找位），换机器或重建 venv 要重做这一步；
    也可用 `FLET_CLIENT_URL` 指到别的镜像。**播放链路一个 GUI 库都不 import**，这两条只影响面板。
- `启动面板.bat` 优先用 `.venv\Scripts\pythonw.exe`，没有 `.venv` 才回落到全局 —— 面板不该因为
  别的项目往全局装了包而改变行为。**它现在起的就是 Flet 那条**（2026-10-04 对着真模拟器跑过一整轮：
  乐曲识别 → `0109_03` 夢我夢中 EXPERT Lv26 → AP 759/759、tag `g341`）。
  直接跑 Flet 面板是 `.venv\Scripts\python.exe tools\flet_gui.py`。
- 跑探针/命令行工具请用 `.\.venv\Scripts\python.exe`，例如
  `.\.venv\Scripts\python.exe tools\probes\hudgate.py`。**36 条有判决的回归**（清单见
  `tools/probes/README.md`）已在 `.venv` 下全 PASS；`capreg` / `mtdiag` 要模拟器的 adb
  （`mtdiag` PART 3 会重注册本机 adb 端点约 1 秒，别在有局在跑时执行）。零设备零联网的那些
  （`panelfly` / `fletgui` 等）不需要桌面会话，本机直接跑就是；**`fletfly`、`fletpanel`、
  `fletfont` 相反，必须在真实桌面上跑**（`fletviewcheck` 2026-10-21 退役，不再是门） —— 它们都要开一个真 Flutter 窗口（Flet 桌面客户端没有离屏模式）。
- **Flet MCP（给 agent 用，不是 Hyoushi 的运行时依赖）**：2026-10-05 曾在 `.venv` 里装过
  `flet-mcp 1.0.3`（连带 `fastmcp` / `mcp` 等约 60 个包，`.venv\Scripts\flet.exe mcp` 起 stdio
  服务器），**2026-10-21 已卸、改用全局那份（见本节末）**。它答的是**它自己所装那份 venv** 的
  Flet 事实：
  `get_api`（控制 / 事件 / `Padding` 这类 dataclass / 枚举按名字查）、`list_controls`、`get_enum`、
  `search_enum_members`、`enum_has_member`、`find_icon`；默认只开 API + Icons 两组，示意与 CLI
  帮助要 `FLET_MCP_ENABLE_EXAMPLES="1"` / `FLET_MCP_ENABLE_CLI="1"`。它不 import Hyoushi 的任何东西，
  所以**不写进 `requirements.txt`**（那个文件的口径是「工具链真正 import 的包」）。
  **2026-10-21 改成用全局那一份**（用户 m54057 的裁定）：`%USERPROFILE%\.mcp\flet-mcp`
  （它自己的 venv，跑 `run_flet_mcp.py`；服务器自报 `flet-mcp 4.1.3`，答的是**那个 venv 里**的
  Flet 版本事实，不是本项目 `.venv` 的 1.0.3）。DSH 侧接线在
  `%USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml` 的 `mcp-flet` 条目
  （`@deepseek-ai/dsh-mcp-client`、`serverName: flet`、`command` 指
  `.mcp\flet-mcp\Scripts\python.exe`、`args: ['run_flet_mcp.py']`、
  `FLET_MCP_ENABLE_EXAMPLES=1`），模型看到的工具名是 `mcp__flet__get_api` 这种形态；**改完要重启
  DSH 才会注入**（本会话的工具清单里没有 `mcp__flet__*` 就是这个原因）。项目 `.venv` 里那份已卸
  （`flet-mcp` + `fastmcp` + `fastmcp-slim` + `mcp` + `mcp-types`，`.venv` 385 → 364 MB，`pip check`
  无缺、`import flet` 正常）。代价不变：这 6 个工具的定义会进每一次请求（`get_api("Switch")` 一次约
  8.5 KB），不用时把那段删掉即可。
- `.venv/` 已在 `.gitignore` 里。
