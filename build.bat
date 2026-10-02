@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe tools\generate_extension.py
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --workpath .build --distpath app CloudDesk.spec
if errorlevel 1 exit /b 1
echo Build completed: app\CloudDesk\CloudDesk.exe
