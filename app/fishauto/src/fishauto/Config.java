package fishauto;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 配置：{@code ~/.fishauto/config.json}，**热加载**（每 1 秒查一次 mtime）。
 * 改完存盘即生效，不必重启游戏 —— 调试期这一点非常值钱。
 *
 * 默认值刻意保守：**enabled=false 且 dry_run=true**。
 * 也就是说：装上去什么都不会发生，必须显式打开才会按键。
 *
 *   enabled           总开关（false = 连判定都不做）
 *   dry_run           true = 只判定 + 只记录，**绝不按键**（默认）
 *   strategy          cadence = 固定节奏连按（v0.1 行为，默认，保回滚）
 *                     geometry = 看指针进绿区才按（v0.2 新增，需自行开）
 *   geo_rule          geometry 的判定规则：center（指针中心入区，默认/最优）
 *                     | left（指针左沿入区）| whole（指针整体入区）
 *   geo_margin        几何判定的余量 px（默认 8；实测帧总宽残差 ±4.5px，必须容忍）
 *   geo_lead_px       提前量 px（默认 0；实测指针中位 +1px/帧，已被余量覆盖）
 *   auto_cast         true = 手上拿鱼竿且没抛竿时自动右键抛竿（默认 false）
 *   cadence_ms        连按间隔；geometry 模式下兼作「两次按下的最小冷却」
 *   hold_ticks        「按住」类按键（Shift）按几个 tick（20 tick = 1s）
 *   idle_timeout_ms   多久没有新字幕帧就认为本局结束
 *   max_press_per_game 单局按键次数上限（防呆）
 *   max_games         连续自动多少局后自动停（0 = 不限）
 *   use_left/use_right/use_shift  允许使用哪些按键
 *   log_frames        是否把 QTE 每一帧原始字幕也记进日志（数据很有用，默认 true）
 *   bite_log          ★v0.2.1★ 是否观测「咬钩信号」：每 tick 读一次 player.fishing.biting
 *                     与它的 Δmotion.y，只在**边沿**写 hook_bite / hook_clear 两行。
 *                     **只记录，不参与任何决策**（默认 false）。它**不受 enabled 影响** ——
 *                     所以可以「enabled=false + bite_log=true」纯观测，一个键都不按。
 *
 * ★ v0.3.0：完整循环（抛竿 -> 咬钩 -> 收杆）★
 *   reel_on_bite      true = 检测到咬钩**自动右键收杆**（默认 false）。
 *                     这是"按节拍"的替代：实测上鱼时间随机、重新抛竿会重置，
 *                     而 biting 是服务端同步的真信号，咬钩 -> 小游戏开局只隔 300~360ms。
 *   reel_delay_ms     咬钩后延迟多少 ms 再收杆（默认 0 = 立刻）
 *   cast_delay_ms     一局结束后延迟多少 ms 再抛竿（默认 1500；给服务器留出结算时间）
 *   form_strategy     ★B/C 形态怎么处理★
 *                     observe = 只把形态写进日志，一个键都不按（默认，最安全）
 *                     auto    = A 走 geometry；C 按底图判定色段按键；B 仍不按（无可靠信号）
 *   c_margin          C 形态判定余量 px（作用于**指针中心**，默认 0）
 *                     实测（app/_probe_replayC.py，20 局回放）：余量 0 时 14/20 的
 *                     按下点**精确落在色段内**；余量 2 掉到 6/20 —— 因为余量会把
 *                     触发点整体前移，窄色段（bar8 只有 5px）一前移就压到边界外。
 *   hold_key          「收杆/彩色」型用哪个键：**right（默认）** | left | shift
 *                     —— 实测 C 形态（彩虹条/颜色题）就是玩家说的「右键收杆型」，
 *                     题面里没有「按下 X 开始」，所以键只能由配置给。改成别的键即回滚。
 */
public final class Config {
    private Config() {
    }

    private static Path path;
    private static long mtime = -1;
    private static long lastCheck;

    // 生效值
    public static boolean enabled = false;
    public static boolean dryRun = true;
    public static String strategy = "cadence";
    public static String geoRule = "center";
    public static int geoMargin = 8;
    public static int geoLeadPx = 0;
    public static boolean autoCast = false;
    public static int cadenceMs = 130;
    public static int holdTicks = 2;
    public static int idleTimeoutMs = 1200;
    public static int maxPressPerGame = 80;
    public static int maxGames = 0;
    public static boolean useLeft = true;
    public static boolean useRight = true;
    public static boolean useShift = true;
    public static boolean logFrames = true;
    /** ★ v0.2.1：咬钩信号观测（只记录，不参与任何决策）。与 enabled 无关。 */
    public static boolean biteLog = false;

