@echo off
REM Bootstrap the Michigan Pesticide Heat Map on Windows.
setlocal enabledelayedexpansion
cd /d "%~dp0"

where py >nul 2>&1 && set "PY=py -3"
if "%PY%"=="" where python >nul 2>&1 && set "PY=python"
if "%PY%"=="" (
  echo [setup] Python not found. Install Python 3.10+ and re-run.
  exit /b 1
)

echo [setup] Using interpreter:
%PY% --version

if not exist ".venv" (
  echo [setup] Creating virtual environment .venv ...
  %PY% -m venv .venv
)

set "VENV_PY=.venv\Scripts\python.exe"

echo [setup] Installing Python dependencies ...
"%VENV_PY%" -m pip install --quiet --upgrade pip
"%VENV_PY%" -m pip install --quiet -r requirements.txt

echo [setup] Downloading and ingesting real datasets ...
"%VENV_PY%" -m app.data_loader

echo [setup] Generating app icon ...
"%VENV_PY%" scripts\make_icon.py

echo [setup] Creating desktop shortcut ...
"%VENV_PY%" create_shortcut.py

echo.
echo ============================================================
echo  Setup complete. Double-click "Michigan Pesticide Map" on
echo  your desktop to launch the app at any time.
echo ============================================================
echo.

echo [setup] Starting server on http://127.0.0.1:8080 ...
"%VENV_PY%" app.py
