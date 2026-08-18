@echo off
chcp 65001 >nul
title AI Sanal Dolap
cd /d "%~dp0"

echo.
echo   AI Sanal Dolap baslatiliyor...
echo   Kapatmak icin bu pencereyi kapat ya da Ctrl+C
echo.

REM Tarayiciyi 3 saniye sonra ac (sunucu ayaga kalksin diye)
start "" /b cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000"

python cli.py web

echo.
echo   Sunucu durdu.
pause
