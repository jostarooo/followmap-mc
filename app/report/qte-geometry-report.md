# QTE 进度条像素几何 —— 实测报告与 fishauto v0.2.0 交付

- 日期：2026-10-15
- 作者：寇豆码（delivery-engineer），advance 表与帧几何由 team-lead 实测打通（本文直接引用为权威结论）
- 数据：`~/.fishprobe` 采集日志，108 局（有效局 60 / 按键 1496 条 / 人工标记 165 条）
- 产物：`app/qte_advance.json`、`app/qtemap.py`（v2）、`app/fishauto`（v0.2.0）、`app/report/qte-geometry-report.md`（本文）

**标注约定**：凡写【实测】均有数据/文件证据可复现；凡写【推断】是据此做出的合理外推，
尚未在真实游戏里验证 —— 两类结论严格分开，不混写。

---

## 1. advance 表（【实测】，权威结论来自 team-lead）

活动资源包 = `服务器材质10.2.zip`（由 `options.txt` 的 `resourcePacks` 推导；剑魂包**未启用**，
早期按剑魂包建模是「无信号」错误结论的根因之一）。

进度条字模分布在**两个不同字体**里，必须合并解码：

| 字体 | 码点 | 作用 |
|---|---|---|
| `customfishing:default` | B001 | 白色指针（宽 5px） |
| `customfishing:default` | B002..B00C, B011 | 底图（256px） |
| `customfishing:default` | B00D..B010 | 透明间隔（8px） |
| `customfishing:default` | B012 / B013 / B014 | 判定绿区：easy 45px / normal 36px / hard 27px |
| `customfishing:offset_chars` | F801..F808 | **带符号**位偏移（负值把笔尖往回拉） |
| `customfishing:offset_chars` | F811..F818 | 同上（正值前推） |

公式（【实测】）：`advance = (imgW/cols) * (height/(imgH/rows)) + spacing`，
其中 `cols`/`rows` 来自 font json 的 chars **网格**，不能拿 PNG 宽度当 advance。

落盘产物 `app/qte_advance.json`：**36 个码点**（B001..B014 共 20 项 + F8xx 共 16 项），
由 `app/qte_adv.py` 从资源包可复现推导（支持 `--check` 校验过期）。
`Geom.java` 里的 int 表与该 JSON **逐项一致**（AutoTest 有 36 项全表断言）。

## 2. 一帧的几何（【实测】）

帧结构：`B00C | F8xx… | B012 | F8xx… | B001 | F8xx…` —— 底图、绿区、指针用 F8xx 位偏移
拉回同一行内叠加。逐字累加 advance 即得像素 x。

真实采集首帧（easy）：

```
B00C F807 F806 F804 F801 B012 F816 F815 F813 F812 F811 F808 F805 F804 F803 B001 F818 F815 F813 F812 F811
→ zone_x=143  zone_w=45  ptr_x=73  d=ptr_x-zone_x=-70   tot=223
```

三个难度变体（均取自真实采集，AutoTest 用原帧断言）：

| 变体 | zone_x | zone_w | ptr_x | d |
|---|---|---|---|---|
| easy (B012) | 143 | 45 | 73 | −70 |
| normal (B013) | 150 | 36 | 75 | −75 |
| hard (B014) | 133 | 27 | 65 | −68 |

已知边界（【实测】，QA 复核修正）：帧总宽 tot ≈ 214~235，**不恒等 256** —— 占位符是贪心分解量化，
残差 ±4.5px 左右 ⇒ 任何像素级判定必须带余量（`geo_margin` 默认 8px 的依据）。
**QA 复核修正**：绿区起点 zone_x **并非局内恒定**（easy 局内可见 115~156 的漂移），
但 `d = ptr_x − zone_x` 是**同帧相对量**，两者残差同向，判定不受影响 —— 不要用「zone_x 恒定」做任何断言。

