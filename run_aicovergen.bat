@echo off
cd /d "%~dp0"
title AICoverGen Launcher
set HF_HOME=D:\AI_Cache\huggingface
set TORCH_HOME=D:\AI_Cache\torch
set PIP_CACHE_DIR=D:\AI_Cache\pip
.\.venv\Scripts\python.exe launch.py

