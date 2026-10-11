# -*- coding: utf-8 -*-
"""稀有遗迹提醒：从 mod 落盘的区块地表数据里识别「巫师 / 武士 / 白金」类遗迹。

设计依据（都是实测反推，不是拍的）
----------------------------------
1) **数据够用**：CoordBridge 模组每个 chunk 存的就是「256 列的地表方块名」。
   而玩家在 Xaero 地图上认遗迹，依据也正是「地表长什么样」。两者的信息量等价，
   所以不需要扫地下、不需要额外内存开销，更不需要改模组。

2) **指纹来自真实数据**：`app/structures_DIM1.json` 是对末地 1484 个 region
   全量扫描出的 1274 个「人造结构」候选簇。对其中三类取了真实实例做统计
   （白金 12 例 / 武士 8 例 / 巫师 9 例），每个实例的特征方块一致率 100%：

     白金星殿   石砖楼梯 97 + 虫蛀石砖 93 + 苔石楼梯 81 + 苔石砖楼梯 40
                + 平滑石台阶 30 + 平滑石英楼梯 27 + 红羊毛 18（= 描述里的「正中一个红色核心」）
     武士的修行地 末地石砖 380 + 下界岩 370 + 磨制玄武岩 95 + 绯红木板 68
     巫师的圣修所 磨制黑石砖 440 + 黑石 210 + 裂纹磨制黑石砖 115 + 深板岩砖 65

3) **判据 = 锚点（家族合计）+ 可选组 + 纯度**：单看「出现了哪些方块」会误伤
   （末地有上百个下界系小遗迹）。再加一条「该类型的特征方块占全部人造方块的比例」
   就能把它们分开。实测：在 140 个真实 region / 上万个 5x5 窗口上跑，命中 128 处，
   与独立余弦判据的**类型归属零不一致**。

   还加了一组 `any`「至少满足一组」的锚点：模组每个 chunk 只存**每列的地表方块**，
   同一座建筑被屋顶/上层挡住的部分，露出来的方块比例会变，所以单个方块的绝对数量
   在不同实例间会漂移。实测到一处分金星殿只用 `mossy_stone_brick_stairs`（22）、
   另一处只用 `mossy_cobblestone_stairs`（92）——固定阈值会漏掉变体。

5) **锚点必须写成「家族合计」，不能钉在单个方块名上**（2026-10-09 真机复现的漏检）：
   同一建筑换一个实例，露出地表的**成员**会换。真机 4 个武士实例的「末地石砖系」
   总量稳定在 64~67，但拆开看是 `end_stone_bricks` 15 + `end_stone_brick_wall` 38
   + `end_stone_brick_stairs` 11 —— 而旧指纹要求 `end_stone_bricks >= 90`（那个数字
   来自另一个变体），于是**4 个实例全被漏掉**。同类问题还有 `polished_basalt`：
   一个实例只有 11（旧阈值 20）。
   所以指纹表支持 `"@家族名": 阈值` 写法，锚点取家族成员的**合计**。
   这条只有真机数据能发现：A 段喂的是被截断成前 10 项的簇直方图，看不出成员替换。

6) **武士要另一条「恒定构件合计」通路**（2026-10-10 真机复现的漏检）：
   模组落盘的直方图 = 建筑**高出地形基准（height 56/57）**的那部分用料；低于基准的列写
   NODATA。于是武士的用料要分两半看：
     · **恒定构件**（末地石砖系 / 净下界砖系 / 诡异台阶 / 绯红系共 16 项，= `groups.samurai_core`）
       每次完整露出，17 座实例合计 **116~197**，第 18 名骤降到 66 —— 其余所有建筑最大仅 66；
     · **可变构件**（下界岩、磨制玄武岩）会被地形**整个埋掉**，实测两座武士 `netherrack`
       只有 9~10、`polished_basalt` **归零**。
   旧指纹把 `polished_basalt >= 5` 钉在 `anchors` 上，这两座**必漏**。
   现改为 `anchors` 只留 `@end_brick >= 30`，`any` 首条加 `{"@samurai_core": 90}`。
   注意 **武士这条走绝对数、不走占比**（与上面巫师相反）：被埋的只是低处的可变构件，
   恒定构件在高处几乎不缩水，绝对数就是稳的；实测占比反而更差（武士 0.36~0.80）。
   `samurai_core` 刻意不含 `end_stone_bricks` / 菌岩，否则会和紫珀殿（末地石砖 68~153）、
   幽匿殿（末地石砖 66 + 诡异台阶 16）串类；`dirt` 则要并进武士用料表（建筑自带的土质演武场，
   每座 18~33 列，漏掉会让纯度虚低到 0.79）。

4) **触发时机 = 新落盘的区块**：mod 只在**玩家真正加载了**的区块上写文件，
   所以「文件是新出现的」天然等价于「这块地形刚进视距」——正好是需求要的语义，
   也天然合规（只读已加载区域，不碰视距外）。
"""
import json
import os
import re
import struct
import time
from collections import Counter, OrderedDict

