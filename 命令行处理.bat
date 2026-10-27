@echo off
chcp 65001 >nul
if "%~1"=="" (
    echo 用法: 命令行处理.bat PDF文件 [输出目录] [最大页数]
    echo 示例: 命令行处理.bat "1945-01-01(1).pdf" "results_cli" 3
    pause
    exit /b 1
)
set "OUTPUT_DIR=%~2"
if "%OUTPUT_DIR%"=="" set "OUTPUT_DIR=results_cli"
set "PYTHON_EXE=%~dp0backend\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [错误] PaddleOCR环境尚未安装，请先运行“安装PaddleOCR.bat”。
    pause
    exit /b 1
)
set "OCR_BACKEND=paddleocr"
set "OCR_PADDLE_VERSION=PP-OCRv5"
cd /d "%~dp0backend"
if "%~3"=="" (
    "%PYTHON_EXE%" process_newspaper.py "%~1" -o "%OUTPUT_DIR%"
) else (
    "%PYTHON_EXE%" process_newspaper.py "%~1" -o "%OUTPUT_DIR%" -p "%~3"
)
pause
