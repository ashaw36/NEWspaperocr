@echo off
chcp 65001 > nul
echo 正在重启 Flask 服务...

REM 停止所有占用5000端口的进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    echo 停止进程 %%a
    taskkill /F /PID %%a 2>nul
)

timeout /t 2 /nobreak > nul

echo 启动新服务...
cd /d "%~dp0"
python app.py

pause
