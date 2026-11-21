@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\local-launch.ps1" -Action start
if errorlevel 1 pause
