@echo off
title MockMaster Launcher

echo ==========================================
echo        MockMaster Setup + Run
echo ==========================================
echo.

REM Go to script directory
cd /d %~dp0

REM Create venv if not exists
if not exist ".venv" (
    echo Creating virtual environment...
    py -m venv .venv
)

REM Activate venv
call .venv\Scripts\activate

REM Upgrade pip
python -m pip install --upgrade pip

REM Install requirements
if exist requirements.txt (
    echo Installing requirements...
    pip install -r requirements.txt
) else (
    echo requirements.txt not found!
    pause
    exit /b
)

REM Run FastAPI app
echo.
echo Starting server...
echo.

uvicorn backend.main:app --reload

pause