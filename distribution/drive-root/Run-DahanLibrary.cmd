@echo off
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0DahanPhotoLibraryData\production\Start-DahanLibrary.ps1" %*
exit /b %ERRORLEVEL%
