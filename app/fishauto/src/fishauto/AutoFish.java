package fishauto;

/**
 * 状态机：方块传说「钓鱼岛屿」收杆 QTE 的第一版自动玩家。
 *
 * <pre>
 *   IDLE ──标题**刚变成**「按下 X 开始」/ 字幕出现进度条字模──> QTE
 *   QTE  ──按 X 连按（默认 130ms 一次）──────────────────> 读到自带反馈 / 帧超时
 *   有结果 ──> 立即记 qte_end 并回 IDLE
 *   无结果 ──> SETTLE 再等 2s（结果文本常晚一瞬） ──> 记 qte_end 回 IDLE
 * </pre>
 *
 * ★ v0.2 新增：geometry 策略（看指针进绿区才按）★
 *   v0.1 只能连按，是因为当时没解出指针位置 —— 根因是把活动资源包认错了，
 *   并且把韩文音节区的 B0xx 字模当成「全宽格 advance=8」。
 *   实测（见 app/report/qte-geometry-report.md）：
 *     - 活动包 = 服务器材质10.2.zip（从 options.txt 推导，剑魂包根本没启用）；
 *     - B0xx -> customfishing:default，F8xx -> customfishing:offset_chars（**带符号**位偏移）；
 *     - advance = (imgW/cols) * (height/(imgH/rows)) + spacing；
 *     - 指针 x 与绿区 x 由此可精确解出（easy 局首帧：zone_x=143, zone_w=45, ptr_x=73, d=-70）。
 *   判定规则经规则扫描选型：center（指针中心入区）+ 余量 8px 分离度最优
 *   （HIT 局 0.380 vs FAIL 局 0.206，全帧基线 0.464）。
 *   ⚠️ 诚实结论：人工按键的 in-zone 比例**不高于**全帧基线（玩家本来就在连按），
 *      所以「进绿区才按」没有从人工数据里得到强证明 —— geometry 默认**不开**，
 *      strategy 默认仍是 cadence（= v0.1 行为），要试必须显式改配置。
 *
 * ★ v0.2.1 新增：咬钩观测 + 形态标注（**都不改按键行为**）★
 *   - 配置 `bite_log`（默认 false）→ 边沿记录 `hook_bite` / `hook_clear`，
 *     用来实测 `player.fishing.biting` 在本服是否真的会被驱动；
 *   - frame 日志新增 `form` 字段（A / C / B），三形态实测**局内 100% 单一**。
 *   两者都是**追加**：strategy 默认仍是 cadence，按键行为与 v0.2.0 逐字一致。
 *
 * ★ v0.3.0：完整钓鱼循环 + 三形态分流（**默认仍然全关**）★
 *   用户的真实流程：右键抛竿 -> 鱼咬钩 -> 右键收杆 -> 小游戏 -> 上鱼 -> 循环。
 *   本轮把这条链补齐，并把"按节拍"彻底换掉：
 *   <pre>
 *     没抛竿 ─[auto_cast]─> 右键抛竿 ─> 等咬钩 ─[reel_on_bite]─> 右键收杆 ─> 小游戏
 *   </pre>
 *   - **为什么不能按节拍**：实测上鱼时间**随机不固定**（9~11s 只是均值），
 *     而且**一旦重新抛竿，计时就重置** —— 节拍法只会越走越偏。
 *     `player.fishing.biting` 是服务端同步的真信号，咬钩 -> 开局只隔 300~360ms。
 *   - **形态分流**（三种小游戏，实测局内 100% 单一）：
 *     A（指针 + 独立绿区字形，60%）→ geometry：指针进绿区才按；
 *     C（有指针，判定色**画在底图里**，20%）→ 底图色段判定（form_strategy=auto 才启用）；
 *     B（无指针，只有鱼图标 + 挣扎动画，20%）→ **不按**（当前无可靠信号，硬按必输）。
 *   - 新增观测字段：`frame` 带 `bar/cptr/czone/tcp`，`qte_begin` 带 `form`，
 *     新事件 `reel` / `form_skip`。**观测字段只增不改**，老字段语义不变。
 *
 * ★ 安全性（默认全关）★
 *   - 默认 `enabled=false` + `dry_run=true` + `strategy=cadence`：装上去什么都不做。
 *   - 只写原版 KeyMapping 字段 ⇒ 等价于玩家按键；不碰 OS 键鼠、不装钩子、不抢光标。
 *   - 标题只在**发生变化的当刻**作为开局触发（`Gui.title` 会驻留很久，
 *     不判变化会把一局当成很多局）。
 *   - 有界面（聊天/背包/Esc）打开时绝不按键。
 *   - 单局按键次数上限；`~/.fishauto/STOP` = 急停（仍记录，不再按键）。
 *   - 任何 Throwable 都不许带进游戏主循环。
 */
