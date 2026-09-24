@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title NovaTech Project Launcher

echo.
echo =====================================================
echo   NovaTech Recruitment Platform - Automatic Setup
echo =====================================================
echo.

where node.exe >nul 2>nul || goto :node_missing
where npm.cmd >nul 2>nul || goto :node_missing
node.exe -e "const [major,minor]=process.versions.node.split('.').map(Number);process.exit(major>22||(major===22&&minor>=12)?0:1)" >nul 2>nul || goto :node_old

set "PYTHON_CMD="
where py.exe >nul 2>nul && py -3.12 -c "import sys" >nul 2>nul && set "PYTHON_CMD=py -3.12"
if not defined PYTHON_CMD where python.exe >nul 2>nul && set "PYTHON_CMD=python"
if not defined PYTHON_CMD goto :python_missing

if not exist ".env" (
  copy /Y ".env.example" ".env" >nul
  echo [SETUP] Created .env from .env.example.
  echo [ACTION REQUIRED] Complete .env, then run start.bat again.
  start "NovaTech Environment" notepad.exe "%~dp0.env"
  pause
  exit /b 1
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo [SETUP] Creating Python virtual environment...
  call %PYTHON_CMD% -m venv "%~dp0backend\.venv"
  if errorlevel 1 goto :failed
)

echo [SETUP] Checking backend dependencies...
call "%~dp0backend\.venv\Scripts\python.exe" -c "import fastapi,uvicorn,httpx,pydantic_settings,jwt,fitz,docx,reportlab,multipart,tzdata" >nul 2>nul
if errorlevel 1 (
  echo [SETUP] Installing missing backend dependencies...
  call "%~dp0backend\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "%~dp0backend\requirements.txt"
  if errorlevel 1 goto :failed
) else (
  echo [SETUP] Backend dependencies are already installed.
)

echo [SETUP] Synchronizing frontend dependencies...
pushd "%~dp0frontend"
call npm.cmd install
if errorlevel 1 (
  popd
  goto :failed
)
popd

echo.
echo [START] FastAPI backend: http://localhost:8000
start "NovaTech Backend" /D "%~dp0backend" cmd.exe /k "".venv\Scripts\python.exe" main.py"

echo [START] Next.js frontend: http://localhost:3000
start "NovaTech Frontend" /D "%~dp0frontend" cmd.exe /k "set NOVATECH_SKIP_BROWSER=1&& npm.cmd run dev"

echo [START] Waiting for the website, then opening your default browser...
start "NovaTech Browser Launcher" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open-browser.ps1" -Url "http://localhost:3000" -TimeoutSeconds 180

echo.
echo =====================================================
echo   Startup commands launched successfully
echo   Website:    http://localhost:3000
echo   API health: http://localhost:8000/health
echo   API docs:   http://localhost:8000/api/docs
echo =====================================================
echo.
echo Keep the Backend and Frontend terminal windows open.
echo This launcher can now be closed.
pause
exit /b 0

:node_missing
echo [ERROR] Node.js/npm was not found.
echo Install Node.js 22.12 or newer, restart VS Code, and run start.bat again.
pause
exit /b 1

:node_old
echo [ERROR] This project requires Node.js 22.12 or newer.
echo Upgrade Node.js, restart VS Code, and run start.bat again.
pause
exit /b 1

:python_missing
echo [ERROR] Python 3 was not found.
echo Install Python 3.12 and enable Add Python to PATH.
pause
exit /b 1

:failed
echo.
echo [ERROR] Setup failed. Read the error shown above.
pause
exit /b 1
