@echo off
rem Member B local test environment: starts the workbench at http://127.0.0.1:8765/
rem Nothing here uploads to GitHub. Keys stay in the git-ignored .env file.
setlocal
cd /d "%~dp0"
chcp 65001 >nul

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating Python environment .venv ...
  where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
  if not exist ".venv\Scripts\python.exe" (
    echo Python 3.10+ is required. Install it from https://www.python.org/downloads/ and run this again.
    pause & exit /b 1
  )
)
echo [2/4] Checking packages ...
".venv\Scripts\python.exe" -m pip install -q -r requirements-live.txt
if errorlevel 1 ( echo Package install failed. & pause & exit /b 1 )

if not exist ".env" copy /y ".env.example" ".env" >nul
".venv\Scripts\python.exe" -m modules.member_b.env_file check --env .env
if errorlevel 1 (
  echo [3/4] No OpenAI key in .env yet. Enter it now ^(saved only in the git-ignored .env^):
  ".venv\Scripts\python.exe" -m modules.member_b.env_file set --env .env
) else (
  echo [3/4] Using the OpenAI key in .env ^(run set_openai_key.bat to change it^)
)

if not exist "data\evidence_library.json" (
  echo.
  echo The evidence library is missing. Build it once, for example:
  echo   .venv\Scripts\python.exe scripts\prepare_evidence.py --brief "D:\MA6094 Capstone Brief.pdf" --pack "D:\Harbourline_Data_Pack.zip" --sponsor-answers "D:\Capstone Sponsor Answers - Round 1.pdf"
  echo The page still opens; the offline preview works without it.
  echo.
)

echo [4/4] Starting Member B at http://127.0.0.1:8765/  (close this window to stop)
start "" "http://127.0.0.1:8765/"
".venv\Scripts\python.exe" -m modules.member_b.http_api --env-file .env
pause
