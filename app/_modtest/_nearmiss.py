# -*- coding: utf-8 -*-
"""普查：真机数据里「独立余弦明确是某类、但当前判据判否」的窗口。

目的：定位用户报的「巫师被地形淹没 → 漏检」。不猜，直接把卡住的那条判据列出来。
用法：python _modtest/_nearmiss.py [在哪个维度目录下扫，默认 minecraft_the_end]
"""
import os
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from followmap.ruins import Signatures, parse_chunk, safe_dim  # noqa: E402

ROOT = r"C:\Users\jostaro\.coordbridge"

# 与 test_ruins.py 完全相同的独立参考向量（与分类器解耦的真值来源）
REF = {
    "白金星殿": {
        "minecraft:stone_brick_stairs": 97,
        "minecraft:infested_stone_bricks": 93,
        "minecraft:mossy_cobblestone_stairs": 81,
        "minecraft:mossy_stone_brick_stairs": 40,
        "minecraft:smooth_stone_slab": 30,
        "minecraft:smooth_quartz_stairs": 27,
        "minecraft:red_wool": 18,
    },
    "武士的修行地": {
        "minecraft:end_stone_bricks": 380,
        "minecraft:netherrack": 370,
        "minecraft:polished_basalt": 95,
        "minecraft:crimson_planks": 68,
    },
    "巫师的圣修所": {
        "minecraft:polished_blackstone_bricks": 440,
        "minecraft:blackstone": 210,
        "minecraft:cracked_polished_blackstone_bricks": 115,
        "minecraft:deepslate_bricks": 65,
    },
}
COS_TRUTH = 0.90


def cos(hist, ref):
    num = sum(hist.get(k, 0) * v for k, v in ref.items())
    if not num:
        return 0.0
    na = sum(v * v for v in hist.values()) ** 0.5
    nb = sum(v * v for v in ref.values()) ** 0.5
    return num / (na * nb) if na and nb else 0.0


def truth_of(hist):
    best, bn = 0.0, None
    for name, ref in REF.items():
        c = cos(hist, ref)
        if c > best:
            best, bn = c, name
    return (bn, best) if best >= COS_TRUTH else (None, best)


def load_hist(dim):
    """把该维度全部已落盘 chunk 读成 {(cx,cz): Counter}。

    结果缓存到 `_hist_<safe>.pkl`：解析 3 万个文件要 40 秒，调参时要反复用。
    想强制重读就删掉缓存文件。
    """
    import pickle
    cache = os.path.join(HERE, "_hist_%s.pkl" % safe_dim(dim).replace(":", "_"))
    if os.path.exists(cache):
        with open(cache, "rb") as fh:
            hist = pickle.load(fh)
        print("缓存命中：%d 个 chunk（%s）" % (len(hist), os.path.basename(cache)))
        return hist
    base = os.path.join(ROOT, "chunks", safe_dim(dim))
    hist = {}
    n = 0
    t0 = time.time()
    for rx in sorted(os.listdir(base)):
        if not rx.startswith("r"):
            continue
        for rz in sorted(os.listdir(os.path.join(base, rx))):
            d = os.path.join(base, rx, rz)
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                if not f.endswith(".bin"):
                    continue
                a, _, b = f[:-4].partition("_")
                try:
                    cx, cz = int(a), int(b)
                except ValueError:
                    continue
                h = parse_chunk(os.path.join(d, f))
                if h:
                    hist[(cx, cz)] = h
                    n += 1
    print("读入 %d 个 chunk，用时 %.1fs" % (n, time.time() - t0))
    with open(cache, "wb") as fh:
        pickle.dump(hist, fh)
    return hist


def win(hist, ccx, ccz, r):
    out = Counter()
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            c = hist.get((ccx + dx, ccz + dz))
            if c:
                out.update(c)
    return out


