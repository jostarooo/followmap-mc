# -*- coding: utf-8 -*-
"""
Xaero's World Map  ——  region.xaero 解析器
=========================================

格式逆向自 XaerosWorldMap_1.37.6 的 xaero.map.file.MapSaveLoad
（saveRegion / savePixel / saveOverlay / loadRegion / loadPixel / loadOverlay）。

文件布局
--------
    [u8  0xFF]                      magic
    [i32 版本]                      393224 = (major=6 << 16) | minor=8
    重复，直到 EOF:
        [u8 chunkId]                高 4 位 = chunk 行(z)，低 4 位 = chunk 列(x)
        for tileZ in 0..3:
          for tileX in 0..3:
            [i32 first]             -1 表示该 tile 未加载(直接跳过)
            for z in 0..15:
              for x in 0..15:
                 params = first(仅首格) 或 [i32]
                 ... 见 read_pixel
            [u8  worldInterpretationVersion]
            [i32 caveStart]
            [u8  caveDepth]

    region = 8×8 chunk，chunk = 4×4 tile，tile = 16×16 方块  =>  512×512 方块

每格 params 的位标志
--------------------
    0x000001  有方块状态（否则为空气；草方块不存状态）
    0x000002  有 overlay（水/植物等覆盖层），后随 1 字节 overlay 数量
    0x000040  height 单独存 1 字节（否则从 params 内解码）
    0x000100  (biome 相关) 无 biome 数据
    0x200000  该方块状态首次出现 -> 后面跟 NBT
    0x400000  biome 首次出现
    0x800000  biome 用数字 ID 而非字符串
    0x1000000 topHeight 单独存 1 字节
    高位       light / slope / height 编码

像素数据按 (z 外, x 内) 行优先。
"""

import io
import os
import struct
import zipfile

# ----------------------------------------------------------------------------
# NBT（无压缩，等同 Java DataInputStream 读法）
# ----------------------------------------------------------------------------
TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12

_AIR = "minecraft:air"
_VOID_AIR = "minecraft:void_air"
# params & 1 == 0 表示该格的方块是「grass 哨兵」——Xaero 用 MapBlock.isGrass()
# (state.getBlock() == Blocks.field_10219) 判定，这类方块不写入状态（颜色由生物群系决定）。
# 实践上就是草/矮草/蕨/树叶一类，统一按草皮色渲染。
_GRASS = "minecraft:grass_block"


