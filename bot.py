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
from feishu_writer import save_to_feishu_doc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 加载配置（支持环境变量）
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")
try:
    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)
except FileNotFoundError:
    config = {}

# 环境变量覆盖配置（Render 部署使用）
FEISHU = {
    "app_id": os.environ.get("FEISHU_APP_ID", config.get("feishu", {}).get("app_id", "")),
    "app_secret": os.environ.get("FEISHU_APP_SECRET", config.get("feishu", {}).get("app_secret", "")),
    "verification_token": os.environ.get("FEISHU_VERIFICATION_TOKEN", config.get("feishu", {}).get("verification_token", "")),
    "wiki_space_id": os.environ.get("FEISHU_WIKI_SPACE_ID", config.get("feishu", {}).get("wiki_space_id", "")),
}
OBSIDIAN = {
    "vault_path": os.environ.get("OBSIDIAN_VAULT_PATH", config.get("obsidian", {}).get("vault_path", "/tmp/obsidian-vault")),
    "clippings_folder": config.get("obsidian", {}).get("clippings_folder", "X-Clippings"),
}
CLAUDE = {
    "api_key": os.environ.get("DASHSCOPE_API_KEY", config.get("claude", {}).get("api_key", "")),
    "base_url": os.environ.get("CLAUDE_BASE_URL", config.get("claude", {}).get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")),
    "model": config.get("claude", {}).get("model", "qwen3.5-plus"),
}

app = FastAPI(title="X to Obsidian Bot")

# 飞书客户端
import lark_oapi as lark

client = lark.Client.builder() \
    .app_id(FEISHU["app_id"]) \
    .app_secret(FEISHU["app_secret"]) \
    .build()

# 已处理消息缓存（去重，最多保留100条，1小时过期）
processed_messages = deque(maxlen=100)

# 记录最近发送消息的用户 open_id
recent_sender_open_id = ""


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

    # 5. 保存到飞书文档（存到个人文档空间）
    feishu_result = ""
    logger.info("正在保存到飞书...")
    doc_url = save_to_feishu_doc(
        client,
        summary.get("title", "推文摘要"),
        tweet,
        summary,
    )
    if doc_url:
        feishu_result = f"\n📚 飞书文档: {doc_url}"

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
    # 记录完整 sender 信息用于调试
    logger.info(f"sender 数据: {event.get('sender', {})}")
    message_id = message.get("message_id", "")
    msg_type = message.get("message_type", "")

    # 记录发送者 open_id
    sender = event.get("sender", {})
    sender_open_id = sender.get("open_id", "")
    # 飞书 v2 事件中 open_id 可能在 sender_id 下
    if not sender_open_id:
        sender_id = sender.get("sender_id", {})
        sender_open_id = sender_id.get("open_id", "") or sender_id.get("user_id", "")
    if sender_open_id:
        global recent_sender_open_id
        recent_sender_open_id = sender_open_id
        logger.info(f"收到消息，发送者 open_id: {sender_open_id}")

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


@app.get("/debug/env")
async def debug_env():
    return {
        "app_id_set": bool(FEISHU.get("app_id")),
        "app_secret_set": bool(FEISHU.get("app_secret")),
    }


@app.get("/debug/doc")
async def debug_doc():
    """测试创建飞书文档"""
    from feishu_writer import save_to_feishu_doc

    result = save_to_feishu_doc(
        client,
        "测试文档",
        {"text": "这是测试内容", "url": "https://x.com/test/status/123"},
        {"summary_zh": "测试摘要", "tags": ["test"]},
    )
    return {"result": result, "user_open_id_set": bool(os.environ.get("FEISHU_USER_OPEN_ID", ""))}


@app.get("/debug/share")
async def debug_share():
    """测试分享功能"""
    from feishu_writer import save_to_feishu_doc, share_document_to_user, USER_OPEN_ID

    doc_url = save_to_feishu_doc(
        client,
        "分享测试文档",
        {"text": "测试分享功能", "url": "https://x.com/test/status/123"},
        {"summary_zh": "测试", "tags": ["test"]},
    )

    if not doc_url:
        return {"error": "创建文档失败"}

    doc_id = doc_url.split("/")[-1]

    return {
        "doc_url": doc_url,
        "doc_id": doc_id,
        "user_open_id": USER_OPEN_ID,
        "user_open_id_set": bool(USER_OPEN_ID),
        "hint": "请在 Render 设置环境变量 FEISHU_USER_OPEN_ID=你的open_id",
    }


@app.get("/debug/myid")
async def debug_myid():
    """返回最近发送消息用户的 open_id"""
    return {
        "open_id": recent_sender_open_id,
        "user_open_id_env": os.environ.get("FEISHU_USER_OPEN_ID", ""),
        "hint": "发送一条消息给 Bot，然后访问此端点获取你的 open_id",
    }


@app.get("/debug/perm")
async def debug_perm():
    """测试分享权限"""
    from feishu_writer import share_document_to_user, USER_OPEN_ID
    import subprocess, shutil

    # 先创建一个测试文档
    from feishu_writer import save_to_feishu_doc
    doc_url = save_to_feishu_doc(
        client,
        "权限测试文档",
        {"text": "测试", "url": "https://x.com/test"},
        {"summary_zh": "测试", "tags": ["test"]},
    )

    if not doc_url:
        return {"error": "创建文档失败"}

    doc_id = doc_url.split("/")[-1]

    # 尝试分享
    if USER_OPEN_ID:
        success = share_document_to_user(client, doc_id, USER_OPEN_ID)
        return {
            "doc_url": doc_url,
            "doc_id": doc_id,
            "user_open_id": USER_OPEN_ID,
            "share_success": success,
        }
    else:
        return {
            "doc_url": doc_url,
            "user_open_id": USER_OPEN_ID,
            "error": "FEISHU_USER_OPEN_ID 未设置",
        }


if __name__ == "__main__":
    import uvicorn

    # Render 使用 PORT 环境变量
    port = int(os.environ.get("PORT", config.get("server", {}).get("port", 9090)))
    host = config.get("server", {}).get("host", "0.0.0.0")
    logger.info(f"启动 X to Obsidian Bot on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
