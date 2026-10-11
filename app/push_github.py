#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把本项目「当前版本」发布到 GitHub 仓库 jostarooo/followmap-mc（走 API）。

为什么不用 git push
-------------------
本机 `github.com` 网页域名被代理挡住（超时），但 `api.github.com` 可达，
所以 `git push`（git 协议 / HTTPS 网页域名）走不通。本脚本改用 GitHub 的
**Git Data API**：blobs -> tree -> commit -> ref，效果与一次 `git push` 等同。

用法
----
    python push_github.py                     # 推当前 HEAD（不改工作区）
    python push_github.py --commit            # 先把工作区改动提交（自动写提交信息）再推
    python push_github.py --commit -m "修 xxx" # 用指定提交信息
    python push_github.py --build --commit    # 先重编模组 jar，再提交并推
    python push_github.py --dry-run           # 只列清单，不联网

    （双击同目录的 `发布到GitHub.bat` 等于 `--build --commit`，最省事。）

Token 从哪来（按顺序找，用第一个命中的）
----------------------------------------
    1) 命令行  --token xxx
    2) 环境变量 GH_TOKEN / GITHUB_TOKEN
    3) --token-file 指定的文件
    4) %USERPROFILE%\\.followmap-gh-token     （自己建，文件里只放一行 token）

Token 需要的权限（细粒度 token 的两个坑，都实测踩过）
-----------------------------------------------------
    * Repository access 必须包含本仓库（选 All repositories 最省事）
    * Repository permissions -> **Contents: Read and write**
      只把仓库加进访问列表只解决「看得见」，不解决「写得进」：
      症状是 `POST /git/blobs` 返回 403 `Resource not accessible by personal access token`。
    * 细粒度 token **不能创建仓库**（`POST /user/repos` -> 403）。本仓库已建好，
      正常发布走不到那一步。

已知的 API 行为（别当成 bug）
-----------------------------
    * 零提交的空仓库上 Git Data API 会 409 `Git Repository is empty` ——
      blobs/trees/commits 都要求仓库里已有 git 对象，那是第一次提交才创建的。
      本脚本检测到分支不存在时会先用 Contents API 放一个 `.gitkeep` 把仓库激活。
    * GitHub 存 commit message 时会**去掉结尾换行**，所以远端 commit 的 SHA
      与本地同内容的提交**必然不同**（tree SHA 仍然相同）。这是正常的。

只读本地 git 对象；只有在显式给了 --commit 时才会动工作区（git add + commit）。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
HERE = os.path.dirname(os.path.abspath(__file__))        # app/
DEFAULT_ROOT = os.path.dirname(HERE)                     # 项目根
DEFAULT_OWNER = "jostarooo"
DEFAULT_REPO = "followmap-mc"
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".followmap-gh-token")


