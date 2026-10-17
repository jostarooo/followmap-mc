# -*- coding: utf-8 -*-
"""自检用：列出标题含关键词的窗口，报可见性 / 最小化 / 位置尺寸（DPI 感知）。"""
import ctypes
import sys
from ctypes import wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

u = ctypes.windll.user32
needle = sys.argv[1] if len(sys.argv) > 1 else ""
rows = []


@ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
def cb(hwnd, _lp):
    n = u.GetWindowTextLengthW(hwnd)
    if n:
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        if needle in buf.value:
            r = wintypes.RECT()
            u.GetWindowRect(hwnd, ctypes.byref(r))
            rows.append((hwnd, buf.value, bool(u.IsWindowVisible(hwnd)),
                         bool(u.IsIconic(hwnd)), r.left, r.top,
                         r.right - r.left, r.bottom - r.top))
    return True


u.EnumWindows(cb, 0)
for hwnd, title, vis, minz, x, y, w, h in rows:
    print("hwnd=%-10s vis=%-5s minimized=%-5s pos=(%s,%s) size=%sx%s  %r"
          % (hwnd, vis, minz, x, y, w, h, title))
if not rows:
    print("没找到:", needle)
