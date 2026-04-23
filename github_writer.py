"""GitHub 同步模块 — 将 Obsidian 笔记推送到 GitHub 私有仓库"""

import base64
import logging
import os
from datetime import datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")  # e.g. "username/x-clippings"
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
GITHUB_API = "https://api.github.com"


def _headers() -> dict:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def _check_rate_limit() -> None:
    """检查 GitHub API rate limit"""
    try:
        resp = httpx.get(f"{GITHUB_API}/rate_limit", headers=_headers(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            remaining = data["resources"]["core"]["remaining"]
            if remaining < 10:
                logger.warning(f"GitHub API rate limit low: {remaining} remaining")
    except Exception:
        pass


def file_exists(path: str) -> str | None:
    """检查文件是否已存在，返回 SHA（用于更新）或 None"""
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}"
    params = {"ref": GITHUB_BRANCH}
    try:
        resp = httpx.get(url, headers=_headers(), params=params, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("sha")
    except Exception:
        pass
    return None


def push_file(path: str, content: bytes, message: str) -> str | None:
    """
    推送文件到 GitHub repo。

    参数:
        path: 仓库内的文件路径 (e.g. "X-Clippings/2024-01-01-author-123.md")
        content: 文件内容 bytes
        message: commit message

    返回:
        成功返回文件 URL，失败返回 None
    """
    if not GITHUB_TOKEN or not GITHUB_REPO:
        logger.error("GITHUB_TOKEN 或 GITHUB_REPO 未设置")
        return None

    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{path}"
    encoded = base64.b64encode(content).decode("utf-8")

    body = {
        "message": message,
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }

    # 如果文件已存在，需要带上 SHA 才能更新
    existing_sha = file_exists(path)
    if existing_sha:
        body["sha"] = existing_sha

    try:
        resp = httpx.put(url, headers=_headers(), json=body, timeout=30)

        if resp.status_code in (200, 201):
            result = resp.json()
            html_url = result.get("content", {}).get("html_url", "")
            logger.info(f"文件推送成功: {path}")
            return html_url
        else:
            logger.error(f"推送失败 {path}: {resp.status_code} {resp.text[:200]}")
            return None

    except Exception as e:
        logger.error(f"推送异常 {path}: {e}")
        return None


def push_note(
    tweet_data: dict,
    summary_data: dict,
    replies: list[dict] | None = None,
    clippings_folder: str = "X-Clippings",
    attachments_folder: str = "attachments",
) -> str | None:
    """
    将推文笔记写入 GitHub（Obsidian 格式）。

    返回: GitHub 文件 URL 或 None
    """
    from writer import sanitize_filename

    tweet_id = tweet_data.get("id", "unknown")
    author = tweet_data.get("author_handle", "unknown").lstrip("@")
    date_prefix = datetime.now().strftime("%Y-%m-%d")

    filename = sanitize_filename(f"{date_prefix}-{author}-{tweet_id}") + ".md"
    note_path = f"{clippings_folder}/{filename}"

    # 下载并上传图片
    image_refs = _download_and_push_images(
        tweet_data.get("images", []),
        tweet_id,
        attachments_folder,
    )

    # 构建 frontmatter
    import yaml

    tags = summary_data.get("tags", [])
    tags.append("x-post")

    frontmatter = {
        "title": summary_data.get("title", "推文摘要"),
        "source": tweet_data.get("url", ""),
        "author": tweet_data.get("author_handle", ""),
        "date": date_prefix,
        "tags": sorted(set(tags)),
        "type": "x-post",
    }

    # 构建笔记
    parts = []
    parts.append("---")
    parts.append(yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).strip())
    parts.append("---")
    parts.append("")
    parts.append(f"## 摘要\n{summary_data.get('summary_zh', '')}")
    parts.append("")
    parts.append(f"## 原文\n{tweet_data.get('text', '')}")
    parts.append("")

    if image_refs:
        parts.append("## 媒体")
        for ref in image_refs:
            parts.append(f"![[{ref}]]")
        parts.append("")

    parts.append("## 数据")
    parts.append(
        f"赞 {tweet_data.get('like_count', 0)} | "
        f"转发 {tweet_data.get('retweet_count', 0)} | "
        f"回复 {tweet_data.get('reply_count', 0)}"
    )

    if replies and len(replies) > 0:
        parts.append("")
        parts.append(f"## 评论（{len(replies)}条）")
        for i, reply in enumerate(replies[:10]):
            r_author = reply.get("author", "未知")
            text = reply.get("text", "")
            parts.append(f"{r_author}: {text}")

            reply_images = reply.get("images", [])
            if reply_images:
                for j, img in enumerate(reply_images):
                    img_url = img.get("url", "")
                    if img_url:
                        ext = Path(img_url.split("?")[0]).suffix or ".jpg"
                        img_remote = f"{attachments_folder}/x-{tweet_id}/reply{i+1}-img{j+1}{ext}"
                        _download_and_push_single_image(img_url, img_remote)
                        parts.append(f"![[{img_remote}]]")
        parts.append("")

    content = "\n".join(parts)

    commit_msg = f"clip: @{author} - {summary_data.get('title', tweet_id)[:50]}"
    url = push_file(note_path, content.encode("utf-8"), commit_msg)

    if url:
        logger.info(f"GitHub 笔记已保存: {note_path}")
    return url


def _download_and_push_images(
    images: list[dict],
    tweet_id: str,
    attachments_folder: str = "attachments",
) -> list[str]:
    """下载图片并推送到 GitHub，返回 Obsidian 引用路径"""
    if not images:
        return []

    saved = []
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for i, img in enumerate(images):
            url = img.get("url", "")
            if not url:
                continue

            ext = Path(url.split("?")[0]).suffix or ".jpg"
            remote_name = f"img{i+1}{ext}"
            remote_path = f"{attachments_folder}/x-{tweet_id}/{remote_name}"

            try:
                resp = client.get(url)
                resp.raise_for_status()

                result = push_file(remote_path, resp.content, f"img: {tweet_id}/{remote_name}")
                if result:
                    obsidian_ref = f"{attachments_folder}/x-{tweet_id}/{remote_name}"
                    saved.append(obsidian_ref)
                    logger.info(f"图片已推送到 GitHub: {remote_path}")
            except Exception as e:
                logger.error(f"图片推送失败 {url}: {e}")

    return saved


def _download_and_push_single_image(img_url: str, remote_path: str) -> str | None:
    """下载单张图片并推送到 GitHub"""
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(img_url)
            resp.raise_for_status()
            return push_file(remote_path, resp.content, f"img: {remote_path}")
    except Exception as e:
        logger.error(f"图片推送失败 {img_url}: {e}")
        return None
