# -*- coding: utf-8 -*-
"""官方(Mojang named) 映射  +  Fabric intermediary 映射  ->  官名 -> intermediary

用途：生成一个「纯反射」Fabric 模组所需的全部字符串名。
- client.txt          : named  -> obf（含描述符，Mojang 官方发布）
- intermediary tiny   : obf    -> intermediary（Fabric，v1 格式，含 obf 描述符）

因为 client.txt 给出 official 名 -> obf 名，tiny 给出 (obf 类, obf 名) -> intermediary 名，
两者按 obf 名对接即可。

**按 MC 版本参数化**（2026-10-11）
--------------------------------
模组是纯反射的，唯一跟 MC 版本绑定的就是这些字符串。要支持新版本（例如 1.20.1），
必须用**那个版本自己的**两份映射重新推导，不能照抄 —— 官方名一样不等于 intermediary
一样（intermediary 是按每个版本的 obf 名生成的）。

    Bridge("1.20.1")             # 用 1.20.1 的映射
    client_txt_path("1.20.1")    # 官方映射放哪（cache/mappings/client-1.20.1.txt）
    intermediary_jar_path(v)     # intermediary jar 在哪个 .minecraft/libraries 下
    fetch_mappings(v)            # 本机缺文件时下载（只在显式调用时才联网）

老的 `client.txt`（无版本后缀）继续当作 1.20.4 的映射用，保证老工作流不变。
"""
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_DIR = os.path.join(HERE, "cache", "mappings")

# 默认目标版本。**别乱改**：modmap.py --check 就是拿它核对 Names.java 里的常量。
DEFAULT_MC = "1.20.4"

# 本机的 .minecraft 根目录（找 fabric intermediary jar 用）。版本换了只是子目录名不同，
# 所以列根目录就够了；顺序靠前的优先。
MC_ROOTS = [
    r"D:\config\game\mc\pcl2\.minecraft",                                # 当前主用（PCL2）
    r"D:\config\mc\.minecraft",                                          # 旧的 PCL2 装法
    r"D:\config\game\mc\方块传说V3.0客户端 2K(2560×1440)\.minecraft",     # 整合包客户端
]

_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
_FABRIC_MAVEN = ("https://maven.fabricmc.net/net/fabricmc/intermediary/%s/"
                 "intermediary-%s.jar")


def client_txt_path(mc=DEFAULT_MC):
    """某个版本的 Mojang 官方映射路径（不保证存在）。"""
    return os.path.join(MAP_DIR, "client-%s.txt" % mc)


def _legacy_client_txt():
    return os.path.join(MAP_DIR, "client.txt")


def intermediary_jar_path(mc=DEFAULT_MC):
    """某个版本的 Fabric intermediary jar（不保证存在）。"""
    rel = os.path.join("libraries", "net", "fabricmc", "intermediary", mc,
                       "intermediary-%s.jar" % mc)
    for root in MC_ROOTS:
        p = os.path.join(root, rel)
        if os.path.exists(p):
            return p
    return os.path.join(MAP_DIR, "intermediary-%s.jar" % mc)


def _resolve_client_txt(mc):
    p = client_txt_path(mc)
    if os.path.exists(p):
        return p
    if mc == DEFAULT_MC and os.path.exists(_legacy_client_txt()):
        return _legacy_client_txt()          # 老的 client.txt 就是 1.20.4 的
    return p


def _resolve_intermediary(mc):
    return intermediary_jar_path(mc)


def resources_for(mc=DEFAULT_MC):
    """-> (client.txt 路径, intermediary jar 路径, 缺失项说明列表)。"""
    ct = _resolve_client_txt(mc)
    ij = _resolve_intermediary(mc)
    missing = []
    if not os.path.exists(ct):
        missing.append("官方映射 %s（可用 python modmap.py --fetch %s 下载）" % (ct, mc))
    if not os.path.exists(ij):
        missing.append("intermediary %s（可用 python modmap.py --fetch %s 下载）" % (ij, mc))
    return ct, ij, missing


