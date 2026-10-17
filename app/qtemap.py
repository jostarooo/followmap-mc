#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
qtemap.py —— 方块传说钓鱼 QTE 进度条的**像素几何解码器**（v2）

原理（全部实测，见 report/qte-geometry-report.md）：
  subtitle 文本 = 「进度条字模 + U+F8xx 位偏移占位」拼出来的一维像素条。
  * B001..B014 -> customfishing:default      （指针 / 底图 / 判定绿区）
  * F801..F808、F811..F818 -> customfishing:offset_chars（**带符号**位偏移，负值回退）
  两张表来自活动资源包（从 options.txt 推导，见 qte_adv.py），合并后才能解码 ——
  一帧里 B0xx 与 F8xx 属于**两个不同字体**（mod 用多个 sibling 组件各带 style.font 拼出来）。

  advance 公式： advance = (imgW/cols) * (height/(imgH/rows)) + spacing
    - pointer.png  5x15   height=15 -> 5
    - bar*.png     256x8  height=8  -> 256
    - fish_icon    16x10  height=5  -> 8     （不能用 PNG 宽 16 当 advance！）
    - judgment_*   45/36/27 x 6 -> 45/36/27
    - space_split  256x256 height=±h -> ±h

  帧几何：
    zone_x = 判定绿区（B012/B013/B014）字模的 x 起点
    zone_w = 绿区宽度（easy 45 / normal 36 / hard 27）
    ptr_x  = 指针（B001）字模的 x 起点
    d      = ptr_x - zone_x    （<0 = 指针在绿区左侧，∈[0,w] = 在绿区内）

  已知边界（实测）：帧总宽 tot ≈ 220~229，不恒等 256 —— 占位符是贪心分解量化，
  残差 ±4.5px，所以判定规则必须容忍 ±5px，不能拿 tot==256 当不变量。

用法：
  python qtemap.py --table                     # 打印 advance 表
  python qtemap.py --frame "<subtitle>"        # 解码单帧几何
  python qtemap.py --list                      # 列出所有 QTE 局
  python qtemap.py --trace N                   # 追踪第 N 局每帧几何
  python qtemap.py --geom N                    # 第 N 局逐帧 zone/ptr/d（供人工核对）
  python qtemap.py --align                     # 按键对齐 + 规则扫描（HIT/FAIL 分离度）
