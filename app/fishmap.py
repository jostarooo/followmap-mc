# -*- coding: utf-8 -*-
"""fishprobe 探针所需的全部 intermediary 名（由 mapbridge 从官方映射 + intermediary 确定性推导）。

与 modmap.py 同源、同 Bridge，只是换了目标表。**不要手改 Names.java 里的字符串**，
改完跑 `python fishmap.py --check` 逐字核对。

目标链路（MC 1.20.4 / 日常 PCL2 实例；1.20.1 亦通用）：

    Minecraft.getInstance()
      -> .player                     (LocalPlayer/Player -> LivingEntity)
      -> .gui                        (Gui)
           -> .getBossOverlay()      (BossHealthOverlay)
                -> .events            (Map<UUID, LerpingBossEvent>)
      -> Gui.title / Gui.subtitle / Gui.overlayMessageString   (Title / ActionBar 文本)

    BossEvent.getName() / getPercent() / getColor() / getStyle() / getOverlay() / getId()

    LivingEntity.getMainHandItem() / getOffhandItem() / getHealth() / getMaxHealth()
    ItemStack.getItem() / getCount() / getHoverName() / isEmpty()
    BuiltInRegistries.ITEM -> Registry.getKey(Item) -> ResourceLocation
    Component.getString() -> 纯文本
    Player.experienceLevel / experienceProgress

用法：
    python fishmap.py                 # 打印对照表
    python fishmap.py --java          # 打印可直接粘进 Java 的常量块
    python fishmap.py --check         # 与 Names.java 逐字核对
"""
import os
import re
import sys

from mapbridge import Bridge

# 默认目标版本。用户日常在玩的是 **1.20.4**（PCL2 实例）。
# 1.20.1 与 1.20.4 的 intermediary 名**完全一致**（已实测：intermediary-1.20.3 与
# intermediary-1.20.4 的 mappings.tiny 逐字节相同，且本表在两个版本上解析结果相同），
# 所以同一个 Names.java / 同一个 jar 可以同时跑这两个版本。切版本只需 `--mc`。
DEFAULT_MC = "1.20.4"

# ------------------------------------------------------------------ 目标表
CLS = {
    "MC":           "net.minecraft.client.Minecraft",
    "GUI":          "net.minecraft.client.gui.Gui",
    "BOSS_OVERLAY": "net.minecraft.client.gui.components.BossHealthOverlay",
    # ★ 更正（2026-10-14 实测）：早先记的「BossEvent 1.20.2+ 搬到 client.gui.components」是**错的**。
    #   核对了 1.20.1 / 1.20.2 / 1.20.3 / 1.20.4 / 1.20.5 五份官方映射，BossEvent **一直**
    #   在 net.minecraft.world（intermediary 恒为 class_1259）。容易被记混的是**容器**
    #   BossHealthOverlay —— 它在 client.gui.components，那个从 1.20.1 起就没变过。
    "BOSS_EVENT":   "net.minecraft.world.BossEvent",
    "COMPONENT":    "net.minecraft.network.chat.Component",
    "LIVING":       "net.minecraft.world.entity.LivingEntity",
    "PLAYER":       "net.minecraft.world.entity.player.Player",
    "LOCAL_PLAYER": "net.minecraft.client.player.LocalPlayer",
    "ITEMSTACK":    "net.minecraft.world.item.ItemStack",
    "ITEM":         "net.minecraft.world.item.Item",
    "BUILTIN_REGS": "net.minecraft.core.registries.BuiltInRegistries",
    "REGISTRY":     "net.minecraft.core.Registry",
    "RESLOC":       "net.minecraft.resources.ResourceLocation",
    "ENTITY":       "net.minecraft.world.entity.Entity",
    "LEVEL":        "net.minecraft.world.level.Level",
    "SERVERDATA":   "net.minecraft.client.multiplayer.ServerData",
}

