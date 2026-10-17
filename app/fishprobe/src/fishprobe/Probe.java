package fishprobe;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * 探针主体：纯反射观察 Minecraft 客户端内存，把 BossBar / Title / ActionBar / 手持物
 * 写成事件流。
 *
 * **不链接任何 Minecraft 类** —— 全部走 {@link Names} 里的 intermediary 名 +
 * {@code Class.forName}，因此可以用 javac 直接编译（不需要 Gradle / Loom），
 * 也天然规避了"编译期映射与运行期不一致"的问题。
 *
 * 三条采集通道（对应方案文档的 A 通道）：
 * <ol>
 *   <li>**BossBar** —— 反射 {@code BossHealthOverlay.events}。这是本服务器承载自定义
 *       玩法数据的已验证通道（BlockLegend RPG API 同款做法）。</li>
 *   <li>**Title / ActionBar** —— 反射 {@code Gui.title/subtitle/overlayMessageString}。
 *       这两个字段是"当前显示中"的文本容器，逐 tick 读即可捕获瞬时提示。</li>
 *   <li>**状态快照** —— 手持物 / 副手 / 血量 / 经验等级。</li>
 * </ol>
 *
 * 采集策略：**只在内容变化时落盘**。BossBar 的 percent 逐 tick 变化（客户端插值），
 * 所以等价于 20Hz 采样；而静止的条不会产生垃圾行。
 */
public final class Probe {
    private Probe() {
    }

    static boolean ready;
    static String error = "";
    private static final StringBuilder REPORT = new StringBuilder(2048);
    private static int attempts;
    private static long nextRetryAt;

    // ---- 反射句柄 ----
    private static Method mGetInstance;
    private static Field fPlayer, fLevel, fGui;
    private static Method mGetBoss;
    private static Field fBossEvents, fBossRaw;
    private static Field fTitle, fSubtitle, fOverlayMsg;
    private static Method mBossName, mBossPct, mBossColor, mBossOverlay;
    private static Method mMainHand, mOffHand, mHealth;
    private static Field fXpLevel;
    private static Method mItemGet, mItemKey, mComponentStr;
    private static Object itemRegistry;

    // ---- 上一帧（变化检测）----
    private static final Map<String, String> BAR_STATE = new LinkedHashMap<>();
    /** null = 本会话还没读到过。首次只做初始化、不落盘，避免开局"空文本"噪音。 */
    private static String lastTitle;
    private static String lastSub;
    private static String lastAction;
    private static String lastState = "\u0000";
    private static long ticks;
    /** 是否已进入世界（决定会话文件的开关）。 */
    private static boolean inWorld;