def main():
    dim = sys.argv[1] if len(sys.argv) > 1 else "minecraft:the_end"
    sigs = Signatures()
    hist = load_hist(dim)
    r = sigs.window // 2

    cells = sorted({(cx // 2 * 2, cz // 2 * 2) for (cx, cz) in hist})
    print("候选窗口 %d 个（%dx%d 区块窗口）" % (len(cells), sigs.window, sigs.window))

    hit_by = Counter()
    miss_by = Counter()          # 漏检按「余弦归属类型」分
    reasons = {}                 # 漏检 -> Counter(卡住的判据)
    samples = []                 # 漏检样本（留给后面细看）

    t0 = time.time()
    for wcx, wcz in cells:
        h = win(hist, wcx, wcz, r)
        if sum(h.values()) < 60:
            continue
        got = sigs.classify(h)
        tn, tc = truth_of(h)
        if got:
            hit_by[got[0]] += 1
            continue
        if not tn:
            continue
        miss_by[tn] += 1
        ok, purity, details = sigs.passes(tn, h)
        meta = sigs.types[tn]
        # 是哪条锚点 / any / 纯度 卡住的？
        why = []
        for k, need in meta["anchors"].items():
            v = sigs._anchor(k, h)
            if v < need:
                why.append("%s %d<%d" % (k, v, need))
        if not why and meta["any"]:
            if not any(all(sigs._anchor(k, h) >= v for k, v in g.items())
                       for g in meta["any"]):
                best = None
                for g in meta["any"]:
                    gd = {k: sigs._anchor(k, h) for k in g}
                    lack = max((v - gd[k], k) for k, v in g.items())
                    if best is None or lack < best:
                        best = lack
                why.append("any组差 %s" % (best[1],))
        if not why:
            why.append("纯度 %.2f<%.2f" % (purity, sigs.min_purity))
        key = "; ".join(why)
        reasons.setdefault(key, Counter())[tn] += 1
        samples.append((tn, tc, purity, key, (wcx * 16 + 8, wcz * 16 + 8), h))

    print("扫描用时 %.1fs" % (time.time() - t0))
    print("=" * 78)
    print("命中: %s  合计 %d" % (dict(hit_by), sum(hit_by.values())))
    print("漏检（余弦>=0.90 但判否）: %s  合计 %d"
          % (dict(miss_by), sum(miss_by.values())))
    print("=" * 78)
    print("漏检原因 TOP（按出现次数）:")
    rows = sorted(((sum(c.values()), k, dict(c)) for k, c in reasons.items()),
                  reverse=True)
    for n, k, c in rows[:25]:
        print("  %4d  %-58s %s" % (n, k[:58], c))

    print()
    print("漏检样本（每个原因取前 2 个）:")
    seen = {}
    for tn, tc, purity, key, pos, h in sorted(samples, key=lambda s: -s[1]):
        if seen.get(key, 0) >= 2:
            continue
        seen[key] = seen.get(key, 0) + 1
        top = " ".join("%s=%d" % (k.replace("minecraft:", ""), v)
                       for k, v in sorted(h.items(), key=lambda kv: -kv[1])[:8])
        print("  %s cos=%.2f 纯=%.2f @(%d,%d)  卡: %s"
              % (tn, tc, purity, pos[0], pos[1], key))
        print("        %s" % top)

    # ---- 误报侧：判出来了，但独立余弦的**归属**是另一类（且余弦不低）----
    print()
    print("=" * 78)
    wrong = []
    suspicious = []
    for wcx, wcz in cells:
        h = win(hist, wcx, wcz, r)
        if sum(h.values()) < 60:
            continue
        got = sigs.classify(h)
        if not got:
            continue
        best, bn = 0.0, None
        for nm, ref in REF.items():
            c = cos(h, ref)
            if c > best:
                best, bn = c, nm
        if bn != got[0] and best >= 0.70:
            wrong.append((got[0], bn, best, (wcx * 16 + 8, wcz * 16 + 8)))
        elif best < 0.60:
            suspicious.append((got[0], bn, best, (wcx * 16 + 8, wcz * 16 + 8)))
    print("真误报（判为 X，独立余弦归属 Y 且 cos>=0.70）: %d 处" % len(wrong))
    for t, bn, c, pos in wrong[:10]:
        print("   判=%-8s 实属=%-8s cos=%.2f @(%d,%d)" % (t, bn, c, pos[0], pos[1]))
    print("可疑命中（对三类余弦都 <0.60，可能是真误报）: %d 处" % len(suspicious))
    for t, bn, c, pos in suspicious[:10]:
        print("   判=%-8s 最高余弦=%s(%.2f) @(%d,%d)" % (t, bn, c, pos[0], pos[1]))


if __name__ == "__main__":
    main()
