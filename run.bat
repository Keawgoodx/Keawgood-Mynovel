@echo off
rem เปิด Keawgood_Mynovel แบบไม่มีหน้าต่างดำ (ถ้าโปรแกรมพัง ดู logs\crash.log หรือเปิด run_debug.bat)
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Virtual environment not found. Please run install.bat first.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0Keawgood_Mynovel.py"
endlocal
exit