"""

import argparse
import collections
import datetime
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# --------------------------------------------------------------------------
# 控制台 UTF-8（被重定向时 Windows 默认 GBK，会打乱中文）
# --------------------------------------------------------------------------
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
EVENTS = os.path.join(DATA, "events")
INPUTS = os.path.join(DATA, "inputs")

ADV_JSON = os.path.join(HERE, "qte_advance.json")

# 语义分组（与 customfishing 资源包一一对应）
POINTER = 0xB001
JUDG = (0xB012, 0xB013, 0xB014)                       # easy / normal / hard
BARGLYPH = set(range(0xB002, 0xB00D)) | {0xB011}      # 底图（bar1..bar10/rainbow/bar11）
FISH = set(range(0xB00D, 0xB011))                     # 鱼 / 挣扎鱼图标
POINTER_W = 5.0

_table_cache = None


def build_table(force=False, verbose=False):
    """返回 (dict: 码点 -> advance, 来源说明)。读 qte_advance.json，缺了就让 qte_adv.py 现算。"""
    global _table_cache
    if _table_cache is not None and not force:
        return _table_cache
    if not os.path.exists(ADV_JSON):
        import qte_adv
        qte_adv.build()
    meta = json.load(open(ADV_JSON, encoding="utf-8"))
    tab = {int(k): float(v["advance"]) for k, v in meta["points"].items()}
    _table_cache = (tab, "%s / %s" % (meta.get("pack", "?"), meta.get("fonts")))
    if verbose:
        print("advance 表来源：%s（%d 码点）" % (_table_cache[1], len(tab)))
    return _table_cache


def adv_of(cp):
    return build_table()[0].get(cp)


def is_bar(cp):
    """进度条本体字模（B0xx，落在韩文音节区，但**不是**全宽格 —— 这是 v1 的错误假设）。"""
    return 0xAC00 <= cp <= 0xD7A3 and cp in build_table()[0]


def is_glyph(ch):
    return 0xE000 <= ord(ch) <= 0xF8FF


def is_sep(ch):
    """兼容旧接口：v2 里「分隔符」= 进度条本体字模。"""
    return is_bar(ord(ch))


# --------------------------------------------------------------------------
# 解码
# --------------------------------------------------------------------------
def decode(text, table=None, sep_adv=None):
    """把一个 subtitle 文本解成几何：返回 (cells, seps, total_width)

    cells: [{'ch','cp','x0','x1','w','kind'}...]  kind = bar/offset/other
           x 可为负（F8xx 是带符号位偏移，负值把笔尖往回拉）
    seps : 进度条本体字模（旧接口兼容，用作坐标锚点）
    """
    tab = table if table is not None else build_table()[0]
    cells, x = [], 0.0
    for ch in text:
        cp = ord(ch)
        if cp in tab:
            w, kind = tab[cp], ("bar" if is_bar(cp) else "offset")
        elif is_bar(cp):
            w, kind = 0.0, "bar"       # 表里没有的 B0xx（如 title 用的 B015..）：按 0 处理
        else:
            w, kind = 0.0, "other"
        cells.append({"ch": ch, "cp": cp, "x0": x, "x1": x + w, "w": w, "kind": kind})
        x += w
    seps = [{"idx": i, "cp": c["cp"], "x0": c["x0"], "x1": c["x1"]}
            for i, c in enumerate(cells) if c["kind"] == "bar"]
    return cells, seps, x


def frame_geom(text, table=None):
    """一帧的关键几何。解不出（缺绿区或缺指针）返回 None。

    返回 dict(zone_cp, zone_x, zone_w, ptr_x, ptr_w, d, total)
      d = ptr_x - zone_x；d ∈ [0, zone_w] 视为指针在绿区内。
    """
    tab = table if table is not None else build_table()[0]
    zone = None
    ptr = None
    x = 0.0
    for ch in text:
        cp = ord(ch)
        w = tab.get(cp)
        if w is None:
            if is_bar(cp):
                w = 0.0                 # 表里没有的 B0xx（如 title 用的 B015..）：按 0 处理
            else:
                return None             # 未知字形 → 这帧解不可靠
        if zone is None and cp in JUDG:
            zone = (cp, x, w)
        if ptr is None and cp == POINTER:
            ptr = x
        x += w
    if zone is None or ptr is None:
        return None
    return {
        "zone_cp": zone[0], "zone_x": zone[1], "zone_w": zone[2],
        "ptr_x": ptr, "ptr_w": POINTER_W,
        "d": ptr - zone[1],
        "total": x,
    }


def sep_signature(text):
    """结构签名 = 进度条字模个数 + 首个 + 末个码点"""
    ids = [ord(c) for c in text if is_bar(ord(c))]
    if not ids:
        return None
    return (len(ids), ids[0], ids[-1])


def shape_of(sigs):
    if not sigs:
        return "?"
    cnt = collections.Counter(s[0] for s in sigs)
    k = cnt.most_common(1)[0][0]
    if k == 3:
        return "T3"
    if k == 2:
        tails = collections.Counter(s[2] for s in sigs if s[0] == 2)
        if tails.most_common(1)[0][0] == POINTER:
            return "T3s"
        return "T2"
    return "T%d" % k


# --------------------------------------------------------------------------
# 数据读取
# --------------------------------------------------------------------------
def load_events():
    evs = []
    for f in sorted(glob.glob(os.path.join(EVENTS, "*.jsonl"))):
        sess = os.path.basename(f).replace("session-", "").replace("-world.jsonl", "")
        for line in open(f, encoding="utf-8"):
            try:
                o = json.loads(line)
            except Exception:
                continue
            if "wall" in o:
                o["_sess"] = sess
                evs.append(o)
    evs.sort(key=lambda o: o["wall"])
    return evs


def load_keys():
    """B 通道按键。剔除标记键 i / . / '（它们是人工打点，不是游戏按键）。"""
    out = []
    for f in sorted(glob.glob(os.path.join(INPUTS, "*-keys.jsonl"))):
        for line in open(f, encoding="utf-8"):
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("wall") and o.get("type") in ("key", "mouse"):
                if o.get("name") in ("i", ".", "'"):
                    continue
                out.append(o)
    out.sort(key=lambda o: o["wall"])
    return out


