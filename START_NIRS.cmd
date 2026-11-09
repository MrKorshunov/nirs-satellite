@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo.
    echo NIRS - initial setup is required.
    echo Double-click SETUP_NIRS.cmd first.
    echo.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m nirs_satellite.launcher_gui
if errorlevel 1 (
    echo Could not start the user interface.
    pause
)
exit /b 0
