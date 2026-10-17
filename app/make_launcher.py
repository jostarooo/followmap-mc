#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""make_launcher —— 生成「启动采集.bat」与「采集看板.bat」

为什么要有这个脚本，而不是直接手写 bat
--------------------------------------
因为 **bat 的编码/行尾是个真会踩死人的坑**。2026-10-14 实测对照（同一份内容）：

    UTF-8 + LF      -> ❌ 第 1 行就被 cmd 拆错，报 `'ho' 不是内部或外部命令`
                       （连 `chcp` 和最后的 python 启动行都一起废掉）
    UTF-8 + CRLF    -> ⚠️ 中文能显示，但**仍有一行被劈开**（`'用' is not recognized`）
    GBK   + CRLF    -> ✅ 能跑，但**依赖本机活动代码页是 936**，换机器即失效
    ASCII + 任意行尾 -> ✅ 稳

根因：cmd.exe 按**活动代码页**逐块解码 bat 文件，多字节中文在 DBCS(GBK) 下
按字节对消耗，会**吃掉换行字节**，导致行边界错位；而 `chcp 65001` 又是**执行到才生效**，
救不了文件前半段已经读错的部分。

所以结论是：**bat 只留 ASCII，所有中文提示交给 Python 打印**（Python 在真控制台走
WriteConsoleW，与代码页无关）。行尾仍写 CRLF —— 那是 cmd 的正式要求。
用 Write 工具直接写 .bat 会落成 LF，所以必须经由本脚本生成。

生成的两个文件
--------------
  启动采集.bat   开 B 通道键鼠记录器（本窗口），**同时**另开一个窗口跑实时看板
  采集看板.bat   只开实时看板（不采集），用于事后复盘
  鼠标自检.bat   30 秒内点几下鼠标，立刻报出是哪个来源抓到的（Raw / 轮询兜底）

用法：
    python make_launcher.py            # 生成/覆盖两个 .bat 并自检
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = "D:\\python\\python.exe"
KEY = "fishkey.py"
VIZ = "fishviz.py"

# 通用前导：找 python / 切目录 / 校验脚本存在
PREAMBLE = [
    "@echo off",
    "chcp 65001 >nul",
    'cd /d "%~dp0"',
]


def head(title, banner):
    return PREAMBLE + [
        'title %s' % title,
        "echo ================================================================",
        "echo  %s" % banner,
        "echo ================================================================",
        "echo.",
        'if not exist "%s" (' % PY,
        "  echo [X] Python not found: %s" % PY,
        "  pause",
        "  exit /b 1",
        ")",
    ]


def script_guard(pkg):
    return [
        'if not exist "%%~dp0%s" (' % pkg,
        "  echo [X] %s missing next to this .bat" % pkg,
        "  pause",
        "  exit /b 1",
        ")",
    ]


LAUNCHER = (
    head("BlockLegend Fishing Collector - channel B + live dashboard",
         "BlockLegend fishing collector: channel B capture + live dashboard")
    + script_guard(KEY)
    + script_guard(VIZ)
    + [
        "echo  Channel B (key/mouse marks) runs in THIS window; the live",
        "echo  dashboard opens in a second window and refreshes itself.",
        "echo  Close this window or press Ctrl+C to stop capturing.",
        "echo.",
        # 看板窗口：--watch 5 每 5 秒重算重生成，页面 meta refresh 自动重载；
        # --open 只在首次打开浏览器（第二次起不会重复开）。
        'start "FishViz Dashboard" "%s" "%%~dp0%s" --watch 5 --open' % (PY, VIZ),
        "timeout /t 1 /nobreak >nul",
        '"%s" "%%~dp0%s" %%*' % (PY, KEY),
        'if "%~1"=="" pause',
        "",
    ]
)

DASHBOARD = (
    head("BlockLegend Fishing Dashboard",
         "BlockLegend fishing dashboard - per-minigame sample counts")
    + script_guard(VIZ)
    + [
        "echo  Tips:",
        "echo    --watch 5   keep refreshing (page reloads itself)",
        "echo    --verbose   also dump every episode in the console",
        "echo.",
        '"%s" "%%~dp0%s" --watch 5 --open %%*' % (PY, VIZ),
        'if "%~1"=="" pause',
        "",
    ]
)

MOUSECHECK = (
    head("BlockLegend Mouse Link Self-Test",
         "Mouse link self-test - click the mouse a few times")
    + script_guard(KEY)
    + [
        "echo  This tells you WHICH source caught your click:",
        "echo    Raw Input   = hardware level (external mouse usually)",
        "echo    polling     = driver-synthesised (touchpad tap usually)",
        "echo  It exits as soon as one full click is seen (or after 30s).",
        "echo  Read-only: no cursor grab, no injection, no blocking.",
        "echo.",
        '"%s" "%%~dp0%s" --mousetest 30 %%*' % (PY, KEY),
        'if "%~1"=="" pause',
        "",
    ]
)

# ---------------------------------------------------------------- fishauto
CTL = "fishauto_ctl.py"


