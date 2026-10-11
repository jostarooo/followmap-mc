# -*- coding: utf-8 -*-
"""遗迹识别的离线验证。

分两段：
  A) **判定逻辑**：把 structures_DIM1.json 里全部 1274 个真实候选簇
     直接喂给 Signatures.classify，和「独立真值」比精度/召回。
     真值 = 与分类器**无关**的余弦相似度（参考向量取文档里记录的真实实例实测
     方块数），>= COS_TRUTH 即认定该簇是这类遗迹。用余弦而不是「模板阈值」当
     真值，是为了避免「用同一套标准互相证明」。
     同时扫一遍 min_purity，把标定过程本身留档。
  B) **整条链路**：把 Xaero region 数据反向合成为 mod 的 chunk .bin +
     index_<dim>.json，真跑一遍 RuinWatcher，验证「扫目录 -> 解析 -> 窗口判定
     -> 去重 -> 报警」整条链路，并检查有没有误报。

用法：
    python _modtest/test_ruins.py            # A + B
    python _modtest/test_ruins.py a          # 只跑 A（秒级）
"""
import json
import os
import shutil
import struct
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
sys.path.insert(0, HERE)

from followmap.ruins import RuinWatcher, Signatures, safe_dim, NATURAL  # noqa: E402

DIM1 = os.path.join(APP, "structures_DIM1.json")

# 参考向量：文档里记录的真实实例实测方块数（与 followmap/ruins.py 的 docstring 一致）。
# 只当「真值」用，不参与识别；换成余弦是为了和分类器的「锚点+纯度」完全解耦。
REF = {
    "白金星殿": {
        "minecraft:stone_brick_stairs": 97,
        "minecraft:infested_stone_bricks": 93,
        "minecraft:mossy_cobblestone_stairs": 81,
        "minecraft:mossy_stone_brick_stairs": 40,
        "minecraft:smooth_stone_slab": 30,
        "minecraft:smooth_quartz_stairs": 27,
        "minecraft:red_wool": 18,
    },
    "武士的修行地": {
        "minecraft:end_stone_bricks": 380,
        "minecraft:netherrack": 370,
        "minecraft:polished_basalt": 95,
        "minecraft:crimson_planks": 68,
    },
    "巫师的圣修所": {
        "minecraft:polished_blackstone_bricks": 440,
        "minecraft:blackstone": 210,
        "minecraft:cracked_polished_blackstone_bricks": 115,
        "minecraft:deepslate_bricks": 65,
    },
}
COS_TRUTH = 0.90          # 余弦 >= 0.90 才算真值（高纯度，宁缺毋滥）


def _cos(hist, ref):
    num = sum(hist.get(k, 0) * v for k, v in ref.items())
    if not num:
        return 0.0
    na = sum(v * v for v in hist.values()) ** 0.5
    nb = sum(v * v for v in ref.values()) ** 0.5
    return num / (na * nb) if na and nb else 0.0


def _truth_of(b):
    """给一个簇打上独立真值标签（取余弦最高且过线的那一类）。"""
    best, bn = 0.0, None
    for name, ref in REF.items():
        c = _cos(b, ref)
        if c > best:
            best, bn = c, name
    return (bn, best) if best >= COS_TRUTH else (None, best)


def _fmt_detail(kv):
    """命中明细里 `%方块` 是**占比**（0~1 的小数），其余是计数。

    占比必须按小数打：`%d` 会把 0.26 截成 0，看起来像"占比判据没生效"，
    而占比正是抗地形淹没的核心量，显示成 0 会直接误导排查（真机复现过）。
    """
    k, v = kv
    return "%s=%.2f" % (k, v) if k.startswith("%") else "%s=%d" % (k, v)


def _detail_top(det, n=3):
    """取前 n 项明细用于打印：**先列占比**（抗淹没的关键量，值小容易被计数挤掉），
    再按计数从大到小补足。返回可直接喂给 _fmt_detail 的 (短名, 值) 列表。"""
    rs = [(k, v) for k, v in det.items() if k.startswith("%")]
    cs = sorted(((k, v) for k, v in det.items() if not k.startswith("%")),
                key=lambda kv: -kv[1])
    return [(k.replace("minecraft:", ""), v) for k, v in (rs + cs)[:n]]


