# -*- coding: utf-8 -*-
"""量分布：为「被地形淹没」重定判据提供依据。

对真机数据里每个 5x5 窗口，先按**独立余弦**分类（cos>=0.90 才算真值），
再把各候选量按真值类型分组打印分布，看哪条判据能把真值与噪声分开。
用法：python _modtest/_dist.py [维度]
"""
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from followmap.ruins import Signatures  # noqa: E402
import _nearmiss as NM  # noqa: E402  复用 load_hist / cos / truth_of


def pct(vals, p):
    if not vals:
        return 0
    k = max(0, min(len(vals) - 1, int(round((len(vals) - 1) * p))))
    return vals[k]


def show(title, groups):
    """groups: {label: [values]}"""
    print("  %-34s %6s %6s %6s %6s %6s" % (title, "n", "min", "p25", "p50", "max"))
    for lab, v in groups.items():
        v = sorted(v)
        if not v:
            continue
        print("    %-32s %6d %6d %6d %6d %6d"
              % (lab, len(v), v[0], pct(v, 0.25), pct(v, 0.5), v[-1]))


def main():
    dim = sys.argv[1] if len(sys.argv) > 1 else "minecraft:the_end"
    sigs = Signatures()
    hist = NM.load_hist(dim)
    r = sigs.window // 2
    cells = sorted({(cx // 2 * 2, cz // 2 * 2) for (cx, cz) in hist})

    W = "巫师的圣修所"
    wsig = {
        "pbrick": ("minecraft:polished_blackstone_bricks",),
        "pbrick_any": ("minecraft:polished_blackstone_bricks",
                       "minecraft:polished_blackstone_brick_stairs",
                       "minecraft:polished_blackstone_brick_slab",
                       "minecraft:polished_blackstone_brick_wall",
                       "minecraft:cracked_polished_blackstone_bricks"),
        "blackstone": ("minecraft:blackstone",),
        "cracked": ("minecraft:cracked_polished_blackstone_bricks",),
        "deepslate_bricks": ("minecraft:deepslate_bricks",),
        "deepslate_any": ("minecraft:deepslate_bricks", "minecraft:deepslate_tiles",
                          "minecraft:cracked_deepslate_tiles",
                          "minecraft:cracked_deepslate_bricks"),
    }

    groups = {}
    noise = {}
    n_truth = 0
    noise_top = []
    for wcx, wcz in cells:
        h = NM.win(hist, wcx, wcz, r)
        if sum(h.values()) < 60:
            continue
        tn, tc = NM.truth_of(h)
        if tn != W:
            if tn is None and tc < 0.70:      # 明显不是三类的窗口 = 噪声
                hit_v = sum(v for k2, v in h.items() if k2 in sigs._sets[W])
                tot_v = sum(h.values())
                for k, names in wsig.items():
                    noise.setdefault(k, []).append(sum(h.get(n, 0) for n in names))
                noise.setdefault("hit", []).append(hit_v)
                noise.setdefault("total", []).append(tot_v)
                noise.setdefault("purity", []).append(round(100.0 * hit_v / tot_v))
                noise_top.append((hit_v / tot_v, tc, wcx * 16 + 8, wcz * 16 + 8, h))
            continue
        n_truth += 1
        for k, names in wsig.items():
            groups.setdefault(k, []).append(sum(h.get(n, 0) for n in names))
        groups.setdefault("hit", []).append(
            sum(v for k2, v in h.items() if k2 in sigs._sets[W]))
        groups.setdefault("total", []).append(sum(h.values()))
        groups.setdefault("purity", []).append(
            round(100 * sum(v for k2, v in h.items() if k2 in sigs._sets[W])
                  / sum(h.values())))

    print("巫师真值窗口 %d 个；明显非三类窗口 %d 个" % (n_truth, len(noise.get("hit", []))))
    print()
    print("真值（cos>=0.90 判为巫师）:")
    show("量", groups)
    print()
    print("噪声（三类都不是，且最高余弦<0.70）:")
    show("量", noise)
    print()
    print("噪声里纯度最高的 8 个窗口（看它们到底像什么）:")
    for pu, tc, x, z, h in sorted(noise_top, reverse=True)[:8]:
        top = " ".join("%s=%d" % (k.replace("minecraft:", ""), v)
                       for k, v in sorted(h.items(), key=lambda kv: -kv[1])[:7])
        print("   纯=%.2f 余弦=%.2f @(%7d,%7d)  %s" % (pu, tc, x, z, top))


if __name__ == "__main__":
    main()