# (标签, 类键, 字段官名)
FIELDS = [
    ("F_PLAYER",      "MC",           "player"),
    ("F_GUI",         "MC",           "gui"),
    ("F_LEVEL",       "MC",           "level"),
    # --- BossBar 容器 ---
    ("F_BOSS_EVENTS", "BOSS_OVERLAY", "events"),
    # ★ 关键：LerpingBossEvent 会覆盖 getProgress() 返回**客户端插值后**的值（渲染用），
    #   服务器每 tick 下发的**原始设定值**在这个字段里。两个都要记：
    #   插值值 = 玩家眼睛看到的进度条位置（视觉方案要对齐的就是它），
    #   字段值 = 服务器权威数据（自动化判定应当基于它）。
    ("F_BOSS_RAW",    "BOSS_EVENT",   "progress"),
    # --- Title / ActionBar（Gui 上的持久字段，Title 显示期间可读）---
    ("F_OVERLAY_MSG", "GUI",          "overlayMessageString"),
    ("F_TITLE",       "GUI",          "title"),
    ("F_SUBTITLE",    "GUI",          "subtitle"),
    ("F_OVERLAY_T",   "GUI",          "overlayMessageTime"),
    ("F_TITLE_T",     "GUI",          "titleTime"),
    # --- 状态快照 ---
    ("F_XP_LEVEL",    "PLAYER",       "experienceLevel"),
    ("F_XP_PROG",     "PLAYER",       "experienceProgress"),
    ("F_DIM",         "LEVEL",        "dimension"),
    ("F_ITEM_REG",    "BUILTIN_REGS", "ITEM"),
    ("F_SRV_IP",      "SERVERDATA",   "ip"),
]

# (标签, 类键, 方法官名, 参数(源码风格))
METHODS = [
    ("M_INSTANCE",      "MC",          "getInstance",       ""),
    ("M_GET_BOSS",      "GUI",         "getBossOverlay",    ""),
    # --- BossEvent 观察（★ 实测：1.20.1 与 1.20.4 都用 getProgress()，方法名未变；
    #     1.20.4 的 BossEvent 同样**没有** getStyle()。别照搬 1.20.5+ 的资料）---
    ("M_BOSS_NAME",     "BOSS_EVENT",  "getName",           ""),
    ("M_BOSS_PERCENT",  "BOSS_EVENT",  "getProgress",       ""),
    ("M_BOSS_COLOR",    "BOSS_EVENT",  "getColor",          ""),
    ("M_BOSS_OVERLAY",  "BOSS_EVENT",  "getOverlay",        ""),
    ("M_BOSS_ID",       "BOSS_EVENT",  "getId",             ""),
    ("M_BOSS_DARKEN",   "BOSS_EVENT",  "shouldDarkenScreen", ""),
    ("M_BOSS_MUSIC",    "BOSS_EVENT",  "shouldPlayBossMusic", ""),
    ("M_BOSS_FOG",      "BOSS_EVENT",  "shouldCreateWorldFog", ""),
    # --- 手持物 / 状态 ---
    ("M_MAIN_HAND",     "LIVING",      "getMainHandItem",   ""),
    ("M_OFF_HAND",      "LIVING",      "getOffhandItem",    ""),
    ("M_HEALTH",        "LIVING",      "getHealth",         ""),
    ("M_MAX_HEALTH",    "LIVING",      "getMaxHealth",      ""),
    ("M_ITEM_GET",      "ITEMSTACK",   "getItem",           ""),
    ("M_ITEM_COUNT",    "ITEMSTACK",   "getCount",          ""),
    ("M_ITEM_NAME",     "ITEMSTACK",   "getHoverName",      ""),
    ("M_ITEM_EMPTY",    "ITEMSTACK",   "isEmpty",           ""),
    ("M_GET_X",         "ENTITY",      "getX",              ""),
    ("M_GET_Y",         "ENTITY",      "getY",              ""),
    ("M_GET_Z",         "ENTITY",      "getZ",              ""),
    ("M_ITEM_KEY",      "REGISTRY",    "getKey",            "java.lang.Object"),
]

# 名字**不经混淆**、因此 intermediary 里根本没有记录的成员 —— 直接写固定字符串。
# 依据：javap 反汇编客户端 jar 实测（`javap -p -cp "BlockLegend V3.0.jar" sw`）：
#   public default java.lang.String getString();
# Component.getString() 因为在实现 com.mojang.brigadier.Message#getString()，
# Mojang 保留了原名，Fabric 也就不生成 intermediary 条目 —— 映射表里查不到是正常的。
RAW = {
    "M_COMPONENT_STR": "getString",
}

HERE = os.path.dirname(os.path.abspath(__file__))
NAMES_JAVA = os.path.join(HERE, "fishprobe", "src", "fishprobe", "Names.java")


