"""推文内容提取模块 — 使用 oEmbed API（公开，无需认证）"""

import logging
import os
import re
import json

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# 匹配 X/Twitter URL 的正则
X_URL_PATTERN = re.compile(
    r"https?://(?:x\.com|twitter\.com)/\w+/status/(\d+)"
)

# Playwright 导入（备用方案）
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


def extract_tweet_id(url: str) -> str | None:
    """从 URL 中提取推文 ID"""
    match = X_URL_PATTERN.search(url)
    return match.group(1) if match else None


def is_x_url(text: str) -> str | None:
    """检查文本中是否包含 X/Twitter 链接，返回第一个匹配的完整URL"""
    match = X_URL_PATTERN.search(text)
    return match.group(0) if match else None


def extract_tweet_oembed(url: str) -> dict | None:
    """
    使用 oEmbed API 提取推文（公开 API，无需认证）。

    这是首选方法，最简单最可靠。
    """
    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return None

    try:
        # oEmbed API
        oembed_url = f"https://publish.twitter.com/oembed?url={url}"

        with httpx.Client(timeout=30) as client:
            resp = client.get(oembed_url)
            resp.raise_for_status()

        data = resp.json()

        # 从 HTML 中解析推文内容
        html = data.get("html", "")
        soup = BeautifulSoup(html, "html.parser")

        # 提取文本
        p_tag = soup.find("p")
        text = p_tag.get_text() if p_tag else ""

        # 清理 HTML 实体
        text = text.replace("&#39;", "'").replace("&amp;", "&").replace("&mdash;", "—")

        # 提取作者
        author_name = data.get("author_name", "")
        author_handle = ""
        author_url = data.get("author_url", "")
        if author_url:
            # 从 URL 提取 handle: https://twitter.com/LinQingV
            author_handle = "@" + author_url.split("/")[-1]

        # oEmbed 不提供统计数据和图片，需要额外获取
        # 但对于基本功能已经足够

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


def extract_tweet_playwright(url: str) -> dict | None:
    """使用 Playwright 提取推文（备用方案，获取更多信息）"""
    if not HAS_PLAYWRIGHT:
        logger.warning("Playwright 未安装")
        return None

    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )
            page = context.new_page()
            page.set_default_timeout(60000)

            logger.info(f"Playwright 正在访问: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            try:
                page.wait_for_selector('[data-testid="tweet"]', timeout=30000)
            except:
                page.wait_for_selector('article', timeout=15000)

            tweet_text = ""
            for selector in ['[data-testid="tweetText"]', 'article div[dir="auto"]']:
                try:
                    el = page.locator(selector).first
                    if el.count() > 0:
                        tweet_text = el.inner_text(timeout=5000)
                        if tweet_text:
                            break
                except:
                    continue

            author_name = ""
            author_handle = ""
            try:
                spans = page.locator('[data-testid="User-Name"] span').all()
                if spans:
                    author_name = spans[0].inner_text() if len(spans) > 0 else ""
                # 从 URL 提取 handle
                username = url.split("/")[3]
                author_handle = "@" + username
            except:
                pass

            images = []
            try:
                img_elements = page.locator('[data-testid="tweetPhoto"] img')
                for i in range(img_elements.count()):
                    img_url = img_elements.nth(i).get_attribute("src")
                    if img_url:
                        img_url = img_url.split("?")[0] + "?format=orig"
                        images.append({"url": img_url, "alt": ""})
            except:
                pass

            browser.close()

            return {
                "id": tweet_id,
                "text": tweet_text,
                "author_name": author_name,
                "author_handle": author_handle,
                "created_at": "",
                "like_count": 0,
                "retweet_count": 0,
                "reply_count": 0,
                "url": url,
                "images": images,
            }

    except Exception as e:
        logger.error(f"Playwright 提取失败: {e}")
        return None


def extract_tweet(url: str) -> dict | None:
    """
    提取推文内容。

    优先使用 oEmbed（最简单可靠），失败时尝试 Playwright。
    """
    # 优先使用 oEmbed
    result = extract_tweet_oembed(url)
    if result:
        logger.info("使用 oEmbed API 成功提取推文")
        return result

    # 备用：Playwright（获取更多信息如图片）
    logger.info("oEmbed 失败，尝试 Playwright...")
    return extract_tweet_playwright(url)


def extract_replies(url: str, max_replies: int = 20) -> list[dict]:
    """
    提取推文的评论/回复。

    oEmbed 不提供评论，需要使用 Playwright。
    """
    if not HAS_PLAYWRIGHT:
        logger.warning("Playwright 未安装，无法提取评论")
        return []

    return extract_replies_playwright(url, max_replies)


def extract_replies_playwright(url: str, max_replies: int = 20) -> list[dict]:
    """使用 Playwright 提取评论"""
    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            page = browser.new_page()
            page.set_default_timeout(60000)

            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector('[data-testid="tweet"]', timeout=30000)

            replies = []
            for _ in range(2):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

                reply_elements = page.locator('[data-testid="tweet"]').all()
                for reply in reply_elements[1:]:
                    try:
                        text = reply.locator('[data-testid="tweetText"]').inner_text()
                        author = reply.locator('[data-testid="User-Name"] a').first.inner_text()

                        images = []
                        imgs = reply.locator('[data-testid="tweetPhoto"] img')
                        for i in range(imgs.count()):
                            img_url = imgs.nth(i).get_attribute("src")
                            if img_url:
                                images.append({"url": img_url.split("?")[0] + "?format=orig", "alt": ""})

                        replies.append({"text": text, "author": author, "images": images})
                        if len(replies) >= max_replies:
                            break
                    except:
                        continue

                if len(replies) >= max_replies:
                    break

            browser.close()
            logger.info(f"提取到 {len(replies)} 条评论")
            return replies

    except Exception as e:
        logger.error(f"提取评论失败: {e}")
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
    else:
        print("用法: python extractor.py <tweet_url>")
