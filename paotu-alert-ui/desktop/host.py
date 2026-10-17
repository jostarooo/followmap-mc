# -*- coding: utf-8 -*-
"""末地跑图提醒 · 控制台（桌面壳 / 运行模式宿主）

把 `paotu-alert-ui/index.html` 装进一个**原生窗口**（Windows 上走 Edge WebView2），
用 `?live=1` 打开 → 界面进入「运行模式」，并由本进程把真实数据推进去：

    实时坐标     ~/.coordbridge/coords.json            （CoordBridge 模组 10Hz 落盘）
    区块地形     ~/.coordbridge/chunks/<world>/*.bin   （CBB1 快照，真实地表方块）
    已发现遗迹   <app>/out/found_ruins.json
    模组自检     ~/.coordbridge/scan_status.txt · status.txt

界面上改提醒方式 / 改设置会经 js_api 回调到这里，落盘到 `runtime/actions.jsonl`，
供 Python 主程序读取（也可以在 config.json 里关掉回传）。

**边界（说清楚，别误解）**：本壳负责「显示真实数据 + 把操作记下来」，
它**不做**遗迹判定 —— 判定在 followmap 主程序里。壳不 import、不改动主程序任何代码，
只读它落盘的文件；整个 desktop/ 目录可以直接删掉。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import struct
import sys
import threading
import time
from pathlib import Path

import webview

APP_TITLE = "末地跑图提醒 · 控制台"
MAP_TITLE = "末地跑图地图"
VERSION = "1.1.0"

BRIDGE = Path.home() / ".coordbridge"
COORDS = BRIDGE / "coords.json"
SCAN_STATUS = BRIDGE / "scan_status.txt"
STATUS = BRIDGE / "status.txt"
CHUNK_DIR = BRIDGE / "chunks"

# 找不到主程序时的兜底路径（exe 同级的 config.json 可以覆盖）
DEFAULT_APP_DIR = Path(r"D:\wbworkspace\2026-10-08-17-29-12\fangkuai-chuanshuo\app")

# ── CBB1 区块快照格式（与 CoordBridge 模组写出的字节布局一致）────────────────
#    u32 magic 'CBB1' | u16 ver | u16 flags | i32 cx | i32 cz | u16 palette_n
#    之后 palette_n × (u16 长度 + utf-8 方块名)，再 256 × i16 高度，再 256 × u16 调色板索引
HDR = struct.Struct("<IHHiiH")
MAGIC = 0x31424243
EMPTY = 0xFFFF
MAX_CHUNKS = 3000            # 地图一次最多画多少区块（超出按离玩家远近挑）
BATCH = 400                  # 分批发给界面，单批区块数
PUSH_HZ = 5                  # 坐标推送频率（coords.json 本身是 10Hz）
MOVE_CHUNKS = 24             # 玩家移动超过这么多区块才重画地图
MIN_REPUSH_S = 8.0           # 两次重画之间的最小间隔


# ══════════════════════════════════════════════════════════════════════════
# 路径
# ══════════════════════════════════════════════════════════════════════════
def res_dir() -> Path:
    """只读资源目录（打包后是 PyInstaller 的临时解包目录）。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def exe_dir() -> Path:
    """可执行文件（或本脚本）所在目录 —— 读写运行时文件用它，别用 res_dir。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def raise_window_by_title(title: str) -> bool:
    """把标题完全匹配的顶层窗口还原（若被最小化）并切到前台。

    为什么要这一步：独立地图窗口是「置顶」的，关掉它之后系统有时会把控制台
    留在后面甚至缩下去 —— 用户按「收回地图」的本意是「回到控制台」，所以这里
    主动把它还到眼前。**只在确实最小化时才 SW_RESTORE**，免得把用户手动
    最大化的窗口给还原成普通尺寸。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:                                            # noqa: BLE001
        return False
    try:
        u = ctypes.windll.user32
    except Exception:                                            # noqa: BLE001
        return False

    hits = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lp):
        n = u.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value == title and u.IsWindowVisible(hwnd):
                hits.append(hwnd)
        return True

    try:
        u.EnumWindows(_cb, 0)
    except Exception:                                            # noqa: BLE001
        return False
    if not hits:
        return False
    hwnd = hits[0]
    try:
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 9)                                # SW_RESTORE
        u.SetForegroundWindow(hwnd)
    except Exception:                                            # noqa: BLE001
        return False
    return True


