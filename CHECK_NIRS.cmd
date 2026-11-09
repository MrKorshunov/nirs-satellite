@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run SETUP_NIRS.cmd first.
    pause
    exit /b 1
)
echo NIRS: Unit tests...
".venv\Scripts\python.exe" -m unittest discover -s tests -p "test_*.py" -v
if errorlevel 1 goto fail
set "TAG=%RANDOM%%RANDOM%"
echo NIRS: Basilisk integrated spacecraft smoke test...
".venv\Scripts\python.exe" -m experiments.mission_03.run --viz-mode off --duration-hours 0.2 --require-two-captures --output-name physical_check_%TAG%
if errorlevel 1 goto fail
echo NIRS: Multi-task scheduling smoke test...
".venv\Scripts\python.exe" -m experiments.mission_02.run --duration-hours 0.3 --step-s 10 --output-name planning_check_%TAG%
if errorlevel 1 goto fail
echo.
echo SUCCESS: All checks passed. Open the results folder for reports.
pause
exit /b 0
:fail
echo.
echo ERROR: At least one check failed. Copy the last error lines above.
pause
exit /b 1
