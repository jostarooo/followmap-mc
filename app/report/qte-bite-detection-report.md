# 咬钩检测：拆解 xplus-autofish，并给出 fishauto 可行的等价路线

日期：2026-10-15 · 触发：用户提示「可以参考我之前装的自动钓鱼 mod，里面的自动收杆功能有这项咬钩检测」

---

## 0. 为什么要做这件事

v0.2.0 之后我们的 QTE 触发只有一条来源：**读屏幕文本**（`Gui.title/subtitle` 里的「按下 X 开始」）。
它有已知弱点：

- 形态 B 局（20%）里 `key=unknown`，文本认不出；
- 实测「进度条帧可能比标题早到一 tick」，只能事后用 `key_upgrade` 补；
- 完全依赖中文文案，服务器改文案就失效。

而 xplus-autofish 用的是**物理信号**（浮标运动 / 水花声）。拆开它，看能不能拿过来。

---

## 1. 被拆的产物

| 项 | 值 |
|---|---|
| 文件 | `mods/[自动钓鱼XPlus版] xplus-autofish-1.0.0-fabric-1.20.4.jar` |
| 版本 | `1.0.0-fabric-1.20.4`，id `autofish`，作者 troyboy50 / Wudji（GitHub `Wudji/XPlus-AutoFish`） |
| 本实例状态 | `mods/` 里已改名 `.disabled`（为了不与 QTE 抢右键） |
| 用户配置 | `config/autofish.config`：`isAutofishEnabled:false`、**`useSoundDetection:false`** ⇒ 用户用的是**速度检测**那条路 |
| 工具 | `javap -p -c -constants`（JDK 21，`D:\dev\eclipse\jres\jdk-21.0.2`）；客户端 jar `versions\1.20.4-Fabric 0.16.14\1.20.4-Fabric 0.16.14.jar`（内含混淆名 `cfw` = `FishingHook`） |

---

## 2. 它的注入面（mixin）

`autofish.mixins.json` + `xplus-autofish-refmap.json` 写得很清楚，只有两个 mixin：

| mixin | 目标 | 说明 |
|---|---|---|
| `MixinClientPlayNetworkHandler` | `class_634.method_11132` = `onEntityVelocityUpdate(EntityVelocityUpdateS2CPacket)` | **速度包** |
| | `class_634.method_43596` = `onGameMessage(GameMessageS2CPacket)` | 只用于 ClearLag 正则，**不是咬钩检测** |
| | `class_634.method_11146` = `onPlaySound(PlaySoundS2CPacket)` | **水花声** |
| `MixinFishHookEntity` | `class_1536.method_6949` = `FishingHook.tickFishingLogic(BlockPos)` | 影子字段 `field_7173`（= `nibble`）与 `getHookedEntity()` |

⇒ **它是在网络层拦包**。这一点决定了 fishauto 不能照抄（我们没有任何 mixin / 不装钩子）。

---

## 3. 三条检测路径（反编译原文）

### 路径 1 —— 单机：`tickFishingLogic`
`FishingHook.tickFishingLogic` 注入后回调 `lambda$tickFishingLogic$1(int nibble, Entity hooked)`：

```
autofishEnabled && !shouldUseMPDetection()
  && player != null && player.fishing != null
  && nibble > 0
  && hooked.getUuid() == player.getUuid()
⇒ catchFish()
```

`shouldUseMPDetection()` 的判据是 `forceMPDetection || !client.isLocalServer()`。
**在真服务器上它恒为 true ⇒ 路径 1 在方块传说上根本不会执行。**

### 路径 2 —— 多人·速度（`FishMonitorMPMotion`）

```java
PACKET_MOTION_Y_THRESHOLD     = -350;   // 包内速度单位 = 1/8000 格每 tick ⇒ -0.04375 格/tick
START_CATCHING_AFTER_THRESHOLD = 1000;  // ms

hookTick():  浮标包围盒内若含 WATER 材质块 ⇒ hasHitWater = true
handlePacket(EntityVelocityUpdateS2CPacket p):
    if (p.entityId != player.fishing.getId()) return;
    if (hasHitWater && bobberRiseTimestamp == 0 && p.getVelocityY() > 0)
        bobberRiseTimestamp = now;                       // 记「抛入水后回弹」的时刻
    if (hasHitWater && bobberRiseTimestamp != 0
        && now - bobberRiseTimestamp > 1000
        && p.getVelocityX() == 0 && p.getVelocityZ() == 0
        && p.getVelocityY() < -350)
        catchFish();                                     // ← 咬钩
```

