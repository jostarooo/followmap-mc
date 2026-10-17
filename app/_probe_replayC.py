# -*- coding: utf-8 -*-
"""C 形态自动按键「回放仿真」：用 Java 侧的同一条逻辑跑真实帧，估算命中率。

逻辑与 Geom/AutoFish.decideC 对齐：
  off   = 246 - barW(bar)
  zone  = [off + 图内色段起, off + 图内色段止]（题目色，缺省 green）
  判定  = 指针中心 (ptr+2) ∈ [z0-m, z1+m]
  限流  = 两次按间隔 >= cadence_ms（帧距 ~50ms）
"""
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
import qtemap as Q  # noqa: E402

LOG = os.path.join(os.path.expanduser("~"), ".fishauto", "log")
RIGHT_EDGE = 246
POINTER_HALF = 2
BARW = {0xB002: 184, 0xB003: 184, 0xB004: 184, 0xB005: 184, 0xB006: 184,
        0xB007: 184, 0xB008: 184, 0xB009: 184, 0xB00A: 184, 0xB00B: 120}
SEGS = {
    0xB002: [(84, 100, "green")], 0xB003: [(52, 68, "green")], 0xB004: [(116, 132, "green")],
    0xB005: [(84, 92, "green"), (132, 140, "green")],
    0xB006: [(4, 12, "green"), (60, 68, "green"), (108, 116, "green"), (140, 148, "green")],
    0xB007: [(68, 76, "green"), (84, 92, "green"), (100, 108, "green")],
    0xB008: [(156, 160, "green")], 0xB009: [(84, 88, "green")],
    0xB00A: [(4, 8, "green"), (176, 180, "green")],
    0xB00B: [(4, 20, "red"), (20, 36, "orange"), (36, 52, "yellow"), (52, 68, "green"),
             (68, 84, "lightblue"), (84, 100, "blue"), (100, 116, "purple")],
}
W2C = [("深蓝", "blue"), ("浅蓝", "lightblue"), ("青色", "lightblue"), ("红色", "red"),
       ("橙色", "orange"), ("黄色", "yellow"), ("绿色", "green"), ("紫色", "purple")]


def colorof(t):
    if not t:
        return "green"
    for k, v in W2C:
        if k in t:
            return v
    return "green"


def load():
    tab = Q.build_table()[0]
    games = []
    for f in sorted(glob.glob(os.path.join(LOG, "session-*.jsonl"))):
        rows = []
        for line in open(f, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
        g, pending = None, None
        for r in rows:
            t = r.get("type")
            tx = r.get("title") or ""
            if t in ("notice", "qte_begin") and any(k in tx for k in ("红", "橙", "黄", "绿", "青", "蓝", "紫")):
                if "水母" not in tx and "caught" not in (r.get("text") or ""):
                    pending = tx
            if t == "qte_begin":
                g = {"color": pending, "frames": [], "end": None, "game": r.get("game")}
                games.append(g)
                pending = None
            elif t == "frame" and g is not None:
                g["frames"].append(r)
            elif t == "qte_end" and g is not None:
                g["end"] = r
    out = []
    for G in games:
        fr = []
        bar = 0
        for r in G["frames"]:
            x, p, b, ok = 0, None, 0, True
            for ch in r["sub"]:
                cp = ord(ch)
                a = tab.get(cp)
                if a is None:
                    ok = False
                    break
                if p is None and cp == 0xB001:
                    p = x
                if b == 0 and 0xB002 <= cp <= 0xB00B:
                    b = cp
                x += a
            if not ok:
                continue
            if b:
                bar = b
            if p is not None:
                fr.append((r.get("wall"), p))
        if bar and fr:
            out.append({"bar": bar, "fr": fr, "col": colorof(G["color"]),
                        "res": (G["end"] or {}).get("result"), "game": G["game"], "tx": G["color"]})
    return out


def main():
    cadence = int(sys.argv[sys.argv.index("--cadence") + 1]) if "--cadence" in sys.argv else 130
    margin = int(sys.argv[sys.argv.index("--margin") + 1]) if "--margin" in sys.argv else 2
    C = load()
    print("C 局 %d 个   cadence=%dms margin=%d  RIGHT_EDGE=%d" % (len(C), cadence, margin, RIGHT_EDGE))
    print()
    print("%-4s %-8s %-10s %-5s %-22s %s" % ("局", "底图", "目标色", "结果", "自动按键时机(ptr@zone)", "是否落在色段内"))
    fired_in = 0
    fired_total = 0
    ret = collections.Counter()
    for g in C:
        segs = [(s, e) for s, e, c in SEGS[g["bar"]] if c == g["col"]]
        off = RIGHT_EDGE - BARW[g["bar"]]
        zones = [(off + s, off + e) for s, e in segs]
        presses, last = [], -10 ** 9
        for wall, p in g["fr"]:
            if wall - last < cadence:
                continue
            mid = p + POINTER_HALF
            if any(z0 - margin <= mid <= z1 + margin for z0, z1 in zones):
                presses.append((p, [z for z in zones]))
                last = wall
        inside = [p for p, zs in presses if any(z0 <= p + POINTER_HALF <= z1 for z0, z1 in zs)]
        fired_total += 1
        if presses and len(inside) == len(presses):
            fired_in += 1
        ret[g["res"]] += 1
        ztxt = " ".join("%d-%d" % z for z in zones)
        print("%-4s %-8s %-10s %-5s %-22s %s"
              % (g["game"], "%04X" % g["bar"], g["col"], g["res"],
                 ("%d次,首ptr=%d" % (len(presses), presses[0][0])) if presses else "不按",
                 ("全部在段内 [%s]" % ztxt) if presses and len(inside) == len(presses)
                 else ("部分在段内" if inside else "全在段外")))
    print()
    print("会按键的局: %d/%d   其中「按下的每一帧都在色段内」: %d" % (fired_total, len(C), fired_in))
    print("结果分布: %s" % dict(ret))


if __name__ == "__main__":
    main()
