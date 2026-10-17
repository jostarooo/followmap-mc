# -*- coding: utf-8 -*-
"""C 形态对齐常数标定：跨全部会话，取每个 C 组的「指针末值」= 玩家按下瞬间，
反解「底图内容右缘」O。用 8 个颜色题/绿色题分组求共识。
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
import qtemap as Q  # noqa: E402

LOG = os.path.join(os.path.expanduser("~"), ".fishauto", "log")
BARW = {0xB002: 184, 0xB003: 184, 0xB004: 184, 0xB005: 184, 0xB006: 184,
        0xB007: 184, 0xB008: 184, 0xB009: 184, 0xB00A: 184, 0xB00B: 120}
BANDS = {
    0xB002: [(84, 100, "green")], 0xB003: [(52, 68, "green")], 0xB004: [(116, 132, "green")],
    0xB005: [(84, 92, "green"), (132, 140, "green")],
    0xB006: [(4, 12, "green"), (60, 68, "green"), (108, 116, "green"), (140, 148, "green")],
    0xB007: [(68, 76, "green"), (84, 92, "green"), (100, 108, "green")],
    0xB008: [(156, 160, "green")], 0xB009: [(84, 88, "green")],
    0xB00A: [(4, 8, "green"), (176, 180, "green")],
    0xB00B: [(4, 20, "red"), (20, 36, "orange"), (36, 52, "yellow"), (52, 68, "green"),
             (68, 84, "lightblue"), (84, 100, "blue"), (100, 116, "purple")],
}
W2C = [("深蓝", "blue"), ("浅蓝", "lightblue"), ("青色", "lightblue"),
       ("红色", "red"), ("橙色", "orange"), ("黄色", "yellow"),
       ("绿色", "green"), ("紫色", "purple")]


def colorof(t):
    if not t:
        return "green"
    for k, v in W2C:
        if k in t:
            return v
    return "green"


def main():
    tab = Q.build_table()[0]
    allg = []
    for f in sorted(glob.glob(os.path.join(LOG, "session-*.jsonl"))):
        rows = []
        for line in open(f, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
        g = None
        pending = None
        for r in rows:
            t = r.get("type")
            txt = (r.get("title") or "")
            if t in ("notice", "qte_begin"):
                if any(k in txt for k in ("红", "橙", "黄", "绿", "青", "蓝", "紫")):
                    # 排除「You caught a(n) 蓝水母」这类结果文本
                    if "水母" not in txt and "caught" not in (r.get("text") or ""):
                        pending = txt
            if t == "qte_begin":
                g = {"game": r.get("game"), "color": pending, "frames": [], "end": None,
                     "sess": os.path.basename(f)}
                allg.append(g)
                pending = None
            elif t == "frame" and g is not None:
                g["frames"].append(r)
            elif t == "qte_end" and g is not None:
                g["end"] = r

    C = []
    for G in allg:
        ptrs, bar = [], 0
        for fr in G["frames"]:
            x, p, b, ok = 0, None, 0, True
            for ch in fr["sub"]:
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
                ptrs.append(p)
        if bar and ptrs:
            C.append({"bar": bar, "col": colorof(G["color"]), "ptrs": ptrs,
                      "res": (G["end"] or {}).get("result"), "tx": G["color"],
                      "game": G["game"], "sess": G["sess"]})

    # 合并被切碎的连续局：同底图 + 同目标色 + 指针首尾相接
    merged = []
    for c in C:
        if merged:
            m = merged[-1]
            if (m["bar"] == c["bar"] and m["col"] == c["col"]
                    and c["ptrs"][0] <= m["ptrs"][-1] + 12):
                m["ptrs"] += c["ptrs"]
                m["res"] = c["res"]
                m["ids"].append(c["game"])
                continue
        merged.append({"bar": c["bar"], "col": c["col"], "ptrs": list(c["ptrs"]),
                       "res": c["res"], "tx": c["tx"], "ids": [c["game"]]})

    print("合并后 %d 组（原 %d 局）" % (len(merged), len(C)))
    print("%-14s %-8s %-10s %-5s %-14s %-11s %s"
          % ("局", "底图", "目标色", "结果", "指针范围", "反解O(low,high)", "提示"))
    impl = []
    for m in merged:
        bar, col = m["bar"], m["col"]
        last = m["ptrs"][-1]
        segs = [(s, e) for s, e, cc in BANDS[bar] if cc == col]
        ids = "/".join(str(i) for i in m["ids"])
        if not segs:
            print("%-14s %-8s %-10s %-5s %-14s %-11s %s"
                  % (ids, "%04X" % bar, col, m["res"],
                     "%d..%d" % (min(m["ptrs"]), last), "-", m["tx"]))
            continue
        best = None
        for s, e in segs:
            d = 0 if s <= last <= e else min(abs(last - s), abs(last - e))
            # last 落在段内 -> O 的可行区间 [last+W-e, last+W-s]
            lo, hi = last + BARW[bar] - e, last + BARW[bar] - s
            if best is None or d < best[0]:
                best = (d, lo, hi)
        d, lo, hi = best
        impl.append((lo, hi))
        print("%-14s %-8s %-10s %-5s %-14s %-11s %s"
              % (ids, "%04X" % bar, col, m["res"],
                 "%d..%d" % (min(m["ptrs"]), last), "%d,%d" % (lo, hi), m["tx"]))

    if impl:
        # 正确判据：末帧只是"按下后不久"，且多绿段底图可以按在任一段上
        #  → 每组取「到最近目标色段的距离」，再扫 O + 容差
        raw = []
        for m in merged:
            bar, col = m["bar"], m["col"]
            segs = [(s, e) for s, e, cc in BANDS[bar] if cc == col]
            if segs:
                raw.append((bar, m["ptrs"][-1], segs))
        print()
        print("—— 扫描 O（判据：末帧到最近目标色段 ≤ tol）——")
        for tol in (0, 4, 8):
            best = []
            for O in range(238, 257):
                n = 0
                for bar, last, segs in raw:
                    off = O - BARW[bar]
                    d = min(0 if off + s <= last <= off + e
                            else min(abs(last - (off + s)), abs(last - (off + e)))
                            for s, e in segs)
                    if d <= tol:
                        n += 1
                best.append((n, O))
            mx = max(b[0] for b in best)
            ok = [o for n, o in best if n == mx]
            print("  tol=%-2d  最佳 %d/%d  O=%s" % (tol, mx, len(raw), ok))


if __name__ == "__main__":
    main()
