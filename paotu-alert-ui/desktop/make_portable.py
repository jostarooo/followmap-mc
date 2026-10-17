# -*- coding: utf-8 -*-
"""打一个「便携版」目录，可以直接拷到别的电脑上双击就用（**含 exe**）。

用法：
    python make_portable.py                  # 输出到 paotu-alert-ui/dist/PaotuAlert-Portable
    python make_portable.py D:\\somewhere     # 输出到指定目录

**为什么需要它**：`dist/` 里除了 exe 还堆着 PyInstaller 的中间产物，而 `dist/runtime/`
里躺着**本机**跑出来的日志与动作留档；`desktop/config.example.json` 里又写着
**本机绝对路径**。直接整个拷过去，既大又脏。这里按**白名单**收文件。

收进去的东西分四类：
  ① 程序（`末地跑图提醒控制台.exe` —— 界面与图标已内嵌，目标机免装 Python）
  ② 双击入口（`启动.bat` / `启动-分离地图.bat`，**内容纯 ASCII**）
  ③ 说明书与配置模板（`README-便携说明.md` / `config.example.json`）
  ④ 数据来源模组（`coordbridge-*.jar`，另一个电脑要装它才有坐标与地形）

**明确不收**：`config.json`（本机配置，里面是本机绝对路径，带过去只会把对方带偏）、
`runtime/` 下的日志与 `actions.jsonl`、PyInstaller 的 `build/`、`_qa/` 自检截图。

打包末尾有两道自检：
  · **清洁性检查** —— 一旦 `config.json` / `runtime/*.log` 混进来就报出来并删。
    最要紧的是动作留档：那是**本机**的操作流水，带过去纯属噪音。
  · **bat 静态检查** —— 启动器必须是纯 ASCII、无 BOM。cmd.exe 按**字节偏移**解析 .bat，
    一行 UTF-8 中文就会让后面每一行丢掉开头字符（这个坑真炸过一次，见 app/check_bats.py）。
    这里刻意不 import app/check_bats.py —— paotu-alert-ui 要能整目录删掉，不跨项目依赖。
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent        # paotu-alert-ui/desktop/
ROOT = HERE.parent                            # paotu-alert-ui/
DIST = ROOT / "dist"
PROJ = ROOT.parent                            # fangkuai-chuanshuo/（模组在它的 app/ 下）

EXE_NAME = "末地跑图提醒控制台.exe"

# 目录名用纯 ASCII：传给对方的路径里带中文，在部分云盘/压缩工具里会被改编码。
# （exe 本身的中文名改不掉 —— 那是 PyInstaller 里定死的 —— 所以更要让**目录**稳。）
PKG_NAME = "PaotuAlert-Portable"

# ── 本机不该带出去的东西（清洁性检查用）──────────────────────────────────
UNCLEAN = [
    "config.json",                    # 本机配置：含本机绝对路径
    "runtime/bridge.log",
    "runtime/_stderr.txt",
    "runtime/actions.log",
    "runtime/actions.jsonl",
]


# ══════════════════════════════════════════════════════════════════════════
# 从既有文件里读事实，别在文档里再抄一遍（抄了就会跟源码对不上）
# ══════════════════════════════════════════════════════════════════════════
def host_version() -> str:
    try:
        txt = (HERE / "host.py").read_text(encoding="utf-8")
        m = re.search(r'^VERSION\s*=\s*"([^"]+)"', txt, re.M)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


def mod_jar() -> str | None:
    """模组 jar 名跟着 fabric.mod.json 的 version 走，用通配去找。

    app/coordbridge/ 属于 followmap 项目 —— 这里**只读**，不写不改。
    找不到（比如只拿到 paotu-alert-ui 这一个目录）就跳过，不影响出包。
    """
    cands = sorted(glob.glob(str(PROJ / "app" / "coordbridge" / "*.jar")))
    return Path(cands[-1]).name if cands else None


def mod_supported_mc() -> str:
    try:
        d = json.loads((PROJ / "app" / "coordbridge" / "fabric.mod.json")
                       .read_text(encoding="utf-8"))
        return d["depends"]["minecraft"]
    except Exception:                                       # noqa: BLE001
        return ">=1.20.1 <1.20.5"


# ══════════════════════════════════════════════════════════════════════════
# 生成的启动器 / 配置 / 说明书
# ══════════════════════════════════════════════════════════════════════════

# 启动器内容**必须纯 ASCII**：cmd.exe 按字节偏移解析 .bat，一行中文就串行。
# exe 名是中文，所以这里用通配 `*.exe` 取路径，不把中文写进 bat 内容。
LAUNCH_BAT = r"""@echo off
rem Launch the console. ASCII ONLY - see make_portable.py for why.
setlocal
cd /d "%~dp0"
set "EXE="
for %%F in ("%~dp0*.exe") do set "EXE=%%~fF"
if not defined EXE (
    echo [ERROR] No .exe found next to this script.
    pause
    exit /b 1
)
start "" "%EXE%"
endlocal
"""

DETACH_BAT = r"""@echo off
rem Launch the console with the map detached into its own on-top window.
rem ASCII ONLY - see make_portable.py for why.
setlocal
cd /d "%~dp0"
set "EXE="
for %%F in ("%~dp0*.exe") do set "EXE=%%~fF"
if not defined EXE (
    echo [ERROR] No .exe found next to this script.
    pause
    exit /b 1
)
start "" "%EXE%" --detach
endlocal
"""

# 注意 app_dir 刻意留空：写本机路径等于把对方带偏。
CONFIG_TEMPLATE = """{
  "_说明": "把本文件重命名为 config.json 放到 exe 同目录即可生效；所有项都可省略。",

  "app_dir": "",
  "_app_dir": "【按需填】followmap 主程序目录（那个程序负责判定遗迹、写 out/found_ruins.json）。留空则只在 exe 附近自动向上搜索，搜不到就不显示「已发现遗迹」，**其它功能照常**。",

  "dim": "minecraft:the_end",
  "_dim": "游戏不在世界中时，地图默认显示哪个维度。可选 minecraft:the_end / minecraft:overworld / minecraft:the_nether。",

  "echo_actions": true,
  "_echo_actions": "是否把界面上的操作落到 runtime/actions.jsonl，供 followmap 主程序读取。**默认开着**（不写 config.json 也是这个行为）；纯当看板用、不想留档就改成 false。",

  "webview_args": "--no-sandbox",
  "_webview_args": "传给 WebView2 的浏览器参数。**别删**：Chromium 渲染进程的沙箱在受限令牌/作业对象里起不来，去掉它窗口会出现但页面永远不加载。",

  "start_detached": false,
  "_start_detached": "启动时直接把地图分离到独立窗口（等同于双击「启动-分离地图.bat」）。运行中随时可以点界面上的「分离地图」或按 D 切换。",

  "map_window": {
    "width": 560,
    "height": 620,
    "frameless": true,
    "on_top": true,
    "resizable": true,
    "x": null,
    "y": null
  },
  "_map_window": "独立地图窗口的样子。frameless=true 去掉标题栏（拖动靠窗口顶部那条 22px 的拖拽条）；on_top=true 置顶（全屏游戏时也看得见，适合钉在副屏）；x/y 留 null 由系统摆放，想固定在某块屏就填像素坐标。"
}
"""

README = r"""# 末地跑图提醒 · 控制台 —— 便携版

