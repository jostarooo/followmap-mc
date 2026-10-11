# -*- coding: utf-8 -*-
"""按 app.py 的真实图层组合（内存直读 + Xaero 底图）渲染指定中心的一屏，用于和用户截图对照。

用法：python _modtest/_shoot.py 47544 -39155 [输出名]
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
if APP not in sys.path:
    sys.path.insert(0, APP)

from PIL import Image, ImageDraw  # noqa: E402

from followmap.memstore import MEM_MW, CompositeStore, MemLayer  # noqa: E402
from followmap.store import TileStore  # noqa: E402
from followmap.view import MapView  # noqa: E402

SERVER = os.path.join(
    r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14",
    "XaeroWorldMap", "Multiplayer_mcfkcs.com")


def main():
    cx = int(sys.argv[1])
    cz = int(sys.argv[2])
    tag = sys.argv[3] if len(sys.argv) > 3 else ("x%d_z%d" % (cx, cz))
    dim = sys.argv[4] if len(sys.argv) > 4 else "DIM1"

    xaero = TileStore(SERVER)
    dim_map = {}
    # dim_map: Xaero 目录名 -> mod 维度 id（app 里由 build_dim_map 生成）
    try:
        from followmap.memstore import build_dim_map
        dim_map.update(build_dim_map(xaero))
    except Exception as e:
        print("build_dim_map 失败:", e)
    print("dim_map:", {k: v for k, v in dim_map.items() if v})

    mem = MemLayer(dim_map=dim_map, mem_limit=96)

    def base_mw(d):
        return "mw$default"

    store = CompositeStore(xaero, mem, base_mw=base_mw, mem_limit=64)
    view = MapView(store)

    size = (520, 520)
    img = None
    miss = -1
    for i in range(80):
        img, miss = view.render(dim, MEM_MW, cx, cz, size=size, zoom=1,
                                hud_lines=[("%s %s  (%d,%d)" % (dim, MEM_MW, cx, cz),
                                            (255, 220, 120, 255))])
        if miss == 0:
            break
        time.sleep(0.12)
    d = ImageDraw.Draw(img)
    d.line([(260 - 14, 260), (260 + 14, 260)], fill=(255, 60, 60, 255), width=2)
    d.line([(260, 260 - 14), (260, 260 + 14)], fill=(255, 60, 60, 255), width=2)
    p = os.path.join(HERE, "_shot_%s.png" % tag)
    img.convert("RGB").resize((780, 780), Image.NEAREST).save(p)
    print("miss=%d -> %s" % (miss, p))


if __name__ == "__main__":
    main()