    // ------------------------------------------------------------------ 解析
    static synchronized void init() {
        if (ready) {
            return;
        }
        long now = System.currentTimeMillis();
        if (now < nextRetryAt) {
            return;
        }
        REPORT.setLength(0);
        try {
            Class<?> cMC = Class.forName(Names.C_MC);
            Class<?> cGui = Class.forName(Names.C_GUI);
            Class<?> cOverlay = Class.forName(Names.C_BOSS_OVERLAY);
            Class<?> cBoss = Class.forName(Names.C_BOSS_EVENT);
            Class<?> cLiving = Class.forName(Names.C_LIVING);
            Class<?> cStack = Class.forName(Names.C_ITEMSTACK);
            Class<?> cRegistry = Class.forName(Names.C_REGISTRY);
            Class<?> cBuiltin = Class.forName(Names.C_BUILTIN_REGS);
            Class<?> cComponent = Class.forName(Names.C_COMPONENT);

            mGetInstance = bind(cMC, "M_INSTANCE", Names.M_INSTANCE);
            fPlayer = field(cMC, Names.F_PLAYER);
            fLevel = field(cMC, Names.F_LEVEL);
            fGui = field(cMC, Names.F_GUI);

            mGetBoss = bind(cGui, "M_GET_BOSS", Names.M_GET_BOSS);
            fBossEvents = field(cOverlay, Names.F_BOSS_EVENTS);

            mBossName = bind(cBoss, "M_BOSS_NAME", Names.M_BOSS_NAME);
            mBossPct = bind(cBoss, "M_BOSS_PERCENT", Names.M_BOSS_PERCENT);
            mMainHand = bind(cLiving, "M_MAIN_HAND", Names.M_MAIN_HAND);
            mOffHand = bind(cLiving, "M_OFF_HAND", Names.M_OFF_HAND);
            mHealth = bind(cLiving, "M_HEALTH", Names.M_HEALTH);
            mItemGet = bind(cStack, "M_ITEM_GET", Names.M_ITEM_GET);
            mItemKey = bind(cRegistry, "M_ITEM_KEY", Names.M_ITEM_KEY);
            mComponentStr = bind(cComponent, "M_COMPONENT_STR", Names.M_COMPONENT_STR);

            // ---- 以下为"锦上添花"项：缺了仍能采集，只在报告里写明 ----
            optional("M_BOSS_COLOR", () -> mBossColor = bind(cBoss, "M_BOSS_COLOR", Names.M_BOSS_COLOR));
            optional("M_BOSS_OVERLAY", () -> mBossOverlay = bind(cBoss, "M_BOSS_OVERLAY", Names.M_BOSS_OVERLAY));
            optional("F_BOSS_RAW", () -> fBossRaw = field(cBoss, Names.F_BOSS_RAW));
            optional("F_TITLE", () -> fTitle = field(cGui, Names.F_TITLE));
            optional("F_SUBTITLE", () -> fSubtitle = field(cGui, Names.F_SUBTITLE));
            optional("F_OVERLAY_MSG", () -> fOverlayMsg = field(cGui, Names.F_OVERLAY_MSG));
            optional("F_XP_LEVEL", () -> fXpLevel = field(cPlayerCls(), Names.F_XP_LEVEL));
            optional("F_ITEM_REG", () -> itemRegistry = field(cBuiltin, Names.F_ITEM_REG).get(null));

            ready = true;
            error = "";
            attempts = 0;
            Sink.status("OK  " + java.time.Instant.now() + "\n" + REPORT);
        } catch (Throwable t) {
            error = t.getClass().getSimpleName() + ": " + t.getMessage();
            attempts++;
            nextRetryAt = now + (attempts >= 20 ? 600_000L : 2000L);
            Sink.status("FAIL(" + attempts + ")  " + java.time.Instant.now() + "\n"
                    + REPORT + "\n[ERROR] " + error + "\n");
        }
    }

    private static Class<?> cPlayerCls() throws ClassNotFoundException {
        return Class.forName(Names.C_PLAYER);
    }

    /** 可选解析项：失败只在报告里留一行，不阻断整体。 */
    private static void optional(String label, ThrowingRunnable r) {
        try {
            r.run();
        } catch (Throwable t) {
            REPORT.append("[--] ").append(label).append(" 不可用: ")
                    .append(t.getClass().getSimpleName()).append('\n');
            if ("F_BOSS_RAW".equals(label)) {
                fBossRaw = null;
            } else if ("F_TITLE".equals(label)) {
                fTitle = null;
            } else if ("F_SUBTITLE".equals(label)) {
                fSubtitle = null;
            } else if ("F_OVERLAY_MSG".equals(label)) {
                fOverlayMsg = null;
            } else if ("F_XP_LEVEL".equals(label)) {
                fXpLevel = null;
            } else if ("F_ITEM_REG".equals(label)) {
                itemRegistry = null;
            } else if ("M_BOSS_COLOR".equals(label)) {
                mBossColor = null;
            } else if ("M_BOSS_OVERLAY".equals(label)) {
                mBossOverlay = null;
            }
        }
    }

    private interface ThrowingRunnable {
        void run() throws Exception;
    }

    /** 按 [label 的期望描述符] 精确匹配方法 —— 只按名字匹配会在混淆类里挑中同名重载。 */
    private static Method bind(Class<?> c, String label, String name) throws Exception {
        String want = want(label);
        for (Method m : c.getMethods()) {
            if (!m.getName().equals(name)) {
                continue;
            }
            String got = desc(m);
            if (want != null && !want.equals(got)) {
                continue;
            }
            m.setAccessible(true);
            REPORT.append("[ok] ").append(name).append(got)
                    .append("  <- ").append(m.getDeclaringClass().getName()).append('\n');
            return m;
        }
        throw new NoSuchMethodException(c.getName() + "." + name + " 期望 " + want);
    }

