@echo off
setlocal
cd /d %~dp0
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET=%STARTUP%\SurhanScannerAgent.bat"
echo @echo off> "%TARGET%"
echo cd /d "%~dp0">> "%TARGET%"
echo start "" /min "%~dp0SurhanScannerAgent.exe">> "%TARGET%"
echo Surhan Scanner Agent has been added to Windows startup for this user.
echo Startup file: %TARGET%
pause
