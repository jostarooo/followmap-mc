# -*- coding: utf-8 -*-
"""回测：直接用**实时会话日志**（~/.fishauto/log/session-*.jsonl）验证 v0.3.0 的
C 形态解码器，并挖掘 B 形态是否有可用的进度信号。

与 _probe_verifyC.py 的区别：后者走的是离线 .fishprobe/events（人工打点那批），
本脚本走的是模组自己写的 JSONL（含 form 字段、qte_end 结果），能直接算「形态 → 胜率」。

用法：
    python _probe_session_v3.py              # 全部分析
    python _probe_session_v3.py --last 3     # 只看最近 3 个会话
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

# ---- 与 Geom.java 逐项一致的常量 ----
POINTER = 0xB001
POINTER_W = 5
CELL = 256
BAR_W = {0xB002: 184, 0xB003: 184, 0xB004: 184, 0xB005: 184, 0xB006: 184,
         0xB007: 184, 0xB008: 184, 0xB009: 184, 0xB00A: 184,
         0xB00B: 120, 0xB00C: 163, 0xB011: 222}
C_RED, C_ORANGE, C_GREEN, C_TEAL, C_BLUE, C_PURPLE = range(6)
BAR_SEGS = {
    0xB002: [(84, 100, C_GREEN)],
    0xB003: [(52, 68, C_GREEN)],
    0xB004: [(116, 132, C_GREEN)],
    0xB005: [(84, 92, C_GREEN), (132, 140, C_GREEN)],
    0xB006: [(4, 12, C_GREEN), (60, 68, C_GREEN), (108, 116, C_GREEN), (140, 148, C_GREEN)],
    0xB007: [(68, 76, C_GREEN), (84, 92, C_GREEN), (100, 108, C_GREEN)],
    0xB008: [(156, 160, C_GREEN)],
    0xB009: [(84, 88, C_GREEN)],
    0xB00A: [(4, 8, C_GREEN), (176, 180, C_GREEN)],
    0xB00B: [(4, 20, C_RED), (20, 52, C_ORANGE), (52, 68, C_GREEN),
             (68, 84, C_TEAL), (84, 100, C_BLUE), (100, 116, C_PURPLE)],
}


def decode_c(text, color="green"):
    """Geom.decodeC 的 Python 镜像。返回 (ptrX, barCp, zs, ze) 或 None。"""
    tab = Q.build_table()[0]
    x, ptr, bar = 0, None, 0
    for ch in text:
        cp = ord(ch)
        a = tab.get(cp)
        if a is None:
            return None
        if ptr is None and cp == POINTER:
            ptr = x
        if bar == 0 and 0xB002 <= cp <= 0xB00B:
            bar = cp
        x += a
    if ptr is None or bar == 0:
        return None
    segs = BAR_SEGS.get(bar)
    if not segs:
        return None
    want = {"red": C_RED, "orange": C_ORANGE, "green": C_GREEN, "teal": C_TEAL,
            "blue": C_BLUE, "purple": C_PURPLE}.get(color, C_GREEN)
    hit = next((s for s in segs if s[2] == want), None)
    if hit is None:
        return None
    off = CELL - BAR_W.get(bar, 0)
    return (ptr, bar, off + hit[0], off + hit[1])


def in_zone_c(c, margin=6):
    if c is None:
        return False
    ptr, _, zs, ze = c
    return ptr <= ze + margin and ptr + POINTER_W >= zs - margin


# ---------------------------------------------------------------- 读日志
def read_sessions(nlast=None):
    fs = sorted(glob.glob(os.path.join(LOG, "session-*.jsonl")))
    if nlast:
        fs = fs[-nlast:]
    out = []
    for f in fs:
        rows = []
        for line in open(f, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
        out.append((os.path.basename(f), rows))
    return out


def games_of(rows):
    """把事件流切成局：qte_begin 开、qte_end（或下一 qte_begin）收。"""
    games, cur = [], None
    for r in rows:
        t = r.get("type")
        if t == "qte_begin":
            if cur:
                games.append(cur)
            cur = {"begin": r, "frames": [], "end": None}
        elif t == "frame" and cur is not None:
            cur["frames"].append(r)
        elif t == "qte_end" and cur is not None:
            cur["end"] = r
            games.append(cur)
            cur = None
    if cur:
        games.append(cur)
    return games


def game_form(g):
    """形态取帧里的众数（v0.2.1 的 qte_begin 没有 form 字段，只能从帧读）。"""
    cnt = collections.Counter(f.get("form") for f in g["frames"] if f.get("form"))
    if cnt:
        return cnt.most_common(1)[0][0]
    return g["begin"].get("form", "?")


# ---------------------------------------------------------------- 主
def main():
    args = sys.argv[1:]
    nlast = None
    if "--last" in args:
        nlast = int(args[args.index("--last") + 1])

    sess = read_sessions(nlast)
    print("会话数: %d" % len(sess))

    form_stat = collections.defaultdict(lambda: [0, 0])   # form -> [hit, miss]
    all_games = []
    for name, rows in sess:
        for g in games_of(rows):
            f = game_form(g)
            res = (g["end"] or {}).get("result", "?")
            all_games.append((name, f, res, g))
            if res == "hit":
                form_stat[f][0] += 1
            elif res == "miss":
                form_stat[f][1] += 1

    print("\n=== 形态 × 结果（累计 %d 局）===" % len(all_games))
    for f in sorted(form_stat):
        h, m = form_stat[f]
        print("  %-2s  %d 胜 / %d 负  胜率 %s"
              % (f, h, m, ("%.0f%%" % (100.0 * h / (h + m))) if h + m else "--"))

    # ---- C 形态回测 ----
    print("\n=== C 形态：指针 vs 底图判定色段（解码器回测）===")
    print("%-26s %-4s %-6s %-9s %-16s %-10s %-7s %s"
          % ("会话", "局", "帧", "底图", "判定段(屏幕x)", "指针x范围", "命中率", "结果"))
    ctot = collections.Counter()
    for name, f, res, g in all_games:
        if f != "C":
            continue
        frames = g["frames"]
        # 底图：取众数
        cnt = collections.Counter()
        ptrs, inz, tot = [], 0, 0
        for fr in frames:
            c = decode_c(fr.get("sub", ""))
            if c is None:
                continue
            ptr, bar, zs, ze = c
            cnt[bar] += 1
            ptrs.append(ptr)
            tot += 1
            if in_zone_c(c, 6):
                inz += 1
        if not cnt:
            print("%-26s %-4s  帧=%d 解不出" % (name[-22:], g["begin"].get("game"), len(frames)))
            continue
        bar = cnt.most_common(1)[0][0]
        c0 = decode_c(frames[0].get("sub", "")) if frames else None
        zs = c0[2] if c0 and c0[1] == bar else None
        ze = c0[3] if c0 and c0[1] == bar else None
        ctot[res] += 1
        print("%-26s %-4s %-6d U+%04X   %-16s %-10s %5.1f%%  %s"
              % (name[-22:], g["begin"].get("game"), len(frames), bar,
                 "[%s..%s]" % (zs, ze) if zs is not None else "-",
                 "%.0f~%.0f" % (min(ptrs), max(ptrs)) if ptrs else "-",
                 100.0 * inz / tot if tot else 0, res))
    if ctot:
        print("  C 形态小结: hit=%d miss=%d" % (ctot["hit"], ctot["miss"]))

    # ---- B 形态：找信号 ----
    print("\n=== B 形态：帧内容演化（找进度信号）===")
    bshapes = collections.Counter()
    for name, f, res, g in all_games:
        if f != "B":
            continue
        seqs = []
        for fr in g["frames"]:
            cps = tuple(hex(ord(ch)) for ch in fr.get("sub", ""))
            seqs.append(cps)
            bshapes[cps] += 1
        # 呈现首帧 / 中帧 / 末帧的码点序列
        if not seqs:
            continue
        mid = seqs[len(seqs) // 2]
        print("  %-4s %-5s n=%-3d 首=%s" % (
            g["begin"].get("game"), res, len(seqs), "".join(s.replace("0x", "")[:4] + "," for s in seqs[0])[:60]))
        print("            中=%s" % ("".join(s.replace("0x", "")[:4] + "," for s in mid)[:60]))
        print("            末=%s" % ("".join(s.replace("0x", "")[:4] + "," for s in seqs[-1])[:60]))
    print("\n  B 形态出现过的不同码点序列种数: %d" % len(bshapes))
    print("  最常见 5 种:")
    for cps, n in bshapes.most_common(5):
        print("    %dx  %s" % (n, "".join(s.replace("0x", "")[:4] + "," for s in cps)[:70]))


if __name__ == "__main__":
    main()
