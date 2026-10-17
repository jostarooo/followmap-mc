# -*- coding: utf-8 -*-
"""全量局分类：不筛「解得出几何」，把 A/B 两种形态全部捞出来。

用法： python _probe_formB.py [--dump N]
"""
import sys, collections, json
import qtemap as Q

sys.stdout.reconfigure(encoding="utf-8")


def all_episodes(evs, min_frames=5):
    """split_episodes + 同样的合并规则，但**不**按几何可解性过滤。"""
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


def seg_of(text):
    """返回 (段数, 首码点, 末码点, 是否含绿区, 是否含指针)"""
    ids = [ord(c) for c in text if Q.is_bar(ord(c))]
    if not ids:
        return None
    return (len(ids), ids[0], ids[-1],
            any(c in Q.JUDG for c in ids), Q.POINTER in ids)


def main():
    evs = Q.load_events()
    eps = all_episodes(evs)
    print("全量局数（未按几何过滤）: %d" % len(eps))

    kinds = collections.Counter()
    games = []
    for ep in eps:
        sigs = [seg_of(e["text"]) for e in ep]
        sigs = [s for s in sigs if s]
        if not sigs:
            kinds["无条图帧"] += 1
            continue
        c = collections.Counter(sigs)
        top, n = c.most_common(1)[0]
        has_judg = any(s[3] for s in sigs)
        has_ptr = any(s[4] for s in sigs)
        key = (top[0], top[1], top[2], has_judg, has_ptr)
        kinds[key] += 1
        games.append({
            "t0": ep[0]["wall"], "frames": len(ep), "top": top, "n": n,
            "ok": sum(1 for s in sigs if s[3]),
            "has_judg": has_judg, "has_ptr": has_ptr,
            "keys": sorted(set(s[0] for s in sigs)),
            "heads": sorted(set(s[1] for s in sigs)),
            "tails": sorted(set(s[2] for s in sigs)),
            "ep": ep,
        })

    print("\n=== 按 (段数, 首码点, 末码点, 含绿区, 含指针) 分组 ===")
    for k, n in kinds.most_common():
        if isinstance(k, str):
            print("  %-46s %d 局" % (k, n))
            continue
        seg, h, t, j, p = k
        print("  段数=%d 首=U+%04X 末=U+%04X 绿区=%-5s 指针=%-5s -> %d 局"
              % (seg, h, t, j, p, n))

    print("\n=== 逐局 ===")
    print("%-10s %6s %6s %6s %-7s %-7s %s" %
          ("起点(ms)", "帧", "含绿区", "主签名段数", "含绿区", "含指针", "本局出现段数"))
    for g in sorted(games, key=lambda x: x["t0"])[:60]:
        print("%-10s %6d %6d %6s %-7s %-7s %s" %
              (g["t0"], g["frames"], g["ok"], g["top"][0],
               g["has_judg"], g["has_ptr"], g["keys"]))

    if "--dump" in sys.argv:
        n = int(sys.argv[sys.argv.index("--dump") + 1])
        print("\n=== 前 %d 局的帧样例（每局前 6 帧）===" % n)
        for g in sorted(games, key=lambda x: x["t0"])[:n]:
            print("--- t0=%s frames=%d has_judg=%s has_ptr=%s" %
                  (g["t0"], g["frames"], g["has_judg"], g["has_ptr"]))
            for e in g["ep"][:6]:
                s = seg_of(e["text"])
                print("    %-8s %r  -> %s" %
                      ("OK" if s and s[3] else "nozone", e["text"], s))


if __name__ == "__main__":
    main()
