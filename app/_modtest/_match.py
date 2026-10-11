# -*- coding: utf-8 -*-
"""把用户截图与若干候选中心的渲染图做「陆地掩码 IoU / 归一化互相关」打分。

不靠眼睛，直接给数字：哪个中心才是截图所在位置。
"""
import os
import sys

from PIL import Image
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SHOT = r"C:\Users\jostaro\.workbuddy\clipboard-images\clipboard-2026-10-10T15-51-56-983Z-439f07c9.png"


def land_mask(img, hh=115):
    """黄绿色地表 -> 1，其余 -> 0。hh 以上的 HUD 区强制置 0。"""
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    m = ((r + g) / 2 > 90) & (b < 200) & ((r - b) > 25) & (np.abs(r - g) < 30)
    m = m.astype(np.uint8)
    m[:hh, :] = 0
    return m


def score(a, b):
    inter = int(np.logical_and(a, b).sum())
    uni = int(np.logical_or(a, b).sum())
    iou = inter / uni if uni else 0.0
    # 皮尔逊相关
    x = a.astype(np.float32).ravel()
    y = b.astype(np.float32).ravel()
    x = x - x.mean()
    y = y - y.mean()
    d = (np.linalg.norm(x) * np.linalg.norm(y))
    corr = float((x * y).sum() / d) if d else 0.0
    return iou, corr


def main():
    ref = Image.open(SHOT)
    mref = land_mask(ref)
    print("截图陆地占比 %.3f  (%d/%d)" % (mref.mean(), mref.sum(), mref.size))
    rows = []
    for p in sorted(os.listdir(HERE)):
        if not p.startswith("_shot_") and not p.startswith("_cmp_"):
            continue
        img = Image.open(os.path.join(HERE, p))
        m = land_mask(img, hh=0)
        if m.shape != mref.shape:
            m = np.asarray(Image.fromarray(m * 255).resize(
                (mref.shape[1], mref.shape[0]), Image.NEAREST))
            m = (m > 127).astype(np.uint8)
        iou, corr = score(mref, m)
        rows.append((iou, corr, p, m.mean()))
    rows.sort(reverse=True)
    print("%-26s %7s %8s %8s" % ("文件", "IoU", "相关", "陆地占比"))
    for iou, corr, p, lr in rows:
        print("%-26s %7.3f %8.3f %8.3f" % (p, iou, corr, lr))


if __name__ == "__main__":
    main()
