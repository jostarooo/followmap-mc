#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fishauto_ctl.py —— 自动钓鱼模组 fishauto 的控制/观察台（命令行）

模组的行为完全由 `~/.fishauto/config.json` 决定，且**热加载**（每秒查一次 mtime）——
也就是说改完存盘即生效，**不必重启游戏**。本脚本就是替你改这个文件并读回状态。

安全设计（与模组一致）
----------------------
  enabled=false   → 连判定都不做（出厂默认）
  dry_run=true    → 只判定、只记录，**绝不按键**（出厂默认）
  ~/.fishauto/STOP → 急停：立即停止按键，但仍继续记录
  ~/.fishauto/OFF  → 停采：什么都不记了

所以「装上去」是什么都不会发生的；必须显式 on + live 才会真的按键。

用法
----
    python fishauto_ctl.py status           # 看开关、配置、安装位置、日志概况
    python fishauto_ctl.py on | off         # 总开关
    python fishauto_ctl.py live | dry       # 真按键 / 只干跑
    python fishauto_ctl.py stop | resume    # 急停 / 解除急停
    python fishauto_ctl.py speed 130        # 连按间隔 ms
    python fishauto_ctl.py hold 2           # 按住类按键保持几个 tick
    python fishauto_ctl.py bite on | off    # 咬钩观测开关（v0.2.1，默认关）
    python fishauto_ctl.py bite             # 咬钩 / 形态汇总（不带参数就是看）
    python fishauto_ctl.py reel on | off    # ★v0.3.0★ 咬钩自动收杆（默认关）
    python fishauto_ctl.py form observe|auto # ★v0.3.0★ B/C 形态策略（默认 observe＝只观测）
    python fishauto_ctl.py report [N]       # 汇总最近一局（或最近 N 局）
    python fishauto_ctl.py tail [N]         # 打印日志最后 N 行
