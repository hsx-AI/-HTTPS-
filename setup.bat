@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 python -m venv .venv
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" configure_sms_relay.py
if errorlevel 1 exit /b 1
if exist "nuclear-quality-dashboard\package-lock.json" (
  where npm >nul 2>&1
  if not errorlevel 1 (
    pushd nuclear-quality-dashboard
    call npm ci
    if errorlevel 1 (popd & exit /b 1)
    call npm run build
    if errorlevel 1 (popd & exit /b 1)
    popd
  )
)
echo.
echo Setup complete. Run login_atrust.bat or start_scheduler.bat.
pause
