#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_shapes.py —— 方块传说钓鱼采集数据：形态聚类与样本量盘点

做什么：
  1) 把散落在各 session 文件里的 subtitle 帧按时间间隔切成「局」
  2) 每局提取：进度条形态结构（分隔符模板）、帧数、时长、结果文本
  3) 按形态分组，统计「成功 / 失败 / 未知」样本量
  4) 给出"够不够用"的结论（每种形态是否够 20 局）

用法：
  python analyze_shapes.py [--root ~/.fishprobe/events] [--gap 1500] [--detail]
"""
import argparse
import glob
import json
import os
from collections import Counter, defaultdict

# ---------------------------------------------------------------- 基础工具

def is_sep(ch):
    """韩文音节区 = 进度条的分隔符/指针标记"""
    return 0xAC00 <= ord(ch) <= 0xD7A3

def is_glyph(ch):
    """私用区 = 宽度字模（画像素块用）"""
    return 0xE000 <= ord(ch) <= 0xF8FF

def seps_of(text):
    return [ch for ch in text if is_sep(ch)]

def glyphs_of(text):
    return [ch for ch in text if is_glyph(ch)]

def codepoint(ch):
    return "U+%04X" % ord(ch)

def shape_template(sep_lists):
    """
    把一局里所有帧的分隔符序列归一化成"结构模板"。
    恒定出现的分隔符原样保留；会变化的写 *。
    例：[(B011,B00D),(B011,B00E)] -> "B011 *"
    返回 (模板字符串, 变体数)
    """
    if not sep_lists:
        return ("<无>", 0)
    n = max(len(s) for s in sep_lists)
    out = []
    for i in range(n):
        vals = set(codepoint(s[i]) for s in sep_lists if len(s) > i)
        if len(vals) == 1:
            out.append(next(iter(vals)).replace("U+", ""))
        else:
            out.append("*")
    return (" ".join(out), len(sep_lists))

# ---------------------------------------------------------------- 读数据

def load_events(root):
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
            if "wall" not in o:
                continue
            o["_sess"] = sess
            evs.append(o)
    evs.sort(key=lambda o: o["wall"])
    return evs

def split_episodes(subs, gap_ms):
    eps, cur = [], []
    for e in subs:
        if cur and e["wall"] - cur[-1]["wall"] > gap_ms:
            eps.append(cur)
            cur = []
        cur.append(e)
    if cur:
        eps.append(cur)
    return eps

# ---------------------------------------------------------------- 结果判定

SUCCESS = ["Good Job", "GG!", "Good!", "不错", "成功"]
FAIL    = ["What a pity", "Bad luck", "失败", "可惜"]
# 过程提示（不算结果）
NEUTRAL = ["按下", "开始", "集中", "保持", "松懈", "挣扎", "关键时刻",
           "距离", "抓紧", "好机会", "传送", "上钩", "绿色", "紫色",
           "购买", "出售"]

def classify(text):
    if not text:
        return None
    if any(k in text for k in SUCCESS):
        return "成功"
    if any(k in text for k in FAIL):
        return "失败"
    if any(k in text for k in NEUTRAL):
        return None
    return None

# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.fishprobe/events"))
    ap.add_argument("--gap", type=int, default=1500, help="帧间隔超过该毫秒数视为新一局")
    ap.add_argument("--detail", action="store_true", help="打印每局明细")
    args = ap.parse_args()

    evs = load_events(args.root)
    subs = [e for e in evs if e.get("type") == "subtitle" and (e.get("text") or "").strip()]
    eps = split_episodes(subs, args.gap)

    # 结果文本索引： (wall, text) 里所有非字形 title
    titles = [(e["wall"], (e.get("text") or "").strip())
              for e in evs if e.get("type") == "title" and (e.get("text") or "").strip()]

    rows = []
    for ep in eps:
        t0, t1 = ep[0]["wall"], ep[-1]["wall"]
        sep_lists = [seps_of(e["text"] or "") for e in ep]
        tmpl, _ = shape_template(sep_lists)
        # 该局窗口内（开始前 3s ~ 结束后 6s）出现的结果文本
        res = []
        for w, tx in titles:
            if t0 - 3000 <= w <= t1 + 6000:
                r = classify(tx)
                if r:
                    res.append(r)
        result = res[-1] if res else "未标"
        rows.append(dict(t0=t0, t1=t1, frames=len(ep), dur=(t1 - t0) / 1000.0,
                         tmpl=tmpl, result=result, sess=ep[0]["_sess"]))

    # ---- 输出 ----
    print("=" * 72)
    print(" 形态聚类 · 样本量盘点")
    print("=" * 72)
    print(" subtitle 局数 : %d（总帧 %d）" % (len(rows), len(subs)))

    by = defaultdict(lambda: defaultdict(int))
    dur_by = defaultdict(list)
    for r in rows:
        by[r["tmpl"]][r["result"]] += 1
        by[r["tmpl"]]["_n"] += 1
        dur_by[r["tmpl"]].append(r["dur"])

    print()
    print(" %-22s %5s %5s %5s %5s   %s" % ("形态模板", "总数", "成功", "失败", "未知", "平均时长"))
    print(" " + "-" * 68)
    for tmpl, d in sorted(by.items(), key=lambda kv: -kv[1]["_n"]):
        n = d["_n"]
        ds = dur_by[tmpl]
        print(" %-22s %5d %5d %5d %5d   %.1fs" %
              (tmpl, n, d["成功"], d["失败"], d["未标"], sum(ds) / len(ds)))

    print()
    print(" 说明：模板里的 B0xx = 分隔符码点（恒定则原样显示），* = 该位置会变（指针移动）")
    print("       单段型              = 只有 1 个分隔符（极短局/异常帧）")

    if args.detail:
        print()
        print("=" * 72)
        print(" 逐局明细")
        print("=" * 72)
        print("  #  开始时间          时长   帧数  形态模板              结果  会话")
        for i, r in enumerate(rows, 1):
            import datetime
            ts = datetime.datetime.fromtimestamp(r["t0"] / 1000).strftime("%m-%d %H:%M:%S")
            print(" %3d %s %6.1fs %5d  %-22s %-4s %s" %
                  (i, ts, r["dur"], r["frames"], r["tmpl"], r["result"], r["sess"][-8:]))

    # ---- 结论 ----
    print()
    print("=" * 72)
    TARGET = 20
    ok, need = [], []
    for tmpl, d in sorted(by.items(), key=lambda kv: -kv[1]["_n"]):
        if d["_n"] >= TARGET:
            ok.append((tmpl, d["_n"]))
        else:
            need.append((tmpl, d["_n"], TARGET - d["_n"]))
    if ok:
        print(" [够用] " + " | ".join("%s %d局" % (t, n) for t, n in ok))
    if need:
        print(" [不足] " + " | ".join("%s %d局(差%d)" % (t, n, m) for t, n, m in need))
    print("=" * 72)


if __name__ == "__main__":
    main()
