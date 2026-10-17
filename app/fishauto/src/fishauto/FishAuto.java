package fishauto;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;

/**
 * 入口。和 fishprobe 一样刻意只用 fabric-api-base + fabric-lifecycle-events-v1，
 * 并且用**隐式 lambda**（不写参数类型）—— Fabric API 的接口签名用的是 remap 后的
 * {@code net.minecraft.class_xxx} 名，写显式类型就会要求那些类出现在编译 classpath 上。
 */
public class FishAuto implements ClientModInitializer {
    @Override
    public void onInitializeClient() {
        Sink.init();
        Config.init();
        ClientTickEvents.END_CLIENT_TICK.register(client -> AutoFish.tick());
    }
}
