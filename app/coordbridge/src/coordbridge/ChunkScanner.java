package coordbridge;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReferenceArray;

/**
 * 从**游戏内存**直读已加载区块，把「每列地表方块」落盘，供外部跟随地图使用。
 *
 * 为什么要做这个
 * --------------
 * Xaero 的地图落盘是硬编码 60 秒一次（MapSaveLoad.SAVE_TIME = 60000，编译期常量，
 * 改不了配置），实测 region 文件平均 20 秒以上才写一个。一个 region 只有 512 方块宽，
 * 鞘翅 33m/s 只要 15 秒就飞过去 —— 所以「读 Xaero zip」天生滞后。
 * 直读内存的延迟 = 客户端收到区块包的时间（通常 < 1 秒），能够真正跟上跑图。
 *
 * 取值路径（全部反射，字符串名见 Names）
 * --------------------------------------
 *   Minecraft.level -> ClientLevel.getChunkSource() -> ClientChunkCache.storage
 *     -> Storage.chunks (AtomicReferenceArray) -> LevelChunk
 *     -> ChunkAccess.getHeight(WORLD_SURFACE, x, z)  ← 每列 1 次，直接拿地表高度
 *     -> LevelChunkSection.getBlockState(x, y&15, z)
 *     -> BlockState.getBlock() -> BuiltInRegistries.BLOCK.getKey(block)
 *
 * 性能与安全感
 * ------------
 * - 每轮只处理固定数量（BUDGET）的 chunk，200ms 轮询一次，CPU 占用恒定且很低；
 *   视距内数百个 chunk 在 1~3 秒内滚动扫完，新出现的区域会在下一轮被吃到。
 * - 只读、不写入游戏状态、不发网络包。
 * - 后台线程读 chunk：chunks 是 AtomicReferenceArray（读引用原子），
 *   LevelChunkSection 在客户端收包时是**整体替换**而不是原地改写，
 *   因此最多读到「略旧但自洽」的一份数据，不会读到半更新状态。
 * - 任何一步抛异常都只影响当前 chunk，被 catch 掉，不影响游戏。
 *
 * 落盘格式（小端）
 * ----------------
 *   u32 magic 'CBB1' | u16 ver | u16 flags | i32 cx | i32 cz
 *   u16 palCount | palCount × (u16 len + UTF-8 方块名)
 *   256 × i16  colY    (该列地表方块的世界 y；-32768 = 无数据)
 *   256 × u16  colIdx  (调色板下标；0xFFFF = 无数据)    顺序均为 z*16+x
 */
final class ChunkScanner implements Runnable {

    static final int MAGIC = 0x31424243;      // "CBB1"
    static final int VERSION = 1;
    static final int REGION_CHUNKS = 32;      // 512 方块 = 32 chunk（与 Xaero region 对齐）

    /**
     * 本次游戏会话的编号。region 版本号每局都从 1 重新计数，如果外部缓存只按
     * 「版本号」做键，重开游戏后就会命中上一局留下的同号缓存、显示旧地形。
     * 把会话号一起写进 index，外部缓存带上它就不可能串局。
     */
    static final long SESSION = System.currentTimeMillis();

    /** 每轮的时间片 / 轮询间隔 / 单轮 chunk 上限。可用 -Dcoordbridge.*= 覆盖。 */
    private static final int SLICE_MS = Integer.getInteger("coordbridge.slice", 60);
    private static final int SLEEP_MS = Integer.getInteger("coordbridge.sleep", 90);
    private static final int BUDGET = Integer.getInteger("coordbridge.budget", 1024);

    /** 视为「没有方块」的方块名（与 followmap/colors.py 的 AIR_NAMES 保持一致）。 */
    private static final Set<String> SKIP = new HashSet<>(Arrays.asList(
            "minecraft:air", "minecraft:cave_air", "minecraft:void_air",
            "minecraft:barrier", "minecraft:light", "minecraft:structure_void",
            "minecraft:moving_piston"));

    private static final String NONE = "\u0000";

    private final Path home;
    private final IdentityHashMap<Object, String> nameCache = new IdentityHashMap<>();
    private final Map<String, DimState> dims = new HashMap<>();
    private long rounds = 0;

    // 每列缓冲（复用，避免每 chunk 分配）
    private final short[] colY = new short[256];
    private final short[] colIdx = new short[256];

    // 每轮「枚举-排序-处理」用的复用缓冲，避免高频 GC
    private int[] idxBuf = new int[1024];
    private long[] keyBuf = new long[1024];

