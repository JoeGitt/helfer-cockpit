@echo off
rem Helfer-Cockpit ohne Konsolenfenster starten (Meldungen: %USERPROFILE%\.helfer-cockpit\cockpit.log)
start "" "%~dp0python\pythonw.exe" "%~dp0start.py"
