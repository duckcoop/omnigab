@echo off
setlocal
title Local RAG Agent
cd /d "%~dp0"

:: Quick sanity checks
if not exist "venv\Scripts\activate.bat" (
    echo Virtual environment not found. Running full setup...
    call "%~dp0setup.bat" %*
    exit /b
)

if not exist "models\qwen2.5-1.5b-instruct-q4_k_m.gguf" (
    echo Model not found. Running full setup...
    call "%~dp0setup.bat" %*
    exit /b
)

:: Activate venv and launch
call venv\Scripts\activate.bat

if "%1"=="--terminal" (
    echo Starting terminal chat...
    echo.
    python "%~dp0src\demo_ui.py"
) else (
    echo Starting web UI at http://localhost:8000 ...
    echo.
    start "" http://localhost:8000
    python "%~dp0src\web_app.py"
)

pause
