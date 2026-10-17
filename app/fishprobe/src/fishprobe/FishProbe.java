package fishprobe;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;

/**
 * 入口。只做两件事：初始化落盘目录、挂 tick 采集。
 *
 * **刻意不依赖 networking 模块**：会话的开/关由 {@link Probe#tick()} 通过
 * "level 是否为 null"自动判定（进世界 = 开新文件，回主菜单 = 关文件）。
 * 这样依赖面缩到最小（只要 fabric-api-base + fabric-lifecycle-events-v1），
 * 也就少一条运行期被别的模组版本冲突打断的链路。
 *
 * 这里用**隐式 lambda**（不写参数类型）：Fabric API 的接口签名用的是 remap 后的
 * {@code net.minecraft.class_xxx} 名，而我们编译时不带 MC jar，写显式类型会要求
 * 那些类出现在 classpath 上。隐式推断正好绕开。
 */
public class FishProbe implements ClientModInitializer {
    @Override
    public void onInitializeClient() {
        Sink.init();
        ClientTickEvents.END_CLIENT_TICK.register(client -> Probe.tick());
    }
}
