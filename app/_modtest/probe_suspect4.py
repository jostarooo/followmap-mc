# -*- coding: utf-8 -*-
"""可疑点补充证据（二）：soul_soil 小建筑是不是一个**独立的族**。

probe_suspect3 发现 soul_soil>=80 的 chunk 全服有 6 个、彼此孤立、配比一致
（soul_soil : pbricks ≈ 5~6 : 1，真巫师是 0.39 : 1）。这一步：
  1) 放宽阈值（soul_soil>=40）重新连片，看这族小建筑到底有多少个实例；
  2) 每个实例取以 soul_soil 峰值 chunk 为中心的 5x5 chunk 窗口，打全量用料 +
     与巫师参考向量的余弦 + 族内两两余弦；
  3) 对每个实例跑两套判定：现有完整判据、「pbricks>=20 即巫师」的简化判据，
     看简化判据会把几个误报成巫师；
  4) chest 出现在哪个 chunk（全服唯一）。
"""
import os
import pickle
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
sys.path.insert(0, HERE)

from followmap.ruins import Signatures, safe_dim, parse_chunk   # noqa: E402
from test_ruins import REF, _cos                                # noqa: E402

CACHE = os.path.join(os.environ.get("TEMP", "/tmp"), "_probe_blockid_chunks.pkl")


def load():
    with open(CACHE, "rb") as fh:
        return pickle.load(fh)


def blobs(items):
    seen, out = set(), []
    for c0 in sorted(items):
        if c0 in seen:
            continue
        stack, blob = [c0], []
        seen.add(c0)
        while stack:
            cx, cz = stack.pop()
            blob.append((cx, cz))
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    nb = (cx + dx, cz + dz)
                    if nb in items and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
        out.append(blob)
    return out


def main():
    sigs = Signatures()
    hist = load()
    r = sigs.window // 2
    s_wiz = sigs._sets["巫师的圣修所"]
    SS = "minecraft:soul_soil"
    PB = "minecraft:polished_blackstone_bricks"

    # ---- 1) 放宽阈值连片 -----------------------------------------------------
    seeds = {k for k, c in hist.items() if c.get(SS, 0) >= 40}
    print("soul_soil>=40 的 chunk：%d 个" % len(seeds))
    bl = blobs(seeds)
    bl.sort(key=len, reverse=True)
    print("连片后 %d 片，取前 15 片分析：" % len(bl))

    fam = []
    for b in bl[:15]:
        # 峰值 chunk
        peak = max(b, key=lambda c: hist[c].get(SS, 0))
        # 5x5 chunk 窗口
        h = Counter()
        for dx in range(-2, 3):
            for dz in range(-2, 3):
                c = hist.get((peak[0] + dx, peak[1] + dz))
                if c:
                    h.update(c)
        hit = sum(v for k, v in h.items() if k in s_wiz)
        cos = _cos(h, REF["巫师的圣修所"])
        tot = sum(h.values())
        cls = sigs.classify(h)
        ok20 = h.get(PB, 0) >= 20
        fam.append((peak, h))
        print("  峰值chunk (%5d,%5d)  片=%d chunk  窗口总计=%-5d 巫师用料=%-5d "
              "pbricks=%-4d soul_soil=%-4d cos(巫师)=%.2f  完整判据=%s  "
              "pbricks>=20=%s"
              % (peak[0], peak[1], len(b), tot, hit, h.get(PB, 0), h.get(SS, 0),
                 cos, cls[0] if cls else "无", "会误报!" if ok20 else "否"))
        top = ", ".join("%s=%d" % (k.replace("minecraft:", ""), v)
                        for k, v in h.most_common(8))
        print("        主料: %s" % top)
    print()

    # ---- 2) 族内两两余弦 -----------------------------------------------------
    print("族内两两余弦（用 5x5 窗口直方图，只比「巫师用料表」内的键）：")
    print("      " + "  ".join("%d" % i for i in range(len(fam))))
    for i, (_, hi) in enumerate(fam):
        row = []
        for j, (_, hj) in enumerate(fam):
            a = {k: v for k, v in hi.items() if k in s_wiz}
            b = {k: v for k, v in hj.items() if k in s_wiz}
            num = sum(v * b.get(k, 0) for k, v in a.items())
            na = sum(v * v for v in a.values()) ** 0.5
            nb = sum(v * v for v in b.values()) ** 0.5
            row.append(num / (na * nb) if na and nb else 0.0)
        print("  %d   " % i + "  ".join("%.2f" % v for v in row))
    print()

    # ---- 3) chest 在哪 -------------------------------------------------------
    for k, c in sorted(hist.items()):
        if c.get("minecraft:chest"):
            print("chest 出现在 chunk (%d,%d)，计数 %d" % (k[0], k[1], c["minecraft:chest"]))


if __name__ == "__main__":
    main()