    // 统计（写 status 用）
    private volatile String statDim = "";
    private volatile int statScanned = 0;
    private volatile int statWritten = 0;
    private volatile long statRoundMs = 0;
    private volatile long statTotalWritten = 0;
    private volatile String statMode = "-";
    private volatile String statError = "";
    private volatile int statLoaded = 0;
    private volatile int statSweepMs = 0;

    ChunkScanner(Path home) {
        this.home = home;
    }

    // ==================================================================== 主循环
    @Override
    public void run() {
        while (true) {
            try {
                round();
            } catch (Throwable t) {
                statError = t.getClass().getSimpleName() + ": " + t.getMessage();
            }
            try {
                Thread.sleep(SLEEP_MS);
            } catch (InterruptedException e) {
                return;
            }
        }
    }

    /** 一个维度在一次会话中的状态。 */
    private static final class DimState {
        final String dim;
        final String safe;
        final Path chunkDir;
        final Path indexFile;
        int rev = 1;
        int dirty = 0;
        final Map<Long, Long> sig = new HashMap<>();          // chunkKey -> 列数据 hash
        final Map<Long, Integer> regionRev = new HashMap<>(); // regionKey -> 版本号
        final Map<Long, Long> lastSeen = new HashMap<>();     // chunkKey -> 上次处理的轮次

        DimState(String dim, Path home) {
            this.dim = dim;
            this.safe = dim.replace(':', '_').replace('/', '_').replace('\\', '_');
            this.chunkDir = home.resolve("chunks").resolve(safe);
            this.indexFile = home.resolve("index_" + safe + ".json");
        }
    }

    private DimState stateOf(String dim) {
        DimState st = dims.get(dim);
        if (st == null) {
            st = new DimState(dim, home);
            try {
                Files.createDirectories(st.chunkDir);
            } catch (IOException ignored) {
            }
            dims.put(dim, st);
        }
        return st;
    }

    private void round() throws Exception {
        Ref.init();
        if (!Ref.ok) {
            statError = Ref.error;
            return;
        }
        long t0 = System.currentTimeMillis();

        Object mc = Ref.invoke(Ref.mInstance, null);
        if (mc == null) {
            return;
        }
        Object level = Ref.getField(Ref.fLevel, mc);
        if (level == null) {
            return;
        }
        Object cache = Ref.invoke(Ref.mChunkSrc, level);
        if (cache == null) {
            return;
        }
        Object storage = Ref.getField(Ref.fStorage, cache);
        if (storage == null) {
            return;
        }
        Object rawChunks = Ref.getField(Ref.fChunks, storage);
        if (!(rawChunks instanceof AtomicReferenceArray)) {
            return;
        }
        AtomicReferenceArray<?> arr = (AtomicReferenceArray<?>) rawChunks;

        // 当前维度
        String dim = "minecraft:overworld";
        Object key = Ref.getField(Ref.fDim, level);
        if (key != null) {
            Object loc = Ref.invoke(Ref.mLocation, key);
            if (loc != null) {
                dim = loc.toString();
            }
        }
        DimState st = stateOf(dim);

        int n = arr.length();
        if (n <= 0) {
            return;
        }
        if (idxBuf.length < n) {
            idxBuf = new int[n];
            keyBuf = new long[n];
        }

        // 玩家所在 chunk（用于排序：脚下的区块最该先更新）
        int pcx = Integer.MIN_VALUE / 2, pcz = Integer.MIN_VALUE / 2;
        Object player = Ref.getField(Ref.fPlayer, mc);
        if (player != null) {
            pcx = (int) Math.floor(Ref.toDouble(Ref.invoke(Ref.mGetX, player))) >> 4;
            pcz = (int) Math.floor(Ref.toDouble(Ref.invoke(Ref.mGetZ, player))) >> 4;
        }

        // ---- 第一遍：枚举全部已加载区块（只读坐标，极便宜）----
        long roundNo = ++rounds;
        int m = 0;
        for (int i = 0; i < n && m < 0xFFFFF; i++) {
            Object chunk = arr.get(i);
            if (chunk == null) {
                continue;
            }
            Object pos;
            try {
                pos = Ref.invoke(Ref.mChunkPos, chunk);
            } catch (Throwable t) {
                continue;
            }
            if (pos == null) {
                continue;
            }
            int cx, cz;
            try {
                cx = Ref.getInt(Ref.fCposX, pos);
                cz = Ref.getInt(Ref.fCposZ, pos);
            } catch (Throwable t) {
                continue;
            }
            long ck = key(cx, cz);
            Long ls = st.lastSeen.get(ck);
            long since = ls == null ? SWEEP_ROUNDS : Math.min(SWEEP_ROUNDS, roundNo - ls);
            int d = Math.max(Math.abs(cx - pcx), Math.abs(cz - pcz));
            if (d > 4095) {
                d = 4095;
            }
            // 排序键：先「多久没扫过」（越大越优先），同档再「离玩家近」
            long pri = (since << 12) | (4095 - d);
            idxBuf[m] = i;
            keyBuf[m] = (pri << 20) | m;
            m++;
        }
        statLoaded = m;
        if (m == 0) {
            statDim = dim;
            statScanned = 0;
            statWritten = 0;
            statRoundMs = System.currentTimeMillis() - t0;
            return;
        }

        java.util.Arrays.sort(keyBuf, 0, m);

        // ---- 第二遍：按优先级处理，直到时间片用完 ----
        long deadline = t0 + SLICE_MS;
        int scanned = 0;
        int written = 0;
        for (int k = 0; k < m && scanned < BUDGET; k++) {
            int i = idxBuf[(int) (keyBuf[k] & 0xFFFFF)];
            Object chunk = arr.get(i);
            if (chunk == null) {
                continue;
            }
            scanned++;
            try {
                Object pos = Ref.invoke(Ref.mChunkPos, chunk);
                int cx = Ref.getInt(Ref.fCposX, pos);
                int cz = Ref.getInt(Ref.fCposZ, pos);
                st.lastSeen.put(key(cx, cz), roundNo);
                if (chunk(st, chunk, cx, cz)) {
                    written++;
                }
            } catch (Throwable ignored) {
                // 单个 chunk 失败不影响其它
            }
            if (System.currentTimeMillis() >= deadline) {
                break;
            }
        }

        if (st.dirty > 0) {
            st.rev++;
            writeIndex(st);
            st.dirty = 0;
        }

        statDim = dim;
        statScanned = scanned;
        statWritten = written;
        statRoundMs = System.currentTimeMillis() - t0;
        statTotalWritten += written;
        // 整轮耗时估算：本轮（含枚举/排序）+ 睡眠，按本轮实际扫到的比例外推。
        statSweepMs = (int) Math.min(999999L,
                (statRoundMs + SLEEP_MS) * Math.max(1, m) / Math.max(1, scanned));
    }

