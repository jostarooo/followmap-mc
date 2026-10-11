# -*- coding: utf-8 -*-
"""推导「内存直读区块」所需的全部 intermediary 名（纯反射模组的根基）。

链路：
    Minecraft.getInstance()
      -> .level                      (ClientLevel)
      -> .getChunkSource()           (ClientChunkCache)
      -> .storage                    (ClientChunkCache$Storage)
      -> .chunks                     (java.util.concurrent.atomic.AtomicReferenceArray)
      -> get(i)                      (LevelChunk)

    LevelChunk.getPos()              (ChunkPos)  -> .x / .z
    LevelChunk.getSections()         (LevelChunkSection[])
    LevelChunkSection.hasOnlyAir()   -> 跳过整段
    LevelChunkSection.getBlockState(x,y,z) -> BlockState
    BlockState.getBlock()            -> Block
    BuiltInRegistries.BLOCK.getKey(block) -> ResourceLocation

为什么能强转 AtomicReferenceArray：它是 java.base 的**导出包**里的公开类，
读它的 public 方法（length/get）不需要 setAccessible，因此不受 JDK 强封装限制。
（这一点很关键：若走 Array.get 反射反而会撞 InaccessibleObjectException。）

用法：
    python modmap.py                     # 打印 1.20.4 的对照表
    python modmap.py --mc 1.20.1         # 打印指定版本的对照表
    python modmap.py --compare 1.20.1 1.20.4   # 逐项对比两个版本的中介名
    python modmap.py --check [--mc <版本>]     # 与 Names.java 逐字核对
    python modmap.py --java [--mc <版本>]      # 打印可直接粘进 Java 的常量块
    python modmap.py --fetch 1.20.1      # 下载该版本的映射（唯一会联网的用法）
"""
import os
import sys

from mapbridge import Bridge, DEFAULT_MC, resources_for

# 官名（Mojang named）。注意 1.20.4 与 Yarn 命名不同。
CLS = {
    "MC":            "net.minecraft.client.Minecraft",
    "CLIENT_LEVEL":  "net.minecraft.client.multiplayer.ClientLevel",
    "CHUNK_CACHE":   "net.minecraft.client.multiplayer.ClientChunkCache",
    "STORAGE":       "net.minecraft.client.multiplayer.ClientChunkCache$Storage",
    "CHUNK":         "net.minecraft.world.level.chunk.LevelChunk",
    "CHUNK_ACCESS":  "net.minecraft.world.level.chunk.ChunkAccess",
    "SECTION":       "net.minecraft.world.level.chunk.LevelChunkSection",
    "BLOCK_STATE":   "net.minecraft.world.level.block.state.BlockState",
    "BLOCK_ST_BASE": "net.minecraft.world.level.block.state.BlockBehaviour$BlockStateBase",
    "BLOCK":         "net.minecraft.world.level.block.Block",
    "BUILTIN_REGS":  "net.minecraft.core.registries.BuiltInRegistries",
    "REGISTRY":      "net.minecraft.core.Registry",
    "CHUNK_POS":     "net.minecraft.world.level.ChunkPos",
    "HEIGHT_ACC":    "net.minecraft.world.level.LevelHeightAccessor",
    "HEIGHTMAP":     "net.minecraft.world.level.levelgen.Heightmap$Types",
    "RESLOC":        "net.minecraft.resources.ResourceLocation",
    "LEVEL":         "net.minecraft.world.level.Level",
    "ENTITY":        "net.minecraft.world.entity.Entity",
    "REGKEY":        "net.minecraft.resources.ResourceKey",
    "SERVERDATA":    "net.minecraft.client.multiplayer.ServerData",
}

# (标签, 类键, 字段官名)
FIELDS = [
    ("F_LEVEL",      "MC",           "level"),
    ("F_PLAYER",     "MC",           "player"),
    ("F_STORAGE",    "CHUNK_CACHE",  "storage"),
    ("F_CHUNKS",     "STORAGE",      "chunks"),
    ("F_BLOCK_REG",  "BUILTIN_REGS", "BLOCK"),
    ("F_CPOS_X",     "CHUNK_POS",    "x"),
    ("F_CPOS_Z",     "CHUNK_POS",    "z"),
    ("F_DIM",        "LEVEL",        "dimension"),
    ("F_SRV_IP",     "SERVERDATA",   "ip"),
]