"""
import glob
import json
import os
import sys
import datetime

HOME = os.path.join(os.path.expanduser("~"), ".fishauto")
CFG = os.path.join(HOME, "config.json")
LOG = os.path.join(HOME, "log")

# 与模组 Config.java 的 key 顺序保持一致，便于人读
ORDER = ["_说明", "enabled", "dry_run", "strategy", "geo_rule", "geo_margin",
         "geo_lead_px", "auto_cast", "cadence_ms", "hold_ticks",
         "idle_timeout_ms", "max_press_per_game", "max_games",
         "use_left", "use_right", "use_shift", "log_frames", "bite_log",
         # ★ v0.3.0：完整循环 + 三形态
         "reel_on_bite", "reel_delay_ms", "cast_delay_ms",
         "form_strategy", "c_margin", "hold_key"]

DEFAULT = {
    "_说明": "enabled 总开关；dry_run=true 只判定不按键；改完存盘即热加载",
    "enabled": False, "dry_run": True,
    "strategy": "cadence", "geo_rule": "center", "geo_margin": 8, "geo_lead_px": 0,
    "auto_cast": False,
    "cadence_ms": 130, "hold_ticks": 2, "idle_timeout_ms": 1200,
    "max_press_per_game": 80, "max_games": 0,
    "use_left": True, "use_right": True, "use_shift": True, "log_frames": True,
    "bite_log": False,
    # ★ v0.3.0（默认全部保守；与 Config.java 保持一致 —— 20 局回放定 margin=0、C 型按 right）
    "reel_on_bite": False, "reel_delay_ms": 0, "cast_delay_ms": 1500,
    "form_strategy": "observe", "c_margin": 0, "hold_key": "right",
}

BOOL_KEYS = {"enabled", "dry_run", "auto_cast", "use_left", "use_right",
             "use_shift", "log_frames", "bite_log", "reel_on_bite"}
INT_KEYS = {"cadence_ms", "hold_ticks", "idle_timeout_ms",
            "max_press_per_game", "max_games",
            "reel_delay_ms", "cast_delay_ms", "c_margin", "geo_margin", "geo_lead_px"}
STR_KEYS = {"strategy", "geo_rule", "form_strategy", "hold_key"}
# 字符串键的合法取值（写错时给出提示，但不阻止 —— 模组侧会安全退化）
ENUMS = {
    "strategy": ("cadence", "geometry"),
    "geo_rule": ("center", "left", "whole"),
    "form_strategy": ("observe", "auto"),
    "hold_key": ("left", "right", "shift"),
}


# --------------------------------------------------------------------------
def load_cfg():
    """读配置；文件不存在就用出厂默认。容忍任何坏内容。"""
    out = dict(DEFAULT)
    if not os.path.exists(CFG):
        return out
    try:
        raw = json.load(open(CFG, encoding="utf-8"))
    except Exception:                                  # noqa: BLE001
        try:
            # 模组内部用的是极简解析器，允许注释外的松散写法；这里退化处理
            txt = open(CFG, encoding="utf-8").read()
            import re
            raw = {}
            for m in re.finditer(r'"([^"]+)"\s*:\s*("([^"]*)"|true|false|[-\d.]+)',
                                 txt):
                v = m.group(2)
                if v.startswith('"'):
                    raw[m.group(1)] = m.group(3)
                elif v in ("true", "false"):
                    raw[m.group(1)] = (v == "true")
                else:
                    raw[m.group(1)] = float(v) if "." in v else int(v)
        except Exception:                              # noqa: BLE001
            return out
    for k, v in raw.items():
        out[k] = v
    return out


def save_cfg(cfg):
    os.makedirs(HOME, exist_ok=True)
    lines = ["{"]
    keys = [k for k in ORDER if k in cfg] + [k for k in cfg if k not in ORDER]
    for i, k in enumerate(keys):
        v = cfg[k]
        if isinstance(v, bool):
            s = "true" if v else "false"
        elif isinstance(v, str):
            s = json.dumps(v, ensure_ascii=False)
        else:
            s = str(v)
        lines.append('  %s: %s%s' % (json.dumps(k, ensure_ascii=False), s,
                                     "," if i < len(keys) - 1 else ""))
    lines.append("}")
    with open(CFG, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def flag(name):
    return os.path.exists(os.path.join(HOME, name))


def logs():
    return sorted(glob.glob(os.path.join(LOG, "*.jsonl")))


def read_log(path):
    rows = []
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:                              # noqa: BLE001
            pass
    return rows


def installed_jars():
    out = []
    base = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14\mods"
    out += glob.glob(os.path.join(base, "fishauto-*.jar"))
    base2 = r"D:\config\game\mc\方块传说V3.0客户端 2K(2560×1440)\.minecraft\mods"
    out += glob.glob(os.path.join(base2, "fishauto-*.jar"))
    return out


# --------------------------------------------------------------------------
def cmd_status(_):
    cfg = load_cfg()
    print("=" * 68)
    print("fishauto 状态")
    print("=" * 68)
    print("配置: %s %s" % (CFG, "存在" if os.path.exists(CFG) else "**不存在（模组会用出厂默认）**"))
    print()
    print("  enabled            = %-5s  %s" % (
        cfg.get("enabled"), "总开关：关着时连判定都不做" if not cfg.get("enabled") else "已开启"))
    print("  dry_run            = %-5s  %s" % (
        cfg.get("dry_run"), "干跑：只判定/记录，不按键" if cfg.get("dry_run") else "**会真的按键**"))
    print("  auto_cast          = %-5s  %s" % (
        cfg.get("auto_cast"), "自动抛竿（默认关）"))
    print("  strategy           = %-5s  cadence 固定连按 | geometry 指针进绿区才按"
          % cfg.get("strategy"))
    if cfg.get("strategy") == "geometry":
        print("    geo_rule=%s margin=%spx lead=%spx" % (
            cfg.get("geo_rule"), cfg.get("geo_margin"), cfg.get("geo_lead_px")))
    print("  cadence_ms         = %-5s  连按间隔（实测人工 100–300ms）" % cfg.get("cadence_ms"))
    print("  hold_ticks         = %-5s  按住类保持 tick 数（20 tick = 1s）" % cfg.get("hold_ticks"))
    print("  idle_timeout_ms    = %-5s  多久没新字幕帧算本局结束" % cfg.get("idle_timeout_ms"))
    print("  max_press_per_game = %-5s  单局按键上限" % cfg.get("max_press_per_game"))
    print("  max_games          = %-5s  连续多少局后自动停（0=不限）" % cfg.get("max_games"))
    print("  keys               = left=%s right=%s shift=%s" % (
        cfg.get("use_left"), cfg.get("use_right"), cfg.get("use_shift")))
    print("  bite_log           = %-5s  咬钩观测（v0.2.1）：边沿记 hook_bite/hook_clear，只记不决策"
          % cfg.get("bite_log"))
    print()
    print("  ── ★ v0.3.0 完整循环 ──")
    print("  reel_on_bite       = %-5s  %s" % (
        cfg.get("reel_on_bite"),
        "咬钩自动右键收杆（「按节拍」的替代）" if cfg.get("reel_on_bite")
        else "关（默认）—— 需先开：reel on"))
    print("  reel_delay_ms      = %-5s  咬钩后延迟多少 ms 再收杆" % cfg.get("reel_delay_ms"))
    print("  cast_delay_ms      = %-5s  一局结束后延迟多少 ms 再抛竿" % cfg.get("cast_delay_ms"))
    print("  form_strategy      = %-5s  %s" % (
        cfg.get("form_strategy"),
        "A/C 形态自动按键" if cfg.get("form_strategy") == "auto"
        else "只观测不按（默认）—— 要自动：form auto"))
    print("  c_margin           = %-5s  C 形态判定余量 px" % cfg.get("c_margin"))
    print("  hold_key           = %-5s  C/B 按住型用哪个键" % cfg.get("hold_key"))
    print()
    print("急停标志:")
    print("  STOP  %s   %s" % ("存在 —— 不再按键（仍在记录）" if flag("STOP") else "无",
                              os.path.join(HOME, "STOP")))
    print("  OFF   %s   %s" % ("存在 —— 已停采" if flag("OFF") else "无",
                              os.path.join(HOME, "OFF")))
    print()
    jars = installed_jars()
    print("安装位置（%d 个）:" % len(jars))
    for j in jars:
        print("  %s  (%d 字节, %s)" % (
            j, os.path.getsize(j),
            datetime.datetime.fromtimestamp(os.path.getmtime(j)).strftime("%m-%d %H:%M")))
    if not jars:
        print("  **未安装** —— 跑 build_fishprobe.py --root fishauto")
    print()
    fs = logs()
    print("日志（%d 个）: %s" % (len(fs), LOG))
    if fs:
        newest = fs[-1]
        rows = read_log(newest)
        types = {}
        for r in rows:
            types[r.get("type", "?")] = types.get(r.get("type", "?"), 0) + 1
        print("  最新: %s  %d 行" % (os.path.basename(newest), len(rows)))
        print("  事件: %s" % ", ".join("%s=%d" % kv for kv in sorted(types.items())))
        tail_events(rows, 5)
    st = os.path.join(HOME, "status.txt")
    if os.path.exists(st):
        print()
        print("反射自检 status.txt（前 12 行）:")
        for i, line in enumerate(open(st, encoding="utf-8", errors="replace")):
            if i >= 12:
                break
            print("  " + line.rstrip())
    return 0


def tail_events(rows, n):
    ev = [r for r in rows if r.get("type") not in ("frame",)]
    print("  最近 %d 条非 frame 事件:" % n)
    for r in ev[-n:]:
        t = r.get("wall")
        ts = (datetime.datetime.fromtimestamp(t / 1000).strftime("%H:%M:%S.%f")[:-3]
              if t else "--:--:--")
        extra = ""
        for k in ("key", "result", "by", "text", "kind", "value", "n"):
            if k in r:
                extra += " %s=%s" % (k, str(r[k])[:40])
        print("    %s %-12s%s" % (ts, r.get("type"), extra))


def cmd_set(key, value):
    cfg = load_cfg()
    if key in BOOL_KEYS:
        cfg[key] = bool(value)
    elif key in INT_KEYS:
        try:
            cfg[key] = int(value)
        except (TypeError, ValueError):
            print("** %s 需要一个整数，收到 %r **" % (key, value))
            return 2
    elif key in STR_KEYS:
        s = str(value).strip().lower()
        if key in ENUMS and s not in ENUMS[key]:
            print("** %s 只接受 %s，收到 %r（仍会写入，但模组侧会安全退化）**"
                  % (key, "/".join(ENUMS[key]), s))
        cfg[key] = s
    else:
        cfg[key] = value
    save_cfg(cfg)
    print("已写入 %s" % CFG)
    print("  %s = %s" % (key, cfg[key]))
    print()
    if key == "dry_run" and value is False:
        print("  ⚠️ dry_run=false 意味着**会真的按键**。")
        print("     确认 enabled=true 才会生效；随时可用 stop 急停。")
    if key == "reel_on_bite" and cfg.get("reel_on_bite"):
        print("  ⚠️ reel_on_bite=true：**咬钩即自动右键收杆**（不依赖外部注入）。")
        print("     它是「按节拍」的替代：biting 是服务端同步的真信号。")
        if cfg.get("dry_run", True):
            print("     当前 dry_run=true ⇒ 只会记 reel 事件，不会真按键。")
    if key == "form_strategy" and cfg.get("form_strategy") == "auto":
        print("  ⚠️ form_strategy=auto：A 走 geometry、C 按底图色段自动按键。")
        print("     B 形态（无指针）仍**不会**按 —— 没有可靠信号，硬按必输。")
        if cfg.get("dry_run", True):
            print("     当前 dry_run=true ⇒ 只会记 press_dry，不会真按键。")
    if key == "enabled" and value is True and cfg.get("dry_run", True):
        print("  提示：当前 dry_run=true，所以即使开启了也**不会按键**（只记录）。")
        print("        要真按键：python fishauto_ctl.py live")
    print("  热加载：模组每秒查一次文件时间，存盘即生效，不必重启游戏。")
    return 0


def cmd_report(args):
    n = int(args[0]) if args else 1
    fs = logs()
    if not fs:
        print("还没有日志：%s" % LOG)
        return 1
    rows = read_log(fs[-1])
    games = [r for r in rows if r.get("type") == "qte_end"]
    print("日志: %s" % os.path.basename(fs[-1]))
    print("总局数: %d" % len(games))
    hit = sum(1 for g in games if g.get("result") == "hit")
    miss = sum(1 for g in games if g.get("result") == "miss")
    none_ = len(games) - hit - miss
    print("成功 %d / 失败 %d / 未判定 %d%s" % (
        hit, miss, none_,
        ("  成功率 %.0f%%" % (100.0 * hit / max(1, hit + miss))) if hit + miss else ""))
    print()
    for g in games[-n:]:
        t = g.get("wall")
        ts = datetime.datetime.fromtimestamp(t / 1000).strftime("%H:%M:%S") if t else "--"
        print("  %s  key=%-8s result=%-10s presses=%-3s frames=%-3s %.0fms" % (
            ts, g.get("key"), g.get("result"), g.get("presses"),
            g.get("frames"), g.get("ms", 0)))
    return 0


def cmd_bite(_=None):
    """咬钩观测汇总（v0.2.1）+ 帧形态分布。

    判读标准（决定要不要把咬钩信号接入开局触发）：
      * 一条 hook_bite 都没有 -> 先确认 bite_log 是不是还关着；确认开着仍没有 =>
        本服没驱动原版浮标，这条信号作废，回到文本触发。
      * 有 hook_bite，且 qte_begin 的 bite_ago_ms 普遍 >= 0（咬钩早于/紧邻开局）
        => 值得做 bite_source=hook。
    """
    fs = logs()
    if not fs:
        print("还没有日志：%s" % LOG)
        return 1
    rows = read_log(fs[-1])
    print("日志: %s（%d 行）" % (os.path.basename(fs[-1]), len(rows)))

    bites = [r for r in rows if r.get("type") == "hook_bite"]
    clears = [r for r in rows if r.get("type") == "hook_clear"]
    begins = [r for r in rows if r.get("type") == "qte_begin"]
    frames = [r for r in rows if r.get("type") == "frame"]

    print()
    print("咬钩信号: hook_bite %d 条 / hook_clear %d 条" % (len(bites), len(clears)))
    if not bites:
        cfg = load_cfg()
        print()
        if not cfg.get("bite_log"):
            print("  **bite_log 还关着** —— 先开：python fishauto_ctl.py bite on")
        else:
            print("  bite_log 已开，但一条 hook_bite 都没记到 —— 两种可能：")
            print("    1) 这一局你没抛竿 / 没钓（先抛竿等鱼咬钩；干跑不影响观测）")
            print("    2) 本服没驱动原版浮标 => 这条咬钩信号作废，回到文本触发")
        return 0

    holds = [c["held_ms"] for c in clears
             if isinstance(c.get("held_ms"), (int, float)) and c["held_ms"] >= 0]
    if holds:
        h = sorted(holds)
        print("  持钩时长: 中位 %dms  范围 %d~%dms" % (h[len(h) // 2], h[0], h[-1]))
    vys = [b["vy"] for b in bites if isinstance(b.get("vy"), (int, float))]
    if vys:
        v = sorted(vys)
        print("  咬钩那刻 vy: 中位 %.3f（客户端被置位时应落在 -0.24 ~ -0.40）" % v[len(v) // 2])

    print()
    print("与 QTE 开局的关联（qte_begin 共 %d 个）:" % len(begins))
    ago = [b["bite_ago_ms"] for b in begins
           if isinstance(b.get("bite_ago_ms"), (int, float)) and b["bite_ago_ms"] >= 0]
    print("  bite_ago_ms >= 0 的有 %d 个（= 该局开局前刚咬过钩）" % len(ago))
    if ago:
        a = sorted(ago)
        print("  提前量: 中位 %dms  范围 %d~%dms（正数 = 咬钩早于开局）"
              % (a[len(a) // 2], a[0], a[-1]))
    since = [b["since_begin_ms"] for b in bites
             if isinstance(b.get("since_begin_ms"), (int, float)) and b["since_begin_ms"] >= 0]
    if since:
        s = sorted(since)
        print("  hook_bite 落在开局之后的有 %d 次，中位 %dms" % (len(s), s[len(s) // 2]))

    if frames:
        cnt = {}
        for f in frames:
            k = f.get("form", "(旧版无此字段)")
            cnt[k] = cnt.get(k, 0) + 1
        print()
        print("帧形态分布（form 字段）: "
              + ", ".join("%s=%d" % kv for kv in sorted(cnt.items())))
        print("  A=指针+绿区（点按）· C=指针无绿区（颜色题）· B=无指针（挣扎动画）")
    return 0


def cmd_loop(_=None):
    """★ v0.3.0 ★ 外层钓鱼循环汇总：抛竿 / 咬钩 / 收杆 / 形态 / 结果。

    一句话判读：
      * cast 有、reel 有、qte_begin 有  => 闭环成立（抛竿→咬钩→收杆→小游戏）。
      * reel 的 after_bite_ms 应落在 0~400ms（实测咬钩→开局只隔 300~360ms）。
      * form_skip 的局数应 ≈ B 形态局数（B 不会按键）。
    """
    fs = logs()
    if not fs:
        print("还没有日志：%s" % LOG)
        return 1
    rows = read_log(fs[-1])
    cfg = load_cfg()
    print("日志: %s（%d 行）" % (os.path.basename(fs[-1]), len(rows)))
    print()

    def cnt(t):
        return sum(1 for r in rows if r.get("type") == t)

    casts = cnt("cast")
    reels = cnt("reel")
    bites = cnt("hook_bite")
    skips = cnt("form_skip")
    begins = [r for r in rows if r.get("type") == "qte_begin"]
    ends = [r for r in rows if r.get("type") == "qte_end"]

    print("开关 : enabled=%s dry_run=%s auto_cast=%s reel_on_bite=%s form=%s"
          % (cfg.get("enabled"), cfg.get("dry_run"), cfg.get("auto_cast"),
             cfg.get("reel_on_bite"), cfg.get("form_strategy")))
    print("循环 : cast=%d  hook_bite=%d  reel=%d  qte_begin=%d  qte_end=%d  form_skip=%d"
          % (casts, bites, reels, len(begins), len(ends), skips))

    lag = [r["after_bite_ms"] for r in rows
           if r.get("type") == "reel" and isinstance(r.get("after_bite_ms"), (int, float))]
    if lag:
        s = sorted(lag)
        print("收杆 : after_bite_ms 中位 %dms  范围 %d~%dms（理想 0~400ms）"
              % (s[len(s) // 2], s[0], s[-1]))
    elif reels == 0:
        print("收杆 : 0 次 —— 要闭环请先开 reel on（并 live）")

    forms = {}
    for b in begins:
        k = b.get("form", "?")
        forms[k] = forms.get(k, 0) + 1
    if forms:
        print("形态 : " + ", ".join("%s=%d" % kv for kv in sorted(forms.items())))
        print("        A=指针+绿区(点按) · C=指针无绿区(颜色题) · B=无指针(挣扎，不按)")

    hit = sum(1 for e in ends if e.get("result") == "hit")
    miss = sum(1 for e in ends if e.get("result") == "miss")
    if hit + miss:
        print("结果 : 成功 %d / 失败 %d  成功率 %.0f%%"
              % (hit, miss, 100.0 * hit / (hit + miss)))

    # 按形态给成功率（只有 end 带 form 才可靠 → 用 game 编号回连 begin）
    fby = {b.get("game"): b.get("form") for b in begins}
    per = {}
    for e in ends:
        f = fby.get(e.get("game"), "?")
        h, m = per.get(f, (0, 0))
        if e.get("result") == "hit":
            h += 1
        elif e.get("result") == "miss":
            m += 1
        per[f] = (h, m)
    if any(h + m for h, m in per.values()):
        print("形态成功率:")
        for f in sorted(per):
            h, m = per[f]
            r = ("%.0f%%" % (100.0 * h / (h + m))) if h + m else "--"
            print("  %-2s  %d/%d  %s" % (f, h, h + m, r))
    return 0


def cmd_tail(args):
    n = int(args[0]) if args else 20
    fs = logs()
    if not fs:
        print("还没有日志：%s" % LOG)
        return 1
    lines = open(fs[-1], encoding="utf-8", errors="replace").read().splitlines()
    print("日志: %s（共 %d 行，显示最后 %d 行）" % (
        os.path.basename(fs[-1]), len(lines), n))
    for line in lines[-n:]:
        print("  " + line)
    return 0


def cmd_flag(name, on):
    os.makedirs(HOME, exist_ok=True)
    p = os.path.join(HOME, name)
    if on:
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("1\n")
        print("已创建 %s —— %s" % (p, "立即停止按键（仍记录）" if name == "STOP"
                                   else "已停采"))
    else:
        if os.path.exists(p):
            os.remove(p)
            print("已删除 %s —— 恢复" % p)
        else:
            print("%s 本来就不存在" % p)
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    cmd = sys.argv[1].lower()
    rest = sys.argv[2:]

    table = {
        "status": cmd_status, "report": cmd_report, "tail": cmd_tail,
        "loop": cmd_loop, "cycle": cmd_loop,
    }
    if cmd in table:
        return table[cmd](rest)
    if cmd == "on":
        return cmd_set("enabled", True)
    if cmd == "off":
        return cmd_set("enabled", False)
    if cmd == "bite":
        if rest and rest[0].lower() in ("on", "off"):
            return cmd_set("bite_log", rest[0].lower() == "on")
        return cmd_bite()
    if cmd == "reel":
        if rest and rest[0].lower() in ("on", "off"):
            return cmd_set("reel_on_bite", rest[0].lower() == "on")
        return cmd_loop()
    if cmd == "form":
        if rest and rest[0].lower() in ("observe", "auto"):
            return cmd_set("form_strategy", rest[0].lower())
        return cmd_loop()          # 不带参数 = 看形态分布（附在循环汇总尾部）
    if cmd == "live":
        return cmd_set("dry_run", False)
    if cmd == "dry":
        return cmd_set("dry_run", True)
    if cmd == "stop":
        return cmd_flag("STOP", True)
    if cmd == "resume":
        return cmd_flag("STOP", False)
    if cmd == "speed":
        if not rest:
            print("用法: speed <毫秒>")
            return 2
        return cmd_set("cadence_ms", int(rest[0]))
    if cmd == "hold":
        if not rest:
            print("用法: hold <tick 数>")
            return 2
        return cmd_set("hold_ticks", int(rest[0]))
    if cmd == "cast":
        return cmd_set("auto_cast", True)
    if cmd == "nocast":
        return cmd_set("auto_cast", False)
    if cmd == "castdelay":
        if not rest:
            print("用法: castdelay <毫秒>")
            return 2
        return cmd_set("cast_delay_ms", int(rest[0]))
    if cmd == "reeldelay":
        if not rest:
            print("用法: reeldelay <毫秒>")
            return 2
        return cmd_set("reel_delay_ms", int(rest[0]))
    if cmd == "cmargin":
        if not rest:
            print("用法: cmargin <px>")
            return 2
        return cmd_set("c_margin", int(rest[0]))
    if cmd == "holdkey":
        if not rest or rest[0].lower() not in ("left", "right", "shift"):
            print("用法: holdkey left|right|shift")
            return 2
        return cmd_set("hold_key", rest[0].lower())
    if cmd == "strategy":
        if not rest or rest[0].lower() not in ("cadence", "geometry"):
            print("用法: strategy cadence|geometry")
            return 2
        return cmd_set("strategy", rest[0].lower())

    print("未知命令: %s" % cmd)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
