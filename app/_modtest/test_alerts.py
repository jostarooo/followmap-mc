# -*- coding: utf-8 -*-
"""提醒层（followmap/alerts.py）的离线验证。

三段：
  A) **窗口几何解析**：这是"窗口抖动没反应"的真实根因所在。
     双屏时笔记本屏常在主屏左侧，窗口 x 是负数，`tk.geometry()` 返回
     "560x560-1920+40"。旧实现用 `partition("+")` 切串 → size 变成
     "560x560-1920"、y 变成 ""，`int("")` 抛异常被 except 吞掉 → **静默失效**。
     这里把旧写法和新写法都跑一遍，把差异钉死。
  B) **真窗口抖动**：真开一个 Tk 窗口，跑一次 shake，采样 winfo_x
     验证"确实动了、并且停回了原位"。
  C) **音效与通道矩阵**：合成出的 wav 时长/峰值/RMS/连响次数，
     以及每种模式下到底触发哪些通道。

用法： python _modtest/test_alerts.py
"""
import os
import re
import struct
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

from followmap.alerts import (MODES, SOUNDS, Alerter, _GEOM,  # noqa: E402
                              ensure_assets, synth_drop)

BAD_MARK = "!!"


# ------------------------------------------------------------------ A 段
def old_win_pos(g):
    """旧实现（有 bug）：原样 reproduce 出来，用来说明它为什么失效。"""
    try:
        size, _, pos = g.partition("+")
        x0, _, y0 = pos.partition("+")
        return (size.split("+")[0], int(x0), int(y0)), None
    except Exception as e:
        return None, type(e).__name__


class FakeRoot:
    """只实现 geometry()/winfo_*，用来喂各种几何串。"""

    def __init__(self, g, x=7, y=9):
        self._g, self._x, self._y = g, x, y

    def geometry(self):
        return self._g

    def winfo_width(self):
        return 1

    def winfo_height(self):
        return 1

    def winfo_x(self):
        return self._x

    def winfo_y(self):
        return self._y


def part_a():
    print("=" * 78)
    print("A) 窗口几何解析：负坐标必须能解析（双屏最常见的一种排布）")
    print("=" * 78)
    cases = [
        "560x560+40+40",        # 常规
        "560x560-1920+40",      # 笔记本屏在主屏左侧（用户的实际排布类型）
        "560x560+100-200",      # y 为负（主屏在下方）
        "560x560-1920-200",     # 双负
        "640x480+3840+0",       # 主屏右侧延伸
        "560x560",              # 未给出位置（还没 map 过）
    ]
    width = max(len(c) for c in cases)
    print("   %-*s  旧实现(partition '+')      新实现(正则)" % (width, "geometry()"))
    print("   " + "-" * 74)
    ok = True
    for c in cases:
        o, o_err = old_win_pos(c)
        o_txt = ("%s @ %d,%d" % o) if o else "失败 <%s>" % o_err
        n = Alerter._win_pos(FakeRoot(c))
        n_txt = ("%s @ %d,%d" % n) if n and n[0] else "失败"
        good = bool(n and n[0])
        if not good:
            ok = False
        print("   %-*s  %-26s  %-22s %s" % (width, c, o_txt, n_txt,
                                            "" if good else "<<< 解析失败"))
    # 具体校验负坐标取值
    n = Alerter._win_pos(FakeRoot("560x560-1920+40"))
    assert n and n[1] == -1920 and n[2] == 40, n
    print()
    print("   校验 \"560x560-1920+40\" -> 尺寸=%s 位置=(%d,%d)  [正确]" % n)
    print("   旧实现在这一串上会 %s，异常被 except 吞掉 -> 抖动静默失效"
          % (old_win_pos("560x560-1920+40")[1],))
    print()
    print("   A 段结论:", "全部可解析" if ok else "有解析失败")
    return 0 if ok else 2


