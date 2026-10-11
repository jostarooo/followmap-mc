# -*- coding: utf-8 -*-
"""定位某点附近的全部候选窗口：直方图 + 独立余弦 + 判据结果 + 卡在哪一条。

不猜。把「用户看到的建筑」和「分类器的判定」放在同一张表里。
用法：python _modtest/_probe_loc.py <cx> <cz> [半径格]
"""
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from followmap.ruins import Signatures  # noqa: E402
from _nearmiss import REF, cos, load_hist, win  # noqa: E402

SHORT = {}
for _g, _ms in {"NAT": []}.items():
    pass


def short(k):
    return k.replace("minecraft:", "")


def main():
    cx = int(sys.argv[1])
    cz = int(sys.argv[2])
    rad = int(sys.argv[3]) if len(sys.argv) > 3 else 500
    sigs = Signatures()
    hist = load_hist("minecraft:the_end")
    r = sigs.window // 2

    c0 = (cx // 16, cz // 16)
    lo, hi = rad // 16 + r + 1, rad // 16 + r + 1
    cells = sorted({(a // 2 * 2, b // 2 * 2) for (a, b) in hist
                    if abs(a - c0[0]) <= hi and abs(b - c0[1]) <= lo})
    print("附近候选窗口 %d 个（半径 %d 格，窗口 %dx%d 区块）"
          % (len(cells), rad, sigs.window, sigs.window))

    rows = []
    for wcx, wcz in cells:
        h = win(hist, wcx, wcz, r)
        tot = sum(h.values())
        if tot < 60:
            continue
        best, bn = 0.0, None
        for nm, ref in REF.items():
            c = cos(h, ref)
            if c > best:
                best, bn = c, nm
        got = sigs.classify(h)
        rows.append((best, bn, tot, wcx * 16 + 8, wcz * 16 + 8, got, h))

    rows.sort(reverse=True, key=lambda t: t[0])
    print("%-9s %6s %6s %-14s %-22s %s"
          % ("余弦", "归属", "人造数", "位置", "判据结果", "前 6 方块"))
    for best, bn, tot, x, z, got, h in rows[:40]:
        top = " ".join("%s=%d" % (short(k), v)
                       for k, v in sorted(h.items(), key=lambda kv: -kv[1])[:6])
        if got:
            g = "命中 %s (纯度%.2f)" % (got[0], got[1])
        else:
            # 逐类给出卡住的那一条
            why = []
            for nm in sigs.types:
                ok, pur, det = sigs.passes(nm, h)
                if ok:
                    continue
                meta = sigs.types[nm]
                lack = []
                for k, need in meta["anchors"].items():
                    v = sigs._anchor(k, h)
                    if v < need:
                        lack.append("%s %d<%d" % (short(k), v, need))
                if not lack:
                    for k, need in meta.get("ratios", {}).items():
                        v = sigs._anchor(k, h) / (sum(sigs._anchor(kk, h) for kk in []) or 1)
                        v = sigs._anchor(k, h)
                    for k, need in meta.get("ratios", {}).items():
                        v = sigs._anchor(k, h)
                        hit = sum(val for kk, val in h.items() if kk in sigs._sets[nm])
                        rr = v / hit if hit else 0
                        if rr < need:
                            lack.append("%s %.3f<%.2f" % (short(k), rr, need))
                if not lack and meta["any"]:
                    bestg = None
                    for g in meta["any"]:
                        gd = {k: sigs._cond(k, h, sum(val for kk, val in h.items()
                                                      if kk in sigs._sets[nm]))
                              for k in g}
                        miss = max((v - gd[k], k) for k, v in g.items())
                        if bestg is None or miss < bestg:
                            bestg = miss
                    if bestg[0] > 0:
                        lack.append("any差 %s %.2f<%.2f"
                                    % (short(bestg[1]), gd[bestg[1]], g[bestg[1]]))
                if not lack:
                    lack.append("纯度 %.2f<%.2f" % (pur, sigs.min_purity))
                why.append("%s:%s" % (nm, ";".join(lack)))
            g = " || ".join(why)
        print("%-9.3f %-6s %6d (%6d,%6d) %-22s %s"
              % (best, bn or "-", tot, x, z, (g[:22]), top))
        if not got:
            print("        %s" % g[:150])


if __name__ == "__main__":
    main()
