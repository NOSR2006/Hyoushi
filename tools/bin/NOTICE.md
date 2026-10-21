# 本目录内的第三方文件

## `minitouch`

- **是什么**：安卓设备上的触摸注入守护进程。本工具用它把点击与滑动发给模拟器
  （调用方是 `tools/mtouch.py`，路径由 `tools/locate.py` 决定）。
- **文件**：`minitouch`，ELF 64-bit、x86-64、Android 21、已 strip，28048 字节，
  sha256 `230f502c57fd5580d1a47509c596b6f4081fc9e3a7217915592c57ea48883a2b`。
- **来历**：openstf/minitouch 的安卓移植，x86_64 构建（EvATive7 维护的分支）。仓库里
  保存的是原样二进制，未修改、未重新编译、未附加任何内容。
- **许可**：Apache License 2.0，全文见同目录 `LICENSE-APACHE-2.0.txt`。按该许可第 4 条，
  本目录同时给出了来源与未修改的说明。
- **要换一份**：把新的可执行文件覆盖到 `tools/bin/minitouch`，或用环境变量
  `HYOUSHI_MINITOUCH` 指向别处。程序在建立连接时用 `adb push` 把它送到设备的
  `/data/local/tmp/minitouch_bang`，所以换文件不需要动代码。
- **不需要它的话**：可以删掉；`tools/locate.py` 会退回到历史路径，缺件时它给出的提示里
  包含从设备把已有那份拉回来的命令。
