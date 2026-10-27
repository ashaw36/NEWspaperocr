@echo off
chcp 65001 >nul
title 古报纸OCR系统 - 启动服务
set "ROOT=%~dp0"
set "PYTHON_EXE=%ROOT%backend\.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [错误] PaddleOCR环境尚未安装，请先运行“安装PaddleOCR.bat”。
    pause
    exit /b 1
)
set "OCR_BACKEND=paddleocr"
set "OCR_PADDLE_VERSION=PP-OCRv5"

echo ========================================
echo   古报纸OCR系统 - 服务启动器
echo ========================================
echo.

:: 检查Python是否安装
where py >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

:: 启动后端服务
echo [1/2] 正在启动后端服务 (端口5000)...
cd /d "%ROOT%backend"
start "古报纸OCR-后端" cmd /k ""%PYTHON_EXE%" app.py"
timeout /t 3 /nobreak >nul

:: 启动前端服务
echo [2/2] 正在启动前端服务 (端口8080)...
cd /d "%ROOT%frontend"
start "古报纸OCR-前端" cmd /k "py -m http.server 8080"
timeout /t 2 /nobreak >nul

echo.
echo ========================================
echo   服务启动完成！
echo ========================================
echo.
echo   前端界面: http://localhost:8080
echo   后端API:  http://localhost:5000
echo.
echo   提示: 关闭此窗口不会停止服务
echo   要停止服务，请关闭对应的命令行窗口
echo.
echo   按任意键在浏览器中打开应用...
pause >nul

:: 打开浏览器
start http://localhost:8080

exit
