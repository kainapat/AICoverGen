@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: ─── Enable ANSI colors (Windows 10+) ───
for /f "tokens=4-5 delims=. " %%i in ('ver') do set VERSION=%%i.%%j
if "%VERSION%"=="10.0" (
    reg add HKCU\Console /v VirtualTerminalLevel /t REG_DWORD /d 1 /f >nul 2>&1
)

:: ─── Colors ───
set "C_RESET=[0m"
set "C_CYAN=[96m"
set "C_GREEN=[92m"
set "C_YELLOW=[93m"
set "C_RED=[91m"
set "C_GRAY=[90m"
set "C_BOLD=[1m"

:: ─── Banner ───
echo.
echo %C_CYAN%╔══════════════════════════════════════════════════════════════╗%C_RESET%
echo %C_CYAN%║%C_RESET%                                                              %C_CYAN%║%C_RESET%
echo %C_CYAN%║%C_RESET%     %C_BOLD%%C_CYAN%  /\
echo %C_CYAN%║%C_RESET%    %C_BOLD%%C_CYAN% /  \     %C_RESET%AI %C_CYAN%COVER %C_RESET%GEN%R
echo %C_CYAN%║%C_RESET%   %C_BOLD%%C_CYAN% /    \    %C_RESET%WebUI %C_CYAN%Smart Launcher%C_RESET%
echo %C_CYAN%║%C_RESET%  %C_BOLD%%C_CYAN% /      \   %C_RESET%RTX 2050 4GB Optimized%C_CYAN%║%C_RESET%
echo %C_CYAN%║%C_RESET%                                                              %C_CYAN%║%C_RESET%
echo %C_CYAN%╚══════════════════════════════════════════════════════════════╝%C_RESET%
echo.

:: ─── Config ───
set "PYTHON=D:\Code\AICoverGen\.venv\Scripts\python.exe"
set "SCRIPT=src\webui.py"
set "HOST=0.0.0.0"
set "PORT=7860"
set "LOGFILE=D:\Code\AICoverGen\webui.log"

:: ══════════════════════════════════════════
::  STEP 1: Kill old processes
:: ══════════════════════════════════════════
echo  %C_CYAN%[1/4]%C_RESET% %C_BOLD%Checking for old processes...%C_RESET%
set "FOUND="
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
    if not defined FOUND (
        set "FOUND=1"
        echo    %C_YELLOW%Found process on port %PORT%: PID %%a%C_RESET%
        taskkill /F /PID %%a >nul 2>&1
        echo    %C_GREEN%Terminated%C_RESET%
    )
)
if not defined FOUND echo    %C_GRAY%No old processes found%C_RESET%
timeout /t 1 /nobreak >nul
echo.

:: ══════════════════════════════════════════
::  STEP 2: Check Python
:: ══════════════════════════════════════════
echo  %C_CYAN%[2/4]%C_RESET% %C_BOLD%Checking Python...%C_RESET%
"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo    %C_RED%Python not found at %PYTHON%%C_RESET%
    echo    %C_GRAY%Please reinstall Python 3.10.11%C_RESET%
    pause
    exit /b 1
)
for /f "delims=" %%v in ('"%PYTHON%" --version 2^>^&1') do set "PYVER=%%v"
echo    %C_GREEN%%PYVER% %C_GRAY%(%PYTHON%)%C_RESET%
echo.

:: ══════════════════════════════════════════
::  STEP 3: Launch WebUI
:: ══════════════════════════════════════════
echo  %C_CYAN%[3/4]%C_RESET% %C_BOLD%Starting WebUI...%C_RESET%
echo    %C_GRAY%Port: %PORT%%C_RESET%
echo    %C_GRAY%Log:  %LOGFILE%%C_RESET%

