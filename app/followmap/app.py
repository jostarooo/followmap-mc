# -*- coding: utf-8 -*-
"""方案 C 主体：第二屏「外部跟随地图」窗口。

设计目标：跑图时把一块无边框、置顶的小窗口钉在副屏上，每 250ms
以玩家为中心重绘 Xaero 的真实地图数据，不用手动拖官方地图。

坐标来源优先级（自动回退）：
    1) CoordBridge 模组  —— 读 ~/.coordbridge/coords.json（10Hz，精确，带维度）
    2) 屏幕 OCR          —— 截 Minecraft 窗口，模板匹配小地图坐标文本
    3) 手动 / Demo       —— 无游戏时用于验证与调试

用法：
    python followmap/app.py                      # GUI 跟随地图
    python followmap/app.py --selftest 40        # 无窗口自检（Demo 走一圈）
    python followmap/app.py --size 480 --interval 200 --layer surface
    python followmap/app.py --ruin-alert both    # 遗迹提醒：音+抖窗+闪任务栏（默认 auto=音+闪，不抖）
    python followmap/app.py --ruin-volume 1.6    # 水滴音再响一点（>1 走软削波）
    python followmap/app.py --no-ruin            # 关掉遗迹提醒
按键：
    Esc/q 退出   t 置顶开关   f 无边框开关   g 网格   h 帮助
    滚轮/z x 缩放            c 切换层(auto/surface/cave)
    n/p 手动切换维度+图      v 切换坐标源     d Demo 巡游
    r 切换遗迹提醒方式      左键拖动移动窗口

稀有遗迹提醒：只读模组**已经落盘**的区块文件（模组只在玩家真正加载的区块上写文件），
所以「文件新出现」天然等价于「这块地形刚进视距」——正好是「新加载的区块出现时再提醒」，
也天然不碰视距外。

提醒默认走「水滴音三连 + 任务栏闪烁 + 地图打点」，**不抖窗口**：
使用场景是笔记本屏挂机跑图、外接屏刷视频，眼睛在外接屏上，只有声音真正有效。
开局做完基线扫描后，如果发现了「这台机器从没报过」的遗迹（= 改判据前漏掉的那些），
会**合并报一声**，只报一次，之后就进历史库不再响。
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
if APP not in sys.path:
    sys.path.insert(0, APP)

from PIL import Image  # noqa: E402

from followmap import paths as P  # noqa: E402
from followmap import sources as S  # noqa: E402
from followmap.alerts import CYCLE as ALERT_CYCLE, MODES as ALERT_MODES, Alerter  # noqa: E402
from followmap.memstore import MEM_MW, CompositeStore, MemLayer, build_dim_map  # noqa: E402
from followmap.ruins import RuinWatcher  # noqa: E402
from followmap.store import REGION, ZOOMS, TileStore, nearest_zoom  # noqa: E402
from followmap.view import MapView  # noqa: E402

# Xaero 的服务器目录**不写死**：路径跟「装哪个启动器 / 整合包放哪」绑定，
# 写死就没法拷到别人电脑上用。定位顺序见 followmap/paths.py（命令行 > 环境变量 >
# server_path.txt > 模组 status.txt 记录的游戏目录 > 常见启动器位置 > 老默认位置 > 盘符扫描）。
# 这里只保留老路径当兜底常量（paths.resolve_server 找不到任何东西时才会用到它），
# 真正的解析在 parse_args 里做（懒执行，避免 import 模块时就扫盘）。
DEFAULT_SERVER = P.LEGACY_SERVER

# 主城附近的一条闭合巡游路径（DemoSource 自检用）。
# 取自 region(-14,25) 的实测数据范围 x[-7104,-6656] z[12800,13312]，覆盖率 65%。
DEMO_PATH = [(-7040, 12900), (-6720, 12900), (-6720, 13220), (-7040, 13220)]

LAYERS = ("auto", "surface", "cave")
SOURCES = ("auto", "bridge", "ocr", "manual", "demo")
MAP_MODES = ("auto", "mem", "xaero")

HELP = [
    "Esc/q 退出    t 置顶    f 无边框    g 网格    h 帮助",
    "滚轮上滚放大 / 下滚缩小（同 Xaero）    z x 同样",
    "档位 1px=1/2/4/8 格    c 层(auto/surface/cave)",
    "m 地图源(auto/mem/xaero)  v 换坐标源  d Demo巡游",
    "n p 换维度+图            左键拖动窗口",
    "+ - 缩放窗口（或 Ctrl+滚轮 / 右键拖右下角）  0 复位",
    "r 换遗迹提醒方式（auto=音+闪 / sound / both=加抖动 / flag / off）",
]

# 窗口缩放的边界。下界保证 HUD 还排得下，上界在运行时按屏幕尺寸再收一次。
MIN_W, MIN_H = 160, 120
RESIZE_FACTOR = 1.10          # 每次 +- 缩放的比例

# 遗迹提醒的轮询节奏：不用每帧查（帧 250ms），0.6s 一次足够；
# 每轮最多解析多少个新落盘区块（防止玩家高速飞行时单帧卡顿）。
RUIN_POLL_S = 0.6
RUIN_MAX_SCANS = 320


# ---------------------------------------------------------------------------
class FollowApp:
    """把「坐标源 -> 维度解析 -> 视口渲染」串成一条循环。与 Tk 解耦，便于自检。"""

    def __init__(self, args):
        self.args = args
        self.size = args.size
        self.launch_size = args.size       # `0` 键复位用
        self._screen = (1920, 1080)        # run() 里拿真实屏幕尺寸覆盖
        # 缩放语义：zoom = 每像素代表多少方块（值越大看得越远）。
        # 规整到 1/2/4/8 这几档，好让金字塔降采样严格等价于「直接按该档渲染」。
        self.zoom = nearest_zoom(args.zoom)
        self.layer = args.layer
        self.show_grid = not args.no_grid
        self.pin = (args.dim, args.mw) if (args.dim and args.mw) else None

        self.xaero = TileStore(args.server)
        self.resolver = S.DimResolver(self.xaero)

        # 内存直读层：mod 直读游戏内存里已加载区块的地表，落盘到 ~/.coordbridge/chunks。
        # 延迟 < 1 秒；而 Xaero 的地图落盘是硬编码 60 秒一次，所以「脚下这块地」用它才跟得上。
        # 它作为一层盖在 Xaero 底图之上，MapView 完全不用知道底下有几层。
        self.map_mode = getattr(args, "map", "auto")
        self.dim_map = {}          # Xaero 目录名 -> mod 维度 id（原地更新，MemLayer 共享引用）
        self._dim_map_t = 0.0
        self._base_cache = {}
        from concurrent.futures import ThreadPoolExecutor
        self._dim_bg = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dimmap")
        self._dim_job = None
        self.mem = MemLayer(dim_map=self.dim_map, mem_limit=96)
        self.store = CompositeStore(self.xaero, self.mem, base_mw=self._base_mw,
                                    mem_limit=64)
        self.store.inline_ok = not getattr(args, "no_inline", False)
        self.view = MapView(self.store)

        self.bridge = S.BridgeSource()
        self.manual = S.ManualSource(x=args.x, z=args.z)
        self.demo = S.DemoSource(DEMO_PATH, speed=args.demo_speed)
        self.demo.dim = None
        self.demo_pin = None
        self.ocr = None
        self.mode = args.source
        self.demo_on = (args.source == "demo")

        self.last_fix = S.Fix(note="尚未取得坐标")
        self.last_ok_fix = None
        self.source_name = "-"
        self.notes = []
        self.missing = 0
        self.prewarm_stat = {}
        self._mod_note = ""
        self._mod_note_t = 0.0
        self.poi = self._load_poi(args.poi)

        self._pair_list = None
        self._pair_idx = 0
        self._pair_t = 0.0
        self._fallback = ("null", "mw$default")
        self._last_dim = None      # 上次游戏报告的维度（变化时清掉候选图覆盖）
        self._auto_pick = None     # 「脚下真的没数据」时挑出来的更合适的候选图
        self._ridx = {}            # (dim,mw) -> (时间, region 坐标集合) 缓存
        self._empty = 0            # 连续「一张都没画出来」的帧数
        self.alt_note = ""
        self._dim = self._mw = None

        self.t0 = time.time()
        self.frames = 0
        self.fps = 0.0
        self.render_ms = 0.0

        # ---------------- 稀有遗迹提醒（巫师 / 武士 / 白金） ----------------
        # 只读模组**已经落盘**的区块文件，而模组只在玩家真正加载的区块上写文件，
        # 所以「文件新出现」天然等价于「这块地形刚进视距」—— 正好是需求要的
        # 「新加载的区块出现时再提醒」，也天然不碰视距外（合规红线）。
        self.tkroot = None
        self._ruin_iv = RUIN_POLL_S
        self._ruin_t = 0.0
        self._ruin_busy = False
        self._ruin_primed = False
        self._ruin_prime_hits = None   # 基线扫描的发现（历史库里没有的，合并报一声）
        self._ruin_note = ""
        self.ruin_lines = []          # 最近几条命中，给 HUD 用
        want_ruin = not getattr(args, "no_ruin", False)
        self.ruins = RuinWatcher() if want_ruin else None
        self.alerter = Alerter(getattr(args, "ruin_alert", "auto"), log=self._ruin_log,
                               volume=getattr(args, "ruin_volume", 1.5),
                               repeats=getattr(args, "ruin_repeat", 3))
        if self.ruins is not None and not self.ruins.enabled:
            self._ruin_note = self.ruins.sigs.error or "无指纹表"

    # ------------------------------------------------------------- POI
    @staticmethod
    def _load_poi(path):
        if not path or not os.path.exists(path):
            return []
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return []
        out = []
        for it in data if isinstance(data, list) else data.get("poi", []):
            try:
                out.append({"name": str(it.get("name", "?")),
                            "x": float(it["x"]), "z": float(it["z"]),
                            "dim": it.get("dim"), "mw": it.get("mw"),
                            "color": tuple(it["color"]) if it.get("color") else None})
            except Exception:
                continue
        return out

    def poi_for(self, dim, mw):
        out = []
        for p in self.poi:
            if p["dim"] and p["dim"] != dim:
                continue
            # 合成图（MEM_MW）里混着该维度的各子图，POI 不再按子图过滤
            if p["mw"] and mw != MEM_MW and p["mw"] != mw:
                continue
            out.append((p["name"], p["x"], p["z"], p["color"]))
        return out or None

    # ------------------------------------------------------- 遗迹提醒
    def _ruin_log(self, msg):
        self.ruin_lines = ([msg] + self.ruin_lines)[:8]
        # 界面无控制台，落盘留证
        try:
            d = os.path.join(APP, "out")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "ruin_alerts.log"), "a", encoding="utf-8") as fh:
                fh.write("%s  %s\n" % (time.strftime("%m-%d %H:%M:%S"), msg))
        except OSError:
            pass

    def _ruin_dims(self, fix):
        """要盯哪些维度。有坐标就只盯当前维度，省 io。"""
        return [fix.dim] if (fix is not None and fix.dim) else None

    def _ruin_prime(self, dims=None):
        """开局先做一次「基线扫描」，把已有区块的直方图读进来。

        **为什么不能一启动就把基线命中的遗迹全响一遍**：开局时地图上早就有那些遗迹了，
        需求是「新加载的区块出现时才提醒」，一次全响既不语义正确也很吵。所以：
          · 已经在本机历史库（out/found_ruins.json）里的 → 完全静默；
          · **历史库里没有的**（= 这台机器从没报过，比如改判据前漏掉的那些）→
            合并成**一条**提醒，只报一次，之后就进历史库不再响。
        第三条尤其重要：用户的目标是"别因为看视频错过重要遗迹"，
        漏检修复后第一次重启，应该把"以前漏掉的"告诉他，而不是默默标到地图上。

        另外两点：窗口判定要 5x5 区块，先把邻域读进来，后面新落的区块一进来就能立刻
        判对；必须覆盖**所有**维度（dims=None），不然玩家第一趟跑末地时那一万多个文件
        会落到主线程上、卡十几秒。所以丢后台线程。
        """
        import threading

        def work():
            try:
                self._ruin_prime_hits = self.ruins.poll(dims, max_scans=10 ** 9)
            except Exception as e:
                self._ruin_note = "遗迹基线扫描失败: %s" % e
            finally:
                self._ruin_primed = True
                self._ruin_busy = False

        self._ruin_busy = True
        threading.Thread(target=work, name="ruin-prime", daemon=True).start()

    def _ruin_tick(self, fix):
        """每 RUIN_POLL_S 扫一轮新落盘的区块，命中就提醒。"""
        if self.ruins is None or not self.ruins.enabled:
            return
        now = time.time()
        if self._ruin_busy:
            return
        dims = self._ruin_dims(fix)
        if not self._ruin_primed:
            if now - self._ruin_t < 1.0:
                return
            self._ruin_t = now
            self._ruin_prime(None)
            return
        if self._ruin_baseline():
            self._ruin_t = now
            return
        if now - self._ruin_t < self._ruin_iv:
            return
        self._ruin_t = now
        try:
            hits = self.ruins.poll(dims, max_scans=RUIN_MAX_SCANS)
        except Exception as e:
            self._ruin_note = "遗迹扫描失败: %s" % e
            return
        for h in hits:
            self.alerter.notify(h, self.tkroot)

    def _ruin_baseline(self):
        """把基线扫描「历史库里没见过」的发现合并报一声，只报一次。"""
        pend = getattr(self, "_ruin_prime_hits", None)
        if not pend:
            if pend is not None:
                self._ruin_prime_hits = []
            return False
        self._ruin_prime_hits = []
        order = list(self.ruins.sigs.types)
        pick = sorted(pend, key=lambda h: order.index(h["type"])
                      if h.get("type") in order else 99)[0]
        if len(pend) > 1:
            self._ruin_log("基线补报：本机从没记录过的遗迹 %d 处（%s 等），已全部打到地图上"
                           % (len(pend), pick["type"]))
        self.alerter.notify(pick, self.tkroot)
        return True

    def _xaero_dim_of(self, mod_dim):
        """mod 维度 id -> Xaero 目录名。

        三级消歧，因为本服有 20+ 个 dimensionTypeId 都是 minecraft:the_end 的目录
        （hard/easy/训练场…），只按名字猜会投到错的图上。**按可信度从高到低**：

          2) **用模组自己的 region 坐标**去比对：模组 index 里记着它扫过哪些
             region（与世界方块坐标系一致），哪个 Xaero 图里真的存在这些 region，
             哪个就是同一个世界。实测本机 `DIM1/cm$1` 与模组 239 个 region 里
             重合 235 个，其余三个候选都是 0 —— 结论唯一。不需要游戏在线。
          1) dim_map：用玩家坐标算出来的映射；
          0) 才按维度类型名解析。

        缓存必须带可信度：地图每帧都会调这里，而**基线扫描完成前** ruins.dims 还是
        空的，那时只能给出低可信度答案；如果就这么缓存住，等精确答案可用了也换不回来
        （实测：先缓存了 minecraft$easy_the_end，遗迹 POI 被全部过滤掉，一个都不显示）。
        """
        self._xd_cache = getattr(self, "_xd_cache", {})
        hit = self._xd_cache.get(mod_dim)
        if hit and hit[1] >= 2:
            return hit[0]
        d, conf = None, -1
        # 1) 模组 region 坐标比对（精确）
        if self.ruins is not None:
            st = self.ruins.dims.get(mod_dim)
            regs = []
            for key in (st or {}).get("regions") or {}:
                try:
                    a, b = key.split(",")
                    regs.append((int(a), int(b)))
                except ValueError:
                    pass
            if regs:
                try:
                    best, bs = None, 0
                    for c in self.resolver.candidates(mod_dim):
                        s = self._region_index(c[1], c[2])
                        n = sum(1 for rc in regs if rc in s)
                        if n > bs:
                            best, bs = c[1], n
                    if best:
                        d, conf = best, 2
                except Exception:
                    pass
        if d is None:
            d = self._real_dim_for(mod_dim)          # 2) 玩家坐标映射
            conf = 1 if d else -1
        if d is None:
            try:
                r = self.resolver.resolve(mod_dim, "surface")
                d = r[0] if r else None              # 3) 按名猜
                conf = 0 if d else -1
            except Exception:
                d = None
        if d:
            self._xd_cache[mod_dim] = (d, conf)       # 只在可信度升高时覆盖
        return d

    def _ruin_pois(self, dim):
        """把已发现的遗迹投到地图上（永久打点，事后可回看）。

        维度映射按维度批量算一次，不要每条 POI 都去翻 dim_map（每帧都调用）。
        **可信度优先**：`_xaero_dim_of` 给出的是"精确"答案（置信度 2）时就用它，
        不再叠加 dim_map 那份玩家坐标启发式 —— 否则会把遗迹投到同名的别的世界上
        （实测：dim_map 说 minecraft$easy_the_end、精确答案是 DIM1，
        只看 dim_map 的话遗迹一个都不显示）。
        """
        out = []
        if self.ruins is None or not self.ruins.found:
            return out
        cache = getattr(self, "_ruin_dimcache", None)
        if cache is None or time.time() - cache[0] > 10:
            m = {}
            for d, i in self.dim_map.items():
                m.setdefault(i, set()).add(d)
            cache = self._ruin_dimcache = (time.time(), m)
        mp = cache[1]
        xdc = getattr(self, "_xd_cache", {})
        f = self.last_fix
        cur = f.dim if (f is not None and f.ok) else None
        for it in self.ruins.found[-300:]:
            md = it.get("dim")
            xd = self._xaero_dim_of(md)
            conf = (xdc.get(md) or (None, -1))[1]
            if conf >= 2:
                ds = {xd} if xd else set()
            else:
                ds = set(mp.get(md) or ())
                if xd:
                    ds.add(xd)
            if dim not in ds and md != cur:
                continue          # 映射还没建好时，至少「当前维度」能对上
            out.append(("%s%s" % (it.get("icon", ""), it.get("type", "遗迹")),
                        it.get("x", 0), it.get("z", 0), it.get("color")))
        return out

    def _ruin_help(self):
        if self.ruins is None:
            return "遗迹提醒：已关闭（--no-ruin）"
        if not self.ruins.enabled:
            return "遗迹提醒不可用：%s" % (self._ruin_note or "无指纹表")
        if not self._ruin_primed:
            return "遗迹提醒：建立基线中…"
        return "%s  %s" % (self.ruins.status(), self.alerter.status())

    def cycle_alert(self):
        self.alerter.mode = ALERT_CYCLE[
            (ALERT_CYCLE.index(self.alerter.mode) + 1) % len(ALERT_CYCLE)] \
            if self.alerter.mode in ALERT_CYCLE else ALERT_CYCLE[0]
        self._ruin_log("提醒方式 -> %s（%s）" % (self.alerter.mode, self.alerter.status()))

    # ------------------------------------------------------------- 坐标源
    def _pump(self):
        self.notes = []
        m = self.mode
        if self.demo_on:
            m = "demo"

        if m in ("auto", "bridge"):
            f = self.bridge.poll()
            if f.ok:
                self.source_name = "bridge"
                return f
            self.notes.append("bridge: %s" % (f.note or "不可用"))
            if m == "bridge":
                return f

        if m in ("auto", "ocr"):
            if self.ocr is None:
                self.ocr = S.OcrSource(dim=None,
                                       interval=max(0.2, self.args.interval / 1000.0),
                                       votes=self.args.votes)
            f = self.ocr.poll()
            if f.ok:
                self.source_name = "ocr"
                return f
            self.notes.append("ocr: %s" % (f.note or "不可用"))
            if m == "ocr":
                return f

        if m in ("manual", "demo"):
            return self.demo.poll() if m == "demo" else self.manual.poll()

        # auto 且三条外部来源全挂 —— 冻结在最后一次有效位置
        if self.last_ok_fix is not None:
            f = S.Fix(**vars(self.last_ok_fix))
            f.note = "冻结(%s)" % (self.notes[0] if self.notes else "无信号")
            return f
        return S.Fix(note="；".join(self.notes) or "无可用坐标源")

    # ------------------------------------------------------------- 维度
    def _pairs(self):
        """所有 (维度, 子图) 按最近活动排序。

        TTL 从 15s 放到 60s、并且改用 store.scan_dir（一次扫描同时拿到「有几个
        region」与「多新」）：这段原先要 42ms 列维度 + 每个目录各一次 listdir +
        一次逐文件 stat 的 last_activity，实测整套 366ms，而它**挂在渲染路径上**，
        所以每 15 秒就卡一帧。它只用来兜底挑「最近活动的那张图」，60 秒的滞后
        完全够用（Xaero 自己 60 秒才落一次盘）。
        """
        now = time.time()
        if self._pair_list is not None and now - self._pair_t < 60:
            return self._pair_list
        out = []
        for dim, mws in self.store.dims():
            for mw in mws:
                s, la = self.store.scan_dir(dim, mw)
                if s:
                    out.append((la, dim, mw, len(s)))
        out.sort(key=lambda t: -t[0])
        self._pair_list = out
        self._pair_t = now
        if out:
            # 默认回退：取最近活动的图。
            # 注意**不能**只挑 "mw*"：本服有 20+ 个同类型世界（训练场/资源世界…），
            # 它们的 mw$default 可能比玩家真正所在世界的 mw$default 更新。
            self._fallback = (out[0][1], out[0][2])
        return out

    # ------------------------------------------------- 内存直读层
    def _refresh_dim_map(self, cx, cz, ttl=30.0):
        """刷新「Xaero 目录名 <-> mod 维度 id」映射。

        要点：
        - 必须带玩家坐标：本服有 20+ 个 dimensionTypeId 都是 minecraft:overworld 的目录
          （训练场/资源世界/剧情世界…），只有「玩家脚下真的落在里面」的那个才是当前世界。
        - 要扫描上百个目录，耗时几百毫秒，所以丢后台线程，刷新期间继续用旧映射。
        """
        now = time.time()
        if self.dim_map and now - self._dim_map_t < ttl:
            return
        if self._dim_job is not None and not self._dim_job.done():
            return
        self._dim_map_t = now
        self._dim_job = self._dim_bg.submit(build_dim_map, self.xaero, cx, cz)
        self._dim_job.add_done_callback(self._dim_map_done)

    def _dim_map_done(self, fut):
        try:
            m = fut.result()
        except Exception:
            return
        if m:
            self.dim_map.clear()
            self.dim_map.update(m)

    def _mem_ready(self, dim):
        """该 Xaero 维度目录是否有内存直读数据可用。"""
        f = self.last_fix
        if f is not None and f.ok:
            cx, cz = f.x, f.z
        elif self.last_ok_fix is not None:
            cx, cz = self.last_ok_fix.x, self.last_ok_fix.z
        else:
            cx, cz = 0.0, 0.0
        self._refresh_dim_map(cx, cz, 10.0 if self.map_mode == "mem" else 30.0)
        if dim not in self.dim_map:
            return False
        if self.map_mode == "mem":
            return True
        return self.mem.available(dim)

    def _mod_status(self, ttl=5.0):
        """读一次模组自检（~/.coordbridge/scan_status.txt），5 秒缓存。

        为什么值得放进 HUD：这个模组最坑的失效方式是**静默**的 —— 反射解析错了
        不崩游戏、不报错，只是永远不写数据。HUD 上直接把模组的自检结论摊开，
        就不用再去猜「到底是没数据还是地图没叠上」。
        """
        now = time.time()
        if self._mod_note_t and now - self._mod_note_t < ttl:
            return self._mod_note
        self._mod_note_t = now
        note = ""
        try:
            p = os.path.join(os.path.expanduser("~"), ".coordbridge", "scan_status.txt")
            with open(p, encoding="utf-8", errors="ignore") as fh:
                txt = fh.read()
            if "state        : FAIL" in txt:
                err = ""
                for line in txt.splitlines():
                    if line.startswith("state        : FAIL"):
                        err = line.split("FAIL", 1)[1].strip()
                note = "模组反射失败: %s" % err[:38]
            elif "[miss]" in txt or "[bad sig]" in txt:
                note = "模组名字表不匹配（跑 modmap.py --check）"
            else:
                for line in txt.splitlines():
                    if line.startswith("full sweep"):
                        note = line.replace("full sweep   : ", "扫描整轮 ")
                        break
        except OSError:
            note = ""
        self._mod_note = note
        return note

    def _real_dim_for(self, dim_id):
        """mod 的维度 id -> 当前真实所在的 Xaero 目录名。

        dim_map 是用玩家坐标算出来的，所以它比「最近活动」更可信：
        同一个 minecraft:overworld 在本服对应 20+ 个目录。
        """
        for d, i in self.dim_map.items():
            if i == dim_id:
                return d
        return None

    def _base_mw(self, dim):
        """该维度目录下用来打底的子图（取最近活动的那个）。"""
        now = time.time()
        hit = self._base_cache.get(dim)
        if hit and now - hit[0] < 30:
            return hit[1]
        mw = None
        for _la, d, m, _n in self._pairs():     # 已按最后写入时间降序
            if d == dim:
                mw = m
                break
        self._base_cache[dim] = (now, mw)
        return mw

    def _resolve(self, fix):
        """最终决定 (dim, mw)。

        auto/mem 模式下，只要该维度有内存直读数据，就用合成图
        （内存层盖在 Xaero 底图上）—— 这是唯一能跟上跑图速度的图层；
        Xaero 自己的落盘是硬编码 60 秒一次，单靠它会一直滞后。
        洞穴层（cm$*）不叠加：内存层存的是每列地表方块。
        """
        dim, mw = self._resolve_xaero(fix)
        if self.pin or self.map_mode == "xaero" or self.layer == "cave":
            return dim, mw
        # 多世界服务器上 Xaero 的「最近活动」会落到别的同类型世界（训练场/资源世界），
        # 用坐标消歧出来的映射把 dim 纠正过来，否则底图和内存层会对不上。
        if fix.dim:
            real = self._real_dim_for(fix.dim)
            if real and real != dim:
                dim = real
                mw = self._base_mw(dim) or mw
        if not self._mem_ready(dim):
            return dim, mw
        return dim, MEM_MW

    def _resolve_xaero(self, fix):
        self._pairs()          # 保证 _fallback 已就绪（内部 15s 缓存）
        # 0) 手动锁定（n/p 切换或 --dim/--mw）优先级最高
        if self.pin:
            return self.pin
        # 1) 游戏给出的维度 id -> 目录（bridge 路径走这里）
        if fix.dim:
            if fix.dim != self._last_dim:
                self._last_dim = fix.dim
                self._auto_pick = None     # 换维度了，之前挑的候选作废
                self._empty = 0
            cs = self.resolver.candidates(fix.dim)
            if self.layer == "surface":
                cs = [c for c in cs if c[2].startswith("mw")] or cs
            elif self.layer == "cave":
                cs = [c for c in cs if c[2].startswith("cm")] or cs
            if cs:
                # _auto_pick 是「脚下真的没数据」时挑出来的更合适的候选图
                if self._auto_pick:
                    for c in cs:
                        if (c[1], c[2]) == self._auto_pick:
                            return self._auto_pick
                    self._auto_pick = None
                c = cs[0]                  # 缺省：最近写入的那个
                return (c[1], c[2])
            r = self.resolver.resolve(fix.dim, self.layer)
            if r:
                return r
        # 2) Demo 巡游固定看主城地表（没有就退到最近活动的地表图）
        if self.demo_on:
            if self.demo_pin is None:
                c = ("null", "mw$default")
                d = self.store.region_dir(*c)
                has = False
                if os.path.isdir(d):
                    try:
                        has = any(f.endswith(".zip") for f in os.listdir(d))
                    except OSError:
                        has = False
                self.demo_pin = c if has else self._fallback
            return self.demo_pin
        # 3) 完全没有维度信息（纯 OCR / 手动）：按 layer 偏好挑，缺省地表图
        ps = self._pairs()
        if not ps:
            return self._fallback
        if self.layer == "cave":
            hit = next((p for p in ps if p[2].startswith("cm")), None)
            return (hit[1], hit[2]) if hit else self._fallback
        if self.layer == "surface":
            return self._fallback
        # auto 且无维度信息：用地表图（洞穴图只在明确需要时才看）
        return self._fallback

    # ------------------------------------------------- 候选图选择（脚下有无数据）
    def _region_index(self, dim, mw):
        """该目录里所有已存在的 region 坐标集合，30s 缓存。"""
        key = (dim, mw)
        now = time.time()
        hit = self._ridx.get(key)
        if hit and now - hit[0] < 30:
            return hit[1]
        s = set()
        d = self.store.region_dir(dim, mw)
        if os.path.isdir(d):
            try:
                for f in os.listdir(d):
                    if f.endswith(".zip"):
                        try:
                            a, b = f[:-4].split("_")
                            s.add((int(a), int(b)))
                        except ValueError:
                            pass
            except OSError:
                pass
        self._ridx[key] = (now, s)
        return s

    def _near(self, dim, mw, rx, rz, radius=4):
        """玩家所在 region 到该图最近 region 的切比雪夫距离；没找到返回 99。"""
        s = self._region_index(dim, mw)
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

    def _note_empty(self):
        """连续多帧「一张都没画出来」时，去候选图里找脚下真有数据的那个。

        注意区分两种情况：
          - 图层选错了 -> 换个候选图就有数据（这里处理）
          - 玩家走进了 Xaero 还没记录的新区域 -> 任何候选图都没有数据，
            这时候**不该**乱换图（换了只会更迷惑），保持原样并显示提示。
        """
        if self.pin or not self.last_fix.dim:
            return
        self._empty += 1
        if self._empty < 8:
            return
        self._empty = 0
        f = self.last_fix
        rx, rz = int(f.x) // REGION, int(f.z) // REGION
        cs = self.resolver.candidates(f.dim)
        if self.layer == "surface":
            cs = [c for c in cs if c[2].startswith("mw")] or cs
        elif self.layer == "cave":
            cs = [c for c in cs if c[2].startswith("cm")] or cs
        scored = []
        for la, dim, mw, n in cs:
            scored.append((self._near(dim, mw, rx, rz), la, dim, mw))
        if not scored:
            return
        scored.sort(key=lambda t: (t[0], -t[1]))
        best = scored[0]
        cur = (self._dim, self._mw)
        if best[3] is None:
            return
        if best[0] == 0 and (best[2], best[3]) != cur:
            self._auto_pick = (best[2], best[3])
            self.alt_note = "脚下无数据，已切到 %s/%s" % (best[2], best[3])
        elif best[0] >= 99:
            self._auto_pick = None
            self.alt_note = "此处 Xaero 尚未记录（继续走会补上）"
        else:
            self.alt_note = ""

    def cycle_pair(self, delta):
        ps = self._pairs()
        if not ps:
            return
        self._pair_idx = (self._pair_idx + delta) % len(ps)
        self.pin = (ps[self._pair_idx][1], ps[self._pair_idx][2])

    # ------------------------------------------------------------- 缩放
    def _zoom_step(self, direction):
        """direction=+1 放大（看得更清），-1 缩小（看得更远）。

        注意本项目 zoom 的语义是「每像素代表多少方块」，所以**放大是让 zoom 变小**。
        Xaero 地图里滚轮上滚 = 放大，所以滚轮上滚必须映射到 direction=+1，
        否则方向就是反的（这正是之前的问题）。
        """
        i = ZOOMS.index(self.zoom) if self.zoom in ZOOMS else 0
        self.zoom = ZOOMS[max(0, min(len(ZOOMS) - 1, i - direction))]

    def view_span(self):
        """当前视线覆盖的世界方块宽度（用于判断能否追上跑图）。"""
        return self.size[0] * self.zoom

    # --------------------------------------------------------- 窗口缩放
    def clamp_size(self, w, h):
        """把窗口尺寸夹到合法范围（下界保证 HUD 排得下，上界贴屏幕）。

        单独抽出来是为了能在 --selftest 里无窗口验证，不必真开 GUI。
        """
        sw, sh = self._screen
        w = int(max(MIN_W, min(int(w), max(MIN_W, int(sw * 0.98)))))
        h = int(max(MIN_H, min(int(h), max(MIN_H, int(sh * 0.98)))))
        return w, h

    def size_step(self, direction):
        """算出缩放一步之后的尺寸（**不改状态**，便于无窗口测试）。"""
        w, h = self.size
        f = RESIZE_FACTOR if direction > 0 else (1.0 / RESIZE_FACTOR)
        return self.clamp_size(round(w * f), round(h * f))

    # ------------------------------------------------------------- 渲染
    def _hud(self, fix, dim, mw):
        lines = []
        lines.append(("%s / %s" % (dim, mw), (255, 214, 120, 255)))
        if fix.ok:
            lines.append(("X %.1f  Y %.1f  Z %.1f" % (fix.x, fix.y, fix.z),
                          (240, 240, 250, 255)))
        else:
            lines.append(("坐标不可用", (255, 150, 150, 255)))
        # 显示「视野覆盖多少格」比显示 zoom 数值更直观：跑图时你关心的就是看得够不够远
        lines.append(("视野%d格  %s  miss%d  %.0fms" %
                      (self.view_span(), self.source_name, self.missing, self.render_ms),
                      (200, 205, 220, 255)))
        if mw == MEM_MW:
            fr = self.mem.freshness(dim)
            st = self.mem.stats()
            lines.append(("内存直读 延迟%.1fs 建图%d 上次%.0fms" %
                          (fr if fr is not None else -1.0, st["builds"],
                           st["last_build_ms"]),
                          (140, 230, 180, 255)))
        elif self.map_mode != "xaero":
            why = ("洞穴层不叠加" if self.layer == "cave"
                   else "该维度无内存数据" if not self._mem_ready(dim)
                   else "已关闭")
            lines.append(("内存层未启用：%s" % why, (200, 190, 150, 255)))
            note = self._mod_status()
            if note:
                lines.append((note[:46], (255, 170, 140, 255)))
        note = fix.note or ""
        if note:
            lines.append((note[:46], (190, 200, 170, 255)))
        if self.alt_note:
            lines.append((self.alt_note[:46], (255, 200, 130, 255)))
        # 遗迹提醒：最近一条命中放大显示（音效/抖动响了之后，这里告诉你"是哪个、在哪"）
        if self.ruins is not None and self.ruins.enabled:
            if self.ruin_lines:
                lines.append((self.ruin_lines[0][:46], (255, 236, 150, 255)))
                if len(self.ruin_lines) > 1:
                    lines.append(("(%d 条提醒，见 out/ruin_alerts.log)"
                                  % len(self.ruin_lines), (210, 200, 160, 255)))
            else:
                lines.append((self._ruin_help()[:46], (170, 200, 180, 255)))
            n = len(self.ruins.found)
            if n:
                lines.append(("已记录遗迹 %d 处  方式 %s"
                              % (n, self.alerter.mode), (200, 205, 180, 255)))
        elif self.ruins is not None:
            lines.append((self._ruin_help()[:46], (200, 180, 160, 255)))
        if not self.last_ok_fix:
            for i, s in enumerate(self.notes[:2]):
                lines.append((s[:46], (200, 170, 170, 255)))
        if self.args.show_help or getattr(self, "_help", False):
            for s in HELP:
                lines.append((s, (170, 190, 230, 255)))
        return lines

    def _render(self, fix):
        dim, mw = self._resolve(fix)
        cx = fix.x if fix.ok else (self.last_ok_fix.x if self.last_ok_fix else 0)
        cz = fix.z if fix.ok else (self.last_ok_fix.z if self.last_ok_fix else 0)
        t0 = time.perf_counter()
        poi = self.poi_for(dim, mw)
        ruin_poi = self._ruin_pois(dim)
        if ruin_poi:
            poi = (poi or []) + ruin_poi      # 已发现的遗迹和普通 POI 一起投点
        img, miss = self.view.render(dim, mw, cx, cz, size=self.size, zoom=self.zoom,
                                     poi=poi,
                                     hud_lines=self._hud(fix, dim, mw),
                                     show_grid=self.show_grid)
        self.render_ms = (time.perf_counter() - t0) * 1000.0
        self.missing = miss
        self._prewarm(dim, mw, cx, cz)
        return img, dim, mw

    def _prewarm(self, dim, mw, cx, cz):
        """每帧都预取整个视口 + 一圈余量。

        老做法是「等到缺瓦片才补」，玩家跑到哪才有哪，永远慢一步。改成无条件
        覆盖整个视口后，地图是在玩家到达之前就长好的。
        """
        if self.args.no_prewarm:
            self.prewarm_stat = {}
            return
        try:
            self.prewarm_stat = self.store.prewarm(
                dim, mw, cx, cz, size=self.size, zoom=self.zoom, margin=1)
        except Exception:
            self.prewarm_stat = {}

    # ------------------------------------------------------------- 单帧
    def step(self, frame_dt):
        fix = self._pump()
        if fix.ok:
            self.last_ok_fix = fix
        self.last_fix = fix
        img, dim, mw = self._render(fix)
        self._dim, self._mw = dim, mw
        # 一张都没拼上：可能图层选错，也可能玩家走进了没记录的区域
        if self.view.last_drawn == 0 and self.missing == 0:
            self._note_empty()
        else:
            self._empty = 0
        self.frames += 1
        el = max(1e-6, time.time() - self.t0)
        self.fps = self.frames / el
        self._dim, self._mw = dim, mw
        # 遗迹提醒：独立节流，比渲染慢；命中会"响 + 抖地图窗口 + 闪任务栏 + 打点"
        self._ruin_tick(fix)
        return img, fix

    # ============================================================= GUI
    def run(self):
        import tkinter as tk
        from PIL import ImageTk

        root = tk.Tk()
        root.title("跟随地图")
        self.tkroot = root          # 遗迹提醒要抖这个窗口、闪任务栏
        try:
            self._screen = (root.winfo_screenwidth(), root.winfo_screenheight())
        except Exception:
            pass
        self._frameless = not self.args.border
        self._top = not self.args.no_top
        if self._frameless:
            root.overrideredirect(True)
        root.attributes("-topmost", self._top)
        root.geometry("%dx%d+%d+%d" % (self.size[0], self.size[1], self.args.wx, self.args.wy))
        root.configure(bg="#0e0e12")

        canvas = tk.Canvas(root, width=self.size[0], height=self.size[1],
                           highlightthickness=0, bg="#0e0e12")
        canvas.pack(fill="both", expand=True)
        self._img_id = canvas.create_image(0, 0, anchor="nw")
        self._tkimg = None

        def on_tick():
            img, fix = self.step(self.args.interval / 1000.0)
            self._tkimg = ImageTk.PhotoImage(img)
            canvas.itemconfigure(self._img_id, image=self._tkimg)
            root.after(self.args.interval, on_tick)

        # ---- 交互
        st = {"x": 0, "y": 0, "rw": 0, "rh": 0, "rx": 0, "ry": 0}

        # 右下角那个小折角，提示「这里可以拖大小」。画在图片之上，不参与渲染。
        grip = canvas.create_line(0, 0, 0, 0, tags="grip")
        grip2 = canvas.create_line(0, 0, 0, 0, tags="grip")
        for it in (grip, grip2):
            canvas.itemconfigure(it, fill="#7a8090", width=2)

        def draw_grip():
            w, h = self.size
            canvas.coords(grip, w - 14, h - 4, w - 4, h - 14)
            canvas.coords(grip2, w - 8, h - 4, w - 4, h - 8)

        def apply_size(w, h):
            """改窗口尺寸。**只改尺寸、不动位置**（位置由左键拖动负责）。"""
            w, h = self.clamp_size(w, h)
            if (w, h) == self.size:
                return False
            self.size = (w, h)
            canvas.configure(width=w, height=h)
            root.geometry("%dx%d+%d+%d" % (w, h, root.winfo_x(), root.winfo_y()))
            draw_grip()
            return True

        def resize_step(direction):
            return apply_size(*self.size_step(direction))

        draw_grip()

        def press(e):
            st["x"], st["y"] = e.x_root, e.y_root

        def drag(e):
            if self._frameless:
                root.geometry("+%d+%d" % (root.winfo_x() + e.x_root - st["x"],
                                          root.winfo_y() + e.y_root - st["y"]))
                st["x"], st["y"] = e.x_root, e.y_root

        # 右键拖动 = 缩放窗口（锚在左上角，所以窗口不动、只是右下角跟着走）。
        # 为什么不复用左键：左键已经用来移动窗口了，两者共存会让拖动变玄学。
        def press3(e):
            st["rx"], st["ry"] = e.x_root, e.y_root
            st["rw"], st["rh"] = self.size

        def drag3(e):
            apply_size(st["rw"] + (e.x_root - st["rx"]),
                       st["rh"] + (e.y_root - st["ry"]))

        def wheel(e):
            # Ctrl+滚轮 = 缩放窗口；不带修饰键 = 缩放地图（同 Xaero）。
            if e.state & 0x0004:
                resize_step(1 if e.delta > 0 else -1)
            else:
                # 上滚 = 放大（跟 Xaero 地图一致）。注意本项目 zoom 越大看得越远，
                # 所以「放大」要传 +1 让 zoom 变小，而不是直接加 zoom。
                self._zoom_step(1 if e.delta > 0 else -1)

        def wheel_btn(e, direction):
            # 部分平台走 Button-4/5 而不是 MouseWheel
            if getattr(e, "state", 0) & 0x0004:
                resize_step(direction)
            else:
                self._zoom_step(direction)

        def key(name):
            def h(e=None):
                if name in ("quit",):
                    root.destroy()
                elif name == "top":
                    self._top = not self._top
                    root.attributes("-topmost", self._top)
                elif name == "frame":
                    self._frameless = not self._frameless
                    root.overrideredirect(self._frameless)
                    root.attributes("-topmost", self._top)
                elif name == "grid":
                    self.show_grid = not self.show_grid
                elif name == "help":
                    self._help = not getattr(self, "_help", False)
                elif name == "zin":
                    self._zoom_step(+1)      # 放大：看得更清
                elif name == "zout":
                    self._zoom_step(-1)      # 缩小：看得更远
                elif name == "bigger":
                    resize_step(+1)          # 窗口变大
                elif name == "smaller":
                    resize_step(-1)          # 窗口变小
                elif name == "rsize":
                    apply_size(*self.launch_size)   # 回到启动时的尺寸
                elif name == "layer":
                    self.layer = LAYERS[(LAYERS.index(self.layer) + 1) % len(LAYERS)]
                elif name == "map":
                    self.map_mode = MAP_MODES[(MAP_MODES.index(self.map_mode) + 1)
                                              % len(MAP_MODES)]
                elif name == "next":
                    self.cycle_pair(1)
                elif name == "prev":
                    self.cycle_pair(-1)
                elif name == "source":
                    self.mode = SOURCES[(SOURCES.index(self.mode) + 1) % len(SOURCES)]
                    self.demo_on = False
                elif name == "demo":
                    self.demo_on = not self.demo_on
                elif name == "alert":
                    self.cycle_alert()
            return h

        canvas.bind("<Button-1>", press)
        canvas.bind("<B1-Motion>", drag)
        # 右键拖 = 缩放窗口
        canvas.bind("<Button-3>", press3)
        canvas.bind("<B3-Motion>", drag3)
        root.bind("<MouseWheel>", wheel)
        # 部分平台（X11/部分远程桌面）滚轮走 Button-4/5 而非 MouseWheel
        canvas.bind("<Button-4>", lambda e: wheel_btn(e, +1))
        canvas.bind("<Button-5>", lambda e: wheel_btn(e, -1))
        root.bind("<Escape>", key("quit"))
        root.bind("q", key("quit"))
        for k, n in [("t", "top"), ("f", "frame"), ("g", "grid"), ("h", "help"),
                     ("z", "zin"), ("x", "zout"), ("c", "layer"),
                     ("n", "next"), ("p", "prev"), ("v", "source"), ("d", "demo"),
                     ("m", "map"), ("r", "alert"),
                     # 窗口缩放：+ / - 与 0（复位）。Shift 后的符号也一起绑上，
                     # 免得用户按了 + 却以为没反应（+ 在多数键盘上就是 Shift+=）。
                     ("+", "bigger"), ("=", "bigger"),
                     ("-", "smaller"), ("_", "smaller"),
                     ("0", "rsize")]:
            root.bind(k, key(n))
        root.focus_force()

        if self.args.selfclose:
            print("[selfclose] %ds 后自动关闭；首帧渲染完成后窗口即可用"
                  % self.args.selfclose)

            def _bye():
                print("[selfclose] 已渲染 %d 帧，fps=%.1f，当前 %s/%s 坐标(%.1f, %.1f)"
                      % (self.frames, self.fps, getattr(self, "_dim", "?"),
                         getattr(self, "_mw", "?"), self.last_fix.x, self.last_fix.z))
                root.destroy()
            root.after(int(self.args.selfclose * 1000), _bye)

        on_tick()
        root.mainloop()


# ---------------------------------------------------------------------------
def selftest(args):
    """无窗口自检：走一遍「取坐标 -> 解析维度 -> 渲染」循环并落盘若干帧。"""
    app = FollowApp(args)
    app.mode = "demo"
    app.demo_on = True
    N = args.selftest
    out = os.path.join(APP, "out", "follow")
    os.makedirs(out, exist_ok=True)
    miss_hist = []
    t0 = time.time()
    saved = []
    for i in range(N):
        img, fix = app.step(args.interval / 1000.0)
        miss_hist.append(app.missing)
        if i % max(1, N // 4) == 0 or i == N - 1:
            p = os.path.join(out, "f%03d.png" % i)
            img.convert("RGB").save(p)
            saved.append(p)
        print("  #%02d  dim=%s/%-10s  (%.1f, %.1f)  miss=%d  render=%.0fms  fps=%.1f"
              % (i, app._dim, app._mw, fix.x, fix.z, app.missing, app.render_ms, app.fps))
        time.sleep(min(0.05, args.interval / 1000.0 / 5.0))
    el = time.time() - t0
    print("\n自检完成：%d 帧 / %.2fs = %.1f fps（真实循环不含 sleep 更快）" % (N, el, N / el))
    print("缺瓦片：首帧 %d -> 末帧 %d，中位 %d"
          % (miss_hist[0], miss_hist[-1], sorted(miss_hist)[len(miss_hist) // 2]))
    print("落盘帧：%s" % ", ".join(os.path.basename(p) for p in saved))
    bad = [m for m in miss_hist[-3:] if m > 0]
    return 0 if not bad else 2


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="方案C 外部跟随地图")
    ap.add_argument("--server", default=None,
                    help="Xaero 的「服务器」目录（下面按维度分子目录）。"
                         "留空 = 自动定位（命令行 > 环境变量 FOLLOWMAP_XAERO > "
                         "同目录 server_path.txt > 模组 status.txt 记录的游戏目录 > "
                         "常见启动器位置 > 盘符扫描）。换电脑后一般不用手填。")
    ap.add_argument("--size", default="560", help="560 或 640x480")
    ap.add_argument("--zoom", type=int, default=1,
                    help="每像素代表多少方块（会自动规整到 1/2/4/8）")
    ap.add_argument("--no-prewarm", action="store_true",
                    help="关掉视口预取（默认每帧预取整屏+一圈余量）")
    ap.add_argument("--no-inline", action="store_true",
                    help="关掉「热 region 就地重建」（默认开：只对之前建过的 region "
                         "在当帧重建，省掉一整帧延迟；冷建仍只走后台）")
    ap.add_argument("--interval", type=int, default=120,
                    help="重绘周期 ms（默认 120）。地图延迟 = 帧周期 × 帧数，"
                         "所以这是最直接的一档；渲染一帧只要 8ms 左右，调小很划算")
    ap.add_argument("--layer", choices=LAYERS, default="auto")
    ap.add_argument("--source", choices=SOURCES, default="auto")
    ap.add_argument("--map", choices=MAP_MODES, default="auto",
                    help="地图数据源：auto=内存直读层+Xaero 底图（推荐，跟得上跑图）；"
                         "mem=只用内存层；xaero=只用 Xaero（会滞后约半分钟到一分钟）")
    ap.add_argument("--dim", default=None, help="锁定维度目录，如 null / DIM1")
    ap.add_argument("--mw", default=None, help="锁定子图，如 mw$default / cm$111")
    ap.add_argument("--x", type=float, default=0.0)
    ap.add_argument("--z", type=float, default=0.0)
    ap.add_argument("--votes", type=int, default=2, help="OCR 多帧投票帧数")
    ap.add_argument("--demo-speed", type=float, default=40.0)
    ap.add_argument("--poi", default=os.path.join(APP, "poi.json"))
    ap.add_argument("--ruin-alert", choices=ALERT_MODES, default="auto",
                    help="稀有遗迹（巫师/武士/白金）提醒方式，默认 auto = 水滴音(三连)"
                         "+任务栏闪烁+地图打点，**不抖窗口**（场景是笔记本屏挂机、"
                         "外接屏刷视频，眼睛不在笔记本屏上）；both=再加窗口抖动，"
                         "sound=只出声，flag=只闪，off=关")
    ap.add_argument("--ruin-volume", type=float, default=1.5, metavar="V",
                    help="水滴音音量 0.2~3.0。峰值已归一化到满刻度，>1 走 tanh 软削波"
                         "继续推响度（峰值不变，不会数字破音）；实测穿视频声用 1.5~2.0")
    ap.add_argument("--ruin-repeat", type=int, default=3, metavar="N",
                    help="水滴音连响几下（默认 3，从视频声里穿出来的关键）")
    ap.add_argument("--no-ruin", action="store_true", help="关掉遗迹识别提醒")
    ap.add_argument("--wx", type=int, default=40)
    ap.add_argument("--wy", type=int, default=40)
    ap.add_argument("--no-grid", action="store_true")
    ap.add_argument("--no-top", action="store_true")
    ap.add_argument("--border", action="store_true", help="带系统边框（调试）")
    ap.add_argument("--show-help", action="store_true")
    ap.add_argument("--selfclose", type=float, default=0.0, metavar="SEC",
                    help="N 秒后自动关闭（用于验证 GUI 链路）")
    ap.add_argument("--selftest", type=int, default=0, metavar="N")
    a = ap.parse_args(argv)
    # Xaero 目录在这里才解析：import 模块时不做文件系统扫描（否则 --help 也要等）。
    # 返回值第二项是「从哪找到的」，出问题时报出来，省得猜。
    a.server, a.server_src = P.resolve_server(a.server)
    if "x" in a.size:
        w, h = a.size.lower().split("x")
        a.size = (int(w), int(h))
    else:
        a.size = (int(a.size), int(a.size))
    return a


if __name__ == "__main__":
    A = parse_args()
    # 把「底图目录从哪来」打在第一行：换电脑后这是第一手排查信息。
    # （放这里而不是 FollowApp.__init__，免得被 diagnose.py 的渲染自检蹭出一堆输出。）
    print("[followmap] Xaero 底图 : %s" % (A.server or "(没找到)"))
    print("[followmap] 定位来源   : %s" % A.server_src)
    if not (A.server and os.path.isdir(A.server)):
        print("[followmap] !! 底图目录不可用 —— 只有内存直读层，历史区域会是空白。")
        print("[followmap]    解决（任选其一）：")
        print("[followmap]      1) 把 Xaero 的服务器目录写一行进 %s" % os.path.join(APP, P.CFG_NAME))
        print("[followmap]      2) 或用 --server 指定，或设环境变量 FOLLOWMAP_XAERO")
        print("[followmap]      3) 或先让游戏跑一次（模组会把游戏目录写进 %s，下次自动定位）"
              % os.path.join(P.coordbridge_home(), "status.txt"))
    if A.selftest:
        sys.exit(selftest(A))
    try:
        FollowApp(A).run()
    except Exception:
        # 静默启动器没有控制台，崩溃必须落盘，否则什么都看不到
        import traceback
        tb = traceback.format_exc()
        try:
            logd = os.path.join(APP, "out")
            os.makedirs(logd, exist_ok=True)
            with open(os.path.join(logd, "crash.log"), "a", encoding="utf-8") as fh:
                fh.write("\n=== %s ===\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), tb))
        except Exception:
            pass
        sys.stderr.write(tb)
        raise
