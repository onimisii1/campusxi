@echo off
rem Run CampusXI's background jobs on Vercel via Supabase Cron.
rem   schedule-jobs.cmd https://<api address>   set up / update
rem   schedule-jobs.cmd --status                what's scheduled and the last calls
rem   schedule-jobs.cmd --test                  call one job now
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo The API's Python environment is missing: run "python -m venv .venv" and install requirements-dev.txt first.
  pause
  exit /b 1
)
if "%~1"=="" (
  set /p APIURL="API address (e.g. https://campusxi-api.vercel.app): "
  call ".venv\Scripts\python.exe" scripts\schedule_jobs.py %%APIURL%%
) else (
  ".venv\Scripts\python.exe" scripts\schedule_jobs.py %*
)
echo.
pause
