@echo off
cd /d "%~dp0"
set "PY=C:\Users\23166\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" build_all.py
if errorlevel 1 (
  echo.
  echo [!] Failed. See message above.
)
pause