# --------------------------------------------------------------------------- #
# git
# --------------------------------------------------------------------------- #
def git(*args, cwd=None, check=True):
    r = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True)
    if check and r.returncode != 0:
        raise SystemExit("git %s 失败：%s"
                         % (" ".join(args), r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout


def local_tree(root):
    """从 git 索引取文件清单 + 内容（用索引里的字节，与提交完全一致）。"""
    names = [n for n in git("ls-files", "-z", cwd=root).split(b"\0") if n]
    return [(n.decode("utf-8"), git("cat-file", "blob", ":" + n.decode("utf-8"), cwd=root))
            for n in names]


def head_author(root):
    """本地 HEAD 的作者/提交者（原样带到远端，免得被换成 token 主人的账号信息）。"""
    out = {}
    try:
        raw = git("log", "-1", "--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI",
                  cwd=root).decode("utf-8", "replace").strip()
        an, ae, ad, cn, ce, cd = raw.split("\x00")
        out["author"] = {"name": an, "email": ae, "date": ad}
        out["committer"] = {"name": cn, "email": ce, "date": cd}
    except Exception:                                    # noqa: BLE001
        pass
    return out


def mod_version(root):
    try:
        with open(os.path.join(root, "app", "coordbridge", "fabric.mod.json"),
                  encoding="utf-8") as fh:
            return json.load(fh).get("version")
    except Exception:                                    # noqa: BLE001
        return None


def auto_message(root):
    """自动写一条像样的提交信息：时间 + 模组版本 + 变更清单（最多列 12 个）。"""
    lines = git("status", "--porcelain", cwd=root).decode("utf-8", "replace").splitlines()
    paths = []
    for ln in lines:
        p = ln[3:].strip().strip('"')
        if " -> " in p:                                  # 重命名
            p = p.split(" -> ", 1)[1]
        paths.append(p)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    ver = mod_version(root)
    head = "发布 %s" % stamp
    if ver:
        head += "（模组 v%s）" % ver
    body = ["", "变更 %d 个文件：" % len(paths)]
    for p in paths[:12]:
        body.append("- %s" % p)
    if len(paths) > 12:
        body.append("- …（其余 %d 个）" % (len(paths) - 12))
    return head + "\n" + "\n".join(body)


def ensure_commit(args):
    """--commit：把工作区改动提交好（没有改动就跳过）。"""
    dirty = git("status", "--porcelain", cwd=args.root).decode("utf-8", "replace").strip()
    if not dirty:
        print("工作区干净，没有需要提交的改动。")
        return
    msg = args.message or auto_message(args.root)
    git("add", "-A", cwd=args.root)
    git("commit", "-q", "-m", msg, cwd=args.root)
    print("已提交：")
    for ln in git("log", "-1", "--format=%h %s", cwd=args.root).decode("utf-8", "replace").splitlines():
        print("  " + ln)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def api(method, path, token, payload=None, ok=(200, 201)):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "followmap-publisher")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        if e.code in ok:
            return json.loads(detail) if detail.strip().startswith("{") else None
        if e.code == 401:
            raise SystemExit(
                "HTTP 401：token 无效或已被撤销。\n"
                "  重新生成一个后设置 GH_TOKEN 环境变量，或写进 %s" % TOKEN_FILE)
        if e.code == 403 and "not accessible by personal access token" in detail:
            raise SystemExit(
                "HTTP 403：token 权限不足。请到 https://github.com/settings/tokens 打开该 token，\n"
                "  ① Repository access 里要包含 %s/%s\n"
                "  ② Permissions -> Repository permissions -> Contents 必须是 **Read and write**\n"
                "  （只做①只解决「看得见」，不解决「写得进」）"
                % (DEFAULT_OWNER, DEFAULT_REPO))
        raise SystemExit("HTTP %d  %s %s\n%s" % (e.code, method, path, detail))
    except urllib.error.URLError as e:
        raise SystemExit("网络失败 %s %s：%s\n（api.github.com 应该通；检查代理设置）"
                         % (method, path, e))


def resolve_token(args):
    if args.token:
        return args.token
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        v = os.environ.get(name)
        if v:
            return v.strip()
    path = args.token_file or TOKEN_FILE
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            v = fh.read().strip()
        if v:
            print("token 来源: %s" % path)
            return v
    raise SystemExit(
        "没有找到 token。三种办法任选：\n"
        "  1) 设环境变量：set GH_TOKEN=xxx\n"
        "  2) 建一个文件 %s，里面只放一行 token\n"
        "  3) 命令行：python push_github.py --token xxx\n"
        "生成入口：https://github.com/settings/tokens （细粒度，勾 Contents: Read and write）"
        % TOKEN_FILE)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="把当前版本发布到 GitHub（走 API，等价 git push）")
    ap.add_argument("--owner", default=DEFAULT_OWNER)
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--root", default=DEFAULT_ROOT, help="本地 git 仓库根（默认自动推导为项目根）")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--private", action="store_true", default=True,
                    help="仓库不存在时建成私有（默认）")
    ap.add_argument("--public", dest="private", action="store_false")
    ap.add_argument("--token", default=None)
    ap.add_argument("--token-file", default=None)
    ap.add_argument("--commit", action="store_true", help="推送前先提交工作区改动")
    ap.add_argument("--message", "-m", default=None, help="提交信息（配合 --commit）")
    ap.add_argument("--build", action="store_true", help="推送前先重编模组 jar")
    ap.add_argument("--orphan", action="store_true",
                    help="把远端分支强制指向一个全新的无父提交（重写历史，慎用）")
    ap.add_argument("--dry-run", action="store_true", help="只列清单，不联网")
    args = ap.parse_args()

    args.root = os.path.abspath(args.root)
    if not os.path.isdir(os.path.join(args.root, ".git")):
        raise SystemExit("不是 git 仓库：%s" % args.root)

    # ---- 0. 可选：重编模组 ------------------------------------------------- #
    if args.build:
        print("=== 重编模组（build_mod.py --no-install）===")
        r = subprocess.run([sys.executable, "-u", os.path.join(HERE, "build_mod.py"),
                            "--no-install"], cwd=HERE)
        if r.returncode != 0:
            raise SystemExit("模组编译失败，已中止（没有推送任何东西）。")
        print()

    # ---- 1. 可选：本地提交 ------------------------------------------------- #
    if args.commit:
        print("=== 本地提交 ===")
        ensure_commit(args)
        print()

    files = local_tree(args.root)
    total = sum(len(b) for _, b in files)
    print("本地 HEAD 树：%d 个文件，%.2f MB" % (len(files), total / 1048576.0))
    for rel, blob in files:
        print("  %8d  %s" % (len(blob), rel))
    print("  HEAD = %s" % git("rev-parse", "--short", "HEAD",
                              cwd=args.root).decode().strip())
    if args.dry_run:
        print("\n[dry-run] 未联网。")
        return 0

    token = resolve_token(args)

    # ---- 2. 认证 / 仓库 ---------------------------------------------------- #
    me = api("GET", "/user", token)
    print("\n认证成功：%s (id=%s)" % (me["login"], me["id"]))
    owner = args.owner or me["login"]

    try:
        repo = api("GET", "/repos/%s/%s" % (owner, args.repo), token)
        print("仓库：%s  (visibility=%s, default_branch=%s)"
              % (repo["full_name"], repo.get("visibility"), repo.get("default_branch")))
    except SystemExit as e:
        if "HTTP 404" not in str(e):
            raise
        print("仓库不存在，创建中…")
        try:
            repo = api("POST", "/user/repos", token, {
                "name": args.repo,
                "description": "Minecraft 跟随地图 + 稀有遗迹识别提醒（Fabric 只读模组 + Python 第二屏地图）",
                "private": bool(args.private),
                "has_issues": True,
                "has_wiki": False,
                "auto_init": False,
            })
        except SystemExit as e2:
            if "HTTP 403" in str(e2):
                raise SystemExit(
                    "细粒度 token 没有「创建仓库」的权限（GitHub 的硬限制）。\n"
                    "请到 https://github.com/new 手动建一个**空的**仓库（不要勾 README / .gitignore / license），\n"
                    "名字用 %s，然后重跑本脚本。" % args.repo)
            raise
        print("已创建：%s" % repo["full_name"])

    # ---- 3. 空仓库引导（Git Data API 在零提交仓库上会 409） ----------------- #
    branch_exists = True
    try:
        api("GET", "/repos/%s/%s/git/ref/heads/%s" % (owner, args.repo, args.branch), token)
    except SystemExit as e:
        if "HTTP 404" not in str(e):
            raise
        branch_exists = False
    if not branch_exists:
        print("分支 %s 不存在（空仓库）：先用 Contents API 引导一次提交" % args.branch)
        api("PUT", "/repos/%s/%s/contents/.gitkeep" % (owner, args.repo), token, {
            "message": "chore: bootstrap empty repository",
            "content": base64.b64encode(b"").decode("ascii"),
            "branch": args.branch,
        })
    orphan = bool(args.orphan or not branch_exists)

    # ---- 4. blobs ---------------------------------------------------------- #
    print("\n上传 blob…")
    tree = []
    for i, (rel, blob) in enumerate(files, 1):
        sha = api("POST", "/repos/%s/%s/git/blobs" % (owner, args.repo), token, {
            "content": base64.b64encode(blob).decode("ascii"),
            "encoding": "base64",
        })["sha"]
        tree.append({"path": rel, "mode": "100644", "type": "blob", "sha": sha})
        if i % 20 == 0 or i == len(files):
            print("  %d/%d" % (i, len(files)))

    # ---- 5. tree / commit / ref ------------------------------------------- #
    print("创建 tree…")
    parents = []
    if orphan:
        print("  无父提交（orphan / 首提交）")
    else:
        head = api("GET", "/repos/%s/%s/git/ref/heads/%s" % (owner, args.repo, args.branch), token)
        parents = [head["object"]["sha"]]

    tree_sha = api("POST", "/repos/%s/%s/git/trees" % (owner, args.repo), token,
                   {"tree": tree})["sha"]

    raw_msg = git("log", "-1", "--format=%B", cwd=args.root).decode("utf-8", "replace")
    payload = {"message": args.message if (args.message and args.commit) else raw_msg.rstrip("\n"),
               "tree": tree_sha, "parents": parents}
    payload.update(head_author(args.root))
    commit = api("POST", "/repos/%s/%s/git/commits" % (owner, args.repo), token, payload)
    print("创建 commit：%s" % commit["sha"][:12])

    if branch_exists:
        api("PATCH", "/repos/%s/%s/git/refs/heads/%s" % (owner, args.repo, args.branch), token,
            {"sha": commit["sha"], "force": bool(orphan)})
    else:
        api("POST", "/repos/%s/%s/git/refs" % (owner, args.repo), token,
            {"ref": "refs/heads/" + args.branch, "sha": commit["sha"]})

    print("\n完成：https://github.com/%s/%s" % (owner, args.repo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
