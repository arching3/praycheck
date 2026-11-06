@echo off
setlocal
rem run from the project root (this file lives in scripts\)
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" goto run

echo [setup] Creating virtual environment .venv ...
py -3 -m venv .venv
if errorlevel 1 python -m venv .venv
if not exist ".venv\Scripts\python.exe" goto nopython

:run
if "%~1"=="" (
    ".venv\Scripts\python.exe" scripts\split_chat_by_date.py
) else (
    ".venv\Scripts\python.exe" scripts\split_chat_by_date.py "%~1"
)
if errorlevel 1 goto parsefail
echo Date parsing completed.
goto end

:nopython
echo [error] Python 3 not found. Install Python and retry.
goto end

:parsefail
echo [error] Failed to split the chat file. Check that private\전체기간대화내용.txt exists and is readable.

:end
pause
