package net.minecraft;

/**
 * **编译期桩类，不进 jar、不参与运行。**
 *
 * 存在的唯一理由：Fabric API 的 tick 事件接口签名是（remap 后的）
 * {@code void onEndTick(net.minecraft.class_310)}。javac 解析
 * {@code ClientTickEvents.END_CLIENT_TICK.register(...)} 时需要这个类型存在，
 * 而 fishauto 是纯反射模组、编译时**故意不带 MC jar**。
 *
 * 因此只造一个空壳满足编译器；运行期加载的永远是游戏真正的 class_310。
 * 打包时按包名 {net/minecraft/*} 把它排除掉（见 build_fishprobe.py 的 sources/jar 逻辑）。
 */
public class class_310 {
}
