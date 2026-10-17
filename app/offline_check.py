# -*- coding: utf-8 -*-
"""离线验证模组：用**同名桩类**真跑一遍「反射解析 -> 业务逻辑 -> 落盘」全链路。

为什么非要有这一步
------------------
这些模组全靠字符串反射访问 MC，**映射写错时不会报错，只会静默不干活**
（coordbridge 就踩过：一个描述符不匹配导致整条链路无声失效，光看游戏查不出来）。
所以必须有一份「类名/方法名/描述符完全一致」的桩类，在离线环境把链路跑通、
并把产出逐项校验。

两个模组共用本脚本（`--mod` 切换）：

  fishprobe  只读探针：反射读 BossBar / Title / ActionBar / 手持物 -> JSONL
             （桩在 fishprobe/offline/src/net/minecraft/，主类 net.minecraft.OfflineTest）
  fishauto   自动钓鱼一级版：读字幕判定 + 写原版 KeyMapping 字段按键
             （桩在 fishauto/offline/src/net/minecraft/，主类 fishauto.AutoTest）

注意：**不编 FishProbe.java / FishAuto.java**（Fabric 入口，需要 fabric-api），
只编真正干活的那几个类 —— 它们的逻辑与 Fabric 无关。

另有一条独立小检查：`--pred` 用 fabric-loader 自带的谓词解析器，实测
`fabric.mod.json` 里那三条 depends 是否真的会被接受（谓词写错会让 Fabric
**直接拒绝加载整个模组**，且只在启动日志留一行）。它需要 loader jar，所以单独跑。

用法：
    python offline_check.py                 # 默认校验 fishprobe
    python offline_check.py --mod fishauto
    python offline_check.py --all           # 两个都校验
    python offline_check.py --pred          # 额外实测 fabric.mod.json 的版本谓词
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))

JDK = r"D:\dev\eclipse\jres\jdk-21.0.2"
JAVAC = os.path.join(JDK, "bin", "javac.exe")
JAVA = os.path.join(JDK, "bin", "java.exe")

# 控制台默认是 GBK，会让中文诊断信息在我们这边变成乱码 —— 强制 UTF-8。
JOPT = ["-J-Duser.language=en", "-J-Duser.country=US",
        "-J-Dfile.encoding=UTF-8", "-J-Dstdout.encoding=UTF-8",
        "-J-Dstderr.encoding=UTF-8"]
ROPT = ["-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8", "-Dstderr.encoding=UTF-8"]

# --------------------------------------------------------------------------
# 每个模组的差异点
# --------------------------------------------------------------------------
# offline/src 下这些子目录**不进默认编译**（它们需要额外依赖，见 --pred）
EXCLUDE_DIRS = {"predcheck"}

# fabric-loader jar 所在的 libraries 根（找它只为 --pred）
INST_LIBS = r"D:\config\game\mc\pcl2\.minecraft"

MODS = {
    "fishprobe": {
        "root": "fishprobe",
        # 主源码（不含 Fabric 入口 FishProbe.java）
        "main_src": ["Names.java", "Probe.java", "Sink.java"],
        # offline 源码根（下面全部 *.java 都会编进去）
        "offline_src": os.path.join("offline", "src"),
        "out": os.path.join("offline", "out"),
        "main": "net.minecraft.OfflineTest",
        "home": ".fishprobe",
        "logs": os.path.join("events", "*.jsonl"),
    },
    "fishauto": {
        "root": "fishauto",
        "main_src": ["Names.java", "Sink.java", "Config.java",
                     "Geom.java", "Qte.java", "Presser.java", "AutoFish.java"],
        "offline_src": os.path.join("offline", "src"),
        "out": os.path.join("offline", "out"),
        "main": "fishauto.AutoTest",
        "home": ".fishauto",
        "logs": os.path.join("log", "*.jsonl"),
    },
}


def fail(msg):
    print("\n[X] " + msg)
    return 1


# --------------------------------------------------------------------------
# 通用流程
# --------------------------------------------------------------------------
def compile_and_run(mod_name, cfg, keep=False):
    """编译 + 跑桩测试。-> (ok, home, out_dir, stdout)"""
    root = os.path.join(HERE, cfg["root"])
    # 主源码目录名 = 包名（fishprobe / fishauto）
    pkg_dir = os.path.join(root, "src", cfg["root"])
    srcs = [os.path.join(pkg_dir, f) for f in cfg["main_src"]]
    for s in sorted(glob.glob(os.path.join(root, cfg["offline_src"], "**", "*.java"),
                              recursive=True)):
        rel = os.path.relpath(s, os.path.join(root, cfg["offline_src"]))
        if rel.split(os.sep)[0] in EXCLUDE_DIRS:
            continue
        srcs.append(s)
    for s in srcs:
        if not os.path.exists(s):
            return False, None, None, "缺少源文件 " + s

    out = os.path.join(root, cfg["out"])
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)

    print("[1/3] javac 编译 %d 个源文件:" % len(srcs))
    for s in srcs:
        print("        " + os.path.relpath(s, HERE))
    r = subprocess.run([JAVAC] + JOPT + ["-encoding", "UTF-8", "-d", out] + srcs,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return False, None, out, "编译失败:\n" + (r.stdout or "") + (r.stderr or "")

    home = tempfile.mkdtemp(prefix="%s-offline-" % mod_name)
    print("[2/3] 跑离线测试（HOME=%s）" % home)
    r = subprocess.run([JAVA] + ROPT + ["-cp", out, cfg["main"], home],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out_txt = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 or "OFFLINE_OK" not in (r.stdout or ""):
        return False, home, out, "运行失败（exit=%d）:\n%s" % (r.returncode, out_txt)
    print(out_txt.rstrip())
    return True, home, out, out_txt


def check_jsonl(home, cfg):
    """校验产出的 JSONL：能解析、必带双时间戳。-> (checks 列表, files, rows)"""
    ev = os.path.join(home, cfg["home"])
    files = sorted(glob.glob(os.path.join(ev, cfg["logs"])))
    checks = []

    def chk(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    if not files:
        chk("产出了事件文件", False, "空目录 " + ev)
        return checks, files, []

    rows = []
    bad_json = []
    no_wall = []
    for f in files:
        for i, line in enumerate(open(f, encoding="utf-8"), 1):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception as e:                      # noqa: BLE001
                bad_json.append("%s:%d %s" % (os.path.basename(f), i, e))
                continue
            rows.append(o)
            if "t" in o and "wall" not in o:
                no_wall.append("%s:%d" % (os.path.basename(f), i))

    chk("每一行都是合法 JSON", not bad_json, "; ".join(bad_json[:3]))
    chk("带 t 的行同时带 wall（双时间戳齐全）", not no_wall, ", ".join(no_wall[:3]))
    chk("事件流非空", len(rows) > 0, "n=%d" % len(rows))
    return checks, files, rows


def run_one(mod_name):
    cfg = MODS[mod_name]
    print("=" * 72)
    print("离线验证 [%s]  %s" % (mod_name, cfg["root"]))
    print("=" * 72)
    ok, home, out, txt = compile_and_run(mod_name, cfg)
    if not ok:
        print(txt)
        return 1

    print("[3/3] 校验事件流")
    checks, files, rows = check_jsonl(home, cfg)
    types = Counter(r.get("type") for r in rows)
    print("事件统计: " + ", ".join("%s=%d" % kv for kv in sorted(types.items())))
    print("事件文件: %s" % ", ".join(os.path.basename(f) for f in files))
    print()

    width = max((len(n) for n, _, _ in checks), default=10)
    bad = 0
    for name, good, detail in checks:
        if not good:
            bad += 1
        print("  %s %-*s %s" % ("[v]" if good else "[X]", width, name,
                                ("- " + detail) if detail else ""))
    print()
    if bad:
        print("== [%s] 离线验证失败：%d 项不过 ==" % (mod_name, bad))
        return 1
    print("== [%s] 离线验证通过（%d 项）==" % (mod_name, len(checks)))
    print("   日志样本（前 5 行）：")
    for line in list(open(files[0], encoding="utf-8"))[:5]:
        print("     " + line.rstrip())
    return 0


def loader_jar():
    """找最高版本的 fabric-loader jar（给 --pred 用）。"""
    pat = os.path.join(INST_LIBS, "libraries", "net", "fabricmc",
                       "fabric-loader", "*", "fabric-loader-*.jar")
    hits = glob.glob(pat)

    def key(p):
        v = os.path.basename(os.path.dirname(p))
        return tuple(int(x) for x in v.split(".") if x.isdigit())

    return max(hits, key=key) if hits else None


def run_predcheck():
    """单独实测各模组 fabric.mod.json 的版本谓词（需要 loader jar）。"""
    print("=" * 72)
    print("额外检查：fabric.mod.json 的版本谓词")
    print("=" * 72)
    loader = loader_jar()
    if not loader:
        return fail("找不到 fabric-loader jar（%s）" % INST_LIBS)
    print("loader: %s" % os.path.basename(loader))

    srcs = []
    outs = {}
    for name, cfg in sorted(MODS.items()):
        d = os.path.join(HERE, cfg["root"], "offline", "src", "predcheck")
        if not os.path.isdir(d):
            continue
        srcs += sorted(glob.glob(os.path.join(d, "*.java")))
        outs[name] = os.path.join(HERE, cfg["root"], "offline", "out-pred")
    if not srcs:
        return fail("没有找到 predcheck 源文件")

    rc = 0
    for name, out in outs.items():
        if os.path.isdir(out):
            shutil.rmtree(out)
        os.makedirs(out)
        mine = [s for s in srcs if os.sep + os.path.join(MODS[name]["root"]) + os.sep in s]
        if not mine:
            continue
        print("\n-- [%s] javac + run" % name)
        r = subprocess.run([JAVAC] + JOPT + ["-encoding", "UTF-8", "-cp", loader,
                                             "-d", out] + mine,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if r.returncode != 0:
            print("[X] 编译失败:\n" + (r.stdout or "") + (r.stderr or ""))
            rc = 1
            continue
        r = subprocess.run([JAVA] + ROPT + ["-cp", out + os.pathsep + loader,
                                            "predcheck.PredCheck"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        print((r.stdout or "") + (r.stderr or ""))
        if r.returncode != 0:
            rc = 1
    return rc


def main():
    ap = argparse.ArgumentParser(description="模组离线验证（同名桩跑真链路）")
    ap.add_argument("--mod", choices=sorted(MODS), default="fishprobe")
    ap.add_argument("--all", action="store_true", help="两个模组都验")
    ap.add_argument("--pred", action="store_true", help="额外实测 fabric.mod.json 的谓词")
    args = ap.parse_args()

    if not os.path.exists(JAVAC):
        return fail("缺少 javac: %s" % JAVAC)

    todo = sorted(MODS) if args.all else [args.mod]
    rc = 0
    for m in todo:
        rc |= run_one(m)
        print()
    if args.pred:
        rc |= run_predcheck()
        print()
    if rc == 0:
        print("全部离线验证通过。")
    return rc


if __name__ == "__main__":
    sys.exit(main())
