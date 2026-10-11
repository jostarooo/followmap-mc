# -*- coding: utf-8 -*-
"""玩家坐标来源。

优先级：CoordBridge（游戏内小 mod，10Hz 精确） > 屏幕 OCR（小地图坐标文本） > 手动。
每个来源都产出统一的 Fix。
"""
import json
import os
import threading
import time
from dataclasses import dataclass

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)

HOME = os.path.expanduser("~")
# 坐标文件的目录跟 paths.coordbridge_home() 保持一致（认 COORDBRIDGE_HOME 环境变量），
# 否则「模组落盘目录被改过」时，遗迹识别读得到、坐标源却读不到，很难查。
try:
    from followmap.paths import coordbridge_home as _cb_home
    BRIDGE_PATH = os.path.join(_cb_home(), "coords.json")
except Exception:                                    # 极端情况（包结构被拆散）
    BRIDGE_PATH = os.path.join(HOME, ".coordbridge", "coords.json")


@dataclass
class Fix:
    ok: bool = False
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    dim: str = None          # minecraft:overworld 等（来自游戏）
    server: str = None
    ts: float = 0.0
    source: str = ""
    note: str = ""

    def as_xy(self):
        return (self.x, self.z)


# ---------------------------------------------------------------------------
class BaseSource:
    name = "base"

    def poll(self):
        raise NotImplementedError

    def close(self):
        pass


