@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo.
echo ====================================================
echo NIRS satellite simulator - first-time environment
echo ====================================================
echo.
py -3.13 -c "import struct,sys; assert sys.version_info[:2] == (3,13) and struct.calcsize('P') == 8"
if errorlevel 1 (
    echo.
    echo ERROR: Python 3.13 64-bit is not available via py launcher.
    echo Install Python 3.13 x64 from https://www.python.org/downloads/
    echo and enable the Windows Python launcher, then run this file again.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    echo Creating local isolated Python environment...
    py -3.13 -m venv ".venv"
    if errorlevel 1 goto fail
)
echo Checking the existing local Python environment...
".venv\Scripts\python.exe" -c "import struct,sys; assert sys.version_info[:2] == (3,13) and struct.calcsize('P') == 8"
if errorlevel 1 (
    echo.
    echo ERROR: .venv must use 64-bit Python 3.13.
    echo Rename the existing .venv folder in Explorer, then run SETUP_NIRS.cmd again.
    pause
    exit /b 1
)
echo Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
echo Installing verified Basilisk and scenario dependencies...
".venv\Scripts\python.exe" -m pip install "bsk[all,examples]==2.12.2"
if errorlevel 1 goto fail
echo Installing WGS84 area and polygon-intersection dependencies...
".venv\Scripts\python.exe" -m pip install -r science_requirements.txt
if errorlevel 1 goto fail
echo Checking Basilisk and the graphical interface...
".venv\Scripts\python.exe" -c "import Basilisk, tkinter; print('Basilisk + Tkinter OK')"
if errorlevel 1 goto fail
echo Checking launcher command builder...
".venv\Scripts\python.exe" -m unittest discover -s tests -p "test_launcher_core.py" -v
if errorlevel 1 goto fail
echo.
echo Installation successful. Use START_NIRS.cmd from now on.
echo.
pause
exit /b 0
:fail
echo.
echo Installation failed. Check errors above, Python version, disk space and network.
pause
exit /b 1