    /**
     * 把「从未扫过」折算成多少轮没扫，保证新出现的区块一定排在最前。
     * 取值必须让 (since<<12)|(4095-d) 再 <<20 后仍不溢出 long：
     * 2^20 << 12 << 20 = 2^52，安全。
     */
    private static final long SWEEP_ROUNDS = 1L << 20;

    // ==================================================================== 单个 chunk
    /** @return true 表示该 chunk 的内容有变化并已重新落盘。 */
    private boolean chunk(DimState st, Object chunk, int cx, int cz) throws Exception {
        if (Ref.mIsEmpty != null) {
            Object empty = Ref.invoke(Ref.mIsEmpty, chunk);
            if (Boolean.TRUE.equals(empty)) {
                return false;
            }
        }
        long ck = key(cx, cz);

        Object[] sections = (Object[]) Ref.invoke(Ref.mSections, chunk);
        if (sections == null || sections.length == 0) {
            return false;
        }
        int minSec = ((Number) Ref.invoke(Ref.mMinSect, chunk)).intValue();

        Palette pal = new Palette();
        if (Ref.mGetHeight != null && Ref.heightmapWorldSurface != null) {
            statMode = "heightmap";
            byHeightmap(chunk, sections, minSec, pal);
        } else {
            statMode = "sections";
            bySections(sections, minSec, pal);
        }

        long h = hash(pal);
        Long prev = st.sig.get(ck);
        if (prev != null && prev.longValue() == h) {
            return false;                     // 内容没变，不写盘
        }
        st.sig.put(ck, h);
        if (pal.list.isEmpty()) {
            return false;                     // 整块无方块（全空气），不落盘
        }
        writeChunk(st, cx, cz, pal);
        touchRegion(st, cx, cz);
        return true;
    }

    /**
     * 快路径：用客户端 chunk 自带的 heightmap 直接取每列地表高度，
     * 每列 2 次反射调用，且耗时不随地形起伏变化。
     */
    private void byHeightmap(Object chunk, Object[] sections, int minSec, Palette pal)
            throws Exception {
        Arrays.fill(colIdx, (short) -1);
        int minY = minSec * 16;
        for (int z = 0; z < 16; z++) {
            for (int x = 0; x < 16; x++) {
                int h = ((Number) Ref.invokeHH(Ref.mGetHeight, chunk,
                        Ref.heightmapWorldSurface, x, z)).intValue();
                int y = h - 1;                       // heightmap 给的是「地表之上」
                if (y < minY) {
                    continue;
                }
                int si = (y >> 4) - minSec;
                if (si < 0 || si >= sections.length) {
                    continue;
                }
                Object sec = sections[si];
                if (sec == null) {
                    continue;
                }
                put(pal, z * 16 + x, y, Ref.invoke3(Ref.mSecBlock, sec, x, y & 15, z));
            }
        }
    }

