package fishprobe;

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
 * 事件流落盘：{@code ~/.fishprobe/events/<会话>.jsonl}，一行一事件，追加写。
 *
 * 三条设计约束（都是为事后分析服务）：
 * 1. **一行 flush 一次**。采集时最怕"游戏崩了/被杀进程，最后几秒数据全丢"——
 *    而 QTE 恰恰是最后几秒最有价值。flush 的开销在 20 行/秒的量级下可忽略。
 * 2. **两个时间戳都记**。见 {@link #nano()} 与 {@link #wall()}：同进程算间隔用 nano，
 *    跨进程（模组 <-> Python 键鼠记录器）对齐用墙钟，两边缺一不可。
 * 3. **会话独立成文件**，永不覆盖 —— 每次 JOIN 开新文件，这就是训练集本身。
 */
public final class Sink {
    private Sink() {
    }

    /** ~/.fishprobe */
    static Path home;
    private static Path eventsDir;
    private static Writer out;
    private static String sessionFile = "";

    /** OFF 文件存在 -> 暂停采集（不必改配置、不必重启游戏）。 */
    private static boolean off;
    private static long lastOffCheck;

    private static final DateTimeFormatter TS =
            DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss");

    public static void init() {
        try {
            home = Paths.get(System.getProperty("user.home"), ".fishprobe");
            eventsDir = home.resolve("events");
            Files.createDirectories(eventsDir);
            checkOff();
        } catch (Throwable t) {
            // 探针是旁路设施：任何失败都不能影响游戏
        }
    }

    /** 每 1 秒最多查一次 OFF 文件，避免每 tick 都碰磁盘。 */
    static boolean isOff() {
        long now = System.currentTimeMillis();
        if (now - lastOffCheck > 1000L) {
            checkOff();
            lastOffCheck = now;
        }
        return off;
    }

    private static void checkOff() {
        try {
            off = home != null && Files.exists(home.resolve("OFF"));
        } catch (Throwable t) {
            off = false;
        }
    }

    /** 开一个新会话文件。tag 只进文件名（如 join），便于人眼区分。 */
    public static void openSession(String tag) {
        close();
        try {
            String ts = LocalDateTime.now().format(TS);
            sessionFile = "session-" + ts + "-" + tag + ".jsonl";
            Path f = eventsDir.resolve(sessionFile);
            out = new BufferedWriter(new OutputStreamWriter(
                    new FileOutputStream(f.toFile(), true), StandardCharsets.UTF_8), 8192);
            line("{\"t\":" + num(nano()) + ",\"wall\":" + wall()
                    + ",\"type\":\"session\",\"event\":\"open\",\"tag\":\"" + esc(tag)
                    + "\",\"file\":\"" + esc(sessionFile) + "\"}");
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

    /** 写一行。out 为 null（未开会话）时静默丢弃。 */
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

    /** 把反射解析报告写到 ~/.fishprobe/status.txt —— 排障第一现场。 */
    static void status(String text) {
        try {
            Files.writeString(home.resolve("status.txt"), text, StandardCharsets.UTF_8);
        } catch (Throwable ignored) {
            // 忽略
        }
    }

    // ------------------------------------------------------------------ 时间
    /** 墙钟毫秒。跨进程对齐的唯一桥梁（nanoTime 的基准在进程间不可比）。 */
    static long wall() {
        return System.currentTimeMillis();
    }

    /** 单调秒（nanoTime/1e9）。同进程内算间隔用它，不受系统改时间影响。 */
    static double nano() {
        return System.nanoTime() / 1.0e9;
    }

    static String num(double d) {
        return String.format(Locale.ROOT, "%.6f", d);
    }

    // ------------------------------------------------------------------ JSON
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