def load_marks():
    out = []
    for f in sorted(glob.glob(os.path.join(INPUTS, "*-keys.jsonl"))):
        for line in open(f, encoding="utf-8"):
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("wall") and o.get("type") == "mark":
                out.append(o)
    out.sort(key=lambda o: o["wall"])
    return out


def split_episodes(evs, gap_ms=1500):
    """⚠️ 1500ms gap 会把长局切碎（上一轮踩过）：分数局时记得核对局长。"""
    subs = [e for e in evs
            if e.get("type") == "subtitle" and (e.get("text") or "").strip()]
    eps, cur = [], []
    for e in subs:
        if cur and e["wall"] - cur[-1]["wall"] > gap_ms:
            eps.append(cur)
            cur = []
        cur.append(e)
    if cur:
        eps.append(cur)
    return eps


def qte_episodes(evs):
    """只留「解得出几何」的局，并把被 gap 切碎的相邻局重新拼起来。"""
    eps = [e for e in split_episodes(evs) if len(e) >= 5]
    merged = []
    for ep in eps:
        if merged and ep[0]["wall"] - merged[-1][-1]["wall"] <= 3000:
            merged[-1].extend(ep)
        else:
            merged.append(ep)
    out = []
    for ep in merged:
        gs = [frame_geom(e["text"]) for e in ep]
        gs = [g for g in gs if g]
        if len(gs) >= 5:
            out.append(ep)
    return out


def titles_near(evs, t0, back_ms=20000, fwd_ms=1500):
    def ispure(t):
        return all(is_glyph(c) or is_bar(ord(c)) for c in t)
    out = []
    for e in evs:
        if e.get("type") != "title":
            continue
        t = (e.get("text") or "").strip()
        if not t or ispure(t):
            continue
        if t0 - back_ms <= e["wall"] <= t0 + fwd_ms:
            out.append((e["wall"], t))
    return out


def key_requirement(titles):
    req = [t for _, t in titles if "开始" in t and "按下" in t]
    if not req:
        return "(无)"
    t = req[-1]
    core = t.replace("按下", "").replace("开始", "").strip()
    return core or t


def episode_outcome(marks, t1, back=200, fwd=2500):
    """人工打点结局：'.' = success（HIT），"'" = fail（FAIL）。"""
    out = "?"
    for m in marks:
        if t1 - back <= m["wall"] <= t1 + fwd:
            if m.get("role") == "success":
                out = "HIT"
            elif m.get("role") == "fail":
                out = "FAIL"
    return out


def quant(v, p):
    if not v:
        return float("nan")
    s = sorted(v)
    return s[min(len(s) - 1, int(p * len(s)))]


def _ks(a, b):
    """两样本经验分布的最大距离（KS 统计量，0~1）。"""
    if not a or not b:
        return float("nan")
    xs = sorted(set(a) | set(b))

    def cdf(v, s):
        return sum(1 for x in s if x <= v) / float(len(s))
    return max(abs(cdf(x, a) - cdf(x, b)) for x in xs)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def cmd_table(args):
    tab, src = build_table(verbose=True)
    print()
    print("%-8s %10s" % ("码点", "advance"))
    for cp in sorted(tab):
        print("U+%04X  %10.2f" % (cp, tab[cp]))
    print()
    print("（advance 由 %s 实测推导；F8xx 为**带符号**位偏移，负值把笔尖往回拉）" % src)


def cmd_frame(args):
    g = frame_geom(args.frame)
    cells, seps, total = decode(args.frame)
    if not g:
        print("解不出几何（缺绿区或缺指针）。总宽 %.1f，%d 字符" % (total, len(cells)))
        return 1
    print("总宽 %.1f px，%d 个字符，%d 个进度条字模" % (total, len(cells), len(seps)))
    print()
    print("  绿区  U+%04X  x=%.1f .. %.1f  (w=%.0f)" % (
        g["zone_cp"], g["zone_x"], g["zone_x"] + g["zone_w"], g["zone_w"]))
    print("  指针  U+%04X  x=%.1f .. %.1f  (w=%.0f)" % (
        POINTER, g["ptr_x"], g["ptr_x"] + g["ptr_w"], g["ptr_w"]))
    print("  d = ptr_x - zone_x = %+.1f   %s" % (
        g["d"], "★ 在绿区内" if 0 <= g["d"] <= g["zone_w"] else "在绿区外"))
    print()
    print("逐字符：")
    for c in cells:
        print("  %-6s U+%04X w=%-8.1f x=%+8.1f..%+8.1f" % (
            c["kind"], c["cp"], c["w"], c["x0"], c["x1"]))
    return 0


