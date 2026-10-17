#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""mousefix —— 在不注入任何输入的前提下，定位鼠标 Raw Input 收不到的原因

与 mousecheck.py 的区别（**重要**）
----------------------------------
mousecheck.py 用 `SendInput` **真的点一下鼠标**来自我闭环，这会占用光标、可能误点东西；
本工具**一次输入都不发**，只做两件只读/被动的事：

  1) `--devices`  枚举系统里所有 Raw Input 设备（含 HID 触摸板集合），
                  看鼠标按键到底走的是哪个 usage page/usage。
  2) `--listen N` 用**两种窗口形态**各被动监听一段时间，让用户自己点鼠标，
                  对比「message-only 窗口」与「普通隐藏窗口」谁能收到。

用法
----
    python mousefix.py --devices            # 秒出，不打扰
    python mousefix.py --listen 15          # 15 秒被动监听，需要你点鼠标
    python mousefix.py --listen 15 --both   # 两种窗口形态各 15 秒自动对拍
"""
import argparse
import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

WM_INPUT = 0x00FF
WM_DESTROY = 0x0002
WM_QUIT = 0x0012
PM_REMOVE = 0x0001
HWND_MESSAGE = wintypes.HWND(-3)

RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007
RIDI_DEVICEINFO = 0x2000000B
RIM_TYPEMOUSE = 0
RIM_TYPEKEYBOARD = 1

WS_POPUP = 0x80000000
WS_EX_TOOLWINDOW = 0x00000080

RI_BTN = {0x0001: "左键↓", 0x0002: "左键↑", 0x0004: "右键↓", 0x0008: "右键↑",
          0x0010: "中键↓", 0x0020: "中键↑", 0x0040: "侧键1↓", 0x0080: "侧键1↑",
          0x0100: "侧键2↓", 0x0200: "侧键2↑",
          0x0400: "滚轮↑", 0x0800: "滚轮↓", 0x1000: "横滚←", 0x2000: "横滚→"}


# ------------------------------------------------------------------ 结构体
class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT),
                ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD),
                ("hwndTarget", wintypes.HWND)]


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [("hDevice", wintypes.HANDLE),
                ("dwType", wintypes.DWORD)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD),
                ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE),
                ("wParam", wintypes.WPARAM)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [("usFlags", wintypes.USHORT),
                ("usButtonFlags", wintypes.USHORT),
                ("usButtonData", wintypes.USHORT),
                ("ulRawButtons", wintypes.ULONG),
                ("lLastX", wintypes.LONG),
                ("lLastY", wintypes.LONG),
                ("ulExtraInformation", wintypes.ULONG)]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [("MakeCode", wintypes.USHORT),
                ("Flags", wintypes.USHORT),
                ("Reserved", wintypes.USHORT),
                ("VKey", wintypes.USHORT),
                ("Message", wintypes.UINT),
                ("ExtraInformation", wintypes.ULONG)]


class _RAWUNION(ctypes.Union):
    _fields_ = [("mouse", RAWMOUSE), ("keyboard", RAWKEYBOARD)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("data", _RAWUNION)]


class WNDCLASSEXW_STRUCT(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT),
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm", wintypes.HICON)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("data", _INPUTUNION)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RID_DEVICE_INFO_MOUSE(ctypes.Structure):
    _fields_ = [("dwId", wintypes.DWORD),
                ("dwNumberOfButtons", wintypes.DWORD),
                ("dwSampleRate", wintypes.DWORD),
                ("fHasHorizontalWheel", wintypes.BOOL)]


class RID_DEVICE_INFO_KEYBOARD(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD),
                ("dwSubType", wintypes.DWORD),
                ("dwKeyboardMode", wintypes.DWORD),
                ("dwNumberOfFunctionKeys", wintypes.DWORD),
                ("dwNumberOfIndicators", wintypes.DWORD),
                ("dwNumberOfKeysTotal", wintypes.DWORD)]


class RID_DEVICE_INFO_HID(ctypes.Structure):
    _fields_ = [("dwVendorId", wintypes.DWORD),
                ("dwProductId", wintypes.DWORD),
                ("dwVersionNumber", wintypes.DWORD),
                ("usUsagePage", wintypes.USHORT),
                ("usUsage", wintypes.USHORT)]


class _RIDUNION(ctypes.Union):
    _fields_ = [("mouse", RID_DEVICE_INFO_MOUSE),
                ("keyboard", RID_DEVICE_INFO_KEYBOARD),
                ("hid", RID_DEVICE_INFO_HID)]


class RID_DEVICE_INFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("dwType", wintypes.DWORD),
                ("data", _RIDUNION)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
user32.RegisterClassExW.restype = wintypes.ATOM
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW_STRUCT)]
user32.GetRawInputData.restype = wintypes.UINT
user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                   ctypes.POINTER(wintypes.UINT), wintypes.UINT]
user32.RegisterRawInputDevices.restype = wintypes.BOOL
user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE),
                                           wintypes.UINT, wintypes.UINT]
user32.GetRawInputDeviceList.restype = wintypes.UINT
user32.GetRawInputDeviceList.argtypes = [ctypes.POINTER(RAWINPUTDEVICELIST),
                                         ctypes.POINTER(wintypes.UINT), wintypes.UINT]
user32.GetRawInputDeviceInfoW.restype = wintypes.UINT
user32.GetRawInputDeviceInfoW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                          ctypes.c_void_p,
                                          ctypes.POINTER(wintypes.UINT)]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.SendInput.restype = wintypes.UINT
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
SM_CXSCREEN = 0
SM_CYSCREEN = 1


def setup_console():
    try:
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:                                  # noqa: BLE001
        pass
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                              # noqa: BLE001
            pass


# ------------------------------------------------------------------ 设备枚举
def list_devices():
    n = wintypes.UINT(0)
    rc = user32.GetRawInputDeviceList(None, ctypes.byref(n),
                                      ctypes.sizeof(RAWINPUTDEVICELIST))
    if rc == 0xFFFFFFFF or n.value == 0:
        print("[X] GetRawInputDeviceList 失败 err=%d" % ctypes.get_last_error())
        return 1
    arr = (RAWINPUTDEVICELIST * n.value)()
    got = user32.GetRawInputDeviceList(arr, ctypes.byref(n),
                                       ctypes.sizeof(RAWINPUTDEVICELIST))
    if got == 0xFFFFFFFF:
        print("[X] 第二次 GetRawInputDeviceList 失败 err=%d" % ctypes.get_last_error())
        return 1
    print("Raw Input 设备共 %d 个：\n" % n.value)
    print("  %-4s %-10s %-12s %s" % ("#", "类型", "usage", "设备名"))
    print("  " + "-" * 76)
    n_mouse = n_kbd = n_other = 0
    for i in range(got):
        h = arr[i].hDevice
        t = arr[i].dwType
        # 设备名
        pcb = wintypes.UINT(0)
        user32.GetRawInputDeviceInfoW(h, RIDI_DEVICENAME, None, ctypes.byref(pcb))
        name = ""
        if pcb.value:
            buf = ctypes.create_unicode_buffer(pcb.value)
            user32.GetRawInputDeviceInfoW(h, RIDI_DEVICENAME, buf, ctypes.byref(pcb))
            name = buf.value
        # 设备信息
        info = RID_DEVICE_INFO()
        info.cbSize = ctypes.sizeof(RID_DEVICE_INFO)
        pcb2 = wintypes.UINT(ctypes.sizeof(RID_DEVICE_INFO))
        ok = user32.GetRawInputDeviceInfoW(h, RIDI_DEVICEINFO,
                                           ctypes.byref(info), ctypes.byref(pcb2))
        if ok == 0xFFFFFFFF:
            usage = "?"
            extra = ""
        elif t == RIM_TYPEMOUSE:
            usage = "{0x01,0x02}"
            extra = "按键=%d 采样=%d 横滚=%s" % (info.data.mouse.dwNumberOfButtons,
                                             info.data.mouse.dwSampleRate,
                                             bool(info.data.mouse.fHasHorizontalWheel))
        elif t == RIM_TYPEKEYBOARD:
            usage = "{0x01,0x06}"
            extra = "键数=%d" % info.data.keyboard.dwNumberOfKeysTotal
        else:
            hp, hu = info.data.hid.usUsagePage, info.data.hid.usUsage
            usage = "{0x%02X,0x%02X}" % (hp, hu)
            extra = "VID=%04X PID=%04X" % (info.data.hid.dwVendorId,
                                           info.data.hid.dwProductId)
        tn = {0: "鼠标", 1: "键盘", 2: "HID"}.get(t, "?%d" % t)
        if t == 0:
            n_mouse += 1
        elif t == 1:
            n_kbd += 1
        else:
            n_other += 1
        print("  %-4d %-10s %-12s %s" % (i, tn, usage, name[:52]))
        if extra:
            print("       %s" % extra)
    print()
    print("  统计：鼠标类 %d / 键盘类 %d / 其它 HID %d" % (n_mouse, n_kbd, n_other))
    print()
    print("  判读要点：")
    print("   · 只要这里有「鼠标」条目，{0x01,0x02} 注册就该有事件；")
    print("   · 若只有触摸板(usage {0x0D,0x05})而点它收不到，说明按键走的是触摸板集合，")
    print("     需要额外注册 {0x0D,0x05}（Windows 精确式触摸板的经典坑）。")
    return 0


# ------------------------------------------------------------------ 被动监听
class Listener:
    def __init__(self, message_only):
        self.message_only = message_only
        self.hwnd = None
        self.hits = []
        self._proc = None

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_INPUT:
                size = wintypes.UINT(0)
                user32.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size),
                                       ctypes.sizeof(RAWINPUTHEADER))
                if size.value:
                    buf = ctypes.create_string_buffer(size.value)
                    got = user32.GetRawInputData(lparam, RID_INPUT, buf,
                                                 ctypes.byref(size),
                                                 ctypes.sizeof(RAWINPUTHEADER))
                    if got != 0xFFFFFFFF:
                        ri = ctypes.cast(buf, ctypes.POINTER(RAWINPUT)).contents
                        if ri.header.dwType == RIM_TYPEMOUSE:
                            self.hits.append(("mouse", ri.data.mouse.usButtonFlags,
                                              ri.data.mouse.lLastX, ri.data.mouse.lLastY))
                        elif ri.header.dwType == RIM_TYPEKEYBOARD:
                            self.hits.append(("kbd", ri.data.keyboard.VKey, 0, 0))
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:                              # noqa: BLE001
            pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def create(self, cls_name):
        hinst = kernel32.GetModuleHandleW(None)
        self._proc = WNDPROC(self._wnd_proc)
        wc = WNDCLASSEXW_STRUCT()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW_STRUCT)
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = cls_name
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:                            # 1410 = 类已注册
                return False, "RegisterClassExW err=%d" % err
        if self.message_only:
            parent, style, exstyle = HWND_MESSAGE, 0, 0
        else:
            parent, style, exstyle = None, WS_POPUP, WS_EX_TOOLWINDOW
        self.hwnd = user32.CreateWindowExW(exstyle, cls_name, "mousefix", style,
                                           0, 0, 0, 0, parent, None, hinst, None)
        if not self.hwnd:
            return False, "CreateWindowExW err=%d" % ctypes.get_last_error()
        devs = (RAWINPUTDEVICE * 2)(
            RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, self.hwnd),
            RAWINPUTDEVICE(0x01, 0x06, RIDEV_INPUTSINK, self.hwnd),
        )
        if not user32.RegisterRawInputDevices(devs, 2, ctypes.sizeof(RAWINPUTDEVICE)):
            return False, "RegisterRawInputDevices err=%d" % ctypes.get_last_error()
        return True, "ok"

    def pump(self, seconds):
        msg = wintypes.MSG()
        end = time.time() + seconds
        while time.time() < end:
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_QUIT:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.002)

    def destroy(self):
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None


def listen(seconds, message_only, tag):
    kind = "message-only 窗口(HWND_MESSAGE)" if message_only else "普通隐藏窗口(WS_POPUP)"
    print("=" * 68)
    print(" [%s] %s —— 现在开始点鼠标左键（多点几下），也可以按键盘对照" % (tag, kind))
    print("        监听 %d 秒…（不会抢光标、不注入任何输入）" % seconds)
    print("=" * 68)
    ls = Listener(message_only)
    ok, why = ls.create("mousefix_%s" % tag)
    if not ok:
        print(" [X] 建窗失败：%s" % why)
        return None
    try:
        ls.pump(seconds)
    finally:
        ls.destroy()
    mice = [h for h in ls.hits if h[0] == "mouse"]
    kbd = [h for h in ls.hits if h[0] == "kbd"]
    presses = [h for h in mice if h[1]]
    print(" 结果：鼠标事件 %d 条（其中按键/滚轮 %d 条），键盘 %d 条"
          % (len(mice), len(presses), len(kbd)))
    for h in presses[:20]:
        names = " ".join(v for k, v in RI_BTN.items() if h[1] & k)
        print("    mouse  btn=0x%04X [%s]  dx=%d dy=%d"
              % (h[1], names or "仅移动", h[2], h[3]))
    return len(presses)


def inject_netzero_move():
    """注入一对 ±1px 的鼠标移动 —— **净位移为 0、不点击、不抢控制**。

    方向朝屏幕中心，保证两步都不会被屏幕边缘夹掉，因此一定能产生两个真实移动事件。
    目的只有一个：验证「Raw Input 管线当前是否能收到鼠标事件」。
    """
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    w = user32.GetSystemMetrics(SM_CXSCREEN)
    h = user32.GetSystemMetrics(SM_CYSCREEN)
    dx = 1 if pt.x < w // 2 else -1
    dy = 1 if pt.y < h // 2 else -1
    inputs = (INPUT * 4)(
        INPUT(INPUT_MOUSE, _INPUTUNION(MOUSEINPUT(dx, 0, 0, MOUSEEVENTF_MOVE, 0, None))),
        INPUT(INPUT_MOUSE, _INPUTUNION(MOUSEINPUT(0, dy, 0, MOUSEEVENTF_MOVE, 0, None))),
        INPUT(INPUT_MOUSE, _INPUTUNION(MOUSEINPUT(-dx, 0, 0, MOUSEEVENTF_MOVE, 0, None))),
        INPUT(INPUT_MOUSE, _INPUTUNION(MOUSEINPUT(0, -dy, 0, MOUSEEVENTF_MOVE, 0, None))),
    )
    sent = user32.SendInput(4, inputs, ctypes.sizeof(INPUT))
    user32.GetCursorPos(ctypes.byref(POINT()))
    return sent, (pt.x, pt.y, dx, dy)


def verify(message_only, tag):
    """闭环自校验：在当前窗口形态下注入净零位移，看能否收到鼠标事件。"""
    kind = "message-only(HWND_MESSAGE)" if message_only else "普通隐藏窗口(WS_POPUP+TOOLWINDOW)"
    ls = Listener(message_only)
    ok, why = ls.create("mousefix_verify_%s" % tag)
    if not ok:
        print(" [X] %s 建窗失败：%s" % (kind, why))
        return None
    try:
        sent, info = inject_netzero_move()
        ls.pump(0.6)
        # 再补一次，防止事件恰好落在窗口建立前的瞬间
        if not any(h[0] == "mouse" for h in ls.hits):
            inject_netzero_move()
            ls.pump(0.6)
    finally:
        ls.destroy()
    mice = [h for h in ls.hits if h[0] == "mouse"]
    kbd = [h for h in ls.hits if h[0] == "kbd"]
    print(" [%s] %s" % ("v" if mice else "X", kind))
    print("       SendInput 返回 %d（4=全部投递成功）；光标 (%d,%d) 方向(%+d,%+d)"
          % (sent, info[0], info[1], info[2], info[3]))
    print("       收到鼠标事件 %d 条 / 键盘 %d 条" % (len(mice), len(kbd)))
    for h in mice[:6]:
        names = " ".join(v for k, v in RI_BTN.items() if h[1] & k)
        print("         btn=0x%04X [%s] dx=%d dy=%d" % (h[1], names or "纯移动", h[2], h[3]))
    return len(mice)


def main():
    setup_console()
    ap = argparse.ArgumentParser(description="鼠标 Raw Input 被动诊断（不注入输入）")
    ap.add_argument("--devices", action="store_true", help="只枚举设备")
    ap.add_argument("--verify", action="store_true",
                    help="闭环自校验（注入净零位移的 ±1px 移动，不点击、不抢控制）")
    ap.add_argument("--listen", type=float, default=0, help="被动监听秒数")
    ap.add_argument("--both", action="store_true", help="两种窗口形态各跑一遍")
    ap.add_argument("--message-only", action="store_true", help="监听用 message-only 窗口")
    args = ap.parse_args()

    if args.verify:
        print("=" * 68)
        print(" mousefix · 闭环自校验（注入净位移为 0 的 ±1px 移动）")
        print("=" * 68)
        a = verify(True, "msg")
        print()
        b = verify(False, "pop")
        print()
        print("=" * 68)
        if (b or 0) > 0 and (a or 0) == 0:
            print(" 结论：**普通隐藏窗口能收到、message-only 收不到** → 改用普通隐藏窗口即可修复")
        elif (a or 0) > 0 and (b or 0) == 0:
            print(" 结论：message-only 能收到（与现有实现一致）→ 根因不在窗口形态")
        elif (a or 0) == 0 and (b or 0) == 0:
            print(" 结论：两种窗口都收不到 → 鼠标 Raw Input 在本会话被整体屏蔽，")
            print("       需查：安全软件/驱动拦截、或鼠标按键走的是非 {0x01,0x02} 集合")
        else:
            print(" 结论：两种窗口都能收到 → 鼠标管线本身正常")
        return 0

    if args.devices or not args.listen:
        return list_devices()
    if args.both:
        a = listen(args.listen, True, "msg")
        print()
        b = listen(args.listen, False, "pop")
        print()
        print("=" * 68)
        print(" 对拍结论")
        print("   message-only 窗口 : 按键 %s 条" % a)
        print("   普通隐藏窗口      : 按键 %s 条" % b)
        if (b or 0) > 0 and (a or 0) == 0:
            print("   => **普通隐藏窗口可用、message-only 不可用** —— 这就是根因")
        elif (a or 0) > 0 and (b or 0) == 0:
            print("   => message-only 可用（与现有实现一致），问题在别处")
        elif (a or 0) == 0 and (b or 0) == 0:
            print("   => 两种都收不到按键 —— 按键很可能走的是触摸板/其它 HID 集合，")
            print("      需注册 {0x0D,0x05}；请把上面的设备枚举结果发我")
        else:
            print("   => 两种都能收到，链路本身没问题")
        return 0
    return listen(args.listen, args.message_only, "msg" if args.message_only else "pop") and 0 or 0


if __name__ == "__main__":
    sys.exit(main())
