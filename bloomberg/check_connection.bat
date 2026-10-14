@echo off
rem Double-click this file to run the Bloomberg connection check. The window stays open so you can copy the result.
cd /d "%~dp0"
python check_connection.py
echo.
pause
