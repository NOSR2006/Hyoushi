@echo off
rem 面板入口：tools\flet_gui.py（Flet / Material 3 版，仓库里就这一条）。56 个方法名冻在
rem tools\probes\fletgui.py 第 6 关的 PARITY 名单里，全仓不许再有任何 Qt（同一个探针在盯着）。
rem
rem 解释器优先级：.venv 的 pythonw -> .venv 的 python -> PATH 上的 pythonw -> PATH 上的 python。
rem .venv 优先是硬规矩：面板不该因为别的项目往全局环境装了什么而换行为。
rem 没有 .venv 时的补救：python -m venv .venv
rem
rem Flet 的桌面客户端是另一个进程（真 Flutter 窗口，没有离屏模式），首次运行要联网下约 40 MB；
rem 本机已把 flet-windows.zip 放进 .venv\Lib\site-packages\flet_desktop\app\ 里绕过。
rem 缺 flet 的表现是进程当场退出并打印一行。pythonw 没有控制台，所以那种情况请直接跑
rem .venv\Scripts\python.exe tools\flet_gui.py 看得见那行字。
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" tools\flet_gui.py
  exit /b
)
if exist ".venv\Scripts\python.exe" (
  start "" ".venv\Scripts\python.exe" tools\flet_gui.py
  exit /b
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw tools\flet_gui.py
) else (
  python tools\flet_gui.py
)
