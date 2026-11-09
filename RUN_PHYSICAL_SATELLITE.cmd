@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=py -3.13"
)
set "RUN_NAME=satellite_full_%RANDOM%%RANDOM%"
echo.
echo NIRS: BASILISK PHYSICAL SINGLE SPACECRAFT DIAGNOSTIC
echo Real Basilisk reaction wheels + solar panel + eclipse + battery.
echo One synthetic image product, storage and downlink.
echo Synthetic hardware; no battery shutdown or ground receiver/ACK.
echo.
%PY% -m experiments.mission_01.run_mission --actuator rw --power --viz-mode file --viz-step-s 10 --output-name %RUN_NAME%
if errorlevel 1 (
  echo.
  echo ERROR: physical Basilisk scenario failed. Review logs.
) else (
  echo.
  echo RESULTS: results\%RUN_NAME%
  echo VIZARD PLAYBACK: %LOCALAPPDATA%\NIRS_Satellite\viz\%RUN_NAME%.bin
  start "" "results\%RUN_NAME%"
)
pause
