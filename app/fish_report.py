#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fish_report —— 采集数据快速汇总（采完立刻知道：采了几局、成没成、数据够不够）

把两路数据按 **wall（Unix epoch 毫秒）** 合并成一条时间轴：
  A 通道  ~/.fishprobe/events/*.jsonl   （模组探针：BossBar / Title / ActionBar / 状态）
  B 通道  ~/.fishprobe/inputs/*.jsonl   （键鼠记录器：按键 + 打点标记）
然后以「一局开始」打点键（role=episode_start）为界切出逐局 episode，
并给出数据质量检查。

打点键**不写死**：默认 i 开始 / . 成功 / ' 失败，可用 fishkey.py 的
--key-start / --key-success / --key-fail 改；本脚本会从数据里读回实际用的键。

用法：
    python fish_report.py                        # 看默认目录
    python fish_report.py --root D:\\some\\dir    # 看指定目录
    python fish_report.py --limit 40             # 明细显示前 N 局（默认 20）
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter


def load(paths):
    rows, bad = [], 0
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except Exception:
                        bad += 1
                        continue
                    r["_file"] = os.path.basename(p)
                    rows.append(r)
        except Exception as e:                                   # noqa: BLE001
            print("[!] 跳过 %s: %s" % (p, e))
    rows.sort(key=lambda r: r.get("wall", 0))
    return rows, bad


# 数据里没记录打点键时的兜底显示（老数据是 F9/F10/F11）
DEFAULT_MARK_LABEL = {"episode_start": "F9", "success": "F10", "fail": "F11"}


def split_episodes(rows):
    """以「一局开始」(mark/episode_start) 为界切局，success / fail 结标签。"""
    eps, cur = [], None
    for r in rows:
        if r.get("type") == "mark" and r.get("role") == "episode_start":
            if cur is not None:
                eps.append(cur)
            cur = {"start": r, "events": [], "result": None, "end": None}
        elif r.get("type") == "mark" and r.get("role") in ("success", "fail"):
            if cur is not None:
                cur["result"] = r["role"]
                cur["end"] = r
                eps.append(cur)
                cur = None
        elif cur is not None:
            cur["events"].append(r)
    if cur is not None:
        eps.append(cur)
    return eps


def fmt_ts(ms):
    import time
    return time.strftime("%H:%M:%S", time.localtime(ms / 1000.0)) if ms else "--:--:--"


def main():
    ap = argparse.ArgumentParser(description="采集数据快速汇总")
    ap.add_argument("--root", default=None, help="探针根目录（默认 ~/.fishprobe）")
    ap.add_argument("--limit", type=int, default=20, help="明细显示前 N 局")
    args = ap.parse_args()

    root = args.root or os.path.join(os.path.expanduser("~"), ".fishprobe")
    ev = sorted(glob.glob(os.path.join(root, "events", "*.jsonl")))
    ins = sorted(glob.glob(os.path.join(root, "inputs", "*.jsonl")))

    print("=" * 72)
    print(" fish_report · 采集数据汇总")
    print("=" * 72)
    print(" 目录      : %s" % root)
    print(" 模组事件  : %d 个文件" % len(ev))
    print(" 键鼠记录  : %d 个文件" % len(ins))
    if not ev and not ins:
        print()
        print(" 还没有任何数据。检查两件事：")
        print("   1) fishprobe 模组是否在 mods/ 里（进游戏后看 ~/.fishprobe/status.txt）")
        print("   2) 键鼠记录器是否启动过（启动采集.bat）")
        return 1

    rows, bad = load(ev + ins)
    print(" 事件总数  : %d（无法解析 %d 行）" % (len(rows), bad))
    if not rows:
        return 1

    types = Counter(r.get("type") for r in rows)
    print(" 按类型    : " + ", ".join("%s=%d" % kv for kv in sorted(types.items())))

    # ---------------- 数据质量体检 ----------------
    print()
    print("-" * 72)
    print(" 数据质量体检")
    print("-" * 72)
    bars = [r for r in rows if r.get("type") == "bossbar"]
    titles = [r for r in rows if r.get("type") == "title" and r.get("text")]
    acts = [r for r in rows if r.get("type") == "actionbar" and r.get("text")]
    keys = [r for r in rows if r.get("type") == "key"]
    mice = [r for r in rows if r.get("type") == "mouse"]

    # 从数据里读回实际用的打点键（fishkey.py 允许改键，不写死）
    mark_chars = {}
    for r in rows:
        if r.get("type") == "mark" and r.get("role"):
            mark_chars.setdefault(r["role"], r.get("key"))

    def mk(role):
        return mark_chars.get(role) or DEFAULT_MARK_LABEL.get(role, "?")

    def line(name, ok, detail):
        print("   %s %-30s %s" % ("[v]" if ok else "[x]", name, detail))

    line("BossBar 通道有数据", bool(bars),
         "%d 条；unique 进度值 %d 个" % (len(bars), len({r.get("raw") for r in bars})))
    line("BossBar 同时有 shown/raw", all("shown" in r and "raw" in r for r in bars) if bars else False,
         "插值值 vs 服务器原始值")
    line("Title 文本通道有数据", bool(titles), "%d 条不同文本" % len({r.get("text") for r in titles}))
    line("ActionBar 通道有数据", bool(acts), "%d 条不同文本" % len({r.get("text") for r in acts}))
    line("键鼠通道有数据", bool(keys or mice), "按键 %d / 鼠标 %d" % (len(keys), len(mice)))
    nmarks = sum(1 for r in rows if r.get("type") == "mark")
    line("打点标记齐全", all(mark_chars.get(k) for k in ("episode_start", "success", "fail")),
         "开始=%s 成功=%s 失败=%s（共 %d 次打点）"
         % (mk("episode_start"), mk("success"), mk("fail"), nmarks))
    if titles:
        sample = list({r["text"] for r in titles})[:5]
        print("        Title 样本: " + " | ".join(sample))
    if bars and len({r.get("raw") for r in bars}) <= 1:
        print("        [!] BossBar 进度始终不变 —— 可能这条 BossBar 不是收杆进度条，")
        print("            收杆小游戏也许走 Title/ActionBar 或自定义包（看录屏确认）。")

    # ---------------- 逐局 ----------------
    print()
    print("-" * 72)
    print(" 逐局明细（以打点键「%s 一局开始」为界）" % mk("episode_start"))
    print("-" * 72)
    eps = split_episodes(rows)
    if not eps:
        print("   没有找到「一局开始」标记。采集时记得按协议打点：")
        print("     %s = 开始   %s = 成功   %s = 失败"
              % (mk("episode_start"), mk("success"), mk("fail")))
        return 0

    succ = sum(1 for e in eps if e["result"] == "success")
    fail = sum(1 for e in eps if e["result"] == "fail")
    unlabeled = sum(1 for e in eps if e["result"] is None)
    print("   合计 %d 局：成功 %d / 失败 %d / 未标 %d" % (len(eps), succ, fail, unlabeled))
    print()
    print("   %-4s %-9s %6s %-9s %-8s %s" % ("#", "开始", "时长", "进度条", "按键", "结果/Title"))

    for i, e in enumerate(eps[:args.limit], 1):
        t0 = e["start"].get("wall")
        last = e["end"] or (e["events"][-1] if e["events"] else e["start"])
        t1 = last.get("wall", t0)
        dur = (t1 - t0) / 1000.0 if t0 and t1 else 0
        nbar = sum(1 for r in e["events"] if r.get("type") == "bossbar")
        nk = sum(1 for r in e["events"] if r.get("type") in ("key", "mouse"))
        tt = [r["text"] for r in e["events"] if r.get("type") == "title" and r.get("text")]
        label = {"success": "✅ 成功", "fail": "❌ 失败"}.get(e["result"], "—未标")
        print("   %-4d %-9s %5.1fs %-9s %-8s %s %s"
              % (i, fmt_ts(t0), dur, "%d 条" % nbar, "%d" % nk, label,
                 ("「%s」" % tt[0]) if tt else ""))
    if len(eps) > args.limit:
        print("   ... 还有 %d 局未显示（--limit 调整）" % (len(eps) - args.limit))

    print()
    print("=" * 72)
    print(" 下一步：每种形态攒够 20 局（正负都要），再进入离线对齐与规则提取。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
