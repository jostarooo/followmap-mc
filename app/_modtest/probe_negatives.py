# -*- coding: utf-8 -*-
"""把 E 段两个巫师负例（黑石要塞 / 黑石小屋）在真机 chunk 数据里搜出来，
看它们的真实位置、离最近真巫师多远、周围窗口的全貌 —— 判断它们到底是
独立建筑（v5 判据必须挡住）还是某座真巫师的边缘窗口（dedupe 会压掉）。"""
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
M = "minecraft:"


def load():
    with open(CACHE, "rb") as fh:
        return pickle.load(fh)


def main():
    sigs = Signatures()
    hist = load()
    r = sigs.window // 2
    tot = {k: sum(v.values()) for k, v in hist.items()}

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
            truth.setdefault(got[0], []).append((wcx * 16 + 8, wcz * 16 + 8))
    wiz = truth.get("巫师的圣修所", [])
    print("窗口 %d，现有判据巫师命中 %d" % (len(wins), len(wiz)))

    def nearest_wiz(x, z):
        return min(((px - x) ** 2 + (pz - z) ** 2) ** 0.5 for px, pz in wiz)

    print()
    print("=" * 96)
    print("黑石要塞画像：pbricks 130~190 且 blackstone 150~220 且 soul_soil 270~360")
    print("=" * 96)
    for wcx, wcz, h in wins:
        if (130 <= h.get(M + "polished_blackstone_bricks", 0) <= 190
                and 150 <= h.get(M + "blackstone", 0) <= 220
                and 270 <= h.get(M + "soul_soil", 0) <= 360):
            x, z = wcx * 16 + 8, wcz * 16 + 8
            d = nearest_wiz(x, z)
            print("  (%7d,%7d) 距最近巫师 %6.0f  cos=%.3f  pbricks=%d blackstone=%d soul_soil=%d"
                  % (x, z, d, _cos(h, REF["巫师的圣修所"]),
                     h.get(M + "polished_blackstone_bricks", 0),
                     h.get(M + "blackstone", 0), h.get(M + "soul_soil", 0)))

    print()
    print("=" * 96)
    print("黑石小屋画像：pbricks 40~100 且 blackstone 170~260 且 polished_blackstone 40~90")
    print("=" * 96)
    for wcx, wcz, h in wins:
        if (40 <= h.get(M + "polished_blackstone_bricks", 0) <= 100
                and 170 <= h.get(M + "blackstone", 0) <= 260
                and 40 <= h.get(M + "polished_blackstone", 0) <= 90):
            x, z = wcx * 16 + 8, wcz * 16 + 8
            d = nearest_wiz(x, z)
            print("  (%7d,%7d) 距最近巫师 %6.0f  cos=%.3f  pbricks=%d blackstone=%d polished=%d"
                  % (x, z, d, _cos(h, REF["巫师的圣修所"]),
                     h.get(M + "polished_blackstone_bricks", 0),
                     h.get(M + "blackstone", 0),
                     h.get(M + "polished_blackstone", 0)))

    # 要塞窗口周围的完整材质（取离画像最近的一个）
    print()
    print("=" * 96)
    print("最像「要塞」的窗口，其 5x5 窗口全量用料：")
    print("=" * 96)
    best, bh = None, None
    for wcx, wcz, h in wins:
        if (130 <= h.get(M + "polished_blackstone_bricks", 0) <= 190
                and 150 <= h.get(M + "blackstone", 0) <= 220
                and 270 <= h.get(M + "soul_soil", 0) <= 360):
            if best is None or h.get(M + "soul_soil", 0) > bh.get(M + "soul_soil", 0):
                best, bh = (wcx, wcz), h
    if best:
        x, z = best[0] * 16 + 8, best[1] * 16 + 8
        print("  窗口 (%d,%d)，距最近巫师 %.0f 方块" % (x, z, nearest_wiz(x, z)))
        for k, v in bh.most_common(15):
            print("      %-44s %5d" % (k.replace(M, ""), v))


if __name__ == "__main__":
    main()
