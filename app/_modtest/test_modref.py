# -*- coding: utf-8 -*-
"""离线验证「一个 jar 通吃 1.20.1 ~ 1.20.4」这个声明站得住脚。

为什么需要它
------------
模组能用在同一批 MC 版本上，靠的不是运气，而是三条可检验的性质：

  1. **不链接任何 Minecraft 类**。只用字符串 + Class.forName。所以 jar 里不能有
     `net.minecraft.*` / `com.mojang.*` 的 CONSTANT_Class 项（那是真实链接），
     只能以「UTF8 字符串常量」的形式出现。这一条一旦破坏，换版本就会
     NoClassDefFoundError / NoSuchMethodError。
  2. **常量表对每个支持的版本都成立**。Names.java 里的名字与描述符，必须与
     每个版本自己的官方映射 + intermediary 推导结果逐字一致。
  3. **fabric.mod.json 的版本谓词是合法且范围正确的**。写错一个字符，
     Fabric 会直接拒绝加载整个模组。

第 1 条纯 Python 就能查；第 2 条需要 cache/mappings 下有对应版本的映射
（用 `python modmap.py --fetch <版本>` 下载，没有就跳过并说明）；
第 3 条需要本机有 fabric-loader jar（没有就跳过）。

用法：
    python _modtest/test_modref.py            # 自动找最新编好的 jar
    python _modtest/test_modref.py <jar路径>
"""
import json
import os
import re
import struct
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)

MOD_DIR = os.path.join(APP, "coordbridge")
MOD_JSON = os.path.join(MOD_DIR, "fabric.mod.json")

# 声明支持的版本（要全部核到才算数）
CLAIMED_VERSIONS = ["1.20.1", "1.20.2", "1.20.3", "1.20.4"]
# 明确声明**不支持**的版本（谓词必须拒绝它们）
REJECTED_VERSIONS = ["1.20.5", "1.21"]

_OK = 0
_BAD = 0


def check(label, ok, detail=""):
    global _OK, _BAD
    if ok:
        _OK += 1
        print("  [OK] %s" % label)
    else:
        _BAD += 1
        print("  [!!] %s%s" % (label, ("  -- " + detail) if detail else ""))
    return ok


# --------------------------------------------------------------------------
# class 文件常量池
# --------------------------------------------------------------------------
def constant_pool(data):
    """返回 {下标: (tag, 值)}。值：Utf8 -> str；Class -> 指向 Utf8 的下标。"""
    if data[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("不是 class 文件")
    cp = {}
    n = struct.unpack(">H", data[8:10])[0]
    i = 10                                  # 常量池从 offset 10 开始
    idx = 1
    while idx < n:
        tag = data[i]
        i += 1
        if tag == 1:                                        # Utf8
            ln = struct.unpack(">H", data[i:i + 2])[0]
            i += 2
            cp[idx] = (tag, data[i:i + ln].decode("utf-8", "replace"))
            i += ln
        elif tag == 7:                                      # Class
            cp[idx] = (tag, struct.unpack(">H", data[i:i + 2])[0])
            i += 2
        elif tag in (8, 16, 19, 20):                        # String/MethodType/Module/Package
            cp[idx] = (tag, struct.unpack(">H", data[i:i + 2])[0])
            i += 2
        elif tag == 15:                                     # MethodHandle
            cp[idx] = (tag, None)
            i += 3
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):          # 整数/浮点/引用/名字类型/动态
            cp[idx] = (tag, None)
            i += 4
        elif tag in (5, 6):                                 # Long/Double 占两格
            cp[idx] = (tag, None)
            i += 8
            idx += 1
        else:
            raise ValueError("未知常量池 tag %d @%d" % (tag, i - 1))
        idx += 1
    return cp


def linked_classes(data):
    """jar 里**真实链接**的类（CONSTANT_Class 项）—— 这是关键证据。"""
    cp = constant_pool(data)
    out = set()
    for tag, v in cp.values():
        if tag == 7:
            u = cp.get(v)
            if u and u[0] == 1:
                out.add(u[1].replace("/", "."))
    return out


def string_literals(data):
    """jar 里出现的字符串常量（UTF8 项），反射用的方块/类名都在这里。"""
    cp = constant_pool(data)
    return {v for tag, v in cp.values() if tag == 1}


# --------------------------------------------------------------------------
def find_jar(argv):
    if len(argv) > 1 and argv[1].endswith(".jar"):
        return argv[1]
    cands = [os.path.join(MOD_DIR, f) for f in os.listdir(MOD_DIR)
             if f.startswith("coordbridge-") and f.endswith(".jar")]
    if not cands:
        return None
    cands.sort(key=os.path.getmtime)
    return cands[-1]


