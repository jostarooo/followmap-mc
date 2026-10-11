# -*- coding: utf-8 -*-
"""把若干 chunk 的原始地表铺成 ASCII 图，用来"亲眼"看建筑形状与缺列情况。

用法：python _modtest/_dump.py <cxc0> <czc0> [cxc1] [czc1]
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from followmap.ruins import safe_dim  # noqa: E402

HDR = struct.Struct("<IHHiiH")
ROW = 32
# 每列的显示字符：按方块名归类
CLASS = [
    ("end_stone_brick", "."),
    ("end_stone", "e"),
    ("netherrack", "n"),
    ("polished_basalt", "B"),
    ("crimson", "c"),
    ("warped", "w"),
    ("soul_", "s"),
    ("nether_brick", "N"),
    ("red_nether_brick", "R"),
    ("blackstone", "k"),
    ("gilded_blackstone", "g"),
    ("deepslate", "d"),
    ("dirt", "D"),
    ("bone_block", "b"),
    ("shroomlight", "o"),
    ("end_rod", "r"),
    ("weeping_vines", "v"),
    ("twisting_vines", "v"),
    ("chorus", "h"),
    ("air", "_"),
]


def char_of(name):
    n = name.replace("minecraft:", "")
    for k, c in CLASS:
        if k in n:
            return c
    return "?"


def main():
    a, b = int(sys.argv[1]), int(sys.argv[2])
    c = int(sys.argv[3]) if len(sys.argv) > 3 else a
    d = int(sys.argv[4]) if len(sys.argv) > 4 else b
    base = os.path.join(os.path.expanduser("~"), ".coordbridge", "chunks",
                        safe_dim("minecraft:the_end"))
    for cz in range(b, d + 1):
        for row in range(16):
            line = []
            for cx in range(a, c + 1):
                rx, rz = cx // 32, cz // 32
                p = os.path.join(base, "r%d" % rx, "r%d" % rz, "%d_%d.bin" % (cx, cz))
                if not os.path.exists(p):
                    line.append(" " * 16)
                    continue
                with open(p, "rb") as fh:
                    raw = fh.read()
                magic, ver, fl, hx, hz, paln = HDR.unpack_from(raw, 0)
                o = HDR.size
                pal = []
                for _ in range(paln):
                    (n,) = struct.unpack_from("<H", raw, o)
                    o += 2
                    pal.append(raw[o:o + n].decode("utf-8", "replace"))
                    o += n
                idx = struct.unpack_from("<256H", raw, o + 512)
                # 地表索引：低 8 位是 z，高 8 位是 x
                rowv = [idx[row * 16 + k] for k in range(16)]
                line.append("".join(char_of(pal[v]) if v < len(pal) else "#"
                                    for v in rowv))
            print("cz=%d r%02d |%s|" % (cz, row, "|".join(line)))
        print("  " + "".join("%-16s" % ("cx=%d" % cx) for cx in range(a, c + 1)))
    print("图例: . end_stone_brick  e end_stone  n netherrack  B polished_basalt")
    print("      c crimson  w warped  s soul  N nether_brick  R red_nether_brick")
    print("      k blackstone  g gilded  d deepslate  D dirt  b bone  o shroomlight")
    print("      r end_rod  v vines  h chorus  _ air  # NODATA/未知")


if __name__ == "__main__":
    main()
