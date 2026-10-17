#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fishkey —— 方块传说钓鱼采集 · 键鼠只读记录器（B 通道：监督标签）

为什么需要它
------------
模组探针（A 通道）只知道"收到了什么数据"，**不知道这一局成功还是失败、你按得对不对**。
监督信号只能来自你的操作流。B 通道的职责就两件：
  1. 把 A 的连续数据**切成逐局 episode**（打点键 1 为界锚）；
  2. 给每局打上**成功 / 失败**标签（打点键 2 / 3）。

★ 为什么用 Raw Input 而不是键盘钩子 ★
`SetWindowsHookEx(WH_MOUSE_LL / WH_KEYBOARD_LL)` 是**全局钩子，会参与输入链路**，
和别的自动化软件（比如 Windows-MCP）互相看不见对方，用户会觉得"键鼠随机失灵"。
Raw Input（`RIDEV_INPUTSINK`）**只读不拦**，而且是**硬件级原始事件**——
不会被 `SendInput` 注入的合成事件污染。这一点在后续"回放验证"时是刚需：
必须能区分"真人按的"和"程序注入的"。

采集协议（重要：没有协议，数据就是垃圾）
--------------------------------------
    i    一局开始（刚抛竿 / 刚进入收杆小游戏） -> episode 起点锚
    .    这一局成功                             -> 正样本标签
    '    这一局失败                             -> 负样本标签

    ★ 三个键可用 --key-start / --key-success / --key-fail 换掉。
      选键三原则：① 游戏里不能有功能绑定（一按就开背包/切全屏就废了）；
                  ② 三个键彼此不重复；③ 单手够得着，不用低头找。
      （脚本会读 options.txt 自动检查冲突。旧协议的 F11=全屏、F9=clickthrough，
        就是这个坑，所以才换键。）

规则：每种形态至少 20 局；**刻意早按/晚按**，把绿区上下沿逼出来（比 20 次完美命中值钱）。

输出：`~/.fishprobe/inputs/session-<时间>-keys.jsonl`，与模组探针**同格式、同墙钟**，
      两路数据靠 `wall`（Unix epoch 毫秒）对齐。

用法：
    python fishkey.py                     # 开始记录（Ctrl+C 结束）
    python fishkey.py --list              # 只自检 Raw Input 是否注册成功
    python fishkey.py --out D:\\some\\dir   # 指定输出目录
    python fishkey.py --selftest          # 离线自检（不碰真实输入设备）
    python fishkey.py --duration 30       # 记 30 秒自动停（自动化测试用）
