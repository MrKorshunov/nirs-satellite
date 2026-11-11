@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
echo ======================================================
echo Mission05: short 3-scenario retest after Windows crash
echo ======================================================
echo.
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv is missing. Run SETUP_NIRS.cmd in this same folder.
    pause
    exit /b 1
)
echo Step 1: geometry and scheduling unit tests...
".venv\Scripts\python.exe" -m unittest tests.test_mission05_science tests.test_mission04_swath -v
if errorlevel 1 goto fail
echo.
echo Step 2: real Basilisk reference, exact repeat and low-speed wheels...
echo If a native crash occurs, a Python faulthandler traceback will be
echo saved in results\mission05_acceptance_*\reference.log or slow_wheels.log
".venv\Scripts\python.exe" -X faulthandler -m experiments.mission_03.acceptance --cases reference repeat_reference slow_wheels
if errorlevel 1 goto fail
echo.
echo SUCCESS: 3 focused physical scenarios passed.
echo NOW run CHECK_RESEARCH_READY.cmd for all 16 scenarios.
pause
exit /b 0
:fail
echo.
echo TEST FAILED. Do not change original spacecraft parameters.
echo Attach the latest results\mission05_acceptance_*\acceptance_summary.json
echo and reference.log or slow_wheels.log in the same directory.
pause
exit /b 1
