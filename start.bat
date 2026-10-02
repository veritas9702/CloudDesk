@echo off
cd /d "%~dp0"
if exist "app\CloudDesk\CloudDesk.exe" (
  start "" "app\CloudDesk\CloudDesk.exe"
  exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "main.py"
  exit /b
)
echo Please run setup.bat with Python 3.11+ installed first.
pause
