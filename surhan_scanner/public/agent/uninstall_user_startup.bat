@echo off
set "TARGET=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\SurhanScannerAgent.bat"
if exist "%TARGET%" del "%TARGET%"
echo Surhan Scanner Agent startup entry has been removed.
pause
