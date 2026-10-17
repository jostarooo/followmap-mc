package fishauto;

import java.lang.reflect.Field;
import java.lang.reflect.Method;

/**
 * 按键注入 —— **只写原版 KeyMapping 的字段**，不碰 OS 键鼠。
 *
 * 原理（对应 MinecraftClient.handleInputEvents()）：
 * <pre>
 *   while (options.keyAttack.consumeClick()) doAttack();     // 左键：一次「点击」
 *   while (options.keyUse.consumeClick())    doItemUse();    // 右键：一次「使用」
 *   player.input.sneaking = options.keyShift.isDown();       // 左Shift：一个「按住」状态
 * </pre>
 * 所以：
 * <ul>
 *   <li>**clickCount 字段 +1** ⇒ 客户端下一 tick 走一次 doAttack / doItemUse，
 *       走完整原版流程（冷却、动画、序列号、发包）。</li>
 *   <li>**isDown 字段置 true** ⇒ 等于玩家把键按住；置回 false 等于松手。
 *       Shift 靠这条（服务器据客户端上报的潜行状态判定）。</li>
 * </ul>
 *
 * 与「用 SendInput 模拟鼠标」相比，这条路：
 * 不抢用户光标、不装全局钩子、不需要自己构造 PlayerActionC2SPacket（也就不会
 * 因为 1.20.4 的包格式/序列号写错而静默失效）。代价是按键会走玩家自己的按键绑定
 * （改动键位会跟着变），这正是我们想要的语义。
 */
final class Presser {
    private Presser() {
    }

    static boolean ready;
    static String error = "";
    private static final StringBuilder REPORT = new StringBuilder(1024);
    private static int attempts;
    private static long nextRetryAt;

    private static Method mGetInstance, mSetDown, mIsDown, mConsume;
    private static Method mMainHand, mItemGet, mItemKey, mCompStr;
    private static Field fPlayer, fLevel, fGui, fScreen, fOptions;
    private static Field fAttack, fUse, fShift, fJump;
    private static Field fDown, fClicks;
    private static Field fFishing, fItemReg;
    private static Field fTitle, fSubtitle, fOverlay;
    // ★ v0.2.1：咬钩信号（只读）★
    private static Method mDelta;
    private static Field fBiting, fVec3Y;

    /** uiText() 的通道号 */
    static final int UI_TITLE = 0;
    static final int UI_SUBTITLE = 1;
    static final int UI_ACTION = 2;

    private static Object mc;
    private static Object opts;
    private static Object kbAttack, kbUse, kbShift, kbJump;

    // 需要松手回位的键（按住类）
    private static Object heldKey;
    private static int holdLeft;
    /** 松开之后至少要保持「松开」几个 tick（否则游戏看到的是"一直按住"）。 */
    private static int restLeft;

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
            Class<?> cOpt = Class.forName(Names.C_OPTIONS);
            Class<?> cKb = Class.forName(Names.C_KEYBIND);
            Class<?> cPlayer = Class.forName(Names.C_PLAYER);
            Class<?> cStack = Class.forName(Names.C_ITEMSTACK);
            Class<?> cReg = Class.forName(Names.C_REGISTRY);
            Class<?> cBuiltin = Class.forName(Names.C_BUILTIN);

            mGetInstance = bind(cMC, "M_INSTANCE", Names.M_INSTANCE);
            fPlayer = fld(cMC, Names.F_PLAYER);
            fLevel = fld(cMC, Names.F_LEVEL);
            fGui = fld(cMC, Names.F_GUI);
            fScreen = fld(cMC, Names.F_SCREEN);
            fOptions = fld(cMC, Names.F_OPTIONS);

            fAttack = fld(cOpt, Names.F_KB_ATTACK);
            fUse = fld(cOpt, Names.F_KB_USE);
            fShift = fld(cOpt, Names.F_KB_SHIFT);
            fJump = fld(cOpt, Names.F_KB_JUMP);

            fDown = fld(cKb, Names.F_KB_DOWN);
            fClicks = fld(cKb, Names.F_KB_CLICKS);
            if (fDown.getType() != boolean.class) {
                throw new IllegalStateException("isDown 不是 boolean: " + fDown.getType());
            }
            if (fClicks.getType() != int.class) {
                throw new IllegalStateException("clickCount 不是 int: " + fClicks.getType());
            }

            mIsDown = bind(cKb, "M_IS_DOWN", Names.M_IS_DOWN);
            mSetDown = bind(cKb, "M_SET_DOWN", Names.M_SET_DOWN);
            mConsume = bind(cKb, "M_CONSUME", Names.M_CONSUME);

