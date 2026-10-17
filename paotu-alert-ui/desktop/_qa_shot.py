# -*- coding: utf-8 -*-
"""QA 抓图：按窗口标题找到目标窗口，用 PrintWindow(PW_RENDERFULLCONTENT) 抓下来存 PNG。

为什么不用普通截屏：窗口可能被别的程序挡住或不在前台，而 PrintWindow 直接让窗口
自己往内存 DC 里画，层叠顺序无关（WebView2 是 DirectComposition 内容，必须用
flag=2 的 PW_RENDERFULLCONTENT 才抓得到内容）。

用法: python _qa_shot.py <标题关键词> <输出png> [等待秒数]
"""
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
# 关键：先声明 DPI 感知，否则 GetWindowRect 返回的是被虚拟化的坐标
# （本机显示缩放 150%，不声明就只能抓到窗口左侧 2/3，看起来像"页面溢出"）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)      # PER_MONITOR_AWARE_V2
except Exception:                                        # noqa: BLE001
    user32.SetProcessDPIAware()
PW_RENDERFULLCONTENT = 0x00000002
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def find_windows(needle: str):
    hits = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if needle in buf.value:
                    hits.append((hwnd, buf.value))
        return True

    user32.EnumWindows(cb, 0)
    return hits


def grab(hwnd, path: Path):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        raise RuntimeError("窗口尺寸异常 %dx%d" % (w, h))
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    ok = user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)
    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h                       # 负数 = 自上而下
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), DIB_RGB_COLORS)
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1)
    img.convert("RGB").save(path)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    return ok, w, h


def main():
    needle = sys.argv[1]
    out = Path(sys.argv[2])
    wait = float(sys.argv[3]) if len(sys.argv) > 3 else 0
    if wait:
        time.sleep(wait)
    hits = find_windows(needle)
    if not hits:
        print("未找到窗口:", needle)
        return 1
    hwnd, title = hits[0]
    ok, w, h = grab(hwnd, out)
    print("窗口: %r hwnd=%s PrintWindow=%s 尺寸=%dx%d → %s" % (title, hwnd, ok, w, h, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
