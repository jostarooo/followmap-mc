# -*- coding: utf-8 -*-
"""验证：C 类的判定区 = 底图 barN.png 上的绿色段（屏幕 x = 图内 x，因 advance=256=图宽）。

输出：每个 C 类局的底图、绿段区间、指针 x 轨迹、指针落在绿段内的帧比例。
"""
import io
import json
import os
import re
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qtemap as Q  # noqa: E402
import zipraw  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
GAME = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14"
CP2BAR = {0xB002 + i: "bar%d.png" % (i + 1) for i in range(9)}   # B002..B00A -> bar1..bar9
CP2BAR[0xB00B] = "bar_rainbow.png"
CP2BAR[0xB00C] = "bar10.png"
CP2BAR[0xB011] = "bar11.png"


def load_pack():
    opt = open(os.path.join(GAME, "options.txt"), encoding="utf-8").read()
    names = json.loads(re.search(r'^resourcePacks:(\[.*\])\s*$', opt, re.M).group(1))
    packs = [os.path.join(GAME, "resourcepacks", n[5:])
             for n in names if n.startswith("file/")]
    for p in reversed(packs):
        d = zipraw.read_raw(p)
        if any(k.startswith("assets/customfishing/textures/font/bars/") for k in d):
            return d
    raise SystemExit("[X] 找不到 bars 图集")


def green_segs(png_bytes, gmin=150, rmax=130, bmax=130):
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    a = np.array(im).astype(int)
    R, G, B, A = a[:, :, 0], a[:, :, 1], a[:, :, 2], a[:, :, 3]
    g = (A > 128) & (G >= gmin) & (R <= rmax) & (B <= bmax)
    cols = np.where(g.any(axis=0))[0]
    if not len(cols):
        return [], im.size
    segs, s, prev = [], cols[0], cols[0]
    for v in cols[1:]:
        if v <= prev + 2:
            prev = v
            continue
        segs.append((int(s), int(prev)))
        s = prev = v
    segs.append((int(s), int(prev)))
    return segs, im.size


def segs_of(cp, cache, bars):
    fn = CP2BAR.get(cp)
    if not fn or fn not in bars:
        return [], None
    if fn not in cache:
        cache[fn] = green_segs(bars[fn])
    return cache[fn][0], cache[fn][1]


def main():
    d = load_pack()
    bars = {k.split("/")[-1]: d[k] for k in d
            if k.startswith("assets/customfishing/textures/font/bars/")
            and k.endswith(".png")}
    # 先看全部底图的绿段
    print("=== 底图绿段（图内 x，1:1 映射到屏幕）===")
    for cp in sorted(CP2BAR):
        segs, size = segs_of(cp, {}, bars)
        print("  U+%04X %-18s %s  绿段=%s"
              % (cp, CP2BAR[cp], "%dx%d" % size if size else "-",
                 " ".join("[%d..%d w=%d]" % (s, e, e - s + 1) for s, e in segs) or "(无)"))

    evs = Q.load_events()
    from _probe_formB import all_episodes, seg_of
    eps = all_episodes(evs)
    C = []
    for ep in eps:
        sigs = [seg_of(e["text"]) for e in ep]
        sigs = [s for s in sigs if s]
        if not sigs or any(s[3] for s in sigs) or not any(s[4] for s in sigs):
            continue
        C.append(ep)

    cache = {}
    print("\n=== C 类逐局：指针 vs 底图绿段 ===")
    print("%-16s %-6s %-9s %-28s %-12s %s"
          % ("t0", "帧", "底图", "绿段(屏幕 x)", "指针x 范围", "in-zone 比例"))
    for ep in sorted(C, key=lambda e: e[0]["wall"]):
        bars_used = {}
        for e in ep:
            ids = [ord(c) for c in e["text"] if Q.is_bar(ord(c))]
            if ids:
                bars_used[ids[0]] = bars_used.get(ids[0], 0) + 1
        cp = max(bars_used, key=bars_used.get)
        segs, size = segs_of(cp, cache, bars)
        xs = []
        inz = 0
        pts = 0
        for e in ep:
            cells, seps, total = Q.decode(e["text"])
            ptr = None
            for c in cells:
                if c["cp"] == Q.POINTER:
                    ptr = c["x0"]
            if ptr is None:
                continue
            xs.append(ptr)
            pts += 1
            if any(s - Q.POINTER_W <= ptr <= e2 for s, e2 in segs):
                inz += 1
        print("%-16s %-6d U+%04X   %-28s %-12s %.1f%%"
              % (ep[0]["wall"], len(ep), cp,
                 " ".join("[%d-%d]" % s for s in segs) or "(无)",
                 "%.0f~%.0f" % (min(xs), max(xs)) if xs else "-",
                 100.0 * inz / pts if pts else 0))


if __name__ == "__main__":
    main()
