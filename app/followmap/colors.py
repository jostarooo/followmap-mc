# -*- coding: utf-8 -*-
"""方块状态名 -> 颜色。色表来自 block_colors.json（从 MC 客户端 jar 的方块贴图取平均色）。

与 _t3_render.color_of 的区别：未知方块的回退色用 md5 决定，**跨进程稳定**，
否则每次启动颜色都会变（Python 的 str hash 带随机盐）。
"""
import colorsys
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
_COLORS_PATH = os.path.join(APP, "block_colors.json")

AIR_NAMES = {
    "minecraft:air", "minecraft:cave_air", "minecraft:void_air",
    "minecraft:barrier", "minecraft:light", "minecraft:structure_void",
    "minecraft:moving_piston", "minecraft:debug_stick",
}

_COLORS = None


def load_colors(path=None):
    global _COLORS
    if _COLORS is None:
        p = path or _COLORS_PATH
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                _COLORS = json.load(f)
        else:
            _COLORS = {}
        for k, v in list(_COLORS.items()):
            if isinstance(v, list):
                _COLORS[k] = tuple(v)
    return _COLORS


def _fallback(base):
    h = int(hashlib.md5(base.encode("utf-8")).hexdigest()[:8], 16)
    r, g, b = colorsys.hsv_to_rgb((h % 360) / 360.0, 0.28, 0.72)
    return (int(r * 255), int(g * 255), int(b * 255), 255)


def color_of(name):
    """返回 (r,g,b,a)。空气/技术方块 -> 全透明（露出背景）。"""
    base = name.split("[")[0]
    if base in AIR_NAMES:
        return (0, 0, 0, 0)
    c = load_colors().get(base)
    if c is None:
        return _fallback(base)
    if len(c) == 3:
        return (c[0], c[1], c[2], 255)
    return tuple(c[:4])


if __name__ == "__main__":
    for n in ["minecraft:end_stone", "minecraft:air", "minecraft:water",
              "minecraft:oak_planks", "minecraft:unknown_thing"]:
        print("%-32s %s" % (n, color_of(n)))
