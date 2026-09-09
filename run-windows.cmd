@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" %*
set "GAME_ASSIST_EXIT=%ERRORLEVEL%"
if not "%GAME_ASSIST_EXIT%"=="0" (
  echo.
  echo Game Assist stopped with exit code %GAME_ASSIST_EXIT%.
  pause
)
exit /b %GAME_ASSIST_EXIT%
