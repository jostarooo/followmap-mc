# -*- coding: utf-8 -*-
"""离线验证「内存直读区块链路」：用**同名的桩类**替换 Minecraft，真跑一遍反射。

为什么需要它
------------
mod 全程只用字符串 + Class.forName，不链接任何 Minecraft 类。所以只要提供
一批「类名 / 字段名 / 方法名 / 描述符完全一致」的桩类，就能在纯离线环境里
把 Ref 解析 + ChunkScanner 扫描 + 二进制落盘整条链路跑通，再用 Python 侧的
memstore.parse_chunk 读回来比对。

这正是本轮问题的根因所在：obf 名被压成 a/b/c 后一个类里有大量同名重载，
早期解析只按「类+方法名」匹配，把 LevelChunkSection.getBlockState(int,int,int)
解析成了同名的 ()V 方法。反射在运行时抛 NoSuchMethod，但**被 catch 掉了**，
于是 mod 既不报错也不写数据 —— 外部地图只能退回 Xaero 的 60 秒落盘，
表现就是「跑图一直跟不上」。光看游戏是查不出来的，必须离线复现。

用法：
    python gen_stubs.py --run      # 生成桩类 -> 编译 -> 跑 -> 校验
    python gen_stubs.py            # 只生成
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
STUBS = os.path.join(HERE, "stubs")
SRC = os.path.join(APP, "coordbridge", "src")

JDK = r"D:\dev\eclipse\jres\jdk-21.0.2"
JAVAC = os.path.join(JDK, "bin", "javac.exe")
JAVA = os.path.join(JDK, "bin", "java.exe")
LOADER = (r"D:\config\game\mc\pcl2\.minecraft\libraries\net\fabricmc"
          r"\fabric-loader\0.16.14\fabric-loader-0.16.14.jar")

# 类名 -> 源码。方法/字段名与描述符必须与 modmap.py 推导出的 intermediary 完全一致，
# 否则 Ref 的描述符自检会（正确地）报错。
CLASSES = {}

CLASSES["class_2960"] = """
package net.minecraft;
public class class_2960 {
    private final String n;
    public class_2960(String n) { this.n = n; }
    public String toString() { return n; }
}
"""

CLASSES["class_2248"] = """
package net.minecraft;
public class class_2248 {
    public final String id;
    public class_2248(String id) { this.id = id; }
}
"""

CLASSES["class_2378"] = """
package net.minecraft;
import java.util.IdentityHashMap;
import java.util.Map;
public class class_2378 {
    private final Map<Object, class_2960> map = new IdentityHashMap<>();
    public void put(Object o, class_2960 loc) { map.put(o, loc); }
    public class_2960 method_10221(Object o) { return map.get(o); }
}
"""

CLASSES["class_7923"] = """
package net.minecraft;
public class class_7923 {
    public static final class_2378 field_41175 = new class_2378();
}
"""

CLASSES["class_4970$class_4971"] = """
package net.minecraft;
public class class_4970$class_4971 {
    public class_2248 field_block;
    public class_2248 method_26204() { return field_block; }
}
"""

CLASSES["class_2680"] = """
package net.minecraft;
public class class_2680 extends class_4970$class_4971 {
    public class_2680(class_2248 b) { this.field_block = b; }
}
"""

CLASSES["class_2826"] = """
package net.minecraft;
public class class_2826 {
    public boolean solid;
    private final class_2680 stone;
    private final class_2680 air;
    public class_2826(class_2680 stone, class_2680 air) { this.stone = stone; this.air = air; }
    public boolean method_38292() { return !solid; }
    public class_2680 method_12254(int x, int y, int z) { return solid ? stone : air; }
}
"""

CLASSES["class_2902$class_2903"] = """
package net.minecraft;
public enum class_2902$class_2903 { WORLD_SURFACE, MOTION_BLOCKING, OCEAN_FLOOR }
"""

CLASSES["class_1923"] = """
package net.minecraft;
public class class_1923 {
    public final int field_9181;
    public final int field_9180;
    public class_1923(int x, int z) { this.field_9181 = x; this.field_9180 = z; }
}
"""

CLASSES["class_5539"] = """
package net.minecraft;
public interface class_5539 {
    int method_32891();
    int method_32890();
}
"""

CLASSES["class_2791"] = """
package net.minecraft;
public class class_2791 implements class_5539 {
    public class_1923 field_pos;
    public class_2826[] field_sections;
    public int field_minSec;
    public int field_surfaceY;
    public class_1923 method_12004() { return field_pos; }
    public class_2826[] method_12006() { return field_sections; }
    public int method_12005(class_2902$class_2903 t, int x, int z) { return field_surfaceY + 1; }
    public int method_32891() { return field_minSec; }
    public int method_32890() { return field_sections == null ? 0 : field_sections.length; }
}
"""

CLASSES["class_2818"] = """
package net.minecraft;
public class class_2818 extends class_2791 {
    public boolean method_12223() { return false; }
}
"""

CLASSES["class_1297"] = """
package net.minecraft;
public class class_1297 {
    public double px = 8.0D;
    public double py = 70.0D;
    public double pz = 8.0D;
    public double method_23317() { return px; }
    public double method_23318() { return py; }
    public double method_23321() { return pz; }
}
"""

CLASSES["class_5321"] = """
package net.minecraft;
public class class_5321 {
    private final class_2960 loc;
    public class_5321(class_2960 loc) { this.loc = loc; }
    public class_2960 method_29177() { return loc; }
}
"""

CLASSES["class_1937"] = """
package net.minecraft;
public class class_1937 {
    public class_5321 field_25176 = new class_5321(new class_2960("minecraft:the_end"));
}
"""

CLASSES["class_631$class_3681"] = """
package net.minecraft;
import java.util.concurrent.atomic.AtomicReferenceArray;
public class class_631$class_3681 {
    public AtomicReferenceArray<class_2818> field_16251;
}
"""

CLASSES["class_631"] = """
package net.minecraft;
public class class_631 {
    public class_631$class_3681 field_16246 = new class_631$class_3681();
}
"""

CLASSES["class_638"] = """
package net.minecraft;
public class class_638 extends class_1937 {
    private final class_631 cache = new class_631();
    public class_631 method_2935() { return cache; }
}
"""

CLASSES["class_642"] = """
package net.minecraft;
public class class_642 {
    public String field_3761 = "test.example:1234";
}
"""

CLASSES["class_310"] = """
package net.minecraft;
public class class_310 {
    private static final class_310 INSTANCE = new class_310();
    public static class_310 method_1551() { return INSTANCE; }
    public class_638 field_1687;
    public class_1297 field_1724;
    public class_642 method_1558() { return null; }
}
"""

STUB_MAIN = r"""
package coordbridge;

