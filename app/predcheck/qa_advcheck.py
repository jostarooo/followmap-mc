#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""qa_advcheck.py —— 严过关独立验证 #1：advance 表独立重算。

不复用 qte_adv.py 的任何代码路径：
  - 直接用 zipraw 读活动资源包（zipraw 是通用工具，不算 qte_adv 专属逻辑）
  - 自己解析字体 JSON 的 chars 网格（rows=len(chars), cols=len(chars[0])）
  - 自己解析 PNG IHDR 拿真实尺寸（不依赖 PIL）
  - advance = (imgW/cols) * (height/(imgH/rows)) + spacing
  - 与 app/qte_advance.json 的 36 点逐项比对
  - 与 Geom.java 的 switch 表逐项比对（正则抽取 case 行）
"""
import json
import re
import struct
import sys
import io

sys.path.insert(0, r"D:\wbworkspace\2026-10-08-17-29-12\fangkuai-chuanshuo\app")
from zipraw import read_raw

APP = r"D:\wbworkspace\2026-10-08-17-29-12\fangkuai-chuanshuo\app"
PACK = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14\resourcepacks\服务器材质10.2.zip"
FONTS = [
    "assets/customfishing/font/default.json",
    "assets/customfishing/font/offset_chars.json",
]


def png_size(data: bytes):
    """直接解析 PNG IHDR，返回 (width, height)。"""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def tex_path(res: str) -> str:
    """customfishing:font/bars/x.png -> assets/customfishing/textures/font/bars/x.png"""
    ns, p = res.split(":")
    return "assets/%s/textures/%s" % (ns, p)


def main():
    d = read_raw(PACK)
    print("pack 文件数: %d" % len(d))

    recomputed = {}  # codepoint(str) -> advance(float)
    for font in FONTS:
        spec = json.loads(d[font].decode("utf-8"))
        for prov in spec.get("providers", []):
            if prov.get("type") != "bitmap":
                print("  [跳过非 bitmap] %s type=%s" % (font, prov.get("type")))
                continue
            grid = prov["chars"]              # 一行一个字符串
            rows = len(grid)
            cols = len(grid[0])
            assert all(len(r) == cols for r in grid), "网格不齐: %s" % prov["file"]
            img = prov["file"]
            tp = tex_path(img)
            w, h = png_size(d[tp])
            height = prov["height"]
            spacing = sum(prov.get("spacing", [0, 0]))  # x/y spacing；advance 用 x
            adv = (w / cols) * (height / (h / rows)) + spacing
            for row in grid:
                for ch in row:
                    cp = ord(ch)
                    recomputed[str(cp)] = adv
            print("  %-52s img=%dx%d grid=%dx%d height=%+d spacing=%d -> advance=%g"
                  % (img, w, h, cols, rows, height, spacing, adv))

    print("\n重算共 %d 个码点" % len(recomputed))

    # ---- 比对 qte_advance.json ----
    ref = json.load(open(APP + r"\qte_advance.json", encoding="utf-8"))
    points = ref["points"]
    ok = True
    for cp in sorted(set(points) | set(recomputed), key=int):
        a = points.get(cp, {}).get("advance")
        b = recomputed.get(cp)
        if a is None or b is None:
            print("  ✗ 码点 U+%04X: json=%s 重算=%s （缺失）" % (int(cp), a, b))
            ok = False
        elif abs(a - b) > 1e-6:
            print("  ✗ 码点 U+%04X: json=%g 重算=%g （不一致）" % (int(cp), a, b))
            ok = False
    print("qte_advance.json 比对: %s（%d 点）" % ("PASS" if ok else "FAIL", len(points)))

    # ---- 比对 Geom.java ----
    geom_src = open(APP + r"\fishauto\src\fishauto\Geom.java", encoding="utf-8").read()
    java_table = {}
    for m in re.finditer(r"case (0x[0-9A-Fa-f]+)(?:: case 0x[0-9A-Fa-f]+)*: return (-?\d+);", geom_src):
        pass
    # 逐行解析更稳：case 组 + return 可能分组，先抓「连续 case 后 return」的块
    for m in re.finditer(r"((?:case 0x[0-9A-Fa-f]+:\s*)+)return (-?\d+);", geom_src):
        val = int(m.group(2))
        for cpm in re.finditer(r"0x([0-9A-Fa-f]+)", m.group(1)):
            java_table[str(int(cpm.group(1), 16))] = val
    print("Geom.java 抽到 %d 个 case 码点" % len(java_table))

    ok2 = True
    for cp in sorted(set(java_table) | set(recomputed), key=int):
        a = java_table.get(cp)
        b = recomputed.get(cp)
        if a is None or b is None:
            print("  ✗ 码点 U+%04X: java=%s 重算=%s （缺失）" % (int(cp), a, b))
            ok2 = False
        elif abs(a - b) > 1e-6:
            print("  ✗ 码点 U+%04X: java=%g 重算=%g （不一致）" % (int(cp), a, b))
            ok2 = False
    print("Geom.java 比对: %s" % ("PASS" if ok2 else "FAIL"))

    # ---- B001..B014 是否全部在两个字体 JSON 里都有出处 ----
    print("\n码点出处核查（B0xx 应出自 default.json，F8xx 应出自 offset_chars.json）:")
    ok3 = True
    for cp in sorted(recomputed, key=int):
        v = int(cp)
        src = ref["points"].get(cp, {}).get("font", "?")
        want = FONTS[0] if 0xAC00 <= v <= 0xD7A3 else (FONTS[1] if 0xF801 <= v <= 0xF818 else None)
        if want and src != want:
            print("  ✗ U+%04X 字体出处 %s ≠ 预期 %s" % (v, src, want))
            ok3 = False
    print("字体出处核查: %s" % ("PASS" if ok3 else "FAIL"))

    verdict = "PASS" if (ok and ok2 and ok3) else "FAIL"
    print("\n===== 验证#1 advance 表独立重算: %s =====" % verdict)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
