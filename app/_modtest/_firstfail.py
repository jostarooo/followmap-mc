# -*- coding: utf-8 -*-
"""先倒的是哪条锚点：把真值窗口按比例缩小，逐档记录**第一条失败**的判据。

这比"还剩几个"更有用 —— 它直接指出该把哪个阈值降下来。
用法：python _modtest/_firstfail.py
"""
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from followmap.ruins import Signatures  # noqa: E402
import _nearmiss as NM  # noqa: E402
import _rule as R  # noqa: E402
from _shrink import STEPS, shrink, collect  # noqa: E402

DIM = "minecraft:the_end"


def first_fail(sigs, name, h):
    """返回 (卡住的判据, 实得, 需要, 占比)。通过则返回 None。"""
    meta = sigs.types[name]
    gran = sum(h.values())
    if gran < 60:
        return ("窗口总量", gran, 60, 0.0)
    tot = sum(v for k, v in h.items() if k in sigs._sets[name])
    if tot <= 0:
        return ("该类型用料", 0, 1, 0.0)
    for k, need in meta["anchors"].items():
        v = sigs._anchor(k, h)
        if v < need:
            return (k, v, need, (v / tot if tot else 0))
    for g in meta["any"]:
        if all(sigs._anchor(k, h) >= v for k, v in g.items()):
            break
    else:
        if meta["any"]:
            return ("any 组", 0, 0, 0.0)
    pur = tot / gran
    if pur < sigs.min_purity:
        return ("纯度", pur, sigs.min_purity, pur)
    return None


def main():
    sigs = Signatures()
    truth = collect(sigs, NM.load_hist(DIM))
    for name in R.TYPES:
        rows = truth[name]
        if not rows:
            continue
        print("=" * 78)
        print("%s  (窗口 %d 个；下表 = 每个缩放档「第一条倒下的判据」出现次数)"
              % (name, len(rows)))
        print("  缩放:      " + " ".join("%5.2f" % s for s in STEPS))
        cnts = {}
        alive = []
        for s in STEPS:
            c = Counter()
            n = 0
            for h, _p in rows:
                ff = first_fail(sigs, name, shrink(h, s))
                if ff is None:
                    n += 1
                else:
                    c[ff[0]] += 1
            cnts[s] = c
            alive.append(n)
        print("  仍通过:    " + " ".join("%5d" % v for v in alive))
        keys = sorted({k for c in cnts.values() for k in c},
                      key=lambda k: -sum(c[k] for c in cnts.values()))
        for k in keys:
            lab = k.replace("minecraft:", "")[:22]
            print("  %-22s %s" % (lab, " ".join("%5d" % cnts[s][k] for s in STEPS)))
        print()


if __name__ == "__main__":
    main()
