"""推文内容提取模块 — 使用 oEmbed API（公开，无需认证）"""

import logging
import re

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

X_URL_PATTERN = re.compile(
    r"https?://(?:x\.com|twitter\.com)/\w+/status/(\d+)"
)


def extract_tweet_id(url: str) -> str | None:
    match = X_URL_PATTERN.search(url)
    return match.group(1) if match else None


def is_x_url(text: str) -> str | None:
    match = X_URL_PATTERN.search(text)
    return match.group(0) if match else None


def extract_tweet(url: str) -> dict | None:
    """使用 oEmbed API 提取推文（公开 API，无需认证）"""
    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return None

    try:
        oembed_url = f"https://publish.twitter.com/oembed?url={url}"
        with httpx.Client(timeout=30) as client:
            resp = client.get(oembed_url)
            resp.raise_for_status()

        data = resp.json()
        html = data.get("html", "")
        soup = BeautifulSoup(html, "html.parser")

        p_tag = soup.find("p")
        text = p_tag.get_text() if p_tag else ""
        text = text.replace("&#39;", "'").replace("&amp;", "&").replace("&mdash;", "—")

        author_name = data.get("author_name", "")
        author_url = data.get("author_url", "")
        author_handle = "@" + author_url.split("/")[-1] if author_url else ""

        return {
            "id": tweet_id,
            "text": text,
            "author_name": author_name,
            "author_handle": author_handle,
            "created_at": "",
            "like_count": 0,
            "retweet_count": 0,
            "reply_count": 0,
            "url": url,
            "images": [],
        }
    except Exception as e:
        logger.error(f"提取推文失败: {e}")
        return None


def extract_replies(url: str, max_replies: int = 20) -> list[dict]:
    """评论提取需要 X 认证，云端无法实现，返回空列表"""
    logger.info("评论功能需要认证，已禁用")
    return []


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) > 1:
        tweet = extract_tweet(sys.argv[1])
        if tweet:
            print(json.dumps(tweet, ensure_ascii=False, indent=2))
        else:
            print("提取失败")