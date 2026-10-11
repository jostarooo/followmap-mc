# -*- coding: utf-8 -*-
"""打一个「便携版」目录，可以直接拷到别的电脑上用。

用法：
    python make_portable.py                 # 输出到 <项目>/dist/跟随地图-便携版
    python make_portable.py D:\\somewhere   # 输出到指定目录

**为什么需要它**：项目根目录里有一大堆开发期产物（40+ 张调试 PNG、
`structures_DIM1.json`、`_modtest/`、`cache/` 的各种中间件……），
直接整个拷过去既大又容易把 `server_path.txt` 之类的本机配置带过去。
这里按**白名单**收文件，只收运行必需的。

收进去的东西分三类：
  ① 程序本体（followmap/ + 三个顶层模块 + 四个 .bat + 诊断/自检脚本）
  ② 运行期要读的数据（ruins.json / poi.json / block_colors.json /
     assets/ 的音效 / cache/font_ascii.png —— 有它就不用去读游戏 jar）
  ③ 模组（coordbridge/，另一个电脑要装它才有数据；顺带放一份省得再要）

**明确不收**：_modtest/（离线验证）、out/（本机的命中记录与崩溃日志）、
cache/{cls,mappings,memtiles,tiles}（缓存）、coordbridge/{build,src}（编译产物/源码）、
server_path.txt（本机路径，带过去反而会把对方带偏 —— 让它自己扫一次）。

打包末尾还有一道**清洁性检查**：一旦 out/found_ruins.json 之类的运行期产物混进来
（例如打包后在 dist 里跑过程序），会报出来并自动删掉。那是个**去重库**，带过去会让
里面那几处遗迹被当成"已发现"永久静音。
"""
import glob
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))          # app/
ROOT = os.path.dirname(HERE)                                # 项目根

# 目录名用纯 ASCII：传给对方的路径里带中文，在部分云盘/压缩工具里会被改编码，
# 反而容易出问题（读起来不友好没关系，里面的 README 是中文的）。
PKG_NAME = "FollowMap-Portable"

# ---- ① 程序本体 ------------------------------------------------------------
FILES = [
    "requirements.txt",
    "hudtext.py", "mc_font.py", "xaero_region.py",
    "diagnose.py", "check_bats.py",
    "make_portable.py", "打包便携版.bat",
    "ruins.json", "poi.json", "block_colors.json",
    "启动跟随地图.bat", "启动跟随地图-静默.bat", "诊断.bat",
]
DIRS = ["followmap"]
# ---- ② 运行期数据 ----------------------------------------------------------
DATA_FILES = [
    ("assets", ["drop_high.wav", "drop_mid.wav", "drop_low.wav", "_manifest.json"]),
    ("cache", ["font_ascii.png"]),
]
# ---- ③ 模组 ----------------------------------------------------------------
# jar 文件名跟着 fabric.mod.json 的 version 走（build_mod.py 就是这么命名的）。
# 用通配去找，省得每次升版本都回来改这里 —— 漏改会让便携包里带一个旧 jar。
def _mod_jar():
    cands = sorted(glob.glob(os.path.join(HERE, "coordbridge", "coordbridge-*.jar")))
    return os.path.basename(cands[-1]) if cands else "coordbridge-1.3.1.jar"


def _mod_supported_mc():
    """从 fabric.mod.json 读支持范围，写进说明书（别让文档和元数据各说一套）。"""
    try:
        with open(os.path.join(HERE, "coordbridge", "fabric.mod.json"),
                  encoding="utf-8") as fh:
            return json.load(fh)["depends"]["minecraft"]
    except Exception:                                       # noqa: BLE001
        return ">=1.20.1 <1.20.5"


MOD_JAR = _mod_jar()
MOD_MC = _mod_supported_mc()

# 运行期要写的目录（先建好，省得第一次跑时因为权限/路径问题失败）
EMPTY_DIRS = ["out", "cache/tiles", "cache/memtiles"]

