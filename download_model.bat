@echo off
setlocal enabledelayedexpansion
title omnigab - Model Downloader
cd /d "%~dp0"

set "MODELS_DIR=%~dp0models"
set "CONFIG=%~dp0src\config.py"
if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"

echo.
echo  omnigab - Model Downloader
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
    set "REPO=bartowski/Qwen2.5-14B-Instruct-GGUF"
    set "FILE=Qwen2.5-14B-Instruct-Q4_K_M.gguf"
    set "LABEL=Qwen 2.5 14B"
) else (
    echo Invalid choice. Please run again and pick 1-4.
    pause
    exit /b 1
)

set "GGUF_MODEL=%MODELS_DIR%\!FILE!"

if exist "!GGUF_MODEL!" (
    echo.
    echo [OK] !LABEL! already downloaded: !FILE!
    echo.
    set /p "SWITCH=Switch to this model now? (Y/N): "
    if /i "!SWITCH!"=="Y" goto :switch_model
    pause
    exit /b 0
)

echo.
echo Downloading !LABEL! (!FILE!) ...
echo.

:: Strategy 1: Use venv's hf command (new huggingface-hub)
if exist "%~dp0venv\Scripts\hf.exe" (
    echo Using venv hf cli...
    "%~dp0venv\Scripts\hf.exe" download !REPO! !FILE! --local-dir "%MODELS_DIR%"
    goto :check_result
)

:: Strategy 2: hf on PATH
where hf >nul 2>&1
if not errorlevel 1 (
    echo Using system hf cli...
    hf download !REPO! !FILE! --local-dir "%MODELS_DIR%"
    goto :check_result
)

:: Strategy 3: Try legacy huggingface-cli (older installs)
if exist "%~dp0venv\Scripts\huggingface-cli.exe" (
    echo Using venv huggingface-cli...
    "%~dp0venv\Scripts\huggingface-cli.exe" download !REPO! !FILE! --local-dir "%MODELS_DIR%"
    goto :check_result
)

:: Strategy 4: Install huggingface-hub and try again
echo hf cli not found. Installing...

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
    !PYTHON! -m venv venv
)

"%~dp0venv\Scripts\pip.exe" install --upgrade huggingface-hub --quiet

:: Try hf first (new), fall back to huggingface-cli (old)
if exist "%~dp0venv\Scripts\hf.exe" (
    "%~dp0venv\Scripts\hf.exe" download !REPO! !FILE! --local-dir "%MODELS_DIR%"
) else (
    "%~dp0venv\Scripts\huggingface-cli.exe" download !REPO! !FILE! --local-dir "%MODELS_DIR%"
)

:check_result
echo.
if exist "!GGUF_MODEL!" (
    echo [OK] !LABEL! downloaded successfully!
    echo.
    goto :switch_model
) else (
    echo [ERROR] Download may have failed. You can download manually:
    echo.
    echo   1. Open PowerShell in this folder
    echo   2. Run: venv\Scripts\activate
    echo   3. Run: hf download !REPO! !FILE! --local-dir models
    echo.
    echo   Or download from: https://huggingface.co/!REPO!
    echo   Save !FILE! into the models\ folder.
    pause
    exit /b 1
)

:switch_model
echo Updating config.py to use !LABEL!...
echo.

:: Use PowerShell to do the find-and-replace in config.py (preserving encoding)
powershell -Command "$c = [IO.File]::ReadAllText('!CONFIG!'); $c = $c -replace 'GGUF_MODEL_PATH = MODELS_DIR / \".*?\"', 'GGUF_MODEL_PATH = MODELS_DIR / \"!FILE!\"'; [IO.File]::WriteAllText('!CONFIG!', $c)"

:: Verify it worked
findstr /C:"!FILE!" "!CONFIG!" >nul 2>&1
if not errorlevel 1 (
    echo [OK] Config updated! Your agent will now use !LABEL!.
    echo.
    echo     Active model: !FILE!
    echo.
    echo Restart the web app (python src\web_app.py) to load the new model.
) else (
    echo [WARNING] Could not auto-update config.py.
    echo Open src\config.py and change the GGUF_MODEL_PATH line to:
    echo     GGUF_MODEL_PATH = MODELS_DIR / "!FILE!"
)
pause
