# -*- coding: utf-8 -*-
"""在小地图/游戏画面上识别 Xaero 的坐标文本（MC 像素字体）——语法约束解码。

为什么不用通用 OCR
------------------
Xaero 的坐标行格式是**已知**的，例如 ``X: {x}, Y: {y}, Z: {z}``。
只有数字部分是变量，其余字面字符（``X: ``, `` , Y: ``…）的位置由前面数字的位数决定。
于是可以按「格式语法」逐段解码：字面段必须精确匹配，数字段只需在 0-9 里取 argmax。

特征：对角线方向导数
--------------------
MC 文字 = 同一颜色的字形 + 偏移 (d,d) 的 1/4 亮度阴影，所以
    D(x,y) = L(x,y) - L(x-d, y-d)
在字形笔画处强正、阴影处强负。这个特征与背景颜色几乎无关。

尺度：先把文字条按估计缩放 S 重采样回「1 像素 = 1 字体像素」（双线性采样、
对齐到字形栅格），再在规范尺度下匹配（advance = w+1，阴影偏移 d=1）。
这样连 Xaero 的可能非整数缩放也能处理。
"""
import os
import re
import sys
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
if APP not in sys.path:
    sys.path.insert(0, APP)

import mc_font as MF  # noqa: E402

DIGITS = "0123456789"

# 支持的坐标行格式。{n} = 带符号整数段。
FORMATS = [
    "X: {n}, Y: {n}, Z: {n}",
    "{n}, {n}, {n}",
    "X: {n} Y: {n} Z: {n}",
    "X: {n}, Z: {n}",
    "{n}, {n}",
    "XYZ: {n} / {n} / {n}",
    "XYZ: {n} {n} {n}",
    "X {n} Y {n} Z {n}",
]


# ---------------------------------------------------------------------------
def _to_gray(a):
    if a.ndim == 3:
        return (0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]).astype(np.float32)
    return a.astype(np.float32)


def _diag_diff(L, d=1):
    D = np.zeros_like(L)
    D[d:, d:] = L[d:, d:] - L[:-d, :-d]
    return D


# ---------------------------------------------------------------------------
class Templates:
    """一批字符在规范尺度(1 字体像素 = 1 图像像素)下的零均值单位范数模板。"""

    def __init__(self, chars):
        self.chars = [c for c in chars if (MF.table().get(c) or {}).get("w", 0) > 0]
        mats = []
        self.w = []
        for c in self.chars:
            info = MF.table()[c]
            w = info["w"]
            m = np.array(info["mask"], dtype=np.float32)[:, :w]
            t = np.zeros((9, w + 1), dtype=np.float32)
            t[:8, :w] = m
            t[1:, 1:] -= m
            t -= t.mean()
            mats.append(t)
            self.w.append(w)
        self.W = max(m.shape[1] for m in mats)
        self.H = 9
        st = np.zeros((len(mats), self.H, self.W), dtype=np.float32)
        for i, m in enumerate(mats):
            st[i, :, :m.shape[1]] = m
        self.flat = st.reshape(len(mats), -1)
        self.norms = np.sqrt((self.flat * self.flat).sum(axis=1))
        self.norms[self.norms < 1e-9] = 1e-9

    def index(self, ch):
        try:
            return self.chars.index(ch)
        except ValueError:
            return -1

    def score_one(self, patch, ch):
        i = self.index(ch)
        if i < 0:
            return -1.0
        return float(self._scores(patch)[i])

    def argmax(self, patch):
        s = self._scores(patch)
        i = int(np.argmax(s))
        return self.chars[i], float(s[i]), s

    def _scores(self, patch):
        p = patch.reshape(-1) - float(patch.mean())
        if p.size != self.flat.shape[1]:
            return np.full(len(self.chars), -1.0, dtype=np.float32)
        pn = float(np.sqrt((p * p).sum())) + 1e-9
        return (self.flat @ p) / (self.norms * pn)


