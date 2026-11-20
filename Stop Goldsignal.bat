@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\local-launch.ps1" -Action stop
timeout /t 3 >nul
