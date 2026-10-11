# -*- coding: utf-8 -*-
"""把可疑点 (4586,-46944) 和最近的一座真巫师 (4623,-46028) 渲染成俯视图对比。

数据源是 coordbridge 落盘的 chunk .bin：每 chunk 256 列，每列一个地表方块名 + 一个高度。
Xaero 没探索到这一带（region 9_-93 只覆盖了 x4608+ / z-47616 以外），所以底图拿不到，
只能从模组自己的数据画。够用了：建筑的形状、用料分布一眼能看出来。

输出 PNG 到 ruins_img/（该目录已被 .gitignore 排除）。

用法：
    python _modtest/probe_suspect2.py
"""
import json
import os
import struct
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

from PIL import Image                                     # noqa: E402
from followmap.ruins import safe_dim, _HDR, NODATA        # noqa: E402

ROOT = os.path.join(os.path.expanduser("~"), ".coordbridge")
DIM = "minecraft:the_end"
OUT = os.path.join(os.path.dirname(APP), "ruins_img")


def chunk_path(cx, cz):
    return os.path.join(ROOT, "chunks", safe_dim(DIM),
                        "r%d" % (cx // 32), "r%d" % (cz // 32),
                        "%d_%d.bin" % (cx, cz))


def parse_full(cx, cz):
    """-> (heights[256], names[256])；没有该 chunk 返回 None。"""
    p = chunk_path(cx, cz)
    try:
        with open(p, "rb") as f:
            d = f.read()
    except OSError:
        return None
    if len(d) < _HDR.size:
        return None
    magic, ver, _fl, _x, _z, paln = _HDR.unpack_from(d, 0)
    if magic != 0x31424243 or ver != 1:
        return None
    o = _HDR.size
    pal = []
    for _ in range(paln):
        if o + 2 > len(d):
            return None
        (n,) = struct.unpack_from("<H", d, o)
        o += 2
        pal.append(d[o:o + n].decode("utf-8", "replace"))
        o += n
    if o + 1024 > len(d):
        return None
    heights = struct.unpack_from("<256H", d, o)
    idx = struct.unpack_from("<256H", d, o + 512)
    names = []
    for v in idx:
        names.append(None if (v == NODATA or v >= len(pal)) else pal[v])
    return list(heights), names


def block_at(cells, bx, bz):
    """方块坐标 -> (名字, 高度)。"""
    cx, cz = bx // 16, bz // 16
    c = cells.get((cx, cz))
    if not c:
        return None, None
    k = (bz - cz * 16) * 16 + (bx - cx * 16)
    return c[1][k], c[0][k]


def load_area(x0, z0, x1, z1):
    cells = {}
    for cx in range(x0 // 16 - 1, x1 // 16 + 2):
        for cz in range(z0 // 16 - 1, z1 // 16 + 2):
            c = parse_full(cx, cz)
            if c:
                cells[(cx, cz)] = c
    return cells


def render(cells, cx_b, cz_b, size, colors, scale=3, shade=True):
    """以方块坐标 (cx_b,cz_b) 为中心，画 size x size 方块的俯视图。"""
    half = size // 2
    hs = []
    for bz in range(cz_b - half, cz_b + half):
        for bx in range(cx_b - half, cx_b + half):
            _n, h = block_at(cells, bx, bz)
            if h is not None:
                hs.append(h)
    lo = min(hs) if hs else 0
    hi = max(hs) if hs else 1
    rng = max(1, hi - lo)
    img = Image.new("RGB", (size, size))
    px = img.load()
    for j, bz in enumerate(range(cz_b - half, cz_b + half)):
        for i, bx in enumerate(range(cx_b - half, cx_b + half)):
            nm, h = block_at(cells, bx, bz)
            if nm is None:
                px[i, j] = (26, 26, 30)          # 没数据 / 地形（NODATA）
                continue
            c = colors.get(nm) or (150, 150, 150)
            if shade and h is not None:
                f = 0.55 + 0.75 * (h - lo) / rng
                c = tuple(min(255, int(v * f)) for v in c)
            px[i, j] = c
    return img.resize((size * scale, size * scale), Image.NEAREST)


def ascii_map(cells, cx_b, cz_b, w, h, legend):
    out = []
    for bz in range(cz_b - h // 2, cz_b - h // 2 + h):
        row = []
        for bx in range(cx_b - w // 2, cx_b - w // 2 + w):
            nm, _ = block_at(cells, bx, bz)
            row.append(legend(nm))
        out.append("".join(row))
    return out


FAMILY = [
    ("polished_blackstone_bricks", "B"), ("cracked_polished_blackstone", "C"),
    ("polished_blackstone", "P"), ("blackstone", "k"), ("deepslate", "d"),
    ("soul_soil", "s"), ("soul_sand", "S"), ("warped_nylium", "w"),
    ("crimson_nylium", "r"), ("netherrack", "n"), ("basalt", "b"),
    ("obsidian", "O"), ("mud", "m"), ("end_stone", "e"), ("cobweb", "x"),
    ("nether_brick", "N"),
]


def legend(nm):
    if nm is None:
        return "."
    s = nm.replace("minecraft:", "")
    for key, ch in FAMILY:
        if key in s:
            return ch
    return "?"


def main():
    os.makedirs(OUT, exist_ok=True)
    colors = json.load(open(os.path.join(APP, "block_colors.json"), encoding="utf-8"))

    spots = [
        ("可疑点", 4586, -46944),
        ("真巫师", 4623, -46028),
    ]
    imgs = []
    for tag, bx, bz in spots:
        cells = load_area(bx - 100, bz - 100, bx + 100, bz + 100)
        print("=" * 88)
        print("%s (%d,%d)：读到 %d 个 chunk" % (tag, bx, bz, len(cells)))
        print("=" * 88)
        img = render(cells, bx, bz, 192, colors, scale=3)
        imgs.append((tag, bx, bz, img))
        p = os.path.join(OUT, "suspect_%s.png" % ("susp" if tag == "可疑点" else "wiz"))
        img.save(p)
        print("  图 -> %s" % p)

        # 该点周围 ±48 方块的用料统计
        h = Counter()
        for zz in range(bz - 48, bz + 48):
            for xx in range(bx - 48, bx + 48):
                nm, _hh = block_at(cells, xx, zz)
                if nm and nm != "minecraft:end_stone":
                    h[nm] += 1
        print("  ±48 方块内用料前 12：")
        for k, v in h.most_common(12):
            print("      %-42s %5d" % (k.replace("minecraft:", ""), v))
        print()
        print("  局部字符图（96x48 方块，中心=+）：")
        for j, row in enumerate(ascii_map(cells, bx, bz, 96, 48, legend)):
            if j == 24:
                row = row[:48] + "+" + row[49:]
            print("     " + row)
        print()

    # 拼一张对比图
    w = max(i[3].width for i in imgs)
    hh = max(i[3].height for i in imgs)
    pad = 16
    canvas = Image.new("RGB", (w * 2 + pad * 3, hh + pad * 2), (18, 18, 22))
    for k, (tag, bx, bz, img) in enumerate(imgs):
        canvas.paste(img, (pad + k * (w + pad), pad))
    p = os.path.join(OUT, "suspect_compare.png")
    canvas.save(p)
    print("对比图 -> %s  （左=%s，右=%s）" % (p, imgs[0][0], imgs[1][0]))


if __name__ == "__main__":
    main()
