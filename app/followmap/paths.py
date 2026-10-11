# -*- coding: utf-8 -*-
"""运行期路径定位：Xaero 地图目录 + CoordBridge 数据目录。

**为什么单独一个模块**：这两个路径都跟「这台机器」绑定——装的是哪个启动器、
整合包放在哪、Xaero 给服务器起的目录叫什么名字。写死就没法拷到别人电脑上用
（用户实测的需求：程序要能直接发给外地的另一台电脑）。所有「找路径」的逻辑
集中在这里，`app.py` 和 `diagnose.py` 共用同一套，避免两边行为不一致。

定位顺序（先命中先用；全失败返回空串 -> 上层按「没有底图」降级，不崩）：

  1. 命令行 ``--server <目录>``
  2. 环境变量 ``FOLLOWMAP_XAERO``
  3. 本程序目录下的 ``server_path.txt``（一行；可写服务器目录，也可写
     ``XaeroWorldMap`` 目录，后者会再往下挑服务器）
  4. **模组 ``status.txt`` 里记录的游戏目录**（最可靠：模组自己写的 cwd，
     不用猜）。形如 ``cwd : D:\\...\\versions\\1.20.4-Fabric 0.16.14``，
     ``XaeroWorldMap`` 就在它下面。
  5. ``cache/server_path.auto.txt``（上一次盘符扫描的结果，省下 9 秒重扫。
     **故意和 ``server_path.txt`` 分开**：人工口子优先级高于模组数据，自动结果
     写在它之下，模组一旦跑过就能自动纠正错猜）
  6. 常见启动器位置扫描（官方启动器 / CurseForge / Prism / Modrinth / HMCL）
  7. 老机器上的默认位置（兜底，保证以前能跑的一直能跑）
  8. 盘符扫描（最后手段；本机把整合包放在 ``D:\\config\\game\\mc\\pcl2`` 下，
     不属于任何标准位置，当年只有这一条能找出来。成功后把结果写进第 5 条）

第 4/6 条里「挑哪个服务器目录」是关键：本机 XaeroWorldMap 下同时有 5 个服务器
目录（``Multiplayer_mcfkcs.com`` / ``Multiplayer_play.mctop1.com`` /
``Multiplayer_play.mctop1.top`` / ``Multiplayer_Unknown`` / ``新的世界``）。
只按「哪个最新」挑，会在玩家刚去过别的服务器时挑错。所以这里**先用真实数据
定位**：``~/.coordbridge/coords.json`` 里有当前服务器的 host，而 Xaero 的目录名
恰好就是 ``Multiplayer_<host>`` —— 匹配上就直接用，匹配不上再退回「region 最新」。

坐标源目录同理：``COORDBRIDGE_HOME`` 环境变量 > ``~/.coordbridge``。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)                 # app/

XAERO_DIR_NAME = "XaeroWorldMap"
CFG_NAME = "server_path.txt"

# 老机器上的默认位置：只为兜底，不再是唯一答案。
LEGACY_SERVER = os.path.join(
    r"D:\config\game\mc\pcl2\.minecraft\versions\1.20.4-Fabric 0.16.14",
    XAERO_DIR_NAME, "Multiplayer_mcfkcs.com")

# 判「哪个服务器目录更新」时，每个目录最多看这么多个 region 文件就够（够判新鲜度，
# 又不会被几万个 zip 拖慢）。region 文件是 <服务器>/<维度>/<mw>/<rx>_<rz>.zip。
_MAX_ZIP_SCAN = 400
_BUDGET_SHALLOW = 4000       # 标准启动器位置扫描的目录访问预算
_BUDGET_DEEP = 1500          # 每个盘符的预算（上限，防止在超大目录树里卡住）


# ------------------------------------------------------------------ 坐标源目录
def coordbridge_home():
    """CoordBridge 模组的落盘目录（默认 ~/.coordbridge，可用环境变量覆盖）。"""
    return (os.environ.get("COORDBRIDGE_HOME")
            or os.path.join(os.path.expanduser("~"), ".coordbridge"))


# ------------------------------------------------------------------ 服务器线索
_hint_cache = None


def server_hint():
    """当前服务器的 host（来自 CoordBridge 的 coords.json），用来在多服务器目录里挑对那个。

    直接读**真实运行数据**，不猜：coords.json 里的 ``server`` 形如
    ``mcfkcs.com:12345``，去掉端口就是 Xaero 目录名里的那一段。
    """
    global _hint_cache
    if _hint_cache is not None:
        return _hint_cache
    hint = ""
    p = os.path.join(coordbridge_home(), "coords.json")
    try:
        with open(p, encoding="utf-8") as fh:
            raw = json.load(fh) or {}
        hint = str(raw.get("server") or "").split(":")[0].strip().lower()
    except Exception:
        hint = ""
    _hint_cache = hint
    return hint


def server_hint_report():
    """给诊断输出用的一行说明。"""
    return server_hint() or "(coords.json 里没有记录，或模组还没跑过)"


def _norm(s):
    """把目录名归一成可比较的形式：下划线当点，全部小写。"""
    return (s or "").replace("_", ".").lower()


def game_dir_from_mod():
    """从模组的 status.txt 读游戏目录。

    status.txt 里有一行 ``cwd    : <游戏目录>``（Fabric 的工作目录），
    这是**模组自己写出来的**，不需要猜。读不到返回空串。
    """
    p = os.path.join(coordbridge_home(), "status.txt")
    try:
        with open(p, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                k, _, v = line.partition(":")
                if k.strip().lower() == "cwd":
                    d = v.strip()
                    if d and os.path.isdir(d):
                        return d
    except OSError:
        pass
    return ""


# ------------------------------------------------------------------ 新鲜度 / 挑服务器
def latest_activity(server_dir):
    """该服务器目录里最新一个 region zip 的 mtime（0 = 没有任何地图数据）。"""
    best = 0.0
    n = 0
    base_len = len(server_dir.rstrip("\\/"))
    for root, dirs, files in os.walk(server_dir):
        if root[base_len:].count(os.sep) >= 3:      # 只看到 <维度>/<mw> 两层
            dirs[:] = []
            continue
        for f in files:
            if not f.endswith(".zip"):
                continue
            try:
                m = os.path.getmtime(os.path.join(root, f))
            except OSError:
                continue
            if m > best:
                best = m
            n += 1
            if n >= _MAX_ZIP_SCAN:
                return best
    return best


def pick_server(xaero_dir, hint=None):
    """在 ``XaeroWorldMap`` 下挑服务器目录 -> (路径, 理由)。没有可用目录时返回 (None, "")。"""
    if hint is None:
        hint = server_hint()
    try:
        names = os.listdir(xaero_dir)
    except OSError:
        return None, ""
    best = (None, "", -1e18)
    for name in names:
        if name.startswith("."):
            continue
        p = os.path.join(xaero_dir, name)
        if not os.path.isdir(p):
            continue
        act = latest_activity(p)
        if act <= 0:                       # 没有任何 region：不是我们要的服
            continue
        score, why = act, "地图数据最新"
        if hint and hint in _norm(name):
            score += 1e12
            why = "匹配当前服务器 %s" % hint
        if score > best[2]:
            best = (p, why, score)
    return (best[0], best[1]) if best[0] else (None, "")


def _best_from(xaero_dirs, hint):
    """一批 XaeroWorldMap 目录里挑最好的服务器目录 -> (路径, 理由)。"""
    best = (None, "", -1e18)
    for xaero in xaero_dirs:
        p, why = pick_server(xaero, hint)
        if not p:
            continue
        score = latest_activity(p) + (1e12 if (hint and hint in _norm(p)) else 0)
        if score > best[2]:
            best = (p, why, score)
    return (best[0], best[1]) if best[0] else (None, "")


# ------------------------------------------------------------------ 扫描
def _mc_roots():
    """常见启动器/整合包可能放 ``.minecraft`` 的位置（只扫这些，不做全盘搜索）。"""
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    roots = [
        os.path.join(appdata, ".minecraft"),                          # 官方启动器
        os.path.join(home, ".minecraft"),
        os.path.join(home, "curseforge", "minecraft", "Instances"),    # CurseForge
        os.path.join(appdata, "PrismLauncher", "instances"),          # Prism
        os.path.join(appdata, "com.modrinth.theseus", "profiles"),     # Modrinth
        os.path.join(home, "AppData", "Roaming", "gdlauncher_next", "instances"),
        os.path.join(appdata, "HMCL", ".minecraft"),                  # HMCL
        os.path.join(home, "Documents", "curseforge", "minecraft", "Instances"),
    ]
    # 程序自己所在的一两层目录也扫（很多人会把整合包和这个工具放在一起）。
    for base in (APP, os.path.dirname(APP)):
        try:
            for d in os.listdir(base):
                p = os.path.join(base, d)
                if os.path.isdir(p):
                    roots.append(p)
        except OSError:
            pass
    seen, out = set(), []
    for r in roots:
        rp = os.path.realpath(r)
        if rp not in seen:
            seen.add(rp)
            out.append(r)
    return out


# 盘符扫描时跳过的目录：系统目录 + 出了名的大目录（不跳的话 C 盘能扫到天亮）。
_HEAVY = {
    "windows", "program files", "program files (x86)", "programdata",
    "$recycle.bin", "system volume information", "appdata", "node_modules",
    ".git", ".cache", "temp", "tmp", "msys2", "mingw64", "intel", "amd",
    "nvidia", "perflogs", "recovery", "onedrivetemp", "$windows.~bt",
    "python", "anaconda3", "miniconda3", "nuget", "pip", "scoop", "chocolatey",
    "vmware", "hyper-v", "installer", "assembly", "microsoft", "reference",
}
# 允许进入的点开头目录：只有 .minecraft（Xaero 的地图就藏在它下面）。
_DOT_ALLOW = {".minecraft"}
# 任何模式下都不值得进的目录（里面不可能有 XaeroWorldMap，但文件极多）。
_ALWAYS_SKIP = {"assets", "libraries", "downloads", "__pycache__", "node_modules",
                "crash-reports", "screenshots", "shaderpacks", "resourcepacks"}


def _fixed_drives():
    """存在的盘符根目录。只探 C~J（不碰 A/B 软驱），不需要管理员权限。"""
    out = []
    for c in "CDEFGHIJ":
        r = c + ":\\"
        try:
            if os.path.exists(r):
                out.append(r)
        except OSError:
            pass
    return out


def _walk(roots, max_depth, budget, skip_heavy=False):
    """在若干根目录下限深遍历 -> (XaeroWorldMap 列表, .minecraft 列表)。"""
    xaero, mc_dirs, seen = [], [], set()
    left = [budget]

    def visit(d, depth):
        if left[0] <= 0:
            return
        left[0] -= 1
        try:
            names = os.listdir(d)
        except OSError:
            return
        if os.path.basename(d.rstrip("\\/")).lower() == ".minecraft":
            rp = os.path.realpath(d)
            if rp not in seen:
                seen.add(rp)
                mc_dirs.append(d)
        for name in names:
            if left[0] <= 0:
                return
            low = name.lower()
            if name.startswith(".") and low not in _DOT_ALLOW:
                continue
            if low in _ALWAYS_SKIP:
                continue
            if skip_heavy and low in _HEAVY:
                continue
            p = os.path.join(d, name)
            if not os.path.isdir(p):
                continue
            if low == ".minecraft":
                # ★ 关键：**列到它时就记下来，但不进去**。
                # 早期版本只在「进入访问」时才记录，于是 `D:\config\game\mc\pcl2\.minecraft`
                # 这种深一层的装法永远找不到（要再多一层才够深）。
                # 不进去是因为 .minecraft 下有 assets/libraries 几万文件，钻进去纯浪费；
                # 里面真正有用的 versions/saves 交给 _xaero_under_mc 单独钻。
                rp = os.path.realpath(p)
                if rp not in seen:
                    seen.add(rp)
                    mc_dirs.append(p)
                continue
            if name == XAERO_DIR_NAME:
                rp = os.path.realpath(p)
                if rp not in seen:
                    seen.add(rp)
                    xaero.append(p)
                continue
            if depth + 1 < max_depth:
                visit(p, depth + 1)

    for root in roots:
        if os.path.isdir(root):
            visit(root, 0)
    return xaero, mc_dirs


def _xaero_under_mc(mc_dirs):
    """``.minecraft`` 下的 XaeroWorldMap 藏在 ``versions/<版本>/`` 里，单独钻一层。

    只往 ``versions`` 和 ``saves`` 里看：``.minecraft`` 下还有 ``assets``/
    ``libraries`` 这种几万文件的目录，盲扫等于白发时间。
    """
    roots = []
    for mc in mc_dirs:
        for sub in ("versions", "saves"):
            p = os.path.join(mc, sub)
            if os.path.isdir(p):
                roots.append(p)
    if not roots:
        return []
    xaero, _ = _walk(roots, 4, _BUDGET_DEEP, skip_heavy=True)
    return xaero


def find_xaero_dirs(deep=False):
    """找 ``XaeroWorldMap`` 目录 -> 列表。

    ``deep=False``：只扫常见启动器位置（便宜）。
    ``deep=True`` ：再扫所有固定盘符 + 钻进 ``.minecraft``。**最后手段**——
    非系统盘查 5 层，C 盘只查 3 层（系统目录多且慢）。
    """
    xaero, mc_dirs = _walk(_mc_roots(), 5, _BUDGET_SHALLOW)
    xaero += _xaero_under_mc(mc_dirs)
    if not deep:
        return _dedup(xaero)
    for r in _fixed_drives():
        depth = 3 if r.upper().startswith("C") else 5
        x, m = _walk([r], depth, _BUDGET_DEEP, skip_heavy=True)
        xaero += x
        xaero += _xaero_under_mc(m)
    return _dedup(xaero)


def _dedup(paths):
    seen, out = set(), []
    for p in paths:
        rp = os.path.realpath(p)
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out


# ------------------------------------------------------------------ 对外入口
def _resolve_one(cand):
    """把一个候选值解析成服务器目录；解析不出来返回空串。"""
    if not cand:
        return ""
    p = os.path.expanduser(os.path.expandvars(str(cand).strip().strip('"')))
    if not p:
        return ""
    if os.path.basename(p.rstrip("\\/")) == XAERO_DIR_NAME:
        got, _ = pick_server(p)
        return got or ""
    return p if os.path.isdir(p) else ""


def _cfg_line():
    try:
        with open(os.path.join(APP, CFG_NAME), encoding="utf-8-sig") as fh:
            for line in fh:
                s = line.strip()
                if s and not s.startswith("#"):
                    return s
    except OSError:
        pass
    return ""


def _auto_cache_path():
    """自动缓存**不放在 server_path.txt 里**（那是人工口子、优先级更高），
    单独放 cache/ 下，排在模组 status.txt 之后，让模组数据可以纠正它。"""
    return os.path.join(APP, "cache", "server_path.auto.txt")


def _from_mod_status(hint):
    """模组 status.txt 给出的游戏目录 -> (服务器目录, 说明)。"""
    gd = game_dir_from_mod()
    if not gd:
        return None, ""
    cands = [os.path.join(gd, XAERO_DIR_NAME),
             os.path.join(gd, ".minecraft", XAERO_DIR_NAME)]
    if os.path.basename(gd.rstrip("\\/")).lower() == ".minecraft":
        cands.insert(0, os.path.join(gd, XAERO_DIR_NAME))
    for c in cands:
        if os.path.isdir(c):
            p, why = pick_server(c, hint)
            if p:
                return p, "模组 status.txt 的游戏目录（%s）" % why
    return None, ""


def _read_auto_cache():
    """读自动缓存的路径（盘符扫描的结果），排在模组 status.txt **之后**。"""
    try:
        with open(_auto_cache_path(), encoding="utf-8-sig") as fh:
            for line in fh:
                s = line.strip()
                if s and not s.startswith("#"):
                    return s
    except OSError:
        pass
    return ""


def _write_auto_cache(server_dir):
    """把盘符扫描的结果缓存起来，下次启动不用再扫 9 秒。

    **故意不写 server_path.txt**：那是人工口子，优先级排在模组 status.txt 之前。
    自动结果要是写进去，就会盖过模组给出的准确答案——典型场景是「先开工具、
    后开游戏」，猜到一个别的 MC 版本的地图目录，之后再也纠不回来。
    缓存文件排在模组数据之后，模组一旦跑过就能自动纠正。
    """
    try:
        p = _auto_cache_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("# 自动缓存（盘符扫描的结果）。删掉即可重扫；"
                     "要人工指定请用上一层目录的 server_path.txt。\n")
            fh.write(server_dir + "\n")
    except OSError:
        pass


def resolve_server(explicit=None):
    """定位 Xaero 服务器目录 -> (目录, 来源说明)。找不到返回 ("", 说明)。

    分档执行，**便宜的先试、贵的只在必要时才付**（盘符扫描要几秒，不能每次启动都做）。

    某一档「指明了却不可用」时**不直接失败**，而是记一笔继续往下找 —— 换电脑后
    最怕的就是因为一个过期的 `--server` 让整个窗口彻底没底图。但那笔记录会**附到
    最终成功那一档的说明里**（形如「…（注意：命令行 --server 指向的目录不可用：…）」），
    免得「显式指定被无声忽略」变成新的迷惑点。
    """
    notes = []

    def ok(path, src):
        return path, ("%s（注意：%s）" % (src, "；".join(notes)) if notes else src)

    for cand, src in ((explicit, "命令行 --server"),
                      (os.environ.get("FOLLOWMAP_XAERO"), "环境变量 FOLLOWMAP_XAERO"),
                      (_cfg_line(), CFG_NAME)):
        if not cand:
            continue
        got = _resolve_one(cand)
        if got:
            return ok(got, src)
        notes.append("%s 指向的目录不可用：%s" % (src, cand))

    hint = server_hint()

    got, why = _from_mod_status(hint)
    if got:
        return ok(got, why)

    # 上一次盘符扫描的结果（排在模组数据之后：模组一旦跑过就覆盖它，不会答错）。
    got = _resolve_one(_read_auto_cache())
    if got:
        return ok(got, "上次盘符扫描的缓存（%s）" % os.path.basename(got.rstrip("\\/")))

    got, why = _best_from(find_xaero_dirs(deep=False), hint)
    if got:
        return ok(got, "自动扫描（%s）" % why)

    if os.path.isdir(LEGACY_SERVER):
        return ok(LEGACY_SERVER, "旧的默认位置（本机硬编码路径）")

    got, why = _best_from(find_xaero_dirs(deep=True), hint)
    if got:
        _write_auto_cache(got)
        return ok(got, "盘符扫描（%s）" % why)

    return "", "；".join(notes) or "未找到 Xaero 地图目录"


# ------------------------------------------------------------------ 自检
def _fmt(t):
    import time
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "—"


if __name__ == "__main__":
    import time
    print("CoordBridge 目录    :", coordbridge_home())
    print("模组记录的游戏目录  :", game_dir_from_mod() or "(status.txt 没写 / 还没跑过游戏)")
    print("服务器线索 (host)   :", server_hint_report())
    print()
    t0 = time.time()
    found = find_xaero_dirs(deep=False)
    print("浅扫到 %d 个 XaeroWorldMap（%.2fs）：" % (len(found), time.time() - t0))
    for x in found:
        print("  ", x)
        try:
            for name in sorted(os.listdir(x)):
                p = os.path.join(x, name)
                if os.path.isdir(p):
                    print("       %-34s 最新 %s" % (name, _fmt(latest_activity(p))))
        except OSError:
            pass
    print()
    t0 = time.time()
    s, why = resolve_server()
    print("选用: %s   （%.2fs）" % (s or "(没找到)", time.time() - t0))
    print("来源:", why)
    print("存在:", os.path.isdir(s) if s else False)