判据是「**纯竖直、向下、且幅度够大的一记**」——浮标被鱼拽下去的那一下。

### 路径 3 —— 多人·声音（`FishMonitorMPSound`）

```java
HOOKSOUND_DISTANCESQ_THRESHOLD = 25.0;   // 5 格

handlePacket:
    只接受 PlaySoundS2CPacket（PlaySoundFromEntityS2CPacket 直接 return）
    soundId == "minecraft:entity.fishing_bobber.splash"  (或去命名空间的同名)
    && player.fishing != null
    && player.fishing.squaredDistanceTo(x,y,z) < 25.0
    ⇒ catchFish()
```

顺带修掉一个容易记错的常量：**映射表里叫 `FISHING_BOBBER_SPLASH`**（`client-1.20.4.txt` 第 58040 行），不是 `FISHING_BOBBER_SPLASH` 之外的别的写法。

---

## 4. ★ 对我们真正有用的发现：有一条不需要 mixin 的等价信号 ★

上面三条路我们都用不了（要拦包）。但拆**客户端 jar** 时发现了一条反射可读的路。

### 4.1 证据一：客户端**只有** `biting` 是活的

`cfw.l()` = `FishingHook.tick()` 的字节码里，调用咬钩逻辑那一段：

```
540: aload_0
541: invokevirtual  dM()Lctp;        // this.level()
544: getfield       ctp.B:Z          // Level.isClientSide
547: ifne           573              // ← 客户端直接跳过
550: aload_0
551: aload_3
552: invokevirtual  a:(Lhx;)V        // catchingFish(BlockPos)
```

**`catchingFish()` 带 `isClientSide` 判断，只在服务端执行。**

⇒ 客户端**不会**维护 `nibble` / `timeUntilHooked` / `timeUntilLured` / `fishAngle` / `openWater`。
（`nibble` = `field_7173`，正是那个 mixin 影子字段 —— 它在多人游戏里客户端是死的，这也解释了为什么作者的多人路径完全不碰它。）

### 4.2 证据二：`biting` 是**同步字段**，客户端会收到

`cfw.a(agm<?>)` = `FishingHook.onSyncedDataUpdated(EntityDataAccessor<?>)`：

```
59-76:   if (accessor == DATA_BITING)                      // h
             this.biting = entityData.get(DATA_BITING);   // ← 写进字段 d
79-83:       if (this.biting)
86-117:          this.setDeltaMovement(
                     getDeltaMovement().x,
                     -0.4F * Mth.nextFloat(this.random, 0.6F, 1.0F),   // ← ldc_w -0.4f
                     getDeltaMovement().z);
```

并且 `defineSynchedData()` 里注册了 `DATA_HOOKED_ENTITY`(g) 与 **`DATA_BITING`(h)**。

⇒ **服务端一旦置位 `biting`，客户端字段 `FishingHook.biting` 就为 `true`**，同时客户端还会把自身 deltaMovement.y 设成 −0.24 … −0.40。

### 4.3 结论

> **每 tick 反射读一次 `player.fishing.biting`，就是一条不看文本、不受 QTE 形态影响、不需要 mixin 的咬钩信号。**

### 4.4 需要登记的映射名（已用 `mapbridge` 独立核对）

| 用途 | 官方名 | obf | intermediary |
|---|---|---|---|
| 浮标类 | `net.minecraft.world.entity.projectile.FishingHook` | `cfw` | `class_1536` |
| **咬钩标志** | `FishingHook.biting` (boolean) | `d` | **`field_23232`** |
| 浮标状态 | `FishingHook.currentState` (FishHookState) | `p` | `field_7175` |
| 勾中的实体 | `FishingHook.hookedIn` | `o` | 待补 |
| 速度读取 | `Entity.getDeltaMovement()` | — | `method_18798` |
| `Vec3.y` | `net.minecraft.world.phys.Vec3.y` | — | `field_1351` |
| 玩家浮标 | `Player.fishing` | — | `field_7513`（**fishauto 已登记**） |