class _Cur:
    """对 bytes 的顺序读取游标。"""
    __slots__ = ("d", "p")

    def __init__(self, data, pos=0):
        self.d = data
        self.p = pos

    def u1(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def u2(self):
        v = struct.unpack_from(">H", self.d, self.p)[0]
        self.p += 2
        return v

    def i1(self):
        v = struct.unpack_from(">b", self.d, self.p)[0]
        self.p += 1
        return v

    def i2(self):
        v = struct.unpack_from(">h", self.d, self.p)[0]
        self.p += 2
        return v

    def i4(self):
        v = struct.unpack_from(">i", self.d, self.p)[0]
        self.p += 4
        return v

    def i8(self):
        v = struct.unpack_from(">q", self.d, self.p)[0]
        self.p += 8
        return v

    def f4(self):
        v = struct.unpack_from(">f", self.d, self.p)[0]
        self.p += 4
        return v

    def f8(self):
        v = struct.unpack_from(">d", self.d, self.p)[0]
        self.p += 8
        return v

    def utf(self):
        n = self.u2()
        s = self.d[self.p:self.p + n].decode("utf-8", "replace")
        self.p += n
        return s

    def raw(self, n):
        s = self.d[self.p:self.p + n]
        self.p += n
        return s


def _read_payload(c, tag):
    if tag == TAG_BYTE:
        return c.i1()
    if tag == TAG_SHORT:
        return c.i2()
    if tag == TAG_INT:
        return c.i4()
    if tag == TAG_LONG:
        return c.i8()
    if tag == TAG_FLOAT:
        return c.f4()
    if tag == TAG_DOUBLE:
        return c.f8()
    if tag == TAG_BYTE_ARRAY:
        n = c.i4()
        return c.raw(n)
    if tag == TAG_STRING:
        return c.utf()
    if tag == TAG_LIST:
        et = c.u1()
        n = c.i4()
        return [_read_payload(c, et) for _ in range(n)]
    if tag == TAG_COMPOUND:
        out = {}
        while True:
            t = c.u1()
            if t == TAG_END:
                break
            name = c.utf()
            out[name] = _read_payload(c, t)
        return out
    if tag == TAG_INT_ARRAY:
        n = c.i4()
        return [c.i4() for _ in range(n)]
    if tag == TAG_LONG_ARRAY:
        n = c.i4()
        return [c.i8() for _ in range(n)]
    raise ValueError("unknown NBT tag %d @%d" % (tag, c.p))


def read_nbt(c):
    """读一个「无名 compound」——即 NbtIo.write 的产出。"""
    t = c.u1()
    if t == TAG_END:
        return None
    c.utf()                      # root name（恒为空串）
    return _read_payload(c, t)


def nbt_to_blockstate(nbt):
    """把方块状态 NBT 转成 'minecraft:xxx[prop=val,...]' 形式的名字。"""
    if not nbt:
        return _AIR
    name = nbt.get("Name") or _AIR
    props = nbt.get("Properties")
    if props:
        kv = ",".join("%s=%s" % (k, props[k]) for k in sorted(props))
        return "%s[%s]" % (name, kv)
    return name


# ----------------------------------------------------------------------------
# region 解析
# ----------------------------------------------------------------------------
class RegionData:
    """一个 region（512×512 方块）的解析结果。"""

    __slots__ = ("blocks", "height", "biome", "version", "chunks_seen")

    def __init__(self):
        # blocks: dict[(dx, dz)] -> 方块名字符串；dx/dz ∈ [0,512)
        self.blocks = {}
        self.height = {}
        self.biome = {}
        self.version = (0, 0)
        self.chunks_seen = 0

    def at(self, dx, dz):
        return self.blocks.get((dx, dz), _AIR)


def parse_region_bytes(data, keep_height=False, keep_biome=False, strict=True):
    """解析 region.xaero 的原始字节。

    strict=True 时校验「恰好消费完整个文件」——这是格式理解正确的强证据。
    """
    c = _Cur(data)
    magic = c.u1()
    if magic != 0xFF:
        raise ValueError("bad magic 0x%02X (expected 0xFF)" % magic)
    ver = c.i4()
    minor = ver & 0xFFFF
    major = (ver >> 16) & 0xFFFF

    out = RegionData()
    out.version = (major, minor)

    palette = []          # 方块状态（字符串）
    biome_palette = []    # 生物群系名

    def read_pixel(params):
        """读一格；返回 (state_name, height, biome_name)。"""
        # ---- 方块状态 ----
        if params & 0x1:
            if params & 0x200000:                      # 新状态 -> NBT
                nbt = read_nbt(c)
                state = nbt_to_blockstate(nbt)
                palette.append(state)
            else:
                idx = c.i4()
                state = palette[idx] if 0 <= idx < len(palette) else _AIR
        else:
            state = _GRASS                                  # grass 哨兵：草/矮草/蕨/树叶类

        # ---- height ----
        if params & 0x40:
            h = c.u1()
        else:
            # 从 params 里解码（与渲染无关，照抄原逻辑）
            shift = 25 if minor >= 4 else 24
            v = ((params >> 12) & 0xFF) | (((params >> shift) & 0xF) << 8)
            h = (v << 20) >> 20                            # 符号扩展
            h = h & 0xFFFF

        # ---- topHeight ----
        if params & 0x1000000:
            c.u1()

        # ---- overlays ----
        if params & 0x2:
            cnt = c.u1()
            for _ in range(cnt):
                op = c.i4()
                if op & 0x1:
                    if op & 0x400:                          # 新 overlay 状态
                        nb = read_nbt(c)
                        st = nbt_to_blockstate(nb)
                        palette.append(st)
                    else:
                        idx = c.i4()
                        st = palette[idx] if 0 <= idx < len(palette) else _AIR
                    if state in (_AIR, _GRASS):             # 水/植物覆盖层作为地表
                        state = st
                # var3(=minor) < 1 时才读一个 int —— 现代文件不读
                if minor < 1 and (op & 0x2):
                    c.i4()
                var11 = 0
                if var11 == 2 or (op & 0x4):
                    c.i4()
                if minor < 8:
                    if op & 0x8:
                        c.i4()
                # else: 高度从 op 内解码，不读流

        # ---- biome ----
        biome = None
        if params & 0x400000:                               # 新 biome
            if params & 0x800000:
                c.i4()
            else:
                c.utf()
            biome = "<new>"
        elif params & 0x100000:
            idx = c.i4()
            biome = biome_palette[idx] if 0 <= idx < len(biome_palette) else None

        return state, h, biome

    n = len(data)
    while c.p < n:
        chunk_id = c.u1()
        ci = (chunk_id >> 4) & 0xF          # chunkX（高 4 位）
        cj = chunk_id & 0xF                 # chunkZ（低 4 位）
        out.chunks_seen += 1
        for k in range(4):                  # tileX
            for l in range(4):              # tileZ
                head = c.i4()
                if head == -1:
                    continue
                for m in range(16):         # blockX
                    for nn in range(16):    # blockZ
                        params = head if (m == 0 and nn == 0) else c.i4()
                        st, h, bio = read_pixel(params)
                        dx = ci * 64 + k * 16 + m
                        dz = cj * 64 + l * 16 + nn
                        out.blocks[(dx, dz)] = st
                        if keep_height:
                            out.height[(dx, dz)] = h
                        if keep_biome and bio:
                            out.biome[(dx, dz)] = bio
                # tile 尾部
                c.u1()                      # worldInterpretationVersion
                if minor >= 6:
                    c.i4()                  # caveStart
                    if minor >= 7:
                        c.u1()              # caveDepth
    if strict and c.p != n:
        raise ValueError("流未对齐: 已消费 %d / 共 %d 字节 (差 %d)" % (c.p, n, n - c.p))
    return out


def parse_region_file(path, **kw):
    """从 .zip 里读出 region.xaero 并解析。"""
    with zipfile.ZipFile(path) as z:
        name = None
        for nm in z.namelist():
            if nm.endswith("region.xaero"):
                name = nm
                break
        if name is None:
            raise ValueError("no region.xaero in %s" % path)
        data = z.read(name)
    return parse_region_bytes(data, **kw)


# ----------------------------------------------------------------------------
# 目录扫描
# ----------------------------------------------------------------------------
def region_coords(fname):
    """'-10_3.zip' -> (-10, 3)；解析失败返回 None。"""
    base = fname[:-4] if fname.endswith(".zip") else fname
    if "_" not in base:
        return None
    a, _, b = base.rpartition("_")
    try:
        return int(a), int(b)
    except ValueError:
        return None


def iter_region_files(world_map_dir, dim_dir, mw="mw$default"):
    """列出某维度下所有 region 文件 (path, (rx, rz))。"""
    d = os.path.join(world_map_dir, dim_dir, mw)
    if not os.path.isdir(d):
        return
    for f in sorted(os.listdir(d)):
        if not f.endswith(".zip"):
            continue
        rc = region_coords(f)
        if rc is None:
            continue
        yield os.path.join(d, f), rc


# ----------------------------------------------------------------------------
# 自检
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    p = sys.argv[1]
    rd = parse_region_file(p, keep_height=True)
    print("version      :", rd.version)
    print("chunks seen  :", rd.chunks_seen)
    print("blocks       :", len(rd.blocks))
    from collections import Counter
    c = Counter(v.split("[")[0] for v in rd.blocks.values())
    print("top blocks   :")
    for k, v in c.most_common(20):
        print("   %-40s %d" % (k, v))
