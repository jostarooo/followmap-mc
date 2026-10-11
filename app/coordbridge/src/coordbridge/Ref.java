package coordbridge;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Map;

/**
 * 反射解析与缓存。
 *
 * 三个要点：
 * 1) **一次性解析并缓存 Method/Field**。每次调用都沿类层次查找，在「每轮几万次
 *    getBlockState」的量级下光查找就会拖垮游戏。
 * 2) 用 {@code getMethods()} 而不是沿 getSuperclass() 上溯：LevelHeightAccessor /
 *    Registry 的方法是通过**接口**引入的，沿父类链找不到。
 * 3) **按完整描述符校验**（见 Names.sigs()）。只按「类+方法名」找是不够的：
 *    obf 名被压成 a/b/c 后一个类里有大量同名重载，历史上就因此把
 *    LevelChunkSection.getBlockState(int,int,int) 解析成了同名的 ()V 方法，
 *    结果 mod 既不报错也不写数据，表现成「地图一直跟不上」。
 *    现在解析出的 Method 描述符与预期不符就算失败，并把实际签名写进 status.txt。
 *
 * 不链接任何 Minecraft 类，只用字符串 + Class.forName，因此 javac 可直接编译。
 */
final class Ref {
    private Ref() {
    }

    static boolean ok;
    static String error = "";
    /** 解析结果的自检报告（status.txt 里直接可见）。 */
    static String report = "";
    /** 失败后至少隔这么久再重试。首次调用可能早于 BuiltInRegistries 就绪，必须允许重试。 */
    private static long nextRetryAt = 0L;
    private static final long RETRY_MS = 2000L;
    private static final int MAX_ATTEMPTS = 20;

    static Class<?> cMC;
    static Method mInstance, mServer, mGetX, mGetY, mGetZ, mLocation;
    static Method mChunkSrc, mSections, mChunkPos, mMinSect, mOnlyAir, mSecBlock, mStateBlk, mRegKey;
    static Method mGetHeight, mIsEmpty;
    static Field fLevel, fPlayer, fStorage, fChunks, fBlockReg, fCposX, fCposZ, fDim, fSrvIp;
    static Object blockRegistry;
    /** Heightmap.Types.WORLD_SURFACE 枚举常量（枚举名不被混淆，用 name() 匹配）。 */
    static Object heightmapWorldSurface;

    private static int attempts = 0;
    private static final Map<String, String> SIGS = Names.sigs();
    private static final StringBuilder LOG = new StringBuilder(1024);

