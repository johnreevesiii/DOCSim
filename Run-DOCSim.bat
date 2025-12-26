@echo off
setlocal
cd /d "%~dp0"

echo === DOCSim Launcher (Windows) ===
echo.

REM Find Python (prefer the Windows "py" launcher, then "python")
set "PYCMD="
where py >nul 2>nul && set "PYCMD=py"
if not defined PYCMD (
  where python >nul 2>nul && set "PYCMD=python"
)

if not defined PYCMD (
  echo Python was not found.
  echo Install Python 3.9+ and be sure to check "Add Python to PATH" during install.
  echo.
  pause
  exit /b 1
)

REM Entry point detection (supports either repo layout)
if exist "docsim\main.py" (
  %PYCMD% -m docsim.main %*
) else if exist "main.py" (
  %PYCMD% main.py %*
) else (
  echo Could not find a runnable entry point.
  echo Expected either docsim\main.py or main.py in this folder.
  echo.
  pause
  exit /b 1
)

echo.
pause
