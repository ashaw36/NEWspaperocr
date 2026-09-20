@echo off
chcp 65001 >nul
title 古报纸OCR系统 - 停止服务

echo ========================================
echo   古报纸OCR系统 - 停止所有服务
echo ========================================
echo.

:: 停止Python进程
echo 正在停止所有Python服务...
taskkill /F /IM python.exe 2>nul
taskkill /F /IM py.exe 2>nul

if %errorlevel% equ 0 (
    echo [成功] 服务已停止
) else (
    echo [提示] 未发现运行中的服务
)

echo.
echo 按任意键退出...
pause >nul
