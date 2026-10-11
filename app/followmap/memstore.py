# -*- coding: utf-8 -*-
"""内存直读层：把 CoordBridge 模组落盘的「已加载区块地表」渲染成瓦片。

数据来源
--------
    ~/.coordbridge/chunks/<维度>/r<rx>/r<rz>/<cx>_<cz>.bin
    ~/.coordbridge/index_<维度>.json          （每个 region 的版本号，用于判新鲜度）

模组直读游戏内存中的已加载区块，延迟 < 1 秒；而 Xaero 的地图落盘是硬编码 60 秒一次
（MapSaveLoad.SAVE_TIME，编译期常量，改不了配置），实测 region 文件 20 秒以上才写一个。
所以「脚下这块地」用内存层才是实时的，Xaero 层用来补历史区域的底图。

对外两个类
----------
    MemLayer        读 mod 数据、渲染 region 图（内存 LRU + 磁盘缓存）
    CompositeStore  把 MemLayer 叠在 Xaero 的 TileStore 之上，对外接口与 TileStore 一致，
                    因此 MapView 不需要知道底下有几层数据。
"""
import json
import os
import re
import struct
import sys
import threading
import time
from collections import OrderedDict

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
if APP not in sys.path:
    sys.path.insert(0, APP)

from followmap.colors import color_of  # noqa: E402
from followmap.store import REGION, tile_px  # noqa: E402

MAGIC = 0x31424243          # "CBB1"
HDR = struct.Struct("<IHHiiH")
EMPTY = 0xFFFF
NODATA_Y = -32768
REGION_CHUNKS = 32          # 512 方块 / 16 = 32 chunk
MEM_MW = "$mem"             # 虚拟子图名：表示「内存层 + Xaero 底图」的合成图


def parse_chunk(path):
    """解析一个 chunk 快照文件 -> (cx, cz, palette, ys, idx) 或 None。"""
    try:
        with open(path, "rb") as f:
            d = f.read()
    except OSError:
        return None
    if len(d) < HDR.size:
        return None
    magic, ver, _flags, cx, cz, paln = HDR.unpack_from(d, 0)
    if magic != MAGIC or ver != 1:
        return None
    o = HDR.size
    pal = []
    for _ in range(paln):
        if o + 2 > len(d):
            return None
        (n,) = struct.unpack_from("<H", d, o)
        o += 2
        if o + n > len(d):
            return None
        pal.append(d[o:o + n].decode("utf-8", "replace"))
        o += n
    if o + 1024 > len(d):
        return None
    ys = np.frombuffer(d, dtype="<i2", count=256, offset=o)
    idx = np.frombuffer(d, dtype="<u2", count=256, offset=o + 512)
    return cx, cz, pal, ys, idx


def _safe(name):
    return re.sub(r'[^A-Za-z0-9_.$-]', "_", name)


def _scan_dir(store, dim, mw):
    """一次扫描同时拿到 region 坐标集合与最新 mtime。

    优先用 store 自己的 scan_dir（它带 TTL 缓存、用 DirEntry.stat()，且和
    DimResolver/_pairs 共用同一份结果）；对方没有这个方法时才退回自己扫。
    """
    fn = getattr(store, "scan_dir", None)
    if fn is not None:
        try:
            return fn(dim, mw)
        except Exception:
            pass
    s = set()
    la = 0.0
    d = store.region_dir(dim, mw)
    try:
        for f in os.listdir(d):
            if not f.endswith(".zip"):
                continue
            a, _, b = f[:-4].partition("_")
            try:
                s.add((int(a), int(b)))
            except ValueError:
                continue
            try:
                m = os.path.getmtime(os.path.join(d, f))
                if m > la:
                    la = m
            except OSError:
                pass
    except OSError:
        pass
    return s, la


def _near_region(s, rx, rz, radius=8):
    """(rx,rz) 到集合 s 的切比雪夫距离；没找到返回 99。"""
    if not s:
        return 99
    if (rx, rz) in s:
        return 0
    for k in range(1, radius + 1):
        for dx in range(-k, k + 1):
            for dy in (-k, k):
                if (rx + dx, rz + dy) in s or (rx + dy, rz + dx) in s:
                    return k
    return 99


