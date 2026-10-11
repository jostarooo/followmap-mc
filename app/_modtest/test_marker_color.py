# -*- coding: utf-8 -*-
"""启动崩溃回归：POI/遗迹标记的 color 必须能喂给 PIL（2026-10-11）。

根因：found_ruins.json 落盘后 color 变 JSON 数组（list），_load_found 原样带出，
view._marker 把 list 传给 PIL draw_ink → TypeError: color must be int or tuple，
且崩溃条件是「已记录遗迹进入视野」——所以平时好好的，玩家一走到遗迹附近
就每帧必炸、表现为"无法启动"。
"""
import os
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

from PIL import Image, ImageDraw
from followmap.ruins import RuinWatcher
from followmap.view import MapView

# ① 加载路径：found_ruins.json 里的 color 必须转成 tuple
w = RuinWatcher()
assert w.found, "found_ruins.json 为空，无法验证"
for it in w.found:
    assert it.get("color") is None or isinstance(it["color"], tuple), \
        "❌ 加载后 color 仍是 list: %r" % (it.get("color"),)
print("① _load_found：%d 条 found 的 color 全部为 tuple/None  OK" % len(w.found))

# ② 绘制兜底：_marker 对 list / None / tuple 都不抛异常
img = Image.new("RGBA", (60, 60))
d = ImageDraw.Draw(img)
for c in ([220, 70, 60], None, (90, 210, 200, 255)):
    MapView._marker(d, 30, 30, c)
print("② _marker 对 list/None/tuple 均不炸  OK")

print()
print("全部通过：标记颜色回归 2/2")
