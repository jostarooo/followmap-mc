# -*- coding: utf-8 -*-
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xaero_region as XR

V = r"D:/config/game/mc/pcl2/.minecraft/versions/1.20.4-Fabric 0.16.14"
WM = os.path.join(V, "XaeroWorldMap", "Multiplayer_mcfkcs.com")

tests = [
    ("null", "mw$default", "-10_3.zip"),
    ("null", "mw$default", "-13_23.zip"),
    ("minecraft$ziyuan", "mw$default", "-22_27.zip"),
    ("DIM1", "mw$default", "-10_-94.zip"),
    ("minecraft$spawn", "mw$default", "0_0.zip"),
]
for dim, mw, f in tests:
    p = os.path.join(WM, dim, mw, f)
    if not os.path.exists(p):
        print("缺失", p); continue
    size = os.path.getsize(p)
    try:
        rd = XR.parse_region_file(p)
        from collections import Counter
        c = Counter(v.split("[")[0] for v in rd.blocks.values())
        top = ", ".join("%s:%d" % (k.replace("minecraft:", ""), v) for k, v in c.most_common(5))
        print("OK  %-22s %-18s ver=%s chunks=%d blocks=%d | %s" % (dim, f, rd.version, rd.chunks_seen, len(rd.blocks), top))
    except Exception as e:
        print("ERR %-22s %-18s -> %s: %s" % (dim, f, type(e).__name__, e))
        traceback.print_exc(limit=3)
