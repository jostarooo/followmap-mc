package net.minecraft;

/**
 * 桩类的**公开门面**（给 fishauto 包的测试用）。
 *
 * 为什么要单独一个文件：桩类型全部是**包私有**（与真实 MC 一致 —— class_310 之类
 * 本来就不是 public 的对外 API），所以 `fishauto` 包里的 AutoTest 只能通过这个
 * public 门面来搭场景、读结果。
 *
 * 与 Stubs.java 同包（net.minecraft），因此能直接操作那些包私有桩类。
 */
public final class Harness {
    private Harness() {
    }

    private static class_310 mc;
    private static class_329 gui;
    private static class_1657 player;
    private static Object level = new Object();

    /** 建好一套干净场景：有世界、有玩家（手持鱼竿）、有 Gui、没有界面打开。 */
    public static void reset() {
        mc = new class_310();
        gui = new class_329();
        player = new class_1657();
        mc.field_1705 = gui;
        mc.field_1724 = player;
        mc.field_1687 = level;
        mc.field_1755 = null;
        class_310._set(mc);
        setHolding("minecraft:fishing_rod");
        setCasted(false);
    }

    public static void setWorldPresent(boolean present) {
        mc.field_1687 = present ? level : null;
    }

    public static void setTitle(String s) {
        gui.setTitle(s);
    }

    public static void setSubtitle(String s) {
        gui.setSubtitle(s);
    }

    public static void setAction(String s) {
        gui.setAction(s);
    }

    /** 模拟「有界面打开」（聊天 / 背包 / Esc）。 */
    public static void setScreenOpen(boolean open) {
        mc.field_1755 = open ? new Object() : null;
    }

    public static void setHolding(String itemId) {
        player.mainHand = new class_1799(new class_1792(itemId));
    }

    public static void setCasted(boolean casted) {
        player.field_7513 = casted ? new class_1536() : null;
    }

    // ---- ★ v0.2.1：咬钩信号（模拟服务端把 DATABITING 同步下来）----

    /** 设置当前是否咬钩（= 服务端 DATA_BITING）。没抛竿时静默忽略。 */
    public static void setBiting(boolean b) {
        if (player.field_7513 instanceof class_1536) {
            ((class_1536) player.field_7513).field_23232 = b;
        }
    }

    /** 设置鱼漂 Δmotion.y（咬钩那一下真实值约 -0.24…-0.40）。 */
    public static void setHookVy(double y) {
        if (player.field_7513 instanceof class_1536) {
            ((class_1536) player.field_7513).delta.field_1351 = y;
        }
    }

    /** 读回咬钩标志（验证反射管道真的接到了桩字段上）。 */
    public static boolean biting() {
        return player.field_7513 instanceof class_1536
                && ((class_1536) player.field_7513).field_23232;
    }

    // ---- 读按键注入结果 ----
    public static int attackClicks() {
        return mc.field_1690.field_1886.field_1661;
    }

    public static int useClicks() {
        return mc.field_1690.field_1904.field_1661;
    }

    public static boolean shiftDown() {
        return mc.field_1690.field_1832.field_1653;
    }

    public static int shiftClicks() {
        return mc.field_1690.field_1832.field_1661;
    }

    /** 模拟原版管线：把 clickCount 消费掉（验证「写 1 = 按一次」确实成立）。 */
    public static boolean consumeAttack() {
        return mc.field_1690.field_1886.method_1436();
    }

    public static boolean consumeUse() {
        return mc.field_1690.field_1904.method_1436();
    }
}
