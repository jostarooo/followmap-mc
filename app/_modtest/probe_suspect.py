# -*- coding: utf-8 -*-
"""深挖可疑窗口 (4586,-46944)。

背景：probe_blockid_rule2.py 里把「窗口内 polished_blackstone_bricks >= 20 就报巫师」
当成判据跑，报出 38 座，其中 37 座和现有完整判据的命中重合，只有 1 座
（重心约 (4586,-46944)，soul_soil=175 + pbricks=109）距离最近的真巫师 917 方块。

要回答三个问题：
  1) 它到底是什么材料构成的？（窗口直方图全量打印）
  2) 现有完整判据为什么没判它？（逐条 anchors / ratios / any / purity 的实际值）
  3) 空间上它是不是某座大巫师的**边缘窗口**？真巫师重心在 917 方块外，但建筑的
     边缘可能伸得更远 —— 列周围 +-12 chunk 内含 pbricks 的 chunk 分布看连续性。

用法：
    python _modtest/probe_suspect.py
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
from test_ruins import REF, _cos, _truth_of                     # noqa: E402

DIM = "minecraft:the_end"
ROOT = os.path.join(os.path.expanduser("~"), ".coordbridge")
CACHE = os.path.join(os.environ.get("TEMP", "/tmp"), "_probe_blockid_chunks.pkl")

SUSPECT = (4586, -46944)
PB = "minecraft:polished_blackstone_bricks"


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


def win_hist(hist, wcx, wcz, r):
    h = Counter()
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            c = hist.get((wcx + dx, wcz + dz))
            if c:
                h.update(c)
    return h


def centroid(hist, wcx, wcz, r, feat):
    xs, zs = [], []
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            c = hist.get((wcx + dx, wcz + dz))
            if not c:
                continue
            n = sum(v for k, v in c.items() if k in feat)
            if n:
                xs += [wcx + dx] * n
                zs += [wcz + dz] * n
    if not xs:
        return wcx * 16 + 8, wcz * 16 + 8
    return int(sum(xs) / len(xs) * 16 + 8), int(sum(zs) / len(zs) * 16 + 8)


def short(k):
    return k.replace("minecraft:", "")


def main():
    sigs = Signatures()
    hist = load()
    print("已加载 %d chunk" % len(hist))
    r = sigs.window // 2

    # ---------- 1) 现有判据的全部命中（当作真值位置） ----------
    wins = []
    truth = {}
    for c0x, c0z in sorted({(cx // 2, cz // 2) for cx, cz in hist}):
        wcx, wcz = c0x * 2, c0z * 2
        h = win_hist(hist, wcx, wcz, r)
        if sum(h.values()) < 60:
            continue
        wins.append((wcx, wcz, h))
        got = sigs.classify(h)
        if got:
            x, z = centroid(hist, wcx, wcz, r, sigs._sets[got[0]])
            truth.setdefault(got[0], []).append((x, z))
    print("现有判据命中：%s"
          % "  ".join("%s %d" % (t, len(v)) for t, v in truth.items()))
    print()

    # ---------- 2) 定位可疑窗口：pbricks>=20 的窗口里，离真巫师最远的那个 ----------
    wiz = truth.get("巫师的圣修所", [])
    cand = []
    for wcx, wcz, h in wins:
        if h.get(PB, 0) < 20:
            continue
        x, z = centroid(hist, wcx, wcz, r, {PB})
        d = min(((x - px) ** 2 + (z - pz) ** 2) ** 0.5 for px, pz in wiz) if wiz else 1e9
        cand.append((d, wcx, wcz, h, x, z))
    cand.sort(key=lambda t: -t[0])
    print("=" * 88)
    print("pbricks>=20 的窗口共 %d 个，按「到最近真巫师的距离」降序，前 5 个：" % len(cand))
    print("=" * 88)
    for d, wcx, wcz, h, x, z in cand[:5]:
        print("  (%7d,%7d)  距真巫师 %7.0f 方块  pbricks=%-5d 窗口中心chunk=(%d,%d)"
              % (x, z, d, h.get(PB, 0), wcx, wcz))

    if not cand:
        return
    d0, wcx0, wcz0, h0, x0, z0 = cand[0]
    print()
    print("=" * 88)
    print("可疑窗口：重心 (%d,%d)，窗口中心 chunk (%d,%d)，距最近真巫师 %.0f 方块"
          % (x0, z0, wcx0, wcz0, d0))
    print("=" * 88)
    tot = sum(h0.values())
    s = sigs._sets["巫师的圣修所"]
    hit = sum(v for k, v in h0.items() if k in s)
    print("窗口内人造方块合计 %d，其中巫师用料 %d，纯度 %.3f" % (tot, hit, hit / tot))
    print()
    print("  全部用料（前 25 项）：")
    for k, v in h0.most_common(25):
        mark = "  <-巫师用料" if k in s else ""
        print("      %-42s %5d%s" % (short(k), v, mark))
    print()

    # ---------- 3) 现有判据为什么没判它 ----------
    print("  现有判据逐条核对（巫师的圣修所）：")
    ok, purity, det = sigs.passes("巫师的圣修所", h0)
    meta = sigs.types["巫师的圣修所"]
    for k, need in meta["anchors"].items():
        got = sigs._anchor(k, h0)
        print("      anchor %-44s 实测 %-7d 需要 %-7d %s"
              % (short(k), got, need, "OK" if got >= need else "**不达标**"))
    for k, need in meta.get("ratios", {}).items():
        got = sigs._anchor(k, h0)
        print("      ratio  %-44s 实测 %-7d 需要 %-7d" % (short(k), got, need))
    for i, g in enumerate(meta["any"], 1):
        vals = {k: sigs._cond(k, h0, hit) for k in g}
        good = all(vals[k] >= v for k, v in g.items())
        txt = ", ".join("%s=%s" % (short(k), ("%.3f" % v) if k.startswith("%") else int(v))
                        for k, v in vals.items())
        print("      any[%d] 需要 %-38s 实测 %-30s %s"
              % (i, ", ".join("%s>=%s" % (short(k), v) for k, v in g.items()),
                 txt, "OK" if good else "不达标"))
    print("      purity  实测 %.3f  需要 %.2f  %s"
          % (purity, sigs.min_purity, "OK" if purity >= sigs.min_purity else "**不达标**"))
    print("      => 结论：%s" % ("判为巫师" if ok else "未判为巫师"))
    print()

    # ---------- 4) 独立余弦真值：它到底像不像巫师 ----------
    print("  独立真值（余弦相似度，参考向量=真实实例实测）：")
    for name, ref in REF.items():
        print("      %-8s cos=%.3f" % (name, _cos(h0, ref)))
    nm, cv = _truth_of(h0)
    print("      => 真值判定：%s（cos=%.3f，过线需 >=0.90）" % (nm or "都不像", cv))
    print()

    # ---------- 5) 空间分布：周围含 pbricks 的 chunk ------------------------------
    cx0, cz0 = x0 // 16, z0 // 16
    R = 14
    print("  周围 chunk 的 pbricks 分布（行=chunk x，列=chunk z，中心=%d,%d）："
          % (cx0, cz0))
    print("      " + "".join("%4d" % (cz0 + dz) for dz in range(-R, R + 1)))
    for dx in range(-R, R + 1):
        row = "%6d" % (cx0 + dx)
        for dz in range(-R, R + 1):
            c = hist.get((cx0 + dx, cz0 + dz))
            v = c.get(PB, 0) if c else 0
            row += "%4s" % (v if v else ".")
        print(row)

    # ---------- 6) 含 pbricks 的 chunk 在空间上连成几片 ---------------------------
    print()
    print("  含 pbricks 的 chunk，按连通性聚成片（8 邻域），列出前 8 片：")
    cells = {k for k, c in hist.items() if c.get(PB, 0) > 0}
    seen = set()
    blobs = []
    for c0 in sorted(cells):
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
                    if nb in cells and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
        blobs.append(blob)
    blobs.sort(key=lambda b: -len(b))
    for b in blobs[:8]:
        xs = [c[0] for c in b]
        zs = [c[1] for c in b]
        tot_pb = sum(hist[c].get(PB, 0) for c in b)
        print("      %3d 个 chunk, x %d..%d, z %d..%d, pbricks 合计 %d"
              % (len(b), min(xs), max(xs), min(zs), max(zs), tot_pb))
    print("      （共 %d 片）" % len(blobs))

    # ---------- 7) 可疑点所在那一片，换几个窗口大小再判一次 ------------------------
    print()
    print("  把可疑点单独拿出来，换窗口尺寸再看（判据不变）：")
    cx0c, cz0c = x0 // 16, z0 // 16
    for w in (3, 5, 7, 9):
        rr = w // 2
        h = win_hist(hist, cx0c, cz0c, rr)
        if sum(h.values()) < 60:
            print("      window=%d  数据不足" % w)
            continue
        got = sigs.classify(h)
        hh = sum(v for k, v in h.items() if k in s)
        print("      window=%d  总%d 巫师用料%d 纯度%.3f  ->  %s"
              % (w, sum(h.values()), hh, hh / sum(h.values()),
                 got[0] if got else "未命中"))

    # ---------- 8) 真巫师 vs 可疑点的用料对比 ------------------------------------
    print()
    print("  对照：最近的一座真巫师的窗口用料（前 12 项）：")
    if wiz:
        px, pz = min(wiz, key=lambda p: (p[0] - x0) ** 2 + (p[1] - z0) ** 2)
        hw = win_hist(hist, px // 16, pz // 16, r)
        hw_tot = sum(hw.values())
        hw_hit = sum(v for k, v in hw.items() if k in s)
        print("      真巫师 (%d,%d) 总%d 纯度%.3f" % (px, pz, hw_tot, hw_hit / hw_tot))
        for k, v in hw.most_common(12):
            print("          %-42s %5d" % (short(k), v))


if __name__ == "__main__":
    main()
