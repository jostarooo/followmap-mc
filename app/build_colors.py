# -*- coding: utf-8 -*-
"""
从 Minecraft 客户端 jar 的方块贴图生成「方块 -> 颜色」表。
=========================================================

Xaero 的世界地图本质上是「每个方块取一个代表色」。我们沿用同样思路：
读 assets/minecraft/textures/block/<name>.png，过滤透明像素后取平均色。

输出 block_colors.json:  {"minecraft:stone": [r,g,b], ...}

对少数据需要「生物群系染色」的方块（草、树叶、水）做特判，
否则贴图本身是灰白的，渲染出来会失真。
"""
import io
import os
import json
from collections import Counter

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
MC = r"D:\config\game\mc\pcl2\.minecraft"
JAR = os.path.join(MC, "versions", "1.20.4-Fabric 0.16.14", "1.20.4-Fabric 0.16.14.jar")
OUT = os.path.join(HERE, "block_colors.json")

# ----------------------------------------------------------------------------
# 需要特殊处理的方块（贴图是灰白的，或需要固定色）
# ----------------------------------------------------------------------------
SPECIAL = {
    # 生物群系染色 -> 取平原风格色
    "minecraft:grass_block": (124, 176, 74),
    "minecraft:grass": (124, 176, 74),
    "minecraft:short_grass": (124, 176, 74),
    "minecraft:tall_grass": (124, 176, 74),
    "minecraft:fern": (124, 176, 74),
    "minecraft:large_fern": (124, 176, 74),
    "minecraft:oak_leaves": (60, 122, 52),
    "minecraft:jungle_leaves": (48, 138, 44),
    "minecraft:spruce_leaves": (52, 96, 60),
    "minecraft:birch_leaves": (110, 160, 66),
    "minecraft:dark_oak_leaves": (44, 96, 36),
    "minecraft:acacia_leaves": (108, 152, 44),
    "minecraft:azalea_leaves": (86, 138, 52),
    "minecraft:mangrove_leaves": (74, 138, 54),
    "minecraft:cherry_leaves": (226, 168, 196),
    "minecraft:vine": (72, 118, 54),
    "minecraft:lily_pad": (60, 116, 50),
    "minecraft:water": (52, 92, 200),
    "minecraft:bubble_column": (60, 110, 210),
    "minecraft:flowing_water": (52, 92, 200),
    "minecraft:sugar_cane": (140, 190, 110),
    "minecraft:kelp": (60, 118, 76),
    "minecraft:kelp_plant": (60, 118, 76),
    "minecraft:seagrass": (74, 132, 84),
    "minecraft:tall_seagrass": (74, 132, 84),
    "minecraft:lava": (207, 92, 20),
    "minecraft:cauldron": (70, 70, 74),
    "minecraft:water_cauldron": (52, 92, 200),
    "minecraft:fire": (255, 160, 40),
    "minecraft:nether_portal": (120, 40, 190),
    "minecraft:end_portal": (10, 10, 20),
    "minecraft:end_gateway": (20, 16, 40),
    # 末地（遗迹识别最关心）
    "minecraft:end_stone": (219, 222, 158),
    "minecraft:end_stone_bricks": (208, 212, 148),
    "minecraft:chorus_plant": (89, 58, 89),
    "minecraft:chorus_flower": (150, 100, 150),
    "minecraft:purpur_block": (169, 126, 169),
    "minecraft:purpur_pillar": (172, 130, 172),
    "minecraft:obsidian": (20, 16, 28),
    "minecraft:crying_obsidian": (40, 20, 80),
}

# 后缀剥离（楼梯/台阶等用基础材质）
SUFFIXES = [
    "_stairs", "_slab", "_wall", "_fence_gate", "_fence", "_door", "_trapdoor",
    "_button", "_pressure_plate", "_hanging_sign", "_sign", "_carpet", "_pane",
    "_bars", "_chain", "_banner", "_bed", "_head", "_skull", "_candle", "_grate",
]