# ---------------------------------------------------------------------------
def _mask_cols(ch):
    info = MF.table().get(ch)
    if not info or info["w"] <= 0:
        return None
    m = info["mask"]
    w = info["w"]
    cols = [c for c in range(w) if any(m[r][c] for r in range(8))]
    if not cols:
        return None
    return cols[0], cols[-1]


def _adv(ch):
    return MF.advance(ch, 1)


def _width(chars):
    return sum(_adv(c) for c in chars)


# ---------------------------------------------------------------------------
@dataclass
class OcrResult:
    ok: bool = False
    text: str = ""
    coords: tuple = None
    fmt: str = ""
    scale: float = 0.0
    score: float = 0.0
    box: tuple = None
    note: str = ""
    digits: tuple = None


class CoordOCR:
    def __init__(self, formats=None, max_digits=7, beam=10, min_score=0.60):
        self.formats = formats or FORMATS
        self.max_digits = max_digits
        self.beam = beam
        self.min_score = min_score
        self.dt = Templates(DIGITS)
        self.lit = Templates("0123456789-+.,:/ XYZ" + "abcdefghijklmnopqrstuvwxyz")
        self._lock = None          # (s, y0, x0_canon, fmt) 锁定参数

    # ================================================================ 采样
    @staticmethod
    def _sample(L, ox, oy, s, h, w):
        """在 L 上以 (ox,oy) 为原点、步长 s 双线性采样成 h x w 的规范图。"""
        H, W = L.shape
        yy = oy + np.arange(h, dtype=np.float32) * s
        xx = ox + np.arange(w, dtype=np.float32) * s
        y0 = np.clip(np.floor(yy).astype(np.int32), 0, H - 1)
        x0 = np.clip(np.floor(xx).astype(np.int32), 0, W - 1)
        y1 = np.clip(y0 + 1, 0, H - 1)
        x1 = np.clip(x0 + 1, 0, W - 1)
        fy = np.clip(yy - y0, 0, 1)[:, None]
        fx = np.clip(xx - x0, 0, 1)[None, :]
        top = L[y0][:, x0] * (1 - fx) + L[y0][:, x1] * fx
        bot = L[y1][:, x0] * (1 - fx) + L[y1][:, x1] * fx
        return top * (1 - fy) + bot * fy

    # ================================================================ 格式拆分
    @staticmethod
    def _segments(fmt):
        segs = []
        i = 0
        while i < len(fmt):
            if fmt.startswith("{n}", i):
                segs.append(("num", True))
                i += 3
            else:
                j = fmt.find("{n}", i)
                if j < 0:
                    j = len(fmt)
                segs.append(("lit", fmt[i:j]))
                i = j
        return segs

    # ================================================================ 解码
    def _decode(self, D, x_start, y0, segs, topk=8):
        """在 D（规范尺度）上按 segs 解码，返回候选列表
        [(mean, x_end, n_chars, text, digits), ...]，按平均分降序。
        """
        H, W = D.shape
        if y0 + 9 > H:
            return []
        states = [(x_start, "", 0.0, 0, ())]
        for kind, spec in segs:
            nxt = []
            for x, text, sc, n, dg in states:
                if kind == "lit":
                    cur = x
                    ok = True
                    okt = []
                    for ch in spec:
                        wdc = self.lit.W
                        if cur + wdc > W or y0 + 9 > H:
                            ok = False
                            break
                        info = MF.table().get(ch)
                        if info is None or info["w"] <= 0:
                            # 无字形（空格等）：按步进占位，不打分
                            okt.append(ch)
                            cur += _adv(ch)
                            continue
                        patch = D[y0:y0 + 9, cur:cur + wdc]
                        v = self.lit.score_one(patch, ch)
                        if v < 0.15:
                            ok = False
                            break
                        okt.append(ch)
                        sc += v
                        n += 1
                        cur += _adv(ch)
                    if ok:
                        nxt.append((cur, text + "".join(okt), sc, n, dg))
                else:
                    # 数字段：长度 1..max_digits，可带前导 '-'
                    for sign in ("", "-"):
                        base = x
                        ssum0 = 0.0
                        nn0 = 0
                        if sign:
                            wdc = self.lit.W
                            if base + wdc > W or y0 + 9 > H:
                                continue
                            patch = D[y0:y0 + 9, base:base + wdc]
                            v = self.lit.score_one(patch, "-")
                            if v < 0.15:
                                continue
                            ssum0 = v
                            nn0 = 1
                            base += _adv("-")
                        cur = base
                        ds = ""
                        ssum = ssum0
                        nn = nn0
                        for L in range(1, self.max_digits + 1):
                            if cur + self.dt.W > W or y0 + 9 > H:
                                break
                            patch = D[y0:y0 + 9, cur:cur + self.dt.W]
                            ch, v, _ = self.dt.argmax(patch)
                            ds += ch
                            ssum += max(0.0, v)
                            nn += 1
                            cur += _adv(ch)
                            nxt.append((cur, text + sign + ds, sc + ssum, n + nn,
                                        dg + (int(sign + ds),)))
            if not nxt:
                return []
            nxt.sort(key=lambda st: -(st[2] / max(1, st[3])))
            seen = set()
            keep = []
            for st in nxt:
                k = st[0]
                if k in seen:
                    continue
                seen.add(k)
                keep.append(st)
                if len(keep) >= self.beam:
                    break
            states = keep
        out = []
        for x, text, sc, n, dg in states:
            if n == 0:
                continue
            out.append((sc / n, x, n, text, dg))
        out.sort(key=lambda c: -c[0])
        return out[:topk]

    # ================================================================ 主入口
    def read(self, img, roi=None, scales=None, locked=False):
        """img: PIL.Image；roi=(l,t,r,b)。返回 OcrResult。"""
        if isinstance(img, Image.Image):
            ox0, oy0 = (roi[0], roi[1]) if roi else (0, 0)
            crop = img.crop(roi) if roi else img
            L = _to_gray(np.asarray(crop.convert("RGB"), dtype=np.float32))
        else:
            ox0, oy0 = 0, 0
            L = _to_gray(np.asarray(img, dtype=np.float32))
        H, W = L.shape
        if H < 8 or W < 16:
            return OcrResult(note="区域太小")

        res = self._locate(L, scales, locked)
        if res is None:
            return OcrResult(note="未定位到文字行")
        r = res
        r.box = (r.box[0] + ox0, r.box[1] + oy0, r.box[2], r.box[3])
        return r

    def _glyph_mask(self, L):
        """用「字形-阴影配对」特征定位字形像素，并判断极性。

        E_up(x,y) = min( max(D(x,y),0),   max(-D(x+d,y+d),0) )   亮字（字形比背景亮）
        E_dn(x,y) = min( max(-D(x,y),0),  max(-D(x+d,y+d),0) )   暗字（字形比背景暗）
        只有 (x,y) 是字形、(x+d,y+d) 是它的阴影（阴影恒比字暗）时才强；
        阴影外缘、地形边缘都被压掉。d = 阴影偏移（像素）。

        返回 (E, d, 能量, 极性)；极性 +1 表示亮字（解码用 +D），-1 表示暗字（用 -D）。
        """
        best = None
        for d in range(1, 9):
            Dd = _diag_diff(L, d)
            pos = np.maximum(Dd, 0.0)
            neg = np.maximum(-Dd, 0.0)
            ds = np.roll(np.roll(Dd, -d, axis=0), -d, axis=1)
            dneg = np.maximum(-ds, 0.0)
            E_up = np.minimum(pos, dneg)
            E_dn = np.minimum(neg, dneg)
            tu = float(E_up.sum())
            td = float(E_dn.sum())
            if tu >= td:
                E, t, pol = E_up, tu, 1.0
            else:
                E, t, pol = E_dn, td, -1.0
            if best is None or t > best[0]:
                best = (t, d, E, pol)
        return best[2], best[1], best[0], best[3]

    def _locate(self, L, scales, locked):
        H, W = L.shape
        E, d_best, etot, pol = self._glyph_mask(L)
        if etot < 500.0:
            return None
        thr = max(2.0, float(E.max()) * 0.25)
        mask = E > thr
        rowe = mask.sum(axis=1)
        if rowe.max() < 3:
            return None
        rows = np.where(rowe > rowe.max() * 0.15)[0]
        ylo, yhi = int(rows[0]), int(rows[-1])
        band_h = yhi - ylo + 1

        cole = mask[ylo:yhi + 1, :].sum(axis=0)
        cols = np.where(cole > cole.max() * 0.10)[0]
        if len(cols) < 8:
            return None
        xlo, xhi = int(cols[0]), int(cols[-1])
        ink_w = xhi - xlo + 1

        if scales is None:
            if locked and self._lock:
                base = self._lock[0]
                scales = [round(base * f, 3) for f in (0.95, 0.975, 1.0, 1.025, 1.05)]
            else:
                s0 = band_h / 7.0
                cand = {round(s0 * f, 2) for f in (0.90, 0.95, 1.0, 1.05, 1.11)}
                cand.add(round(s0, 2))
                cand.add(float(d_best))
                r = round(s0)
                if abs(r - s0) < 0.6:
                    cand.add(float(r))
                scales = sorted(s for s in cand if 0.35 <= s <= 9.0)

        PADX, PADY = 6, 4
        best = None
        for s in scales:
            cw = int(round(ink_w / s)) + 2 * PADX + 8
            ch = max(9, int(round(band_h / s)) + 2 * PADY + 8)
            ox = xlo - PADX * s
            oy = ylo - PADY * s
            canon = self._sample(L, ox, oy, s, ch, cw)
            D = _diag_diff(canon, 1)
            if pol < 0:
                D = -D
            qx1 = PADX + int(round(ink_w / s)) + 1
            for fmt in self.formats:
                segs = self._segments(fmt)
                for x_start in self._starts(segs, PADX):
                    for y0 in (PADY, PADY + 1, PADY - 1):
                        if y0 < 1:
                            continue
                        for mean, xend, n, text, dg in self._decode(D, x_start, y0, segs):
                            dist = abs(xend - qx1)
                            if dist > 4:
                                continue
                            score = mean - 0.02 * dist - 0.003 * max(0, n - 26)
                            if best is None or score > best[0]:
                                best = (score, s, fmt, text, dg, mean, dist,
                                        (ylo, yhi, xlo, xhi))
        if best is None:
            return None

        score, s, fmt, text, dg, mean, dist, bb = best
        nums = tuple(int(v) for v in self._nums(text))
        coords, note = _to_coords(nums, fmt)
        confident = score >= self.min_score
        if coords is None:
            confident = False
        else:
            self._lock = (s, 1, 0, fmt)
        ylo, yhi, xlo, xhi = bb
        padx = int(8 * s)
        pady = int(4 * s)
        bx0 = max(0, xlo - padx)
        by0 = max(0, ylo - pady)
        bx1 = min(W, xhi + padx)
        by1 = min(H, yhi + pady)
        if not confident and not note:
            note = "置信度不足 (%.2f < %.2f)" % (score, self.min_score)
        return OcrResult(ok=confident, text=text, coords=coords if confident else None,
                         fmt=fmt, scale=s, score=score, digits=nums,
                         box=(bx0, by0, bx1 - bx0, by1 - by0), note=note)

    def _starts(self, segs, padx):
        """第一段的字符格起点候选（规范坐标，含采样左内边距 padx）。"""
        kind, spec = segs[0]
        out = []
        if kind == "lit":
            cols = _mask_cols(spec[0])
            out.append(padx - (cols[0] if cols else 0))
        else:
            offs = set()
            for ch in DIGITS + "-":
                cols = _mask_cols(ch)
                if cols:
                    offs.add(padx - cols[0])
            out = sorted(offs)
        return out

    @staticmethod
    def _nums(text):
        return [int(v) for v in re.findall(r"-?\d+", text)]


