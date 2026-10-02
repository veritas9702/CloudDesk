@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -File "%~dp0tools\clean_legacy.ps1"
if errorlevel 1 (
  echo Cleanup did not complete. See the error above.
  pause
  exit /b 1
)
pause