def resolve(mc=DEFAULT_MC):
    b = Bridge(mc)
    classes, fields, methods, errors = {}, {}, {}, []
    for key, official in CLS.items():
        try:
            classes[key] = b.cls(official)
        except Exception as e:                       # noqa: BLE001
            errors.append(("class", key, official, str(e)))
    for label, key, name in FIELDS:
        try:
            fields[label] = b.field(CLS[key], name)
        except Exception as e:                       # noqa: BLE001
            errors.append(("field", label, "%s.%s" % (CLS[key], name), str(e)))
    for label, key, name, args in METHODS:
        try:
            methods[label] = b.method(CLS[key], name, args)
        except Exception as e:                       # noqa: BLE001
            errors.append(("method", label, "%s.%s(%s)" % (CLS[key], name, args), str(e)))
    methods.update(RAW)                              # 不混淆的成员直接落常量
    return b, classes, fields, methods, errors


def resolve_full(mc=DEFAULT_MC):
    """{标签: method_full 结果 or None}。解析不出的记 None（由 resolve 的 errors 报告）。"""
    b = Bridge(mc)
    out = {}
    for label, key, name, args in METHODS:
        try:
            out[label] = b.method_full(CLS[key], name, args)
        except Exception:                            # noqa: BLE001
            out[label] = None
    return out


def java_block(mc=DEFAULT_MC):
    _, classes, fields, methods, errors = resolve(mc)
    full = resolve_full(mc)
    out = []
    out.append("    // ---- 类（intermediary，运行期 Class.forName 的目标）----")
    for k in CLS:
        if k in classes:
            out.append('    static final String C_%s = "%s";' % (k, classes[k].replace("/", ".")))
    out.append("")
    out.append("    // ---- 字段 ----")
    for label, _, _ in FIELDS:
        if label in fields:
            out.append('    static final String %s = "%s";' % (label, fields[label]))
    out.append("")
    out.append("    // ---- 方法 ----")
    for label, _, _, _ in METHODS:
        if label in methods:
            out.append('    static final String %s = "%s";' % (label, methods[label]))
    out.append("    // ---- 不混淆成员（固定名，映射表里查不到）----")
    for label, raw in RAW.items():
        out.append('    static final String %s = "%s";' % (label, raw))
    out.append("")
    out.append("    // ---- 预期描述符（运行期自检用）----")
    out.append("    static final String[][] SIGS = {")
    for label, _, _, _ in METHODS:
        info = full.get(label)
        if info:
            out.append('        {"%s", "%s"},' % (label, info["desc"]))
    out.append("    };")
    return "\n".join(out), errors


def check(mc=DEFAULT_MC):
    _, classes, fields, methods, errors = resolve(mc)
    txt = open(NAMES_JAVA, encoding="utf-8").read()

    def val(label):
        m = re.search(r'\b%s\s*=\s*"([^"]*)"' % label, txt)
        return m.group(1) if m else None

    bad = []
    for k, inter in classes.items():
        want = inter.replace("/", ".")
        if val("C_" + k) != want:
            bad.append(("class", k, val("C_" + k), want))
    for label, inter in fields.items():
        if val(label) != inter:
            bad.append(("field", label, val(label), inter))
    for label, inter in methods.items():
        if val(label) != inter:
            bad.append(("method", label, val(label), inter))
    for label, raw in RAW.items():
        if val(label) != raw:
            bad.append(("raw", label, val(label), raw))
    for label, info in resolve_full(mc).items():
        if info is None:
            continue
        m = re.search(r'\{"%s"\s*,\s*"([^"]*)"' % label, txt)
        got = m.group(1) if m else None
        if got != info["desc"]:
            bad.append(("sig", label, got, info["desc"]))

    for kind, label, got, want in bad:
        print("[X] %-8s %-16s Names.java=%s  应为 %s" % (kind, label, got, want))
    for kind, label, what, msg in errors:
        print("[X] 解析失败 %-8s %-16s %s\n    %s" % (kind, label, what, msg))
    if bad or errors:
        print("\n核对失败：%d 项不一致，%d 项无法解析。" % (len(bad), len(errors)))
        return 1
    print("核对通过：%d 类 / %d 字段 / %d 方法 / %d 描述符 与映射完全一致。"
          % (len(classes), len(fields), len(methods), len(resolve_full(mc))))
    return 0


