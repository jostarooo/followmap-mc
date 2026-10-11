# -*- coding: utf-8 -*-
"""v4（备份）vs v5（直接方块 id）判据的全量对拍。

对 71124 chunk 的全部判定窗口分别跑两版 Signatures.classify：
  - 按建筑分组（重心 + dedupe_blocks）后对比：v5 独有建筑必须逐个过目（应为
    半座巫师 + 被淹没的低计数实例），v4 独有建筑必须为 0（否则就是回归）；
  - 类型混淆必须为 0。
"""
import json
import os
import pickle
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

from followmap.ruins import Signatures, safe_dim, parse_chunk   # noqa: E402

CACHE = os.path.join(os.environ.get("TEMP", "/tmp"), "_probe_blockid_chunks.pkl")
OLD = os.path.join(HERE, "ruins_v4_backup.json")


def load():
    with open(CACHE, "rb") as fh:
        return pickle.load(fh)


def centroid(hist, wcx, wcz, r, feat):
    xs, zs = [], []
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            c = hist.get((wcx + dx, wcz + dz))
            if not c:
                continue
            n = sum(v for k, v in c.items() if k in feat)
            if n:
                xs += [wcx + dx] * n
                zs += [wcz + dz] * n
    if not xs:
        return wcx * 16 + 8, wcz * 16 + 8
    return int(sum(xs) / len(xs) * 16 + 8), int(sum(zs) / len(zs) * 16 + 8)


def buildings(sigs, hist, r):
    """-> {type: {(x,z): (purity, n_windows)}}"""
    d2 = sigs.dedupe_blocks ** 2
    out = {}
    seen = set()
    for c0x, c0z in sorted({(cx // 2, cz // 2) for cx, cz in hist}):
        if (c0x, c0z) in seen:
            continue
        seen.add((c0x, c0z))
        wcx, wcz = c0x * 2, c0z * 2
        h = Counter()
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                c = hist.get((wcx + dx, wcz + dz))
                if c:
                    h.update(c)
        if sum(h.values()) < 60:
            continue
        got = sigs.classify(h)
        if not got:
            continue
        name, purity, _det = got
        x, z = centroid(hist, wcx, wcz, r, sigs._sets[name])
        for g in out.setdefault(name, {}):
            if (g[0] - x) ** 2 + (g[1] - z) ** 2 < d2:
                break
        else:
            out[name][(x, z)] = (purity, h)
    return out


def main():
    old = Signatures(OLD)
    new = Signatures()
    hist = load()
    r = new.window // 2
    bo = buildings(old, hist, r)
    bn = buildings(new, hist, r)
    print("v4：%s" % "  ".join("%s %d" % (t, len(v)) for t, v in sorted(bo.items())))
    print("v5：%s" % "  ".join("%s %d" % (t, len(v)) for t, v in sorted(bn.items())))

    ok = True
    for t in sorted(set(bo) | set(bn)):
        so = set(bo.get(t, ()))
        sn = set(bn.get(t, ()))
        lost = so - sn
        gained = sn - so
        print()
        print("%s：v4 有 %d，v5 有 %d；v5 新增 %d，v5 丢失 %d"
              % (t, len(so), len(sn), len(gained), len(lost)))
        # 丢失 = 回归（允许 96 方块内的重心漂移：放宽到 100 内算同一座）
        for x, z in sorted(lost):
            near = [k for k in sn if (k[0] - x) ** 2 + (k[1] - z) ** 2 <= 100 ** 2]
            if near:
                print("  [漂移] (%d,%d) -> (%d,%d)" % (x, z, near[0][0], near[0][1]))
                continue
            print("  [丢失!] (%d,%d)" % (x, z))
            ok = False
        # 新增 = 必须逐个过目
        for x, z in sorted(gained):
            purity, h = bn[t][(x, z)]
            top = ", ".join("%s=%d" % (k.replace("minecraft:", ""), v)
                            for k, v in h.most_common(6))
            print("  [新增] (%7d,%7d) 纯度 %.3f  %s" % (x, z, purity, top))
    print()
    print("结论：%s" % ("通过（v5 覆盖 v4 全部命中，新增建筑见上）" if ok else "存在丢失，禁止上线！"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
