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
echo Two physically switched imaging targets, storage and downlink.
echo Synthetic hardware; energy-reserve gate; no physical ground receiver/ACK.
echo.
%PY% -m experiments.mission_03.run --duration-hours 0.2 --viz-mode file --viz-step-s 10 --require-two-captures --output-name %RUN_NAME%
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