final class AutoFish {
    private AutoFish() {
    }

    static final String S_IDLE = "idle";
    static final String S_QTE = "qte";
    static final String S_SETTLE = "settle";

    // ★ v0.3.0：外层「钓鱼循环」状态 ★
    //   idle   = 没抛竿（等自动抛竿）
    //   casted = 已抛竿、浮标在水里（等咬钩）
    //   reeled = 已收杆（等小游戏出现 / 或本局作废）
    static final String L_IDLE = "idle";
    static final String L_CASTED = "casted";
    static final String L_REELED = "reeled";

    static String state = S_IDLE;
    static int games;
    static int presses;
    static int frames;
    static int unknownKeyGames;
    static int pressesThisGame;

    static long qteStartWall;
    static long lastQteFrameWall;
    static long lastPressWall;
    static long settleUntil;
    static long lastCastWall;
    static long lastHeartbeat;

    static String reqKey;
    static String lastSub = "";
    static String lastTitle = "";
    static String lastAction = "";
    static String lastResult = "";
    static String lastCfg = "";

    static boolean inWorld;
    static boolean halted;
    static long ticks;
    static boolean geomSkipLogged;
    // ★ v0.2.1：咬钩观测状态 ★
    static boolean lastBiting;
    static boolean biteSeen;
    static long biteAt;
    // ★ v0.3.0：外层循环 / 形态分流 ★
    static String loop = L_IDLE;
    static long reeledBiteAt;          // 已经为「哪一次咬钩」收过杆（防重复）
    static int reels;
    static int formSkips;
    static String lastForm = "";
    /**
     * C 形态的**题目颜色**（red/orange/.../blue/purple，null = 还没读到）。
     * 开局时从 title 读一次并锁定 —— title 中途会变（比如变成结果文本），
     * 每帧现读会把题面读丢；而题面在小游戏一开始就给出了（实测 4/4 局成立）。
     */
    static String formColor;

