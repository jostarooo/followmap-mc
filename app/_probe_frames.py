# -*- coding: utf-8 -*-
"""把实时日志里的指定局**逐帧摊开**：码点序列 + 指针 x + 绿区 x。
用来判定「底图内容在 256 格里到底贴左还是贴右」。
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


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else "12"
    sess = sorted(glob.glob(os.path.join(LOG, "session-*.jsonl")))[-1]
    rows = [json.loads(l) for l in open(sess, encoding="utf-8") if l.strip()]
    print("会话: %s" % os.path.basename(sess))

    gid = None
    cur = []
    games = {}
    for r in rows:
        if r.get("type") == "qte_begin":
            gid = r.get("game")
            cur = []
            games[gid] = {"begin": r, "frames": [], "end": None}
        elif r.get("type") == "frame" and gid in games:
            games[gid]["frames"].append(r)
        elif r.get("type") == "qte_end" and gid in games:
            games[gid]["end"] = r

    tab = Q.build_table()[0]
    BARW = {0xB002: 184, 0xB003: 184, 0xB004: 184, 0xB005: 184, 0xB006: 184,
            0xB007: 184, 0xB008: 184, 0xB009: 184, 0xB00A: 184,
            0xB00B: 120, 0xB00C: 163, 0xB011: 222}
    SEG = {
        0xB002: [(84, 100)], 0xB003: [(52, 68)], 0xB004: [(116, 132)],
        0xB005: [(84, 92), (132, 140)], 0xB006: [(4, 12), (60, 68), (108, 116), (140, 148)],
        0xB007: [(68, 76), (84, 92), (100, 108)], 0xB008: [(156, 160)],
        0xB009: [(84, 88)], 0xB00A: [(4, 8), (176, 180)],
        0xB00B: [(52, 68)],
    }

    for g in (want.split(",") if "," in want else [want]):
        g = int(g)
        if g not in games:
            print("没有局 %s" % g)
            continue
        G = games[g]
        print("\n=== 局 %d  by=%s  form(首帧)=%s  结果=%s  帧数=%d ===" % (
            g, G["begin"].get("by"), (G["frames"][0].get("form") if G["frames"] else "?"),
            (G["end"] or {}).get("result"), len(G["frames"])))
        print("title(首)=%r" % G["begin"].get("title"))
        print("%-4s %-34s %-7s %-7s %s" % ("n", "码点(hex)", "bar", "ptr_x", "zone_x(左对齐)"))
        ptrs = []
        for fr in G["frames"]:
            text = fr["sub"]
            x = 0
            ptr = None
            bar = 0
            for ch in text:
                cp = ord(ch)
                a = tab.get(cp)
                if a is None:
                    break
                if ptr is None and cp == 0xB001:
                    ptr = x
                if bar == 0 and 0xB002 <= cp <= 0xB00B:
                    bar = cp
                x += a
            if ptr is not None:
                ptrs.append(ptr)
            cps = ",".join("%04x" % ord(c) for c in text)
            zx = ""
            if bar in SEG:
                zx = " ".join("%d-%d" % (s, e) for s, e in SEG[bar])
            print("%-4s %-34s %-7s %-7s %s"
                  % (fr.get("n"), cps[:34], "%04x" % bar if bar else "-",
                     ptr if ptr is not None else "-", zx))
        if ptrs:
            print("→ 指针 x 范围 %d..%d（跨度 %d）" % (min(ptrs), max(ptrs), max(ptrs) - min(ptrs)))


if __name__ == "__main__":
    main()
