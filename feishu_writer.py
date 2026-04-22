"""飞书 Wiki 笔记保存模块"""

import logging
import json

import lark_oapi as lark
from lark_oapi.api.docx.v1 import (
    CreateDocumentRequest,
    CreateDocumentRequestBody,
    CreateDocumentBlockChildrenRequest,
    CreateDocumentBlockChildrenRequestBody,
    GetDocumentBlockRequest,
)

logger = logging.getLogger(__name__)


def save_to_feishu_wiki(
    client,
    space_id: str,
    title: str,
    content: str,
    tweet_data: dict,
    summary_data: dict,
    replies: list = None,
) -> str | None:
    """
    将推文保存到飞书知识库 Wiki。

    策略：先创建文档，写入内容，然后添加到 Wiki。

    参数:
        client: lark client
        space_id: 知识库 ID
        title: 页面标题
        content: 页面内容（Markdown 格式）
        tweet_data: 推文数据
        summary_data: 摘要数据
        replies: 评论列表

    返回:
        文档 URL 或 None
    """
    try:
        # 1. 创建飞书文档
        logger.info("正在创建飞书文档...")

        create_doc_req = CreateDocumentRequest.builder() \
            .request_body(CreateDocumentRequestBody.builder()
                         .title(title)
                         .folder_token("")  # 根目录
                         .build()) \
            .build()

        create_doc_resp = client.docx.v1.document.create(create_doc_req)

        if not create_doc_resp.success():
            logger.error(f"创建文档失败: {create_doc_resp.msg}")
            return None

        doc_id = create_doc_resp.data.document.document_id
        logger.info(f"文档创建成功: doc_id={doc_id}")

        # 2. 写入文档内容
        write_document_content(client, doc_id, tweet_data, summary_data, replies)

        # 3. 添加文档到 Wiki（使用 MoveDocsToWiki API）
        # 注意：飞书 Wiki API 的正确用法
        try:
            from lark_oapi.api.wiki.v2 import MoveDocsToWikiSpaceNodeRequest, MoveDocsToWikiSpaceNodeRequestBody

            move_req = MoveDocsToWikiSpaceNodeRequest.builder() \
                .space_id(space_id) \
                .request_body(MoveDocsToWikiSpaceNodeRequestBody.builder()
                             .obj_type("docx")  # 文档类型
                             .obj_token(doc_id)
                             .parent_node_token("")  # 根目录
                             .build()) \
                .build()

            move_resp = client.wiki.v2.space_node.move_docs_to_wiki(move_req)

            if not move_resp.success():
                logger.warning(f"添加到 Wiki 失败: {move_resp.msg}")
                # 返回文档链接（即使不在 Wiki 中）
                return f"https://my.feishu.cn/docx/{doc_id}"

            node_token = move_resp.data.node.token
            wiki_url = f"https://my.feishu.cn/wiki/{space_id}/{node_token}"
            logger.info(f"已添加到 Wiki: {wiki_url}")
            return wiki_url

        except Exception as e:
            logger.warning(f"添加到 Wiki 异常: {e}")
            # 返回文档链接
            return f"https://my.feishu.cn/docx/{doc_id}"

    except Exception as e:
        logger.error(f"保存到飞书失败: {e}")
        return None


def write_document_content(client, doc_id: str, tweet_data: dict, summary_data: dict, replies: list):
    """
    写入飞书文档内容。

    使用 docx API 向文档添加内容块。
    """
    try:
        # 首先获取文档的根块（page block）
        from lark_oapi.api.docx.v1 import GetDocumentBlockRequest

        get_block_req = GetDocumentBlockRequest.builder() \
            .document_id(doc_id) \
            .block_id(doc_id) \
            .build()

        get_block_resp = client.docx.v1.document_block.get(get_block_req)

        if not get_block_resp.success():
            logger.warning(f"获取文档块失败: {get_block_resp.msg}")
            # 尝试直接使用 doc_id 作为 block_id
            root_block_id = doc_id
        else:
            # 获取 page block 的 ID
            root_block_id = get_block_resp.data.block.block_id

        logger.info(f"根块 ID: {root_block_id}")

        # 构建内容块
        blocks = []

        # 添加摘要
        summary_text = summary_data.get("summary_zh", "")
        if summary_text:
            blocks.append({
                "block_type": 2,  # text block
                "text": {
                    "elements": [
                        {"text_run": {"content": f"## 摘要\n\n{summary_text}\n\n"}}
                    ],
                    "style": {}
                }
            })

        # 添加原文
        original_text = tweet_data.get("text", "")
        if original_text:
            blocks.append({
                "block_type": 2,  # text block
                "text": {
                    "elements": [
                        {"text_run": {"content": f"## 原文\n\n{original_text}\n\n"}}
                    ],
                    "style": {}
                }
            })

        # 添加评论
        if replies:
            replies_text = "\n".join([
                f"- {r.get('author', '未知')}: {r.get('text', '')[:100]}"
                for r in replies[:5]
            ])
            blocks.append({
                "block_type": 2,
                "text": {
                    "elements": [
                        {"text_run": {"content": f"## 评论（{len(replies)}条）\n\n{replies_text}"}}
                    ],
                    "style": {}
                }
            })

        # 添加标签
        tags = summary_data.get("tags", [])
        if tags:
            tags_text = " ".join([f"#{t}" for t in tags])
            blocks.append({
                "block_type": 2,
                "text": {
                    "elements": [
                        {"text_run": {"content": f"## 标签\n\n{tags_text}"}}
                    ],
                    "style": {}
                }
            })

        # 使用 docx API 添加块
        for block in blocks:
            try:
                create_block_req = CreateDocumentBlockChildrenRequest.builder() \
                    .document_id(doc_id) \
                    .block_id(root_block_id)  # 使用正确的根块 ID
                    .request_body(CreateDocumentBlockChildrenRequestBody.builder()
                                 .children([block])
                                 .index(-1)  # 插入到末尾
                                 .build()) \
                    .build()

                create_block_resp = client.docx.v1.document_block_children.create(create_block_req)
                if not create_block_resp.success():
                    logger.warning(f"添加文档块失败: {create_block_resp.msg}")

            except Exception as e:
                logger.warning(f"添加块异常: {e}")

        logger.info(f"文档内容写入完成: {doc_id}")

    except Exception as e:
        logger.error(f"写入文档内容失败: {e}")