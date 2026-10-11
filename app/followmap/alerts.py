# -*- coding: utf-8 -*-
"""遗迹提醒的「怎么提醒」这一层。

使用场景（2026-10-09 按用户实机场景重定）
----------------------------------------
  笔记本自带屏：挂机飞末地跑图（顺带显示这张跟随地图）
  外接大屏幕　：刷视频 —— **眼睛在这儿**

所以两条结论：

  · **只有声音是 100% 有效的通道。** 地图窗口、任务栏、游戏画面全都在不看的那块
    屏上，抖动再花哨也没人看。因此水滴音做成了「满刻度归一化 + 连响三下」，
    目的就是能从视频声里穿出来。
  · 「抖动地图窗口」默认**关闭**（`--ruin-alert both` 才开）。它本来是为「余光扫
    地图」的场景设计的；在这个场景里不但没用，还会在拖动窗口时打架。

保留的三条视觉辅助（都不会干扰游戏）：
  · 窗口抖动（默认关）—— FlashWindowEx 不抢焦点，`geometry` 走 after 链不阻塞主循环。
  · 任务栏闪烁（默认开）—— 不抢焦点、不打断游戏；切回桌面时能立刻看到是哪个窗口。
  · 地图永久打点（图标 + 名字）—— 事后可回看。

音效是**现场合成**的（不依赖任何外部音频文件）：水滴音 = 指数衰减 + 快速上滑的
正弦（水滴落水的经典「plip」由气泡振荡上滑产生）。三种遗迹用三个音高，
光听声音就知道是哪一种遗迹。

两个实测踩到的坑（都记在这儿，别再犯）
--------------------------------------
1) **窗口几何串必须用正则解析，不能 `partition("+")`。** 双屏时笔记本屏常在主屏
   左侧，窗口 x 是**负数**，`tk.geometry()` 返回 `"560x560-1920+40"`；
   用 `partition("+")` 切会得到 `size="560x560-1920"`、`y=""`，
   `int("")` 抛异常后被 except 吞掉 → **抖动静默失效**（表现得像"没实现"）。
2) **音量只能靠波形本身。** `winsound` 没有音量参数；`waveOutSetVolume` 改的是整机
   输出音量（会动到用户在看视频时的音量），不能用。所以：波形峰值归一化到满刻度
   + 连响三下；`vol > 1` 走 tanh 软削波继续推响度，峰值始终 ≤ 满刻度，不会数字破音。
"""
import math
import os
import re
import struct
import sys
import threading
import time
import wave

# auto   = 水滴音 + 任务栏闪烁 + 地图打点（默认；**不含抖动**，见模块说明）
# both   = 水滴音 + 窗口抖动 + 任务栏闪烁
# sound  = 只响
# flag   = 只闪任务栏
# shake  = 只抖窗口（调试用）
# off    = 全关（仍会在日志/地图留档）
MODES = ("auto", "both", "sound", "shake", "flag", "off")
CYCLE = ("auto", "sound", "both", "flag", "off")   # r 键循环顺序（跳开调试项）

# 抖动位移序列（像素）。**别调小**：旧版最大只有 6px、总时长 0.29s，
# 在 520~560px 的窗口上只有 ~1% 宽度，实测很容易被当成"根本没抖"。
# 现在最大 16px、10 步约 0.4s，且回到原位（最后一项是 (0,0)）。
_STEPS = [(16, 0), (-16, 0), (13, -10), (-13, 10), (10, 6),
          (-10, -6), (6, -4), (-6, 4), (2, 0), (0, 0)]

_GEOM = re.compile(r"^\s*(\d+)x(\d+)(?:([+-]\d+)([+-]\d+))?\s*$")

# 波形参数：改了必须同步 SOUND_VER，否则磁盘上的旧 wav 会被当成"已经是对的"。
SOUND_VER = 3
PING_REPEATS = 3        # 连响几下：从视频声里穿出来的关键
PING_GAP_MS = 170       # 两响之间静音多久
SOUND_VOLUME = 1.5      # <=1 直接缩放；>1 软削波推响度（峰值恒定不变）
_MANIFEST = "_manifest.json"


