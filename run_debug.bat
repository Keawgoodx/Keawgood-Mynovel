@echo off
rem เปิดแบบมีหน้าต่างดำ เอาไว้ดู error เวลาโปรแกรมเปิดไม่ขึ้น
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Please run install.bat first.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
python "%~dp0Keawgood_Mynovel.py"
echo.
pause
endlocal
