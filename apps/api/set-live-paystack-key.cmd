@echo off
rem Put the LIVE Paystack secret key on the live API (Vercel). Typing is hidden; nothing goes to chat or git.
rem Needs: logged in to Vercel (npx vercel@latest login).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo The API's Python environment is missing: run "python -m venv .venv" and install requirements-dev.txt first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\set_live_paystack_key.py
echo.
pause
