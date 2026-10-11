# -*- coding: utf-8 -*-
"""阈值平台扫描：对每个「绝对下限 x 占比下限」格点量出 (真漏检, 真误报)，
把零漏检零误报的格点连成平台，取平台正中（余量最大）而不是贴边取值。

用法：python _modtest/_scan.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from followmap.ruins import Signatures  # noqa: E402
import _nearmiss as NM  # noqa: E402
import _rule as R  # noqa: E402

DIM = "minecraft:the_end"


def scan(sigs, rows, tname, base_anchors, base_any, probe, floors, ratios):
    """固定 base_anchors/base_any，扫 (probe 的绝对下限 x 占比下限)。"""
    print("---- %s：探针 %s，其它锚点固定 %s"
          % (tname, probe, {k.replace("minecraft:", ""): v
                            for k, v in base_anchors.items()}))
    print("      floor\\ratio " + " ".join("%6.2f" % r for r in ratios))
    for f in floors:
        cells = []
        for r in ratios:
            rule = {"anchors": dict(base_anchors), "ratios": {probe: r}}
            rule["anchors"][probe] = f
            if base_any:
                rule["any"] = base_any
            st, mp, fp = R.run(sigs, rows, {tname: rule})
            m, fpv = st[tname]["miss"], st[tname]["fp"]
            cells.append("  %2d/%-2d" % (m, fpv))
        print("      %5d     " % f + " ".join(cells))
    print("      （格式 漏/误报；0/0 即安全）")


def main():
    sigs = Signatures()
    rows = R.rows_of(sigs, NM.load_hist(DIM))
    print("窗口 %d 个\n" % len(rows))

    W = "巫师的圣修所"
    scan(sigs, rows, W, {}, None, R.PB,
         [60, 80, 100, 120, 140, 160, 180],
         [0.20, 0.24, 0.26, 0.28, 0.30, 0.32, 0.35, 0.40])
    print()
    S = "武士的修行地"
    scan(sigs, rows, S,
         {"@end_brick": 45, "minecraft:polished_basalt": 8}, None,
         "minecraft:netherrack",
         [30, 45, 60, 80, 100, 120],
         [0.08, 0.10, 0.12, 0.15, 0.18, 0.22, 0.26])
    print()
    B = "白金星殿"
    scan(sigs, rows, B,
         {"minecraft:infested_stone_bricks": 55, "minecraft:red_wool": 3},
         [{"@mossy": 18},
          {"minecraft:smooth_stone_slab": 10,
           "minecraft:smooth_quartz_stairs": 10}],
         "@stone_brick",
         [40, 60, 80, 100, 120, 140],
         [0.20, 0.25, 0.28, 0.30, 0.34, 0.40, 0.45])


if __name__ == "__main__":
    main()
