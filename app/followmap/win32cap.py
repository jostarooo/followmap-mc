# -*- coding: utf-8 -*-
"""抓取正在运行的 Minecraft 窗口客户区（PrintWindow + PW_RENDERFULLCONTENT）。"""
import ctypes
import ctypes.wintypes as wt
import sys

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 0x00000002
SW_RESTORE = 9
SW_SHOWNOACTIVATE = 4


class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


def enum_windows():
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, lparam):
        n = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if n > 0:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        out.append({"hwnd": hwnd, "title": title, "cls": cls.value,
                    "visible": bool(user32.IsWindowVisible(hwnd)),
                    "iconic": bool(user32.IsIconic(hwnd))})
        return True

    user32.EnumWindows(cb, 0)
    return out


def find_mc():
    """返回 Minecraft 主窗口 info（GLFW 类名优先），按客户区面积降序。"""
    cands = []
    for w in enum_windows():
        cl, tl = w["cls"].lower(), w["title"].lower()
        if cl.startswith("glfw") and "helper" not in cl:
            w["score"] = 2
        elif "minecraft" in tl or "方块传说" in w["title"]:
            w["score"] = 1
        else:
            continue
        cr = client_rect(w["hwnd"])
        w["client"] = cr
        w["area"] = cr[4] * cr[5] if cr else 0
        cands.append(w)
    cands.sort(key=lambda x: (-x["score"], -x["area"]))
    return cands


def client_rect(hwnd):
    """客户区在屏幕上的 (l,t,r,b,w,h)。最小化时返回 None。"""
    if user32.IsIconic(hwnd):
        return None
    cr = wt.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(cr)):
        return None
    cw, ch = cr.right - cr.left, cr.bottom - cr.top
    if cw <= 0 or ch <= 0:
        return None
    o = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(o))
    return o.x, o.y, o.x + cw, o.y + ch, cw, ch


def restore(hwnd, activate=False):
    user32.ShowWindow(hwnd, SW_RESTORE if activate else SW_SHOWNOACTIVATE)


def capture(hwnd):
    """截取客户区，返回 PIL.Image(RGB)；失败返回 (None, 原因)。"""
    from PIL import Image
    rc = client_rect(hwnd)
    if rc is None:
        return None, "窗口已最小化或无客户区"
    l, t, r, b, w, h = rc
    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    ok = user32.PrintWindow(hwnd, mdc, PW_RENDERFULLCONTENT)
    if not ok:
        user32.PrintWindow(hwnd, mdc, 0)
    bi = _BMIH()
    bi.biSize = ctypes.sizeof(_BMIH)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    got = gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    try:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hwnd, hdc)
    except Exception:
        pass
    if not got:
        return None, "GetDIBits 失败"
    im = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    return im, None


if __name__ == "__main__":
    ws = find_mc()
    print("候选窗口:", len(ws))
    for w in ws:
        print("   hwnd=%s cls=%-10s iconic=%s client=%s title=%s"
              % (w["hwnd"], w["cls"], w["iconic"], w.get("client"), w["title"][:50]))
    if not ws:
        sys.exit(1)
    im, err = capture(ws[0]["hwnd"])
    print("截图:", (im.size if im else None), err)