# 生成给对方的说明文件
README = """# 跟随地图 · 便携版

这个文件夹是可以直接拷到别的电脑上用的版本。**先看「另一台电脑要准备什么」。**

## 一、另一台电脑要准备什么

| # | 要装的东西 | 说明 |
|---|---|---|
| 1 | **Python 3.9+** | 装的时候勾上 *Add python.exe to PATH*。装完命令行敲 `python --version` 能出版本号就行。 |
| 2 | **两个库** | 在这个文件夹里开命令行，敲：`pip install -r requirements.txt`（只有 Pillow 和 numpy） |
| 3 | **Minecraft 1.20.1 ~ 1.20.4 + Fabric** | 模组声明支持 `__MOD_MC__`。**同一个 jar 这几个版本通用**：模组全程只用「字符串 + 反射」，不链接任何 Minecraft 类；它用到的 20 类 / 9 字段 / 17 方法 / 17 描述符在 1.20.1~1.20.4 之间**逐字相同**（实测 `python modmap.py --compare 1.20.1 1.20.4` → 63 项完全一致），所以不需要按版本挑 jar。1.20.5 及以上不支持。 |
| 4 | **CoordBridge 模组** | 把 `coordbridge\\__MOD_JAR__` 丢进 `.minecraft\\mods\\`。**这是数据来源，不装就没有任何数据。** |
| 5 | **Xaero's World Map 模组** | 提供历史底图（旧区域）。不装也能跑，只是走过的老区域没有底图。 |
| 6 | 进同一个服务器 | 本程序的用途是「刷视频时也听得到稀有遗迹提醒」，得在同一个服里跑图才有意义。 |

> 装完模组**必须重启游戏**才会生效。重启后进一次服务器，
> `C:\\Users\\<用户名>\\.coordbridge\\` 下会出现 `coords.json` / `chunks\\`。

## 二、怎么启动

双击 **启动跟随地图.bat**（想开窗口不想要黑框就双击 **启动跟随地图-静默.bat**）。

启动后窗口第一行会打印它用的是哪个地图目录，例如：

    [followmap] Xaero 底图 : D:\\...\\XaeroWorldMap\\Multiplayer_xxx.com
    [followmap] 定位来源   : 模组 status.txt 的游戏目录（匹配当前服务器 xxx.com）

**路径是自动找的**，顺序是：
命令行 `--server` > 环境变量 `FOLLOWMAP_XAERO` > 同目录的 `server_path.txt`
> 模组 `status.txt` 里记录的游戏目录 > `cache\\server_path.auto.txt`
（上次扫描的缓存）> 常见启动器位置扫描 > 盘符扫描。

## 三、底图是空白的怎么办

只有这一个环节需要手填。如果启动时打印「`!! 底图目录不可用`」，说明那台电脑上
Xaero 的地图目录不在自动扫描能覆盖的位置。三种办法，任选其一：

1. **先让游戏跑一次**（最省事）—— 进一次服务器，模组会把游戏目录写进
   `.coordbridge\\status.txt`，下次启动程序就能自动定位到。
2. **填 `server_path.txt`** —— 把 **Xaero 的「服务器」目录**（就是里面按维度分子目录、
   再往下是 `mw$default` 的那一层）写进去一行：

       D:\\你的路径\\XaeroWorldMap\\Multiplayer_你的服务器名

   找不准的话：进游戏 → 开 Xaero 世界地图 → 在 `.minecraft` 里搜 `XaeroWorldMap` 文件夹
   → 里面的 `Multiplayer_*` 就是。也可以直接把 `XaeroWorldMap` 这一层写进去
   （程序会自己往下挑服务器）。写完不用重启电脑，重开一次程序就行。
3. **命令行指定** —— `python followmap\\app.py --server "D:\\你的路径\\...\\Multiplayer_xxx"`，
   或设环境变量 `FOLLOWMAP_XAERO`。

> 如果程序自动扫到了目录（第一次可能要等 9 秒），会把结果记进
> `cache\\server_path.auto.txt`，以后再启动就是秒开。这个缓存**优先级低于模组数据**：
> 万一猜错了，模组一跑过就会自动纠正，不用手删。

**注意**：内存直读层（`$mem`）不依赖 Xaero。所以底图空白时，你正在跑的那片区域
仍然是实时的，只是回头看不到老区域。

## 四、出问题先跑诊断

双击 **诊断.bat**（或 `python diagnose.py`）。它会逐步检查解释器 / 依赖 / 文件 /
地图目录 / 渲染 / 坐标源 / 模组链路，最后给出「哪一层有问题」。

## 五、这个文件夹里的东西

    followmap\\          程序本体
    hudtext.py          HUD 文本渲染（中文走系统字体）
    mc_font.py          MC 像素字体（优先用 cache\\font_ascii.png，不读游戏 jar）
    xaero_region.py     Xaero region 文件解析
    ruins.json          遗迹指纹表（可自己改阈值）
    poi.json            地图标记
    block_colors.json   方块颜色表（39KB，别删）
    assets\\             三种水滴音（缺了会现场重新合成）
    cache\\font_ascii.png  MC 像素字体图集（810 字节，别删，否则要去游戏 jar 里取）
    coordbridge\\        CoordBridge 模组 jar（`__MOD_JAR__`，装到 .minecraft\\mods\\）
    out\\                运行时会写：命中的遗迹记录、提醒日志、崩溃日志
    cache\\              font_ascii.png（字体图集）+ server_path.auto.txt（路径缓存）
    server_path.txt     底图目录的手填口子（自动扫描失败时才需要）
    make_portable.py    重新打一个便携版（改过配置后想再发一份时用）
    打包便携版.bat        make_portable.py 的双击入口（纯 ASCII 名，怕命令行出乱码）
    check_bats.py        .bat 的编码自检（双击前想确认 bat 没坏可以跑）

祝顺利。有问题先看 `诊断.bat` 的输出。
"""


