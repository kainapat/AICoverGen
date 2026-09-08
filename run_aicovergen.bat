@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   AICoverGen - Smart Launcher
echo   RTX 2050 4GB Optimized
============================================
echo.

:: Configuration
set "PYTHON=D:\Code\AICoverGen\.venv\Scripts\python.exe"
set "SCRIPT=src\webui.py"
set "HOST=0.0.0.0"
set "PORT=7860"
set "LOGFILE=D:\Code\AICoverGen\webui.log"

:: Step 1: Kill old processes on port
echo [1/4] Checking for old processes on port %PORT%...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
    echo   Killing PID %%a...
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

:: Step 2: Check Python
echo [2/4] Checking Python...
"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python not found at %PYTHON%
    pause
    exit /b 1
)
echo   Python OK

:: Step 3: Launch WebUI
echo [3/4] Starting WebUI on port %PORT%...
echo   Log: %LOGFILE%
echo.
echo   URL: http://127.0.0.1:%PORT%
echo   URL: http://%COMPUTERNAME%:%PORT%
echo.

:: Run with logging
"%PYTHON%" -u "%SCRIPT%" --listen --listen-host %HOST% --listen-port %PORT% > "%LOGFILE%" 2>&1 &
set "WEBUI_PID=%!"

:: Step 4: Wait and verify
echo [4/4] Waiting for WebUI to start...
set "READY=0"
for /l %%i in (1,1,15) do (
    timeout /t 1 /nobreak >nul
    "%PYTHON%" -c "import socket; s=socket.socket(); s.settimeout(1); exit(0 if s.connect_ex(('127.0.0.1',%PORT%))==0 else 1); s.close()" >nul 2>&1
    if !errorlevel! equ 0 (
        set "READY=1"
        goto :ready
    )
    echo   Waiting... %%i/15
)

:ready
if "%READY%"=="1" (
    echo.
    echo ============================================
    echo   WebUI is running!
    echo   Local:   http://127.0.0.1:%PORT%
    echo   Network: http://%COMPUTERNAME%:%PORT%
    echo.
    echo   Press Ctrl+C to stop, or close this window.
    echo ============================================
    echo.
    :: Keep window open and follow log
    echo Following log (Ctrl+C to stop):
    echo ----------------------------------------
    type "%LOGFILE%"
) else (
    echo.
    echo ============================================
    echo   ERROR: WebUI failed to start!
    echo   Check log: %LOGFILE%
    echo ============================================
    echo.
    type "%LOGFILE%"
    pause
)

endlocal
