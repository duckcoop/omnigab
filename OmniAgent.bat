@echo off
title OmniAgent
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

echo.
echo   Starting OmniAgent Desktop...
echo   (Close the window to shut down)
echo.

venv\Scripts\python.exe desktop_app.py
