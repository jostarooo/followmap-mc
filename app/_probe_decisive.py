# -*- coding: utf-8 -*-
"""临时：门禁决定性检验 —— 「决定性按键」（离结局标记最近的那次）是否落在绿区内。
用完可删。若 HIT 局的决定性按键大多 in-zone，则聚合稀释（连按刷低比例）被解释，规则成立。"""
import sys, os, json, glob
sys.stdout.reconfigure(encoding='utf-8')
APP = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.expanduser("~"), ".fishprobe")

ADV = {int(k): v["advance"] for k, v in
       json.load(open(os.path.join(APP, "qte_advance.json"), encoding="utf-8"))["points"].items()}
JUDG = {0xB012, 0xB013, 0xB014}


def fg(text):
    x = 0.0
    jx = jw = px = None
    for c in text:
        cp = ord(c)
        a = ADV.get(cp)
        if a is None:
            return None
        if cp in JUDG and jx is None:
            jx, jw = x, a
        if cp == 0xB001 and px is None:
            px = x
        x += a
    return (jx, jw, px) if (jx is not None and px is not None) else None


def load(pat, types):
    out = []
    for f in sorted(glob.glob(pat)):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("wall") and o.get("type") in types:
                out.append(o)
    out.sort(key=lambda o: o["wall"])
    return out


subs = [e for e in load(os.path.join(DATA, "events", "*.jsonl"), ("subtitle",))
        if (e.get("text") or "").strip()]
press = load(os.path.join(DATA, "inputs", "*.jsonl"), ("key", "mouse"))
marks = load(os.path.join(DATA, "inputs", "*.jsonl"), ("mark",))
marks = [m for m in marks if m.get("key") in (".", "'")]

eps, cur = [], []
for e in subs:
    if cur and e["wall"] - cur[-1]["wall"] > 1500:
        eps.append(cur)
        cur = []
    cur.append(e)
if cur:
    eps.append(cur)

rows = []
for ep in eps:
    fr = [(e["wall"], fg(e["text"])) for e in ep]
    fr = [(w, g) for w, g in fr if g]
    if len(fr) < 5:
        continue
    t0, t1 = fr[0][0], fr[-1][0]
    for m in marks:
        if t1 - 200 <= m["wall"] <= t1 + 2500:
            win = [k for k in press
                   if m["wall"] - 1200 <= k["wall"] <= m["wall"] + 200
                   and k.get("name") not in ("i", ".", "'")]
            if not win:
                rows.append((m["key"], t0, len(fr), 0, None, None, None))
                break
            near = min(win, key=lambda k: abs(k["wall"] - m["wall"]))
            nf = min(fr, key=lambda f: abs(f[0] - near["wall"]))
            if abs(nf[0] - near["wall"]) > 100:
                rows.append((m["key"], t0, len(fr), len(win), None, None, None))
                break
            jx, jw, px = nf[1]
            rows.append((m["key"], t0, len(fr), len(win), px - jx, jw,
                         0 <= px - jx <= jw))
            break

print("%-8s %-12s %5s %5s %8s %6s %7s"
      % ("结局", "局起点", "帧数", "窗内键", "d", "区宽", "in-zone"))
import datetime
for r in rows:
    print("%-8s %-12s %5d %5d %8s %6s %7s"
          % ("HIT" if r[0] == "." else "FAIL",
             datetime.datetime.fromtimestamp(r[1] / 1000.0).strftime("%H:%M:%S"),
             r[2], r[3],
             ("%.0f" % r[4]) if r[4] is not None else "-", r[5],
             ("是" if r[6] else "否") if r[6] is not None else "-"))

ok = [r for r in rows if r[0] == "." and r[6] is not None]
bad = [r for r in rows if r[0] == "'" and r[6] is not None]
print()
if ok:
    print("HIT  决定性按键 in-zone: %d/%d = %.0f%%" % (sum(r[6] for r in ok), len(ok), 100.0 * sum(r[6] for r in ok) / len(ok)))
if bad:
    print("FAIL 决定性按键 in-zone: %d/%d = %.0f%%" % (sum(r[6] for r in bad), len(bad), 100.0 * sum(r[6] for r in bad) / len(bad)))