def build_dim_map(store, cx=None, cz=None):
    """Xaero 目录名 -> mod 维度 id。

    mod 只知道维度类型（minecraft:overworld），但服务器往往开了**多个同类型世界**
    （训练场、资源世界、剧情世界…），它们的 dimensionTypeId 一模一样。
    实测本服有 20+ 个 overworld 目录，而玩家真正在的是 null。
    所以**不能按名字或写入时间猜**：优先选「玩家脚下真的落在这个世界的 region 里」的那个，
    其次才比最后写入时间。
    """
    trx = trz = None
    if cx is not None and cz is not None:
        trx, trz = int(cx) // REGION, int(cz) // REGION

    best = {}          # dimId -> ((near, -lastActivity), dimDir)
    for dim, mws in store.dims():
        t = store.dim_type(dim)
        if not t:
            continue
        near = 99
        la = 0.0
        for mw in mws:
            s, m = _scan_dir(store, dim, mw)
            if not s:
                continue
            if trx is not None:
                near = min(near, _near_region(s, trx, trz))
            if m > la:
                la = m
        if la <= 0.0:
            continue
        score = (near, -la)
        cur = best.get(t)
        if cur is None or score < cur[0]:
            best[t] = (score, dim)
    return {v[1]: k for k, v in best.items()}


