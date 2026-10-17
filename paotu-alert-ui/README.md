# 末地跑图提醒 · 前端操作界面

方块传说服务器「末地跑图 + 稀有遗迹提醒」程序的**独立操作台**。

三种用法：
1. **预览**：双击 `index.html` —— 单文件、零依赖、零网络，跑内置演示数据。
2. **运行模式（推荐）**：双击 `dist\末地跑图提醒控制台.exe` —— 原生窗口 + **真实数据**
   （CoordBridge 实时坐标 / 真实落盘地形 / 真实已发现遗迹）。
3. **发给别的电脑**：`dist\PaotuAlert-Portable.zip` —— 自带 exe 的便携包，对方**免装 Python**（见 §8）。

```
paotu-alert-ui/
├── index.html        ← 界面全部内容（结构 + 样式 + 逻辑，2192 行 / 120 KB，IIFE 封装）
│                       一份文件三种视图：控制台 / 地图窗口 / 控制台(地图已分离)，见 §7
├── README.md         ← 本文件
├── dist/             ← 打包产物
│   ├── 末地跑图提醒控制台.exe     单文件桌面版（12.6 MB，免安装；运行时在旁边建 runtime/）
│   ├── PaotuAlert-Portable/     便携版目录：自带 exe 的分发包，见 §8
│   └── PaotuAlert-Portable.zip  便携版压缩包（12.4 MB，拷给别人用这个）
├── desktop/          ← 桌面壳（运行模式宿主），源码 + 打包脚本
│   ├── host.py            原生窗口 + 真实数据桥 + 地图窗口管理（pywebview / Edge WebView2）
│   ├── build.py           一键打包成单文件 exe
│   ├── make_portable.py   一键打便携版（白名单收文件 + 清洁性检查 + bat 自检 + zip）
│   ├── 打包便携版.bat       make_portable.py 的双击入口
│   ├── make_icon.py       生成 app.ico（像素风图标）
│   ├── app.ico            窗口 / exe 图标
│   ├── config.example.json  可选配置（改名为 config.json 放 exe 旁即生效）
│   ├── _qa_shot.py        截图自检（PrintWindow + PW_RENDERFULLCONTENT，不受遮挡影响）
│   ├── _qa_windows.py     列出窗口的可见性 / 最小化 / 位置尺寸（DPI 感知）
│   ├── _qa_close_window.py  按标题发 WM_CLOSE（用来验「关掉地图窗口自动收回」）
│   ├── _qa_bridge_dom.cjs 页面级桥自检：点按钮 / 按键有没有真的打到 pywebview 桥上
│   └── _qa_probe.py       宿主探查（窗口/进程/环境）
└── _qa/              ← 自检截图（纯留档，可随时删）
```

---

## 1. 隔离声明（重要）

这个目录**与项目里其它文件完全无关**，满足「独立模块」要求：

| 约束 | 实际情况 |
|---|---|
| 是否引用既有文件 | ❌ 不引用。没有 import / require / fetch，没有外部 CSS、JS、字体、图片 |
| 是否修改既有文件 | ❌ 不修改。`followmap/`、`app.py`、`ruins.json`、`out/*` 一个字节都没动 |
| 是否依赖既有逻辑 | ❌ 不依赖。界面自带演示数据源，脱离游戏与 Python 程序也能独立运行 |
| 对外全局符号 | 只有 **1 个**：`window.PaoTuAlertUI`（见 §5），不污染其它命名空间 |
| 网络请求 | 0 次。favicon 也用内联 data-URI，断网可用 |
| 删除方式 | 直接删掉整个 `paotu-alert-ui/` 目录即可，无残留 |

它读取的**参数值**（遗迹判据、去重半径、轮询间隔、音量、连响次数…）是从既有文件里
**抄下来的常量**，只是为了让界面数字与真实程序一致；运行时不读那些文件。

---

## 2. 怎么打开

- **最简**：双击 `index.html`（Edge / Chrome 均可）。
- **要预览/联调**：起一个本地静态服务再访问，避免个别浏览器对 `file://` 的限制：
  ```
  cd D:\wbworkspace\2026-10-08-17-29-12\fangkuai-chuanshuo\paotu-alert-ui
  python -m http.server 8770 --bind 127.0.0.1
  # 浏览器打开 http://127.0.0.1:8770/index.html
  ```

---

## 3. 三个核心模块

