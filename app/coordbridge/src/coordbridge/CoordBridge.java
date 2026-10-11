package coordbridge;

import net.fabricmc.api.ClientModInitializer;

import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.time.Instant;

/**
 * CoordBridge —— 把当前玩家坐标 + 维度 + 服务器地址写到 ~/.coordbridge/coords.json
 *
 * 设计要点
 * --------
 * 1. 完全使用「反射 + 字符串」，**不链接任何 Minecraft 类**，因此可以用 javac 直接编译，
 *    不需要 Gradle / Loom / Yarn。
 * 2. 字符串取自 Fabric 运行时命名（intermediary），由 mapbridge.py 从
 *    Mojang 官方映射(client.txt) + Fabric intermediary 确定性推导。
 *    对应关系（官方名）：
 *        class_310     = net.minecraft.client.Minecraft
 *        field_1724    = Minecraft.player       (LocalPlayer)
 *        field_1687    = Minecraft.level        (ClientLevel)
 *        method_1551   = Minecraft.getInstance()
 *        method_1558   = Minecraft.getCurrentServer() -> ServerData
 *        method_23317/23318/23321 = Entity.getX/getY/getZ
 *        field_25176   = Level.dimension        (ResourceKey)
 *        method_29177  = ResourceKey.location() -> ResourceLocation
 *        field_3761    = ServerData.ip
 *    **常量统一放在 Names.java，这里不再抄一份**：抄两份会漂移，而漂移的表现是
 *    status.txt 里的自检报假错（明明能用却报 NOT FOUND），很难查。
 *
 * 3. 支持版本：Minecraft **1.20.1 ~ 1.20.4**（Fabric）。
 *    这几个版本用到的 20 类 / 9 字段 / 17 方法 / 17 描述符**完全相同**（实测对比，
 *    见 `python modmap.py --compare 1.20.1 1.20.4`），所以同一个 jar 通吃，
 *    不需要为每个 MC 版本分别构建。fabric.mod.json 里声明为 ">=1.20.1 <1.20.5"。
 * 4. 客户端单机/多人皆可；不发送任何网络包，只在本地落一个 JSON。
 */
public class CoordBridge implements ClientModInitializer {

    // 全部常量取自 Names（同一份推导结果，别在这里重抄）。
    private static final String C_MC = Names.C_MC;
    private static final String F_PLAYER = Names.F_PLAYER;
    private static final String F_LEVEL = Names.F_LEVEL;
    private static final String M_INSTANCE = Names.M_INSTANCE;
    private static final String M_SERVER = Names.M_SERVER;
    private static final String M_GET_X = Names.M_GET_X;
    private static final String M_GET_Y = Names.M_GET_Y;
    private static final String M_GET_Z = Names.M_GET_Z;
    private static final String F_DIM = Names.F_DIM;
    private static final String M_LOCATION = Names.M_LOCATION;
    private static final String F_SRV_IP = Names.F_SRV_IP;

    private static Path outFile;
    private static Path statusFile;
    private static Path scanStatusFile;
    private static ChunkScanner scanner;

    @Override
    public void onInitializeClient() {
        Path dir;
        try {
            dir = Paths.get(System.getProperty("user.home"), ".coordbridge");
            Files.createDirectories(dir);
            outFile = dir.resolve("coords.json");
            statusFile = dir.resolve("status.txt");
            scanStatusFile = dir.resolve("scan_status.txt");
            atomicWrite(statusFile, statusText());
        } catch (Throwable t) {
            return;
        }
        Thread t = new Thread(CoordBridge::loop, "coordbridge-writer");
        t.setDaemon(true);
        t.start();

        // 内存直读区块 -> 落盘（供外部跟随地图使用，绕过 Xaero 的 60 秒落盘节流）
        scanner = new ChunkScanner(dir);
        Thread sc = new Thread(scanner, "coordbridge-scan");
        sc.setDaemon(true);
        sc.setPriority(Thread.MIN_PRIORITY + 1);   // 不与游戏渲染线程抢 CPU
        sc.start();

        Thread ss = new Thread(CoordBridge::scanStatusLoop, "coordbridge-scan-status");
        ss.setDaemon(true);
        ss.start();
    }