def cmd_list(args):
    evs = load_events()
    eps = qte_episodes(evs)
    marks = load_marks()
    print("%-4s %-9s %-6s %-6s %-10s %-5s %s" % (
        "#", "时间", "帧", "形态", "按键要求", "结局", "绿区"))
    n = 0
    for i, ep in enumerate(eps, 1):
        n += 1
        t0 = ep[0]["wall"]
        g = frame_geom(ep[0]["text"])
        sigs = {sep_signature(e["text"]) for e in ep if sep_signature(e["text"])}
        titles = titles_near(evs, t0)
        print("%-4d %-9s %-6d %-6s %-10s %-5s %s" % (
            n,
            datetime.datetime.fromtimestamp(t0 / 1000).strftime("%H:%M:%S"),
            len(ep), shape_of(sigs), key_requirement(titles),
            episode_outcome(marks, ep[-1]["wall"]),
            ("U+%04X w=%.0f" % (g["zone_cp"], g["zone_w"])) if g else "-"))
    print()
    print("有效局数：%d" % n)


def cmd_trace(args):
    evs = load_events()
    eps = qte_episodes(evs)
    if args.trace < 1 or args.trace > len(eps):
        print("局号超范围（1..%d）" % len(eps))
        return 1
    ep = eps[args.trace - 1]
    titles = titles_near(evs, ep[0]["wall"])
    print("局 #%d  起 %s  帧 %d  按键要求 %s" % (
        args.trace,
        datetime.datetime.fromtimestamp(ep[0]["wall"] / 1000).strftime("%H:%M:%S"),
        len(ep), key_requirement(titles)))
    print()
    print("%-12s %8s %8s %8s %8s %s" % ("时间", "zone_x", "zone_w", "ptr_x", "d", "in-zone"))
    for e in ep:
        g = frame_geom(e["text"])
        if not g:
            continue
        ts = datetime.datetime.fromtimestamp(e["wall"] / 1000).strftime("%H:%M:%S.%f")[:-3]
        print("%-12s %8.1f %8.0f %8.1f %+8.1f %s" % (
            ts, g["zone_x"], g["zone_w"], g["ptr_x"], g["d"],
            "★" if 0 <= g["d"] <= g["zone_w"] else ""))
    return 0


