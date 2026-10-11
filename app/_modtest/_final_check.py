# -*- coding: utf-8 -*-
"""最终候选方案的全局评估：三类新判据同时启用，逐项核 命中/漏检/误报/可疑。

三类同时换判据时，最容易出的问题是「A 类的新阈值把 B 类的建筑也吃了」，
所以必须**一次全开**评估，不能一类一类单独看。
用法：python _modtest/_final_check.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from followmap.ruins import Signatures  # noqa: E402
import _nearmiss as NM  # noqa: E402
import _rule as R  # noqa: E402

DIM = "minecraft:the_end"

# 最终方案
NEW = {
    "巫师的圣修所": {
        "anchors": {R.PB: 100},
        "ratios": {R.PB: 0.26},
    },
    "武士的修行地": {
        "anchors": {"@end_brick": 30, "minecraft:polished_basalt": 5},
        "ratios": {"minecraft:netherrack": 0.12},
    },
    "白金星殿": {
        "anchors": {"minecraft:infested_stone_bricks": 35,
                    "minecraft:red_wool": 3},
        "ratios": {"@stone_brick": 0.30},
        "any": [{"@mossy": 12},
                {"minecraft:smooth_stone_slab": 6,
                 "minecraft:smooth_quartz_stairs": 6}],
    },
}


def main():
    sigs = Signatures()
    rows = R.rows_of(sigs, NM.load_hist(DIM))
    print("窗口 %d 个\n" % len(rows))

    for tag, rules in (("旧判据", {}), ("新判据", NEW)):
        stat, mp, fp = R.run(sigs, rows, rules)
        print("=== %s ===" % tag)
        for t in R.TYPES:
            s = stat[t]
            print("   %-8s 命中 %-3d  真漏检 %-3d  真误报 %-3d  同类非典型 %d"
                  % (t, s["hit"], s["miss"], s["fp"], s["sib"]))
        print("   合计 命中 %d  真漏检 %d  真误报 %d"
              % (sum(stat[t]["hit"] for t in R.TYPES),
                 sum(stat[t]["miss"] for t in R.TYPES),
                 sum(stat[t]["fp"] for t in R.TYPES)))
        for t, pos, c in mp:
            print("     漏 %-6s (%7d,%7d) cos=%.2f" % (t, pos[0], pos[1], c))
        for t, pos, bn, c in fp:
            print("     误判 判=%-6s (%7d,%7d) 余弦归属=%s(%.2f)" % (t, pos[0], pos[1], bn, c))
        print()

    # 可疑命中：判出来了，但独立余弦对**任何**一类的值都很低 -> 可能是真的误报
    print("=== 可疑命中（判为某类，但余弦对三类都 < 0.60）===")
    for tag, rules in (("旧", {}), ("新", NEW)):
        n = 0
        samp = []
        for h, pos in rows:
            got = None
            for t in R.TYPES:
                ok = R.apply_rule(sigs, h, t, rules[t]) if t in rules \
                    else sigs.passes(t, h)[0]
                if ok:
                    got = t
                    break
            if not got:
                continue
            bn, bc = R.best_of(h)
            if bc < 0.60:
                n += 1
                samp.append((pos, got, bn, round(bc, 2)))
        print("   %s判据：%d 个" % (tag, n))
        for pos, got, bn, bc in samp[:10]:
            print("       判=%-6s (%7d,%7d) 最高余弦=%s(%.2f)" % (got, pos[0], pos[1], bn, bc))


if __name__ == "__main__":
    main()
