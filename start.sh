#!/bin/bash
# 快速启动脚本

echo "🗞️ 古报纸 OCR 系统 - 启动脚本"
echo "================================"
echo ""

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "⚠️  未找到虚拟环境，正在创建..."
    python -m venv .venv
    echo "✅ 虚拟环境创建完成"
fi

# Activate virtual environment
echo "📦 激活虚拟环境..."
source .venv/Scripts/activate 2>/dev/null || source .venv/bin/activate 2>/dev/null

# Check dependencies
if ! python -c "import flask" 2>/dev/null; then
    echo "📥 安装依赖包..."
    pip install -r backend/requirements.txt
    echo "✅ 依赖安装完成"
fi

# Check .env file
if [ ! -f "backend/.env" ]; then
    echo "⚙️  配置文件不存在，创建默认配置..."
    cp backend/.env.example backend/.env 2>/dev/null || echo "AI_PROVIDER=deepseek" > backend/.env
    echo "✅ 配置文件已创建: backend/.env"
    echo "   请编辑此文件配置 AI 服务 API 密钥"
fi

# Start service
echo ""
echo "🚀 启动服务..."
cd backend
python app.py
