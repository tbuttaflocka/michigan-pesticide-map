@echo off
title Michigan Pesticide Heat Map Server
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PY=venv\Scripts\python.exe"
) else (
    set "PY=py"
)

echo ============================================================
echo  Michigan Pesticide Application Heat Map
echo  Interpreter: %PY%
echo  Working dir: %CD%
echo ============================================================
echo.

if not exist "data\michigan_pesticides.sqlite" (
    echo [setup] Database not found. Running one-time data loader ^(downloads ^~250 MB^) ...
    "%PY%" -m app.data_loader
    if errorlevel 1 (
        echo.
        echo [error] Data loader failed. See messages above.
        pause
        exit /b 1
    )
)

echo [run] Starting Flask server on http://localhost:8080 ...
echo [run] Browser will open in a few seconds. Close this window to stop the server.
echo.

REM Open the browser shortly after the server starts.
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8080"

REM Run server in the foreground so the user sees logs and Ctrl+C still works.
"%PY%" app.py

echo.
echo [stopped] Server has exited.
pause