# (标签, 类键, 方法官名, 参数(源码风格))
METHODS = [
    ("M_INSTANCE",   "MC",            "getInstance",    ""),
    ("M_SERVER",     "MC",            "getCurrentServer", ""),
    ("M_GET_X",      "ENTITY",        "getX",           ""),
    ("M_GET_Y",      "ENTITY",        "getY",           ""),
    ("M_GET_Z",      "ENTITY",        "getZ",           ""),
    ("M_LOCATION",   "REGKEY",        "location",       ""),
    ("M_CHUNK_SRC",  "CLIENT_LEVEL",  "getChunkSource", ""),
    ("M_SECTIONS",   "CHUNK_ACCESS",  "getSections",    ""),
    ("M_CHUNK_POS",  "CHUNK_ACCESS",  "getPos",         ""),
    # 每列 1 次调用直接拿到地表高度（客户端收到的 heightmap），
    # 比从 y=15 逐层扫 4096 个方块快一个数量级，且耗时不随地形起伏变化。
    ("M_GET_HEIGHT", "CHUNK_ACCESS",  "getHeight",
     "net.minecraft.world.level.levelgen.Heightmap$Types,int,int"),
    ("M_IS_EMPTY",   "CHUNK",         "isEmpty",        ""),
    ("M_MIN_SECT",   "HEIGHT_ACC",    "getMinSection",  ""),
    ("M_SECT_CNT",   "HEIGHT_ACC",    "getSectionsCount", ""),
    ("M_ONLY_AIR",   "SECTION",       "hasOnlyAir",     ""),
    ("M_SEC_BLOCK",  "SECTION",       "getBlockState",  "int,int,int"),
    ("M_STATE_BLK",  "BLOCK_ST_BASE", "getBlock",       ""),
    ("M_REG_KEY",    "REGISTRY",      "getKey",         "java.lang.Object"),
]


def _bridge(mc=None):
    """按版本取 Bridge。不给版本就用默认（1.20.4）。"""
    return Bridge(mc or DEFAULT_MC)


def resolve(bridge=None, mc=None):
    b = bridge or _bridge(mc)
    classes, fields, methods, errors = {}, {}, {}, []

    for key, official in CLS.items():
        try:
            classes[key] = b.cls(official)
        except Exception as e:
            errors.append(("class", key, official, str(e)))

    for label, key, name in FIELDS:
        try:
            fields[label] = b.field(CLS[key], name)
        except Exception as e:
            errors.append(("field", label, "%s.%s" % (CLS[key], name), str(e)))

    for label, key, name, args in METHODS:
        try:
            methods[label] = b.method(CLS[key], name, args)
        except Exception as e:
            errors.append(("method", label, "%s.%s(%s)" % (CLS[key], name, args), str(e)))

    return classes, fields, methods, errors


def resolve_full(bridge=None, mc=None):
    """返回 {标签: method_full 结果}，含 intermediary 签名，供运行时自检。"""
    b = bridge or _bridge(mc)
    out = {}
    for label, key, name, args in METHODS:
        out[label] = b.method_full(CLS[key], name, args)
    return out


def names_for(mc):
    """某个版本完整的名字表 -> {classes, fields, methods, errors, mc}。

    classes 的键带 `C_` 前缀、fields/methods 的键就是 Names.java 里的常量名，
    这样可以直接拿去和 Names.java 对账、或喂给 gen_stubs.py 生成桩类。
    """
    classes, fields, methods, errors = resolve(mc=mc)
    return {
        "mc": mc,
        "classes": {"C_" + k: v.replace("/", ".") for k, v in classes.items()},
        "fields": dict(fields),
        "methods": dict(methods),
        "errors": errors,
    }