### ① 跑图状态显示（左上）
- **跟随地图预览**：Canvas 逐区块绘制，`1px = N 格`（×1/×2/×4/×8 四档，同真实程序的 `ZOOMS`），
  128 格网格线、菱形遗迹标记 + 名称、玩家红点 + 白描边 + 十字准线 + 朝向三角。
  未探索区域保持虚空黑 —— **视觉上就能看出「只扫了已探索区域」这条红线**。
- **HUD 叠加**：把真实程序画在窗口上的那几行原样搬过来（维度/地图子图 · X Y Z · 视野格 /
  坐标源 / miss / 渲染 ms · 内存直读延迟 · 最近一条命中 · 已记录遗迹数）。
- **读数区**：维度、地图源、视野、渲染耗时、缺瓦片、内存延迟、已扫区块、已记录遗迹。
- **扫描节拍**：0.6 s 一轮的心跳条 + 轮询计数。

### ② 提醒设置（右上）
- **提醒方式**：`auto / sound / both / flag / off` 五档，与 `alerts.py` 的 `MODES` 一一对应；
  通道开关（水滴音 / 窗口抖动 / 任务栏闪烁 / 地图打点）是当前方式的**只读回显**，
  因为组合由方式决定，只能在程序侧改。
- **响度**：音量（0.2–2.0，`>1` 走 tanh 软削波）+ 连响次数（1–5）。
- **遗迹类型**：三类**已实测标定**的判据各自开关（白金 / 巫师 / 武士），
  未标定的三类压成一行 chip 不占版面。
- **去重与重置**：去重半径（96 格基准）、同类冷却、只报稀有、距离方位提示、
  本周期与下次重置倒计时。

### ③ 手动控制（右下）
立即扫描（`S`）、暂停/恢复（空格）、打点当前位置、复位窗口与视图、试听三档音高、
抖动预览、闪烁预览、切换坐标源、切换图层、清空去重库（危险操作，二次确认）、导出日志。
外加一张快捷键表（`S / 空格 / R / C / V / Z / X / G / M / D / H`），其中 **`D` = 分离/收回地图**（见 §7）。

---

## 4. 界面上的数字都是从哪来的

| 界面元素 | 取值 | 来源 |
|---|---|---|
| 三类遗迹图标/颜色/音效 | ★ #e8e8f0 drop_high ／ ◆ #5ad2c8 drop_mid ／ ▲ #dc463c drop_low | `app/ruins.json` v5 `types` |
| 判据文案 | `infested_stone_bricks≥10`、`polished_blackstone_bricks≥20`、`@end_brick≥30 + 黑石件≥1` | 同上（真机 71124 chunk 全量检验后的定稿） |
| 去重半径 96 格 | `dedupe_blocks: 96` | `ruins.json` |
| 纯度阈值 0.80 | `min_purity: 0.80` | `ruins.json` |
| 轮询 0.6 s | `RUIN_POLL_S = 0.6` | `followmap/app.py` |
| 音量 1.5 / 连响 3 | `--ruin-volume 1.5` / `--ruin-repeat 3` 默认值 | 同上 |
| 缩放档 1/2/4/8 | `ZOOMS = (1,2,4,8)` | `followmap/store.py` |
| 128 格网格 | `view.py` 的 `step = 128`、`GRID_COLOR = (255,255,255,28)` | `followmap/view.py` |
| 地图子图名 `mw$default` / `cm$1` | 地表 / 洞穴图 | `view.py` 自检用例 |
| 发现流的历史 13 条 | 真实坐标与纯度 | `app/out/found_ruins.json`（91 条里取前 13 条） |
| 提醒方式循环顺序 | auto→sound→both→flag→off | `alerts.py` 的 `CYCLE` |
| 水滴音物理模型 | 频率**上滑** + 指数衰减 + 二次谐波 + 连响（后几响 0.92ⁿ） | `alerts.py` 的 `synth_drop`，界面用 WebAudio 实时合成 |

> 「发现流」开局展示的 13 条标着 **历史 · 打点留档** —— 那是上一次运行真实落盘过的记录，
> 用来区分本次会话的新命中。

---

## 5. 接后端：唯一接口 `window.PaoTuAlertUI`

界面默认跑**内置演示数据源**（玩家沿真实遗迹坐标自主巡游）。要把它接到 Python 侧，
在页面加载后注入一个适配器即可 —— 界面不主动拉数据：