def part_a():
    sigs = Signatures()
    data = json.load(open(DIM1, encoding="utf-8"))
    cl = data["clusters"]

    # 先给每个簇定独立真值
    truth = {k: set() for k in REF}
    for c in cl:
        b = dict(c["blocks"])
        nm, _c = _truth_of(b)
        if nm:
            truth[nm].add(tuple(c["center"]))

    print("=" * 78)
    print("A) 判定逻辑 vs 独立真值（余弦>=%.2f，全部 %d 个候选簇）" % (COS_TRUTH, len(cl)))
    print("=" * 78)
    for name in REF:
        print("   真值 %-8s : %3d 处" % (name, len(truth[name])))
    print("   真值合计 %d 处（占全部 %.1f%%）"
          % (sum(len(v) for v in truth.values()),
             100.0 * sum(len(v) for v in truth.values()) / len(cl)))

    def run(purity_override=None, red_wool_override=None):
        """按给定阈值跑一遍（不改磁盘配置）。

        返回 (tp, loose, mismatch)：
          tp       —— 真值(cod>=COS_TRUTH)且被判对
          loose    —— 判为某类、且独立余弦的**最高归属就是这一类**，但余弦 < COS_TRUTH
                      （= 同类的小尺寸/变形实例，不是误报，只是没典型到 0.90）
          mismatch —— 判为 A 类、但独立余弦最高归属是 B 类（= 真正的类型混淆，必须为 0）
        """
        old_p = sigs.min_purity
        if purity_override is not None:
            sigs.min_purity = purity_override
        old_rw = None
        if red_wool_override is not None:
            old_rw = sigs.types["白金星殿"]["anchors"]["minecraft:red_wool"]
            sigs.types["白金星殿"]["anchors"]["minecraft:red_wool"] = red_wool_override
        tp = {k: 0 for k in REF}
        loose = 0
        mismatch = []
        for c in cl:
            b = dict(c["blocks"])
            nm, cos = _truth_of(b)          # nm 为 None 表示余弦没过线
            bestn, bestc = None, 0.0
            for k, ref in REF.items():
                cc = _cos(b, ref)
                if cc > bestc:
                    bestc, bestn = cc, k
            # 用与线上完全相同的判据（Signatures.passes），不在这里重写一遍阈值
            passed = [n for n in sigs.types if sigs.passes(n, b)[0]]
            if not passed:
                continue
            if nm and nm in passed:
                tp[nm] += 1
            if nm is None and len(passed) == 1 and passed[0] == bestn:
                loose += 1
            bad = [p for p in passed if p != bestn or (nm and nm != p)]
            for p in bad:
                mismatch.append((p, tuple(c["center"]), round(bestc, 3), bestn))
        sigs.min_purity = old_p
        if old_rw is not None:
            sigs.types["白金星殿"]["anchors"]["minecraft:red_wool"] = old_rw
        return tp, loose, mismatch

    print()
    print("   min_purity   red_wool   白金星殿          武士的修行地        巫师的圣修所      同类   混淆")
    print("   " + "-" * 84)
    for rw in (5, 3):
        for p in (0.72, 0.76, 0.80, 0.84, 0.86, 0.90):
            tp, loose, mm = run(p, rw)
            cells = []
            for name in REF:
                t = len(truth[name])
                cells.append("%3d/%3d=%5.1f%%" % (tp[name], t, 100.0 * tp[name] / max(1, t)))
            star = "  <=" if (rw == 3 and abs(p - sigs.min_purity) < 1e-9) else ""
            print("   %.2f         %d        %s  %3d   %3d%s"
                  % (p, rw, "  ".join(cells), loose, len(mm), star))
        print()

    # 采用配置的最终结论
    tp, loose, mm = run()
    print("   当前 ruins.json（min_purity=%.2f, red_wool=%d）:"
          % (sigs.min_purity,
             sigs.types["白金星殿"]["anchors"]["minecraft:red_wool"]))
    for name in REF:
        t = len(truth[name])
        print("      %-8s 召回 %3d/%3d = %5.1f%%" % (name, tp[name], t,
                                                    100.0 * tp[name] / max(1, t)))
    print("      另判为同类的非典型实例 %d 处（余弦 0.84~0.90，不是误报）" % loose)
    print("      类型混淆 %d 处%s" % (len(mm), " <== 必须为 0" if mm else "（零混淆）"))
    for name, ctr, c, bn in mm[:8]:
        print("        判为 %-8s 实为 %-8s (%8d,%8d) cos=%.3f" % (name, bn, ctr[0], ctr[1], c))
    ok = (not mm) and all(tp[n] >= 0.85 * len(truth[n]) for n in REF)
    print()
    print("   A 段结论:", "零类型混淆，各类召回 >=85%，通过" if ok else "有问题，见上")
    return 0 if ok else 2


