# -*- coding: utf-8 -*-
"""按「遗迹」而不是「窗口」算召回 + 淹没存活曲线。

为什么必须这样算：判定窗口是 5x5 区块，同一座遗迹会产生很多个偏移窗口；
生产上去重半径 96 格，**命中任意一个窗口就算发现了这座遗迹**。
所以拿窗口数当召回会严重低估（武士 147 个窗口其实只是十几座遗迹的偏移）。

用法：python _modtest/_ruincurve.py
"""
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from followmap.ruins import Signatures  # noqa: E402
import _nearmiss as NM  # noqa: E402
import _rule as R  # noqa: E402

DIM = "minecraft:the_end"
STEPS = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2]
DEDUP = 96          # 与 ruins.json 的 dedupe_blocks 一致


def cluster(pts):
    """把 (x,z,payload) 按 <=DEDUP 格并查集聚类 -> [[payload,...], ...]"""
    n = len(pts)
    par = list(range(n))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            dx = pts[i][0] - pts[j][0]
            dz = pts[i][1] - pts[j][1]
            if dx * dx + dz * dz <= DEDUP * DEDUP:
                a, b = find(i), find(j)
                if a != b:
                    par[a] = b
    out = {}
    for i in range(n):
        out.setdefault(find(i), []).append(pts[i][2])
    return list(out.values())


def collect_ruins(sigs, hist):
    r = sigs.window // 2
    per = {t: [] for t in R.TYPES}
    for w, z in sorted({(cx // 2 * 2, cz // 2 * 2) for (cx, cz) in hist}):
        h = NM.win(hist, w, z, r)
        if sum(h.values()) < 60:
            continue
        tn, tc = R.best_of(h)
        if tn:
            per[tn].append((w * 16 + 8, z * 16 + 8, h))
    return {t: cluster(v) for t, v in per.items()}


def shrink(h, s):
    out = {}
    for k, v in h.items():
        n = int(round(v * s))
        if n > 0:
            out[k] = n
    return out


def curve(sigs, ruins, name, rule, tag):
    row = []
    for s in STEPS:
        got = 0
        for group in ruins[name]:
            if any(R.apply_rule(sigs, shrink(h, s), name, rule)
                   for h in group):
                got += 1
        row.append(got)
    n = len(ruins[name])
    print("   %-44s %s   (遗迹 n=%d)"
          % (tag, " ".join("%3d" % v for v in row), n))


def main():
    sigs = Signatures()
    ruins = collect_ruins(sigs, NM.load_hist(DIM))
    print("按遗迹聚类后：%s" % {k: len(v) for k, v in ruins.items()})
    print("缩放:        " + " ".join("%3.1f" % s for s in STEPS))
    print()

    W = "巫师的圣修所"
    print("巫师:")
    curve(sigs, ruins, W, {"anchors": {}, "ratios": {}}, "基线上限（占比=0，即只靠纯度+总量>=60）")
    curve(sigs, ruins, W,
          {"anchors": {R.PB: 140, R.BL: 55, R.CR: 30, R.DS: 18}, "ratios": {}},
          "旧判据")
    curve(sigs, ruins, W,
          {"anchors": {R.PB: 100}, "ratios": {R.PB: 0.28}}, "新 pbrick>=100 + 占比>=0.28")
    curve(sigs, ruins, W,
          {"anchors": {R.PB: 70}, "ratios": {R.PB: 0.28}}, "新 pbrick>=70  + 占比>=0.28")
    print()

    S = "武士的修行地"
    print("武士:")
    curve(sigs, ruins, S, {"anchors": {}, "ratios": {}}, "基线上限")
    curve(sigs, ruins, S,
          {"anchors": {"minecraft:netherrack": 60, "@end_brick": 45,
                       "minecraft:polished_basalt": 8, "@crimson": 25}, "ratios": {}},
          "旧判据")
    curve(sigs, ruins, S,
          {"anchors": {"@end_brick": 30, "minecraft:polished_basalt": 5},
           "ratios": {"minecraft:netherrack": 0.14}},
          "新 endbrick>=30 + basalt>=5 + netherrack占比>=0.14")
    curve(sigs, ruins, S,
          {"anchors": {"@end_brick": 30}, "ratios": {"minecraft:netherrack": 0.12}},
          "新 endbrick>=30 + netherrack占比>=0.12")
    print()

    B = "白金星殿"
    print("白金:")
    curve(sigs, ruins, B, {"anchors": {}, "ratios": {}}, "基线上限")
    curve(sigs, ruins, B,
          {"anchors": {"minecraft:infested_stone_bricks": 55,
                       "@stone_brick": 120,
                       "minecraft:red_wool": 3},
           "ratios": {},
           "any": [{"@mossy": 18},
                   {"minecraft:smooth_stone_slab": 10,
                    "minecraft:smooth_quartz_stairs": 10}]},
          "旧判据")
    curve(sigs, ruins, B,
          {"anchors": {"minecraft:infested_stone_bricks": 35,
                       "minecraft:red_wool": 3},
           "ratios": {"@stone_brick": 0.30},
           "any": [{"@mossy": 12},
                   {"minecraft:smooth_stone_slab": 6,
                    "minecraft:smooth_quartz_stairs": 6}]},
          "新 infested>=35 + stonebrick占比>=0.30")


if __name__ == "__main__":
    main()
