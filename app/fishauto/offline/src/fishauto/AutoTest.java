package fishauto;

import net.minecraft.Harness;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

/**
 * fishauto 离线验证：用同名桩类（{@code net.minecraft.Stubs}）真跑一遍
 * 「反射解析 -> 读 Title/副标题/动作栏 -> 状态机 -> 写 KeyMapping 字段 -> 落盘」全链路。
 *
 * 为什么必须有这一步：反射访问 MC 时**映射写错不会抛异常，只会静默不干活**。
 * 本项目已踩过（描述符不匹配 → 链路无声失效），所以在离线用同名桩把它逼出来。
 */
public final class AutoTest {
    private AutoTest() {
    }

    /** 一个真实抓到的 T3 帧（底图 + 占位 + 绿区 + 占位 + 指针 + 占位） */
    static final String FRAME = "\uB00C\uF807\uF806\uF804\uF801\uB012"
            + "\uF816\uF815\uF813\uF812\uF811\uF807\uF805\uF804\uF802\uF801"
            + "\uB001\uF817\uF815\uF813\uF812";

    // ---- v0.2 几何用例帧：全部从真实采集日志里原样取出（不是构造的）----
    // easy 变体首帧：zone_x=143 zone_w=45 ptr_x=73 d=-70（= team-lead 权威帧）
    static final String FRAME_EASY_FIRST = "\uB00C\uF807\uF806\uF804\uF801\uB012"
            + "\uF816\uF815\uF813\uF812\uF811\uF808\uF805\uF804\uF803"
            + "\uB001\uF818\uF815\uF813\uF812\uF811";
    // normal 变体首帧：zone_x=150 zone_w=36 ptr_x=75 d=-75
    static final String FRAME_NORMAL_FIRST = "\uB00C\uF807\uF806\uF803\uB013"
            + "\uF816\uF815\uF814\uF812\uF811\uF808\uF805\uF804\uF803"
            + "\uB001\uF818\uF815\uF813\uF812\uF811";
    // hard 变体某帧：zone_x=133 zone_w=27 ptr_x=65 d=-68
    static final String FRAME_HARD = "\uB00C\uF807\uF806\uF804\uF803\uF802\uF801\uB014"
            + "\uF817\uF814\uF813\uF812\uF811\uF808\uF805\uF804\uF803\uF802"
            + "\uB001\uF818\uF815\uF813\uF812\uF811";

    // ---- v0.2.1：另两种形态的最小帧（form() 只看**条图码点集合**，不看占位）----
    // C 形态实测码点集合 = {B001} ∪ {B002..B00C 之一}：有指针、**无绿区**（颜色题）
    static final String FRAME_C = "\uB001\uB004";
    // B 形态实测码点集合 = {B00D..B010 之一} ∪ {B011}：**无指针**，只有挣扎动画
    static final String FRAME_B = "\uB00D\uB011";

    // ---- ★ v0.3.0：C 形态的「指针落点」帧 ----
    //   同一底图 bar3（B004，内容宽 184，条内容右缘 = 246 ⇒ 左端 = 246-184 = 62），
    //   绿段图内 116..132 ⇒ 屏幕 178..194。只改指针 x：
    //     FRAME_C_HIT  : B004(256) + F807(-66) → ptr=190（在 178..194 内）
    //     FRAME_C_MISS : B004(256)             → ptr=256（在区外）
    static final String FRAME_C_HIT = "\uB004\uF807\uB001";
    static final String FRAME_C_MISS = "\uB004\uB001";

    static final List<String> NAMES = new ArrayList<>();
    static final List<Boolean> OKS = new ArrayList<>();
    static final List<String> DETAIL = new ArrayList<>();
    static Path cfg;

    static void chk(String name, boolean ok) {
        chk(name, ok, "");
    }

    static void chk(String name, boolean ok, String detail) {
        NAMES.add(name);
        OKS.add(ok);
        DETAIL.add(detail == null ? "" : detail);
    }

    public static void main(String[] args) throws Exception {
        String home = args.length > 0 ? args[0]
                : System.getProperty("java.io.tmpdir") + "/fishauto-offline";
        System.setProperty("user.home", home);

        // 提前把配置写成"开+干跑"，Config.init 就能读到
        Path fa = Paths.get(home, ".fishauto");
        Files.createDirectories(fa);
        cfg = fa.resolve("config.json");
        writeCfg(true, true, 20, 1200, false);

        Sink.init();
        Config.init();

        unit();
        phaseDryRun();
        phaseLive();
        phaseOutcome();
        phaseLeftTap();
        phaseScreenGuard();
        phaseStopFlag();
        phaseLeaveWorld();
        phaseFrameTriggerAndSubtitleMiss();
        phaseGeoCadenceBackstop();
        phaseGeometry();
        phaseBiteLog();
        phaseLoop();
        phaseFormC();
        phaseLogSanity();

        report();
    }

