@echo off
chcp 65001 >nul
title AI Sanal Dolap - ag uzerinden
cd /d "%~dp0"

echo.
echo   AI Sanal Dolap baslatiliyor (ayni Wi-Fi'daki cihazlar da erisebilir)
echo.
echo   Bu bilgisayarin adresleri:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo      http://%%a:8000
echo.
echo   Kapatmak icin bu pencereyi kapat ya da Ctrl+C
echo.

start "" /b cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000"

python cli.py web --host 0.0.0.0

echo.
echo   Sunucu durdu.
pause
