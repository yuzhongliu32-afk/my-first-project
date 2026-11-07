@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
echo 1. Rehearsal ^(no API keys^)
echo 2. Live team sandbox
set "mode=1"
set /p "mode=Choose 1 or 2 [1]: "
set "requirements=requirements.txt"
set "options="
if "%mode%"=="2" (
    set "requirements=requirements-live.txt"
    set "options=--live"
) else if not "%mode%"=="1" goto failed
set "python=py -3"
where py >nul 2>&1
if errorlevel 1 set "python=python"
%python% -c "import sys; sys.exit(sys.version_info < (3, 11))"
if errorlevel 1 (
    echo Install Python 3.11 or newer, then reopen this launcher.
    goto failed
)
if not exist ".venv\Scripts\python.exe" (
    %python% -m venv .venv
    if errorlevel 1 goto failed
)
if "%mode%"=="2" (
    ".venv\Scripts\python.exe" -c "import jsonschema, pypdf, openai, dotenv"
) else (
    ".venv\Scripts\python.exe" -c "import jsonschema, pypdf"
)
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r "%requirements%"
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m harbourline.console %options%
if errorlevel 1 goto failed
exit /b 0

:failed
echo Startup failed. See START-HERE.md.
pause
exit /b 1
