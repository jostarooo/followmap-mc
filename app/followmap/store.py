# -*- coding: utf-8 -*-
"""region 瓦片仓库：解析 + 着色 + 内存/磁盘缓存 + 后台预取。

- 每个 region(512x512 方块) 渲染成一张 RGBA 图，空气透明。
- **金字塔**：一次解析 + 一次着色产出 512x512 底图，再用 NEAREST 降采样出全部缩放档位
  （512->256->128->64 各 0.01~0.08ms）。因此切换缩放档位**不再重算**——这是原先
  「每换一档就要重新解析+着色 150ms」的根治办法。
- 磁盘缓存 cache/tiles/<dim>/<mw>/<rx>_<rz>@<zoom>.png，用「源文件 mtime <= 缓存 mtime」
  判断新鲜度，所以 Xaero 重写了某个 region 时会自动重新渲染。
- 内存 LRU 按**字节**计量：金字塔让同一 region 有多个档位，按条目数计会误淘汰。
"""
import os
import re
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
if APP not in sys.path:
    sys.path.insert(0, APP)

import xaero_region as XR            # noqa: E402
from followmap.colors import color_of  # noqa: E402

REGION = 512

# 支持的缩放档位：每像素代表多少方块。取 2 的幂，这样每档都是上一档的精确
# NEAREST 降采样，金字塔才严格等价于「直接按该档渲染」。
ZOOMS = (1, 2, 4, 8)


def tile_px(zoom):
    """该缩放档位下，一个 region 占多少像素。"""
    return (REGION + int(zoom) - 1) // int(zoom)


def nearest_zoom(z):
    """把任意缩放值规整到最近的受支持档位。"""
    z = max(1, int(z))
    return min(ZOOMS, key=lambda v: (abs(v - z), v))


_FNAME_RE = re.compile(r"^(-?\d+)_(-?\d+)\.(zip|xaero)$")


def _safe(s):
    return re.sub(r'[^A-Za-z0-9_.$-]', "_", s)


