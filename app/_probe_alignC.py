# -*- coding: utf-8 -*-
"""C 类（有指针、无独立绿区）对齐分析：按键时刻的指针位置 vs 结局。

目的：判定区是「底图上的绿段」还是别的东西 —— 用人工按键数据说话。
"""
import sys
import collections

import qtemap as Q

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")
from _probe_formB import all_episodes, seg_of   # noqa: E402

BAR = {0xB002 + i: "bar%d" % (i + 1) for i in range(9)}
BAR[0xB00B] = "rainbow"
BAR[0xB00C] = "bar10"
BAR[0xB011] = "bar11"


def kind(ep):
    sigs = [seg_of(e["text"]) for e in ep]
    sigs = [s for s in sigs if s]
    if not sigs:
        return "?"
    if any(s[3] for s in sigs):
        return "A"
    if any(s[4] for s in sigs):
        return "C"
    return "B"


def ptr_of(text):
    cells, _, _ = Q.decode(text)
    for c in cells:
        if c["cp"] == Q.POINTER:
            return c["x0"]
    return None


def main():
    evs = Q.load_events()
    keys = Q.load_keys()
    marks = Q.load_marks()
    eps = all_episodes(evs)
    print("按键记录 %d 条 / 打点 %d 条 / 局 %d" % (len(keys), len(marks), len(eps)))

    rows = []
    for ep in eps:
        k = kind(ep)
        if k != "C":
            continue
        t0, t1 = ep[0]["wall"], ep[-1]["wall"]
        ks = [x for x in keys if t0 <= x["wall"] <= t1]
        out = Q.episode_outcome(marks, t1)
        cps = collections.Counter()
        for e in ep:
            ids = [ord(c) for c in e["text"] if Q.is_bar(ord(c))]
            if ids:
                cps[ids[0]] += 1
        cp = cps.most_common(1)[0][0] if cps else 0
        # 按键时刻最近的帧
        presspts = []
        for x in ks:
            best, bd = None, 10 ** 9
            for e in ep:
                d = abs(e["wall"] - x["wall"])
                if d < bd:
                    best, bd = e, d
            if best is not None and bd <= 400:
                px = ptr_of(best["text"])
                if px is not None:
                    presspts.append((round(px, 1), x.get("name"), bd))
        xs = [ptr_of(e["text"]) for e in ep]
        xs = [v for v in xs if v is not None]
        rows.append({
            "t0": t0, "frames": len(ep), "cp": cp, "bar": BAR.get(cp, "?"),
            "out": out, "presses": len(ks), "pts": presspts,
            "xmin": min(xs) if xs else None, "xmax": max(xs) if xs else None,
        })

    print("\n%-16s %-8s %-5s %-4s %-6s %-12s %s"
          % ("t0", "底图", "帧", "结局", "按键", "指针范围", "按键时的指针 x"))
    for r in sorted(rows, key=lambda r: r["t0"]):
        print("%-16s %-8s %-5d %-4s %-6d %-12s %s"
              % (r["t0"], r["bar"], r["frames"], r["out"], r["presses"],
                 "%.0f~%.0f" % (r["xmin"], r["xmax"]) if r["xmin"] is not None else "-",
                 " ".join("%.0f(%s)" % (p[0], p[1]) for p in r["pts"][:14])))

    # 聚合：按键指针位置分布
    print("\n=== 按键时指针位置聚合（按结局）===")
    for o in ("HIT", "FAIL", "?"):
        v = [p[0] for r in rows if r["out"] == o for p in r["pts"]]
        if v:
            v.sort()
            print("  %-5s 按键 %-4d 中位 %.1f  IQR[%.1f,%.1f]  min=%.1f max=%.1f"
                  % (o, len(v), v[len(v) // 2], v[len(v) // 4],
                     v[3 * len(v) // 4], v[0], v[-1]))
        else:
            print("  %-5s 无按键数据" % o)

    print("\n=== 底图分布 ===")
    c = collections.Counter(r["bar"] for r in rows)
    for k, v in c.most_common():
        outs = collections.Counter(r["out"] for r in rows if r["bar"] == k)
        print("  %-8s %2d 局  结局 %s" % (k, v, dict(outs)))


if __name__ == "__main__":
    main()