            // Title / 副标题 / 动作栏（QTE 信号来源）
            fTitle = fld(cGui, Names.F_TITLE);
            fSubtitle = fld(cGui, Names.F_SUBTITLE);
            fOverlay = fld(cGui, Names.F_OVERLAY_MSG);
            Class<?> cComp = Class.forName(Names.C_COMPONENT);
            mCompStr = bind(cComp, "M_COMPONENT_STR", Names.M_COMPONENT_STR);

            // 手持物 / 鱼漂（可选，缺了只是不能自动抛竿）
            try {
                fFishing = fld(cPlayer, Names.F_FISHING);
                Class<?> cLiving = Class.forName(Names.C_LIVING);
                mMainHand = bind(cLiving, "M_MAIN_HAND", Names.M_MAIN_HAND);
                mItemGet = bind(cStack, "M_ITEM_GET", Names.M_ITEM_GET);
                mItemKey = bind(cReg, "M_ITEM_KEY", Names.M_ITEM_KEY);
                fItemReg = fld(cBuiltin, Names.F_ITEM_REG);
                REPORT.append("[ok] 手持物 / 鱼漂可用\n");
            } catch (Throwable t) {
                REPORT.append("[--] 手持物 / 鱼漂不可用: ")
                        .append(t.getClass().getSimpleName()).append('\n');
                fFishing = null;
                mMainHand = null;
            }

            // ★ v0.2.1：咬钩信号（可选，缺了只是不能观测咬钩）★
            //   只读 player.fishing 上的两个值，**不注入任何东西**：
            //     biting    —— 服务端同步下来的 DATA_BITING（客户端是活的）
            //     Δmotion.y —— biting 置位那一 tick，客户端会把它设成 -0.24…-0.40
            try {
                Class<?> cHook = Class.forName(Names.C_FISH_HOOK);
                Class<?> cEntity = Class.forName(Names.C_ENTITY);
                Class<?> cVec3 = Class.forName(Names.C_VEC3);
                fBiting = fld(cHook, Names.F_BITING);
                if (fBiting.getType() != boolean.class) {
                    throw new IllegalStateException("biting 不是 boolean: " + fBiting.getType());
                }
                mDelta = bind(cEntity, "M_DELTA", Names.M_DELTA);
                fVec3Y = fld(cVec3, Names.F_VEC3_Y);
                REPORT.append("[ok] 咬钩信号（biting / Δy）可用\n");
            } catch (Throwable t) {
                REPORT.append("[--] 咬钩信号不可用: ")
                        .append(t.getClass().getSimpleName()).append('\n');
                fBiting = null;
                mDelta = null;
                fVec3Y = null;
            }

