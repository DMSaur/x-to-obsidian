"""推文内容提取模块 — 使用 Playwright (自带 Chromium，适合云端部署)"""

import logging
import os
import re

logger = logging.getLogger(__name__)

# 匹配 X/Twitter URL 的正则
X_URL_PATTERN = re.compile(
    r"https?://(?:x\.com|twitter\.com)/\w+/status/(\d+)"
)

# 检测运行环境
USE_PLAYWRIGHT = os.environ.get("USE_PLAYWRIGHT", "false").lower() == "true"

# Playwright 导入（可选，云端部署时安装）
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

# xreach 导入（本地使用）
XREACH_PATH = "/Users/dimo/.nvm/versions/node/v24.14.0/bin/xreach"
NODE_PATH = "/Users/dimo/.nvm/versions/node/v24.14.0/bin"


def extract_tweet_id(url: str) -> str | None:
    """从 URL 中提取推文 ID"""
    match = X_URL_PATTERN.search(url)
    return match.group(1) if match else None


def is_x_url(text: str) -> str | None:
    """检查文本中是否包含 X/Twitter 链接，返回第一个匹配的完整URL"""
    match = X_URL_PATTERN.search(text)
    return match.group(0) if match else None


def extract_tweet_playwright(url: str) -> dict | None:
    """使用 Playwright 提取推文（云端部署）"""
    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return None

    try:
        with sync_playwright() as p:
            # 启动 Chromium（添加反检测参数）
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            # 增加超时到 60 秒
            page.set_default_timeout(60000)

            # 访问推文页面（使用 domcontentloaded 而非 networkidle）
            logger.info(f"Playwright 正在访问: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # 等待推文内容加载（增加超时）
            logger.info("等待推文内容...")
            try:
                page.wait_for_selector('[data-testid="tweet"]', timeout=30000)
            except PlaywrightTimeout:
                # 尝试备用选择器
                page.wait_for_selector('article', timeout=15000)

            # 提取推文文本
            tweet_text = ""
            try:
                # 尝试多个选择器
                for selector in ['[data-testid="tweetText"]', 'div[data-testid="tweet"] div[dir="auto"]', 'article div[dir="auto"]']:
                    try:
                        text_element = page.locator(selector).first
                        if text_element.count() > 0:
                            tweet_text = text_element.inner_text(timeout=5000)
                            if tweet_text:
                                break
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"提取文本失败: {e}")

            # 提取作者信息
            author_name = ""
            author_handle = ""
            try:
                # 尝试多种方式获取作者
                user_link = page.locator('a[href*="/LinQingV"]').first
                if user_link.count() > 0:
                    author_handle = "@LinQingV"
                spans = page.locator('[data-testid="User-Name"] span').all()
                if spans:
                    author_name = spans[0].inner_text() if len(spans) > 0 else ""
            except Exception as e:
                logger.warning(f"提取作者失败: {e}")

            # 提取图片
            images = []
            try:
                img_elements = page.locator('[data-testid="tweetPhoto"] img')
                for i in range(img_elements.count()):
                    img_url = img_elements.nth(i).get_attribute("src")
                    if img_url:
                        # 获取原图 URL（替换参数）
                        img_url = img_url.split("?")[0] + "?format=orig"
                        images.append({"url": img_url, "alt": ""})
            except Exception:
                pass

            # 提取统计数据
            like_count = 0
            retweet_count = 0
            reply_count = 0
            try:
                # 查找 likes 按钮的数据
                likes_group = page.locator('[data-testid="like"]').first
                likes_text = likes_group.inner_text()
                if likes_text:
                    like_count = int(likes_text) if likes_text.isdigit() else 0
            except Exception:
                pass

            browser.close()

            return {
                "id": tweet_id,
                "text": tweet_text,
                "author_name": author_name,
                "author_handle": author_handle,
                "created_at": "",
                "like_count": like_count,
                "retweet_count": retweet_count,
                "reply_count": reply_count,
                "url": url,
                "images": images,
            }

    except Exception as e:
        logger.error(f"Playwright 提取失败: {e}")
        return None


def extract_tweet_xreach(url: str) -> dict | None:
    """使用 xreach CLI 提取推文（本地运行）"""
    import json
    import subprocess

    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return None

    try:
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
        tweet = data[0] if isinstance(data, list) else data

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

    except Exception as e:
        logger.error(f"xreach 提取失败: {e}")
        return None


def extract_tweet(url: str) -> dict | None:
    """
    提取推文内容。

    自动选择方法：
    - 云端（USE_PLAYWRIGHT=true）: 使用 Playwright
    - 本地: 使用 xreach CLI
    """
    if USE_PLAYWRIGHT and HAS_PLAYWRIGHT:
        logger.info("使用 Playwright 提取推文")
        return extract_tweet_playwright(url)
    else:
        logger.info("使用 xreach 提取推文")
        return extract_tweet_xreach(url)


def extract_replies_playwright(url: str, max_replies: int = 20) -> list[dict]:
    """使用 Playwright 提取评论（云端部署）"""
    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(30000)

            page.goto(url, wait_until="networkidle")

            # 等待回复加载
            page.wait_for_selector('[data-testid="tweet"]', timeout=15000)

            # 滚动加载更多回复
            replies = []
            for _ in range(3):  # 滚动3次
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

                reply_elements = page.locator('[data-testid="tweet"]').all()
                for reply in reply_elements[1:]:  # 跳过第一条（原推文）
                    try:
                        text = reply.locator('[data-testid="tweetText"]').inner_text()
                        author = reply.locator('[data-testid="User-Name"] a').first.inner_text()

                        images = []
                        img_elements = reply.locator('[data-testid="tweetPhoto"] img')
                        for i in range(img_elements.count()):
                            img_url = img_elements.nth(i).get_attribute("src")
                            if img_url:
                                images.append({"url": img_url.split("?")[0] + "?format=orig", "alt": ""})

                        replies.append({
                            "text": text,
                            "author": author,
                            "images": images,
                        })

                        if len(replies) >= max_replies:
                            break
                    except Exception:
                        continue

                if len(replies) >= max_replies:
                    break

            browser.close()
            logger.info(f"Playwright 提取到 {len(replies)} 条评论")
            return replies

    except Exception as e:
        logger.error(f"Playwright 提取评论失败: {e}")
        return []


def extract_replies_xreach(url: str, max_replies: int = 20) -> list[dict]:
    """使用 xreach CLI 提取评论（本地运行）"""
    import json
    import subprocess

    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return []

    try:
        env = os.environ.copy()
        env["PATH"] = NODE_PATH + ":" + env.get("PATH", "")

        result = subprocess.run(
            [XREACH_PATH, "thread", tweet_id, "--json"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )

        if result.returncode != 0:
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

        logger.info(f"xreach 提取到 {len(replies)} 条评论")
        return replies

    except Exception as e:
        logger.error(f"xreach 提取评论失败: {e}")
        return []


def extract_replies(url: str, max_replies: int = 20) -> list[dict]:
    """提取推文的评论/回复。"""
    if USE_PLAYWRIGHT and HAS_PLAYWRIGHT:
        return extract_replies_playwright(url, max_replies)
    else:
        return extract_replies_xreach(url, max_replies)


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        tweet = extract_tweet(sys.argv[1])
        if tweet:
            print(json.dumps(tweet, ensure_ascii=False, indent=2))
        else:
            print("提取失败")
    else:
        print("用法: python extractor.py <tweet_url>")
