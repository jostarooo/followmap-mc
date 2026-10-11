# -*- coding: utf-8 -*-
"""把遗迹扫描结果转成跟随地图的 POI 文件。

`scan_structures.py` 输出的是「异常方块聚集簇」——只能说明"这附近有东西"，
不能自动认出是巫师/武士/白金。所以这里的做法是：
  - 自动把每个簇落成一个「候选遗迹 N」标记，跑到附近时地图上就能看到；
  - 你人工确认后，直接编辑 poi.json 把 name 改成真名（或加一条新的）。

用法：
    python make_poi.py structures_DIM1.json structures_minecraft_hard_the_end.json
    python make_poi.py --out poi.json --min-count 200 *.json
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

VERSION_DIR = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14"
DEFAULT_SERVER = os.path.join(VERSION_DIR, "XaeroWorldMap", "Multiplayer_mcfkcs.com")


def pick_mw(store, dim):
    """给维度目录挑一个子图：优先 mw$default，否则最多的那个。"""
    d = os.path.join(store.server_dir, dim)
    if not os.path.isdir(d):
        return None
    subs = [s for s in os.listdir(d) if os.path.isdir(os.path.join(d, s))]
    if "mw$default" in subs:
        return "mw$default"
    mw = sorted([s for s in subs if s.startswith("mw")])
    if mw:
        return mw[0]
    cm = sorted([s for s in subs if s.startswith("cm")])
    return cm[0] if cm else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default=os.path.join(HERE, "poi.json"))
    ap.add_argument("--min-count", type=int, default=100,
                    help="只保留方块数 >= 该值的簇")
    ap.add_argument("--top", type=int, default=0,
                    help="每个文件只保留最大的 N 个簇（0=不限）")
    ap.add_argument("--server", default=DEFAULT_SERVER)
    ap.add_argument("--keep-existing", action="store_true",
                    help="保留 poi.json 里已有的条目（默认覆盖）")
    a = ap.parse_args()

    from followmap.store import TileStore
    store = TileStore(a.server)

    out = []
    if a.keep_existing and os.path.exists(a.out):
        try:
            out = json.load(open(a.out, encoding="utf-8"))
        except Exception:
            out = []

    files = []
    for pat in a.files:
        files.extend(sorted(glob.glob(pat)) if any(c in pat for c in "*?") else [pat])

    for fp in files:
        if not os.path.exists(fp):
            print("跳过（不存在）:", fp)
            continue
        data = json.load(open(fp, encoding="utf-8"))
        dim = data.get("dim") or os.path.splitext(os.path.basename(fp))[0]
        mw = pick_mw(store, dim)
        cl = [c for c in data.get("clusters", []) if c.get("count", 0) >= a.min_count]
        cl.sort(key=lambda c: -c.get("count", 0))
        if a.top:
            cl = cl[:a.top]
        print("%-34s dim=%-30s mw=%-12s 簇 %d/%d"
              % (os.path.basename(fp), dim, mw, len(cl), len(data.get("clusters", []))))
        for c in cl:
            cx, cz = c["center"]
            out.append({"name": "候选遗迹 %d块" % c.get("count", 0),
                        "x": cx, "z": cz, "dim": dim, "mw": mw,
                        "count": c.get("count"), "cells": c.get("cells")})

    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("\n写出 %d 条 -> %s" % (len(out), a.out))
    print("提示：确认名称后直接改 poi.json 里的 name 字段即可在地图上显示真名。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