"""
import argparse
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)

# ------------------------------------------------------------------ 常量
WM_INPUT = 0x00FF
WM_DESTROY = 0x0002
WM_QUIT = 0x0012
PM_REMOVE = 0x0001
HWND_MESSAGE = wintypes.HWND(-3)

RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIM_TYPEKEYBOARD = 1

RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
RI_MOUSE_LEFT_BUTTON_UP = 0x0002
RI_MOUSE_RIGHT_BUTTON_DOWN = 0x0004
RI_MOUSE_RIGHT_BUTTON_UP = 0x0008
RI_MOUSE_MIDDLE_BUTTON_DOWN = 0x0010
RI_MOUSE_MIDDLE_BUTTON_UP = 0x0020
RI_MOUSE_BUTTON_4_DOWN = 0x0040
RI_MOUSE_BUTTON_4_UP = 0x0080
RI_MOUSE_BUTTON_5_DOWN = 0x0100
RI_MOUSE_BUTTON_5_UP = 0x0200

RI_KEY_BREAK = 0x01     # 该位为 1 = 抬起

# ---- 鼠标按键的虚拟键码（用于 GetAsyncKeyState 轮询兜底）----
# 为什么要有这个兜底：2026-10-14 实测，Raw Input 的鼠标**移动**能正常收到
# （自注入 ±1px 与真人移动都进得来），但整场采集里**一条鼠标按键事件都没有**，
# 而同一时间有 15 局小游戏明确提示「按下 左键 开始」。
# 说明：笔记本**精确式触摸板(PTP)**的"轻触点击"是驱动**合成**出来的鼠标输入，
# 不走 `{0x01,0x02}` 这条原始鼠标集合，Raw Input 看不到它。
# `GetAsyncKeyState` 读的是**最终生效的按键状态**，不论来源（物理鼠标 / 触摸板轻触 /
# 驱动合成）都能读到，且是纯读取，不装钩子、不注入、不拦输入。
VK_MOUSE_BUTTONS = {0x01: "left", 0x02: "right", 0x04: "middle",
                    0x05: "x1", 0x06: "x2"}
POLL_INTERVAL_S = 0.004        # 250Hz：人手最快动作也有几十毫秒，够用
RAW_DEDUP_MS = 40              # 与 Raw Input 的同一动作去重窗口

# ---- 采集协议：三个打点键（默认 i / . / '）----
DEFAULT_MARK_CHARS = {"start": "i", "success": ".", "fail": "'"}
MARK_ROLES = {"start": "episode_start", "success": "success", "fail": "fail"}
SLOT_LABEL = {"start": "一局开始", "success": "这一局成功", "fail": "这一局失败"}

# 键盘布局差异时的兜底表（直接查 VkKeyScanW，查不到才用它）
VK_FALLBACK = {"i": 0x49, ".": 0xBE, "'": 0xDE}

# options.txt 里的 GLFW 键名（用于冲突检查）
GLFW_NAME = {".": "period", "'": "apostrophe", ",": "comma", ";": "semicolon",
             "/": "slash", "\\": "backslash", "-": "minus", "=": "equal",
             "[": "left.bracket", "]": "right.bracket", "`": "grave"}

VK_NAMES = {
    0x08: "BACK", 0x09: "TAB", 0x0D: "ENTER", 0x10: "SHIFT", 0x11: "CTRL",
    0x12: "ALT", 0x1B: "ESC", 0x20: "SPACE", 0x25: "LEFT", 0x26: "UP",
    0x27: "RIGHT", 0x28: "DOWN", 0xA0: "LSHIFT", 0xA1: "RSHIFT",
    0xA2: "LCTRL", 0xA3: "RCTRL",
}


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


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [("hDevice", wintypes.HANDLE), ("dwType", wintypes.DWORD)]


def count_raw_devices():
    """返回 (鼠标类设备数, 键盘类设备数, 总设备数)；查不到返回 None。

    启动时打一行，是为了避免再出现"静默收不到事件"——2 分钟白采一圈才发现。
    """
    n = wintypes.UINT(0)
    rc = user32.GetRawInputDeviceList(None, ctypes.byref(n),
                                      ctypes.sizeof(RAWINPUTDEVICELIST))
    if rc == 0xFFFFFFFF or not n.value:
        return None
    arr = (RAWINPUTDEVICELIST * n.value)()
    got = user32.GetRawInputDeviceList(arr, ctypes.byref(n),
                                       ctypes.sizeof(RAWINPUTDEVICELIST))
    if got == 0xFFFFFFFF:
        return None
    m = k = 0
    for i in range(got):
        if arr[i].dwType == RIM_TYPEMOUSE:
            m += 1
        elif arr[i].dwType == RIM_TYPEKEYBOARD:
            k += 1
    return (m, k, got)


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


# 函数签名（64 位下必须显式声明 restype/argtypes，否则指针会被截断成 int32）
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
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT, wintypes.UINT]
# VkKeyScanW 返回 SHORT，负值(-1)=该字符在当前布局打不出来。必须声明 c_short，
# 否则 ctypes 默认按 int 收，-1 会被读成 0x0000FFFF，落进 VK 表里就是灾难。
user32.VkKeyScanW.restype = ctypes.c_short
user32.VkKeyScanW.argtypes = [ctypes.c_wchar]
# GetAsyncKeyState 返回 SHORT：最高位(0x8000)=当前按下。
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
# 设备枚举：启动时自检「系统到底有没有鼠标类设备」，避免又出现"静默收不到"
user32.GetRawInputDeviceList.restype = wintypes.UINT
user32.GetRawInputDeviceList.argtypes = [ctypes.c_void_p,
                                         ctypes.POINTER(wintypes.UINT), wintypes.UINT]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


# ------------------------------------------------------------------ 键位
def vk_of(ch):
    """字符 -> 虚拟键码 VK（跟随当前键盘布局；查不到退回兜底表）。"""
    try:
        r = user32.VkKeyScanW(ch)
        if r != -1:
            return r & 0xFF
    except Exception:                                  # noqa: BLE001
        pass
    return VK_FALLBACK.get(ch)


def build_marks(chars):
    """{'start': 'i', ...} -> {VK: (显示名, role)}。"""
    out = {}
    for slot, ch in chars.items():
        vk = vk_of(ch)
        if vk is not None:
            out[vk] = (ch, MARK_ROLES[slot])
    return out


# ------------------------------------------------------------------ 环境
def setup_console():
    """让中文在「真控制台」和「重定向到文件」两种情况下都能正确输出。

    Python 在真控制台下走 WriteConsoleW，本来就正确；但一旦 stdout 被重定向，
    它就退回 locale 编码（简中 Windows = GBK），于是日志变乱码。这里显式把
    控制台代码页与流编码都钉到 UTF-8，两种情况都稳。
    """
    try:
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:                                  # noqa: BLE001
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                              # noqa: BLE001
            pass


# ------------------------------------------------------------------ 记录器
class Recorder:
    def __init__(self, out_dir, marks=None, poll_buttons=True):
        self.out_dir = out_dir
        self.marks = marks if marks is not None else build_marks(DEFAULT_MARK_CHARS)
        self.fh = None
        self.path = None
        self.pressed_kbd = set()
        self.pressed_mouse = set()
        self.n_events = 0
        self.n_marks = 0
        self.t0 = time.perf_counter_ns()
        # ---- 鼠标按键兜底（GetAsyncKeyState 轮询）----
        self.use_poll = poll_buttons
        self._poll_state = {name: False for name in VK_MOUSE_BUTTONS.values()}
        self._last_raw_ms = {name: -10 ** 9 for name in VK_MOUSE_BUTTONS.values()}
        self.n_raw_mouse = 0
        self.n_poll_mouse = 0
        self.n_poll_dup = 0
        self.t_start = time.time()

    # ---- 时间：与 Java 的 System.currentTimeMillis() 同为 Unix epoch 毫秒 ----
    def _stamps(self):
        return (round((time.perf_counter_ns() - self.t0) / 1e9, 6),
                time.time_ns() // 1_000_000)

    def emit(self, obj):
        t, wall = self._stamps()
        obj = dict(obj)
        obj["t"] = t
        obj["wall"] = wall
        # 保持与模组探针一致的键序：t, wall, type, ...
        ordered = {"t": obj.pop("t"), "wall": obj.pop("wall"), "type": obj.pop("type")}
        ordered.update(obj)
        self.fh.write(json.dumps(ordered, ensure_ascii=False) + "\n")
        self.fh.flush()
        self.n_events += 1

    def open(self):
        os.makedirs(self.out_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.path = os.path.join(self.out_dir, "session-%s-keys.jsonl" % ts)
        self.fh = open(self.path, "a", encoding="utf-8", newline="\n")
        self.emit({"type": "session", "event": "open", "source": "fishkey",
                   "file": os.path.basename(self.path),
                   "marks": {k: v[0] for k, v in sorted(self.marks.items())}})

    def close(self):
        if self.fh:
            try:
                self.emit({"type": "session", "event": "close",
                           "events": self.n_events})
                self.fh.close()
            except Exception:                          # noqa: BLE001
                pass
            self.fh = None

    # ---- 事件处理 ----
    def on_keyboard(self, kb):
        vk = kb.VKey
        if vk == 0 or vk == 0xFF:      # 某些伪键（如 PrintScreen 的抬起）会被置 0xFF
            return
        up = bool(kb.Flags & RI_KEY_BREAK)
        if up:
            if vk not in self.pressed_kbd:
                return                  # 没见过按下就不记抬起（去抖动）
            self.pressed_kbd.discard(vk)
        else:
            if vk in self.pressed_kbd:
                return                  # 按住不放的自动重复，只记第一次
            self.pressed_kbd.add(vk)

        mark = self.marks.get(vk)
        name = VK_NAMES.get(vk) or (mark[0] if mark else "vk%02X" % vk)
        ev = {"type": "key", "dev": "keyboard", "vk": vk, "name": name,
              "act": "up" if up else "down"}
        if mark:
            ev["mark"] = mark[1]        # 打点键同时标出 role，方便人工核对
        self.emit(ev)

        if not up and mark:             # 打点只在「按下」那一下产生，避免抬起重复计数
            self.n_marks += 1
            self.emit({"type": "mark", "key": mark[0], "role": mark[1]})

    def on_mouse(self, ms):
        flags = ms.usButtonFlags
        pairs = [
            (RI_MOUSE_LEFT_BUTTON_DOWN, RI_MOUSE_LEFT_BUTTON_UP, "left"),
            (RI_MOUSE_RIGHT_BUTTON_DOWN, RI_MOUSE_RIGHT_BUTTON_UP, "right"),
            (RI_MOUSE_MIDDLE_BUTTON_DOWN, RI_MOUSE_MIDDLE_BUTTON_UP, "middle"),
            (RI_MOUSE_BUTTON_4_DOWN, RI_MOUSE_BUTTON_4_UP, "x1"),
            (RI_MOUSE_BUTTON_5_DOWN, RI_MOUSE_BUTTON_5_UP, "x2"),
        ]
        for down_f, up_f, name in pairs:
            if flags & down_f:
                if name in self.pressed_mouse:
                    continue
                self.pressed_mouse.add(name)
                self._mark_raw(name)
                self.emit({"type": "mouse", "dev": "mouse", "btn": name,
                           "act": "down", "src": "raw"})
            elif flags & up_f:
                if name not in self.pressed_mouse:
                    continue
                self.pressed_mouse.discard(name)
                self._mark_raw(name)
                self.emit({"type": "mouse", "dev": "mouse", "btn": name,
                           "act": "up", "src": "raw"})

    def _mark_raw(self, name):
        self.n_raw_mouse += 1
        self._last_raw_ms[name] = time.time_ns() // 1_000_000

    def poll_buttons(self):
        """轮询鼠标按键状态，兜住 Raw Input 看不到的"合成"鼠标输入。

        2026-10-14 实测结论：Raw Input 的鼠标**移动**完全正常（自注入与真人移动
        都收得到），但整场只有"按下左键"的小游戏里**一条按键事件都没有**。
        原因是笔记本**精确式触摸板**的轻触点击由驱动**合成**，不走 `{0x01,0x02}`
        原始鼠标集合 —— 而 `GetAsyncKeyState` 读的是**最终生效的按键状态**，
        不论来源（外接鼠标 / 触摸板轻触 / 驱动合成）都能读到。
        纯读取：不装钩子、不注入、不拦输入，不影响游戏。
        """
        if not self.use_poll:
            return
        now = time.time_ns() // 1_000_000
        for vk, name in VK_MOUSE_BUTTONS.items():
            down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
            if down == self._poll_state[name]:
                continue
            self._poll_state[name] = down
            if now - self._last_raw_ms.get(name, -10 ** 9) <= RAW_DEDUP_MS:
                self.n_poll_dup += 1          # Raw Input 刚记过这一下，去重
                continue
            self.n_poll_mouse += 1
            self.emit({"type": "mouse", "dev": "poll", "btn": name,
                       "act": "down" if down else "up", "src": "poll"})


# ------------------------------------------------------------------ 主流程
def handle_raw_bytes(raw, rec):
    """从 RAWINPUT 原始字节解析并分发。

    单独抽出来是为了让 --selftest 能构造假事件走**同一条解析路径**——
    结构体的字段偏移/大小写错的话，真实跑起来只会"静默收不到事件"，
    极难排查；离线喂字节是唯一能提前发现的办法。
    """
    buf = ctypes.create_string_buffer(raw, len(raw))
    ri = ctypes.cast(buf, ctypes.POINTER(RAWINPUT)).contents
    if ri.header.dwType == RIM_TYPEKEYBOARD:
        rec.on_keyboard(ri.data.keyboard)
    elif ri.header.dwType == RIM_TYPEMOUSE:
        rec.on_mouse(ri.data.mouse)


def parse_input(lparam, rec):
    """从 WM_INPUT 的 lParam 取出 RAWINPUT 并分发。"""
    size = wintypes.UINT(0)
    user32.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size),
                           ctypes.sizeof(RAWINPUTHEADER))
    if size.value == 0:
        return
    buf = ctypes.create_string_buffer(size.value)
    got = user32.GetRawInputData(lparam, RID_INPUT, buf, ctypes.byref(size),
                                 ctypes.sizeof(RAWINPUTHEADER))
    if got == 0xFFFFFFFF:
        return
    handle_raw_bytes(buf.raw, rec)


# ------------------------------------------------------------------ 键位冲突检查
GAME_DIR_CANDIDATES = [
    r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14",
    r"D:\config\game\mc\方块传说V3.0客户端 2K(2560×1440)\.minecraft",
]


def check_keybinds(chars, game_dir=None):
    """读 options.txt，看这三个字符有没有被游戏/模组占用。

    占用不一定是致命的（有些绑定只在特定界面生效），但**一按就有副作用的键不能用**，
    必须让用户自己判断。读不到就静默跳过，不打扰。
    """
    cands = [game_dir] if game_dir else GAME_DIR_CANDIDATES
    options = None
    for d in cands:
        if not d:
            continue
        p = os.path.join(d, "options.txt")
        if os.path.isfile(p):
            options = p
            break
    if not options:
        return []
    try:
        with open(options, encoding="utf-8", errors="replace") as fh:
            lines = [l.rstrip("\n") for l in fh]
    except Exception:                                  # noqa: BLE001
        return []

    hits = []
    for slot, ch in chars.items():
        glfw = GLFW_NAME.get(ch, ch.lower() if ch.isalnum() else None)
        if not glfw:
            continue
        needle = "key.keyboard.%s" % glfw
        for l in lines:
            if l.startswith("key_") and l.endswith(needle):
                hits.append((ch, SLOT_LABEL[slot], l.split(":", 1)[0][4:]))
    return hits


# ------------------------------------------------------------------ 自检
def selftest(chars=None):
    """构造假 RAWINPUT 字节，验证「结构体解析 -> 记录 -> JSONL」全链路。

    不碰任何真实输入设备，因此可以随时跑。覆盖：三个打点键、键盘按下/抬起去重、
    鼠标左键按下/抬起，以及**换键后 role 是否跟着变**。
    """
    import tempfile
    chars = dict(DEFAULT_MARK_CHARS, **(chars or {}))
    marks = build_marks(chars)
    v_start, v_ok, v_bad = (vk_of(chars["start"]), vk_of(chars["success"]),
                            vk_of(chars["fail"]))

    tmp = tempfile.mkdtemp(prefix="fishkey-selftest-")
    rec = Recorder(tmp, marks)
    rec.open()

    def kbd(vk, up=False):
        ri = RAWINPUT()
        ri.header.dwType = RIM_TYPEKEYBOARD
        ri.header.dwSize = ctypes.sizeof(RAWINPUT)
        ri.data.keyboard.VKey = vk
        ri.data.keyboard.Flags = RI_KEY_BREAK if up else 0
        ri.data.keyboard.Message = 0x101 if up else 0x100
        return bytes(ri)

    def mouse(btn_flags):
        ri = RAWINPUT()
        ri.header.dwType = RIM_TYPEMOUSE
        ri.header.dwSize = ctypes.sizeof(RAWINPUT)
        ri.data.mouse.usButtonFlags = btn_flags
        return bytes(ri)

    handle_raw_bytes(kbd(v_start), rec)              # 开始键 down -> key + mark
    handle_raw_bytes(kbd(v_start), rec)              # 自动重复  -> 应被去重丢弃
    handle_raw_bytes(kbd(v_start, up=True), rec)     # 开始键 up
    handle_raw_bytes(kbd(v_ok, up=True), rec)        # 无对应按下 -> 应被丢弃
    handle_raw_bytes(kbd(v_ok), rec)                 # 成功键 down
    handle_raw_bytes(kbd(v_ok, up=True), rec)
    handle_raw_bytes(kbd(v_bad), rec)                # 失败键 down
    handle_raw_bytes(kbd(v_bad, up=True), rec)
    handle_raw_bytes(mouse(RI_MOUSE_LEFT_BUTTON_DOWN), rec)
    handle_raw_bytes(mouse(RI_MOUSE_LEFT_BUTTON_UP), rec)
    handle_raw_bytes(mouse(RI_MOUSE_LEFT_BUTTON_DOWN), rec)
    handle_raw_bytes(mouse(RI_MOUSE_LEFT_BUTTON_UP), rec)
    rec.close()

    # ---- 轮询兜底：单独一个记录器 + monkeypatch GetAsyncKeyState，离线验证状态机 ----
    # （不碰真实鼠标：把 GetAsyncKeyState 换成可控假函数，喂"按下/抬起"序列）
    rec2 = Recorder(tempfile.mkdtemp(prefix="fishkey-selftest-poll-"), marks)
    rec2.open()
    fake = {vk: 0 for vk in VK_MOUSE_BUTTONS}
    _orig_gaks = user32.GetAsyncKeyState
    user32.GetAsyncKeyState = (lambda vk: fake.get(vk, 0))
    try:
        rec2.poll_buttons()                 # 初始全抬起：不该产生事件
        idle_n = rec2.n_poll_mouse
        fake[0x01] = -32768                 # 左键按下（0x8000 置位）
        rec2.poll_buttons()
        fake[0x01] = 0                      # 抬起
        rec2.poll_buttons()
        rec2.poll_buttons()                 # 状态没变：不该重复计
        poll_n = rec2.n_poll_mouse
        # 去重：Raw Input 刚记过同一动作，轮询应当让位
        handle_raw_bytes(mouse(RI_MOUSE_LEFT_BUTTON_DOWN), rec2)
        handle_raw_bytes(mouse(RI_MOUSE_LEFT_BUTTON_UP), rec2)
        dup0 = rec2.n_poll_dup
        fake[0x01] = -32768
        rec2.poll_buttons()
        fake[0x01] = 0
        rec2.poll_buttons()
        dup_delta = rec2.n_poll_dup - dup0
        # 等效 --no-poll-buttons：关掉后完全不记
        rec2.use_poll = False
        fake[0x02] = -32768
        rec2.poll_buttons()
        off_n = rec2.n_poll_mouse
        rec2.use_poll = True
        fake[0x02] = 0
    finally:
        user32.GetAsyncKeyState = _orig_gaks
    rec2.close()
    prows = [json.loads(l) for l in open(rec2.path, encoding="utf-8") if l.strip()]
    pmouse = [r for r in prows if r["type"] == "mouse"]
    p_poll = [r for r in pmouse if r.get("src") == "poll"]
    p_raw = [r for r in pmouse if r.get("src") == "raw"]

    rows = [json.loads(l) for l in open(rec.path, encoding="utf-8") if l.strip()]
    keys = [r for r in rows if r["type"] == "key"]
    kdowns = [r for r in keys if r["act"] == "down"]
    marks_ev = [r for r in rows if r["type"] == "mark"]
    mice = [r for r in rows if r["type"] == "mouse"]

    def has_mark(role):
        return any(r["role"] == role for r in marks_ev)

    checks = [
        ("结构体大小 RAWKEYBOARD=%d RAWINPUT=%d" % (ctypes.sizeof(RAWKEYBOARD),
                                                     ctypes.sizeof(RAWINPUT)),
         ctypes.sizeof(RAWINPUTHEADER) == 24 and ctypes.sizeof(RAWINPUT) == 48),
        ("三个打点键 VK 解析成功 (0x%02X/0x%02X/0x%02X)" % (v_start, v_ok, v_bad),
         len(marks) == 3 and None not in (v_start, v_ok, v_bad)),
        ("开始键按下只记一次（自动重复被去重）",
         sum(1 for r in kdowns if r["vk"] == v_start) == 1),
        ("开始键抬起被记录",
         any(r["act"] == "up" and r["vk"] == v_start for r in keys)),
        ("无对应按下的抬起被丢弃（按下 3 次 / 抬起 3 次）",
         len(kdowns) == 3 and len(keys) == 6),
        ("产生 episode_start 标记", has_mark("episode_start")),
        ("产生 success 标记", has_mark("success")),
        ("产生 fail 标记", has_mark("fail")),
        ("mark 只在按下产生，不重复（恰好 3 条）", len(marks_ev) == 3),
        ("mark.key 是配置的字符而非 VK 数字",
         {r["key"] for r in marks_ev} == {chars["start"], chars["success"], chars["fail"]}),
        ("鼠标左键 2 按下 2 抬起", len(mice) == 4),
        ("鼠标事件带来源标记 src=raw", all(r.get("src") == "raw" for r in mice)),
        ("每条都有 t 与 wall",
         all(isinstance(r.get("t"), float) and isinstance(r.get("wall"), int) for r in rows)),
        # ---- 轮询兜底（合成点击唯一读得到的通道）----
        ("轮询兜底：初始全抬起时不产生事件", idle_n == 0),
        ("轮询兜底：捕获 按下+抬起（2 条，src=poll）",
         poll_n == 2 and len(p_poll) == 2),
        ("轮询兜底：与 Raw Input 重复的同一动作被去重（2 条）", dup_delta == 2),
        ("轮询兜底：Raw 产出的仍标 src=raw（2 条）", len(p_raw) == 2),
        ("轮询兜底：关掉开关后完全不记（等效 --no-poll-buttons）", off_n == poll_n),
    ]
    ok = True
    for name, passed in checks:
        print("  %s %s" % ("[v]" if passed else "[X]", name))
        ok = ok and passed
    print("  -- 打点键: 开始=%r 成功=%r 失败=%r" % (chars["start"], chars["success"],
                                                    chars["fail"]))
    print("  -- 事件序列: %s" % ", ".join(r["type"] for r in rows))
    print("  -- 文件: %s" % rec.path)
    return 0 if ok else 1


# ------------------------------------------------------------------ 入口
def main():
    setup_console()

    ap = argparse.ArgumentParser(description="方块传说钓鱼采集 · 键鼠只读记录器")
    ap.add_argument("--out", default=None, help="输出目录（默认 ~/.fishprobe/inputs）")
    ap.add_argument("--list", action="store_true", help="只自检 Raw Input 注册，不进记录循环")
    ap.add_argument("--duration", type=float, default=0,
                    help="记录 N 秒后自动退出（0 = 直到 Ctrl+C）")
    ap.add_argument("--selftest", action="store_true",
                    help="用构造的字节验证解析逻辑，不碰真实输入")
    ap.add_argument("--key-start", default=DEFAULT_MARK_CHARS["start"],
                    help="「一局开始」打点键，单个字符（默认 i）")
    ap.add_argument("--key-success", default=DEFAULT_MARK_CHARS["success"],
                    help="「成功」打点键，单个字符（默认 .）")
    ap.add_argument("--key-fail", default=DEFAULT_MARK_CHARS["fail"],
                    help="「失败」打点键，单个字符（默认 '）")
    ap.add_argument("--game-dir", default=None,
                    help="游戏实例目录（用来自动检查按键冲突；一般不用填）")
    ap.add_argument("--no-poll-buttons", action="store_true",
                    help="关掉鼠标按键轮询兜底（默认开启；Raw Input 收不到的合成点击靠它）")
    ap.add_argument("--mousetest", type=float, default=0,
                    help="鼠标链路实测：N 秒内请点鼠标左键，按来源分别统计后退出")
    ap.add_argument("--heartbeat", type=float, default=60,
                    help="每隔 N 秒打一行进度（0 = 不打）")
    args = ap.parse_args()

    chars = {"start": args.key_start, "success": args.key_success, "fail": args.key_fail}
    for slot, ch in chars.items():
        if len(ch) != 1:
            print("[X] --key-%s 必须是单个字符，收到 %r" % (slot, ch))
            return 2
    marks = build_marks(chars)
    if len(marks) != 3:
        print("[X] 三个打点键里有重复或无法识别（当前 %r），请换键。" % (chars,))
        return 2

    if args.selftest:
        print("=" * 66)
        print(" fishkey · 解析逻辑自检（不碰真实输入设备）")
        print("=" * 66)
        return selftest(chars)

    out_dir = args.out or os.path.join(os.path.expanduser("~"), ".fishprobe", "inputs")
    rec = Recorder(out_dir, marks, poll_buttons=not args.no_poll_buttons)
    if args.mousetest and not args.duration:
        args.duration = args.mousetest

    # ---- 隐藏消息窗口（message-only），只用来接 WM_INPUT ----
    hinst = kernel32.GetModuleHandleW(None)
    cls_name = "fishkey_rawinput_wnd"

    wndproc_ref = [None]     # 必须持有引用，否则回调被 GC 掉会直接崩进程

    def wnd_proc(hwnd, msg, wparam, lparam):
        try:
            if msg == WM_INPUT:
                parse_input(lparam, rec)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception as e:                         # noqa: BLE001
            print("[warn] wndproc: %s" % e, file=sys.stderr)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    wndproc_ref[0] = WNDPROC(wnd_proc)

    wc = WNDCLASSEXW_STRUCT()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW_STRUCT)
    wc.lpfnWndProc = wndproc_ref[0]
    wc.hInstance = hinst
    wc.lpszClassName = cls_name
    if not user32.RegisterClassExW(ctypes.byref(wc)):
        err = ctypes.get_last_error()
        if err != 1410:                                # 1410 = 类已存在，可忽略
            print("[X] RegisterClassExW 失败，GetLastError=%d" % err)
            return 1

    hwnd = user32.CreateWindowExW(0, cls_name, "fishprobe-key", 0,
                                  0, 0, 0, 0, HWND_MESSAGE, None, hinst, None)
    if not hwnd:
        print("[X] CreateWindowExW 失败，GetLastError=%d" % ctypes.get_last_error())
        return 1

    # ---- 注册 Raw Input：鼠标 + 键盘，RIDEV_INPUTSINK = 后台也能收 ----
    devs = (RAWINPUTDEVICE * 2)(
        RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, hwnd),    # UsagePage=Generic, Mouse
        RAWINPUTDEVICE(0x01, 0x06, RIDEV_INPUTSINK, hwnd),    # UsagePage=Generic, Keyboard
    )
    if not user32.RegisterRawInputDevices(devs, 2, ctypes.sizeof(RAWINPUTDEVICE)):
        print("[X] RegisterRawInputDevices 失败，GetLastError=%d" % ctypes.get_last_error())
        return 1

    print("=" * 66)
    print(" fishkey · 键鼠只读记录器（Raw Input，不装钩子、不拦输入）")
    print("=" * 66)
    print(" 自检：Raw Input 注册成功（鼠标 + 键盘）")
    dev = count_raw_devices()
    if dev is None:
        print(" 设备：枚举失败（不影响采集，但请留意鼠标事件是否为 0）")
    else:
        m, k, tot = dev
        print(" 设备：系统共 %d 个 Raw Input 设备，其中鼠标类 %d / 键盘类 %d" % (tot, m, k))
        if m == 0:
            print(" [!] 没发现任何鼠标类设备 —— 鼠标事件可能一直为 0，请查硬件/驱动配置。")
    print(" 鼠标：Raw Input 之外另开 GetAsyncKeyState 轮询兜底（%s）"
          % ("开" if rec.use_poll else "关 --no-poll-buttons"))
    print("       触摸板的\"轻触点击\"是驱动合成的，不进原始鼠标集合，只有兜底读得到。")
    if args.list:
        print(" --list 指定，自检完毕退出。")
        return 0

    rec.open()
    print(" 输出 : %s" % rec.path)
    if args.mousetest:
        print()
        print("=" * 66)
        print(" 鼠标链路实测：接下来 %.0f 秒，请**点几下鼠标左键**（右键/中键也可）" % args.duration)
        print(" 纯记录，不抢光标、不注入、不拦输入。切到游戏里点也可以。")
        print("=" * 66)
    print(" VK   : 开始=0x%02X 成功=0x%02X 失败=0x%02X" %
          (vk_of(chars["start"]), vk_of(chars["success"]), vk_of(chars["fail"])))
    print()
    print(" 采集协议（打点键）：")
    print("   %-2s = 一局开始（刚抛竿 / 刚进收杆小游戏）" % chars["start"])
    print("   %-2s = 这一局成功" % chars["success"])
    print("   %-2s = 这一局失败" % chars["fail"])
    print()

    hits = check_keybinds(chars, args.game_dir)
    if hits:
        print(" [!] 按键冲突警告（这些键在 options.txt 里已有绑定）：")
        for ch, label, bind in hits:
            print("       %-2s (%s)  已被 %s 占用 —— 按下去可能触发游戏动作，" % (ch, label, bind))
            print("       %s 建议先在游戏里把该绑定改成别的键。" % (" " * 7,))
        print()
    else:
        print(" 键位检查：三个键在 options.txt 里均无绑定，干净。")
        print()

    print(" Ctrl+C 结束记录。")
    print("-" * 66)

    msg = wintypes.MSG()
    deadline = time.time() + args.duration if args.duration > 0 else None
    next_beat = (time.time() + args.heartbeat) if args.heartbeat > 0 else None
    running = True
    try:
        # 统一用「PeekMessage + 短睡」循环：既泵消息队列，也能每轮轮询一次鼠标按键。
        # 轮询周期 4ms（250Hz）—— 人手最快的动作也有几十毫秒，不可能漏。
        while running:
            if deadline is not None and time.time() >= deadline:
                break
            drained = False
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                drained = True
                if msg.message == WM_QUIT:
                    running = False
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            rec.poll_buttons()
            # 鼠标实测模式：抓到一次完整的「按下+抬起」就立刻收工，不用等满时长
            if args.mousetest and (rec.n_raw_mouse + rec.n_poll_mouse) >= 2:
                print()
                print(" [ok] 已抓到鼠标按键，提前结束实测。")
                break
            if next_beat is not None and time.time() >= next_beat:
                next_beat = time.time() + args.heartbeat
                print(" [%s] 实时：鼠标 raw %d + 轮询 %d（去重 %d）/ 键盘 key %d 条 / "
                      "打点 %d 次 / 落盘 %d 条"
                      % (time.strftime("%H:%M:%S"), rec.n_raw_mouse, rec.n_poll_mouse,
                         rec.n_poll_dup, rec.n_events - rec.n_marks, rec.n_marks,
                         rec.n_events))
                sys.stdout.flush()
            if not drained:
                time.sleep(POLL_INTERVAL_S)
    except KeyboardInterrupt:
        pass
    finally:
        rec.poll_buttons()               # 收尾再补一次，别漏掉最后一次抬起
        rec.close()
        print()
        print("=" * 66)
        print(" 已结束。共记录 %d 条事件 -> %s" % (rec.n_events, rec.path))
        print(" 鼠标来源：Raw Input %d 条 / 轮询兜底 %d 条（与 Raw 重复而去重 %d 条）"
              % (rec.n_raw_mouse, rec.n_poll_mouse, rec.n_poll_dup))
        if rec.n_raw_mouse == 0 and rec.n_poll_mouse == 0:
            print(" [!] 全程没记到任何鼠标按键。若本次操作含「按下 左键」的小游戏，")
            print("     说明两个来源都没抓到，请把这段输出发出来一起看。")
        print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
