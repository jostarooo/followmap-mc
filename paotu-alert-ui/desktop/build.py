# -*- coding: utf-8 -*-
"""一键打包成单文件 exe。

用法（在已装好依赖的解释器下）：
    <venv>/Scripts/python.exe build.py            # 无控制台窗口（正式）
    <venv>/Scripts/python.exe build.py --console  # 带控制台（排查启动问题时用）

产物：paotu-alert-ui/dist/末地跑图提醒控制台.exe
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # paotu-alert-ui/
DIST = ROOT / "dist"
BUILD = ROOT / "build"
NAME = "末地跑图提醒控制台"

# 这些包宿主用不到，排除掉能显著缩小体积、也少一堆打包坑
EXCLUDES = [
    "tkinter", "unittest", "pydoc_data", "test", "lib2to3",
    "PIL", "numpy", "scipy", "pandas", "matplotlib",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
    "webview.platforms.qt", "webview.platforms.gtk",
    "webview.platforms.cocoa", "webview.platforms.android",
    "webview.platforms.cef", "webview.platforms.mshtml",
]


def main():
    console = "--console" in sys.argv
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        "--name", NAME,
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        "--add-data", "%s%s." % (ROOT / "index.html", os.pathsep),
        "--add-data", "%s%sdesktop" % (HERE / "app.ico", os.pathsep),
        # pywebview 带 lib/*.dll（WebView2 托管程序集）与注入用 JS，必须整包收
        "--collect-all", "webview",
        "--collect-all", "clr_loader",
        "--hidden-import", "pythonnet",
        "--hidden-import", "webview.platforms.edgechromium",
    ]
    if console:
        args.append("--console")
    else:
        args.append("--windowed")
    ic = HERE / "app.ico"
    if ic.exists():
        args += ["--icon", str(ic)]
    for e in EXCLUDES:
        args += ["--exclude-module", e]
    args.append(str(HERE / "host.py"))

    print(" ".join(args))
    r = subprocess.run(args, cwd=str(ROOT))
    if r.returncode != 0:
        print("打包失败，返回码", r.returncode)
        return r.returncode
    exe = DIST / (NAME + ".exe")
    if exe.exists():
        print("产物: %s（%.1f MB）" % (exe, exe.stat().st_size / 1048576))
    else:
        print("没找到产物:", exe)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
