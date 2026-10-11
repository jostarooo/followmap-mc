# -*- coding: utf-8 -*-
"""paths.py 的离线自检：定位顺序、自动缓存的读写在模组数据之后。

**不碰真实盘符扫描**（要 9 秒），全部用临时目录 + monkeypatch 模拟「另一台电脑」。
跑法：D:\\python\\python.exe _modtest\\test_paths.py
"""
import os
import sys
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

from followmap import paths as P  # noqa: E402

ok = True


def check(name, cond, extra=""):
    global ok
    print("  [%s] %s%s" % ("OK" if cond else "!!", name, ("  " + extra) if extra else ""))
    if not cond:
        ok = False


def make_xaero(root):
    """在 root 下造一个 XaeroWorldMap/服务器目录/维度/region zip 的假结构。"""
    xaero = os.path.join(root, "XaeroWorldMap")
    srv = os.path.join(xaero, "Multiplayer_otherhost.com")
    dim = os.path.join(srv, "DIM1", "mw$default")
    os.makedirs(dim, exist_ok=True)
    with open(os.path.join(dim, "0_0.zip"), "wb") as fh:
        fh.write(b"PK\x03\x04 fake")
    return srv


print("== 1. 自动缓存读写往返 ==")
tmp = tempfile.mkdtemp(prefix="fmp_paths_")
try:
    P.APP = tmp                                   # 让缓存写到临时目录
    fake_srv = make_xaero(os.path.join(tmp, "some", "deep", "place", "1.20.4"))
    P._write_auto_cache(fake_srv)
    got = P._read_auto_cache()
    check("写进去能读出来", got == fake_srv, got)
    check("缓存文件在 cache/ 下", os.path.isfile(os.path.join(tmp, "cache", "server_path.auto.txt")))
    check("注释行不会被当成路径", not got.startswith("#"))

    print("== 2. 缓存排在模组数据之后（模组能纠正错猜）==")
    # 造一个「模组记录的游戏目录」指向另一个位置
    cb = os.path.join(tmp, "cb")
    os.makedirs(cb, exist_ok=True)
    other_srv = make_xaero(os.path.join(tmp, "real", "game", "1.20.4-Fabric"))
    gamedir = os.path.join(tmp, "real", "game", "1.20.4-Fabric")
    with open(os.path.join(cb, "status.txt"), "w", encoding="utf-8") as fh:
        fh.write("cwd    : %s\n" % gamedir)
    with open(os.path.join(cb, "coords.json"), "w", encoding="utf-8") as fh:
        fh.write('{"server": "otherhost.com:25565"}')
    os.environ["COORDBRIDGE_HOME"] = cb
    P._hint_cache = None

    P.LEGACY_SERVER = os.path.join(tmp, "nope", "不存在")
    # 浅扫会扫 APP 附近；APP=tmp，里面没有 .minecraft，所以浅扫必然空
    srv, why = P.resolve_server()
    check("模组数据压过自动缓存", srv == other_srv, "%s  <- %s" % (srv, why))
    check("来源说明是模组 status.txt", "status.txt" in why, why)

    print("== 3. 模组数据缺失时，回落到自动缓存 ==")
    os.remove(os.path.join(cb, "status.txt"))
    os.remove(os.path.join(cb, "coords.json"))
    P._hint_cache = None
    srv2, why2 = P.resolve_server()
    check("回落到缓存", srv2 == fake_srv, "%s  <- %s" % (srv2, why2))
    check("来源说明是缓存", "缓存" in why2, why2)

    print("== 4. 人工口子 server_path.txt 优先级最高（除命令行/环境变量外）==")
    with open(os.path.join(tmp, P.CFG_NAME), "w", encoding="utf-8") as fh:
        fh.write("# 手写一行\n%s\n" % other_srv)
    srv3, why3 = P.resolve_server()
    check("server_path.txt 生效", srv3 == other_srv, "%s  <- %s" % (srv3, why3))
    check("来源说明是 server_path.txt", "server_path.txt" in why3, why3)

    print("== 5. 命令行 --server 压过一切 ==")
    srv4, _ = P.resolve_server(explicit=fake_srv)
    check("--server 生效", srv4 == fake_srv, srv4)

    print("== 6. XaeroWorldMap 层会自动往下挑服务器 ==")
    srv5, _ = P.resolve_server(explicit=os.path.join(tmp, "real", "game", "1.20.4-Fabric", "XaeroWorldMap"))
    check("指向 XaeroWorldMap 也能解析出服务器目录", srv5 == other_srv, srv5)

    print("== 7. 显式指定失效时不静默：回落到别的档，但来源里带「注意」=")
    srv6, why6 = P.resolve_server(explicit=os.path.join(tmp, "根本不存在的目录"))
    check("仍能定位到可用目录", srv6 == other_srv, srv6)
    check("来源说明里带出「不可用」告警", "注意" in why6 and "不可用" in why6, why6)
    # 反过来：完全没有人工线索、也没有模组数据、也没有缓存 → 必须给空串 + 说明，不抛异常
    os.remove(os.path.join(tmp, P.CFG_NAME))
    os.remove(P._auto_cache_path())
    P.LEGACY_SERVER = os.path.join(tmp, "nope", "不存在")
    # 深扫会去扫真实盘符（本机确实有 Xaero），这里必须屏蔽掉，
    # 否则测的就不是「什么都没有」这条分支了，还要白等 9 秒。
    _orig_scan = P.find_xaero_dirs
    P.find_xaero_dirs = lambda deep=False: []
    try:
        srv7, why7 = P.resolve_server()
    finally:
        P.find_xaero_dirs = _orig_scan
    check("啥都没有时给出空串与说明（不抛异常）", srv7 == "" and bool(why7), "%r <- %s" % (srv7, why7))

finally:
    os.environ.pop("COORDBRIDGE_HOME", None)
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("结果:", "全部通过" if ok else "有失败项")
sys.exit(0 if ok else 1)
