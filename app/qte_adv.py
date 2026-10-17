#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
qte_adv.py —— 方块传说钓鱼 QTE 字体 advance 表的**可复现构建器**。

它做三件事：
  1. 从实例的 options.txt 推导「当前启用的资源包」顺序（不硬编码包名）；
  2. 按优先级从高到低找第一个提供 `customfishing` 字体的包，
     用 zipraw 读出 `customfishing:font/default.json` 与 `customfishing:font/offset_chars.json`；
  3. 按 Minecraft bitmap provider 规则推导每个码点的真实 advance，落盘 `qte_advance.json`。

advance 公式（1.20.4 BitmapProvider 实测校准）：
    cols   = max(len(row) for row in chars)     # chars 是「一行一个字符串」的网格
    rows   = len(chars)
    cellW  = imgW / cols
    cellH  = imgH / rows
    advance = cellW * (height / cellH) + spacing
注意：不能用 PNG 像素宽度当 advance —— fish_icon.png 是 16x10 但 advance = 8。

为什么必须合并两张字体表：
    一帧 subtitle 里 B0xx 与 F8xx 属于**两个不同字体**
    （mod 用多个 sibling 组件各带 style.font 拼出来），任何单字体表都会漏。

用法：
    python qte_adv.py                 # 构建并打印摘要
    python qte_adv.py --check         # 只校验 qte_advance.json 是否与当前包一致
"""
import argparse
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import zipraw  # noqa: E402

OUT = os.path.join(HERE, "qte_advance.json")

# 候选实例（与 build_fishprobe.py 的 INSTANCES 一致；按存在性挑第一个）
INSTANCES = [
    r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14",
    r"D:\config\game\mc\方块传说V3.0客户端 2K(2560×1440)\.minecraft",
]

# 关心的两个字体（mod 命名空间 customfishing）
FONT_JSONS = [
    "assets/customfishing/font/default.json",
    "assets/customfishing/font/offset_chars.json",
]


def png_size(b):
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack_from(">II", b, 16)


def find_game_dir():
    for d in INSTANCES:
        if os.path.isdir(d):
            return d
    raise SystemExit("[X] 找不到任何已知实例目录")


def active_packs(game_dir):
    """按 options.txt 推导启用的资源包，返回「低优先级 -> 高优先级」的绝对路径列表。"""
    opt = os.path.join(game_dir, "options.txt")
    if not os.path.exists(opt):
        raise SystemExit("[X] 找不到 options.txt: " + opt)
    m = re.search(r'^resourcePacks:(\[.*\])\s*$', open(opt, encoding="utf-8").read(), re.M)
    if not m:
        raise SystemExit("[X] options.txt 里没有 resourcePacks 行")
    names = json.loads(m.group(1))
    out = []
    for n in names:
        if n.startswith("file/"):
            p = os.path.join(game_dir, "resourcepacks", n[5:])
            if os.path.exists(p):
                out.append(p)
            else:
                print("[!] 启用列表里的包不存在: %s" % p)
    return out


def parse_font(doc, sizes, pack_label):
    """把一张 font json 解成 cp -> 条目。返回 dict。"""
    out = {}
    for pr in doc.get("providers", []):
        if pr.get("type") != "bitmap":
            continue                       # 本模组只用 bitmap；space 型另计
        f = pr.get("file", "")
        ns, rest = f.split(":", 1) if ":" in f else ("minecraft", f)
        real = "assets/%s/textures/%s" % (ns, rest)
        wh = sizes.get(real)
        cs = pr.get("chars") or []
        if isinstance(cs, str):
            cs = [cs]
        if not wh or not cs:
            continue
        iw, ih = wh
        rows = len(cs)
        cols = max((len(r) for r in cs), default=1)
        if not cols or not rows:
            continue
        cellW, cellH = iw / float(cols), ih / float(rows)
        h = pr.get("height") or 0
        sp = pr.get("spacing") or 0
        adv = cellW * (h / cellH) + sp if cellH else 0.0
        for row in cs:
            for ch in row:
                cp = ord(ch)
                if cp not in out:          # 先到先得（与 MC provider 顺序一致）
                    out[cp] = {
                        "advance": round(adv, 4),
                        "file": f,
                        "img": "%dx%d" % (iw, ih),
                        "height": h,
                        "spacing": sp,
                        "font": None,
                        "pack": pack_label,
                    }
    return out


def build():
    game = find_game_dir()
    packs = active_packs(game)
    print("实例 gameDir: %s" % game)
    print("启用资源包（低 -> 高优先级）:")
    for p in packs:
        print("   " + os.path.basename(p))

    # 从最高优先级往下找第一个提供 customfishing 字体的包
    chosen = None
    for p in reversed(packs):
        try:
            d = zipraw.read_raw(p)
        except Exception as e:                             # noqa: BLE001
            print("[!] 读不了 %s: %r" % (p, e))
            continue
        if not all(k in d for k in FONT_JSONS):
            continue
        chosen = (p, d)
        break
    if not chosen:
        raise SystemExit("[X] 启用包里没有任何一个提供 customfishing 字体")
    pack, d = chosen
    print("\n生效包: %s" % os.path.basename(pack))

    # 只解压需要的 png（customfishing/textures/font/**），避免整包解压
    sizes = {}
    for name, b in d.items():
        if name.startswith("assets/customfishing/textures/font/") and name.endswith(".png"):
            s = png_size(b)
            if s:
                sizes[name] = s

    table = {}
    for fn in FONT_JSONS:
        doc = json.loads(d[fn].decode("utf-8-sig"))
        t = parse_font(doc, sizes, os.path.basename(pack))
        for cp, e in t.items():
            e["font"] = fn
            table.setdefault(cp, e)

    meta = {
        "_说明": "方块传说钓鱼 QTE 字体 advance 表；由 qte_adv.py 从活动资源包实测推导，勿手改",
        "game_dir": game,
        "pack": os.path.basename(pack),
        "packs_active": [os.path.basename(p) for p in packs],
        "fonts": FONT_JSONS,
        "formula": "advance = (imgW/cols) * (height/(imgH/rows)) + spacing",
        "points": {str(cp): table[cp] for cp in sorted(table)},
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    print("\n落盘 %s（%d 个码点）" % (OUT, len(table)))
    return meta


def show(meta):
    print("\n%-8s %-46s %-9s %8s  %s" % ("码点", "file", "img", "advance", "font"))
    for cp in sorted(int(k) for k in meta["points"]):
        e = meta["points"][str(cp)]
        print("U+%04X  %-46s %-9s %8.2f  %s" % (
            cp, e["file"], e["img"], e["advance"],
            os.path.basename(e["font"])))


def check():
    if not os.path.exists(OUT):
        print("[X] 缺少 " + OUT)
        return 1
    old = json.load(open(OUT, encoding="utf-8"))
    new = build()
    if old.get("points") == new["points"] and old.get("pack") == new["pack"]:
        print("\n[v] qte_advance.json 与当前活动包一致（%s, %d 码点）"
              % (new["pack"], len(new["points"])))
        return 0
    print("\n[X] qte_advance.json 已过期（包或数值变了），请重新生成")
    return 1


def main():
    ap = argparse.ArgumentParser(description="QTE 字体 advance 表构建器")
    ap.add_argument("--check", action="store_true", help="校验已有表是否过期")
    a = ap.parse_args()
    if a.check:
        return check()
    meta = build()
    show(meta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