    private static String want(String label) {
        for (String[] row : Names.SIGS) {
            if (row[0].equals(label)) {
                return row[1];
            }
        }
        return null;
    }

    private static Field field(Class<?> c, String name) throws Exception {
        Class<?> k = c;
        while (k != null) {
            try {
                Field f = k.getDeclaredField(name);
                f.setAccessible(true);
                REPORT.append("[ok] field ").append(name)
                        .append("  <- ").append(k.getName()).append('\n');
                return f;
            } catch (NoSuchFieldException e) {
                k = k.getSuperclass();
            }
        }
        throw new NoSuchFieldException(c.getName() + "." + name);
    }

    private static String desc(Method m) {
        StringBuilder sb = new StringBuilder(48).append('(');
        for (Class<?> p : m.getParameterTypes()) {
            sb.append(type(p));
        }
        return sb.append(')').append(type(m.getReturnType())).toString();
    }

    private static String type(Class<?> c) {
        if (c.isArray()) {
            return c.getName().replace('.', '/');
        }
        if (c.isPrimitive()) {
            switch (c.getName()) {
                case "void": return "V";
                case "boolean": return "Z";
                case "byte": return "B";
                case "char": return "C";
                case "short": return "S";
                case "int": return "I";
                case "long": return "J";
                case "float": return "F";
                case "double": return "D";
                default: return "?";
            }
        }
        return "L" + c.getName().replace('.', '/') + ";";
    }

    // ------------------------------------------------------------------ 采集
    public static void reset() {
        BAR_STATE.clear();
        lastTitle = null;
        lastSub = null;
        lastAction = null;
        lastState = "\u0000";
    }

    public static void tick() {
        if (!ready) {
            init();
            if (!ready) {
                return;
            }
        }
        if (Sink.isOff()) {
            return;
        }
        ticks++;
        try {
            Object mc = mGetInstance.invoke(null);
            if (mc == null) {
                return;
            }
            Object level = fLevel.get(mc);
            if (level == null) {                 // 主菜单 / 加载中
                if (inWorld) {
                    inWorld = false;
                    Sink.close();                // 离开世界即收尾落盘
                }
                reset();
                return;
            }
            if (!inWorld) {                      // 进入世界 -> 开新会话文件
                inWorld = true;
                Sink.openSession("world");
                reset();
            }
            collectBars(mc);
            collectText(mc);
            if (ticks % 5 == 0) {
                snapshot(mc);
            }
        } catch (Throwable ignored) {
            // 探针绝不能把异常带进游戏主循环
        }
    }

    /** 通道 1：BossBar。服务器承载自定义玩法数据的主通道。 */
    private static void collectBars(Object mc) throws Exception {
        Object gui = fGui.get(mc);
        if (gui == null) {
            return;
        }
        Object overlay = mGetBoss.invoke(gui);
        if (overlay == null) {
            return;
        }
        Object raw = fBossEvents.get(overlay);
        if (!(raw instanceof Map)) {
            return;
        }
        Map<?, ?> map = (Map<?, ?>) raw;
        if (map.isEmpty()) {
            BAR_STATE.clear();
            return;
        }

        long w = Sink.wall();
        double n = Sink.nano();
        Set<String> seen = new HashSet<>();
        for (Map.Entry<?, ?> en : map.entrySet()) {
            Object bar = en.getValue();
            if (bar == null) {
                continue;
            }
            String uuid = String.valueOf(en.getKey());
            seen.add(uuid);

            String name = comp(mBossName.invoke(bar));
            String shown = f2s(asFloat(mBossPct.invoke(bar)));
            String rawVal = fBossRaw == null ? "null" : f2s(asFloat(fBossRaw.get(bar)));
            String color = mBossColor == null ? "" : enumName(mBossColor.invoke(bar));
            String ov = mBossOverlay == null ? "" : enumName(mBossOverlay.invoke(bar));

            String sig = name + '|' + shown + '|' + rawVal + '|' + color + '|' + ov;
            if (sig.equals(BAR_STATE.get(uuid))) {
                continue;
            }
            BAR_STATE.put(uuid, sig);

            Sink.line("{\"t\":" + Sink.num(n) + ",\"wall\":" + w
                    + ",\"type\":\"bossbar\",\"uuid\":\"" + Sink.esc(uuid)
                    + "\",\"name\":\"" + Sink.esc(name)
                    + "\",\"shown\":" + shown + ",\"raw\":" + rawVal
                    + ",\"color\":\"" + Sink.esc(color)
                    + "\",\"overlay\":\"" + Sink.esc(ov) + "\"}");
        }
        BAR_STATE.keySet().retainAll(seen);
    }