def compare(mc_a, mc_b):
    """逐项对比两个版本的中介名**与描述符**，返回 (差异列表, 全部项数, a, b)。

    两类都要比：光名字一样不够。Ref 在运行期拿 Names.sigs() 里的**完整描述符**校验
    解析到的 Method，描述符对不上照样判失败（这是防"名字对、签名错"的兜底）。
    所以版本对比必须把 resolve_full 的 desc 一起对上。
    """
    a = names_for(mc_a)
    b = names_for(mc_b)
    for n in (a, b):
        if n["errors"]:
            print("!! %s 有 %d 项解析失败：" % (n["mc"], len(n["errors"])))
            for kind, label, what, msg in n["errors"]:
                print("   [%s] %-14s %s -- %s" % (kind, label, what, msg))

    diffs = []
    total = 0
    for kind in ("classes", "fields", "methods"):
        keys = list(a[kind].keys()) + [k for k in b[kind] if k not in a[kind]]
        for k in keys:
            total += 1
            va, vb = a[kind].get(k), b[kind].get(k)
            if va != vb:
                diffs.append((kind, k, va, vb))

    # 描述符（Names.sigs() 的内容）
    fa, fb = resolve_full(mc=mc_a), resolve_full(mc=mc_b)
    for label in list(fa.keys()) + [k for k in fb if k not in fa]:
        total += 1
        da = (fa.get(label) or {}).get("desc")
        db = (fb.get(label) or {}).get("desc")
        if da != db:
            diffs.append(("sig", label, da, db))

    return diffs, total, a, b


NAMES_JAVA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "coordbridge", "src", "coordbridge", "Names.java")
HERE = os.path.dirname(os.path.abspath(__file__))


def check(bridge=None, mc=None, java_path=None):
    """核对 Names.java 里的常量是否与映射推导结果**逐字一致**。

    这是防回归的关键一步：映射写错时 mod 会静默失效（方法找不到 -> 整条链路
    停摆 -> 外部地图退回 60 秒落盘的 Xaero），只有精确比对才能提前发现。
    """
    import re as _re
    b = bridge or _bridge(mc)
    names_java = java_path or NAMES_JAVA
    classes, fields, methods, errors = resolve(b)
    txt = open(names_java, encoding="utf-8").read()

    def val(label):
        m = _re.search(r'\b%s\s*=\s*"([^"]*)"' % label, txt)
        return m.group(1) if m else None

    bad = []
    for key, inter in classes.items():
        want = inter.replace("/", ".")
        got = val("C_" + key)
        if got != want:
            bad.append(("class", key, got, want))
    for label, inter in fields.items():
        got = val(label)
        if got != inter:
            bad.append(("field", label, got, inter))
    for label, inter in methods.items():
        got = val(label)
        if got != inter:
            bad.append(("method", label, got, inter))

    # 描述符表（Names.sigs()）。**必须一起核**：名字对而描述符错时，Ref 的运行期自检
    # 会把方法判为"找不到"，整条取方块链路静默失效 —— 正是最难查的那种故障。
    full = resolve_full(b)
    n_sig = 0
    for label, info in full.items():
        n_sig += 1
        m = _re.search(r'm\.put\(\s*%s\s*,\s*"([^"]*)"\s*\)' % label, txt)
        got = m.group(1) if m else None
        if got != info["desc"]:
            bad.append(("sig", label, got, info["desc"]))

    print("核对目标：%s（MC %s）" % (os.path.relpath(names_java, HERE), b.mc))
    for kind, label, got, want in bad:
        print("[X] %-8s %-14s Names.java=%-16s 应为 %s" % (kind, label, got, want))
    for kind, label, what, msg in errors:
        print("[X] 解析失败 %-8s %-14s %s\n    %s" % (kind, label, what, msg))
    if bad or errors:
        print("\n核对失败：%d 项不一致，%d 项无法解析。" % (len(bad), len(errors)))
        return 1
    print("核对通过：%d 类 / %d 字段 / %d 方法 / %d 描述符 与映射完全一致。"
          % (len(classes), len(fields), len(methods), n_sig))
    return 0


