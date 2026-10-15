@echo off
rem TEST: fetches everything from Bloomberg now and saves the files in a folder on your Desktop. Uploads NOTHING.
cd /d "%~dp0"
python bbg_sync.py --test
echo.
pause
