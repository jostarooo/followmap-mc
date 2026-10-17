package fishauto;

import java.io.BufferedWriter;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Locale;

/**
 * 运行日志：{@code ~/.fishauto/log/session-<时间>-auto.jsonl}，一行一事件，每行 flush。
 *
 * 三件事必须记全，否则这一版就白跑了（它同时承担「下一版学习数据」的角色）：
 * <ol>
 *   <li>**本体的每一个动作**：按了什么键、第几次、当时字幕长什么样 ——
 *       有了「按键时刻 + 当时帧」，才可能事后反推真正的判定规则；</li>
 *   <li>**每一帧原始字幕**（不含按键也记）—— 指纹与几何两路分析都靠它；</li>
 *   <li>**结果**：成功 / 失败 / 超时，来自游戏自带反馈文本。</li>
 * </ol>
 *
 * OFF 语义与 fishprobe 一致：{@code ~/.fishauto/OFF} 存在即停采（不必重启）。
 * 另设 **急停**：{@code ~/.fishauto/STOP} 存在 → 立即停止自动按键（但继续记录）。
 */
public final class Sink {
    private Sink() {
    }

    static Path home;
    private static Path logDir;
    private static Writer out;
    private static String file = "";

    private static boolean off;
    private static boolean stop;
    private static long lastCheck;

    private static final DateTimeFormatter TS = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss");

    public static void init() {
        try {
            home = Paths.get(System.getProperty("user.home"), ".fishauto");
            logDir = home.resolve("log");
            Files.createDirectories(logDir);
            checkFlags();
        } catch (Throwable t) {
            // 旁路设施：任何失败都不能影响游戏
        }
    }

    /** 每 1 秒最多碰一次磁盘。 */
    static boolean isOff() {
        long now = System.currentTimeMillis();
        if (now - lastCheck > 1000L) {
            checkFlags();
            lastCheck = now;
        }
        return off;
    }

    /** 急停：~/.fishauto/STOP 存在 —— 仍在记录，但**不再按键**。 */
    static boolean isStopped() {
        long now = System.currentTimeMillis();
        if (now - lastCheck > 1000L) {
            checkFlags();
            lastCheck = now;
        }
        return stop;
    }

    private static void checkFlags() {
        try {
            off = home != null && Files.exists(home.resolve("OFF"));
            stop = home != null && Files.exists(home.resolve("STOP"));
        } catch (Throwable t) {
            off = false;
            stop = false;
        }
    }

    static String sessionName() {
        return file;
    }

    public static void openSession(String tag) {
        close();
        try {
            String ts = LocalDateTime.now().format(TS);
            file = "session-" + ts + "-" + tag + ".jsonl";
            Path f = logDir.resolve(file);
            out = new BufferedWriter(new OutputStreamWriter(
                    new FileOutputStream(f.toFile(), true), StandardCharsets.UTF_8), 8192);
            line("{\"t\":" + num(nano()) + ",\"wall\":" + wall()
                    + ",\"type\":\"session\",\"event\":\"open\",\"tag\":\"" + esc(tag)
                    + "\",\"file\":\"" + esc(file) + "\"}");
        } catch (Throwable t) {
            out = null;
        }
    }

    public static void close() {
        if (out != null) {
            try {
                out.flush();
                out.close();
            } catch (Throwable ignored) {
                // 忽略
            }
            out = null;
        }
    }

    static void line(String json) {
        if (out == null) {
            return;
        }
        try {
            out.write(json);
            out.write('\n');
            out.flush();
        } catch (Throwable ignored) {
            // 忽略
        }
    }

    /** 反射自检报告 -> ~/.fishauto/status.txt（排障第一现场）。 */
    static void status(String text) {
        try {
            Files.writeString(home.resolve("status.txt"), text, StandardCharsets.UTF_8);
        } catch (Throwable ignored) {
            // 忽略
        }
    }

    static long wall() {
        return System.currentTimeMillis();
    }

    static double nano() {
        return System.nanoTime() / 1.0e9;
    }

    static String num(double d) {
        return String.format(Locale.ROOT, "%.6f", d);
    }

    static String esc(String s) {
        if (s == null) {
            return "";
        }
        StringBuilder sb = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) {
                        sb.append(String.format(Locale.ROOT, "\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
            }
        }
        return sb.toString();
    }
}