def ui_file() -> Path:
    return res_dir() / "index.html"


def icon_file():
    """窗口图标：打包后在 _MEIPASS/desktop/app.ico 或 _MEIPASS/app.ico。"""
    for p in (res_dir() / "desktop" / "app.ico", res_dir() / "app.ico",
              exe_dir() / "app.ico"):
        try:
            if p.exists():
                return p
        except OSError:
            continue
    return None


def state_dir() -> Path:
    d = exe_dir() / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_config() -> dict:
    for p in (exe_dir() / "config.json", res_dir() / "desktop" / "config.json"):
        try:
            if p.exists():
                return json.loads(p.read_text("utf-8"))
        except Exception:
            continue
    return {}


def find_app_dir(cfg: dict):
    """定位 followmap 主程序目录：环境变量 > config.json > 向上找 > 默认路径。"""
    cands = []
    env = os.environ.get("PAOTU_APP")
    if env:
        cands.append(Path(env))
    if cfg.get("app_dir"):
        cands.append(Path(cfg["app_dir"]))
    p = exe_dir()
    for _ in range(6):
        cands.append(p)
        p = p.parent
    cands.append(DEFAULT_APP_DIR)
    for c in cands:
        try:
            if c and (c / "followmap" / "app.py").exists():
                return c
        except OSError:
            continue
    return None


# ══════════════════════════════════════════════════════════════════════════
# 工具
# ══════════════════════════════════════════════════════════════════════════
def read_json(path: Path):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return None


