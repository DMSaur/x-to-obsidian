# 纯 Python 镜像（使用 oEmbed API，无需认证）
FROM python:3.11-slim

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

ENV PORT=8080

CMD ["python", "bot.py"]