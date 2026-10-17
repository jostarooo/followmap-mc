# -*- coding: utf-8 -*-
"""深挖 C 类（有指针无绿区）与 B 类（首 B011）的帧结构：段落点是否逐帧变化 + title/actionbar 里有什么。"""
import sys, collections, json
import qtemap as Q

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")
from _probe_formB import all_episodes, seg_of


def dump(ep, evs, label, limit=18):
    print("=" * 78)
    print("%s  t0=%s  frames=%d" % (label, ep[0]["wall"], len(ep)))
    t0, t1 = ep[0]["wall"], ep[-1]["wall"]
    print("-- 同窗口 title/actionbar --")
    for e in evs:
        if e.get("type") in ("title", "actionbar") and t0 - 1500 <= e.get("wall", 0) <= t1 + 1500:
            t = (e.get("text") or "").strip()
            if t:
                print("   [%s] %s %r" % (e["wall"], e["type"], t))
    print("-- 帧（段落点 = 各 bar 字形的 x0..x1，Δ 为相邻帧位移）--")
    prev = None
    for i, e in enumerate(ep[:limit]):
        cells, seps, total = Q.decode(e["text"])
        xs = ["U+%04X@%.0f" % (s["cp"], s["x0"]) for s in seps]
        d = ""
        if prev is not None and len(prev) == len(seps):
            ds = [seps[j]["x0"] - prev[j] for j in range(len(seps))]
            d = "  Δ=" + ",".join("%+.0f" % v for v in ds)
        prev = [s["x0"] for s in seps]
        print("  %2d %-6s len=%-3d total=%-6.1f  %s%s"
              % (i, "OK" if seg_of(e["text"]) and seg_of(e["text"])[3] else "nozone",
                 len(e["text"]), total, "  ".join(xs), d))


def main():
    evs = Q.load_events()
    eps = all_episodes(evs)
    cls = {"A": [], "C": [], "B": []}
    for ep in eps:
        sigs = [seg_of(e["text"]) for e in ep]
        sigs = [s for s in sigs if s]
        if not sigs:
            continue
        has_judg = any(s[3] for s in sigs)
        has_ptr = any(s[4] for s in sigs)
        top = collections.Counter(sigs).most_common(1)[0][0]
        if has_judg:
            cls["A"].append(ep)
        elif has_ptr:
            cls["C"].append(ep)
        else:
            cls["B"].append(ep)
    print("A=%d C=%d B=%d" % (len(cls["A"]), len(cls["C"]), len(cls["B"])))
    # 每类取两局（一长一短）
    for k in ("C", "B"):
        sel = sorted(cls[k], key=lambda e: -len(e))
        for ep in (sel[0], sel[len(sel) // 2]) if len(sel) > 1 else sel:
            dump(ep, evs, "【%s 类】" % k, limit=22)

    # C 类首码点的局内变化
    print("=" * 78)
    print("C 类：局内首段码点 + 段落点变化（看首码点是否也是变量）")
    for ep in sorted(cls["C"], key=lambda e: -len(e))[:6]:
        heads = []
        for e in ep:
            ids = [ord(c) for c in e["text"] if Q.is_bar(ord(c))]
            cells, seps, total = Q.decode(e["text"])
            heads.append((ids[0] if ids else None,
                          "%.0f" % seps[0]["x0"] if seps else "-",
                          "%.0f" % seps[-1]["x0"] if len(seps) > 1 else "-"))
        ch = sorted(set(h[0] for h in heads))
        print("  局 t0=%s 帧=%d 首码点集合=%s | x0 序列前12=%s | 末段x前12=%s"
              % (ep[0]["wall"], len(ep),
                 " ".join("U+%04X" % c for c in ch if c),
                 [h[1] for h in heads[:12]], [h[2] for h in heads[:12]]))


if __name__ == "__main__":
    main()
