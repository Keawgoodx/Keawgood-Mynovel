@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Keawgood_Mynovel - Build ^& Release
if not exist ".venv\Scripts\python.exe" (
    echo ไม่พบ .venv — กรุณาดับเบิลคลิก install.bat ก่อน
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
python release.py --publish %*
echo.
pause
endlocal
