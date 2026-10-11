# -*- coding: utf-8 -*-
"""快速渲染一个/多个 region，用于验证坐标方向与数据正确性。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import xaero_region as XR
from PIL import Image

V = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14"
WM = os.path.join(V, "XaeroWorldMap", "Multiplayer_mcfkcs.com")
OUT = os.path.join(HERE, "out")

# 正式色表：由 block_colors.json 提供（从 MC 方块贴图取平均色）
import json as _json
_COLORS = None


def _load_colors():
    global _COLORS
    if _COLORS is None:
        p = os.path.join(HERE, "block_colors.json")
        _COLORS = _json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    return _COLORS


AIR_NAMES = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air",
             "minecraft:barrier", "minecraft:light", "minecraft:structure_void"}


def color_of(name):
    base = name.split("[")[0]
    if base in AIR_NAMES:
        return (0, 0, 0, 0)                       # 空气透明，露出背景
    c = _load_colors().get(base)
    if c is None:
        h = abs(hash(base)) % 360
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(h / 360.0, 0.28, 0.72)
        c = (int(r * 255), int(g * 255), int(b * 255))
    if len(c) == 3:
        c = (c[0], c[1], c[2], 255)
    return c


def render_region(dim, mw, fname, bg=(24, 24, 28)):
    p = os.path.join(WM, dim, mw, fname)
    rd = XR.parse_region_file(p)
    img = Image.new("RGBA", (512, 512), bg + (255,))
    px = img.load()
    for (dx, dz), nm in rd.blocks.items():
        px[dx, dz] = color_of(nm)
    return img, rd


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    cases = [
        ("主世界/主城", "null", "mw$default", "-10_3.zip"),
        ("末地", "DIM1", "mw$default", "-10_-94.zip"),
        ("资源世界", "minecraft$ziyuan", "mw$default", "-22_27.zip"),
        ("出生地", "minecraft$spawn", "mw$default", "0_0.zip"),
    ]
    for label, dim, mw, f in cases:
        try:
            img, rd = render_region(dim, mw, f)
            o = os.path.join(OUT, "r_%s.png" % label)
            img.save(o)
            print("%-12s -> %s  blocks=%d ver=%s" % (label, o, len(rd.blocks), rd.version))
        except Exception as e:
            print("%-12s -> ERR %s" % (label, e))