            ready = true;
            error = "";
            attempts = 0;
            Sink.status("OK  " + java.time.Instant.now() + "\n" + REPORT
                    + "绑定计数: " + count() + "\n");
        } catch (Throwable t) {
            error = t.getClass().getSimpleName() + ": " + t.getMessage();
            attempts++;
            nextRetryAt = now + (attempts >= 20 ? 600_000L : 2000L);
            Sink.status("FAIL(" + attempts + ")  " + java.time.Instant.now() + "\n"
                    + REPORT + "\n[ERROR] " + error + "\n");
        }
    }

    private static int count() {
        int n = 0;
        for (String s : new String[]{"mc", "opts", "attack", "use", "shift"}) {
            n++;
        }
        return n;
    }

    private static Method bind(Class<?> c, String label, String name) throws Exception {
        String want = null;
        for (String[] row : Names.SIGS) {
            if (row[0].equals(label)) {
                want = row[1];
            }
        }
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

    private static Field fld(Class<?> c, String name) throws Exception {
        Class<?> k = c;
        while (k != null) {
            try {
                Field f = k.getDeclaredField(name);
                f.setAccessible(true);
                REPORT.append("[ok] field ").append(name).append(" : ")
                        .append(f.getType().getSimpleName())
                        .append("  <- ").append(k.getName()).append('\n');
                return f;
            } catch (NoSuchFieldException e) {
                k = k.getSuperclass();
            }
        }
        throw new NoSuchFieldException(c.getName() + "." + name);
    }

    private static String desc(Method m) {
        StringBuilder sb = new StringBuilder(32).append('(');
        for (Class<?> p : m.getParameterTypes()) {
            sb.append(type(p));
        }
        return sb.append(')').append(type(m.getReturnType())).toString();
    }

    private static String type(Class<?> c) {
        if (c.isArray()) {
            return c.getName().replace('.', '/');
        }
        if (!c.isPrimitive()) {
            return "L" + c.getName().replace('.', '/') + ";";
        }
        switch (c.getName()) {
            case "void": return "V";
            case "boolean": return "Z";
            case "int": return "I";
            case "long": return "J";
            case "float": return "F";
            case "double": return "D";
            case "byte": return "B";
            case "char": return "C";
            case "short": return "S";
            default: return "?";
        }
    }

    // ------------------------------------------------------------------ 运行期
    /** 每 tick 先调它：刷新句柄，并把到期的「按住」松掉。 */
    static boolean attach() {
        if (!ready) {
            init();
        }
        if (!ready) {
            return false;
        }
        try {
            mc = mGetInstance.invoke(null);
            if (mc == null) {
                return false;
            }
            opts = fOptions.get(mc);
            if (opts == null) {
                return false;
            }
            kbAttack = fAttack.get(opts);
            kbUse = fUse.get(opts);
            kbShift = fShift.get(opts);
            kbJump = fJump.get(opts);
            return kbAttack != null && kbUse != null && kbShift != null;
        } catch (Throwable t) {
            return false;
        }
    }

    /**
     * 松手回位。返回 true 表示这一 tick 干了活。
     *
     * ★ 为什么要 restLeft ★
     *   原版只在每个 tick 读一次 {@code keyShift.isDown()}。如果我们在同一个 tick 里
     *   「松开 + 立刻再按下」，游戏看到的永远是「按住」——那就不是连点，而是长按。
     *   所以释放之后强制保持 1 个 tick 松开，确保游戏**真的**观察到一次「按 → 松」。
     */
    static boolean tickRelease() {
        if (holdLeft > 0) {
            holdLeft--;
            if (holdLeft == 0 && heldKey != null) {
                writeDown(heldKey, false);
                heldKey = null;
                restLeft = 1;
                return true;
            }
            return false;
        }
        if (restLeft > 0) {
            restLeft--;
        }
        return false;
    }

    /** 正在按住、或刚松开还在强制间隔 —— 此时不允许再发下一次「按住」。 */
    static boolean busy() {
        return holdLeft > 0 || restLeft > 0;
    }

    static int pressCount(Object kb) {
        try {
            return fClicks.getInt(kb);
        } catch (Throwable t) {
            return -1;
        }
    }

    static boolean isDown(Object kb) {
        try {
            return fDown.getBoolean(kb);
        } catch (Throwable t) {
            return false;
        }
    }

    /** 点一下（左键 / 右键）。 */
    static boolean tap(Object kb) {
        if (kb == null) {
            return false;
        }
        try {
            int c = fClicks.getInt(kb);
            fClicks.setInt(kb, c + 1);
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    /** 按住（Shift）。 */
    static boolean hold(Object kb, int ticks) {
        if (kb == null) {
            return false;
        }
        try {
            writeDown(kb, true);
            heldKey = kb;
            holdLeft = Math.max(1, ticks);
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    // ---- ★ v0.3.0：无限按住（开始 / 松手由调用方决定）----
    //   为什么需要：C 形态（底图判定色段）与"攒满进度条"类玩法要求**持续按住**，
    //   而 hold(kb, ticks) 是定长的（默认 2 tick，是给 Shift 短按设计的），
    //   表达不了"按住直到指针进判定区"。所以把"何时松手"外置给状态机。

    /** 开始按住（不自动松手，直到 {@link #holdStop()} 或 {@link #reset()}）。 */
    static boolean holdStart(Object kb) {
        if (kb == null) {
            return false;
        }
        try {
            writeDown(kb, true);
            heldKey = kb;
            holdLeft = Integer.MAX_VALUE / 2;    // 实际等于"不自动到期"
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    /** 松手（并强制下一个 tick 保持松开，确保游戏观察到一次真实的「按->松」）。 */
    static boolean holdStop() {
        if (heldKey == null) {
            return false;
        }
        writeDown(heldKey, false);
        heldKey = null;
        holdLeft = 0;
        restLeft = 1;
        return true;
    }

    /** 当前是否正处于「按住」状态。 */
    static boolean holding() {
        return heldKey != null;
    }

    private static void writeDown(Object kb, boolean v) {
        try {
            if (mSetDown != null) {
                mSetDown.invoke(kb, v);
            } else {
                fDown.setBoolean(kb, v);
            }
            // 双保险：有些版本 setDown 只改状态不写字段
            fDown.setBoolean(kb, v);
        } catch (Throwable ignored) {
            // 忽略
        }
    }

    static Object kbAttack() {
        return kbAttack;
    }

    static Object kbUse() {
        return kbUse;
    }

    static Object kbShift() {
        return kbShift;
    }

    static Object kbJump() {
        return kbJump;
    }

    static Object byName(String key) {
        switch (key == null ? "" : key) {
            case Qte.KEY_LEFT: return kbAttack;
            case Qte.KEY_RIGHT: return kbUse;
            case Qte.KEY_SHIFT: return kbShift;
            case Qte.KEY_JUMP: return kbJump;
            default: return null;
        }
    }

    // ---- 只读状态 ----
    static Object mc() {
        return mc;
    }

    static Object level() {
        try {
            return mc == null ? null : fLevel.get(mc);
        } catch (Throwable t) {
            return null;
        }
    }

    static Object player() {
        try {
            return mc == null ? null : fPlayer.get(mc);
        } catch (Throwable t) {
            return null;
        }
    }

    /** 有界面打开（聊天 / 背包 / Esc）时为 true —— 此时**绝不**按键。 */
    static boolean screenOpen() {
        try {
            return mc != null && fScreen.get(mc) != null;
        } catch (Throwable t) {
            return true;
        }
    }

    /** 客户端侧自己的鱼漂实体（= player.fishing）；null = 没抛竿。 */
    static Object hook() {
        if (fFishing == null) {
            return null;
        }
        try {
            Object p = player();
            return p == null ? null : fFishing.get(p);
        } catch (Throwable t) {
            return null;
        }
    }

    /** 客户端侧自己的鱼漂；null = 没抛竿。 */
    static boolean casted() {
        return hook() != null;
    }

    // ---- ★ v0.2.1：咬钩信号（全部只读；读不到一律安全退化，绝不影响主线）----

    /** 咬钩读取是否可用（绑定成功）。 */
    static boolean biteReady() {
        return fBiting != null;
    }

    /** 当前是否咬钩（服务端同步字段 `biting`）；读不到返回 false。 */
    static boolean hookBiting() {
        if (fBiting == null) {
            return false;
        }
        try {
            Object h = hook();
            return h != null && fBiting.getBoolean(h);
        } catch (Throwable t) {
            return false;
        }
    }

    /** 鱼漂当前 Δmotion.y；读不到返回 NaN（用来交叉验证 biting 是不是真的同步到了）。 */
    static double hookVy() {
        if (mDelta == null || fVec3Y == null) {
            return Double.NaN;
        }
        try {
            Object h = hook();
            if (h == null) {
                return Double.NaN;
            }
            Object v = mDelta.invoke(h);
            return v == null ? Double.NaN : fVec3Y.getDouble(v);
        } catch (Throwable t) {
            return Double.NaN;
        }
    }

    /** 主手物品 id（如 minecraft:fishing_rod），取不到返回 ""。 */
    static String mainHand() {
        if (mMainHand == null || mItemGet == null || mItemKey == null || fItemReg == null) {
            return "";
        }
        try {
            Object p = player();
            if (p == null) {
                return "";
            }
            Object stack = mMainHand.invoke(p);
            if (stack == null) {
                return "";
            }
            Object item = mItemGet.invoke(stack);
            if (item == null) {
                return "";
            }
            Object reg = fItemReg.get(null);
            if (reg == null) {
                return "";
            }
            Object rl = mItemKey.invoke(reg, item);
            return rl == null ? "" : rl.toString();
        } catch (Throwable t) {
            return "";
        }
    }

    /** 读 Title / 副标题 / 动作栏当前文本（QTE 的全部信号都从这三处来）。 */
    static String uiText(int which) {
        try {
            if (mc == null || fGui == null) {
                return "";
            }
            Object gui = fGui.get(mc);
            if (gui == null) {
                return "";
            }
            Field f = which == UI_TITLE ? fTitle : (which == UI_SUBTITLE ? fSubtitle : fOverlay);
            if (f == null) {
                return "";
            }
            Object comp = f.get(gui);
            if (comp == null) {
                return "";
            }
            Object s = mCompStr.invoke(comp);
            return s == null ? "" : (String) s;
        } catch (Throwable t) {
            return "";
        }
    }

    static void reset() {
        heldKey = null;
        holdLeft = 0;
        restLeft = 0;
    }
}
