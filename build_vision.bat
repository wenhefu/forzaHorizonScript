@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Create the virtual environment first.
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
".venv\Scripts\python.exe" -m pip install onnxruntime opencv-python PyYAML onnx
".venv\Scripts\python.exe" -m compileall -q vision_launcher.py v3 benchmarks
".venv\Scripts\pyinstaller.exe" --clean --noconfirm Forza6HelperVision.spec

if exist README_VISION.md copy /Y README_VISION.md dist\README_VISION.txt >nul

echo.
echo Vision build complete: dist\Forza6HelperVision.exe
