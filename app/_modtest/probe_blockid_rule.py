# -*- coding: utf-8 -*-
"""探针：检验「单个方块 id 即可判定遗迹」这个简化判据在真机数据上是否成立。

命题（用户提出，都是「充分性」方向：出现即判定）：
  A) 末地出现黑石(blackstone)     -> 必然是巫师遗迹
  B) 末地出现石砖(stone_brick 系) -> 必然是白金遗迹

指纹表里 anchors 保证的是**必要性**（巫师必然含磨制黑石砖 >= 100）。
本探针测的是反过来成不成立，并顺带找出「哪个具体方块 id 才是干净的分界线」。

只读：不写去重库、不改任何项目文件。解析结果缓存在系统临时目录。
"""
import os
import pickle
import sys
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

from followmap.ruins import Signatures, safe_dim, parse_chunk   # noqa: E402

DIM = "minecraft:the_end"
ROOT = os.path.join(os.path.expanduser("~"), ".coordbridge")
CACHE = os.path.join(os.environ.get("TEMP", "/tmp"), "_probe_blockid_chunks.pkl")

BLACKSTONE = [
    "minecraft:blackstone",
    "minecraft:blackstone_stairs",
    "minecraft:blackstone_slab",
    "minecraft:gilded_blackstone",
    "minecraft:polished_blackstone",
    "minecraft:polished_blackstone_bricks",
    "minecraft:polished_blackstone_brick_wall",
    "minecraft:polished_blackstone_brick_stairs",
    "minecraft:polished_blackstone_brick_slab",
    "minecraft:polished_blackstone_slab",
    "minecraft:polished_blackstone_stairs",
    "minecraft:polished_blackstone_wall",
    "minecraft:polished_blackstone_pressure_plate",
    "minecraft:cracked_polished_blackstone_bricks",
]

# 候选简化判据：(标签, 取值函数, 目标类型)
def mk(sigs):
    sb = list(sigs.groups.get("stone_brick", []))
    return [
        ("黑石系合计",       lambda h: sum(h.get(b, 0) for b in BLACKSTONE),        "巫师的圣修所"),
        ("原料黑石",         lambda h: h.get("minecraft:blackstone", 0),            "巫师的圣修所"),
        ("磨制黑石砖",       lambda h: h.get("minecraft:polished_blackstone_bricks", 0), "巫师的圣修所"),
        ("磨制黑石砖系",     lambda h: sum(h.get(b, 0) for b in
                                       ["minecraft:polished_blackstone_bricks",
                                        "minecraft:polished_blackstone_brick_wall",
                                        "minecraft:polished_blackstone_brick_stairs",
                                        "minecraft:polished_blackstone_brick_slab",
                                        "minecraft:cracked_polished_blackstone_bricks"]), "巫师的圣修所"),
        ("石砖系合计",       lambda h: sum(h.get(b, 0) for b in sb),                "白金星殿"),
        ("stone_bricks",     lambda h: h.get("minecraft:stone_bricks", 0),          "白金星殿"),
        ("虫蛀石砖",         lambda h: h.get("minecraft:infested_stone_bricks", 0), "白金星殿"),
    ]


def load_all():
    if os.path.exists(CACHE):
        try:
            with open(CACHE, "rb") as fh:
                h = pickle.load(fh)
            print("  命中缓存 %r -> %d chunk" % (CACHE, len(h)))
            return h
        except Exception as e:
            print("  缓存不可用(%s)，重新解析" % e)
    base = os.path.join(ROOT, "chunks", safe_dim(DIM))
    hist = {}
    t0 = time.perf_counter()
    for rx in os.listdir(base):
        p1 = os.path.join(base, rx)
        if not os.path.isdir(p1):
            continue
        for rz in os.listdir(p1):
            p2 = os.path.join(p1, rz)
            if not os.path.isdir(p2):
                continue
            for fn in os.listdir(p2):
                if not fn.endswith(".bin"):
                    continue
                a, _, b = fn[:-4].partition("_")
                try:
                    cx, cz = int(a), int(b)
                except ValueError:
                    continue
                h = parse_chunk(os.path.join(p2, fn))
                hist[(cx, cz)] = h if h else Counter()
    print("  解析 %d chunk（%.1fs）" % (len(hist), time.perf_counter() - t0))
    try:
        with open(CACHE, "wb") as fh:
            pickle.dump(hist, fh, -1)
        print("  已缓存 -> %r" % CACHE)
    except Exception as e:
        print("  缓存写入失败(忽略):", e)
    return hist


def centroid(hist, cx, cz, r, featset):
    xs, zs = [], []
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            c = hist.get((cx + dx, cz + dz))
            if not c:
                continue
            hit = sum(v for k, v in c.items() if k in featset)
            if hit:
                xs += [cx + dx] * hit
                zs += [cz + dz] * hit
    if not xs:
        return cx * 16 + 8, cz * 16 + 8
    return int(sum(xs) / len(xs) * 16 + 8), int(sum(zs) / len(zs) * 16 + 8)


