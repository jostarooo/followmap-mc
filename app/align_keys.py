#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
align_keys.py —— 把 B 通道（真实键鼠）与 A 通道（游戏状态）按墙钟时间对齐

目的：
  1) 验证「按键要求」与「实际按下」是否对得上（左Shift / 左键）
  2) 量化人工按键的**时机抖动**（若抖动极小 = 疑似脚本；抖动几十 ms = 人工）
  3) 找出没被 B 通道覆盖的局（采样空白），作为补采清单
"""
import argparse, collections, glob, json, os

def is_sep(ch):
    return 0xAC00 <= ord(ch) <= 0xD7A3

def load(root, sub):
    out = []
    for f in sorted(glob.glob(os.path.join(root, sub, "*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if "wall" in o:
                o["_f"] = os.path.basename(f)
                out.append(o)
    out.sort(key=lambda o: o["wall"])
    return out

def load_key_sessions(root):
    """每个 keys 文件返回 (start_wall, end_wall, 文件名)。覆盖判断必须按单文件，"""
    spans = []
    for f in sorted(glob.glob(os.path.join(root, "inputs", "*.jsonl"))):
        ws = []
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if "wall" in o and o.get("type") in ("key", "mouse", "mark"):
                ws.append(o["wall"])
        if ws:
            spans.append((min(ws), max(ws), os.path.basename(f)))
    return spans

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.fishprobe"))
    ap.add_argument("--gap", type=int, default=1500)
    ap.add_argument("--show", type=int, default=30)
    args = ap.parse_args()

    evs = load(args.root, "events")
    keys = load(args.root, "inputs")

    subs = [e for e in evs if e.get("type") == "subtitle" and (e.get("text") or "").strip()]
    titles = [(e["wall"], (e.get("text") or "").strip())
              for e in evs if e.get("type") == "title" and (e.get("text") or "").strip()]

    eps, cur = [], []
    for e in subs:
        if cur and e["wall"] - cur[-1]["wall"] > args.gap:
            eps.append(cur); cur = []
        cur.append(e)
    if cur:
        eps.append(cur)

    # 真实按键（键盘 down / 鼠标 down）
    ev_key = [(e["wall"], e.get("dev"), e.get("name") or ("mouse:" + str(e.get("btn"))),
               e.get("act")) for e in keys
              if e.get("type") in ("key", "mouse") and e.get("act") == "down"]

    kb_spans = load_key_sessions(args.root)
    print("=" * 78)
    print(" B 通道 session : %d 个" % len(kb_spans))
    for s0, s1, fn in kb_spans:
        import datetime as _dt
        a = _dt.datetime.fromtimestamp(s0 / 1000).strftime("%H:%M:%S")
        b = _dt.datetime.fromtimestamp(s1 / 1000).strftime("%H:%M:%S")
        print("   %s  %s -> %s  (%.1f 分钟)" % (fn[-13:], a, b, (s1 - s0) / 60000))
    kbd = sum(1 for e in keys if e.get("type") == "key")
    mou = sum(1 for e in keys if e.get("type") == "mouse")
    print(" 按键事件: 键盘 %d / 鼠标 %d" % (kbd, mou))
    print(" A 通道对局     : %d 段(含碎片)" % len(eps))
    print("=" * 78)

    def in_span(t0):
        for s0, s1, _ in kb_spans:
            if s0 - 5000 <= t0 <= s1 + 5000:
                return True
        return False

    print()
    print(" %-3s %-19s %5s %-18s %-14s %s" % ("#", "开始(本地)", "帧", "形态", "窗内真实按键", "按键相对局开始(ms)"))
    print(" " + "-" * 74)
    covered = 0
    for i, ep in enumerate(eps, 1):
        if len(ep) < 5:
            continue
        t0, t1 = ep[0]["wall"], ep[-1]["wall"]
        # 形态
        seqs = [[c for c in (e.get("text") or "") if is_sep(c)] for e in ep]
        seqs = [s for s in seqs if s]
        k = collections.Counter(len(s) for s in seqs).most_common(1)[0][0] if seqs else 0
        ok = [s for s in seqs if len(s) == k]
        shape = {3: "T3", 2: "T2", 1: "T1"}.get(k, "?%d" % k)
        if k == 2 and ok and ord(ok[0][0]) == 0xB011:
            shape = "T2"
        # 窗口内按键
        win = [(w, dev, nm) for w, dev, nm, _ in ev_key if t0 - 2500 <= w <= t1 + 2500]
        names = collections.Counter(nm for _, _, nm in win)
        # 只在 B 通道覆盖范围内的局才显示按键
        in_range = in_span(t0)
        if in_range and win:
            covered += 1
            deltas = ", ".join("%+d" % (w - t0) for w, _, _ in win[:8])
            nm_s = " ".join("%s×%d" % (n, c) for n, c in names.most_common(4))
        elif in_range:
            nm_s, deltas = "(无)", "-"
        else:
            nm_s, deltas = "[未覆盖]", "-"
        import datetime
        ts = datetime.datetime.fromtimestamp(t0 / 1000).strftime("%H:%M:%S.%f")[:-3]
        if i <= args.show:
            print(" %-3d %-19s %5d %-18s %-14s %s" % (i, ts, len(ep), shape, nm_s, deltas))
    print(" " + "-" * 74)
    print(" B 通道实际覆盖到的有效局：%d" % covered)

    # 抖动量化：Shift 按下 相对 最近局起点的偏移
    print()
    print(" 人工按键时机抖动（仅统计被 B 通道覆盖的局）")
    print(" " + "-" * 74)
    deltas_all = []
    for ep in eps:
        if len(ep) < 5:
            continue
        t0 = ep[0]["wall"]
        if not in_span(t0):
            continue
        near = [w - t0 for w, dev, nm, _ in ev_key
                if abs(w - t0) <= 1200 and nm in ("SHIFT", "left", "CTRL")]
        if near:
            deltas_all.append(min(near, key=abs))
    if deltas_all:
        deltas_all.sort()
        n = len(deltas_all)
        avg = sum(deltas_all) / n
        var = sum((d - avg) ** 2 for d in deltas_all) / n
        print("   样本 %d 个; 偏移范围 %+d ~ %+d ms; 均值 %.0f ms; 标准差 %.0f ms"
              % (n, deltas_all[0], deltas_all[-1], avg, var ** 0.5))
        print("   判读：标准差 <10ms 疑似脚本；30~200ms 属正常人工反应")
    else:
        print("   无样本（B 通道未覆盖任何局）")


if __name__ == "__main__":
    main()
