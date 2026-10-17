package fishauto;

import java.util.Locale;

/**
 * QTE 信号判定：把「界面上的文字」翻译成状态机的输入。
 *
 * 全部结论来自实测数据（~/.fishprobe，108 局有效样本），不是猜的：
 *
 * 1. **是不是 QTE 帧**：字幕里出现韩文音节区码点（U+AC00–U+D7A3）即为真。
 *    服务器用 `customfishing:font/default.json` 把 U+B001..U+B014 映射成进度条贴图
 *    （U+B001=白色指针 / U+B002..B00C=底图 / U+B012..B014=绿区·简单45px·普通36px·困难27px），
 *    U+F8xx 是透明宽度占位。实测 100% 命中，无误报。
 *    ★ 注意：QTE 期间 **title 也在变**（单字模 U+B001.. 逐步推进，约 150ms 一跳），
 *      所以「标题变化」不能单独当开局信号 —— 必须用下面的 reqKey 过滤。
 *
 * 2. **要求按什么键**：标题文本形如「按下 <键> 开始」。
 *    实测出现过「左键」（对应 Options.keyAttack）、「左Shift」（对应 keyShift）；
 *    **采集数据里 0 条「右键」**（所谓"未知按键"的 27 局，复查后是 gap 切局把一局切碎了，
 *    尾部片段丢掉了标题，不是第三种键；见 qtemap.py --list）。
 *    这里仍然把右键/空格一并支持，代价为零，且你提到过可能存在右键形态。
 *
 * 3. **结果**：以**游戏自带反馈文本**为准（人工打点实测有漏标/错标）。
 *    下表的「命中率」是在 108 局上逐局关联统计出来的（见 /tmp/_corr.py 的等价分析）：
 *
 *    | 文本 | 出现在 | 关联 |
 *    |---|---|---|
 *    | `You caught a(n) …` | actionbar / subtitle | 成功 61/61 |
 *    | `Whoa! Nice catch!` | subtitle | 成功 |
 *    | `GG!` | title | 成功 28/28 |
 *    | `Good Job!` | title | 成功 33/33 |
 *    | `The fish escaped...` | subtitle | 失败 37/37 |
 *    | `What a pity!` | title | 失败 14/14 |
 *    | `Be concentrated!` | title | 失败 11/11（与 escaped 同时出现，不是过程提示） |
 *    | `Bad luck` / `Try next time!` | title | 失败 |
 *
 *    ⚠️ 早期版本把 `Good Job!` / `Be concentrated!` 当"过程提示"，是错的 ——
 *      它们与成败 **100% 相关**，应当直接作为结果。
 *
 *    过程提示（不算结果）：`Let's see what it is!`、`Oh <鱼> here we go!`、
 *    `好机会，保持冷静！`、`距离收竿只差一步！`、`抓紧竿子，鱼就在钩上！`
 */
final class Qte {
    private Qte() {
    }

    static final String KEY_LEFT = "left";
    static final String KEY_RIGHT = "right";
    static final String KEY_SHIFT = "shift";
    static final String KEY_JUMP = "jump";
    static final String KEY_UNKNOWN = "unknown";

    static final String HIT = "hit";
    static final String MISS = "miss";
    static final String WARN = "warn";

    // ---- ★ v0.2.1：帧形态 ★ ----
    static final String FORM_A = "A";          // 指针 + 绿区，点按型（几何可解）
    static final String FORM_C = "C";          // 指针、无绿区，颜色题（需按住）
    static final String FORM_B = "B";          // 无指针，只有挣扎动画图标
    static final String FORM_UNKNOWN = "?";    // 都不是

    /** 进度条字模所在码点范围（插件把进度条做进了韩文音节区）。 */
    static boolean isBarChar(int cp) {
        return cp >= 0xAC00 && cp <= 0xD7A3;
    }

    /** 透明宽度占位（剑魂资源包 space 字体）。 */
    static boolean isSpacer(int cp) {
        return cp >= 0xF800 && cp <= 0xF8FF;
    }

    /** 这一帧是不是 QTE 帧（字幕里有没有进度条字模）。 */
    static boolean isQteFrame(String sub) {
        if (sub == null) {
            return false;
        }
        for (int i = 0; i < sub.length(); i++) {
            if (isBarChar(sub.charAt(i))) {
                return true;
            }
        }
        return false;
    }

    /** 这一帧里进度条元素个数（用于统计/诊断）。 */
    static int barCount(String sub) {
        if (sub == null) {
            return 0;
        }
        int n = 0;
        for (int i = 0; i < sub.length(); i++) {
            if (isBarChar(sub.charAt(i))) {
                n++;
            }
        }
        return n;
    }

