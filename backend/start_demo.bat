@echo off
chcp 65001 > nul
cd /d D:\古报纸OCR\backend

echo ============================================
echo    古报纸 OCR 识别系统 - 快速启动
echo ============================================
echo.
echo [1] 正在检查环境...

REM 激活虚拟环境(如果存在)
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [√] 虚拟环境已激活
) else (
    echo [!] 未找到虚拟环境，使用系统Python
)

echo.
echo [2] 停止旧服务...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    taskkill /F /PID %%a 2>nul
)
timeout /t 2 /nobreak > nul

echo.
echo [3] 启动服务...
echo.
echo ============================================
echo    服务地址: http://127.0.0.1:5000
echo    演示界面: http://127.0.0.1:5000/demo
echo    健康检查: http://127.0.0.1:5000/api/health
echo ============================================
echo.

REM 启动服务
python app.py

pause
