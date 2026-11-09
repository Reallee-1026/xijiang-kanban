@echo off
chcp 65001 >nul
cd /d E:\AILearn\ship
"C:\Users\23166\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" update_data.py >> run.log 2>&1