    /** 通道 2：Title / 副标题 / 动作栏。Gui 上的"当前显示中"文本容器。 */
    private static void collectText(Object mc) throws Exception {
        Object gui = fGui.get(mc);
        if (gui == null) {
            return;
        }
        String t = fTitle == null ? "" : comp(get(fTitle, gui));
        String s = fSubtitle == null ? "" : comp(get(fSubtitle, gui));
        String a = fOverlayMsg == null ? "" : comp(get(fOverlayMsg, gui));

        long w = Sink.wall();
        double n = Sink.nano();
        if (lastTitle == null) {
            lastTitle = t;                       // 首次仅初始化
        } else if (!t.equals(lastTitle)) {
            lastTitle = t;
            Sink.line("{\"t\":" + Sink.num(n) + ",\"wall\":" + w
                    + ",\"type\":\"title\",\"text\":\"" + Sink.esc(t) + "\"}");
        }
        if (lastSub == null) {
            lastSub = s;
        } else if (!s.equals(lastSub)) {
            lastSub = s;
            Sink.line("{\"t\":" + Sink.num(n) + ",\"wall\":" + w
                    + ",\"type\":\"subtitle\",\"text\":\"" + Sink.esc(s) + "\"}");
        }
        if (lastAction == null) {
            lastAction = a;
        } else if (!a.equals(lastAction)) {
            lastAction = a;
            Sink.line("{\"t\":" + Sink.num(n) + ",\"wall\":" + w
                    + ",\"type\":\"actionbar\",\"text\":\"" + Sink.esc(a) + "\"}");
        }
    }

    /** 通道 3：状态快照（每 5 tick，且只在变化时写）。 */
    private static void snapshot(Object mc) throws Exception {
        Object player = fPlayer.get(mc);
        if (player == null) {
            return;
        }
        String main = itemId(mMainHand.invoke(player));
        String off = itemId(mOffHand.invoke(player));
        String hp = f2s(asFloat(mHealth.invoke(player)));
        int xp = fXpLevel == null ? -1 : fXpLevel.getInt(player);

        String key = main + '|' + off + '|' + hp + '|' + xp;
        if (key.equals(lastState)) {
            return;
        }
        lastState = key;

        Sink.line("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + Sink.wall()
                + ",\"type\":\"state\",\"main\":\"" + Sink.esc(main)
                + "\",\"off\":\"" + Sink.esc(off)
                + "\",\"hp\":" + hp + ",\"xp\":" + xp + "}");
    }

    // ------------------------------------------------------------------ 工具
    private static Object get(Field f, Object o) {
        try {
            return f.get(o);
        } catch (Throwable t) {
            return null;
        }
    }

    private static String comp(Object component) {
        if (component == null) {
            return "";
        }
        try {
            Object s = mComponentStr.invoke(component);
            return s == null ? "" : (String) s;
        } catch (Throwable t) {
            return "";
        }
    }

    /** ItemStack -> "minecraft:fishing_rod"。探针只用它判断"手上拿的是不是鱼竿"。 */
    private static String itemId(Object stack) {
        if (stack == null || itemRegistry == null) {
            return "";
        }
        try {
            Object item = mItemGet.invoke(stack);
            if (item == null) {
                return "";
            }
            Object rl = mItemKey.invoke(itemRegistry, item);
            return rl == null ? "" : rl.toString();
        } catch (Throwable t) {
            return "";
        }
    }

    private static float asFloat(Object o) {
        return o instanceof Number ? ((Number) o).floatValue() : Float.NaN;
    }

    private static String f2s(float f) {
        return Float.isFinite(f) ? Float.toString(f) : "null";
    }

    private static String enumName(Object o) {
        return o instanceof Enum ? ((Enum<?>) o).name() : "";
    }
}
