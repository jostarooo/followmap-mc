# -*- coding: utf-8 -*-
"""按世界坐标矩形渲染地图（跨 region 拼接）。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import xaero_region as XR
from _t3_render import color_of, WM
from PIL import Image, ImageDraw

_cache = {}


def load_region(dim, mw, rx, rz):
    key = (dim, mw, rx, rz)
    if key in _cache:
        return _cache[key]
    p = os.path.join(WM, dim, mw, "%d_%d.zip" % (rx, rz))
    v = None
    if os.path.exists(p):
        try:
            v = XR.parse_region_file(p)
        except Exception:
            v = None
    _cache[key] = v
    return v


def render_rect(dim, x0, z0, x1, z1, mw="mw$default", bg=(20, 20, 24)):
    """渲染世界坐标矩形 [x0,x1) x [z0,z1)，1 像素 = 1 方块。"""
    W, H = x1 - x0, z1 - z0
    img = Image.new("RGBA", (W, H), bg + (255,))
    px = img.load()
    rx0, rx1 = x0 // 512, (x1 - 1) // 512
    rz0, rz1 = z0 // 512, (z1 - 1) // 512
    missing = 0
    for rx in range(rx0, rx1 + 1):
        for rz in range(rz0, rz1 + 1):
            rd = load_region(dim, mw, rx, rz)
            if rd is None:
                missing += 1
                continue
            bx, bz = rx * 512, rz * 512
            for (dx, dz), nm in rd.blocks.items():
                wx, wz = bx + dx, bz + dz
                if x0 <= wx < x1 and z0 <= wz < z1:
                    px[wx - x0, wz - z0] = color_of(nm)
    return img, missing


if __name__ == "__main__":
    OUT = os.path.join(HERE, "out")
    os.makedirs(OUT, exist_ok=True)
    # 前三处主岛建筑的簇中心（来自 scan_structures.py）
    targets = [
        ("c1_glass", -384, -544),
        ("c2_blackstone", 784, 280),
        ("c3_quartz", 280, -624),
    ]
    R = 448
    for name, cx, cz in targets:
        img, miss = render_rect("DIM1", cx - R, cz - R, cx + R, cz + R)
        d = ImageDraw.Draw(img)
        # 十字标出中心
        d.line([(R - 12, R), (R + 12, R)], fill=(255, 60, 60, 255), width=2)
        d.line([(R, R - 12), (R, R + 12)], fill=(255, 60, 60, 255), width=2)
        p = os.path.join(OUT, "struct_%s.png" % name)
        img.save(p)
        print("%-16s center=(%d,%d) -> %s  缺 region:%d" % (name, cx, cz, p, miss))
