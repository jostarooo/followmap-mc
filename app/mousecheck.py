#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""mousecheck —— 诊断真实鼠标事件为什么收不到（不依赖用户操作）

背景
----
B 通道（fishkey.py）实测收到了键盘事件、却**一条鼠标事件都没有**。
而 fishkey 里鼠标与键盘是同一个 `RegisterRawInputDevices` 一起注册的，
`--selftest` 里鼠标解析又是通过的 —— 所以问题必然出在**真实运行时的投递环节**。

本工具用**自己注入的合成鼠标事件**做闭环验证：
  A. 先只注册鼠标，用 SendInput 发一次左键按下/抬起 -> 看能否通过 Raw Input 收到
     · 收到  => 注册与解析链路本身没问题，真凶在"别的进程抢走了鼠标投递"
     · 收不到=> message-only 窗口（HWND_MESSAGE）+ Raw Input 的组合有问题
  B. 再对拍三种注册形态，锁定正确写法
     1) HWND_MESSAGE（当前 fishkey 的写法）
     2) 普通隐藏窗口（WS_POPUP，不显示）
     3) HWND_MESSAGE 但用 RIDEV_INPUTSINK|RIDEV_DEVNOTIFY

用法：
    python mousecheck.py            # 跑完整诊断
    python mousecheck.py --live 15  # 额外进入 15 秒实时监听（你自己点鼠标验证）
