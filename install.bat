@echo off
REM First-time setup for the GitHub download: installs dependencies, then starts the app.
REM (Needs Python 3.12+ installed from python.org with "Add Python to PATH" ticked.)
cd /d "%~dp0"

echo Installing dependencies (one time)...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Could not install dependencies. Make sure Python is installed and on PATH:
    echo   https://www.python.org/downloads/
    pause
    exit /b 1
)

echo.
echo Starting Yappity Yapp... it will ask for your OpenAI API key on first run.
start "" pythonw -m app
echo Done. Look for the microphone icon in your system tray. You can close this window.
pause
