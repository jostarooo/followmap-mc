# -*- coding: utf-8 -*-
"""规则评估：显式写出候选规则，逐条量「命中 / 真漏检 / 真误报」。

口径与既有测试套件一致（独立余弦的**归属**才算真值）。
用法：python _modtest/_rule.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from followmap.ruins import Signatures  # noqa: E402
import _nearmiss as NM  # noqa: E402

DIM = "minecraft:the_end"
TYPES = ("白金星殿", "武士的修行地", "巫师的圣修所")
PB = "minecraft:polished_blackstone_bricks"
CR = "minecraft:cracked_polished_blackstone_bricks"
DS = "minecraft:deepslate_bricks"
BL = "minecraft:blackstone"


def best_of(h):
    best, bn = 0.0, None
    for name, ref in NM.REF.items():
        c = NM.cos(h, ref)
        if c > best:
            best, bn = c, name
    return bn, best


def rows_of(sigs, hist):
    r = sigs.window // 2
    return [(NM.win(hist, w, z, r), (w * 16 + 8, z * 16 + 8))
            for w, z in sorted({(cx // 2 * 2, cz // 2 * 2) for (cx, cz) in hist})
            if sum(NM.win(hist, w, z, r).values()) >= 60]


def apply_rule(sigs, h, name, rule):
    """rule = {"anchors": {...}, "ratios": {...}, "purity": float}"""
    tot = sum(v for k, v in h.items() if k in sigs._sets[name])
    gran = sum(h.values())
    if gran < 60 or tot <= 0:
        return False
    for k, need in rule.get("anchors", {}).items():
        if sigs._anchor(k, h) < need:
            return False
    for k, need in rule.get("ratios", {}).items():
        if (sigs._anchor(k, h) / tot) < need:
            return False
    anyg = rule.get("any")
    if anyg:
        if not any(all(sigs._anchor(k, h) >= v for k, v in g.items())
                   for g in anyg):
            return False
    return tot / gran >= rule.get("purity", 0.80)


def run(sigs, rows, rules):
    """rules: {type: rule}；未列出的类型用当前 rules.json 判据。"""
    stat = {t: {"hit": 0, "miss": 0, "fp": 0, "sib": 0} for t in TYPES}
    miss_pos, fp_pos = [], []
    for h, pos in rows:
        bn, bc = best_of(h)
        got = None
        for t in TYPES:
            if t in rules:
                ok = apply_rule(sigs, h, t, rules[t])
            else:
                ok = sigs.passes(t, h)[0]
            if ok:
                got = t
                break
        if got:
            stat[got]["hit"] += 1
            if bn == got:
                stat[got]["sib"] += 1
            elif bc >= 0.70:
                stat[got]["fp"] += 1
                fp_pos.append((got, pos, bn, round(bc, 2)))
        elif bn and bc >= 0.90:
            stat[bn]["miss"] += 1
            miss_pos.append((bn, pos, round(bc, 2)))
    return stat, miss_pos, fp_pos


def show(tag, stat, miss_pos, fp_pos):
    print("%-34s %s" % (tag, "  ".join(
        "%s[命中%d 漏%d 误报%d 同类%d]" % (t[0], stat[t]["hit"], stat[t]["miss"],
                                          stat[t]["fp"], stat[t]["sib"])
        for t in TYPES)))
    for t, pos, c in miss_pos:
        print("      漏检 %-6s (%7d,%7d) cos=%.2f" % (t, pos[0], pos[1], c))
    for t, pos, bn, c in fp_pos:
        print("      误报 判=%-6s (%7d,%7d) 余弦归属=%s(%.2f)" % (t, pos[0], pos[1], bn, c))


def main():
    sigs = Signatures()
    rows = rows_of(sigs, NM.load_hist(DIM))
    print("窗口 %d 个\n" % len(rows))

    print("=== 巫师的圣修所（问题类型）===")
    show("W0 当前判据", *run(sigs, rows, {}))

    cands = {
        "W1 pbrick>=140 + 占比>=0.28":
            {"anchors": {PB: 140}, "ratios": {PB: 0.28}},
        "W2 pbrick>=100 + 占比>=0.28":
            {"anchors": {PB: 100}, "ratios": {PB: 0.28}},
        "W3 pbrick>=100 + 占比>=0.30 + 裂纹>=25":
            {"anchors": {PB: 100, CR: 25}, "ratios": {PB: 0.30}},
        "W4 pbrick>=140 + 占比>=0.30":
            {"anchors": {PB: 140}, "ratios": {PB: 0.30}},
        "W5 pbrick>=140 + 占比>=0.28 + 黑石族>=50":
            {"anchors": {PB: 140, BL: 50}, "ratios": {PB: 0.28}},
        "W6 pbrick>=140 + 占比>=0.28 + 裂纹>=20":
            {"anchors": {PB: 140, CR: 20}, "ratios": {PB: 0.28}},
    }
    for tag, w in cands.items():
        show(tag, *run(sigs, rows, {TYPES[2]: w}))

    print()
    print("=== 顺带看武士 / 白金的同类改法（当前它们没漏，别弄坏）===")
    show("S0/S1 当前判据", *run(sigs, rows, {}))
    show("S2 武士 netherrack>=60 改占比>=0.15", *run(sigs, rows, {
        TYPES[1]: {"anchors": {"@end_brick": 45, "minecraft:polished_basalt": 8},
                   "ratios": {"minecraft:netherrack": 0.15}}}))
    show("S3 白金 @stone_brick>=120 -> >=60 + 占比>=0.30", *run(sigs, rows, {
        TYPES[0]: {"anchors": {"minecraft:infested_stone_bricks": 55,
                               "minecraft:red_wool": 3},
                   "ratios": {"@stone_brick": 0.30}},
        "any": [{"@mossy": 18},
                {"minecraft:smooth_stone_slab": 10,
                 "minecraft:smooth_quartz_stairs": 10}]}))


if __name__ == "__main__":
    main()