def jd(obj) -> str:
    """紧凑 JSON（喂给 evaluate_js 用）。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.$-]", "_", s or "")


def parse_chunk(path: Path):
    """解析一个 CBB1 快照 → (cx, cz, palette, ys_bytes, idx_bytes)。"""
    try:
        d = path.read_bytes()
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
    ys = d[o:o + 512]
    idx = d[o + 512:o + 1024]
    return cx, cz, pal, ys, idx


def scan_indexes():
    """~/.coordbridge/index_<world>.json → [(world_key, meta)]，meta 带 dim/chunks/t。"""
    out = []
    try:
        files = list(BRIDGE.glob("index_*.json"))
    except OSError:
        files = []
    for f in files:
        key = f.name[len("index_"):-len(".json")]
        meta = read_json(f) or {}
        try:
            mt = f.stat().st_mtime
        except OSError:
            mt = 0.0
        out.append((key, meta, mt))
    return out


def pick_world(dim_hint=None, server_hint=None):
    """挑一个 world 目录：优先当前服务器 → 指定维度里最新的 → 全局最新。"""
    idx = scan_indexes()
    if not idx:
        return None, {}
    if server_hint:
        want = "minecraft_" + safe_name(server_hint)
        for key, meta, _ in idx:
            if key == want:
                return key, meta
    if dim_hint:
        cands = [x for x in idx if (x[1].get("dim") or "") == dim_hint]
        if cands:
            cands.sort(key=lambda x: (x[1].get("t") or 0, x[2]), reverse=True)
            return cands[0][0], cands[0][1]
    idx.sort(key=lambda x: (x[1].get("t") or 0, x[2]), reverse=True)
    return idx[0][0], idx[0][1]


def index_chunks(world: str):
    """扫一个 world 目录 → [(cx, cz, path, mtime)]。

    坐标直接**从文件名 `<cx>_<cz>.bin` 解析**，一个区块文件都不打开 ——
    本机实测某世界有 28295 个区块，逐个读文件要 43 秒，只扫目录条目不到 2 秒。
    """
    root = CHUNK_DIR / world
    out = []
    try:
        regions = [e for e in os.scandir(root) if e.is_dir()]
    except OSError:
        return out
    for rg in regions:
        try:
            subs = [e for e in os.scandir(rg.path) if e.is_dir()]
        except OSError:
            continue
        for sub in subs:
            try:
                for e in os.scandir(sub.path):
                    if not e.name.endswith(".bin"):
                        continue
                    a, _, b = e.name[:-4].partition("_")
                    try:
                        cx = int(a)
                        cz = int(b)
                    except ValueError:
                        continue
                    try:
                        mt = e.stat().st_mtime
                    except OSError:
                        mt = 0.0
                    out.append((cx, cz, e.path, mt))
            except OSError:
                continue
    return out


def pick_relevant(items, px, pz, limit, use_near=True):
    """挑要画的区块：优先玩家附近的（地图视图就该看脚下），超出上限时按 mtime 取最新。"""
    if len(items) <= limit:
        return items
    if use_near:
        def d2(it):
            dx = it[0] * 16 + 8 - px
            dz = it[1] * 16 + 8 - pz
            return dx * dx + dz * dz
        return sorted(items, key=d2)[:limit]
    return sorted(items, key=lambda it: it[3], reverse=True)[:limit]


def load_terrain(items, limit: int = MAX_CHUNKS):
    """把选中的区块读成给界面用的 payload（高度与索引各压成 base64）。"""
    out = []
    for cx, cz, path, _mt in items[:limit]:
        try:
            rec = parse_chunk(Path(path))
        except OSError:
            continue
        if not rec:
            continue
        _cx, _cz, pal, ys, idx = rec
        out.append({
            "cx": cx, "cz": cz, "pal": pal,
            "ys": base64.b64encode(ys).decode("ascii"),
            "idx": base64.b64encode(idx).decode("ascii"),
        })
    return out


# ══════════════════════════════════════════════════════════════════════════
# 桥：把真实数据推进界面
# ══════════════════════════════════════════════════════════════════════════
class Bridge:
    def __init__(self, main_win, app_dir, cfg):
        self.main_win = main_win
        self.map_win = None          # 「地图分离」时才有：独立的只显示地图的窗口
        self.app_dir = app_dir
        self.cfg = cfg or {}
        self.dim_hint = self.cfg.get("dim") or "minecraft:the_end"
        self._stop = threading.Event()
        self._page = threading.Event()
        self._coord_t = None
        self._world = None
        self._world_meta = {}
        self._world_chunks = []
        self._terrain_sig = None
        self._idx = None
        self._idx_at = 0.0
        self._idx_world = None
        self._tp = (0.0, 0.0)
        self._last_push = 0.0
        self._found_sig = None
        self._known_found = set()
        self._tick_n = 0
        self._resync = False         # 窗口增减后要求「重推一遍全量」
        self._log_lock = threading.Lock()
        self._win_lock = threading.Lock()

    # ── 日志 ─────────────────────────────────────────────────────────
    def log(self, msg: str):
        line = "%s  %s" % (time.strftime("%H:%M:%S"), msg)
        with self._log_lock:
            try:
                with open(state_dir() / "bridge.log", "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

    # ── 窗口集合 ─────────────────────────────────────────────────────
    def all_windows(self):
        with self._win_lock:
            return [w for w in (self.main_win, self.map_win) if w is not None]

    def map_windows(self):
        """需要「地图数据」（区块地形）的窗口 —— 同一时刻只有一个在画地图：
        地图被分离时是那个独立窗口，否则是主控制台窗口。
        地形一次读盘 3000 块要 3 秒多，只推一份。"""
        with self._win_lock:
            return [self.map_win] if self.map_win is not None else [self.main_win]

    def set_map_window(self, win):
        """地图窗口的页面刚加载完时调用：接下来地形推给它，并让它拿一次全量。"""
        with self._win_lock:
            self.map_win = win
        self._coord_t = None                 # 强制重推一次坐标
        self._resync = True

    def clear_map_window(self):
        """地图窗口关掉时调用：地形改回推主窗口，并让主窗口重拿一次全量。"""
        with self._win_lock:
            self.map_win = None
        self._coord_t = None
        self._resync = True

    # ── 与页面通信 ───────────────────────────────────────────────────
    def page_ready(self):
        self._page.set()

    def js(self, code: str, target=None):
        for w in (self.map_windows() if target == "map" else self.all_windows()):
            try:
                w.evaluate_js(code)
            except Exception as e:                               # noqa: BLE001
                self.log("evaluate_js 失败: %r" % (e,))

    def call(self, expr: str, target=None):
        """expr 形如 'applyRuntime({...})' —— 统一挂到唯一全局出口下。"""
        self.js("window.PaoTuAlertUI && window.PaoTuAlertUI.%s;" % expr, target)

    def call_main(self, expr: str):
        """只对主控制台窗口说话（例如告诉它「地图已被分离」）。"""
        try:
            self.main_win.evaluate_js("window.PaoTuAlertUI && window.PaoTuAlertUI.%s;" % expr)
        except Exception as e:                                   # noqa: BLE001
            self.log("evaluate_js(main) 失败: %r" % (e,))

    # ── 主循环 ───────────────────────────────────────────────────────
    def start(self):
        threading.Thread(target=self._run, name="paotu-bridge", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _run(self):
        if not self._page.wait(30):
            self.log("页面 30s 内未回执，继续推数据（可能收不到回执）")
        self.call("setLive(true)")
        self._refresh_terrain(force=True)
        self._refresh_found(seed=True)
        self.log("桥接启动：app_dir=%s world=%s" % (self.app_dir, self._world))
        while not self._stop.is_set():
            self._tick_n += 1
            try:
                if self._resync:
                    self._resync = False
                    self._resync_windows()
                self._push_coords()
                if self._tick_n % PUSH_HZ == 0:          # 约每秒
                    self._refresh_found()
                if self._tick_n % (PUSH_HZ * 3) == 0:    # 约每 3 秒
                    self._refresh_terrain()
            except Exception as e:                       # noqa: BLE001
                self.log("tick 异常: %r" % (e,))
            self._stop.wait(1.0 / PUSH_HZ)

    def _resync_windows(self):
        """窗口增减（分离 / 收回地图）后：给当前该收数据的窗口重推一遍全量。"""
        who = "地图窗口" if self.map_win is not None else "主窗口"
        self.call("setLive(true)")
        self._found_sig = None
        self._refresh_found(seed=True)
        if self._world_chunks and self._world:
            self._push_terrain(self._world_chunks, self._world, self._world_meta)   # 用缓存，不重读盘
        else:
            self._refresh_terrain(force=True)
        self.log("窗口变化 → 重推全量给%s（%d 块）" % (who, len(self._world_chunks)))


    # ── 坐标 ─────────────────────────────────────────────────────────
    def _push_coords(self):
        d = read_json(COORDS)
        if d is None:
            self.call("applyRuntime(%s)" % jd({
                "inGame": False, "note": "未找到 coords.json",
                "nav": "未找到 CoordBridge 落盘（模组未装或游戏未启动过）"}))
            return
        t = d.get("t")
        if t == self._coord_t:
            return                                   # 没更新就不推，省开销
        self._coord_t = t
        age = max(0.0, (time.time() * 1000.0 - float(t or 0)) / 1000.0)
        in_game = bool(d.get("in_game"))
        fresh = in_game and age < 3.0
        n = self._world_n or 0
        payload = {"inGame": in_game, "age": round(age, 2), "memLag": round(age, 2),
                   "memBuilds": n}
        if fresh:
            payload.update({"x": float(d.get("x", 0.0)), "y": float(d.get("y", 0.0)),
                            "z": float(d.get("z", 0.0))})
            if d.get("dim"):
                payload["dim"] = d["dim"]
            if d.get("server"):
                payload["server"] = d["server"]
            payload["nav"] = "实时坐标 · 已落盘 %d 块 · 延迟 %.2fs" % (n, age)
            nd = d.get("dim")
            if nd and self._world_meta.get("dim") and self._world_meta.get("dim") != nd:
                self._terrain_sig = None             # 换维度了，下一轮重画地图
                self._world = None
        else:
            note = d.get("error") or ("不在游戏中" if not in_game else "数据过期 %.1fs" % age)
            payload["note"] = note
            payload["nav"] = "%s · 已落盘 %d 块" % (note, n)
        self.call("applyRuntime(%s)" % jd(payload))

    # ── 地形 ─────────────────────────────────────────────────────────
    @property
    def _world_n(self):
        return len(self._world_chunks) if getattr(self, "_world_chunks", None) else 0

    def _refresh_terrain(self, force=False):
        d = read_json(COORDS) or {}
        fresh = bool(d.get("in_game")) and \
            (time.time() * 1000.0 - float(d.get("t") or 0)) < 3000.0
        px = float(d.get("x") or 0.0)
        pz = float(d.get("z") or 0.0)
        world, meta = pick_world(d.get("dim") if fresh else self.dim_hint,
                                 d.get("server") if fresh else None)
        if not world:
            self.call("applyRuntime(%s)" % jd({
                "world": None, "nav": "未找到区块落盘目录 ~/.coordbridge/chunks"}))
            return

        now = time.time()
        changed = force or self._idx is None
        if force or self._idx is None or (now - self._idx_at) > 10.0 or world != self._idx_world:
            t0 = time.time()
            items = index_chunks(world)
            if not items:
                return
            newest = max(i[3] for i in items)
            sig = (world, len(items), round(newest, 1))
            changed = force or sig != self._terrain_sig
            self._idx, self._idx_at, self._idx_world = items, now, world
            self._terrain_sig = sig
            self.log("区块索引已刷新: %s %d 块，%.2fs" % (world, len(items), time.time() - t0))

        moved = abs(px - self._tp[0]) + abs(pz - self._tp[1]) > MOVE_CHUNKS * 16
        if not (changed or moved or world != self._world):
            return
        if not changed and (now - self._last_push) < MIN_REPUSH_S:
            return                                   # 飞太快时别把桥线程占满

        t0 = time.time()
        if len(self._idx) <= MAX_CHUNKS:
            sel = self._idx
        elif fresh:
            sel = pick_relevant(self._idx, px, pz, MAX_CHUNKS, use_near=True)
        else:
            sel = pick_relevant(self._idx, px, pz, MAX_CHUNKS, use_near=False)
        terrain = load_terrain(sel)
        if not terrain:
            return
        self._world = world
        self._world_meta = meta
        self._world_chunks = terrain
        self._tp = (px, pz)
        self._last_push = now
        self._push_terrain(terrain, world, meta, t0)

    def _push_terrain(self, terrain, world, meta, t0=None):
        """把地形分批推给「正在画地图的那个窗口」（主窗口或独立地图窗口，只推一份）。"""
        t0 = time.time() if t0 is None else t0
        n_all = len(self._idx) if self._idx else len(terrain)
        # 分批推：单次 evaluate_js 的字符串太大时 WebView2 会截断/卡住
        for i in range(0, len(terrain), BATCH):
            self.call("setTerrain(%s,%d)" % (jd(terrain[i:i + BATCH]), 0 if i == 0 else 1),
                      target="map")
            time.sleep(0.04)
        self.call("applyRuntime(%s)" % jd({
            "world": world,
            "dim": meta.get("dim") or self.dim_hint,
            "memBuilds": len(terrain),
            "nav": "已落盘 %d 块 · 地图画 %d 块 · %s" % (
                n_all, len(terrain),
                "跟随玩家" if n_all > MAX_CHUNKS else "全部")}))
        self.log("地形已更新: %s %d/%d 块，%.2fs → %s" % (
            world, len(terrain), n_all, time.time() - t0,
            "地图窗口" if self.map_win is not None else "主窗口"))

    # ── 已发现遗迹 ───────────────────────────────────────────────────
    def _refresh_found(self, seed=False):
        if not self.app_dir:
            return
        p = self.app_dir / "out" / "found_ruins.json"
        try:
            st = p.stat()
        except OSError:
            return
        sig = (st.st_mtime, st.st_size)
        if not seed and sig == self._found_sig:
            return
        first = self._found_sig is None
        self._found_sig = sig
        d = read_json(p)
        if not d:
            return
        items = d.get("found") or []
        norm = [{"type": i.get("type"), "x": i.get("x"), "z": i.get("z"),
                 "pure": i.get("pure")} for i in items if i.get("type") is not None]
        if seed or first:
            self.call("seedFound(%s)" % jd(norm))
        new = []
        for it in norm:
            k = (it["type"], it["x"], it["z"])
            if k in self._known_found:
                continue
            self._known_found.add(k)
            if not (seed or first):
                new.append(it)
        for it in new:
            self.call("pushAlert(%s)" % jd(it))
        if new:
            self.log("新命中 %d 条（已推给界面）" % len(new))


# ══════════════════════════════════════════════════════════════════════════
# js_api：界面 → Python 的回传
# ══════════════════════════════════════════════════════════════════════════
class Api:
    """暴露给页面的 js_api。

    ⚠️ 这里的**属性名一律加下划线**：pywebview 生成 js_api 时会用 dir() 遍历
    所有「不以 _ 开头」的属性并**递归**下去（见 webview/util.py:get_functions），
    把 bridge / shell / 窗口对象一路走到底 —— 结果是启动时刷一屏
    `Error while processing bridge.xxx.native.AccessibilityObject... maximum
    recursion depth exceeded`，还白白拖慢页面加载。加下划线它就直接跳过。
    """

    def __init__(self, app_dir, cfg, shell=None):
        self._app_dir = app_dir
        self._cfg = cfg or {}
        self._echo = self._cfg.get("echo_actions", True)
        self._bridge = None           # 由 main() 在窗口建好后回填
        self._shell = shell           # 窗口管理（分离 / 收回地图窗口）

    def _act(self, kind: str, data):
        rec = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "data": data}
        if not self._echo:
            return {"ok": True, "echo": False}
        try:
            d = state_dir()
            with open(d / "actions.jsonl", "a", encoding="utf-8") as f:
                f.write(jd(rec) + "\n")
            with open(d / "actions.log", "a", encoding="utf-8") as f:
                f.write("%s  %-15s %s\n" % (rec["at"], kind, jd(data)))
        except OSError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    # 页面加载完调一次，告诉宿主可以开始推了
    def ready(self):
        if self._bridge:
            self._bridge.page_ready()
        return {"ok": True, "version": VERSION, "app": str(self._app_dir or "")}

    # ── 地图分离 ─────────────────────────────────────────────────────
    # 界面上的「分离地图」按钮 → 这里 → Shell 真的开一个独立窗口；
    # 「收回地图」/ 关掉那个窗口 → attach_map() 把窗口销毁，并通知主窗口地图回来了。
    def detach_map(self):
        if not self._shell:
            return {"ok": False, "error": "桌面壳未就绪"}
        r = self._shell.detach_map()
        self._act("detach_map", r)
        return r

    def attach_map(self):
        if not self._shell:
            return {"ok": False, "error": "桌面壳未就绪"}
        r = self._shell.attach_map()
        self._act("attach_map", r)
        return r

    def map_state(self):
        return {"ok": True, "detached": bool(self._shell and self._shell.map_win)}

    def set_mode(self, mid=None):
        return self._act("set_mode", {"mode": mid})

    def apply_settings(self, o=None):
        return self._act("apply_settings", o or {})

    def scan(self):
        return self._act("scan", {})

    def pause(self, on=None):
        return self._act("pause", {"running": on})

    def info(self):
        b = self._bridge
        return {
            "version": VERSION,
            "app_dir": str(self._app_dir or ""),
            "bridge": str(BRIDGE),
            "world": b._world if b else None,
            "chunks": b._world_n if b else 0,
            "map_detached": bool(self._shell and self._shell.map_win),
        }

    def open_dir(self, which="bridge"):
        p = {"bridge": BRIDGE, "state": state_dir(),
             "app": self._app_dir, "out": (self._app_dir / "out") if self._app_dir else None}
        t = p.get(which)
        if t and Path(t).exists():
            try:
                os.startfile(str(t))                     # noqa: S606
                return {"ok": True, "path": str(t)}
            except OSError as e:
                return {"ok": False, "error": str(e)}
        return {"ok": False, "error": "路径不存在: %s" % t}


# ══════════════════════════════════════════════════════════════════════════
# 窗口管理：主控制台 + 可分离的独立地图窗口
# ══════════════════════════════════════════════════════════════════════════
class Shell:
    """管窗口，不管数据（数据是 Bridge 的事）。

    「把地图分离出来」= 再开一个**只显示地图**的小窗口（同一份 index.html，
    只是 URL 带 `&view=map`），并把主控制台那边的地图区腾空（`view=panel` 形态）。
    这样做旧能省屏幕：地图可以钉在角落 / 副屏常驻，主窗口缩到只剩设置与提醒流。
    """

    def __init__(self, ui_uri: str, cfg: dict):
        self.ui_uri = ui_uri
        self.cfg = cfg or {}
        self.bridge = None
        self.main_win = None
        self.map_win = None            # Api.map_state() 要读这个名字
        # js_api 是「每个窗口各一份」的：不给新窗口传，它页面里的
        # window.pywebview.api 就是**空对象**，调 attach_map() 直接是 undefined。
        # （pywebview util.inject_pywebview → get_functions(window._js_api)）
        self.api = None                # 由 main() 回填，开地图窗口时要一起传
        self._lock = threading.Lock()

    def attach_bridge(self, bridge):
        self.bridge = bridge

    # 独立地图窗口的几何 / 样式：config.json 的 map_window 段可覆盖
    def _map_geom(self) -> dict:
        c = self.cfg.get("map_window") or {}
        return {
            "width": int(c.get("width", 560)),
            "height": int(c.get("height", 620)),
            "x": c.get("x"), "y": c.get("y"),
            "frameless": bool(c.get("frameless", True)),   # 无边框 → 省掉标题栏
            "on_top": bool(c.get("on_top", True)),         # 置顶 → 游戏全屏时也看得见
            "resizable": bool(c.get("resizable", True)),
        }

    def detach_map(self):
        with self._lock:
            if self.map_win is not None:
                return {"ok": True, "already": True}
            g = self._map_geom()
            try:
                w = webview.create_window(
                    MAP_TITLE, self.ui_uri + "&view=map",
                    width=g["width"], height=g["height"], x=g["x"], y=g["y"],
                    frameless=g["frameless"], easy_drag=False,   # 拖动只认拖拽条，别抢画布
                    on_top=g["on_top"], resizable=g["resizable"],
                    min_size=(200, 200), background_color="#0b0912",
                    text_select=False,
                    js_api=self.api,            # ← 漏了这个，地图窗口里 button/D 键就全是哑的
                )
            except Exception as e:                                # noqa: BLE001
                return {"ok": False, "error": "create_window 失败: %r" % (e,)}
            self.map_win = w
            w.events.loaded += self._on_map_loaded
            w.events.closed += self._on_map_closed
        if self.bridge:
            self.bridge.log("已开独立地图窗口（无边框=%s 置顶=%s %dx%d）"
                            % (g["frameless"], g["on_top"], g["width"], g["height"]))
        return {"ok": True}

    def attach_map(self):
        with self._lock:
            w, self.map_win = self.map_win, None
        if self.bridge:
            self.bridge.clear_map_window()          # 地形改回推主窗口（会触发重推全量）
        if w is not None:
            try:
                w.destroy()
            except Exception as e:                                # noqa: BLE001
                if self.bridge:
                    self.bridge.log("destroy 地图窗口失败: %r" % (e,))
        if self.bridge:
            self.bridge.call_main("setMapDetached(false)")
            self.bridge.log("已收回地图窗口，地图回到控制台")
        self._focus_main()
        return {"ok": True}

    def _focus_main(self):
        """把控制台窗口还原并切到前台（关掉置顶的地图窗口后，用户想看的是控制台）。"""
        try:
            raise_window_by_title(APP_TITLE)
        except Exception as e:                                    # noqa: BLE001
            if self.bridge:
                self.bridge.log("切回控制台失败（不影响功能）: %r" % (e,))

    # ── 事件 ─────────────────────────────────────────────────────────
    # 地图窗口的页面加载完时探一下它的桥：js_api 是**按窗口**注入的，漏传参数
    # 页面里 window.pywebview.api 就是个空对象，界面上那枚「收回控制台」会静默失效。
    # 所以这里把「适配器返回值 / api 里有几个函数」记进日志，出问题一眼能看出来。
    API_PROBE_JS = (
        "JSON.stringify({ui:!!window.PaoTuAlertUI,"
        " hasBridge:!!window.pywebview,"
        " apiKeys:window.pywebview&&window.pywebview.api"
        "   ?Object.keys(window.pywebview.api).length:-1})"
    )

    def _on_map_loaded(self, *_a):
        w = self.map_win
        if w is None:
            return
        try:
            r = w.evaluate_js(ADAPTER_JS)
        except Exception as e:                                    # noqa: BLE001
            r = "注入失败 %r" % (e,)
        try:
            probe = w.evaluate_js(self.API_PROBE_JS)
        except Exception as e:                                    # noqa: BLE001
            probe = "探测失败 %r" % (e,)
        if self.bridge:
            self.bridge.set_map_window(w)                        # → 下一拍重推全量给地图窗口
            self.bridge.call_main("setMapDetached(true)")        # 主窗口让出地图区
            self.bridge.log("独立地图窗口页面已加载，注入运行模式: %r；桥自检 %s" % (r, probe))

    def _on_map_closed(self, *_a):
        """用户直接点窗口的 X 关掉地图窗口 —— 等同于「收回地图」。"""
        with self._lock:
            self.map_win = None
        if self.bridge:
            self.bridge.clear_map_window()
            self.bridge.call_main("setMapDetached(false)")
            self.bridge.log("独立地图窗口已关闭，地图回到控制台")
        self._focus_main()


# ══════════════════════════════════════════════════════════════════════════
# 启动
# ══════════════════════════════════════════════════════════════════════════
ADAPTER_JS = """
(function () {
  if (!window.PaoTuAlertUI) return 'no-ui';
  window.PaoTuAlertUI.setLive(true);
  window.PaoTuAlertUI.setAdapter({
    setMode: function (id) { try { window.pywebview.api.set_mode(id); } catch (e) {} },
    applySettings: function (o) { try { window.pywebview.api.apply_settings(o); } catch (e) {} },
    onScan: function () { try { window.pywebview.api.scan(); } catch (e) {} },
    onPause: function (on) { try { window.pywebview.api.pause(on); } catch (e) {} },
    onDetachMap: function () { try { window.pywebview.api.detach_map(); } catch (e) {} },
    onAttachMap: function () { try { window.pywebview.api.attach_map(); } catch (e) {} },
    isMarkOn: function () { return true; }
  });
  try { window.pywebview.api.ready(); } catch (e) {}
  return 'live';
})();
"""


def main():
    ap = argparse.ArgumentParser(description="末地跑图提醒 · 控制台（桌面壳）")
    ap.add_argument("--dim", help="强制地图维度，如 minecraft:the_end")
    ap.add_argument("--app", help="followmap 主程序目录（覆盖自动探测）")
    ap.add_argument("--width", type=int, default=1560)
    ap.add_argument("--height", type=int, default=980)
    ap.add_argument("--detach", action="store_true",
                    help="启动时就把地图分离到独立窗口（等同于 config.json 的 start_detached）")
    ap.add_argument("--debug", action="store_true", help="打开 WebView 调试")
    args = ap.parse_args()

    cfg = load_config()
    if args.dim:
        cfg["dim"] = args.dim
    app_dir = Path(args.app) if args.app else find_app_dir(cfg)
    ui = ui_file()
    if not ui.exists():
        print("找不到界面文件: %s" % ui, file=sys.stderr)
        return 2

    # ── WebView2 启动参数 ─────────────────────────────────────────
    # 默认 --no-sandbox：Chromium 的渲染进程沙箱在受限令牌 / 作业对象里起不来，
    # 表现是「窗口出现但永远白/黑、页面不加载、loaded 事件不触发」。
    # 本页面是纯本地、零网络的单文件，关掉渲染沙箱风险很低；可在 config.json
    # 用 webview_args 覆盖（留空字符串 = 不加任何参数）。
    if "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS" not in os.environ:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = \
            cfg.get("webview_args", "--no-sandbox")

    # 用 # 而不是 ? —— file:// 下的 query 会被编码成 %3F，浏览器认不出 .html 后缀
    live_url = ui.as_uri() + "#live=1"
    shell = Shell(live_url, cfg)          # ui_uri 存的是「带 #live=1 的完整地址」
    api = Api(app_dir, cfg, shell)
    shell.api = api                       # 地图窗口也要拿到同一份 js_api（见 Shell.__init__）
    win = webview.create_window(
        APP_TITLE, live_url,
        width=args.width, height=args.height, min_size=(360, 520),
        background_color="#0b0912", text_select=True,
        js_api=api,
    )
    shell.main_win = win
    bridge = Bridge(win, app_dir, cfg)
    api._bridge = bridge
    shell.attach_bridge(bridge)

    want_detach = args.detach or bool(cfg.get("start_detached"))

    def on_loaded():
        r = win.evaluate_js(ADAPTER_JS)
        try:
            vp = win.evaluate_js(
                "JSON.stringify({w:window.innerWidth,h:window.innerHeight,"
                "dpr:window.devicePixelRatio,scrollW:document.documentElement.scrollWidth,"
                "clientW:document.documentElement.clientWidth,"
                "screenW:screen.width,screenAvailW:screen.availWidth})")
        except Exception as e:                                # noqa: BLE001
            vp = "读取失败 %r" % (e,)
        bridge.log("页面已加载，注入运行模式: %r；视口 %s" % (r, vp))
        bridge.page_ready()
        if want_detach:
            # 非 master 窗口必须等主窗口建好才能建（pywebview 内部会等），
            # 不能同步调，扔到线程里最省事
            threading.Thread(target=shell.detach_map, daemon=True).start()

    win.events.loaded += on_loaded
    bridge.start()

    try:
        ic = icon_file()
        webview.start(gui="edgechromium", debug=args.debug,
                      private_mode=False, storage_path=str(state_dir() / "webview"),
                      icon=str(ic) if ic else None)
    finally:
        bridge.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