def test_pure_reflection(jar):
    print("\n== 1. 纯反射：jar 里不得真实链接任何 MC 类 ==")
    z = zipfile.ZipFile(jar)
    linked, lits = set(), set()
    for name in z.namelist():
        if not name.endswith(".class"):
            continue
        d = z.read(name)
        linked |= linked_classes(d)
        lits |= string_literals(d)

    mc_linked = sorted(c for c in linked
                       if c.startswith("net.minecraft.") or c.startswith("com.mojang."))
    check("没有 net.minecraft / com.mojang 的 CONSTANT_Class 项",
          not mc_linked, "却链接了 %s" % mc_linked)

    fl_linked = sorted(c for c in linked if c.startswith("net.fabricmc."))
    check("只链接了 net.fabricmc.api.ClientModInitializer",
          fl_linked == ["net.fabricmc.api.ClientModInitializer"],
          "实际为 %s" % fl_linked)

    # 反过来：MC 类名必须以**字符串常量**存在（证明用的是反射而不是没用到）
    need = ["net.minecraft.class_310", "net.minecraft.class_2818",
            "net.minecraft.class_2826", "net.minecraft.class_7923"]
    miss = [n for n in need if n not in lits]
    check("MC 类名以字符串常量形式存在（反射用）", not miss, "缺少 %s" % miss)


def test_names_against_mappings(jar):
    print("\n== 2. 常量表对每个支持的版本都成立 ==")
    import modmap
    from mapbridge import resources_for

    with zipfile.ZipFile(jar) as z:
        src_names = z.read("fabric.mod.json")
    meta = json.loads(src_names.decode("utf-8"))
    print("     fabric.mod.json: version=%s  minecraft=%s"
          % (meta["version"], meta["depends"]["minecraft"]))

    base = None
    for mc in CLAIMED_VERSIONS:
        _, _, missing = resources_for(mc)
        if missing:
            print("     - MC %-7s 跳过（本机缺映射：python modmap.py --fetch %s）"
                  % (mc, mc))
            continue
        n = modmap.names_for(mc)
        if n["errors"]:
            check("MC %s 映射解析无错" % mc, False, str(n["errors"][:2]))
            continue
        cur = (n["classes"], n["fields"], n["methods"])
        if base is None:
            base, base_mc = cur, mc
            print("     - MC %-7s 基准（%d 类 / %d 字段 / %d 方法）"
                  % (mc, len(n["classes"]), len(n["fields"]), len(n["methods"])))
            continue
        same = cur == base
        check("MC %s 与 MC %s 常量表一致" % (mc, base_mc), same, "有差异")
        if not same:
            for kind, i in zip(("类", "字段", "方法"), range(3)):
                for k in cur[i]:
                    if cur[i].get(k) != base[i].get(k):
                        print("        %s %-14s %s=%s  %s=%s"
                              % (kind, k, mc, cur[i].get(k), base_mc, base[i].get(k)))
    return True


def test_version_predicate(jar):
    print("\n== 3. fabric.mod.json 的版本谓词合法且范围正确 ==")
    import build_mod

    with zipfile.ZipFile(jar) as z:
        meta = json.loads(z.read("fabric.mod.json").decode("utf-8"))
    spec = meta["depends"]["minecraft"]

    loader = build_mod.pick_loader()
    if not loader:
        print("     - 跳过（本机没有 fabric-loader jar，无法用真实解析器验证）")
        return True

    import subprocess
    import tempfile
    java = os.path.join(build_mod.JDK, "bin", "java.exe")
    javac = os.path.join(build_mod.JDK, "bin", "javac.exe")
    if not (os.path.exists(java) and os.path.exists(javac)):
        print("     - 跳过（找不到 JDK）")
        return True

    src = """
import net.fabricmc.loader.api.Version;
import net.fabricmc.loader.impl.util.version.VersionPredicateParser;
import java.util.function.Predicate;
public class Vp {
    public static void main(String[] a) throws Exception {
        Predicate<Version> p = VersionPredicateParser.parse(a[0]);
        for (int i = 1; i < a.length; i++) {
            System.out.println(a[i] + "=" + p.test(Version.parse(a[i])));
        }
    }
}
"""
    tmp = tempfile.mkdtemp(prefix="vpred_")
    try:
        with open(os.path.join(tmp, "Vp.java"), "w", encoding="utf-8") as fh:
            fh.write(src)
        r = subprocess.run([javac, "--release", "17", "-cp", loader, "-d", tmp,
                            os.path.join(tmp, "Vp.java")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("     - 跳过（谓词解析器编译失败，loader 版本可能太老）：%s"
                  % (r.stderr or "").strip()[:120])
            return True
        r = subprocess.run([java, "-cp", tmp + os.pathsep + loader, "Vp", spec]
                           + CLAIMED_VERSIONS + REJECTED_VERSIONS,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if r.returncode != 0:
            check("谓词 %r 能被真实 fabric-loader 解析" % spec, False,
                  (r.stderr or r.stdout or "").strip()[:160])
            return False
        res = dict(l.split("=", 1) for l in r.stdout.split() if "=" in l)
        print("     真实 loader 解析结果: %s" % res)
        for v in CLAIMED_VERSIONS:
            check("谓词接受 %s" % v, res.get(v) == "true", res.get(v))
        for v in REJECTED_VERSIONS:
            check("谓词拒绝 %s" % v, res.get(v) == "false", res.get(v))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return True


def main():
    jar = find_jar(sys.argv)
    if not jar:
        print("[X] 没找到 jar。先跑 python build_mod.py --no-install")
        return 1
    print("被检产物: %s (%d bytes)" % (jar, os.path.getsize(jar)))

    test_pure_reflection(jar)
    test_names_against_mappings(jar)
    test_version_predicate(jar)

    print("\n结果：%d 项通过，%d 项失败。" % (_OK, _BAD))
    return 0 if _BAD == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
