"""核官方文档用的**本机取页**小工具（给 agent 用，不是 Hyoushi 的运行时依赖：视图层不 import 它）。

为什么要另起一条路（2026-10-05 实测，同一台机器、同一分钟）：

  * `developer.android.com` —— harness 的 `web_fetch` 两次都是 `TypeError: fetch failed`；
    python + 极简 UA 是 200 / 473 112 B / 正文 37 320 字符。**换成完整浏览器头（Accept +
    Accept-Language）反而被 302 到 `oauth2authorize`** —— 所以「多带浏览器头」在这里是坏主意。
  * `m3.material.io` —— 谁都只能拿到 SPA 壳（页面自己写着 `This website requires JavaScript.`，
    `/llms.txt` 是 404）。这里确实取不到正文，官方数值改从 token 导出与 Compose token 源码取。
  * `raw.githubusercontent.com` —— python 200 `text/plain`；`curl.exe` → `(35) Recv failure:
    Connection was reset`。
  * `api.github.com` —— 能连，但匿名配额会耗尽（`core.remaining 0`），别拿它当主力。

用法：

    python tools/webfetch.py <url>                  # 剥掉标签的可见文本
    python tools/webfetch.py <url> --grep 56px      # 只打印含该子串的行（核 token 最常用）
    python tools/webfetch.py <url> --grep=container-height --after 1   # 连下一行一起打
    python tools/webfetch.py <url> --raw            # 原样打印响应体
    python tools/webfetch.py <url> --json           # 只打印一行 JSON（url/status/bytes/chars）
    python tools/webfetch.py <url> -o out.txt       # 写文件（UTF-8），不在终端刷屏
    python tools/webfetch.py <url> --max 4000       # 截断到 4000 字符（默认 0 = 全打）

退出码：0 取到；1 没取到（DNS/超时/4xx/5xx）；2 取到了但没有可见文本（SPA 壳就是这个症状）。

两个坑：① `--grep` 的值以 `-` 开头时用 `--grep=-space`（argparse 会把它当选项）；② `.scss` 的
token 常常**键在一行、值在下一行**（`'list-item-leading-space':` / `if(..., 16px),`），要 `--after 1`。
"""
from __future__ import annotations

import argparse
import gzip
import html as _html
import json
import re
import sys
import urllib.error
import urllib.request

# 「极简 UA」= 只用 UA 头。实测这一档能拿到 devsite 正文；再加 Accept/Accept-Language 就会被
# 送去 oauth —— 所以别「顺手补全」这里。
UA_MIN = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
UA_FULL = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HDR_MIN = {"User-Agent": UA_MIN}
HDR_FULL = {
    "User-Agent": UA_FULL,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

TAG_RE = re.compile(r"<[^>]+>")


def fetch(url, full_ua=False, timeout=30):
    """-> (status, final_url, content_type, bytes)。4xx/5xx 由调用方接 `HTTPError`。"""
    req = urllib.request.Request(url, headers=HDR_FULL if full_ua else HDR_MIN)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        if body[:2] == b"\x1f\x8b":                     # 有的服务器无视我们没要 gzip
            body = gzip.decompress(body)
        return r.status, r.geturl(), r.headers.get("Content-Type", ""), body


def decode(body, content_type=""):
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.I)
    enc = m.group(1) if m else "utf-8"
    try:
        return body.decode(enc, "replace")
    except LookupError:
        return body.decode("utf-8", "replace")


def visible_text(page):
    """HTML -> 可见文本。脚本/样式/注释整块丢掉（m3.material.io 的壳就是这么露馅的）。"""
    s = re.sub(r"(?is)<(script|style|noscript|svg|head)\b.*?</\1>", " ", page)
    s = re.sub(r"(?is)<!--.*?-->", " ", s)
    s = re.sub(r"(?i)<(br|/p|/div|/li|/tr|/h[1-6]|/section|/td)\s*/?>", "\n", s)
    s = _html.unescape(TAG_RE.sub(" ", s))
    out = []
    for line in s.split("\n"):
        line = re.sub(r"[ \t\u00a0]+", " ", line).strip()
        if line or (out and out[-1]):                   # 折叠连续空行，但保留段间一行
            out.append(line)
    return "\n".join(out).strip()


def is_html(content_type, page):
    return "html" in (content_type or "").lower() or re.search(r"(?i)<(html|body|div|p)\b", page[:2000])


def main(argv=None):
    ap = argparse.ArgumentParser(description="本机取页（核官方源用）")
    ap.add_argument("url")
    ap.add_argument("--raw", action="store_true", help="原样打印响应体，不剥标签")
    ap.add_argument("--json", action="store_true", help="只打印一行 JSON 摘要")
    ap.add_argument("--grep", default=None, help="只打印含该子串的行（大小写不敏感）")
    ap.add_argument("--after", type=int, default=0,
                    help="配合 --grep：每个命中再跟打 N 行（.scss 的键值常分两行）")
    ap.add_argument("--max", type=int, default=0, help="截断到 N 个字符（0 = 不截）")
    ap.add_argument("-o", "--out", default=None, help="写到文件而不是终端")
    ap.add_argument("--full-ua", action="store_true",
                    help="带上完整浏览器头（对照用：devsite 会 302 到 oauth）")
    ap.add_argument("--timeout", type=float, default=30.0)
    a = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        status, final, ctype, body = fetch(a.url, a.full_ua, a.timeout)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
        print(f"HTTP {e.code} {e.reason}" + (f" -> {loc}" if loc else ""))
        return 1
    except Exception as e:                               # noqa: BLE001 - 取页工具，报清楚比分类重要
        print(f"{type(e).__name__}: {e}")
        return 1

    text = decode(body, ctype)
    kind = "html" if is_html(ctype, text) else "text"
    shown = text if (a.raw or kind == "text") else visible_text(text)

    if a.grep:
        needle = a.grep.lower()
        lines = shown.split("\n")
        hits = []
        for i, ln in enumerate(lines):
            if needle in ln.lower():
                hits.extend(lines[i:i + 1 + max(0, a.after)])
                hits.append("----")
        shown = "\n".join(hits)
        if not hits:
            print(f"（{a.url} 里没有含 {a.grep!r} 的行；正文 {len(text)} 字符）")
            return 0

    if a.json:
        payload = {"url": a.url, "final": final, "status": status, "type": ctype,
                   "bytes": len(body), "chars": len(shown), "kind": kind}
        print(json.dumps(payload, ensure_ascii=False))
    elif a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(shown + "\n")
        print(f"写出 {a.out}（{len(shown)} 字符）")
    else:
        if a.max and len(shown) > a.max:
            print(shown[:a.max] + f"\n…（截断，全文 {len(shown)} 字符）")
        else:
            print(shown)

    if not shown.strip():
        print(f"（{a.url} 取到了但没有可见文本 —— SPA 壳的典型症状）")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
