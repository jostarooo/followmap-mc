# -*- coding: utf-8 -*-
"""
v0.3 判定规则验证：A 形态（绿区字形）与 C 形态（底图色段）的「指针进入判定区」

数据：~/.fishauto/log/session-20261016-202809-auto.jsonl（11 局，用户手动玩 + 模组记录）
用法：PYTHONUTF8=1 D:\python\python.exe _probe_v3_rule.py
"""
import json, os, glob, sys

LOG = os.path.expanduser('~/.fishauto/log/session-20261016-202809-auto.jsonl')
P = json.load(open(os.path.join(os.path.dirname(__file__), 'qte_advance.json'), encoding='utf-8'))['points']
ADV = {int(k): v['advance'] for k, v in P.items()}

# 底图：码点 -> (内容宽, [(色段起, 色段止, 颜色)])  —— 图内坐标（1x）
# 内容宽由 _img_bars/*.png 像素实测（PNG 是 3x，坐标已除以 3）
BARS = {
    0xB002: (184, [(4, 52, 'red'), (52, 84, 'orange'), (84, 100, 'green'), (100, 132, 'orange'), (132, 180, 'red')]),
    0xB003: (184, [(4, 20, 'red'), (20, 52, 'orange'), (52, 68, 'green'), (68, 100, 'orange'), (100, 180, 'red')]),
    0xB004: (184, [(4, 84, 'red'), (84, 116, 'orange'), (116, 132, 'green'), (132, 164, 'orange'), (164, 180, 'red')]),
    0xB005: (184, [(4, 52, 'red'), (52, 84, 'orange'), (84, 92, 'green'), (92, 108, 'orange'), (108, 116, 'red'),
                   (116, 132, 'orange'), (132, 140, 'green'), (140, 156, 'orange'), (156, 180, 'red')]),
    0xB006: (184, [(4, 12, 'green'), (12, 28, 'red'), (28, 60, 'orange'), (60, 68, 'green'), (68, 84, 'orange'),
                   (84, 92, 'red'), (92, 108, 'orange'), (108, 116, 'green'), (116, 132, 'orange'),
                   (132, 140, 'red'), (140, 148, 'green'), (148, 156, 'orange'), (156, 180, 'red')]),
    0xB007: (184, [(4, 68, 'orange'), (68, 76, 'green'), (76, 84, 'red'), (84, 92, 'green'), (92, 100, 'red'),
                   (100, 108, 'green'), (108, 116, 'red'), (116, 180, 'orange')]),
    0xB008: (184, [(4, 140, 'red'), (140, 148, 'orange'), (148, 156, 'red'), (156, 160, 'green'),
                   (160, 168, 'red'), (168, 180, 'orange')]),
    0xB009: (184, [(4, 68, 'red'), (68, 84, 'orange'), (84, 88, 'green'), (88, 108, 'orange'), (108, 180, 'red')]),
    0xB00A: (184, [(4, 8, 'green'), (8, 176, 'red'), (176, 180, 'green')]),
    0xB00B: (120, [(4, 20, 'red'), (20, 52, 'orange'), (52, 68, 'green'), (68, 84, 'teal'),
                   (84, 100, 'blue'), (100, 116, 'purple')]),
    0xB00C: (163, [(4, 159, 'orange')]),   # bar10 无绿块（A 形态底图）
}

def scan(sub):
    """-> (zoneX, ptrX) 或 None"""
    x = 0; zx = None; px = None; bar = None
    for c in sub:
        cp = ord(c)
        a = ADV.get(cp)
        if a is None:
            return None
        if cp in BARS and bar is None:
            bar = cp
        if 0xB012 <= cp <= 0xB014 and zx is None:
            zx = x
        if cp == 0xB001 and px is None:
            px = x
        x += a
    return (zx, px, bar, x)

def c_zone(bar, ptr_x):
    """C 形态：ptr 右沿(ptr_x+5) 是否落在底图绿段内 -> (命中, 绿段屏幕区间列表)"""
    if bar not in BARS or BARS[bar] is None:
        return (False, [])
    W, segs = BARS[bar]
    off = 256 - W
    greens = [(off + a, off + b) for (a, b, col) in segs if col == 'green']
    hit = any(a <= ptr_x + 5 <= b or a <= ptr_x <= b for (a, b) in greens)
    return (hit, greens)

def main():
    ev = []
    for l in open(LOG, encoding='utf-8'):
        l = l.strip()
        if not l: continue
        try: ev.append(json.loads(l))
        except Exception: pass
    games = []; cur = None
    for o in ev:
        t = o.get('type')
        if t == 'qte_begin': cur = {'begin': o, 'frames': [], 'texts': []}
        elif t == 'frame' and cur is not None: cur['frames'].append(o)
        elif t in ('signal', 'notice') and cur is not None: cur['texts'].append(o)
        elif t == 'qte_end' and cur is not None: cur['end'] = o; games.append(cur); cur = None
    if cur: games.append(cur)

    print('局  form key      result  A绿区(zone)             C绿段(屏幕)            指针命中帧  区间')
    for i, g in enumerate(games, 1):
        fr = g['frames']
        form = fr[0].get('form') if fr else '?'
        zx = None; gp = []
        nA = nC = 0
        pmin = pmax = None
        for x in fr:
            s = scan(x.get('sub', ''))
            if not s: continue
            zone, ptr, bar, tot = s
            if ptr is None: continue
            pmin = ptr if pmin is None else min(pmin, ptr)
            pmax = ptr if pmax is None else max(pmax, ptr)
            if form == 'A' and zone is not None and zone <= ptr + 2 <= zone + 45:
                nA += 1
            if form == 'C':
                ok, greens = c_zone(bar, ptr)
                if ok: nC += 1
                if greens and not gp: gp = greens
        print('%2d  %-4s %-8s %-7s nA=%-4d                   nC=%-4d               ptr=%s..%s  %s' % (
            i, form, g['begin'].get('key'), g.get('end', {}).get('result'), nA, nC, pmin, pmax, gp))

if __name__ == '__main__':
    main()
