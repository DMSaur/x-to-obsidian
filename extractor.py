"""推文内容提取模块 — 调用 xreach CLI"""

import json
import os
import re
import subprocess
import logging

# xreach 绝对路径（launchd 环境变量不同）
XREACH_PATH = "/Users/dimo/.nvm/versions/node/v24.14.0/bin/xreach"
# Node PATH（xreach 需要）
NODE_PATH = "/Users/dimo/.nvm/versions/node/v24.14.0/bin"

logger = logging.getLogger(__name__)

# 匹配 X/Twitter URL 的正则
X_URL_PATTERN = re.compile(
    r"https?://(?:x\.com|twitter\.com)/\w+/status/(\d+)"
)


def extract_tweet_id(url: str) -> str | None:
    """从 URL 中提取推文 ID"""
    match = X_URL_PATTERN.search(url)
    return match.group(1) if match else None


def is_x_url(text: str) -> str | None:
    """检查文本中是否包含 X/Twitter 链接，返回第一个匹配的完整URL"""
    match = X_URL_PATTERN.search(text)
    return match.group(0) if match else None


def extract_tweet(url: str) -> dict | None:
    """
    调用 xreach CLI 提取推文内容。

    返回:
        {
            "id": "tweet_id",
            "text": "推文原文",
            "author_name": "显示名",
            "author_handle": "@handle",
            "created_at": "ISO时间",
            "like_count": 0,
            "retweet_count": 0,
            "reply_count": 0,
            "url": "原始链接",
            "images": [{"url": "https://...", "alt": "描述"}]
        }
    """
    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        logger.error(f"无法从 URL 提取推文 ID: {url}")
        return None

    try:
        # 使用推文 ID 而非完整 URL（xreach 对某些 URL 格式不兼容）
        # 设置 PATH 确保 node 可被找到
        env = os.environ.copy()
        env["PATH"] = NODE_PATH + ":" + env.get("PATH", "")

        result = subprocess.run(
            [XREACH_PATH, "tweet", tweet_id, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        if result.returncode != 0:
            logger.error(f"xreach 错误: {result.stderr}")
            return None

        data = json.loads(result.stdout)

        # xreach 返回的是列表（单条推文时也是列表）
        tweet = data[0] if isinstance(data, list) else data

        # 提取图片（仅 photo 类型）
        images = []
        for m in tweet.get("media", []):
            if m.get("type") == "photo":
                images.append({
                    "url": m.get("url", ""),
                    "alt": m.get("altText", ""),
                })

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

    except subprocess.TimeoutExpired:
        logger.error("xreach 超时")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"xreach 输出解析失败: {e}")
        return None
    except Exception as e:
        logger.error(f"提取推文失败: {e}")
        return None


if __name__ == "__main__":
    # 测试
    import sys

    if len(sys.argv) > 1:
        tweet = extract_tweet(sys.argv[1])
        if tweet:
            print(json.dumps(tweet, ensure_ascii=False, indent=2))
        else:
            print("提取失败")
    else:
        print("用法: python extractor.py <tweet_url>")