**双击 `末地跑图提醒控制台.exe` 就能用，不用装 Python。**

这个文件夹里是一份已经打好包的程序（版本 `__VERSION__`），拷到别的 Windows 电脑上即可运行。
先花一分钟看「一、另一台电脑要准备什么」，再看「二、怎么启动」。

---

## 一、另一台电脑要准备什么

分两档：**能开起来** 和 **有数据可看**。前者零成本，后者要装东西。

### 档 A：能开起来（必须）

| # | 要装的东西 | 说明 |
|---|---|---|
| 1 | **Windows 10 1803+ / 11** | 程序用的是系统自带的 **Edge WebView2** 内核。Win11 与较新的 Win10 **一般已经自带**；万一提示缺 WebView2，去微软官网搜 *WebView2 Runtime* 免费装一个（Evergreen 版）。 |
| 2 | —— 不需要 Python —— | exe 里已经把 Python 解释器、界面、图标全打进去了（`--onefile` 单文件）。**对方机器不用装 Python，也不用 pip。** |

装好后双击 exe，会出现一个**深色的控制台窗口**。此时它跑的是「运行模式」，
只是**还没有数据** —— 地图空白、坐标显示 `--`，属于正常。

### 档 B：有数据可看（要玩方块传说才需要）

数据**全部来自 Minecraft 侧**，程序自己不产生任何地图数据：

