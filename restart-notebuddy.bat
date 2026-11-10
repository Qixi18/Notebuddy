@echo off
call "%~dp0start-notebuddy.bat" -Restart %*
set "NOTEBUDDY_RESTART_EXIT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %NOTEBUDDY_RESTART_EXIT%
