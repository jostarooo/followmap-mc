# -*- coding: utf-8 -*-
"""地图延迟分段探针：用**真机数据**量出「从模组落盘到画到屏上」每一段的耗时。

不猜、不估算 —— 每段都实测。
输出一张表：段名 / 单次耗时 / 每帧调用次数 / 每帧合计。

用法：
    python _modtest/probe_latency.py
    python _modtest/probe_latency.py --size 560 --zoom 2
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

from followmap import paths as P                      # noqa: E402
from followmap.store import TileStore, ZOOMS, REGION  # noqa: E402
from followmap.memstore import MemLayer, CompositeStore, MEM_MW, _safe  # noqa: E402
from followmap.view import MapView                    # noqa: E402
from followmap.sources import BridgeSource            # noqa: E402


def timeit(fn, n=1, warm=0):
    """返回 (单次毫秒, 最后一次返回值)。"""
    for _ in range(warm):
        fn()
    t0 = time.perf_counter()
    r = None
    for _ in range(n):
        r = fn()
    return (time.perf_counter() - t0) * 1000.0 / max(1, n), r


class Rows:

    def __init__(self):
        self.rows = []

    def add(self, seg, ms, per_frame=1, note=""):
        self.rows.append((seg, ms, per_frame, ms * per_frame, note))

    def add_periodic(self, seg, ms, period, note=""):
        """偶发开销：每 period 秒才付一次，折算到每帧。"""
        self.rows.append((seg, ms, period, 0.0, "每 %.0fs 一次 -> 摊到每帧 %.3fms | %s"
                          % (period, ms / period, note)))

    def dump(self):
        print()
        print("%-44s %10s %8s %10s  %s" % ("段", "单次ms", "每帧次", "每帧ms", "说明"))
        print("-" * 122)
        tot = 0.0
        for seg, ms, pf, sub, note in self.rows:
            tot += sub
            print("%-44s %10.3f %8s %10.3f  %s" % (seg, ms, pf, sub, note))
        print("-" * 122)
        print("%-44s %10s %8s %10.3f" % ("合计（每帧固定开销）", "", "", tot))
        return tot


def measure_freshness(interval=0.25, rounds=6):
    """端到端新鲜度：模组写入一个 chunk → 画面上真的看见它，要多久？

    做法：造一份最小内存层数据（1 个 region），然后完全照主程序每帧的做法
    （`region_image(allow_build=False)` + 主循环的 sleep）轮询；
    某一刻「模组」改写一个 chunk 并 bump 版本号，量到画面出现新内容为止。
    这条路把三件事一起量了：索引 TTL、后台建图、帧周期。
    """
    import json
    import shutil
    import tempfile
    import struct as _struct

    out = []
    for i in range(rounds):
        root = tempfile.mkdtemp(prefix="probe_fresh_")
        try:
            safe = "minecraft_the_end"
            d = os.path.join(root, "chunks", safe, "r0", "r0")
            os.makedirs(d, exist_ok=True)
            idxf = os.path.join(root, "index_%s.json" % safe)

            def write_chunk(cx, cz, block, ver, fill=0):
                pal = ["minecraft:end_stone", block]
                b = bytearray()
                b += _struct.pack("<IHHiiH", 0x31424243, 1, 0, cx, cz, len(pal))
                for s in pal:
                    u = s.encode("utf-8")
                    b += _struct.pack("<H", len(u)) + u
                import numpy as _np
                ys = _np.full(256, 63, dtype="<i2")
                ix = _np.full(256, fill, dtype="<u2")
                b += ys.tobytes() + ix.tobytes()
                with open(os.path.join(d, "%d_%d.bin" % (cx, cz)), "wb") as f:
                    f.write(bytes(b))
                with open(idxf, "w", encoding="utf-8") as f:
                    json.dump({"dim": "minecraft:the_end", "sid": 1000 + i, "rev": ver,
                               "t": time.time() * 1000, "chunks": 1,
                               "regions": {"0,0": ver}}, f)

            write_chunk(0, 0, "minecraft:purpur_block", 1, fill=0)
            mem = MemLayer(root=root, cache_dir=os.path.join(root, "cache"),
                           dim_map={"null": "minecraft:the_end"}, mem_limit=32)
            comp = CompositeStore(object(), mem, base_mw=lambda d: None, mem_limit=32)

            def pixel():
                # 完全照 MapView.render 的做法：allow_build=False，缺了就交给 store
                im = comp.get("null", MEM_MW, 0, 0, 2, allow_build=False)
                if im is None:
                    return None
                return im.getpixel((4, 4))

            # 预热：等第一帧出来
            t0 = time.perf_counter()
            while time.perf_counter() - t0 < 5:
                if pixel() is not None:
                    break
                time.sleep(interval)
            base = pixel()

            # 「模组」此刻改写 chunk：整块换成青金石（颜色明显不同）
            t0 = time.perf_counter()
            write_chunk(0, 0, "minecraft:lapis_block", 2, fill=1)
            seen = None
            while time.perf_counter() - t0 < 5:
                p = pixel()
                if p is not None and p != base:
                    seen = (time.perf_counter() - t0) * 1000.0
                    break
                time.sleep(interval)
            out.append(("%d) 写盘 -> 画面变化（帧周期 %.0fms）" % (i + 1, interval * 1000),
                        seen if seen is not None else -1.0))
        finally:
            shutil.rmtree(root, ignore_errors=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="560")
    ap.add_argument("--zoom", type=int, default=2)
    ap.add_argument("--server", default=None)
    ap.add_argument("--interval", type=float, default=0.25,
                    help="模拟帧周期（秒），用来量端到端新鲜度")
    a = ap.parse_args()

    W = H = int(a.size) if "x" not in a.size else None
    size = (int(a.size.split("x")[0]), int(a.size.split("x")[1])) if "x" in a.size else (int(a.size), int(a.size))
    R = Rows()

    srv, src = P.resolve_server(a.server)
    print("Xaero 服务器目录: %s" % (srv or "(未找到)"))
    print("定位来源        : %s" % src)
    print("视口            : %dx%d  zoom=%d" % (size[0], size[1], a.zoom))
    if not srv:
        print("!! 没有底图目录，只能测内存层。")
    print()

    # ---------------------------------------------------------- 1 坐标源
    br = BridgeSource()
    ms, f = timeit(br.poll, n=200)
    R.add("坐标源 BridgeSource.poll（读 coords.json）", ms, 1,
          "age=%s" % (f.note or "-"))

    # ---------------------------------------------------------- 2 内存层索引
    xs = TileStore(srv) if srv else None
    dim_map = {}

    # 先用玩家当前坐标建立维度映射（跟主程序一样）
    from followmap.memstore import build_dim_map
    if f.ok and xs:
        t0 = time.perf_counter()
        dm = build_dim_map(xs, f.x, f.z)
        cold_map = (time.perf_counter() - t0) * 1000.0
        dim_map.update(dm)
        R.add_periodic("build_dim_map（扫上百个维度目录）", cold_map, 30,
                       "构建维度映射，后台线程做")
    else:
        dim_map["null"] = "minecraft:overworld"
        R.add_periodic("build_dim_map", 0.0, 30, "无坐标，跳过")

    mem = MemLayer(dim_map=dim_map, cache_dir=os.path.join(APP, "cache", "memtiles"))
    # 找一个真有内存数据的 (dim -> safe)
    did = None
    for k, v in dim_map.items():
        if mem._index(k):
            did = k
            break
    if did is None:
        did = list(dim_map)[0] if dim_map else "null"
    safe = _safe(dim_map.get(did, "minecraft:overworld"))
    print("内存层维度      : %s -> %s（safe=%s）" % (did, dim_map.get(did), safe))

    t0 = time.perf_counter()
    idx = mem._index(did)
    cold_idx = (time.perf_counter() - t0) * 1000.0
    R.add_periodic("MemLayer._index 冷读 index_<dim>.json", cold_idx, 1.0,
                   "TTL=1.0s，到点才真读盘")
    ms, _ = timeit(lambda: mem._index(did), n=1000)
    R.add("MemLayer._index 命中缓存", ms, 1,
          "★ 1 秒 TTL 决定「模组刚写的版本」最晚 1s 才被看见")

    # ---------------------------------------------------------- 3 Xaero 存在性
    if xs:
        dims = xs.dims()
        print("Xaero 维度目录数 : %d" % len(dims))
        dim_x = None
        for d, mws in dims:
            for mw in mws:
                if xs._existing(d, mw):
                    dim_x, mw_x = d, mw
                    break
            if dim_x:
                break
        ms, _ = timeit(lambda: xs._existing(dim_x, mw_x), n=500)
        R.add("TileStore._existing（命中 1.5s 缓存）× 视口格数", ms, 16,
              "视口每格都要问一次 region 存不存在")
        t0 = time.perf_counter()
        xs._exist.clear()
        xs._existing(dim_x, mw_x)
        cold = (time.perf_counter() - t0) * 1000.0
        R.add_periodic("TileStore._existing 冷 listdir", cold, 1.5, "TTL=1.5s")

    # ---------------------------------------------------------- 4 瓦片取用
    # 找一个内存层真有图的 region
    regs = (idx or {}).get("regions", {})
    probe_reg = None
    for k in list(regs)[:200]:
        rx, rz = [int(x) for x in k.split(",")]
        if mem.region_image(did, rx, rz, 1, allow_build=False) is not None:
            probe_reg = (rx, rz)
            break
    if probe_reg is None and regs:
        k = list(regs)[0]
        rx, rz = [int(x) for x in k.split(",")]
        mem.region_image(did, rx, rz, 1, allow_build=True)   # 让它建一次
        probe_reg = (rx, rz)
    print("取样的内存 region: %s" % (probe_reg,))

    if probe_reg:
        rx, rz = probe_reg
        ver = mem.region_ver(did, rx, rz)
        sid = mem.session(did)
        key = (safe, rx, rz, a.zoom, ver, sid)
        cp = mem._cache_path(safe, sid, rx, rz, a.zoom, ver)

        ms, _ = timeit(lambda: mem.region_image(did, rx, rz, a.zoom, allow_build=False), n=300)
        R.add("MemLayer 内存命中（LRU）", ms, 1, "最快路径")

        # 真·磁盘命中：确保 PNG 已落盘，再清掉 LRU 那一项
        if not os.path.exists(cp):
            img0 = mem.region_image(did, rx, rz, a.zoom, allow_build=True)
            time.sleep(0.4)                 # 等后台写盘线程落盘
        with mem._lock:
            mem._mem.pop(key, None)
        ok = False
        if os.path.exists(cp):
            ms, im = timeit(lambda: (mem._mem.pop(key, None),
                                     mem.region_image(did, rx, rz, a.zoom, allow_build=False))[1],
                            n=100)
            ok = im is not None
        if ok:
            R.add("MemLayer 磁盘命中（PNG 解码，在 UI 线程）", ms, 1,
                  "★ LRU 被淘汰/首帧时走这条，实测 %.0fKB/张" % (os.path.getsize(cp) / 1024.0))
        else:
            R.add("MemLayer 磁盘命中", 0.0, 0, "该 region 无磁盘缓存，跳过")

        # 真冷建：把磁盘缓存挪走，强制从 .bin 重建
        if os.path.exists(cp + ".bak"):
            try:
                os.remove(cp + ".bak")
            except OSError:
                pass
        if os.path.exists(cp):
            os.rename(cp, cp + ".bak")
        with mem._lock:
            mem._mem.pop(key, None)
        ms, _ = timeit(lambda: mem.region_image(did, rx, rz, a.zoom, allow_build=True), n=3)
        R.add_periodic("MemLayer 冷建一整个 region（后台池）", ms, 10.0,
                       "打开上百个 .bin；版本号一变就要重建一次")
        if os.path.exists(cp + ".bak"):
            try:
                os.remove(cp)
            except OSError:
                pass
            try:
                os.rename(cp + ".bak", cp)
            except OSError:
                pass

    # ---------------------------------------------------------- 5 合成
    comp = None
    if xs:
        comp = CompositeStore(xs, mem,
                              base_mw=lambda d: (mw_x if xs.region_path(d, mw_x, 0, 0) else None))
        # 直接用一个真实存在的底图 region
        brx = brz = None
        for f2 in os.listdir(os.path.join(xs.server_dir, dim_x, mw_x))[:400]:
            if f2.endswith(".zip"):
                aa, bb = f2[:-4].split("_")
                brx, brz = int(aa), int(bb)
                break
        # Xaero 单张取用：内存命中 vs 磁盘解码
        if brx is not None:
            ms, _ = timeit(lambda: xs.get(dim_x, mw_x, brx, brz, a.zoom, allow_build=True), n=3)
            R.add_periodic("Xaero 冷建一张 region（解析 zip + 着色 + 全部档位）", ms, 60.0,
                           "Xaero 自己 60s 才落一次盘，跟它同频")
            ms, _ = timeit(lambda: xs.get(dim_x, mw_x, brx, brz, a.zoom, allow_build=False), n=300)
            R.add("Xaero 内存命中", ms, 1, "底图通常整屏都在 LRU 里")
            # 磁盘命中：清 LRU
            cp2 = xs._cache_path(dim_x, mw_x, brx, brz, a.zoom)
            if os.path.exists(cp2):
                with xs._lock:
                    xs._mem.pop((dim_x, mw_x, brx, brz, a.zoom), None)
                ms, _ = timeit(lambda: (xs._lock.acquire(),
                                        xs._mem.pop((dim_x, mw_x, brx, brz, a.zoom), None),
                                        xs._lock.release(),
                                        xs.get(dim_x, mw_x, brx, brz, a.zoom,
                                               allow_build=False))[-1], n=60)
                R.add("Xaero 磁盘命中（PNG 解码）", ms, 1, "底图 LRU 被挤掉时走这条")

        if brx is not None and probe_reg:
            ms, _ = timeit(lambda: comp.get(dim_x, MEM_MW, probe_reg[0], probe_reg[1], a.zoom,
                                            allow_build=False), n=200)
            R.add("CompositeStore.get（LRU 命中）", ms, 1, "叠完就缓存")
            # 合成缓存缺失：under.copy() + alpha_composite
            kk = None
            with comp._lock:
                for k in list(comp._mem):
                    if k[1] == probe_reg[0] and k[2] == probe_reg[1]:
                        kk = k
                        break
                if kk:
                    comp._mem.pop(kk, None)
            if kk:
                ms, _ = timeit(lambda: comp.get(dim_x, MEM_MW, probe_reg[0], probe_reg[1],
                                                a.zoom, allow_build=False), n=100)
                R.add("CompositeStore 合成（底图 copy + 内存层 alpha 合成）", ms, 1,
                      "★ 版本号一变，合成缓存键就变，必须重合成")
                with comp._lock:
                    comp._mem[k] = comp._mem.get(k)   # 保持原状

    # ---------------------------------------------------------- 6 整帧渲染
    store = comp if comp is not None else mem
    view = MapView(store)

    cx, cz = (f.x, f.z) if f.ok else (0.0, 0.0)
    hud = [("HUD 行 1 %s" % did, (255, 214, 120, 255)),
           ("X %.1f Y %.1f Z %.1f" % (cx, 0.0, cz), (240, 240, 250, 255)),
           ("内存直读 延迟0.4s 建图12 上次9ms", (140, 230, 180, 255)),
           ("已记录遗迹 31 处  方式 auto", (200, 205, 180, 255))]

    dim_use = dim_x if xs else did
    mw_use = MEM_MW if xs else "$mem"

    # 预热视口
    for _ in range(60):
        img, miss = view.render(dim_use, mw_use, cx, cz,
                                size=size, zoom=a.zoom, hud_lines=hud)
        if miss == 0:
            break
    ms, _ = timeit(lambda: view.render(dim_use, mw_use, cx, cz, size=size, zoom=a.zoom,
                                       hud_lines=hud), n=40)
    R.add("MapView.render 整帧（拼接+HUD+POI+玩家）", ms, 1,
          "视口 %d 格 / 缺瓦片 %d" % (((size[0] // (REGION // a.zoom) + 2)
                                  * (size[1] // (REGION // a.zoom) + 2)), miss))

    # HUD 文本单独量
    import hudtext as HT
    ms, _ = timeit(lambda: [HT.render(s, 1, fg=c) for s, c in hud], n=50)
    R.add("HUD 文字渲染 4 行", ms, 1, "看 hudtext 有没有缓存")

    # ---------------------------------------------------------- 7 Tk 上传
    try:
        import tkinter as tk
        from PIL import ImageTk
        root = tk.Tk()
        root.withdraw()
        im = img.convert("RGBA")
        ms, _ = timeit(lambda: ImageTk.PhotoImage(im), n=20)
        R.add("ImageTk.PhotoImage（像素送进 Tk）", ms, 1,
              "%dx%d = %.2f MB/帧" % (size[0], size[1], size[0] * size[1] * 4 / 1048576.0))
        root.destroy()
    except Exception as e:
        R.add("ImageTk.PhotoImage", 0.0, 0, "无 Tk 环境: %s" % e)

    # ---------------------------------------------------------- 8 偶发开销
    if xs:
        ms, _ = timeit(lambda: xs.dims(), n=20)
        R.add_periodic("TileStore.dims 列全部维度目录", ms, 15, "_pairs 用")
        ms, _ = timeit(lambda: xs.last_activity(dim_x, mw_x), n=20)
        R.add_periodic("TileStore.last_activity 全 listdir+stat", ms, 15, "_pairs 用")

    tot = R.dump()

    # ---------------------------------------------------------- 9 端到端新鲜度
    print()
    print("== 端到端：模组写盘 -> 画面上看见（合成数据，走真实代码路径）==")
    {"ok": True, "x": 0.0, "z": 0.0}
    fresh = measure_freshness(interval=a.interval)
    R2 = Rows()
    for k, v in fresh:
        R2.add(k, v, 1)
    R2.dump()

    print()
    print("== 结论用的推导 ==")
    ms_frame = tot
    print("  每帧固定开销            : %.1f ms" % ms_frame)
    print("  帧周期 --interval 250ms : 实际 fps ≈ %.1f" % (1000.0 / (250.0 + ms_frame)))
    print("  模组侧 full sweep 周期  : 约 90 ms（scan_status.txt 实测）")
    print("  MemLayer 索引 TTL       : 1.0 s   <- 数据新鲜度上限")
    print("  Xaero _existing TTL     : 1.5 s")
    print("  Xaero 自身落盘周期      : 60 s（MapSaveLoad.SAVE_TIME，编译期常量）")

    print()
    print("stats: xaero=%s" % (xs.stats() if xs else "-"))
    print("       mem   =%s" % mem.stats())
    return 0


if __name__ == "__main__":
    sys.exit(main())
