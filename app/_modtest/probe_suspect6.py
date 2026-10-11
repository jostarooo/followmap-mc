# -*- coding: utf-8 -*-
"""最终验证：可疑点是不是「半座巫师」。

方法：对 15 座真巫师，把各自的用料按**东西两半**分开统计，看 blackstone /
polished_blackstone 是不是偏在某一侧；再把真巫师的**东半**与可疑点的可见部分
对比（同为一半时用料配比应一致）。若一致，则「加载边界截断」假设成立，
现有判据等玩家补齐西侧 chunk 后自然会报，无需改判据。
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
WATCH = ["polished_blackstone_bricks", "blackstone", "cracked_polished_blackstone_bricks",
         "polished_blackstone", "soul_soil", "deepslate_bricks", "netherrack",
         "polished_blackstone_brick_stairs", "basalt", "warped_nylium"]
WIZ_PEAKS = [(1483, -2446), (2836, -3111), (3038, -2625), (270, 3008), (1650, -2447),
             (2760, 3073), (2777, 3077), (3041, 2862), (334, 3008), (504, -2424),
             (638, 3007), (1190, -3087), (1291, -2446), (1384, -2445), (1440, 3021)]
SUSPECT_PEAK = (286, -2936)


def load():
    with open(CACHE, "rb") as fh:
        return pickle.load(fh)


def blob_of(hist, seed, mat):
    """seed 周围含 mat 的连通片。"""
    cells = set()
    stack = [seed]
    seen = {seed}
    while stack:
        cx, cz = stack.pop()
        if hist.get((cx, cz), {}).get("minecraft:" + mat):
            cells.add((cx, cz))
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    nb = (cx + dx, cz + dz)
                    if nb not in seen and hist.get(nb, {}).get("minecraft:" + mat):
                        seen.add(nb)
                        stack.append(nb)
    return cells


def split_ew(cells, hist):
    """按片的中线分东西两半，返回 (东, 西) 两个 Counter。"""
    xs = sorted(c[0] for c in cells)
    mid = (xs[0] + xs[-1]) / 2.0
    east, west = Counter(), Counter()
    for cx, cz in cells:
        c = hist.get((cx, cz), Counter())
        (east if cx + 0.5 > mid else west).update(c)
    return east, west, mid


def fmt(h):
    return ", ".join("%s=%d" % (k.replace("minecraft:", ""), v)
                     for k, v in h.most_common(8))


def main():
    hist = load()
    print("=" * 100)
    print("真巫师按东西中线对半分后的用料（前 8 项）：")
    print("=" * 100)
    for px, pz in WIZ_PEAKS:
        cells = blob_of(hist, (px, pz), "polished_blackstone_bricks")
        east, west, mid = split_ew(cells, hist)
        print("巫师 (%5d,%5d)  blob=%2d chunk  中线x=%.1f" % (px, pz, len(cells), mid))
        print("    东半: %s" % fmt(east))
        print("    西半: %s" % fmt(west))
    print()

    # 可疑点可见部分 vs 真巫师东半的配比
    print("=" * 100)
    print("配比对比（各材料占「黑石砖家族+黑石+灵魂沙」合计的份额）：")
    print("=" * 100)
    sus = Counter()
    for cx in range(285, 290):
        for cz in range(-2939, -2932):
            c = hist.get((cx, cz))
            if c:
                sus.update(c)
    key = ["minecraft:polished_blackstone_bricks", "minecraft:blackstone",
           "minecraft:cracked_polished_blackstone_bricks", "minecraft:polished_blackstone",
           "minecraft:soul_soil"]
    sus_tot = sum(sus.get(k, 0) for k in key)
    print("可疑点可见部分: " + "  ".join(
        "%s=%.2f" % (k.replace("minecraft:", ""), sus.get(k, 0) / sus_tot) for k in key))
    for px, pz in WIZ_PEAKS[:6]:
        cells = blob_of(hist, (px, pz), "polished_blackstone_bricks")
        east, west, _mid = split_ew(cells, hist)
        for tag, half in (("东半", east), ("西半", west)):
            t = sum(half.get(k, 0) for k in key)
            if not t:
                continue
            print("巫师(%5d,%5d)%s: " % (px, pz, tag) + "  ".join(
                "%s=%.2f" % (k.replace("minecraft:", ""), half.get(k, 0) / t) for k in key))


if __name__ == "__main__":
    main()
