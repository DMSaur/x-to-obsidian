"""推文内容提取模块 — 使用 fxtwitter API（公开，无需认证，含图片）"""

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


def _extract_via_fxtwitter(url: str, tweet_id: str) -> dict | None:
    """使用 fxtwitter API 提取推文（含图片、互动数据）"""
    # 从 URL 中提取 screen_name
    match = re.match(r"https?://(?:x\.com|twitter\.com)/(\w+)/status/\d+", url)
    screen_name = match.group(1) if match else "i"

    api_url = f"https://api.fxtwitter.com/{screen_name}/status/{tweet_id}"
    headers = {"User-Agent": "X-To-Obsidian/1.0 (https://github.com/dimo/x-to-obsidian)"}
    with httpx.Client(timeout=30) as client:
        resp = client.get(api_url, headers=headers)
        resp.raise_for_status()

    data = resp.json()
    tweet = data.get("tweet")
    if not tweet:
        return None

    # 提取图片
    images = []
    media = tweet.get("media", {})
    for item in media.get("all", []):
        if item.get("type") == "photo":
            img_url = item.get("url", "")
            if img_url:
                images.append({"url": img_url})

    author = tweet.get("author", {})
    created_at = tweet.get("created_at", "")
    # fxtwitter 返回的是时间戳字符串，转为日期格式
    if created_at and len(created_at) > 10:
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            created_at = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

    return {
        "id": tweet_id,
        "text": tweet.get("text", ""),
        "author_name": author.get("name", ""),
        "author_handle": "@" + author.get("screen_name", "") if author.get("screen_name") else "",
        "created_at": created_at,
        "like_count": tweet.get("likes", 0),
        "retweet_count": tweet.get("retweets", 0),
        "reply_count": tweet.get("replies", 0),
        "url": url,
        "images": images,
    }


def _extract_via_oembed(url: str, tweet_id: str) -> dict | None:
    """使用 oEmbed API 提取推文（降级方案）"""
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


def extract_tweet(url: str) -> dict | None:
    """提取推文内容（优先 fxtwitter，降级 oEmbed）"""
    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return None

    # 优先使用 fxtwitter（含图片 + 互动数据）
    try:
        result = _extract_via_fxtwitter(url, tweet_id)
        if result:
            logger.info(f"fxtwitter 提取成功，{len(result['images'])} 张图片")
            return result
    except Exception as e:
        logger.warning(f"fxtwitter 提取失败，降级到 oEmbed: {e}")

    # 降级到 oEmbed（无图片）
    try:
        result = _extract_via_oembed(url, tweet_id)
        if result:
            logger.info("oEmbed 提取成功（无图片）")
            return result
    except Exception as e:
        logger.error(f"oEmbed 也失败: {e}")

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