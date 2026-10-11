# -*- coding: utf-8 -*-
"""
扫描某个维度里的「人造结构」候选点。
====================================

原理：末地（DIM1）的自然地表只有 end_stone / chorus_plant / chorus_flower / air。
凡是出现其它方块的位置，都是人造结构 —— 也就是遗迹。

对每个 region 解析后，把「非自然方块」按 16×16 格分桶统计，
主进程汇总后按桶内非自然方块数量排序，即得到遗迹候选点。

输出 structures_<dim>.json
"""
import os
import sys
import json
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import xaero_region as XR

V = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14"
WM = os.path.join(V, "XaeroWorldMap", "Multiplayer_mcfkcs.com")

NATURAL = {
    "minecraft:air", "minecraft:cave_air", "minecraft:void_air",
    "minecraft:end_stone", "minecraft:chorus_plant", "minecraft:chorus_flower",
    "minecraft:grass_block", "minecraft:barrier", "minecraft:light",
}

DIMS = sys.argv[1:] or ["DIM1"]


def scan_region(args):
    path, rx, rz = args
    try:
        rd = XR.parse_region_file(path)
    except Exception:
        return None
    buckets = Counter()
    names_in_bucket = {}
    for (dx, dz), nm in rd.blocks.items():
        base = nm.split("[")[0]
        if base in NATURAL:
            continue
        wx = rx * 512 + dx
        wz = rz * 512 + dz
        key = (wx // 16, wz // 16)
        buckets[key] += 1
        d = names_in_bucket.setdefault(key, Counter())
        d[base] += 1
    return (rx, rz, buckets, {k: dict(v.most_common(6)) for k, v in names_in_bucket.items()})


def main():
    for dim in DIMS:
        jobs = [(p, rc[0], rc[1]) for p, rc in XR.iter_region_files(WM, dim)]
        if not jobs:
            print("[%s] 无 region" % dim)
            continue
        print("[%s] region 数: %d  开始扫描..." % (dim, len(jobs)), flush=True)

        total = Counter()
        details = {}
        with ProcessPoolExecutor(max_workers=8) as ex:
            for r in ex.map(scan_region, jobs, chunksize=8):
                if not r:
                    continue
                rx, rz, buckets, dinfo = r
                for k, v in buckets.items():
                    total[k] += v
                for k, v in dinfo.items():
                    d = details.setdefault(k, Counter())
                    d.update(v)

        # 聚合成更大的簇：把相邻(含对角)的非空桶连起来
        cells = {k for k, v in total.items() if v >= 8}
        seen = set()
        clusters = []
        for c in cells:
            if c in seen:
                continue
            stack = [c]
            seen.add(c)
            members = []
            while stack:
                cur = stack.pop()
                members.append(cur)
                cx, cz = cur
                for dx in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        nb = (cx + dx, cz + dz)
                        if nb in cells and nb not in seen:
                            seen.add(nb)
                            stack.append(nb)
            # 统计
            cnt = sum(total[m] for m in members)
            agg = Counter()
            for m in members:
                agg.update(details.get(m, {}))
            xs = [m[0] for m in members]
            zs = [m[1] for m in members]
            clusters.append({
                "count": cnt,
                "cells": len(members),
                "bbox": [min(xs) * 16, min(zs) * 16, (max(xs) + 1) * 16, (max(zs) + 1) * 16],
                "center": [int((min(xs) + max(xs) + 1) / 2 * 16), int((min(zs) + max(zs) + 1) / 2 * 16)],
                "blocks": agg.most_common(10),
            })
        clusters.sort(key=lambda c: -c["count"])

        out = os.path.join(HERE, "structures_%s.json" % dim.replace("$", "_").replace(":", "_"))
        with open(out, "w", encoding="utf-8") as fp:
            json.dump({"dim": dim, "region_count": len(jobs), "clusters": clusters}, fp,
                      ensure_ascii=False, indent=1)
        print("  簇数: %d -> %s" % (len(clusters), out))
        for i, c in enumerate(clusters[:15]):
            bs = ", ".join("%s×%d" % (b.replace("minecraft:", ""), n) for b, n in c["blocks"][:4])
            print("   #%-2d center=(%6d,%7d) 方块=%-6d 面积=%-4d %s"
                  % (i + 1, c["center"][0], c["center"][1], c["count"], c["cells"], bs))
        print()


if __name__ == "__main__":
    main()
