\
@echo off
REM One-click launcher for DOCSim (Windows)
REM If PowerShell execution policy blocks scripts, this bypasses it for this run.
powershell -ExecutionPolicy Bypass -File "%~dp0Run-DOCSim.ps1"
pause
