@echo off
REM Windows 启动脚本

echo ===============================
echo 古报纸 OCR 系统 - 启动脚本
echo ===============================
echo.

REM Check if virtual environment exists
if not exist ".venv" (
    echo 未找到虚拟环境，正在创建...
    python -m venv .venv
    echo 虚拟环境创建完成
)

REM Activate virtual environment
echo 激活虚拟环境...
call .venv\Scripts\activate.bat

REM Check dependencies
python -c "import flask" >nul 2>&1
if errorlevel 1 (
    echo 安装依赖包...
    pip install -r backend\requirements.txt
    echo 依赖安装完成
)

REM Check .env file
if not exist "backend\.env" (
    echo 配置文件不存在，创建默认配置...
    if exist "backend\.env.example" (
        copy backend\.env.example backend\.env
    ) else (
        echo AI_PROVIDER=deepseek > backend\.env
    )
    echo 配置文件已创建: backend\.env
    echo 请编辑此文件配置 AI 服务 API 密钥
)

REM Start service
echo.
echo 启动服务...
cd backend
python app.py

pause