    /** 每分钟把扫描器状态落一份，便于外部诊断。 */
    private static void scanStatusLoop() {
        while (true) {
            try {
                Thread.sleep(1000L);
            } catch (InterruptedException e) {
                return;
            }
            try {
                if (scanner != null && scanStatusFile != null) {
                    atomicWrite(scanStatusFile, scanner.statusText());
                }
            } catch (Throwable ignored) {
            }
        }
    }

    private static void loop() {
        while (true) {
            String json;
            try {
                json = snapshot();
            } catch (Throwable e) {
                json = "{\"t\":" + Instant.now().toEpochMilli()
                        + ",\"in_game\":false,\"error\":\"" + esc(String.valueOf(e)) + "\"}";
            }
            try {
                atomicWrite(outFile, json);
            } catch (Throwable ignored) {
            }
            try {
                Thread.sleep(100L);
            } catch (InterruptedException e) {
                return;
            }
        }
    }

    private static String snapshot() throws Exception {
        StringBuilder sb = new StringBuilder(200);
        sb.append("{\"t\":").append(Instant.now().toEpochMilli());

        Object mc = invokeStatic(C_MC, M_INSTANCE);
        if (mc == null) {
            sb.append(",\"in_game\":false}");
            return sb.toString();
        }
        Object player = getFieldOrNull(mc, F_PLAYER);
        Object level = getFieldOrNull(mc, F_LEVEL);
        if (player == null || level == null) {
            sb.append(",\"in_game\":false}");
            return sb.toString();
        }

        double x = toDouble(invoke(player, M_GET_X));
        double y = toDouble(invoke(player, M_GET_Y));
        double z = toDouble(invoke(player, M_GET_Z));

        String dim = null;
        Object key = getFieldOrNull(level, F_DIM);
        if (key != null) {
            Object loc = invoke(key, M_LOCATION);
            if (loc != null) {
                dim = String.valueOf(loc);
            }
        }

        String server = null;
        Object sd = invoke(mc, M_SERVER);
        if (sd != null) {
            Object ip = getFieldOrNull(sd, F_SRV_IP);
            if (ip != null) {
                server = String.valueOf(ip);
            }
        }

        sb.append(",\"in_game\":true");
        sb.append(",\"x\":").append(round(x));
        sb.append(",\"y\":").append(round(y));
        sb.append(",\"z\":").append(round(z));
        sb.append(",\"dim\":").append(dim == null ? "null" : "\"" + esc(dim) + "\"");
        sb.append(",\"server\":").append(server == null ? "null" : "\"" + esc(server) + "\"");
        sb.append(",\"local\":").append(server == null);
        sb.append("}");
        return sb.toString();
    }

    // ------------------------------------------------------------------
    // 反射工具：沿类层次向上查找（Minecraft 的字段/方法都是 public，但仍做兼容处理）
    // ------------------------------------------------------------------
    private static Object invokeStatic(String cls, String method) throws Exception {
        Class<?> c = Class.forName(cls);
        Method m = findMethod(c, method, 0);
        if (m == null) {
            throw new NoSuchMethodException(cls + "." + method);
        }
        return m.invoke(null);
    }

    private static Object invoke(Object obj, String method) throws Exception {
        Method m = findMethod(obj.getClass(), method, 0);
        if (m == null) {
            throw new NoSuchMethodException(obj.getClass().getName() + "." + method);
        }
        return m.invoke(obj);
    }

    private static Object getFieldOrNull(Object obj, String field) {
        Class<?> c = obj.getClass();
        while (c != null) {
            try {
                Field f = c.getDeclaredField(field);
                f.setAccessible(true);
                return f.get(obj);
            } catch (NoSuchFieldException e) {
                c = c.getSuperclass();
            } catch (Throwable e) {
                return null;
            }
        }
        return null;
    }

