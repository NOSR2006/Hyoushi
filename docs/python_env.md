# Python 环境约定

## 一、虚拟环境

本项目使用 Python 3.13（64 位）创建虚拟环境。仓库自带的 `.venv/` 即为该环境，已被 `.gitignore` 排除。
重建方式：

```bat
cd /d <项目目录>
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

以下版本号、体积与路径数据取自作者的开发机（Windows 11、Python 3.13.11、MuMu 模拟器）。
在其他机器上部署时，不得照搬这些路径：外部程序的默认位置统一由 `tools/locate.py` 定义，
应以 `HYOUSHI_*` 环境变量指向实际位置（见根目录 `README.md` 第二节）。

## 二、依赖清单

`requirements.txt` 中的版本已固定：numpy 2.4.1、opencv-python 5.0.0.93、windows-capture 2.0.1、
pillow 12.1.0、pypinyin 0.55.0、darkdetect 0.8.0、material-color-utilities 0.2.6、flet 1.0.3、
flet-desktop 1.0.3。

有关依赖的两项约定：

1. `opencv-python` 于 2026-10-06 由 `-headless` 变更为带图形界面的版本。原因是 `windows-capture`
   的元数据要求 `opencv-python`，而两者共用同一批 `cv2` 文件，同时安装会互相覆盖。
2. `windows-capture` 仅供 `run.py --host` 使用：`tools/hostcap.py` 按类名定位 MuMu 的 `nemuwin`
   插件，将窗口调整为插件对应的 1280×720 后按偏移切片（实测 60.0 fps；`adb screencap` 为 3.6 fps），
   并与一张 `screencap` 执行对齐自检（含补回 MuMu 偶发整幅压暗的颜色表）后启用；任何一步不通过
   即静默回退至 adb。其代价是会将模拟器窗口的客户区调整为 1312×782（否则 MuMu 会缩放设备画面，
   导致像素与设备像素不再一一对应）；局末 `stop()` 依据记录的原矩形恢复（实测客户区
   1277×762 → 1312×782 → 停止抓帧后恢复原矩形），因此属于单局内的临时调整。
   此外 MuMu 侧栏会遮挡画面右侧 40 列（1240–1279），该区域在 host 帧中被补为设备像素（冻结于
   自检时刻）；`detect.py` 的判读不会触及这些列（掩码右界为 1116）。

## 三、图形界面相关

1. `tkinter` 随解释器附带，但本项目已不使用。界面层先后由 customtkinter/tksheet 迁移至 PySide6，
   2026-10-05 整体迁移至 Flet；Qt 相关的源文件、回归测试与基线已全部删除，`requirements.txt`
   亦不再固定 `PySide6`。
2. `coloraide` 已移除。该包原先用于在回归测试中计算 WCAG 对比度，全库无引用（2026-10-06 核查）。
3. **Flet** 是 `tools/flet_gui.py` 的视图层，Python 侧约 4 MB。其桌面客户端不在 wheel 包内：
   首次运行时会从 `https://github.com/flet-dev/flet/releases/download/...` 下载 `flet-windows.zip`
   （约 40 MB，解压至 `%USERPROFILE%\.flet\client\`）。网络受限时，可将该压缩包直接放入
   `.venv\Lib\site-packages\flet_desktop\app\`（该路径为 `flet_desktop.get_package_bin_dir()` 的
   首个查找位置），或以 `FLET_CLIENT_URL` 指向镜像。更换机器或重建虚拟环境后需重新执行此步骤。
   演奏链路不引用任何图形界面库，上述内容仅影响界面。
4. `启动面板.bat` 优先调用 `.venv\Scripts\pythonw.exe`，仅在缺少 `.venv` 时回退至全局解释器，
   以避免其他项目在全局环境安装的包影响本程序行为。该脚本启动的是 Flet 界面。直接启动方式为
   `.venv\Scripts\python.exe tools\flet_gui.py`。

## 四、回归测试与验收

执行回归测试与命令行工具时应使用 `.\.venv\Scripts\python.exe`，例如
`.\.venv\Scripts\python.exe tools\probes\hudgate.py`。

1. 发版批次共 36 条具有判定结论的回归测试（位于 `tools/probes/`），已在 `.venv` 下
   全部通过。
2. `capreg` 与 `mtdiag` 需要模拟器 adb 在线；`mtdiag` 的 PART 3 会重新注册本机 adb 端点，
   耗时约 1 秒，不得在对局运行期间执行。
3. 不依赖设备与网络的回归测试（`panelfly`、`fletgui` 等）无需桌面会话。
4. `fletfly`、`fletpanel`、`fletfont` 必须在真实桌面会话中执行，三者均需打开 Flutter 窗口
   （Flet 桌面客户端不提供离屏模式）。原像素基线检查工具 `fletviewcheck` 已于 2026-10-21 退役，
   不再作为验收门。

## 五、Flet MCP（开发辅助，非运行时依赖）

Flet MCP 为开发阶段查询 Flet API 的服务，不属于本项目的运行时依赖，故不列入 `requirements.txt`
（该文件的口径为工具链实际引用的包）。

1. 2026-10-05 曾在 `.venv` 内安装 `flet-mcp 1.0.3`（连同 `fastmcp`、`mcp` 等约 60 个包，以
   `.venv\Scripts\flet.exe mcp` 启动 stdio 服务器）。
2. 2026-10-21 已卸载该项目内版本，改用全局安装的一份：`%USERPROFILE%\.mcp\flet-mcp`
   （独立虚拟环境，运行 `run_flet_mcp.py`；服务器自报 `flet-mcp 4.1.3`，所答为该项目虚拟环境内的
   Flet 版本事实，而非本仓库 `.venv` 的 1.0.3）。
3. 该服务提供六个工具：`get_api`（按名称查询控件、事件、`Padding` 等数据类与枚举）、
   `list_controls`、`get_enum`、`search_enum_members`、`enum_has_member`、`find_icon`。
   默认仅启用 API 与图标两组，示例与命令行帮助需设置 `FLET_MCP_ENABLE_EXAMPLES="1"` 与
   `FLET_MCP_ENABLE_CLI="1"`。
4. 宿主侧接线位于 `%USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml` 的 `mcp-flet` 条目
   （`@deepseek-ai/dsh-mcp-client`、`serverName: flet`、`command` 指向
   `.mcp\flet-mcp\Scripts\python.exe`、`args: ['run_flet_mcp.py']`、`FLET_MCP_ENABLE_EXAMPLES=1`），
   工具名以 `mcp__flet__get_api` 的形式呈现。修改后需重启宿主程序方可生效。
5. 项目 `.venv` 内的对应包已卸载（`flet-mcp`、`fastmcp`、`fastmcp-slim`、`mcp`、`mcp-types`；
   `.venv` 由 385 MB 降至 364 MB，`pip check` 无缺项，`import flet` 正常）。
6. 该服务的工具定义会计入每次请求（单次 `get_api` 约 8.5 KB）。不使用时，可移除该条接线。

## 六、版本管理

`.venv/` 已被 `.gitignore` 排除，不得提交。
