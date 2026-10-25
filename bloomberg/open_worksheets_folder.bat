@echo off
rem Opens the folder for your W ^<GO^> worksheet exports (it is created if it does not exist yet).
rem Save each worksheet's Excel export here; the daily sync adds names the screener does not have yet to the Inbox theme.
if not exist "%USERPROFILE%\bbg_sync\worksheets" mkdir "%USERPROFILE%\bbg_sync\worksheets"
start "" explorer "%USERPROFILE%\bbg_sync\worksheets"
