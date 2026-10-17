#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
qte_rule.py —— 用真实按键时刻反推 QTE 判定规则

已破解的字形协议（来源：服务器资源包 generated.zip → customfishing:font/default.json）

  U+B001  bars/pointer.png              5x15   指针（白色竖直指示器）
  U+B002..B00A  bars/bar1..bar9.png     256x8  进度条底图（9 种皮肤）
  U+B00B  bars/bar_rainbow.png          256x8  彩虹底图
  U+B00C  bars/bar10.png                256x8  进度条底图（ascent 低 1px）
  U+B00D  bars/fish_icon.png            16x10  鱼图标
  U+B00E..B010  struggling_fish_icon    16x10  挣扎鱼图标（3 个高度）
  U+B011  bars/bar11.png                256x20 加粗底图
  U+B012  bars/judgment_area_easy.png   45x6   ★ 判定绿区（简单）
  U+B013  bars/judgment_area_normal.png 36x6   ★ 判定绿区（普通）
  U+B014  bars/judgment_area_hard.png   27x6   ★ 判定绿区（困难）
  U+F8xx  剑魂资源包 space:default      1x1    宽度阶梯 3..10 / 18..1026（透明占位）

⇒ subtitle = 「底图 + 若干宽度占位 + 判定区 + 若干宽度占位 + 指针 + 收尾占位」
  ⇒ **指针相对判定区起点的像素偏移 = 判定区宽度 + 它们之间的占位宽度和**
  ⇒ 该偏移随时间变化 = 指针在扫动；判定区固定 ⇒ 「何时该按」应当落在某个偏移区间内。