"%PYTHON%" -u "%SCRIPT%" --listen --listen-host %HOST% --listen-port %PORT% > "%LOGFILE%" 2>&1 &
set "WEBUI_PID=%!"
echo    %C_GREEN%Process started (PID: %WEBUI_PID%)%C_RESET%
echo.

:: ══════════════════════════════════════════
::  STEP 4: Wait and verify
:: ══════════════════════════════════════════
echo  %C_CYAN%[4/4]%C_RESET% %C_BOLD%Waiting for WebUI to start...%C_RESET%
set "READY=0"
for /l %%i in (1,1,15) do (
    timeout /t 1 /nobreak >nul
    "%PYTHON%" -c "import socket; s=socket.socket(); s.settimeout(1); exit(0 if s.connect_ex(('127.0.0.1',%PORT%))==0 else 1); s.close()" >nul 2>&1
    if !errorlevel! equ 0 (
        set "READY=1"
        goto :ready
    )
    <nul set /p "=    %C_GRAY%Connecting... %%i/15%C_RESET%"
    echo.
)

:ready
echo.
if "%READY%"=="1" (
    echo %C_GREEN%╔══════════════════════════════════════════════════════════════╗%C_RESET%
    echo %C_GREEN%║%C_RESET%                                                              %C_GREEN%║%C_RESET%
    echo %C_GREEN%║%C_RESET%   %C_BOLD%%C_GREEN%  WebUI is running!%C_RESET%                                     %C_GREEN%║%C_RESET%
    echo %C_GREEN%║%C_RESET%                                                              %C_GREEN%║%C_RESET%
    echo %C_GREEN%║%C_RESET%   %C_CYAN%Local:   %C_RESET%http://127.0.0.1:%PORT%                            %C_GREEN%║%C_RESET%
    echo %C_GREEN%║%C_RESET%   %C_CYAN%Network: %C_RESET%http://%COMPUTERNAME%:%PORT%                     %C_GREEN%║%C_RESET%
    echo %C_GREEN%║%C_RESET%                                                              %C_GREEN%║%C_RESET%
    echo %C_GREEN%║%C_RESET%   %C_GRAY%Press Ctrl+C to stop, or close this window.%C_RESET%              %C_GREEN%║%C_RESET%
    echo %C_GREEN%║%C_RESET%                                                              %C_GREEN%║%C_RESET%
    echo %C_GREEN%╚══════════════════════════════════════════════════════════════╝%C_RESET%
    echo.
    echo %C_CYAN%  Open in browser:%C_RESET%
    echo    ^> http://127.0.0.1:%PORT%
    echo.
    echo %C_CYAN%  First time?%C_RESET%
    echo    1. Go to %C_BOLD%"Download model"%C_RESET% tab
    echo    2. Choose a voice model from Public Models
    echo    3. Go to %C_BOLD%"Generate"%C_RESET% tab
    echo    4. Enter YouTube URL or local audio file
    echo    5. Set Pitch and click Generate!
    echo.
    echo %C_GRAY%  ──────────────────────────────────────────────────────────%C_RESET%
    echo.
) else (
    echo %C_RED%╔══════════════════════════════════════════════════════════════╗%C_RESET%
    echo %C_RED%║%C_RESET%   %C_BOLD%%C_RED%  ERROR: WebUI failed to start!%C_RESET%                            %C_RED%║%C_RESET%
    echo %C_RED%║%C_RESET%                                                              %C_RED%║%C_RESET%
    echo %C_RED%║%C_RESET%   %C_GRAY%Check log: %LOGFILE%%C_RESET%                     %C_RED%║%C_RESET%
    echo %C_RED%╚══════════════════════════════════════════════════════════════╝%C_RESET%
    echo.
    echo %C_YELLOW%  Last 5 lines of log:%C_RESET%
    echo %C_GRAY%  ──────────────────────────────────────────────────────────%C_RESET%
    powershell -command "Get-Content '%LOGFILE%' -Tail 5 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host '  ' $_ }"
    echo.
    pause
)

endlocal