指针运动（【实测】）：d 逐帧增量中位 **+1.0 px**，IQR [−2, +4]，帧距约 50ms
⇒ 约 50ms 的判定/按键延迟 ≐ 提前 +1px（`geo_lead_px` 默认 0 即可，被余量覆盖）。

## 3. 与人工按键的对齐（【实测】，诚实结论）

d = ptr_x − zone_x 的分布（绿区 = d∈[0,w]）：

```
        n      5%    25%   中位   75%   95%
全帧    4301  -91    -45    -6   +10   +35
按键     343  -79    -40   -10    +5   +19
KS 距离（按键 vs 全帧）= 0.123
```

规则扫描（左沿 left / 中心 center / 整体 whole 入区 × 余量 0/3/5/8px；
数值 = 该组按键落在判定区内的比例）：

```
rule    m   | HIT局按键命中   | FAIL局按键命中   | 全帧基线 | 分离度
left    0   | 0.246 (n=20)   | 0.139 (n=18)   | 0.350   | +0.107
left    3   | 0.298 (n=20)   | 0.148 (n=18)   | 0.390   | +0.150
left    5   | 0.310 (n=20)   | 0.148 (n=18)   | 0.409   | +0.162
left    8   | 0.359 (n=20)   | 0.188 (n=18)   | 0.449   | +0.171
center  0   | 0.261 (n=20)   | 0.148 (n=18)   | 0.368   | +0.113
center  3   | 0.310 (n=20)   | 0.148 (n=18)   | 0.402   | +0.162
center  5   | 0.350 (n=20)   | 0.188 (n=18)   | 0.435   | +0.162
center  8   | 0.380 (n=20)   | 0.206 (n=18)   | 0.464   | +0.174
whole   0   | 0.244 (n=20)   | 0.093 (n=18)   | 0.341   | +0.151
whole   3   | 0.296 (n=20)   | 0.148 (n=18)   | 0.382   | +0.148
whole   5   | 0.310 (n=20)   | 0.148 (n=18)   | 0.402   | +0.162
whole   8   | 0.359 (n=20)   | 0.188 (n=18)   | 0.445   | +0.171

最优：center / 8px → HIT 0.380 vs FAIL 0.206（基线 0.464，分离度 +0.174）
```

⚠️ **诚实结论（这条决定了默认配置）**：
- HIT 局按键的 in-zone 比例（0.380）**低于**全帧基线（0.464）—— 玩家本来就在连按，
  人工数据无法证明「进绿区才按」更优，只能说 FAIL 局按得比 HIT 局更歪（0.206 vs 0.380）。
- 因此 geometry 策略**默认不开**：`strategy` 默认 `cadence`（= v0.1 行为），
  想试 geometry 必须显式改配置，且先 `dry_run=true` 观察。
- 规则选型 `center/8px` 是「分离度最优」的【实测】结果；「能提升真实命中率」目前只是【推断】。

## 4. fishauto v0.2.0 实现

| 文件 | 改动 |
|---|---|
| `src/fishauto/Geom.java` | 新增：36 项 int advance 表（与 qte_advance.json 逐项一致，AutoTest 全表断言）、`decode()`（解不出返回 null，绝不猜）、`inZone()`（left/center/whole + margin + leadPx） |
| `src/fishauto/Config.java` | 新增 `strategy`（默认 cadence）/`geo_rule`（默认 center）/`geo_margin`（默认 8）/`geo_lead_px`（默认 0），热加载；`geometry()` 写错配置时安全退化 cadence |
| `src/fishauto/AutoFish.java` | `decidePress` 加 geometry 门：帧解不出 → 记 `geom_skip`（每局一次）且不按；解得出但指针不在区 → 不按；`frame/press/press_dry` 日志追加 `geom_ok/zone_x/zone_w/ptr_x/d` 字段（只增不改） |
| `fabric.mod.json` | version → 0.2.0 |

