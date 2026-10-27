@echo off
chcp 65001 >nul
setlocal
title 古报纸OCR - 安装PaddleOCR

echo ========================================
echo   安装 PaddleOCR CPU 环境（Python 3.12）
echo ========================================
echo.
cd /d "%~dp0backend"

where uv >nul 2>&1
if %errorlevel% equ 0 (
    echo [1/2] 正在创建独立 Python 3.12 环境...
    uv venv .venv --python 3.12
    if errorlevel 1 goto install_failed
    echo [2/2] 正在安装项目依赖和 PaddleOCR...
    uv pip install --python .venv\Scripts\python.exe -r requirements-paddle.txt
    if errorlevel 1 goto install_failed
    goto install_complete
)

where py >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 uv 或 Python Launcher。
    echo 请安装 uv，或安装 Python 3.12 后重试。
    pause
    exit /b 1
)

echo [1/2] 正在创建独立 Python 3.12 环境...
py -3.12 -m venv .venv
if errorlevel 1 goto python_missing
echo [2/2] 正在安装项目依赖和 PaddleOCR...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-paddle.txt
if errorlevel 1 goto install_failed

:install_complete
echo.
echo 安装完成。首次启动 PaddleOCR 时还会下载识别模型。
echo 之后双击“启动系统.bat”即可使用。
pause
exit /b 0

:python_missing
echo.
echo [错误] 没有找到 Python 3.12。请先安装 uv 或 Python 3.12。
pause
exit /b 1

:install_failed
echo.
echo [错误] 安装未完成。请检查网络后重新运行本脚本。
pause
exit /b 1
