package fishauto;

/**
 * QTE 进度条**像素几何解码器**（v0.2 新增）—— 把一帧字幕解成「指针 vs 绿区」的相对位置。
 *
 * 全部数值从活动资源包实测推导（见 app/report/qte-geometry-report.md 与 app/qte_advance.json）：
 *
 *   一帧 subtitle = 进度条字模 + U+F8xx 位偏移占位，例如（easy 变体首帧）：
 *     B00C F807 F806 F804 F801 B012 F816 F815 F813 F812 F811 F808 F805 F804 F803
 *          B001 F818 F815 F813 F812 F811
 *   按 advance 逐字累加 x：
 *     B00C(底图 256) + F807(-66) F806(-34) F804(-10) F801(-3) = 绿区起点 x=143
 *     B012(绿区 45)  + 段2 合计 -115                            = 指针起点 x=73
 *   ⇒ d = ptr_x - zone_x = -70（指针在绿区左侧 70px）。
 *
 * advance 表（integer，全部无小数，所以这里用纯 int 运算）：
 *   B001=5；B002..B00C=256；B00D..B010=8；B011=256；
 *   B012=45  B013=36  B014=27
 *   F801=-3 F802=-4 F803=-6 F804=-10 F805=-18 F806=-34 F807=-66 F808=-130
 *   F811=-1 F812=+1 F813=+3 F814=+7 F815=+15 F816=+31 F817=+63 F818=+127
 *
 * ★ 与 v0.1 的关键差别 ★
 *   v0.1 假设「韩文音节区全宽格 advance=8」，把 B00C/B012/B001 也当 8px 算 →
 *   指针位置永远对不上（这就是 v0.1 只能退化成连按的根因）。
 *   v0.2：B0xx 与 F8xx 属于**两个不同字体**，必须合并两张表；F8xx 是**带符号**位偏移。
 *
 * 已知边界（实测）：帧总宽 tot ≈ 220~229，不恒等 256 —— 占位符是贪心分解量化，
 * 残差 ±4.5px，所以判定必须带余量（geo_margin，默认 8px）。
 *
 * 判定规则（与 qtemap.py --align 扫描一致，选分离度最优的 center / 8px 做默认）：
 *   d = ptr_x - zone_x（指针左沿相对绿区左沿）
 *   left   : -m <= d          <= w + m     指针左沿入区
 *   center : -m <= d + 2      <= w + m     指针中心入区（指针宽 5，中心 +2）
 *   whole  : -m <= d, d + 5   <= w + m     指针整体入区
 */
final class Geom {
    private Geom() {
    }

    static final int POINTER = 0xB001;
    static final int POINTER_W = 5;
    static final int POINTER_HALF = 2;          // 中心偏移 = (5-1)/2

    /** 判定绿区（B012 easy / B013 normal / B014 hard）。 */
    static boolean isJudge(int cp) {
        return cp >= 0xB012 && cp <= 0xB014;
    }

    static int judgeW(int cp) {
        switch (cp) {
            case 0xB012: return 45;
            case 0xB013: return 36;
            case 0xB014: return 27;
            default: return 0;
        }
    }

    /** 是否进度条本体字模（B0xx 韩文音节区）。 */
    static boolean isBarChar(int cp) {
        return cp >= 0xAC00 && cp <= 0xD7A3;
    }

    /**
     * 单个码点的 advance。查不到返回 {@link #UNKNOWN}。
     * ⚠️ 这张表必须与 app/qte_advance.json 逐项一致（AutoTest 有逐项断言）。
     */
    static final int UNKNOWN = Integer.MIN_VALUE;

    static int advance(int cp) {
        switch (cp) {
            // ---- customfishing:default（进度条本体）----
            case 0xB001: return 5;
            case 0xB002: case 0xB003: case 0xB004: case 0xB005:
            case 0xB006: case 0xB007: case 0xB008: case 0xB009:
            case 0xB00A: case 0xB00B: case 0xB00C:
                return 256;
            case 0xB00D: case 0xB00E: case 0xB00F: case 0xB010:
                return 8;
            case 0xB011: return 256;
            case 0xB012: return 45;
            case 0xB013: return 36;
            case 0xB014: return 27;
            // ---- customfishing:offset_chars（带符号位偏移）----
            case 0xF801: return -3;
            case 0xF802: return -4;
            case 0xF803: return -6;
            case 0xF804: return -10;
            case 0xF805: return -18;
            case 0xF806: return -34;
            case 0xF807: return -66;
            case 0xF808: return -130;
            case 0xF811: return -1;
            case 0xF812: return 1;
            case 0xF813: return 3;
            case 0xF814: return 7;
            case 0xF815: return 15;
            case 0xF816: return 31;
            case 0xF817: return 63;
            case 0xF818: return 127;
            default:
                return UNKNOWN;
        }
    }

