"""Obsidian 笔记写入模块"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """清理文件名中的特殊字符"""
    return re.sub(r'[<>:"/\\|?*]', "", name).strip()


def download_images(
    images: list[dict],
    tweet_id: str,
    vault_path: str,
    attachments_folder: str = "attachments",
) -> list[str]:
    """
    下载推文图片到 Obsidian vault 附件目录。

    返回: Obsidian 内部引用路径列表（相对 vault 根目录）
    """
    if not images:
        return []

    vault = Path(vault_path)
    img_dir = vault / attachments_folder / f"x-{tweet_id}"
    img_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for i, img in enumerate(images):
            url = img.get("url", "")
            if not url:
                continue

            # 从 URL 推断文件扩展名
            ext = Path(urlparse(url).path).suffix or ".jpg"
            local_name = f"img{i+1}{ext}"
            local_path = img_dir / local_name

            try:
                resp = client.get(url)
                resp.raise_for_status()
                local_path.write_bytes(resp.content)
                # Obsidian 内部引用路径
                obsidian_ref = f"{attachments_folder}/x-{tweet_id}/{local_name}"
                saved.append(obsidian_ref)
                logger.info(f"图片已下载: {local_path}")
            except Exception as e:
                logger.error(f"图片下载失败 {url}: {e}")

    return saved


def write_note(
    tweet_data: dict,
    summary_data: dict,
    vault_path: str,
    clippings_folder: str = "X-Clippings",
    attachments_folder: str = "attachments",
) -> str | None:
    """
    将推文写入 Obsidian vault。

    参数:
        tweet_data: extractor.extract_tweet() 返回的字典
        summary_data: summarizer.summarize_tweet() 返回的字典
        vault_path: Obsidian vault 根路径
        clippings_folder: 笔记存放子目录名
        attachments_folder: 图片附件存放目录名

    返回:
        成功时返回文件路径，失败返回 None
    """
    vault = Path(vault_path)
    output_dir = vault / clippings_folder
    output_dir.mkdir(parents=True, exist_ok=True)

    tweet_id = tweet_data.get("id", "unknown")
    author = tweet_data.get("author_handle", "unknown").lstrip("@")
    date_prefix = datetime.now().strftime("%Y-%m-%d")

    filename = sanitize_filename(f"{date_prefix}-{author}-{tweet_id}") + ".md"
    filepath = output_dir / filename

    # 下载图片
    image_refs = download_images(
        tweet_data.get("images", []),
        tweet_id,
        vault_path,
        attachments_folder,
    )

    # 构建 frontmatter
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

    # 构建笔记内容
    parts = []
    parts.append("---")
    parts.append(yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False).strip())
    parts.append("---")
    parts.append("")
    parts.append(f"## 摘要\n{summary_data.get('summary_zh', '')}")
    parts.append("")
    parts.append(f"## 原文\n{tweet_data.get('text', '')}")
    parts.append("")

    # 图片引用（Obsidian wikilink 格式）
    if image_refs:
        parts.append("## 媒体")
        for ref in image_refs:
            parts.append(f"![[{ref}]]")
        parts.append("")

    # 互动数据
    parts.append("## 数据")
    parts.append(
        f"赞 {tweet_data.get('like_count', 0)} | "
        f"转发 {tweet_data.get('retweet_count', 0)} | "
        f"回复 {tweet_data.get('reply_count', 0)}"
    )

    content = "\n".join(parts)

    try:
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"笔记已写入: {filepath}")
        return str(filepath)
    except Exception as e:
        logger.error(f"写入笔记失败: {e}")
        return None


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        vault = sys.argv[1]
    else:
        vault = "/Users/dimo/Documents/Obsidian Vault"

    # 测试写入
    test_tweet = {
        "id": "191234567890",
        "text": "USTR announces new tariff review results for Section 301",
        "author_handle": "@TradeWatcher",
        "url": "https://x.com/TradeWatcher/status/191234567890",
        "like_count": 42,
        "retweet_count": 12,
        "reply_count": 5,
    }
    test_summary = {
        "title": "301关税复审",
        "summary_zh": "美国贸易代表办公室宣布了对华301关税的最新复审结果。",
        "tags": ["trade-policy", "tariffs"],
    }
    path = write_note(test_tweet, test_summary, vault)
    if path:
        print(f"测试成功: {path}")
    else:
        print("写入失败")