NODATA = 0xFFFF
REGION_CHUNKS = 32

# 末地自然地表：这些方块不参与「人造结构」统计
NATURAL = {
    "minecraft:air", "minecraft:cave_air", "minecraft:void_air",
    "minecraft:end_stone", "minecraft:chorus_plant", "minecraft:chorus_flower",
    "minecraft:barrier", "minecraft:light", "minecraft:structure_void",
    "minecraft:water", "minecraft:lava",
}

_HDR = struct.Struct("<IHHiiH")


def safe_dim(name):
    return re.sub(r'[^A-Za-z0-9_.$-]', "_", name)


def parse_chunk(path):
    """解析一个 chunk 快照 -> Counter(方块名) 或 None。只统计人造方块。

    与 memstore.parse_chunk 是同一份二进制格式，但这里只要直方图，
    不需要 numpy，也不保留坐标/高度。
    """
    try:
        with open(path, "rb") as f:
            d = f.read()
    except OSError:
        return None
    if len(d) < _HDR.size:
        return None
    magic, ver, _flags, _cx, _cz, paln = _HDR.unpack_from(d, 0)
    if magic != 0x31424243 or ver != 1:
        return None
    o = _HDR.size
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
    idx = struct.unpack_from("<256H", d, o + 512)
    hist = Counter()
    for v in idx:
        if v == NODATA or v >= len(pal):
            continue
        nm = pal[v]
        if nm in NATURAL:
            continue
        hist[nm] += 1
    return hist


