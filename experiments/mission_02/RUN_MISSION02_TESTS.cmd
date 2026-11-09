@echo off
setlocal
cd /d "%~dp0\..\.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m unittest tests.test_mission02_model -v
) else (
  py -3.13 -m unittest tests.test_mission02_model -v
)
pause
