@echo off
rem Prayer Tracker launcher: first run sets up a portable Python inside this folder, then starts the app.
cd /d "%~dp0"
title Prayer Tracker
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\launcher.ps1"
if errorlevel 1 pause
