# -*- coding: utf-8 -*-
"""新旧判据逐窗口对照（跑在 C 段同一批 Xaero region 上）。

C 段命中里巫师从 57 变 51，必须查清是「丢了真命中」还是「去重口径位移」。
本脚本直接把每个窗口按新旧两套判据各判一次，列出**旧过新不过**的那些窗口及其实得值。

用法：python _modtest/_ab_cmp.py
"""
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from followmap.ruins import Signatures, NATURAL  # noqa: E402
import xaero_region as XR  # noqa: E402

V = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14"
SRC = os.path.join(V, "XaeroWorldMap", "Multiplayer_mcfkcs.com", "DIM1", "mw$default")

OLD = {
    "白金星殿": {"anchors": {"minecraft:infested_stone_bricks": 55,
                             "@stone_brick": 120,
                             "minecraft:red_wool": 3},
                 "any": [{"@mossy": 18},
                         {"minecraft:smooth_stone_slab": 10,
                          "minecraft:smooth_quartz_stairs": 10}]},
    "武士的修行地": {"anchors": {"minecraft:netherrack": 60, "@end_brick": 45,
                                 "minecraft:polished_basalt": 8, "@crimson": 25}},
    "巫师的圣修所": {"anchors": {"minecraft:polished_blackstone_bricks": 140,
                                 "minecraft:blackstone": 55,
                                 "minecraft:cracked_polished_blackstone_bricks": 30,
                                 "minecraft:deepslate_bricks": 18}},
}


def judge(sigs, h, name, rule):
    meta = sigs.types[name]
    gran = sum(h.values())
    if gran < 60:
        return False
    tot = sum(v for k, v in h.items() if k in sigs._sets[name])
    if tot <= 0:
        return False
    for k, need in rule["anchors"].items():
        if sigs._anchor(k, h) < need:
            return False
    for k, need in rule.get("ratios", {}).items():
        if (sigs._anchor(k, h) / tot) < need:
            return False
    if rule.get("any"):
        if not any(all(sigs._anchor(k, h) >= v for k, v in g.items())
                   for g in rule["any"]):
            return False
    return tot / gran >= sigs.min_purity


def main():
    import random
    sigs = Signatures()
    allreg = []
    for f in os.listdir(SRC):
        if f.endswith(".zip"):
            a, _, b = f[:-4].partition("_")
            try:
                allreg.append((int(a), int(b)))
            except ValueError:
                pass
    random.seed(7)
    random.shuffle(allreg)
    regions = allreg[:140]

    hist = {}
    for rx, rz in regions:
        p = os.path.join(SRC, "%d_%d.zip" % (rx, rz))
        try:
            rd = XR.parse_region_file(p)
        except Exception:
            continue
        for (dx, dz), st in rd.blocks.items():
            nm = st.split("[")[0]
            if nm in NATURAL:
                continue
            key = (rx * 32 + dx // 16, rz * 32 + dz // 16)
            hist.setdefault(key, Counter())[nm] += 1

    r = sigs.window // 2
    cells = sorted({(cx // 2 * 2, cz // 2 * 2) for cx, cz in hist})
    print("region %d 个 / chunk %d 个 / 窗口 %d 个" % (len(regions), len(hist), len(cells)))

    lost = {t: [] for t in sigs.types}
    gained = {t: [] for t in sigs.types}
    for wcx, wcz in cells:
        h = Counter()
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                c = hist.get((wcx + dx, wcz + dz))
                if c:
                    h.update(c)
        if sum(h.values()) < 60:
            continue
        for t in sigs.types:
            o = judge(sigs, h, t, OLD[t])
            n = sigs.passes(t, h)[0]
            if o and not n:
                lost[t].append((wcx * 16 + 8, wcz * 16 + 8, h))
            elif n and not o:
                gained[t].append((wcx * 16 + 8, wcz * 16 + 8, h))

    for t in sigs.types:
        print()
        print("=== %s：旧过 / 新不过 %d 个；旧不过 / 新过 %d 个"
              % (t, len(lost[t]), len(gained[t])))
        for x, z, h in lost[t]:
            tot = sum(v for k, v in h.items() if k in sigs._sets[t])
            pb = h.get("minecraft:polished_blackstone_bricks", 0)
            print("   丢 (%7d,%7d) 该类型用料=%d 纯度=%.2f"
                  % (x, z, tot, tot / sum(h.values())))
            print("       主料前 6: %s"
                  % " ".join("%s=%d" % (k.replace("minecraft:", ""), v)
                             for k, v in sorted(h.items(), key=lambda kv: -kv[1])[:6]))
            # 是哪一条卡住的
            meta = sigs.types[t]
            why = []
            for k, need in meta["anchors"].items():
                if sigs._anchor(k, h) < need:
                    why.append("%s %d<%d" % (k.replace("minecraft:", ""),
                                             sigs._anchor(k, h), need))
            for k, need in meta.get("ratios", {}).items():
                rr = sigs._anchor(k, h) / tot if tot else 0
                if rr < need:
                    why.append("%%%s %.3f<%.2f" % (k.replace("minecraft:", ""), rr, need))
            print("       新判据卡在: %s" % ("; ".join(why) or "无（应为通过）"))


if __name__ == "__main__":
    main()