def fetch_mappings(mc, log=print):
    """把某个版本的官方映射与 intermediary 映射下载到 cache/mappings/。

    **只在显式调用时联网**（`python modmap.py --fetch 1.20.1`），不在 import 或
    --check 时偷偷下 —— 否则离线环境下会莫名卡住，且报错难查。
    """
    os.makedirs(MAP_DIR, exist_ok=True)
    ok = True

    dst_ct = client_txt_path(mc)
    if os.path.exists(dst_ct):
        log("官方映射已存在：%s" % dst_ct)
    else:
        log("查询 Mojang 版本清单…")
        man = json.loads(_get(_MANIFEST).decode("utf-8"))
        ent = next((x for x in man["versions"] if x["id"] == mc), None)
        if ent is None:
            log("[X] 版本清单里没有 %s" % mc)
            return False
        meta = json.loads(_get(ent["url"]).decode("utf-8"))
        cm = meta["downloads"]["client_mappings"]
        log("下载官方映射 %s（%d 字节）…" % (cm["url"], cm["size"]))
        data = _get(cm["url"])
        got = hashlib.sha1(data).hexdigest()
        if got != cm["sha1"]:
            log("[X] sha1 不符：%s != %s" % (got, cm["sha1"]))
            return False
        with open(dst_ct, "wb") as fh:
            fh.write(data)
        log("已写 %s（sha1 校验通过）" % dst_ct)

    dst_ij = os.path.join(MAP_DIR, "intermediary-%s.jar" % mc)
    if os.path.exists(dst_ij):
        log("intermediary 已存在：%s" % dst_ij)
    else:
        url = _FABRIC_MAVEN % (mc, mc)
        log("下载 intermediary %s…" % url)
        try:
            data = _get(url)
        except Exception as e:                      # noqa: BLE001
            log("[X] 下载失败：%s" % e)
            log("    本机 libraries 里若已有 intermediary-%s.jar，直接用即可，不必下载。" % mc)
            return False
        with open(dst_ij, "wb") as fh:
            fh.write(data)
        log("已写 %s" % dst_ij)

    _, _, missing = resources_for(mc)
    if missing:
        ok = False
        for m in missing:
            log("[X] 仍缺：%s" % m)
    return ok


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "coordbridge-modmap/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        # 公司/沙箱代理会拦截 maven/mojang 域并回 401/403（环境变量 HTTP_PROXY 生效时）。
        # 这时回退「完全不走代理」的直连再试一次；真实网络环境下两条路等价，无副作用。
        if e.code not in (401, 403):
            raise
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=30) as r:
            return r.read()

# 有实现的方法带 "起始行:结束行:" 前缀；接口/抽象方法**没有**行号，例如：
#     net.minecraft.resources.ResourceLocation getKey(java.lang.Object) -> b
# 所以行号前缀必须是可选的，否则会漏掉全部抽象方法（如 Registry.getKey）。
_METHOD_RE = re.compile(r'^\s*(?:\d+:\d+:)?(.+?)\s+(\S+?)\((.*?)\)\s+->\s*(\S+)\s*$')
_FIELD_RE = re.compile(r'^\s*(\S+)\s+(\S+)\s+->\s+(\S+)\s*$')
_CLASS_RE = re.compile(r'^(\S+)\s+->\s+(\S+):\s*$')

# 源码风格类型 -> JVM 描述符里的基本类型字母
_PRIM = {"void": "V", "boolean": "Z", "byte": "B", "char": "C",
         "short": "S", "int": "I", "long": "J", "float": "F", "double": "D"}


def _split_args(args_src):
    """把 'int,int' / 'net.minecraft.Heightmap$Types,int,int' 拆成类型列表。

    源码风格描述符里的参数之间只会用逗号分隔，且**没有泛型**（已擦除），
    所以直接 split 是安全的。
    """
    s = (args_src or "").strip()
    if s in ("", "void"):
        return []
    return [t.strip() for t in s.split(",")]


