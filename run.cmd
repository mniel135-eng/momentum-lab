@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" "lab.py" > "logs\last_run.log" 2>&1