    // ------------------------------------------------------------------ A 纯函数
    private static void unit() {
        chk("Qte.isQteFrame 认进度条帧", Qte.isQteFrame(FRAME), "len=" + FRAME.length());
        chk("Qte.isQteFrame 不误报普通文本",
                !Qte.isQteFrame("\u4f60\u9493\u5230\u4e86\u4e00\u6761\u9c7c")
                        && !Qte.isQteFrame(""));
        chk("readable 把纯字模帧滤掉", !Qte.readable(FRAME));
        chk("readable 认中文提示", Qte.readable("\u6293\u7d27\u7aff\u5b50\uff0c\u9c7c\u5c31\u5728\u94a9\u4e0a\uff01"));
        chk("barCount 数出 3 个进度条元素", Qte.barCount(FRAME) == 3,
                "n=" + Qte.barCount(FRAME));

        chk("从标题抽「左Shift」", "shift".equals(Qte.reqKey("\u6309\u4e0b \u5de6Shift \u5f00\u59cb")));
        chk("从标题抽「左键」", "left".equals(Qte.reqKey("\u6309\u4e0b \u5de6\u952e \u5f00\u59cb")));
        chk("★ 防御性支持「右键」", "right".equals(Qte.reqKey("\u6309\u4e0b \u53f3\u952e \u5f00\u59cb")));
        chk("防御性支持「空格」", "jump".equals(Qte.reqKey("\u6309\u4e0b \u7a7a\u683c \u5f00\u59cb")));
        chk("非开始提示返回 null",
                Qte.reqKey("\u5728\u5173\u952e\u65f6\u523b\u6536\u6746") == null);
        // ★ QTE 期间 title 自己是单字模在跳（实测），必须不被当成开局信号
        chk("★ 单字模 title（U+B001）不被当成开始提示",
                Qte.reqKey("\uB001") == null && Qte.isQteFrame("\uB001"));

        // 结果词表基于 108 局逐局关联统计（不是猜的）
        chk("classify 成功 caught", "hit".equals(Qte.classify(
                "You caught a(n) Cod which is 42cm long! (Best record: 50.00cm)")));
        chk("classify 成功 Nice catch", "hit".equals(Qte.classify("Whoa! Nice catch!")));
        chk("classify 成功 GG!", "hit".equals(Qte.classify("GG!")));
        chk("classify 成功 Good Job!", "hit".equals(Qte.classify("Good Job!")));
        chk("classify 失败 escaped", "miss".equals(Qte.classify("The fish escaped...")));
        chk("classify 失败 What a pity!", "miss".equals(Qte.classify("What a pity!")));
        chk("★ classify 失败 Be concentrated!（100% 与 escaped 同时出现）",
                "miss".equals(Qte.classify("Be concentrated!")));
        chk("classify 失败 Bad luck", "miss".equals(Qte.classify("Bad luck")));
        chk("classify 失败 Try next time!", "miss".equals(Qte.classify("Try next time!")));
        chk("classify 过程提示 Let's see what it is!",
                "warn".equals(Qte.classify("Let's see what it is!")));
        chk("classify 过程提示 Oh ... here we go!",
                "warn".equals(Qte.classify("Oh \u9b54\u9b3c\u9c7c here we go!")));
        chk("classify 无关文本返回 null", Qte.classify("Hello") == null);

        // ---------------- v0.2 几何解码（advance 表实测自活动资源包）----------------
        // 默认策略必须是 cadence（= v0.1 行为），geometry 只能显式打开 —— 回滚保底
        chk("★ 默认 strategy=cadence 且 geometry 未激活",
                "cadence".equals(Config.strategy) && !Config.geometry());

        // advance 全表 36 项逐项断言（必须与 app/qte_advance.json 完全一致）
        int[][] adv = {
                {0xB001, 5},
                {0xB002, 256}, {0xB003, 256}, {0xB004, 256}, {0xB005, 256},
                {0xB006, 256}, {0xB007, 256}, {0xB008, 256}, {0xB009, 256},
                {0xB00A, 256}, {0xB00B, 256}, {0xB00C, 256},
                {0xB00D, 8}, {0xB00E, 8}, {0xB00F, 8}, {0xB010, 8},
                {0xB011, 256},
                {0xB012, 45}, {0xB013, 36}, {0xB014, 27},
                {0xF801, -3}, {0xF802, -4}, {0xF803, -6}, {0xF804, -10},
                {0xF805, -18}, {0xF806, -34}, {0xF807, -66}, {0xF808, -130},
                {0xF811, -1}, {0xF812, 1}, {0xF813, 3}, {0xF814, 7},
                {0xF815, 15}, {0xF816, 31}, {0xF817, 63}, {0xF818, 127},
        };
        int badAdv = 0;
        for (int[] e : adv) {
            if (Geom.advance(e[0]) != e[1]) {
                badAdv++;
            }
        }
        chk("★ Geom.advance 全表 36 项与 qte_advance.json 一致", badAdv == 0,
                "错 " + badAdv + " 项");
        chk("★ 未知字形返回 UNKNOWN，decode 拒解（绝不猜）",
                Geom.advance('A') == Geom.UNKNOWN
                        && Geom.decode(FRAME + "A") == null
                        && Geom.decode("The fish escaped...") == null
                        && Geom.decode("") == null);
        chk("★ judgeW：easy 45 / normal 36 / hard 27",
                Geom.judgeW(0xB012) == 45 && Geom.judgeW(0xB013) == 36
                        && Geom.judgeW(0xB014) == 27);

        // 真实采集帧（三个难度变体各一）——数值与 qtemap.py 解码逐项对齐
        int[] gEasy = Geom.decode(FRAME_EASY_FIRST);
        chk("★ 真实 easy 首帧：zone_x=143 zone_w=45",
                gEasy != null && gEasy[0] == 143 && gEasy[1] == 45,
                gEasy == null ? "decode=null" : "");
        chk("★ 真实 easy 首帧：ptr_x=73 d=-70（与人工对齐结论一致）",
                gEasy != null && gEasy[2] == 73 && gEasy[3] == -70);
        int[] gNorm = Geom.decode(FRAME_NORMAL_FIRST);
        chk("★ 真实 normal 首帧：zone_x=150 w=36 ptr_x=75 d=-75",
                gNorm != null && gNorm[0] == 150 && gNorm[1] == 36
                        && gNorm[2] == 75 && gNorm[3] == -75);
        int[] gHard = Geom.decode(FRAME_HARD);
        chk("★ 真实 hard 帧：zone_x=133 w=27 ptr_x=65 d=-68",
                gHard != null && gHard[0] == 133 && gHard[1] == 27
                        && gHard[2] == 65 && gHard[3] == -68);
        int[] gT3 = Geom.decode(FRAME);
        chk("★ 存量 T3 帧：zone_x=143 w=45 ptr_x=136 d=-7",
                gT3 != null && gT3[0] == 143 && gT3[1] == 45
                        && gT3[2] == 136 && gT3[3] == -7);

        // inZone 三规则 + 余量（规则扫描选型：center / 8px 分离度最优）
        chk("★ inZone center/8：d=-70 绿区外不按", !Geom.inZone(gEasy, "center", 8, 0));
        chk("★ inZone center/8：d=-7 绿区内按", Geom.inZone(gT3, "center", 8, 0));
        // 构造边界帧：d=-10（center 刚好过 -8 余量，left 不过）
        int[] gEdgeL = Geom.decode("\uB00C\uF807\uF806\uF804\uF801\uB012\uF806\uF805\uF801\uB001");
        chk("★ inZone 边界：d=-10 时 center 过、left 不过",
                gEdgeL != null && gEdgeL[3] == -10
                        && Geom.inZone(gEdgeL, "center", 8, 0)
                        && !Geom.inZone(gEdgeL, "left", 8, 0));
        // 构造边界帧：d=+51（center 刚好过 +53 余量，whole 不过）
        int[] gEdgeR = Geom.decode("\uB00C\uF807\uF806\uF804\uF801\uB012\uF814\uF811\uB001");
        chk("★ inZone 边界：d=+51 时 center 过、whole 不过",
                gEdgeR != null && gEdgeR[3] == 51
                        && Geom.inZone(gEdgeR, "center", 8, 0)
                        && !Geom.inZone(gEdgeR, "whole", 8, 0));
        chk("★ geo_lead_px 提前量生效（lead=-5px 把 d=-7 推出区）",
                !Geom.inZone(gT3, "center", 8, -5));

        // ---------------- v0.2.1：三形态判据（全量 132 局重扫得出，局内 100% 单一）----
        chk("★ form：A = 指针 + 绿区（三个难度变体都是 A）",
                "A".equals(Qte.form(FRAME)) && "A".equals(Qte.form(FRAME_EASY_FIRST))
                        && "A".equals(Qte.form(FRAME_NORMAL_FIRST))
                        && "A".equals(Qte.form(FRAME_HARD)));
        chk("★ form：C = 有指针但**无绿区**（颜色题）", "C".equals(Qte.form(FRAME_C)));
        chk("★ form：B = **无指针**，只有挣扎动画图标（B00D..B010 + B011）",
                "B".equals(Qte.form(FRAME_B)) && "B".equals(Qte.form("\uB011\uB00F")));
        chk("★ form：空 / 无关文本 -> ?",
                "?".equals(Qte.form("")) && "?".equals(Qte.form("The fish escaped..."))
                        && "?".equals(Qte.form(null)));
        chk("★ C / B 形态几何必然不可解（无绿区 ⇒ decode=null，这正是 geom_skip 的来源）",
                Geom.decode(FRAME_C) == null && Geom.decode(FRAME_B) == null);
        chk("★ 默认 bite_log=false（观测也必须显式打开）", !Config.biteLog);

        // ---------------- ★ v0.3.0：底图色段（C 形态）与颜色题 ----------------
        chk("Qte.colorAsk 认「绿色!」", "green".equals(Qte.colorAsk("\u7eff\u8272!")));
        chk("Qte.colorAsk 认「紫色!」", "purple".equals(Qte.colorAsk("\u7d2b\u8272!")));
        chk("Qte.colorAsk 认「红色!」", "red".equals(Qte.colorAsk("\u7ea2\u8272!")));
        chk("★ Qte.colorAsk 认「浅蓝色!」→ lightblue（实测题面）",
                "lightblue".equals(Qte.colorAsk("\u6d45\u84dd\u8272!")));
        chk("★ Qte.colorAsk 认「深蓝色!」→ blue（实测题面）",
                "blue".equals(Qte.colorAsk("\u6df1\u84dd\u8272!")));
        chk("★ 判定顺序：「浅蓝色」绝不能被「蓝色」抢先命中",
                !"blue".equals(Qte.colorAsk("\u6d45\u84dd\u8272!")),
                Qte.colorAsk("\u6d45\u84dd\u8272!"));
        chk("Qte.colorAsk 认「橙色!」/「黄色!」",
                "orange".equals(Qte.colorAsk("\u6a59\u8272!"))
                        && "yellow".equals(Qte.colorAsk("\u9ec4\u8272!")));
        chk("★ Qte.reelHint 认「在关键时刻收杆」（题面没写键，按右键收杆型处理）",
                Qte.reelHint("\u5728\u5173\u952e\u65f6\u523b\u6536\u7aff")
                        && !Qte.reelHint("\u6309\u4e0b \u5de6\u952e \u5f00\u59cb")
                        && !Qte.reelHint(null));
        chk("★ Qte.reqKey 对「在关键时刻收杆」返回 null（要靠 reelHint 补认）",
                Qte.reqKey("\u5728\u5173\u952e\u65f6\u523b\u6536\u7aff") == null);

        chk("Qte.colorAsk 普通提示返回 null（不是颜色题就别乱认）",
                Qte.colorAsk("\u597d\u673a\u4f1a\uff0c\u4fdd\u6301\u51b7\u9759\uff01") == null
                        && Qte.colorAsk("\u8dd1\u6389\u4e86") == null
                        && Qte.colorAsk(null) == null);

        // 底图内容宽（决定"内容贴 cell 右缘"的偏移量）
        chk("★ Geom.barW：bar1..bar9 内容宽 184", Geom.barW(0xB002) == 184
                && Geom.barW(0xB00A) == 184);
        chk("★ Geom.barW：bar_rainbow 120 / bar10 163 / bar11 222",
                Geom.barW(0xB00B) == 120 && Geom.barW(0xB00C) == 163
                        && Geom.barW(0xB011) == 222);
        chk("★ Geom.barId：只认「有判定色段」的底图（bar1..bar9/rainbow）",
                Geom.barId(FRAME_C_HIT) == 0xB004
                        && Geom.barId(FRAME) == 0            // bar10 无判定色 → 0
                        && Geom.barId(FRAME_B) == 0          // bar11 同上
                        && Geom.barId("") == 0);

        // ★ 关键：bar3 绿段屏幕坐标 = (246-184)+116 .. (246-184)+132 = 178..194
        int[] cHit = Geom.decodeC(FRAME_C_HIT, null);
        chk("★ Geom.decodeC：bar3 判定色段落到屏幕 178..194（右缘常数 246）",
                cHit != null && cHit[2] == 178 && cHit[3] == 194,
                cHit == null ? "null" : cHit[2] + ".." + cHit[3]);
        chk("★ Geom.inZoneC：ptr=190（中心 192 落在 178..194 内）",
                Geom.inZoneC(cHit, 0));
        int[] cMiss = Geom.decodeC(FRAME_C_MISS, null);
        chk("★ Geom.inZoneC：ptr=256 在判定色段外",
                cMiss != null && cMiss[0] == 256 && !Geom.inZoneC(cMiss, 0),
                cMiss == null ? "null" : "ptr=" + cMiss[0]);

        // 颜色题：rainbow 是**七段**等宽长条（红橙黄绿浅蓝深蓝紫），题目颜色决定取哪一段
        int[] cGreen = Geom.decodeC("\uB00B\uF808\uB001", "green");
        int[] cRed = Geom.decodeC("\uB00B\uF808\uB001", "red");
        int[] cLight = Geom.decodeC("\uB00B\uF808\uB001", "lightblue");
        int[] cBlue = Geom.decodeC("\uB00B\uF808\uB001", "blue");
        chk("★ 颜色题：rainbow 上「绿色」与「红色」取到不同的段",
                cGreen != null && cRed != null && cGreen[2] != cRed[2],
                "green=" + (cGreen == null ? "-" : cGreen[2])
                        + " red=" + (cRed == null ? "-" : cRed[2]));
        chk("★ 颜色题：浅蓝色(68..84) 与 深蓝色(84..100) 是**两段**，不能混",
                cLight != null && cBlue != null && cLight[2] != cBlue[2],
                "light=" + (cLight == null ? "-" : cLight[2])
                        + " blue=" + (cBlue == null ? "-" : cBlue[2]));
        // rainbow 内容右缘 246、内容宽 120 ⇒ 左端 126
        chk("★ rainbow 七段屏幕坐标：红 130..146 / 绿 178..194 / 紫 226..242",
                cRed != null && cRed[2] == 130 && cRed[3] == 146
                        && cGreen[2] == 178 && cGreen[3] == 194
                        && Geom.decodeC("\uB00B\uB001", "purple")[2] == 226,
                cRed == null ? "null" : ("red=" + cRed[2] + ".." + cRed[3]
                        + " green=" + cGreen[2] + ".." + cGreen[3]));
        chk("★ 颜色题：橙色段存在（旧的六段表把橙+黄并成一段，已修正）",
                Geom.decodeC("\uB00B\uB001", "orange") != null
                        && Geom.decodeC("\uB00B\uB001", "orange")[2] == 146);
        chk("★ Geom.decodeC：无判定色段的底图（bar10）返回 null",
                Geom.decodeC("\uB00C\uB001", null) == null);
        chk("★ Geom.decodeC：无指针（B 形态）返回 null",
                Geom.decodeC(FRAME_B, null) == null);
        chk("★ Geom.decodeC：出现未知字形 → null（绝不猜）",
                Geom.decodeC(FRAME_C_HIT + "A", null) == null);

        // 出厂默认：新开关必须都是"关"（装上什么都不做）
        chk("★ 默认 reel_on_bite=false / form_strategy=observe / c_margin=0",
                !Config.reelOnBite && "observe".equals(Config.formStrategy)
                        && Config.cMargin == 0);
        chk("★ Config.formAuto() 只在 form_strategy=auto 时为真",
                !Config.formAuto());
    }

