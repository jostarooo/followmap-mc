# -*- coding: utf-8 -*-
"""生成桌面壳的应用图标 app.ico（像素风，与界面同款紫珀菱形标记）。

用 PIL 画，构建前跑一次即可；产出 desktop/app.ico（多尺寸 ICO）。
"""
from pathlib import Path

from PIL import Image

# 32×32 像素图：'.' 透明 / 'o' 描边 / 'b' 面板底 / 'B' 面板亮边
#                              '/' 菱形亮面 / '#' 菱形主体 / '\\' 菱形暗面 / '*' 高光
ART = [
    "................................",
    "................................",
    "....oooooooooooooooooooooooo....",
    "...obbbbbbbbbbbbbbbbbbbbbbbbo...",
    "...obBBBBBBBBBBBBBBBBBBBBBBbo...",
    "...obBbbbbbbbbbbbbbbbbbbbbBbo...",
    "...obBbbbbbbbb##bbbbbbbbbbBbo...",
    "...obBbbbbbbb/##\\bbbbbbbbbBbo...",
    "...obBbbbbbb/####\\bbbbbbbbBbo...",
    "...obBbbbbb/######\\bbbbbbbBbo...",
    "...obBbbbb/########\\bbbbbbBbo...",
    "...obBbbb/###*######\\bbbbbBbo...",
    "...obBbb/#####*######\\bbbbBbo...",
    "...obBb/#####*########\\bbbBbo...",
    "...obBb\\#########*####/bbbBbo...",
    "...obBbb\\###########/bbbbBbo...",
    "...obBbbb\\####*####/bbbbbBbo...",
    "...obBbbbb\\#######/bbbbbbBbo...",
    "...obBbbbbb\\#####/bbbbbbbBbo...",
    "...obBbbbbbb\\###/bbbbbbbbBbo...",
    "...obBbbbbbbb\\#/bbbbbbbbbBbo...",
    "...obBbbbbbbbbbbbbbbbbbbbbBbo...",
    "...obBbbbbbbbbbbbbbbbbbbbbBbo...",
    "...obBBBBBBBBBBBBBBBBBBBBBBbo...",
    "...obbbbbbbbbbbbbbbbbbbbbbbbo...",
    "....oooooooooooooooooooooooo....",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
]

PAL = {
    ".": (0, 0, 0, 0),
    "o": (7, 6, 11, 255),
    "b": (36, 28, 51, 255),
    "B": (72, 56, 100, 255),
    "#": (189, 147, 207, 255),
    "/": (230, 213, 238, 255),
    "\\": (138, 95, 156, 255),
    "*": (255, 255, 255, 255),
}


def build() -> Image.Image:
    h = len(ART)
    w = len(ART[0])
    im = Image.new("RGBA", (w, h))
    px = im.load()
    for y, row in enumerate(ART):
        for x, ch in enumerate(row):
            if x < w:
                px[x, y] = PAL.get(ch, PAL["."])
    return im


def main():
    out = Path(__file__).resolve().parent / "app.ico"
    base = build()
    sizes = [256, 128, 64, 48, 32, 16]
    frames = [base.resize((s, s), Image.NEAREST) for s in sizes]
    frames[0].save(out, format="ICO", sizes=[(s, s) for s in sizes],
                   append_images=frames[1:])
    # 顺手出一张 PNG 便于预览
    base.resize((256, 256), Image.NEAREST).save(Path(__file__).parent / "_icon_preview.png")
    print("写出:", out, out.stat().st_size, "字节")


if __name__ == "__main__":
    main()
