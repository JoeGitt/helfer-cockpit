@echo off
rem Helfer-Cockpit mit sichtbarer Konsole starten (zur Fehlersuche)
cd /d "%~dp0"
"%~dp0python\python.exe" "%~dp0start.py" %*
pause
