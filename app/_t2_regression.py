# -*- coding: utf-8 -*-
"""全量回归：解析所有 region 文件，统计 EOF 精确对齐率，并收集全局方块名。"""
import os
import sys
import json
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import xaero_region as XR

V = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14"
WM = os.path.join(V, "XaeroWorldMap", "Multiplayer_mcfkcs.com")


def collect_jobs():
    jobs = []
    for dim in sorted(os.listdir(WM)):
        d = os.path.join(WM, dim)
        if not os.path.isdir(d):
            continue
        for mw in sorted(os.listdir(d)):
            sub = os.path.join(d, mw)
            if not os.path.isdir(sub):
                continue
            for f in os.listdir(sub):
                if f.endswith(".zip") and XR.region_coords(f):
                    jobs.append((dim, mw, os.path.join(sub, f)))
    return jobs


def work(job):
    dim, mw, path = job
    try:
        rd = XR.parse_region_file(path)
        names = set(v.split("[")[0] for v in rd.blocks.values())
        return (True, dim, mw, os.path.basename(path), len(rd.blocks), names, "")
    except Exception as e:
        return (False, dim, mw, os.path.basename(path), 0, set(), "%s: %s" % (type(e).__name__, e))


def main():
    jobs = collect_jobs()
    print("总 region 文件数:", len(jobs), flush=True)
    ok = 0
    fails = []
    all_names = Counter()
    per_dim = Counter()
    with ProcessPoolExecutor(max_workers=8) as ex:
        for i, r in enumerate(ex.map(work, jobs, chunksize=16)):
            good, dim, mw, f, nb, names, err = r
            if good:
                ok += 1
                per_dim[dim] += 1
                for n in names:
                    all_names[n] += 1
            else:
                fails.append((dim, mw, f, err))
            if (i + 1) % 500 == 0:
                print("  ... %d/%d" % (i + 1, len(jobs)), flush=True)
    print()
    print("=" * 70)
    print("解析成功(EOF 精确对齐): %d / %d  = %.2f%%" % (ok, len(jobs), 100.0 * ok / max(1, len(jobs))))
    print()
    print("失败样本 (最多 25 条):")
    for dim, mw, f, err in fails[:25]:
        print("   %-30s %-14s %-16s %s" % (dim, mw, f, err))
    if len(fails) > 25:
        print("   ... 其余 %d 条" % (len(fails) - 25))
    print()
    print("全局出现过的方块种类数:", len(all_names))
    out = os.path.join(HERE, "block_inventory.json")
    with open(out, "w", encoding="utf-8") as fp:
        json.dump({"regions": len(all_names) and all_names,
                   "per_block_region_count": dict(all_names),
                   "per_dim_ok": dict(per_dim),
                   "total_files": len(jobs), "ok_files": ok}, fp,
                  ensure_ascii=False, indent=1)
    print("已写出:", out)


if __name__ == "__main__":
    main()
