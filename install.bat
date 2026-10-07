@echo off
setlocal
set SCRIPT_DIR=%~dp0
if not exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    echo [1/3] Creating virtual environment...
    py -3 -m venv "%SCRIPT_DIR%.venv"
    if errorlevel 1 goto :fail
)

echo [2/3] Installing requirements...
call "%SCRIPT_DIR%.venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r "%SCRIPT_DIR%requirements.txt"
if errorlevel 1 goto :fail

echo [3/3] Installation complete. Run run.bat to start Keawgood_Mynovel.
goto :end

:fail
echo Installation failed.
pause
exit /b 1

:end
endlocal
