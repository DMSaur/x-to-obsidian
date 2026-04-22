"""飞书 Wiki 笔记保存模块"""

import logging
import base64
import httpx

from lark_oapi.api.wiki.v2 import *
from lark_oapi.api.docx.v1 import *

logger = logging.getLogger(__name__)


def create_feishu_document(client, title: str, content_blocks: list) -> str | None:
    """
    创建飞书文档并返回文档 token。

    参数:
        client: lark client
        title: 文档标题
        content_blocks: 文档内容块列表

    返回:
        文档 token 或 None
    """
    # 飞书文档需要通过特定 API 创建
    # 使用 docx.CreateDocument API (如果存在)
    # 或者使用预创建的模板文档复制

    # 实际飞书 API 中，文档创建需要通过 drive API
    # 这里我们尝试一种简化方案：直接使用飞书内置的文档创建功能

    try:
        # 方法1：尝试使用飞书的文档创建 API
        # 注意：飞书文档创建需要特殊处理

        # 创建文档请求（使用 docx API）
        # 首先需要获取一个文档 token，通常需要通过其他方式

        # 暂时使用另一种方案：创建 Wiki 页面时飞书会自动创建关联文档
        return None

    except Exception as e:
        logger.error(f"创建飞书文档失败: {e}")
        return None


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

    参数:
        client: lark client
        space_id: 知识库 ID
        title: 页面标题
        content: 页面内容（Markdown 格式）
        tweet_data: 推文数据
        summary_data: 摘要数据
        replies: 评论列表

    返回:
        Wiki 页面 URL 或 None
    """
    try:
        # 构建 Wiki 页面内容（飞书文档格式）
        # 飞书文档使用 Block 结构

        # 创建 Wiki 页面节点
        # obj_type = "doc" 表示文档类型
        # 飞书会自动创建关联的文档

        request = CreateSpaceNodeRequest.builder() \
            .space_id(space_id) \
            .request_body(CreateSpaceNodeRequestBody.builder()
                         .obj_type("doc")  # 文档类型
                         .obj_token("")    # 空表示创建新文档
                         .parent_node_token("")  # 空表示根目录
                         .node_title(title)
                         .build()) \
            .build()

        response = client.wiki.v2.space_node.create(request)

        if not response.success():
            logger.error(f"创建 Wiki 页面失败: {response.msg}")
            # 尝试另一种方式
            return None

        node_token = response.data.node.token
        obj_token = response.data.node.obj_token

        logger.info(f"Wiki 页面创建成功: node_token={node_token}, obj_token={obj_token}")

        # 写入文档内容
        if obj_token:
            write_document_content(client, obj_token, content, tweet_data, summary_data, replies)

        # 返回 Wiki 页面 URL
        wiki_url = f"https://my.feishu.cn/wiki/{space_id}/{node_token}"
        return wiki_url

    except Exception as e:
        logger.error(f"保存到飞书 Wiki 失败: {e}")
        return None


def write_document_content(client, doc_token: str, content: str, tweet_data: dict, summary_data: dict, replies: list):
    """
    写入飞书文档内容。

    使用 docx API 向文档添加内容块。
    """
    try:
        # 飞书文档内容使用 Block 结构
        # 这里我们构建简单的文本块

        # 创建标题块
        blocks = []

        # 添加摘要
        summary_text = summary_data.get("summary_zh", "")
        if summary_text:
            blocks.append({
                "type": "text",
                "text": f"## 摘要\n{summary_text}\n"
            })

        # 添加原文
        original_text = tweet_data.get("text", "")
        if original_text:
            blocks.append({
                "type": "text",
                "text": f"## 原文\n{original_text}\n"
            })

        # 添加评论
        if replies:
            replies_text = "\n".join([
                f"{r.get('author', '未知')}: {r.get('text', '')}"
                for r in replies[:5]
            ])
            blocks.append({
                "type": "text",
                "text": f"## 评论（{len(replies)}条）\n{replies_text}"
            })

        # 使用 docx API 添加内容
        # CreateDocumentBlockChildrenRequest 用于向文档添加块

        for block in blocks:
            try:
                request = CreateDocumentBlockChildrenRequest.builder() \
                    .document_id(doc_token) \
                    .block_id("") \
                    .request_body(CreateDocumentBlockChildrenRequestBody.builder()
                                 .children([{
                                     "type": block["type"],
                                     "text": block["text"]
                                 }])
                                 .build()) \
                    .build()

                response = client.docx.v1.document_block_children.create(request)
                if not response.success():
                    logger.warning(f"添加文档块失败: {response.msg}")

            except Exception as e:
                logger.warning(f"添加文档块异常: {e}")

        logger.info(f"文档内容写入完成: {doc_token}")

    except Exception as e:
        logger.error(f"写入文档内容失败: {e}")


def upload_image_to_feishu(client, image_url: str) -> str | None:
    """
    上传图片到飞书，返回 image_token。

    用于在飞书文档中插入图片。
    """
    try:
        # 下载图片
        with httpx.Client(timeout=30) as http_client:
            resp = http_client.get(image_url)
            resp.raise_for_status()
            image_data = resp.content

        # 飞书图片上传 API
        # 使用 drive.v1.media.upload 或类似 API

        # 暂时返回 None，图片功能需要额外实现
        return None

    except Exception as e:
        logger.error(f"上传图片失败: {e}")
        return None