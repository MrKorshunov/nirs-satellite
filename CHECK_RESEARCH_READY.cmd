@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
    echo Run SETUP_NIRS.cmd before scientific acceptance.
    pause
    exit /b 1
)
echo ============================================================
echo NIRS Mission05: UTC, WGS84 and schedule independent tests
echo ============================================================
".venv\Scripts\python.exe" -m unittest tests.test_mission05_science tests.test_mission04_swath -v
if errorlevel 1 goto fail
echo.
echo Running physical Basilisk acceptance: multiple normal/failed scenarios...
".venv\Scripts\python.exe" -m experiments.mission_03.acceptance --viz
if errorlevel 1 goto fail
echo.
echo SUCCESS: UTC, schedule, WGS84 coverage and physical acceptance PASSED.
echo Open results\mission05_acceptance_*\acceptance_summary.json
pause
exit /b 0
:fail
echo.
echo FAILED: DO NOT consider Mission05 ready. Inspect result logs and fix the errors.
pause
exit /b 1
