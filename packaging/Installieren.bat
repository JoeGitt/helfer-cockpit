@echo off
rem Doppelklick: lädt die neueste Version von GitHub und richtet das Helfer-Cockpit ein (ohne Admin-Rechte)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
pause
