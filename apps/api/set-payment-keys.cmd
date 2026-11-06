@echo off
rem Add or check the CampusXI payment keys. Double-click this file, or run it from any terminal.
rem   set-payment-keys.cmd           add / change keys (input is hidden)
rem   set-payment-keys.cmd --check   only check the keys already saved
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo The API's Python environment is missing: run "python -m venv .venv" and install requirements-dev.txt first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\set_payment_keys.py %*
echo.
pause
