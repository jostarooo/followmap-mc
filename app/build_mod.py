# -*- coding: utf-8 -*-
"""编译 CoordBridge 模组：javac 直接编译（不需要 Gradle/Loom）+ 打包成 jar + 安装。

依赖：
  - JDK（javac），本机 D:\\dev\\eclipse\\jres\\jdk-21.0.2
  - fabric-loader jar（提供 net.fabricmc.api.ClientModInitializer 接口，不含任何 MC 类）

★ 一个 jar 通吃 1.20.1 ~ 1.20.4 ★
模组是纯反射的：只用字符串 + Class.forName，不链接任何 Minecraft 类。它需要的
20 类 / 9 字段 / 17 方法 / 17 描述符在这几个版本间**逐字相同**（实测见
`python modmap.py --compare 1.20.1 1.20.4`，输出「63 项完全一致」），所以
**不需要按 MC 版本分别构建**，也就没有 1.20.1 专用 jar 这回事 ——
`--mc` 只决定「默认装进哪个实例」，不改变产物。

用法：
    python build_mod.py                       # 编译 + 装进 1.20.4 的 mods
    python build_mod.py --mc 1.20.1           # 编译 + 装进 1.20.1 的 mods
    python build_mod.py --install-all         # 装进所有检测到的支持版本实例
    python build_mod.py --no-install          # 只编译
    python build_mod.py --mods "D:\\xxx\\mods"   # 手工指定安装目录（可重复）
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
ROOT = os.path.join(HERE, "coordbridge")
SRC = os.path.join(ROOT, "src")
BUILD = os.path.join(ROOT, "build")
MOD_JSON = os.path.join(ROOT, "fabric.mod.json")

JDK = r"D:\dev\eclipse\jres\jdk-21.0.2"
JAVAC = os.path.join(JDK, "bin", "javac.exe")

# 找 loader / mods 目录的地方（与 followmap/paths.py 的 MC_ROOTS 同源）。
MC_ROOTS = [
    r"D:\config\game\mc\pcl2\.minecraft",
    r"D:\config\mc\.minecraft",
]
DEFAULT_MC = "1.20.4"
LOADER_MIN = (0, 14, 0)


def _loader_jars():
    """本机所有 fabric-loader jar -> [(版本元组, 路径)]，按版本升序。"""
    out = []
    for root in MC_ROOTS:
        pat = os.path.join(root, "libraries", "net", "fabricmc", "fabric-loader",
                           "*", "fabric-loader-*.jar")
        for p in glob.glob(pat):
            m = re.search(r"fabric-loader-([0-9][0-9A-Za-z.\-+]*)\.jar$",
                          os.path.basename(p))
            if not m:
                continue
            out.append((_vt(m.group(1)), p))
    out.sort()
    return out


def _vt(s):
    """'0.16.14' -> (0, 16, 14)；非数字部分丢掉。"""
    nums = re.findall(r"\d+", s)
    return tuple(int(x) for x in nums[:3]) if nums else (0,)


def pick_loader():
    """选一个 loader jar。**任何版本都行**：只用来编译一个接口，不影响运行。

    要求 >=0.14（低于这个版本 ClientModInitializer 的包名/API 不同）。
    取满足条件里**最低**的那个 —— 对着「声明支持的最低版本」编译，就不会
    无意中用到只有新 loader 才有的 API。运行期用什么版本由目标机器决定，
    与编译期无关（模组只在 class 里引用 net/fabricmc/api/ClientModInitializer，
    这个接口从 0.4 起就没变过）。
    """
    ok = [(v, p) for v, p in _loader_jars() if v >= LOADER_MIN]
    return ok[0][1] if ok else None


def mod_version():
    """从 fabric.mod.json 读版本号 —— jar 名由它推导，杜绝「文件名与元数据不一致」。"""
    with open(MOD_JSON, encoding="utf-8") as fh:
        return json.load(fh)["version"]


def supported_range():
    with open(MOD_JSON, encoding="utf-8") as fh:
        return json.load(fh)["depends"]["minecraft"]


def mc_dirs(mc):
    """某个 MC 版本在本机的实例目录（versions/<mc>* 里带 mods 或看起来像实例的）。"""
    found = []
    for root in MC_ROOTS:
        for p in sorted(glob.glob(os.path.join(root, "versions", mc + "*"))):
            if os.path.isdir(p) and not p.endswith(".zip"):
                found.append(p)
    return found


def mods_dirs(mc):
    """某版本要安装进去的 mods 目录（不存在则创建）。"""
    out = []
    for d in mc_dirs(mc):
        md = os.path.join(d, "mods")
        try:
            os.makedirs(md, exist_ok=True)
        except OSError:
            continue
        out.append(md)
    return out


def all_supported_mc():
    """本机装了的、且在声明支持范围内的 MC 版本。"""
    lo, hi = _range_bounds(supported_range())
    seen = []
    for root in MC_ROOTS:
        for p in glob.glob(os.path.join(root, "versions", "*")):
            if not os.path.isdir(p) or p.endswith(".zip"):
                continue
            m = re.match(r"^(\d+\.\d+(?:\.\d+)?)", os.path.basename(p))
            if not m:
                continue
            v = m.group(1)
            if lo <= _vt(v) < hi and v not in seen:
                seen.append(v)
    return sorted(seen, key=_vt)


def _range_bounds(spec):
    """把 ">=1.20.1 <1.20.5" 解析成 ((1,20,1), (1,20,5))。"""
    lo = (0,)
    hi = (9999,)
    for tok in spec.split():
        m = re.match(r"^([<>]=?|=)(.+)$", tok)
        if not m:
            continue
        op, ver = m.group(1), _vt(m.group(2))
        if op in (">=", ">", "="):
            lo = ver
        elif op in ("<", "<="):
            hi = ver
    return lo, hi


def main():
    javac = JAVAC
    if not os.path.exists(javac):
        # 兜底：PATH 里的 javac
        javac = shutil.which("javac") or javac
    if not os.path.exists(javac):
        print("[X] 缺少 javac: %s" % JAVAC)
        return 1

    loader = pick_loader()
    if not loader:
        print("[X] 找不到 fabric-loader jar。请在游戏里跑过一次 Fabric 版本，")
        print("    或手工指定；它只提供 ClientModInitializer 接口，不含 MC 类。")
        return 1

    ver = mod_version()
    rng = supported_range()
    jar_out = os.path.join(ROOT, "coordbridge-%s.jar" % ver)

    print("[0/4] 目标版本范围 : MC %s" % rng)
    print("      编译用 loader : %s" % os.path.basename(loader))
    print("      产物          : %s" % os.path.basename(jar_out))

    if os.path.isdir(BUILD):
        shutil.rmtree(BUILD)
    os.makedirs(BUILD)

    srcs = []
    for d, _, fs in os.walk(SRC):
        for f in fs:
            if f.endswith(".java"):
                srcs.append(os.path.join(d, f))
    srcs.sort()
    print("[1/4] 源文件 %d 个: %s" % (len(srcs), [os.path.basename(s) for s in srcs]))

    cmd = [javac, "--release", "17", "-encoding", "UTF-8",
           "-cp", loader, "-d", BUILD] + srcs
    # javac 在中文 Windows 上按 GBK 输出诊断信息，按 utf-8 硬解会抛
    # UnicodeDecodeError（而且是在 subprocess 的读线程里抛，很容易被误读成编译失败）。
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("[X] 编译失败:\n", r.stdout, r.stderr)
        return 1
    print("[2/4] 编译完成")

    classes = []
    for d, _, fs in os.walk(BUILD):
        for f in fs:
            if f.endswith(".class"):
                classes.append(os.path.join(d, f))
    if not classes:
        print("[X] 没有产出 class")
        return 1

    with zipfile.ZipFile(jar_out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(MOD_JSON, "fabric.mod.json")
        for c in classes:
            z.write(c, os.path.relpath(c, BUILD).replace(os.sep, "/"))
    print("[3/4] 打包完成: %s (%d bytes)" % (jar_out, os.path.getsize(jar_out)))
    with zipfile.ZipFile(jar_out) as z:
        for n in z.namelist():
            print("      ", n)

    # ------------------------------------------------------------ 安装
    if "--no-install" in sys.argv:
        print("[4/4] 已跳过安装（--no-install）")
        return 0

    targets = list(_multi_arg("--mods"))
    if not targets:
        if "--install-all" in sys.argv:
            vers = all_supported_mc()
            if not vers:
                print("[!] 本机没有检测到处于支持范围内的 MC 实例。")
            for v in vers:
                targets += mods_dirs(v)
            print("[4/4] --install-all：本机支持范围内的实例 %s" % (vers or "无"))
        else:
            mc = _one_arg("--mc", DEFAULT_MC)
            targets = mods_dirs(mc)
            if not targets:
                print("[!] 没找到 MC %s 的实例目录（%s 下 versions\\%s*）"
                      % (mc, "/".join(MC_ROOTS), mc))
                print("    用 --mods \"路径\" 手工指定，或 --install-all。")

    me = os.path.basename(jar_out)
    for md in targets:
        # ★ 先清旧版本，清干净了才拷新的 ★
        # 两个同 mod id 的 jar 同时在 mods/ 里，Fabric 会直接判重复、**拒绝加载整个模组**
        # （游戏起不来，而且报错指向 mods 目录，与本工具无关，很难联想到是这里造成的）。
        # 正在玩游戏时旧 jar 被 JVM 占着删不掉 —— 这时**宁可不装**，也不能留下双 jar。
        olds = [f for f in sorted(os.listdir(md))
                if f.startswith("coordbridge-") and f.endswith(".jar") and f != me]
        stuck = []
        for f in olds:
            try:
                os.remove(os.path.join(md, f))
                print("      已移除旧版本: %s" % f)
            except OSError as e:
                stuck.append((f, e))
        if stuck:
            print("[!] %s 里有旧版本且删不掉：%s" % (md, ", ".join(f for f, _ in stuck)))
            print("    **本次不安装** —— 留着两个同 id 的 jar 会让 Fabric 拒绝加载。")
            print("    原因多半是游戏正在运行（jar 被占用）。关掉游戏后再跑一次本脚本即可。")
            continue
        try:
            dst = os.path.join(md, me)
            shutil.copy2(jar_out, dst)
            print("[4/4] 已安装: %s" % dst)
        except Exception as e:                      # noqa: BLE001
            print("[!] 安装失败（%s）: %s" % (e, md))

    if not targets:
        print("[4/4] 产物已就绪，未安装。手动复制:\n    %s" % jar_out)
    return 0


def _one_arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if len(sys.argv) > i + 1:
            return sys.argv[i + 1]
    return default


def _multi_arg(flag):
    """收集所有 `--mods <路径>` 出现（可重复）。"""
    out = []
    for i, a in enumerate(sys.argv):
        if a == flag and len(sys.argv) > i + 1:
            out.append(sys.argv[i + 1])
    return out


if __name__ == "__main__":
    sys.exit(main())