    // ---- ★ v0.3.0：完整循环（抛竿 -> 咬钩 -> 收杆 -> 小游戏 -> 循环）----
    /** 咬钩时自动右键收杆（默认 false）。这是"按节拍"的替代品。 */
    public static boolean reelOnBite = false;
    /** 咬钩后延迟多少 ms 再收杆（0 = 立刻）。 */
    public static int reelDelayMs = 0;
    /** 一局结束后延迟多少 ms 再抛竿。 */
    public static int castDelayMs = 1500;
    /** B/C 形态策略：observe（只观测，默认）| auto（自动按键）。 */
    public static String formStrategy = "observe";
    /** C 形态判定余量 px（作用于**指针中心**；标定不确定度 ±4px，默认 2）。 */
    public static int cMargin = 0;
    /** 「收杆/彩色」型默认用哪个键：right（默认）| left | shift。 */
    public static String holdKey = "right";

    public static String source = "(默认值，未读到配置文件)";

    public static void init() {
        try {
            path = Paths.get(System.getProperty("user.home"), ".fishauto", "config.json");
            if (!Files.exists(path)) {
                Files.createDirectories(path.getParent());
                Files.writeString(path, defaultJson(), StandardCharsets.UTF_8);
            }
            reload(true);
        } catch (Throwable t) {
            // 配置读不到就用默认值（且默认是关的）
        }
    }

    /** 每秒查一次 mtime，变了就重载。 */
    static void maybeReload() {
        long now = System.currentTimeMillis();
        if (now - lastCheck < 1000L) {
            return;
        }
        lastCheck = now;
        reload(false);
    }

    private static void reload(boolean force) {
        try {
            if (path == null || !Files.exists(path)) {
                return;
            }
            long m = Files.getLastModifiedTime(path).toMillis();
            if (!force && m == mtime) {
                return;
            }
            mtime = m;
            Map<String, String> kv = parse(Files.readString(path, StandardCharsets.UTF_8));
            enabled = bool(kv, "enabled", enabled);
            dryRun = bool(kv, "dry_run", dryRun);
            strategy = str(kv, "strategy", strategy);
            geoRule = str(kv, "geo_rule", geoRule);
            geoMargin = num(kv, "geo_margin", geoMargin);
            geoLeadPx = num(kv, "geo_lead_px", geoLeadPx);
            autoCast = bool(kv, "auto_cast", autoCast);
            cadenceMs = Math.max(20, num(kv, "cadence_ms", cadenceMs));
            holdTicks = Math.max(1, num(kv, "hold_ticks", holdTicks));
            idleTimeoutMs = Math.max(200, num(kv, "idle_timeout_ms", idleTimeoutMs));
            maxPressPerGame = Math.max(1, num(kv, "max_press_per_game", maxPressPerGame));
            maxGames = Math.max(0, num(kv, "max_games", maxGames));
            useLeft = bool(kv, "use_left", useLeft);
            useRight = bool(kv, "use_right", useRight);
            useShift = bool(kv, "use_shift", useShift);
            logFrames = bool(kv, "log_frames", logFrames);
            biteLog = bool(kv, "bite_log", biteLog);
            reelOnBite = bool(kv, "reel_on_bite", reelOnBite);
            reelDelayMs = Math.max(0, num(kv, "reel_delay_ms", reelDelayMs));
            castDelayMs = Math.max(200, num(kv, "cast_delay_ms", castDelayMs));
            formStrategy = str(kv, "form_strategy", formStrategy);
            cMargin = Math.max(0, num(kv, "c_margin", cMargin));
            holdKey = str(kv, "hold_key", holdKey);
            source = "已加载 " + path + " @" + m;
        } catch (Throwable t) {
            source = "配置解析失败：" + t.getClass().getSimpleName() + " " + t.getMessage();
        }
    }

