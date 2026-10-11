# -*- coding: utf-8 -*-
"""可疑点的地表高度图：东侧「空的」chunk 是天然平地，还是被抬高了的埋藏丘？

原理：模组每个 chunk 记 256 列的 (地表方块, 地表高度)。自然末地地表高 56/57
（对应 NODATA）。如果东半建筑被末地石**埋住**，那片的地表高度会明显高于
56/57（末地石堆在建筑上面）。这是不翻地形就能看穿埋藏的关键。

对照：也画一座真巫师 (4623,-46028) 的高度图。
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

from followmap.ruins import safe_dim, _HDR        # noqa: E402

ROOT = os.path.join(os.path.expanduser("~"), ".coordbridge")
DIM = "minecraft:the_end"
_cache = {}


def heights(cx, cz):
    key = (cx, cz)
    if key in _cache:
        return _cache[key]
    p = os.path.join(ROOT, "chunks", safe_dim(DIM),
                     "r%d" % (cx // 32), "r%d" % (cz // 32),
                     "%d_%d.bin" % (cx, cz))
    h = None
    try:
        with open(p, "rb") as f:
            d = f.read()
        if len(d) >= _HDR.size:
            magic, ver, _fl, _x, _z, paln = _HDR.unpack_from(d, 0)
            if magic == 0x31424243 and ver == 1:
                o = _HDR.size
                ok = True
                for _ in range(paln):
                    if o + 2 > len(d):
                        ok = False
                        break
                    (n,) = struct.unpack_from("<H", d, o)
                    o += 2 + n
                if ok and o + 1024 <= len(d):
                    h = struct.unpack_from("<256H", d, o)
    except OSError:
        h = None
    _cache[key] = h
    return h


def hgt(bx, bz):
    cx, cz = bx // 16, bz // 16
    h = heights(cx, cz)
    if h is None:
        return None
    return h[(bz - cz * 16) * 16 + (bx - cx * 16)]


def draw(bx0, bz0, w, h, title):
    print(title)
    print("      " + "".join("%4d" % (bx0 + i) for i in range(0, w, 8)) + "  (每格=2x2 方块取最大，.. =无数据)")
    for j in range(0, h, 2):
        line = []
        for i in range(0, w, 2):
            best = None
            for dx in range(2):
                for dz in range(2):
                    v = hgt(bx0 + i + dx, bz0 + j + dz)
                    if v is not None:
                        best = v if best is None else max(best, v)
            line.append("%3d" % best if best is not None else " ..")
        print("z%6d  %s" % (bz0 + j, "".join(line)))
    print()


def main():
    draw(4544, -46992, 128, 96,
         "可疑点高度图（建筑在 x4576..4616；注意东侧/西侧的高度是否回落到 56~60）")
    draw(4560, -46076, 128, 96,
         "对照：真巫师 (4623,-46028) 高度图")


if __name__ == "__main__":
    main()
