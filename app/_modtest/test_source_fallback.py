# -*- coding: utf-8 -*-
"""频闪修复回归：auto 模式的 OCR 门槛（2026-10-11）。

背景：原先 auto 下 bridge 失败一帧（开菜单/加载屏/JSON 截断）就立刻以
0.2s 间隔 PrintWindow 抓 GL 游戏窗口 → 屏幕频闪。修复后：
  ① bridge 连续失败不满 5 秒，OCR 绝不激活（菜单/加载屏场景）；
  ② 满 5 秒后才激活，抓屏间隔下限 1.0s（原 0.2s）；
  ③ bridge 一恢复，门槛重新计时；
  ④ 显式 --source ocr 不设门槛。

用 __new__ 构造裸对象直接驱动 FollowApp._pump，不建 Tk、不碰真窗口
（win32cap.capture 被打桩，只数调用次数）。
"""
import os
import sys
import types

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "_modtest"))

from followmap import app as appmod
from followmap import sources as S

# ---- 时间快进：把 followmap.app 里的 time 换成可拨动的假钟
class FakeTime:
    def __init__(self):
        self.t = 1000.0
    def time(self):
        return self.t
    def sleep(self, dt):
        self.t += dt

FT = FakeTime()
appmod.time = FT
S.time = FT          # OcrSource 内部节流也用同一口假钟

# ---- 打桩 win32cap.capture，数调用次数并记录调用时刻
CAP_CALLS = []
import followmap.win32cap as capmod
_orig_capture = capmod.capture
def fake_capture(hwnd):
    CAP_CALLS.append(FT.t)
    img = S.Fix(ok=True, x=1.0, y=64.0, z=2.0, dim="minecraft:overworld",
                ts=FT.t, source="ocr", note="")
    # 返回 (PIL 图, None) 会走真 OCR；这里直接在 OcrSource.poll 的上层截断——
    # 更简单的做法：让 capture 返回 (None, "stub")，poll 记 note 返回，不进 OCR 引擎。
    return None, "stub"
capmod.capture = fake_capture

# ---- 组装裸 FollowApp（不跑 __init__）
a = object.__new__(appmod.FollowApp)
a.mode = "auto"
a.demo_on = False
a.bridge = S.BridgeSource(path=r"C:\__nonexistent__\coords.json")  # 永远失败
a.ocr = None
a._ocr_gate_t = None
a.last_ok_fix = None
a.manual = S.ManualSource(x=0, z=0)
a.demo = S.DemoSource([])
a.args = types.SimpleNamespace(interval=120, votes=2)

fails = []

def tick(n=1, dt=0.12):
    for _ in range(n):
        FT.t += dt
        f = appmod.FollowApp._pump(a)
        fails.append((FT.t, f))

# ---- 用例 ①：bridge 失败 5 秒内（≈42 帧，模拟开菜单）OCR 不得激活
tick(42)
assert a.ocr is None, "❌ 5 秒内 OCR 就被激活了（门槛没生效）"
assert len(CAP_CALLS) == 0, "❌ 5 秒内发生了 PrintWindow 抓屏"
print("① bridge 失败 5 秒内：OCR 未激活、抓屏 0 次  OK")

# ---- 用例 ②：失败满 5 秒后 OCR 才激活
tick(3)  # 再走 ~0.36s 越过 5s 门槛
assert a.ocr is not None, "❌ 5 秒后 OCR 仍未激活"
assert len(CAP_CALLS) >= 1, "❌ 门槛过后没有抓屏"
print("② 失败满 5 秒后：OCR 激活、开始抓屏  OK")

# ---- 用例 ③：抓屏间隔 >= 1.0s（interval 下限生效）
tick(40)  # 再跑 ~4.8s
gaps = [b - a_ for a_, b in zip(CAP_CALLS, CAP_CALLS[1:])]
assert gaps and min(gaps) >= 1.0 - 0.05, "❌ 抓屏间隔 %s < 1.0s" % (gaps[:5],)
print("③ 抓屏间隔最小 %.2fs（>=1.0s）  OK" % min(gaps))

# ---- 用例 ④：bridge 恢复后门槛重置（直接改指向真文件再删掉来模拟一次恢复）
class RevivingBridge:
    def __init__(self):
        self.n = 0
    def poll(self):
        self.n += 1
        if self.n <= 5:
            return S.Fix(note="挂")
        return S.Fix(ok=True, x=1.0, y=64.0, z=2.0, dim=None,
                     ts=FT.t, source="bridge", note="ok")

a.bridge = RevivingBridge()
a._ocr_gate_t = None
a.ocr = None
CAP_CALLS.clear()
# 5 帧失败（<5s，不激活）→ 1 帧成功（重置）→ 再 42 帧失败（<5s，仍不激活）
tick(5)
tick(1)   # bridge ok
a.bridge = S.BridgeSource(path=r"C:\__nonexistent__\coords.json")  # 再挂
tick(42)
assert len(CAP_CALLS) == 0, "❌ bridge 恢复后门槛未重置，第二次故障提前激活了 OCR"
print("④ bridge 恢复后门槛重置，第二次短故障仍不抓屏  OK")

# ---- 用例 ⑤：显式 --source ocr 无门槛，第一帧就抓
b = object.__new__(appmod.FollowApp)
b.mode = "ocr"
b.demo_on = False
b.bridge = S.BridgeSource(path=r"C:\__nonexistent__\coords.json")
b.ocr = None
b._ocr_gate_t = None
b.last_ok_fix = None
b.manual = S.ManualSource(x=0, z=0)
b.demo = S.DemoSource([])
b.args = types.SimpleNamespace(interval=120, votes=2)
FT.t += 1
f = appmod.FollowApp._pump(b)
assert b.ocr is not None, "❌ 显式 ocr 模式没有构造 OcrSource"
print("⑤ 显式 --source ocr：立即激活（无门槛）  OK")

print()
print("全部通过：频闪修复回归 5/5")
