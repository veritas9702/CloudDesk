@echo off
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo Setup completed. Run start.bat.
pause
exit /b
:fail
echo Setup failed. Install Python 3.11+ and check network connectivity.
pause
exit /b 1
