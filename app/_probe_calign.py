# -*- coding: utf-8 -*-
"""C 形态几何标定：对每个 C 局打印「底图色带（三种对齐假设）+ 指针轨迹」，
找出「指针行程」与「色带」的真正对应关系。

三种假设：
  L  左对齐：屏幕 x = 图内 x            （off = 0）
  R  右对齐：屏幕 x = (256-内容宽)+图内 x
  M  居中：  屏幕 x = (256-内容宽)/2 + 图内 x
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

NAME2CP = {"bar1": 0xB002, "bar2": 0xB003, "bar3": 0xB004, "bar4": 0xB005,
           "bar5": 0xB006, "bar6": 0xB007, "bar7": 0xB008, "bar8": 0xB009,
           "bar9": 0xB00A, "bar_rainbow": 0xB00B, "bar10": 0xB00C, "bar11": 0xB011}

# 像素实测（图内 1x 坐标）：name -> [(start,end,name), ...]
BANDS = {
    "bar1": [(4, 20, "red"), (20, 36, "orange"), (36, 52, "yellow"), (52, 68, "green2"),
             (68, 84, "yellow"), (84, 100, "green"), (100, 116, "yellow"),
             (116, 132, "orange"), (132, 180, "red")],
    "bar2": [(4, 20, "red"), (20, 36, "orange"), (36, 52, "yellow"), (52, 68, "green"),
             (68, 84, "yellow"), (84, 100, "orange"), (100, 180, "red")],
    "bar3": [(4, 84, "red"), (84, 100, "orange"), (100, 116, "yellow"), (116, 132, "green"),
             (132, 148, "yellow"), (148, 164, "orange"), (164, 180, "red")],
    "bar4": [(4, 52, "red"), (52, 68, "orange"), (68, 84, "yellow"), (84, 92, "green"),
             (92, 100, "yellow"), (100, 108, "orange"), (108, 116, "red"),
             (116, 124, "orange"), (124, 132, "yellow"), (132, 140, "green"),
             (140, 148, "yellow"), (148, 156, "orange"), (156, 180, "red")],
    "bar5": [(4, 12, "green"), (12, 28, "red"), (28, 44, "orange"), (44, 60, "yellow"),
             (60, 68, "green"), (68, 76, "yellow"), (76, 84, "orange"), (84, 92, "red"),
             (92, 100, "orange"), (100, 108, "yellow"), (108, 116, "green"),
             (116, 124, "yellow"), (124, 132, "orange"), (132, 140, "red"),
             (140, 148, "green"), (148, 156, "yellow"), (156, 180, "red")],
    "bar6": [(4, 20, "yellow"), (20, 36, "orange"), (36, 52, "yellow"), (52, 68, "orange"),
             (68, 76, "green"), (76, 84, "red"), (84, 92, "green"), (92, 100, "red"),
             (100, 108, "green"), (108, 116, "red"), (116, 132, "yellow"),
             (132, 148, "orange"), (148, 164, "yellow"), (164, 180, "orange")],
    "bar7": [(4, 140, "red"), (140, 148, "orange"), (148, 156, "red"), (156, 160, "green"),
             (160, 168, "red"), (168, 180, "yellow")],
    "bar8": [(4, 68, "red"), (68, 80, "orange"), (80, 84, "yellow"), (84, 88, "green"),
             (88, 92, "yellow"), (92, 108, "orange"), (108, 180, "red")],
    "bar9": [(4, 8, "green"), (8, 176, "red"), (176, 180, "green")],
    "bar_rainbow": [(4, 20, "red"), (20, 36, "orange"), (36, 52, "yellow"), (52, 68, "green"),
                    (68, 84, "teal"), (84, 100, "blue"), (100, 116, "purple")],
    "bar10": [(4, 159, "red")],
    "bar11": [(1, 221, "orange")],
}
CONTENT_W = {"bar1": 184, "bar2": 184, "bar3": 184, "bar4": 184, "bar5": 184,
             "bar6": 184, "bar7": 184, "bar8": 184, "bar9": 184, "bar_rainbow": 120,
             "bar10": 163, "bar11": 222}


def load_games(nlast=1):
    fs = sorted(glob.glob(os.path.join(LOG, "session-*.jsonl")))[-nlast:]
    rows = []
    for f in fs:
        rows += [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
    games, cur = [], None
    for r in rows:
        t = r.get("type")
        if t == "qte_begin":
            cur = {"begin": r, "frames": [], "end": None}
            games.append(cur)
        elif t == "frame" and cur is not None:
            cur["frames"].append(r)
        elif t == "qte_end" and cur is not None:
            cur["end"] = r
            cur = None
    return games


def analyze(g):
    tab = Q.build_table()[0]
    ptrs, bar = [], 0
    for fr in g["frames"]:
        x = 0
        p = None
        b = 0
        ok = True
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
    return bar, ptrs


def main():
    nlast = 1
    if "--last" in sys.argv:
        nlast = int(sys.argv[sys.argv.index("--last") + 1])
    games = load_games(nlast)
    cp2name = {v: k for k, v in NAME2CP.items()}
    rows = []
    for g in games:
        bar, ptrs = analyze(g)
        if not bar or not ptrs:
            continue
        nm = cp2name.get(bar)
        if nm is None or nm not in BANDS:
            continue
        rows.append((g, nm, ptrs))

    forms = collections.Counter()
    for g, nm, ptrs in rows:
        f = collections.Counter(x.get("form") for x in g["frames"] if x.get("form"))
        forms[f.most_common(1)[0][0] if f else "?"] += 1
    print("局数 %d，其中 C 类候选 %d，形态分布 %s" % (len(games), len(rows), dict(forms)))

    print("\n%-4s %-12s %-5s %-14s %-24s %s"
          % ("局", "底图", "结果", "指针行程", "指针 vs 绿色带（左对齐）", "命中帧"))
    for g, nm, ptrs in rows:
        greens = [(s, e) for s, e, c in BANDS[nm] if c == "green"]
        pmin, pmax = min(ptrs), max(ptrs)
        left = " ".join("[%d-%d]%s" % (s, e, "★" if any(s <= p <= e for p in ptrs) else "×")
                        for s, e in greens)
        hitframes = sum(1 for p in ptrs if any(s - 6 <= p <= e + 6 for s, e in greens))
        print("%-4s %-12s %-5s %-14s %-24s %d/%d"
              % (g["begin"].get("game"), nm, (g["end"] or {}).get("result"),
                 "%d..%d(%d)" % (pmin, pmax, pmax - pmin), left, hitframes, len(ptrs)))

    # 逐局细看：指针行程 vs 内容宽
    print("\n=== 指针行程 vs 底图内容宽 ===")
    print("%-4s %-12s %-16s %-10s %s" % ("局", "底图", "指针行程", "内容宽", "行程/内容"))
    for g, nm, ptrs in rows:
        pmin, pmax = min(ptrs), max(ptrs)
        cw = CONTENT_W[nm]
        print("%-4s %-12s %-16s %-10d %.2f"
              % (g["begin"].get("game"), nm, "%d..%d" % (pmin, pmax), cw,
                 (pmax - pmin) / float(cw)))


if __name__ == "__main__":
    main()
