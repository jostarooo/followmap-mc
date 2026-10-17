#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fishviz —— 采集数据可视化看板

回答一个问题：**每种不同的小游戏，各记录了多少次、够不够用。**

数据来源（与 fishprobe / fishkey 一致的落盘结构）
------------------------------------------------
  A 通道  ~/.fishprobe/events/*.jsonl     Fabric 探针（title / subtitle / actionbar / bossbar / state）
  B 通道  ~/.fishprobe/inputs/*.jsonl     Raw Input 键鼠记录器（key / mouse / mark）
  C 统计  ~/.fishprobe/stats/history.jsonl 本工具追加的历次汇总（用于看累计进度）

一局的判定
----------
1. QTE 帧 = subtitle 文本里含**韩文音节分隔符**(U+AC00–U+D7A3)的帧；
   纯英文/中文的 subtitle（如 "You caught a(n) 红海星"）不算。
2. 按帧间隔 > gap(默认 1500ms) 切局。
3. 形态 = 「分隔符个数 + 首尾分隔符」归一（**数值变化是指针在动，不是形态**）：
     · 3 段、首 U+B00C、尾 U+B001        -> T3
     · 2 段、首 U+B011                    -> T2
     · 2 段、尾 U+B001、首 U+B003..B00B   -> T3s（疑似 T3 极短局）
4. 按键要求 = 局前最近的 title「按下 <X> 开始」。
5. 结果 = 游戏自带反馈优先（比人工打点可靠）：
     成功 `You caught a(n) <鱼>`（actionbar / subtitle）
     失败 `What a pity!` / `The fish escaped...` / `Be concentrated!` / `Bad luck`
   没有游戏反馈时才退化用 B 通道的 i/./' 打点。

用法
----
    python fishviz.py                     # 终端表格 + 生成 HTML 看板
    python fishviz.py --watch 5           # 每 5 秒重算重生成（页面自带自动刷新）
    python fishviz.py --open              # 生成后直接打开浏览器
    python fishviz.py --snapshot          # 追加一行累计进度到 stats/history.jsonl
    python fishviz.py --text              # 只要终端表格
    python fishviz.py --json              # 打印模型 JSON
"""
import argparse
import collections
import datetime
import glob
import html
import json
import os
import sys
import time
from string import Template

# ---------------------------------------------------------------- 常量
TARGET_PER_CELL = 20          # 每格目标局数（补采目标）
DEFAULT_GAP_MS = 1500
MIN_FRAMES = 5                # 少于此帧数视为残缺局

SUCCESS_PREFIX = "You caught a(n)"
FAIL_PATTERNS = ("What a pity", "The fish escaped", "Be concentrated",
                 "Bad luck", "可惜", "失败")

SHAPE_ORDER = ["T3", "T2", "T3s", "其它"]
SHAPE_LABEL = {
    "T3": "T3 · 三段布局 (B00C … B001)",
    "T2": "T2 · 两段布局 (B011 …)",
    "T3s": "T3s · 两段极短局 (…B001)",
    "其它": "其它 / 未归类",
}
SHAPE_COLOR = {"T3": "#e2544a", "T2": "#3f7fd6", "T3s": "#d99a2b", "其它": "#8a8f98"}
REQ_ORDER = ["左键", "左Shift", "其它", "未知"]
RESULT_ORDER = ["成功", "失败", "未知"]


def setup_console():
    """中文 / emoji 在真控制台与重定向两种情况下都能正确输出。"""
    try:
        import ctypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.SetConsoleOutputCP(65001)
        k.SetConsoleCP(65001)
    except Exception:                                  # noqa: BLE001
        pass
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                              # noqa: BLE001
            pass


def home(*p):
    return os.path.join(os.path.expanduser("~"), ".fishprobe", *p)


# ---------------------------------------------------------------- 分类
def is_sep(ch):
    return 0xAC00 <= ord(ch) <= 0xD7A3


def seps_of(text):
    return [ch for ch in (text or "") if is_sep(ch)]


def cp(ch):
    return "U+%04X" % ord(ch)


def is_qte_frame(text):
    """QTE 进度条帧：subtitle 里含韩文音节分隔符。"""
    return bool(seps_of(text))


def norm_shape(sep_sets):
    seqs = [s for s in sep_sets if s]
    if not seqs:
        return "其它"
    k = collections.Counter(len(s) for s in seqs).most_common(1)[0][0]
    ok = [s for s in seqs if len(s) == k]
    f = collections.Counter(s[0] for s in ok).most_common(1)[0][0]
    l = collections.Counter(s[-1] for s in ok).most_common(1)[0][0]
    if k == 3 and ord(f) == 0xB00C:
        return "T3"
    if k == 2 and ord(f) == 0xB011:
        return "T2"
    if k == 2 and ord(l) == 0xB001:
        return "T3s"
    return "其它"


def norm_req(text):
    """从「按下 左键 开始」这类文本里抽出按键要求。"""
    if not text:
        return "未知"
    if "左键" in text or "左击" in text:
        return "左键"
    if "Shift" in text or "shift" in text or "上档" in text:
        return "左Shift"
    return "其它"


def is_result_text(text):
    if not text:
        return None
    if text.startswith(SUCCESS_PREFIX):
        return "成功"
    for p in FAIL_PATTERNS:
        if p in text:
            return "失败"
    return None


# ---------------------------------------------------------------- 读取
def load_events(ev_dir):
    evs = []
    if not os.path.isdir(ev_dir):
        return evs
    for f in sorted(glob.glob(os.path.join(ev_dir, "*.jsonl"))):
        sess = os.path.basename(f).replace("session-", "").replace("-world.jsonl", "")
        for line in open(f, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:                          # noqa: BLE001
                continue
            if "wall" in o:
                o["_sess"] = sess
                evs.append(o)
    evs.sort(key=lambda o: o["wall"])
    return evs


def load_input_sessions(in_dir):
    """B 通道：返回 [(文件, 起, 止, 事件列表)]，以及打点事件。"""
    sessions = []
    if not os.path.isdir(in_dir):
        return sessions
    for f in sorted(glob.glob(os.path.join(in_dir, "*.jsonl"))):
        rows = []
        for line in open(f, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:                          # noqa: BLE001
                continue
        ws = [r["wall"] for r in rows if r.get("wall")]
        if ws:
            sessions.append((os.path.basename(f), min(ws), max(ws), rows))
    return sessions


# ---------------------------------------------------------------- 建模
def build_model(ev_dir=None, in_dir=None, gap_ms=DEFAULT_GAP_MS):
    ev_dir = ev_dir or home("events")
    in_dir = in_dir or home("inputs")
    evs = load_events(ev_dir)
    inputs = load_input_sessions(in_dir)

    # ---- QTE 帧 -> 切局
    qte = [e for e in evs if e.get("type") == "subtitle" and is_qte_frame(e.get("text"))]
    eps, cur = [], []
    for e in qte:
        if cur and e["wall"] - cur[-1]["wall"] > gap_ms:
            eps.append(cur)
            cur = []
        cur.append(e)
    if cur:
        eps.append(cur)

    # ---- 辅助索引
    titles = [(e["wall"], (e.get("text") or "").strip())
              for e in evs if e.get("type") == "title" and (e.get("text") or "").strip()]
    req_titles = [(w, t) for w, t in titles if t.startswith("按下")]
    fb = [(e["wall"], (e.get("text") or "").strip())
          for e in evs if e.get("type") in ("actionbar", "subtitle", "title")
          and (e.get("text") or "").strip()]
    marks = []
    for name, a, b, rows in inputs:
        for r in rows:
            if r.get("type") == "mark":
                marks.append((r["wall"], r.get("role") or ""))
    key_downs = []
    for name, a, b, rows in inputs:
        for r in rows:
            if r.get("type") == "key" and r.get("act") == "down":
                key_downs.append((r["wall"], r.get("name") or ""))
            elif r.get("type") == "mouse":
                key_downs.append((r["wall"], "MOUSE:" + str(r.get("btn"))))

    def covered(t):
        return any(a - 5000 <= t <= b + 5000 for _, a, b, _ in inputs)

    episodes = []
    for i, ep in enumerate(eps, 1):
        t0, t1 = ep[0]["wall"], ep[-1]["wall"]
        shape = norm_shape([seps_of(e.get("text") or "") for e in ep])
        # 按键要求：局前 12s 内最近的「按下 … 开始」
        req_txt, req = "", "未知"
        near = [(w, t) for w, t in req_titles if t0 - 12000 <= w <= t0 + 600]
        if near:
            req_txt = near[-1][1]
            req = norm_req(req_txt)
        # 结果：游戏自带反馈优先
        win = [t for t in fb if t0 - 500 <= t[0] <= t1 + 9000]
        res, res_src, fish = "未知", "", ""
        for w, t in win:
            if t.startswith(SUCCESS_PREFIX):
                res = "成功"
                res_src = "游戏反馈"
                fish = t[len(SUCCESS_PREFIX):].strip()
                break
        if res == "未知":
            for w, t in win:
                if is_result_text(t) == "失败":
                    res, res_src = "失败", "游戏反馈"
                    break
        if res == "未知":                # 退化到人工打点
            mk = [r for w, r in marks if t0 - 500 <= w <= t1 + 9000]
            if "success" in mk:
                res, res_src = "成功", "人工打点"
            elif "fail" in mk:
                res, res_src = "失败", "人工打点"
        # B 通道真实输入
        bt = [n for w, n in key_downs if t0 - 500 <= w <= t1 + 2000]
        n_shift = sum(1 for n in bt if n == "SHIFT")
        n_mouse = sum(1 for n in bt if n.startswith("MOUSE:"))
        episodes.append(dict(
            idx=i, t0=t0, t1=t1, wall0=t0, wall1=t1, sess=ep[0].get("_sess", ""),
            frames=len(ep), dur=round((t1 - t0) / 1000.0, 2),
            shape=shape, req=req, req_text=req_txt, result=res, result_src=res_src,
            fish=fish, covered=covered(t0), real_keys=len(bt),
            n_shift=n_shift, n_mouse=n_mouse,
        ))

    valid = [e for e in episodes if e["frames"] >= MIN_FRAMES]

    # ---- 交叉统计
    matrix = collections.defaultdict(lambda: collections.defaultdict(
        lambda: collections.defaultdict(int)))
    for e in valid:
        matrix[e["shape"]][e["req"]][e["result"]] += 1

    by_shape = collections.defaultdict(lambda: collections.Counter())
    for e in valid:
        by_shape[e["shape"]]["局数"] += 1
        by_shape[e["shape"]][e["result"]] += 1
        by_shape[e["shape"]]["有真实按键"] += 1 if e["real_keys"] else 0

    shapes = [s for s in SHAPE_ORDER if s in by_shape]
    shapes += [s for s in by_shape if s not in SHAPE_ORDER]

    model = dict(
        generated=time.time(),
        generated_str=time.strftime("%Y-%m-%d %H:%M:%S"),
        ev_dir=ev_dir, in_dir=in_dir,
        events_total=len(evs), qte_frames=len(qte),
        episodes_raw=len(episodes), episodes=len(valid),
        dropped=len(episodes) - len(valid),
        shapes=shapes,
        by_shape={s: dict(by_shape[s]) for s in by_shape},
        matrix={s: {r: dict(matrix[s][r]) for r in matrix[s]} for s in matrix},
        episodes_list=valid,
        inputs=[dict(file=n, t0=a, t1=b,
                     events=len(rows),
                     mouse=sum(1 for r in rows if r.get("type") == "mouse"))
                for n, a, b, rows in inputs],
        files_events=len(glob.glob(os.path.join(ev_dir, "*.jsonl"))),
        covered_eps=sum(1 for e in valid if e["covered"]),
        with_keys=sum(1 for e in valid if e["real_keys"]),
        success=sum(1 for e in valid if e["result"] == "成功"),
        fail=sum(1 for e in valid if e["result"] == "失败"),
        span=(min((e["t0"] for e in valid), default=0),
              max((e["t1"] for e in valid), default=0)),
        target=TARGET_PER_CELL,
    )
    model["gaps"] = compute_gaps(model)
    return model


def compute_gaps(m):
    """自动生成「还差什么」清单。"""
    gaps = []
    for s in m["shapes"]:
        for r in REQ_ORDER:
            cell = m["matrix"].get(s, {}).get(r)
            if not cell:
                continue
            n = sum(cell.values())
            if n < m["target"]:
                gaps.append(dict(shape=s, req=r, have=n, need=m["target"] - n,
                                 succ=cell.get("成功", 0), fail=cell.get("失败", 0)))
    gaps.sort(key=lambda g: g["have"])
    return gaps


# ---------------------------------------------------------------- 终端输出
def fmt_ts(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S")


def render_text(m, verbose=False):
    W = 92
    print("=" * W)
    print(" 钓鱼采集数据看板 · %s" % m["generated_str"])
    print("=" * W)
    print(" A 通道 %d 个文件 / %d 事件，其中 QTE 帧 %d"
          % (m["files_events"], m["events_total"], m["qte_frames"]))
    print(" B 通道 %d 个会话，共 %d 条记录"
          % (len(m["inputs"]), sum(i["events"] for i in m["inputs"])))
    print(" 切出 %d 段，有效局 %d（丢弃 <%d 帧的碎片 %d 段）"
          % (m["episodes_raw"], m["episodes"], MIN_FRAMES, m["dropped"]))
    if m["span"][1]:
        print(" 时间跨度 %s ~ %s" % (fmt_ts(m["span"][0]), fmt_ts(m["span"][1])))
    print()
    print(" ── 每种小游戏记录了多少次 " + "─" * (W - 24))
    print("   %-30s %6s %6s %6s %6s" % ("形态", "局数", "成功", "失败", "有真实按键"))
    for s in m["shapes"]:
        d = m["by_shape"][s]
        bar = "█" * min(40, d.get("局数", 0))
        print("   %-30s %6d %6d %6d %6d  %s"
              % (SHAPE_LABEL.get(s, s), d.get("局数", 0), d.get("成功", 0),
                 d.get("失败", 0), d.get("有真实按键", 0), bar))
    print()
    print(" ── 形态 × 按键要求 × 结果 " + "─" * (W - 22))
    print("   %-10s %-9s %5s %5s %5s %5s   %s"
          % ("形态", "按键要求", "局数", "成功", "失败", "未知", "目标进度"))
    for s in m["shapes"]:
        for r in REQ_ORDER:
            cell = m["matrix"].get(s, {}).get(r)
            if not cell:
                continue
            n = sum(cell.values())
            ok, bad = cell.get("成功", 0), cell.get("失败", 0)
            unknown = n - ok - bad
            filled = int(round(min(1.0, n / m["target"]) * 12))
            prog = "[%s%s] %d/%d%s" % ("█" * filled, "·" * (12 - filled),
                                       n, m["target"], "" if n >= m["target"] else "  ← 缺")
            print("   %-10s %-9s %5d %5d %5d %5d   %s"
                  % (s, r, n, ok, bad, unknown, prog))
    print()
    print(" ── B 通道覆盖 " + "─" * (W - 14))
    for i in m["inputs"]:
        print("   %-38s %s ~ %s  %5d 条  鼠标 %d 条"
              % (i["file"], fmt_ts(i["t0"]), fmt_ts(i["t1"]), i["events"], i["mouse"]))
    print("   有效局中被 B 通道覆盖 %d/%d，其中有真实按键事件 %d 局"
          % (m["covered_eps"], m["episodes"], m["with_keys"]))
    print()
    if m["gaps"]:
        print(" ── 还差什么（目标每格 %d 局） " % m["target"] + "─" * (W - 30))
        for g in m["gaps"][:14]:
            print("   %-8s × %-8s 已有 %2d，还缺 %2d   (成功 %d / 失败 %d)"
                  % (g["shape"], g["req"], g["have"], g["need"], g["succ"], g["fail"]))
    else:
        print(" 每格都已达到 %d 局目标。" % m["target"])
    print("=" * W)
    if verbose:
        print()
        print(" 全部有效局：")
        print("   %3s %8s %10s %6s %6s %-6s %-8s %-6s %s"
              % ("#", "时间", "会话", "帧数", "秒", "形态", "按键", "结果", "真实按键"))
        for e in m["episodes_list"]:
            print("   %3d %8s %10s %6d %6.1f %-6s %-8s %-6s shift=%d mouse=%d %s"
                  % (e["idx"], fmt_ts(e["t0"]), e["sess"][-6:], e["frames"], e["dur"],
                     e["shape"], e["req"], e["result"], e["n_shift"], e["n_mouse"],
                     ("·" + e["fish"]) if e["fish"] else ""))
    return 0


# ---------------------------------------------------------------- HTML
def esc(s):
    return html.escape(str(s), quote=True)


def bar_row(label, count, total, color, sub=""):
    pct = (count / total * 100) if total else 0
    return (
        '<div class="bar-row">'
        '<div class="bar-label">%s</div>'
        '<div class="bar-track"><div class="bar-fill" style="width:%.2f%%;background:%s"></div></div>'
        '<div class="bar-num">%d<span class="muted">%s</span></div>'
        '</div>' % (esc(label), pct, color, count, sub)
    )


def cell_color(n, target):
    if n == 0:
        return "rgba(140,150,165,.10)", "#8a8f98"
    ratio = min(1.0, n / target)
    # 从浅到深
    r = int(240 - 175 * ratio)
    g = int(246 - 120 * ratio)
    b = int(250 - 90 * ratio)
    return "rgba(63,127,214,%.2f)" % (0.12 + 0.72 * ratio), ("#fff" if ratio > 0.55 else "inherit")


def render_html(m):
    total = m["episodes"] or 1
    maxshape = max([m["by_shape"][s].get("局数", 0) for s in m["shapes"]] or [1])

    # KPI
    kpis = [
        ("有效局数", m["episodes"], "共 %d 段原始切片" % m["episodes_raw"]),
        ("形态种类", len([s for s in m["shapes"] if s != "其它"]), "T2 / T3 / T3s"),
        ("成功率", "%d%%" % round(m["success"] / total * 100), "%d 成功 / %d 失败"
         % (m["success"], m["fail"])),
        ("有真实按键", "%d/%d" % (m["with_keys"], m["episodes"]),
         "B 通道覆盖 %d 局" % m["covered_eps"]),
    ]
    kpi_html = "".join(
        '<div class="kpi"><div class="kpi-v">%s</div><div class="kpi-k">%s</div>'
        '<div class="kpi-s">%s</div></div>' % (esc(v), esc(k), esc(s))
        for k, v, s in kpis)

    # 形态条形图
    bars = "".join(
        bar_row(SHAPE_LABEL.get(s, s), m["by_shape"][s].get("局数", 0), maxshape,
                SHAPE_COLOR.get(s, "#888"),
                " · 成功 %d / 失败 %d / 有真实按键 %d"
                % (m["by_shape"][s].get("成功", 0), m["by_shape"][s].get("失败", 0),
                   m["by_shape"][s].get("有真实按键", 0)))
        for s in m["shapes"])

    # 矩阵
    head = "".join('<th>%s</th>' % esc(r) for r in REQ_ORDER)
    body = ""
    for s in m["shapes"]:
        body += '<tr><th class="rowh" style="border-left:4px solid %s">%s</th>' % (
            SHAPE_COLOR.get(s, "#888"), esc(s))
        for r in REQ_ORDER:
            cell = m["matrix"].get(s, {}).get(r)
            n = sum(cell.values()) if cell else 0
            bg, fg = cell_color(n, m["target"])
            ok = cell.get("成功", 0) if cell else 0
            bad = cell.get("失败", 0) if cell else 0
            unk = n - ok - bad
            cls = "cell" + (" empty" if n == 0 else "") + (" full" if n >= m["target"] else "")
            tip = "%s × %s：共 %d 局（成功 %d / 失败 %d / 未知 %d）" % (s, r, n, ok, bad, unk)
            body += ('<td class="%s" style="background:%s;color:%s" title="%s">'
                     '<span class="cn">%d</span>'
                     '<span class="csub">%d/%d</span></td>'
                     % (cls, bg, fg, esc(tip), n, ok, bad))
        body += "</tr>"
    matrix_html = '<table class="matrix"><thead><tr><th></th>%s</tr></thead><tbody>%s</tbody></table>' % (head, body)

    # 覆盖时间条（SVG）
    timeline = render_timeline_svg(m)

    # 进度条清单
    gaps = ""
    for g in m["gaps"][:16]:
        pct = min(100, g["have"] / m["target"] * 100)
        gaps += ('<div class="gap"><div class="gap-hd"><span class="tag" style="background:%s">%s</span>'
                 '<span class="tag tag2">%s</span><span class="muted">成功 %d / 失败 %d</span></div>'
                 '<div class="bar-track sm"><div class="bar-fill" style="width:%.1f%%;background:%s"></div></div>'
                 '<div class="gap-ft">已有 %d / %d，还缺 <b>%d</b></div></div>'
                 % (SHAPE_COLOR.get(g["shape"], "#888"), esc(g["shape"]), esc(g["req"]),
                    g["succ"], g["fail"], pct, SHAPE_COLOR.get(g["shape"], "#888"),
                    g["have"], m["target"], g["need"]))
    if not gaps:
        gaps = '<div class="ok">每格都已达到 %d 局目标 🎉</div>' % m["target"]

    # 会话明细
    sess_rows = ""
    for i in m["inputs"]:
        dur = (i["t1"] - i["t0"]) / 60000.0
        sess_rows += ("<tr><td class='mono'>%s</td><td>%s</td><td>%s</td>"
                      "<td>%.1f</td><td>%d</td><td>%d</td></tr>"
                      % (esc(i["file"]), fmt_ts(i["t0"]), fmt_ts(i["t1"]), dur,
                         i["events"], i["mouse"]))
    if not sess_rows:
        sess_rows = "<tr><td colspan='6' class='muted'>（还没有 B 通道记录）</td></tr>"

    # 明细（最新 40 局）
    eps_rows = ""
    for e in list(reversed(m["episodes_list"]))[:40]:
        rc = {"成功": "ok", "失败": "bad", "未知": ""}.get(e["result"], "")
        eps_rows += (
            "<tr><td>%s</td><td>%d</td><td>%s</td><td><span class='shape' style='background:%s'>%s</span></td>"
            "<td>%s</td><td class='%s'>%s</td><td>%d</td><td class='mono small'>%s</td></tr>"
            % (fmt_ts(e["t0"]), e["frames"], esc(e["shape"]),
               SHAPE_COLOR.get(e["shape"], "#888"), esc(e["shape"]),
               esc(e["req"]), rc, esc(e["result"]),
               e["n_shift"] + e["n_mouse"], esc(e["fish"] or "")))

    refresh = m.get("_refresh")
    meta = ('<meta http-equiv="refresh" content="%d">' % refresh) if refresh else ""
    live = ('<span class="live">● 实时刷新 %ds</span>' % refresh) if refresh else ""

    hist_html = render_history_html(load_history())

    return _HTML_TMPL.substitute(
        meta=meta, live=live, ts=esc(m["generated_str"]), nf=m["files_events"],
        ne=m["events_total"], qf=m["qte_frames"], nb=len(m["inputs"]),
        nbe=sum(i["events"] for i in m["inputs"]),
        kpi=kpi_html, bars=bars, matrix=matrix_html, timeline=timeline,
        hist=hist_html, gaps=gaps, sess=sess_rows, eps=eps_rows, target=m["target"],
        t3=SHAPE_COLOR["T3"], t2=SHAPE_COLOR["T2"], t3s=SHAPE_COLOR["T3s"])


_HTML_TMPL = Template("""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
$meta
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ctext y='26' font-size='26'%3E%F0%9F%8E%A3%3C/text%3E%3C/svg%3E">
<title>钓鱼采集数据看板</title>
<style>
:root{
  --bg:#f5f6f8; --panel:#ffffff; --line:#e3e6ea; --fg:#1d2126; --muted:#6b7280;
  --accent:#3f7fd6; --ok:#1f9d55; --bad:#d1483f; --warn:#c2761b;
  --shadow:0 1px 3px rgba(16,24,40,.06),0 8px 24px rgba(16,24,40,.05);
}
@media (prefers-color-scheme: dark){
  :root{ --bg:#16181d; --panel:#1e2128; --line:#2c313a; --fg:#e6e8ec; --muted:#9aa2ae;
         --shadow:0 1px 3px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3); }
}
*{box-sizing:border-box}
body{margin:0;padding:26px 22px 60px;background:var(--bg);color:var(--fg);
  font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",system-ui,sans-serif;}
.wrap{max-width:1120px;margin:0 auto}
h1{font-size:20px;margin:0 0 4px;font-weight:650}
.sub{color:var(--muted);font-size:12.5px;margin-bottom:20px}
.live{color:var(--ok);font-weight:600;margin-left:8px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-bottom:22px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;box-shadow:var(--shadow)}
.kpi-v{font-size:26px;font-weight:700;line-height:1.2}
.kpi-k{font-size:12.5px;color:var(--muted);margin-top:2px}
.kpi-s{font-size:11.5px;color:var(--muted);margin-top:6px;opacity:.85}
section{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:18px;box-shadow:var(--shadow)}
h2{font-size:14.5px;margin:0 0 14px;font-weight:650;letter-spacing:.2px}
h2 small{font-weight:400;color:var(--muted);margin-left:8px;font-size:12px}
.bar-row{display:grid;grid-template-columns:250px 1fr 260px;align-items:center;gap:12px;margin:9px 0}
.bar-label{font-size:13px}
.bar-track{height:20px;background:rgba(130,140,155,.14);border-radius:6px;overflow:hidden}
.bar-track.sm{height:9px;margin:6px 0 4px}
.bar-fill{height:100%;border-radius:6px;transition:width .3s}
.bar-num{font-variant-numeric:tabular-nums;font-size:13px;font-weight:600}
.muted{color:var(--muted);font-weight:400;font-size:11.5px;margin-left:6px}
table{width:100%;border-collapse:separate;border-spacing:6px}
.matrix th{font-size:12.5px;color:var(--muted);font-weight:600;padding:4px}
.matrix .rowh{text-align:left;padding-left:10px;white-space:nowrap;font-size:13px}
.cell{text-align:center;border-radius:9px;padding:11px 6px;border:1px solid transparent}
.cell.empty{border:1px dashed rgba(150,160,175,.55);color:var(--muted)}
.cell.full{border:1px solid rgba(31,157,85,.75)}
.cn{display:block;font-size:19px;font-weight:700;font-variant-numeric:tabular-nums}
.csub{display:block;font-size:11px;opacity:.72;font-variant-numeric:tabular-nums}
table.list{width:100%;border-spacing:0;font-size:12.5px}
table.list th{text-align:left;color:var(--muted);font-weight:600;padding:7px 10px;border-bottom:1px solid var(--line);font-size:12px}
table.list td{padding:7px 10px;border-bottom:1px solid var(--line)}
table.list tr:last-child td{border-bottom:none}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:11.5px}
.small{font-size:11px;color:var(--muted)}
.shape{display:inline-block;padding:1px 8px;border-radius:20px;color:#fff;font-size:11.5px;font-weight:600}
.ok{color:var(--ok);font-weight:600}.bad{color:var(--bad);font-weight:600}
.gap{background:rgba(130,140,155,.06);border:1px solid var(--line);border-radius:10px;padding:11px 13px;margin-bottom:10px}
.gap-hd{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tag{display:inline-block;padding:1px 9px;border-radius:20px;color:#fff;font-size:11.5px;font-weight:600}
.tag2{background:transparent;color:var(--fg);border:1px solid var(--line)}
.gap-ft{font-size:12px;color:var(--muted)}
.gap-ft b{color:var(--bad)}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:10px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px;vertical-align:middle}
footer{color:var(--muted);font-size:11.5px;text-align:center;margin-top:26px;line-height:1.9}
</style></head><body><div class="wrap">
<h1>钓鱼采集数据看板$live</h1>
<div class="sub">生成于 $ts · A 通道 $nf 文件 / $ne 事件（QTE 帧 $qf） · B 通道 $nb 会话 / $nbe 条记录</div>

<div class="kpis">$kpi</div>

<section>
  <h2>每种小游戏记录了多少次<small>按 subtitle 分隔符结构归一；数值变化是指针在动，不算形态差异</small></h2>
  $bars
</section>

<section>
  <h2>形态 × 按键要求 × 结果<small>格内上=局数，下=成功/失败；虚线=空白格，绿框=已够 $target 局</small></h2>
  $matrix
  <div class="legend">
    <span><i style="background:$t3"></i>T3 三段</span>
    <span><i style="background:$t2"></i>T2 两段</span>
    <span><i style="background:$t3s"></i>T3s 极短</span>
    <span>※ 悬停格子可看细分</span>
  </div>
</section>

<section>
  <h2>采集覆盖时间条<small>青色带 = B 通道（键鼠记录器）实际在跑的时段；竖线 = 每一局，亮色表示该局录到了真实按键；&#8776; = 被压缩掉的空闲时段</small></h2>
  $timeline
</section>

<section>
  <h2>累计进度<small>每轮采集自动落一条快照，看样本怎么长</small></h2>
  $hist
</section>

<section>
  <h2>还差什么<small>补采目标：每格 $target 局；失败样本尤为稀缺</small></h2>
  $gaps
</section>

<section>
  <h2>B 通道会话明细</h2>
  <table class="list"><thead><tr><th>文件</th><th>开始</th><th>结束</th><th>分钟</th><th>事件</th><th>鼠标</th></tr></thead>
  <tbody>$sess</tbody></table>
</section>

<section>
  <h2>最近 40 局明细</h2>
  <table class="list"><thead><tr><th>时间</th><th>帧</th><th>形态</th><th></th><th>按键要求</th><th>结果</th><th>真实按键</th><th>钓到</th></tr></thead>
  <tbody>$eps</tbody></table>
</section>

<footer>fishviz · 数据来自 ~/.fishprobe/ · 成功信号优先取游戏自带反馈，缺失才退化用人工打点</footer>
</div></body></html>
""")


def _make_scale(pts, clip_ms):
    """建一个"压缩空闲缺口"的时间轴映射（断轴）。

    采集是断续的：14:25 只有 1 局，然后空了 2 小时，再是 16:46–17:20 的密集段。
    按真实时长铺轴，密集段会被挤成右边一小撮。这里把**超过 clip_ms 的空白**
    压成固定宽度，让"有数据的时段"占满图宽，同时在断点画虚线说明中断。
    """
    segs = []
    acc = 0.0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        if b <= a:
            continue
        dt = min(b - a, clip_ms)
        segs.append((a, b, acc, dt, (b - a) > clip_ms))
        acc += dt
    total = acc or 1.0

    def U(t):
        if not segs:
            return 0.0
        if t <= segs[0][0]:
            return 0.0
        for a, b, x0, dt, clipped in segs:
            if a <= t <= b:
                return (x0 + (t - a) / (b - a) * dt) / total
        return 1.0

    return U, total, segs


def render_timeline_svg(m, clip_ms=180000):
    eps = m["episodes_list"]
    if not eps:
        return '<div class="muted">暂无数据</div>'
    W, H = 1000, 132
    PADL = 6
    keypts = [e["t0"] for e in eps] + [e["t1"] for e in eps]
    for i in m["inputs"]:
        keypts += [i["t0"], i["t1"]]
    pts = sorted(set(keypts))
    U, total, segs = _make_scale(pts, clip_ms)

    def X(t):
        return PADL + U(t) * (W - 2 * PADL)

    P = ['<svg viewBox="0 0 %d %d" style="width:100%%;height:auto" role="img">' % (W, H)]
    P.append('<rect x="0" y="4" width="%d" height="%d" fill="rgba(130,140,155,.07)" rx="6"/>'
             % (W, H - 30))
    # B 通道窗口
    for i in m["inputs"]:
        x = X(i["t0"]); w = max(1.5, X(i["t1"]) - x)
        P.append('<rect x="%.1f" y="10" width="%.1f" height="%d" fill="rgba(56,178,172,.26)" '
                 'stroke="rgba(56,178,172,.75)" stroke-width="1" rx="2"/>' % (x, w, H - 44))
    # 各形态一行，局刻度按结果描色
    shapes = m["shapes"]
    nrow = max(1, len(shapes))
    rowh = (H - 52) / nrow
    rowmap = {s: k for k, s in enumerate(shapes)}
    for e in eps:
        x = X(e["t0"])
        y = 10 + rowmap.get(e["shape"], 0) * rowh
        col = SHAPE_COLOR.get(e["shape"], "#888")
        op = 0.95 if e["real_keys"] else 0.40
        P.append('<rect x="%.1f" y="%.1f" width="2.6" height="%.1f" fill="%s" opacity="%.2f">'
                 '<title>%s %s %s %s</title></rect>'
                 % (x, y, rowh - 3, col, op, fmt_ts(e["t0"]), e["shape"], e["req"], e["result"]))
    # 断点虚线（压缩掉的空闲）
    for a, b, x0, dt, clipped in segs:
        if clipped:
            x = PADL + (x0 + dt) / total * (W - 2 * PADL)
            P.append('<line x1="%.1f" y1="6" x2="%.1f" y2="%d" stroke="rgba(130,140,155,.6)" '
                     'stroke-width="1" stroke-dasharray="3 4"/>' % (x, x, H - 26))
            P.append('<text x="%.1f" y="%d" font-size="10" fill="#8a8f98" '
                     'text-anchor="middle">&#8776;</text>' % (x, H - 14))
    # 时间刻度：每段起点 + 末点
    lab = [segs[0][0]] if segs else []
    lab += [s[0] for s in segs if s[4]] + [segs[-1][1] if segs else 0]
    lab = lab[:9]
    for t in lab:
        x = X(t)
        P.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="rgba(130,140,155,.5)"/>'
                 % (x, H - 30, x, H - 25))
        anc = "start" if x < 40 else ("end" if x > W - 40 else "middle")
        P.append('<text x="%.1f" y="%d" font-size="11" fill="#8a8f98" text-anchor="%s">%s</text>'
                 % (x, H - 6, anc, fmt_ts(t)))
    # 每形态行标签
    for s, k in rowmap.items():
        y = 10 + k * rowh + rowh / 2 + 3
        P.append('<text x="%.1f" y="%.1f" font-size="10" fill="#8a8f98">%s</text>' % (8, y, s))
    P.append("</svg>")
    return "".join(P)


def load_history():
    p = home("stats", "history.jsonl")
    rows = []
    if os.path.isfile(p):
        for line in open(p, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:                          # noqa: BLE001
                continue
    return rows


def render_history_html(rows):
    """累计快照：本条看的是「随着不断采集，样本在怎么长」。"""
    if not rows:
        return ('<div class="muted">还没有快照。用 <code>采集看板.bat</code> 或 '
                '<code>fishviz.py --snapshot</code> 记一次基线，之后每采一轮就会长出一条。</div>')
    if len(rows) == 1:
        r = rows[-1]
        return ('<div class="muted">已有 1 条基线快照（%s：有效局 %d / 有真实按键 %d）。'
                '<br>再采集几轮并各记一次快照，这里就会出现增长趋势。</div>'
                % (esc(r.get("when", "")), r.get("episodes", 0), r.get("with_keys", 0)))
    W, H = 1000, 150
    PADL, PADR, PADT, PADB = 44, 12, 14, 26
    xs = [r.get("ts", 0) for r in rows]
    x0, x1 = min(xs), max(xs)
    span = max(1.0, x1 - x0)
    series = [("有效局数", "episodes", "#3f7fd6"), ("有真实按键", "with_keys", "#1f9d55")]
    ymax = max([r.get(k, 0) for r in rows for _, k, _ in series] + [1])

    def X(t):
        return PADL + (t - x0) / span * (W - PADL - PADR)

    def Y(v):
        return H - PADB - (v / ymax) * (H - PADT - PADB)

    P = ['<svg viewBox="0 0 %d %d" style="width:100%%;height:auto" role="img">' % (W, H)]
    for k in range(5):
        v = ymax * k / 4
        P.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="rgba(130,140,155,.22)"/>'
                 % (PADL, Y(v), W - PADR, Y(v)))
        P.append('<text x="%d" y="%.1f" font-size="10" fill="#8a8f98" text-anchor="end">%d</text>'
                 % (PADL - 6, Y(v) + 3, round(v)))
    for name, key, col in series:
        pts = " ".join("%.1f,%.1f" % (X(r.get("ts", 0)), Y(r.get(key, 0))) for r in rows)
        P.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2.2"/>' % (pts, col))
        for r in rows:
            P.append('<circle cx="%.1f" cy="%.1f" r="3" fill="%s"><title>%s %s=%d</title></circle>'
                     % (X(r.get("ts", 0)), Y(r.get(key, 0)), col,
                        esc(r.get("when", "")), name, r.get(key, 0)))
    for r in rows[:1] + rows[-1:]:
        P.append('<text x="%.1f" y="%d" font-size="10" fill="#8a8f98" text-anchor="middle">%s</text>'
                 % (X(r.get("ts", 0)), H - 8, esc((r.get("when") or "")[5:16])))
    P.append("</svg>")
    legend = "".join('<span><i style="background:%s"></i>%s</span>' % (c, n)
                     for n, _, c in series)
    tail = "".join(
        "<tr><td>%s</td><td>%d</td><td>%d</td><td>%d</td></tr>"
        % (esc(r.get("when", "")), r.get("episodes", 0), r.get("with_keys", 0),
           r.get("covered", 0))
        for r in list(reversed(rows))[:8])
    return ("%s<div class=\"legend\">%s</div>"
            "<table class=\"list\" style=\"margin-top:12px\"><thead><tr><th>快照时间</th>"
            "<th>有效局</th><th>有真实按键</th><th>B 通道覆盖</th></tr></thead><tbody>%s</tbody></table>"
            % ("".join(P), legend, tail))


# ---------------------------------------------------------------- 累计快照
def append_snapshot(m):
    d = home("stats")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "history.jsonl")
    row = dict(ts=round(m["generated"], 1), when=m["generated_str"],
               episodes=m["episodes"], success=m["success"], fail=m["fail"],
               covered=m["covered_eps"], with_keys=m["with_keys"],
               shapes={s: m["by_shape"][s].get("局数", 0) for s in m["shapes"]},
               cells={"%s|%s" % (s, r): sum(m["matrix"].get(s, {}).get(r, {}).values())
                      for s in m["shapes"] for r in REQ_ORDER})
    # 同一分钟内不重复追加（反复跑 --snapshot 不刷屏）
    if os.path.isfile(p):
        try:
            last = None
            for line in open(p, encoding="utf-8"):
                if line.strip():
                    last = json.loads(line)
            if last and abs(last["ts"] - row["ts"]) < 60:
                lines = open(p, encoding="utf-8").read().rstrip("\n").split("\n")
                lines[-1] = json.dumps(row, ensure_ascii=False)
                open(p, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
                print(" 已更新本分钟快照 -> %s" % p)
                return p
        except Exception:                              # noqa: BLE001
            pass
    with open(p, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(" 已追加累计快照 -> %s" % p)
    return p


# ---------------------------------------------------------------- 入口
def main():
    setup_console()
    ap = argparse.ArgumentParser(description="钓鱼采集数据可视化看板")
    ap.add_argument("--events-dir", default=None)
    ap.add_argument("--inputs-dir", default=None)
    ap.add_argument("--gap", type=int, default=DEFAULT_GAP_MS)
    ap.add_argument("--out", default=None, help="HTML 输出路径（默认 app/report/dashboard.html）")
    ap.add_argument("--watch", type=float, default=0,
                    help="每 N 秒重算并重生成（配合页面自动刷新）")
    ap.add_argument("--open", action="store_true", help="生成后用默认浏览器打开")
    ap.add_argument("--snapshot", action="store_true", help="追加一行累计进度")
    ap.add_argument("--text", action="store_true", help="只输出终端表格")
    ap.add_argument("--verbose", action="store_true", help="终端额外列出全部有效局")
    ap.add_argument("--json", action="store_true", help="输出模型 JSON")
    args = ap.parse_args()

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "report", "dashboard.html")
    cycle = 0
    while True:
        cycle += 1
        m = build_model(args.events_dir, args.inputs_dir, args.gap)
        if not args.json and not args.text:
            render_text(m, args.verbose)
        if args.json:
            print(json.dumps({k: v for k, v in m.items() if k != "episodes_list"},
                             ensure_ascii=False, indent=2))
        if args.snapshot or (args.watch > 0 and cycle == 1):
            append_snapshot(m)
        if not args.json:
            m["_refresh"] = int(args.watch) if args.watch > 0 else None
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(render_html(m))
            print(" 看板已生成 -> %s" % out)
            if args.open:
                try:
                    os.startfile(out)                  # noqa: S606  (Windows)
                    args.open = False
                except Exception as e:                 # noqa: BLE001
                    print(" [!] 自动打开失败：%s" % e)
        if args.watch <= 0:
            break
        time.sleep(max(1.0, args.watch))
        print("\n" + "─" * 92 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