| # | 要装的东西 | 说明 |
|---|---|---|
| 3 | **Minecraft + Fabric** | 模组声明支持 `__MOD_MC__`。 |
| 4 | **CoordBridge 模组** | 把 `coordbridge\__MOD_JAR__` 丢进 `.minecraft\mods\`。**这是唯一的数据来源，不装就永远是空地图**（实时坐标 + 地形都靠它）。 |
| 5 | **Xaero's World Map**（可选） | 提供历史底图。不装也能跑，只是没走过的老区域不显示。 |
| 6 | **followmap 主程序**（可选） | 界面右下角那个「已发现遗迹」列表要它才有（它负责判定并把结果写进 `out\found_ruins.json`）。不装只是这一块空白，**其它功能不受影响**；装了就在 `config.json` 里把 `app_dir` 指向它。 |
| 7 | 进同一个服务器 | 这程序的用途是「刷视频时也听得到稀有遗迹提醒」，得在同一个服里跑图才有意义。 |

> 装完模组**必须重启游戏**才生效。重启后进一次服务器，
> `C:\Users\<用户名>\.coordbridge\` 下会出现 `coords.json` 与 `chunks\`，
> 这时控制台的地图就会亮起来。

---

## 二、怎么启动

| 想干什么 | 双击哪个 |
|---|---|
| 普通启动 | **`末地跑图提醒控制台.exe`**（或 `启动.bat`，后者会把工作目录也设对） |
| 启动就把地图甩到独立小窗 | **`启动-分离地图.bat`** |
| 只看看界面长什么样（不接数据） | **`index.html`**（用 Edge/Chrome 打开，跑内置演示数据） |

**地图分离**：游戏占一个屏、控制台占另一个屏时，控制台里那块地图预览是多余的。
点界面上的 `⧉ 分离地图` 或按 **`D`**，地图会变成一个**无边框、置顶**的小窗（游戏全屏也看得见），
拖它顶部那条 22px 的横条可以移动，钉在副屏角落正合适。地图窗口里点 `⤢ 收回控制台`、
再按一次 `D`、或者**直接把地图窗口关掉**，都能收回。

---

## 三、数据从哪来 / 地图空白怎么办

控制台读三个地方，**全是只读**，不写游戏的数据：

| 界面上的东西 | 来源 | 没有会怎样 |
|---|---|---|
| 玩家坐标 | `C:\Users\<你>\.coordbridge\coords.json` | 显示 `--`（模组没装或没进服务器） |
| 地形区块 | `C:\Users\<你>\.coordbridge\chunks\<世界>\*.bin` | 地图空白（模组没装，或还没跑过图） |
| 已发现遗迹 | `<followmap 主程序>\out\found_ruins.json` | 列表空白（没配 `app_dir`，或主程序没跑过） |

地图空白时**不用慌**，按顺序排查：

1. 模组装了吗？── `.minecraft\mods\` 里有 `coordbridge-*.jar` 吗（版本要对 `__MOD_MC__`）
2. 重启游戏了吗？── 模组装完必须重启才加载
3. 进过服务器吗？── 进一次，然后看 `C:\Users\<你>\.coordbridge\` 这个文件夹有没有出现
4. 还是空？── 在游戏里走几步，地形是**按玩家附近 ±24 区块**实时读的，站着不动只会显示脚下那一片

---

## 四、可选配置 `config.json`

把 **`config.example.json` 改名成 `config.json`** 放在 exe 旁边即生效。文件里每一段都写了注释
（键名带下划线开头的 `"_说明"` 之类是注释行，程序会忽略）。最常动的两个：

- `app_dir` —— 指向 followmap 主程序目录，用来显示「已发现遗迹」
- `start_detached` —— 改成 `true`，以后启动就自动分离地图（不用再点 `启动-分离地图.bat`）

命令行也认一个参数： `末地跑图提醒控制台.exe --detach`（等同 `start_detached`）。

---

## 五、这个文件夹里有什么

    末地跑图提醒控制台.exe    主程序（__EXE_MB__ MB，界面/图标已内嵌，免装 Python）
    启动.bat                  普通启动的双击入口
    启动-分离地图.bat          启动并直接分离出独立地图窗口
    index.html                界面本体，双击可看演示效果（不接真实数据）
    config.example.json       配置模板（改名 config.json 生效）
    coordbridge\              数据来源模组，装到 .minecraft\mods\
    runtime\                  运行期日志（程序自己写，删掉无妨）
    README-便携说明.md         本文件

**界面能不能改？** 能 —— 但 `index.html` 只是给你看的副本，**exe 里的界面是打包时内嵌的**，
改这个文件不影响 exe。想要新界面得重新打包（见项目 README）。

**怎么卸载？** 直接删掉整个文件夹。程序不在注册表、系统目录、`AppData` 里留任何东西
（`C:\Users\<你>\.coordbridge\` 是**模组**写的，跟本程序无关，要清也得自己去删）。
"""


# ══════════════════════════════════════════════════════════════════════════
# bat 自检（刻意自己实现，不 import app/check_bats.py）
# ══════════════════════════════════════════════════════════════════════════
def check_bat_static(path: Path):
    """返回问题列表。cmd.exe 按字节偏移解析 .bat，非 ASCII 或 BOM 都会串行。"""
    problems = []
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        problems.append("带 UTF-8 BOM（cmd 会把 BOM 当命令的一部分）")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        problems.append("带 UTF-16 BOM（cmd 不支持 UTF-16 的 .bat）")
    body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    bad = [(i, b) for i, b in enumerate(body) if b > 0x7F]
    if bad:
        ln = body[:bad[0][0]].count(b"\n") + 1
        problems.append("第 %d 行有非 ASCII 字节 0x%02X（会吃掉后续每行的开头字符）"
                        % (ln, bad[0][1]))
    if b"\n" in body and body.count(b"\r\n") != body.count(b"\n"):
        problems.append("换行不是纯 CRLF（老版本 cmd 会出错）")
    return problems


def main():
    dst = Path(sys.argv[1]) if len(sys.argv) > 1 else DIST / PKG_NAME
    dst = dst.resolve()
    exe = DIST / EXE_NAME

    print("源目录  : %s" % ROOT)
    print("目标目录: %s" % dst)
    print()

    if not exe.is_file():
        print("!! 没找到 %s" % exe)
        print("   先打包 exe：cd desktop && <python> build.py")
        return 1

    if dst.exists():
        # 只删自己生成的目标目录。有 exe 在就认为"确实是我们打的便携版"，
        # 万一用户指了个别的目录、里面又有东西，就别删（防误伤）。
        if not list(dst.glob("*.exe")) and any(dst.iterdir()):
            print("目标目录已存在且不像便携版输出，为安全起见不删除：%s" % dst)
            print("请换一个空目录，或手动删掉它再跑。")
            return 2
        shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True, exist_ok=True)

    n_file = n_byte = 0

    def copy(src: Path, rel: str):
        nonlocal n_file, n_byte
        if not src.is_file():
            print("  !! 缺少 %s（跳过）" % rel)
            return
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        n_file += 1
        n_byte += src.stat().st_size

    def write(rel: str, text: str):
        nonlocal n_file, n_byte
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        # newline="\r\n"：bat 与 txt 在 Windows 上要 CRLF（Notepad 与 cmd 都认这个）
        with open(out, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write(text)
        n_file += 1
        n_byte += out.stat().st_size

    print("① 程序")
    copy(exe, EXE_NAME)

    print("② 双击入口")
    write("启动.bat", LAUNCH_BAT)
    write("启动-分离地图.bat", DETACH_BAT)

    print("③ 说明书与配置")
    copy(ROOT / "index.html", "index.html")
    write("config.example.json", CONFIG_TEMPLATE)
    write("README-便携说明.md",
          README.replace("__VERSION__", host_version())
                .replace("__EXE_MB__", "%.1f" % (exe.stat().st_size / 1048576.0))
                .replace("__MOD_JAR__", mod_jar() or "coordbridge-<版本>.jar")
                .replace("__MOD_MC__", mod_supported_mc()))

    print("④ 数据来源模组")
    jar = mod_jar()
    if jar:
        # 只读 app/coordbridge/ —— 不写不改，paotu-alert-ui 之外一个字节没动
        copy(PROJ / "app" / "coordbridge" / jar, os.path.join("coordbridge", jar))
        copy(PROJ / "app" / "coordbridge" / "fabric.mod.json",
             os.path.join("coordbridge", "fabric.mod.json"))
    else:
        print("  .. 没找到模组 jar（app/coordbridge/*.jar），便携包里不放模组")
        (dst / "coordbridge").mkdir(exist_ok=True)

    (dst / "runtime").mkdir(exist_ok=True)          # exe 自己也会建，先给上省得纠结

    # ---- 清洁性检查 --------------------------------------------------------
    dirty = [rel for rel in UNCLEAN if (dst / rel).exists()]
    if dirty:
        print()
        print("!! 打包目录里混进了本机运行期产物：")
        for rel in dirty:
            print("     %s" % rel)
        print("   已自动删除。**别在打包目录里直接跑 exe** —— 要验证先整个拷到别处再跑。")
        for rel in dirty:
            try:
                (dst / rel).unlink()
            except OSError:
                pass

    # ---- bat 静态检查 ------------------------------------------------------
    print()
    print("bat 自检：")
    bat_bad = 0
    for p in sorted(dst.glob("*.bat")):
        problems = check_bat_static(p)
        if problems:
            bat_bad += 1
            for q in problems:
                print("   [FAIL] %s: %s" % (p.name, q))
        else:
            print("   [ ok ] %s（纯 ASCII，无 BOM，CRLF）" % p.name)

    # ---- 顺手打个 zip ------------------------------------------------------
    # 对方多半是「云盘/微信传一个压缩包」，比传一个文件夹省事（目录结构也不会被压平）。
    zpath = Path(str(dst).rstrip("\\/") + ".zip")
    try:
        if zpath.exists():
            zpath.unlink()
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for root, _dirs, files in os.walk(dst):
                for f in sorted(files):
                    p = Path(root) / f
                    z.write(p, os.path.relpath(p, dst.parent))
            z.writestr("%s/runtime/" % PKG_NAME, "")   # 空目录也要留（exe 往里写日志）
        print()
        print("压缩包：%s（%.1f MB）" % (zpath, zpath.stat().st_size / 1048576.0))
    except Exception as e:                                    # noqa: BLE001
        print("!! 打 zip 失败（不影响便携版目录本身）：%s" % e)

    print()
    print("完成：%d 个文件，%.1f MB" % (n_file, n_byte / 1048576.0))
    print("路径：%s" % dst)
    print()
    print("下一步：把上面那个 .zip（或整个文件夹）拷到另一台电脑，")
    print("       解压后照里面的 README-便携说明.md 装 WebView2 和 CoordBridge 模组。")
    return 1 if bat_bad else 0


if __name__ == "__main__":
    sys.exit(main())
