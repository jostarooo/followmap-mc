# -*- coding: utf-8 -*-
"""窗口缩放验证：逻辑层（无窗口）+ 真开窗口按键/滚轮。

用法：python _modtest/test_resize.py
"""
import os
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from followmap.app import (FollowApp, MIN_W, MIN_H, RESIZE_FACTOR,  # noqa: E402
                           parse_args)

FAIL = []


def check(desc, got, want):
    ok = got == want
    print("   %-52s %-22s %s" % (desc, repr(got), "OK" if ok else "<<< 期望 " + repr(want)))
    if not ok:
        FAIL.append(desc)
    return ok


def part_a():
    print("=" * 78)
    print("A) 尺寸逻辑（无窗口）：夹紧、等比缩放、复位")
    print("=" * 78)
    args = parse_args(["--size", "400x300", "--source", "demo", "--interval", "200"])
    app = FollowApp(args)
    app._screen = (1920, 1080)
    check("启动尺寸", app.size, (400, 300))
    check("复位目标 = 启动尺寸", app.launch_size, (400, 300))

    check("下界夹紧 clamp(50,50)", app.clamp_size(50, 50), (MIN_W, MIN_H))
    check("上界夹紧 clamp(99999,99999)", app.clamp_size(99999, 99999),
          (int(1920 * 0.98), int(1080 * 0.98)))

    big = app.size_step(+1)
    small = app.size_step(-1)
    print("   放大一步 %s -> %s（x%.2f）" % (app.size, big, big[0] / app.size[0]))
    print("   缩小一步 %s -> %s（x%.2f）" % (app.size, small, small[0] / app.size[0]))
    check("放大的比例≈RESIZE_FACTOR", round(big[0] / app.size[0], 2), round(RESIZE_FACTOR, 2))
    check("缩小的比例≈1/RESIZE_FACTOR", round(small[0] / app.size[0], 2),
          round(1 / RESIZE_FACTOR, 2))

    # 一直放大也不该超过屏幕
    app.size = (400, 300)
    for _ in range(40):
        app.size = app.size_step(+1)
    check("狂放大 40 次后仍 <= 屏幕 98%",
          app.size[0] <= int(1920 * 0.98) and app.size[1] <= int(1080 * 0.98), True)
    # 一直缩小也不该低于下界
    for _ in range(40):
        app.size = app.size_step(-1)
    check("狂缩小 40 次后仍 >= 下界", app.size, (MIN_W, MIN_H))

    # 视野随尺寸线性变化（说明渲染真的按新尺寸走，不是只改了窗口壳）
    app.size = (400, 300)
    app.zoom = 2
    s1 = app.view_span()
    app.size = (800, 300)
    check("视野宽度随窗口宽度翻倍", (s1, app.view_span()), (800, 1600))
    return app.launch_size


def part_b(launch):
    print()
    print("=" * 78)
    print("B) 真开窗口：按 + / -，看 Tk 窗口尺寸是不是真的变了")
    print("=" * 78)
    if os.environ.get("SKIP_GUI"):
        print("   SKIP_GUI=1，跳过")
        return
    args = parse_args(["--size", "360", "--source", "demo", "--interval", "120",
                       "--no-top"])
    app = FollowApp(args)

    got = {"before": None, "after_key": None, "after_ctrl_wheel": None,
           "after_minus": None, "after_reset": None}
    orig_mainloop = tk.Tk.mainloop

    def fake_mainloop(self):
        root = self
        for _ in range(6):
            root.update_idletasks()
            root.update()
        got["before"] = (root.winfo_width(), root.winfo_height())

        root.focus_force()
        for _ in range(3):
            root.event_generate("<KeyPress-plus>")
            root.update_idletasks()
            root.update()
        got["after_key"] = (root.winfo_width(), root.winfo_height())

        # Ctrl+滚轮（Windows 上 Ctrl 在 state 的 0x0004 位）
        for _ in range(3):
            root.event_generate("<MouseWheel>", delta=120, state=0x0004)
            root.update_idletasks()
            root.update()
        got["after_ctrl_wheel"] = (root.winfo_width(), root.winfo_height())

        root.event_generate("<KeyPress-minus>")
        for _ in range(6):
            root.update_idletasks()
            root.update()
        got["after_minus"] = (root.winfo_width(), root.winfo_height())

        root.event_generate("<KeyPress-0>")
        for _ in range(6):
            root.update_idletasks()
            root.update()
        got["after_reset"] = (root.winfo_width(), root.winfo_height())
        root.destroy()

    tk.Tk.mainloop = fake_mainloop
    try:
        app.run()
    finally:
        tk.Tk.mainloop = orig_mainloop

    print("   窗口尺寸轨迹：")
    for k in ("before", "after_key", "after_ctrl_wheel", "after_minus", "after_reset"):
        print("      %-18s %s" % (k, got[k]))
    check("启动 = 请求的 360x360", got["before"], (360, 360))
    check("按 3 次 + 后变大", got["after_key"][0] > got["before"][0], True)
    check("Ctrl+滚轮 3 次后继续变大",
          got["after_ctrl_wheel"][0] > got["after_key"][0], True)
    check("按 - 后变小", got["after_minus"][0] < got["after_ctrl_wheel"][0], True)
    check("按 0 后回到启动尺寸", got["after_reset"], launch)


if __name__ == "__main__":
    part_a()
    part_b((360, 360))
    print()
    if FAIL:
        print("结论：%d 项不符 -> %s" % (len(FAIL), "; ".join(FAIL)))
        sys.exit(2)
    print("结论：全部通过")
