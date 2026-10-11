# -*- coding: utf-8 -*-
"""截取正在运行的 Minecraft 窗口（PrintWindow），用于定位小地图与坐标文本。

要点：
- Minecraft (GLFW) 窗口的类名固定为 GLFW30 / GLFW31...
- GetWindowRect 可能因最大化/DWM 返回异常尺寸，改用 GetClientRect + ClientToScreen。
- PrintWindow 走 PW_RENDERFULLCONTENT(0x2) 才能拿到 GL/D3D 渲染内容。
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys

from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 0x00000002


def enum_windows():
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        r = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        out.append((hwnd, buf.value, cls.value, r.left, r.top, r.right, r.bottom))
        return True

    user32.EnumWindows(cb, 0)
    return out


def client_rect_screen(hwnd):
    """返回客户区在屏幕上的 (l, t, r, b)，以及客户区宽高。"""
    cr = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(cr))
    cw, ch = cr.right - cr.left, cr.bottom - cr.top
    origin = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return origin.x, origin.y, origin.x + cw, origin.y + ch, cw, ch


def find_mc():
    """找 Minecraft 窗口：优先 GLFW 类名，其次标题关键字。不做尺寸过滤。"""
    cands = []
    for hwnd, title, cls, l, t, r, b in enum_windows():
        cl = cls.lower()
        tl = title.lower()
        hit = cl.startswith("glfw") or "minecraft" in tl or "方块传说" in title
        if not hit:
            continue
        cl_, ct, cr_, cb_, cw, ch = client_rect_screen(hwnd)
        cands.append({
            "hwnd": hwnd, "title": title, "cls": cls,
            "win": (l, t, r, b), "client": (cl_, ct, cr_, cb_),
            "size": (cw, ch),
        })
    # 客户区大的优先
    cands.sort(key=lambda c: -c["size"][0] * c["size"][1])
    return cands


def capture(hwnd, l, t, r, b, out):
    w, h = r - l, b - t
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    ok = user32.PrintWindow(hwnd, mdc, PW_RENDERFULLCONTENT)
    if not ok:
        user32.PrintWindow(hwnd, mdc, 0)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                    ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    got = gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    if not got:
        return False
    im = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    im.save(out)
    return True


if __name__ == "__main__":
    OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(OUT, exist_ok=True)
    cands = find_mc()
    print("候选窗口:")
    for c in cands:
        print("    hwnd=%s cls=%-10s size=%dx%d title=%s" %
              (c["hwnd"], c["cls"], c["size"][0], c["size"][1], c["title"][:50]))
    if not cands:
        print("\n所有可见窗口:")
        for hwnd, title, cls, l, t, r, b in enum_windows():
            if title.strip():
                print("    %-40s cls=%-28s %dx%d" % (title[:40], cls[:28], r - l, b - t))
        sys.exit(1)
    c = cands[0]
    p = os.path.join(OUT, "mc_shot.png")
    l, t, r, b = c["client"]
    if capture(c["hwnd"], l, t, r, b, p):
        print("已保存:", p, "客户区尺寸=", (r - l, b - t))
    else:
        print("截图失败")