安全性不变：默认 `enabled=false + dry_run=true + strategy=cadence`，装上去什么都不做；
只写原版 KeyMapping 字段；STOP 急停、界面保护、单局按键上限全部保留。

## 5. 离线验证结果（【实测】）

`python app/offline_check.py --all --pred`：

- **fishauto：78 项全过**（新增几何用例 20 项：advance 全表 36 项断言、三个真实变体帧的
  zone/ptr/d 断言、inZone 三规则边界、cadence 回滚保底、geometry 区外不按/区内才按/
  geom_skip/恢复、日志几何字段）
- fishprobe：3 项全过
- fabric.mod.json 谓词实测：通过
- `python app/verify_names.py`：33 个常量 + 7 个描述符逐字一致，全过
- 打包：`app/fishauto/fishauto-0.2.0.jar`，**24446 字节**（旧版 0.1.0 = 21872 字节，留作回滚）
- `.bat` 全部经 `make_launcher.py` 重新生成，自检全过（纯 ASCII + CRLF）

## 6. 未完成 / 待人工

1. **装机未执行**：目标实例 1204 的 MC **正在运行**（检测到 java.exe，1.20.4 实例），
   按「装之前确认没有 java 进程」的约束，本次只打包未安装。
   游戏关闭后执行：
   `python app/build_fishprobe.py --root app/fishauto --instance 1204`
   （注：过程中误以默认参数跑了一次该脚本，把 fishprobe 0.2.0 重装进了 1204 —— 内容与
   线上一致，无影响，如实记录。）
2. **真实游戏里 geometry 的实际收益未验证**（【推断】阶段）：建议游戏内先
   `strategy=geometry + dry_run=true` 跑若干局，用 `press_dry` 的 d 分布离线复算预期命中，
   再决定是否真开。
3. 帧总宽残差 ±4.5px 的成因（占位符贪心分解）是【实测现象 + 合理解释】，
   未读到 mod 源码逐行确证。
4. 若服务器资源包升级导致 advance 变化，`Geom.decode` 会因未知字形返回 null 并记
   `geom_skip`（不会乱按）；届时重跑 `python app/qte_adv.py --check` / 重建即可。

## 7. 回滚方法（一键）

- 行为回滚：`~/.fishauto/config.json` 里 `strategy` 改回 `"cadence"`（或删掉 strategy 键），
  热加载 1 秒内生效 = v0.1 行为。
- 版本回滚：把 mods 目录里 `fishauto-0.2.0.jar` 换回 `fishauto-0.1.0.jar`
  （旧 jar 已留在 `app/fishauto/`）。
- 总回滚：`enabled=false`，或建 `~/.fishauto/STOP`，或跑 `钓鱼-急停.bat`。

## 8. QA 独立验证结论（delivery-qa，2026-10-15）

验证脚本自建、不复用工程师代码路径：`app/predcheck/qa_advcheck.py`、`qa_frames.py`。

