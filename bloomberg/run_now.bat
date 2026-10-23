@echo off
rem Bespoke run: fetch analyst consensus for EVERY theme stock now and upload it (ignores the weekly schedule).
rem Optionally type extra tickers; ones not in any theme yet are added to the Inbox theme.
cd /d "%~dp0"
echo Extra tickers to include, e.g.  NVDA, 2330 TT, 0700 HK
echo (leave empty and press Enter for the theme stocks only)
set "TICKERS="
set /p "TICKERS=Tickers: "
python bbg_sync.py --now %TICKERS%
echo.
pause
