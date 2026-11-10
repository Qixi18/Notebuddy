@echo off
setlocal EnableExtensions
title NoteBuddy - Local Web

pushd "%~dp0" || exit /b 1
set "NOTEBUDDY_EXIT=1"
set "NOTEBUDDY_PWSH=pwsh.exe"
where.exe pwsh.exe >nul 2>&1
if not errorlevel 1 goto run
set "NOTEBUDDY_PWSH=%ProgramFiles%\PowerShell\7\pwsh.exe"
if exist "%NOTEBUDDY_PWSH%" goto run
echo [ERROR] PowerShell 7 is required. Install it and try again.
goto finish

:run
if not exist "scripts\dev.ps1" (
    echo [ERROR] Keep this file in the NoteBuddy project root.
    goto finish
)
echo NoteBuddy local web: http://localhost:5173
echo Keep this window open while using NoteBuddy. Press Ctrl+C to stop.
echo.
"%NOTEBUDDY_PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev.ps1" %*
set "NOTEBUDDY_EXIT=%ERRORLEVEL%"

:finish
if not "%NOTEBUDDY_EXIT%"=="0" (
    echo.
    echo [ERROR] NoteBuddy could not start. See the error above.
    echo If port 8000 or 5173 is already in use by NoteBuddy, run:
    echo   start-notebuddy.bat -Restart
    echo For missing dependencies, run scripts\setup.ps1 in PowerShell 7.
)
popd
if "%~1"=="" pause
exit /b %NOTEBUDDY_EXIT%
