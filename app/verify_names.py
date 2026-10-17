# -*- coding: utf-8 -*-
"""verify_names.py —— 逐条核对模组里写死的 intermediary 名（**独立重算**，不看代码注释）

为什么要单独有这一步
--------------------
模组全靠字符串反射访问 MC。**映射名写错不会报错，只会静默不干活**
（本项目已踩过）。而 Names.java 的注释再怎么写「已核验」，也只是注释；
真正可信的是「从 Mojang 官方映射 + Fabric intermediary **重新推导一遍**，
再与代码里写死的字符串逐字比对」。

推导链（与 mapbridge 一致）：
    Mojang client.txt：official 名 -> obf 名（含字段表 / 方法签名表）
    Fabric intermediary：obf 名 -> intermediary 名
    两者按 obf 名对接。

用法：
    python verify_names.py                 # 核 fishauto
    python verify_names.py --mod fishprobe
    python verify_names.py --all
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from mapbridge import Bridge                                  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

MC = "1.20.4"

# --------------------------------------------------------------------------
# 期望表：常量名 -> (类型, official 类, [名字], [参数源码类型])
# 类型：class / field / method
# --------------------------------------------------------------------------
MCM = "net.minecraft.client.Minecraft"
GM = "net.minecraft.client.gui.Gui"
OPT = "net.minecraft.client.Options"
KM = "net.minecraft.client.KeyMapping"

TABLES = {
    "fishauto": {
        # ---- 类 ----
        "C_MC": ("class", MCM, None, None),
        "C_GUI": ("class", GM, None, None),
        "C_OPTIONS": ("class", OPT, None, None),
        "C_KEYBIND": ("class", KM, None, None),
        "C_PLAYER": ("class", "net.minecraft.world.entity.player.Player", None, None),
        "C_COMPONENT": ("class", "net.minecraft.network.chat.Component", None, None),
        "C_LIVING": ("class", "net.minecraft.world.entity.LivingEntity", None, None),
        "C_ITEMSTACK": ("class", "net.minecraft.world.item.ItemStack", None, None),
        "C_REGISTRY": ("class", "net.minecraft.core.Registry", None, None),
        "C_BUILTIN": ("class", "net.minecraft.core.registries.BuiltInRegistries", None, None),
        # ---- 字段 ----
        "F_PLAYER": ("field", MCM, "player", None),
        "F_LEVEL": ("field", MCM, "level", None),
        "F_GUI": ("field", MCM, "gui", None),
        "F_SCREEN": ("field", MCM, "screen", None),
        "F_OPTIONS": ("field", MCM, "options", None),
        "F_TITLE": ("field", GM, "title", None),
        "F_SUBTITLE": ("field", GM, "subtitle", None),
        "F_OVERLAY_MSG": ("field", GM, "overlayMessageString", None),
        "F_KB_ATTACK": ("field", OPT, "keyAttack", None),
        "F_KB_USE": ("field", OPT, "keyUse", None),
        "F_KB_SHIFT": ("field", OPT, "keyShift", None),
        "F_KB_JUMP": ("field", OPT, "keyJump", None),
        "F_KB_DOWN": ("field", KM, "isDown", None),
        "F_KB_CLICKS": ("field", KM, "clickCount", None),
        "F_FISHING": ("field", "net.minecraft.world.entity.player.Player", "fishing", None),
        "F_ITEM_REG": ("field", "net.minecraft.core.registries.BuiltInRegistries", "ITEM", None),
        # ---- 方法 ----
        "M_INSTANCE": ("method", MCM, "getInstance", ""),
        "M_IS_DOWN": ("method", KM, "isDown", ""),
        "M_SET_DOWN": ("method", KM, "setDown", "boolean"),
        "M_CONSUME": ("method", KM, "consumeClick", ""),
        "M_MAIN_HAND": ("method", "net.minecraft.world.entity.LivingEntity",
                        "getMainHandItem", ""),
        "M_ITEM_GET": ("method", "net.minecraft.world.item.ItemStack", "getItem", ""),
        "M_ITEM_KEY": ("method", "net.minecraft.core.Registry", "getKey",
                       "java.lang.Object"),
    },
}

# 只有这些常量出现在 SIGS 里，需要顺带核对描述符
SIG_EXPECT = {
    "M_INSTANCE": ("method", MCM, "getInstance", ""),
    "M_IS_DOWN": ("method", KM, "isDown", ""),
    "M_SET_DOWN": ("method", KM, "setDown", "boolean"),
    "M_CONSUME": ("method", KM, "consumeClick", ""),
    "M_MAIN_HAND": ("method", "net.minecraft.world.entity.LivingEntity",
                    "getMainHandItem", ""),
    "M_ITEM_GET": ("method", "net.minecraft.world.item.ItemStack", "getItem", ""),
    "M_ITEM_KEY": ("method", "net.minecraft.core.Registry", "getKey", "java.lang.Object"),
}


def parse_names(path):
    """把 Names.java 里 static final String X = "..."; 抽成 dict。"""
    out = {}
    for m in re.finditer(r'static\s+final\s+String\s+(\w+)\s*=\s*"([^"]*)"\s*;',
                         open(path, encoding="utf-8").read()):
        out[m.group(1)] = m.group(2)
    return out


def parse_sigs(path):
    """把 Names.java 的 SIGS 数组抽成 {常量名: 描述符}。"""
    txt = open(path, encoding="utf-8").read()
    i = txt.find("SIGS")
    if i < 0:
        return {}
    seg = txt[i:]
    out = {}
    for m in re.finditer(r'\{\s*"(\w+)"\s*,\s*"([^"]+)"\s*\}', seg):
        out[m.group(1)] = m.group(2)
    return out


def verify(mod, b):
    root = os.path.join(HERE, mod)
    path = os.path.join(root, "src", mod, "Names.java")
    got = parse_names(path)
    sigs = parse_sigs(path)
    table = TABLES[mod]

    print("=" * 78)
    print("核对 [%s] %s（independently recomputed from %s mappings）"
          % (mod, os.path.relpath(path, HERE), MC))
    print("=" * 78)

    bad = 0
    missing = [k for k in table if k not in got]
    extra = [k for k in got if k not in table and not k.startswith("M_COMPONENT")]
    for k in missing:
        print("  [X] Names.java 缺少常量 %s" % k)
        bad += 1
    if extra:
        print("  [!] Names.java 里有未列入核对表的常量: %s" % ", ".join(extra))

    rows = []
    for const, spec in sorted(table.items()):
        kind, cls, name, args = spec
        try:
            if kind == "class":
                # Bridge 给的是 JVM 内部名（斜杠），Names.java 里是 Class.forName 用的点号名
                want = b.cls(cls).replace("/", ".")
            elif kind == "field":
                want = b.field(cls, name)
            else:
                want = b.method(cls, name, args)
        except Exception as e:                              # noqa: BLE001
            want = "ERROR: %s" % e
        have = got.get(const, "(缺失)")
        ok = have == want
        if not ok:
            bad += 1
        rows.append((const, kind, cls.split(".")[-1], name or "", have, want, ok))

    w = max(len(r[0]) for r in rows)
    for const, kind, cls, name, have, want, ok in rows:
        label = "%s.%s" % (cls, name) if name else cls
        print("  %s %-*s %-6s %-42s %s" % (
            "[v]" if ok else "[X]", w, const, kind, label,
            have if ok else "写的是 %s，应为 %s" % (have, want)))

    # ---- 描述符 ----
    if sigs:
        print()
        print("  SIGS 描述符（运行期自检用的那张表）：")
        for const, desc in sorted(sigs.items()):
            spec = SIG_EXPECT.get(const)
            if not spec:
                print("    [!] %s 不在核对表里" % const)
                continue
            _, cls, name, args = spec
            c = b.classes[cls]
            cand = c["by_name"][name]
            if args is not None:
                cand = [x for x in cand if x[0][1:].partition(")")[0] == args]
            src = cand[0][0]
            want = b.inter_desc(b.obf_desc(src))
            ok = desc == want
            if not ok:
                bad += 1
            print("    %s %-14s %s" % ("[v]" if ok else "[X]", const,
                                       desc if ok else "写的是 %s，应为 %s" % (desc, want)))

    print()
    if bad == 0:
        print("== [%s] 全部 %d 个常量与 %d 个描述符逐字一致 ==" % (mod, len(table), len(sigs)))
        print("   结论：运行期不会因为映射名写错而静默失效。")
        return 0
    print("== [%s] 有 %d 处不一致 ==" % (mod, bad))
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mod", default="fishauto", choices=sorted(TABLES))
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    b = Bridge(MC)
    print("映射来源：%s" % os.path.basename(b.client_txt))
    print("           %s" % os.path.basename(b.intermediary_jar))
    print()
    rc = 0
    for m in (sorted(TABLES) if a.all else [a.mod]):
        rc |= verify(m, b)
        print()
    return rc


if __name__ == "__main__":
    sys.exit(main())
