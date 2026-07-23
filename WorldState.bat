@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\worldstate.ps1" %*
set "WORLDSTATE_EXIT=%ERRORLEVEL%"
if not "%WORLDSTATE_EXIT%"=="0" (
  echo.
  echo World State Terminal encountered an error.
  pause
)
exit /b %WORLDSTATE_EXIT%