    // ------------------------------------------------------------------ B 干跑
    private static void phaseDryRun() throws Exception {
        sleep(1100);                                  // 让 Config 热加载到新配置
        Harness.reset();
        Harness.setTitle("\u6309\u4e0b \u5de6Shift \u5f00\u59cb");
        // 真实 QTE 的字幕**每 tick 都在变**（实测字模长度 7–13 跳动），
        // 所以帧记录是「变化才记」；这里逐帧加一个透明占位来复现这种变化。
        for (int i = 0; i < 12; i++) {
            Harness.setSubtitle(FRAME + pad(i));
            AutoFish.tick();
            sleep(25);
        }

        chk("status.txt 反射解析成功", statusText().startsWith("OK"),
                firstLine(statusText()));
        chk("▶ 干跑：qte_begin 记到且按键=shift", find("qte_begin", "\"key\":\"shift\"") != null);
        chk("▶ 干跑：press_dry >= 5", count("press_dry") >= 5, "n=" + count("press_dry"));
        chk("★ 干跑绝不真按键（shift clickCount=0 且 isDown=false）",
                Harness.shiftClicks() == 0 && !Harness.shiftDown()
                        && Harness.attackClicks() == 0 && Harness.useClicks() == 0,
                "shift clicks=" + Harness.shiftClicks() + " down=" + Harness.shiftDown());
        chk("▶ 每一帧原始字幕都落盘（frame >= 10）", count("frame") >= 10,
                "n=" + count("frame"));
        chk("▶ 只有 1 个日志文件", logFiles().size() == 1,
                logFiles().toString());
    }

