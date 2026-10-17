# fishauto v0.3.0 任务笔记正文

## 做了什么

把 fishauto 从「半自动（只解 A 形态）」推到「全自动完成小游戏 + 外层钓鱼循环闭环」：

1. **外层循环 `loopTick()`**：`auto_cast` 自动抛竿 → 检测到咬钩（`biting` 上升沿）自动右键收杆（`reel_on_bite`，带 `reel_delay_ms` 与 `after_bite_ms` 记录）→ QTE 交给形态分流 → 结束后按 `cast_delay_ms` 冷却进入下一局。替代了之前不准确的「按节拍」（上鱼时间随机，重抛会重置）。
2. **C 形态（彩色长条）解码器**：`Geom.decodeC`/`inZoneC` + 底图色段表 `barSegs`。关键标定：
   - **对齐常数 246**：屏幕 x = (246 − 底图内容宽) + 图内坐标，即**底图内容右缘固定在 x=246**。之前的 256（贴 cell 右缘）系统性右偏，左对齐则彩虹条（内容宽 120）完全对不上。
   - **rainbow 是 7 段不是 6 段**：红/橙/黄/绿/浅蓝/深蓝/紫。浅蓝 RGB(52,242,213) 与深蓝 RGB(82,132,218) 必须先于「蓝」判断。
   - **c_margin=0**：20 局回放实测 0 最优（14/20 精确落段内），余量 2 掉到 6/20（窄段只有 5px，余量把触发点前移就压出界）。
3. **颜色题**：`Qte.colorAsk` 解析 title 里的「深蓝色!」等题面，`AutoFish` 开局读一次并锁定（title 中途会变）。
4. **C 形态按「右键」**：用户口径「右键收杆型：进度条跑到绿色立刻按右键收杆」，`hold_key` 默认 `right`。
5. **B 形态**：`form_skip`（本局首次遇到记一次，无指针无操作），`frame.tcp` 记 title 私有区码点备用。
6. **离线自检 136 项全过**（新增 `phaseLoop` 外层循环用例 + `phaseFormC` 形态分流用例），全量 `--all --pred` 通过，jar 已编译（30234B）。
7. **控制台**：`fishauto_ctl.py` 新增 `reel on|off` / `form observe|auto` / `loop` / `castdelay` / `reeldelay` / `cmargin` / `holdkey`，DEFAULT 同步 6 新键。
8. **手册升级 v0.3.0**：`D:\wbworkspace\方块传说-自动钓鱼fishauto-使用说明.md`。

## 踩坑（值得记）

- **qte_advance.json 的结构**：advance 在 `points` 键下，key 是**十进制码点字符串**（不是顶层码点键、不是十六进制）。
- **对齐模型三次翻转**：先按 A 形态结论定「贴 cell 右缘 256」→ C 局命中率 0~32% 推翻 → 量 PNG alpha 包围盒以为是「左对齐」→ 用 15 组 C 局末帧反解才定案 **246**。教训：**A/C 两类底图内容宽不同（184/120），只有按内容宽右对齐才能同时成立**。
- **指针末值 ≠ 按下瞬间**：游戏按键后还会演几帧，用「末帧」标定会系统性偏差；但玩家按键会截断帧序列，反解时取「最近色段距离 + 容差」扫描，tol=0 时 O=246 唯一最优（12/15）。
- **离线测试状态残留**：新增 `hardReset()`（`Harness.reset()` + `AutoFish.reset()`，后者从 private 改包私有）；且 Config 热加载挂在 `tick()` 里，`hardReset` 不 tick 就读不到新配置——测试要先 `tick(1,25)`。
- **mods 目录的 jar 被运行中的游戏进程锁住**：`mv` 探测确认，装机必须关游戏。

## 产物

- `app/fishauto/fishauto-0.3.0.jar`（30234B，已编译**待装**——游戏 PID 41156 还开着）
- `app/fishauto_ctl.py`（v0.3.0 命令集）
- `app/_probe_calign.py` / `_probe_fitO.py` / `_probe_replayC.py`（标定链，可复跑）
- 手册：`D:\wbworkspace\方块传说-自动钓鱼fishauto-使用说明.md`（v0.3.0）

## 待办（下轮）

1. **关游戏 → `build_fishprobe.py --root fishauto --instance 1204` 装机 → 重启游戏**
2. 实测顺序：`reel on`（看 `ctl loop` 的 after_bite_ms）→ `form auto`（看 C 命中率）→ 最后 `live`
3. C 形态 tap 丢鱼的话切 `Presser.holdStart/holdStop`（已备好未接入）
4. B 形态信号从 `frame.tcp` 里挖
