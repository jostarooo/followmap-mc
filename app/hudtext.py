# -*- coding: utf-8 -*-
"""HUD 文本渲染：纯 ASCII 行走 MC 像素字体（保持游戏观感），含中文的行走系统 TTF。

为什么需要这个：`ascii.png` 只有 256 个 ASCII 字形，中文会被渲染成**完全空白**。
HUD 里最关键的诊断信息（"不在游戏中"、"等待投票一致"、"此处无地图数据"）都是中文，
不换字体就等于把这些字全抹掉了。

按「整行」切换而不是逐字混合，避免基线对齐的麻烦；同一行内字体统一，观感也不会花。
"""
import os
import sys
from functools import lru_cache

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import mc_font as MF  # noqa: E402

_TTF_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",     # 微软雅黑
    r"C:\Windows\Fonts\simhei.ttf",   # 黑体
    r"C:\Windows\Fonts\Deng.ttf",     # 等线
    r"C:\Windows\Fonts\msjh.ttc",     # 微软正黑
    r"C:\Windows\Fonts\simsun.ttc",   # 宋体
]

_font_cache = {}
_MEASURE = ImageDraw.Draw(Image.new("RGBA", (1, 1)))


def has_cjk(s):
    return any(ord(c) > 127 for c in s)


def _font(px):
    if px in _font_cache:
        return _font_cache[px]
    f = None
    for p in _TTF_CANDIDATES:
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, px)
                break
            except Exception:
                continue
    _font_cache[px] = f
    return f


def ttf_px(scale=1):
    """和 MC 字体视觉重量接近的字号：MC scale=1 的字形高 7px，中文给 12px 才看得清。"""
    return int(round(6.5 * scale + 5))


def use_mc(text, mode="auto"):
    if mode == "mc":
        return True
    if mode == "ttf":
        return False
    return not has_cjk(text)


def measure(text, scale=1, mode="auto"):
    """返回 (宽, 高)。"""
    if use_mc(text, mode):
        return MF.text_width(text, scale), 8 * scale + 2
    f = _font(ttf_px(scale))
    if f is None:
        return MF.text_width(text, scale), 8 * scale + 2
    w = int(_MEASURE.textlength(text, font=f))
    asc, desc = f.getmetrics()
    return w + 2, asc + desc + 2


def render(text, scale=1, fg=(235, 235, 245, 255), mode="auto", shadow=True):
    """渲染一行，返回 RGBA Image（含 +1px 右侧/底部阴影余量）。

    带 LRU 缓存：HUD 每帧都要重画好几行，其中维度名 / 遗迹计数 / 帮助这些**内容不变**，
    实测四行一共 5.1ms/帧，白白重复。缓存后只有坐标那种真会变的行需要重画。
    返回的是**同一个 Image 对象**，所有调用方都只做 alpha_composite（只读），
    不会改动它 —— 所以共享是安全的。
    """
    if not text:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    return _render_cached(text, scale, fg, mode, shadow)


@lru_cache(maxsize=384)
def _render_cached(text, scale, fg, mode, shadow):
    if use_mc(text, mode):
        return MF.render(text, scale, fg=fg, shadow=shadow)
    return _render_ttf(text, scale, fg, shadow)


def _render_ttf(text, scale, fg, shadow):
    px = ttf_px(scale)
    f = _font(px)
    if f is None:                      # 一个中文字体都没有 -> 退回 MC（会是空白，但至少不崩）
        return MF.render(text, scale, fg=fg, shadow=shadow)
    w = int(_MEASURE.textlength(text, font=f))
    asc, desc = f.getmetrics()
    off = max(1, int(round(scale)))
    img = Image.new("RGBA", (w + 2 + off, asc + desc + 2 + off), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if shadow:
        d.text((1 + off, 1 + off), text, font=f,
               fill=(fg[0] // 4, fg[1] // 4, fg[2] // 4, fg[3]))
    d.text((1, 1), text, font=f, fill=fg)
    return img


if __name__ == "__main__":
    print("字体:", _font(ttf_px(1)))
    cases = ["X -6845.0 Y 64.0 Z 12700.0", "minecraft$steam3 / mw$default",
             "等待投票一致 (2/3)", "此处无地图数据", "bridge: 未找到 coords.json"]
    total_h = 0
    for s in cases:
        w, h = measure(s, 1)
        total_h += h
        print("  %-34s mc=%-5s w=%3d h=%2d" % (s, use_mc(s), w, h))
    out = Image.new("RGBA", (420, total_h + 12), (16, 16, 22, 255))
    y = 4
    for s in cases:
        im = render(s, 1)
        out.alpha_composite(im, (4, y))
        y += im.height
    p = os.path.join(HERE, "cache", "hudtext_test.png")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    out.convert("RGB").save(p)
    print("已渲染:", p)
