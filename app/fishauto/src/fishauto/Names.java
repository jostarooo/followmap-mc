package fishauto;

/**
 * fishauto 用到的全部 intermediary 名。
 *
 * ★ 推导来源与 fishprobe/Names.java 完全相同 ★
 *   Mojang 官方 client_mappings（named -> obf）+ Fabric intermediary（obf -> intermediary），
 *   由 `mapbridge.Bridge("1.20.4")` 确定性推导，逐项已核（见 app/mapbridge.py）。
 *
 * 1.20.1 与 1.20.4 的 intermediary 完全一致 ⇒ 同一 jar 两版通用。
 *
 * 为什么按键注入要落在 KeyMapping 上：
 *   原版在 MinecraftClient.handleInputEvents() 里用
 *       while (options.keyAttack.consumeClick()) doAttack();
 *       while (options.keyUse.consumeClick())    doItemUse();
 *       player.input.sneaking = options.keyShift.isDown();
 *   也就是说 —— **clickCount 字段 = 一次「点击」**，**isDown 字段 = 「按住」状态**。
 *   直接写这两个字段，等价于玩家按键：客户端照常执行 doAttack / doItemUse，
 *   照常走原版逻辑与发包（含 attack 冷却、use 冷却、动画、序列号）。
 *   这样我们**不碰 OS 层键鼠**（不抢用户鼠标、不装钩子），也不需要自己构造网络包。
 */
final class Names {
    private Names() {
    }

    // ---- 类 ----
    static final String C_MC = "net.minecraft.class_310";        // Minecraft
    static final String C_GUI = "net.minecraft.class_329";       // Gui
    static final String C_OPTIONS = "net.minecraft.class_315";   // Options
    static final String C_KEYBIND = "net.minecraft.class_304";   // KeyMapping
    static final String C_PLAYER = "net.minecraft.class_1657";   // Player
    static final String C_COMPONENT = "net.minecraft.class_2561"; // Component
    static final String C_LIVING = "net.minecraft.class_1309";   // LivingEntity
    static final String C_ITEMSTACK = "net.minecraft.class_1799"; // ItemStack
    static final String C_REGISTRY = "net.minecraft.class_2378"; // Registry
    static final String C_BUILTIN = "net.minecraft.class_7923";  // BuiltInRegistries
    // ★ v0.2.1：咬钩信号（只读，不注入）★
    static final String C_FISH_HOOK = "net.minecraft.class_1536"; // FishingHook
    static final String C_ENTITY = "net.minecraft.class_1297";    // Entity
    static final String C_VEC3 = "net.minecraft.class_243";       // Vec3

    // ---- 字段 ----
    static final String F_PLAYER = "field_1724";     // MC.player
    static final String F_LEVEL = "field_1687";      // MC.level
    static final String F_GUI = "field_1705";        // MC.gui
    static final String F_SCREEN = "field_1755";     // MC.screen（非 null = 有界面打开）
    static final String F_OPTIONS = "field_1690";    // MC.options
    static final String F_TITLE = "field_2016";      // Gui.title
    static final String F_SUBTITLE = "field_2039";   // Gui.subtitle
    static final String F_OVERLAY_MSG = "field_2018"; // Gui.overlayMessageString
    // Options 里的按键绑定
    static final String F_KB_ATTACK = "field_1886";  // Options.keyAttack
    static final String F_KB_USE = "field_1904";     // Options.keyUse
    static final String F_KB_SHIFT = "field_1832";   // Options.keyShift
    static final String F_KB_JUMP = "field_1903";    // Options.keyJump
    // KeyMapping 内部状态
    static final String F_KB_DOWN = "field_1653";    // KeyMapping.isDown      (boolean)
    static final String F_KB_CLICKS = "field_1661";  // KeyMapping.clickCount  (int)
    // 鱼漂（客户端侧只有自己那根）
    static final String F_FISHING = "field_7513";    // Player.fishing
    // ★ v0.2.1：咬钩信号 ★
    //   FishingHook.biting 是**同步字段**（DATA_BITING），服务端一置位客户端就有；
    //   而 nibble / timeUntilHooked 那些只在服务端跑（cfw.tick() 里被 isClientSide 挡住），
    //   客户端永远是死的 —— 详见 app/report/qte-bite-detection-report.md 第 4 节。
    static final String F_BITING = "field_23232";    // FishingHook.biting  (boolean)
    static final String F_VEC3_Y = "field_1351";     // Vec3.y             (double)

    // ---- 手持物 ----
    static final String F_ITEM_REG = "field_41178";  // BuiltInRegistries.ITEM

    // ---- 方法 ----
    static final String M_INSTANCE = "method_1551";  // Minecraft.getInstance()
    static final String M_IS_DOWN = "method_1434";   // KeyMapping.isDown()
    static final String M_SET_DOWN = "method_23481"; // KeyMapping.setDown(boolean)
    static final String M_CONSUME = "method_1436";   // KeyMapping.consumeClick()
    static final String M_MAIN_HAND = "method_6047"; // LivingEntity.getMainHandItem()
    static final String M_ITEM_GET = "method_7909";  // ItemStack.getItem()
    static final String M_ITEM_KEY = "method_10221"; // Registry.getKey(Object)
    static final String M_DELTA = "method_18798";    // Entity.getDeltaMovement() -> Vec3

    // ---- 不混淆成员（映射表里查不到，固定字符串）----
    static final String M_COMPONENT_STR = "getString";

    // ---- 期望描述符（运行期自检）----
    static final String[][] SIGS = {
        {"M_INSTANCE", "()Lnet/minecraft/class_310;"},
        {"M_IS_DOWN", "()Z"},
        {"M_SET_DOWN", "(Z)V"},
        {"M_CONSUME", "()Z"},
        {"M_MAIN_HAND", "()Lnet/minecraft/class_1799;"},
        {"M_ITEM_GET", "()Lnet/minecraft/class_1792;"},
        {"M_ITEM_KEY", "(Ljava/lang/Object;)Lnet/minecraft/class_2960;"},
        {"M_DELTA", "()Lnet/minecraft/class_243;"},
    };
}
