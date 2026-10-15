@echo off
rem Fetch everything from Bloomberg now and upload it (ignores the time slots). Use after a successful test.
cd /d "%~dp0"
python bbg_sync.py --now
echo.
pause