    /** 给字幕加 n 个透明占位，模拟真实帧的变化。 */
    static String pad(int i) {
        StringBuilder sb = new StringBuilder(4);
        for (int k = 0; k < i % 3; k++) {
            sb.append('\uF801');
        }
        return sb.toString();
    }

    // ------------------------------------------------------------------ C 真按键
    private static void phaseLive() throws Exception {
        writeCfg(true, false, 20, 1200, false);
        sleep(1100);
        Harness.setTitle("\u6309\u4e0b \u5de6Shift \u5f00\u59cb");
        Harness.setSubtitle(FRAME);

        boolean sawDown = false;
        boolean sawUp = false;
        int downStreak = 0;
        int maxStreak = 0;
        for (int i = 0; i < 21; i++) {
            AutoFish.tick();
            if (Harness.shiftDown()) {
                sawDown = true;
                downStreak++;
                maxStreak = Math.max(maxStreak, downStreak);
            } else {
                downStreak = 0;
                if (sawDown) {
                    sawUp = true;
                }
            }
            sleep(25);
        }
        chk("★ Shift 形态写的是 isDown（按下）", sawDown);
        chk("★ 松手回位：按下之后确实恢复 false", sawUp);
        chk("★ 不是长按：按住最多持续 2 个 tick（hold_ticks=2）",
                maxStreak <= 2, "最长连续按下 " + maxStreak + " tick");
        chk("▶ press 事件 >= 5", count("press") >= 5, "n=" + count("press"));
        chk("▶ press 事件带当时字幕（可用于事后学规则）",
                find("press", "\"sub\":\"\uB00C") != null);
        chk("▶ press 事件带序号 n", find("press", "\"n\":") != null);
    }

    // ------------------------------------------------------------------ D 结果挂靠
    private static void phaseOutcome() throws Exception {
        Harness.setAction("You caught a(n) \u9cd6\u9c7c which is 42cm");
        tick(3, 25);
        chk("▶ 自带反馈识别为成功 signal=hit", find("signal", "\"kind\":\"hit\"") != null);
        chk("★ qte_end 结果记为 hit", find("qte_end", "\"result\":\"hit\"") != null,
                find("qte_end", "\"result\":\"hit\""));
    }

    // ------------------------------------------------------------------ E 左键
    private static void phaseLeftTap() throws Exception {
        Harness.setAction("");
        Harness.setTitle("\u6309\u4e0b \u5de6\u952e \u5f00\u59cb");
        Harness.setSubtitle(FRAME);
        int before = count("press");
        tick(10, 25);
        chk("★ 左键形态真的写了 clickCount", Harness.attackClicks() > 0,
                "clicks=" + Harness.attackClicks());
        chk("★ 原版管线能消费这次点击（写 1 <=> 按一次）", Harness.consumeAttack());
        chk("▶ press 事件 key=left", find("press", "\"key\":\"left\"") != null);
        chk("▶ 记录到按键来源为左键", count("press") > before);
    }

    // ------------------------------------------------------------------ F 界面保护
    private static void phaseScreenGuard() throws Exception {
        Harness.setScreenOpen(true);
        Harness.setSubtitle(FRAME);
        int p0 = count("press");
        int d0 = count("press_dry");
        tick(8, 25);
        chk("★ 有界面打开时一个键都不按",
                count("press") == p0 && count("press_dry") == d0,
                "press " + p0 + "->" + count("press")
                        + " dry " + d0 + "->" + count("press_dry"));
        Harness.setScreenOpen(false);
    }

    // ------------------------------------------------------------------ G 急停
    private static void phaseStopFlag() throws Exception {
        Path stop = Paths.get(System.getProperty("user.home"), ".fishauto", "STOP");
        Files.writeString(stop, "stop", StandardCharsets.UTF_8);
        sleep(1100);                                   // 让 Sink 重新检查标志
        Harness.setSubtitle(FRAME);
        int d0 = count("press_dry");
        int p0 = count("press");
        tick(8, 25);
        chk("★ STOP 急停：不再真按键（转为只记录 press_dry）",
                count("press_dry") > d0 && count("press") == p0,
                "dry " + d0 + "->" + count("press_dry") + " press " + p0 + "->" + count("press"));
        Files.deleteIfExists(stop);
        sleep(1100);
        int p1 = count("press");
        tick(6, 25);
        chk("▶ 急停解除后恢复按键", count("press") > p1,
                "press " + p1 + "->" + count("press"));
    }

    // ------------------------------------------------------------------ H 离世界
    private static void phaseLeaveWorld() throws Exception {
        Harness.setSubtitle("");
        tick(3, 25);
        int before = count("world_leave");
        Harness.setWorldPresent(false);
        tick(2, 25);
        chk("▶ 离开世界记 world_leave 并收尾", count("world_leave") > before);
        Harness.setWorldPresent(true);
    }