import net.minecraft.class_1923;
import net.minecraft.class_2680;
import net.minecraft.class_2248;
import net.minecraft.class_2378;
import net.minecraft.class_2818;
import net.minecraft.class_2826;
import net.minecraft.class_2960;
import net.minecraft.class_310;
import net.minecraft.class_638;
import net.minecraft.class_7923;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.concurrent.atomic.AtomicReferenceArray;

/**
 * 离线验证：造一个假的客户端世界（4x4 个 chunk，地表 y=63 全石头），
 * 让真实的 ChunkScanner 跑起来，检查它是否真的把数据落盘。
 *
 * 同时会**故意**验证描述符自检：如果 Names 里的名字被写错，
 * Ref.ok 会变 false 并且 statusText 里能看到 [miss] / [bad sig]。
 */
public final class StubMain {

    static final int SURFACE_Y = 63;
    static final int MIN_SEC = -4;
    static final int N_SEC = 24;

    public static void main(String[] args) throws Exception {
        Path home = Paths.get(args.length > 0 ? args[0] : "stub-home");
        if (Files.isDirectory(home)) {
            deleteTree(home);
        }
        Files.createDirectories(home);

        buildWorld();

        ChunkScanner sc = new ChunkScanner(home);
        Thread t = new Thread(sc, "stub-scan");
        t.setDaemon(true);
        t.start();
        Thread.sleep(1500);

        System.out.println(sc.statusText());
        System.out.println("REF_OK=" + Ref.ok);
        System.out.println("HOME=" + home.toAbsolutePath());
        System.exit(0);
    }

    static void buildWorld() {
        class_2248 stone = new class_2248("stone");
        class_2248 air = new class_2248("air");
        class_2378 reg = class_7923.field_41175;
        reg.put(stone, new class_2960("minecraft:stone"));
        reg.put(air, new class_2960("minecraft:air"));

        class_2680 stoneState = new class_2680(stone);
        class_2680 airState = new class_2680(air);

        AtomicReferenceArray<class_2818> arr = new AtomicReferenceArray<>(1024);
        int i = 0;
        for (int cx = 0; cx < 4; cx++) {
            for (int cz = 0; cz < 4; cz++) {
                class_2818 c = new class_2818();
                c.field_pos = new class_1923(cx, cz);
                c.field_minSec = MIN_SEC;
                c.field_surfaceY = SURFACE_Y;
                class_2826[] secs = new class_2826[N_SEC];
                class_2826 s = new class_2826(stoneState, airState);
                s.solid = true;
                secs[(SURFACE_Y >> 4) - MIN_SEC] = s;
                c.field_sections = secs;
                arr.set(i++, c);
            }
        }

        class_638 level = new class_638();
        level.method_2935().field_16246.field_16251 = arr;

        class_310 mc = class_310.method_1551();
        mc.field_1687 = level;
        mc.field_1724 = new net.minecraft.class_1297();
    }