    public static String describe() {
        return "enabled=" + enabled + " dry_run=" + dryRun
                + " strategy=" + strategy
                + ("geometry".equals(strategy)
                        ? "(rule=" + geoRule + " margin=" + geoMargin + "px lead=" + geoLeadPx + "px)"
                        : "")
                + " cadence=" + cadenceMs + "ms hold=" + holdTicks + "t"
                + " idle=" + idleTimeoutMs + "ms maxpress=" + maxPressPerGame
                + " keys[left=" + useLeft + " right=" + useRight + " shift=" + useShift + "]"
                + " bite_log=" + biteLog
                + " reel=" + reelOnBite + " form=" + formStrategy;
    }

    /** geometry 策略是否生效（配置写错时安全退化到 cadence）。 */
    public static boolean geometry() {
        return "geometry".equalsIgnoreCase(strategy);
    }

    /** B/C 形态是否允许自动按键。 */
    public static boolean formAuto() {
        return "auto".equalsIgnoreCase(formStrategy);
    }

    // ------------------------------------------------------------------ 极简 JSON
    /**
     * 只认 `"key": 123` / `"key": true` / `"key": "str"` 这种平铺标量。
     * 刻意不引 JSON 库：模组依赖面越小越不容易和别的模组冲突。
     */
    private static Map<String, String> parse(String s) {
        Map<String, String> out = new LinkedHashMap<>();
        int i = 0;
        while (true) {
            int q = s.indexOf('"', i);
            if (q < 0) {
                break;
            }
            int e = s.indexOf('"', q + 1);
            if (e < 0) {
                break;
            }
            String key = s.substring(q + 1, e);
            int c = s.indexOf(':', e + 1);
            if (c < 0) {
                break;
            }
            int j = c + 1;
            while (j < s.length() && Character.isWhitespace(s.charAt(j))) {
                j++;
            }
            String val;
            if (j < s.length() && s.charAt(j) == '"') {
                int v = s.indexOf('"', j + 1);
                if (v < 0) {
                    break;
                }
                val = s.substring(j + 1, v);
                i = v + 1;
            } else {
                int k = j;
                while (k < s.length() && ",}\n\r".indexOf(s.charAt(k)) < 0) {
                    k++;
                }
                val = s.substring(j, k).trim();
                i = k;
            }
            out.put(key, val);
        }
        return out;
    }

    private static boolean bool(Map<String, String> kv, String k, boolean dft) {
        String v = kv.get(k);
        if (v == null) {
            return dft;
        }
        return "true".equalsIgnoreCase(v) || "1".equals(v) || "yes".equalsIgnoreCase(v);
    }

    private static String str(Map<String, String> kv, String k, String dft) {
        String v = kv.get(k);
        return (v == null || v.isEmpty()) ? dft : v.trim().toLowerCase(java.util.Locale.ROOT);
    }

    private static int num(Map<String, String> kv, String k, int dft) {
        try {
            String v = kv.get(k);
            return v == null ? dft : (int) Double.parseDouble(v);
        } catch (Throwable t) {
            return dft;
        }
    }

    private static String defaultJson() {
        return "{\n"
                + "  \"_说明\": \"enabled 总开关；dry_run=true 只判定不按键；改完存盘即热加载。"
                + "strategy=cadence 固定连按（默认，=v0.1 行为），geometry 看指针进绿区才按\",\n"
                + "  \"enabled\": false,\n"
                + "  \"dry_run\": true,\n"
                + "  \"strategy\": \"cadence\",\n"
                + "  \"geo_rule\": \"center\",\n"
                + "  \"geo_margin\": 8,\n"
                + "  \"geo_lead_px\": 0,\n"
                + "  \"auto_cast\": false,\n"
                + "  \"cadence_ms\": 130,\n"
                + "  \"hold_ticks\": 2,\n"
                + "  \"idle_timeout_ms\": 1200,\n"
                + "  \"max_press_per_game\": 80,\n"
                + "  \"max_games\": 0,\n"
                + "  \"use_left\": true,\n"
                + "  \"use_right\": true,\n"
                + "  \"use_shift\": true,\n"
                + "  \"log_frames\": true,\n"
                + "  \"bite_log\": false,\n"
                + "  \"reel_on_bite\": false,\n"
                + "  \"reel_delay_ms\": 0,\n"
                + "  \"cast_delay_ms\": 1500,\n"
                + "  \"form_strategy\": \"observe\",\n"
                + "  \"c_margin\": 0,\n"
                + "  \"hold_key\": \"right\"\n"
                + "}\n";
    }
}
