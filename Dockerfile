# Python + Node.js (使用 NodeSource 安装)
FROM python:3.11-slim

WORKDIR /app

# 安装 Node.js 18 + 编译工具（better-sqlite3 需要）
RUN apt-get update && \
    apt-get install -y curl ca-certificates python3 make g++ && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 安装 xreach CLI（正确的包名是 xreach-cli）
RUN npm install -g xreach-cli

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

ENV PORT=8080

CMD ["python", "bot.py"]