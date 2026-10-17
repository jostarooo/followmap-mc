package net.minecraft;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * **离线验证用桩类集**（只为在没装游戏的情况下真跑一遍 fishprobe 的反射链路）。
 *
 * 约束：类名 / 字段名 / 方法名 / **描述符** 必须与 fishmap.py 从映射推导出的
 * intermediary 名逐字一致 —— 否则 Probe 的描述符自检会（正确地）报错。
 * 这正是这套桩存在的意义：把「映射写错」这类静默故障在离线阶段就逼出来。
 *
 * ★ 命名坑（对齐真实 MC 1.20.1）★
 * - 进度方法叫 {@code method_5412}（getProgress），字段是 {@code field_5774}。
 * - 真实里 events 存的是 LerpingBossEvent，它的 getProgress() 返回**插值后**的值，
 *   而 field_5774 是服务器下发的原始值。桩里用两个字段模拟这个差异，
 *   以便验证 Probe 确实分别读到了 shown / raw 两条数据。
 */

/** 占位外部类：本文件里其余类都是包私有，靠它撑住文件名。 */
public final class Stubs {
    private Stubs() {
    }
}

// ------------------------------------------------------------------ 基础类型

class class_2960 {
    private final String id;

    class_2960(String id) {
        this.id = id;
    }

    @Override
    public String toString() {
        return id;
    }
}

class class_1792 {
    final String id;

    class_1792(String id) {
        this.id = id;
    }

    @Override
    public String toString() {
        return id;
    }
}

class class_1799 {
    private final class_1792 item;

    class_1799(class_1792 item) {
        this.item = item;
    }

    /** getItem() */
    public class_1792 method_7909() {
        return item;
    }
}

interface class_2378 {
    /** getKey(Object) -> ResourceLocation */
    class_2960 method_10221(Object o);
}

class class_7923 {
    /** BuiltInRegistries.ITEM */
    public static class_2378 field_41178;
}

interface class_2561 {
    /** Component.getString() —— 注意：真实里它不混淆，名字就是 getString */
    default String getString() {
        return "";
    }
}

class Text implements class_2561 {
    private final String s;

    Text(String s) {
        this.s = s;
    }

    @Override
    public String getString() {
        return s;
    }

    @Override
    public String toString() {
        return s;
    }
}

// ------------------------------------------------------------------ BossBar

class class_1259 {
    /** BossEvent.progress —— 服务器下发的**原始**值 */
    public float field_5774;

    /** 模拟 LerpingBossEvent 的插值结果（getProgress() 实际返回的东西） */
    public float shownLerp;

    private final UUID uuid = UUID.randomUUID();
    private class_2561 nameText = new Text("");

    public void setName(String s) {
        this.nameText = new Text(s);
    }

    /** getId() */
    public UUID method_5407() {
        return uuid;
    }

    /** getName() */
    public class_2561 method_5414() {
        return nameText;
    }

    /** getProgress() —— 桩里返回"插值值"，与 field_5774 故意不同 */
    public float method_5412() {
        return shownLerp;
    }

    /** getColor() */
    public class_1260 method_5420() {
        return class_1260.GREEN;
    }

    /** getOverlay() */
    public class_1261 method_5415() {
        return class_1261.PROGRESS;
    }

    enum class_1260 { PINK, BLUE, RED, GREEN, YELLOW, PURPLE, WHITE }

    enum class_1261 { PROGRESS, NOTCHED_6, NOTCHED_10, NOTCHED_12, NOTCHED_20 }
}

class class_337 {
    /** BossHealthOverlay.events */
    public Map<UUID, class_1259> field_2060 = new HashMap<>();
}

// ------------------------------------------------------------------ Gui

class class_329 {
    /** Gui.title */
    public class_2561 field_2016;
    /** Gui.subtitle */
    public class_2561 field_2039;
    /** Gui.overlayMessageString */
    public class_2561 field_2018;

    private final class_337 bossOverlay = new class_337();

    /** Gui.getBossOverlay() */
    public class_337 method_1740() {
        return bossOverlay;
    }

    public void setTitle(String s) {
        field_2016 = s == null ? null : new Text(s);
    }

    public void setActionBar(String s) {
        field_2018 = s == null ? null : new Text(s);
    }
}

// ------------------------------------------------------------------ 玩家

class class_1309 {
    public class_1799 mainHand;
    public class_1799 offHand;
    public float health = 20f;

    /** getMainHandItem() */
    public class_1799 method_6047() {
        return mainHand;
    }

    /** getOffhandItem() */
    public class_1799 method_6079() {
        return offHand;
    }

    /** getHealth() */
    public float method_6032() {
        return health;
    }
}

class class_1657 extends class_1309 {
    /** Player.experienceLevel */
    public int field_7520;
}

class class_746 extends class_1657 {
}

// ------------------------------------------------------------------ Minecraft

class class_310 {
    private static class_310 instance;

    /** Minecraft.player */
    public Object field_1724;
    /** Minecraft.gui */
    public Object field_1705;
    /** Minecraft.level */
    public Object field_1687;

    /** Minecraft.getInstance() */
    public static class_310 method_1551() {
        return instance;
    }

    public static void _set(class_310 m) {
        instance = m;
    }
}