def parse_client_txt(path=None):
    """返回 {official_class: {'obf':obf, 'fields':{name:obf}, 'methods':{name+sig:obf},
                            'methods_by_name':{name:[(desc, obf)]}}}"""
    if path is None:
        path = _resolve_client_txt(DEFAULT_MC)
    classes = {}
    cur = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            m = _CLASS_RE.match(line)
            if m:
                cur = {"obf": m.group(2), "fields": {}, "methods": {}, "by_name": {}}
                classes[m.group(1)] = cur
                continue
            if cur is None or not line[:1].isspace():
                continue
            s = line.rstrip("\n")
            mm = _METHOD_RE.match(s)
            if mm:
                ret, name, args, obf = mm.groups()
                desc = "(%s)%s" % (args, ret)
                cur["methods"]["%s%s" % (name, desc)] = obf
                cur["by_name"].setdefault(name, []).append((desc, obf))
                continue
            fm = _FIELD_RE.match(s)
            if fm:
                typ, name, obf = fm.groups()
                cur["fields"][name] = obf
    return classes


def parse_intermediary(path=None):
    """返回 (obf_class->inter, inter->obf, {(obf_owner, obf_field):inter},
                                 {(obf_owner, obf_name, obf_desc):inter})"""
    if path is None:
        path = _resolve_intermediary(DEFAULT_MC)
    with zipfile.ZipFile(path) as z:
        txt = z.read("mappings/mappings.tiny").decode("utf-8", "replace")
    lines = txt.split("\n")
    assert lines[0].startswith("v1"), lines[0]
    o2i, i2o = {}, {}
    fields, methods = {}, {}
    for line in lines[1:]:
        if not line:
            continue
        p = line.split("\t")
        k = p[0]
        if k == "CLASS":
            o2i[p[1]] = p[2]
            i2o[p[2]] = p[1]
        elif k == "FIELD":
            fields[(p[1], p[3])] = p[4]
        elif k == "METHOD":
            methods[(p[1], p[2], p[3])] = p[4]
    return o2i, i2o, fields, methods


