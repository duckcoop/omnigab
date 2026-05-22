@echo off
title RAG Agent v2.0
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Run setup first.
    pause
    exit /b 1
)

echo.
echo   Starting RAG Agent Desktop App...
echo   (Close the window to shut down)
echo.

venv\Scripts\python.exe desktop_app.py
