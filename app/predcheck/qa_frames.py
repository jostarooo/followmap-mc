#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""qa_frames.py —— 严过关独立验证 #3：真实帧解码交叉验证（v2）

  1. 从 ~/.fishprobe/events 把 QTE subtitle 帧按局分组（间隔>3s = 新局），
     只保留含判定绿区（B012/13/14）的局；排除报告示例帧。
  2. 抽 ≥6 局、每局 4 帧（首/1/3/末位次）。
  3. 每帧双路解码：
     a) 子进程调 qtemap.py --frame（工具原入口，直接传 Unicode argv）；
     b) 用验证#1 自己重算的 advance 表独立解码（未知 B0xx 按 0 宽，与 qtemap 语义一致；
        未知非 B0xx 字形 → 解不出，两路都必须拒绝）。
  4. 合理性：zone_w ∈ {45,36,27}；局内 zone_x 波动统计（对照残差 ±4.5px 说法）；
     ptr 相邻帧（wall 间隔≤100ms）位移分布。
"""
import glob
import json
import os
import re
import statistics
import subprocess
import sys

PY = r"D:\python\python.exe"
QTEMAP = r"D:\wbworkspace\2026-10-08-17-29-12\fangkuai-chuanshuo\app\qtemap.py"
ENV = dict(os.environ, PYTHONUTF8="1")

ADV = {
    0xB001: 5, 0xB002: 256, 0xB003: 256, 0xB004: 256, 0xB005: 256, 0xB006: 256,
    0xB007: 256, 0xB008: 256, 0xB009: 256, 0xB00A: 256, 0xB00B: 256, 0xB00C: 256,
    0xB00D: 8, 0xB00E: 8, 0xB00F: 8, 0xB010: 8, 0xB011: 256,
    0xB012: 45, 0xB013: 36, 0xB014: 27,
    0xF801: -3, 0xF802: -4, 0xF803: -6, 0xF804: -10,
    0xF805: -18, 0xF806: -34, 0xF807: -66, 0xF808: -130,
    0xF811: -1, 0xF812: 1, 0xF813: 3, 0xF814: 7,
    0xF815: 15, 0xF816: 31, 0xF817: 63, 0xF818: 127,
}
REPORT_SAMPLE = ("B00C F807 F806 F804 F801 B012 F816 F815 F813 F812 F811 "
                 "F808 F805 F804 F803 B001 F818 F815 F813 F812 F811")


def my_decode(text):
    """独立解码。未知非 B0xx 字形 → None（拒绝）。未知 B0xx → 0 宽。"""
    zone = ptr = None
    x = 0
    for ch in text:
        cp = ord(ch)
        w = ADV.get(cp)
        if w is None:
            if 0xAC00 <= cp <= 0xD7A3:
                w = 0            # 表外 B0xx（title 用），0 宽
            else:
                return None      # 真未知字形 → 拒绝
        if zone is None and cp in (0xB012, 0xB013, 0xB014):
            zone = (cp, x, w)
        if ptr is None and cp == 0xB001:
            ptr = x
        x += w
    if zone is None or ptr is None:
        return None
    return {"zone_cp": zone[0], "zone_x": zone[1], "zone_w": zone[2],
            "ptr_x": ptr, "d": ptr - zone[1], "total": x}


RX_ZONE = re.compile(r"绿区\s+U\+([0-9A-Fa-f]+)\s+x=(-?[\d.]+)")
RX_PTR = re.compile(r"指针\s+U\+([0-9A-Fa-f]+)\s+x=(-?[\d.]+)")
RX_W = re.compile(r"\(w=(-?[\d.]+)\)")
RX_D = re.compile(r"d = ptr_x - zone_x = \+?(-?[\d.]+)")


def qtemap_frame(text):
    r = subprocess.run([PY, QTEMAP, "--frame", text], capture_output=True,
                       encoding="utf-8", env=ENV, timeout=60)
    out = r.stdout + r.stderr
    mz = RX_ZONE.search(out)
    mp = RX_PTR.search(out)
    md = RX_D.search(out)
    if not (mz and mp and md):
        return None, out
    wz = RX_W.search(out[mz.start():])
    return {
        "zone_cp": int(mz.group(1), 16), "zone_x": float(mz.group(2)),
        "zone_w": float(wz.group(1)) if wz else None,
        "ptr_x": float(mp.group(2)), "d": float(md.group(1)),
    }, out


def collect_rounds():
    rounds, cur, last = [], [], None
    for f in sorted(glob.glob(os.path.expanduser("~/.fishprobe/events/*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("type") != "subtitle":
                continue
            txt = e.get("text", "")
            if not any(0xB001 <= ord(c) <= 0xD7A3 for c in txt):
                continue
            if txt == REPORT_SAMPLE:
                continue
            w = e.get("wall", 0)
            if last is not None and w - last > 3000 and cur:
                rounds.append(cur)
                cur = []
            cur.append((w, txt))
            last = w
    if cur:
        rounds.append(cur)
    # 只留含判定绿区的局
    out = []
    for r in rounds:
        if any(my_decode(t) for _, t in r):
            out.append(r)
    return out


def main():
    rounds = collect_rounds()
    print("含判定绿区的局数: %d" % len(rounds))

    # 选局：不同难度 + 不同 session，取 8 局
    picked, seen = [], set()
    for i, r in enumerate(rounds):
        cps = {my_decode(t)["zone_cp"] for _, t in r if my_decode(t)}
        key = (tuple(sorted(cps)), i % 3)  # 难度 + 粗略 session 区分
        if key not in seen or len(picked) < 6:
            seen.add(key)
            picked.append((i, r))
        if len(picked) >= 8:
            break

    all_ok = True
    for i, r in picked:
        idxs = sorted(set([0, len(r)//3, 2*len(r)//3, len(r)-1]))
        print("\n== 局 #%d（%d 帧）抽 %d 帧 ==" % (i, len(r), len(idxs)))
        zx_seen = []
        agree_all = True
        prev = None
        moves = []
        for k in idxs:
            wall, text = r[k]
            g = my_decode(text)
            q, out = qtemap_frame(text)
            if g is None:
                print("  [帧%d] 两路均拒绝（qtemap解不出=%s）" % (k, q is None))
                if q is not None:
                    all_ok = False
                continue
            if q is None:
                print("  [帧%d] 独立解出但 qtemap 拒绝 ✗" % k)
                all_ok = False
                continue
            agree = (abs(q["zone_x"] - g["zone_x"]) < 0.5 and
                     abs(q["ptr_x"] - g["ptr_x"]) < 0.5 and
                     abs(q["d"] - g["d"]) < 0.5 and
                     q["zone_w"] == g["zone_w"])
            agree_all = agree_all and agree
            zx_seen.append(g["zone_x"])
            if prev is not None and wall - prev[0] <= 100:
                moves.append((wall - prev[0], g["ptr_x"] - prev[1]))
            prev = (wall, g["ptr_x"])
            print("  [帧%d] zone=%s x=%d w=%d ptr_x=%d d=%+d tot=%d | qtemag一致=%s"
                  % (k, hex(g["zone_cp"]), g["zone_x"], g["zone_w"],
                     g["ptr_x"], g["d"], g["total"], "PASS" if agree else "FAIL"))
            if not agree:
                print("      qtemap 输出: zone_x=%.1f ptr_x=%.1f d=%.1f w=%.0f"
                      % (q["zone_x"], q["ptr_x"], q["d"], q["zone_w"] or -1))
                all_ok = False
        zx_range = (min(zx_seen), max(zx_seen)) if zx_seen else None
        # 相邻帧位移（全部帧，不只抽样）
        seq = [(w, my_decode(t)) for w, t in r]
        seq = [(w, g) for w, g in seq if g]
        step_moves = []
        for a, b in zip(seq, seq[1:]):
            if b[0] - a[0] <= 100:
                step_moves.append(b[1]["ptr_x"] - a[1]["ptr_x"])
        med = statistics.median(step_moves) if step_moves else None
        in_band = sum(1 for v in step_moves if -5 <= v <= 8)
        print("  局内 zone_x 范围: %s（n=%d） | 相邻帧位移 中位=%s min=%s max=%s，[-5,8]内 %d/%d"
              % (zx_range, len(zx_seen), med,
                 min(step_moves) if step_moves else None,
                 max(step_moves) if step_moves else None,
                 in_band, len(step_moves)))
        if not agree_all:
            all_ok = False

    print("\n===== 验证#3 真实帧交叉验证: %s（%d 局）=====" % ("PASS" if all_ok else "FAIL", len(picked)))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
