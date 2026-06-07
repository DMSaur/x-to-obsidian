"""GitHub 同步状态查询 — 查询 GitHub 仓库的最新提交和笔记统计"""

import logging
import os
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

from github_writer import (
    GITHUB_API,
    GITHUB_BRANCH,
    GITHUB_REPO,
    GITHUB_TOKEN,
    _headers,
)


def get_sync_status() -> dict:
    """
    查询 GitHub 仓库同步状态。

    返回: {
        total_notes: int,
        total_attachments: int,
        latest_commit_date: str,
        latest_commit_msg: str,
        recent_notes: [str],  # 最近5篇笔记标题
        repo_url: str,
    }
    """
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return {"error": "GITHUB_TOKEN 或 GITHUB_REPO 未设置"}

    # 1. 获取文件树（统计笔记和附件数量）
    tree_url = f"{GITHUB_API}/repos/{GITHUB_REPO}/git/trees/{GITHUB_BRANCH}"
    params = {"recursive": "1"}
    try:
        resp = httpx.get(tree_url, headers=_headers(), params=params, timeout=30)
        if resp.status_code != 200:
            return {"error": f"获取文件树失败: {resp.status_code}"}
        tree = resp.json().get("tree", [])
    except Exception as e:
        return {"error": f"连接 GitHub 失败: {e}"}

    notes = [
        item for item in tree
        if item.get("type") == "blob"
        and item.get("path", "").startswith("X-Clippings/")
        and item.get("path", "").endswith(".md")
    ]
    attachments = [
        item for item in tree
        if item.get("type") == "blob"
        and item.get("path", "").startswith("attachments/")
    ]

    # 2. 获取最近提交
    commits_url = f"{GITHUB_API}/repos/{GITHUB_REPO}/commits"
    commits_params = {"per_page": 6, "sha": GITHUB_BRANCH}
    try:
        resp = httpx.get(commits_url, headers=_headers(), params=commits_params, timeout=15)
        commits = resp.json() if resp.status_code == 200 else []
    except Exception:
        commits = []

    # 最新提交信息
    latest = commits[0] if commits else {}
    latest_date = ""
    latest_msg = ""
    if latest:
        date_str = latest.get("commit", {}).get("author", {}).get("date", "")
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                delta = now - dt
                if delta.days == 0:
                    hours = delta.seconds // 3600
                    latest_date = f"{hours} 小时前" if hours > 0 else "刚刚"
                elif delta.days == 1:
                    latest_date = "1 天前"
                else:
                    latest_date = f"{delta.days} 天前"
            except Exception:
                latest_date = date_str
        latest_msg = latest.get("commit", {}).get("message", "").split("\n")[0]

    # 最近笔记标题（从提交消息提取，取最近5条 clip 类型的）
    recent_notes = []
    for c in commits:
        msg = c.get("commit", {}).get("message", "").split("\n")[0]
        if msg.startswith("clip:"):
            title = msg.replace("clip:", "").strip()
            recent_notes.append(title)
        if len(recent_notes) >= 5:
            break

    return {
        "total_notes": len(notes),
        "total_attachments": len(attachments),
        "latest_date": latest_date,
        "latest_msg": latest_msg,
        "recent_notes": recent_notes,
        "repo_url": f"https://github.com/{GITHUB_REPO}",
    }
