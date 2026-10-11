# -*- coding: utf-8 -*-
"""把某维度所有 region 按坐标拼成一张整图（验证坐标方向与连续性）。"""
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import xaero_region as XR
from _t3_render import color_of, WM
from PIL import Image

DIM = sys.argv[1] if len(sys.argv) > 1 else "DIM1"
MW = sys.argv[2] if len(sys.argv) > 2 else "mw$default"
OUT = os.path.join(HERE, "out", "stitch_%s.png" % DIM.replace("$", "_").replace(":", "_"))

jobs = list(XR.iter_region_files(WM, DIM, MW))
print("region 数:", len(jobs))
if not jobs:
    raise SystemExit("no regions")

xs = [rc[0] for _, rc in jobs]
zs = [rc[1] for _, rc in jobs]
x0, x1 = min(xs), max(xs)
z0, z1 = min(zs), max(zs)
W = (x1 - x0 + 1) * 512
H = (z1 - z0 + 1) * 512
print("region 范围 x[%d..%d] z[%d..%d]  ->  画布 %dx%d 世界坐标 x[%d..%d] z[%d..%d]"
      % (x0, x1, z0, z1, W, H, x0 * 512, (x1 + 1) * 512, z0 * 512, (z1 + 1) * 512))

# 上限保护：整图过长时按整数倍降采样
K = 1
while max(W, H) / K > 7000:
    K *= 2
CELL = 512 // K
W2, H2 = (x1 - x0 + 1) * CELL, (z1 - z0 + 1) * CELL
print("降采样 1/%d -> 画布 %dx%d" % (K, W2, H2))

sheet = Image.new("RGBA", (W2, H2), (18, 18, 22, 255))
blocks_total = 0
for path, (rx, rz) in jobs:
    try:
        rd = XR.parse_region_file(path)
    except Exception as e:
        print("  跳过", os.path.basename(path), e)
        continue
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    px = img.load()
    for (dx, dz), nm in rd.blocks.items():
        px[dx, dz] = color_of(nm)
    if K > 1:
        img = img.resize((CELL, CELL), Image.BOX)
    blocks_total += len(rd.blocks)
    sheet.alpha_composite(img, ((rx - x0) * CELL, (rz - z0) * CELL))

sheet.save(OUT)
print("已写出:", OUT, sheet.size, "总方块格:", blocks_total)
