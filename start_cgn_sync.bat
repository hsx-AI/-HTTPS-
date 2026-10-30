@echo off
cd /d "%~dp0"
if not exist "%CD%\.venv\Scripts\python.exe" (
  echo Please run setup.bat first.
  pause
  exit /b 1
)
"%CD%\.venv\Scripts\python.exe" "%~dp0cgn_sync.py" %*
exit /b %ERRORLEVEL%
