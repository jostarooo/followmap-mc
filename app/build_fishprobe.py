# -*- coding: utf-8 -*-
"""编译 fishprobe 探针：javac 直接编译（不需要 Gradle/Loom）+ 打包 + 安装。

依赖（都从本机客户端现取的，不联网）：
  1. fabric-loader jar —— 提供 net.fabricmc.api.ClientModInitializer
  2. fabric-api 里的 **nested 模块**：fabric-api-base / fabric-lifecycle-events-v1
     （Fabric API 是 jar-in-jar 结构，类都在 META-INF/jars/*.jar 里，
      所以必须先把需要的模块**提取出来**才能进 javac 的 classpath）

★ 为什么不用 Gradle / Loom ★
fishprobe 是**纯反射**模组：所有 Minecraft 类都通过字符串 + Class.forName 访问，
一个 MC 类都不链接。所以既不需要 MC jar，也不需要 remap，javac 一条命令就够。
（这是沿用 coordbridge 已跑通的思路；见 fishmap.py 顶部的说明。）

★ 多实例（2026-10-14）★
用户日常在玩的是 **1.20.4**（PCL2 实例），另有方块传说 V3.0 客户端（1.20.1）。
两者 intermediary 名完全一致（见 fishmap.py），所以**同一个 jar 两边都能跑**，
构建脚本按 --instance 选安装目标即可。

  用法：
    python build_fishprobe.py                    # 编译 + 装进默认实例（1.20.4）
    python build_fishprobe.py --no-install       # 只编译
    python build_fishprobe.py --instance v30     # 装进方块传说 V3.0（1.20.1）
    python build_fishprobe.py --install-all      # 装进全部已知实例
    python build_fishprobe.py --list             # 只看实例表
    python build_fishprobe.py --mods "D:\\x\\mods"   # 手工指定 mods 目录（可重复）
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _select_root():
    """--root 可指向别的模组目录（fishauto 就复用了本脚本）。"""
    if "--root" in sys.argv:
        i = sys.argv.index("--root")
        if len(sys.argv) > i + 1:
            return os.path.abspath(sys.argv[i + 1])
    return os.path.join(HERE, "fishprobe")


ROOT = _select_root()
SRC = os.path.join(ROOT, "src")
BUILD = os.path.join(ROOT, "build")
LIBS = os.path.join(ROOT, "libs")
STUBS = os.path.join(ROOT, "stubs")   # 编译期桩类（不进 jar）
MOD_JSON = os.path.join(ROOT, "fabric.mod.json")

JDK = r"D:\dev\eclipse\jres\jdk-21.0.2"
JAVAC = os.path.join(JDK, "bin", "javac.exe")

# ---------------------------------------------------------------- 目标实例
# game : gameDir —— **PCL2 开了版本隔离时，gameDir 就是 versions\<版本名>**，
#                   mods / config / saves 都在它下面（不是 .minecraft\mods！）
# libs : libraries 所在根 —— 永远在 .minecraft 下（各版本共享）
INSTANCES = {
    "1204": {
        "label": "日常 · 1.20.4（PCL2）",
        "game": r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14",
        "libs": r"D:\config\game\mc\pcl2\.minecraft",
    },
    "v30": {
        "label": "方块传说 V3.0 客户端 · 1.20.1",
        "game": r"D:\config\game\mc\方块传说V3.0客户端 2K(2560×1440)\.minecraft",
        "libs": r"D:\config\game\mc\方块传说V3.0客户端 2K(2560×1440)\.minecraft",
    },
}
DEFAULT_INSTANCE = "1204"

# 需要从 Fabric API 里提取的 nested 模块
#   fabric-api-base            -> net.fabricmc.fabric.api.event.Event（事件注册的根基）
#   fabric-lifecycle-events-v1 -> ClientTickEvents
NEED_MODULES = ["fabric-api-base", "fabric-lifecycle-events-v1"]


def instance():
    name = DEFAULT_INSTANCE
    if "--instance" in sys.argv:
        i = sys.argv.index("--instance")
        if len(sys.argv) > i + 1:
            name = sys.argv[i + 1]
    if name not in INSTANCES:
        print("[X] 未知实例 %r，可选：%s" % (name, ", ".join(INSTANCES)))
        sys.exit(2)
    return name, INSTANCES[name]


def mods_dir(inst):
    return os.path.join(inst["game"], "mods")


def _ver_key(path):
    """从 .../fabric-loader-0.16.14.jar 取 (0,16,14) 供排序。"""
    m = re.search(r"fabric-loader-([0-9][0-9.]*)\.jar$", os.path.basename(path))
    if not m:
        return ()
    return tuple(int(x) for x in m.group(1).split(".") if x.isdigit())


def _declared_loader_version(inst):
    """从实例的版本 JSON 里读它**实际使用**的 fabric-loader 版本。"""
    name = os.path.basename(inst["game"].rstrip("\\/"))
    jp = os.path.join(inst["game"], name + ".json")
    if not os.path.exists(jp):
        return None
    try:
        with open(jp, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception:                                # noqa: BLE001
        return None
    for lib in d.get("libraries", []):
        n = lib.get("name", "")
        if n.startswith("net.fabricmc:fabric-loader:"):
            return n.split(":")[-1]
    return None


def loader_jar(inst):
    """本例的 fabric-loader jar。

    优先用实例版本 JSON 声明的那个（保证与运行期一致）；取不到再回退到最高版本。
    loader 只用来编译 `ClientModInitializer`，该接口自 0.14 起未变，所以两者都安全。
    """
    v = _declared_loader_version(inst)
    if v:
        p = os.path.join(inst["libs"], "libraries", "net", "fabricmc",
                         "fabric-loader", v, "fabric-loader-%s.jar" % v)
        if os.path.exists(p):
            return p
    pat = os.path.join(inst["libs"], "libraries", "net", "fabricmc",
                       "fabric-loader", "*", "fabric-loader-*.jar")
    found = glob.glob(pat)
    if not found:
        return None
    return max(found, key=_ver_key)


def fabric_api_jar(inst):
    """本例 mods 里的 Fabric API 总包。

    1.20.4 官方名是 fabric-api-<ver>.jar；方块传说 V3.0 用的是 [LIB] Fabric API-*.jar，
    两种都兜住。
    """
    md = mods_dir(inst)
    for pat in ("fabric-api-*.jar", "*Fabric API*.jar", "fabric-api*.jar"):
        hits = sorted(glob.glob(os.path.join(md, pat)))
        # 排除 sources / javadoc 之类
        hits = [h for h in hits if "-sources" not in h and "-javadoc" not in h]
        if hits:
            return hits[0]
    return None


def extract_modules(inst):
    """把 NEED_MODULES 从 Fabric API 的 META-INF/jars/ 提取到 libs/。-> 路径列表"""
    os.makedirs(LIBS, exist_ok=True)
    api = fabric_api_jar(inst)
    if not api:
        print("[X] 在 %s 里找不到 Fabric API 总包" % mods_dir(inst))
        return []
    print("      Fabric API: %s" % os.path.basename(api))
    out = []
    with zipfile.ZipFile(api) as z:
        names = [n for n in z.namelist() if n.startswith("META-INF/jars/")]
        for mod in NEED_MODULES:
            hit = None
            for n in names:
                base = os.path.basename(n)
                # 模块 jar 名形如 fabric-lifecycle-events-v1-0.97.3.jar
                if base.startswith(mod + "-") and base.endswith(".jar"):
                    hit = n
                    break
            if hit is None:
                print("  [!] Fabric API 里找不到模块 %s" % mod)
                continue
            dst = os.path.join(LIBS, os.path.basename(hit))
            with z.open(hit) as fh, open(dst, "wb") as out_fh:
                out_fh.write(fh.read())
            print("  提取 %s -> %s" % (os.path.basename(hit), os.path.relpath(dst, HERE)))
            out.append(dst)
    return out


def mod_json():
    with open(MOD_JSON, encoding="utf-8") as fh:
        return json.load(fh)


def mod_id():
    return mod_json()["id"]


def mod_version():
    return mod_json()["version"]


def sources():
    """主源码 + 编译期桩类。桩类只为满足 javac 对 MC 类型的解析，打包时会被剔除。"""
    out = []
    for root in (SRC, STUBS):
        for d, _, fs in os.walk(root):
            for f in fs:
                if f.endswith(".java"):
                    out.append(os.path.join(d, f))
    return sorted(out)


def compile_jar(inst):
    javac = JAVAC if os.path.exists(JAVAC) else (shutil.which("javac") or JAVAC)
    if not os.path.exists(javac):
        print("[X] 缺少 javac: %s" % JAVAC)
        return None

    loader = loader_jar(inst)
    if not loader:
        print("[X] 找不到 fabric-loader jar（candidates: %s）" % inst["libs"])
        return None
    print("[0/4] 编译用 loader : %s" % os.path.basename(loader))

    libs = extract_modules(inst)
    if not libs:
        print("[X] 没能提取到 Fabric API 模块（fabric-api-base / fabric-lifecycle-events-v1）")
        return None

    cp = os.pathsep.join([loader] + libs)      # Windows 是 ';'
    srcs = sources()
    print("[1/4] 源文件 %d 个: %s" % (len(srcs), [os.path.basename(s) for s in srcs]))

    if os.path.isdir(BUILD):
        shutil.rmtree(BUILD)
    os.makedirs(BUILD)

    cmd = [javac, "-J-Duser.language=en", "-J-Duser.country=US",
           "--release", "17", "-encoding", "UTF-8",
           "-cp", cp, "-d", BUILD] + srcs
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("[X] 编译失败:\n" + (r.stdout or "") + (r.stderr or ""))
        return None
    if r.stdout or r.stderr:
        print("    编译输出: " + (r.stdout or r.stderr))
    print("[2/4] 编译完成")

    ver = mod_version()
    jar_out = os.path.join(ROOT, "%s-%s.jar" % (mod_id(), ver))
    classes = []
    for d, _, fs in os.walk(BUILD):
        for f in fs:
            if f.endswith(".class"):
                classes.append(os.path.join(d, f))
    if not classes:
        print("[X] 没有产出 class")
        return None

    with zipfile.ZipFile(jar_out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(MOD_JSON, "fabric.mod.json")
        for c in classes:
            rel = os.path.relpath(c, BUILD).replace(os.sep, "/")
            if rel.startswith("net/minecraft/"):
                continue            # 编译期桩，绝不能进 jar
            z.write(c, rel)
    print("[3/4] 打包完成: %s (%d bytes)" % (jar_out, os.path.getsize(jar_out)))
    with zipfile.ZipFile(jar_out) as z:
        for n in z.namelist():
            print("       %s" % n)
    return jar_out


def install(jar_out):
    targets = list(_multi_arg("--mods"))
    if not targets:
        if "--install-all" in sys.argv:
            for name, inst in INSTANCES.items():
                md = mods_dir(inst)
                if os.path.isdir(md):
                    targets.append(md)
                else:
                    print("[!] 跳过 %s（mods 目录不存在）: %s" % (name, md))
        else:
            name, inst = instance()
            targets = [mods_dir(inst)]

    me = os.path.basename(jar_out)
    done = 0
    for md in targets:
        if not os.path.isdir(md):
            try:
                os.makedirs(md, exist_ok=True)
            except OSError:
                print("[!] 目标不存在且建不出来: %s" % md)
                continue
        # ★ 先清旧版本 ★ 两个同 id 的 jar 会让 Fabric 直接拒绝加载整个模组
        olds = [f for f in sorted(os.listdir(md))
                if f.startswith(mod_id() + "-") and f.endswith(".jar") and f != me]
        stuck = []
        for f in olds:
            try:
                os.remove(os.path.join(md, f))
                print("      已移除旧版本: %s" % f)
            except OSError as e:
                stuck.append((f, e))
        if stuck:
            print("[!] %s 里有旧版本且删不掉（游戏在跑？）：%s" % (md, ", ".join(f for f, _ in stuck)))
            print("    **本次不安装** —— 留着两个同 id 的 jar 会让 Fabric 拒绝加载。")
            continue
        try:
            dst = os.path.join(md, me)
            shutil.copy2(jar_out, dst)
            print("[4/4] 已安装: %s" % dst)
            done += 1
        except Exception as e:                       # noqa: BLE001
            print("[!] 安装失败（%s）: %s" % (e, md))

    if not targets or not done:
        print("[4/4] 产物已就绪，未安装。手动复制:\n    %s" % jar_out)
        return 1
    return 0


def _multi_arg(flag):
    out = []
    for i, a in enumerate(sys.argv):
        if a == flag and len(sys.argv) > i + 1:
            out.append(sys.argv[i + 1])
    return out


def show_instances():
    print("已知实例：")
    for name, inst in INSTANCES.items():
        md = mods_dir(inst)
        mark = " ← 默认" if name == DEFAULT_INSTANCE else ""
        print("  [%-5s] %s%s" % (name, inst["label"], mark))
        print("          game : %s  %s" % (inst["game"], "OK" if os.path.isdir(inst["game"]) else "缺失"))
        print("          mods : %s  %s" % (md, "OK" if os.path.isdir(md) else "缺失"))
        api = fabric_api_jar(inst)
        print("          API  : %s" % (os.path.basename(api) if api else "未找到"))
        ld = loader_jar(inst)
        print("          load : %s" % (os.path.basename(ld) if ld else "未找到"))


def main():
    if "--list" in sys.argv:
        show_instances()
        return 0

    name, inst = instance()
    print("目标实例 [%s] %s" % (name, inst["label"]))
    print("  gameDir: %s" % inst["game"])
    print("  mods   : %s" % mods_dir(inst))

    jar_out = compile_jar(inst)
    if not jar_out:
        return 1
    if "--no-install" in sys.argv:
        print("[4/4] 已跳过安装（--no-install）")
        return 0
    return install(jar_out)


if __name__ == "__main__":
    sys.exit(main())
