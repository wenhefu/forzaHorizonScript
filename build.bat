@echo off
setlocal
REM Build a standalone Windows .exe. Run this ON Windows.
REM Produces dist\Forza6Helper.exe and dist\README.txt for friends.
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe

%PY% -m pip install -r requirements.txt pyinstaller
%PY% -m compileall -q .
if errorlevel 1 exit /b 1
%PY% -m unittest discover -s tests
if errorlevel 1 exit /b 1

%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --collect-all vgamepad --collect-all rapidocr_onnxruntime --collect-all onnxruntime --add-data "assets;assets" --name Forza6Helper gui.py
if errorlevel 1 exit /b 1

if not exist dist mkdir dist
copy /Y release\README.txt dist\README.txt >nul
echo.
echo Done. Your EXE is at: dist\Forza6Helper.exe
echo Friend instructions copied to: dist\README.txt
pause
