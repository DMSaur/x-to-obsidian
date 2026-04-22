"""飞书 Bot 主服务 — 接收消息、处理 X 链接、存入 Obsidian"""

import logging
import os
from collections import deque
from datetime import datetime, timedelta

import yaml
from fastapi import FastAPI, Request, Response
from lark_oapi.api.im.v1 import *

from extractor import extract_tweet, extract_replies, is_x_url
from summarizer import summarize_tweet
from writer import write_note
from feishu_writer import save_to_feishu_wiki

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 加载配置
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")
with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

FEISHU = config["feishu"]
OBSIDIAN = config["obsidian"]
CLAUDE = config["claude"]

app = FastAPI(title="X to Obsidian Bot")

# 飞书客户端
import lark_oapi as lark

client = lark.Client.builder() \
    .app_id(FEISHU["app_id"]) \
    .app_secret(FEISHU["app_secret"]) \
    .build()

# 已处理消息缓存（去重，最多保留100条，1小时过期）
processed_messages = deque(maxlen=100)


def is_message_processed(message_id: str) -> bool:
    """检查消息是否已处理（去重）"""
    for msg_id, timestamp in processed_messages:
        if msg_id == message_id:
            # 1小时内已处理过
            if datetime.now() - timestamp < timedelta(hours=1):
                return True
    return False


def mark_message_processed(message_id: str):
    """标记消息已处理"""
    processed_messages.append((message_id, datetime.now()))


def send_reply(message_id: str, text: str):
    """通过飞书 API 回复消息"""
    # 飞书消息内容需要是 JSON 字符串格式
    import json
    content_json = json.dumps({"text": text})

    request = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(ReplyMessageRequestBody.builder()
                      .msg_type("text")
                      .content(content_json)
                      .build()) \
        .build()
    response = client.im.v1.message.reply(request)
    if not response.success():
        logger.error(f"回复消息失败: {response.msg}")
    return response


def add_reaction(message_id: str, reaction_type: str):
    """通过飞书 API 添加表情"""
    request = CreateMessageReactionRequest.builder() \
        .message_id(message_id) \
        .request_body(CreateMessageReactionRequestBody.builder()
                      .reaction_type(reaction_type)
                      .build()) \
        .build()
    response = client.im.v1.message_reaction.create(request)
    if not response.success():
        logger.error(f"添加表情失败: {response.msg}")
    return response
    return response


def process_x_url(url: str, retry_count: int = 0, max_retries: int = 3) -> str:
    """
    处理一条 X 链接：提取 → 摘要 → 写入 Obsidian。
    支持重试机制（最多3次，每次10分钟超时）。
    返回处理结果文本。
    """
    # 1. 提取推文
    logger.info(f"正在提取推文: {url}")
    tweet = extract_tweet(url)
    if not tweet:
        return "❌ 推文提取失败，请检查链接是否有效。"

    # 2. 提取评论（如果有）
    logger.info("正在提取评论...")
    replies = extract_replies(url, max_replies=20)

    # 3. 生成摘要+标签（10分钟超时）
    logger.info(f"正在生成摘要: @{tweet.get('author_handle', '')}")
    try:
        summary = summarize_tweet(
            tweet,
            replies=replies,  # 传入评论用于生成摘要
            api_key=CLAUDE.get("api_key") or None,
            base_url=CLAUDE.get("base_url") or None,
            model=CLAUDE.get("model", "qwen3.5-plus"),
            timeout=600,  # 10分钟
        )
    except Exception as e:
        # 超时或错误，检查是否可以重试
        if retry_count < max_retries:
            logger.warning(f"API调用失败，准备重试 ({retry_count + 1}/{max_retries}): {e}")
            return process_x_url(url, retry_count + 1, max_retries)
        else:
            return f"❌ API调用失败，已重试{max_retries}次: {e}"

    if not summary:
        if retry_count < max_retries:
            logger.warning(f"摘要生成失败，准备重试 ({retry_count + 1}/{max_retries})")
            return process_x_url(url, retry_count + 1, max_retries)
        else:
            return "❌ AI摘要生成失败，已重试多次。"

    # 4. 写入 Obsidian（包含评论）
    logger.info("正在写入 Obsidian...")
    filepath = write_note(
        tweet,
        summary,
        OBSIDIAN["vault_path"],
        replies=replies,
        clippings_folder=OBSIDIAN.get("clippings_folder", "X-Clippings"),
    )
    if not filepath:
        return "❌ 写入 Obsidian 失败。"

    # 5. 保存到飞书 Wiki（可选）
    feishu_result = ""
    wiki_space_id = FEISHU.get("wiki_space_id", "")
    if wiki_space_id:
        logger.info("正在保存到飞书 Wiki...")
        wiki_url = save_to_feishu_wiki(
            client,
            wiki_space_id,
            summary.get("title", "推文摘要"),
            "",  # content
            tweet,
            summary,
            replies,
        )
        if wiki_url:
            feishu_result = f"\n📚 飞书 Wiki: {wiki_url}"

    tags_str = " ".join(f"#{t}" for t in summary.get("tags", []))
    replies_info = f"💬 {len(replies)}条评论" if replies else ""
    result = (
        f"✅ 已保存到 Obsidian\n"
        f"📰 {summary.get('title', '')}\n"
        f"📝 {summary.get('summary_zh', '')}\n"
        f"🏷️ {tags_str}\n"
        f"👤 {tweet.get('author_handle', '')} {replies_info}"
        f"{feishu_result}"
    )
    return result


@app.post("/webhook/event")
async def handle_event(request: Request):
    """处理飞书事件回调"""
    body = await request.json()

    # 飞书 URL 验证（首次配置时）
    if body.get("type") == "url_verification":
        challenge = body.get("challenge", "")
        token = body.get("token", "")
        # 校验 token（如果配置中有值）
        expected_token = FEISHU.get("verification_token", "")
        if expected_token and token != expected_token:
            logger.warning(f"Token mismatch: got {token}, expected {expected_token}")
            return Response(status_code=403)
        logger.info(f"URL verification: challenge={challenge}")
        return {"challenge": challenge}

    # 处理消息事件
    header = body.get("header", {})
    event_type = header.get("event_type", "")

    if event_type != "im.message.receive_v1":
        return {"status": "ignored"}

    event = body.get("event", {})
    message = event.get("message", {})
    message_id = message.get("message_id", "")
    msg_type = message.get("message_type", "")

    # 仅处理文本消息
    if msg_type != "text":
        return {"status": "ignored"}

    # 去重检查（避免飞书事件重复推送）
    if is_message_processed(message_id):
        logger.info(f"消息已处理，跳过: {message_id}")
        return {"status": "ok"}

    # 提取消息文本
    import json
    content = json.loads(message.get("content", "{}"))
    text = content.get("text", "")

    # 检查是否包含 X URL
    url = is_x_url(text)
    if not url:
        return {"status": "ignored"}

    logger.info(f"收到 X 链接: {url}")

    # 标记消息已处理（防止重复）
    mark_message_processed(message_id)

    # 先回复确认，让用户知道正在处理
    send_reply(message_id, "⏳ 正在处理中...")

    # 异步处理（避免飞书超时重试）
    try:
        result = process_x_url(url)
        send_reply(message_id, result)
    except Exception as e:
        logger.error(f"处理失败: {e}")
        send_reply(message_id, f"❌ 处理失败: {e}")

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "x-to-obsidian"}


if __name__ == "__main__":
    import uvicorn

    host = config.get("server", {}).get("host", "0.0.0.0")
    port = config.get("server", {}).get("port", 9090)
    logger.info(f"启动 X to Obsidian Bot on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
