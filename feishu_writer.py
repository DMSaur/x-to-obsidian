"""飞书文档保存模块"""

import logging

from lark_oapi.api.docx.v1 import (
    CreateDocumentRequest,
    CreateDocumentRequestBody,
    CreateDocumentBlockChildrenRequest,
    CreateDocumentBlockChildrenRequestBody,
    GetDocumentBlockRequest,
)

logger = logging.getLogger(__name__)

BLOCK_TYPE_TEXT = 2
BLOCK_TYPE_HEADING2 = 4


def create_heading2(text: str) -> dict:
    return {"block_type": BLOCK_TYPE_HEADING2, "heading2": {"elements": [{"text_run": {"content": text}}]}}


def create_text(text: str) -> dict:
    return {"block_type": BLOCK_TYPE_TEXT, "text": {"elements": [{"text_run": {"content": text}}]}}


def save_to_feishu_doc(client, title: str, tweet_data: dict, summary_data: dict) -> str | None:
    """创建飞书文档，存到个人文档空间（你是 owner，可管理删除）"""
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

        doc_url = f"https://my.feishu.cn/docx/{doc_id}"
        logger.info(f"文档保存成功: {doc_url}")
        return doc_url

    except Exception as e:
        logger.error(f"保存文档失败: {e}")
        return None


def write_document_content(client, doc_id: str, tweet_data: dict, summary_data: dict):
    """写入飞书文档内容"""
    try:
        # 获取根块
        req = GetDocumentBlockRequest.builder().document_id(doc_id).block_id(doc_id).build()
        resp = client.docx.v1.document_block.get(req)

        root_block_id = resp.data.block.block_id if resp.success() and resp.data else doc_id

        blocks = []

        # 摘要
        if summary_data.get("summary_zh"):
            blocks.extend([create_heading2("摘要"), create_text(summary_data["summary_zh"])])

        # 原文
        if tweet_data.get("text"):
            blocks.extend([create_heading2("原文"), create_text(tweet_data["text"])])

        # 评论提示
        blocks.extend([create_heading2("评论"), create_text("需要认证才能获取评论，请点击来源链接查看")])

        # 标签
        if summary_data.get("tags"):
            blocks.extend([create_heading2("标签"), create_text(" ".join(f"#{t}" for t in summary_data["tags"]))])

        # 来源
        if tweet_data.get("url"):
            blocks.extend([create_heading2("来源"), create_text(tweet_data["url"])])

        # 添加块
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