@echo off
rem Sets up Windows Task Scheduler to run the sync every 15 minutes while you are logged in to Windows.
rem The script itself decides whether anything is due (weekdays 07:00-21:00, slots 08:30 / 16:30 / 20:00) and
rem whether Bloomberg is logged in, so most runs finish in about a second and do nothing.
cd /d "%~dp0"
set "PYW="
for /f "delims=" %%i in ('where pythonw 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
  echo Could not find pythonw.exe. Re-run the Python installer and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
schtasks /Create /F /TN "Bloomberg sync" /SC MINUTE /MO 15 /TR "\"%PYW%\" \"%~dp0bbg_sync.py\""
if errorlevel 1 (
  echo.
  echo Windows did not allow the scheduled task. Send this window to Claude: there is another way.
) else (
  echo.
  echo Done. The sync now checks every 15 minutes. To see what it did, double-click show_log.bat.
)
pause
