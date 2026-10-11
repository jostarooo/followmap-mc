# -*- coding: utf-8 -*-
"""Minecraft 像素字体：从客户端 jar 提取 ascii.png，复现 MC 的字形/步进(advance)算法。

MC 的 BitmapProvider 逻辑（1.13+）：
  - ascii.png 是 16x16 个 8x8 字形格，字符 code = row*16 + col
  - 实际字形宽度 w = 从右往左找第一列有非透明像素的 x 索引 + 1（无像素则 0）
  - scale = (image.width / 16) / 8.0
  - advance = round(w * scale) + 1
  - 绘制时整格按 guiScale 放大，所以 devpx 宽 = w * guiScale
本模块只处理 1:1 的 ascii.png（scale=1），guiScale 由调用方作为 `scale` 传入。
"""
import os
import zipfile

from PIL import Image

JAR = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14\1.20.4-Fabric 0.16.14.jar"
_FONT_ENTRY = "assets/minecraft/textures/font/ascii.png"
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")


def _load_atlas(jar=JAR):
    """返回 (PIL.Image RGBA 128x128, cell 像素尺寸)。"""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    png = os.path.join(_CACHE_DIR, "font_ascii.png")
    if not os.path.exists(png):
        with zipfile.ZipFile(jar) as z:
            data = z.read(_FONT_ENTRY)
        with open(png, "wb") as f:
            f.write(data)
    im = Image.open(png).convert("RGBA")
    return im


_ATLAS = None


def atlas():
    global _ATLAS
    if _ATLAS is None:
        _ATLAS = _load_atlas()
    return _ATLAS


def cell_chars():
    """返回 [(code, col, row)]，覆盖全部 256 格。"""
    out = []
    for row in range(16):
        for col in range(16):
            out.append((row * 16 + col, col, row))
    return out


def _glyph_mask(im, col, row, cw, ch):
    """返回 (mask 二维 list[ch][cw] of 0/1, trimmed_width)。"""
    px = im.load()
    x0, y0 = col * cw, row * ch
    m = [[0] * cw for _ in range(ch)]
    for y in range(ch):
        for x in range(cw):
            r, g, b, a = px[x0 + x, y0 + y]
            m[y][x] = 1 if a > 0 else 0
    w = 0
    for x in range(cw - 1, -1, -1):
        if any(m[y][x] for y in range(ch)):
            w = x + 1
            break
    return m, w


_TABLE = None


def table():
    """{char: {'mask':[[...]], 'w':trimmed_width, 'adv':advance}}（scale=1 基准）。"""
    global _TABLE
    if _TABLE is not None:
        return _TABLE
    im = atlas()
    W, H = im.size
    cw, ch = W // 16, H // 16
    t = {}
    for code, col, row in cell_chars():
        if code < 32 or code == 127:
            continue
        mask, w = _glyph_mask(im, col, row, cw, ch)
        t[chr(code)] = {"mask": mask, "w": w, "cw": cw, "ch": ch,
                        "adv": int(0.5 + w) + 1}
    _TABLE = t
    return t


# MC 的 font/include/space.json 显式定义了空格步进：{" ": 4}
_SPACE_ADV = {" ": 4, "\u200c": 0}


def advance(ch, scale=1):
    """设备像素步进。

    MC: BitmapProvider 里 advance = round(w * bitmapScale) + 1 —— 这是**文本单位**，
    渲染时再乘 GUI 缩放。ascii.png 的 bitmapScale = 1，所以
        advance_文本 = w + 1
        advance_设备 = (w + 1) * scale
    空格由 space provider 定义（4 文本单位）-> 4 * scale。
    """
    if ch in _SPACE_ADV:
        return _SPACE_ADV[ch] * scale
    t = table()
    if ch not in t:
        return 5 * scale
    return (t[ch]["w"] + 1) * scale


def text_width(s, scale=1):
    return sum(advance(c, scale) for c in s)


def glyph_bitmap(ch, scale=1):
    """把字形按 scale 整数放大，返回 (mask[scale*ch][scale*cw] 0/1, w_dev)。"""
    t = table()
    info = t.get(ch)
    if info is None:
        return [[0] * (4 * scale) for _ in range(8 * scale)], 0
    cw, ch = info["cw"], info["ch"]
    m = info["mask"]
    up = [[0] * (cw * scale) for _ in range(ch * scale)]
    for y in range(ch * scale):
        for x in range(cw * scale):
            up[y][x] = m[y // scale][x // scale]
    return up, info["w"] * scale


def render(text, scale=1, fg=(255, 255, 255, 255), bg=None, shadow=True,
           line_h=None, pad=0):
    """按 MC 的方式渲染一行文字，返回 PIL.Image。

    shadow: MC 的阴影是 (fg/4, alpha) 偏移 (+1, +1)（scale=1 时；本文取 1 像素）。
    """
    line_h = line_h or (8 * scale + 2)
    w = text_width(text, scale)
    img = Image.new("RGBA", (w + pad * 2 + 2, line_h + pad * 2 + 2), bg or (0, 0, 0, 0))
    px = img.load()
    sh = (fg[0] // 4, fg[1] // 4, fg[2] // 4, fg[3])

    def blit(mask, ox, oy, color):
        for y in range(len(mask)):
            for x in range(len(mask[y])):
                if mask[y][x]:
                    X, Y = ox + x, oy + y
                    if 0 <= X < img.width and 0 <= Y < img.height:
                        px[X, Y] = color

    cx = pad
    for c in text:
        bm, _ = glyph_bitmap(c, scale)
        if bm and bm[0]:
            if shadow:
                blit(bm, cx + scale, pad + scale, sh)   # 阴影偏移 = 1 文本单位 = scale 设备像素
            blit(bm, cx, pad, fg)
        cx += advance(c, scale)
    return img


if __name__ == "__main__":
    t = table()
    print("atlas size:", atlas().size)
    print("字符数:", len(t))
    for c in "0123456789-+.,:XYZ":
        i = t.get(c)
        print("  %r w=%d adv=%d" % (c, i["w"], i["adv"]))
    from PIL import Image as I
    canvas = I.new("RGBA", (400, 30 * 5), (20, 20, 26, 255))
    y = 0
    for s in (1, 2, 3, 4):
        im = render("X: -1234 / Y: 64 / Z: 5678", s,
                    fg=(85, 255, 85, 255) if s % 2 else (255, 255, 255, 255))
        canvas.alpha_composite(im, (2, y))
        y += 30
    out = os.path.join(_CACHE_DIR, "font_test.png")
    canvas.save(out)
    print("已渲染测试:", out)