# --------------------------------------------------------------------- 音效
def synth_drop(path, f0=760.0, f1=1900.0, ms=120, rate=44100,
               repeats=PING_REPEATS, gap_ms=PING_GAP_MS, vol=SOUND_VOLUME):
    """合成水滴音：频率快速上滑 + 指数衰减包络，再连响 `repeats` 下。

    水滴声的物理来源是气泡振荡，频率**上滑**（不是下滑），这是它和普通「叮」
    最大的区别；下滑的正弦听起来像敲门/报警，不像水。

    响度：先按峰值归一化到满刻度（旧实现固定在 0.85，白丢约 1.4dB），
    再按 `vol` 决定是缩放还是软削波。后几响略轻（0.92^n），听感像"提醒三声"
    而不是回声。
    """
    n = max(8, int(rate * ms / 1000.0))
    ping = []
    ph = 0.0
    for i in range(n):
        t = i / float(rate)
        u = i / float(n)
        f = f0 + (f1 - f0) * (u ** 1.5)
        ph += 2.0 * math.pi * f / rate
        amp = math.exp(-t / 0.030) * (1.0 - u) ** 0.6
        # 加一点二次谐波，听感更「水」
        ping.append((math.sin(ph) * 0.85 + math.sin(ph * 2.0) * 0.15) * amp)
    pk = max(abs(v) for v in ping) or 1.0
    ping = [v / pk for v in ping]

    gap = [0.0] * max(0, int(rate * gap_ms / 1000.0))
    sig = []
    for r in range(max(1, int(repeats))):
        k = 1.0 if r == 0 else 0.92 ** r
        sig.extend(v * k for v in ping)
        if r != repeats - 1:
            sig.extend(gap)

    if vol > 1.0:
        d = math.tanh(vol)
        sig = [math.tanh(v * vol) / d for v in sig]
    elif vol < 1.0:
        sig = [v * vol for v in sig]

    out = bytearray()
    pack = struct.Struct("<h").pack
    for v in sig:
        out += pack(int(max(-1.0, min(1.0, v)) * 32767))
    tmp = path + ".tmp"
    with wave.open(tmp, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(out))
    os.replace(tmp, path)
    return path


SOUNDS = {
    # 名称 -> (起频, 止频, 时长ms)   音高不同，听声辨遗迹
    "drop_high": (980.0, 2400.0, 105),   # 白金星殿
    "drop_mid": (760.0, 1900.0, 120),    # 巫师的圣修所
    "drop_low": (520.0, 1350.0, 145),    # 武士的修行地
}


def _sig(repeats, gap_ms, vol):
    return "%d|r%d|g%d|v%.2f" % (SOUND_VER, int(repeats), int(gap_ms), float(vol))


def ensure_assets(adir=None, repeats=PING_REPEATS, gap_ms=PING_GAP_MS,
                  vol=SOUND_VOLUME):
    """确保三种水滴音都在，且与当前参数一致；返回 {名称: 路径}。

    用旁挂清单记参数指纹：换了 `repeats/gap/vol` 或改了合成算法（SOUND_VER），
    旧 wav 会被重算——否则"改了音量却没效果"会很难查。
    """
    import json
    here = os.path.dirname(os.path.abspath(__file__))
    adir = adir or os.path.join(os.path.dirname(here), "assets")
    out = {}
    try:
        os.makedirs(adir, exist_ok=True)
    except OSError:
        return out
    mp = os.path.join(adir, _MANIFEST)
    try:
        with open(mp, encoding="utf-8") as fh:
            man = json.load(fh)
        if not isinstance(man, dict):
            man = {}
    except Exception:
        man = {}
    want = _sig(repeats, gap_ms, vol)
    dirty = False
    for name, (f0, f1, ms) in SOUNDS.items():
        p = os.path.join(adir, name + ".wav")
        ok = (os.path.exists(p) and os.path.getsize(p) > 2000
              and man.get(name) == want)
        if not ok:
            try:
                synth_drop(p, f0, f1, ms, repeats=repeats, gap_ms=gap_ms, vol=vol)
                man[name] = want
                dirty = True
            except Exception:
                out.pop(name, None)
                continue
        out[name] = p
    if dirty:
        try:
            with open(mp, "w", encoding="utf-8") as fh:
                json.dump(man, fh, ensure_ascii=False, indent=1)
        except OSError:
            pass
    return out