# ------------------------------------------------------------------ B 段
def synth_home(home, dim, regions):
    """把 Xaero region 数据反合成 mod 的落盘格式，用于端到端验证。

    保真度要点：Xaero 解析出来的是 **BlockState 字符串**（带 `[facing=...]` 后缀），
    而模组写的是 `RegistryKey.toString()`，即**裸方块名**。这里必须剥掉状态后缀，
    否则合成出来的数据比真实落盘"更细"，判定会整片失败（实测过）。
    """
    import xaero_region as XR
    V = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14"
    WM = os.path.join(V, "XaeroWorldMap", "Multiplayer_mcfkcs.com")
    safe = safe_dim(dim)
    base = os.path.join(home, "chunks", safe)
    reg_rev = {}
    n = 0
    for rx, rz in regions:
        p = os.path.join(WM, dim, "mw$default", "%d_%d.zip" % (rx, rz))
        if not os.path.exists(p):
            continue
        try:
            rd = XR.parse_region_file(p)
        except Exception:
            continue
        d = os.path.join(base, "r%d" % rx, "r%d" % rz)
        os.makedirs(d, exist_ok=True)
        # 按 16x16 分块落盘
        grid = {}
        for (dx, dz), st in rd.blocks.items():
            nm = st.split("[")[0]          # BlockState -> 裸方块名（与模组一致）
            cx, cz = rx * 32 + dx // 16, rz * 32 + dz // 16
            g = grid.get((cx, cz))
            if g is None:
                g = grid[(cx, cz)] = {}
            g[(dx % 16, dz % 16)] = nm
        for (cx, cz), cells in grid.items():
            pal = []
            idx = []
            palmap = {}
            ys = []
            for z in range(16):
                for x in range(16):
                    nm = cells.get((x, z))
                    if nm is None or nm in NATURAL:
                        idx.append(0xFFFF)
                        ys.append(-32768)
                        continue
                    k = palmap.get(nm)
                    if k is None:
                        k = len(pal)
                        palmap[nm] = k
                        pal.append(nm)
                    idx.append(k)
                    ys.append(64)
            body = bytearray()
            body += struct.pack("<IHHiiH", 0x31424243, 1, 0, cx, cz, len(pal))
            for s in pal:
                u = s.encode("utf-8")
                body += struct.pack("<H", len(u)) + u
            body += struct.pack("<256h", *ys)
            body += struct.pack("<256H", *idx)
            with open(os.path.join(d, "%d_%d.bin" % (cx, cz)), "wb") as f:
                f.write(bytes(body))
            n += 1
        reg_rev["%d,%d" % (rx, rz)] = 1
    with open(os.path.join(home, "index_%s.json" % safe), "w", encoding="utf-8") as f:
        json.dump({"dim": dim, "sid": 1, "rev": 1, "t": time.time() * 1000,
                   "chunks": n, "regions": reg_rev}, f)
    return n


# ------------------------------------------------------------------ 公共小工具
def _win_cos(w, sigs, hit):
    """取某处命中所在窗口的直方图，返回 (独立余弦归属类型, 余弦值)。"""
    r = sigs.window // 2
    wcx, wcz = int(hit["x"]) // 16 // 2 * 2, int(hit["z"]) // 16 // 2 * 2
    hh = Counter()
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            c = w.hist.get((hit["dim"], wcx + dx, wcz + dz))
            if c:
                hh.update(c)
    bestn, bestc = "", 0.0
    for name, ref in REF.items():
        c = _cos(hh, ref)
        if c > bestc:
            bestc, bestn = c, name
    return bestn, bestc