    // ------------------------------------------------- I 帧触发 + 副标题结果
    private static void phaseFrameTriggerAndSubtitleMiss() throws Exception {
        // 刻意把 title 清掉 ⇒ 只能靠「字幕帧变化」开局（真实里 title 常是单字模在跳）
        Harness.setTitle("");
        Harness.setSubtitle(FRAME + "\uF802");
        int begin0 = count("qte_begin");
        tick(3, 25);
        chk("★ 只有 title 变化（无「按下 X 开始」）时也能被帧变化开局",
                count("qte_begin") > begin0, "qte_begin " + begin0 + "->" + count("qte_begin"));
        chk("▶ 帧触发的 begin 记了 by=frame",
                find("qte_begin", "\"by\":\"frame\"") != null);
        chk("▶ 帧触发时按键未知，被记为 unknown 且只 skip 不按",
                find("qte_begin", "\"key\":\"unknown\"") != null
                        && find("press_skip", "\"key\":\"unknown\"") != null);

        // ★ 关键路径：进度条帧比标题早到 ⇒ 先以 unknown 开局，标题补到后必须改认
        //   （实测按键每局随机：左键 26 / 左Shift 68，绝不能沿用上一局）
        int left0 = countNeedle("\"type\":\"press\",\"key\":\"left\"");
        Harness.setTitle("\u6309\u4e0b \u5de6\u952e \u5f00\u59cb");
        tick(2, 25);
        chk("★ 局内补认按键：标题迟到也能改认成 left（记 key_upgrade）",
                find("key_upgrade", "\"key\":\"left\"") != null,
                find("key_upgrade", "\"key\":\"left\""));
        int left1 = countNeedle("\"type\":\"press\",\"key\":\"left\"");
        chk("★ 改认之后真的按下了左键（不是沿用上一局）", left1 > left0,
                "press(key=left) " + left0 + " -> " + left1);

        // 实测：`The fish escaped...` **只出现在副标题**里（37/37）。
        Harness.setSubtitle("The fish escaped...");
        tick(3, 25);
        chk("★ 副标题里的失败文本被识别（signal kind=miss）",
                find("signal", "\"kind\":\"miss\"") != null,
                find("signal", "\"kind\":\"miss\""));
        chk("★ qte_end 把这一局记为 miss",
                find("qte_end", "\"result\":\"miss\"") != null,
                find("qte_end", "\"result\":\"miss\""));
    }

    // ------------------------------------------------- J cadence 回滚保底
    /** strategy=cadence（默认）＝ v0.1 行为：完全不看几何，指针在哪都连按。 */
    private static void phaseGeoCadenceBackstop() throws Exception {
        writeCfg(true, true, 20, 1200, false);
        sleep(1100);
        Harness.reset();
        Harness.setTitle("\u6309\u4e0b \u5de6\u952e \u5f00\u59cb");
        Harness.setSubtitle(FRAME_EASY_FIRST);        // d=-70，指针在绿区左侧很远
        int d0 = count("press_dry");
        tick(6, 25);
        chk("★ cadence 策略不看几何：指针在绿区外也连按（=v0.1，回滚保底）",
                count("press_dry") > d0,
                "dry " + d0 + "->" + count("press_dry"));
    }

    // ------------------------------------------------- K geometry 策略
    private static void phaseGeometry() throws Exception {
        writeCfgGeo(true, true, "geometry", "center", 8, 0);
        sleep(1100);
        tick(1, 25);                                  // 触发一次 maybeReload
        chk("▶ geometry 策略已被配置激活（center/8px/lead0）",
                Config.geometry() && "center".equals(Config.geoRule)
                        && Config.geoMargin == 8 && Config.geoLeadPx == 0,
                "strategy=" + Config.strategy + " rule=" + Config.geoRule
                        + " margin=" + Config.geoMargin);

        Harness.reset();
        Harness.setTitle("\u6309\u4e0b \u5de6\u952e \u5f00\u59cb");

        // 1) 指针在绿区外（d=-70）→ 一个键都不按
        Harness.setSubtitle(FRAME_EASY_FIRST);
        int d0 = count("press_dry");
        tick(6, 25);
        chk("★ geometry：指针在绿区外（d=-70）不按",
                count("press_dry") == d0,
                "dry " + d0 + "->" + count("press_dry"));

        // 2) 指针入区（真实 T3 帧 d=-7，center 规则 -5 ∈ [-8,53]）→ 按（干跑）
        Harness.setSubtitle(FRAME);
        tick(6, 25);
        chk("★ geometry：指针入区（d=-7）才按（干跑）",
                count("press_dry") > d0,
                "dry " + d0 + "->" + count("press_dry"));
        chk("▶ press_dry 带几何字段（zone_x/zone_w/ptr_x/d）",
                find("press_dry", "\"ptr_x\":136,\"d\":-7") != null,
                find("press_dry", "\"ptr_x\":136,\"d\":-7"));

        // 3) 帧里混入未知字形 → 几何不可信 → geom_skip（每局只记一次）且不按
        Harness.setSubtitle(FRAME + "A");
        int d1 = count("press_dry");
        tick(4, 25);
        chk("★ geometry：帧解不出几何 → geom_skip 且不按",
                countNeedle("\"type\":\"geom_skip\"") == 1 && count("press_dry") == d1,
                "skip=" + countNeedle("\"type\":\"geom_skip\"")
                        + " dry " + d1 + "->" + count("press_dry"));

        // 4) 好帧回来 → 恢复按键
        Harness.setSubtitle(FRAME);
        tick(4, 25);
        chk("★ geometry：几何恢复后继续按键",
                count("press_dry") > d1,
                "dry " + d1 + "->" + count("press_dry"));

        // 5) frame 日志带几何字段；解不出的帧记 geom_ok=false
        chk("▶ frame 日志带几何字段（真实首帧 143/45/73/-70）",
                find("frame", "\"zone_x\":143,\"zone_w\":45,\"ptr_x\":73,\"d\":-70") != null);
        chk("▶ 解不出的帧记 geom_ok=false",
                find("frame", "\"geom_ok\":false") != null);

        // 收尾：回到 cadence，避免影响后面的相位
        writeCfg(true, true, 20, 1200, false);
        sleep(1100);
    }