    static synchronized void init() {
        if (ok) {
            return;
        }
        long now = System.currentTimeMillis();
        if (now < nextRetryAt) {
            return;
        }
        LOG.setLength(0);
        try {
            Class<?> cLevel = Class.forName(Names.C_LEVEL);
            Class<?> cChunkAccess = Class.forName(Names.C_CHUNK_ACCESS);
            Class<?> cHeightAcc = Class.forName(Names.C_HEIGHT_ACC);
            Class<?> cSection = Class.forName(Names.C_SECTION);
            Class<?> cBlockStBase = Class.forName(Names.C_BLOCK_ST_BASE);
            Class<?> cRegistry = Class.forName(Names.C_REGISTRY);
            Class<?> cChunkPos = Class.forName(Names.C_CHUNK_POS);
            Class<?> cRegKey = Class.forName(Names.C_REGKEY);
            Class<?> cServerData = Class.forName(Names.C_SERVERDATA);
            Class<?> cEntity = Class.forName(Names.C_ENTITY);
            Class<?> cChunkCache = Class.forName(Names.C_CHUNK_CACHE);
            Class<?> cStorage = Class.forName(Names.C_STORAGE);
            Class<?> cBuiltin = Class.forName(Names.C_BUILTIN_REGS);

            cMC = Class.forName(Names.C_MC);

            mInstance = need(get(cMC, Names.M_INSTANCE, 0), "Minecraft.getInstance");
            mServer = findMethod(cMC, Names.M_SERVER, 0);
            mGetX = need(get(cEntity, Names.M_GET_X, 0), "Entity.getX");
            mGetY = need(get(cEntity, Names.M_GET_Y, 0), "Entity.getY");
            mGetZ = need(get(cEntity, Names.M_GET_Z, 0), "Entity.getZ");
            mLocation = need(get(cRegKey, Names.M_LOCATION, 0), "ResourceKey.location");

            fLevel = need(findField(cMC, Names.F_LEVEL), "Minecraft.level");
            fPlayer = need(findField(cMC, Names.F_PLAYER), "Minecraft.player");
            fDim = need(findField(cLevel, Names.F_DIM), "Level.dimension");
            fSrvIp = cServerData == null ? null : findField(cServerData, Names.F_SRV_IP);

            // ---- 区块扫描链路 ----
            mChunkSrc = need(get(Class.forName(Names.C_CLIENT_LEVEL), Names.M_CHUNK_SRC, 0),
                    "ClientLevel.getChunkSource");
            fStorage = need(findField(cChunkCache, Names.F_STORAGE), "ClientChunkCache.storage");
            fChunks = need(findField(cStorage, Names.F_CHUNKS), "ClientChunkCache$Storage.chunks");
            mSections = need(get(cChunkAccess, Names.M_SECTIONS, 0), "ChunkAccess.getSections");
            mChunkPos = need(get(cChunkAccess, Names.M_CHUNK_POS, 0), "ChunkAccess.getPos");
            fCposX = need(findField(cChunkPos, Names.F_CPOS_X), "ChunkPos.x");
            fCposZ = need(findField(cChunkPos, Names.F_CPOS_Z), "ChunkPos.z");
            mMinSect = need(get(cHeightAcc, Names.M_MIN_SECT, 0), "LevelHeightAccessor.getMinSection");
            mOnlyAir = need(get(cSection, Names.M_ONLY_AIR, 0), "LevelChunkSection.hasOnlyAir");
            // 这里是最容易出事的一步：getBlockState 在 LevelChunkSection 里有 6 个同名重载
            mSecBlock = need(get(cSection, Names.M_SEC_BLOCK, 3), "LevelChunkSection.getBlockState");
            mStateBlk = need(get(cBlockStBase, Names.M_STATE_BLK, 0), "BlockStateBase.getBlock");
            mRegKey = need(get(cRegistry, Names.M_REG_KEY, 1), "Registry.getKey");

            // 客户端 chunk 自带 heightmaps（WORLD_SURFACE / MOTION_BLOCKING），
            // 用来一次定位地表；枚举字段名会被混淆，但 name() 不会，故按名字匹配。
            Class<?> cHeightmap = Class.forName(Names.C_HEIGHTMAP);
            mGetHeight = need(get(cChunkAccess, Names.M_GET_HEIGHT, 3), "ChunkAccess.getHeight");
            mIsEmpty = findMethod(Class.forName(Names.C_CHUNK), Names.M_IS_EMPTY, 0);
            Object hmEnum = null;
            if (cHeightmap.isEnum()) {
                for (Object e : cHeightmap.getEnumConstants()) {
                    if ("WORLD_SURFACE".equals(((Enum<?>) e).name())) {
                        hmEnum = e;
                        break;
                    }
                }
            }
            heightmapWorldSurface = hmEnum;

            fBlockReg = need(findField(cBuiltin, Names.F_BLOCK_REG), "BuiltInRegistries.BLOCK");
            blockRegistry = fBlockReg.get(null);
            if (blockRegistry == null) {
                throw new IllegalStateException("BuiltInRegistries.BLOCK 为 null");
            }
            ok = true;
            error = "";
            attempts = 0;
            report = LOG.toString();
            return;
        } catch (Throwable t) {
            error = t.getClass().getSimpleName() + ": " + t.getMessage();
            report = LOG.toString();
            attempts++;
            nextRetryAt = now + (attempts >= MAX_ATTEMPTS ? 600_000L : RETRY_MS);
        }
    }