```js
// 后端推送状态
window.PaoTuAlertUI.setAdapter({
  onState: function (s) { /* 界面就绪时回吐一次当前设置 */ },
  setMode: function (id) { /* 用户在界面改了提醒方式：auto|sound|both|flag|off */ },
  applySettings: function (o) {
    // o = {mode, volume, repeat, dedupe, cooldown, only_rare, distance_hint,
    //      layer, zoom, enabled:{遗迹名:bool}}
  }
});

// 程序侧发现遗迹 → 界面立刻按当前提醒方式走一遍（响铃 + 弹条 + 进流 + 打点）
window.PaoTuAlertUI.pushAlert({ type: '巫师的圣修所', x: 4625, z: -46008, pure: 0.995 });

// 其它
window.PaoTuAlertUI.getState();   // 取当前全部设置与运行态
window.PaoTuAlertUI.scan();       // 触发一次「立即扫描」（等同 S 键）
window.PaoTuAlertUI.pause();      // 暂停 / 恢复
window.PaoTuAlertUI.setMode('both');
window.PaoTuAlertUI.toast('◆', '标题', '副标题');   // 走界面统一的提示条
```

设置改动同时会存进 `localStorage['paotu-alert-ui']`，刷新后保留（不影响程序侧）。

---

## 6. 退出预览 → 进入运行模式

**同一份 `index.html` 同时支持两种模式**，靠一个启动标记切换，不分叉代码：

| | 预览模式 | 运行模式 |
|---|---|---|
| 怎么启动 | 双击 `index.html` | 双击 `dist\末地跑图提醒控制台.exe` |
| 启动标记 | 无 | URL 末尾带 `#live=1` |
| 顶栏徽章 | `预览 · 演示数据`（灰点） | `运行中 · <维度>`（绿点，脉动） |
| 玩家位置 | 脚本模拟巡游 | `~/.coordbridge/coords.json` 实时坐标 |
| 地形 | 程序生成的末地石噪点 | **真实落盘区块**（CBB1 快照） |
| 已发现遗迹 | 13 条历史样本 | `out/found_ruins.json` 真实全量 |
| 主循环 | 自己走 `stepDemo()` + 随机命中 | 演示逻辑**全部停掉**，只等后端推数据 |

> **所以「退出预览进入运行模式」= 用带 `#live=1` 的方式打开页面。**
> 手动也能切：在浏览器里打开 `index.html` 后，在地址栏末尾补 `#live=1` 再回车 ——
> 但这样**没有后端推数据**，只会看到一张空地图（演示数据已被关掉）。
> 真正的运行模式由下面的桌面壳提供数据源。

### 桌面壳（`desktop/host.py`，已打包成 exe）做了四件事

1. **开原生窗口**：pywebview + Edge WebView2（winforms 后端），无地址栏 / 标签页，
   固定标题「末地跑图提醒 · 控制台」，带 `app.ico` 图标。
2. **注入适配器**：页面 `loaded` 后执行一段 JS —— `setLive(true)` + `setAdapter({...})`，
   把 §5 那套接口接到 Python 侧；之后每次状态变化反向推
   `applyRuntime` / `setTerrain` / `seedFound`。
3. **管地图窗口**：随时开 / 关一个只显示地图的独立窗口，并把地形推给**当前该画地图的那一个**
   窗口（见 §7）。
4. **搬运真实数据**（来源都在 `~/.coordbridge/` 与 `out/`）：

   | 数据 | 来源 | 推送节奏 |
   |---|---|---|
   | 玩家坐标 | `~/.coordbridge/coords.json` | 10 Hz 读，按 `t` 去重（值变了才推） |
   | 已发现遗迹 | `out/found_ruins.json` | 文件变化时刷新 |
   | 地形区块 | `~/.coordbridge/chunks/<world>/…`（CBB1） | 移动 > 24 区块 或 距上次 > 8 s 才重扫；分批 400/批 |

   地形是**重活**，分三步降开销：先只读文件名解析 `cx/cz` 建索引
   （28 295 块 / **0.14 s**），再按「玩家 ±24 区块」读相关区块（3 000 块 / **3.4 s**），
   最后排序 + 截断到上限 3 000 块，分批喂给界面。

**真机实测**（`runtime/bridge.log` 实录）：

```
页面已加载，注入运行模式: 'live'
区块索引已刷新: minecraft_overworld 28295 块，0.14s
地形已更新: minecraft_overworld 3000/28295 块，3.36s
```

地图上能看到真实的**主世界陆地 / 水域**与**玩家轨迹**（截图 `_qa/live-full.png`），
而不是预览模式的末地石噪点。exe 启动后会在自己旁边建一个 `runtime/`（日志 + 动作留档），
删掉 exe 与 `runtime/` 即无残留。

### 自己重新打包

```
cd desktop
# build.py 已封装好全部参数，用装了 pywebview + pyinstaller 的那个解释器直接跑：
  python build.py
  # → ..\dist\末地跑图提醒控制台.exe
```