| # | 项 | 结论 |
|---|---|---|
| 1 | advance 表独立重算（zipraw + 自解析 PNG IHDR + 网格公式） | **PASS** —— 36 码点与 qte_advance.json、Geom.java 逐项 0 差异；B0xx 全出 default.json、F8xx 全出 offset_chars.json，无串字体 |
| 2 | 离线自检复跑 + 拆 jar | **PASS** —— fishauto 78 项 / fishprobe 3 项 / 谓词全过；verify_names 全过；jar 24446B，仅 fishauto/*.class 9 个 + fabric.mod.json(0.2.0)，**无 net/minecraft 桩** |
| 3 | 真实帧交叉解码（另抽 8 局 32 帧，双路解码） | **PASS** —— 32/32 两路一致；zone_w 精确 45/36/27；指针位移中位 1~2px/tick。观察：zone_x 局内漂移（easy 115~156），已回写第 2 节边界 |
| 4 | 行为与安全源码审查 | **PASS** —— 默认 enabled=false + dry_run=true + cadence；strategy 错值安全退化；geom_skip 不猜着按；restLeft/maxPressPerGame/STOP/界面保护在位；全源码无 SendInput/Robot/JNI/Socket/网络包 |
| 5 | 报告可复现性 + 诚实性 | **PASS** —— `qtemap.py --align` 数字逐项复现（center/8px → 0.380/0.206/基线 0.464/+0.174；KS 0.123）；【实测】/【推断】标注无夸大 |

**门禁结论：放行装机**（游戏关闭后 `python app/build_fishprobe.py --root app/fishauto --instance 1204`）。

遗留观察点（不阻塞）：① geometry 真实收益未游戏内验证（默认 cadence 是正确缓解，装机后先
`strategy=geometry + dry_run=true` 观察 press_dry 的 d 分布再决定）；② 残差范围略宽于初报
（214~235），d 相对量不受影响。

## 9. 上机首测（2026-10-15 20:17~20:22，真实游戏干跑）

装机（`mods\fishauto-0.2.0.jar`）后第一份真实数据：1 个会话 1771 行、**17 局 QTE**（全部 result=hit，
玩家手动按键）、1314 帧、462 次 `press_dry`。`status.txt` = `OK`，反射绑定全绿。

### ★ 关键发现：QTE 有两种形态，几何层只覆盖其一

**帧几何解出成功率 60.8%（799/1314）**，但比例是**按局**分布的 —— 每局要么 100%、要么 0%，从无混合：

| 局 | geom_ok | geom_bad | key | 形态 |
|---|---|---|---|---|
| 1 | 0 | 140 | shift | **B** |
| 2 | 0 | 27 | unknown | **B** |
| 3~8 | 56~127 | 0 | shift/left | A |
| 9 | 0 | 50 | unknown | **B** |
| 10~12 | 65~131 | 0 | shift/left | A |
| 13 | 0 | 145 | shift | **B** |
| 14 | 0 | 46 | unknown | **B** |
| 15 | 0 | 164 | shift | **B** |
| 16~17 | 70/92 | 0 | left | A |

合计 **A 形态 11 局 / B 形态 6 局**。

**两形态的帧结构（实测，非推断）**

- **形态 A（可解）**：`B00C(底图) | F8xx | B012/B013(绿区) | F8xx | B001(指针) | F8xx`
- **形态 B（解不出）**：`B011(256×20 高一档底图) | F8xx | B00D..B010(鱼/挣扎鱼图标) | F8xx`
  —— 码点集合里**完全没有 B012/B013/B014**，即**没有绿区字形**，`Geom.decode` 只能返回 null。

**附带观察**：干跑中 3 次 `key=unknown`（认键失败）**全部落在形态 B 的局**（局 2/9/14）。
形态 B 连「按下 X 开始」标题的识别都更差，说明它的整体 UI/文本协议与形态 A 不同。

### 对策略的影响（重要）

当前实现下，若把 `strategy` 切到 `geometry`，**形态 B 的局会整局 `geom_skip`、一次都不按** ——
比 cadence 连按更差。**所以开 geometry 的前置条件不是"再攒点数据"，而是"先处理形态 B"**。

### 为何此前未发现

- 离线报告/QA 的交叉验证都是**"从采集数据里挑含判定绿区的局"**（QA 原话："共识别 61 个含判定绿区的局"）
  —— 这是**采样偏差**：筛选条件本身就排除了形态 B。真实上机数据才把它暴露出来。
- 教训：**上机首测必须跑，且要按"全量局"而非"符合条件的局"统计**。

### 本日同时修复

`钓鱼-开始干跑.bat` / `钓鱼-开始按键.bat` 末尾缺 `pause` 导致双击后**窗口一闪而过**
（用户报"界面打不开"），已由 `make_launcher.py` 补 `if "%~1"=="" pause` 重新生成，自检 6 项全过。