def _to_coords(nums, fmt):
    if len(nums) == 3:
        return (nums[0], nums[1], nums[2]), ""
    if len(nums) == 2:
        return (nums[0], nums[1]), "只有 2 个数"
    return None, "数字个数=%d" % len(nums)


# ---------------------------------------------------------------------------
def synth(text, scale=3, bg_img=None, fg=(255, 255, 255, 255), seed=0):
    rng = np.random.default_rng(seed)
    si = int(round(scale))
    w = MF.text_width(text, si) + 24
    h = 8 * si + 24
    if bg_img is not None:
        bw, bh = bg_img.size
        x = int(rng.integers(0, max(1, bw - w)))
        y = int(rng.integers(0, max(1, bh - h)))
        base = bg_img.crop((x, y, x + w, y + h)).convert("RGB")
    else:
        base = Image.new("RGB", (w, h), tuple(int(v) for v in rng.integers(0, 215, 3)))
    txt = MF.render(text, si, fg=fg)
    if abs(scale - si) > 1e-6:
        nw = max(1, int(round(txt.width * scale / si)))
        nh = max(1, int(round(txt.height * scale / si)))
        txt = txt.resize((nw, nh), Image.BILINEAR)
    out = base.copy()
    out.paste(txt, (12, 10), txt)
    return out