def cmd_align(args):
    """按键对齐 + 规则扫描。

    三条规则 × 余量 m（m 是几何量化残差的容忍度，实测 tot 残差 ±4.5px）：
      left   : 指针**左沿**落进 [zone_x-m, zone_x+w+m]
      center : 指针**中心**落进同区间
      whole  : 指针**整体**落进同区间
    指标：HIT 局按键命中率 / FAIL 局按键命中率 / 全帧基线命中率，分离度 = HIT-FAIL。
    """
    evs = load_events()
    eps = qte_episodes(evs)
    keys = load_keys()
    marks = load_marks()
    print("有效局 %d，按键 %d 条，标记 %d 条" % (len(eps), len(keys), len(marks)))

    rows = []
    all_d, press_d = [], []
    for ep in eps:
        fr = [(e["wall"], frame_geom(e["text"])) for e in ep]
        fr = [(w, g) for w, g in fr if g]
        if len(fr) < 5:
            continue
        t0, t1 = fr[0][0], fr[-1][0]
        out = episode_outcome(marks, t1)
        kk = [k for k in keys if t0 - 80 <= k["wall"] <= t1 + 80]
        pd = []
        for k in kk:
            near = min(fr, key=lambda f: abs(f[0] - k["wall"]))
            if abs(near[0] - k["wall"]) > 100:
                continue
            d = near[1]["d"]
            pd.append(d)
            press_d.append(d)
        for _, g in fr:
            all_d.append(g["d"])
        rows.append({"t0": t0, "n": len(fr), "out": out, "pd": pd,
                     "alld": [g["d"] for _, g in fr], "zw": fr[0][1]["zone_w"]})

    print()
    print("d = ptr - zone_x 分布（绿区 = d∈[0, w]，w 中位 %.0f）" % quant([r["zw"] for r in rows], .5))
    for name, v in (("全帧", all_d), ("按键", press_d)):
        print("  %-4s n=%-5d  5%%=%+7.1f 25%%=%+7.1f 中位=%+7.1f 75%%=%+7.1f 95%%=%+7.1f" % (
            name, len(v), quant(v, .05), quant(v, .25), quant(v, .5), quant(v, .75), quant(v, .95)))
    print("  ★ KS 距离（按键 vs 全帧）: %.3f" % _ks(all_d, press_d))

    def hit(rule, d, w, m):
        if rule == "left":
            return -m <= d <= w + m
        if rule == "center":
            return -m <= d + 2.5 <= w + m
        if rule == "whole":
            return -m <= d and d + 5 <= w + m
        return False

    print()
    print("%-7s %-3s | %-18s | %-18s | %-9s | %s" % (
        "rule", "m", "HIT局按键命中", "FAIL局按键命中", "全帧基线", "分离度"))
    best = None
    for rule in ("left", "center", "whole"):
        for m in (0, 3, 5, 8):
            agg = [[], [], []]
            for r in rows:
                w = r["zw"]
                if r["out"] == "HIT":
                    agg[0].append(sum(1 for d in r["pd"] if hit(rule, d, w, m)) / max(1, len(r["pd"])))
                elif r["out"] == "FAIL":
                    agg[1].append(sum(1 for d in r["pd"] if hit(rule, d, w, m)) / max(1, len(r["pd"])))
                agg[2].append(sum(1 for d in r["alld"] if hit(rule, d, w, m)) / max(1, len(r["alld"])))
            a = sum(agg[0]) / max(1, len(agg[0]))
            b = sum(agg[1]) / max(1, len(agg[1]))
            c = sum(agg[2]) / max(1, len(agg[2]))
            sep = a - b
            mark = ""
            if best is None or sep > best[1]:
                best = ((rule, m), sep, a, b, c)
            print("%-7s %-3d | %.3f (n=%d)   | %.3f (n=%d)   | %-9.3f | %+0.3f" % (
                rule, m, a, len(agg[0]), b, len(agg[1]), c, sep))
    if best:
        print("\n  ★ 最优规则：%s / 余量 %dpx  → HIT %.3f vs FAIL %.3f（全帧基线 %.3f，分离度 %+.3f）"
              % (best[0][0], best[0][1], best[2], best[3], best[4], best[1]))

    # 指针速度（给提前量用）
    spd = []
    for r in rows:
        al = r["alld"]
        for i in range(1, len(al)):
            spd.append(al[i] - al[i - 1])
    print()
    print("指针 d 逐帧增量：中位 %+.1f px  IQR[%+.1f, %+.1f]（帧距约 50ms）" % (
        quant(spd, .5), quant(spd, .25), quant(spd, .75)))
    print("  ⇒ 约 50ms 判定/按键延迟 ≐ 提前 %+.1f px（geo_lead_px 默认值依据）" % quant(spd, .5))
    return 0


def main():
    ap = argparse.ArgumentParser(description="QTE 进度条像素几何解码器 v2")
    ap.add_argument("--table", action="store_true", help="打印 advance 表")
    ap.add_argument("--frame", help="解码单个 subtitle 文本")
    ap.add_argument("--list", action="store_true", help="列出所有 QTE 局")
    ap.add_argument("--trace", type=int, help="追踪第 N 局每帧几何")
    ap.add_argument("--geom", type=int, help="同 --trace（几何视角的别名）")
    ap.add_argument("--align", action="store_true", help="按键对齐 + 规则扫描")
    args = ap.parse_args()

    if args.table:
        return cmd_table(args)
    if args.frame:
        return cmd_frame(args)
    if args.list:
        return cmd_list(args)
    if args.trace:
        return cmd_trace(args)
    if args.geom:
        return cmd_trace(args)
    if args.align:
        return cmd_align(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