`FishHookState` 三态：`FLYING` / `HOOKED_IN_ENTITY` / `BOBBING`（可用于「竿有没有抛出去」）。

> 顺带核对到了 `nibble` = `field_7173`（= mixin 影子字段），两条独立路径（javap 影子名 + mapbridge 官方名）互相对上，可作为映射链正确的又一例证。

---

## 5. 对 fishauto 的落地设计（零风险、默认不变）

**原则不变**：默认全关、只读、不抢输入。新增能力必须是**追加**且**显式开启**。

### 5.1 观测（先证伪，再实现）

即使 `biting` 在理论上可读，它由**原版服务端** `catchingFish` 驱动 —— 本服是 CustomFishing 插件自定义玩法，必须实测确认它没被旁路。

最小观测件（只记不决策）：

- 新增配置 `bite_log`（默认 `false`）。开启后每 tick 读 `player.fishing.biting` 与 `Δmotion.y`，在**边沿跳变**时写一行：

```json
{"type":"hook_bite","game":31,"t":...,"wall":...,"biting":true,"vy":-0.317,"lead_ms":null}
{"type":"hook_clear","game":31,"wall":...,"biting":false,"vy":0.0}
```

- 若 `hook_bite` 与 `qte_begin` 同时出现、且 `lead_ms` 稳定为负（早到）或 0 ⇒ 信号有效。
- 若整场钓下来**一条 `hook_bite` 都没有** ⇒ 服务端旁路了这个字段，此路作废，回到文本触发。

### 5.2 启用（观测通过后再做）

- 新增配置 `bite_source`：`"text"`（默认）| `"hook"`。
- `hook` 模式下：`biting` **上升沿**即 `begin(...)`，`trigger="hook"`，`reqKey` 先给 `unknown`，由既有的 **`key_upgrade`** 在标题到达时补认 —— 这条补认链路 v0.2.0 已经验证过，可复用，不需要新机制。

### 5.3 已知的「不做」

- **不**复刻声音路径（要拦 `PlaySoundS2CPacket`，非 mixin 不可得）。
- **不**复刻速度包路径（同上）。速度可以用 `getDeltaMovement()` 轮询近似，但客户端每 tick 会衰减，阈值要重标定 —— 只有 `biting` 失效时才值得做。

---

## 6. 复现命令

```bash
JDK=/d/dev/eclipse/jres/jdk-21.0.2/bin

# 1. 解包 mod
unzip -o -q "mods/[自动钓鱼XPlus版] xplus-autofish-1.0.0-fabric-1.20.4.jar" -d /tmp/xplug

# 2. 看注入面
cat /tmp/xplug/autofish.mixins.json /tmp/xplug/xplus-autofish-refmap.json

# 3. 读检测逻辑
$JDK/javap -p -c -constants -classpath /tmp/xplug troy.autofish.monitor.FishMonitorMPMotion
$JDK/javap -p -c -constants -classpath /tmp/xplug troy.autofish.monitor.FishMonitorMPSound

# 4. 读客户端 FishingHook（obf = cfw）
V="D:/config/game/mc/pcl2/.minecraft/versions/1.20.4-Fabric 0.16.14"
$JDK/javap -p -c -constants -classpath "$V/1.20.4-Fabric 0.16.14.jar" cfw

# 5. 核对映射名（本工程自带）
cd app && python -c "from mapbridge import Bridge; b=Bridge('1.20.4'); print(b.field('net.minecraft.world.entity.projectile.FishingHook','biting'))"
```

---

## 7. 待办 / 结论边界

- **【实测】** 三条检测路径的完整逻辑与阈值（反编译）。
- **【实测】** 客户端只有 `biting` / `hookedIn` 是活的，`nibble` 等只在服务端。
- **【实测】** 映射名 `field_23232` 等（mapbridge 独立核对）。
- **【推断 / 待实测】** 方块传说是否仍让原版浮标走完咬钩流程 ⇒ `biting` 是否真的会置位。**这是上线前必须证伪的一项**，方法见 5.1。
- **【已知】** 本服确实是 CustomFishing 插件（`logs/latest.log` 里 `customfishing:items/golden_fishing_rod` 等模型挂在 `minecraft:fishing_rod#inventory` 上 ⇒ 用的是**原版钓鱼竿 + CustomModelData**，不是替换物品）。