    // ------------------------------------------------- L 咬钩观测（v0.2.1）
    /**
     * 咬钩信号**观测**：只在边沿写 hook_bite / hook_clear，而且**与 enabled 无关**。
     *
     * 这一段所有断言都只涉及日志与"没按键"，因为观测件的本分就是不动按键行为。
     */
    private static void phaseBiteLog() throws Exception {
        settleOut();                       // ★ 先让上一局的 SETTLE 走完，状态机才是干净的
        // 1) 总开关关着也能观测 —— 这正是它的用法：纯观测、一个键都不按
        writeCfgBite(false, true, true);
        sleep(1100);
        Harness.reset();
        Harness.setCasted(true);
        tick(2, 25);
        chk("★ enabled=false + bite_log=true：一个键都不按，但观测照常",
                Harness.attackClicks() == 0 && Harness.useClicks() == 0
                        && Harness.shiftClicks() == 0,
                "attack=" + Harness.attackClicks() + " use=" + Harness.useClicks()
                        + " shift=" + Harness.shiftClicks());

        int b0 = count("hook_bite");
        tick(3, 25);
        chk("▶ 没咬钩时不写 hook_bite（边沿语义）", count("hook_bite") == b0,
                "n=" + count("hook_bite"));

        // 2) 咬钩上升沿 -> 一条 hook_bite（带当时 vy）
        Harness.setBiting(true);
        Harness.setHookVy(-0.317);
        tick(3, 25);
        chk("★ 咬钩上升沿记一条 hook_bite，且带当时 vy",
                count("hook_bite") == b0 + 1
                        && find("hook_bite", "\"vy\":-0.317") != null,
                find("hook_bite", "\"vy\":-0.317"));
        chk("▶ 反射管道真的读到了桩字段（不是恒 false）", Harness.biting());

        // 3) 持续咬钩不重复写
        int b1 = count("hook_bite");
        tick(4, 25);
        chk("★ 持续咬钩期间不重复写（只记边沿）", count("hook_bite") == b1,
                "n " + b1 + "->" + count("hook_bite"));

        // 4) 下降沿 -> hook_clear（带 held_ms）
        Harness.setBiting(false);
        Harness.setHookVy(0.0);
        tick(3, 25);
        chk("★ 咬钩结束记 hook_clear，且带 held_ms",
                count("hook_clear") == 1 && find("hook_clear", "\"held_ms\":") != null,
                find("hook_clear", "\"held_ms\":"));

        // 5) 收竿：浮标没了就清状态，不再产生事件
        Harness.setCasted(false);
        tick(3, 25);
        int c0 = count("hook_clear");
        tick(3, 25);
        chk("★ 收竿后不再产生咬钩事件（hook()==null 即清状态）",
                count("hook_clear") == c0, "n " + c0 + "->" + count("hook_clear"));

        // 6) 关掉 bite_log -> 一条都不写（默认静默）
        writeCfgBite(false, true, false);
        sleep(1100);
        Harness.setCasted(true);
        Harness.setBiting(false);
        tick(2, 25);
        int a0 = count("hook_bite") + count("hook_clear");
        Harness.setBiting(true);
        tick(3, 25);
        chk("★ bite_log=false 时一条咬钩事件都不写（出厂默认静默）",
                count("hook_bite") + count("hook_clear") == a0,
                "n " + a0 + "->" + (count("hook_bite") + count("hook_clear")));

        // 7) 与开局的时间关联：qte_begin.bite_ago_ms（咬钩比开局早多少毫秒）
        writeCfgBite(true, true, true);
        sleep(1100);
        Harness.reset();
        Harness.setCasted(true);
        Harness.setBiting(false);
        tick(2, 25);                       // 先把边沿状态归位
        settleOut();                       // ★ 同理：不回到 IDLE 就永远不会判开局
        Harness.setTitle("\u6309\u4e0b \u5de6\u952e \u5f00\u59cb");
        Harness.setSubtitle(FRAME);
        Harness.setBiting(true);           // 咬钩与开局几乎同时
        tick(4, 25);
        chk("★ qte_begin 带 bite_ago_ms（有咬钩时不是 -1）",
                findNot("qte_begin", "\"bite_ago_ms\":", "\"bite_ago_ms\":-1") != null,
                findNot("qte_begin", "\"bite_ago_ms\":", "\"bite_ago_ms\":-1"));
        chk("★ frame 日志带 form 字段（这一帧是 A）",
                find("frame", "\"form\":\"A\"") != null);

        // 收尾：回出厂默认（enabled=false / dry_run=true / bite_log=false）
        writeCfgBite(false, true, false);
        sleep(1100);
    }

    // ------------------------------------------------- L2 外层钓鱼循环（v0.3.0）
    /**
     * 玩家真实流程：右键抛竿 -> 鱼咬钩 -> 右键收杆 -> 小游戏。
     *
     * 这一段**故意用 dry_run=false**：`auto_cast` / `reel_on_bite` 是"真动作"，
     * 离线里"真按键"= 写 KeyMapping 的 clickCount 字段（安全，且能验证链路真的通）。
     *
     * 为什么不能用"按节拍"收杆（本轮的核心结论）：
     *   上鱼时间**随机不固定**，而且**重新抛竿会重置计时** —— 节拍法必然越走越偏。
     *   biting 是服务端同步下来的真信号，咬钩 -> 开局只隔 300~360ms（实测）。
     */
    private static void phaseLoop() throws Exception {
        writeCfgLoop(true, false, true, true);        // enabled, dry_run=false, auto_cast, reel_on_bite
        sleep(1100);
        hardReset();                                 // ★ 从干净的 IDLE 起步
        chk("▶ hardReset 后状态机应为 idle",
                "idle".equals(AutoFish.state) && "idle".equals(AutoFish.loop),
                "state=" + AutoFish.state + " loop=" + AutoFish.loop);

        // 1) 自动抛竿
        //    ★ Config 热加载是挂在 tick() 里的，光 sleep 不会重载 —— 必须先 tick 一次
        tick(1, 25);
        hardReset();                                 // 清掉上一步可能顺手抛出的竿
        sleep(600);                                  // 越过 cast_delay_ms 冷却
        chk("▶ loop 前置条件：enabled & auto_cast & !dry_run & !halted",
                Config.enabled && Config.autoCast && !Config.dryRun && !AutoFish.halted,
                "enabled=" + Config.enabled + " autoCast=" + Config.autoCast
                        + " dry=" + Config.dryRun + " halted=" + AutoFish.halted
                        + " hand=" + Presser.mainHand());
        int u0 = Harness.useClicks();
        int c0 = count("cast");
        tick(2, 25);
        chk("★ auto_cast：手上是鱼竿且没抛竿 → 自动右键抛竿",
                Harness.useClicks() > u0, "use " + u0 + "->" + Harness.useClicks());
        chk("▶ 记了一条 cast 事件", count("cast") > c0, "n " + c0 + "->" + count("cast"));

        // 2) 已抛竿、未咬钩：不能乱收杆
        Harness.setCasted(true);
        Harness.setBiting(false);
        tick(2, 25);
        int r0 = count("reel");
        tick(2, 25);
        chk("▶ 没咬钩时不收杆（不会把竿白收回来）", count("reel") == r0, "n=" + r0);

        // 3) ★ 咬钩 -> 立刻收杆
        Harness.setBiting(true);
        int u1 = Harness.useClicks();
        tick(3, 25);
        chk("★ reel_on_bite：咬钩时自动右键收杆（真写 clickCount）",
                count("reel") == r0 + 1 && Harness.useClicks() > u1,
                "reel " + r0 + "->" + count("reel") + " use " + u1 + "->" + Harness.useClicks());
        chk("▶ reel 事件带 after_bite_ms（咬钩到收杆的延迟，用来对表 300ms 规律）",
                find("reel", "\"after_bite_ms\":") != null);

        // 4) 同一次咬钩只收一次（否则每次 tick 都点一下右键）
        int r1 = count("reel");
        tick(4, 25);
        chk("★ 同一次咬钩只收一次杆", count("reel") == r1, "n " + r1 + "->" + count("reel"));

        // 5) 收杆后浮标消失 -> 回 idle（下一轮循环的起点）
        Harness.setCasted(false);
        Harness.setBiting(false);
        tick(2, 25);
        chk("▶ 收杆后 loop 回到 idle", "idle".equals(AutoFish.loop),
                "loop=" + AutoFish.loop);

        // 6) 关掉 reel_on_bite -> 咬钩也不收杆（默认出厂就是这个状态）
        writeCfgLoop(true, false, false, false);
        sleep(1100);
        Harness.reset();
        Harness.setCasted(true);
        Harness.setBiting(false);
        tick(2, 25);
        int r2 = count("reel");
        Harness.setBiting(true);
        tick(4, 25);
        chk("★ reel_on_bite=false 时咬钩不收杆（出厂默认静默）",
                count("reel") == r2, "n " + r2 + "->" + count("reel"));

        writeCfg(true, true, 20, 1200, false);       // 回安全配置
        sleep(1100);
    }