if __name__ == "__main__":
    import time
    eng = CoordOCR()
    V = r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14"
    bg_img = None
    try:
        from followmap.store import TileStore
        st = TileStore(os.path.join(V, "XaeroWorldMap", "Multiplayer_mcfkcs.com"))
        bg_img = st.get("null", "mw$default", -10, 3, 1, allow_build=True)
        bg_img = bg_img.convert("RGB") if bg_img else None
    except Exception as e:
        print("背景加载失败", e)

    TEXTS = [
        ("X: -1234, Y: 64, Z: 5678", (3, 4)),
        ("-9398, 66, 6411", (2, 3)),
        ("X: 33, Y: 71, Z: -1024", (2, 3)),
        ("X: -120, Y: 5, Z: 900", (2, 4)),
        ("X: 1, Y: 2, Z: 3", (2, 3)),
        ("X: -4096, Y: 128, Z: 4096", (1, 3)),
        ("X: 12876, Y: 63, Z: -3540", (2, 3)),
        ("X: 0, Y: 0, Z: 0", (3, 3)),
    ]
    FGS = [(255, 255, 255, 255), (85, 255, 85, 255), (255, 255, 85, 255), (55, 55, 55, 255)]

    tot = ok = 0
    bad = []
    t_all = time.time()
    for text, scales in TEXTS:
        for s in scales:
            for bi in (0, 1, 2):
                for fi, fg in enumerate(FGS):
                    bg = [None, bg_img, Image.new("RGB", (400, 200), (215, 205, 175))][bi]
                    img = synth(text, s, bg_img=bg, fg=fg, seed=bi * 10 + fi)
                    t0 = time.time()
                    r = eng.read(img)
                    dt = time.time() - t0
                    tot += 1
                    good = r.text.strip() == text.strip()
                    ok += 1 if good else 0
                    if not good:
                        bad.append("s=%s bg=%d fg=%d %-28s -> %-28s sc=%.2f %.2fs"
                                   % (s, bi, fi, text, r.text, r.score, dt))
    print("准确率 %d/%d = %.1f%%  总用时 %.1fs" % (ok, tot, 100.0 * ok / tot, time.time() - t_all))
    if bad:
        print("失败样本 (%d):" % len(bad))
        for b in bad[:30]:
            print("   ", b)