def names_java_source(mc=DEFAULT_MC):
    """生成完整的 Names.java 源码。"""
    block, errors = java_block(mc)
    header = '''package fishprobe;

/**
 * 全部 intermediary 名 —— fishprobe 探针（纯反射，不链接任何 MC 类）的根基。
 *
 * ★ 本文件由 `python fishmap.py --write` 生成，不要手改 ★
 *   改完请跑 `python fishmap.py --check` 逐字核对。
 *
 * 推导链：Mojang 官方映射 client-%s.txt（named -> obf）
 *       + Fabric intermediary-%s.jar 的 mappings/mappings.tiny（obf -> intermediary）
 *       两者按 obf 名对接。见同目录 mapbridge.py。
 *
 * 与 coordbridge 的 Names.java 是**两套独立目标表**（那套是区块直读，这套是
 * BossBar / Title / 手持物观察），共用同一个 mapbridge.py 推导器。
 *
 * ★ 版本事实（2026-10-14 逐条实测，别再照抄资料猜）★
 * 1. `BossEvent` 在 **net.minecraft.world**，1.20.1 到 1.20.5 **一直没搬**（intermediary 恒为
 *    class_1259）。早先这里记的「1.20.2+ 搬到 client.gui.components」是**错的**——
 *    那是它的**容器** BossHealthOverlay，那个本来就一直在 client.gui.components。
 * 2. 进度方法叫 **getProgress()**（1.20.1 与 1.20.4 一致，未改名）。
 * 3. 1.20.4 的 BossEvent **没有 getStyle()**。
 * 4. `Component.getString()` **不经过混淆**（它实现了 brigadier 的 Message#getString），
 *    intermediary 里查不到它 —— 直接写死 "getString"，见固定表。
 * 5. ★ **1.20.1 与 1.20.4 的 intermediary 名完全一致**：Fabric 为这两个版本生成的
 *    mappings.tiny 逐字节相同（CLASS 段各 7764 行全等）。因此本文件两版通用，
 *    同一个 jar 可同时装进两个客户端；换版本只需 `python fishmap.py --mc <版本>`。
 */
final class Names {
    private Names() {
    }

''' % (mc, mc)
    return header + block + "\n}\n", errors


def write_names(mc=DEFAULT_MC):
    src, errors = names_java_source(mc)
    os.makedirs(os.path.dirname(NAMES_JAVA), exist_ok=True)
    with open(NAMES_JAVA, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src)
    print("已写入 %s（%d 字节）" % (NAMES_JAVA, len(src.encode("utf-8"))))
    if errors:
        for kind, label, what, msg in errors:
            print("[X] %s %s %s -- %s" % (kind, label, what, msg))
        return 1
    return 0


def main():
    mc = DEFAULT_MC
    if "--mc" in sys.argv:
        mc = sys.argv[sys.argv.index("--mc") + 1]

    if "--check" in sys.argv:
        return check(mc)

    if "--write" in sys.argv:
        return write_names(mc)

    if "--java" in sys.argv:
        block, errors = java_block(mc)
        print(block)
        if errors:
            print()
            print("!! %d 项解析失败：" % len(errors))
            for kind, label, what, msg in errors:
                print("   [%s] %-16s %s\n        %s" % (kind, label, what, msg))
            return 1
        return 0

    _, classes, fields, methods, errors = resolve(mc)
    full = resolve_full(mc)
    print("MC 版本：%s" % mc)
    print("%-16s %-46s %s" % ("键", "intermediary", "官方名"))
    print("-" * 116)
    for key, official in CLS.items():
        print("%-16s %-46s %s" % ("C_" + key, classes.get(key, "ERR"), official))
    print()
    for label, key, name in FIELDS:
        print("%-16s %-46s %s.%s" % (label, fields.get(label, "ERR"), CLS[key], name))
    print()
    for label, key, name, args in METHODS:
        info = full.get(label) or {}
        print("%-16s %-46s %s.%s(%s)  %s"
              % (label, methods.get(label, "ERR"), CLS[key], name, args,
                 info.get("desc", "")))
    print()
    for label, raw in RAW.items():
        print("%-16s %-46s （不混淆，固定名）" % (label, raw))
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
