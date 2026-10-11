# -*- coding: utf-8 -*-
"""两件事：
1) 回归测试：给 launcher 插一行 UTF-8 中文，确认 check_bats.py 能抓住。
2) 端到端：用真实 cmd 跑 launcher（第 4+ 个参数会透传给 app.py），
   加 --selfclose 让它自己关掉窗口，验证整条链路真能开出地图界面。

用法： python _modtest/test_launcher.py
"""
import io
import os
import subprocess

# 本脚本在 app/_modtest/ 下，launcher 在它的上一级
APPDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(APPDIR, "\u542f\u52a8\u8ddf\u968f\u5730\u56fe.bat")
ZH = os.path.join(APPDIR, "__zh_regress.bat")

raw = io.open(SRC, "rb").read()
lines = raw.split(b"\n")

# ---------------- 1) 回归：插一行中文（放在 chcp 之后，复现真实事故） ----------------
pos = next(i for i, l in enumerate(lines) if b"chcp 65001" in l) + 1
zh_line = u'rem 150ms \u91cd\u7ed8\uff1a\u6574\u5c4f\u53d6\u56fe\u5728\u7f13\u5b58\u547d\u4e2d\u4e0b\u53ea\u8981 1~2ms\uff0c\u5237\u65b0\u5feb\u4e00\u500d\uff0c"\u8ddf\u5f97\u4e0a"\u9760\u7684\u5c31\u662f\u5b83'.encode("utf-8")
zh = lines[:pos] + [zh_line] + lines[pos:]
try:
    os.remove(ZH)
except OSError:
    pass
io.open(ZH, "wb").write(b"\n".join(zh))
print("=" * 68)
print("1) 回归测试：往 launcher 插入 1 行 UTF-8 中文，看校验器能否抓住")
print("=" * 68)
r = subprocess.run(["D:\\python\\python.exe", "check_bats.py", "--run"],
                   cwd=APPDIR, capture_output=True, timeout=120,
                   stdin=subprocess.DEVNULL)
txt = (r.stdout + r.stderr).decode("utf-8", "replace")
for l in txt.split("\n"):
    if "__zh_regress" in l or "非 ASCII" in l or "展开为空" in l or "结论" in l or "干跑" in l:
        print("   " + l.strip())
print("   校验器退出码 =", r.returncode, "(非 0 = 成功拦住)")
try:
    os.remove(ZH)
except OSError:
    pass

# ---------------- 2) 端到端：真实启动 ----------------
print()
print("=" * 68)
print("2) 端到端：真实 cmd 启动 launcher（透传 --selfclose 6）")
print("=" * 68)
cmd = ['cmd.exe', '/c', SRC, '520', '150', 'auto', '--selfclose', '6']
r = subprocess.run(cmd, cwd=APPDIR, capture_output=True, timeout=90,
                   stdin=subprocess.DEVNULL)
out = (r.stdout + r.stderr).decode("utf-8", "replace").replace("\r", "")
print("exit =", r.returncode)
for l in out.split("\n"):
    if l.strip():
        print("   |" + l)
ok = (r.returncode == 0) and ("\u5df2\u6e32\u67d3" in out or "selfclose" in out)
print()
print("端到端结论：", "OK - 地图窗口成功开出并自行关闭" if ok else "FAIL")

# ---------------- 3) 静默版端到端（pythonw，无控制台） ----------------
import time

print()
print("=" * 68)
print("3) 静默版端到端：确认 launcher 能把参数交给 app.py 并真的跑起来")
print("=" * 68)
SILENT = os.path.join(APPDIR, "\u542f\u52a8\u8ddf\u968f\u5730\u56fe-\u9759\u9ed8.bat")
FRAME = os.path.join(APPDIR, "out", "follow", "f000.png")

# 判据不用进程计数：`start` 派生的进程在本沙箱里对 tasklist 不可见
# （进程隔离），即使它确实在跑。改成看「有没有产出落盘帧」——
# 让 app.py 走 --selftest（无窗口、会写 out/follow/f000.png）。
base_mt = os.path.getmtime(FRAME) if os.path.exists(FRAME) else 0.0
r = subprocess.run(["cmd.exe", "/c", SILENT, "520", "--selftest", "8"],
                   cwd=APPDIR, capture_output=True, timeout=30,
                   stdin=subprocess.DEVNULL)
print("launcher exit =", r.returncode)
new_mt = 0.0
for _ in range(24):
    time.sleep(0.5)
    if os.path.exists(FRAME):
        new_mt = os.path.getmtime(FRAME)
        if new_mt > base_mt:
            break
ok2 = new_mt > base_mt
print("落盘帧 out/follow/f000.png: 运行前 mtime=%.3f -> 运行后 %.3f" % (base_mt, new_mt))
print("静默版结论：",
      "OK - launcher 成功把参数交给 app.py，并跑出了新的落盘帧" if ok2
      else "FAIL - app.py 没被拉起来 / 没产出新帧")