    /**
     * ★ v0.2.1：帧形态判定 ★
     *
     * <pre>
     *   A —— 指针(U+B001) + 绿区(U+B012..B014)：点按型，几何可解        80 局 / 60.6%
     *   C —— 指针(U+B001) 但**没有绿区**：判定色画在底图里，是颜色题     26 局 / 19.7%
     *   B —— **没有指针**，只有 U+B011 + 鱼图标(U+B00D..B010)：挣扎动画   26 局 / 19.7%
     *   ? —— 都不是（残缺帧）
     * </pre>
     *
     * 数字来自**全量 132 局**重扫（app/_probe_form_rule.py），并且
     * **局内形态 100% 单一、混合局 0 个** —— 形态是「按局固定」的。
     *
     * ★ 判据成立的关键前提（实测）★
     *   B 形态的局里**一次都没有出现过 U+B001**。这是它与 C 唯一的区分点 ——
     *   因为 `icons` 字体里 U+B001 也叫「进度图标 1」，万一 B 局用到它就会被误判成 C。
     *   132 局实测 0 次，所以这个顺序（先判指针、再判图标）是安全的。
     *
     * ⚠️ 现在它**只用于日志标注**，不参与按键决策 —— 分流要等 C 形态的
     *    「按住/点按」玩法确认后再做。
     */
    static String form(String sub) {
        if (sub == null || sub.isEmpty()) {
            return FORM_UNKNOWN;
        }
        boolean ptr = false;
        boolean zone = false;
        boolean icon = false;
        for (int i = 0; i < sub.length(); i++) {
            int cp = sub.charAt(i);
            if (cp == 0xB001) {
                ptr = true;                        // 指针（default）／进度图标 1（icons）
            } else if (cp >= 0xB012 && cp <= 0xB014) {
                zone = true;                       // 绿区：easy / normal / hard
            } else if (cp == 0xB011 || (cp >= 0xB00D && cp <= 0xB010)) {
                icon = true;                       // 挣扎动画：bar11 + 鱼图标
            }
        }
        if (ptr) {
            return zone ? FORM_A : FORM_C;
        }
        return icon ? FORM_B : FORM_UNKNOWN;
    }

    /**
     * 从标题里抽「按下 <键> 开始」的 `<键>`，归一到 KEY_* 常量。
     * 认不出返回 null（= 这句话不是开始提示）。
     */
    static String reqKey(String title) {
        if (title == null || title.isEmpty()) {
            return null;
        }
        String start = "\u5f00\u59cb";                        // 开始
        String press = "\u6309\u4e0b";                        // 按下
        if (title.indexOf(start) < 0 || title.indexOf(press) < 0) {
            return null;
        }
        String core = title;
        int a = core.indexOf(press);
        int b = core.indexOf(start, a);
        if (a >= 0 && b > a) {
            core = core.substring(a + press.length(), b);
        }
        return norm(core);
    }

    /**
     * ★ v0.3.0：标题是不是在说「该收杆了」★
     *
     * 实测有一类局标题是「在关键时刻收杆」（无「按下 X 开始」），
     * 按玩家口径它属于**右键收杆型**；此时 {@link #reqKey} 会返回 null，
     * 若不做这个补认，整个 code path 会退化成 KEY_UNKNOWN → 一次都不按（press_skip）。
     */
    static boolean reelHint(String title) {
        return title != null && title.indexOf("\u6536\u7aff") >= 0;      // 收杆
    }

    /** 把任意描述按键的文本归一成 KEY_*。 */
    static String norm(String s) {
        if (s == null) {
            return null;
        }
        String t = s.toLowerCase();
        boolean right = t.contains("\u53f3") || t.contains("right");      // 右
        boolean left = t.contains("\u5de6") || t.contains("left");        // 左
        if (t.contains("shift")) {
            if (right) {
                return KEY_SHIFT;                 // 右Shift 暂按 shift 处理
            }
            return KEY_SHIFT;
        }
        if (t.contains("\u952e") || t.contains("\u51fb") || t.contains("mouse")) {  // 键 / 击
            if (right) {
                return KEY_RIGHT;
            }
            if (left) {
                return KEY_LEFT;
            }
        }
        if (t.contains("\u7a7a\u683c") || t.contains("space")) {          // 空格
            return KEY_JUMP;
        }
        if (right) {
            return KEY_RIGHT;
        }
        if (left) {
            return KEY_LEFT;
        }
        return KEY_UNKNOWN;
    }