# ------------------------------------------------------------------ B 段
def part_b():
    print("=" * 78)
    print("B) 真窗口抖动：真开一个 Tk 窗口，跑 shake，看它到底动不动")
    print("=" * 78)
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception as e:
        print("   跳过：起不了 Tk（%s）" % e)
        return 0
    try:
        W = H = 240
        base_x, base_y = 120, 120
        root.title("shake-test")
        root.geometry("%dx%d+%d+%d" % (W, H, base_x, base_y))
        root.update()
        al = Alerter("both", log=lambda s: None)
        al.sound_ok = False          # 这一段只听抖，不出声

        got = al._win_pos(root)
        print("   窗口实际位置: %s" % (got,))
        xs = []
        t0 = time.time()
        ret = al.shake(root, step_ms=18)
        while time.time() - t0 < 1.5 and getattr(al, "_shaking", False):
            root.update()
            xs.append(root.winfo_x())
            time.sleep(0.004)
        root.update()
        end = root.winfo_x()
        moved = [v for v in xs if v != base_x]
        amp = max((abs(v - base_x) for v in xs), default=0)
        print("   shake() 返回 %s，采样 %d 次，偏离原位 %d 次，最大位移 %dpx"
              % (ret, len(xs), len(moved), amp))
        print("   位移序列前 12 个: %s" % [v - base_x for v in xs[:12]])
        print("   结束后回到原位: %s (x=%d, 期望 %d)" % (end == base_x, end, base_x))

        # 顺带验证模式矩阵：auto 不该抖（用户场景：眼睛在另一块屏上）
        al.mode = "auto"
        al._shaking = False
        ch = al.channels()
        print("   auto 模式通道: %s（shake=%s）" % (ch, ch["shake"]))
        # 幅度也要够大：旧版 6px 在 520px 窗口上只有 1%，实测容易被当成"没抖"
        if amp < 12:
            print("   %s 最大位移只有 %dpx，太容易被忽略" % (BAD_MARK, amp))
        ok = (ret and len(moved) >= 4 and amp >= 12 and end == base_x
              and not ch["shake"])
    finally:
        try:
            root.destroy()
        except Exception:
            pass
    print()
    print("   B 段结论:", "抖动真实生效且能回位" if ok else "抖动没生效，见上")
    return 0 if ok else 2


# ------------------------------------------------------------------ C 段
def _bursts(path, rel=0.05, env_ms=6):
    """数一段 wav 里有几个「音块」（把包络平滑掉再数连续响区间）。

    必须平滑：波形每个周期都会过零点两次，直接拿瞬时值比阈值会把一个音
    数成几百个（第一版就这么错过）。
    """
    import array
    with wave.open(path, "rb") as w:
        n, rate = w.getnframes(), w.getframerate()
        raw = w.readframes(n)
    a = array.array("h")
    a.frombytes(raw)
    pk = max(abs(v) for v in a) or 1
    step = max(1, int(rate * env_ms / 1000.0))
    env = [max(abs(v) for v in a[i:i + step]) for i in range(0, len(a), step)]
    thr = pk * rel
    out, cur = 0, False
    for e in env:
        loud = e > thr
        if loud and not cur:
            out += 1
        cur = loud
    return out, n / float(rate), pk, list(a)


def _rms(a):
    if not a:
        return 0.0
    return (sum(float(v) * v for v in a) / len(a)) ** 0.5


