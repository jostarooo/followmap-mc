package net.minecraft;

import fishprobe.Probe;
import fishprobe.Sink;

import java.io.File;
import java.util.UUID;

/**
 * 离线跑一遍 fishprobe 的完整采集链路（不需要装游戏）。
 *
 * 放在 net.minecraft 包里是为了能直接用包私有的桩类；
 * fishprobe 侧的 Probe/Sink 入口是 public（见各自类注释）。
 *
 * 用法（由 offline_check.py 驱动）：
 *     java -cp <out> net.minecraft.OfflineTest <临时HOME>
 */
public class OfflineTest {

    public static void main(String[] args) throws Exception {
        String home = args.length > 0 ? args[0]
                : new File(System.getProperty("java.io.tmpdir"), "fishprobe-offline").getAbsolutePath();
        new File(home).mkdirs();
        // ★ 必须在 Sink.init() 之前改 user.home，否则会写进真实的 ~/.fishprobe
        System.setProperty("user.home", home);

        Sink.init();   // 会话文件由 Probe.tick() 在「进入世界」时自动开

        // ---------------------------------------------------------- 搭桩世界
        class_310 mc = new class_310();
        class_310._set(mc);
        class_329 gui = new class_329();
        class_746 player = new class_746();
        mc.field_1705 = gui;
        mc.field_1724 = player;
        mc.field_1687 = new Object();          // 非 null => 判定"在世界里"

        class_1792 rod = new class_1792("minecraft:fishing_rod");
        class_1792 bait = new class_1792("minecraft:carrot");
        class_1792 air = new class_1792("minecraft:air");
        class_7923.field_41178 = o -> new class_2960(
                o instanceof class_1792 ? ((class_1792) o).id : "minecraft:air");

        player.mainHand = new class_1799(rod);
        player.offHand = new class_1799(bait);
        player.field_7520 = 37;

        // 1) 进世界：开会话 + 状态快照
        Probe.tick();

        // 2) BossBar 出现，进度逐帧推进（shown 与 raw 故意不同，验证两条数据都读到）
        class_1259 bar = new class_1259();
        bar.setName("🀄 钓鱼");
        gui.method_1740().field_2060.put(UUID.randomUUID(), bar);
        for (int i = 0; i <= 10; i++) {
            bar.field_5774 = i / 10f;          // 服务器原始值
            bar.shownLerp = i / 10f + 0.05f;   // 客户端插值
            Probe.tick();
        }

        // 3) Title 弹出，再清空
        gui.setTitle("按下左键 开始");
        Probe.tick();
        gui.setTitle(null);
        Probe.tick();

        // 4) 动作栏
        gui.setActionBar("在关键时刻收杆");
        Probe.tick();

        // 5) 收杆后鱼竿换回空手（跨过 snapshot 的 5-tick 节拍）
        player.mainHand = new class_1799(air);
        for (int i = 0; i < 5; i++) {
            Probe.tick();
        }

        Sink.close();
        System.out.println("OFFLINE_OK home=" + home);
    }
}
