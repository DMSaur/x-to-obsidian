# 使用官方 Python 镜像，手动安装 Node.js
FROM python:3.11-slim

WORKDIR /app

# 安装 Node.js 18 (使用 NodeSource)
RUN apt-get update && \
    apt-get install -y curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 安装 xreach CLI
RUN npm install -g xreach

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 设置环境变量
ENV PORT=8080

# 启动服务
CMD ["python", "bot.py"]