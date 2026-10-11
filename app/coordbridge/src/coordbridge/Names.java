package coordbridge;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 全部 intermediary 名，由 app/modmap.py 从
 *   Mojang 官方映射 cache/mappings/client-<版本>.txt
 * + Fabric intermediary-<版本>.jar (mappings/mappings.tiny)
 * 确定性推导得出（官方名 -> obf -> intermediary）。
 *
 * 不要手改任何字符串：改完请跑
 *     python modmap.py                              # 打印对照表
 *     python modmap.py --check                      # 逐字核对本文件（含描述符表）
 *     python modmap.py --check --mc 1.20.1          # 按 1.20.1 核对
 *     python modmap.py --compare 1.20.1 1.20.4      # 两版本差异
 *
 * ★ 踩过的坑（务必保留这条注释）★
 * 早期的解析只按「类 + 方法名」匹配，忽略描述符。obf 名会被压成 a/b/c…，
 * 一个类里往往有 5~6 个同名重载，于是 getBlockState(int,int,int) 被解析成了
 * 同名的 ()V 方法 —— 反射在运行时直接抛 NoSuchMethod，整条取方块链路报废，
 * 但**游戏不报错、mod 只是静默地什么都不写**，表现为「外部地图一直跟不上」。
 * 现在解析走「完整描述符精确匹配」，并且本文件附 SIG 表在运行时二次校验：
 * 解析到的 Method 如果描述符对不上，status.txt 会直接写明，不再静默失效。
 *
 * 用途链路（内存直读区块）：
 *   Minecraft.level -> ClientLevel.getChunkSource() -> ClientChunkCache.storage
 *     -> Storage.chunks (AtomicReferenceArray) -> LevelChunk
 *     -> ChunkAccess.getSections() -> LevelChunkSection
 *     -> LevelChunkSection.getBlockState(x,y,z) -> BlockState
 *     -> BlockStateBase.getBlock() -> BuiltInRegistries.BLOCK.getKey(block) -> ResourceLocation
 *
 * ★ 版本范围：Minecraft 1.20.1 ~ 1.20.4（Fabric）★
 * 这 20 类 / 9 字段 / 17 方法 / 17 描述符在上述版本间**逐字相同**（实测：
 * `python modmap.py --compare 1.20.1 1.20.4` 报「63 项完全一致」），
 * 所以**同一个 jar 通吃这几个版本**，不必按 MC 版本分别构建。
 * 上界卡在 <1.20.5：1.20.5 的这 63 项虽然也相同，但那次是注册表大改版
 * （BuiltInRegistries -> Registries），行为没在真机验过，不擅自宣称支持。
 * 要支持更远的版本：python modmap.py --fetch <版本>，再 --compare 一次。
 */
final class Names {
    private Names() {
    }

    // ---------------------------------------------------------------- 类
    static final String C_MC = "net.minecraft.class_310";
    static final String C_CLIENT_LEVEL = "net.minecraft.class_638";
    static final String C_CHUNK_CACHE = "net.minecraft.class_631";
    static final String C_STORAGE = "net.minecraft.class_631$class_3681";
    static final String C_CHUNK = "net.minecraft.class_2818";
    static final String C_CHUNK_ACCESS = "net.minecraft.class_2791";
    static final String C_SECTION = "net.minecraft.class_2826";
    static final String C_BLOCK_STATE = "net.minecraft.class_2680";
    static final String C_BLOCK_ST_BASE = "net.minecraft.class_4970$class_4971";
    static final String C_BLOCK = "net.minecraft.class_2248";
    static final String C_BUILTIN_REGS = "net.minecraft.class_7923";
    static final String C_REGISTRY = "net.minecraft.class_2378";
    static final String C_CHUNK_POS = "net.minecraft.class_1923";
    static final String C_HEIGHT_ACC = "net.minecraft.class_5539";
    static final String C_HEIGHTMAP = "net.minecraft.class_2902$class_2903";
    static final String C_RESLOC = "net.minecraft.class_2960";
    static final String C_LEVEL = "net.minecraft.class_1937";
    static final String C_ENTITY = "net.minecraft.class_1297";
    static final String C_REGKEY = "net.minecraft.class_5321";
    static final String C_SERVERDATA = "net.minecraft.class_642";

    // ---------------------------------------------------------------- 字段
    static final String F_LEVEL = "field_1687";
    static final String F_PLAYER = "field_1724";
    static final String F_STORAGE = "field_16246";
    static final String F_CHUNKS = "field_16251";
    static final String F_BLOCK_REG = "field_41175";
    static final String F_CPOS_X = "field_9181";
    static final String F_CPOS_Z = "field_9180";
    static final String F_DIM = "field_25176";
    static final String F_SRV_IP = "field_3761";

    // ---------------------------------------------------------------- 方法
    static final String M_INSTANCE = "method_1551";
    static final String M_SERVER = "method_1558";
    static final String M_GET_X = "method_23317";
    static final String M_GET_Y = "method_23318";
    static final String M_GET_Z = "method_23321";
    static final String M_LOCATION = "method_29177";
    static final String M_CHUNK_SRC = "method_2935";
    static final String M_SECTIONS = "method_12006";
    static final String M_CHUNK_POS = "method_12004";
    /** ChunkAccess.getHeight(Heightmap$Types, int, int) —— 每列 1 次拿地表高度。 */
    static final String M_GET_HEIGHT = "method_12005";
    static final String M_IS_EMPTY = "method_12223";
    static final String M_MIN_SECT = "method_32891";
    static final String M_SECT_CNT = "method_32890";
    static final String M_ONLY_AIR = "method_38292";
    /** LevelChunkSection.getBlockState(int,int,int) -> BlockState（注意有 6 个同名重载）。 */
    static final String M_SEC_BLOCK = "method_12254";
    static final String M_STATE_BLK = "method_26204";
    /** Registry.getKey(Object) -> ResourceLocation（由 Object 继承，参数是擦除后的 Object）。 */
    static final String M_REG_KEY = "method_10221";

    /**
     * 每个方法的**预期 JVM 描述符**（intermediary 类名）。
     * Ref 解析出 Method 后逐字比对，不一致就当解析失败处理 —— 这是防「映射写错后
     * mod 静默失效」的兜底。由 modmap.py --full 生成。
     */
    static Map<String, String> sigs() {
        Map<String, String> m = new LinkedHashMap<>();
        m.put(M_INSTANCE, "()Lnet/minecraft/class_310;");
        m.put(M_SERVER, "()Lnet/minecraft/class_642;");
        m.put(M_GET_X, "()D");
        m.put(M_GET_Y, "()D");
        m.put(M_GET_Z, "()D");
        m.put(M_LOCATION, "()Lnet/minecraft/class_2960;");
        m.put(M_CHUNK_SRC, "()Lnet/minecraft/class_631;");
        m.put(M_SECTIONS, "()[Lnet/minecraft/class_2826;");
        m.put(M_CHUNK_POS, "()Lnet/minecraft/class_1923;");
        m.put(M_GET_HEIGHT, "(Lnet/minecraft/class_2902$class_2903;II)I");
        m.put(M_IS_EMPTY, "()Z");
        m.put(M_MIN_SECT, "()I");
        m.put(M_SECT_CNT, "()I");
        m.put(M_ONLY_AIR, "()Z");
        m.put(M_SEC_BLOCK, "(III)Lnet/minecraft/class_2680;");
        m.put(M_STATE_BLK, "()Lnet/minecraft/class_2248;");
        m.put(M_REG_KEY, "(Ljava/lang/Object;)Lnet/minecraft/class_2960;");
        return m;
    }
}