def ctl(lines):
    return head("BlockLegend Auto-Fish Control",
                "BlockLegend auto-fish (fishauto) control") + script_guard(CTL) + lines


AUTOFISH_MENU = ctl([
    "echo  The mod obeys ~/.fishauto/config.json and reloads it every second,",
    "echo  so changes take effect WITHOUT restarting the game.",
    "echo.",
    "echo  Factory defaults are FULLY OFF: enabled=false, dry_run=true.",
    "echo  Nothing happens until you turn it on AND set it live.",
    "echo.",
    "echo  Common commands (pass them to this .bat as arguments):",
    "echo    status              show switches / config / install / log summary",
    "echo    on | off            master switch",
    "echo    dry | live          dry-run (record only) | really press keys",
    "echo    stop | resume       emergency stop / resume",
    "echo    speed 130           press cadence in ms (human: 100-300)",
    "echo    hold 2              hold ticks for hold-type keys",
    "echo    report [N]          summarise the last N games",
    "echo    tail [N]            dump the last N log lines",
    "echo.",
    '"%s" "%%~dp0%s" %%*' % (PY, CTL),
    'if "%~1"=="" pause',
    "",
])

AUTOFISH_DRY = ctl([
    "echo  DRY RUN: the mod judges and logs the QTE but NEVER presses a key.",
    "echo  Use this to verify the reflection binding works on your machine.",
    "echo.",
    '"%s" "%%~dp0%s" on' % (PY, CTL),
    '"%s" "%%~dp0%s" dry' % (PY, CTL),
    '"%s" "%%~dp0%s" status %%*' % (PY, CTL),
    'if "%~1"=="" pause',
    "",
])

AUTOFISH_LIVE = ctl([
    "echo  WARNING: this makes the mod REALLY PRESS KEYS (left click / LShift).",
    "echo  It only writes the vanilla KeyMapping fields, so it is equivalent to",
    "echo  you pressing the key yourself - but it WILL act while you play.",
    "echo.",
    "echo  Emergency stop at any time:  fishauto_ctl.py stop   (or this .bat: stop)",
    "echo.",
    "pause",
    '"%s" "%%~dp0%s" on' % (PY, CTL),
    '"%s" "%%~dp0%s" live' % (PY, CTL),
    '"%s" "%%~dp0%s" status %%*' % (PY, CTL),
    'if "%~1"=="" pause',
    "",
])

AUTOFISH_STOP = ctl([
    "echo  Creating ~/.fishauto/STOP - the mod stops pressing keys immediately",
    "echo  (it keeps logging). Remove with:  %s resume" % CTL,
    "echo.",
    '"%s" "%%~dp0%s" stop' % (PY, CTL),
    '"%s" "%%~dp0%s" status %%*' % (PY, CTL),
    'if "%~1"=="" pause',
    "",
])

TARGETS = [
    ("\u542f\u52a8\u91c7\u96c6.bat", LAUNCHER),        # 启动采集.bat
    ("\u91c7\u96c6\u770b\u677f.bat", DASHBOARD),       # 采集看板.bat
    ("\u9f20\u6807\u81ea\u68c0.bat", MOUSECHECK),      # 鼠标自检.bat
    ("\u81ea\u52a8\u9493\u9c7c\u63a7\u5236.bat", AUTOFISH_MENU),   # 自动钓鱼控制.bat
    ("\u9493\u9c7c-\u5f00\u59cb\u5e72\u8dd1.bat", AUTOFISH_DRY),   # 钓鱼-开始干跑.bat
    ("\u9493\u9c7c-\u5f00\u59cb\u6309\u952e.bat", AUTOFISH_LIVE),  # 钓鱼-开始按键.bat
    ("\u9493\u9c7c-\u6025\u505c.bat", AUTOFISH_STOP),              # 钓鱼-急停.bat
]


def write_and_check(name, lines):
    path = os.path.join(HERE, name)
    data = "\r\n".join(lines).encode("ascii")
    with open(path, "wb") as fh:
        fh.write(data)
    raw = open(path, "rb").read()
    crlf = raw.count(b"\r\n")
    lone_lf = raw.count(b"\n") - crlf
    checks = [
        ("纯 ASCII（无中文，免疫代码页）", all(c < 128 for c in raw)),
        ("无 UTF-8 BOM", raw[:3] != b"\xef\xbb\xbf"),
        ("行尾全为 CRLF（裸 LF = 0）", lone_lf == 0 and crlf > 0),
        ("python 路径正确", PY.encode() in raw),
        ("参数透传 %*", b"%*" in raw),
        ("末尾有换行（最后一行不留半截）", raw.endswith(b"\r\n")),
    ]
    print("")
    print("目标: %s" % path)
    print("大小: %d 字节, CRLF=%d, 裸LF=%d" % (len(raw), crlf, lone_lf))
    ok = True
    for label, passed in checks:
        print("  %s %s" % ("[v]" if passed else "[X]", label))
        ok = ok and passed
    return ok


def main():
    ok = True
    for name, lines in TARGETS:
        ok = write_and_check(name, lines) and ok
    print("")
    print(" 全部通过。" if ok else " 有检查未通过，请修。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
