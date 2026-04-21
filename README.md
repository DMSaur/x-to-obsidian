# X to Obsidian Bot

飞书 Bot，自动将 X/Twitter 帖子保存到 Obsidian vault。

## 功能

- 飞书群发送 X 链接 → 自动提取推文内容（文本+图片）
- Qwen AI 生成中文摘要 + 自动标签
- 图片下载到 Obsidian vault 附件目录
- 生成 Markdown 笔记（frontmatter + wikilink 图片引用）

## 安装

```bash
cd ~/x-to-obsidian
pip3 install -r requirements.txt
```

## 配置

1. 复制配置模板：
   ```bash
   cp config.yaml.template config.yaml
   ```

2. 填入实际配置值（飞书凭证、Obsidian vault 路径、API key）

3. 飞书开放平台配置：
   - 创建自建应用 → 添加机器人能力
   - 事件订阅 URL：`https://你的隧道地址/webhook/event`
   - 订阅事件：`im.message.receive_v1`
   - 权限：`im:message:receive_as_bot`, `im:message:send_as_bot`

## 运行

```bash
# 启动 cloudflared 隧道
cloudflared tunnel --url http://localhost:9090

# 启动 Bot
python3 bot.py
```

## 依赖

- xreach CLI（推文提取）
- 飞书开放平台 SDK
- OpenAI SDK（兼容 DashScope）
- httpx（图片下载）

## 项目结构

```
x-to-obsidian/
├── bot.py              # 飞书 Bot 主服务
├── extractor.py        # 推文提取
├── summarizer.py       # AI 摘要+标签
├── writer.py           # Obsidian 笔记写入
├── config.yaml         # 配置（敏感，不上传）
└── requirements.txt
```