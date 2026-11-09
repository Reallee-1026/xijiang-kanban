@echo off
chcp 65001 >nul
cd /d E:\AILearn\ship
set "PY=C:\Users\23166\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" serve.py 8123
pause