    /**
     * 解一帧。返回 {@code int[]{zoneX, zoneW, ptrX, d, total}}，解不出返回 null。
     *
     * 「解不出」的两种情况：
     *   1. 字幕里没有绿区或没有指针（不是 QTE 几何帧，比如结果文本）；
     *   2. 出现了表里没有的字形（资源包升级 / 新条图变体）—— 此时几何不可信，
     *      必须返回 null，**绝不猜**。
     */
    static int[] decode(String sub) {
        if (sub == null || sub.isEmpty()) {
            return null;
        }
        int x = 0;
        int zoneX = UNKNOWN, zoneW = 0, ptrX = UNKNOWN;
        for (int i = 0; i < sub.length(); i++) {
            int cp = sub.charAt(i);
            int a = advance(cp);
            if (a == UNKNOWN) {
                return null;                    // 未知字形 → 这帧解不可靠
            }
            if (zoneX == UNKNOWN && isJudge(cp)) {
                zoneX = x;
                zoneW = judgeW(cp);
            }
            if (ptrX == UNKNOWN && cp == POINTER) {
                ptrX = x;
            }
            x += a;
        }
        if (zoneX == UNKNOWN || ptrX == UNKNOWN) {
            return null;
        }
        return new int[]{zoneX, zoneW, ptrX, ptrX - zoneX, x};
    }

    /** 判定规则。g = decode() 的返回值。 */
    static boolean inZone(int[] g, String rule, int margin, int leadPx) {
        if (g == null) {
            return false;
        }
        int d = g[3] + leadPx;
        int w = g[1];
        if ("left".equals(rule)) {
            return d >= -margin && d <= w + margin;
        }
        if ("whole".equals(rule)) {
            return d >= -margin && d + POINTER_W <= w + margin;
        }
        return d + POINTER_HALF >= -margin && d + POINTER_HALF <= w + margin;   // center（默认）
    }

    // ==================================================================
    // ★ v0.3.0：C 形态的判定区 —— **底图里画好的彩色段** ★
    //
    //   A 形态的判定区是**独立绿区字形**（B012/B013/B014，45/36/27px 纯绿），所以
    //   decode() 能直接念出 zone_x。C 形态没有这个字形 —— 判定色**画在底图 PNG 里**，
    //   所以必须自带一张「底图 -> 色段」表。
    //
    //   表来源：app/_img_bars/*.png 像素实测（PNG 是 3x 分辨率，坐标已 /3）。
    //
    //   ★ 对齐常数 246（v0.3.0 现场标定，别再改回 256）★
    //     屏幕 x = (246 - 底图内容宽) + 图内坐标
    //     —— 即底图**内容右缘固定落在 x=246**，而不是"贴 cell（256）右缘"。
    //
    //     标定方法（app/_probe_fitO.py，跨全部会话、合并被切碎的局后 15 组）：
    //     取每组的**指针末值** ≈ 玩家按下那一刻，要求它落在「题目要求的颜色段」内。
    //     扫 O：**O=246 且零容差时唯一命中 12/15 组**（其余 3 组是"按下后游戏又演了几帧"）；
    //     放到 ±4px 容差则 15/15 全中，可行区间 [242,246]。
    //     用 256 会系统性右偏 10px；用 0（左对齐）则彩虹条（内容仅 120 宽）完全对不上
    //     （指针行程 125~215 全落在图外）。
    //
    //     ⚠️ 两类底图内容宽不同（184 / 120），只有「按内容宽右对齐」才能同时解释两者。
    //        左对齐 / 居中 / 固定偏移都无法同时成立。
    // ==================================================================

    /** 底图内容**右缘**在屏幕上的 x（实测标定值，见上）。 */
    static final int RIGHT_EDGE = 246;

    /** advance 空间的格宽（一帧进度条 = 一个 256px 的 glyph）。 */
    static final int CELL = 256;

    static final int C_RED = 0;
    static final int C_ORANGE = 1;
    static final int C_YELLOW = 2;
    static final int C_GREEN = 3;
    static final int C_LIGHTBLUE = 4;              // 浅蓝色 RGB(52,242,213)，旧称 teal/青色
    static final int C_BLUE = 5;                   // 深蓝色 RGB(82,132,218)
    static final int C_PURPLE = 6;

    /** 底图内容宽（1x 像素）；未知返回 0。 */
    static int barW(int cp) {
        switch (cp) {
            case 0xB002: case 0xB003: case 0xB004: case 0xB005:
            case 0xB006: case 0xB007: case 0xB008: case 0xB009:
            case 0xB00A:
                return 184;
            case 0xB00B:
                return 120;                       // bar_rainbow（七色）
            case 0xB00C:
                return 163;                       // bar10（A 形态底图，无判定色）
            case 0xB011:
                return 222;                       // bar11（B 形态底图）
            default:
                return 0;
        }
    }

