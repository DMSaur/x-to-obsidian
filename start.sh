#!/bin/bash
# X to Obsidian Bot 启动脚本

cd "$(dirname "$0")"

# 激活 Python 环境（如果需要）
# source /path/to/venv/bin/activate

# 启动服务
exec python3 bot.py
