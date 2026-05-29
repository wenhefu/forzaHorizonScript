@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Create the virtual environment first.
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements_vision.txt
".venv\Scripts\python.exe" -m pip install pyinstaller vgamepad
".venv\Scripts\python.exe" -m compileall -q v2 v3 v4 v4_launcher.py
".venv\Scripts\pyinstaller.exe" --clean --noconfirm Forza6HelperV4.spec

if exist README_V4.md copy /Y README_V4.md dist\README_V4.txt >nul
if exist README_VISION.md copy /Y README_VISION.md dist\README_VISION.txt >nul

echo.
echo V4 build complete: dist\Forza6HelperV4.exe