# ---------------------------------------------------------------------------
class Signatures:
    """从 ruins.json 加载遗迹指纹。"""

    def __init__(self, path=None):
        HERE = os.path.dirname(os.path.abspath(__file__))
        self.path = path or os.path.join(os.path.dirname(HERE), "ruins.json")
        self.window = 5                 # 判定窗口边长（chunk 数），5 => 80x80 方块
        self.min_purity = 0.80
        self.dedupe_blocks = 96
        self.types = OrderedDict()
        self._sets = {}
        self._all = set()
        self.error = ""
        try:
            with open(self.path, encoding="utf-8") as fh:
                cfg = json.load(fh)
        except Exception as e:
            self.error = "读不到 %s: %s" % (self.path, e)
            return
        self.window = int(cfg.get("window_chunks", 5))
        self.min_purity = float(cfg.get("min_purity", 0.80))
        self.dedupe_blocks = int(cfg.get("dedupe_blocks", 96))
        # 方块家族：锚点里写 "@名字" 表示取这些成员的**合计**。
        # 同一建筑的不同实例，露在地表的家族成员会置换（见模块 docstring 第 5 条）。
        self.groups = {k: list(v) for k, v in (cfg.get("groups") or {}).items()
                       if k and v}
        for name, t in (cfg.get("types") or {}).items():
            if not t.get("enabled", True):
                continue
            blocks = set(t.get("blocks") or [])
            anchors = dict(t.get("anchors") or {})
            if not blocks or not anchors:
                continue
            self.types[name] = {"icon": t.get("icon", "?"),
                                "color": tuple(t.get("color") or (255, 210, 90)),
                                "anchors": anchors,
                                "ratios": {k: float(v)
                                           for k, v in (t.get("ratios") or {}).items()},
                                "any": [dict(g) for g in (t.get("any") or []) if g],
                                "sound": t.get("sound", "drop")}
            # 锚点/占比里引用到的家族成员，天然属于这个类型的"用料"，
            # 自动并进纯度集合：否则改了 groups 却忘了同步 blocks，纯度会被无谓压低。
            for k in (list(self.types[name]["anchors"])
                      + list(self.types[name]["ratios"])
                      + [x for g in self.types[name]["any"] for x in g]):
                k = k.lstrip("%")          # any 组里允许写 "占比键"（前面带 %）
                if k.startswith("@"):
                    blocks |= set(self.groups.get(k[1:], ()))
            self._sets[name] = blocks
            self._all |= blocks

    @property
    def ok(self):
        return bool(self.types)

    def _anchor(self, key, hist):
        """锚点取值。key 形如 "minecraft:xxx"（单方块）或 "@家族名"（家族合计）。

        家族写法是必须的：同一建筑的实例之间，露在地表的**家族成员**会置换
        （实测 4 个武士实例的末地石砖系总量稳定 64~67，但拆开是 end_stone_bricks 15
        / wall 38 / stairs 11），钉在单个方块名上必然漏。
        """
        if key.startswith("@"):
            return sum(hist.get(b, 0) for b in self.groups.get(key[1:], ()))
        return hist.get(key, 0)

    def relevant(self, name):
        """该方块是否参与统计（能出现在任意指纹里）。"""
        return name in self._all

    def _cond(self, key, hist, hit):
        """条件取值。`"%xxx"` = 占比（分母是该类型用料总量 hit），其余按 `_anchor` 取值。

        占比必须能用在同一处，才能写出「占比够高」**或**「次要特征齐备」这种并列判据——
        这正是同时兼容「被地形淹没」和「完整露出但配料比例不同」的关键。
        """
        if key.startswith("%"):
            v = self._anchor(key[1:], hist)
            return (v / hit) if hit else 0.0
        return self._anchor(key, hist)

    def passes(self, name, hist):
        """单一类型判定：返回 (是否通过, 纯度, 命中详情)。判据见 classify 的 docstring。

        抽出来是为了让离线测试与线上判定走**同一份逻辑**，避免两边阈值各写一遍。
        """
        meta = self.types.get(name)
        if not meta:
            return False, 0.0, {}
        total = sum(hist.values())
        if total < 60:
            return False, 0.0, {}
        s = self._sets[name]
        hit = sum(v for k, v in hist.items() if k in s)
        if hit <= 0:
            return False, 0.0, {}
        purity = hit / total
        details = {}
        for k, need in meta["anchors"].items():
            got = self._anchor(k, hist)
            details[k] = got
            if got < need:
                return False, purity, details
        # 占比锚点：**尺度无关**，抗地形淹没。
        # 分母 = 该类型的用料总量（= 纯度的分子），所以纯度为 1 时等价于"占总人造方块的比例"。
        # details 里记的是**占比本身**（不是计数），键前缀 "%"，与计数区分开。
        for k, need in meta.get("ratios", {}).items():
            got = self._anchor(k, hist)
            r = got / hit
            details["%%%s" % k] = round(r, 3)
            if r < need:
                return False, purity, details
        if meta["any"]:
            for g in meta["any"]:
                gd = {k: self._cond(k, hist, hit) for k in g}
                details.update(gd)
                if all(gd[k] >= v for k, v in g.items()):
                    break
            else:
                return False, purity, details
        if purity < self.min_purity:
            return False, purity, details
        return True, purity, details

    def classify(self, hist):
        """窗口直方图 -> (类型名, 纯度, 命中详情) 或 None。纯度高者胜。"""
        total = sum(hist.values())
        if total < 60:
            return None
        best = None
        for name in self.types:
            ok, purity, details = self.passes(name, hist)
            if not ok:
                continue
            if best is None or purity > best[1]:
                best = (name, purity, details)
        return best


