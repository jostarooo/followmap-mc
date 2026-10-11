# -*- coding: utf-8 -*-
"""校验 .bat 启动器：静态编码检查 + cmd 干跑验证。

背景（真实事故，2026-10-08）
---------------------------
cmd.exe 读 .bat 时按「当前控制台代码页」解码每一行，并按**字节数**推进
文件指针。只要文件里出现一行 UTF-8 中文，指针就会漂移，之后每一行都被
吃掉开头字符：

    rem ...   ->  'em' 不是内部或外部命令
    set "SIZE=%~1"  ->  'et' ...      -> SIZE 变成空

结果：python 收到 `--size --interval 150`，argparse 报错秒退，
窗口根本打不开（看起来像"地图界面无法打开"）。

用法
----
    python check_bats.py          # 只做静态检查（快）
    python check_bats.py --run    # 静态 + 让 cmd 干跑一遍，验证变量展开

干跑会把「启动 python 的那一行」换成 echo 探针，因此不会真的开窗口，
但变量的展开结果、以及有没有出现解析错误，都能真实暴露出来。
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys

APPDIR = os.path.dirname(os.path.abspath(__file__))

VAR_RE = re.compile(r'set\s+"?([A-Za-z_][A-Za-z0-9_]*)=')


def find_bats() -> list[str]:
    out = []
    for root, dirs, files in os.walk(APPDIR):
        dirs[:] = [d for d in dirs if d not in ("_probe", "__pycache__")]
        for f in files:
            if f.lower().endswith(".bat"):
                out.append(os.path.join(root, f))
    return sorted(out)


def static_check(path: str) -> tuple[list[str], bytes]:
    """返回 (问题列表, 原始字节)。"""
    raw = io.open(path, "rb").read()
    problems: list[str] = []

    bad_lines = []
    for n, line in enumerate(raw.split(b"\n"), 1):
        if any(c > 127 for c in line):
            bad_lines.append(n)
    if bad_lines:
        n_bytes = sum(1 for c in raw if c > 127)
        problems.append(
            "%d 个非 ASCII 字节（第 %s 行）—— cmd 按字节推进指针会漂移，"
            "后续行会被吃掉首字符" % (n_bytes, "、".join(map(str, bad_lines))))
    if raw[:3] == b"\xef\xbb\xbf":
        problems.append("文件带 UTF-8 BOM（应保存为无 BOM）")
    return problems, raw


def launch_line_index(lines: list[bytes]) -> int | None:
    """找到「真正执行 app.py」的那一行。

    要小心的干扰行：
        set "APPPY=%~dp0followmap\\app.py"      <- 变量定义，含 app.py 但不是启动行
        if exist "%APPPY%" goto have_script    <- 条件判断
        rem ... app.py ...                     <- 注释
        echo  script : %APPPY%                 <- 回显
    真正的启动行形如：
        "%PY%" -u "%APPPY%" --size ...          （本启动器）
        start "" "%PYW%" "%~dp0followmap\\app.py" ...（静默启动器）
    """
    hit = None
    for i, line in enumerate(lines):
        s = line.strip()
        sl = s.lower()
        if b"app.py" not in line and b"%apppy%" not in sl:
            continue
        if sl.startswith((b"rem", b"::", b"echo", b"set ", b"set\"", b"if ", b"if(")):
            continue
        if sl.startswith(b'"') or sl.startswith(b"start ") or sl.startswith(b"%py%"):
            hit = i
    return hit


def dry_run(path: str, raw: bytes) -> tuple[bool, str]:
    """把启动行换成 echo 探针后，用 cmd 真跑一遍。"""
    lines = raw.split(b"\n")
    idx = launch_line_index(lines)
    if idx is None:
        return True, "（没有可干跑的启动行，跳过）"

    names = []
    for m in VAR_RE.finditer(raw.decode("ascii", "replace")):
        n = m.group(1).upper()
        if n not in names:
            names.append(n)
    probe_vars = [n for n in ("SIZE", "INTERVAL", "LAYER") if n in names]
    marker = "__PROBE_OK__" + "".join(" [%" + n + "%]" for n in probe_vars)

    probe = list(lines)
    probe[idx] = b"echo " + marker.encode("ascii")

    probe_path = os.path.join(APPDIR, "__probe.bat")
    try:
        os.remove(probe_path)
    except OSError:
        pass
    io.open(probe_path, "wb").write(b"\n".join(probe))
    try:
        # stdin=DEVNULL：失败分支里的 `pause` 会立刻读到 EOF 返回，
        # 否则校验器自己会被 "Press any key" 卡死。
        r = subprocess.run('cmd.exe /c "%s"' % probe_path,
                           capture_output=True, timeout=25,
                           stdin=subprocess.DEVNULL)
        raw_out = r.stdout + r.stderr
        rc = r.returncode
    except subprocess.TimeoutExpired as e:
        raw_out = (e.stdout or b"") + (e.stderr or b"")
        rc = "TIMEOUT"
    finally:
        try:
            os.remove(probe_path)
        except OSError:
            pass

    text = raw_out.decode("utf-8", "replace").replace("\r", "")
    linesout = [l for l in text.split("\n") if l.strip()]

    probs: list[str] = []
    hit = [l for l in linesout if "__PROBE_OK__" in l]
    if not hit:
        probs.append("干跑没能到达启动行（exit=%s）" % rc)
    else:
        vals = re.findall(r"\[([^\]]*)\]", hit[-1])
        empties = [probe_vars[i] for i, v in enumerate(vals) if not v.strip()]
        if empties:
            probs.append("这些变量展开为空：%s —— 典型的字节漂移症状"
                         % "、".join(empties))
        if rc == 0 or rc == "TIMEOUT":
            pass
        else:
            probs.append("干跑退出码 = %s" % rc)
    for bad in ("is not recognized", "\ufffd\ufffd"):
        if bad in text:
            probs.append("cmd 报了解析错误（见到 %r）" % bad)
            break

    summary = "干跑 exit=%s  探针: %s" % (rc, hit[-1].strip() if hit else "—")
    return (not probs), summary + ("" if not probs else "  ||  " + " ; ".join(probs))


def main() -> int:
    do_run = "--run" in sys.argv
    bats = find_bats()
    print("检查 %d 个 .bat（目录 %s）" % (len(bats), APPDIR))
    if do_run:
        print("模式：静态检查 + cmd 干跑\n")
    else:
        print("模式：仅静态检查（加 --run 可让 cmd 干跑验证变量）\n")

    failed = 0
    for path in bats:
        name = os.path.relpath(path, APPDIR)
        problems, raw = static_check(path)
        print("-" * 66)
        print("%s  (%d 字节)" % (name, len(raw)))
        if problems:
            failed += 1
            for p in problems:
                print("   [FAIL] %s" % p)
        else:
            print("   [ ok ] 纯 ASCII，无 BOM")
        if do_run:
            ok, msg = dry_run(path, raw)
            print("   [%s] %s" % (" ok " if ok else "FAIL", msg))
            if not ok:
                failed += 1

    print("-" * 66)
    if failed:
        print("结论：%d 个文件有问题。bat 必须保持纯 ASCII 才能被 cmd 正确解析。" % failed)
        print("修法：把所有中文改成英文，或放进 Python 输出里。")
    else:
        print("结论：全部通过。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