    // ------------------------------------------------- L3 三形态分流（v0.3.0）
    /**
     * A 走 geometry；B **明确不按**；C 默认只观测（form_strategy=observe），
     * 只有显式 auto 才按"底图判定色段"出手。
     */
    private static void phaseFormC() throws Exception {
        // ---- 1) observe（出厂默认）：B/C 一个键都不按 ----
        writeCfgForm(true, true, "cadence", "observe", "right", 0);
        sleep(1100);
        hardReset();

        // A) B 形态：结构里没有指针 -> 明确不按（记一条 form_skip）
        Harness.reset();
        Harness.setCasted(true);
        tick(1, 25);
        int d0 = count("press_dry");
        Harness.setSubtitle(FRAME_B);
        tick(3, 25);
        chk("★ B 形态（无指针）：不按键，且记一条 form_skip",
                count("press_dry") == d0 && count("form_skip") >= 1,
                "dry " + d0 + "->" + count("press_dry"));

        // B) C 形态：observe 语义 = 只标注、不动作
        hardReset();
        Harness.reset();
        Harness.setCasted(true);
        tick(1, 25);
        Harness.setSubtitle(FRAME_C_HIT);
        tick(4, 25);
        chk("★ observe（默认）：C 形态就算指针压在判定色段上也不按键",
                count("press_dry") == d0, "dry " + d0 + "->" + count("press_dry"));
        chk("★ frame 日志标注 form=C（观测语义：只标注、不动作）",
                find("frame", "\"form\":\"C\"") != null);

        // ---- 2) auto：C 形态按"底图判定色段"出手 ----
        writeCfgForm(true, true, "cadence", "auto", "right", 0);
        sleep(1100);
        hardReset();
        Harness.reset();
        Harness.setCasted(true);
        tick(1, 25);
        int d1 = count("press_dry");
        Harness.setSubtitle(FRAME_C_MISS);
        tick(4, 25);
        chk("★ auto：C 形态指针在判定色段外 → 不按",
                count("press_dry") == d1, "dry " + d1 + "->" + count("press_dry"));

        hardReset();
        Harness.reset();
        Harness.setCasted(true);
        tick(1, 25);
        Harness.setSubtitle(FRAME_C_HIT);
        tick(4, 25);
        chk("★ auto：C 形态指针进判定色段 → 按（干跑记 press_dry form=C）",
                count("press_dry") > d1 && find("press_dry", "\"form\":\"C\"") != null,
                "dry " + d1 + "->" + count("press_dry"));
        chk("▶ C 形态的 press_dry 带 ptr / zone（可事后核对判定）",
                find("press_dry", "\"ptr\":") != null
                        && find("press_dry", "\"zone\":[178,194]") != null);
        chk("★ C 形态 = 「右键收杆型」：按的是右键，不是左键",
                find("press_dry", "\"form\":\"C\"") != null
                        && find("press_dry", "\"form\":\"C\",\"key\":\"right\"") != null);

        writeCfg(true, true, 20, 1200, false);       // 回安全配置
        sleep(1100);
    }

    // ------------------------------------------------------------------ I 日志体检
    private static void phaseLogSanity() throws Exception {        int bad = 0;
        int noWall = 0;
        int total = 0;
        for (Path p : logFiles()) {
            for (String line : Files.readAllLines(p, StandardCharsets.UTF_8)) {
                line = line.trim();
                if (line.isEmpty()) {
                    continue;
                }
                total++;
                if (!balanced(line)) {
                    bad++;
                }
                if (line.contains("\"t\":") && !line.contains("\"wall\":")) {
                    noWall++;
                }
            }
        }
        chk("▶ 每行都是结构完整的一行 JSON", bad == 0, "坏行 " + bad + "/" + total);
        chk("▶ 带 t 的行同时带 wall（双时间戳齐全）", noWall == 0, "缺 wall " + noWall);
        chk("▶ 有 session 开场事件", count("session") >= 1);
    }

    // ------------------------------------------------------------------ 工具
    static void tick(int n, int gapMs) throws InterruptedException {
        for (int i = 0; i < n; i++) {
            AutoFish.tick();
            sleep(gapMs);
        }
    }

    static void sleep(long ms) throws InterruptedException {
        Thread.sleep(ms);
    }

    /**
     * 让状态机从 SETTLE 回到 IDLE。
     *
     * 坑：{@code settle()} 只在 tick 里推进（比较 settleUntil），**sleep 本身不会推进它** ——
     * 所以要「先睡过 2s 超时，再 tick 一次」。不这么做，后面所有依赖「判定开局」的用例
     * 都会静默失败（踩过一次：qte_begin 一直不出现，而 bite_log 用例看似代码有问题）。
     */
    static void settleOut() throws InterruptedException {
        sleep(2100);
        tick(1, 25);
    }

    /**
     * ★ v0.3.0：**强制**把状态机打回 IDLE。
     *
     * 为什么还要多一个：{@code settleOut()} 只对 SETTLE 有效；如果上一段测试把状态留在
     * **QTE** 里，它推不动（QTE 只认"字幕超时"或"结果文本"）。而 QTE 期间
     * {@code loopTick()} 会直接 return —— 于是后面所有"抛竿/收杆"用例都会静默失败
     * （本轮就踩了：7 项不过，全因状态卡在上一段的 QTE）。
     *
     * 最可靠的复位是**离开世界**：{@code AutoFish.tick()} 见到 level==null 会调 reset()。
     */
    static void hardReset() throws InterruptedException {
        Harness.reset();      // 干净场景：新 mc/player/gui，没抛竿、没咬钩、没界面
        AutoFish.reset();     // 状态机回 IDLE（**不 tick** —— tick 会顺手把竿抛出去）
    }

    static void writeCfg(boolean enabled, boolean dryRun, int cadence, int idle, boolean autoCast)
            throws IOException {
        String s = "{\n"
                + "  \"enabled\": " + enabled + ",\n"
                + "  \"dry_run\": " + dryRun + ",\n"
                + "  \"auto_cast\": " + autoCast + ",\n"
                + "  \"cadence_ms\": " + cadence + ",\n"
                + "  \"hold_ticks\": 2,\n"
                + "  \"idle_timeout_ms\": " + idle + ",\n"
                + "  \"max_press_per_game\": 200,\n"
                + "  \"max_games\": 0,\n"
                + "  \"use_left\": true,\n"
                + "  \"use_right\": true,\n"
                + "  \"use_shift\": true,\n"
                + "  \"log_frames\": true\n"
                + "}\n";
        Files.writeString(cfg, s, StandardCharsets.UTF_8);
    }

    /** 带 strategy / geo_* 的完整配置（v0.2 几何用例用）。 */
    static void writeCfgGeo(boolean enabled, boolean dryRun, String strategy,
                            String rule, int margin, int lead) throws IOException {
        String s = "{\n"
                + "  \"enabled\": " + enabled + ",\n"
                + "  \"dry_run\": " + dryRun + ",\n"
                + "  \"strategy\": \"" + strategy + "\",\n"
                + "  \"geo_rule\": \"" + rule + "\",\n"
                + "  \"geo_margin\": " + margin + ",\n"
                + "  \"geo_lead_px\": " + lead + ",\n"
                + "  \"auto_cast\": false,\n"
                + "  \"cadence_ms\": 20,\n"
                + "  \"hold_ticks\": 2,\n"
                + "  \"idle_timeout_ms\": 1200,\n"
                + "  \"max_press_per_game\": 200,\n"
                + "  \"max_games\": 0,\n"
                + "  \"use_left\": true,\n"
                + "  \"use_right\": true,\n"
                + "  \"use_shift\": true,\n"
                + "  \"log_frames\": true\n"
                + "}\n";
        Files.writeString(cfg, s, StandardCharsets.UTF_8);
    }