def part_c():
    print("=" * 78)
    print("C) 音效：峰值/响度/连响次数 + 各模式触发的通道")
    print("=" * 78)
    adir = os.path.join(HERE, "_alerts_assets")
    import shutil
    shutil.rmtree(adir, ignore_errors=True)
    os.makedirs(adir, exist_ok=True)

    ok = True
    info = {}
    exp_dur = (3 * 120 + 2 * 170) / 1000.0        # 3 响 120ms + 2 个 170ms 间隔
    for vol in (1.0, 1.5, 2.5):
        p = os.path.join(adir, "t_%.1f.wav" % vol)
        synth_drop(p, 760.0, 1900.0, 120, repeats=3, gap_ms=170, vol=vol)
        nb, dur, pk, a = _bursts(p)
        rms = _rms(a)
        info[vol] = (nb, dur, pk, rms)
        bad = []
        if nb != 3:
            bad.append("连响数不是 3")
        if pk < 32000:
            bad.append("峰值没顶到满刻度")
        if abs(dur - exp_dur) > 0.02:
            bad.append("时长不是 %.2fs" % exp_dur)
        if bad:
            ok = False
        print("   vol=%.1f  连响 %d 下  时长 %.3fs  峰值 %d  有效值 %.0f  文件 %d 字节  %s"
              % (vol, nb, dur, pk, rms, os.path.getsize(p),
                 "" if not bad else "<<< " + "、".join(bad)))
    # 响度必须随 vol 单调上升（软削波的意义）
    r1, r15, r25 = info[1.0][3], info[1.5][3], info[2.5][3]
    mono = r1 < r15 < r25
    print("   响度单调: %.0f < %.0f < %.0f -> %s（否则 vol 就是摆设）"
          % (r1, r15, r25, mono))
    ok = ok and mono
    # 峰值不随 vol 上升（说明是软削波，不是硬拉爆）
    if not (info[1.0][2] == info[1.5][2] == info[2.5][2]):
        print("   注意：峰值随 vol 变化了，说明不是纯软削波")
        ok = False

    print()
    print("   三种遗迹的音高（听声辨类型）:")
    for name, (f0, f1, ms) in SOUNDS.items():
        p = os.path.join(adir, name + ".wav")
        synth_drop(p, f0, f1, ms)
        nb, dur, pk, a = _bursts(p)
        print("      %-10s %5.0f->%5.0fHz %3dms  连响%d 时长%.2fs 峰值%d"
              % (name, f0, f1, ms, nb, dur, pk))
        info[name] = (nb, dur, pk, _rms(a), f0, f1)
    uniq = len({(v[4], v[5]) for k, v in info.items() if isinstance(k, str)})
    print("      音高互不相同: %s（%d 种）" % (uniq == 3, uniq))
    ok = ok and uniq == 3

    print()
    print("   模式 -> 触发通道（auto 不抖，是这次按使用场景改的）:")
    expect = {
        "auto":  (True, False, True),
        "sound": (True, False, False),
        "both":  (True, True, True),
        "shake": (False, True, False),
        "flag":  (False, False, True),
        "off":   (False, False, False),
    }
    print("      %-6s %-22s %-22s %s" % ("模式", "实际(音/抖/闪)", "期望", ""))
    for m in MODES:
        al = Alerter(m, assets_dir=adir, log=lambda s: None)
        c = al.channels()
        got = (c["sound"], c["shake"], c["flash"])
        e = expect.get(m)
        good = (e is None) or (got == e)
        ok = ok and good
        print("      %-6s %-22s %-22s %s" % (m, got, e, "" if good else "<<< 不符"))

    print()
    print("   ensure_assets 参数指纹：换 vol 会重算 wav（否则「改了音量却没效果」很难查）")
    m1 = ensure_assets(adir, repeats=3, vol=1.0)
    mt1 = open(os.path.join(adir, "_manifest.json"), encoding="utf-8").read()
    m2 = ensure_assets(adir, repeats=3, vol=2.0)
    mt2 = open(os.path.join(adir, "_manifest.json"), encoding="utf-8").read()
    changed = mt1 != mt2
    print("      清单随 vol 变化: %s  （%d 个音）" % (changed, len(m2)))
    ok = ok and changed
    shutil.rmtree(adir, ignore_errors=True)
    print()
    print("   C 段结论:", "音效与通道矩阵全部符合预期" if ok else "有不符，见上")
    return 0 if ok else 2


if __name__ == "__main__":
    what = (sys.argv[1] if len(sys.argv) > 1 else "abc").lower()
    rc = 0
    if "a" in what:
        rc |= part_a()
        print()
    if "b" in what:
        rc |= part_b()
        print()
    if "c" in what:
        rc |= part_c()
    sys.exit(rc)
