@echo off
setlocal
cd /d "%~dp0"
where pythonw.exe >nul 2>nul
if errorlevel 1 (
  echo Python desktop runtime was not found.
  echo Please install Python 3.12 or newer, then open this file again.
  pause
  exit /b 1
)
start "World State Terminal" /D "%~dp0" pythonw.exe "%~dp0scripts\worldstate_desktop.py"
exit /b 0
