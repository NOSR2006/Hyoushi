"""README.md 措辞与事实修正（一次性文档编辑工具，干跑默认，--go 写盘）。

字节级替换 + 命中数校验；任何一处命中数不是 1 就整份不写盘。
"""
import io
import sys

PAIRS = [
    # 1) 与 DISCLAIMER 第十二条（许可优先）口径对齐
    ("> [DISCLAIMER.md](DISCLAIMER.md)，那是可以约束作者的唯一一份文件。",
     "> [DISCLAIMER.md](DISCLAIMER.md)，其中载明了使用边界、风险与责任划分。"),
    # 2) 口语改陈述句（面向使用者，不改技术信息）
    ("（停在这一页最省事，工具不用满世界找路）",
     "（停在这一页最省事：工具不必先到别处找路）"),
    ("5. 想中途收手点「本轮停止」；卡住了点「强制终止」。",
     "5. 中途停止用「本轮停止」；无响应时用「强制终止」。"),
    ("第一局如果满屏 GREAT/GOOD，说明提前量不对路。",
     "第一局若满屏 GREAT/GOOD，说明提前量与本机不匹配。"),
    (" 单位毫秒，默认值就是最优的出厂值，**不懂就一个都别动**。",
     " 单位毫秒；默认值即出厂值，**不确定时保持不动**。"),
    ("| 一直读不出页面、原地打转 |", "| 一直读不出页面、在同一页反复动作 |"),
    ("或机器太卡（关掉别的吃 CPU 的程序）",
     "或机器卡顿（关闭占用 CPU 的其他程序）"),
    ("| 多人局一直匹配不到人 | 房间里没别人。工具等 2 分钟会自己取消重排，一局最多重来两次 |",
     "| 多人局一直匹配不到人 | 房间内没有其他玩家。工具等待 2 分钟会取消重排，一局最多重试两次 |"),
    ("面板能做的事，命令行都能做，适合挂机或脚本化：",
     "面板能做的事命令行都能做，适合后台批量运行或脚本化："),
    ("- 一局最长可能跑五分钟以上，外面包 `timeout` 时给足 **900 秒**。",
     "- 一局最长可能跑五分钟以上，若用 `timeout` 限制时长请给足 **900 秒**。"),
    # 3) docs/ 现状：入库只剩 python_env.md
    ("| `docs/` | Python 环境与 Flet 客户端约定（另有两份面向二次开发的说明留在本机、不随仓库分发） |",
     "| `docs/` | 仅 `python_env.md`（Python 环境与 Flet 客户端约定）；其余内部与上游文档留在本机、不随仓库分发 |"),
    # 4) 权利主张程序在第六条，不是第十条
    ("按 `DISCLAIMER.md` 第十条办理。", "按 `DISCLAIMER.md` 第六条办理。"),
]


def main() -> int:
    go = "--go" in sys.argv[1:]
    path = "README.md"
    raw = io.open(path, encoding="utf-8").read()
    bad = []
    for old, new in PAIRS:
        n = raw.count(old)
        print("%s%2d  %s" % ("ok " if n == 1 else "!! ", n,
                            old[:30].replace("\n", " ")))
        if n == 1:
            raw = raw.replace(old, new)
        else:
            bad.append(old)
    if bad:
        print("\n有 %d 处命中数不为 1，未写盘。" % len(bad))
        return 1
    if go:
        io.open(path, "w", encoding="utf-8", newline="").write(raw)
        print("\n已写盘：%s" % path)
    else:
        print("\n干跑通过（加 --go 写盘）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
