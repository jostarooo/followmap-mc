# -*- coding: utf-8 -*-
"""看 bars/*.png 的真实像素：每张底图上绿区画在哪、bar11 又是什么。"""
import io
import os
import re
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zipraw  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

GAME = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14"


def active_packs():
    opt = os.path.join(GAME, "options.txt")
    m = re.search(r'^resourcePacks:(\[.*\])\s*$',
                  open(opt, encoding="utf-8").read(), re.M)
    names = [] if not m else __import__("json").loads(m.group(1))
    out = []
    for n in names:
        if n.startswith("file/"):
            p = os.path.join(GAME, "resourcepacks", n[5:])
            if os.path.exists(p):
                out.append(p)
    return out


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else None
    packs = active_packs()
    target = None
    for p in reversed(packs):
        d = zipraw.read_raw(p)
        if any(k.startswith("assets/customfishing/textures/font/bars/") for k in d):
            target = (p, d)
            break
    if not target:
        raise SystemExit("[X] 找不到含 bars 图集的包")
    pack, d = target
    print("包: %s\n" % os.path.basename(pack))

    keys = sorted(k for k in d
                  if k.startswith("assets/customfishing/textures/font/bars/")
                  and k.endswith(".png"))
    if name:
        keys = [k for k in keys if name in k]
    for k in keys:
        b = d[k]
        im = Image.open(io.BytesIO(b)).convert("RGBA")
        a = np.array(im).astype(int)
        w, h = im.size
        R, G, B, A = a[:, :, 0], a[:, :, 1], a[:, :, 2], a[:, :, 3]
        solid = A > 128
        green = solid & (G > 90) & (G - R > 40) & (G - B > 40)
        gcols = np.where(green.any(axis=0))[0]
        scols = np.where(solid.any(axis=0))[0]
        rows = np.where(solid.any(axis=1))[0]

        def rng(idx):
            if len(idx) == 0:
                return "(无)"
            out, s, prev = [], idx[0], idx[0]
            for v in idx[1:]:
                if v == prev + 1:
                    prev = v
                    continue
                out.append("%d-%d" % (s, prev))
                s = prev = v
            out.append("%d-%d" % (s, prev))
            return ",".join(out)

        # 绿色列的连续区间（可能多段）
        segs = []
        if len(gcols):
            s = prev = gcols[0]
            for v in gcols[1:]:
                if v <= prev + 2:
                    prev = v
                    continue
                segs.append((s, prev))
                s = prev = v
            segs.append((s, prev))
        segtxt = " ".join("[%d..%d w=%d]" % (s, e, e - s + 1) for s, e in segs) or "(无)"

        # 顶行 / 中行的颜色摘要（每 16px 采样一列）
        y = int(rows[len(rows) // 2]) if len(rows) else 0
        pat = []
        for x in range(0, w, 16):
            if not solid[y, x]:
                pat.append("..")
            else:
                c = (R[y, x], G[y, x], B[y, x])
                if green[y, x]:
                    pat.append("GG")
                elif c[0] > 200 and c[1] > 200 and c[2] > 200:
                    pat.append("ww")
                else:
                    pat.append("%02x" % (c[0] >> 4) + "%02x" % (c[1] >> 4))
        print("%-26s %3dx%-3d  实体行=%s  绿列: %s"
              % (os.path.basename(k), w, h, rng(rows)[:24], segtxt))
        print("     中行(y=%d) 采样: %s" % (y, " ".join(pat)))


if __name__ == "__main__":
    main()