    private static Method findMethod(Class<?> c, String name, int argCount) {
        Class<?> k = c;
        while (k != null) {
            try {
                Method m = k.getDeclaredMethod(name);
                m.setAccessible(true);
                return m;
            } catch (NoSuchMethodException e) {
                k = k.getSuperclass();
            } catch (Throwable e) {
                return null;
            }
        }
        return null;
    }

    private static double toDouble(Object o) {
        return o instanceof Number ? ((Number) o).doubleValue() : 0.0D;
    }

    private static String round(double v) {
        return String.valueOf(Math.round(v * 1000.0D) / 1000.0D);
    }

    private static String esc(String s) {
        StringBuilder b = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char ch = s.charAt(i);
            switch (ch) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default:
                    if (ch < 0x20) {
                        b.append(String.format("\\u%04x", (int) ch));
                    } else {
                        b.append(ch);
                    }
            }
        }
        return b.toString();
    }

    private static String statusText() {
        StringBuilder sb = new StringBuilder();
        sb.append("coordbridge status\n");
        sb.append("time   : ").append(Instant.now()).append('\n');
        sb.append("java   : ").append(System.getProperty("java.version")).append('\n');
        sb.append("cwd    : ").append(System.getProperty("user.dir")).append('\n');
        sb.append("target : MC 1.20.1~1.20.4 / Fabric (intermediary)\n\n");
        check(sb, "Minecraft class", () -> Class.forName(C_MC));
        check(sb, "Minecraft.getInstance", () -> findMethod(Class.forName(C_MC), M_INSTANCE, 0));
        check(sb, "Entity.getX/Y/Z",
                () -> findMethod(Class.forName(Names.C_ENTITY), M_GET_X, 0));
        check(sb, "Level.dimension",
                () -> Class.forName(Names.C_LEVEL).getDeclaredField(F_DIM));
        check(sb, "ResourceKey.location",
                () -> findMethod(Class.forName(Names.C_REGKEY), M_LOCATION, 0));
        check(sb, "ServerData.ip",
                () -> Class.forName(Names.C_SERVERDATA).getDeclaredField(F_SRV_IP));

        sb.append("\n-- 内存直读区块链路 --\n");
        Ref.init();
        sb.append(String.format("%-24s : %s%n", "reflect bridge",
                Ref.ok ? "OK" : "FAIL " + Ref.error));
        sb.append(String.format("%-24s : %s%n", "block registry",
                Ref.blockRegistry != null ? "OK" : "null"));
        sb.append(String.format("%-24s : %s%n", "heightmap WORLD_SURFACE",
                Ref.heightmapWorldSurface != null ? "OK" : "缺失（退化为逐段扫描）"));
        sb.append(String.format("%-24s : %s%n", "chunk scanner",
                scanner != null ? "running" : "未启动"));
        if (!Ref.report.isEmpty()) {
            sb.append("-- 解析明细 --\n").append(Ref.report);
        }

        sb.append("\nresult : ").append(outFile).append('\n');
        return sb.toString();
    }

    private interface Probe {
        Object run() throws Throwable;
    }

    private static void check(StringBuilder sb, String label, Probe p) {
        sb.append(String.format("%-24s : ", label));
        try {
            Object r = p.run();
            sb.append(r == null ? "NOT FOUND" : "OK");
        } catch (Throwable e) {
            sb.append("FAIL ").append(e.getClass().getSimpleName()).append(" ").append(e.getMessage());
        }
        sb.append('\n');
    }

    private static void atomicWrite(Path p, String content) throws IOException {
        Path tmp = p.resolveSibling(p.getFileName().toString() + ".tmp");
        Files.write(tmp, content.getBytes(StandardCharsets.UTF_8));
        try {
            Files.move(tmp, p, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        } catch (AtomicMoveNotSupportedException e) {
            Files.move(tmp, p, StandardCopyOption.REPLACE_EXISTING);
        }
    }
}
