@echo off
cd /d "%~dp0"
title AICoverGen — Neural Voice Engine
set PYTHONIOENCODING=utf-8
chcp 65001 >nul 2>&1
set HF_HOME=D:\AI_Cache\huggingface
set TORCH_HOME=D:\AI_Cache\torch
set PIP_CACHE_DIR=D:\AI_Cache\pip
set UV_CACHE_DIR=D:\AI_Cache\uv
.\.venv\Scripts\python.exe launch.py
pause
