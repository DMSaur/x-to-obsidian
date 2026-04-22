"""推文内容提取模块 — 使用 oEmbed API + xreach CLI"""

import logging
import os
import re
import json
import subprocess

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# 匹配 X/Twitter URL 的正则
X_URL_PATTERN = re.compile(
    r"https?://(?:x\.com|twitter\.com)/\w+/status/(\d+)"
)

# xreach 路径配置
LOCAL_XREACH_PATH = "/Users/dimo/.nvm/versions/node/v24.14.0/bin/xreach"
LOCAL_NODE_PATH = "/Users/dimo/.nvm/versions/node/v24.14.0/bin"


def get_xreach_config():
    """获取 xreach 执行配置"""
    # 检测云端环境
    if os.environ.get("PORT") == "8080" or not os.path.exists(LOCAL_XREACH_PATH):
        return "xreach", {}  # 云端全局安装
    else:
        env = os.environ.copy()
        env["PATH"] = LOCAL_NODE_PATH + ":" + env.get("PATH", "")
        return LOCAL_XREACH_PATH, env


def extract_tweet_id(url: str) -> str | None:
    """从 URL 中提取推文 ID"""
    match = X_URL_PATTERN.search(url)
    return match.group(1) if match else None


def is_x_url(text: str) -> str | None:
    """检查文本中是否包含 X/Twitter 链接"""
    match = X_URL_PATTERN.search(text)
    return match.group(0) if match else None


def extract_tweet_oembed(url: str) -> dict | None:
    """使用 oEmbed API 提取推文（快速，但不包含评论）"""
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
        logger.error(f"oEmbed 提取失败: {e}")
        return None


def extract_tweet_xreach(url: str) -> dict | None:
    """使用 xreach CLI 提取推文（完整数据，包含图片）"""
    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return None

    xreach_path, env = get_xreach_config()

    try:
        result = subprocess.run(
            [xreach_path, "tweet", tweet_id, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env if env else None,
        )

        if result.returncode != 0:
            logger.error(f"xreach 错误: {result.stderr}")
            return None

        data = json.loads(result.stdout)
        tweet = data[0] if isinstance(data, list) else data

        images = []
        for m in tweet.get("media", []):
            if m.get("type") == "photo":
                images.append({"url": m.get("url", ""), "alt": m.get("altText", "")})

        return {
            "id": tweet.get("id", tweet_id),
            "text": tweet.get("text", ""),
            "author_name": tweet.get("user", {}).get("name", ""),
            "author_handle": "@" + tweet.get("user", {}).get("screenName", ""),
            "created_at": tweet.get("createdAt", ""),
            "like_count": tweet.get("likeCount", 0),
            "retweet_count": tweet.get("retweetCount", 0),
            "reply_count": tweet.get("replyCount", 0),
            "url": url,
            "images": images,
        }
    except Exception as e:
        logger.error(f"xreach 提取失败: {e}")
        return None


def extract_tweet(url: str) -> dict | None:
    """提取推文内容（优先 xreach，失败时用 oEmbed）"""
    result = extract_tweet_xreach(url)
    if result:
        logger.info("xreach 成功提取推文")
        return result

    logger.info("xreach 失败，使用 oEmbed")
    return extract_tweet_oembed(url)


def extract_replies(url: str, max_replies: int = 20) -> list[dict]:
    """使用 xreach CLI 提取评论"""
    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return []

    xreach_path, env = get_xreach_config()

    try:
        result = subprocess.run(
            [xreach_path, "thread", tweet_id, "--json"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env if env else None,
        )

        if result.returncode != 0:
            logger.warning(f"xreach thread 错误: {result.stderr}")
            return []

        data = json.loads(result.stdout)
        replies = []

        for item in data:
            if item.get("id") == tweet_id or item.get("isRetweet"):
                continue

            images = []
            for m in item.get("media", []):
                if m.get("type") == "photo":
                    images.append({"url": m.get("url", ""), "alt": m.get("altText", "")})

            replies.append({
                "text": item.get("text", ""),
                "author": "@" + item.get("user", {}).get("screenName", ""),
                "images": images,
            })

            if len(replies) >= max_replies:
                break

        logger.info(f"提取到 {len(replies)} 条评论")
        return replies

    except Exception as e:
        logger.error(f"提取评论失败: {e}")
        return []


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        tweet = extract_tweet(sys.argv[1])
        if tweet:
            print(json.dumps(tweet, ensure_ascii=False, indent=2))
        else:
            print("提取失败")
    else:
        print("用法: python extractor.py <tweet_url>")