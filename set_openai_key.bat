@echo off
rem Save your OpenAI key and model into the local, git-ignored .env (paste with Ctrl+V; the screen is cleared afterwards).
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
  echo Run start_member_b.bat once first, so the Python environment exists.
  pause & exit /b 1
)
".venv\Scripts\python.exe" -m modules.member_b.env_file set --env .env
echo.
echo If Member B is already running, just refresh the page: the new key is picked up automatically.
pause
