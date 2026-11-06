@echo off
rem Test, bump version and build the distribution zip (only when shipped files changed).
rem Add --force to rebuild even without changes.
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\release.py %*
pause
