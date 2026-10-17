# -*- coding: utf-8 -*-
"""验证「三形态判据」——即准备写进 Java 的 Qte.form(sub) 的 Python 复刻版。

判据（准备写进 mod 的原文）：
    ptr  = 帧里含 0xB001
    zone = 帧里含 0xB012..0xB014
    icon = 帧里含 0xB011 或 0xB00D..0xB010
    form = ptr ? (zone ? "A" : "C") : (icon ? "B" : "?")

要回答三个问题：
  1. 全量 119 局按此判据分出的 A/C/B 各多少？（对照 71/24/24）
  2. 每局内部形态是否单一（无混合帧）？
  3. B 形态的局里**有没有** B001（若 C 帧与 B 帧都含 B001，判据就废了）？

用法： python _probe_form_rule.py [--dump N]
"""
import collections
import sys

import qtemap as Q

sys.stdout.reconfigure(encoding="utf-8")

PTR = 0xB001
ZONE = set(range(0xB012, 0xB015))
ICON = {0xB011} | set(range(0xB00D, 0xB011))


def form(text):
    ptr = zone = icon = False
    for ch in text:
        cp = ord(ch)
        if not Q.is_bar(cp):
            continue
        if cp == PTR:
            ptr = True
        elif cp in ZONE:
            zone = True
        elif cp in ICON:
            icon = True
    if ptr:
        return "A" if zone else "C"
    if icon:
        return "B"
    return "?"


def all_episodes(evs, min_frames=5):
    """与 _probe_formB.py 完全相同的分局规则（**不**按几何可解性过滤）。"""
    eps = Q.split_episodes(evs)
    merged = []
    for ep in eps:
        if len(ep) < 3:
            if merged and ep and ep[0]["wall"] - merged[-1][-1]["wall"] <= 3000:
                merged[-1].extend(ep)
            continue
        if merged and ep[0]["wall"] - merged[-1][-1]["wall"] <= 3000:
            merged[-1].extend(ep)
        else:
            merged.append(list(ep))
    return [ep for ep in merged if len(ep) >= min_frames]


def main():
    evs = Q.load_events()
    eps = all_episodes(evs)
    print("全量局数（未按几何过滤）: %d" % len(eps))

    games = []
    for ep in eps:
        fs = [form(e["text"]) for e in ep]
        fs = [f for f in fs if f != "?"]
        if not fs:
            games.append(("无条图帧", ep, []))
            continue
        games.append((collections.Counter(fs).most_common(1)[0][0], ep, fs))

    print("\n=== 1) 主形态分布（每局取出现最多的形态）===")
    dist = collections.Counter(g[0] for g in games)
    for k, n in dist.most_common():
        print("  %-8s %3d 局  %5.1f%%" % (k, n, 100.0 * n / max(1, len(games))))

    print("\n=== 2) 局内形态纯度（该局出现的全部形态集合）===")
    purity = collections.Counter()
    for main, ep, fs in games:
        purity[(main, tuple(sorted(set(fs))))] += 1
    for (main, seen), n in purity.most_common():
        flag = "★ 混合" if len(seen) > 1 else "单一"
        print("  主=%-3s 实际出现=%-18s %-6s %3d 局" % (main, seen, flag, n))

    mixed = [g for g in games if len(set(g[2])) > 1]
    print("\n混合局数: %d %s" % (len(mixed), "(应尽量少)" if mixed else ""))

    print("\n=== 3) B 形态局里有没有出现 0xB001 指针 ===")
    b_games = [g for g in games if g[0] == "B"]
    print("B 形态局数: %d" % len(b_games))
    bad = 0
    for main, ep, fs in b_games:
        for e in ep:
            cps = sorted({ord(c) for c in e["text"] if Q.is_bar(ord(c))})
            if PTR in cps:
                bad += 1
                break
    print("  含 B001 的 B 局: %d  %s" % (bad, "★ 判据会被 C 抢走" if bad else "OK 判据成立"))

    print("\n=== 4) C 形态局的特征（末码点 / 是否含绿区 / 是否含 icon）===")
    c_games = [g for g in games if g[0] == "C"]
    print("C 形态局数: %d" % len(c_games))
    feat = collections.Counter()
    cpsets = collections.Counter()
    for main, ep, fs in c_games:
        for e in ep:
            cps = {ord(c) for c in e["text"] if Q.is_bar(ord(c))}
            feat[(bool(cps & ZONE), bool(cps & ICON))] += 1
            cpsets[tuple(sorted(cps))] += 1
    for k, n in feat.most_common():
        print("  含绿区=%-5s 含icon=%-5s -> %d 帧" % (k[0], k[1], n))
    print("  码点集合（出现最多的 4 种）:")
    for cs, n in cpsets.most_common(4):
        print("    %s  x%d" % (" ".join("%04X" % c for c in cs), n))

    if "--dump" in sys.argv:
        n = int(sys.argv[sys.argv.index("--dump") + 1])
        print("\n=== 每种形态前 %d 局的帧样例 ===" % n)
        for want in ("A", "C", "B"):
            print("--- form=%s ---" % want)
            shown = 0
            for main, ep, fs in games:
                if main != want or shown >= n:
                    continue
                shown += 1
                print("  局 t0=%s frames=%d 形态集=%s" %
                      (ep[0]["wall"], len(ep), sorted(set(fs))))
                for e in ep[:4]:
                    cps = sorted({ord(c) for c in e["text"] if Q.is_bar(ord(c))})
                    print("      form=%s 条图码点=%s" %
                          (form(e["text"]),
                           " ".join("%04X" % c for c in cps[:14])))


if __name__ == "__main__":
    main()
