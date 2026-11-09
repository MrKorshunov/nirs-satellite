@echo off
setlocal
cd /d "%~dp0\..\.."
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=py -3.13"
)
set "RUN_NAME=mission02_%RANDOM%%RANDOM%"
echo Mission 02: results in results\%RUN_NAME%
%PY% -m experiments.mission_02.run --duration-hours 4 --step-s 10 --output-name %RUN_NAME%
if errorlevel 1 (
  echo Run failed. Check Python 3.13 and Basilisk 2.12.2.
) else (
  start "" "results\%RUN_NAME%\comparison.csv"
)
pause
