@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0WorldState.bat" (
  echo ERROR: WorldState.bat is missing from:
  echo   %~dp0
  pause
  exit /b 1
)
call "%~dp0WorldState.bat" launch
exit /b %ERRORLEVEL%