    public static void tick() {
        try {
            Config.maybeReload();
            if (!Presser.attach()) {
                return;
            }
            // 松手回位永远要做，哪怕已经 OFF —— 否则可能把 Shift 卡住
            Presser.tickRelease();

            if (Sink.isOff()) {
                return;
            }
            ticks++;

            if (Presser.level() == null) {
                if (inWorld) {
                    inWorld = false;
                    log("{\"type\":\"world_leave\"}");
                    Sink.close();
                }
                reset();
                return;
            }
            if (!inWorld) {
                inWorld = true;
                Sink.openSession("auto");
                reset();
                lastCfg = "";
                logConf();
            }
            // ★ v0.2.1：咬钩观测刻意放在总开关**之前** ★
            //   它与 enabled 无关 —— 于是「enabled=false + bite_log=true」就是
            //   纯粹观测模式：一个键都不按，只看浮标咬不咬钩。
            watchBite(Sink.wall());
            if (!Config.enabled) {
                return;
            }
            if (!Config.describe().equals(lastCfg)) {
                logConf();
            }
            long now = Sink.wall();
            loopTick(now);                        // ★ v0.3.0：外层钓鱼循环

            String title = Presser.uiText(Presser.UI_TITLE);
            String sub = Presser.uiText(Presser.UI_SUBTITLE);
            String act = Presser.uiText(Presser.UI_ACTION);

            boolean subChanged = !sub.equals(lastSub);
            boolean titleChanged = !title.equals(lastTitle);
            boolean actChanged = !act.equals(lastAction);
            lastSub = sub;
            lastTitle = title;
            lastAction = act;

            // ---------- 1. 结果识别（游戏自带反馈优先）----------
            // ★ 三处都要扫 ★ 实测（108 局）：
            //   actionbar 给 `You caught a(n) … which is ..cm long!`
            //   subtitle  给 `The fish escaped...` / `You caught a(n) …` / `Whoa! Nice catch!`
            //   title     给 `GG!` / `Good Job!` / `What a pity!` / `Be concentrated!`
            //   漏掉任何一处都会漏掉一部分成败判定。
            if (actChanged && Qte.readable(act)) {
                noteText("actionbar", act, now);
            }
            if (titleChanged && Qte.readable(title)) {
                noteText("title", title, now);
            }
            if (subChanged && Qte.readable(sub)) {
                noteText("subtitle", sub, now);
            }

            // ---------- 2. 结果已明 -> 收尾 ----------
            if (S_QTE.equals(state)
                    && (Qte.HIT.equals(lastResult) || Qte.MISS.equals(lastResult))) {
                endGame(lastResult, now);
            }
            if (S_SETTLE.equals(state)) {
                settle(now);
                return;
            }

            // ---------- 3. 开局判定 ----------
            if (S_IDLE.equals(state)) {
                String rk = Qte.reqKey(title);
                boolean frame = Qte.isQteFrame(sub);
                // ★ 两者都必须「刚变化」★
                //   Gui.title 与 subtitle 都会驻留：不判变化，一局会被判成很多局；
                //   而 QTE 期间 title 自己是单字模在跳（实测约 150ms 一跳），
                //   所以 title 侧必须再用 reqKey 过滤掉那些非「按下 X 开始」的变化。
                if ((rk != null && titleChanged) || (frame && subChanged)) {
                    begin(rk, title, sub, now, frame && subChanged ? "frame" : "title");
                } else {
                    heartbeat(now);            // 抛竿/收杆已由 loopTick 统一负责
                    return;
                }
            }

            // ---------- 4. QTE 中 ----------
            if (S_QTE.equals(state)) {
                // ★ 局内补认按键 ★
                //   实测（108 局）按键种类**每局随机**（左键 26 / 左Shift 68，无规律交替），
                //   所以绝不能沿用上一局的键。而进度条帧有可能比「按下 X 开始」标题早到一 tick，
                //   那时我们是以 unknown 开局的；一旦标题补到，立刻改认，否则整局都不会按键。
                if (Qte.KEY_UNKNOWN.equals(reqKey) && titleChanged) {
                    String late = Qte.reqKey(title);
                    if (late != null) {
                        reqKey = late;
                        log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                                + ",\"type\":\"key_upgrade\",\"game\":" + games
                                + ",\"key\":\"" + Sink.esc(late)
                                + "\",\"title\":\"" + Sink.esc(title) + "\"}");
                    }
                }
                if (Qte.isQteFrame(sub)) {
                    lastQteFrameWall = now;
                    if (subChanged) {
                        frames++;
                        if (Config.logFrames) {
                            // 几何字段只增不改：v0.1 的字段语义保持不变
                            int[] g = Geom.decode(sub);
                            log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                                    + ",\"type\":\"frame\",\"n\":" + frames
                                    + ",\"sub\":\"" + Sink.esc(sub) + "\""
                                    + ",\"form\":\"" + Qte.form(sub) + "\""
                                    + ",\"tcp\":\"" + codePoints(title) + "\""
                                    + geomJson(g) + cJson(Geom.decodeC(sub, null)) + "}");
                        }
                    }
                }
                if (now - lastQteFrameWall > Config.idleTimeoutMs) {
                    endGame("", now);          // 走到 SETTLE 再等一瞬结果
                } else {
                    decidePress(sub, now);
                }
            }
            heartbeat(now);
        } catch (Throwable t) {
            // 绝不允许异常进入游戏主循环
        }
    }

    // ------------------------------------------------------------------ 各步
    private static void begin(String rk, String title, String sub, long now, String trigger) {
        if (rk == null && Qte.reelHint(title)) {
            // 「在关键时刻收杆」这类题面里没有「按下 X 开始」，
            // 但按玩家口径它就是**右键收杆型** —— 不补认的话整局只会记 press_skip。
            rk = Qte.KEY_RIGHT;
        }
        state = S_QTE;
        reqKey = rk == null ? Qte.KEY_UNKNOWN : rk;
        qteStartWall = now;
        lastQteFrameWall = now;
        lastPressWall = 0;                 // 立刻允许第一次按键
        pressesThisGame = 0;
        frames = 0;
        lastResult = "";
        geomSkipLogged = false;
        formSkips = 0;
        lastForm = "";                     // ★ v0.3.0：清空，好让 form_skip 判"本局首次遇到 B"
        formColor = Qte.colorAsk(title);   // ★ C 形态题面（null = 本局无颜色题，按绿段判）
        games++;
        if (Qte.KEY_UNKNOWN.equals(reqKey)) {
            unknownKeyGames++;
        }
        log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                + ",\"type\":\"qte_begin\",\"game\":" + games
                + ",\"by\":\"" + trigger + "\",\"key\":\"" + Sink.esc(reqKey)
                + "\",\"form\":\"" + Qte.form(sub)
                + "\",\"color\":\"" + (formColor == null ? "" : formColor)
                + "\",\"title\":\"" + Sink.esc(title)
                + "\",\"sub\":\"" + Sink.esc(sub)
                + "\",\"bite_ago_ms\":" + (biteSeen ? (now - biteAt) : -1) + "}");
    }

    /** 结果为空 = 超时未定，进 SETTLE 再等一瞬。 */
    private static void endGame(String result, long now) {
        if (Qte.HIT.equals(result) || Qte.MISS.equals(result)) {
            logEnd(result, now);
            state = S_IDLE;
            lastResult = "";
        } else {
            state = S_SETTLE;
            settleUntil = now + 2000;
        }
        pressesThisGame = 0;
        frames = 0;
    }

    /** SETTLE：迟到的结果文本还能挂到本局上。 */
    private static void settle(long now) {
        if (Qte.HIT.equals(lastResult) || Qte.MISS.equals(lastResult)) {
            logEnd(lastResult, now);
            state = S_IDLE;
            lastResult = "";
        } else if (now > settleUntil) {
            logEnd("(未捕获结果)", now);
            state = S_IDLE;
        }
        if (S_IDLE.equals(state) && Config.maxGames > 0 && games >= Config.maxGames) {
            halted = true;
            log("{\"type\":\"halted\",\"reason\":\"达到 max_games=" + Config.maxGames + "\"}");
        }
        heartbeat(now);                        // 抛竿已由 loopTick 统一负责
    }

    private static void logEnd(String result, long now) {
        log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                + ",\"type\":\"qte_end\",\"game\":" + games
                + ",\"key\":\"" + Sink.esc(reqKey) + "\",\"result\":\"" + Sink.esc(result)
                + "\",\"presses\":" + pressesThisGame + ",\"frames\":" + frames
                + ",\"ms\":" + (now - qteStartWall) + "}");
    }

    /** geometry 帧的几何字段（zone_x/zone_w/ptr_x/d）；解不出记 geom_ok=false。 */
    private static String geomJson(int[] g) {
        if (g == null) {
            return ",\"geom_ok\":false";
        }
        return ",\"geom_ok\":true,\"zone_x\":" + g[0] + ",\"zone_w\":" + g[1]
                + ",\"ptr_x\":" + g[2] + ",\"d\":" + g[3];
    }

    /** C 形态几何字段（底图 + 指针 + 判定色段屏幕坐标）。 */
    private static String cJson(int[] c) {
        if (c == null) {
            return ",\"c_ok\":false";
        }
        return ",\"c_ok\":true,\"bar\":" + c[1] + ",\"cptr\":" + c[0]
                + ",\"czone\":[" + c[2] + "," + c[3] + "]";
    }

    /**
     * 私有区码点摘要（十六进制，逗号分隔，跳过普通 ASCII）——
     * ★ v0.3.0：主要是给 **B 形态**找信号用（它的 sub 只有 bar11 + 鱼图标，
     * 进度可能藏在 title 的 icons 字模里，而 title 平时是"不可读"的，不进 notice 日志）。
     */
    private static String codePoints(String s) {
        if (s == null || s.isEmpty()) {
            return "";
        }
        StringBuilder sb = new StringBuilder(s.length() * 4);
        for (int i = 0; i < s.length(); i++) {
            int cp = s.charAt(i);
            if (cp >= 0x20 && cp < 0x7F) {
                continue;
            }
            if (sb.length() > 0) {
                sb.append(',');
            }
            sb.append(Integer.toHexString(cp));
        }
        return sb.toString();
    }

    /**
     * ★ v0.3.0：按形态分流 ★
     * <pre>
     *   A（指针 + 独立绿区字形）      -> decideA（strategy: cadence 连按 / geometry 进绿区才按）
     *   C（有指针，判定色画在底图里）  -> decideC（form_strategy=auto 才按，默认只观测）
     *   B（无指针，只有鱼图标 + 挣扎动画）-> **不按**（当前没有可靠信号，硬按必输）
     * </pre>
     */
    private static void decidePress(String sub, long now) {
        if (pressesThisGame >= Config.maxPressPerGame) {
            return;
        }
        String form = Qte.form(sub);
        if (Qte.FORM_B.equals(form)) {
            if (!Qte.FORM_B.equals(lastForm)) {
                lastForm = Qte.FORM_B;
                formSkips++;
                log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                        + ",\"type\":\"form_skip\",\"game\":" + games
                        + ",\"form\":\"B\",\"reason\":\"无指针，无可靠信号，本局不按键\"}");
            }
            return;
        }
        if (Qte.FORM_C.equals(form)) {
            if (Config.formAuto()) {
                decideC(sub, now);
            }
            return;                        // observe（默认）：只标注形态，绝不按键
        }
        decideA(sub, now);
    }

    /** A 形态（或形态未定）：沿用既有 strategy。 */
    private static void decideA(String sub, long now) {
        boolean holdKey = Qte.KEY_SHIFT.equals(reqKey) || Qte.KEY_JUMP.equals(reqKey);
        // 按住类：正在按住、或刚松开还在强制间隔时不再发下一次
        // （否则每秒都会把「按住」重新续期，游戏看到的是一条长按，而不是连点）
        if (holdKey && Presser.busy()) {
            return;
        }
        // cadence_ms 双重身份：cadence 模式 = 连按间隔；geometry 模式 = 两次按下的最小冷却
        if (now - lastPressWall < Config.cadenceMs) {
            return;
        }
        // ---------- geometry 策略：指针进绿区才按 ----------
        if (Config.geometry()) {
            int[] g = Geom.decode(sub);
            if (g == null) {
                if (!geomSkipLogged) {
                    geomSkipLogged = true;
                    log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                            + ",\"type\":\"geom_skip\",\"game\":" + games
                            + ",\"reason\":\"帧解不出几何（缺绿区/指针或出现未知字形），"
                            + "geometry 策略本局不会按键\"}");
                }
                return;                    // 几何不可信 → 绝不猜，宁可不动
            }
            boolean fire = Geom.inZone(g, Config.geoRule, Config.geoMargin, Config.geoLeadPx);
            if (!fire) {
                return;                    // 指针不在绿区：不按（这正是 geometry 的意义）
            }
        }
        if (Presser.screenOpen()) {
            return;                       // 有界面打开：绝不动键盘鼠标
        }
        Object kb = Presser.byName(reqKey);
        boolean allowed = keyAllowed(reqKey);
        lastPressWall = now;
        pressesThisGame++;
        if (kb == null || !allowed) {
            log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                    + ",\"type\":\"press_skip\",\"key\":\"" + Sink.esc(reqKey)
                    + "\",\"n\":" + pressesThisGame + "}");
            return;
        }
        if (Config.dryRun || halted || Sink.isStopped()) {
            log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                    + ",\"type\":\"press_dry\",\"key\":\"" + Sink.esc(reqKey)
                    + "\",\"n\":" + pressesThisGame
                    + geomJson(Geom.decode(sub))
                    + ",\"sub\":\"" + Sink.esc(sub) + "\"}");
            return;
        }
        boolean ok;
        if (holdKey) {
            ok = Presser.hold(kb, Config.holdTicks);
        } else {
            ok = Presser.tap(kb);
        }
        presses++;
        log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                + ",\"type\":\"press\",\"key\":\"" + Sink.esc(reqKey)
                + "\",\"n\":" + pressesThisGame + ",\"ok\":" + ok
                + geomJson(Geom.decode(sub))
                + ",\"sub\":\"" + Sink.esc(sub) + "\"}");
    }

    /** 这个键是否被配置允许（use_left / use_right / use_shift）。 */
    private static boolean keyAllowed(String key) {
        return (Qte.KEY_LEFT.equals(key) && Config.useLeft)
                || (Qte.KEY_RIGHT.equals(key) && Config.useRight)
                || (Qte.KEY_SHIFT.equals(key) && Config.useShift)
                || (Qte.KEY_JUMP.equals(key) && Config.useShift);
    }

    /**
     * ★ v0.3.0：C 形态 ★ —— 判定区**画在底图上**（没有独立绿区字形），
     * 所以用 {@link Geom#decodeC} 解指针位置 + 底图色段，指针进色段才按。
     *
     * <p>键：C 的题面是提示语/颜色名，没有「按下 X 开始」，认不出 reqKey ——
     * 按玩家口径它**就是「右键收杆型」**，所以取 {@code Config.holdKey}（默认 right）；
     * 万一标题补到了显式键（key_upgrade），以标题为准。
     */
    private static void decideC(String sub, long now) {
        if (now - lastPressWall < Config.cadenceMs) {
            return;
        }
        if (Presser.screenOpen()) {
            return;
        }
        // 题面颜色：开局读一次并锁定（title 中途会变，每帧现读会把题面读丢）
        if (formColor == null) {
            formColor = Qte.colorAsk(Presser.uiText(Presser.UI_TITLE));
        }
        int[] c = Geom.decodeC(sub, formColor);
        if (c == null) {
            return;                       // 解不出：绝不猜
        }
        if (!Geom.inZoneC(c, Config.cMargin)) {
            return;                       // 指针还没进判定色段
        }
        String key = Qte.KEY_UNKNOWN.equals(reqKey) ? Config.holdKey : reqKey;
        Object kb = Presser.byName(key);
        lastPressWall = now;
        pressesThisGame++;
        if (kb == null || !keyAllowed(key)) {
            log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                    + ",\"type\":\"press_skip\",\"form\":\"C\",\"key\":\""
                    + Sink.esc(key) + "\",\"n\":" + pressesThisGame + "}");
            return;
        }
        if (Config.dryRun || halted || Sink.isStopped()) {
            log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                    + ",\"type\":\"press_dry\",\"form\":\"C\",\"key\":\""
                    + Sink.esc(key) + "\",\"n\":" + pressesThisGame
                    + ",\"ptr\":" + c[0] + ",\"zone\":[" + c[2] + "," + c[3] + "]"
                    + ",\"sub\":\"" + Sink.esc(sub) + "\"}");
            return;
        }
        boolean ok = Presser.tap(kb);
        presses++;
        log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                + ",\"type\":\"press\",\"form\":\"C\",\"key\":\""
                + Sink.esc(key) + "\",\"n\":" + pressesThisGame
                + ",\"ok\":" + ok + ",\"ptr\":" + c[0]
                + ",\"zone\":[" + c[2] + "," + c[3] + "]"
                + ",\"sub\":\"" + Sink.esc(sub) + "\"}");
    }

    /** 读到带语义的文本：登记结果 / 登记提示。 */
    private static void noteText(String where, String text, long now) {
        String c = Qte.classify(text);
        if (c == null) {
            log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                    + ",\"type\":\"notice\",\"where\":\"" + where
                    + "\",\"text\":\"" + Sink.esc(text) + "\"}");
            return;
        }
        if (Qte.HIT.equals(c) || Qte.MISS.equals(c)) {
            lastResult = c;
        }
        log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                + ",\"type\":\"signal\",\"where\":\"" + where + "\",\"kind\":\"" + c
                + "\",\"text\":\"" + Sink.esc(text) + "\"}");
    }

    private static void maybeCast(long now) {
        if (!Config.autoCast || Config.dryRun || halted || Sink.isStopped()) {
            return;
        }
        if (Presser.screenOpen() || now - lastCastWall < Config.castDelayMs) {
            return;
        }
        String hand = Presser.mainHand();
        if (hand == null || hand.indexOf("fishing_rod") < 0) {
            return;
        }
        if (Presser.casted()) {
            return;                       // 已经在等了，别把竿收回来
        }
        lastCastWall = now;
        boolean ok = Presser.tap(Presser.kbUse());
        log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                + ",\"type\":\"cast\",\"ok\":" + ok + "}");
    }

    /**
     * ★ v0.3.0：外层「钓鱼循环」★
     *
     * <pre>
     *   没抛竿 ──[手上是鱼竿 & auto_cast]────────────> 右键抛竿    -> casted
     *   casted ──[biting 由 false 变 true & reel_on_bite]──> 右键收杆 -> reeled
     *   reeled ──[小游戏结束]──> 回 idle，隔 cast_delay_ms 再抛竿
     * </pre>
     *
     * 为什么**不能**用"按节拍"：实测**上鱼时间随机不固定**（9~11s 只是统计均值），
     * 而且**一旦重新抛竿计时就重置** —— 节拍法必然越走越偏。
     * 而 {@code player.fishing.biting} 是服务端同步下来的真信号，
     * 咬钩 -> 小游戏开局只隔 **300~360ms**（实测），用它收杆时序误差 &lt; 1 tick。
     *
     * QTE 期间（state != idle）**绝不抛竿**：那时浮标已经收回（hook == null），
     * 若不拦住，就会在小游戏里反复抛竿。
     */
    private static void loopTick(long now) {
        if (halted || Sink.isStopped()) {
            return;
        }
        // 小游戏进行中：浮标本来就没了，不能当成"没抛竿"
        if (S_QTE.equals(state) || S_SETTLE.equals(state)) {
            loop = L_REELED;
            return;
        }
        if (Presser.screenOpen()) {
            return;
        }
        if (!Presser.casted()) {
            loop = L_IDLE;
            reeledBiteAt = 0;
            maybeCast(now);
            return;
        }
        loop = L_CASTED;
        if (!Config.reelOnBite || !Presser.biteReady() || !Presser.hookBiting()) {
            return;
        }
        if (biteAt <= 0 || reeledBiteAt == biteAt) {
            return;                                  // 这次咬钩已经收过杆了
        }
        if (now - biteAt < Config.reelDelayMs) {
            return;                                  // 还没到计划收杆时刻
        }
        reeledBiteAt = biteAt;
        boolean ok = Presser.tap(Presser.kbUse());
        if (ok) {
            reels++;
        }
        loop = L_REELED;
        log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                + ",\"type\":\"reel\",\"ok\":" + ok + ",\"n\":" + reels
                + ",\"after_bite_ms\":" + (now - biteAt) + "}");
    }

    /**
     * ★ v0.2.1：咬钩信号观测 —— **只记录，不参与任何决策** ★
     *
     * 每 tick 读一次 {@code player.fishing.biting}（服务端同步字段），只在**边沿**写日志：
     * <pre>
     *   {"type":"hook_bite", ... "vy":-0.317, "since_begin_ms":-1}   咬钩从 false 跳到 true
     *   {"type":"hook_clear", ... "held_ms":820}                     咬钩结束
     * </pre>
     *
     * 为什么先观测、不直接拿它当开局触发：
     *   {@code biting} 由**原版服务端**的 {@code FishingHook.catchingFish()} 驱动，
     *   而本服是 CustomFishing 的自定义玩法 —— 理论上它可能被旁路。
     *   判据很简单：正常钓一局，日志里**一条 hook_bite 都没有** ⇒ 此路作废，回到文本触发；
     *   有 ⇒ 再看 {@code qte_begin} 上的 {@code bite_ago_ms}（咬钩比开局早多少毫秒）。
     *   背景与证据链见 app/report/qte-bite-detection-report.md。
     *
     * 与 {@code enabled} **无关**：只要 bite_log=true 就观测（哪怕总开关关着）。
     */
    private static void watchBite(long now) {
        if (!Presser.biteReady()) {
            return;
        }
        // ★ v0.3.0：reel_on_bite 也要用这个信号，所以它不再只服务于观测 ★
        if (!Config.biteLog && !Config.reelOnBite) {
            return;
        }
        if (Presser.hook() == null) {
            lastBiting = false;                  // 没抛竿/已收竿：清状态，不刷日志
            return;
        }
        boolean b = Presser.hookBiting();
        if (b == lastBiting) {
            return;                              // 只在边沿处理
        }
        lastBiting = b;
        if (b) {
            biteAt = now;
            biteSeen = true;
        }
        if (!Config.biteLog) {
            return;                              // 状态已更新，只是不写日志
        }
        double vy = Presser.hookVy();
        String v = Double.isNaN(vy) ? "null" : Sink.num(vy);
        if (b) {
            log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                    + ",\"type\":\"hook_bite\",\"game\":" + games
                    + ",\"vy\":" + v + ",\"state\":\"" + state + "\""
                    + ",\"since_begin_ms\":" + (S_QTE.equals(state) ? now - qteStartWall : -1)
                    + "}");
        } else {
            log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                    + ",\"type\":\"hook_clear\",\"game\":" + games
                    + ",\"vy\":" + v
                    + ",\"held_ms\":" + (biteAt > 0 ? now - biteAt : -1) + "}");
        }
    }

    private static void heartbeat(long now) {
        if (now - lastHeartbeat < 60000) {
            return;
        }
        lastHeartbeat = now;
        log("{\"t\":" + Sink.num(Sink.nano()) + ",\"wall\":" + now
                + ",\"type\":\"hb\",\"games\":" + games + ",\"presses\":" + presses
                + ",\"unknownKeyGames\":" + unknownKeyGames
                + ",\"state\":\"" + state + "\",\"loop\":\"" + loop + "\""
                + ",\"reels\":" + reels + ",\"formSkips\":" + formSkips + "}");
    }

    private static void logConf() {
        lastCfg = Config.describe();
        log("{\"type\":\"config\",\"value\":\"" + Sink.esc(lastCfg)
                + "\",\"src\":\"" + Sink.esc(Config.source)
                + "\",\"bite_ready\":" + Presser.biteReady() + "}");
    }

    /** 回到「刚进世界」的干净状态。**包私有**：离线测试要直接调（见 AutoTest.hardReset）。 */
    static void reset() {
        state = S_IDLE;
        reqKey = null;
        lastSub = "";
        lastTitle = "";
        lastAction = "";
        lastResult = "";
        frames = 0;
        pressesThisGame = 0;
        lastQteFrameWall = 0;
        lastBiting = false;
        biteSeen = false;
        biteAt = 0;
        loop = L_IDLE;
        reeledBiteAt = 0;
        lastForm = "";
        formColor = null;
        Presser.reset();
    }

    private static void log(String json) {
        Sink.line(json);
    }
}
