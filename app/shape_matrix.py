#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shape_matrix.py —— 形态 × 按键要求 × 结果 交叉盘点

在 analyze_shapes.py 的基础上：
  · 把形态"归一"（T2 / T3 / 短局），去掉指针移动造成的伪差异
  · 从局前后的 title「按下 XXX 开始」提取本局的按键要求
  · 输出交叉表，并给出"每个格子够不够 20 局"的判断
"""
import argparse
import collections
import datetime
import glob
import json
import os

def is_sep(ch):
    return 0xAC00 <= ord(ch) <= 0xD7A3

def seps_of(text):
    return [ch for ch in text if is_sep(ch)]

def cp(ch):
    return "U+%04X" % ord(ch)

def norm_shape(sep_sets):
    """把一局归一成形态名。

    关键认识（2026-10-14 实测）：分隔符的**数值**变化 = 判定指针在移动，
    不是形态差异。真正的形态由「分隔符个数 + 首尾分隔符」决定：
      · 3 段、首 B00C、尾 B001  -> T3（主体形态）
      · 2 段、首 B011           -> T2（另一种布局）
      · 2 段、尾 B001、首 B003..B00B -> T3s（疑似 T3 的极短局，帧数少）
    """
    seqs = [s for s in sep_sets if s]
    if not seqs:
        return "空帧"
    k = collections.Counter(len(s) for s in seqs).most_common(1)[0][0]
    ok = [s for s in seqs if len(s) == k]
    f = collections.Counter(s[0] for s in ok).most_common(1)[0][0]
    l = collections.Counter(s[-1] for s in ok).most_common(1)[0][0]
    if k == 3 and ord(f) == 0xB00C:
        return "T3-三段(B00C..B001)"
    if k == 2 and ord(f) == 0xB011:
        return "T2-两段(B011..)"
    if k == 2 and ord(l) == 0xB001:
        return "T3s-两段(%s..B001)" % cp(f)
    return "%d段-其他(首%s尾%s)" % (k, cp(f), cp(l))

SUCCESS = ["Good Job", "GG!", "成功"]
FAIL = ["What a pity", "Bad luck", "失败", "可惜"]
NEUTRAL = ["按下", "开始", "集中", "保持", "松懈", "挣扎", "关键时刻",
           "距离", "抓紧", "好机会", "传送", "上钩", "绿色", "紫色",
           "购买", "出售", "收杆", "收竿"]

def classify(t):
    if not t:
        return None
    if any(k in t for k in SUCCESS):
        return "成功"
    if any(k in t for k in FAIL):
        return "失败"
    if any(k in t for k in NEUTRAL):
        return None
    return None

def load(root):
    evs = []
    for f in sorted(glob.glob(os.path.join(root, "*.jsonl"))):
        sess = os.path.basename(f).replace("session-", "").replace("-world.jsonl", "")
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if "wall" in o:
                o["_sess"] = sess
                evs.append(o)
    evs.sort(key=lambda o: o["wall"])
    return evs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.fishprobe/events"))
    ap.add_argument("--gap", type=int, default=1500)
    ap.add_argument("--minframes", type=int, default=5, help="少于此帧数视为残缺局")
    args = ap.parse_args()

    evs = load(args.root)
    subs = [e for e in evs if e.get("type") == "subtitle" and (e.get("text") or "").strip()]
    titles = [(e["wall"], (e.get("text") or "").strip())
              for e in evs if e.get("type") == "title" and (e.get("text") or "").strip()]

    # 切局
    eps, cur = [], []
    for e in subs:
        if cur and e["wall"] - cur[-1]["wall"] > args.gap:
            eps.append(cur); cur = []
        cur.append(e)
    if cur:
        eps.append(cur)

    rows = []
    for ep in eps:
        t0, t1 = ep[0]["wall"], ep[-1]["wall"]
        sep_sets = [seps_of(e["text"] or "") for e in ep]
        shape = norm_shape(sep_sets)
        # 按键要求：该局前 6 秒内的「按下 XXX 开始」
        req = "?"
        for w, tx in titles:
            if t0 - 6000 <= w <= t0 + 500:
                if tx.startswith("按下"):
                    req = tx
        # 结果
        res = "未标"
        for w, tx in titles:
            if t0 - 1000 <= w <= t1 + 6000:
                r = classify(tx)
                if r:
                    res = r
        rows.append(dict(t0=t0, frames=len(ep), dur=(t1 - t0) / 1000.0,
                         shape=shape, req=req, res=res))

    valid = [r for r in rows if r["frames"] >= args.minframes]
    drop = len(rows) - len(valid)

    print("=" * 76)
    print(" 形态 × 按键要求 × 结果")
    print("=" * 76)
    print(" 全部局数 %d，其中残缺局（<%d 帧）%d，有效局 %d"
          % (len(rows), args.minframes, drop, len(valid)))

    # 交叉表：形态 × 按键
    tab = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0, 0]))
    for r in valid:
        key = (r["shape"], r["req"])
        cell = tab[r["shape"]][r["req"]]
        cell[0] += 1
        if r["res"] == "成功": cell[1] += 1
        elif r["res"] == "失败": cell[2] += 1

    print()
    print(" %-24s %-18s %4s %4s %4s" % ("形态", "按键要求", "局数", "成功", "失败"))
    print(" " + "-" * 62)
    for shape in sorted(tab, key=lambda s: -sum(v[0] for v in tab[s].values())):
        for req in sorted(tab[shape], key=lambda r: -tab[shape][r][0]):
            c = tab[shape][req]
            flag = "  <- 够" if c[0] >= 20 else ""
            print(" %-24s %-18s %4d %4d %4d%s" % (shape, req, c[0], c[1], c[2], flag))

    # 按形态汇总
    print()
    print(" 按形态汇总")
    print(" " + "-" * 62)
    agg = collections.defaultdict(lambda: [0, 0, 0])
    for r in valid:
        a = agg[r["shape"]]
        a[0] += 1
        if r["res"] == "成功": a[1] += 1
        elif r["res"] == "失败": a[2] += 1
    for shape in sorted(agg, key=lambda s: -agg[s][0]):
        a = agg[shape]
        print(" %-24s 合计 %3d 局 (成功 %d / 失败 %d / 未知 %d)"
              % (shape, a[0], a[1], a[2], a[0] - a[1] - a[2]))

    # 按键要求汇总
    print()
    print(" 按键要求出现次数（有效局）")
    print(" " + "-" * 62)
    rc = collections.Counter(r["req"] for r in valid)
    for k, v in rc.most_common():
        print("   %-20s %d" % (k, v))

    print("=" * 76)


if __name__ == "__main__":
    main()
