# -*- coding: utf-8 -*-
"""承接 _probe_blockid_rule.py：把「出现即判定」真正当成判据跑一遍，数误报。

问题：如果把判据简化成
    窗口内 <某个方块 id> >= T   =>  直接报出 <某类遗迹>
到底会报出多少座建筑？其中多少是真目标、多少是误报（紫珀殿/幽匿殿之类）？

真值口径：报出的建筑中心 200 方块内有没有被**现有完整判据**判为该类遗迹的命中。
没有 => 判为「误报」，并打印它的主材料（一眼就能看出它其实是哪类建筑）。
"""
import os
import pickle
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

from followmap.ruins import Signatures, safe_dim, parse_chunk   # noqa: E402

DIM = "minecraft:the_end"
ROOT = os.path.join(os.path.expanduser("~"), ".coordbridge")
CACHE = os.path.join(os.environ.get("TEMP", "/tmp"), "_probe_blockid_chunks.pkl")

CASES = [
    ("minecraft:polished_blackstone_bricks", "巫师的圣修所", [1, 20, 100, 138, 500, 1000]),
    ("minecraft:blackstone", "巫师的圣修所", [1, 20, 100, 250]),
    ("minecraft:infested_stone_bricks", "白金星殿", [1, 20, 35, 100, 500]),
    ("minecraft:stone_bricks", "白金星殿", [1, 20]),
]


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


def centroid_blocks(hist, cx, cz, r, featset):
    xs, zs = [], []
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            c = hist.get((cx + dx, cz + dz))
            if not c:
                continue
            hit = sum(v for k, v in c.items() if k in featset)
            if hit:
                xs += [cx + dx] * hit
                zs += [cz + dz] * hit
    if not xs:
        return cx * 16 + 8, cz * 16 + 8
    return int(sum(xs) / len(xs) * 16 + 8), int(sum(zs) / len(zs) * 16 + 8)


def main():
    sigs = Signatures()
    print("读取缓存…")
    t0 = time.perf_counter()
    hist = load()
    tot = {k: sum(v.values()) for k, v in hist.items()}
    print("  %d chunk（%.1fs）" % (len(hist), time.perf_counter() - t0))
    r = sigs.window // 2
    d2 = sigs.dedupe_blocks ** 2

    # 1) 现有完整判据的命中（当作「真值」的位置来源）
    truth = {}
    wins = []
    for c0x, c0z in sorted({(cx // 2, cz // 2) for cx, cz in hist}):
        wcx, wcz = c0x * 2, c0z * 2
        s = 0
        for dx in range(-r, r + 1):
            row = wcx + dx
            for dz in range(-r, r + 1):
                s += tot.get((row, wcz + dz), 0)
        if s < 60:
            continue
        h = Counter()
        for dx in range(-r, r + 1):
            row = wcx + dx
            for dz in range(-r, r + 1):
                c = hist.get((row, wcz + dz))
                if c:
                    h.update(c)
        if not h:
            continue
        wins.append((wcx, wcz, h))
        got = sigs.classify(h)
        if got:
            x, z = centroid_blocks(hist, wcx, wcz, r, sigs._sets[got[0]])
            truth.setdefault(got[0], []).append((x, z))
    print("  现有判据命中：%s" % "  ".join("%s %d" % (t, len(v)) for t, v in truth.items()))
    print("  判定窗口 %d 个" % len(wins))
    print()

    def near(x, z, t, rad=200.0):
        for px, pz in truth.get(t, ()):
            if (px - x) ** 2 + (pz - z) ** 2 <= rad * rad:
                return True
        return False

    for block, want, thresholds in CASES:
        print("=" * 84)
        print("判据：窗口内 %s >= T   =>  报 %s" % (block.replace("minecraft:", ""), want))
        print("=" * 84)
        for T in thresholds:
            cand = [(a, b, h) for a, b, h in wins if h.get(block, 0) >= T]
            # 用该方块做重心
            grp = []
            for wcx, wcz, h in sorted(cand, key=lambda x: -x[2].get(block, 0)):
                x, z = centroid_blocks(hist, wcx, wcz, r, {block})
                for g in grp:
                    if (g["x"] - x) ** 2 + (g["z"] - z) ** 2 < d2:
                        g["w"].append(h)
                        break
                else:
                    grp.append({"x": x, "z": z, "w": [h]})
            tp = [g for g in grp if near(g["x"], g["z"], want)]
            fp = [g for g in grp if not near(g["x"], g["z"], want)]
            print()
            print("  T=%-5d  报出 %d 座：真%s %d 座，误报 %d 座"
                  % (T, len(grp), want, len(tp), len(fp)))
            for g in fp[:6]:
                h = Counter()
                for hh in g["w"]:
                    h.update(hh)
                top = ", ".join("%s=%d" % (k.replace("minecraft:", ""), v)
                                for k, v in h.most_common(5))
                print("      误报 (%7d,%7d)  标记=%-5d  主料: %s"
                      % (g["x"], g["z"], h.get(block, 0), top))
            if len(fp) > 6:
                print("      …还有 %d 座" % (len(fp) - 6))
        print()

    print("=" * 84)
    print("对照：现有完整判据（锚点+可选组+纯度>=0.80）")
    print("=" * 84)
    print("  报出 %d 座（白金 %d / 武士 %d / 巫师 %d）"
          % (sum(len(v) for v in truth.values()), len(truth.get("白金星殿", ())),
             len(truth.get("武士的修行地", ())), len(truth.get("巫师的圣修所", ()))))


if __name__ == "__main__":
    main()