    /**
     * 慢路径：没有 heightmap 时，从最高一段往下逐层找每列第一个非空气方块。
     * 一旦某一层已把 256 列填满就提前结束。
     */
    private void bySections(Object[] sections, int minSec, Palette pal) throws Exception {
        Arrays.fill(colIdx, (short) -1);
        int remain = 256;
        for (int si = sections.length - 1; si >= 0 && remain > 0; si--) {
            Object sec = sections[si];
            if (sec == null) {
                continue;
            }
            if (Boolean.TRUE.equals(Ref.invoke(Ref.mOnlyAir, sec))) {
                continue;
            }
            int wyBase = (minSec + si) * 16;
            for (int y = 15; y >= 0 && remain > 0; y--) {
                int wy = wyBase + y;
                for (int z = 0; z < 16; z++) {
                    int off = z * 16;
                    for (int x = 0; x < 16; x++) {
                        int ci = off + x;
                        if (colIdx[ci] != -1) {
                            continue;
                        }
                        Object st = Ref.invoke3(Ref.mSecBlock, sec, x, y, z);
                        if (put(pal, ci, wy, st)) {
                            remain--;
                        }
                    }
                }
            }
        }
    }

    /** @return true 表示这一列被填上了（非空气）。 */
    private boolean put(Palette pal, int ci, int y, Object state) throws Exception {
        String nm = blockName(state);
        if (nm == null) {
            return false;
        }
        colIdx[ci] = (short) pal.intern(nm);
        colY[ci] = (short) y;
        return true;
    }

    /** BlockState -> 方块名。BlockState 是单例，用 IdentityHashMap 缓存后几乎零开销。 */
    private String blockName(Object state) throws Exception {
        if (state == null) {
            return null;
        }
        String hit = nameCache.get(state);
        if (hit != null) {
            return NONE.equals(hit) ? null : hit;
        }
        Object block = Ref.invoke(Ref.mStateBlk, state);
        Object loc = block == null ? null : Ref.invoke1(Ref.mRegKey, Ref.blockRegistry, block);
        String nm = loc == null ? null : loc.toString();
        if (nm != null && SKIP.contains(nm)) {
            nm = null;
        }
        nameCache.put(state, nm == null ? NONE : nm);
        return nm;
    }

    private long hash(Palette pal) {
        long h = 1125899906842597L;
        for (int i = 0; i < 256; i++) {
            h = h * 31 + colY[i];
            h = h * 31 + colIdx[i];
        }
        h = h * 31 + pal.list.size();
        for (int i = 0; i < pal.list.size(); i++) {
            h = h * 31 + pal.list.get(i).hashCode();
        }
        return h;
    }

    // ==================================================================== 落盘
    private static long key(int cx, int cz) {
        return ((long) cx << 32) | (cz & 0xFFFFFFFFL);
    }

    private void touchRegion(DimState st, int cx, int cz) {
        int rx = Math.floorDiv(cx, REGION_CHUNKS);
        int rz = Math.floorDiv(cz, REGION_CHUNKS);
        long k = key(rx, rz);
        Integer old = st.regionRev.get(k);
        st.regionRev.put(k, (old == null ? 0 : old) + 1);
        st.dirty++;
    }

    private void writeChunk(DimState st, int cx, int cz, Palette pal) throws IOException {
        int est = 64 + 256 * 4;
        for (String s : pal.list) {
            est += s.length() * 4 + 2;
        }
        ByteBuffer b = ByteBuffer.allocate(est).order(ByteOrder.LITTLE_ENDIAN);
        b.putInt(MAGIC);
        b.putShort((short) VERSION);
        b.putShort((short) 0);
        b.putInt(cx);
        b.putInt(cz);
        b.putShort((short) pal.list.size());
        for (int i = 0; i < pal.list.size(); i++) {
            byte[] u = pal.list.get(i).getBytes(StandardCharsets.UTF_8);
            b.putShort((short) u.length);
            b.put(u);
        }
        for (int i = 0; i < 256; i++) {
            b.putShort(colY[i]);
        }
        for (int i = 0; i < 256; i++) {
            b.putShort(colIdx[i]);
        }
        byte[] data = new byte[b.position()];
        b.flip();
        b.get(data);

        // 按 region 分两级子目录：一个维度跑久了会有上万个 chunk 文件，
        // 平铺在一个目录里会让外部程序 listdir 变慢。
        int rx = Math.floorDiv(cx, REGION_CHUNKS);
        int rz = Math.floorDiv(cz, REGION_CHUNKS);
        Path out = st.chunkDir.resolve("r" + rx).resolve("r" + rz)
                .resolve(cx + "_" + cz + ".bin");
        atomicWrite(out, data);
    }

