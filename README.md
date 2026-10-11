# FollowMap · Minecraft 跟随地图 + 稀有遗迹识别提醒

一个跑图辅助工具，由**两个程序**组成：

- **`coordbridge`** —— Fabric 客户端模组。纯反射只读游戏内存里**已加载**的区块，把玩家坐标与地表方块写成一个本地目录；
- **`followmap`** —— Windows 桌面程序。把上面的数据画成一块**无边框、置顶**的小窗口地图，钉在副屏上跟随玩家；同时从新落盘的区块里**识别稀有遗迹并出声提醒**。

两边通过 `~/.coordbridge/` 这个目录交换数据，**不发任何网络包、不改游戏状态、不执行任何游戏操作**。

> 起因很具体：跑图刷稀有遗迹时，眼睛要么盯全屏游戏画面、要么在看外接屏的视频，官方地图又不会跟着人走。
> 这个工具把「地图跟着人」和「有遗迹就出声」两件事拆开解决——声音是唯一 100% 有效的提醒通道，因为不看屏幕也听得见。

---

## 它解决什么问题

| 问题 | 做法 |
|---|---|
| 官方地图窗口不跟随玩家，跑图要手动拖 | 无边框置顶窗口，以玩家为中心 120ms 重绘 |
| Xaero 落盘**硬编码 60 秒一次**，磁盘地图天生滞后 | 模组**直读游戏内存**，延迟 < 1 秒（见下文「为什么不能只读 zip」） |
| 稀有遗迹（巫师 / 武士 / 白金）错过就没了 | 地块指纹识别 + 水滴音三连响 + 任务栏闪烁 + 地图打点 |
| 遗迹会**被地形淹没**，固定阈值必然漏检 | 判据含**占比锚点**（尺度无关），实测淹没 70% 仍能识别 |

---

## 架构

```
┌── 游戏进程（Minecraft 1.20.1 ~ 1.20.4 + Fabric）───────────────────┐
│  coordbridge 模组（纯反射，不链接任何 MC 类）                       │
│    Minecraft.level -> ClientChunkCache.storage -> LevelChunk       │
│      .getHeight(WORLD_SURFACE,x,z) + .getSections()[i].getBlockState│
│        │                                                           │
│        ▼  ~/.coordbridge/                                          │
│    coords.json          玩家坐标 / 维度 / 服务器（10Hz）             │
│    chunks/<维度>/r<rx>/r<rz>/<cx>_<cz>.bin   每 chunk 地表方块快照   │
│    index_<维度>.json     每 region 的版本号 + 本局 sid               │
│    status.txt / scan_status.txt   自检与运行状态                    │
└────────────────────────────────────────────────────────────────────┘
                              │
┌── followmap 桌面程序（Windows / Python 3.9+）──────────────────────┐
│  MemLayer（内存层，延迟 < 1 秒）  ← 解析上面的 .bin，增量按 mtime 缓存 │
│  TileStore（Xaero 层，历史底图）  ← 解析 Xaero 的 region.zip          │
│        └─ CompositeStore：内存层 alpha 合成在底图之上                │
│  RuinWatcher（遗迹识别）          ← 只处理 region 版本号变大的目录     │
│  Alerts（提醒）                   ← 水滴音×3 + 任务栏闪烁 + 地图打点   │
│        └─ MapView.render 以玩家为中心裁一屏 -> Tk 无边框置顶窗口       │
└────────────────────────────────────────────────────────────────────┘
```

**两级回退的坐标源**：模组（精确、带维度）→ 截屏 OCR（`PrintWindow` + 模板匹配，真实地形背景召回约 75%，靠多帧投票兜底）→ 手动 / Demo。

> ⚠️ **OCR 回退带 5 秒门槛**（防屏幕频闪）：`PrintWindow` 抓 OpenGL 游戏窗口会强制其内容走 DWM 重定向，
> 高频抓屏会造成游戏画面/整屏闪烁。所以 `auto` 模式下只有 **bridge 连续失败满 5 秒**（例如没装模组）
> OCR 才顶上，且抓屏间隔下限 1 秒；开菜单/加载屏那种 1~2 秒的短暂失败**不会**触发抓屏。
> 需要立即用 OCR 时显式 `--source ocr`（无门槛）。

---

## 快速开始

### 1. 环境

