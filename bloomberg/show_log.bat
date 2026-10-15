@echo off
rem Opens the sync diary: one entry each time it fetched data or found Bloomberg logged out.
if exist "%LOCALAPPDATA%\bbg_sync\sync.log" (notepad "%LOCALAPPDATA%\bbg_sync\sync.log") else (echo Nothing has run yet. & pause)
