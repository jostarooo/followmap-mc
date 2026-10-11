# -*- coding: utf-8 -*-
"""为「纯方块 id 判据」定阈值（承接 probe_blockid_rule2.py，目标是改 ruins.json）。

第 12 节结论：巫师/白金有**独占 id**（polished_blackstone_bricks / infested_stone_bricks），
可以直接用；但武士没有独占 id（end_brick 家族与紫珀殿/幽匿殿重叠、黑石系与巫师重叠），
需要找到「id + 阈值」的组合。

本探针：
  1) 对每个候选 id 做窗口级阈值扫描：报出组数 / 真目标 / 误报 / 漏检
     （漏检 = 现有完整判据的真值建筑没被新判据盖住）；
  2) 打印「目标建筑窗口内该 id 的最小值」vs「非目标窗口的最大值」，直接看可分带；
  3) 武士试组合判据（@end_brick + 黑石系特征）。

真值口径同第 12 节：报出重心 200 方块内有现有判据同类命中 => 真。
"""
import os
import pickle
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

from followmap.ruins import Signatures, safe_dim, parse_chunk   # noqa: E402

DIM = "minecraft:the_end"
ROOT = os.path.join(os.path.expanduser("~"), ".coordbridge")
CACHE = os.path.join(os.environ.get("TEMP", "/tmp"), "_probe_blockid_chunks.pkl")

M = "minecraft:"
PB = M + "polished_blackstone_bricks"
INF = M + "infested_stone_bricks"
STAIRS = M + "blackstone_stairs"
GILD = M + "gilded_blackstone"
RW = M + "red_wool"


def load():
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as fh:
            return pickle.load(fh)
    base = os.path.join(ROOT, "chunks", safe_dim(DIM))
    hist = {}
    for rx in os.listdir(base):
        p1 = os.path.join(base, rx)
        if not os.path.isdir(p1):
            continue
        for rz in os.listdir(p1):
            p2 = os.path.join(p1, rz)
            if not os.path.isdir(p2):
                continue
            for fn in os.listdir(p2):
                if not fn.endswith(".bin"):
                    continue
                a, _, b = fn[:-4].partition("_")
                try:
                    cx, cz = int(a), int(b)
                except ValueError:
                    continue
                hist[(cx, cz)] = parse_chunk(os.path.join(p2, fn)) or Counter()
    with open(CACHE, "wb") as fh:
        pickle.dump(hist, fh, -1)
    return hist


def centroid_blocks(hist, wcx, wcz, r, featset):
    xs, zs = [], []
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            c = hist.get((wcx + dx, wcz + dz))
            if not c:
                continue
            hit = sum(v for k, v in c.items() if k in featset)
            if hit:
                xs += [wcx + dx] * hit
                zs += [wcz + dz] * hit
    if not xs:
        return wcx * 16 + 8, wcz * 16 + 8
    return int(sum(xs) / len(xs) * 16 + 8), int(sum(zs) / len(zs) * 16 + 8)