| 项 | 要求 |
|---|---|
| 系统 | **仅 Windows**（用到 `winsound` / `FlashWindowEx` / `PrintWindow`） |
| Python | 3.9+，`pip install -r app/requirements.txt`（运行期只依赖 **Pillow + numpy**） |
| 游戏 | Minecraft **1.20.1 ~ 1.20.4 + Fabric** |
| 模组 | 把 `app/coordbridge/coordbridge-1.3.1.jar` 丢进 `.minecraft\mods\`，**重启游戏** |
| 底图（可选） | Xaero's World Map，提供历史区域底图；不装也能跑（内存层不依赖它） |

### 2. 跑起来

```bat
:: 装模组（会先清旧 jar；若游戏在跑、旧 jar 被占用，会整个跳过以免留下双 jar）
python app\build_mod.py --mc 1.20.4

:: 启动地图窗口（双击也行）
app\启动跟随地图.bat
app\启动跟随地图.bat 640 120 surface     :: 尺寸 / 刷新间隔ms / 图层
app\诊断.bat                             :: 起不来时先跑这个
app\打包便携版.bat                       :: 打一份能拷到别的电脑用的最小包
```

进游戏后确认 `~/.coordbridge/scan_status.txt` 里是 `state : OK` —— 那是模组在正常工作。

### 3. 重新编译模组（不需要 Gradle）

模组全程只用「字符串 + `Class.forName`」，javac 直接编译打包：

```bat
python app\build_mod.py --no-install     :: 只编译
python app\build_mod.py --install-all    :: 装进本机所有支持范围内的实例
python app\modmap.py --compare 1.20.1 1.20.4   :: 逐项对比两版本的名字与描述符
python app\_modtest\test_modref.py       :: 验「一个 jar 通吃 1.20.1~1.20.4」的三条依据
```

---

## 核心能力

### 跟随地图

- 无边框、置顶、以玩家为中心，**默认 120ms** 重绘一帧（渲染一帧本身只要 ~8ms）。
- **两层数据自动合成**：内存直读层（实时）+ Xaero 底图（覆盖全部探索过的区域）。
- 缩放档位锁定 **1/2/4/8**（2 的幂 ⇒ 每档都是上一档的精确 NEAREST 降采样，**金字塔**一次着色出全部档位，切档 5~10ms 而非重算 0.6 秒）。
- 窗口缩放与地图缩放**刻意分成两套键位**：`+`/`-`/`0`/`Ctrl+滚轮` 改窗口，滚轮/`z`/`x` 改地图比例。

### 稀有遗迹识别（巫师 / 武士 / 白金）

判据四条**同时**满足：① `anchors` 硬特征全达标 ② `ratios` 占比达标 ③ `any` 组**至少**满足一组 ④ 纯度 ≥ 0.80。

三个来自真机的关键设计（细节见 `app/followmap/README.md` 与 `app/遗迹提醒-验证记录.md`）：

1. **硬特征写成「家族合计」（`@家族名`）而不是单个方块名。**
   同一建筑不同实例露在地表的家族成员会置换——4 个武士的「末地石砖系」总量稳定在 64~67，拆开却是 `bricks 15 / wall 38 / stairs 11`。钉单项 = 整类漏检。
2. **必须有「占比锚点」（`%方块名`）。**
   遗迹直接刷在地形上，被覆盖的列地表变 `end_stone`（不计入统计）⇒ **整座建筑的用料计数等比缩小 s 倍**。故：纯度不变、占比不变，**只有绝对计数 × s**。绝对计数锚点必漏（判据形式缺陷，调阈值救不回来）；占比是尺度无关的。实测巫师淹没 70% 时新判据仍保 18/20，旧判据淹没 50% 就归零。
3. **哪条通路用绝对数、哪条用占比，要按建筑分别判断。**
   武师的**恒定构件**在高处不缩水（17 座实测合计 116~197，第 18 名骤降到 66），所以那条用**绝对数**（`@samurai_core ≥ 90`）；巫师的可变部分占比高且被整体压缩，所以用**占比**。**别照抄、也别顺手把 `@samurai_core` 改成 `%@samurai_core`。**

指纹表是可编辑的：`app/ruins.json`（窗口大小、纯度阈值、家族定义、每类用料表/阈值/图标/颜色/音效）。

### 提醒

默认三通道同时上，**不抖窗口**：

| 通道 | 默认 | 理由 |
|---|---|---|
| **水滴音（连响三下）** | ✅ 主通道 | 眼睛在外接屏/游戏画面，**只有声音 100% 有效**。三种遗迹三个音高，听声辨类 |
| 任务栏闪烁 | ✅ | `FlashWindowEx` 不抢焦点；切回桌面立刻看到是谁在报警 |
| 地图打点 | ✅ | 图标 `★/▲/◆` 永久留在图上，事后可回看 |
| 窗口抖动 | ❌（`r` 切 `both` 开） | 抖的是地图窗口，在原来看不见的那块屏上 |

音效是**现场合成**的（`alerts.py` 现算 WAV，不依赖外部音频文件）：水滴声频率**上滑**（下滑的正弦听起来像敲门的报警声）+ 指数衰减 + 二次谐波；峰值归一化到满刻度、`>1` 走 `tanh` 软削波（**峰值不变、不破音**）。

触发语义：模组只在**玩家真正加载过**的区块上写文件，所以「文件新出现」天然等价于「这块地形刚进视距」——正好是需求要的语义，**天然合规**（绝不扫视距外）。开局会做一次基线扫描，把历史上**从没报过**的命中合并成一条提醒，之后只对增量提醒。

---

## 技术要点

### 模组：**一个 jar 通吃 1.20.1 ~ 1.20.4**

模组是**纯反射**的（只用字符串 + `Class.forName`，javac classpath 上只有 fabric-loader，**不链接任何 Minecraft 类**），所以换 MC 版本能坏掉它的唯一途径是 **intermediary 名字变了**。实测这四版的 **63 项**（20 类 + 9 字段 + 17 方法 + 17 描述符）**逐字相同**，因此不需要「1.20.1 专用版」。

上界卡在 `1.20.5` 的原因：那版 63 项也相同，但注册表大改版（`BuiltInRegistries` → `Registries`），行为未经真机验证。版本谓词是用**真实的 fabric-loader**（0.14.22 / 0.16.13 / 0.16.14 各验一遍）解析验证的，不是推断的。

> ⚠️ 安装模组时会**先清掉旧的 `coordbridge-*.jar`，清干净了才拷新的**。如果旧 jar 删不掉（游戏在跑、被 JVM 占用），**这次就整个跳过不装**——留下两个同 mod id 的 jar，Fabric 会判重复并**拒绝加载整个模组**，而报错指向 `mods\` 目录，很难联想到是这里造成的。

### 踩过最大的坑：映射写错 → 模组「静默失效」

早期 `modmap.py` 解析方法时**只按「类 + 方法名」匹配、忽略描述符**。obf 名会被压成 `a`/`b`/`c`，一个类里同名重载极多（`LevelChunkSection.getBlockState` 就有 6 个 obf 都叫 `a` 的重载），于是解析出的是同名的 `()V` 方法。

**表现极具误导性**：反射运行时抛 `NoSuchMethodException`，但异常被 `catch (Throwable)` 吞掉了 —— 游戏不崩、聊天栏没提示、日志没异常，模组只是**永远不写任何数据**。从外面看就是「地图更新一直跟不上」，像性能问题，实际是内存层从头到尾没工作过。

**两道防线**：解析端按 `(类, 描述符, 方法名)` **精确三元组**取名字（命中不唯一直接报错）；运行端解析出的 `Method` 描述符必须与 `Names.sigs()` 的预期值**逐字相同**，否则判定失败并写进 `~/.coordbridge/scan_status.txt`。

### 延迟：瓶颈是一行 `os.listdir`，不在渲染

`_resolve_xaero()` 每帧都要问「玩家现在在哪张子图」，它调用的 `DimResolver.candidates()` 原本**没有任何缓存**，每次都对所有候选目录做一轮 `os.listdir` + 逐文件 `getmtime`：

| 指标 | 改前 | 改后 |
|---|---|---|
| `app.step()` 每帧（中位） | **310 ms**（其中 `candidates` 占 270ms = 91%） | **1.8 ms** |
| 真正画地图（`MapView.render`） | 7.7 ms | 7.7 ms |
| 帧周期（`--interval 250`） | 560 ms / 1.8 fps | 128 ms / 7.8 fps |
| **端到端**（写 chunk → 画面像素真的变） | 506 ms | **127 ms**（`--interval 120`） |

修法：`scan_dir()` 用**一次 `os.scandir`** 同时拿到「region 坐标集合」和「最新 mtime」（`DirEntry.stat()` 走 Win32 目录枚举自带的数据，不产生额外系统调用），带 TTL 缓存，`_existing()` / `last_activity()` / `_pairs()` / `build_dim_map()` 全部复用；`candidates()` 再加 2 秒结果缓存（Xaero 自己 60 秒才落一次盘）。

> ⚠️ 方法学教训：`--selftest` 走 demo 源码、`fix.dim` 是空的，**恰好绕过这条路径**（自检里 11 fps，看着很正常）。必须用 `--source bridge` 插桩才暴露得出来。

### 为什么不能只读 Xaero 的 zip

从 `XaerosWorldMap_1.37.6_Fabric_1.20.4.jar` 反汇编出 `xaero/map/file/MapSaveLoad.class`：

```java
public static final int SAVE_TIME = 60000;   // 硬编码编译期常量
```

**Xaero 落盘是 60 秒节流**，实测其写入队列约 23 秒才落一个 region（一个 region 只有 512 方块宽，鞘翅 33m/s 只要 15.5 秒就飞过去了）。这是读 zip 这条路的**物理上限**，改配置也没用。要消除滞后只能不走文件——这就是 `coordbridge` 存在的理由。

---

## 目录结构

```
.
├── README.md                      本文件
├── 地图跟随方案.md                 三条跟随路线的论证（含字节码层面的核实）
├── 遗迹提醒应用-设计方案.md        选型、模块划分、合规边界
├── 方块传说服务器-学习笔记.md      服务器机制笔记（遗迹分类的来源）
└── app/
    ├── followmap/                 地图窗口主程序
    │   ├── app.py                 窗口 + 循环 + 交互（含 --selftest）
    │   ├── memstore.py            内存直读层 + CompositeStore 合成
    │   ├── store.py               瓦片仓库：金字塔着色 / LRU / 磁盘缓存 / 预取
    │   ├── ruins.py               稀有遗迹识别层
    │   ├── alerts.py              提醒层：音效合成 / 抖动 / 任务栏闪烁
    │   ├── sources.py             坐标来源 + 维度解析器
    │   ├── paths.py               运行期路径自动定位（Xaero 目录 + coordbridge 目录）
    │   ├── view.py / colors.py / ocr.py / win32cap.py / hudtext.py
    │   └── README.md              ★ 详细技术文档（算法、性能、排错）
    ├── coordbridge/               模组源码与成品
    │   ├── src/coordbridge/*.java
    │   ├── fabric.mod.json
    │   └── coordbridge-1.3.1.jar  ← 已编译成品，直接丢进 mods/
    ├── _modtest/                  离线验证（详见下文）
    ├── assets/                    现场合成的三种水滴音 wav
    ├── ruins.json                 遗迹指纹表（可编辑）
    ├── block_colors.json          方块名 -> 颜色
    ├── poi.json                   地图标记
    ├── requirements.txt           运行期依赖（只有 Pillow + numpy）
    ├── build_mod.py / modmap.py / mapbridge.py    模组编译与映射推导
    ├── make_portable.py           打便携版
    ├── diagnose.py / check_bats.py                诊断与启动器校验
    └── *.bat                      启动器（必须保持纯 ASCII，见下文）
```

---

## 验证

**真值口径**：用与分类器**完全解耦**的余弦相似度（参考向量取真实实例的实测方块数，余弦 ≥ 0.90 才算真值），避免「用同一套标准互相证明」。

```bat
python app\_modtest\test_ruins.py e        :: 回归用例：真机复现过的漏检（秒级）
python app\_modtest\test_ruins.py a        :: A 判定逻辑（1274 个真实候选簇）
python app\_modtest\test_ruins.py b        :: B 端到端（Xaero region 反合成模组格式）
python app\_modtest\test_ruins.py c 140    :: C 真实窗口压力测试
python app\_modtest\test_ruins.py d        :: D 真机落盘数据
python app\_modtest\test_alerts.py abc     :: 提醒层：负坐标几何解析 / 真窗口抖动 / 通道矩阵
python app\_modtest\test_resize.py         :: 窗口缩放
python app\_modtest\test_paths.py          :: 底图目录定位顺序
python app\_modtest\test_modref.py         :: 「一个 jar 通吃」的三条依据
python app\_modtest\gen_stubs.py --run     :: 桩类离线跑通整条反射链路
python app\check_bats.py --run             :: 启动器编码 + 变量展开
```

最新一轮结果：

| 段 | 规模 | 结果 |
|---|---|---|
| E | 13 条真机窗口直方图（含负例 / 淹没例） | 全部命中期望类型 |
| A | 1274 个真实候选簇 | 白金 13/13、武士 59/59、巫师 57/57 —— **三类 100%**，**类型混淆 0** |
| B | 3122 个合成 chunk / 6 处真值 | 命中 10，**召回 6/6**，独立余弦归属不一致 0 |
| C | 140 region / 上万个窗口 | 命中 135，**类型误报 0** |
| D | 数万个真机 `.bin` | 命中与基线一致，用户报过的被淹没实例均已检出 |

**离线桩类**：模组全程只用字符串 + `Class.forName`，所以只要提供一批类名/字段名/方法名/描述符完全一致的**桩类**，就能在没有游戏的环境里把整条链路跑通。`gen_stubs.py` 还会**双向核对桩类与 `Names.java` 是否同步**——桩里写死的名字一旦与映射脱节，这套离线验证就从「证明」退化成「自证」（表面一路 OK、实则什么都没覆盖）。

### ⚠️ 改 `.bat` 必须保持纯 ASCII

cmd 解析 `.bat` 时按**字节**推进文件指针；中文行的字节数与字符数不一致 → 指针漂移 → **从那一行往后每行都丢首字符**（`rem ...` → `em ...` 被当命令执行、`set "SIZE=%~1"` → `et ...`）→ 变量变空 → 窗口打不开。最坑的是报错看起来很像「性能问题」。改完一定跑 `check_bats.py --run`。

---

## 版本与发布

**本仓库是唯一发布出口：所有新版本都推送到这里** —— `https://github.com/jostarooo/followmap-mc`（private），默认分支 `main`。

发布 = 双击 `app\发布到GitHub.bat`，它会依次做三件事：

1. 重编模组 jar（`build_mod.py --no-install`）
2. 提交本地改动（自动写提交信息：时间 + 模组版本 + 变更清单）
3. 把整个 `git HEAD` 树上传（`blobs → tree → commit → ref`）

只改文档、没动模组时用 `发布到GitHub.bat --no-build` 跳过第 1 步；想先看看要传什么，用 `python app\push_github.py --dry-run`（不联网）。

**为什么不用 `git push`**：本机 `github.com` 网页域名被代理挡住（超时），但 `api.github.com` 可达，于是改走 GitHub 官方 **Git Data API**，效果与一次 `git push` 等同。在能正常连 github.com 的机器上，`git remote add origin <url> && git push -u origin main` 同样可用，历史与这边一致。

**需要一个 GitHub token**（`push_github.py` 按此顺序查找）：

1. 环境变量 `GH_TOKEN` / `GITHUB_TOKEN`
2. 文件 `%USERPROFILE%\.followmap-gh-token`（里面只放一行 token）
3. 命令行 `python app\push_github.py --token xxx`

细粒度 token 必须勾对两项，**只做第一项会以 403 失败**：

| 设置 | 要求 | 漏了的症状 |
|---|---|---|
| Repository access | 包含本仓库（选 *All repositories* 最省事） | 仓库直接 404 |
| Permissions → Repository permissions → **Contents** | **Read and write** | `POST /git/blobs` → 403 `Resource not accessible` |
| 创建仓库 | 不需要 | 细粒度 token 本来就建不了库，仓库已在浏览器建好 |

> 另外两条实测出来的 API 行为，别当 bug：① 零提交的空仓库上 Git Data API 会 `409 Git Repository is empty`（脚本会先用 Contents API 放 `.gitkeep` 引导激活）；② GitHub 存 commit message 时会去掉结尾换行，所以远端 commit 的 SHA 与本地同内容提交必然不同，**但 tree SHA 相同、文件逐字节一致**。

---

## 合规边界

本项目**只读**、不做任何自动化：

1. 只读**玩家已经加载过**的区块（等价于「把地图看得更明白」），**绝不扫描视距外**——用模组读渲染距离以外的方块等同透视，**明确不做**；
2. 不自动寻路 / 打怪 / 挖矿，不注入游戏操作；
3. 不发任何网络包，不改游戏状态；
4. 不用于 PVP 优势。

使用时请自行确认所在服务器的规则。读取客户端内存得到的区块数据是**客户端本来就有的**，但各服对「地图类辅助」的尺度不同，**上线前先问服主/管理**是最稳的做法。

---

## 已知限制

- **仅 Windows**（`winsound` / `FlashWindowEx` / `PrintWindow`）。
- 改过模组 jar **必须重启游戏**才生效。
- Xaero 底图天生滞后 60 秒（上游硬编码），内存层补的是「实时」这一半。
- 遗迹指纹是按本服的 3 类稀有遗迹标定的；换服需要重新取真实实例标定（`ruins.json` 可编辑）。

---

## 许可

未声明。默认保留所有权利。