依赖：`pip install pywebview pyinstaller`（本机是在独立 venv 里跑的，路径不进仓库）。

产物是 `--onefile` 单文件（**12.6 MB**），已内嵌 `index.html` 与 `app.ico`，
**目标机器无需装 Python**；唯一前置是 **Edge WebView2 Runtime**
（Win10 1803+ / Win11 通常自带；缺失时微软官网免费安装）。

### 可选配置 `config.json`

把 `desktop/config.example.json` 复制为 `config.json` 放到 **exe 同目录** 即生效：

| 键 | 作用 | 默认 |
|---|---|---|
| `app_dir` | **followmap 主程序目录**（拿它 `out/found_ruins.json` 里的已发现遗迹）。不填就只在 exe 附近向上搜索，搜不到则列表空白，其它功能照常 | 无（自动探测） |
| `dim` | 游戏不在世界中时，地图默认显示哪个维度 | `minecraft:the_end`（在游戏中跟随玩家） |
| `echo_actions` | 把界面操作写进 `runtime/actions.jsonl` | **`true`** |
| `webview_args` | WebView2 启动参数 | `--no-sandbox` |
| `start_detached` | 启动即把地图分离到独立窗口（等同命令行 `--detach`） | `false` |
| `map_window` | 独立地图窗口的几何与样式：`width` / `height` / `x` / `y` / `frameless` / `on_top` / `resizable` | `560×620`、无边框、置顶、可缩放 |

> `app_dir` **不是** CoordBridge 数据目录 —— 那个固定读 `~/.coordbridge`（模组写死的），不可配。

> `--no-sandbox` 是**必需**的：WebView2 渲染进程的沙箱在受限令牌 / Job 对象里起不来，
> 去掉它窗口就是白屏（实测 `--disable-gpu` 单独加也不管用）。

---

## 7. 地图分离（把地图甩到独立窗口，省屏幕）

游戏占一个屏、控制台占另一个屏时，控制台里那块「跟随地图预览」其实是多余的 ——
想常驻盯着看的是地图本身。于是加了**地图分离**：地图单独成一个小窗口，控制台那块腾空，
可以缩到只剩提醒流与设置。

### 怎么用

| 动作 | 操作 |
|---|---|
| 分离 | 控制台里点 `⧉ 分离地图`，或按 **`D`** |
| 收回 | 地图窗口里点 `⤢ 收回控制台`，或按 **`D`**；**直接关掉地图窗口也等于收回** |
| 开机就分离 | `末地跑图提醒控制台.exe --detach`，或 `config.json` 里 `"start_detached": true` |

地图窗口是**无边框 + 置顶**（游戏全屏也看得见）、默认 560×620；
顶部 22 px 是一条**拖拽条**（拖它移动窗口，画布区域不会被误拖）。拖到副屏或屏幕角落钉住即可。

### 原理：一份 `index.html`，三种视图

不为地图窗口单开一个 HTML 文件，靠 URL hash 切视图（`file://` 下 query 会被编码，所以只用 hash）：

| 视图 | 谁在用 | 样子 |
|---|---|---|
| `#view=full` | 控制台（默认） | 完整界面 |
| `#view=map` | 独立地图窗口 | 只有地图 + 顶部拖拽条 + 收回按钮 |
| `#view=panel` | 控制台（地图已被分离时） | 完整界面，但地图那一块塌成一条提示 |

> 正常运行时**不用手写这几个 hash**：控制台固定 `full`；桌面壳开地图窗口时自动加 `&view=map`；
> 地图一被分离，壳调 `setMapDetached(true)` 把控制台切到 `panel` 形态。
> 手动加 hash 只是为了单独预览某一种形态。

### 同一时刻只有一个窗口在画地图

地形是重活（一次读盘 3 000 块要 3 秒多），所以 `Bridge.map_windows()` 只返回
**该画地图的那一个**窗口：地图被分离时是独立窗口，否则是控制台。

窗口切换（分离 / 收回 / 关掉地图窗口）时走 `Bridge._resync_windows()` —— 地形**从内存缓存重推**
给新的那个窗口，不重新读盘。日志上是一条完整的往返：

```
已开独立地图窗口（无边框=True 置顶=True 560x620）
独立地图窗口页面已加载，注入运行模式: 'live'；桥自检 {"ui":true,"hasBridge":true,"apiKeys":10}
地形已更新: minecraft_26guoqing_3_1 422/422 块，0.13s → 地图窗口
窗口变化 → 重推全量给地图窗口（422 块）
……
独立地图窗口已关闭，地图回到控制台
地形已更新: minecraft_26guoqing_3_1 422/422 块，0.60s → 主窗口
```

