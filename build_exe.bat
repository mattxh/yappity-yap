@echo off
REM Build "Yappity Yapp.exe" — a single file you can send to a friend.
REM Run this once on a Windows PC that has Python + the app's dependencies installed.

echo Installing build + app dependencies...
python -m pip install --upgrade pyinstaller
python -m pip install -r requirements.txt

echo.
echo Generating the duck icon...
python -c "from app.startup import make_icon_file; make_icon_file()"

echo.
echo Building Yappity Yapp.exe ...
python -m PyInstaller --noconfirm --clean YappityYapp.spec

echo.
echo ============================================================
echo  Done. Send this file to your friend:
echo     dist\Yappity Yapp.exe
echo  They just double-click it and paste their own OpenAI key.
echo ============================================================
pause