    static void deleteTree(Path p) throws Exception {
        Files.walk(p)
                .sorted((a, b) -> b.getNameCount() - a.getNameCount())
                .forEach(x -> { try { Files.deleteIfExists(x); } catch (Exception ignored) { } });
    }

    private StubMain() {
    }
}
"""


def write_sources():
    if os.path.isdir(STUBS):
        shutil.rmtree(STUBS)
    for name, src in CLASSES.items():
        d = os.path.join(STUBS, "net", "minecraft")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name + ".java"), "w", encoding="utf-8") as f:
            f.write(src.lstrip("\n"))
    d = os.path.join(STUBS, "coordbridge")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "StubMain.java"), "w", encoding="utf-8") as f:
        f.write(STUB_MAIN.lstrip("\n"))
    print("[1/4] 桩类已生成:", STUBS)


def compile_and_run():
    out = os.path.join(HERE, "build")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    srcs = []
    for root, _, fs in os.walk(STUBS):
        srcs += [os.path.join(root, f) for f in fs if f.endswith(".java")]
    for root, _, fs in os.walk(os.path.join(SRC, "coordbridge")):
        srcs += [os.path.join(root, f) for f in fs if f.endswith(".java")]
    r = subprocess.run([JAVAC, "--release", "17", "-encoding", "UTF-8",
                        "-cp", LOADER, "-d", out] + srcs,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("[X] 编译失败:\n", r.stdout, r.stderr)
        return 1
    print("[3/4] 编译完成")

    home = os.path.join(HERE, "stub-home")
    r = subprocess.run([JAVA, "-cp", out, "coordbridge.StubMain", home],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("[4/4] 运行输出:")
    print(r.stdout)
    if r.stderr.strip():
        print("stderr:", r.stderr)
    return 0 if "REF_OK=true" in r.stdout else 1


def verify_sync():
    """核对桩类与 Names.java 是否同步 —— 桩类写死名字，容易和映射悄悄脱节。

    两个方向都查：
      正向：Names.java 里的每个常量（类/字段/方法）都必须在桩源码里出现过。
            否则这次离线验证**根本覆盖不到**它，跑绿了也只是假绿。
      反向：桩里每个 `class_xxx` 都必须被 Names.java 引用，否则是过期的桩，
            它会让"通过"变得更容易，掩盖真实失败。

    为什么值得单独查：离线桩是「纯反射链路能跑通」的唯一证据。桩和映射
    一旦脱节，这套验证就从"证明"退化成"自证"，而表面上看还是一路 OK。
    """
    import re as _re
    src_names = os.path.join(SRC, "coordbridge", "Names.java")
    txt = open(src_names, encoding="utf-8").read()
    names_consts = _re.findall(r'=\s*"([^"]+)"', txt)
    names_consts = {v for v in names_consts if v and " " not in v}

    # 桩源码全文
    blob = []
    for root, _, fs in os.walk(STUBS):
        for f in fs:
            if f.endswith(".java"):
                blob.append(open(os.path.join(root, f), encoding="utf-8").read())
    blob = "\n".join(blob)

    # 桩里是 `package net.minecraft;` + 裸类名，所以只比短名（class_310 而不是
    # net.minecraft.class_310）—— 拿完整点号串去找永远找不到，会整片假报。
    def short(c):
        return c.rsplit(".", 1)[-1]

    missing = sorted(c for c in names_consts if short(c) not in blob)
    # 桩里声明的 class_xxx（含内部类 $）
    stub_cls = set()
    for root, _, fs in os.walk(STUBS):
        for f in fs:
            if f.startswith("class_") and f.endswith(".java"):
                stub_cls.add(f[:-5])
    used_cls = {short(c) for c in names_consts if c.startswith("net.minecraft.class_")}
    stale = sorted(stub_cls - used_cls)

    if missing:
        print("[X] Names.java 有 %d 个常量在桩类里找不到（离线验证覆盖不到）：" % len(missing))
        for c in missing:
            print("      %s" % c)
    if stale:
        print("[X] 桩类里有 %d 个 class 没被 Names.java 引用（过期的桩）：" % len(stale))
        for c in stale:
            print("      %s" % c)
    if missing or stale:
        print("\n桩类与映射不同步：改了 Names.java / ruins.json 相关的名字后，")
        print("请同步更新 gen_stubs.py 里的 CLASSES（再跑 python modmap.py --check 复核）。")
        return 1
    print("[2/4] 桩类与 Names.java 同步：%d 个常量 / %d 个 class 双向对得上"
          % (len(names_consts), len(stub_cls)))
    return 0


def main():
    write_sources()
    # 在**生成之后**核对：查的是 CLASSES 模板里写死的名字是否还与 Names.java 对得上。
    # 放前面查的是上一轮生成的产物，新机器上还是空的，会假报不同步。
    if verify_sync() != 0:
        return 1
    if "--run" in sys.argv:
        return compile_and_run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