截图：`_qa/detach-map-window.png`（独立地图窗口）、`_qa/detach-console.png`（控制台腾空后的样子）。

### 界面接口（新增）

```js
window.PaoTuAlertUI.setMapDetached(true);    // 桌面壳调：告诉界面「地图已分离」
window.PaoTuAlertUI.getState().view;          // 'full' | 'map' | 'panel'
window.PaoTuAlertUI.getState().map_detached;  // 布尔
```

`setMapDetached(on)` 幂等；在 `#view=map` 的地图窗口里调它**无效**（地图窗口永远画地图）。

---

## 8. 便携版（发给别的电脑）

`dist/PaotuAlert-Portable/` + 同名 `.zip` —— 一个**自带 exe** 的完整分发包，
拷到别的 Windows 电脑上解压即用，**对方不用装 Python**。

### 包里有什么

| 文件 | 说明 |
|---|---|
| `末地跑图提醒控制台.exe` | 主程序（12.6 MB，界面 / 图标已内嵌） |
| `启动.bat` / `启动-分离地图.bat` | 双击入口（后者带 `--detach`，一开就把地图甩到独立小窗） |
| `index.html` | 界面副本，双击可看演示效果（不接真实数据） |
| `config.example.json` | 配置模板，**app_dir 已留空** —— 不把本机路径带给对方 |
| `coordbridge/` | CoordBridge 模组 jar，装到 `.minecraft\mods\` |
| `README-便携说明.md` | 面向**接收方**的说明书（前置条件 / 启动 / 数据来源 / 空白排查） |
| `runtime/` | 空目录，运行期日志（exe 自己往里写） |

### 怎么打

```
cd desktop
打包便携版.bat                       # 或者： <python> make_portable.py
```

`make_portable.py` 形制跟着 `app/make_portable.py`（FollowMap 那份便携包）走：

1. **白名单收文件** —— 不收 PyInstaller 的 `build/`、`_qa/` 截图、`dist/runtime/` 里的本机日志。
2. **清洁性检查** —— 目标目录里一旦出现 `config.json` / `runtime/*.log` / `actions.jsonl` 就报出来并删。
   前两个是本机配置与流水，带过去只会把对方带偏（`actions.jsonl` 记的是**本机**的操作）。
3. **bat 静态检查** —— 启动器必须**纯 ASCII、无 BOM、CRLF**。cmd.exe 按**字节偏移**解析 `.bat`，
   一行 UTF-8 中文就会让后面每一行丢掉开头字符。exe 名是中文改不掉，所以 bat 里用通配 `*.exe`
   取路径，**不把中文写进 bat 内容**。
4. **打 zip** —— 标准库 `zipfile`，并且**显式写入空目录 `runtime/`**（不然解压后第一次跑要自己建）。

> 脚本刻意**不 import** `app/check_bats.py` —— `paotu-alert-ui/` 要能整目录删掉，不跨项目依赖。
> 它只**读** `app/coordbridge/*.jar`；找不到就跳过模组那一步，不影响出包。

### 隔离复验（实测）

把 zip 解压到 `%TEMP%` 下的空目录、从零启动（`bridge.log` 实录）：

```
21:55:52  页面已加载，注入运行模式: 'live'
21:55:52  已开独立地图窗口（无边框=True 置顶=True 560x620）
21:55:53  独立地图窗口页面已加载，注入运行模式: 'live'；桥自检 {"ui":true,"hasBridge":true,"apiKeys":10}
21:55:53  地形已更新: … 72/72 块 → 地图窗口
```

**两条入口都验过**：直接运行 `末地跑图提醒控制台.exe --detach`，以及双击 `启动-分离地图.bat`
（后者证明了 bat 里的通配路径确实取到了中文 exe 名）。`apiKeys:10` 说明 §11 那个 `js_api`
修复**已内嵌进 exe**，便携包里没有回归。截图 `_qa/portable-map.png`。

### 接收方还需要什么

exe 免装 Python，但**数据全来自 Minecraft 侧**（程序自己不产生数据），所以对方至少要有：

| 必需 | 说明 |
|---|---|
| Windows 10 1803+ / 11 | 用系统自带的 Edge WebView2 内核（较新系统一般都自带） |
| Minecraft 1.20.1 ~ 1.20.4 + Fabric | —— |
| CoordBridge 模组 | **唯一的数据来源**。不装程序照开，只是地图空白、坐标显示 `--` |

缺模组时**不会崩、不会报错**，只是没有数据 —— 这条路径在代码上有保护
（`app_dir` 为空时直接 return，地形取自 `~/.coordbridge`，与它无关）。
完整清单与排查步骤在包内的 `README-便携说明.md`。

---

## 9. 自适应与自检结果

| 断点 | 表现 |
|---|---|
| ≥ 1180 px | 双列：左「状态 + 发现流」，右「提醒设置 + 手动控制」；两列等高，左列末屏自动撑满 |
| 860–1180 px | 单列堆叠，顺序：地图 → 发现流 → 提醒设置 → 手动控制 |
| ≤ 860 px | 地图读数区折到画布下方；按钮自动换行 |
| ≤ 620 px | 紧凑间距与字号 |

实测（Playwright，逐档验证）：

| 宽度 | 横向溢出 | 地图画布 | 结果 |
|---|---|---|---|
| 1920 | 无 | 674 px | 双列等高（各 1740 px），整页 1908 px |
| 1366 | 无 | 481 px | 双列等高（各 1878 px） |
| 1120 | 无 | 全宽 | 单列堆叠 |
| 768 | 无 | 全宽 | 单列 |
| 390 | 无 | 342 px | 单列，无溢出 |
| 320 | 无 | 257 px | 极限仍无溢出 |

功能自检全部通过：`扫描 / S 键 / R 循环方式 / C 切图层 / V 切坐标源 / 空格暂停 /
G·M 开关 / 危险操作二次确认 / 帮助模态 / 导出 .log（格式与 out/ruin_alerts.log 一致）/
pushAlert 外部推送 / 适配器接口` —— 控制台 **0 error / 0 warning**。

**地图分离专项自检**（`desktop/_qa_bridge_dom.cjs`，真浏览器里点按钮 / 按键，
断言「有没有真的打到 `window.pywebview.api` 上」）—— **6 / 6 通过**：

| 用例 | 期望桥调用 | 结果 |
|---|---|---|
| `#view=map` 点「⤢ 收回控制台」 | `attach_map` | ✅ |
| `#view=map` 按 `D` | `attach_map` | ✅ |
| `#view=full` 点「⧉ 分离地图」 | `detach_map` | ✅ |
| `#view=full` 按 `D` | `detach_map` | ✅ |
| `#view=panel` 点「⤢ 收回地图」 | `attach_map` | ✅ |
| 焦点在输入框里敲 `d` | 一次都不该触发 | ✅ |

桌面壳侧（源码运行 + 打包后的 exe 各跑一遍）：`--detach` 开机分离 ✅ ·
关掉地图窗口自动收回（`独立地图窗口已关闭，地图回到控制台`，控制台**未被最小化**）✅ ·
stderr **0 字节**（`Api` 属性加下划线后，pywebview 的自省噪声消失了）✅。

---

## 10. 已知边界

- 演示数据是**本地模拟**的（区块揭开、遗迹命中概率、内存延迟都在抖动），
  目的是让界面「活着」能看出动效；接上适配器后全部替换为真实数据。
- 界面里的「窗口抖动 / 任务栏闪烁」是**预览动效**（抖自己、闪顶栏），不是真的去调
  `FlashWindowEx` —— 真窗口在 Python 侧，这里只是让你确认强度是否合适。
- 水滴音是**现场合成**的近似：频率曲线、包络、连响次数、软削波都按 `synth_drop` 还原，
  但没有逐样本对齐（浏览器不做 SND_ASYNC 那套）。真要听成品音，用界面里的
  「试听」对比 `app/assets/drop_*.wav` 即可。

---

## 11. 修复记录

### 2026-10-16 · 配置表两处写错（文档更正，非代码 bug）

做便携版时顺手 `grep cfg.get` 核对了配置项的**真实默认值**，发现第 6 节的表格有两行是错的：

| 原来写的 | 真相（`host.py`） |
|---|---|
| `app_dir` = 「指定 CoordBridge 数据目录」 | `app_dir` 是 **followmap 主程序目录**（拿它 `out/found_ruins.json`）。CoordBridge 数据目录固定读 `~/.coordbridge`，**不可配** |
| `echo_actions` 默认 `false` | 默认 **`true`** —— `Api.__init__` 里是 `_cfg.get("echo_actions", True)` |

> 教训：配置表的默认值一律从代码里抄（`grep _cfg.get`），别照着自己的印象写 —— 印象会错，代码不会。

### 2026-10-16 · 地图窗口里的按钮与快捷键全哑了（`js_api` 是按窗口的）

**现象**：地图已经能正常分离出来、地形也画得对，但**在地图窗口里点「⤢ 收回控制台」、按 `D` 都没反应**；
控制台那边一切正常（`D` 能顺利分离出去）。

**取证**：`runtime/actions.log` 里只有 `detach_map`，一次 `attach_map` 都没有 —— 说明调用**根本没发出去**。
外部注入鼠标/键盘在这台机器上被前台锁挡住（见 §11 末尾「两条验不出结论的弯路」），
于是改用**宿主内探针**：在地图窗口 `loaded` 后 evaluate 一小段 JS，把桥的形状写进日志：

```
独立地图窗口页面已加载，注入运行模式: 'live'；桥自检 {"ui":true,"hasBridge":true,"apiKeys":0}
```

`apiKeys:0` —— 那个窗口里的 `window.pywebview.api` 是个**空对象**。

**根因**：pywebview 的 `js_api` 是**每个窗口各注入一份**的。`webview/util.py` 里
`inject_pywebview()` 按 `window._js_api` 生成 `window.pywebview.api`
（`get_functions(window._js_api)`），而 `webview.create_window()` 的 `js_api` 默认是 `None`。
所以主窗口有 api、运行时新建的地图窗口没有 → `window.pywebview.api.attach_map` 是 `undefined`，
**而适配器里 `function () { try { ... } catch (e) {} }` 把这个 TypeError 吞了**，于是完全静默。

**修法**：`Shell` 持一份 `self.api`（`main()` 里回填），开地图窗口时一起传：

```python
w = webview.create_window(
    MAP_TITLE, self.ui_uri + "&view=map",
    ..., js_api=self.api,      # ← 漏了这个，地图窗口里的按钮 / D 键就全是哑的
)
```

**验证**：修后同一段探针变成 `{"ui":true,"hasBridge":true,"apiKeys":10}`；
再用 `_qa_bridge_dom.cjs` 在真浏览器里点按钮 / 按键，确认 `#view=map` 下「收回控制台」与 `D`
都真的打到 `attach_map`（**6 / 6 通过**）。打包后的 exe 里也复现了同样的日志。

**顺手加的护栏**：`Shell._on_map_loaded()` 现在**常驻这段桥自检**（`ui / hasBridge / apiKeys`
三个字段进 `bridge.log`）。以后哪次开窗口又漏传 `js_api=`，日志里直接就有证据，不用再靠猜。

### 2026-10-16 · 地图窗口的三个显示小坑

| 现象 | 根因 | 修法 |
|---|---|---|
| 地图窗口里画布被**拉变形**（canvas 属性 560×560，容器 560×640） | 地图视图沿用了「强制正方形」的尺寸逻辑 | 地图视图改成**铺满窗口**（不强行正方形），整幅等比缩到长边 ≤ 1400（约束每帧贴图数量） |
| 地图窗口的 HUD **压住**顶部拖拽条 | HUD 的 `top` 没把 22 px 拖拽条算进去 | `body.view-map .map-hud{top:28px}` |
| 控制台里「收回地图」按钮**看不见** | `#btnAttach,#btnDetachBack{display:none}` 把占位条里的按钮一起藏了 | 只藏 `#btnDetachBack`（占位条本身默认就是 `display:none`） |
| 直接以 `#view=panel` 打开时「收回地图」**点不到** | `mapDetached` 变量已是 `true`，但 DOM 上没挂 `is-detached` → 按钮的父容器 `display:none` | boot 末尾补一句 `if (VIEW === 'panel') setMapDetached(true);` |

### 2026-10-16 · 两条验不出结论的弯路（别再重复试）

自检「地图窗口里点按钮 / 按键」时，从外部注入输入全部失败，且**都不是程序的问题**：

| 尝试 | 结果 | 结论 |
|---|---|---|
| `SetForegroundWindow` → 点空白处抢焦点 → `keybd_event` | `GetForegroundWindow` 仍不是目标窗口 | 被**前台锁**拒绝。Minecraft 占着前台（全屏独占）时尤其顽固 |
| 加 `AttachThreadInput` + 先敲 ALT + `SwitchToThisWindow` + 重试 6 次 | 依然失败 | 同上 |
| 改为**纯鼠标点击**（置顶窗口，鼠标事件只看落点、不需要焦点） | 窗口并**没有**被激活，按钮也没响应；对照组：点控制台同样不激活 | 这台机器上**合成输入（`SendInput`）整体被挡**，与本程序无关 |
| `mcp__windows-mcp` 那套桌面自动化 | 返回 `USER_CONTROL` | 需要用户接管，同样用不上 |

> **真正管用的替代**：① 用宿主内 `evaluate_js` 打探针（能看到「窗口里到底有什么」）；
> ② 用 `_qa_bridge_dom.cjs` 在真浏览器里验「点按钮 → 有没有打到桥上」。
> 两段一拼，链路照样闭合，不必依赖真鼠标。
> 唯一验过能用的合成输入是**键盘**（`_qa_key.py` 那套，在被测窗口本来就在前台时成功过一次）——
> 已随结论归档删除，不值得再依赖。

### 2026-10-16 · 画面「一直卡在末地不动」+「一直抖动」

**现象**：打开页面后画面像定在末地不动，并且一直在抖。

**取证**：起本地服务后用 Playwright 逐帧采样玩家坐标，12 秒 13 个点，位置**精确交替**：

| 采样 | z | 相对上一个点 |
|---|---|---|
| t + 0.5 s | -45976.1 | — |
| t + 1.5 s | -45966.6 | **+9.5** |
| t + 2.5 s | -45976.1 | **−9.5** |
| …连续 12 次 | | 每次精确 ±9.5 |

心跳条同时在推进（75% → 0%），说明主循环是活的 —— 所以不是卡死，而是**位置在原地来回弹**。

**根因**：`stepDemo()` 旧的目标选择是「每帧重选『最近的、且距离 > 40 格』的航点」。
玩家一旦飞进 40 格阈值内，该航点立刻被排除 → 换成反向的下一个航点；下一帧又飞出 40 格
→ 被换回来。于是**每帧都反向**，位置在两点之间无限震荡（60 fps 下相当于 30 Hz 抖动），
跑图零进展 —— 看着就是「卡在末地」+「一直抖」。这类「阈值切换没有滞回」的选择逻辑是通病。

**修法**：改为**一经锁定不再重选** —— 只在 `≤ 24 格`（`CAPTURE` 半径）判定「到点」时才
推进到下一个航点，其余时间一律朝当前航点飞。

**验证**：同一套采样脚本复测 15 秒 16 点，`directionFlips = 0`，dx / dz 恒定（4.1 / 8.6），
航点剩余距离稳定倒数（7,942 → 7,847 格）。

**连带修掉的第二处**（同一错觉的另一半）：`reveal(S.px, S.pz, 5)` 把「已探索」半径开到
1280 格，远大于视口（1px = 1 格时视口仅 560 格）—— 满屏是同一片末地石噪点，滚动时肉眼
分辨不出在动，进一步加深「卡住」的错觉；且每帧还有 50% 概率随机补一块，每秒新增约 750 个
区块键，跑久了拖慢绘制。现改为 `reveal(…, 2)`（约 512 格宽的一条轨迹）+ 去掉随机补块：
实测 10 秒区块增量由 ~7 500 降到 **14**，轨迹边界也不再抖动。

**新增读数**：标题栏加 `→ 航点 n/8 · 剩 x 格`，跑图进度到此可见（≤ 900 px 自动隐藏，
避免窄屏挤压）。

### 2026-10-16 · 桌面壳（运行模式）打包踩的坑

| 现象 | 根因 | 修法 |
|---|---|---|
| `create_window() got an unexpected keyword argument 'icon'` | pywebview 6.x 把 `icon` 从 `create_window` 挪到了 `webview.start()` | `icon=` 改传给 `start` |
| 原生窗口起来了，但页面**永远不加载**（`loaded` 事件不触发，20 s 后 `evaluate_js` 抛 `Main window failed to start`） | WebView2 渲染进程沙箱在受限令牌 / Job 对象里起不来 | 注入 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--no-sandbox` —— 实测 `--disable-gpu` 单独加**无效** |
| `#live=1` 标记传不进页面 | 用 `?live=1` 会被 `file://` URL 编码成 `%3Flive%3D1` | 改用 `#live=1`（hash 不编码），标记正则改 `/[?&#]live=1/` |
| 首次加载地形卡 **43 s** | 逐块读取 28 295 个 CBB1 文件 | 先只解析**文件名**拿 `cx/cz` 建索引（0.14 s），再按玩家 ±24 区块读相关块（3.0 s） |
| 截图看着右半边被切掉 | 截图工具 DPI 不感知（宿主 150% 缩放，dpr=1.5） | `SetProcessDpiAwareness(2)`；用 `PrintWindow(PW_RENDERFULLCONTENT)` 可穿透 DirectComposition 抓到被遮挡的 WebView2 内容 |
