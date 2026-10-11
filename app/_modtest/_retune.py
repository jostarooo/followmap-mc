# -*- coding: utf-8 -*-
"""判据重定：把「被地形淹没」变成尺度无关问题。

原理（真机数据实测）：
  地形淹没 = 该列地表方块被 end_stone 覆盖 -> 该列对直方图贡献 0。
  于是**该类型的所有用料计数等比缩小**，而
    纯度   = 该类型用料 / 窗口内全部人造方块   —— 等比缩小后**不变**
    比例   = 主特征方块 / 该类型用料           —— 同样**不变**
  但**绝对计数会缩小**。所以凡是拿绝对数当锚点的，淹没到一定程度必然漏。
  => 判据应该写成「纯度 + 比例」这类尺度无关量，绝对数只留一个很低的"最小规模"门槛。

本脚本量出每个候选量的可分性，并直接评估几套候选规则。
用法：python _modtest/_retune.py
"""
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from followmap.ruins import Signatures  # noqa: E402
import _nearmiss as NM  # noqa: E402

DIM = "minecraft:the_end"


def feats(h, sigs, name):
    """算一个窗口的候选特征（短名，方便读表）。"""
    total = sum(h.values())
    s = sigs._sets[name]
    hit = sum(v for k, v in h.items() if k in s)
    f = {"total": total, "hit": hit,
         "purity": (hit / total) if total else 0.0}
    SHORT = {
        "minecraft:polished_blackstone_bricks": "pbrick",
        "minecraft:blackstone": "blackstone",
        "minecraft:cracked_polished_blackstone_bricks": "cracked",
        "minecraft:deepslate_bricks": "deepslate_bricks",
        "minecraft:infested_stone_bricks": "infested",
        "minecraft:red_wool": "red_wool",
        "minecraft:netherrack": "netherrack",
        "minecraft:polished_basalt": "polished_basalt",
    }
    for k in sigs.types[name]["anchors"]:
        short = SHORT.get(k, k.lstrip("@").replace("minecraft:", ""))
        f[short] = sigs._anchor(k, h)
    # 家族派生量（即使没写进锚点也算，方便看趋势）
    for g in ("end_brick", "crimson", "stone_brick", "mossy"):
        f[g] = sigs._anchor("@" + g, h)
    f["pbrick_any"] = sigs._anchor(
        "@pbrick_family", h) if "pbrick_family" in sigs.groups else (
        f["pbrick"]
        + h.get("minecraft:polished_blackstone_brick_stairs", 0)
        + h.get("minecraft:polished_blackstone_brick_slab", 0)
        + h.get("minecraft:polished_blackstone_brick_wall", 0)
        + f["cracked"])
    return f


def main():
    sigs = Signatures()
    hist = NM.load_hist(DIM)
    r = sigs.window // 2
    cells = sorted({(cx // 2 * 2, cz // 2 * 2) for (cx, cz) in hist})

    W = "巫师的圣修所"
    truth, noise = [], []
    for wcx, wcz in cells:
        h = NM.win(hist, wcx, wcz, r)
        if sum(h.values()) < 60:
            continue
        tn, tc = NM.truth_of(h)
        f = feats(h, sigs, W)
        f["_pos"] = (wcx * 16 + 8, wcz * 16 + 8)
        f["_cos"] = tc
        if tn == W:
            truth.append(f)
        elif tn is None and tc < 0.70:
            noise.append(f)

    print("巫师真值 %d 个窗口 / 其它 %d 个窗口" % (len(truth), len(noise)))
    print()

    # ---- 1) 单量可分性 ----
    print("单量可分性（看真值下界 vs 噪声上界，重叠越少越好）")
    print("  %-22s %10s %10s %10s  %s" % ("量", "真值min", "噪声max", "真值p25", "重叠"))
    keys = ["purity", "pbrick", "pbrick_any", "blackstone", "cracked",
            "deepslate_bricks", "hit", "total"]
    for k in keys:
        tv = sorted(f.get(k, 0) for f in truth)
        nv = sorted(f.get(k, 0) for f in noise)
        if not tv or not nv:
            continue
        lo = tv[0]
        hi = nv[-1]
        ov = sum(1 for v in nv if v >= lo)
        print("  %-22s %10.3f %10.3f %10.3f  %d/%d 噪声在真值下界之上"
              % (k, lo, hi, tv[max(0, len(tv) // 4)], ov, len(nv)))

    # ---- 2) 比例型派生量 ----
    print()
    print("比例型派生量（尺度无关）")
    print("  %-22s %10s %10s %10s  %s" % ("量", "真值min", "噪声max", "真值p25", "重叠"))

    def ratio(f, num, den):
        d = f.get(den, 0)
        return (f.get(num, 0) / d) if d else 0.0

    derived = {
        "pbrick/hit": lambda f: ratio(f, "pbrick", "hit"),
        "pbrick_any/hit": lambda f: ratio(f, "pbrick_any", "hit"),
        "(pbrick_any-cracked)/hit": lambda f: ratio(f, "pbrick_any", "hit"),
        "pbrick/total": lambda f: ratio(f, "pbrick", "total"),
        "pbrick_any/total": lambda f: ratio(f, "pbrick_any", "total"),
        "cracked/hit": lambda f: ratio(f, "cracked", "hit"),
        "deepslate_bricks/hit": lambda f: ratio(f, "deepslate_bricks", "hit"),
        "deepslate_bricks/pbrick": lambda f: ratio(f, "deepslate_bricks", "pbrick"),
    }
    for k, fn in derived.items():
        tv = sorted(fn(f) for f in truth)
        nv = sorted(fn(f) for f in noise)
        lo = tv[0]
        ov = sum(1 for v in nv if v >= lo)
        print("  %-22s %10.3f %10.3f %10.3f  %d/%d"
              % (k, lo, nv[-1], tv[max(0, len(tv) // 4)], ov, len(nv)))

    # ---- 3) 真值明细（看淹没程度） ----
    print()
    print("11 个巫师真值窗口明细（按 pbrick 升序，越上面越像被淹没）")
    print("  %-18s %6s %6s %6s %6s %6s %6s %5s %5s"
          % ("位置", "纯", "pbrick", "any", "blk", "crk", "dsl", "hit", "占比"))
    for f in sorted(truth, key=lambda f: f["pbrick"]):
        print("  (%7d,%7d) %6.2f %6d %6d %6d %6d %6d %5d %5.2f"
              % (f["_pos"][0], f["_pos"][1], f["purity"], f["pbrick"],
                 f["pbrick_any"], f["blackstone"], f["cracked"],
                 f["deepslate_bricks"], f["hit"],
                 (f["pbrick"] / f["hit"]) if f["hit"] else 0))

    # ---- 4) 噪声里最"像巫师"的窗口 ----
    print()
    print("噪声里 pbrick 最高的 8 个窗口（必须继续排除掉的）")
    print("  %-18s %6s %6s %6s %6s %6s %6s %5s %5s"
          % ("位置", "纯", "pbrick", "any", "blk", "crk", "dsl", "hit", "占比"))
    for f in sorted(noise, key=lambda f: -f["pbrick"])[:8]:
        print("  (%7d,%7d) %6.2f %6d %6d %6d %6d %6d %5d %5.2f"
              % (f["_pos"][0], f["_pos"][1], f["purity"], f["pbrick"],
                 f["pbrick_any"], f["blackstone"], f["cracked"],
                 f["deepslate_bricks"], f["hit"],
                 (f["pbrick"] / f["hit"]) if f["hit"] else 0))


if __name__ == "__main__":
    main()
