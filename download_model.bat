@echo off
setlocal enabledelayedexpansion
title Local RAG Agent - Model Downloader
cd /d "%~dp0"

set "MODELS_DIR=%~dp0models"
if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"

echo.
echo  Local RAG Agent - Model Downloader
echo  ===================================
echo.
echo  Available models:
echo.
echo    1) Qwen 2.5 1.5B  (~1.1 GB download, ~4 GB RAM)   - Fast, basic quality
echo    2) Qwen 2.5 3B    (~2.1 GB download, ~6 GB RAM)   - Good balance
echo    3) Qwen 2.5 7B    (~4.4 GB download, ~10 GB RAM)  - Great quality
echo    4) Qwen 2.5 14B   (~8.9 GB download, ~16 GB RAM)  - Best quality
echo.

set /p "CHOICE=Pick a model (1-4): "

if "%CHOICE%"=="1" (
    set "REPO=Qwen/Qwen2.5-1.5B-Instruct-GGUF"
    set "FILE=qwen2.5-1.5b-instruct-q4_k_m.gguf"
    set "LABEL=Qwen 2.5 1.5B"
) else if "%CHOICE%"=="2" (
    set "REPO=Qwen/Qwen2.5-3B-Instruct-GGUF"
    set "FILE=qwen2.5-3b-instruct-q4_k_m.gguf"
    set "LABEL=Qwen 2.5 3B"
) else if "%CHOICE%"=="3" (
    set "REPO=Qwen/Qwen2.5-7B-Instruct-GGUF"
    set "FILE=qwen2.5-7b-instruct-q4_k_m.gguf"
    set "LABEL=Qwen 2.5 7B"
) else if "%CHOICE%"=="4" (
    set "REPO=Qwen/Qwen2.5-14B-Instruct-GGUF"
    set "FILE=qwen2.5-14b-instruct-q4_k_m.gguf"
    set "LABEL=Qwen 2.5 14B"
) else (
    echo Invalid choice. Please run again and pick 1-4.
    pause
    exit /b 1
)

set "GGUF_MODEL=%MODELS_DIR%\%FILE%"

if exist "%GGUF_MODEL%" (
    echo.
    echo [OK] %LABEL% already downloaded: %FILE%
    echo Nothing to do.
    pause
    exit /b 0
)

echo.
echo Downloading %LABEL% (%FILE%) ...
echo.

:: Strategy 1: Use venv's huggingface-cli
if exist "%~dp0venv\Scripts\huggingface-cli.exe" (
    echo Using venv huggingface-cli...
    "%~dp0venv\Scripts\huggingface-cli.exe" download %REPO% %FILE% --local-dir "%MODELS_DIR%"
    goto :check_result
)

:: Strategy 2: huggingface-cli on PATH
where huggingface-cli >nul 2>&1
if not errorlevel 1 (
    echo Using system huggingface-cli...
    huggingface-cli download %REPO% %FILE% --local-dir "%MODELS_DIR%"
    goto :check_result
)

:: Strategy 3: Set up Python and install huggingface-hub
echo huggingface-cli not found. Setting up...

set "PYTHON="
where python >nul 2>&1 && set "PYTHON=python"
where python3 >nul 2>&1 && set "PYTHON=python3"
where py >nul 2>&1 && set "PYTHON=py"

if not defined PYTHON (
    echo [ERROR] Python not found. Run setup.bat first.
    pause
    exit /b 1
)

if not exist "%~dp0venv\Scripts\pip.exe" (
    echo Creating virtual environment...
    %PYTHON% -m venv venv
)

"%~dp0venv\Scripts\pip.exe" install huggingface-hub --quiet
"%~dp0venv\Scripts\huggingface-cli.exe" download %REPO% %FILE% --local-dir "%MODELS_DIR%"

:check_result
echo.
if exist "%GGUF_MODEL%" (
    echo [OK] %LABEL% downloaded successfully!
    echo.
    echo To use this model, edit src\config.py and change GGUF_MODEL_PATH to:
    echo     GGUF_MODEL_PATH = MODELS_DIR / "%FILE%"
) else (
    echo [ERROR] Download may have failed. You can download manually from:
    echo         https://huggingface.co/%REPO%
    echo         Save %FILE% into the models\ folder.
)
pause
