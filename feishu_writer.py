"""飞书文档保存模块"""

import logging
import os

from lark_oapi.api.docx.v1 import (
    CreateDocumentRequest,
    CreateDocumentRequestBody,
    CreateDocumentBlockChildrenRequest,
    CreateDocumentBlockChildrenRequestBody,
    GetDocumentBlockRequest,
)
from lark_oapi.api.drive.v1 import (
    BatchCreatePermissionMemberRequest,
    BatchCreatePermissionMemberRequestBody,
)

logger = logging.getLogger(__name__)

BLOCK_TYPE_TEXT = 2
BLOCK_TYPE_HEADING2 = 4

# 你的飞书 open_id（用于分享权限）- 从环境变量读取
USER_OPEN_ID = os.environ.get("FEISHU_USER_OPEN_ID", "")


def create_heading2(text: str) -> dict:
    return {"block_type": BLOCK_TYPE_HEADING2, "heading2": {"elements": [{"text_run": {"content": text}}]}}


def create_text(text: str) -> dict:
    return {"block_type": BLOCK_TYPE_TEXT, "text": {"elements": [{"text_run": {"content": text}}]}}


def share_document_to_user(client, doc_token: str, user_open_id: str) -> dict:
    """分享文档给指定用户（可编辑权限），返回详细结果"""
    try:
        req = BatchCreatePermissionMemberRequest.builder() \
            .token(doc_token) \
            .type("docx") \
            .need_notification(True) \
            .request_body(BatchCreatePermissionMemberRequestBody.builder()
                         .members([{
                             "member_type": "openid",
                             "member_id": user_open_id,
                             "perm": "full_access",
                         }])
                         .build()) \
            .build()

        resp = client.drive.v1.permission_member.batch_create(req)

        return {
            "success": resp.success(),
            "code": resp.code,
            "msg": resp.msg,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def save_to_feishu_doc(client, title: str, tweet_data: dict, summary_data: dict) -> str | None:
    """创建飞书文档，存到个人文档空间，并分享给你"""
    try:
        logger.info("正在创建飞书文档...")

        req = CreateDocumentRequest.builder() \
            .request_body(CreateDocumentRequestBody.builder().title(title).folder_token("").build()) \
            .build()

        resp = client.docx.v1.document.create(req)

        if not resp.success():
            logger.error(f"创建文档失败: {resp.msg}")
            return None

        doc_id = resp.data.document.document_id
        logger.info(f"文档创建成功: doc_id={doc_id}")

        write_document_content(client, doc_id, tweet_data, summary_data)

        if USER_OPEN_ID:
            result = share_document_to_user(client, doc_id, USER_OPEN_ID)
            if not result.get("success"):
                logger.warning(f"分享失败: {result}")
            else:
                logger.info(f"文档已分享给: {USER_OPEN_ID}")

        doc_url = f"https://my.feishu.cn/docx/{doc_id}"
        logger.info(f"文档保存成功: {doc_url}")
        return doc_url

    except Exception as e:
        logger.error(f"保存文档失败: {e}")
        return None


def write_document_content(client, doc_id: str, tweet_data: dict, summary_data: dict):
    """写入飞书文档内容"""
    try:
        req = GetDocumentBlockRequest.builder().document_id(doc_id).block_id(doc_id).build()
        resp = client.docx.v1.document_block.get(req)

        root_block_id = resp.data.block.block_id if resp.success() and resp.data else doc_id

        blocks = []

        if summary_data.get("summary_zh"):
            blocks.extend([create_heading2("摘要"), create_text(summary_data["summary_zh"])])

        if tweet_data.get("text"):
            blocks.extend([create_heading2("原文"), create_text(tweet_data["text"])])

        blocks.extend([create_heading2("评论"), create_text("需要认证才能获取评论，请点击来源链接查看")])

        if summary_data.get("tags"):
            blocks.extend([create_heading2("标签"), create_text(" ".join(f"#{t}" for t in summary_data["tags"]))])

        if tweet_data.get("url"):
            blocks.extend([create_heading2("来源"), create_text(tweet_data["url"])])

        for i, block in enumerate(blocks):
            try:
                req = CreateDocumentBlockChildrenRequest.builder() \
                    .document_id(doc_id) \
                    .block_id(root_block_id) \
                    .request_body(CreateDocumentBlockChildrenRequestBody.builder().children([block]).index(i).build()) \
                    .build()
                resp = client.docx.v1.document_block_children.create(req)
                if not resp.success():
                    logger.warning(f"添加块失败: {resp.msg}")
            except Exception as e:
                logger.warning(f"添加块异常: {e}")

        logger.info(f"文档内容写入完成")

    except Exception as e:
        logger.error(f"写入内容失败: {e}")