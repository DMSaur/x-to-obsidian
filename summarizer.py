"""AI摘要+标签生成模块 — 调用 OpenAI 兼容 API"""

import json
import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位贸易政策和经济学研究助手。用户会给你一条 X/Twitter 推文的内容，请你：

1. 生成一个简短的中文标题（10字以内）
2. 生成中文摘要（2-3句话，抓住核心观点或信息）
3. 生成 2-5 个相关标签（英文，小写，用连字符连接）

请严格按以下 JSON 格式返回，不要有任何其他文字：
{
  "title": "标题",
  "summary_zh": "中文摘要",
  "tags": ["tag1", "tag2", "tag3"]
}"""


def summarize_tweet(
    tweet_data: dict,
    replies: list[dict] = None,  # 评论数据
    api_key: str | None = None,
    base_url: str | None = None,
    model: str = "qwen3.5-plus",
    timeout: int = 600,  # 10分钟超时
) -> dict | None:
    """
    调用 OpenAI 兼容 API 为推文生成摘要和标签。

    参数:
        tweet_data: extractor.extract_tweet() 返回的字典
        api_key: API Key
        base_url: API Base URL
        model: 模型名称
        timeout: 超时时间（秒）

    返回:
        {"title": "...", "summary_zh": "...", "tags": [...]}
    """
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
    )

    user_message = f"""作者: {tweet_data.get('author_name', '')} ({tweet_data.get('author_handle', '')})
日期: {tweet_data.get('created_at', '')}
互动: {tweet_data.get('like_count', 0)} 赞, {tweet_data.get('retweet_count', 0)} 转发, {tweet_data.get('reply_count', 0)} 评论

推文内容:
{tweet_data.get('text', '')}"""

    # 如果有评论，添加评论摘要
    if replies and len(replies) > 0:
        replies_text = "\n".join([
            f"{r.get('author', '未知')}: {r.get('text', '')[:100]}"
            for r in replies[:10]  # 只取前10条评论
        ])
        user_message += f"\n\n热门评论（共{len(replies)}条）:\n{replies_text}"

    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=500,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )

        text = response.choices[0].message.content.strip()

        # 尝试解析 JSON（可能被包裹在 ```json ``` 中）
        if text.startswith("```"):
            lines = text.split("\n")
            # 移除第一行（```json 或 ```）
            if lines[0].startswith("```"):
                lines = lines[1:]
            # 移除最后一行（```）
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        result = json.loads(text)
        logger.info(f"摘要生成成功: {result.get('title', '')}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"AI 返回的 JSON 解析失败: {e}\n原始输出: {text}")
        return None
    except Exception as e:
        logger.error(f"调用 API 失败: {e}")
        return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # 简单测试：传入推文文本
        test_data = {"text": sys.argv[1], "author_name": "Test", "author_handle": "@test"}
        result = summarize_tweet(
            test_data,
            api_key="sk-1722b95b5fc34bada92ebc75618e67c1",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        if result:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("摘要生成失败")
    else:
        print("用法: python summarizer.py <推文文本>")