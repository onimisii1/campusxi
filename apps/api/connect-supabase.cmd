@echo off
rem Connect CampusXI to Supabase: save and check the settings, set up the database.
rem   connect-supabase.cmd           enter / change settings
rem   connect-supabase.cmd --check   only check what's saved (add --migrate to update the tables)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo The API's Python environment is missing: run "python -m venv .venv" and install requirements-dev.txt first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\connect_supabase.py %*
echo.
pause