# --------------------------------------------------------------------- 播放
class Alerter:
    """把一次遗迹命中变成「听得见 + 看得见」。"""

    def __init__(self, mode="auto", assets_dir=None, log=None,
                 volume=SOUND_VOLUME, repeats=PING_REPEATS):
        self.mode = mode if mode in MODES else "auto"
        self.volume = float(volume)
        self.repeats = int(repeats)
        self.sounds = (ensure_assets(assets_dir, repeats=self.repeats,
                                     vol=self.volume)
                       if self.mode != "off" else {})
        self.log = log or (lambda s: None)
        self.count = 0
        self.last = None
        self.sound_ok = self._probe_sound()
        self._lock = threading.Lock()
        self._shaking = False

    def _probe_sound(self):
        if not self.sounds:
            return False
        if not sys.platform.startswith("win"):
            return False
        try:
            import winsound  # noqa: F401
        except Exception:
            return False
        return True

    # ---------------------------------------------------------------- 声音
    def play(self, name="drop_mid"):
        if self.mode == "off":
            return False
        p = self.sounds.get(name) or next(iter(self.sounds.values()), None)
        if self.sound_ok and p and os.path.exists(p):
            try:
                import winsound
                # SND_ASYNC 立刻返回，绝不阻塞地图重绘；NODEFAULT 在找不到设备时静默
                winsound.PlaySound(p, winsound.SND_FILENAME | winsound.SND_ASYNC
                                   | winsound.SND_NODEFAULT)
                return True
            except Exception as e:
                self.log("音效失败: %s" % e)
        # 兜底：自定义 wav 播不出来时至少让系统响一声
        # （真机日志里出现过「仅打点」——三通道全没成功却看不出原因，就是缺这层兜底）
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
            self.log("音效降级：用系统提示音代替水滴音")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------ 窗口抖动
    @staticmethod
    def _win_pos(tkroot):
        """取 (尺寸串, x, y)。**必须能处理负坐标**（双屏时笔记本屏在主屏左侧）。"""
        size = None
        try:
            g = (tkroot.geometry() or "").strip()
            m = _GEOM.match(g)
            if m:
                size = "%sx%s" % (m.group(1), m.group(2))
                if m.group(3) is not None:
                    return size, int(m.group(3)), int(m.group(4))
                # 只给了尺寸（窗口还没被摆过）——位置问 winfo
                return size, tkroot.winfo_x(), tkroot.winfo_y()
        except Exception:
            pass
        try:
            w, h = tkroot.winfo_width(), tkroot.winfo_height()
            if w < 10 or h < 10:
                return None
            return size or ("%dx%d" % (w, h)), tkroot.winfo_x(), tkroot.winfo_y()
        except Exception:
            return None

    def shake(self, tkroot, step_ms=36):
        """抖动 Tk 窗口。用 after 链，不阻塞主循环。"""
        if self.mode == "off" or tkroot is None or self._shaking:
            return False
        got = self._win_pos(tkroot)
        if not got or not got[0]:
            self.log("窗口抖动跳过：拿不到窗口位置")
            return False
        size, bx, by = got

        def do(i):
            if i >= len(_STEPS):
                try:
                    tkroot.geometry("%s+%d+%d" % (size, bx, by))
                except Exception:
                    pass
                self._shaking = False
                return
            dx, dy = _STEPS[i]
            try:
                tkroot.geometry("%s+%d+%d" % (size, bx + dx, by + dy))
                tkroot.after(step_ms, lambda: do(i + 1))
            except Exception:
                self._shaking = False

        self._shaking = True
        try:
            do(0)
            return True
        except Exception:
            self._shaking = False
            return False

    # -------------------------------------------------------- 任务栏闪烁
    def flash(self, tkroot):
        """Windows 任务栏闪烁；不抢焦点（FLASHW_TIMERNOFG）。"""
        if self.mode == "off" or tkroot is None:
            return False
        if not sys.platform.startswith("win"):
            return False
        try:
            import ctypes
            from ctypes import wintypes

            class FLASHWINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT),
                            ("hwnd", wintypes.HWND),
                            ("dwFlags", wintypes.DWORD),
                            ("uCount", wintypes.UINT),
                            ("dwTimeout", wintypes.DWORD)]

            hwnd = tkroot.winfo_id()
            parent = ctypes.windll.user32.GetParent(hwnd)
            if parent:
                hwnd = parent
            FLASHW_ALL, FLASHW_TIMERNOFG = 0x3, 0xC
            fi = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd,
                            FLASHW_ALL | FLASHW_TIMERNOFG, 0, 0)
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(fi))
            return True
        except Exception:
            return False

    # ---------------------------------------------------------------- 总入口
    def channels(self, mode=None):
        """当前模式下会走哪些通道（供测试/自检核对，不产生副作用）。"""
        m = self.mode if mode is None else mode
        return {"sound": m in ("auto", "both", "sound"),
                "shake": m in ("both", "shake"),
                "flash": m in ("auto", "both", "flag")}

    def notify(self, hit, tkroot=None):
        name = hit.get("type", "遗迹")
        self.count += 1
        self.last = hit
        c = self.channels()
        done, miss = [], []
        if c["sound"]:
            (done if self.play(hit.get("sound") or "drop_mid")
             else miss).append("水滴音")
        if c["shake"]:
            (done if self.shake(tkroot) else miss).append("窗口抖动")
        if c["flash"]:
            (done if self.flash(tkroot) else miss).append("任务栏闪烁")
        if self.mode == "off":
            note = "提醒=off，仅打点"
        else:
            note = "+".join(done) or "仅打点"
            if miss:
                note += "（%s 未生效）" % "、".join(miss)
            if not done:
                note += " << 一个通道都没成功，检查音效资源/窗口句柄"
        self.log("发现 %s (%d,%d) 纯度%.0f%% -> %s"
                 % (name, hit.get("x", 0), hit.get("z", 0),
                    hit.get("pure", 0) * 100, note))
        return done

    def status(self):
        if self.mode == "off":
            return "遗迹提醒：关闭"
        c = self.channels()
        ch = "+".join(n for n, on in (("音", c["sound"]), ("抖", c["shake"]),
                                      ("闪", c["flash"])) if on) or "仅打点"
        return "提醒=%s(%s%s) 音效%s" % (
            self.mode, ch, " x%d" % self.repeats if c["sound"] else "",
            "就绪" if self.sound_ok else "不可用")


if __name__ == "__main__":
    al = Alerter()
    print(al.status())
    for n, p in al.sounds.items():
        print("  %-10s %s (%d 字节)" % (n, p, os.path.getsize(p)))
    for n in SOUNDS:
        al.play(n)
        time.sleep(1.4)
