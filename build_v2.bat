@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pyinstaller.exe" (
  ".venv\Scripts\pyinstaller.exe" --noconfirm --clean Forza6HelperV2.spec
) else (
  pyinstaller --noconfirm --clean Forza6HelperV2.spec
)

if errorlevel 1 (
  echo.
  echo V2 build failed.
  exit /b 1
)

echo.
echo V2 build finished: dist\Forza6HelperV2.exe