class TileStore:
    """管理某个「服务器」目录下所有维度的 region 瓦片。"""

    def __init__(self, server_dir, cache_dir=None, max_workers=4,
                 mem_bytes=384 * 1024 * 1024, region_cache_max=24):
        self.server_dir = server_dir
        self.cache_dir = cache_dir or os.path.join(APP, "cache", "tiles", _safe(os.path.basename(server_dir)))
        self.mem_bytes = mem_bytes
        self.region_cache_max = region_cache_max
        self._bytes = 0
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tile")
        self._lock = threading.Lock()
        # OrderedDict 做 LRU：move_to_end / popitem 都是 O(1)。
        # 之前用「dict + list」在放大缩小时缓存有几百个条目，每帧上百次
        # list.remove(key) 是 O(n)，实测能把单帧拖到 25ms。
        self._mem = OrderedDict()   # (dim, mw, rx, rz, zoom) -> Image
        self._pending = {}          # (dim, mw, rx, rz) -> Future（按 region 判重，不是按档位）
        self._region_cache = {}     # path -> (mtime, blocks dict)
        self._rc_order = []         # blocks 很大，限量保存
        self._exist = {}            # (dim, mw) -> (时间, region 坐标集合, 最新 mtime)
        self._exist_lock = threading.Lock()
        # 0.6s：冷扫一次只要 0.16ms（见 scan_dir），没必要为省一点点 IO 让地图晚 1.5 秒
        # 才看见新落盘的 region。
        self.exist_ttl = 0.6
        self._dims_cache = None     # (时间, 结果)；dims() 一次要 40ms，别被反复调
        self._dims_ttl = 5.0
        os.makedirs(self.cache_dir, exist_ok=True)

    # ---------------------------------------------------------------- 目录
    def dims(self):
        """列出该服务器下所有维度目录（含 mw*/cm* 子目录）-> [(dim, [mw...])]

        带 5 秒 TTL：`_pairs()` / `DimResolver._all_pairs()` / `build_dim_map()`
        都会调它，各自还会再遍历一遍，不缓存就会把同一份目录列好几遍。
        """
        now = time.monotonic()
        if self._dims_cache is not None and now - self._dims_cache[0] < self._dims_ttl:
            return self._dims_cache[1]
        out = []
        if os.path.isdir(self.server_dir):
            for d in sorted(os.listdir(self.server_dir)):
                p = os.path.join(self.server_dir, d)
                if not os.path.isdir(p):
                    continue
                try:
                    subs = [s for s in sorted(os.listdir(p))
                            if os.path.isdir(os.path.join(p, s))
                            and ("$" in s or s.startswith("mw") or s.startswith("cm"))]
                except OSError:
                    continue
                if subs:
                    out.append((d, subs))
        self._dims_cache = (now, out)
        return out

    def dim_type(self, dim):
        """读 dimension_config.txt 里的 dimensionTypeId。"""
        p = os.path.join(self.server_dir, dim, "dimension_config.txt")
        if not os.path.exists(p):
            return None
        try:
            with open(p, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("dimensionTypeId:"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
        return None

    def region_dir(self, dim, mw):
        return os.path.join(self.server_dir, dim, mw)

    def scan_dir(self, dim, mw, ttl=None):
        """**一次** scandir 同时拿到「region 坐标集合」与「最新 mtime」，带 TTL 缓存。

        为什么必须合并 + 缓存：原先 `_existing()` 与 `last_activity()` 各扫一遍目录
        （后者还要逐文件 stat），而分辨率器会把这两件事对**所有候选目录**做一遍。
        实测本机 overworld 有 100+ 个候选目录，单次 `candidates()` = 270ms，
        而它**每帧都被调用**（`_resolve_xaero` 里回答「玩家在哪张子图」）——
        于是每帧 310ms 里有 270ms 花在反复列目录上，真正的画图只用 7.7ms，
        帧率被压到 ~1.8fps。这就是地图「跟得慢」的主因，不是渲染慢。

        用 `os.scandir` + `DirEntry.stat()`：目录枚举时 Win32 已经把
        WIN32_FIND_DATA 取回来了，不用再产生系统调用（实测比 getmtime 快得多）。
        """
        key = (dim, mw)
        now = time.monotonic()
        if ttl is None:
            ttl = self.exist_ttl
        with self._exist_lock:
            hit = self._exist.get(key)
            if hit is not None and now - hit[0] <= ttl:
                return hit[1], hit[2]
        s = set()
        la = 0.0
        try:
            with os.scandir(self.region_dir(dim, mw)) as it:
                for e in it:
                    if not e.name.endswith(".zip"):
                        continue
                    a, _, b = e.name[:-4].partition("_")
                    try:
                        s.add((int(a), int(b)))
                    except ValueError:
                        continue
                    try:
                        m = e.stat().st_mtime
                    except OSError:
                        continue
                    if m > la:
                        la = m
        except OSError:
            pass
        with self._exist_lock:
            self._exist[key] = (now, s, la)
        return s, la

    def _existing(self, dim, mw):
        """该目录里已存在的 region 坐标集合（走 scan_dir 的 TTL 缓存）。"""
        return self.scan_dir(dim, mw)[0]

    def region_path(self, dim, mw, rx, rz):
        if (rx, rz) not in self._existing(dim, mw):
            return None
        return os.path.join(self.region_dir(dim, mw), "%d_%d.zip" % (rx, rz))

    def last_activity(self, dim, mw):
        """该目录里最新的 region 文件 mtime（用于猜当前维度）。"""
        return self.scan_dir(dim, mw)[1]

    # ---------------------------------------------------------------- 解析缓存
    def _blocks_of(self, path):
        mtime = os.path.getmtime(path)
        with self._lock:
            hit = self._region_cache.get(path)
            if hit and hit[0] == mtime:
                return hit[1]
        rd = XR.parse_region_file(path)
        with self._lock:
            if path not in self._region_cache:
                self._rc_order.append(path)
            self._region_cache[path] = (mtime, rd.blocks)
            # blocks 一个 region 就有几万项，必须限量，否则跑图久了内存会失控
            while len(self._rc_order) > self.region_cache_max:
                old = self._rc_order.pop(0)
                if old != path:
                    self._region_cache.pop(old, None)
        return rd.blocks

    # ---------------------------------------------------------------- 着色
    def _shade_full(self, blocks):
        """把 blocks 着色成 512x512 RGBA（空气/技术方块透明）。"""
        cmap = {}
        buf = bytearray(REGION * REGION * 4)
        for (dx, dz), nm in blocks.items():
            if not (0 <= dx < REGION and 0 <= dz < REGION):
                continue
            c = cmap.get(nm)
            if c is None:
                c = color_of(nm)
                cmap[nm] = c
            o = (dz * REGION + dx) * 4
            buf[o] = c[0]
            buf[o + 1] = c[1]
            buf[o + 2] = c[2]
            buf[o + 3] = c[3]
        return Image.frombuffer("RGBA", (REGION, REGION), bytes(buf),
                                "raw", "RGBA", 0, 1)

    def _build_zooms(self, dim, mw, rx, rz, zooms=None):
        """解析一次 + 着色一次，产出全部缩放档位 {zoom: Image}。

        这是「切换缩放不卡」的关键：底图只做一次，其余档位是 NEAREST 降采样，
        每档只要 0.01~0.08ms（相比重新解析+着色 ~150ms）。
        """
        path = self.region_path(dim, mw, rx, rz)
        if path is None:
            return {}
        try:
            blocks = self._blocks_of(path)
        except Exception:
            return {}
        if not blocks:
            return {}
        base = self._shade_full(blocks)
        want = tuple(zooms) if zooms else ZOOMS
        out = {}
        for z in want:
            z = int(z)
            if z <= 1:
                out[1] = base
            else:
                n = tile_px(z)
                out[z] = base.resize((n, n), Image.NEAREST)
        # 保证 base 一定被缓存（否则每次都要重新着色）
        out.setdefault(1, base)
        return out

    def _render_region(self, dim, mw, rx, rz, zoom=1):
        """单档位渲染（保留给旧调用点用）。"""
        return self._build_zooms(dim, mw, rx, rz, zooms=(int(zoom),)).get(int(zoom))

    # ---------------------------------------------------------------- 缓存读写
    def _cache_path(self, dim, mw, rx, rz, zoom):
        d = os.path.join(self.cache_dir, _safe(dim), _safe(mw))
        return os.path.join(d, "%d_%d@%d.png" % (rx, rz, zoom))

    def _from_disk(self, dim, mw, rx, rz, zoom):
        src = self.region_path(dim, mw, rx, rz)
        if src is None:
            return None
        cp = self._cache_path(dim, mw, rx, rz, zoom)
        if not os.path.exists(cp):
            return None
        try:
            if os.path.getmtime(cp) + 1.0 < os.path.getmtime(src):
                return None
        except OSError:
            return None
        try:
            im = Image.open(cp)
            im.load()
            return im.convert("RGBA")
        except Exception:
            return None

    def _to_disk(self, img, dim, mw, rx, rz, zoom):
        cp = self._cache_path(dim, mw, rx, rz, zoom)
        try:
            os.makedirs(os.path.dirname(cp), exist_ok=True)
            tmp = cp + ".tmp"
            img.save(tmp, "PNG", compress_level=1)
            os.replace(tmp, cp)
        except Exception:
            pass

    # ---------------------------------------------------------------- 对外
    def get(self, dim, mw, rx, rz, zoom=1, allow_build=False):
        """取瓦片（可能为 None）。allow_build=False 时只读缓存，绝不阻塞。"""
        zoom = int(zoom)
        key = (dim, mw, rx, rz, zoom)
        with self._lock:
            hit = self._mem.get(key)
            if hit is not None:
                self._touch(key)
                return hit

        img = self._from_disk(dim, mw, rx, rz, zoom)
        if img is not None:
            self._put(key, img)
            return img

        if not allow_build:
            return None

        # 一次构建全部档位：用户接下来切缩放时，其它档位已经在手上，不用重新解析
        built = self._build_zooms(dim, mw, rx, rz)
        for z, im in built.items():
            self._put((dim, mw, rx, rz, z), im)
            self._to_disk(im, dim, mw, rx, rz, z)
        return built.get(zoom)

    def request(self, dim, mw, rx, rz, zoom=1):
        """后台请求瓦片；若已在内存直接返回。按 region 判重（一次构建出全部档位）。"""
        zoom = int(zoom)
        key = (dim, mw, rx, rz, zoom)
        rk = (dim, mw, rx, rz)
        with self._lock:
            hit = self._mem.get(key)
            if hit is not None:
                return hit
            if rk in self._pending:
                return None
            self._pending[rk] = self._pool.submit(self._build_job, dim, mw, rx, rz, zoom)
        return None

    def _build_job(self, dim, mw, rx, rz, zoom):
        try:
            return self.get(dim, mw, rx, rz, zoom, allow_build=True)
        finally:
            with self._lock:
                self._pending.pop((dim, mw, rx, rz), None)

    # ---------------------------------------------------------------- LRU
    def _touch(self, key):
        """调用方需持有 _lock。"""
        try:
            self._mem.move_to_end(key)
        except KeyError:
            pass

    def _drop(self, key):
        img = self._mem.pop(key, None)
        if img is not None:
            self._bytes -= img.width * img.height * 4

    def _put(self, key, img):
        sz = img.width * img.height * 4
        with self._lock:
            if key in self._mem:
                self._drop(key)
            self._mem[key] = img
            self._bytes += sz
            # 至少保留几片，否则视口比缓存上限还大时会每帧反复淘汰重建
            while self._bytes > self.mem_bytes and len(self._mem) > 8:
                self._drop(next(iter(self._mem)))

    def prewarm(self, dim, mw, cx, cz, size=None, zoom=1, margin=1,
                radius_regions=None, max_pending=8):
        """把玩家周围「将会看到」的 region 丢给后台线程池。

        size 给定时按真实视口范围算——这才是跟得上跑图的关键：预取范围必须覆盖
        整屏 + 一圈余量，而不是等某片缺了才补（那样玩家永远比地图快一步）。

        按离玩家的距离由近到远排队，地图从中心往外长出来。队列刻意压得比较短
        （实测 region 解析是纯 Python，受 GIL 限制，线程再多也不会更快——实测
        2~4 个 worker 反而比 6~8 个快），排长队只会让「当前最需要的那片」等更久。
        """
        zoom = int(zoom)
        if size:
            hx = (size[0] // 2 + 1) * zoom
            hz = (size[1] // 2 + 1) * zoom
        else:
            hx = hz = REGION * (radius_regions if radius_regions else 1)
        rx0 = int(cx - hx) // REGION - margin
        rx1 = int(cx + hx) // REGION + margin
        rz0 = int(cz - hz) // REGION - margin
        rz1 = int(cz + hz) // REGION + margin
        prx, prz = int(cx) // REGION, int(cz) // REGION

        cells = []
        for rx in range(rx0, rx1 + 1):
            for rz in range(rz0, rz1 + 1):
                # 不存在的地图文件根本不用排队，省掉无谓的任务与磁盘探测
                if self.region_path(dim, mw, rx, rz) is None:
                    continue
                cells.append((max(abs(rx - prx), abs(rz - prz)), rx, rz))
        cells.sort()

        with self._lock:
            before = len(self._pending)
        for _, rx, rz in cells:
            with self._lock:
                if len(self._pending) >= max_pending:
                    break
            self.request(dim, mw, rx, rz, zoom)
        with self._lock:
            after = len(self._pending)
        return {"候选": len(cells), "已排队": after - before, "在途": after}

    def stats(self):
        with self._lock:
            return {"mem": len(self._mem),
                    "mb": round(self._bytes / 1048576.0, 1),
                    "pending": len(self._pending),
                    "blocks_cached": len(self._region_cache)}


if __name__ == "__main__":
    V = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14"
    S = os.path.join(V, "XaeroWorldMap", "Multiplayer_mcfkcs.com")
    st = TileStore(S)
    dims = st.dims()
    print("维度数:", len(dims))
    for d, subs in dims[:6]:
        print("   %-40s type=%-24s subs=%s" % (d, st.dim_type(d), subs[:3]))
    t0 = time.time()
    img = st.get("null", "mw$default", -10, 3, 1, allow_build=True)
    print("主城 region(-10,3) ->", None if img is None else img.size, "%.2fs" % (time.time() - t0))
    t0 = time.time()
    img = st.get("null", "mw$default", -10, 3, 1, allow_build=True)
    print("再取一次(应命中磁盘缓存) %.3fs" % (time.time() - t0))