"""
import argparse
import collections
import datetime
import glob
import json
import os
import sys

import qtemap as Q

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DATA = os.path.join(os.path.expanduser("~"), ".fishprobe")
INPUTS = os.path.join(DATA, "inputs")

# customfishing 进度条字模：码点 -> (宽度, 语义)
CF = {
    0xB001: (5,    "pointer"),
    0xB002: (256,  "bar"),
    0xB003: (256,  "bar"),
    0xB004: (256,  "bar"),
    0xB005: (256,  "bar"),
    0xB006: (256,  "bar"),
    0xB007: (256,  "bar"),
    0xB008: (256,  "bar"),
    0xB009: (256,  "bar"),
    0xB00A: (256,  "bar"),
    0xB00B: (256,  "bar"),
    0xB00C: (256,  "bar"),
    0xB00D: (8,    "fish"),
    0xB00E: (8,    "fish_struggle"),
    0xB00F: (8,    "fish_struggle"),
    0xB010: (8,    "fish_struggle"),
    0xB011: (256,  "bar_thick"),
    0xB012: (45,   "judgment_easy"),
    0xB013: (36,   "judgment_normal"),
    0xB014: (27,   "judgment_hard"),
}
JUDGE = {0xB012: 45, 0xB013: 36, 0xB014: 27}


def layout(text, table):
    """把一帧拆成带语义的元素序列，并给出每个元素的 x 偏移。

    x 以「本帧字符串的排版原点」为 0 累加；因为指针/判定区之间的**相对距离**
    才是关键，绝对原点无所谓。
    """
    out = []
    x = 0.0
    for ch in text:
        cp = ord(ch)
        if cp in CF:
            w, kind = CF[cp]
        elif Q.is_sep(ch):
            w, kind = Q.SEP_ADVANCE, "sep"
        else:
            w, kind = table.get(cp, 8.0), "spacer"
        out.append({"cp": cp, "x0": x, "x1": x + w, "w": w, "kind": kind})
        x += w
    return out, x


def frame_geom(text, table):
    """返回一帧的关键几何量（找不到就返回 None）"""
    els, total = layout(text, table)
    judge = None
    pointer = None
    for e in els:
        if e["kind"].startswith("judgment") and judge is None:
            judge = e
        if e["kind"] == "pointer" and pointer is None:
            pointer = e
    if judge is None or pointer is None:
        return None
    # 判定区右边缘 → 指针左边缘之间的距离（占位宽度和）
    gap = sum(e["w"] for e in els if judge["x1"] <= e["x0"] < pointer["x0"])
    return {
        "total": total,
        "judge_x0": judge["x0"], "judge_w": judge["w"],
        "judge_cp": judge["cp"],
        "pointer_x0": pointer["x0"], "pointer_w": pointer["w"],
        "gap": gap,
        "offset": judge["x1"] + gap,      # 指针左缘（以字符串原点计）
        "rel": gap,                        # 指针相对判定区右缘的偏移
    }


def load_inputs():
    """B 通道：按键事件（含 mouse），带墙钟时间"""
    ev = []
    for f in sorted(glob.glob(os.path.join(INPUTS, "*-keys.jsonl"))):
        for line in open(f, encoding="utf-8"):
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("wall"):
                o["_sess"] = os.path.basename(f)
                ev.append(o)
    ev.sort(key=lambda o: o["wall"])
    return ev


def main():
    ap = argparse.ArgumentParser(description="QTE 判定规则反推")
    ap.add_argument("--episode", type=int, help="只看第 N 局")
    ap.add_argument("--show", type=int, default=25, help="打印前 N 帧")
    ap.add_argument("--rule", action="store_true", help="只输出按键时刻的偏移统计")
    args = ap.parse_args()

    table, _ = Q.build_table()
    evs = Q.load_events()
    eps = [e for e in Q.split_episodes(evs) if len(e) >= 5]
    keys = load_inputs()

    # 只保留与 B 通道时间窗有交集的局
    bwin = []
    if keys:
        w = [k["wall"] for k in keys]
        bwin = (min(w), max(w))

    print("B 通道按键事件 %d 条，窗口 %s" % (
        len(keys),
        datetime.datetime.fromtimestamp(bwin[0] / 1000).strftime("%H:%M:%S") + "~" +
        datetime.datetime.fromtimestamp(bwin[1] / 1000).strftime("%H:%M:%S") if bwin else "无"))
    print()

    hdr = "%-4s %-9s %-5s %-9s %-8s %-8s %-8s %s"
    print(hdr % ("#", "时间", "帧", "判定区", "判定宽", "指针x", "相对偏移", "B通道按键"))
    rows = []
    for i, ep in enumerate(eps, 1):
        if args.episode and i != args.episode:
            continue
        t0, t1 = ep[0]["wall"], ep[-1]["wall"]
        g0 = frame_geom(ep[0]["text"], table)
        gN = None
        for e in reversed(ep):
            gN = frame_geom(e["text"], table)
            if gN:
                break
        if not g0:
            continue
        # 本局时间窗内的按键
        kk = [k for k in keys if t0 - 200 <= k["wall"] <= t1 + 200 and
              k.get("type") in ("key", "mouse")]
        inb = "IN" if (bwin and bwin[0] - 5000 <= t0 <= bwin[1] + 5000) else "OUT"
        print(hdr % (i,
                     datetime.datetime.fromtimestamp(t0 / 1000).strftime("%H:%M:%S"),
                     len(ep),
                     "U+%04X" % g0["judge_cp"],
                     "%.0f" % g0["judge_w"],
                     "%.0f" % g0["pointer_x0"],
                     "%.0f" % g0["rel"],
                     "%d 条 %s" % (len(kk), inb)))
        rows.append((i, ep, g0, gN, kk, inb))

    if not args.rule:
        print()
        print("=== 逐帧偏移序列（前 %d 帧）===" % args.show)
        for i, ep, g0, gN, kk, inb in rows:
            print("--- 局 #%d ---" % i)
            prev = None
            for e in ep[:args.show]:
                g = frame_geom(e["text"], table)
                if not g:
                    continue
                d = "" if prev is None else "%+.0f" % (g["rel"] - prev)
                ts = datetime.datetime.fromtimestamp(e["wall"] / 1000).strftime("%H:%M:%S.%f")[:-3]
                hit = "  <-- 按键" if any(abs(k["wall"] - e["wall"]) <= 60 for k in kk) else ""
                print("   %s rel=%-6.0f Δ=%-6s total=%.0f%s" % (ts, g["rel"], d, g["total"], hit))
                prev = g["rel"]

    # ---- 核心：按键时刻的偏移分布 vs 全部帧的偏移分布 ----
    print()
    print("=== 按键时刻的偏移 vs 全帧偏移 ===")
    allrel = collections.Counter()
    pressrel = collections.Counter()
    for i, ep, g0, gN, kk, inb in rows:
        if not kk:
            continue
        geoms = [(e["wall"], frame_geom(e["text"], table)) for e in ep]
        geoms = [(w, g) for w, g in geoms if g]
        for w, g in geoms:
            allrel[int(round(g["rel"] / 4.0)) * 4] += 1
        for k in kk:
            near = min(geoms, key=lambda wg: abs(wg[0] - k["wall"]))
            if abs(near[0] - k["wall"]) <= 120:
                pressrel[int(round(near[1]["rel"] / 4.0)) * 4] += 1
    print("全帧偏移分布（4px 桶）:", dict(sorted(allrel.items())))
    print("按键时刻偏移分布      :", dict(sorted(pressrel.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
