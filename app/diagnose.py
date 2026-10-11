# -*- coding: utf-8 -*-
"""启动失败时的逐步诊断。由 诊断.bat 调用，也可直接 python diagnose.py。

把「bat 层的问题」和「Python/GUI 层的问题」分开：全过 = 问题在 bat/启动方式；
某步报错 = 问题在这一步，照着看就行。
"""
import os
import platform
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

OK = "[OK]  "
BAD = "[FAIL]"
WARN = "[WARN]"

failures = []


def step(n, title):
    print("\n%s %s" % ("-" * 4, title))


def main():
    print("=" * 62)
    print(" 方案C 跟随地图 · 启动诊断")
    print("=" * 62)

    # ---------------------------------------------------------- 1 解释器
    step(1, "Python 解释器")
    print("  可执行文件: %s" % sys.executable)
    print("  版本      : %s" % sys.version.split()[0])
    print("  位数      : %d bit" % (64 if sys.maxsize > 2 ** 32 else 32))
    print("  系统      : %s %s" % (platform.system(), platform.release()))
    print("  代码目录  : %s" % HERE)

    # ---------------------------------------------------------- 2 依赖
    step(2, "依赖模块")
    # numpy 是 memstore / ocr 要的（内存直读层与坐标 OCR）；换电脑装环境时最容易漏。
    for mod, label in [("PIL", "Pillow"), ("PIL.ImageTk", "Pillow ImageTk"),
                       ("numpy", "numpy"), ("tkinter", "tkinter")]:
        try:
            m = __import__(mod, fromlist=["_"])
            v = getattr(m, "__version__", None) or getattr(m, "TkVersion", "?")
            print("  %s %-18s %s" % (OK, label, v))
        except Exception as e:
            print("  %s %-18s %s" % (BAD, label, e))
            failures.append("缺少模块 %s（pip install %s）"
                            % (label, "pillow" if label.startswith("Pillow") else
                               ("numpy" if label == "numpy" else label)))

    # ---------------------------------------------------------- 3 文件
    step(3, "程序文件")
    need = ["followmap/app.py", "followmap/store.py", "followmap/view.py",
            "followmap/memstore.py", "followmap/sources.py", "followmap/ocr.py",
            "followmap/colors.py", "followmap/win32cap.py", "followmap/paths.py",
            "followmap/ruins.py", "followmap/alerts.py",
            "mc_font.py", "hudtext.py", "xaero_region.py",
            "cache/font_ascii.png", "block_colors.json", "ruins.json", "poi.json",
            "assets/drop_high.wav", "assets/drop_mid.wav", "assets/drop_low.wav"]
    for rel in need:
        p = os.path.join(HERE, rel)
        if os.path.exists(p):
            print("  %s %-28s %d 字节" % (OK, rel, os.path.getsize(p)))
        else:
            print("  %s %-28s 缺失" % (BAD, rel))
            failures.append("缺文件 %s" % rel)

    # 启动器 .bat 的编码（最容易踩的坑：地图窗口"打不开"多半就是它）
    import glob as _glob
    bad_bats = []
    for bp in sorted(_glob.glob(os.path.join(HERE, "*.bat"))):
        try:
            raw = open(bp, "rb").read()
        except OSError:
            continue
        n_bad = sum(1 for c in raw if c > 127)
        if n_bad:
            bad_bats.append((os.path.basename(bp), n_bad))
    if bad_bats:
        for nm, n_bad in bad_bats:
            print("  %s %-28s %d 个非 ASCII 字节" % (BAD, nm, n_bad))
        print("       启动器必须保持纯 ASCII：cmd 逐行解析时会按**字节**推进文件")
        print("       指针，中文行的字节数让它漂移，后续行就丢首字符：")
        print("           rem xxx   ->  'em' 不是内部或外部命令")
        print("           set \"SIZE=..\" -> 'et' ...      -> SIZE 变空")
        print("       于是 python 收到 --size --interval，argparse 秒退，窗口打不开。")
        print("       修法：把 bat 里的中文改成英文（地图窗口内部中文不受影响）；")
        print("             改完跑  python check_bats.py --run  复核。")
        failures.append("启动器 .bat 含非 ASCII 字符（会导致地图窗口打不开）")
    else:
        print("  %s %-28s 纯 ASCII，可被 cmd 正确解析" % (OK, "启动器 .bat"))

    # ---------------------------------------------------------- 4 地图数据
    step(4, "Xaero 地图数据（路径自动定位）")
    from followmap import paths as P
    server, why = P.resolve_server()
    print("  模组记录的游戏目录: %s"
          % (P.game_dir_from_mod() or "(status.txt 没写 / 还没跑过游戏)"))
    print("  服务器线索 (host) : %s" % P.server_hint_report())
    print("  选用服务器目录    : %s" % (server or "(没找到)"))
    print("  定位来源          : %s" % why)
    ok_dir = bool(server) and os.path.isdir(server)
    print("  目录存在          : %s" % ("是" if ok_dir else "否"))
    if ok_dir:
        dims = [d for d in os.listdir(server) if os.path.isdir(os.path.join(server, d))]
        print("  维度目录数        : %d" % len(dims))
    else:
        # 这一条是「换电脑后」最容易踩的：不是代码坏了，是那台机器上 Xaero 的
        # 地图目录不在标准位置。给三个明确的手工指定方式，别让人去猜。
        print("  %s 换电脑后如果这里失败：把 Xaero 的服务器目录（就是含各维度"
              "子目录的那一层）写进 %s，" % (BAD, P.CFG_NAME))
        print("       一行即可；也可用环境变量 FOLLOWMAP_XAERO，或启动时加 "
              "--server \"<目录>\"。")
        failures.append("找不到 Xaero 服务器目录（游戏没跑过 / 路径不对）")

    # ---------------------------------------------------------- 5 渲染自检
    step(5, "无窗口渲染自检（不依赖游戏）")
    try:
        from followmap.app import FollowApp, parse_args
        from followmap import sources as S
        # ★ 必须带 --no-ruin：`app.step()` 每帧都会走 _ruin_tick，第一帧就会拉起
        #   后台基线扫描并**写 out/found_ruins.json**。诊断本该是只读的 ——
        #   否则「先跑诊断、后开工具」时，诊断会抢先写进一个不完整的去重库，
        #   里面那几处遗迹之后就被当成"已发现"永久静音了（打包分发时尤其致命：
        #   dist 里的 out/ 本来是空的，跑一次诊断就多出一个残缺库）。
        #   第 9 步本来就会单独打印指纹表与提醒通道，覆盖度不受影响。
        a = parse_args(["--source", "demo", "--size", "300", "--interval", "250",
                        "--no-ruin"])
        app = FollowApp(a)
        app.mode = "demo"
        app.demo_on = True
        for i in range(8):
            img, fix = app.step(0.25)
        print("  %s 渲染 8 帧成功，末帧 %s/%s @ (%.0f, %.0f)，尺寸 %s"
              % (OK, app._dim, app._mw, fix.x, fix.z, img.size))
        print("       单帧耗时约 %.0fms，缺失瓦片 %d" % (app.render_ms, app.missing))
    except Exception:
        print("  %s 渲染自检抛异常：" % BAD)
        traceback.print_exc()
        failures.append("渲染自检失败")

    # ---------------------------------------------------------- 6 坐标源
    step(6, "玩家坐标来源")
    try:
        b = S.BridgeSource()
        print("  模组文件  : %s" % b.path)
        print("  是否已生成: %s" % ("是" if b.available() else "否 —— 需要在装了 coordbridge 后重启游戏"))
        st = os.path.join(os.path.dirname(b.path), "status.txt")
        if os.path.exists(st):
            with open(st, encoding="utf-8", errors="ignore") as fh:
                print("  status.txt: %s" % fh.read().strip()[:400])
        f = b.poll()
        print("  读取结果  : ok=%s  %s" % (f.ok, f.note))
        if f.ok:
            print("  坐标      : X %.1f  Y %.1f  Z %.1f  维度 %s" % (f.x, f.y, f.z, f.dim))
    except Exception as e:
        print("  %s %s" % (BAD, e))
        failures.append("坐标源检查失败")

    try:
        from followmap import win32cap
        ws = win32cap.find_mc()
        if not ws:
            print("  %s 没找到 Minecraft 窗口（游戏没开）" % WARN)
        else:
            for w in ws[:3]:
                print("  窗口 hwnd=%s cls=%s 客户区=%s 最小化=%s"
                      % (w["hwnd"], w.get("cls"), w.get("client"), w.get("iconic")))
    except Exception as e:
        print("  %s 窗口枚举失败: %s" % (WARN, e))

    # ---------------------------------------------------------- 7 内存直读层
    step(7, "内存直读层（CoordBridge 模组直读游戏内存，绕开 Xaero 的 60 秒落盘）")
    try:
        import time as _time
        cb = os.path.join(os.path.expanduser("~"), ".coordbridge")
        chunks = os.path.join(cb, "chunks")
        ss = os.path.join(cb, "scan_status.txt")
        print("  数据目录  : %s  %s" % (cb, "存在" if os.path.isdir(cb) else "不存在"))
        text = ""
        if os.path.exists(ss):
            with open(ss, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
            print("  scan_status.txt:")
            for line in text.rstrip().split("\n")[:16]:
                print("      " + line)
            # 关键：这个模组最容易「静默失效」——反射解析错了不会崩游戏，
            # 只是永远不写数据，表现成「地图一直跟不上」。所以这里必须显式拦。
            bad_markers = ("state        : FAIL", "[miss]", "[bad sig]",
                           "找不到 Class", "找不到 Level", "找不到 Chunk",
                           "找不到 Minecraft", "找不到 Entity", "找不到 ResourceKey",
                           "找不到 Registry", "找不到 Block", "找不到 ServerData")
            hit = [m for m in bad_markers if m in text]
            if hit:
                print("")
                print("  %s 反射解析失败：mod 名字表与现实不符，扫描器不会产出任何数据。" % BAD)
                for line in text.splitlines():
                    if "FAIL" in line or "error" in line or "[" in line:
                        print("       " + line.strip())
                print("       修法：在 app 目录跑 `python modmap.py --check` 核对 Names.java，")
                print("             再 `python build_mod.py` 重打包，最后**重启游戏**。")
                failures.append("CoordBridge 反射解析失败（见 scan_status.txt）")
            elif "total written: 0" in text:
                print("")
                print("  %s 扫描器已启动但一个 chunk 都没写 —— 可能还没进世界。" % WARN)
            else:
                for line in text.splitlines():
                    if line.startswith("total written") or line.startswith("full sweep"):
                        print("  %s %s" % (OK, line.strip()))
        else:
            print("  %s scan_status.txt 不存在 —— 扫描线程没跑起来" % WARN)
            print("       需要装好 coordbridge 并**重启游戏**（改过 jar 必须重启）")
        if os.path.isdir(chunks):
            total = 0
            for d in sorted(os.listdir(chunks)):
                p = os.path.join(chunks, d)
                if not os.path.isdir(p):
                    continue
                n, newest = 0, 0.0
                for root, _dirs, fs in os.walk(p):
                    for f in fs:
                        if not f.endswith(".bin"):
                            continue
                        n += 1
                        try:
                            m = os.path.getmtime(os.path.join(root, f))
                            if m > newest:
                                newest = m
                        except OSError:
                            pass
                total += n
                age = ("%.1f 秒前" % (_time.time() - newest)) if newest else "-"
                print("  %s %-24s %6d 个 chunk   最新 %s" % (OK, d, n, age))
            if total == 0:
                failures.append("内存层没有任何 chunk 数据（扫描器没在产出）")
        else:
            print("  chunks 目录: 不存在（还没扫到任何区块）")
            failures.append("内存层没有 chunks 目录")

        # index_*.json 是内存层的「存在性 + 新鲜度」来源，必须能读到
        idxs = [f for f in os.listdir(cb) if f.startswith("index_") and f.endswith(".json")] \
            if os.path.isdir(cb) else []
        if not idxs:
            print("  %s 没有 index_*.json —— 外部地图会以为没有内存数据" % BAD)
            failures.append("缺 index_*.json")
        else:
            import json as _json
            for f in idxs:
                try:
                    with open(os.path.join(cb, f), encoding="utf-8") as fh:
                        d = _json.load(fh)
                except (OSError, ValueError) as e:
                    print("  %s %s 解析失败: %s" % (BAD, f, e))
                    failures.append("index 文件损坏: %s" % f)
                    continue
                age = _time.time() - d.get("t", 0) / 1000.0
                print("  %s %-28s rev=%s regions=%d sid=%s  更新于 %.1f 秒前"
                      % (OK, f, d.get("rev"), len(d.get("regions", {})),
                         d.get("sid"), age))
    except Exception:
        print("  %s 内存层检查失败：" % BAD)
        traceback.print_exc()
        failures.append("内存层检查失败")

    # ---------------------------------------------------------- 8 GUI
    step(8, "GUI 冒烟测试（建窗口但不进事件循环）")
    try:
        import tkinter as tk
        from PIL import Image, ImageTk
        r = tk.Tk()
        r.withdraw()
        c = tk.Canvas(r, width=64, height=64, highlightthickness=0)
        c.pack()
        iid = c.create_image(0, 0, anchor="nw")
        r.update_idletasks()
        r.update()
        ph = ImageTk.PhotoImage(Image.new("RGBA", (64, 64), (200, 40, 40, 255)))
        c.itemconfigure(iid, image=ph)
        r.update_idletasks()
        r.destroy()
        print("  %s Tk 窗口 / Canvas / PhotoImage 全部可用" % OK)
    except Exception:
        print("  %s GUI 冒烟测试失败：" % BAD)
        traceback.print_exc()
        failures.append("GUI 不可用")

    # ---------------------------------------------------------- 9 遗迹提醒
    step(9, "稀有遗迹提醒（巫师/武士/白金，只读已落盘区块）")
    try:
        from followmap.ruins import Signatures, RuinWatcher
        from followmap.alerts import ensure_assets, SOUNDS
        sg = Signatures()
        if not sg.ok:
            print("  %s 指纹表读不出来：%s" % (BAD, sg.error or "未启用任何类型"))
            print("       修法：检查 %s 是否存在且是合法 JSON" % sg.path)
            failures.append("遗迹指纹表不可用")
        else:
            print("  %s 指纹表 %s  纯度阈值 %.2f  判定窗口 %dx%d 区块"
                  % (OK, os.path.basename(sg.path), sg.min_purity,
                     sg.window, sg.window))
            if sg.groups:
                print("      方块家族 %d 个：%s"
                      % (len(sg.groups),
                         ", ".join("@%s(%d种)" % (k, len(v))
                                   for k, v in sg.groups.items())))
            else:
                print("  %s 指纹表没有定义方块家族（groups）——"
                      "锚点只能钉在单个方块名上，容易漏掉变体" % WARN)
                failures.append("指纹表缺少 groups（会导致变体漏检）")
            for name, m in sg.types.items():
                an = " ".join("%s>=%d" % (k.replace("minecraft:", ""), v)
                              for k, v in m["anchors"].items())
                nrat = len(m.get("ratios") or {}) + sum(
                    1 for g in m["any"] for k in g if k.startswith("%"))
                print("      %-8s 硬特征 %d 项  占比通路 %d 条  可选组 %d 组  用料 %d 种  音效 %s"
                      % (name, len(m["anchors"]), nrat, len(m["any"]),
                         len(sg._sets[name]), m["sound"]))
                print("               锚点: %s" % an)
                for i, g in enumerate(m["any"]):
                    parts = []
                    for k, v in g.items():
                        if k.startswith("%"):
                            # 占比阈值：写成百分比，和「计数阈值」一眼区分开
                            parts.append("%s>=%d%%"
                                         % (k[1:].replace("minecraft:", ""),
                                            round(v * 100)))
                        else:
                            parts.append("%s>=%s" % (k.replace("minecraft:", ""), v))
                    print("               通路%d: %s" % (i + 1, " 且 ".join(parts)))
            # 抗淹没自检：没有任何「占比通路」= 全是绝对计数锚点，被地形淹没的实例必漏
            has_ratio = any((t.get("ratios") or {})
                            or any(k.startswith("%")
                                   for g in (t.get("any") or []) for k in g)
                            for t in sg.types.values())
            if not has_ratio:
                print("  %s 指纹表里没有任何占比通路（ratios 或 any 里的 %%键）——"
                      "被地形淹没的实例会漏检" % WARN)
                failures.append("指纹表缺少占比通路（会导致地形淹没漏检）")
        # 音效资源（现场合成，缺失或参数变了都会自动重算）
        try:
            from followmap.alerts import Alerter, PING_REPEATS, SOUND_VOLUME
            al = Alerter()
            print("  %s 提醒通道：%s" % (OK, al.status()))
            print("      默认不抖窗口（使用场景是笔记本屏挂机、外接屏刷视频，"
                  "眼睛不在笔记本屏上）；要抖动用 --ruin-alert both")
            if al.sounds:
                import wave as _wave
                p0 = sorted(al.sounds.values())[0]
                with _wave.open(p0, "rb") as wf:
                    dur = wf.getnframes() / float(wf.getframerate())
                print("      水滴音：%d 连响 / 时长 %.2fs / 音量 %.2f（峰值已归一化到满刻度）"
                      % (PING_REPEATS, dur, SOUND_VOLUME))
        except Exception:
            print("  %s 提醒层自检失败：" % BAD)
            traceback.print_exc()
            failures.append("提醒层自检失败")
        adir = os.path.join(HERE, "assets")
        snd = ensure_assets(adir)
        if not snd:
            print("  %s 水滴音合成失败（不影响识别，只会没有声音）" % WARN)
        else:
            miss = [n for n in SOUNDS if n not in snd]
            print("  %s 水滴音 %d/%d 就绪：%s"
                  % (OK, len(snd), len(SOUNDS),
                     ", ".join("%s(%dKB)" % (n, os.path.getsize(p) // 1024)
                               for n, p in sorted(snd.items()))))
            if miss:
                failures.append("水滴音缺失: %s" % ", ".join(miss))
        # 实际盯着的区块数据
        w = RuinWatcher()
        dims = w._scan_dims()
        print("  可识别的维度: %s" % (", ".join(sorted(dims)) or "（无）"))
        if not dims:
            print("  %s 没有 chunks 数据 —— 模组还没跑过（改过 jar 必须重启游戏）" % WARN)
        nbin = 0
        for dim in dims:
            idx = w._read_index(dim)
            if idx:
                print("      %-28s sid=%s rev=%s chunks=%s regions=%d"
                      % (dim, idx.get("sid"), idx.get("rev"),
                         idx.get("chunks"), len(idx.get("regions") or {})))
        # 已有的命中记录
        fp = w.found_path
        if os.path.exists(fp):
            import json as _json
            with open(fp, encoding="utf-8") as fh:
                fd = _json.load(fh).get("found") or []
            from collections import Counter
            c = Counter(it.get("type") for it in fd)
            print("  %s 已记录遗迹 %d 处（%s）  %s"
                  % (OK, len(fd), ", ".join("%s×%d" % kv for kv in c.items()), fp))
        else:
            print("  还没记录任何遗迹（%s 不存在，正常运行后会生成）" % os.path.basename(fp))
        log = os.path.join(HERE, "out", "ruin_alerts.log")
        if os.path.exists(log):
            with open(log, encoding="utf-8", errors="ignore") as fh:
                lines = fh.read().rstrip().split("\n")
            print("  最近提醒 %d 条，末条：%s" % (len(lines), lines[-1][:70]))
    except Exception:
        print("  %s 遗迹提醒检查失败：" % BAD)
        traceback.print_exc()
        failures.append("遗迹提醒层检查失败")

    # ---------------------------------------------------------- 10 崩溃日志
    step(10, "历史崩溃日志")
    crash = os.path.join(HERE, "out", "crash.log")
    if os.path.exists(crash):
        print("  发现 %s：" % crash)
        with open(crash, encoding="utf-8", errors="ignore") as fh:
            tail = fh.read()[-1500:]
        print("  " + tail.replace("\n", "\n  "))
        print("  （建议先解决这个 traceback）")
    else:
        print("  无崩溃日志（说明 GUI 主循环没抛过异常）")

    # ---------------------------------------------------------- 总结
    print("\n" + "=" * 62)
    if failures:
        print(" 结果：发现 %d 个问题" % len(failures))
        for f in failures:
            print("   - %s" % f)
        print("\n 把以上完整内容发回来即可定位。")
        return 1
    print(" 结果：全部通过。")
    print(" 说明 Python / 数据 / GUI 三层都正常，问题只可能在 bat 或启动方式上。")
    print(" 下一步：直接双击 启动跟随地图.bat；若仍无窗口，看 out\\crash.log。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
