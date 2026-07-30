@echo off
setlocal
cd /d "%~dp0"
set "WORLDSTATE_EXE=%~dp0apps\desktop-tauri\src-tauri\target\release\worldstate-terminal.exe"
set "WORLDSTATE_DEBUG_EXE=%~dp0apps\desktop-tauri\src-tauri\target\debug\worldstate-terminal.exe"
if exist "%WORLDSTATE_EXE%" (
  start "WorldState Terminal" "%WORLDSTATE_EXE%"
  exit /b 0
)
if exist "%WORLDSTATE_DEBUG_EXE%" (
  start "WorldState Terminal" "%WORLDSTATE_DEBUG_EXE%"
  exit /b 0
)
call "%~dp0WorldState.bat" start
exit /b %ERRORLEVEL%
