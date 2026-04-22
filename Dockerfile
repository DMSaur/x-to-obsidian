# 包含 Python 和 Node.js 的镜像
FROM nikolaik/python-nodejs:python3.11-nodejs18

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 xreach (Node.js CLI)
RUN npm install -g xreach

# 复制代码
COPY . .

# 设置环境变量
ENV PORT=8080

# 启动服务
CMD ["python", "bot.py"]