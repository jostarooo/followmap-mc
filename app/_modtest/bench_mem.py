# -*- coding: utf-8 -*-
"""合成一份「末地跑图」规模的内存层数据，实测 Python 侧渲染能不能跟上。

结论指标：
  - 冷建 region（1024 个 chunk 全部首次解析）
  - 热重建 region（只改了 1 个 chunk，其余走 mtime 增量复用）
  - 整屏合成一帧（N 个 region）
"""
import os
import shutil
import struct
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)


def make_chunk(path, cx, cz, y, idx_of):
    """写一个与 mod 落盘格式完全一致的 chunk 快照。"""
    pal = ["minecraft:end_stone", "minecraft:obsidian", "minecraft:purpur_block"]
    b = bytearray()
    b += struct.pack("<IHHiiH", 0x31424243, 1, 0, cx, cz, len(pal))
    for s in pal:
        u = s.encode("utf-8")
        b += struct.pack("<H", len(u)) + u
    ys = np.full(256, y, dtype="<i2")
    idx = np.array([idx_of(i) for i in range(256)], dtype="<u2")
    b += ys.tobytes() + idx.tobytes()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(bytes(b))


def build_dataset(root, regions=3, chunk_step=3):
    r"""造 regions x regions 个 region 的完整数据（每 chunk 16x16，步长 chunk_step 表示稀疏度）。"""
    safe = "minecraft_the_end"
    n = 0
    for rx in range(regions):
        for rz in range(regions):
            for cx in range(rx * 32, rx * 32 + 32, chunk_step):
                for cz in range(rz * 32, rz * 32 + 32, chunk_step):
                    make_chunk(os.path.join(root, "chunks", safe, "r%d" % rx, "r%d" % rz,
                                            "%d_%d.bin" % (cx, cz)),
                               cx, cz, 63 + (cx + cz) % 7, lambda i: (i * 7 + cx) % 3)
                    n += 1
    # index：所有 region 的版本号都设为 1
    import json
    regs = {}
    for rx in range(regions):
        for rz in range(regions):
            regs["%d,%d" % (rx, rz)] = 1
    with open(os.path.join(root, "index_%s.json" % safe), "w", encoding="utf-8") as f:
        json.dump({"dim": "minecraft:the_end", "sid": 1, "rev": 1, "t": time.time() * 1000,
                   "chunks": n, "regions": regs}, f)
    return n


def main():
    root = os.path.join(HERE, "bench-home")
    if os.path.isdir(root):
        shutil.rmtree(root)
    os.makedirs(root)
    t0 = time.perf_counter()
    n = build_dataset(root, regions=3, chunk_step=3)
    print("生成 %d 个 chunk 快照，用时 %.2fs" % (n, time.perf_counter() - t0))

    from followmap.memstore import MemLayer
    dim_map = {"null": "minecraft:the_end"}
    mem = MemLayer(root=root, cache_dir=os.path.join(HERE, "bench-cache"),
                   dim_map=dim_map, mem_limit=64)

    # ---- 冷建：单 region 首次全解析 ----
    t0 = time.perf_counter()
    img = mem.region_image("null", 0, 0, 1)
    cold = (time.perf_counter() - t0) * 1000
    print("冷建 region(1024 chunk 满铺): %.1f ms   -> %s" %
          (cold, None if img is None else img.size))

    # ---- 热重建：改 1 个 chunk，让版本号 +1 ----
    import json
    idxf = os.path.join(root, "index_minecraft_the_end.json")
    make_chunk(os.path.join(root, "chunks", "minecraft_the_end", "r0", "r0", "0_0.bin"),
               0, 0, 99, lambda i: 1)
    with open(idxf, encoding="utf-8") as f:
        d = json.load(f)
    d["regions"]["0,0"] = 2
    with open(idxf, "w", encoding="utf-8") as f:
        json.dump(d, f)
    mem._idx.clear()

    t0 = time.perf_counter()
    mem.region_image("null", 0, 0, 1)
    warm = (time.perf_counter() - t0) * 1000
    print("热重建 region(仅 1 chunk 变化): %.1f ms   (复用 %d 个 chunk)"
          % (warm, mem.reused))

    # ---- 整屏：9 个 region 冷建 + 再取一遍（缓存命中）----
    t0 = time.perf_counter()
    for rx in range(3):
        for rz in range(3):
            mem.region_image("null", rx, rz, 1)
    screen_cold = (time.perf_counter() - t0) * 1000
    mem.hits = 0
    t0 = time.perf_counter()
    for rx in range(3):
        for rz in range(3):
            mem.region_image("null", rx, rz, 1)
    screen_hit = (time.perf_counter() - t0) * 1000
    print("整屏 9 region 冷建: %.1f ms；缓存全命中: %.2f ms" % (screen_cold, screen_hit))

    # ---- 视口合成（含裁剪 + 拼接 + HUD）----
    from followmap.view import MapView

    class FakeStore:
        def region_path(self, dim, mw, rx, rz):
            return "<mem>" if mem.has_region(dim, rx, rz) else None

        def get(self, dim, mw, rx, rz, zoom=1, allow_build=False):
            return mem.region_image(dim, rx, rz, zoom)

        def request(self, *a, **k):
            return None

    v = MapView(FakeStore())
    v.render("null", "$mem", 256.0, 256.0, size=(520, 520), zoom=2,
             hud_lines=[("x", (255, 255, 255, 255))])
    t0 = time.perf_counter()
    for _ in range(10):
        v.render("null", "$mem", 256.0, 256.0, size=(520, 520), zoom=2,
                 hud_lines=[("x", (255, 255, 255, 255))])
    print("视口渲染 10 帧 zoom=2: %.2f ms/帧" % ((time.perf_counter() - t0) * 100))

    print("stats:", mem.stats())
    shutil.rmtree(root, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
