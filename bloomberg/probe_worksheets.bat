@echo off
rem PROBE: can the Bloomberg API read a Security Worksheet (W ^<GO^>) by name? Uploads NOTHING.
rem Press Enter to probe W45 Alpha, or type another worksheet's name exactly as W ^<GO^> shows it.
cd /d "%~dp0"
set "WS="
set /p WS="Worksheet to probe (Enter = W45 Alpha): "
if "%WS%"=="" (python probe_worksheets.py) else (python probe_worksheets.py "%WS%")
echo.
pause
