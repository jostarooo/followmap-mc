package net.minecraft;

import java.util.HashMap;
import java.util.Map;

/**
 * **fishauto 离线验证用桩类集** —— 类名/字段名/方法名/**描述符**必须与
 * mapbridge 推导出的 intermediary 名逐字一致，否则 Presser 的描述符自检会（正确地）报错。
 *
 * 存在的意义：反射访问 MC 时**映射写错不会抛异常，只会静默不干活**
 * （本项目已踩过：一个描述符不匹配导致整条链路无声失效）。
 * 所以必须有一份同名桩，在离线把「解析 -> 读文本 -> 判定 -> 写 KeyMapping 字段」跑通。
 *
 * 桩里刻意模拟两件真实行为：
 *   1. {@code method_1436() consumeClick} 会把 clickCount 减 1 并返回是否真的消费到 ——
 *      这样「写 clickCount = 1 等于按一次」这件事是被真验证过的；
 *   2. {@code method_23481(Z) setDown} 只改字段，和原版一致。
 */

/** 占位外部类：本文件其余类都是包私有，靠它撑住文件名。 */
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
    private final String id;

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
    public static class_2378 field_41178 = o -> new class_2960(String.valueOf(o));
}

interface class_2561 {
    /** Component.getString() —— 真实里不混淆，名字就是 getString */
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

// ------------------------------------------------------------------ KeyMapping / Options

class class_304 {
    /** KeyMapping.isDown */
    public boolean field_1653;
    /** KeyMapping.clickCount */
    public int field_1661;
    /** KeyMapping.key（本测试不用，仅占位说明真实结构里有它） */
    public Object field_1655;

    /** KeyMapping.isDown() */
    public boolean method_1434() {
        return field_1653;
    }

    /** KeyMapping.setDown(boolean) */
    public void method_23481(boolean down) {
        field_1653 = down;
    }

    /** KeyMapping.consumeClick() —— 真逻辑：有计数就消费一次 */
    public boolean method_1436() {
        if (field_1661 == 0) {
            return false;
        }
        field_1661--;
        return true;
    }
}

class class_315 {
    /** Options.keyAttack / keyUse / keyShift / keyJump */
    public class_304 field_1886 = new class_304();
    public class_304 field_1904 = new class_304();
    public class_304 field_1832 = new class_304();
    public class_304 field_1903 = new class_304();
}

// ------------------------------------------------------------------ Gui / Player / Minecraft

class class_329 {
    /** Gui.title / subtitle / overlayMessageString */
    public class_2561 field_2016;
    public class_2561 field_2039;
    public class_2561 field_2018;

    public void setTitle(String s) {
        field_2016 = s == null ? null : new Text(s);
    }

    public void setSubtitle(String s) {
        field_2039 = s == null ? null : new Text(s);
    }

    public void setAction(String s) {
        field_2018 = s == null ? null : new Text(s);
    }
}

class class_1309 {
    public class_1799 mainHand;

    /** getMainHandItem() */
    public class_1799 method_6047() {
        return mainHand;
    }
}

class class_1657 extends class_1309 {
    /** Player.fishing —— 客户端侧自己的鱼漂 */
    public Object field_7513;
}

// ------------------------------------------------- ★ v0.2.1：咬钩信号（只读）★
//
// 真实里 class_1536(FishingHook) extends class_1297(Entity)，biting 是**同步字段**
// （DATA_BITING）—— 服务端一置位，客户端这个 boolean 就为 true。
// 桩里把它做平：只要字段名/类型/描述符一致，「反射能否读到」这件事就被真验证了。

class class_243 {
    /** Vec3.y */
    public double field_1351;
    /** Vec3.z */
    public double field_1350;

    class_243(double x, double y, double z) {
        this.field_1351 = y;
    }
}

class class_1297 {
    /** 当前速度（真实里每 tick 衰减；桩里由测试直接设） */
    public class_243 delta = new class_243(0, 0, 0);

    /** Entity.getDeltaMovement() */
    public class_243 method_18798() {
        return delta;
    }
}

class class_1536 extends class_1297 {
    /** FishingHook.biting —— 服务端同步下来的咬钩标志 */
    public boolean field_23232;
}

class class_310 {
    private static class_310 instance;

    /** Minecraft.player / gui / level / screen / options */
    public Object field_1724;
    public Object field_1705;
    public Object field_1687;
    public Object field_1755;
    public class_315 field_1690 = new class_315();

    /** Minecraft.getInstance() */
    public static class_310 method_1551() {
        return instance;
    }

    public static void _set(class_310 m) {
        instance = m;
    }
}