def main():
    sigs = Signatures()
    rules = mk(sigs)
    print("指纹表: %d 类  window=%d  min_purity=%.2f" %
          (len(sigs.types), sigs.window, sigs.min_purity))
    print("读取真机末地区块…")
    hist = load_all()
    tot = {k: sum(v.values()) for k, v in hist.items()}
    print()
    r = sigs.window // 2

    cells = sorted({(cx // 2, cz // 2) for cx, cz in hist})
    print("扫描 %d 个窗口格…" % len(cells))
    t0 = time.perf_counter()

    wins = []          # 所有通过总量门槛的窗口
    n_win = 0
    for c0x, c0z in cells:
        wcx, wcz = c0x * 2, c0z * 2
        s = 0
        for dx in range(-r, r + 1):
            row = wcx + dx
            for dz in range(-r, r + 1):
                s += tot.get((row, wcz + dz), 0)
        if s < 60:
            continue
        h = Counter()
        for dx in range(-r, r + 1):
            row = wcx + dx
            for dz in range(-r, r + 1):
                c = hist.get((row, wcz + dz))
                if c:
                    h.update(c)
        if not h:
            continue
        got = sigs.classify(h)
        wins.append({
            "wcx": wcx, "wcz": wcz, "hist": h,
            "type": got[0] if got else None,
            "pure": got[1] if got else 0.0,
        })
        if got:
            n_win += 1
    print("  实际判定 %d 个窗口，命中 %d 个（%.1fs）" %
          (len(wins), n_win, time.perf_counter() - t0))
    print()

    # ---------- 建筑级聚类 ----------
    d2 = sigs.dedupe_blocks ** 2
    hits = sorted([w for w in wins if w["type"]], key=lambda x: -x["pure"])
    clusters = []
    for w in hits:
        wcx, wcz = w["wcx"], w["wcz"]
        s = sigs._sets[w["type"]]
        x, z = centroid(hist, wcx, wcz, r, s)
        for cl in clusters:
            if cl["type"] != w["type"]:
                continue
            if (cl["x"] - x) ** 2 + (cl["z"] - z) ** 2 < d2:
                cl["wins"].append((wcx, wcz, w["hist"]))
                break
        else:
            clusters.append({"type": w["type"], "x": x, "z": z,
                             "purity": w["pure"], "wins": [(wcx, wcz, w["hist"])]})
    for cl in clusters:
        h = Counter()
        for _a, _b, hh in cl["wins"]:
            h.update(hh)
        cl["h"] = h
    print("建筑级：%d 座  " % len(clusters) +
          "  ".join("%s %d" % (t, sum(1 for c in clusters if c["type"] == t))
                    for t in sigs.types))
    print()

    # ---------- 逐类：黑石系各成员到底是谁在用 ----------
    print("=" * 84)
    print("一、黑石系各成员在三类遗迹上的实际用量（建筑级，取该类全部座数的合计）")
    print("=" * 84)
    hdr = "%-46s" % "方块 id"
    print(hdr + "  " + "  ".join("%-14s" % t[:6] for t in sigs.types))
    for b in BLACKSTONE:
        row = "%-46s" % b.replace("minecraft:", "")
        for t in sigs.types:
            lst = [c for c in clusters if c["type"] == t]
            v = sum(c["h"].get(b, 0) for c in lst)
            nz = sum(1 for c in lst if c["h"].get(b, 0) > 0)
            row += "  %-14s" % ("%d (%d/%d座)" % (v, nz, len(lst)) if v else "0")
        print(row)
    print()
    print("石砖系各成员：")
    for b in sigs.groups.get("stone_brick", []):
        row = "%-46s" % b.replace("minecraft:", "")
        for t in sigs.types:
            lst = [c for c in clusters if c["type"] == t]
            v = sum(c["h"].get(b, 0) for c in lst)
            nz = sum(1 for c in lst if c["h"].get(b, 0) > 0)
            row += "  %-14s" % ("%d (%d/%d座)" % (v, nz, len(lst)) if v else "0")
        print(row)
    print()

    # ---------- 候选简化判据：能不能靠一个阈值分开 ----------
    print("=" * 84)
    print("二、候选简化判据的可分性（建筑级：该类所有座数的取值范围）")
    print("=" * 84)
    for label, fn, want in rules:
        vals = {}
        for t in sigs.types:
            lst = [c for c in clusters if c["type"] == t]
            vals[t] = [fn(c["h"]) for c in lst]
        pos = sorted(vals.get(want) or [0])
        neg = sorted(x for t, v in vals.items() if t != want for x in v)
        lo_pos = pos[0] if pos else 0
        hi_neg = max(neg) if neg else 0
        ok = lo_pos > hi_neg
        print()
        print("[%s]  =>  判为 %s" % (label, want))
        for t in sigs.types:
            v = vals.get(t) or []
            print("     %-10s n=%2d  范围 %s" %
                  (t, len(v), ("%d ~ %d" % (min(v), max(v))) if v else "-"))
        if ok:
            print("     ✅ 可分：%s 最低 %d  >  其它类型最高 %d   （阈值取 %d，余量 %.1fx）"
                  % (want, lo_pos, hi_neg, (lo_pos + hi_neg) // 2 or 1,
                     (lo_pos / hi_neg) if hi_neg else 99))
        else:
            print("     ❌ 不可分：%s 最低 %d  <=  其它类型最高 %d  —— 无论阈值取多少都会串类"
                  % (want, lo_pos, hi_neg))
    print()

    # ---------- 命题 A/B：出现即判定 ----------
    print("=" * 84)
    print("三、命题检验：「出现某方块 => 必然是某遗迹」（出现 = 数量 >= 1）")
    print("=" * 84)
    for label, fn, want in rules:
        hit = [c for c in clusters if fn(c["h"]) >= 1]
        cnt = Counter(c["type"] for c in hit)
        wrong = {t: n for t, n in cnt.items() if t != want}
        print()
        print("  [%s] 出现 => %s" % (label, want))
        print("     共 %d 座含该方块：" % len(hit), end="")
        print("  " + "  ".join("%s %d" % (t, n) for t, n in cnt.most_common()))
        if wrong:
            print("     ❌ 命题不成立：还有 %s" %
                  "、".join("%s %d 座" % (t, n) for t, n in wrong.items()))
        else:
            print("     ✅ 命题在这一批真机数据上成立（无反例）")
    print()

    # ---------- 误报风险：未识别窗口里含这些方块的 ----------
    print("=" * 84)
    print("四、误报风险：含这些方块、但**没有被判成任何遗迹**的窗口")
    print("=" * 84)
    for label, fn, want in rules:
        cand = [w for w in wins if not w["type"] and fn(w["hist"]) >= 20]
        print()
        print("  [%s] 未识别窗口里该值 >= 20 的：%d 个" % (label, len(cand)))
        shown, seen = 0, set()
        for w in sorted(cand, key=lambda x: -fn(x["hist"])):
            key = (w["wcx"] // 6, w["wcz"] // 6)
            if key in seen:
                continue
            seen.add(key)
            top = ", ".join("%s=%d" % (k.replace("minecraft:", ""), v)
                            for k, v in w["hist"].most_common(6))
            print("      值=%-5d 人造总数=%-5d 窗心(%7d,%7d)  %s"
                  % (fn(w["hist"]), sum(w["hist"].values()),
                     w["wcx"] * 16, w["wcz"] * 16, top))
            shown += 1
            if shown >= 4:
                break
        if not shown:
            print("      （无）")

    # ---------- 关键补充：那些「含标记但没被判成该类」的窗口，是边缘还是别的建筑 ----------
    print()
    print("=" * 84)
    print("五、上一段的窗口到底是「已知遗迹的边缘」还是「另外的建筑」？")
    print("=" * 84)
    for label, fn, want in rules:
        cand = [w for w in wins if not w["type"] and fn(w["hist"]) >= 20]
        if not cand:
            continue
        # 同样按 96 方块半径聚类
        grp = []
        for w in sorted(cand, key=lambda x: -fn(x["hist"])):
            x, z = w["wcx"] * 16 + 8, w["wcz"] * 16 + 8
            for g in grp:
                if (g["x"] - x) ** 2 + (g["z"] - z) ** 2 < d2:
                    g["w"].append(w)
                    break
            else:
                grp.append({"x": x, "z": z, "w": [w]})
        print()
        print("  [%s] 未识别窗口 %d 个 -> 聚成 %d 簇" % (label, len(cand), len(grp)))
        for g in grp:
            h = Counter()
            for w in g["w"]:
                h.update(w["hist"])
            # 距最近的已识别遗迹多远
            best, bt = None, None
            for cl in clusters:
                d = ((cl["x"] - g["x"]) ** 2 + (cl["z"] - g["z"]) ** 2) ** 0.5
                if best is None or d < best:
                    best, bt = d, cl["type"]
            top = ", ".join("%s=%d" % (k.replace("minecraft:", ""), v)
                            for k, v in h.most_common(6))
            if best is not None and best < 200:
                tag = "已知%s(%d方块) 的边缘" % (bt, int(best))
            else:
                tag = "**独立建筑**（最近遗迹 %s %d 方块）" % (bt, int(best or -1))
            print("    标记值=%-5d 人造总数=%-5d  (%7d,%7d)  %s" %
                  (fn(h), sum(h.values()), g["x"], g["z"], tag))
            print("        %s" % top)

    print()
    print("窗口级总计：判定窗口 %d 个，命中 %d 个，未识别 %d 个"
          % (len(wins), n_win, len(wins) - n_win))


if __name__ == "__main__":
    main()
