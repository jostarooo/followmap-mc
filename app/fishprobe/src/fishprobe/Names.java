package fishprobe;

/**
 * 全部 intermediary 名 —— fishprobe 探针（纯反射，不链接任何 MC 类）的根基。
 *
 * ★ 本文件由 `python fishmap.py --write` 生成，不要手改 ★
 *   改完请跑 `python fishmap.py --check` 逐字核对。
 *
 * 推导链：Mojang 官方映射 client-1.20.4.txt（named -> obf）
 *       + Fabric intermediary-1.20.4.jar 的 mappings/mappings.tiny（obf -> intermediary）
 *       两者按 obf 名对接。见同目录 mapbridge.py。
 *
 * 与 coordbridge 的 Names.java 是**两套独立目标表**（那套是区块直读，这套是
 * BossBar / Title / 手持物观察），共用同一个 mapbridge.py 推导器。
 *
 * ★ 版本事实（2026-10-14 逐条实测，别再照抄资料猜）★
 * 1. `BossEvent` 在 **net.minecraft.world**，1.20.1 到 1.20.5 **一直没搬**（intermediary 恒为
 *    class_1259）。早先这里记的「1.20.2+ 搬到 client.gui.components」是**错的**——
 *    那是它的**容器** BossHealthOverlay，那个本来就一直在 client.gui.components。
 * 2. 进度方法叫 **getProgress()**（1.20.1 与 1.20.4 一致，未改名）。
 * 3. 1.20.4 的 BossEvent **没有 getStyle()**。
 * 4. `Component.getString()` **不经过混淆**（它实现了 brigadier 的 Message#getString），
 *    intermediary 里查不到它 —— 直接写死 "getString"，见固定表。
 * 5. ★ **1.20.1 与 1.20.4 的 intermediary 名完全一致**：Fabric 为这两个版本生成的
 *    mappings.tiny 逐字节相同（CLASS 段各 7764 行全等）。因此本文件两版通用，
 *    同一个 jar 可同时装进两个客户端；换版本只需 `python fishmap.py --mc <版本>`。
 */
final class Names {
    private Names() {
    }

    // ---- 类（intermediary，运行期 Class.forName 的目标）----
    static final String C_MC = "net.minecraft.class_310";
    static final String C_GUI = "net.minecraft.class_329";
    static final String C_BOSS_OVERLAY = "net.minecraft.class_337";
    static final String C_BOSS_EVENT = "net.minecraft.class_1259";
    static final String C_COMPONENT = "net.minecraft.class_2561";
    static final String C_LIVING = "net.minecraft.class_1309";
    static final String C_PLAYER = "net.minecraft.class_1657";
    static final String C_LOCAL_PLAYER = "net.minecraft.class_746";
    static final String C_ITEMSTACK = "net.minecraft.class_1799";
    static final String C_ITEM = "net.minecraft.class_1792";
    static final String C_BUILTIN_REGS = "net.minecraft.class_7923";
    static final String C_REGISTRY = "net.minecraft.class_2378";
    static final String C_RESLOC = "net.minecraft.class_2960";
    static final String C_ENTITY = "net.minecraft.class_1297";
    static final String C_LEVEL = "net.minecraft.class_1937";
    static final String C_SERVERDATA = "net.minecraft.class_642";

    // ---- 字段 ----
    static final String F_PLAYER = "field_1724";
    static final String F_GUI = "field_1705";
    static final String F_LEVEL = "field_1687";
    static final String F_BOSS_EVENTS = "field_2060";
    static final String F_BOSS_RAW = "field_5774";
    static final String F_OVERLAY_MSG = "field_2018";
    static final String F_TITLE = "field_2016";
    static final String F_SUBTITLE = "field_2039";
    static final String F_OVERLAY_T = "field_2041";
    static final String F_TITLE_T = "field_2023";
    static final String F_XP_LEVEL = "field_7520";
    static final String F_XP_PROG = "field_7510";
    static final String F_DIM = "field_25176";
    static final String F_ITEM_REG = "field_41178";
    static final String F_SRV_IP = "field_3761";

    // ---- 方法 ----
    static final String M_INSTANCE = "method_1551";
    static final String M_GET_BOSS = "method_1740";
    static final String M_BOSS_NAME = "method_5414";
    static final String M_BOSS_PERCENT = "method_5412";
    static final String M_BOSS_COLOR = "method_5420";
    static final String M_BOSS_OVERLAY = "method_5415";
    static final String M_BOSS_ID = "method_5407";
    static final String M_BOSS_DARKEN = "method_5417";
    static final String M_BOSS_MUSIC = "method_5418";
    static final String M_BOSS_FOG = "method_5419";
    static final String M_MAIN_HAND = "method_6047";
    static final String M_OFF_HAND = "method_6079";
    static final String M_HEALTH = "method_6032";
    static final String M_MAX_HEALTH = "method_6063";
    static final String M_ITEM_GET = "method_7909";
    static final String M_ITEM_COUNT = "method_7947";
    static final String M_ITEM_NAME = "method_7964";
    static final String M_ITEM_EMPTY = "method_7960";
    static final String M_GET_X = "method_23317";
    static final String M_GET_Y = "method_23318";
    static final String M_GET_Z = "method_23321";
    static final String M_ITEM_KEY = "method_10221";
    // ---- 不混淆成员（固定名，映射表里查不到）----
    static final String M_COMPONENT_STR = "getString";

    // ---- 预期描述符（运行期自检用）----
    static final String[][] SIGS = {
        {"M_INSTANCE", "()Lnet/minecraft/class_310;"},
        {"M_GET_BOSS", "()Lnet/minecraft/class_337;"},
        {"M_BOSS_NAME", "()Lnet/minecraft/class_2561;"},
        {"M_BOSS_PERCENT", "()F"},
        {"M_BOSS_COLOR", "()Lnet/minecraft/class_1259$class_1260;"},
        {"M_BOSS_OVERLAY", "()Lnet/minecraft/class_1259$class_1261;"},
        {"M_BOSS_ID", "()Ljava/util/UUID;"},
        {"M_BOSS_DARKEN", "()Z"},
        {"M_BOSS_MUSIC", "()Z"},
        {"M_BOSS_FOG", "()Z"},
        {"M_MAIN_HAND", "()Lnet/minecraft/class_1799;"},
        {"M_OFF_HAND", "()Lnet/minecraft/class_1799;"},
        {"M_HEALTH", "()F"},
        {"M_MAX_HEALTH", "()F"},
        {"M_ITEM_GET", "()Lnet/minecraft/class_1792;"},
        {"M_ITEM_COUNT", "()I"},
        {"M_ITEM_NAME", "()Lnet/minecraft/class_2561;"},
        {"M_ITEM_EMPTY", "()Z"},
        {"M_GET_X", "()D"},
        {"M_GET_Y", "()D"},
        {"M_GET_Z", "()D"},
        {"M_ITEM_KEY", "(Ljava/lang/Object;)Lnet/minecraft/class_2960;"},
    };
}