    private void writeIndex(DimState st) {
        StringBuilder sb = new StringBuilder(2048);
        sb.append("{\"dim\":\"").append(esc(st.dim))
          .append("\",\"sid\":").append(SESSION)
          .append(",\"rev\":").append(st.rev)
          .append(",\"t\":").append(System.currentTimeMillis())
          .append(",\"chunks\":").append(st.sig.size())
          .append(",\"regions\":{");
        boolean first = true;
        for (Map.Entry<Long, Integer> e : st.regionRev.entrySet()) {
            if (!first) {
                sb.append(',');
            }
            first = false;
            long k = e.getKey();
            sb.append('"').append((int) (k >> 32)).append(',').append((int) (k & 0xFFFFFFFFL))
              .append("\":").append(e.getValue());
        }
        sb.append("}}");
        try {
            atomicWrite(st.indexFile, sb.toString().getBytes(StandardCharsets.UTF_8));
        } catch (IOException ignored) {
        }
    }

    private static void atomicWrite(Path p, byte[] data) throws IOException {
        Files.createDirectories(p.getParent());
        Path tmp = p.resolveSibling(p.getFileName().toString() + ".tmp");
        Files.write(tmp, data);
        try {
            Files.move(tmp, p, StandardCopyOption.REPLACE_EXISTING,
                    StandardCopyOption.ATOMIC_MOVE);
        } catch (AtomicMoveNotSupportedException e) {
            Files.move(tmp, p, StandardCopyOption.REPLACE_EXISTING);
        }
    }

    // ==================================================================== 状态
    String statusText() {
        StringBuilder sb = new StringBuilder();
        sb.append("coordbridge chunk scanner\n");
        sb.append("slice/round  : ").append(SLICE_MS).append(" ms  (上限 ").append(BUDGET).append(" chunks)\n");
        sb.append("sleep        : ").append(SLEEP_MS).append(" ms\n");
        sb.append("heightmap    : ").append(Ref.heightmapWorldSurface != null ? "OK" : "缺失（退化为逐段扫描）").append('\n');
        sb.append("mode         : ").append(statMode).append('\n');
        sb.append("dim          : ").append(statDim).append('\n');
        sb.append("loaded chunks: ").append(statLoaded).append('\n');
        sb.append("last round   : scanned ").append(statScanned)
          .append(" chunks, written ").append(statWritten)
          .append(", ").append(statRoundMs).append(" ms\n");
        sb.append("full sweep   : 约 ").append(statSweepMs).append(" ms（全量刷一遍的周期，越短越跟得上跑图）\n");
        sb.append("total written: ").append(statTotalWritten).append('\n');
        if (!statError.isEmpty()) {
            sb.append("error        : ").append(statError).append('\n');
        }
        sb.append('\n');
        sb.append("---- 反射解析自检（描述符必须与 Names.sigs() 一致）----\n");
        sb.append(Ref.ok ? "state        : OK\n" : "state        : FAIL " + Ref.error + "\n");
        if (!Ref.report.isEmpty()) {
            sb.append(Ref.report);
        }
        sb.append('\n');
        sb.append(String.format("%-26s %8s %8s %8s%n", "dimension", "chunks", "regions", "rev"));
        for (DimState st : dims.values()) {
            sb.append(String.format("%-26s %8d %8d %8d%n",
                    st.dim, st.sig.size(), st.regionRev.size(), st.rev));
        }
        return sb.toString();
    }

    /** 调色板：chunk 内用到的方块名去重。 */
    static final class Palette {
        final ArrayList<String> list = new ArrayList<>();
        private final HashMap<String, Integer> map = new HashMap<>();

        int intern(String s) {
            Integer i = map.get(s);
            if (i != null) {
                return i;
            }
            int n = list.size();
            map.put(s, n);
            list.add(s);
            return n;
        }
    }

    private static String esc(String s) {
        StringBuilder b = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char ch = s.charAt(i);
            if (ch == '"' || ch == '\\') {
                b.append('\\').append(ch);
            } else if (ch < 0x20) {
                b.append(String.format("\\u%04x", (int) ch));
            } else {
                b.append(ch);
            }
        }
        return b.toString();
    }
}