class MemLayer:
    """读 ~/.coordbridge/chunks/ 并渲染 region。"""

    def __init__(self, root=None, cache_dir=None, dim_map=None, mem_limit=192):
        self.root = (root or os.environ.get("COORDBRIDGE_HOME")
                     or os.path.join(os.path.expanduser("~"), ".coordbridge"))
        self.chunks_root = os.path.join(self.root, "chunks")
        self.cache_dir = cache_dir or os.path.join(APP, "cache", "memtiles")
        self.dim_map = dim_map if dim_map is not None else {}  # 由调用方原地更新，不复制
        self._mem = OrderedDict()
        self._mem_limit = mem_limit
        self._idx = {}                          # safe -> (t, data, mtime_ns)
        # 索引检查：**先看文件 mtime，变了才重新解析 JSON**。
        #
        # 这个值决定「模组刚写进去的区块最晚多久被看见」。原先是 1.0 秒硬 TTL，
        # 等于白送 1 秒延迟；纯降 TTL 又会让每帧读 16~32 次 JSON（0.29ms/次）。
        # 走 mtime 门控后，没变化时每帧只多一次 stat（~0.17ms），一旦模组重写了
        # index 文件就立刻重新解析 —— 既拿到接近 0 的延迟，又不为它付每帧的 IO。
        self.index_ttl = 0.05
        self._lock = threading.Lock()
        self._pending = set()
        # 逐 chunk 的解析结果缓存：safe -> {(cx,cz): (mtime, rgba16x16, mask16x16)}
        # 模组每轮只重写「内容变了」的 chunk，所以重建 region 时只有极少数文件需要
        # 真正解析 —— 其余直接复用上一次的 16x16 小块。这是跟得上跑图的关键：
        # 否则每秒都要把一屏几十个 region 的 3 万个文件重读一遍。
        self._ccache = OrderedDict()
        self._ccache_regions = 24
        self._saving = set()
        from concurrent.futures import ThreadPoolExecutor
        self._pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="memtile")

        # 统计
        self.last_build_ms = 0.0
        self.builds = 0
        self.hits = 0
        self.reused = 0

    # ------------------------------------------------------------ 元信息
    def _index(self, dim):
        """读 index_<safe>.json。先比 mtime，文件没动就不重新解析。"""
        did = self.dim_map.get(dim)
        if not did:
            return None
        safe = _safe(did)
        now = time.time()
        hit = self._idx.get(safe)
        if hit is not None and now - hit[0] < self.index_ttl:
            return hit[1]
        path = os.path.join(self.root, "index_%s.json" % safe)
        try:
            mt = os.stat(path).st_mtime_ns
        except OSError:
            mt = None
        if hit is not None and mt is not None and mt == hit[2]:
            # 文件一个字节都没动 —— 只把时间戳往后推，省掉 JSON 解析。
            self._idx[safe] = (now, hit[1], mt)
            return hit[1]
        data = None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            # 模组是**直接覆写**这个文件的，所以偶尔会正好读到写了一半的内容
            # （截断的 JSON -> ValueError）。这时必须**沿用上一次读到的值**，
            # 否则会把内存层误判成「该维度无数据」，整屏退回滞后的 Xaero 底图。
            data = hit[1] if hit is not None else None
        self._idx[safe] = (now, data, mt)
        return data

    def available(self, dim):
        """该维度是否已有内存层数据。"""
        idx = self._index(dim)
        return bool(idx and idx.get("regions"))

    def freshness(self, dim):
        """内存层最后一次更新的距今秒数；没有数据时返回 None。"""
        idx = self._index(dim)
        if not idx or not idx.get("t"):
            return None
        return max(0.0, time.time() - idx["t"] / 1000.0)

    def region_ver(self, dim, rx, rz):
        """该 region 的版本号；0 表示内存层没有这块。"""
        idx = self._index(dim)
        if not idx:
            return 0
        return int(idx.get("regions", {}).get("%d,%d" % (rx, rz), 0))

    def session(self, dim):
        """本次游戏会话号。版本号每局从 1 重新计数，缓存键必须带上会话号，
        否则重开游戏会命中上一局同号的缓存、显示旧地形。"""
        idx = self._index(dim)
        return int(idx.get("sid", 0)) if idx else 0

    def is_warm(self, dim, rx, rz):
        """该 region 的逐 chunk 小块是否还在缓存里。

        在 = 「之前建过，只是有几个 chunk 变了」→ 重建实测只要 40~50ms（1024 chunk
        的密集 region；冷建要 420ms）。只有这种情况才允许在 UI 线程就地做完。
        """
        did = self.dim_map.get(dim)
        if not did:
            return False
        # 这里不加锁：_ccache 本来就在 _chunk_tile / _build 里无锁访问（GIL 下单条
        # dict 操作是原子的），这里只是一次成员判断，加锁反而会和后台构建互相等。
        return _safe(did) in self._ccache

    def has_region(self, dim, rx, rz):
        return self.region_ver(dim, rx, rz) > 0

    def request(self, dim, rx, rz, zoom=1):
        """后台渲染该 region（按 版本+档位 去重，避免每帧重复排队）。"""
        key = (dim, rx, rz, zoom, self.region_ver(dim, rx, rz))
        with self._lock:
            if key in self._pending:
                return False
            self._pending.add(key)
        self._pool.submit(self._job, key, dim, rx, rz, zoom)
        return True

    def _job(self, key, dim, rx, rz, zoom):
        try:
            self.region_image(dim, rx, rz, zoom)
        except Exception:
            pass
        finally:
            with self._lock:
                self._pending.discard(key)

    # ------------------------------------------------------------ 渲染
    def _cache_path(self, safe, sid, rx, rz, zoom, ver):
        return os.path.join(self.cache_dir, safe,
                            "%d_%d@%d_s%d_v%d.png" % (rx, rz, zoom, sid, ver))

    def _to_disk(self, path, img, safe, rx, rz, zoom):
        """把 PNG 落盘放到后台，避免在 UI 线程里做 PNG 编码（一张 512x512 约 10~20ms）。"""
        with self._lock:
            if path in self._saving:
                return
            self._saving.add(path)
        self._pool.submit(self._save_job, path, img, rx, rz, zoom)

    def _save_job(self, path, img, rx, rz, zoom):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # 同一 region/档位的**旧会话 / 旧版本**文件删掉，避免无限累积
            d = os.path.dirname(path)
            pat = re.compile(r"^%d_%d@%d_s\d+_v\d+\.png$" % (rx, rz, zoom))
            for f in os.listdir(d):
                if pat.match(f) and f != os.path.basename(path):
                    try:
                        os.remove(os.path.join(d, f))
                    except OSError:
                        pass
            img.save(path)
        except (OSError, ValueError):
            pass
        finally:
            with self._lock:
                self._saving.discard(path)

    def _chunk_tile(self, safe, entry, cx, cz, cmap):
        """返回 (rgba16x16, mask16x16)；文件没变则直接复用缓存。

        关键：用 DirEntry.stat() 而不是 os.stat(path)。
        实测本机（Windows）单次 stat 约 170us、单次 open 约 180us，
        一个满铺 region 有 1024 个文件 —— 逐个 stat+open 要 350ms，
        整屏直接卡死。DirEntry.stat() 用的是 os.scandir 目录枚举时
        就已经拿到的 WIN32_FIND_DATA，不产生额外系统调用，几乎免费。
        """
        try:
            mtime = entry.stat().st_mtime_ns
        except OSError:
            return None, None
        cc = self._ccache.get(safe)
        if cc is None:
            cc = {}
            self._ccache[safe] = cc
            while len(self._ccache) > self._ccache_regions:
                self._ccache.popitem(last=False)
        else:
            self._ccache.move_to_end(safe)
        key = (cx, cz)
        hit = cc.get(key)
        if hit is not None and hit[0] == mtime:
            self.reused += 1
            return hit[1], hit[2]
        rec = parse_chunk(entry.path)
        if rec is None:
            cc[key] = (mtime, None, None)
            return None, None
        _cx, _cz, pal, _ys, idx = rec
        flat = idx.reshape(16, 16)
        sel = flat != EMPTY
        if not sel.any():
            cc[key] = (mtime, None, None)
            return None, None
        cols = np.empty((len(pal), 4), dtype=np.uint8)
        for i, nm in enumerate(pal):
            c = cmap.get(nm)
            if c is None:
                c = color_of(nm)
                cmap[nm] = c
            cols[i] = c
        rgba = cols[np.where(sel, flat, 0)]
        cc[key] = (mtime, rgba, sel)
        return rgba, sel

    def _build(self, safe, rx, rz):
        """把该 region 覆盖的 chunk 快照拼成 512x512 RGBA（未覆盖处透明）。"""
        d = os.path.join(self.chunks_root, safe, "r%d" % rx, "r%d" % rz)
        if not os.path.isdir(d):
            return None
        try:
            entries = list(os.scandir(d))
        except OSError:
            return None

        buf = np.zeros((REGION, REGION, 4), dtype=np.uint8)
        cmap = {}
        any_px = False
        for e in entries:
            if not e.name.endswith(".bin"):
                continue
            base = e.name[:-4]
            a, _, b = base.partition("_")
            try:
                cx, cz = int(a), int(b)
            except ValueError:
                continue
            bx = (cx - rx * REGION_CHUNKS) * 16
            bz = (cz - rz * REGION_CHUNKS) * 16
            if bx < 0 or bz < 0 or bx > REGION - 16 or bz > REGION - 16:
                continue
            rgba, sel = self._chunk_tile(safe, e, cx, cz, cmap)
            if rgba is None:
                continue
            sub = buf[bz:bz + 16, bx:bx + 16]
            sub[sel] = rgba[sel]
            any_px = True

        if not any_px:
            return None
        return Image.frombuffer("RGBA", (REGION, REGION), buf.tobytes(),
                                "raw", "RGBA", 0, 1)

    def stats(self):
        return {"mem": len(self._mem), "builds": self.builds, "hits": self.hits,
                "reused": self.reused, "last_build_ms": self.last_build_ms}

    def region_image(self, dim, rx, rz, zoom=1, allow_build=True):
        """渲染（或取缓存）某 region 的内存层图；无数据返回 None。

        allow_build=False 时**只查缓存**（内存 + 磁盘），不触发构建。
        构建一个 region 需要打开几百个快照文件，必须放到后台线程做，
        否则 UI 线程会卡住 —— 跑图时一卡就是好几百毫秒，比数据晚到更难受。
        """
        did = self.dim_map.get(dim)
        if not did:
            return None
        safe = _safe(did)
        ver = self.region_ver(dim, rx, rz)
        if ver <= 0:
            return None
        sid = self.session(dim)
        key = (safe, rx, rz, zoom, ver, sid)

        with self._lock:
            hit = self._mem.get(key)
            if hit is not None:
                self._mem.move_to_end(key)
                self.hits += 1
                return hit

        cp = self._cache_path(safe, sid, rx, rz, zoom, ver)
        img = None
        if os.path.exists(cp):
            try:
                img = Image.open(cp).convert("RGBA")
                img.load()
            except (OSError, ValueError):
                img = None
        if img is None:
            if not allow_build:
                return None
            t0 = time.perf_counter()
            full = self._build(safe, rx, rz)
            if full is None:
                return None
            n = tile_px(zoom)
            img = full if n == REGION else full.resize((n, n), Image.NEAREST)
            self.last_build_ms = (time.perf_counter() - t0) * 1000.0
            self.builds += 1
            self._to_disk(cp, img, safe, rx, rz, zoom)

        with self._lock:
            self._mem[key] = img
            while len(self._mem) > self._mem_limit:
                self._mem.popitem(last=False)
        return img


