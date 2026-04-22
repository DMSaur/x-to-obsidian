"""飞书 Wiki 笔记保存模块"""

import logging

from lark_oapi.api.docx.v1 import (
    CreateDocumentRequest,
    CreateDocumentRequestBody,
    CreateDocumentBlockChildrenRequest,
    CreateDocumentBlockChildrenRequestBody,
    GetDocumentBlockRequest,
)

logger = logging.getLogger(__name__)

# 飞书文档 block 类型
BLOCK_TYPE_TEXT = 2
BLOCK_TYPE_HEADING2 = 4
BLOCK_TYPE_HEADING3 = 5


def create_heading2(text: str) -> dict:
    """创建二级标题 block"""
    return {
        "block_type": BLOCK_TYPE_HEADING2,
        "heading2": {
            "elements": [{"text_run": {"content": text}}]
        }
    }


def create_text(text: str) -> dict:
    """创建文本 block"""
    return {
        "block_type": BLOCK_TYPE_TEXT,
        "text": {
            "elements": [{"text_run": {"content": text}}]
        }
    }


def save_to_feishu_wiki(
    client,
    space_id: str,
    title: str,
    content: str,
    tweet_data: dict,
    summary_data: dict,
    replies: list = None,
) -> str | None:
    """将推文保存到飞书知识库 Wiki。"""
    try:
        logger.info("正在创建飞书文档...")

        create_doc_req = CreateDocumentRequest.builder() \
            .request_body(CreateDocumentRequestBody.builder()
                         .title(title)
                         .folder_token("")
                         .build()) \
            .build()

        create_doc_resp = client.docx.v1.document.create(create_doc_req)

        if not create_doc_resp.success():
            logger.error(f"创建文档失败: {create_doc_resp.msg}")
            return None

        doc_id = create_doc_resp.data.document.document_id
        logger.info(f"文档创建成功: doc_id={doc_id}")

        write_document_content(client, doc_id, tweet_data, summary_data, replies)

        try:
            from lark_oapi.api.wiki.v2 import MoveDocsToWikiSpaceNodeRequest, MoveDocsToWikiSpaceNodeRequestBody

            move_req = MoveDocsToWikiSpaceNodeRequest.builder() \
                .space_id(space_id) \
                .request_body(MoveDocsToWikiSpaceNodeRequestBody.builder()
                             .obj_type("docx")
                             .obj_token(doc_id)
                             .parent_node_token("")
                             .build()) \
                .build()

            move_resp = client.wiki.v2.space_node.move_docs_to_wiki(move_req)

            if not move_resp.success():
                logger.warning(f"添加到 Wiki 失败: {move_resp.msg}")
                return f"https://my.feishu.cn/docx/{doc_id}"

            node_token = move_resp.data.node.token
            wiki_url = f"https://my.feishu.cn/wiki/{space_id}/{node_token}"
            logger.info(f"已添加到 Wiki: {wiki_url}")
            return wiki_url

        except Exception as e:
            logger.warning(f"添加到 Wiki 异常: {e}")
            return f"https://my.feishu.cn/docx/{doc_id}"

    except Exception as e:
        logger.error(f"保存到飞书失败: {e}")
        return None


def write_document_content(client, doc_id: str, tweet_data: dict, summary_data: dict, replies: list):
    """写入飞书文档内容。"""
    try:
        # 获取文档根块
        get_block_req = GetDocumentBlockRequest.builder() \
            .document_id(doc_id) \
            .block_id(doc_id) \
            .build()

        get_block_resp = client.docx.v1.document_block.get(get_block_req)

        if not get_block_resp.success():
            root_block_id = doc_id
        else:
            root_block_id = get_block_resp.data.block.block_id

        logger.info(f"根块 ID: {root_block_id}")

        # 构建内容块列表
        blocks = []

        # === 摘要 ===
        summary_text = summary_data.get("summary_zh", "")
        if summary_text:
            blocks.append(create_heading2("摘要"))
            blocks.append(create_text(summary_text))

        # === 原文 ===
        original_text = tweet_data.get("text", "")
        if original_text:
            blocks.append(create_heading2("原文"))
            blocks.append(create_text(original_text))

        # === 评论 ===
        if replies and len(replies) > 0:
            blocks.append(create_heading2(f"评论（{len(replies)}条）"))
            for r in replies[:10]:
                author = r.get("author", "未知")
                text = r.get("text", "")[:200]
                blocks.append(create_text(f"**{author}**: {text}"))
        else:
            # 即使没有评论也显示提示
            blocks.append(create_heading2("评论"))
            blocks.append(create_text("暂无评论数据"))

        # === 标签 ===
        tags = summary_data.get("tags", [])
        if tags:
            blocks.append(create_heading2("标签"))
            tags_text = " ".join([f"#{t}" for t in tags])
            blocks.append(create_text(tags_text))

        # === 来源 ===
        source_url = tweet_data.get("url", "")
        if source_url:
            blocks.append(create_heading2("来源"))
            blocks.append(create_text(source_url))

        # 添加块到文档
        for i, block in enumerate(blocks):
            try:
                req = CreateDocumentBlockChildrenRequest.builder() \
                    .document_id(doc_id) \
                    .block_id(root_block_id) \
                    .request_body(CreateDocumentBlockChildrenRequestBody.builder()
                                 .children([block])
                                 .index(i)
                                 .build()) \
                    .build()

                resp = client.docx.v1.document_block_children.create(req)
                if not resp.success():
                    logger.warning(f"添加文档块失败: {resp.msg}")
            except Exception as e:
                logger.warning(f"添加块异常: {e}")

        logger.info(f"文档内容写入完成: {doc_id}")

    except Exception as e:
        logger.error(f"写入文档内容失败: {e}")