"""
import argparse
import ctypes
import os
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
RIDEV_DEVNOTIFY = 0x00002000
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIM_TYPEKEYBOARD = 1

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
RI_MOUSE_LEFT_BUTTON_UP = 0x0002


# ------------------------------------------------------------------ 结构体
class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT),
                ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD),
                ("hwndTarget", wintypes.HWND)]


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
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.SendInput.restype = wintypes.UINT
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


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


# ------------------------------------------------------------------ 一次试验
class Trial:
    """在指定窗口形态下注册鼠标 Raw Input，用合成点击验证能否收到。"""

    def __init__(self, cls_name, message_only, flags, label):
        self.label = label
        self.cls_name = cls_name
        self.message_only = message_only
        self.flags = flags
        self.hits = []
        self.hwnd = None
        self._wndproc = None

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
                            self.hits.append(("mouse", ri.data.mouse.usButtonFlags))
                        elif ri.header.dwType == RIM_TYPEKEYBOARD:
                            self.hits.append(("kbd", ri.data.keyboard.VKey))
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:                              # noqa: BLE001
            pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self):
        hinst = kernel32.GetModuleHandleW(None)
        self._wndproc = WNDPROC(self._wnd_proc)
        wc = WNDCLASSEXW_STRUCT()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW_STRUCT)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = self.cls_name
        if not user32.RegisterClassExW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:
                return "RegisterClassExW 失败 err=%d" % err

        parent = HWND_MESSAGE if self.message_only else None
        style = 0 if self.message_only else 0x80000000   # WS_POPUP
        self.hwnd = user32.CreateWindowExW(0, self.cls_name, "mousecheck", style,
                                           0, 0, 0, 0, parent, None, hinst, None)
        if not self.hwnd:
            return "CreateWindowExW 失败 err=%d" % ctypes.get_last_error()

        dev = RAWINPUTDEVICE(0x01, 0x02, self.flags, self.hwnd)
        if not user32.RegisterRawInputDevices(ctypes.byref(dev), 1,
                                              ctypes.sizeof(RAWINPUTDEVICE)):
            return "RegisterRawInputDevices 失败 err=%d" % ctypes.get_last_error()

        # ---- 自我注入一次左键 down/up（合成事件也要能走通才说明链路 OK）----
        inputs = (INPUT * 2)(
            INPUT(INPUT_MOUSE, _INPUTUNION(MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, None))),
            INPUT(INPUT_MOUSE, _INPUTUNION(MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, None))),
        )
        user32.SendInput(2, inputs, ctypes.sizeof(INPUT))

        # ---- 抽 400ms 消息 ----
        msg = wintypes.MSG()
        deadline = time.time() + 0.4
        while time.time() < deadline:
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_QUIT:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.002)

        mouse_hits = [h for h in self.hits if h[0] == "mouse"]
        return "收到鼠标事件 %d 条" % len(mouse_hits)

    def destroy(self):
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)


def live_listen(seconds):
    """实时监听：用户自己动鼠标/按键，直接看有没有事件进来。"""
    import json
    print("=" * 68)
    print(" 实时监听 %d 秒 —— 请现在去点鼠标左键、动动鼠标、按几个键" % seconds)
    print("=" * 68)
    rec_hits = []

    hinst = kernel32.GetModuleHandleW(None)
    cls_name = "mousecheck_live_wnd"
    holder = [None]

    def proc(hwnd, msg, wparam, lparam):
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
                            bf = ri.data.mouse.usButtonFlags
                            if bf:
                                rec_hits.append(("mouse", bf, ri.data.mouse.lLastX,
                                                 ri.data.mouse.lLastY))
                        elif ri.header.dwType == RIM_TYPEKEYBOARD:
                            rec_hits.append(("kbd", ri.data.keyboard.VKey, 0, 0))
                return 0
        except Exception:                              # noqa: BLE001
            pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    holder[0] = WNDPROC(proc)
    wc = WNDCLASSEXW_STRUCT()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW_STRUCT)
    wc.lpfnWndProc = holder[0]
    wc.hInstance = hinst
    wc.lpszClassName = cls_name
    user32.RegisterClassExW(ctypes.byref(wc))
    hwnd = user32.CreateWindowExW(0, cls_name, "live", 0x80000000,
                                  0, 0, 0, 0, None, None, hinst, None)
    devs = (RAWINPUTDEVICE * 2)(
        RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, hwnd),
        RAWINPUTDEVICE(0x01, 0x06, RIDEV_INPUTSINK, hwnd),
    )
    user32.RegisterRawInputDevices(devs, 2, ctypes.sizeof(RAWINPUTDEVICE))

    msg = wintypes.MSG()
    deadline = time.time() + seconds
    while time.time() < deadline:
        if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            if msg.message == WM_QUIT:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        else:
            time.sleep(0.002)

    nm = len([h for h in rec_hits if h[0] == "mouse"])
    nk = len([h for h in rec_hits if h[0] == "kbd"])
    print("\n结果：鼠标 %d 条 / 键盘 %d 条" % (nm, nk))
    if rec_hits:
        print("样本（前 25 条）：")
        for h in rec_hits[:25]:
            print("   ", h)
    if nm == 0:
        print("\n[!] 一条鼠标事件都没收到 —— 说明系统在本进程注册的 sink 上不投递鼠标。")
    return 0


def main():
    setup_console()
    ap = argparse.ArgumentParser(description="鼠标 Raw Input 投递诊断")
    ap.add_argument("--live", type=float, default=0,
                    help="额外进行 N 秒实时监听（用户自己点鼠标验证）")
    args = ap.parse_args()

    print("=" * 68)
    print(" mousecheck · 鼠标 Raw Input 投递诊断")
    print("=" * 68)
    print(" 结构体: RAWINPUTHEADER=%d  RAWINPUT=%d"
          % (ctypes.sizeof(RAWINPUTHEADER), ctypes.sizeof(RAWINPUT)))
    print()

    trials = [
        ("mousecheck_cls_msg", True, RIDEV_INPUTSINK,
         "① message-only 窗口 + RIDEV_INPUTSINK（fishkey 当前写法）"),
        ("mousecheck_cls_pop", False, RIDEV_INPUTSINK,
         "② 普通隐藏窗口 WS_POPUP + RIDEV_INPUTSINK"),
        ("mousecheck_cls_dev", True, RIDEV_INPUTSINK | RIDEV_DEVNOTIFY,
         "③ message-only + RIDEV_INPUTSINK|RIDEV_DEVNOTIFY"),
    ]
    results = []
    for cls, msgonly, flags, label in trials:
        t = Trial(cls, msgonly, flags, label)
        try:
            r = t.run()
        except Exception as e:                         # noqa: BLE001
            r = "异常: %s" % e
        finally:
            t.destroy()
        ok = r.startswith("收到鼠标事件") and "0 条" not in r
        results.append((label, r, ok))
        print("  %s %s" % ("[v]" if ok else "[X]", label))
        print("       %s" % r)
    print()

    good = [l for l, _, ok in results if ok]
    if good:
        print(" 结论：能用的是 -> %s" % good[0])
    else:
        print(" 结论：三种写法都收不到合成鼠标事件。")
        print("       合成事件走 SendInput，若连它都收不到，说明问题不在窗口形态，")
        print("       而在系统层面（例如安全软件/驱动层拦截，或本进程会话限制）。")

    if args.live > 0:
        print()
        return live_listen(args.live)
    return 0


if __name__ == "__main__":
    sys.exit(main())
