package predcheck;

import net.fabricmc.loader.api.Version;
import net.fabricmc.loader.api.metadata.version.VersionPredicate;
import net.fabricmc.loader.impl.util.version.VersionPredicateParser;

/**
 * 用 Fabric 自己的谓词解析器，实测 fishprobe 的 fabric.mod.json 里那三条 depends。
 *
 * 为什么必须实测：谓词语法写错（或用错语义）时，Fabric 会**直接拒绝加载整个模组**
 * —— 而且只在游戏启动日志里留一行，很容易被忽略。离线先跑一遍最省事。
 */
public final class PredCheck {
    private static int fail;

    private PredCheck() {
    }

    private static void t(String label, boolean got, boolean want) {
        boolean ok = got == want;
        if (!ok) {
            fail++;
        }
        System.out.printf("  [%s] %-52s test=%-5s 期望=%s%n",
                ok ? "v" : "X", label, got, want);
    }

    public static void main(String[] args) throws Exception {
        System.out.println("用 Fabric loader 的解析器实测依赖谓词：");

        VersionPredicate mc = VersionPredicateParser.parse(">=1.20.1 <1.20.5");
        t("minecraft >=1.20.1 <1.20.5  vs  1.20.4（日常）", mc.test(Version.parse("1.20.4")), true);
        t("minecraft >=1.20.1 <1.20.5  vs  1.20.1（V3.0）", mc.test(Version.parse("1.20.1")), true);
        t("minecraft >=1.20.1 <1.20.5  vs  1.19.4（应排除）", mc.test(Version.parse("1.19.4")), false);
        t("minecraft >=1.20.1 <1.20.5  vs  1.20.5（应排除）", mc.test(Version.parse("1.20.5")), false);

        VersionPredicate ld = VersionPredicateParser.parse(">=0.15.0");
        t("fabricloader >=0.15.0  vs  0.16.14（1.20.4 实例）", ld.test(Version.parse("0.16.14")), true);
        t("fabricloader >=0.15.0  vs  0.19.3（V3.0 实例）", ld.test(Version.parse("0.19.3")), true);
        t("fabricloader >=0.15.0  vs  0.14.22（应排除）", ld.test(Version.parse("0.14.22")), false);

        // 参考信息，不断言：0.1.0 用的 ~1.20.1 在新版本上的行为
        try {
            VersionPredicate old = VersionPredicateParser.parse("~1.20.1");
            System.out.printf("  [i] 参考：旧谓词 ~1.20.1 对 1.20.4 = %s%n",
                    old.test(Version.parse("1.20.4")));
        } catch (Exception e) {
            System.out.printf("  [i] 参考：~1.20.1 解析/求值异常 %s%n", e);
        }

        if (fail == 0) {
            System.out.println("\n== 谓词校验通过：fabric.mod.json 的 depends 不会被 Fabric 拒绝 ==");
        } else {
            System.out.printf("%n== 有 %d 项不符合预期 ==%n", fail);
        }
        System.exit(fail == 0 ? 0 : 1);
    }
}
