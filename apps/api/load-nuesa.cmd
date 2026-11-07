@echo off
rem Load the NUESA tournament from the data folder into the database in apps\api\.env.
rem Run after: connect-supabase.cmd --check --migrate, bootstrap.py add-school, bootstrap.py make-admin.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo The API's Python environment is missing: run "python -m venv .venv" and install requirements-dev.txt first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\load_nuesa.py %*
echo.
pause
