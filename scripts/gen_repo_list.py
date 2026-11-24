#!/usr/bin/env python3
"""重写组织 profile README 里两个自动区块：公开仓库列表、FDM 版本记录。

区块用 HTML 注释标记包围，脚本只替换标记之间的内容：

    <!-- REPOS:START --> ... <!-- REPOS:END -->
    <!-- FDM:START -->   ... <!-- FDM:END -->

数据源：
    GET /orgs/{org}/repos?type=public   只返回公开仓库，私有仓库天然不会泄露
    GET /repos/{org}/fdm/releases       取最近的正式版，拼版本表

只用标准库。CI 里由 GITHUB_TOKEN 提供认证；本地跑可以用 GH_TOKEN。
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

ORG = os.environ.get("ORG", "AhSir-GBA")
FEATURED = os.environ.get("FEATURED_REPO", "fdm")
README = os.environ.get("README_PATH", os.path.join("profile", "README.md"))
API = "https://api.github.com"
TOKEN = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()

MAX_RELEASES = 4
MARK = "<!-- 本段由 .github/workflows/update-repos.yml 自动生成，手改会在下次运行时被覆盖 -->"


def get_json(url, token=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "org-profile-readme"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp), resp.headers.get("Link", "")
    except urllib.error.HTTPError:
        if token:
            return get_json(url, None)  # 组织级 token 读不到时退回匿名（公开数据 60 次/小时够用）
        raise


def get_all(url):
    items, page = [], 1
    sep = "&" if "?" in url else "?"
    while True:
        batch, link = get_json("%s%sper_page=100&page=%d" % (url, sep, page), TOKEN or None)
        if not isinstance(batch, list) or not batch:
            return items
        items += batch
        if 'rel="next"' not in (link or ""):
            return items
        page += 1


def cell(text, limit=120):
    s = re.sub(r"\s+", " ", (text or "")).strip()
    s = s.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s or "—"


def build_repos():
    repos = [r for r in get_all("%s/orgs/%s/repos?type=public" % (API, ORG)) if not r.get("fork")]
    repos = [r for r in repos if r["name"].lower() != ".github"]
    repos.sort(key=lambda r: r.get("pushed_at") or "", reverse=True)

    lines = [
        "| 仓库 | 说明 | 语言 | Star | 最近更新 |",
        "|---|---|---|---|---|",
    ]
    for r in repos:
        name = r["name"]
        badge = " <sub>已归档</sub>" if r.get("archived") else ""
        lines.append(
            "| **[%s](%s)**%s | %s | %s | %d | %s |"
            % (
                name,
                r["html_url"],
                badge,
                cell(r.get("description")),
                cell(r.get("language"), 20),
                r.get("stargazers_count") or 0,
                (r.get("pushed_at") or "")[:10] or "—",
            )
        )
    if len(lines) == 2:
        lines.append("| _暂无公开仓库_ | | | | |")
    return "\n".join(lines)


def build_releases():
    url = "%s/repos/%s/%s/releases" % (API, ORG, FEATURED)
    data, _ = get_json(url + "?per_page=30", TOKEN or None)
    rels = [r for r in data if not r.get("draft") and not r.get("prerelease")] if isinstance(data, list) else []
    if not rels:
        return "| 版本 | 更新重点 | 安装包 |\n|---|---|---|\n| _暂无发布_ | | |"

    # 按版本号而不是创建时间排序：补历史版本时创建时间会乱序
    def vkey(r):
        nums = re.findall(r"\d+", r["tag_name"])
        return [int(n) for n in nums]

    rels.sort(key=vkey, reverse=True)
    lines = ["| 版本 | 更新重点 | 安装包 |", "|---|---|---|"]
    for i, r in enumerate(rels[:MAX_RELEASES]):
        tag = r["tag_name"]
        title = r.get("name") or tag
        focus = re.sub(r"^FDM\s*%s\s*[—–\-]+\s*" % re.escape(tag), "", title, flags=re.I).strip()
        if not focus or focus.lower() == tag.lower():
            focus = title
        exes = [a for a in r.get("assets", []) if a["name"].lower().endswith(".exe")]
        if exes:
            pkg = "[%s](%s)" % (exes[0]["name"], exes[0]["browser_download_url"])
        else:
            pkg = "[Release 页](%s)" % r["html_url"]
        label = "**%s** · 最新" % tag if i == 0 else tag
        lines.append("| %s | %s | %s |" % (label, cell(focus), pkg))
    return "\n".join(lines)


def replace_block(text, start, end, body):
    if start not in text or end not in text:
        print("跳过：README 缺少 %s / %s 标记" % (start, end), file=sys.stderr)
        return text
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    return "%s%s\n%s\n\n%s\n%s%s" % (head, start, MARK, body, end, tail)


def main():
    try:
        with open(README, encoding="utf-8") as f:
            original = f.read()
    except FileNotFoundError:
        sys.exit("找不到 %s" % README)

    text = replace_block(original, "<!-- REPOS:START -->", "<!-- REPOS:END -->", build_repos())
    text = replace_block(text, "<!-- FDM:START -->", "<!-- FDM:END -->", build_releases())

    if text == original:
        print("两个区块都没有变化，不写文件")
        return
    with open(README, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("已更新 %s" % README)


if __name__ == "__main__":
    main()
