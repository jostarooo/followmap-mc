# -*- coding: utf-8 -*-
"""核验 1.20.4 映射资源是否真的对齐（防止 1.20.3 的映射被误当成 1.20.4 用）。

背景：cache/mappings/client.txt 与 client-1.20.3.txt 的 sha1 完全相同，
说明无后缀那份其实是 1.20.3 的。若 1.20.4 的 obf 名与 1.20.3 不同，
拿 1.20.3 的 named->obf 去配 1.20.4 的 intermediary 会**静默错配**。

核验三件事：
  1. Mojang 官方：1.20.3 与 1.20.4 的 client_mappings sha1 是否相同（相同=映射一致）
  2. Fabric：intermediary-1.20.3 与 1.20.4 的 CLASS 段是否逐字相同
  3. 本机：libraries 下有哪些 intermediary 版本
"""
import hashlib
import os
import sys
import urllib.error
import urllib.request
import zipfile

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_DIR = os.path.join(HERE, "cache", "mappings")

MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
FABRIC_MVN = "https://maven.fabricmc.net/net/fabricmc/intermediary/%s/intermediary-%s.jar"

ROOTS = [
    r"D:\config\game\mc\pcl2\.minecraft",
    r"D:\config\game\mc\方块传说V3.0客户端 2K(2560×1440)\.minecraft",
]


def get(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": "fishprobe-verify/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403):
            raise
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with op.open(req, timeout=timeout) as r:
            return r.read()


def main():
    print("=" * 78)
    print("① Mojang 官方映射：1.20.3 vs 1.20.4 的 client_mappings sha1")
    print("=" * 78)
    try:
        import json
        man = json.loads(get(MANIFEST).decode("utf-8"))
        ents = {v["id"]: v for v in man["versions"]}
        got = {}
        for v in ("1.20.2", "1.20.3", "1.20.4"):
            e = ents.get(v)
            if not e:
                print("  %-8s 版本清单里没有" % v)
                continue
            meta = json.loads(get(e["url"]).decode("utf-8"))
            cm = meta["downloads"]["client_mappings"]
            got[v] = cm["sha1"]
            print("  %-8s client_mappings sha1=%s  size=%d" % (v, cm["sha1"], cm["size"]))
        if "1.20.3" in got and "1.20.4" in got:
            same = got["1.20.3"] == got["1.20.4"]
            print()
            print("  >>> 1.20.3 与 1.20.4 官方映射 %s" % ("完全一致 ✅" if same else "不同 ❌（必须用 1.20.4 自己的）"))
            if not same:
                # 记下 1.20.4 真实 sha1，供后续下载校验
                print("      1.20.4 真实 sha1 = %s" % got["1.20.4"])
        elif not got:
            print("  [X] 联网失败，改用下面 ② 的 Fabric 侧证据")
    except Exception as e:                                   # noqa: BLE001
        print("  [X] 联网失败：%s" % e)
        print("      （不影响 ②，Fabric 侧证据是本机的，离线可查）")

    print()
    print("=" * 78)
    print("② Fabric intermediary：1.20.3 vs 1.20.4 的类映射是否相同")
    print("=" * 78)

    def inter_path(v):
        rel = os.path.join("libraries", "net", "fabricmc", "intermediary", v,
                           "intermediary-%s.jar" % v)
        for root in ROOTS:
            p = os.path.join(root, rel)
            if os.path.exists(p):
                return p
        return os.path.join(MAP_DIR, "intermediary-%s.jar" % v)

    jars = {}
    for v in ("1.20.3", "1.20.4"):
        p = inter_path(v)
        ok = os.path.exists(p)
        jars[v] = p if ok else None
        print("  %-8s -> %s  %s" % (v, p, "OK" if ok else "缺失"))

    # 1.20.3 不在本机时，尝试从 Fabric maven 拉（小文件，约 600KB）
    if jars["1.20.3"] is None:
        try:
            print("  1.20.3 本机缺失，从 Fabric maven 下载…")
            data = get(FABRIC_MVN % ("1.20.3", "1.20.3"))
            dst = os.path.join(MAP_DIR, "intermediary-1.20.3.jar")
            open(dst, "wb").write(data)
            jars["1.20.3"] = dst
            print("    已写 %s（%d 字节）" % (dst, len(data)))
        except Exception as e:                               # noqa: BLE001
            print("    下载失败：%s" % e)

    def load_tiny(p):
        with zipfile.ZipFile(p) as z:
            return z.read("mappings/mappings.tiny").decode("utf-8", "replace")

    if jars["1.20.3"] and jars["1.20.4"]:
        t3 = load_tiny(jars["1.20.3"])
        t4 = load_tiny(jars["1.20.4"])
        print()
        print("  intermediary-1.20.3.jar sha1 = %s" % hashlib.sha1(open(jars["1.20.3"], "rb").read()).hexdigest())
        print("  intermediary-1.20.4.jar sha1 = %s" % hashlib.sha1(open(jars["1.20.4"], "rb").read()).hexdigest())
        print("  mappings.tiny 逐字节相同：%s" % ("是 ✅" if t3 == t4 else "否 ❌"))
        cls3 = sorted(l for l in t3.split("\n") if l.startswith("CLASS"))
        cls4 = sorted(l for l in t4.split("\n") if l.startswith("CLASS"))
        print("  CLASS 段行数：1.20.3=%d  1.20.4=%d  相同=%s"
              % (len(cls3), len(cls4), cls3 == cls4))

    print()
    print("=" * 78)
    print("③ 本机 libraries 里的 intermediary 版本")
    print("=" * 78)
    for root in ROOTS:
        d = os.path.join(root, "libraries", "net", "fabricmc", "intermediary")
        if os.path.isdir(d):
            print("  %s" % d)
            for v in sorted(os.listdir(d)):
                print("     - %s" % v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