def _arg_of(flag, default=None):
    """取 `--flag value` 后面的值。"""
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if len(sys.argv) > i + 1:
            return sys.argv[i + 1]
    return default


def print_compare(mc_a, mc_b):
    from mapbridge import resources_for
    for mc in (mc_a, mc_b):
        _, _, missing = resources_for(mc)
        if missing:
            print("[X] 缺少 MC %s 的映射资源：" % mc)
            for m in missing:
                print("    - %s" % m)
            print("    （用 python modmap.py --fetch %s 下载）" % mc)
            return 1

    diffs, total, a, b = compare(mc_a, mc_b)
    print("对比：MC %s  vs  MC %s" % (mc_a, mc_b))
    print("-" * 96)
    if not diffs:
        print("** 完全一致 **：%d 项（%d 类 + %d 字段 + %d 方法 + %d 描述符）"
              "在两版本间没有任何差异。"
              % (total, len(a["classes"]), len(a["fields"]),
                 len(a["methods"]), len(a["methods"])))
        print()
        print("=> 同一份 Names.java（同一个 jar）在 %s 和 %s 上都能解析成功。" % (mc_a, mc_b))
        return 0

    print("有 %d / %d 项不同：" % (len(diffs), total))
    print()
    print("%-9s %-16s %-26s %s" % ("种类", "常量名", mc_a, mc_b))
    for kind, label, va, vb in diffs:
        print("%-9s %-16s %-26s %s" % (kind, label, va, vb))
    print()
    print("=> 两版本无法共用一份常量表，必须按版本构建（或让运行时按版本取候选名）。")
    return 2


def main():
    if "--fetch" in sys.argv:
        from mapbridge import fetch_mappings
        return 0 if fetch_mappings(_arg_of("--fetch", DEFAULT_MC)) else 1

    if "--compare" in sys.argv:
        i = sys.argv.index("--compare")
        rest = [x for x in sys.argv[i + 1:] if not x.startswith("--")]
        if len(rest) < 2:
            print("用法：python modmap.py --compare <版本A> <版本B>")
            return 1
        return print_compare(rest[0], rest[1])

    mc = _arg_of("--mc", DEFAULT_MC)
    java_path = _arg_of("--java-into")

    if "--check" in sys.argv:
        return check(mc=mc, java_path=java_path)
    if "--full" in sys.argv:
        import json
        full = resolve_full(mc=mc)
        print(json.dumps(full, ensure_ascii=False, indent=2))
        return 0

    want_java = "--java" in sys.argv
    classes, fields, methods, errors = resolve(mc=mc)

    if want_java:
        print("    // ---- 类 ----")
        for k, v in classes.items():
            print("    private static final String C_%s = \"%s\";" % (k, v.replace("/", ".")))
        print()
        print("    // ---- 字段 ----")
        for k, v in fields.items():
            print("    private static final String %s = \"%s\";" % (k, v))
        print()
        print("    // ---- 方法 ----")
        for k, v in methods.items():
            print("    private static final String %s = \"%s\";" % (k, v))
    else:
        print("MC 版本：%s" % mc)
        print("%-16s %-46s %s" % ("键", "intermediary", "官方名"))
        print("-" * 112)
        for k, v in classes.items():
            print("%-16s %-46s %s" % (k, v, CLS[k]))
        print()
        for label, key, name in FIELDS:
            print("%-16s %-46s %s.%s" % (label, fields.get(label, "ERR"), CLS[key], name))
        print()
        for label, key, name, args in METHODS:
            print("%-16s %-46s %s.%s(%s)" % (label, methods.get(label, "ERR"), CLS[key], name, args))

    print()
    if errors:
        print("!! %d 项解析失败：" % len(errors))
        for kind, label, what, msg in errors:
            print("   [%s] %-16s %s\n        %s" % (kind, label, what, msg))
        return 1
    print("全部 %d 类 / %d 字段 / %d 方法 解析成功。"
          % (len(classes), len(fields), len(methods)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
