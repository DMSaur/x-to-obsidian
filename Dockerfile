# Python + Playwright (自带 Chromium)
FROM python:3.11-slim

WORKDIR /app

# 安装 Playwright 所需的系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Playwright Chromium（约 280MB）
RUN playwright install chromium --with-deps

# 复制代码
COPY . .

# 设置环境变量（启用 Playwright 模式）
ENV PORT=8080
ENV USE_PLAYWRIGHT=true

# 启动服务
CMD ["python", "bot.py"]