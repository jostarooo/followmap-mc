# -*- coding: utf-8 -*-
"""可疑点（峰值 chunk 286,-2936）周围的**已加载 chunk 地图**。

假设：可疑建筑可能只被玩家加载了一半（模组只记已加载的 chunk），西侧
chunk 283~285 缺数据只是因为玩家没走到，不是建筑到那为止。
验证：画出周围已加载/缺数据的分布，并看 pbricks 是否顶到加载边界。
"""
import os
import pickle
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
sys.path.insert(0, HERE)

CACHE = os.path.join(os.environ.get("TEMP", "/tmp"), "_probe_blockid_chunks.pkl")
PB = "minecraft:polished_blackstone_bricks"
SS = "minecraft:soul_soil"


def main():
    with open(CACHE, "rb") as fh:
        hist = pickle.load(fh)

    cx0, cz0 = 286, -2936
    R = 12
    print("已加载 chunk 地图（# = 有数据且含 pbricks，o = 有数据无 pbricks，. = 缺数据）：")
    print("      " + "".join("%4d" % (cz0 + dz) for dz in range(-R, R + 1)))
    for dx in range(-R, R + 1):
        row = "%6d" % (cx0 + dx)
        for dz in range(-R, R + 1):
            c = hist.get((cx0 + dx, cz0 + dz))
            if c is None:
                row += "%4s" % "."
            elif c.get(PB):
                row += "%4s" % "#"
            else:
                row += "%4s" % "o"
        print(row)

    print()
    print("同样式，但标记 soul_soil（# = 有数据且含 soul_soil>=1）：")
    print("      " + "".join("%4d" % (cz0 + dz) for dz in range(-R, R + 1)))
    for dx in range(-R, R + 1):
        row = "%6d" % (cx0 + dx)
        for dz in range(-R, R + 1):
            c = hist.get((cx0 + dx, cz0 + dz))
            if c is None:
                row += "%4s" % "."
            elif c.get(SS):
                row += "%4s" % "#"
            else:
                row += "%4s" % "o"
        print(row)

    # pbricks chunk 是否顶到缺数据边界
    cells = {k for k, c in hist.items() if c.get(PB)}
    near = [k for k in cells if abs(k[0] - cx0) <= 6 and abs(k[1] - cz0) <= 6]
    print()
    print("附近含 pbricks 的 chunk：%s" % sorted(near))
    for cx, cz in sorted(near):
        miss = []
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if (cx + dx, cz + dz) not in hist:
                    miss.append((cx + dx, cz + dz))
        if miss:
            print("  (%d,%d) 紧邻缺数据 chunk：%s" % (cx, cz, sorted(miss)))


if __name__ == "__main__":
    main()