class Bridge:
    def __init__(self, mc=DEFAULT_MC):
        ct, ij, missing = resources_for(mc)
        if missing:
            raise FileNotFoundError(
                "缺少 %s 的映射资源：\n  - %s" % (mc, "\n  - ".join(missing)))
        self.mc = mc
        self.client_txt, self.intermediary_jar = ct, ij
        self.classes = parse_client_txt(ct)
        self.o2i, self.i2o, self.fields, self.methods = parse_intermediary(ij)

    def obf_owner(self, official_class):
        c = self.classes.get(official_class)
        return c["obf"] if c else None

    def cls(self, official_class):
        return self.o2i.get(self.obf_owner(official_class))

    def field(self, official_class, name):
        c = self.classes.get(official_class)
        if not c:
            raise KeyError("no class " + official_class)
        obf_class = c["obf"]
        obf_field = c["fields"].get(name)
        if obf_field is None:
            raise KeyError("no field %s.%s" % (official_class, name))
        inter = self.fields.get((obf_class, obf_field))
        if inter is None:
            raise KeyError("no intermediary for %s.%s (obf=%s)" % (official_class, name, obf_field))
        return inter

    def _obf_type(self, src_type):
        """源码风格类型 -> JVM 描述符片段（用 obf 类名）。"""
        t = src_type.strip()
        dim = 0
        while t.endswith("[]"):
            dim += 1
            t = t[:-2].strip()
        if t in _PRIM:
            base = _PRIM[t]
        else:
            c = self.classes.get(t)
            if c is not None:
                base = "L%s;" % c["obf"]
            elif len(t) <= 2 and t.isupper():
                # 泛型类型变量（T/TAU 之类），擦除后就是 Object
                base = "Ljava/lang/Object;"
            else:
                base = "L%s;" % t.replace(".", "/")
        return "[" * dim + base

    def obf_desc(self, src_desc):
        """client.txt 的 '(参数)返回' 源码风格描述符 -> obf JVM 描述符。"""
        assert src_desc.startswith("(")
        a, _, r = src_desc[1:].partition(")")
        args = "".join(self._obf_type(t) for t in _split_args(a))
        return "(%s)%s" % (args, self._obf_type(r))

    def method(self, official_class, name, args_src=None):
        """按「方法名 + 参数列表(源码风格)」找 intermediary 名。

        **必须用完整描述符精确定位**，不能只按 (类, 方法名) 匹配：
        同一个类里往往有多个方法共用同一个 obf 名（obf 名会被压成 a/b/c…），
        只按名字匹配会随便挑中一个 —— 例如 LevelChunkSection.getBlockState(int,int,int)
        有 (III)LBlockState; / (IIILBlockState;)LBlockState; 等 6 个 obf 名都叫 'a' 的
        重载，按名字匹配拿到的可能是 ()V 那个，直接导致整条取方块链路报废。
        """
        c = self.classes.get(official_class)
        if not c:
            raise KeyError("no class " + official_class)
        obf_class = c["obf"]
        cand = c["by_name"].get(name)
        if not cand:
            raise KeyError("no method %s.%s" % (official_class, name))

        if args_src is None:
            if len(cand) > 1:
                raise KeyError("ambiguous %s.%s: %s" % (official_class, name,
                                                        [d for d, _ in cand]))
            hits = cand
        else:
            hits = [(desc, obf) for (desc, obf) in cand
                    if desc[1:].partition(")")[0] == args_src]

        resolved = []
        for desc, obf in hits:
            od = self.obf_desc(desc)
            inter = self.methods.get((obf_class, od, obf))
            if inter is not None:
                resolved.append((od, inter))
        if not resolved:
            raise KeyError("no intermediary for %s.%s(%s) in %s"
                           % (official_class, name, args_src, hits))
        if len(resolved) > 1:
            raise KeyError("ambiguous intermediary for %s.%s(%s): %s"
                           % (official_class, name, args_src, resolved))
        return resolved[0][1]

    def inter_desc(self, obf_desc):
        """obf JVM 描述符 -> intermediary JVM 描述符（只换类名，不动结构）。"""
        out = []
        i = 0
        while i < len(obf_desc):
            ch = obf_desc[i]
            if ch == "L":
                j = obf_desc.index(";", i)
                obf_cls = obf_desc[i + 1:j]
                out.append("L" + self.o2i.get(obf_cls, obf_cls) + ";")
                i = j + 1
            else:
                out.append(ch)
                i += 1
        return "".join(out)

    def method_full(self, official_class, name, args_src=None):
        """返回 {name, desc, params, ret}，全部为 intermediary 名。

        params / ret 是**擦除后**的 JVM 类型（intermediary 类名或基本类型字母），
        供 mod 在运行时反查「解析到的 Method 描述符是否与预期一致」，
        从而让映射错误在 status.txt 里直接暴露，而不是静默失效。
        """
        c = self.classes.get(official_class)
        if not c:
            raise KeyError("no class " + official_class)
        obf_class = c["obf"]
        cand = c["by_name"].get(name)
        if not cand:
            raise KeyError("no method %s.%s" % (official_class, name))
        hits = cand if args_src is None else [
            (d, o) for (d, o) in cand if d[1:].partition(")")[0] == args_src]
        resolved = []
        for desc, obf in hits:
            od = self.obf_desc(desc)
            inter = self.methods.get((obf_class, od, obf))
            if inter is not None:
                resolved.append((self.inter_desc(od), inter))
        if len(resolved) != 1:
            raise KeyError("cannot uniquely resolve %s.%s(%s): %s"
                           % (official_class, name, args_src, resolved))
        idesc, iname = resolved[0]
        a, _, r = idesc[1:].partition(")")
        params, i = [], 0
        while i < len(a):
            st = i
            while a[i] == "[":
                i += 1
            if a[i] == "L":
                i = a.index(";", i)
            i += 1
            params.append(a[st:i])
        return {"name": iname, "desc": idesc, "params": params, "ret": r}