    /**
     * 底图色段表：每行 {@code {start, end, color}}，**图内坐标**（1x）。
     * 返回 null = 该底图没有判定色段（bar10 / bar11）。
     *
     * <p>bar1..bar9 是「红->绿->红」的对称渐变，判定区（绿色）在中间；彩虹条是七色等宽。
     * ⚠️ 这些区间是**像素分类**结果（阈值判定），边界有 ±2px 过渡，不能当硬边界用。
     */
    static int[][] barSegs(int cp) {
        switch (cp) {
            case 0xB002: return new int[][]{{84, 100, C_GREEN}};                                     // bar1
            case 0xB003: return new int[][]{{52, 68, C_GREEN}};                                      // bar2
            case 0xB004: return new int[][]{{116, 132, C_GREEN}};                                    // bar3
            case 0xB005: return new int[][]{{84, 92, C_GREEN}, {132, 140, C_GREEN}};                 // bar4
            case 0xB006: return new int[][]{{4, 12, C_GREEN}, {60, 68, C_GREEN},
                                           {108, 116, C_GREEN}, {140, 148, C_GREEN}};                // bar5
            case 0xB007: return new int[][]{{68, 76, C_GREEN}, {84, 92, C_GREEN},
                                           {100, 108, C_GREEN}};                                     // bar6 (=bar6.png)
            case 0xB008: return new int[][]{{156, 160, C_GREEN}};                                    // bar7
            case 0xB009: return new int[][]{{84, 88, C_GREEN}};                                      // bar8
            case 0xB00A: return new int[][]{{4, 8, C_GREEN}, {176, 180, C_GREEN}};                   // bar9
            // ★ rainbow = **七段**等宽 16px（红橙黄绿浅蓝深蓝紫）★
            //   旧的六段表把「橙+黄」并成了一段，会漏掉黄色题，已在 v0.3.0 修正。
            case 0xB00B: return new int[][]{{4, 20, C_RED}, {20, 36, C_ORANGE},
                                            {36, 52, C_YELLOW}, {52, 68, C_GREEN},
                                            {68, 84, C_LIGHTBLUE}, {84, 100, C_BLUE},
                                            {100, 116, C_PURPLE}};                               // bar_rainbow
            default:
                return null;
        }
    }

    /** 帧里出现的底图码点（B002..B00B）；没有返回 0。 */
    static int barId(String sub) {
        if (sub == null) {
            return 0;
        }
        for (int i = 0; i < sub.length(); i++) {
            int cp = sub.charAt(i);
            if (cp >= 0xB002 && cp <= 0xB00B) {
                return cp;
            }
        }
        return 0;
    }

    /**
     * 题目颜色名 -> 色段 id。缺省 = 绿色（bar1..bar9 只有绿色判定段，
     * 颜色题只出现在 rainbow 底图上）。
     */
    private static int colorId(String c) {
        if (c == null) {
            return C_GREEN;
        }
        switch (c) {
            case "red": return C_RED;
            case "orange": return C_ORANGE;
            case "yellow": return C_YELLOW;
            case "lightblue": case "cyan": case "teal": return C_LIGHTBLUE;   // 浅蓝色
            case "blue": case "darkblue": return C_BLUE;                     // 深蓝色
            case "purple": return C_PURPLE;
            default: return C_GREEN;
        }
    }

    /**
     * C 形态解码。返回 {@code int[]{ptrX, barCp, zStart, zEnd}}（z* 为**屏幕坐标**），
     * 解不出返回 null。{@code color} = 题目要求的颜色（null = 绿色）。
     */
    static int[] decodeC(String sub, String color) {
        if (sub == null || sub.isEmpty()) {
            return null;
        }
        int x = 0;
        int ptrX = UNKNOWN;
        int bar = 0;
        for (int i = 0; i < sub.length(); i++) {
            int cp = sub.charAt(i);
            int a = advance(cp);
            if (a == UNKNOWN) {
                return null;
            }
            if (ptrX == UNKNOWN && cp == POINTER) {
                ptrX = x;
            }
            if (bar == 0 && cp >= 0xB002 && cp <= 0xB00B) {
                bar = cp;
            }
            x += a;
        }
        if (ptrX == UNKNOWN || bar == 0) {
            return null;
        }
        int[][] segs = barSegs(bar);
        if (segs == null) {
            return null;
        }
        int want = colorId(color);
        int[] hit = null;
        for (int[] s : segs) {
            if (s[2] == want) {
                hit = s;
                break;
            }
        }
        if (hit == null) {
            return null;
        }
        int off = RIGHT_EDGE - barW(bar);          // ★ 246 标定，不是 256 ★
        return new int[]{ptrX, bar, off + hit[0], off + hit[1]};
    }

    /**
     * C 形态判定：**指针中心**是否落在判定色段内（含余量）。
     *
     * 为什么用「中心」而不是「整体相交」：标定常数有 ±4px 不确定度，
     * 而窄色段只有 5px 宽（bar8 绿段 84..88）—— 「相交」规则会把误差全摊到一侧，
     * 「中心」规则把误差摊到两侧，最坏情况下的距离更小。
     *
     * <p>余量 {@code margin} 默认 **0**（见 Config.cMargin）：20 局回放实测，
     * 余量 0 时 14/20 的按下点精确落在色段内；余量 2 掉到 6/20 —— 余量会把
     * 触发点整体**前移**，窄色段一前移就压到边界外。想更激进可调到 -2（更晚按）。
     */
    static boolean inZoneC(int[] c, int margin) {
        if (c == null) {
            return false;
        }
        int mid = c[0] + POINTER_HALF;
        return mid >= c[2] - margin && mid <= c[3] + margin;
    }
}