# 找不到贴图时的关键词兜底色
KEYWORD = [
    ("water", (52, 92, 200)), ("lava", (207, 92, 20)),
    ("leaves", (72, 130, 56)), ("grass", (124, 176, 74)),
    ("planks", (158, 128, 78)), ("log", (110, 86, 52)),
    ("stone", (125, 125, 125)), ("cobble", (114, 114, 114)),
    ("deepslate", (80, 80, 84)), ("blackstone", (44, 38, 42)),
    ("sand", (219, 207, 163)), ("gravel", (131, 127, 126)),
    ("dirt", (134, 96, 67)), ("snow", (240, 243, 246)),
    ("ice", (160, 196, 232)), ("glass", (200, 220, 230)),
    ("wool", (220, 220, 220)), ("terracotta", (150, 110, 90)),
    ("concrete", (180, 180, 180)), ("copper", (200, 120, 90)),
    ("iron", (216, 216, 216)), ("gold", (246, 208, 61)),
    ("diamond", (98, 219, 214)), ("emerald", (82, 217, 118)),
    ("netherrack", (110, 60, 60)), ("basalt", (86, 86, 90)),
    ("end_stone", (219, 222, 158)), ("purpur", (169, 126, 169)),
    ("quartz", (235, 231, 223)), ("brick", (150, 96, 80)),
    ("prismarine", (100, 160, 150)), ("obsidian", (20, 16, 28)),
    ("amethyst", (140, 100, 200)), ("glowstone", (250, 220, 130)),
    ("sea_lantern", (200, 226, 220)), ("moss", (90, 130, 62)),
    ("mud", (60, 58, 66)), ("clay", (160, 166, 179)),
]


def _avg_color(im):
    im = im.convert("RGBA")
    px = list(im.getdata())
    rs = gs = bs = n = 0
    for r, g, b, a in px:
        if a < 128:
            continue
        rs += r * r
        gs += g * g
        bs += b * b
        n += 1
    if n == 0:
        return None
    return (int((rs / n) ** 0.5), int((gs / n) ** 0.5), int((bs / n) ** 0.5))


def main():
    import zipfile
    z = zipfile.ZipFile(JAR)
    names = set(z.namelist())
    PREFIX = "assets/minecraft/textures/block/"

    tex = {}
    for n in names:
        if n.startswith(PREFIX) and n.lower().endswith(".png"):
            short = n[len(PREFIX):-4]
            tex[short] = n
    print("可用方块贴图:", len(tex))

    cache = {}

    def color_of_texture(short):
        if short in cache:
            return cache[short]
        path = tex.get(short)
        if path is None:
            cache[short] = None
            return None
        try:
            im = Image.open(io.BytesIO(z.read(path)))
            c = _avg_color(im)
        except Exception:
            c = None
        cache[short] = c
        return c

    def candidates(base):
        n = base
        yield n
        for s in SUFFIXES:
            if n.endswith(s):
                yield n[:-len(s)]
                break
        for extra in (n + "_top", n + "_side", n + "_front", n + "_block",
                      n + "_planks", n + "_stage0", n + "_age0", n + "_0"):
            yield extra

    def keyword_color(n):
        for k, c in KEYWORD:
            if k in n:
                return c
        return None

    # 收集所有需要着色的方块名：从真实数据来
    inv = os.path.join(HERE, "block_inventory.json")
    blocks = set()
    if os.path.exists(inv):
        d = json.load(open(inv, encoding="utf-8"))
        blocks = set(d.get("per_block_region_count", {}).keys())
    print("数据里出现过的方块:", len(blocks))

    out = {}
    stats = Counter()
    for full in sorted(blocks):
        if full in SPECIAL:
            out[full] = list(SPECIAL[full])
            stats["special"] += 1
            continue
        n = full.split(":")[1] if ":" in full else full
        c = None
        for cand in candidates(n):
            c = color_of_texture(cand)
            if c:
                stats["texture"] += 1
                break
        if c is None:
            c = keyword_color(n)
            if c:
                stats["keyword"] += 1
        if c is None:
            import colorsys
            h = (abs(hash(full)) % 360) / 360.0
            r, g, b = colorsys.hsv_to_rgb(h, 0.25, 0.70)
            c = (int(r * 255), int(g * 255), int(b * 255))
            stats["hash"] += 1
        out[full] = list(c)

    # 把 SPECIAL 里但数据没出现的也补进去（便于直接按名查）
    for k, v in SPECIAL.items():
        out.setdefault(k, list(v))

    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=0, sort_keys=True)
    print("统计:", dict(stats))
    print("写出:", OUT, "共", len(out), "种")

    # 抽样展示
    show = ["minecraft:stone", "minecraft:dirt", "minecraft:sand", "minecraft:water",
            "minecraft:end_stone", "minecraft:chorus_plant", "minecraft:quartz_block",
            "minecraft:grass_block", "minecraft:oak_leaves", "minecraft:gravel"]
    for k in show:
        v = out.get(k)
        print("   %-30s %s  #%02x%02x%02x" % (k, v, v[0], v[1], v[2]) if v else "   %-30s None" % k)


if __name__ == "__main__":
    main()