# 官名（Mojang named）。注意与 Yarn 命名不同（Minecraft / Level / LocalPlayer / ResourceKey）。
# 这几个官名在 1.20.1~1.20.4 之间**完全一致**；版本差异只体现在 obf/intermediary 上，
# 所以这张表不用按版本拆（真拆的话 Bridge 的接口也得跟着改，得不偿失）。
TARGETS = {
    "mc": "net.minecraft.client.Minecraft",
    "player_cls": "net.minecraft.client.player.LocalPlayer",
    "entity": "net.minecraft.world.entity.Entity",
    "level": "net.minecraft.world.level.Level",
    "regkey": "net.minecraft.resources.ResourceKey",
    "resloc": "net.minecraft.resources.ResourceLocation",
    "serverdata": "net.minecraft.client.multiplayer.ServerData",
    "clientlevel": "net.minecraft.client.multiplayer.ClientLevel",
}

# 需求表：(标签, 类, 种类, 官名, 官描述符或 None)
WANT = [
    ("MC.class",         "mc",          "class", None, None),
    ("MC.getInstance",   "mc",          "method", "getInstance", ""),
    ("MC.getCurrentServer", "mc",       "method", "getCurrentServer", ""),
    ("MC.field.player",  "mc",          "field", "player", None),
    ("MC.field.level",   "mc",          "field", "level", None),
    ("MC.field.isLocalServer", "mc",    "field", "isLocalServer", None),
    ("Entity.class",     "entity",      "class", None, None),
    ("Entity.getX",      "entity",      "method", "getX", ""),
    ("Entity.getY",      "entity",      "method", "getY", ""),
    ("Entity.getZ",      "entity",      "method", "getZ", ""),
    ("Level.class",      "level",       "class", None, None),
    ("Level.field.dimension", "level",  "field", "dimension", None),
    ("ResourceKey.class", "regkey",     "class", None, None),
    ("ResourceKey.location", "regkey",  "method", "location", ""),
    ("ResourceLocation.class", "resloc", "class", None, None),
    ("ServerData.class", "serverdata",  "class", None, None),
    ("ServerData.field.ip", "serverdata", "field", "ip", None),
    ("ClientLevel.class", "clientlevel", "class", None, None),
    ("Player.class",     "player_cls",  "class", None, None),
]


if __name__ == "__main__":
    mc = DEFAULT_MC
    if "--mc" in sys.argv:
        mc = sys.argv[sys.argv.index("--mc") + 1]
    if "--fetch" in sys.argv:
        i = sys.argv.index("--fetch")
        tgt = sys.argv[i + 1] if len(sys.argv) > i + 1 else DEFAULT_MC
        raise SystemExit(0 if fetch_mappings(tgt) else 1)

    ct, ij, missing = resources_for(mc)
    print("MC 版本     : %s" % mc)
    print("官方映射    : %s  %s" % (ct, "OK" if os.path.exists(ct) else "缺失"))
    print("intermediary: %s  %s" % (ij, "OK" if os.path.exists(ij) else "缺失"))
    if missing:
        for m in missing:
            print("  !! %s" % m)
        raise SystemExit(1)
    print()

    b = Bridge(mc)
    print("%-34s %-46s %s" % ("需求", "intermediary 名", "官方名"))
    print("-" * 110)
    res = {}
    for label, key, kind, name, desc in WANT:
        official = TARGETS[key]
        try:
            if kind == "class":
                v = b.cls(official)
            elif kind == "field":
                v = b.field(official, name)
            else:
                v = b.method(official, name, desc)
        except Exception as e:
            v = "ERR: %s" % e
        res[label] = v
        print("%-34s %-46s %s" % (label, v, official + ("." + name if name else "")))

