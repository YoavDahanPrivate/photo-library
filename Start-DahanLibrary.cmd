@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-DahanLibrary.ps1"
if errorlevel 1 echo Startup did not pass all checks. Read the error above.
pause
