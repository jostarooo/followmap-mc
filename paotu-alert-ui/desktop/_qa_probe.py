# -*- coding: utf-8 -*-
"""布局探针：在真实 WebView2 里按不同宽度量顶栏是否溢出。用完即删。

用法: python _qa_probe.py [宽度,宽度,...]
"""
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "_probe.log"

os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--no-sandbox")

SETUP = r"""
(function () {
  var U = window.PaoTuAlertUI;
  if (!U) return 'no-ui';
  U.setLive(true);
  U.applyRuntime({dim:'minecraft:overworld', world:'minecraft_mcfkcs.com_12345',
                  inGame:true, x:10167.1, y:86.0, z:15753.4, memLag:0.10, memBuilds:3000,
                  nav:'实时坐标 · 已落盘 3000 块 · 延迟 0.10s'});
  return 'live';
})()
"""

PROBE = r"""
(function () {
  var de = document.documentElement;
  var tb = document.querySelector('.topbar');
  var pills = document.querySelector('.pills');
  var brand = document.querySelector('.brand');
  var over = [].slice.call(document.querySelectorAll('*')).filter(function (n) {
    var r = n.getBoundingClientRect();
    return r.width > 0 && r.right > de.clientWidth + 1;
  }).slice(0, 6).map(function (n) {
    return n.tagName + '.' + (n.className || '').toString().slice(0, 20);
  });
  return JSON.stringify({
    innerW: window.innerWidth,
    clientW: de.clientWidth,
    scrollW: de.scrollWidth,
    hOverflow: de.scrollWidth > de.clientWidth,
    topbarH: Math.round(tb.getBoundingClientRect().height),
    brandW: Math.round(brand.getBoundingClientRect().width),
    pillsW: Math.round(pills.getBoundingClientRect().width),
    pillsH: Math.round(pills.getBoundingClientRect().height),
    pillsRight: Math.round(pills.getBoundingClientRect().right),
    pillCount: pills.querySelectorAll('.pill, .btn').length,
    liveText: (document.querySelector('#liveName') || {}).textContent,
    overflowing: over
  });
})()
"""


def w(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(str(m) + "\n")


LOG.write_text("", encoding="utf-8")

import webview  # noqa: E402

UI = HERE.parent / "index.html"
win = webview.create_window("PROBE", UI.as_uri() + "#live=1", width=1560, height=980)
ready = threading.Event()
win.events.loaded += ready.set
sizes = [int(x) for x in (sys.argv[1].split(",") if len(sys.argv) > 1
                          else "1920,1560,1366,1280,1120,900,600,390".split(","))]


def probe():
    if not ready.wait(25):
        w("loaded 事件超时")
        os._exit(1)
    time.sleep(1.2)
    try:
        w("setup => " + str(win.evaluate_js(SETUP)))
    except Exception as e:                                    # noqa: BLE001
        w("setup ERR %r" % (e,))
    for width in sizes:
        try:
            win.resize(width, 900)
        except Exception as e:                                # noqa: BLE001
            w("resize(%d) 失败 %r" % (width, e))
            continue
        time.sleep(0.9)
        try:
            w("%4d  %s" % (width, win.evaluate_js(PROBE)))
        except Exception as e:                                # noqa: BLE001
            w("%4d  ERR %r" % (width, e))
    os._exit(0)


threading.Thread(target=probe, daemon=True).start()
webview.start(gui="edgechromium", private_mode=False,
              storage_path=str(HERE / "_probestore"), debug=False)
