@echo off
rem Removes the scheduled sync.
schtasks /Delete /F /TN "Bloomberg sync"
pause
