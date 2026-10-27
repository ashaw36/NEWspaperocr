@echo off
cd /d D:\古报纸OCR\backend
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do taskkill /F /PID %%a 2>nul
timeout /t 2 /nobreak > nul
python app.py
pause