    // ------------------------------------------------------------------ 工具

    /**
     * 按名称 + 参数个数查找，并**校验描述符与 Names.sigs() 一致**。
     * 不一致直接返回 null —— 宁可判定「找不到」并让 status.txt 写明，
     * 也不能拿一个签名不对的 Method 去 invoke（那样只会在运行时抛异常，难以定位）。
     */
    private static Method get(Class<?> c, String name, int argc) {
        Method m = findMethod(c, name, argc);
        if (m == null) {
            LOG.append("  [miss] ").append(name).append(" argc=").append(argc)
               .append(" in ").append(c == null ? "null" : c.getName()).append('\n');
            return null;
        }
        String want = SIGS.get(name);
        String got = descOf(m);
        if (want != null && !want.equals(got)) {
            LOG.append("  [bad sig] ").append(name)
               .append(" owner=").append(m.getDeclaringClass().getName())
               .append("\n            got  ").append(got)
               .append("\n            want ").append(want).append('\n');
            return null;
        }
        LOG.append("  [ok] ").append(name).append(' ').append(got)
           .append("  <- ").append(m.getDeclaringClass().getName()).append('\n');
        return m;
    }

    private static <T> T need(T v, String what) {
        if (v == null) {
            throw new IllegalStateException("找不到 " + what);
        }
        return v;
    }

    /** JVM 描述符（intermediary 类名），用于与 Names.sigs() 比对。 */
    private static String descOf(Method m) {
        StringBuilder sb = new StringBuilder(48).append('(');
        for (Class<?> p : m.getParameterTypes()) {
            sb.append(typeOf(p));
        }
        return sb.append(')').append(typeOf(m.getReturnType())).toString();
    }

    private static String typeOf(Class<?> c) {
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

    /** 先查 public（含继承与接口实现），再沿父类链查 declared。 */
    static Method findMethod(Class<?> c, String name, int argc) {
        if (c == null) {
            return null;
        }
        Method[] pub;
        try {
            pub = c.getMethods();
        } catch (Throwable t) {
            pub = new Method[0];
        }
        for (Method m : pub) {
            if (m.getName().equals(name) && m.getParameterCount() == argc) {
                try {
                    m.setAccessible(true);
                } catch (Throwable ignored) {
                }
                return m;
            }
        }
        Class<?> k = c;
        while (k != null) {
            Method[] decl;
            try {
                decl = k.getDeclaredMethods();
            } catch (Throwable t) {
                decl = new Method[0];
            }
            for (Method m : decl) {
                if (m.getName().equals(name) && m.getParameterCount() == argc) {
                    try {
                        m.setAccessible(true);
                    } catch (Throwable ignored) {
                    }
                    return m;
                }
            }
            k = k.getSuperclass();
        }
        return null;
    }

    static Field findField(Class<?> c, String name) {
        Class<?> k = c;
        while (k != null) {
            try {
                Field f = k.getDeclaredField(name);
                f.setAccessible(true);
                return f;
            } catch (NoSuchFieldException e) {
                k = k.getSuperclass();
            } catch (Throwable t) {
                return null;
            }
        }
        return null;
    }

    static Object invoke(Method m, Object obj) throws Exception {
        return m.invoke(obj);
    }

    static Object invoke3(Method m, Object obj, int a, int b, int c) throws Exception {
        return m.invoke(obj, a, b, c);
    }

    static Object invoke1(Method m, Object obj, Object a) throws Exception {
        return m.invoke(obj, a);
    }

    /** 3 参重载（Heightmap 路径：getHeight(Types, x, z)）。 */
    static Object invokeHH(Method m, Object obj, Object type, int x, int z) throws Exception {
        return m.invoke(obj, type, x, z);
    }

    static Object getField(Field f, Object obj) throws Exception {
        return f.get(obj);
    }

    static int getInt(Field f, Object obj) throws Exception {
        return f.getInt(obj);
    }

    static double toDouble(Object o) {
        return o instanceof Number ? ((Number) o).doubleValue() : 0.0D;
    }
}