def main():
    dst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist", PKG_NAME)
    dst = os.path.abspath(dst)
    print("源目录  : %s" % HERE)
    print("目标目录: %s" % dst)
    print()

    if os.path.exists(dst):
        # 只删我们自己生成的目标目录（用户在命令行显式指定的同名目录也删，
        # 这是"重新打一次"的预期行为；为避免误伤，先确认它像个便携版）
        marker = os.path.join(dst, "followmap")
        if not os.path.isdir(marker) and os.listdir(dst):
            print("目标目录已存在且不像便携版输出，为安全起见不删除：%s" % dst)
            print("请换一个空目录，或手动删掉它再跑。")
            return 2
        shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst, exist_ok=True)

    n_file = 0
    n_byte = 0

    def copy(rel):
        nonlocal n_file, n_byte
        src = os.path.join(HERE, rel)
        if not os.path.isfile(src):
            print("  !! 缺少 %s（跳过）" % rel)
            return
        out = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copy2(src, out)
        n_file += 1
        n_byte += os.path.getsize(src)

    print("① 程序本体")
    for f in FILES:
        copy(f)
    for d in DIRS:
        sdir = os.path.join(HERE, d)
        for root, dirs, files in os.walk(sdir):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for f in sorted(files):
                if f.endswith(".pyc"):
                    continue
                full = os.path.join(root, f)
                copy(os.path.relpath(full, HERE))

    print("② 运行期数据")
    for d, names in DATA_FILES:
        for f in names:
            copy(os.path.join(d, f))

    print("③ 模组")
    # jar 名从通配来（见 _mod_jar），别在这里写死版本号
    copy(os.path.join("coordbridge", MOD_JAR))
    copy(os.path.join("coordbridge", "fabric.mod.json"))

    for d in EMPTY_DIRS:
        os.makedirs(os.path.join(dst, d), exist_ok=True)

    # ---- 清洁性检查 --------------------------------------------------------
    # 运行期产物绝对不能跟着发出去。最阴的是 out/found_ruins.json：它是**去重库**，
    # 里面的遗迹会被当成"已发现"永久静音。曾经因为「打包后在 dist 里跑了一次诊断」
    # 而混进来一个残缺的库（4 条），对方拿去用就会漏掉那 4 处提醒。
    # （诊断已改成 --no-ruin 只读，这里再加一道，防止以后又冒出来。）
    dirty = []
    for rel in ("out/found_ruins.json", "out/ruin_alerts.log", "out/crash.log",
                "cache/server_path.auto.txt"):
        p = os.path.join(dst, rel)
        if os.path.exists(p):
            dirty.append(rel)
    if dirty:
        print()
        print("!! 打包目录里混进了运行期产物（会被对方带去，可能造成误判）：")
        for rel in dirty:
            print("     %s" % rel)
        print("   已自动删除。请勿在打包目录里直接跑程序/诊断 —— 要验证先整个拷出去再跑。")
        for rel in dirty:
            try:
                os.remove(os.path.join(dst, rel))
            except OSError:
                pass

    # server_path.txt 模板：全是注释行，程序会跳过（只有非 # 开头的行才当路径用），
    # 所以放着不会把对方带偏，却给了个明确的手填位置。
    with open(os.path.join(dst, "server_path.txt"), "w", encoding="utf-8") as fh:
        fh.write("# 底图目录的手填口子。自动扫描失败时才需要动它。\n"
                 "# 填「Xaero 的服务器目录」（里面按维度分子目录、再往下是 mw$default）；\n"
                 "# 也可以只填到 ...\\XaeroWorldMap，程序会自己往下挑服务器。\n"
                 "# 下面只是例子，把中间的版本目录名换成你自己的（1.20.1 / 1.20.4 都行）：\n"
                 "# 去掉这行开头的 # 并改成你的路径即可：\n"
                 "# C:\\Users\\你的用户名\\AppData\\Roaming\\.minecraft\\versions\\"
                 "1.20.1-Fabric 0.16.13\\XaeroWorldMap\\Multiplayer_你的服务器\n")

    with open(os.path.join(dst, "README-移植说明.md"), "w", encoding="utf-8") as fh:
        # 用 replace 而不是 % 或 format：README 里全是反斜杠路径和 `$`，
        # 走格式化容易出现意料之外的转义/占位符冲突。
        fh.write(README.replace("__MOD_JAR__", MOD_JAR).replace("__MOD_MC__", MOD_MC))

    # ---- 顺手打个 zip ------------------------------------------------------
    # 对方多半是「云盘 / 微信传一个压缩包」，比传一个 34 个文件的文件夹省事得多
    # （而且目录结构不会被压平）。用标准库 zipfile，无外部依赖。
    zpath = dst.rstrip("\\/") + ".zip"
    try:
        import zipfile
        if os.path.exists(zpath):
            os.remove(zpath)
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for root, dirs, files in os.walk(dst):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in sorted(files):
                    p = os.path.join(root, f)
                    z.write(p, os.path.relpath(p, os.path.dirname(dst)))
            for rel in EMPTY_DIRS:          # 空目录也要留（out/ 是运行时要写的）
                z.writestr("%s/%s/" % (os.path.basename(dst), rel), "")
        print("压缩包：%s  （%.0f KB）"
              % (zpath, os.path.getsize(zpath) / 1024.0))
    except Exception as e:
        print("!! 打 zip 失败（不影响便携版目录本身）：%s" % e)

    print()
    print("完成：%d 个文件，%.1f MB" % (n_file, n_byte / 1048576.0))
    print("路径：%s" % dst)
    print()
    print("下一步：把上面那个 .zip（或整个文件夹）拷到另一台电脑（U 盘/网盘都行），")
    print("       解压后照里面的 README-移植说明.md 装 Python 和两个模组。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