    /** 带 bite_log 的配置（v0.2.1 咬钩观测用）。 */
    static void writeCfgBite(boolean enabled, boolean dryRun, boolean biteLog)
            throws IOException {
        String s = "{\n"
                + "  \"enabled\": " + enabled + ",\n"
                + "  \"dry_run\": " + dryRun + ",\n"
                + "  \"bite_log\": " + biteLog + ",\n"
                + "  \"strategy\": \"cadence\",\n"
                + "  \"auto_cast\": false,\n"
                + "  \"cadence_ms\": 130,\n"
                + "  \"hold_ticks\": 2,\n"
                + "  \"idle_timeout_ms\": 1200,\n"
                + "  \"max_press_per_game\": 200,\n"
                + "  \"max_games\": 0,\n"
                + "  \"use_left\": true,\n"
                + "  \"use_right\": true,\n"
                + "  \"use_shift\": true,\n"
                + "  \"log_frames\": true\n"
                + "}\n";
        Files.writeString(cfg, s, StandardCharsets.UTF_8);
    }

    /** 带 auto_cast / reel_on_bite 的配置（v0.3.0 外层循环用）。 */
    static void writeCfgLoop(boolean enabled, boolean dryRun, boolean autoCast, boolean reelOnBite)
            throws IOException {
        String s = "{\n"
                + "  \"enabled\": " + enabled + ",\n"
                + "  \"dry_run\": " + dryRun + ",\n"
                + "  \"auto_cast\": " + autoCast + ",\n"
                + "  \"reel_on_bite\": " + reelOnBite + ",\n"
                + "  \"reel_delay_ms\": 0,\n"
                + "  \"cast_delay_ms\": 500,\n"
                + "  \"strategy\": \"cadence\",\n"
                + "  \"cadence_ms\": 20,\n"
                + "  \"hold_ticks\": 2,\n"
                + "  \"idle_timeout_ms\": 1200,\n"
                + "  \"max_press_per_game\": 200,\n"
                + "  \"max_games\": 0,\n"
                + "  \"use_left\": true,\n"
                + "  \"use_right\": true,\n"
                + "  \"use_shift\": true,\n"
                + "  \"log_frames\": true\n"
                + "}\n";
        Files.writeString(cfg, s, StandardCharsets.UTF_8);
    }

    /** 带 form_strategy / hold_key / c_margin 的配置（v0.3.0 形态分流用）。 */
    static void writeCfgForm(boolean enabled, boolean dryRun, String strategy,
                             String formStrategy, String holdKey, int cMargin)
            throws IOException {
        String s = "{\n"
                + "  \"enabled\": " + enabled + ",\n"
                + "  \"dry_run\": " + dryRun + ",\n"
                + "  \"strategy\": \"" + strategy + "\",\n"
                + "  \"form_strategy\": \"" + formStrategy + "\",\n"
                + "  \"hold_key\": \"" + holdKey + "\",\n"
                + "  \"c_margin\": " + cMargin + ",\n"
                + "  \"auto_cast\": false,\n"
                + "  \"cadence_ms\": 20,\n"
                + "  \"hold_ticks\": 2,\n"
                + "  \"idle_timeout_ms\": 1200,\n"
                + "  \"max_press_per_game\": 200,\n"
                + "  \"max_games\": 0,\n"
                + "  \"use_left\": true,\n"
                + "  \"use_right\": true,\n"
                + "  \"use_shift\": true,\n"
                + "  \"log_frames\": true\n"
                + "}\n";
        Files.writeString(cfg, s, StandardCharsets.UTF_8);
    }

    static List<Path> logFiles() throws IOException {
        List<Path> out = new ArrayList<>();
        Path dir = Paths.get(System.getProperty("user.home"), ".fishauto", "log");
        if (!Files.isDirectory(dir)) {
            return out;
        }
        try (DirectoryStream<Path> ds = Files.newDirectoryStream(dir, "*.jsonl")) {
            for (Path p : ds) {
                out.add(p);
            }
        }
        return out;
    }

    static int count(String type) throws IOException {
        int n = 0;
        String needle = "\"type\":\"" + type + "\"";
        for (Path p : logFiles()) {
            for (String line : Files.readAllLines(p, StandardCharsets.UTF_8)) {
                if (line.contains(needle)) {
                    n++;
                }
            }
        }
        return n;
    }

    static String find(String type, String extra) throws IOException {
        String needle = "\"type\":\"" + type + "\"";
        for (Path p : logFiles()) {
            for (String line : Files.readAllLines(p, StandardCharsets.UTF_8)) {
                if (line.contains(needle) && (extra == null || line.contains(extra))) {
                    return line.trim();
                }
            }
        }
        return null;
    }

    /** 找 type 事件里含 field 但**不含** exclude 的一行（用来排除默认值，如 -1）。 */
    static String findNot(String type, String field, String exclude) throws IOException {
        String needle = "\"type\":\"" + type + "\"";
        for (Path p : logFiles()) {
            for (String line : Files.readAllLines(p, StandardCharsets.UTF_8)) {
                if (line.contains(needle) && line.contains(field)
                        && (exclude == null || !line.contains(exclude))) {
                    return line.trim();
                }
            }
        }
        return null;
    }

    /** 按任意子串计数（比 count(type) 更细，可区分 key）。 */
    static int countNeedle(String needle) throws IOException {
        int n = 0;
        for (Path p : logFiles()) {
            for (String line : Files.readAllLines(p, StandardCharsets.UTF_8)) {
                if (line.contains(needle)) {
                    n++;
                }
            }
        }
        return n;
    }

    static String statusText() throws IOException {
        Path p = Paths.get(System.getProperty("user.home"), ".fishauto", "status.txt");
        return Files.exists(p) ? Files.readString(p, StandardCharsets.UTF_8) : "";
    }

    static String firstLine(String s) {
        int i = s.indexOf('\n');
        return (i < 0 ? s : s.substring(0, i));
    }

    /** 极简结构校验：引号成对、花括号配平。 */
    static boolean balanced(String s) {
        int q = 0;
        int b = 0;
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '\\') {
                i++;
                continue;
            }
            if (c == '"') {
                q++;
            } else if (c == '{') {
                b++;
            } else if (c == '}') {
                b--;
            }
        }
        return q % 2 == 0 && b == 0;
    }

    static void report() {
        int width = 0;
        for (String n : NAMES) {
            width = Math.max(width, n.length());
        }
        int fail = 0;
        System.out.println();
        for (int i = 0; i < NAMES.size(); i++) {
            boolean ok = OKS.get(i);
            if (!ok) {
                fail++;
            }
            System.out.printf("  %s %-" + width + "s %s%n",
                    ok ? "[v]" : "[X]", NAMES.get(i),
                    DETAIL.get(i).isEmpty() ? "" : "- " + DETAIL.get(i));
        }
        System.out.println();
        if (fail == 0) {
            System.out.println("== 离线验证通过：" + NAMES.size() + " 项全过 ==");
            System.out.println("OFFLINE_OK");
        } else {
            System.out.println("== 离线验证失败：" + fail + "/" + NAMES.size() + " 项不过 ==");
            System.exit(1);
        }
    }
}
