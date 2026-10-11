# -*- coding: utf-8 -*-
"""淹没率压力测试：把真值窗口按比例缩小，看判据在哪一档开始漏。

原理：地形淹没 = 该列地表被 end_stone 覆盖 -> 该列对直方图贡献 0。
      所以近似等价于「该建筑所有用料计数等比缩小 s 倍」。
      纯度与占比在这种缩放下**不变**，只有**绝对数**锚点会先倒。
      -> 这正好能量出「旧判据怕淹没、新判据不怕」。

用法：python _modtest/_shrink.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from followmap.ruins import Signatures  # noqa: E402
import _nearmiss as NM  # noqa: E402
import _rule as R  # noqa: E402

DIM = "minecraft:the_end"
STEPS = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.35, 0.3, 0.25, 0.2]


def shrink(h, s):
    out = {}
    for k, v in h.items():
        n = int(round(v * s))
        if n > 0:
            out[k] = n
    return out


def collect(sigs, hist):
    """总体 = 「独立余弦归属为该类型」的全部窗口。

    不用 cos>=0.90 当门槛：真机里武士/白金的实例没有一个能到 0.90（说明参考向量
    与真机实例的差距更大），用 0.90 会把它们全排除掉。改用**归属**（argmax），
    这样也能把当前被漏掉的那些窗口一起纳进来 —— 否则测不出「淹没漏检」。
    """
    r = sigs.window // 2
    truth = {t: [] for t in R.TYPES}
    for w, z in sorted({(cx // 2 * 2, cz // 2 * 2) for (cx, cz) in hist}):
        h = NM.win(hist, w, z, r)
        if sum(h.values()) < 60:
            continue
        tn, tc = R.best_of(h)
        if tn:
            truth[tn].append((h, (w * 16 + 8, z * 16 + 8)))
    return truth


def survive(sigs, name, h, rule=None):
    if rule is None:
        return sigs.passes(name, h)[0]
    return R.apply_rule(sigs, h, name, rule)


def curve(sigs, truth, name, rule, tag):
    row = []
    for s in STEPS:
        got = sum(1 for h, _p in truth[name] if survive(sigs, name, shrink(h, s), rule))
        row.append(got)
    n = len(truth[name])
    print("   %-40s %s   (n=%d)" % (tag, " ".join("%2d" % v for v in row), n))
    return row


def main():
    sigs = Signatures()
    truth = collect(sigs, NM.load_hist(DIM))
    print("真值窗口：%s" % {k: len(v) for k, v in truth.items()})
    print("缩放系数:  " + " ".join("%2.2f" % s for s in STEPS))
    print()

    W = "巫师的圣修所"
    print("巫师 —— 淹没到哪一档还剩几个：")
    curve(sigs, truth, W, None, "旧判据（pbrick140 + blk55 + crk30 + dsl18）")
    curve(sigs, truth, W,
          {"anchors": {R.PB: 100}, "ratios": {R.PB: 0.28}},
          "新 pbrick>=100 + 占比>=0.28")
    curve(sigs, truth, W,
          {"anchors": {R.PB: 70}, "ratios": {R.PB: 0.28}},
          "新 pbrick>=70  + 占比>=0.28")
    curve(sigs, truth, W,
          {"anchors": {R.PB: 60}, "ratios": {R.PB: 0.28}},
          "新 pbrick>=60  + 占比>=0.28")
    print()

    S = "武士的修行地"
    print("武士 —— 淹没到哪一档还剩几个：")
    curve(sigs, truth, S, None,
          "旧判据（netherrack60 + endbrick45 + basalt8 + crimson25）")
    curve(sigs, truth, S,
          {"anchors": {"@end_brick": 30, "minecraft:polished_basalt": 5},
           "ratios": {"minecraft:netherrack": 0.14}},
          "新 endbrick>=30 + basalt>=5 + netherrack占比>=0.14")
    print()

    B = "白金星殿"
    print("白金 —— 淹没到哪一档还剩几个：")
    curve(sigs, truth, B, None, "旧判据（infested55 + stonebrick120 + redwool3）")
    curve(sigs, truth, B,
          {"anchors": {"minecraft:infested_stone_bricks": 35,
                       "minecraft:red_wool": 3},
           "ratios": {"@stone_brick": 0.30},
           "any": [{"@mossy": 12},
                   {"minecraft:smooth_stone_slab": 6,
                    "minecraft:smooth_quartz_stairs": 6}]},
          "新 infested>=35 + stonebrick占比>=0.30")


if __name__ == "__main__":
    main()
