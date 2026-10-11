# -*- coding: utf-8 -*-
"""把真机数据里所有「人造方块簇」聚合出来：位置、规模、完整用料、独立余弦、判据结果。

这是修判据前必须先有的全局图景 —— 只看单个窗口会被 80x80 的窗口截断骗到。
"""
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from followmap.ruins import Signatures  # noqa: E402
from _nearmiss import REF, cos, load_hist  # noqa: E402


def clusters(hist, gap=1):
    """chunk 级 8 连通聚类（gap=1 表示允许隔 1 个 chunk 也并起来）。"""
    cells = set(hist)
    seen = set()
    out = []
    for c in cells:
        if c in seen:
            continue
        stack = [c]
        seen.add(c)
        grp = []
        while stack:
            cur = stack.pop()
            grp.append(cur)
            for dx in range(-1 - gap, 2 + gap):
                for dz in range(-1 - gap, 2 + gap):
                    n = (cur[0] + dx, cur[1] + dz)
                    if n in cells and n not in seen:
                        seen.add(n)
                        stack.append(n)
        out.append(grp)
    return out


def main():
    sigs = Signatures()
    hist = load_hist("minecraft:the_end")
    cl = clusters(hist)
    cl.sort(key=lambda g: -sum(sum(hist[c].values()) for c in g))
    print("人造簇 %d 个（chunk 级 8 连通 + 间隔 1）" % len(cl))
    print("=" * 110)
    hdr = ("%-16s %5s %6s %7s %7s %-8s %s"
           % ("中心(块)", "chunk", "人造数", "最佳余弦", "归属", "判定", "主要用料"))
    print(hdr)
    for g in cl:
        tot = sum(sum(hist[c].values()) for c in g)
        if tot < 40:
            continue
        agg = Counter()
        for c in g:
            agg.update(hist[c])
        xs = [c[0] * 16 + 8 for c in g]
        zs = [c[1] * 16 + 8 for c in g]
        cx = sum(xs) // len(xs)
        cz = sum(zs) // len(zs)
        best, bn = 0.0, None
        for nm, ref in REF.items():
            v = cos(agg, ref)
            if v > best:
                best, bn = v, nm
        got = sigs.classify(sigs_window(agg, sigs))
        top = " ".join("%s=%d" % (k.replace("minecraft:", ""), v)
                       for k, v in agg.most_common(7))
        print("%-16s %5d %6d %7.3f %-8s %-8s %s"
              % ("(%d,%d)" % (cx, cz), len(g), tot, best, bn,
                 (got[0] if got else "-"), top))


def sigs_window(agg, sigs):
    """簇的整体直方图直接当窗口喂给分类器（簇比 5x5 窗口更接近"一座建筑"）。"""
    return agg


if __name__ == "__main__":
    main()