class CompositeStore:
    """把内存层（实时）叠在 Xaero 层（历史底图）之上。

    对外与 TileStore 同接口；当 mw == MEM_MW 时返回合成图：
    先铺 Xaero 的底图，再把内存层 alpha 合成上去（内存层未覆盖处透明）。
    """

    def __init__(self, xaero, mem, base_mw=None, mem_limit=128, max_workers=4):
        self.xaero = xaero
        self.mem = mem
        self.base_mw = base_mw or (lambda dim: None)   # dim -> 用作底图的子图名
        self._mem = OrderedDict()
        self._mem_limit = mem_limit
        self._lock = threading.Lock()
        from concurrent.futures import ThreadPoolExecutor
        self._pool = ThreadPoolExecutor(max_workers=max_workers,
                                        thread_name_prefix="compose")
        self.composed = 0
        # 「就地重建热 region」的令牌桶。
        # 热重建实测 40~50ms（只有几个 chunk 变了，其余走逐 chunk 缓存），完全可以
        # 在一帧里做完；这样数据**当帧**就出现，省掉「丢后台 -> 下一帧才画」的整整
        # 一帧。但不能无限制：玩家狂奔时可能一帧变好几片，全做就把帧时间堆起来了。
        # 限速成「每秒最多 5 片、最多攒 2 片」，保证再糟也就多花 ~100ms/秒。
        self.inline_ok = True
        self.inline_rate = 5.0
        self.inline_burst = 2.0
        self._inline_tokens = 2.0
        self._inline_last = time.monotonic()
        self.inline_ms = 0.0      # 累计花在就地重建上的毫秒（HUD/自检用）

    # ------------------------------------------------------------ 转发
    def dims(self):
        return self.xaero.dims()

    def dim_type(self, dim):
        return self.xaero.dim_type(dim)

    def region_dir(self, dim, mw):
        return self.xaero.region_dir(dim, mw)

    def last_activity(self, dim, mw):
        return self.xaero.last_activity(dim, mw)

    def scan_dir(self, dim, mw, ttl=None):
        """转发给底层的 Xaero 层（内存层自己不需要扫目录）。"""
        return self.xaero.scan_dir(dim, mw, ttl)

    def stats(self):
        s = self.xaero.stats()
        s["composed"] = self.composed
        s["mem"] = self.mem.stats()
        return s

    def region_path(self, dim, mw, rx, rz):
        if mw != MEM_MW:
            return self.xaero.region_path(dim, mw, rx, rz)
        if self.mem.has_region(dim, rx, rz):
            return "<mem:%s:%d,%d>" % (dim, rx, rz)
        base = self.base_mw(dim)
        return self.xaero.region_path(dim, base, rx, rz) if base else None

    # ------------------------------------------------------------ 取图
    def _take_inline(self):
        """令牌桶：允许就扣一个令牌并返回 True。"""
        now = time.monotonic()
        self._inline_tokens = min(
            self.inline_burst,
            self._inline_tokens + (now - self._inline_last) * self.inline_rate)
        self._inline_last = now
        if self._inline_tokens >= 1.0:
            self._inline_tokens -= 1.0
            return True
        return False

    def get(self, dim, mw, rx, rz, zoom=1, allow_build=False):
        if mw != MEM_MW:
            return self.xaero.get(dim, mw, rx, rz, zoom, allow_build=allow_build)

        ver = self.mem.region_ver(dim, rx, rz)
        sid = self.mem.session(dim)
        base = self.base_mw(dim)
        bver = None
        if base:
            try:
                bver = self.xaero.region_path(dim, base, rx, rz) is not None
            except Exception:
                bver = None

        key = (dim, rx, rz, zoom, ver, base, bver, sid)
        with self._lock:
            hit = self._mem.get(key)
            if hit is not None:
                self._mem.move_to_end(key)
                return hit

        under = None
        if base:
            under = self.xaero.get(dim, base, rx, rz, zoom, allow_build=allow_build)
        # 内存层只查缓存，不在这里构建：冷建要打开几百个快照文件（实测 420ms），
        # 放在 UI 线程会直接卡帧。缺的那一张交给后台池，下一帧自然出现。
        top = self.mem.region_image(dim, rx, rz, zoom, allow_build=allow_build)
        if top is None and self.mem.has_region(dim, rx, rz):
            # 例外：**热**重建（这个 region 之前建过，chunk 小块还在缓存里）只要
            # 40~50ms，就地做完能让数据**当帧**出现 —— 省掉一整帧。冷建绝不做。
            if (self.inline_ok and self.mem.is_warm(dim, rx, rz) and self._take_inline()):
                t0 = time.perf_counter()
                top = self.mem.region_image(dim, rx, rz, zoom, allow_build=True)
                self.inline_ms += (time.perf_counter() - t0) * 1000.0
            if top is None:
                self.mem.request(dim, rx, rz, zoom)

        if under is None and top is None:
            return None
        if top is None:
            img = under
        elif under is None:
            # 底图还没就绪：先只给内存层，且**不缓存**，等底图到位后再合成
            img = top
        else:
            img = under.copy()
            img.alpha_composite(top)
            self.composed += 1
        if under is not None and top is not None:
            with self._lock:
                self._mem[key] = img
                while len(self._mem) > self._mem_limit:
                    self._mem.popitem(last=False)
        return img

    def request(self, dim, mw, rx, rz, zoom=1):
        if mw != MEM_MW:
            return self.xaero.request(dim, mw, rx, rz, zoom)
        base = self.base_mw(dim)
        if base:
            self.xaero.request(dim, base, rx, rz, zoom)
        if self.mem.has_region(dim, rx, rz):
            self.mem.request(dim, rx, rz, zoom)
        return None

    def prewarm(self, dim, mw, cx, cz, size=None, zoom=1, margin=1):
        if mw != MEM_MW:
            return self.xaero.prewarm(dim, mw, cx, cz, size=size, zoom=zoom, margin=margin)
        base = self.base_mw(dim)
        if base:
            self.xaero.prewarm(dim, base, cx, cz, size=size, zoom=zoom, margin=margin)
        if not size:
            return None
        hx = (size[0] // 2 + 1) * zoom
        hz = (size[1] // 2 + 1) * zoom
        rx0 = int(cx - hx) // REGION - margin
        rx1 = int(cx + hx) // REGION + margin
        rz0 = int(cz - hz) // REGION - margin
        rz1 = int(cz + hz) // REGION + margin
        q = 0
        for rx in range(rx0, rx1 + 1):
            for rz in range(rz0, rz1 + 1):
                if self.mem.has_region(dim, rx, rz) and self.mem.request(dim, rx, rz, zoom):
                    q += 1
        return q
