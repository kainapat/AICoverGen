@echo off
cd /d "%~dp0"
title AICoverGen
echo.
echo   AI Cover Gen - Starting...
echo   ---------------------------
echo.
.\.venv\Scripts\python.exe src\webui.py --listen --listen-port 7860
echo.
echo   WebUI stopped.
timeout /t 3 /nobreak >nul

