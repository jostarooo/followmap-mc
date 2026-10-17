#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""zipraw.py —— 读「本地头文件名被改写」的 zip（标准库会因名字不一致直接拒绝）

服务器资源包常见保护手段：中央目录里名字正常，但本地头里的文件名被替换成
`../\\\\...` 之类，于是 zipfile.read() 抛 BadZipFile('File name in directory ... differ')。

做法：按字节流顺序扫描 PK\\x03\\x04 本地头，用中央目录里的第 i 项提供
comp_size / uncomp_size / method（两者顺序一致），自己 zlib 解压。
"""
import struct
import zlib
import zipfile


def _central(z):
    return [(i.filename, i.compress_type, i.compress_size, i.file_size,
             i.header_offset) for i in z.infolist()]


def read_raw(path):
    """返回 dict: 中央目录名 -> bytes"""
    data = open(path, "rb").read()
    z = zipfile.ZipFile(path)
    cent = _central(z)
    out = {}
    pos = 0
    idx = 0
    n = len(data)
    while idx < len(cent):
        p = data.find(b"PK\x03\x04", pos)
        if p < 0:
            break
        (ver, flags, method, mt, md, crc, csize, usize,
         nlen, elen) = struct.unpack_from("<HHHHHIIIHH", data, p + 4)
        body = p + 30 + nlen + elen
        name, cm, csz, usz, _off = cent[idx]
        if csz == 0 and csize:
            csz = csize
        if usz == 0 and usize:
            usz = usize
        raw = data[body:body + csz]
        if cm == 0:
            out[name] = raw
        elif cm == 8:
            try:
                out[name] = zlib.decompress(raw, -15)
            except zlib.error:
                out[name] = zlib.decompress(raw)
        else:
            out[name] = b""
        pos = body + csz
        idx += 1
    return out


if __name__ == "__main__":
    import sys
    d = read_raw(sys.argv[1])
    print("读出 %d 个文件" % len(d))
    pat = sys.argv[2] if len(sys.argv) > 2 else ""
    for k in sorted(d):
        if pat in k:
            print("  %-70s %d" % (k, len(d[k])))
