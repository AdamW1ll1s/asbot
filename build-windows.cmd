@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build.ps1" %*
set "GAME_ASSIST_EXIT=%ERRORLEVEL%"
echo.
if "%GAME_ASSIST_EXIT%"=="0" (
  echo Build complete: dist\GameAssist-Windows.zip
) else (
  echo Build failed with exit code %GAME_ASSIST_EXIT%.
)
pause
exit /b %GAME_ASSIST_EXIT%
