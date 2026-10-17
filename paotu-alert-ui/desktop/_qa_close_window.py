# -*- coding: utf-8 -*-
"""自检用：按标题给窗口发 WM_CLOSE（等价于用户点右上角 X）。"""
import ctypes
import sys
from ctypes import wintypes

u = ctypes.windll.user32
WM_CLOSE = 0x0010
needle = sys.argv[1]
hits = []


@ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
def cb(hwnd, _lp):
    n = u.GetWindowTextLengthW(hwnd)
    if n:
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        if needle in buf.value and u.IsWindowVisible(hwnd):
            hits.append((hwnd, buf.value))
    return True


u.EnumWindows(cb, 0)
for hwnd, title in hits:
    u.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    print("已发送 WM_CLOSE → %r hwnd=%s" % (title, hwnd))
if not hits:
    print("没找到窗口:", needle)
