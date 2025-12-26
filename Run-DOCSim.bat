@echo off
setlocal
cd /d "%~dp0"

echo === DOCSim Launcher (Windows) ===
echo.

REM Prefer Windows Python launcher "py", fallback to "python"
set "PYCMD="
where py >nul 2>nul && set "PYCMD=py"
if not defined PYCMD (
  where python >nul 2>nul && set "PYCMD=python"
)

if not defined PYCMD (
  echo Python was not found.
  echo Install Python 3.9+ and check "Add Python to PATH" during install.
  echo.
  pause
  exit /b 1
)

%PYCMD% main.py

echo.
pause
