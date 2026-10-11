# -*- coding: utf-8 -*-
"""地图视口：把 region 瓦片拼成以玩家为中心的一屏，并叠加玩家标记/HUD。"""
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
if APP not in sys.path:
    sys.path.insert(0, APP)

import hudtext as HT  # noqa: E402
from followmap.store import REGION, TileStore  # noqa: E402

GRID_COLOR = (255, 255, 255, 28)
PLAYER_FILL = (255, 70, 70, 255)
PLAYER_EDGE = (255, 255, 255, 255)


class MapView:
    def __init__(self, store: TileStore, bg=(14, 14, 18, 255), empty=(60, 60, 70, 90)):
        self.store = store
        self.bg = bg
        self.empty = empty

    def render(self, dim, mw, cx, cz, size=(560, 560), zoom=1, poi=None,
               hud_lines=(), show_grid=True, pending_hint=True):
        W, H = size
        zoom = max(1, int(zoom))
        img = Image.new("RGBA", (W, H), self.bg)

        # 视口左上角世界坐标；对齐到 zoom 的整数倍，避免重采样抖动
        x0 = int(cx) - (W // 2) * zoom
        z0 = int(cz) - (H // 2) * zoom
        x0 -= x0 % zoom
        z0 -= z0 % zoom
        x1, z1 = x0 + W * zoom, z0 + H * zoom

        missing = 0
        drawn = 0
        rx0, rx1 = x0 // REGION, (x1 - 1) // REGION
        rz0, rz1 = z0 // REGION, (z1 - 1) // REGION
        tile_px = REGION // zoom

        for rx in range(rx0, rx1 + 1):
            for rz in range(rz0, rz1 + 1):
                # 先确认这个 region 到底存不存在；不存在就没必要碰磁盘/内存
                if self.store.region_path(dim, mw, rx, rz) is None:
                    continue
                # 先看内存，没有就丢到后台渲染
                tile = self.store.get(dim, mw, rx, rz, zoom, allow_build=False)
                if tile is None:
                    self.store.request(dim, mw, rx, rz, zoom)
                    missing += 1
                    continue
                bx, bz = rx * REGION, rz * REGION
                # 需要粘贴的像素范围
                sx0 = max(0, x0 - bx) // zoom
                sz0 = max(0, z0 - bz) // zoom
                sx1 = min(REGION, x1 - bx) // zoom
                sz1 = min(REGION, z1 - bz) // zoom
                if sx1 <= sx0 or sz1 <= sz0:
                    continue
                src = tile.crop((sx0, sz0, sx1, sz1))
                dx = (bx + sx0 * zoom - x0) // zoom
                dz = (bz + sz0 * zoom - z0) // zoom
                img.alpha_composite(src, (dx, dz))
                drawn += 1

        self.last_drawn = drawn
        self.last_missing = missing

        d = ImageDraw.Draw(img, "RGBA")   # RGBA 模式才会做 alpha 混合
        if show_grid:
            step = 128 // 1
            gx = (-x0) // step
            g0 = step // zoom
            if g0 >= 24:
                xx = ((-x0) % step) // zoom
                while xx < W:
                    d.line([(xx, 0), (xx, H)], fill=GRID_COLOR)
                    xx += g0
                zz = ((-z0) % step) // zoom
                while zz < H:
                    d.line([(0, zz), (W, zz)], fill=GRID_COLOR)
                    zz += g0

        # POI
        if poi:
            for name, px, pz, color in poi:
                sx = int((px - x0) / zoom)
                sz = int((pz - z0) / zoom)
                if -20 <= sx <= W + 20 and -20 <= sz <= H + 20:
                    self._marker(d, sx, sz, color or (255, 200, 60, 255))
                    t = HT.render(name, 1, fg=(255, 255, 255, 255))
                    img.alpha_composite(t, (sx + 7, sz - t.height // 2))

        # 玩家
        pcx = int((cx - x0) / zoom)
        pcz = int((cz - z0) / zoom)
        self._player(d, pcx, pcz)
        d.line([(pcx - 14, pcz), (pcx - 5, pcz)], fill=PLAYER_FILL)
        d.line([(pcx + 5, pcz), (pcx + 14, pcz)], fill=PLAYER_FILL)
        d.line([(pcx, pcz - 14), (pcx, pcz - 5)], fill=PLAYER_FILL)
        d.line([(pcx, pcz + 5), (pcx, pcz + 14)], fill=PLAYER_FILL)

        # 空数据提示：放在玩家标记**下方**，否则会被标记压住
        if drawn == 0 and pending_hint:
            msg = ("此处无地图数据" if missing == 0 else "地图渲染中…")
            sub = "%s / %s" % (dim, mw)
            t = HT.render(msg, 2, fg=(214, 218, 230, 255))
            y = pcz + 24
            img.alpha_composite(t, ((W - t.width) // 2, y))
            t2 = HT.render(sub, 1, fg=(156, 162, 178, 255))
            img.alpha_composite(t2, ((W - t2.width) // 2, y + t.height + 3))

        # HUD：先铺一层半透明底板，否则压在浅色地形上读不清。
        # 文本走 hudtext（ASCII 用 MC 像素字体，中文自动切系统 TTF），行高按实际图片算。
        if hud_lines:
            rendered = [HT.render(s, 1, fg=c or (235, 235, 245, 255))
                        for s, c in hud_lines]
            tw = max(t.width for t in rendered)
            th = sum(t.height for t in rendered) + 6
            d.rounded_rectangle([6, 4, 18 + tw, 4 + th], radius=3,
                                fill=(8, 8, 12, 172))
            y = 8
            for t in rendered:
                img.alpha_composite(t, (12, y))
                y += t.height
        return img, missing

    @staticmethod
    def _marker(d, x, y, color):
        d.polygon([(x, y - 6), (x + 6, y), (x, y + 6), (x - 6, y)],
                  fill=color, outline=(0, 0, 0, 220))
        d.point((x, y), fill=(0, 0, 0, 255))

    @staticmethod
    def _player(d, x, y):
        d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=PLAYER_FILL, outline=PLAYER_EDGE)


if __name__ == "__main__":
    import time
    V = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14"
    st = TileStore(os.path.join(V, "XaeroWorldMap", "Multiplayer_mcfkcs.com"))
    mv = MapView(st)
    OUT = os.path.join(APP, "out")
    os.makedirs(OUT, exist_ok=True)
    cases = [
        ("主城(地表)", "null", "mw$default", -800, 700),
        ("主城(洞穴图)", "null", "cm$111", -800, 700),
        ("末地主岛", "DIM1", "mw$default", 0, 0),
        ("末地外岛", "DIM1", "cm$1", 5816, -47608),
    ]
    for label, dim, mw, cx, cz in cases:
        t0 = time.time()
        img, miss = mv.render(dim, mw, cx, cz, size=(560, 560), zoom=1,
                              hud_lines=[("%s  %s  (%d,%d)" % (label, mw, cx, cz),
                                          (255, 220, 120, 255))])
        for k in range(60):
            img, miss = mv.render(dim, mw, cx, cz, size=(560, 560), zoom=1,
                                  hud_lines=[("%s  %s  (%d,%d)" % (label, mw, cx, cz),
                                              (255, 220, 120, 255))])
            if miss == 0:
                break
            time.sleep(0.15)
        p = os.path.join(OUT, "view_%s.png" % label)
        img.convert("RGB").save(p)
        print("%-14s -> %s  缺瓦片 %d  迭代 %d  用时 %.1fs"
              % (label, p, miss, k + 1, time.time() - t0))
