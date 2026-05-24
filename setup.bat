@echo off
setlocal enabledelayedexpansion
title OmniAgent - Setup
cd /d "%~dp0"

echo.
echo  =============================================
echo    OmniAgent - One-Click Setup
echo  =============================================
echo.

:: -----------------------------------------------
:: 1. Find Python
:: -----------------------------------------------
set "PYTHON="
where python >nul 2>&1 && set "PYTHON=python" && goto :found_python
where python3 >nul 2>&1 && set "PYTHON=python3" && goto :found_python
where py >nul 2>&1 && set "PYTHON=py" && goto :found_python

for /d %%D in ("C:\Users\%USERNAME%\AppData\Local\Python\pythoncore-3.*") do (
    if exist "%%D\python.exe" ( set "PYTHON=%%D\python.exe" & goto :found_python )
)
for /d %%D in ("C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" ( set "PYTHON=%%D\python.exe" & goto :found_python )
)
for /d %%D in ("C:\Python3*") do (
    if exist "%%D\python.exe" ( set "PYTHON=%%D\python.exe" & goto :found_python )
)

echo [ERROR] Python not found. Install Python 3.10-3.12 from https://www.python.org
pause
exit /b 1

:found_python
echo [OK] Found Python: %PYTHON%

%PYTHON% --version

:: -----------------------------------------------
:: Strict Python 3.12 enforcement
:: -----------------------------------------------
:: Prebuilt CUDA wheels for llama-cpp-python (and many ML deps) target
:: Python 3.10-3.12. Newer Python = no wheel = silent CPU fallback or
:: source-build failure. OmniAgent locks to 3.12 to keep installs sane.
%PYTHON% -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" 2>nul
if errorlevel 1 (
    echo.
    echo  =============================================
    echo    [ERROR] OmniAgent requires Python 3.12.
    echo  =============================================
    echo.
    %PYTHON% -c "import sys; print(f'   You are running: Python {sys.version.split()[0]}')"
    echo.
    echo   Why: prebuilt CUDA wheels for llama-cpp-python only ship for
    echo        Python 3.10-3.12. Newer Pythons silently fall back to CPU
    echo        or fail to install GPU acceleration entirely.
    echo.
    echo   How to fix:
    echo     1. Install Python 3.12 from https://www.python.org/downloads/release/python-3128/
    echo        ^(any 3.12.x release works^).
    echo     2. During install, check "Add python.exe to PATH".
    echo     3. Delete the existing venv folder in this directory:
    echo          rmdir /s /q venv
    echo     4. Rerun setup.bat
    echo.
    echo   Tip: you can keep your other Python versions installed; the venv
    echo        will pick whichever python is first on PATH after rebuild.
    echo.
    pause
    exit /b 1
)
echo [OK] Python 3.12 confirmed.

:: -----------------------------------------------
:: 2. Virtual environment
:: -----------------------------------------------
echo.
if exist "venv\Scripts\activate.bat" (
    echo [OK] venv already exists.
) else (
    echo [SETUP] Creating venv...
    %PYTHON% -m venv venv
    if errorlevel 1 (
        echo [ERROR] venv creation failed.
        pause
        exit /b 1
    )
)
call venv\Scripts\activate.bat

:: -----------------------------------------------
:: 3. GPU detection (delegated to scripts/detect_gpu.py)
:: -----------------------------------------------
:: Python helper sidesteps cmd batch quirks (commas in nvidia-smi args,
:: stderr leaking through 2>nul before redirect parsing, etc.).
echo.
echo [SETUP] Detecting NVIDIA GPU...
set "GPU_PRESENT=0"
set "GPU_NAME="
set "VRAM_GB=0"

for /f "usebackq tokens=1,2,3 delims=|" %%A in (`%PYTHON% "%~dp0scripts\detect_gpu.py" 2^>nul`) do (
    set "GPU_PRESENT=%%A"
    set "GPU_NAME=%%B"
    set "VRAM_GB=%%C"
)

if "!GPU_PRESENT!"=="1" (
    echo [OK] NVIDIA GPU: !GPU_NAME!  ^(VRAM: !VRAM_GB! GB^)
) else (
    echo [INFO] No NVIDIA GPU detected. CPU-only.
)

:: -----------------------------------------------
:: 4. Install dependencies
:: -----------------------------------------------
:: llama-cpp-python install is delegated to scripts/install_llama_cpp.py.
:: That helper handles the GPU/CPU wheel cascade, CUDA runtime DLL install,
:: and post-install verification in one place. Keeping it in Python avoids
:: cmd batch nested-paren miscounts that bit us before.
echo.
echo [SETUP] Installing dependencies...
pip install --upgrade pip --quiet 2>nul

echo [SETUP] Installing llama-cpp-python ^(GPU/CPU wheel selected automatically^)...
python "%~dp0scripts\install_llama_cpp.py"
if errorlevel 1 (
    echo [ERROR] Could not install llama-cpp-python at all.
    pause
    exit /b 1
)

:: --- Step 4e: project requirements ---
echo.
echo [SETUP] Installing application dependencies: fastapi, uvicorn, sentence-transformers, faiss, etc.
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [WARNING] Some packages had issues. Retrying with output...
    pip install -r requirements.txt
)

:: --- Step 4f: Playwright browser (used by the Indeed apply tool) ---
echo.
echo [SETUP] Installing Playwright Chromium browser...
python -m playwright install chromium 2>nul
if errorlevel 1 (
    echo [WARNING] Chromium install failed. The Indeed apply tool will not work
    echo           until you run:  venv\Scripts\python.exe -m playwright install chromium
) else (
    echo [OK] Playwright + Chromium ready.
)

echo.
echo [OK] Dependencies installed.

:: -----------------------------------------------
:: 5. Download default model
:: -----------------------------------------------
set "MODELS_DIR=%~dp0models"
set "GGUF_MODEL=%MODELS_DIR%\qwen2.5-1.5b-instruct-q4_k_m.gguf"

if not exist "%GGUF_MODEL%" (
    echo.
    echo [SETUP] Downloading default Qwen2.5-1.5B model ^(~1.1 GB^)...
    if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"
    "%~dp0venv\Scripts\huggingface-cli.exe" download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir "%MODELS_DIR%"
    if not exist "%GGUF_MODEL%" (
        echo [ERROR] Model download failed.
        pause
        exit /b 1
    )
)

:: -----------------------------------------------
:: 6. Build vector index if empty
:: -----------------------------------------------
if not exist "%~dp0vectorstore\faiss_index" (
    if exist "%~dp0data\docs" (
        echo.
        echo [SETUP] Building vector index from docs...
        python "%~dp0src\rag_agent.py" ingest 2>nul
    )
)

:: -----------------------------------------------
:: 7. Summary + launch
:: -----------------------------------------------
echo.
echo  =============================================
echo    OmniAgent setup complete!
if "!GPU_PRESENT!"=="1" (
    echo    GPU:  ENABLED  ^(!GPU_NAME!, VRAM: !VRAM_GB! GB^)
) else (
    echo    GPU:  CPU only
)
echo  =============================================
echo.

:: Flags:
::   --terminal    launch the CLI demo instead of the desktop UI
::   --no-launch   complete install verification only; do not start anything
::                 (handy when re-running setup to confirm dependencies)
if "%1"=="--no-launch" (
    echo Setup verified. Skipping launch ^(--no-launch^).
    echo Run OmniAgent.bat to start the app.
    pause
    exit /b 0
)

if "%1"=="--terminal" (
    python "%~dp0src\demo_ui.py"
) else (
    python "%~dp0desktop_app.py"
)

pause