# ---------------------------------------------------------------------------
class RuinWatcher:
    """盯住 ~/.coordbridge/chunks，从**新落盘**的区块里识别遗迹。

    只处理「region 版本号变大的目录」，因此每轮的工作量正比于玩家真正跑了多少，
    不会随已探索面积增长。

    换局（index 里的 sid 变了）时**不重扫**：模组的版本号会重排，按"变了就重扫"
    处理会让主线程卡十几秒并重放历史；这里直接把当前版本号当作新基线，内存直方图
    保留（旧区块文件还在磁盘上，数据依然有效，留着才能让 5x5 判定窗口完整）。
    """

    def __init__(self, sigs=None, root=None, found_path=None):
        self.sigs = sigs or Signatures()
        self.root = (root or os.environ.get("COORDBRIDGE_HOME")
                     or os.path.join(os.path.expanduser("~"), ".coordbridge"))
        here = os.path.dirname(os.path.abspath(__file__))
        self.found_path = found_path or os.path.join(os.path.dirname(here),
                                                     "out", "found_ruins.json")
        self.hist = {}                 # (dim, cx, cz) -> Counter
        self.dims = {}                 # dim -> {sid, regions:{rx,rz:rev}, t}
        self.found = []                # [{type,x,z,dim,at}]
        self.hits = []                 # 本会话最近命中（给 HUD 显示）
        self.scans = 0
        self.chunks = 0
        self.last_ms = 0.0
        self.last_error = ""
        self.enabled = self.sigs.ok
        self._load_found()

    # ---------------------------------------------------------- 去重库
    def _load_found(self):
        try:
            with open(self.found_path, encoding="utf-8") as fh:
                data = json.load(fh)
            now = time.time()
            for it in data.get("found") or []:
                if now - float(it.get("ts", 0)) < 3 * 86400:
                    # JSON 落盘后 color 会变回 list；PIL draw_ink 只认 int/tuple，
                    # list 直接传给 view._marker 会 TypeError（2026-10-11 启动崩溃根因）。
                    c = it.get("color")
                    it["color"] = tuple(c) if isinstance(c, (list, tuple)) else None
                    self.found.append(it)
        except Exception:
            pass

    def _save_found(self):
        try:
            os.makedirs(os.path.dirname(self.found_path), exist_ok=True)
            tmp = self.found_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"found": self.found[-800:]}, fh, ensure_ascii=False)
            os.replace(tmp, self.found_path)
        except OSError:
            pass

    def _is_new(self, name, dim, x, z):
        d2 = self.sigs.dedupe_blocks ** 2
        for it in self.found:
            if it.get("type") != name or it.get("dim") != dim:
                continue
            dx = float(it.get("x", 0)) - x
            dz = float(it.get("z", 0)) - z
            if dx * dx + dz * dz < d2:
                return False
        return True

    # ---------------------------------------------------------- 轮询
    def _read_index_safe(self, safe):
        p = os.path.join(self.root, "index_%s.json" % safe)
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None

    def _read_index(self, dim):
        return self._read_index_safe(safe_dim(dim))

    def poll(self, dims=None, max_scans=240):
        """扫一轮新落盘的区块，返回新的命中列表。"""
        if not self.enabled:
            return []
        t0 = time.perf_counter()
        out = []
        self.scans += 1
        n_chunks = 0
        dims = dims or self._list_dims()
        for dim in dims:
            idx = self._read_index(dim)
            if not idx:
                continue
            sid = int(idx.get("sid", 0))
            regions = idx.get("regions") or {}
            st = self.dims.get(dim)
            if st is None:
                # 第一次见到这个维度：正常扫（历史区块全部算"脏"，正好当基线）
                st = {"sid": sid, "regions": {}}
                self.dims[dim] = st
            elif st["sid"] != sid:
                # 换了一局游戏。模组的 region 版本号会重排，如果按"版本号变了就重扫"
                # 处理，主线程要卡十几秒，而且会重放历史。这里直接把当前版本号当新基线。
                # **不清空** hist：旧的区块文件还躺在磁盘上，数据依然有效，留着才能
                # 保证 5x5 判定窗口完整。之后玩家真正加载的新区块一样会顶起版本号。
                st["sid"] = sid
                st["regions"] = {k: v for k, v in regions.items() if "," in k}
                continue
            dirty = []
            for key, rev in regions.items():
                try:
                    rx, rz = key.split(",")
                    rx, rz = int(rx), int(rz)
                except ValueError:
                    continue
                if st["regions"].get(key, -1) != rev:
                    dirty.append((rx, rz))
                st["regions"][key] = rev
            if not dirty:
                continue
            # 新脏的 region 优先（版本号变化 ≈ 玩家刚跑过）
            for rx, rz in dirty:
                if n_chunks >= max_scans:
                    break
                n_chunks += self._scan_region(dim, rx, rz, out)
        self.chunks += n_chunks
        self.last_ms = (time.perf_counter() - t0) * 1000.0
        if out:
            self.hits = (out + self.hits)[:6]
        return out

    def _list_dims(self):
        try:
            if self.dims:
                return sorted(self.dims)
        except Exception:
            pass
        return self._scan_dims()

    def _scan_dims(self):
        """chunks 下的维度目录 -> **真实维度 id**。

        注意目录名是被洗过字符的（minecraft:the_end -> minecraft_the_end），
        不能直接当维度 id 用：上层要靠 "minecraft:the_end" 去 Xaero 那边对图。
        真名就记在 index 文件的 dim 字段里。
        """
        out = []
        base = os.path.join(self.root, "chunks")
        try:
            names = os.listdir(base)
        except OSError:
            return []
        for name in names:
            if not os.path.isdir(os.path.join(base, name)):
                continue
            idx = self._read_index_safe(name)
            real = (idx or {}).get("dim")
            out.append(real if real else name)
        return out

    def _scan_region(self, dim, rx, rz, out):
        # 目录名里维度 id 已被 mod 洗过（':' -> '_'），要从 index 反查回真名
        safe = safe_dim(dim)
        d = os.path.join(self.root, "chunks", safe, "r%d" % rx, "r%d" % rz)
        try:
            entries = list(os.scandir(d))
        except OSError:
            return 0
        n = 0
        todo = []
        for e in entries:
            if not e.name.endswith(".bin"):
                continue
            base = e.name[:-4]
            a, _, b = base.partition("_")
            try:
                cx, cz = int(a), int(b)
            except ValueError:
                continue
            key = (dim, cx, cz)
            if key in self.hist:
                continue
            todo.append((key, e.path, cx, cz))
            n += 1
            if n >= 400:
                break
        if not todo:
            return 0
        for key, path, cx, cz in todo:
            h = parse_chunk(path)
            self.hist[key] = h if h else Counter()
        self._evaluate(dim, [(cx, cz) for _k, _p, cx, cz in todo], out)
        return n

    # ---------------------------------------------------------- 判定
    def _window_hist(self, dim, ccx, ccz, r):
        h = Counter()
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                c = self.hist.get((dim, ccx + dx, ccz + dz))
                if c:
                    h.update(c)
        return h

    def _evaluate(self, dim, cells, out):
        r = self.sigs.window // 2
        seen = set()
        for ccx, ccz in cells:
            c0 = (ccx // 2, ccz // 2)      # 每 2x2 chunk 只判一次，省一半开销
            if c0 in seen:
                continue
            seen.add(c0)
            wcx, wcz = c0[0] * 2, c0[1] * 2
            hist = self._window_hist(dim, wcx, wcz, r)
            if not hist:
                continue
            got = self.sigs.classify(hist)
            if not got:
                continue
            name, purity, details = got
            # 命中中心取「特征方块的重心」，比窗口中心准得多
            xs = []
            zs = []
            s = self.sigs._sets[name]
            o = r
            for dx in range(-o, o + 1):
                for dz in range(-o, o + 1):
                    c = self.hist.get((dim, wcx + dx, wcz + dz))
                    if not c:
                        continue
                    hit = sum(v for k, v in c.items() if k in s)
                    if hit:
                        xs += [wcx + dx] * hit
                        zs += [wcz + dz] * hit
            cxb = (sum(xs) / len(xs) * 16 + 8) if xs else wcx * 16 + 8
            czb = (sum(zs) / len(zs) * 16 + 8) if zs else wcz * 16 + 8
            cxb, czb = int(cxb), int(czb)
            if not self._is_new(name, dim, cxb, czb):
                continue
            meta = self.sigs.types[name]
            # sound 必须带上：提醒层靠它「听声辨遗迹」。漏了会全部退化成默认音，
            # 三种遗迹听起来一模一样（真机冒烟测试抓到过）。
            it = {"type": name, "dim": dim, "x": cxb, "z": czb,
                  "pure": round(purity, 3), "icon": meta["icon"],
                  "color": meta["color"], "sound": meta["sound"],
                  "at": time.strftime("%H:%M:%S"),
                  "ts": time.time(),
                  "detail": {k.replace("minecraft:", ""): v
                             for k, v in sorted(details.items(), key=lambda kv: -kv[1])}}
            self.found.append(it)
            self._save_found()
            out.append(it)

    def status(self):
        if not self.enabled:
            return "遗迹识别未启用（%s）" % (self.sigs.error or "无指纹表")
        return "遗迹识别 %d类 已扫%d chunk %.0fms" % (
            len(self.sigs.types), self.chunks, self.last_ms)


if __name__ == "__main__":
    import sys
    w = RuinWatcher()
    print(w.status())
    print("指纹:", ", ".join(w.sigs.types) or "(空)")
    dims = sys.argv[1:] or None
    hits = w.poll(dims, max_scans=100000)
    print("命中 %d 处" % len(hits))
    for h in hits:
        print("   %-8s (%7d,%7d) 维度=%s 纯度=%.3f %s"
              % (h["type"], h["x"], h["z"], h["dim"], h["pure"], h["detail"]))
