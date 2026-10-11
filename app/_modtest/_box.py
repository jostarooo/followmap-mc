# -*- coding: utf-8 -*-
"""把一个世界坐标方框内的**全部**人造方块聚合出来，看某个建筑真正用了什么。

比 5x5 窗口更全：窗口只有 80x80 格，大楼会被截断，导致「某种料一个都没有」的假象。
用法：python _modtest/_box.py <cx> <cz> [半边长格]
"""
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from followmap.ruins import Signatures, NATURAL  # noqa: E402
from _nearmiss import REF, cos  # noqa: E402
import pickle  # noqa: E402

CACHE = os.path.join(HERE, "_raw_minecraft_the_end.pkl")


def load_raw(dim="minecraft:the_end"):
    """原始解析：**不丢自然方块**，保留每 chunk 256 列的地表方块名。"""
    import struct
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as fh:
            return pickle.load(fh)
    from followmap.ruins import safe_dim
    base = os.path.join(os.path.expanduser("~"), ".coordbridge", "chunks",
                        safe_dim(dim))
    HDR = struct.Struct("<IHHiiH")
    out = {}
    for rx in os.listdir(base):
        pd = os.path.join(base, rx)
        if not os.path.isdir(pd):
            continue
        for rz in os.listdir(pd):
            d = os.path.join(pd, rz)
            if not os.path.isdir(d):
                continue
            for f in os.listdir(d):
                if not f.endswith(".bin"):
                    continue
                p = os.path.join(d, f)
                with open(p, "rb") as fh:
                    raw = fh.read()
                magic, ver, fl, cx, cz, paln = HDR.unpack_from(raw, 0)
                o = HDR.size
                pal = []
                for _ in range(paln):
                    (n,) = struct.unpack_from("<H", raw, o)
                    o += 2
                    pal.append(raw[o:o + n].decode("utf-8", "replace"))
                    o += n
                idx = struct.unpack_from("<256H", raw, o + 512)
                out[(cx, cz)] = [pal[v] if v < len(pal) else "?" for v in idx]
    with open(CACHE, "wb") as fh:
        pickle.dump(out, fh)
    return out


def main():
    cx = int(sys.argv[1])
    cz = int(sys.argv[2])
    rad = int(sys.argv[3]) if len(sys.argv) > 3 else 192
    raw = load_raw()
    x0, x1 = cx - rad, cx + rad
    z0, z1 = cz - rad, cz + rad

    h = Counter()
    natural = Counter()
    chunks = 0
    for (ccx, ccz), cols in raw.items():
        bx, bz = ccx * 16, ccz * 16
        if bx + 16 < x0 or bx > x1 or bz + 16 < z0 or bz > z1:
            continue
        chunks += 1
        for v in cols:
            if v in NATURAL:
                natural[v] += 1
            else:
                h[v] += 1

    print("方框 (%d,%d)±%d  覆盖 chunk %d 个" % (cx, cz, rad, chunks))
    print("人造方块合计 %d ；自然方块 %s" % (sum(h.values()),
                                       dict(natural.most_common(4))))
    print("--- 人造方块完整用料（全部） ---")
    for k, v in h.most_common(60):
        print("   %-46s %d" % (k, v))
    best, bn = 0.0, None
    for nm, ref in REF.items():
        c = cos(h, ref)
        print("   余弦[%s] = %.3f" % (nm, c))
        if c > best:
            best, bn = c, nm
    print("=> 最相近: %s (%.3f)" % (bn, best))

    sigs = Signatures()
    for nm in sigs.types:
        ok, pur, det = sigs.passes(nm, h)
        print("   判定[%s] %s 纯度%.3f  %s"
              % (nm, "通过" if ok else "否", pur, det))


if __name__ == "__main__":
    main()
