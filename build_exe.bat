@echo off
REM Build VoiceToText.exe — a single file you can send to a friend.
REM Run this once on a Windows PC that has Python + the app's dependencies installed.

echo Installing build + app dependencies...
python -m pip install --upgrade pyinstaller
python -m pip install -r requirements.txt

echo.
echo Building VoiceToText.exe ...
python -m PyInstaller --noconfirm --clean VoiceToText.spec

echo.
echo ============================================================
echo  Done. Send this file to your friend:
echo     dist\VoiceToText.exe
echo  They just double-click it and paste their own OpenAI key.
echo ============================================================
pause