# ---------------------------------------------------------------------------
class BridgeSource(BaseSource):
    """读 CoordBridge 模组写出的 ~/.coordbridge/coords.json。"""
    name = "coordbridge"

    def __init__(self, path=BRIDGE_PATH, stale_after=3.0):
        self.path = path
        self.stale_after = stale_after
        self._mt = 0.0

    def available(self):
        return os.path.exists(self.path)

    def poll(self):
        f = Fix(source=self.name)
        if not os.path.exists(self.path):
            f.note = "未找到 %s（模组未安装或游戏未启动过）" % self.path
            return f
        try:
            st = os.stat(self.path)
            if st.st_mtime == self._mt:
                pass
            with open(self.path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception as e:
            f.note = "读取失败: %s" % e
            return f
        f.ts = time.time()
        if not d.get("in_game"):
            f.note = d.get("error") or "不在游戏中"
            return f
        now_ms = time.time() * 1000.0
        age = (now_ms - float(d.get("t", 0))) / 1000.0
        if age > self.stale_after:
            f.note = "数据过期 %.1fs（游戏可能已退出）" % age
            return f
        f.ok = True
        f.x = float(d.get("x", 0.0))
        f.y = float(d.get("y", 0.0))
        f.z = float(d.get("z", 0.0))
        f.dim = d.get("dim")
        f.server = d.get("server")
        f.note = "age=%.2fs" % age
        return f


# ---------------------------------------------------------------------------
class ManualSource(BaseSource):
    name = "manual"

    def __init__(self, x=0.0, z=0.0, dim=None):
        self.x, self.z, self.dim = float(x), float(z), dim
        self._lock = threading.Lock()

    def set(self, x=None, z=None, dim=None):
        with self._lock:
            if x is not None:
                self.x = float(x)
            if z is not None:
                self.z = float(z)
            if dim is not None:
                self.dim = dim

    def move(self, dx, dz):
        with self._lock:
            self.x += dx
            self.z += dz

    def poll(self):
        with self._lock:
            return Fix(True, self.x, 0.0, self.z, self.dim, None, time.time(),
                       self.name, "手动")


# ---------------------------------------------------------------------------
class DemoSource(BaseSource):
    """演示/自测：沿一条路径走，便于验证跟随是否流畅。"""
    name = "demo"

    def __init__(self, path, speed=40.0):
        self.path = path
        self.speed = speed
        self.t0 = time.time()
        self.dim = None

    def poll(self):
        segs = self.path
        if not segs:
            return Fix(source=self.name, note="无路径")
        lens = []
        total = 0.0
        for i in range(len(segs)):
            (x0, z0), (x1, z1) = segs[i], segs[(i + 1) % len(segs)]
            L = ((x1 - x0) ** 2 + (z1 - z0) ** 2) ** 0.5
            lens.append(L)
            total += L
        if total <= 0:
            return Fix(source=self.name, note="路径退化")
        s = ((time.time() - self.t0) * self.speed) % total
        acc = 0.0
        for i, L in enumerate(lens):
            if acc + L >= s:
                t = (s - acc) / max(1e-6, L)
                (x0, z0), (x1, z1) = segs[i], segs[(i + 1) % len(segs)]
                return Fix(True, x0 + (x1 - x0) * t, 64.0, z0 + (z1 - z0) * t,
                           self.dim, None, time.time(), self.name, "")
            acc += L
        return Fix(source=self.name, note="?")


# ---------------------------------------------------------------------------
class OcrSource(BaseSource):
    """截取游戏窗口 -> 在 ROI 里识别坐标文本。带锁定与多帧投票。"""
    name = "ocr"

    def __init__(self, roi=None, dim=None, interval=0.5, votes=2, max_jump=2000,
                 scan_full=True):
        from followmap.ocr import CoordOCR
        from followmap import win32cap
        self._cap = win32cap
        self._eng = CoordOCR()
        self.roi = roi                 # 相对客户区的 (l,t,r,b)，None=自动
        self.dim = dim
        self.interval = interval
        self.votes = votes
        self.max_jump = max_jump
        self.scan_full = scan_full
        self._hwnd = None
        self._cand = []                # 最近若干次读数
        self._last = None
        self._next = 0.0
        self._last_box = None
        self.note = ""

    def _find_window(self):
        ws = self._cap.find_mc()
        for w in ws:
            if w.get("client"):
                return w["hwnd"]
        return ws[0]["hwnd"] if ws else None

    def poll(self):
        f = Fix(source=self.name)
        now = time.time()
        if now < self._next:
            if self._last:
                self._last.ts = now
            return self._last or f
        self._next = now + self.interval

        if self._hwnd is None or not self._cap.user32.IsWindow(self._hwnd):
            self._hwnd = self._find_window()
        if self._hwnd is None:
            f.note = "找不到 Minecraft 窗口"
            return f
        img, err = self._cap.capture(self._hwnd)
        if img is None:
            f.note = err
            return f

        roi = self.roi
        if roi is None and self.scan_full:
            roi = self._auto_roi(img)
        r = self._eng.read(img, roi=roi)
        self._last_box = r.box
        if not r.ok:
            f.note = r.note or ("识别失败: %r" % r.text)
            return f

        nums = r.digits
        self._cand.append((nums, now))
        self._cand = self._cand[-max(2, self.votes):]
        # 多帧投票：最近 votes 次必须一致
        if len(self._cand) >= self.votes:
            recent = self._cand[-self.votes:]
            if all(c[0] == recent[0][0] for c in recent):
                nums = recent[0][0]
            else:
                f.note = "等待投票一致 (%s)" % (recent[-1][0],)
                return f
        else:
            f.note = "第 %d/%d 帧" % (len(self._cand), self.votes)
            return f

        if len(nums) == 3:
            x, y, z = nums
        elif len(nums) == 2:
            x, y, z = nums[0], 0, nums[1]
        else:
            f.note = "数字个数异常"
            return f
        if self._last and self._last.ok:
            jump = max(abs(x - self._last.x), abs(z - self._last.z))
            if jump > self.max_jump:
                f.note = "跳变过大 (%d)" % jump
                return f
        f.ok = True
        f.x, f.y, f.z = float(x), float(y), float(z)
        f.dim = self.dim
        f.note = "score=%.2f scale=%.2f" % (r.score, r.scale)
        self._last = f
        return f

    def _auto_roi(self, img):
        """在小地图可能出现的位置附近做一次全图扫描，锁定 ROI。"""
        if self._last_box:
            bx, by, bw, bh = self._last_box
            pad = 24
            return (max(0, bx - pad), max(0, by - pad),
                    min(img.width, bx + bw + pad), min(img.height, by + bh + pad))
        return None


# ---------------------------------------------------------------------------
class DimResolver:
    """把游戏给出的维度 id 解析成 Xaero 的 (dim 目录, mw 子目录)。

    服务器多世界时同一个 dimensionTypeId 会对应很多目录，用「region 文件最近写入时间」
    挑最可能的那个；解析结果带 TTL 缓存。
    """

    def __init__(self, store, ttl=20.0, cand_ttl=2.0):
        self.store = store
        self.ttl = ttl
        self.cand_ttl = cand_ttl
        self._cache = {}
        self._cand = {}
        self._pairs = None
        self._pairs_t = 0.0

    def _all_pairs(self):
        now = time.time()
        if self._pairs is not None and now - self._pairs_t < 60:
            return self._pairs
        out = []
        for dim, mws in self.store.dims():
            dt = self.store.dim_type(dim)
            for mw in mws:
                out.append((dim, mw, dt))
        self._pairs = out
        self._pairs_t = now
        return out

    def candidates(self, dim_type):
        """返回该维度下的所有 (活动时间, dim, mw, 文件数)，按最近写入降序。

        Xaero 有两种子目录：mw$default = 地表图；cm$N = 洞穴图（caveMaps 开启时）。
        最新写入的那个通常就是玩家当前所在的图。

        **必须带缓存**：地图每帧都调这里来回答「玩家现在在哪张子图」，而这个答案
        至多几分钟才变一次；算一遍却要对上百个候选目录各做一次目录扫描 + 逐文件
        stat —— 实测未缓存时单次 270ms（overworld），是全帧 310ms 的绝对大头。
        底图数据（Xaero）本身 60 秒才落一次盘，2 秒的缓存不会看漏任何东西。
        """
        now = time.time()
        hit = self._cand.get(dim_type)
        if hit is not None and now - hit[0] < self.cand_ttl:
            return hit[1]
        out = []
        for dim, mw, dt in self._all_pairs():
            if dt != dim_type:
                continue
            s, la = self.store.scan_dir(dim, mw)     # 一次扫描拿到「有没有」与「多新」
            if s:
                out.append((la, dim, mw, len(s)))
        out.sort(key=lambda t: -t[0])
        self._cand[dim_type] = (now, out)
        return out

    def resolve(self, dim_type, layer="auto"):
        """layer: 'auto' | 'surface'(mw) | 'cave'(cm)"""
        if not dim_type:
            return None
        key = (dim_type, layer)
        now = time.time()
        hit = self._cache.get(key)
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        cs = self.candidates(dim_type)
        if not cs:
            return None
        pick = None
        if layer == "surface":
            pick = next((c for c in cs if c[2].startswith("mw")), None)
        elif layer == "cave":
            pick = next((c for c in cs if c[2].startswith("cm")), None)
        if pick is None:
            pick = cs[0]
        res = (pick[1], pick[2])
        self._cache[key] = (now, res)
        return res


if __name__ == "__main__":
    import sys
    V = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14"
    sys.path.insert(0, APP)
    from followmap.store import TileStore
    st = TileStore(os.path.join(V, "XaeroWorldMap", "Multiplayer_mcfkcs.com"))
    dr = DimResolver(st)
    for dt in ["minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"]:
        print("%-24s -> %s" % (dt, dr.resolve(dt)))
    b = BridgeSource()
    print("bridge available:", b.available())
    print("bridge poll:", b.poll())
