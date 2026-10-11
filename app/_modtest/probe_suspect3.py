# -*- coding: utf-8 -*-
"""可疑点 (4586,-46944) 的补充证据：

1) 「装饰方块」出现统计：可疑窗口里有 light_blue/white/blue stained_glass_pane、
   iron_bars、chain —— 这几样都不在巫师（也不在武士/白金）的用料表里。
   如果这 71124 个 chunk 里它们**只在这里出现**，那基本是玩家手搓的建筑；
   如果成片出现，就是某种我没收录的小遗迹。
2) soul_soil 富集区聚类：soul_soil>=80 的 chunk 连片之后有几片？每片长什么样？
   （巫师本体也带 soul_soil，先把巫师的片认出来，剩下的才是问题。）
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

CACHE = os.path.join(os.environ.get("TEMP", "/tmp"), "_probe_blockid_chunks.pkl")
DECOR = [
    "minecraft:light_blue_stained_glass_pane",
    "minecraft:white_stained_glass_pane",
    "minecraft:blue_stained_glass_pane",
    "minecraft:iron_bars",
    "minecraft:chain",
    "minecraft:chest",
    "minecraft:crafting_table",
    "minecraft:furnace",
    "minecraft:respawn_anchor",
    "minecraft:enchanting_table",
    "minecraft:bookshelf",
    "minecraft:note_block",
    "minecraft:jukebox",
    "minecraft:lantern",
]


def load():
    with open(CACHE, "rb") as fh:
        return pickle.load(fh)


def blobs(cells, key=lambda c: True):
    """8 邻域连片。cells: {(cx,cz): Counter}，key 决定哪些 chunk 参与。"""
    cs = {k for k, c in cells.items() if key(c)}
    seen, out = set(), []
    for c0 in sorted(cs):
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
                    if nb in cs and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
        out.append(blob)
    return out


def main():
    sigs = Signatures()
    hist = load()
    print("已加载 %d chunk" % len(hist))
    r = sigs.window // 2
    s_wiz = sigs._sets["巫师的圣修所"]

    # ---- 1) 装饰方块出现在哪些 chunk ----------------------------------------
    print("=" * 88)
    print("1) 装饰方块的全服出现统计（含任意一种即计数）")
    print("=" * 88)
    hits = {}
    for k, c in hist.items():
        for b in DECOR:
            if c.get(b):
                hits.setdefault(b, []).append(k)
    for b in DECOR:
        v = hits.get(b, [])
        print("  %-42s %4d 个 chunk" % (b.replace("minecraft:", ""), len(v)))
    print()

    # 玻璃板/铁栏/链条出现的 chunk 连片
    dec = ["light_blue_stained_glass_pane", "white_stained_glass_pane",
           "blue_stained_glass_pane", "iron_bars", "chain"]
    decfull = ["minecraft:" + d for d in dec]
    cs = {}
    for k, c in hist.items():
        n = sum(c.get(b, 0) for b in decfull)
        if n:
            cs[k] = n
    print("  玻璃板/铁栏/链条合计出现的 chunk：%d 个，连片：" % len(cs))
    for b in blobs({k: Counter({"x": v}) for k, v in cs.items()}):
        xs = [c[0] for c in b]
        zs = [c[1] for c in b]
        print("      %2d chunk  x %d..%d  z %d..%d"
              % (len(b), min(xs), max(xs), min(zs), max(zs)))
    print()

    # ---- 2) soul_soil 富集区 -------------------------------------------------
    print("=" * 88)
    print("2) soul_soil >= 80 的 chunk 连片（巫师本体也含 soul_soil）")
    print("=" * 88)
    cs2 = {k: c for k, c in hist.items() if c.get("minecraft:soul_soil", 0) >= 80}
    print("  chunk 数：%d" % len(cs2))
    bl = blobs(cs2)
    bl.sort(key=len, reverse=True)
    print("  片数：%d，前 10 片：" % len(bl))
    for b in bl[:10]:
        xs = [c[0] for c in b]
        zs = [c[1] for c in b]
        tot = Counter()
        for c in b:
            tot.update(hist[c])
        hit = sum(v for k, v in tot.items() if k in s_wiz)
        pb = tot.get("minecraft:polished_blackstone_bricks", 0)
        ss = tot.get("minecraft:soul_soil", 0)
        ratio = pb / hit if hit else 0
        print("      %2d chunk  x %5d..%5d z %5d..%5d  soul_soil=%-5d pbricks=%-5d "
              "巫师用料=%-5d 占比=%.2f %s"
              % (len(b), min(xs), max(xs), min(zs), max(zs), ss, pb, hit, ratio,
                 "<-巫师主体" if ratio >= 0.26 else ""))
    print()

    # ---- 3) 巫师本体窗口里，玻璃板/铁栏是否出现过 ------------------------------
    print("=" * 88)
    print("3) 现有判据判为巫师的 263 座里，含玻璃板/铁栏/链条的有几座")
    print("=" * 88)
    n = 0
    for (c0x, c0z) in sorted({(cx // 2, cz // 2) for cx, cz in hist}):
        wcx, wcz = c0x * 2, c0z * 2
        h = Counter()
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                c = hist.get((wcx + dx, wcz + dz))
                if c:
                    h.update(c)
        if sigs.classify(h) and sigs.classify(h)[0] == "巫师的圣修所":
            if any(h.get(b) for b in decfull):
                n += 1
    print("  含装饰方块的巫师：%d / 263" % n)


if __name__ == "__main__":
    main()