    // ---- ★ v0.3.0：C 形态的「颜色题」★ ----
    /**
     * 题目要求的颜色。C 形态的 rainbow 底图是**七色等宽长条**
     * （红 橙 黄 绿 浅蓝 深蓝 紫，各 16px），开局 title 直接给题面，
     * 实测出现过 `绿色!` / `浅蓝色!` / `深蓝色!`（各若干局）。
     * 指针走到该颜色段时按键。没有颜色题返回 null（= 按默认的绿色段判）。
     *
     * ⚠️ 判定顺序不能乱：`浅蓝色` / `深蓝色` 都**包含**「蓝色」，
     *    必须先匹配「浅蓝」「深蓝」再匹配「蓝」，否则会一律退化成 blue。
     */
    static String colorAsk(String title) {
        if (title == null || title.isEmpty()) {
            return null;
        }
        // ---- 先长后短，避免"浅蓝色"被"蓝色"抢先命中 ----
        if (title.indexOf("\u6d45\u84dd\u8272") >= 0) {      // 浅蓝色
            return "lightblue";
        }
        if (title.indexOf("\u6df1\u84dd\u8272") >= 0) {      // 深蓝色
            return "blue";
        }
        if (title.indexOf("\u7eff\u8272") >= 0) {            // 绿色
            return "green";
        }
        if (title.indexOf("\u7d2b\u8272") >= 0) {            // 紫色
            return "purple";
        }
        if (title.indexOf("\u7ea2\u8272") >= 0) {            // 红色
            return "red";
        }
        if (title.indexOf("\u6a59\u8272") >= 0) {            // 橙色
            return "orange";
        }
        if (title.indexOf("\u9ec4\u8272") >= 0) {            // 黄色
            return "yellow";
        }
        if (title.indexOf("\u9752\u8272") >= 0) {            // 青色（= 浅蓝同段）
            return "lightblue";
        }
        if (title.indexOf("\u84dd\u8272") >= 0) {            // 蓝色（兜底）
            return "blue";
        }
        return null;
    }

    /** 结果/提示分类。null = 与钓鱼无关的文本。 */
    static String classify(String text) {        if (text == null || text.isEmpty()) {
            return null;
        }
        String raw = text.trim();
        String t = raw.toLowerCase(Locale.ROOT);

        // ---- 成功（108 局实测全部 100% 相关）----
        if (t.contains("caught")                       // You caught a(n) <鱼> [which is ..cm long!]
                || t.contains("nice catch")            // Whoa! Nice catch!
                || t.contains("good job")              // Good Job!
                || t.equals("gg!") || t.startsWith("gg!")   // GG!
                || raw.contains("\u9493\u5230")        // 钓到
                || raw.contains("\u9493\u4e0a")        // 钓上
                || raw.contains("\u6536\u7aff\u6210\u529f")) {   // 收杆成功
            return HIT;
        }

        // ---- 失败 ----
        if (t.contains("escaped")                      // The fish escaped...
                || t.contains("pity")                  // What a pity!
                || t.contains("be concentrated")       // Be concentrated!（与 escaped 同时出现）
                || t.contains("bad luck")              // Bad luck
                || t.contains("try next time")         // Try next time!
                || raw.contains("\u8dd1\u6389")        // 跑掉
                || raw.contains("\u8dd1\u4e86")        // 跑了
                || raw.contains("\u8131\u94a9")        // 脱钩
                || raw.contains("\u53ef\u60dc")        // 可惜
                || raw.contains("\u9003\u6389")) {     // 逃掉
            return MISS;
        }

        // ---- 过程提示（不算结果，只记证据）----
        if (t.contains("here we go")                   // Oh <鱼> here we go!
                || t.contains("let's see what it is")  // Let's see what it is!
                || raw.contains("\u4fdd\u6301\u51b7\u9759")     // 保持冷静
                || raw.contains("\u597d\u673a\u4f1a")           // 好机会
                || raw.contains("\u53ea\u5dee\u4e00\u6b65")     // 只差一步
                || raw.contains("\u6293\u7d27\u7aff\u5b50")) {  // 抓紧竿子
            return WARN;
        }
        return null;
    }

    /** 只保留「可读」文本（滤掉纯字模帧，否则日志会被进度条刷爆）。 */
    static boolean readable(String s) {
        if (s == null || s.isEmpty()) {
            return false;
        }
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (!isBarChar(c) && !isSpacer(c)) {
                return true;
            }
        }
        return false;
    }
}
