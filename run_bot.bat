@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [error] Could not find .venv\Scripts\python.exe
    echo.
    echo Create the virtual environment and install dependencies first:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -e ".[dev]"
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" holoquiz_bot.py
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [error] HoloQuiz bot stopped with exit code %EXIT_CODE%.
    echo.
    pause
)

exit /b %EXIT_CODE%