def main():
    sigs = Signatures()
    hist = load()
    r = sigs.window // 2
    d2 = sigs.dedupe_blocks ** 2
    tot = {k: sum(v.values()) for k, v in hist.items()}

    # ---- 窗口集合 + 现有判据真值 ----
    wins = []
    truth = {}
    for c0x, c0z in sorted({(cx // 2, cz // 2) for cx, cz in hist}):
        wcx, wcz = c0x * 2, c0z * 2
        s = 0
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                s += tot.get((wcx + dx, wcz + dz), 0)
        if s < 60:
            continue
        h = Counter()
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                c = hist.get((wcx + dx, wcz + dz))
                if c:
                    h.update(c)
        wins.append((wcx, wcz, h))
        got = sigs.classify(h)
        if got:
            x, z = centroid_blocks(hist, wcx, wcz, r, sigs._sets[got[0]])
            truth.setdefault(got[0], []).append((x, z))
    print("窗口 %d 个；现有判据命中：%s"
          % (len(wins), "  ".join("%s %d" % (t, len(v)) for t, v in truth.items())))

    def near(x, z, t, rad=200.0):
        return any((px - x) ** 2 + (pz - z) ** 2 <= rad * rad
                   for px, pz in truth.get(t, ()))

    def scan(name, keys, T):
        """keys: 单 id 或 (说明, lambda(h)->值)。返回组列表。"""
        if callable(keys):
            val = keys
            label = name
        else:
            val = lambda h, k=keys: h.get(k, 0)
            label = keys.replace(M, "")
        cand = [w for w in wins if val(w[2]) >= T]
        grp = []
        for wcx, wcz, h in sorted(cand, key=lambda w: -val(w[2])):
            feat = {keys} if not callable(keys) else None
            x, z = centroid_blocks(hist, wcx, wcz, r, feat or {keys})
            for g in grp:
                if (g["x"] - x) ** 2 + (g["z"] - z) ** 2 < d2:
                    g["w"].append((wcx, wcz, h))
                    break
            else:
                grp.append({"x": x, "z": z, "w": [(wcx, wcz, h)]})
        return label, T, grp

    def report(label, T, grp, want):
        tp = [g for g in grp if near(g["x"], g["z"], want)]
        fp = [g for g in grp if not near(g["x"], g["z"], want)]
        # 漏检：真值建筑 200 内没有任何报出组
        covered = 0
        for px, pz in truth.get(want, ()):
            if any((g["x"] - px) ** 2 + (g["z"] - pz) ** 2 <= 200 ** 2 for g in grp):
                covered += 1
        n = len(truth.get(want, ()))
        print("  %-38s T=%-4d 报 %3d  真 %3d  误 %2d  漏 %d/%d"
              % (label, T, len(grp), len(tp), len(fp), n - covered, n))
        return fp

    # ---- 1) 巫师 / 白金：独占 id 复核 ----
    print()
    print("=" * 90)
    print("1) 独占 id 阈值复核")
    print("=" * 90)
    for t in (10, 20, 50, 100):
        report("pbricks => 巫师", t, scan("", PB, t)[2], "巫师的圣修所")
    for t in (1, 3, 5, 10, 35):
        report("infested => 白金", t, scan("", INF, t)[2], "白金星殿")
    print()

    # ---- 2) 武士候选 id 的可分带 ----
    print("=" * 90)
    print("2) 武士候选 id：目标窗口最小值 vs 非目标窗口最大值")
    print("=" * 90)
    sam = [w for w in wins if near(0, 0, "武士的修行地") is None]  # placeholder
    # 直接按真值位置给窗口贴标签：窗口重心 200 内有武士真值 => 武士窗口
    tw = {"武士的修行地": [], "巫师的圣修所": [], "白金星殿": [], "其他": []}
    for wcx, wcz, h in wins:
        x, z = wcx * 16 + 8, wcz * 16 + 8
        lab = "其他"
        for t in ("武士的修行地", "巫师的圣修所", "白金星殿"):
            if any((px - x) ** 2 + (pz - z) ** 2 <= 200 ** 2 for px, pz in truth[t]):
                lab = t
                break
        tw[lab].append(h)
    for key in (STAIRS, GILD, PB, INF, M + "end_stone_bricks", M + "end_stone_brick_wall"):
        row = []
        for lab in ("武士的修行地", "巫师的圣修所", "白金星殿", "其他"):
            vals = [h.get(key, 0) for h in tw[lab]]
            nz = [v for v in vals if v]
            row.append("%s: max=%-4d 含id窗口=%d/%d"
                       % (lab[:2], max(vals) if vals else 0, len(nz), len(vals)))
        print("  %-34s %s" % (key.replace(M, ""), "  |  ".join(row)))
    # 武士窗口里 end_brick 家族与黑石系的分布
    eb = sigs.groups["end_brick"]
    print()
    print("  武士窗口 @end_brick 分布：", sorted(
        (sum(h.get(k, 0) for k in eb) for h in tw["武士的修行地"]))[:50])
    print("  其他窗口 @end_brick >=30 的主料（防紫珀殿/幽匿殿串类，前 8 个）：")
    others = []
    for h in tw["其他"]:
        if sum(h.get(k, 0) for k in eb) >= 30:
            others.append(h)
    others.sort(key=lambda h: -sum(v for k, v in h.items() if k in eb))
    for h in others[:8]:
        top = ", ".join("%s=%d" % (k.replace(M, ""), v) for k, v in h.most_common(4))
        print("      end_brick=%-4d %s"
              % (sum(h.get(k, 0) for k in eb), top))
    print()

    # ---- 3) 武士组合判据扫描 ----
    print("=" * 90)
    print("3) 武士组合判据扫描（anchors=@end_brick>=30 的前提下，any 走 OR）")
    print("=" * 90)

    def sam_rule(h, stair_t, gild_t):
        return (sum(h.get(k, 0) for k in eb) >= 30
                and (h.get(STAIRS, 0) >= stair_t or h.get(GILD, 0) >= gild_t))

    for st, gd in ((1, 1), (1, 10), (2, 10), (2, 15), (3, 15), (2, 20), (3, 20), (1, 20)):
        val = lambda h, st=st, gd=gd: 1 if sam_rule(h, st, gd) else 0
        label, T, grp = scan("stairs>=%d|gild>=%d" % (st, gd), val, 1)
        # scan 的 feat=None 分支要用 keys，绕一下：手动分组
        cand = [w for w in wins if sam_rule(w[2], st, gd)]
        grp = []
        for wcx, wcz, h in sorted(cand, key=lambda w: -sum(v for k, v in w[2].items() if k in eb)):
            x, z = centroid_blocks(hist, wcx, wcz, r, set(eb))
            for g in grp:
                if (g["x"] - x) ** 2 + (g["z"] - z) ** 2 < d2:
                    g["w"].append(h)
                    break
            else:
                grp.append({"x": x, "z": z, "w": [h]})
        report("@end_brick>=30 & stairs>=%d|gild>=%d" % (st, gd), 1, grp, "武士的修行地")
    print()

    # ---- 4) 无 end_brick 前提的纯黑石系判据（对照）----
    print("=" * 90)
    print("4) 纯黑石系判据（无 @end_brick 前提，对照用）")
    print("=" * 90)
    for st in (1, 2, 3, 5):
        cand = [w for w in wins if w[2].get(STAIRS, 0) >= st]
        grp = []
        for wcx, wcz, h in sorted(cand, key=lambda w: -w[2].get(STAIRS, 0)):
            x, z = centroid_blocks(hist, wcx, wcz, r, {STAIRS})
            for g in grp:
                if (g["x"] - x) ** 2 + (g["z"] - z) ** 2 < d2:
                    g["w"].append(h)
                    break
            else:
                grp.append({"x": x, "z": z, "w": [h]})
        report("blackstone_stairs >= %d" % st, st, grp, "武士的修行地")
    for gd in (5, 10, 15, 20, 30):
        cand = [w for w in wins if w[2].get(GILD, 0) >= gd]
        grp = []
        for wcx, wcz, h in sorted(cand, key=lambda w: -w[2].get(GILD, 0)):
            x, z = centroid_blocks(hist, wcx, wcz, r, {GILD})
            for g in grp:
                if (g["x"] - x) ** 2 + (g["z"] - z) ** 2 < d2:
                    g["w"].append(h)
                    break
            else:
                grp.append({"x": x, "z": z, "w": [h]})
        report("gilded_blackstone >= %d" % gd, gd, grp, "武士的修行地")


if __name__ == "__main__":
    main()
