@echo off
setlocal enabledelayedexpansion
title Local RAG Agent - Model Downloader
cd /d "%~dp0"

set "MODELS_DIR=%~dp0models"
set "GGUF_MODEL=%MODELS_DIR%\qwen2.5-1.5b-instruct-q4_k_m.gguf"

echo.
echo  Local RAG Agent - Model Downloader
echo.

if exist "%GGUF_MODEL%" (
    echo [OK] Model already exists: qwen2.5-1.5b-instruct-q4_k_m.gguf
    echo Nothing to do.
    pause
    exit /b 0
)

echo Downloading Qwen2.5-1.5B-Instruct (Q4_K_M) ... ~1.1 GB
echo.

if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"

:: Strategy 1: Use venv's huggingface-cli (most reliable)
if exist "%~dp0venv\Scripts\huggingface-cli.exe" (
    echo Using venv huggingface-cli...
    "%~dp0venv\Scripts\huggingface-cli.exe" download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir "%MODELS_DIR%"
    goto :check_result
)

:: Strategy 2: huggingface-cli is on PATH
where huggingface-cli >nul 2>&1
if not errorlevel 1 (
    echo Using system huggingface-cli...
    huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir "%MODELS_DIR%"
    goto :check_result
)

:: Strategy 3: Find Python and install huggingface-hub into venv, then use it
echo huggingface-cli not found. Setting up...

set "PYTHON="
where python >nul 2>&1 && set "PYTHON=python"
where python3 >nul 2>&1 && set "PYTHON=python3"
where py >nul 2>&1 && set "PYTHON=py"

if not defined PYTHON (
    echo [ERROR] Python not found. Run setup.bat first, or install Python from https://www.python.org
    pause
    exit /b 1
)

:: Create venv if it doesn't exist
if not exist "%~dp0venv\Scripts\pip.exe" (
    echo Creating virtual environment...
    %PYTHON% -m venv venv
)

:: Install huggingface-hub and download
"%~dp0venv\Scripts\pip.exe" install huggingface-hub --quiet
"%~dp0venv\Scripts\huggingface-cli.exe" download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir "%MODELS_DIR%"

:check_result
echo.
if exist "%GGUF_MODEL%" (
    echo [OK] Model downloaded successfully!
) else (
    echo [ERROR] Download may have failed. You can download it manually from:
    echo         https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF
    echo         Save qwen2.5-1.5b-instruct-q4_k_m.gguf into the models\ folder.
)
pause