def part_b():
    data = json.load(open(DIM1, encoding="utf-8"))
    cl = data["clusters"]
    truth = {k: [] for k in REF}
    for c in cl:
        b = dict(c["blocks"])
        nm, _cos_v = _truth_of(b)
        if nm:
            truth[nm].append((c["center"][0], c["center"][1]))

    # 取每个真值簇所在 region
    pick = []
    for name in REF:
        for x, z in truth[name][:2]:
            pick.append((x // 512, z // 512))
    # 再加几个「只含别的小遗迹」的负样本 region
    neg = []
    for c in sorted(cl, key=lambda c: -c["count"]):
        x, z = c["center"]
        if (x // 512, z // 512) in pick:
            continue
        b = dict(c["blocks"])
        if _truth_of(b)[0]:
            continue
        neg.append((x // 512, z // 512))
        if len(neg) >= 6:
            break
    regions = sorted(set(pick + neg))
    rset = set(regions)

    # 召回口径的真值：只算「真的被合成进 home 的那些 region 里」的全部同类真值簇
    truth_all = {k: [] for k in REF}
    for name in REF:
        for x, z in truth[name]:
            if (x // 512, z // 512) in rset:
                truth_all[name].append((x, z))
    total_truth = sum(len(v) for v in truth_all.values())

    home = os.path.join(HERE, "_ruinhome")
    shutil.rmtree(home, ignore_errors=True)
    os.makedirs(home, exist_ok=True)
    t0 = time.time()
    print("=" * 78)
    print("B) 端到端：把 %d 个 region 反合成 mod 落盘格式，真跑 RuinWatcher" % len(regions))
    print("=" * 78)
    n = synth_home(home, "DIM1", regions)
    print("   合成 %d 个 chunk 文件，用时 %.1fs" % (n, time.time() - t0))

    sigs = Signatures()
    found = os.path.join(HERE, "_ruinhome_found.json")
    try:
        os.remove(found)          # 去重库必须清空，否则上一轮的命中会被全部跳过
    except OSError:
        pass
    w = RuinWatcher(root=home, found_path=found)
    t0 = time.time()
    hits = w.poll(["DIM1"], max_scans=1000000)
    dt = time.time() - t0
    print("   扫描 + 判定 %.2fs  文件数=%d  命中 %d 处" % (dt, n, len(hits)))

    okh = 0
    for h in sorted(hits, key=lambda h: h["type"]):
        best = 1e18
        for x, z in truth.get(h["type"], []):
            d = (x - h["x"]) ** 2 + (z - h["z"]) ** 2
            if d < best:
                best = d
        dist = int(best ** 0.5)
        # 独立校验：这处命中的窗口，余弦归属是哪一类？
        cx, cz = _win_cos(w, sigs, h)
        same = (cx == h["type"])
        flag = "OK " if dist <= 96 else ("同类" if same else "!! ")
        if dist <= 96:
            okh += 1
        print("   %s %-8s (%7d,%7d) 纯度%.2f 距同类真值%4d格 独立余弦归属=%s(%.2f)"
              % (flag, h["type"], h["x"], h["z"], h["pure"], dist, cx, cz))
    print("   （标记「同类」= 不在保守真值集里，但独立余弦也归到同一类：同族变形实例，非误报）")
    wrong = [h for h in hits if _win_cos(w, sigs, h)[0] != h["type"]]

    # 召回口径：合成区域里**全部**同类真值簇，有多少在 96 格内被命中
    print()
    print("   召回（区域内全部真值簇，命中半径 96 格）：")
    total_rec = 0
    for name in REF:
        t = truth_all[name]
        if not t:
            continue
        got = 0
        for x, z in t:
            if any((x - h["x"]) ** 2 + (z - h["z"]) ** 2 <= 96 * 96
                   for h in hits if h["type"] == name):
                got += 1
        total_rec += got
        print("      %-8s %3d/%3d = %5.1f%%" % (name, got, len(t), 100.0 * got / len(t)))
    print("      合计     %3d/%3d = %5.1f%%"
          % (total_rec, total_truth, 100.0 * total_rec / max(1, total_truth)))
    print()
    print("   B 段结论: 命中 %d 处；对得上保守真值 %d 处；独立余弦归属不一致（真误报）%d 处"
          % (len(hits), okh, len(wrong)))
    shutil.rmtree(home, ignore_errors=True)
    try:
        os.remove(found)
    except OSError:
        pass
    return 0 if hits and not wrong else 2


# ------------------------------------------------------------------ C 段
def part_c(n_region=100):
    """大规模真实窗口压力测试：直接解析 Xaero region，跑真实判定，统计误报。

    为什么值得单独跑：A 段用的是 structures_DIM1.json 里**被截断成前 10 项**的直方图，
    纯度会被系统性高估；B 段只覆盖 6 个 region。C 段用**完整的真实区块直方图**，
    在几十个 region、上万个 5x5 窗口上跑，才能说清"到底会不会误报"。
    """
    import random
    import xaero_region as XR
    V = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14"
    WM = os.path.join(V, "XaeroWorldMap", "Multiplayer_mcfkcs.com")
    src = os.path.join(WM, "DIM1", "mw$default")
    allreg = []
    for f in os.listdir(src):
        if f.endswith(".zip"):
            a, _, b = f[:-4].partition("_")
            try:
                allreg.append((int(a), int(b)))
            except ValueError:
                pass
    if not allreg:
        print("C) 跳到：找不到 Xaero region")
        return 0

    data = json.load(open(DIM1, encoding="utf-8"))
    cl = data["clusters"]
    truth = {k: [] for k in REF}
    for c in cl:
        b = dict(c["blocks"])
        nm, _c = _truth_of(b)
        if nm:
            truth[nm].append((c["center"][0], c["center"][1]))
    need = set()
    for name in REF:
        for x, z in truth[name]:
            need.add((x // 512, z // 512))
    pos = sorted(need & set(allreg))
    rest = sorted(set(allreg) - need)
    random.seed(7)
    random.shuffle(rest)
    regions = pos + rest[:max(0, n_region - len(pos))]

    print("=" * 78)
    print("C) 真实窗口压力测试：%d 个 region（含真值的 %d 个 + 随机 %d 个）"
          % (len(regions), len(pos), len(regions) - len(pos)))
    print("=" * 78)
    sigs = Signatures()
    w = RuinWatcher(root=os.path.join(HERE, "_c_nohome"),
                    found_path=os.path.join(HERE, "_c_found.json"))
    try:
        os.remove(os.path.join(HERE, "_c_found.json"))
    except OSError:
        pass
    w.sigs = sigs
    w.enabled = True

    out = []
    nwin = 0
    t0 = time.time()
    for i, (rx, rz) in enumerate(regions):
        p = os.path.join(src, "%d_%d.zip" % (rx, rz))
        try:
            rd = XR.parse_region_file(p)
        except Exception:
            continue
        grid = {}
        for (dx, dz), st in rd.blocks.items():
            nm = st.split("[")[0]
            if nm in NATURAL:
                continue
            cx, cz = rx * 32 + dx // 16, rz * 32 + dz // 16
            g = grid.get((cx, cz))
            if g is None:
                g = grid[(cx, cz)] = Counter()
            g[nm] += 1
        for k, v in grid.items():
            w.hist[("DIM1", k[0], k[1])] = v
        cells = list(grid.keys())
        nwin += len(cells)
        w._evaluate("DIM1", cells, out)
        if (i + 1) % 20 == 0:
            print("   ... %d/%d region，命中累计 %d" % (i + 1, len(regions), len(out)))
    dt = time.time() - t0

    print("   解析 %d 个 region / %.1fs；参与判定的 chunk %d 个，命中 %d 处"
          % (len(regions), dt, nwin, len(out)))
    print()
    per = {k: 0 for k in REF}
    wrong = []
    for h in out:
        per[h["type"]] += 1
        bn, bc = _win_cos(w, sigs, h)
        if bn != h["type"]:
            wrong.append((h, bn, bc))
    print("   命中分布:", {k: v for k, v in per.items()})
    print("   独立余弦归属不一致（真误报）: %d 处" % len(wrong))
    for h, bn, bc in wrong[:10]:
        print("      判为 %-8s 实为 %-8s (%8d,%8d) cos=%.2f 纯度%.2f"
              % (h["type"], bn, h["x"], h["z"], bc, h["pure"]))
    if len(wrong) > 10:
        print("      ... 其余 %d" % (len(wrong) - 10))
    print()
    print("   C 段结论:", "零类型误报" if not wrong else "存在 %d 处类型误报" % len(wrong))
    try:
        os.remove(os.path.join(HERE, "_c_found.json"))
    except OSError:
        pass
    return 0 if not wrong else 2


# ------------------------------------------------------------------ D 段
def part_d():
    """真机数据：直接扫 ~/.coordbridge/chunks 里**真实落盘**的区块文件。

    前面的 A/B/C 都基于 Xaero 地图数据回推，这一段是玩家真跑出来的东西
    （模组自己写的 .bin），也是唯一能证明「模组写的格式 Python 侧真能读懂」的一环。
    """
    home = os.path.join(os.path.expanduser("~"), ".coordbridge")
    base = os.path.join(home, "chunks")
    if not os.path.isdir(base):
        print("D) 跳过：没有 %s" % base)
        return 0
    print("=" * 78)
    print("D) 真机落盘数据：%s" % base)
    print("=" * 78)
    tmp = os.path.join(HERE, "_d_found.json")
    try:
        os.remove(tmp)
    except OSError:
        pass
    w = RuinWatcher(root=home, found_path=tmp)
    dims = w._scan_dims()
    nbin = 0
    for dim in dims:
        for root, _d, fs in os.walk(os.path.join(base, safe_dim(dim))):
            nbin += sum(1 for f in fs if f.endswith(".bin"))
    print("   维度 %d 个，区块文件 %d 个" % (len(dims), nbin))
    t0 = time.time()
    hits = w.poll(dims, max_scans=10 ** 9)
    print("   扫描 %.1fs  解析 %d 个区块  命中 %d 处" % (time.time() - t0, w.chunks, len(hits)))
    per = Counter(h["type"] for h in hits)
    print("   命中分布:", dict(per))
    # 独立校验：每处命中所在窗口的余弦归属必须与判定类型一致（否则就是类型误报），
    # 并把家族合计打出来——2026-10-09 的武士漏检就是靠这一列定位的
    wrong = []
    fam = {"end_brick": ["minecraft:end_stone_bricks", "minecraft:end_stone_brick_wall",
                         "minecraft:end_stone_brick_stairs", "minecraft:end_stone_brick_slab"],
           "stone_brick": ["minecraft:stone_bricks", "minecraft:stone_brick_stairs"],
           "crimson": ["minecraft:crimson_planks", "minecraft:crimson_hyphae",
                       "minecraft:crimson_slab", "minecraft:crimson_nylium"]}
    r = w.sigs.window // 2
    for h in sorted(hits, key=lambda h: (h["type"], h["x"])):
        wcx, wcz = int(h["x"]) // 16 // 2 * 2, int(h["z"]) // 16 // 2 * 2
        hh = Counter()
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                c = w.hist.get((h["dim"], wcx + dx, wcz + dz))
                if c:
                    hh.update(c)
        bn, bc = "", 0.0
        for nm, ref in REF.items():
            cc = _cos(hh, ref)
            if cc > bc:
                bc, bn = cc, nm
        good = (bn == h["type"])
        if not good:
            wrong.append((h, bn, bc))
        print("      %s %-8s (%7d,%7d) 纯度%.2f 独立余弦=%s(%.2f) %s"
              % ("OK " if good else "!! ", h["type"], h["x"], h["z"], h["pure"],
                 bn, bc, " ".join(_fmt_detail(kv) for kv in _detail_top(h["detail"]))))
        print("           家族: %s"
              % {k: sum(hh.get(b, 0) for b in v) for k, v in fam.items()
                 if sum(hh.get(b, 0) for b in v)})
    print("   独立余弦归属不一致（类型误报）: %d 处" % len(wrong))
    for h, bn, bc in wrong[:8]:
        print("      判为 %-8s 实为 %-8s (%7d,%7d) cos=%.2f"
              % (h["type"], bn, h["x"], h["z"], bc))
    # 与 structures_DIM1.json 的覆盖范围对照（说明差异来自数据范围，不是误报）
    data = json.load(open(DIM1, encoding="utf-8"))
    cl = data["clusters"]
    xs = [c["center"][0] for c in cl]
    zs = [c["center"][1] for c in cl]
    print("   参考集 structures_DIM1.json: %d 簇，x %d..%d  z %d..%d"
          % (len(cl), min(xs), max(xs), min(zs), max(zs)))
    inside = sum(1 for h in hits if min(xs) <= h["x"] <= max(xs) and min(zs) <= h["z"] <= max(zs))
    print("   其中落在参考集坐标范围内的 %d 处（其余在参考集未扫描的坐标区，无法对照）" % inside)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return 0 if hits and not wrong else 2


# ------------------------------------------------------------------ E 段
# 2026-10-09 用户报「旁边的武士遗迹没有检测出来」时，从真机数据里抠出来的窗口。
# 这几条把"锚点必须写成家族合计"这个结论固化下来：
#   · 4 个真实武士实例的「末地石砖系」总量稳定 64~67，但 end_stone_bricks 只有 15，
#     旧指纹要求 >=90 -> 全漏；
#   · 有个实例 polished_basalt 只有 11，旧阈值 20 -> 也漏。
# 用例里的直方图是从真机窗口原样抄下来的（只抄了 topN，总数与现场略有出入，
# 但判定结论一致），任何一条从"期望"变成"漏"都说明指纹表又被钉死在单方块上了。
#
# 2026-10-10 用户又报「两个武士遗迹没检测到」，追加 4 条（两正两负），把两条结论钉住：
#   · 【可变构件不能进 anchors】武士的 netherrack / polished_basalt 会被地形全埋
#     （实测 netherrack=9~10、polished_basalt=0），任何把这些钉进 anchors 的写法必漏；
#   · 【恒定构件合计是安全分离面】@samurai_core = 116~197（第 18 名 66），阈值 90 兜底，
#     且 core 刻意不含 end_stone_bricks / nylium，靠两条负例（紫珀殿 / 幽匿殿）守住不串类。
#   武士这条走**绝对数**（不用占比），理由见 ruins.json 的 _note。
REGRESSION = [
    ("武士/典型（end_stone_bricks 仅 15，靠家族合计）", "武士的修行地", {
        "minecraft:netherrack": 139, "minecraft:end_stone_brick_wall": 38,
        "minecraft:polished_basalt": 31, "minecraft:nether_brick_wall": 30,
        "minecraft:warped_slab": 27, "minecraft:dirt": 22,
        "minecraft:soul_soil": 22, "minecraft:soul_sand": 21,
        "minecraft:crimson_slab": 18, "minecraft:end_stone_bricks": 15,
        "minecraft:crimson_planks": 13, "minecraft:crimson_hyphae": 13,
        "minecraft:end_stone_brick_stairs": 11, "minecraft:gilded_blackstone": 10,
        "minecraft:warped_nylium": 8,
        "minecraft:polished_blackstone_brick_slab": 8,
        "minecraft:crimson_nylium": 8, "minecraft:weeping_vines_plant": 8}),
    ("武士/变体（polished_basalt 仅 11）", "武士的修行地", {
        "minecraft:netherrack": 106, "minecraft:end_stone_brick_wall": 38,
        "minecraft:warped_slab": 27, "minecraft:crimson_nylium": 25,
        "minecraft:nether_brick_wall": 24, "minecraft:dirt": 22,
        "minecraft:crimson_slab": 18, "minecraft:end_stone_bricks": 15,
        "minecraft:crimson_planks": 13, "minecraft:crimson_hyphae": 13,
        "minecraft:end_stone_brick_stairs": 11, "minecraft:polished_basalt": 11,
        "minecraft:gilded_blackstone": 10}),
    ("白金/靠 @mossy 组命中（苔石楼梯换成苔石砖楼梯）", "白金星殿", {
        "minecraft:infested_stone_bricks": 168, "minecraft:stone_brick_stairs": 36,
        "minecraft:red_wool": 28, "minecraft:mossy_cobblestone_stairs": 8,
        "minecraft:mossy_stone_brick_stairs": 22, "minecraft:stone_bricks": 10,
        "minecraft:stone_brick_slab": 6, "minecraft:smooth_stone_slab": 30}),
    # 负例：巫师窗口里天然含 netherrack 90（够武士的 60），但一点末地石砖都没有
    ("巫师（含 netherrack 90，不得判成武士）", "巫师的圣修所", {
        "minecraft:polished_blackstone_bricks": 403, "minecraft:soul_soil": 300,
        "minecraft:blackstone": 173, "minecraft:polished_blackstone": 80,
        "minecraft:netherrack": 90, "minecraft:cracked_polished_blackstone_bricks": 63,
        "minecraft:deepslate_bricks": 30, "minecraft:basalt": 30,
        "minecraft:warped_nylium": 29}),
    # 负例：末地自然地形 + 零星人造，不该报任何一类
    ("散落人造方块（不该报）", None, {
        "minecraft:end_rod": 40, "minecraft:obsidian": 30,
        "minecraft:netherrack": 12, "minecraft:dirt": 10}),

    # ================= 2026-10-10 用户报「巫师漏检 / 被地形淹没」=================
    # 真机窗口原样搬进来（~/.coordbridge 里那一批）。淹没会让**所有绝对计数等比缩水**，
    # 所以这两个用例专门压「绝对数锚点」：blackstone 38 < 旧阈值 55、
    # deepslate_bricks 16 < 旧阈值 18 —— 旧判据在这两个上必漏。
    ("巫师/被淹没（blackstone 38、deepslate 16，旧判据必漏）", "巫师的圣修所", {
        "minecraft:polished_blackstone_bricks": 243,
        "minecraft:polished_blackstone_brick_stairs": 49,
        "minecraft:soul_soil": 39, "minecraft:blackstone": 38,
        "minecraft:cracked_polished_blackstone_bricks": 34,
        "minecraft:polished_blackstone_brick_wall": 27,
        "minecraft:polished_blackstone_slab": 24,
        "minecraft:polished_blackstone": 23, "minecraft:polished_deepslate": 21,
        "minecraft:deepslate_bricks": 16, "minecraft:cobbled_deepslate_slab": 16,
        "minecraft:blackstone_slab": 15, "minecraft:mud": 15,
        "minecraft:netherrack": 13, "minecraft:smooth_basalt": 11,
        "minecraft:polished_blackstone_brick_slab": 10, "minecraft:basalt": 8,
        "minecraft:polished_deepslate_wall": 8, "minecraft:obsidian": 6,
        "minecraft:soul_lantern": 5, "minecraft:sculk": 5}),
    # 同族的另一种淹没形态：主料占比掉到 0.33（新占比阈值 0.26 仍过）
    ("巫师/被淹没（露出比例低，主料占比 0.33）", "巫师的圣修所", {
        "minecraft:polished_blackstone_bricks": 276, "minecraft:blackstone": 126,
        "minecraft:soul_soil": 102, "minecraft:polished_blackstone": 62,
        "minecraft:cracked_polished_blackstone_bricks": 50,
        "minecraft:polished_blackstone_brick_stairs": 46,
        "minecraft:netherrack": 33, "minecraft:polished_deepslate": 21,
        "minecraft:mud": 17, "minecraft:polished_blackstone_brick_wall": 17,
        "minecraft:basalt": 15, "minecraft:cobbled_deepslate_slab": 14,
        "minecraft:deepslate_bricks": 14, "minecraft:warped_nylium": 11,
        "minecraft:polished_blackstone_slab": 9, "minecraft:obsidian": 9,
        "minecraft:smooth_basalt": 8, "minecraft:polished_deepslate_wall": 8,
        "minecraft:crying_obsidian": 6, "minecraft:dark_oak_fence": 4}),
    # 负例（真机噪声里最像巫师的那两个，必须继续排除）：
    #   ① 靠**占比**排除：pbrick 161（> 绝对下限），但主料占比只有 0.152；
    #   ② 靠**绝对下限**排除：主料占比不低但 pbrick 只有 69。
    #   两条新判据各被一个负例压住，缺一条就会放进来。
    ("负例·黑石要塞（pbrick 161 但主料占比仅 0.152）", None, {
        "minecraft:soul_soil": 310, "minecraft:blackstone": 181,
        "minecraft:polished_blackstone_bricks": 161, "minecraft:netherrack": 90,
        "minecraft:polished_blackstone": 84,
        "minecraft:polished_blackstone_brick_stairs": 58,
        "minecraft:polished_blackstone_brick_wall": 38,
        "minecraft:warped_nylium": 37, "minecraft:deepslate_bricks": 28,
        "minecraft:basalt": 28, "minecraft:cracked_polished_blackstone_bricks": 24,
        "minecraft:polished_blackstone_brick_slab": 21,
        "minecraft:polished_deepslate": 21}),
    ("负例·黑石小屋（占比不低但 pbrick 仅 69）", None, {
        "minecraft:blackstone": 215, "minecraft:polished_blackstone_bricks": 69,
        "minecraft:polished_blackstone": 63,
        "minecraft:polished_blackstone_brick_wall": 25,
        "minecraft:deepslate_bricks": 22, "minecraft:soul_soil": 22,
        "minecraft:polished_deepslate": 10,
        "minecraft:polished_blackstone_brick_stairs": 9,
        "minecraft:crying_obsidian": 7, "minecraft:polished_blackstone_slab": 6}),

    # ============ 2026-10-10 用户报「两个武士遗迹没检测到」(4744,-39224) ============
    # 地图 HUD 是 DIM1/$mem（模组落盘的区块直接渲染），所以窗口里的方块名 = 建筑
    # **高出地形基准(56/57)** 的那部分用料；低于地形基准的列写 NODATA，不出现在直方图里。
    # 这两座武士的**下界岩/磨制玄武岩被地形全埋**（netherrack=9~10、polished_basalt=0），
    # 旧指纹把 polished_basalt >= 5 钉在 anchors 上 -> 两座全漏。
    # 新判据用「@samurai_core 恒定构件合计 >= 90」这条通路接住：
    #   17 座武士实例的 @samurai_core = 116~197（第 18 名骤降到 66），阈值 90 很安全。
    # 注意：武士这条必须用**绝对数**，不能改成占比 —— 恒定构件在高处几乎不缩水，
    # 被埋的只是低处的下界岩/玄武岩；实测占比反而更差（武士 0.36~0.80，别类也有 0.66~1.14）。
    # 直方图从真机窗口原样抄下（只抄 topN，判定结论一致）。
    ("武士/被埋（下界岩9、磨制玄武岩0，旧 anchors 必漏）", "武士的修行地", {
        "minecraft:end_stone_brick_wall": 38, "minecraft:dirt": 33,
        "minecraft:nether_brick_wall": 30, "minecraft:warped_slab": 27,
        "minecraft:crimson_slab": 18, "minecraft:end_stone_bricks": 14,
        "minecraft:crimson_hyphae": 14, "minecraft:crimson_planks": 13,
        "minecraft:crimson_nylium": 13, "minecraft:end_stone_brick_stairs": 11,
        "minecraft:warped_nylium": 10, "minecraft:netherrack": 9,
        "minecraft:weeping_vines_plant": 8, "minecraft:warped_planks": 7,
        "minecraft:gilded_blackstone": 7, "minecraft:end_rod": 6,
        "minecraft:crimson_fence": 6, "minecraft:shroomlight": 2,
        "minecraft:warped_wart_block": 2, "minecraft:blackstone": 2,
        "minecraft:blackstone_stairs": 2, "minecraft:bone_block": 1}),
    ("武士/被埋（下界岩10、磨制玄武岩0，另一实例）", "武士的修行地", {
        "minecraft:end_stone_brick_wall": 38, "minecraft:dirt": 31,
        "minecraft:nether_brick_wall": 30, "minecraft:warped_slab": 27,
        "minecraft:crimson_slab": 18, "minecraft:end_stone_bricks": 14,
        "minecraft:crimson_hyphae": 14, "minecraft:crimson_planks": 13,
        "minecraft:crimson_nylium": 13, "minecraft:end_stone_brick_stairs": 11,
        "minecraft:netherrack": 10, "minecraft:warped_nylium": 9,
        "minecraft:gilded_blackstone": 8, "minecraft:weeping_vines_plant": 8,
        "minecraft:warped_planks": 7, "minecraft:end_rod": 6,
        "minecraft:crimson_fence": 6, "minecraft:shroomlight": 2,
        "minecraft:warped_wart_block": 2, "minecraft:blackstone": 2,
        "minecraft:blackstone_stairs": 2, "minecraft:bone_block": 2,
        "minecraft:soul_soil": 1}),
    # 两条负例压住「@samurai_core」不能靠末地石砖/菌岩蒙混：
    #   · 紫珀殿：末地石砖 68、紫珀系一大把，但**一个恒定构件都没有**（core=0）；
    #   · 幽匿殿：末地石砖 66、还真带 warped_slab 16 + nether_brick_fence 14，
    #     但 core 合计只有 ~40 出头，到不了 90。
    # 这两条把「武士 core 不含 end_stone_bricks、不含 nylium」这个边界钉死。
    ("负例·紫珀殿（末地石砖多但无恒定构件）", None, {
        "minecraft:purpur_block": 153, "minecraft:end_stone_bricks": 68,
        "minecraft:purpur_pillar": 53, "minecraft:purpur_stairs": 35,
        "minecraft:magenta_stained_glass": 23, "minecraft:obsidian": 13,
        "minecraft:crying_obsidian": 5, "minecraft:purpur_slab": 4,
        "minecraft:chain": 2}),
    ("负例·幽匿殿（有末地石砖与诡异台阶但不达标）", None, {
        "minecraft:sculk": 102, "minecraft:reinforced_deepslate": 72,
        "minecraft:end_stone_bricks": 66,
        "minecraft:polished_blackstone_stairs": 43,
        "minecraft:purpur_block": 38,
        "minecraft:polished_blackstone_brick_stairs": 36,
        "minecraft:purpur_pillar": 32, "minecraft:magenta_stained_glass": 24,
        "minecraft:red_nether_brick_wall": 16, "minecraft:warped_slab": 16,
        "minecraft:nether_brick_fence": 14, "minecraft:red_nether_brick_slab": 14,
        "minecraft:twisting_vines_plant": 14, "minecraft:warped_stairs": 13,
        "minecraft:cracked_deepslate_bricks": 10, "minecraft:cobbled_deepslate": 9,
        "minecraft:sculk_catalyst": 9, "minecraft:purpur_stairs": 8,
        "minecraft:weeping_vines_plant": 7,
        "minecraft:infested_chiseled_stone_bricks": 6,
        "minecraft:nether_brick_stairs": 4, "minecraft:purpur_slab": 2,
        "minecraft:infested_deepslate": 2, "minecraft:small_amethyst_bud": 1}),
]


def part_e():
    print("=" * 78)
    print("E) 回归用例：真机复现过的漏检（武士家族 / 武士恒定构件 / 巫师被地形淹没）")
    print("=" * 78)
    sigs = Signatures()
    print("   %-52s %-10s %-10s %s" % ("用例", "期望", "实得", ""))
    print("   " + "-" * 78)
    ok = True
    for desc, want, hist in REGRESSION:
        got = sigs.classify(Counter(hist))
        got_name = got[0] if got else None
        good = got_name == want
        ok = ok and good
        extra = ""
        if got:
            extra = "纯度%.2f %s" % (got[1],
                                     " ".join(_fmt_detail(kv) for kv in _detail_top(got[2])))
        print("   %-52s %-10s %-10s %s %s"
              % (desc, want or "(不报)", got_name or "(不报)",
                 "" if good else "<<< 不符", extra))
    print()
    print("   E 段结论:", "全部符合" if ok else "有不符（说明锚点又被钉回单个方块名了）")
    return 0 if ok else 2


if __name__ == "__main__":
    what = (sys.argv[1] if len(sys.argv) > 1 else "ab").lower()
    rc = 0
    if "a" in what:
        rc |= part_a()
        print()
    if "b" in what:
        rc |= part_b()
        print()
    if "c" in what:
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 100
        rc |= part_c(n)
        print()
    if "d" in what:
        rc |= part_d()
        print()
    if "e" in what:
        rc |= part_e()
    sys.exit(rc)
