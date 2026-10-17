"""轮询最新 fishauto 会话日志，等待下一个「咬钩 / QTE」事件。

用法:  python _watch_fish.py [超时秒数]

只报新产生的、和收杆 QTE 有关的行：
  notice(含 按下/开始/上钩/收杆) / qte_begin / signal / qte_end / 首个 frame
命中即退出（返回码 0）；超时返回 2。

存在意义：Windows 侧截图一次要 1~3 秒，而读本地日志只要几十毫秒，
所以用它当「传感器」给外部操控当触发器。
"""
import json
import os
import glob
import sys
import time

LOG = os.path.expanduser("~/.fishauto/log")
KEYWORDS = ("\u6309\u4e0b", "\u5f00\u59cb", "\u4e0a\u94a9", "\u6536\u6746")  # 按下/开始/上钩/收杆


def newest():
    fs = glob.glob(os.path.join(LOG, "session-*.jsonl"))
    return max(fs, key=os.path.getmtime) if fs else None


def main():
    secs = 20.0
    for a in sys.argv[1:]:
        if a.startswith("-"):
            continue
        try:
            secs = float(a)
        except ValueError:
            pass

    f = newest()
    if not f:
        print("(no log)")
        return 1
    pos = os.path.getsize(f)
    t0 = time.time()
    seen_frame = False
    nframe = 0

    while time.time() - t0 < secs:
        cur = newest()
        if cur:
            f = cur
        try:
            size = os.path.getsize(f)
        except OSError:
            time.sleep(0.05)
            continue
        if size < pos:
            pos = 0
        if size > pos:
            with open(f, encoding="utf-8", errors="replace") as fh:
                fh.seek(pos)
                chunk = fh.read()
                pos = fh.tell()
            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                t = o.get("type")
                if t == "frame":
                    nframe += 1
                    if not seen_frame:
                        seen_frame = True
                        print("FRAME %s" % json.dumps(o, ensure_ascii=False)[:150])
                    continue
                if t == "hb":
                    continue
                txt = o.get("text") or ""
                hit = t in ("qte_begin", "signal", "qte_end") or \
                    (t == "notice" and any(k in txt for k in KEYWORDS))
                if not hit:
                    continue
                print("%-9s %s" % (t, json.dumps(o, ensure_ascii=False)[:220]))
                if nframe:
                    print("(共 %d 帧)" % nframe)
                return 0
        time.sleep(0.05)

    print("(timeout %.0fs, 期间 %d 帧)" % (secs, nframe))
    return 2


if __name__ == "__main__":
    sys.exit(main())
