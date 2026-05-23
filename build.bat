@echo off
REM Build a standalone Windows .exe. Run this ON Windows (Python required).
REM Produces dist\Forza6Helper.exe which you can share with friends.
pip install pyinstaller vgamepad
pyinstaller --onefile --windowed --name Forza6Helper gui.py
echo.
echo Done. Your EXE is at: dist\Forza6Helper.exe
pause
